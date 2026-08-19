from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine, Row, RowMapping

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import load_persisted_pipeline_config
from liveclip.application.reviewing import (
    BatchReviewCommand,
    ClipDetail,
    ClipPatch,
    RenderSnapshot,
    ReviewCommand,
    ReviewConflict,
    ReviewResourceNotFound,
    ReviewSnapshot,
    TranscriptSegmentSnapshot,
    TranscriptSnapshot,
)
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    CandidateClipRow,
    CaptionCueRow,
    DeliveryRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    TaskRow,
    TranscriptRow,
    TranscriptSegmentRow,
    TranscriptWordRow,
)
from liveclip.db.release_package_invalidation import invalidate_active_release_packages
from liveclip.domain.edit_plan import (
    CaptionCue,
    EditPlan,
    Layout,
    caption_cues_from_transcript_segments,
    edit_plan_from_json_data,
    validate_edit_plan_bounds,
)
from liveclip.domain.keywords import derive_keyword_occurrences
from liveclip.domain.state_transitions import (
    DeliveryStatus,
    FailureClass,
    RenderStatus,
    ReviewStatus,
    TaskStatus,
    record_review_status,
    transition_delivery,
    transition_render,
    transition_task,
)
from liveclip.domain.transcript import TranscriptSegment, TranscriptWord
from liveclip.renderer.contracts import is_clean_review_proxy


class SqlAlchemyReviewRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_clip(self, clip_id: str) -> ClipDetail:
        with self._engine.connect() as connection:
            return _get_clip(connection, clip_id)

    def revise_clip(self, clip_id: str, patch: ClipPatch) -> ClipDetail:
        return self._revise_and_maybe_review(clip_id, patch, command=None)

    def revise_and_review(
        self,
        clip_id: str,
        patch: ClipPatch,
        command: ReviewCommand,
    ) -> ClipDetail:
        if patch.expected_revision != command.expected_revision:
            raise ReviewConflict("clip patch and review must expect the same current revision")
        return self._revise_and_maybe_review(clip_id, patch, command=command)

    def _revise_and_maybe_review(
        self,
        clip_id: str,
        patch: ClipPatch,
        *,
        command: ReviewCommand | None,
    ) -> ClipDetail:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            context = _load_current_context(connection, clip_id)
            current_revision = int(context["current_revision"])
            if patch.expected_revision != current_revision:
                raise ReviewConflict("clip revision changed; reload before editing")
            current_plan = edit_plan_from_json_data(context["plan_json"])
            plan_payload = current_plan.model_dump(mode="python")
            plan_payload.update(
                {
                    "source_start_ms": (
                        patch.source_start_ms
                        if patch.source_start_ms is not None
                        else current_plan.source_start_ms
                    ),
                    "source_end_ms": (
                        patch.source_end_ms
                        if patch.source_end_ms is not None
                        else current_plan.source_end_ms
                    ),
                    "title": patch.title if patch.title is not None else current_plan.title,
                    "layout": (
                        Layout(patch.layout) if patch.layout is not None else Layout.CENTER_CROP
                    ),
                }
            )
            plan = EditPlan.model_validate(plan_payload)
            config = load_persisted_pipeline_config(
                context["config_json"],
                str(context["config_fingerprint"]),
            )
            validate_edit_plan_bounds(
                plan,
                source_duration_ms=int(context["source_duration_ms"]),
                minimum_duration_ms=config.minimum_clip_ms,
                maximum_duration_ms=config.maximum_clip_ms,
                allowed_start_ms=int(context["allowed_start_ms"]),
                allowed_end_ms=int(context["allowed_end_ms"]),
            )
            current_revision_id = str(context["revision_id"])
            current_captions = _load_captions(connection, current_revision_id)
            bounds_changed = (
                plan.source_start_ms != current_plan.source_start_ms
                or plan.source_end_ms != current_plan.source_end_ms
            )
            if patch.captions is not None:
                captions = patch.captions
            elif bounds_changed:
                captions = _captions_for_interval(
                    connection,
                    run_id=str(context["run_id"]),
                    source_start_ms=plan.source_start_ms,
                    source_end_ms=plan.source_end_ms,
                )
            else:
                captions = current_captions
            # Domain construction applies caption ordering, bounds, text and executable-data rules.
            from liveclip.domain.review import EditPlanRevision, RevisionOrigin

            next_revision = current_revision + 1
            domain_revision = EditPlanRevision(
                clip_id=clip_id,
                revision=next_revision,
                parent_revision=current_revision,
                origin=RevisionOrigin.HUMAN,
                plan=plan,
                captions=captions,
                created_at=now,
            )
            if plan == current_plan and captions == current_captions:
                raise ReviewConflict("clip patch does not change the current revision")
            revision_id = new_id()
            connection.execute(
                insert(EditPlanRevisionRow).values(
                    id=revision_id,
                    candidate_clip_id=clip_id,
                    revision=next_revision,
                    parent_revision=current_revision,
                    origin=domain_revision.origin.value,
                    source_start_ms=plan.source_start_ms,
                    source_end_ms=plan.source_end_ms,
                    score=plan.score,
                    title=plan.title,
                    hook=plan.hook,
                    reason=plan.reason,
                    layout=plan.layout.value,
                    caption_template=plan.caption_template.value,
                    effect=plan.effect.value,
                    risk_flags_json=list(plan.risk_flags),
                    prompt_version=plan.prompt_version,
                    model=plan.model,
                    degraded=plan.degraded,
                    plan_json=plan.model_dump(mode="json"),
                    created_at=now,
                )
            )
            for cue_index, cue in enumerate(captions):
                connection.execute(
                    insert(CaptionCueRow).values(
                        id=new_id(),
                        edit_plan_revision_id=revision_id,
                        cue_index=cue_index,
                        start_ms=cue.start_ms,
                        end_ms=cue.end_ms,
                        text=cue.text,
                    )
                )
            changed = connection.execute(
                update(CandidateClipRow)
                .where(
                    CandidateClipRow.id == clip_id,
                    CandidateClipRow.current_revision == current_revision,
                )
                .values(current_revision=next_revision)
                .returning(CandidateClipRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise ReviewConflict("clip revision changed during editing")
            connection.execute(
                update(ProjectRow)
                .where(
                    ProjectRow.id == context["project_id"],
                    ProjectRow.current_pipeline_run_id == context["run_id"],
                )
                .values(revision_epoch=ProjectRow.revision_epoch + 1, updated_at=now)
            )
            _invalidate_active_deliveries(
                connection,
                project_id=str(context["project_id"]),
                generation=int(context["generation"]),
                instant=now,
            )
            invalidate_active_release_packages(
                connection,
                instant=now,
                project_id=str(context["project_id"]),
            )
            render_task_ids = tuple(
                str(value)
                for value in connection.scalars(
                    select(RenderJobRow.task_id)
                    .join(
                        CandidateClipRow,
                        CandidateClipRow.id == RenderJobRow.candidate_clip_id,
                    )
                    .where(
                        CandidateClipRow.pipeline_run_id == context["run_id"],
                        RenderJobRow.task_id.is_not(None),
                        RenderJobRow.status.in_(
                            [RenderStatus.QUEUED.value, RenderStatus.RUNNING.value]
                        ),
                    )
                )
                if value is not None
            )
            for status in (
                RenderStatus.QUEUED,
                RenderStatus.RUNNING,
                RenderStatus.SUCCEEDED,
                RenderStatus.FAILED,
            ):
                transition_render(status, RenderStatus.STALE)
            connection.execute(
                update(RenderJobRow)
                .where(
                    RenderJobRow.candidate_clip_id == clip_id,
                    RenderJobRow.status.in_(
                        [
                            RenderStatus.QUEUED.value,
                            RenderStatus.RUNNING.value,
                            RenderStatus.SUCCEEDED.value,
                            RenderStatus.FAILED.value,
                        ]
                    ),
                )
                .values(status=RenderStatus.STALE.value, updated_at=now)
            )
            # Project revision_epoch fences all in-flight render tasks. Renders for
            # unchanged clips that already succeeded remain reusable, while queued
            # or running work from the old epoch must stop and be re-enqueued.
            connection.execute(
                update(RenderJobRow)
                .where(
                    RenderJobRow.candidate_clip_id.in_(
                        select(CandidateClipRow.id).where(
                            CandidateClipRow.pipeline_run_id == context["run_id"],
                            CandidateClipRow.id != clip_id,
                        )
                    ),
                    RenderJobRow.status.in_(
                        [
                            RenderStatus.QUEUED.value,
                            RenderStatus.RUNNING.value,
                            RenderStatus.FAILED.value,
                        ]
                    ),
                )
                .values(status=RenderStatus.STALE.value, updated_at=now)
            )
            if render_task_ids:
                connection.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.id.in_(render_task_ids),
                        TaskRow.status == TaskStatus.QUEUED.value,
                    )
                    .values(
                        status=TaskStatus.CANCELLED.value,
                        cancellation_requested_at=now,
                        completed_at=now,
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.id.in_(render_task_ids),
                        TaskRow.status == TaskStatus.RUNNING.value,
                    )
                    .values(cancellation_requested_at=now, updated_at=now)
                )
            if command is not None:
                _record_review_decision(
                    connection,
                    clip_id=clip_id,
                    revision_id=revision_id,
                    command=command,
                    decided_at=now,
                )
            result = _get_clip(connection, clip_id)
        return result

    def review_clip(self, clip_id: str, command: ReviewCommand) -> ClipDetail:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            context = _load_current_context(connection, clip_id)
            if command.expected_revision != int(context["current_revision"]):
                raise ReviewConflict("clip revision changed; reload before reviewing")
            current_plan = edit_plan_from_json_data(context["plan_json"])
            if (
                command.status == ReviewStatus.APPROVED
                and current_plan.layout is not Layout.CENTER_CROP
            ):
                raise ReviewConflict(
                    "clip must be revised to the required center-crop layout before approval"
                )
            decision_changed = _record_review_decision(
                connection,
                clip_id=clip_id,
                revision_id=str(context["revision_id"]),
                command=command,
                decided_at=now,
            )
            if decision_changed:
                _invalidate_active_deliveries(
                    connection,
                    project_id=str(context["project_id"]),
                    generation=int(context["generation"]),
                    instant=now,
                )
                invalidate_active_release_packages(
                    connection,
                    instant=now,
                    candidate_clip_ids=(clip_id,),
                )
            result = _get_clip(connection, clip_id)
        return result

    def review_clips_batch(
        self,
        project_id: str,
        command: BatchReviewCommand,
        *,
        idempotency: IdempotencyContext | None = None,
    ) -> tuple[ClipDetail, ...]:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            replayed_project_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="review_batch",
            )
            if replayed_project_id is not None:
                if replayed_project_id != project_id:
                    raise ReviewConflict("batch review replay does not match this project")
                return tuple(_get_clip(connection, item.clip_id) for item in command.items)

            contexts: list[tuple[RowMapping, ReviewCommand]] = []
            for item in command.items:
                context = _load_current_context(connection, item.clip_id)
                if str(context["project_id"]) != project_id:
                    raise ReviewConflict("batch review clip does not belong to this project")
                item_command = item.command()
                if item_command.expected_revision != int(context["current_revision"]):
                    raise ReviewConflict("clip revision changed; reload before batch reviewing")
                current_plan = edit_plan_from_json_data(context["plan_json"])
                if (
                    item_command.status == ReviewStatus.APPROVED
                    and current_plan.layout is not Layout.CENTER_CROP
                ):
                    raise ReviewConflict(
                        "clip must be revised to the required center-crop layout before approval"
                    )
                contexts.append((context, item_command))

            changed_clip_ids: list[str] = []
            for item, (context, item_command) in zip(
                command.items,
                contexts,
                strict=True,
            ):
                if _record_review_decision(
                    connection,
                    clip_id=item.clip_id,
                    revision_id=str(context["revision_id"]),
                    command=item_command,
                    decided_at=now,
                ):
                    changed_clip_ids.append(item.clip_id)
            first_context = contexts[0][0]
            if changed_clip_ids:
                _invalidate_active_deliveries(
                    connection,
                    project_id=project_id,
                    generation=int(first_context["generation"]),
                    instant=now,
                )
                invalidate_active_release_packages(
                    connection,
                    instant=now,
                    candidate_clip_ids=tuple(changed_clip_ids),
                )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="review_batch",
                resource_id=project_id,
                response_status_code=200,
            )
            return tuple(_get_clip(connection, item.clip_id) for item in command.items)

    def get_transcript(self, project_id: str) -> TranscriptSnapshot:
        with self._engine.connect() as connection:
            project = connection.execute(
                select(ProjectRow.current_pipeline_run_id).where(ProjectRow.id == project_id)
            ).one_or_none()
            if project is None or project.current_pipeline_run_id is None:
                raise ReviewResourceNotFound("project does not exist")
            run_id = str(project.current_pipeline_run_id)
            transcript = connection.execute(
                select(
                    TranscriptRow.id,
                    TranscriptRow.language,
                    TranscriptRow.provider,
                    TranscriptRow.model,
                    TranscriptRow.word_timing_status,
                ).where(TranscriptRow.pipeline_run_id == run_id)
            ).one_or_none()
            if transcript is None:
                raise ReviewResourceNotFound("project transcript is not available")
            segments = tuple(
                TranscriptSegmentSnapshot(
                    segment_id=str(row.id),
                    index=int(row.segment_index),
                    start_ms=int(row.source_start_ms),
                    end_ms=int(row.source_end_ms),
                    text=str(row.text),
                )
                for row in connection.execute(
                    select(
                        TranscriptSegmentRow.id,
                        TranscriptSegmentRow.segment_index,
                        TranscriptSegmentRow.source_start_ms,
                        TranscriptSegmentRow.source_end_ms,
                        TranscriptSegmentRow.text,
                    )
                    .where(TranscriptSegmentRow.transcript_id == transcript.id)
                    .order_by(TranscriptSegmentRow.segment_index)
                )
            )
            return TranscriptSnapshot(
                project_id=project_id,
                run_id=run_id,
                language=str(transcript.language),
                provider=str(transcript.provider),
                model=str(transcript.model),
                word_timing_status=str(transcript.word_timing_status),
                segments=segments,
            )


def _record_review_decision(
    connection: Connection,
    *,
    clip_id: str,
    revision_id: str,
    command: ReviewCommand,
    decided_at: datetime,
) -> bool:
    record_review_status(ReviewStatus.PENDING_REVIEW, command.status)
    normalized_reason = command.reason.strip() if command.reason else None
    latest = connection.execute(
        select(
            ReviewDecisionRow.status,
            ReviewDecisionRow.rejection_reason,
        )
        .where(ReviewDecisionRow.edit_plan_revision_id == revision_id)
        .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
        .limit(1)
    ).one_or_none()
    if latest is not None and (
        str(latest.status),
        str(latest.rejection_reason) if latest.rejection_reason else None,
    ) == (command.status.value, normalized_reason):
        return False
    connection.execute(
        insert(ReviewDecisionRow).values(
            id=new_id(),
            candidate_clip_id=clip_id,
            edit_plan_revision_id=revision_id,
            status=command.status.value,
            rejection_reason=normalized_reason,
            decided_at=decided_at,
        )
    )
    return True


def _load_current_context(connection: Connection, clip_id: str) -> RowMapping:
    row = (
        connection.execute(
            select(
                CandidateClipRow.id,
                CandidateClipRow.project_id,
                CandidateClipRow.pipeline_run_id.label("run_id"),
                CandidateClipRow.current_revision,
                CandidateClipRow.allowed_start_ms,
                CandidateClipRow.allowed_end_ms,
                EditPlanRevisionRow.id.label("revision_id"),
                EditPlanRevisionRow.plan_json,
                PipelineRunRow.config_json,
                PipelineRunRow.config_fingerprint,
                ProjectRow.current_pipeline_run_id,
                ProjectRow.current_generation.label("generation"),
                SourceMediaRow.duration_ms.label("source_duration_ms"),
            )
            .join(
                EditPlanRevisionRow,
                (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
                & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
            )
            .join(PipelineRunRow, PipelineRunRow.id == CandidateClipRow.pipeline_run_id)
            .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
            .join(SourceMediaRow, SourceMediaRow.project_id == CandidateClipRow.project_id)
            .where(
                CandidateClipRow.id == clip_id,
                CandidateClipRow.selected_for_review.is_(True),
                CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ReviewResourceNotFound("clip does not exist in the current project generation")
    return row


def _invalidate_active_deliveries(
    connection: Connection,
    *,
    project_id: str,
    generation: int,
    instant: datetime,
) -> None:
    """Fail old delivery snapshots and cancel their tasks inside the edit transaction."""

    active = connection.execute(
        select(DeliveryRow.id, DeliveryRow.task_id, DeliveryRow.status).where(
            DeliveryRow.project_id == project_id,
            DeliveryRow.expected_generation == generation,
            DeliveryRow.status.in_([DeliveryStatus.QUEUED.value, DeliveryStatus.CREATING.value]),
        )
    ).all()
    if not active:
        return
    for row in active:
        transition_delivery(DeliveryStatus(str(row.status)), DeliveryStatus.FAILED)
    delivery_ids = tuple(str(row.id) for row in active)
    task_ids = tuple(str(row.task_id) for row in active if row.task_id is not None)
    error_code = "DELIVERY_SNAPSHOT_STALE"
    safe_message = "Delivery became stale after the approved clip set changed"
    connection.execute(
        update(DeliveryRow)
        .where(
            DeliveryRow.id.in_(delivery_ids),
            DeliveryRow.status.in_([DeliveryStatus.QUEUED.value, DeliveryStatus.CREATING.value]),
        )
        .values(
            status=DeliveryStatus.FAILED.value,
            error_code=error_code,
            safe_error_message=safe_message,
            completed_at=instant,
        )
    )
    if not task_ids:
        return
    queued_task_ids = tuple(
        str(row.id)
        for row in connection.execute(
            select(TaskRow.id).where(
                TaskRow.id.in_(task_ids),
                TaskRow.status == TaskStatus.QUEUED.value,
            )
        )
    )
    for _ in queued_task_ids:
        transition_task(TaskStatus.QUEUED, TaskStatus.CANCELLED)
    if queued_task_ids:
        connection.execute(
            update(TaskRow)
            .where(
                TaskRow.id.in_(queued_task_ids),
                TaskRow.status == TaskStatus.QUEUED.value,
            )
            .values(
                status=TaskStatus.CANCELLED.value,
                cancellation_requested_at=instant,
                failure_class=FailureClass.DETERMINISTIC.value,
                error_code=error_code,
                safe_error_message=safe_message,
                completed_at=instant,
                updated_at=instant,
            )
        )
    connection.execute(
        update(TaskRow)
        .where(
            TaskRow.id.in_(task_ids),
            TaskRow.status == TaskStatus.RUNNING.value,
        )
        .values(
            cancellation_requested_at=instant,
            failure_class=FailureClass.DETERMINISTIC.value,
            error_code=error_code,
            safe_error_message=safe_message,
            updated_at=instant,
        )
    )


def _get_clip(connection: Connection, clip_id: str) -> ClipDetail:
    row = (
        connection.execute(
            select(
                CandidateClipRow.id,
                CandidateClipRow.project_id,
                CandidateClipRow.pipeline_run_id.label("run_id"),
                CandidateClipRow.candidate_key,
                CandidateClipRow.allowed_start_ms,
                CandidateClipRow.allowed_end_ms,
                CandidateClipRow.transcript_text,
                CandidateClipRow.context_before,
                CandidateClipRow.context_after,
                CandidateClipRow.rule_score,
                CandidateClipRow.reasons_json,
                CandidateClipRow.rank,
                CandidateClipRow.current_revision,
                EditPlanRevisionRow.id.label("revision_id"),
                EditPlanRevisionRow.plan_json,
                EditPlanRevisionRow.created_at.label("revision_created_at"),
                ProjectRow.current_generation.label("generation"),
                ProjectRow.revision_epoch,
                PipelineRunRow.config_json,
            )
            .join(
                EditPlanRevisionRow,
                (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
                & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
            )
            .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
            .join(PipelineRunRow, PipelineRunRow.id == CandidateClipRow.pipeline_run_id)
            .where(
                CandidateClipRow.id == clip_id,
                CandidateClipRow.selected_for_review.is_(True),
                CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ReviewResourceNotFound("clip does not exist in the current project generation")
    revision_id = str(row["revision_id"])
    decision = connection.execute(
        select(
            ReviewDecisionRow.status,
            ReviewDecisionRow.rejection_reason,
            ReviewDecisionRow.decided_at,
        )
        .where(ReviewDecisionRow.edit_plan_revision_id == revision_id)
        .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
        .limit(1)
    ).one_or_none()
    review = (
        ReviewSnapshot(status=ReviewStatus.PENDING_REVIEW)
        if decision is None
        else ReviewSnapshot(
            status=ReviewStatus(str(decision.status)),
            reason=str(decision.rejection_reason) if decision.rejection_reason else None,
            decided_at=decision.decided_at,
        )
    )

    def render_snapshot(item: Row[Any]) -> RenderSnapshot:
        status = RenderStatus(str(item.status))
        incompatible_proxy = str(item.kind) == "proxy" and not is_clean_review_proxy(
            spec=item.spec_json,
            pipeline_config=row["config_json"],
        )
        if incompatible_proxy and status == RenderStatus.SUCCEEDED:
            status = RenderStatus.STALE
        return RenderSnapshot(
            render_id=str(item.id),
            task_id=str(item.task_id) if item.task_id else None,
            kind=str(item.kind),
            status=status,
            edit_plan_revision=int(item.edit_plan_revision),
            width=int(item.width),
            height=int(item.height),
            video_asset_id=(
                str(item.asset_id) if item.asset_id and not incompatible_proxy else None
            ),
            subtitle_asset_id=(
                str(item.subtitle_asset_id)
                if item.subtitle_asset_id and not incompatible_proxy
                else None
            ),
            quality_report_asset_id=(
                str(item.quality_report_asset_id)
                if item.quality_report_asset_id and not incompatible_proxy
                else None
            ),
            contact_sheet_asset_id=(
                str(item.contact_sheet_asset_id)
                if item.contact_sheet_asset_id and not incompatible_proxy
                else None
            ),
            error_code=str(item.error_code) if item.error_code else None,
            safe_error_message=(str(item.safe_error_message) if item.safe_error_message else None),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    renders = tuple(
        render_snapshot(item)
        for item in connection.execute(
            select(
                RenderJobRow.id,
                RenderJobRow.task_id,
                RenderJobRow.kind,
                RenderJobRow.status,
                RenderJobRow.spec_json,
                RenderJobRow.edit_plan_revision,
                RenderJobRow.width,
                RenderJobRow.height,
                RenderJobRow.asset_id,
                RenderJobRow.subtitle_asset_id,
                RenderJobRow.quality_report_asset_id,
                RenderJobRow.contact_sheet_asset_id,
                RenderJobRow.error_code,
                RenderJobRow.safe_error_message,
                RenderJobRow.created_at,
                RenderJobRow.updated_at,
            )
            .where(RenderJobRow.candidate_clip_id == clip_id)
            .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
        )
    )
    current_revision = int(row["current_revision"])
    current_plan = edit_plan_from_json_data(row["plan_json"])
    has_active_layout = current_plan.layout is Layout.CENTER_CROP
    current_active = any(
        render.edit_plan_revision == current_revision
        and render.status in {RenderStatus.QUEUED, RenderStatus.RUNNING}
        for render in renders
    )
    actions = ["edit"]
    if has_active_layout:
        actions.append("approve")
    actions.append("reject")
    if has_active_layout and not current_active:
        actions.append("render_proxy")
        if review.status == ReviewStatus.APPROVED:
            actions.append("render_final")
    if (
        has_active_layout
        and review.status == ReviewStatus.APPROVED
        and any(
            render.kind in {"proxy", "final"}
            and render.edit_plan_revision == current_revision
            and render.status == RenderStatus.SUCCEEDED
            and render.video_asset_id is not None
            and render.subtitle_asset_id is not None
            for render in renders
        )
    ):
        actions.append("deliver")
    captions = _load_captions(connection, revision_id)
    keywords = derive_keyword_occurrences(
        captions,
        source_start_ms=current_plan.source_start_ms,
        source_end_ms=current_plan.source_end_ms,
        title=current_plan.title,
        hook=current_plan.hook,
        reason=current_plan.reason,
        segments=_load_transcript_segments(
            connection,
            run_id=str(row["run_id"]),
            source_start_ms=current_plan.source_start_ms,
            source_end_ms=current_plan.source_end_ms,
        ),
    )
    return ClipDetail(
        clip_id=clip_id,
        project_id=str(row["project_id"]),
        run_id=str(row["run_id"]),
        generation=int(row["generation"]),
        revision_epoch=int(row["revision_epoch"]),
        candidate_key=str(row["candidate_key"]),
        allowed_start_ms=int(row["allowed_start_ms"]),
        allowed_end_ms=int(row["allowed_end_ms"]),
        transcript_text=str(row["transcript_text"]),
        context_before=str(row["context_before"]),
        context_after=str(row["context_after"]),
        rule_score=float(row["rule_score"]),
        reasons=tuple(str(value) for value in row["reasons_json"]),
        rank=int(row["rank"]) if row["rank"] is not None else None,
        current_revision=current_revision,
        plan=current_plan,
        captions=captions,
        keywords=keywords,
        revision_created_at=row["revision_created_at"],
        review=review,
        renders=renders,
        allowed_actions=tuple(actions),
    )


def _load_captions(connection: Connection, revision_id: str) -> tuple[CaptionCue, ...]:
    return tuple(
        CaptionCue(start_ms=int(row.start_ms), end_ms=int(row.end_ms), text=str(row.text))
        for row in connection.execute(
            select(CaptionCueRow.start_ms, CaptionCueRow.end_ms, CaptionCueRow.text)
            .where(CaptionCueRow.edit_plan_revision_id == revision_id)
            .order_by(CaptionCueRow.cue_index)
        )
    )


def _load_transcript_segments(
    connection: Connection,
    *,
    run_id: str,
    source_start_ms: int,
    source_end_ms: int,
) -> tuple[TranscriptSegment, ...]:
    rows = tuple(
        connection.execute(
            select(
                TranscriptSegmentRow.id,
                TranscriptSegmentRow.source_start_ms,
                TranscriptSegmentRow.source_end_ms,
                TranscriptSegmentRow.text,
            )
            .join(TranscriptRow, TranscriptRow.id == TranscriptSegmentRow.transcript_id)
            .where(
                TranscriptRow.pipeline_run_id == run_id,
                TranscriptSegmentRow.source_end_ms > source_start_ms,
                TranscriptSegmentRow.source_start_ms < source_end_ms,
            )
            .order_by(TranscriptSegmentRow.segment_index)
        )
    )
    return tuple(
        TranscriptSegment(
            segment_id=str(row.id),
            start_ms=int(row.source_start_ms),
            end_ms=int(row.source_end_ms),
            text=str(row.text),
            words=(
                tuple(
                    TranscriptWord(
                        start_ms=int(word.source_start_ms),
                        end_ms=int(word.source_end_ms),
                        text=str(word.text),
                    )
                    for word in connection.execute(
                        select(
                            TranscriptWordRow.source_start_ms,
                            TranscriptWordRow.source_end_ms,
                            TranscriptWordRow.text,
                        )
                        .where(TranscriptWordRow.segment_id == row.id)
                        .order_by(TranscriptWordRow.word_index)
                    )
                )
                or None
            ),
        )
        for row in rows
    )


def _captions_for_interval(
    connection: Connection,
    *,
    run_id: str,
    source_start_ms: int,
    source_end_ms: int,
) -> tuple[CaptionCue, ...]:
    rows = connection.execute(
        select(
            TranscriptSegmentRow.id,
            TranscriptSegmentRow.source_start_ms,
            TranscriptSegmentRow.source_end_ms,
            TranscriptSegmentRow.text,
        )
        .join(TranscriptRow, TranscriptRow.id == TranscriptSegmentRow.transcript_id)
        .where(
            TranscriptRow.pipeline_run_id == run_id,
            TranscriptSegmentRow.source_end_ms > source_start_ms,
            TranscriptSegmentRow.source_start_ms < source_end_ms,
        )
        .order_by(TranscriptSegmentRow.segment_index)
    )
    segments = tuple(
        TranscriptSegment(
            segment_id=str(row.id),
            start_ms=int(row.source_start_ms),
            end_ms=int(row.source_end_ms),
            text=str(row.text),
        )
        for row in rows
    )
    try:
        return caption_cues_from_transcript_segments(
            segments,
            source_start_ms=source_start_ms,
            source_end_ms=source_end_ms,
        )
    except ValueError as exc:
        raise ReviewConflict("edited clip interval has no transcript captions") from exc
