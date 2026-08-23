from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from liveclip.application.clips import ClipSummary
from liveclip.application.edit_packages import (
    ClipHandoffDownload,
    EditPackageClipMetadata,
    EditPackageConflict,
    EditPackageContent,
    EditPackageManifestClip,
    EditPackagePersistence,
    EditPackagePreset,
    EditPackageRequest,
    EditPackageResourceNotFound,
    EditPackageSnapshot,
    EditPackageWork,
    EditPackageWorkClip,
)
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    CandidateClipRow,
    CaptionCueRow,
    EditPackageClipRow,
    EditPackageRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.domain.edit_plan import CaptionCue, edit_plan_from_json_data
from liveclip.domain.project_lifecycle import ProjectLifecycle
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    EditPackageStatus,
    PipelineRunStatus,
    PipelineStage,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    TaskKind,
    TaskStatus,
    transition_edit_package,
    transition_task,
)
from liveclip.renderer.contracts import is_clean_review_proxy


@dataclass(frozen=True, slots=True)
class _ProjectEvidence:
    project_id: str
    project_name: str
    owner_username: str
    run_id: str
    generation: int
    revision_epoch: int
    pipeline_config: dict[str, Any]
    source_filename: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class _ClipEvidence:
    edit_plan_revision_id: str
    render_job_id: str
    video_asset_id: str
    video_relative_path: str
    video_sha256: str
    video_size_bytes: int
    contact_sheet_asset_id: str
    contact_sheet_relative_path: str
    contact_sheet_sha256: str
    contact_sheet_size_bytes: int


class SqlAlchemyEditPackageRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue_edit_package(
        self,
        project_id: str,
        requested_by_user_id: str,
        request: EditPackageRequest,
        selections: tuple[ClipSummary, ...],
        *,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> EditPackageSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            replay_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="edit_package",
            )
            if replay_id is not None:
                return _get_edit_package(connection, replay_id)
            project = _project_evidence(connection, project_id)
            requester_username = _require_active_editor(
                connection,
                project_id=project_id,
                user_id=requested_by_user_id,
            )
            if len(selections) != len(request.items):
                raise EditPackageConflict("edit package selection changed before enqueue")

            rows: list[tuple[EditPackageClipMetadata, _ClipEvidence]] = []
            for item, summary in zip(request.items, selections, strict=True):
                if item.clip_id != summary.clip_id:
                    raise EditPackageConflict("edit package selection order changed")
                metadata = _metadata_from_summary(summary)
                evidence = _current_clip_evidence(
                    connection,
                    project=project,
                    metadata=metadata,
                    expected_proxy_asset_id=summary.proxy_asset_id,
                )
                rows.append((metadata, evidence))

            current_version = connection.scalar(
                select(func.max(EditPackageRow.version)).where(
                    EditPackageRow.project_id == project_id
                )
            )
            version = int(current_version or 0) + 1
            if version > 999:
                raise EditPackageConflict("edit package version space is exhausted")
            edit_package_id = new_id()
            task_id = new_id()
            snapshot_fingerprint = _selection_fingerprint(
                project=project,
                requested_by_user_id=requested_by_user_id,
                preset=request.preset,
                content=request.content,
                clips=rows,
            )
            package_fingerprint = _package_fingerprint(
                snapshot_fingerprint=snapshot_fingerprint,
                edit_package_id=edit_package_id,
                version=version,
                include_zip=request.include_zip,
                created_at=now,
            )
            connection.execute(
                insert(TaskRow).values(
                    id=task_id,
                    kind=TaskKind.DELIVERY.value,
                    target_id=edit_package_id,
                    operation_key=f"edit-package:{edit_package_id}",
                    input_fingerprint=package_fingerprint,
                    resource_class=ResourceClass.HEAVY.value,
                    pipeline_run_id=project.run_id,
                    status=TaskStatus.QUEUED.value,
                    priority=650,
                    not_before=now,
                    expected_generation=project.generation,
                    expected_revision_epoch=project.revision_epoch,
                    attempt_count=0,
                    retry_count=0,
                    manual_retry_count=0,
                    max_retries=max_retries,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(EditPackageRow).values(
                    id=edit_package_id,
                    project_id=project_id,
                    requested_by_user_id=requested_by_user_id,
                    task_id=task_id,
                    version=version,
                    status=EditPackageStatus.QUEUED.value,
                    expected_revision_epoch=project.revision_epoch,
                    snapshot_fingerprint=snapshot_fingerprint,
                    directory_relative_path=f"edit-packages/v{version:03d}",
                    preset=request.preset,
                    content=request.content,
                    include_zip=request.include_zip,
                    expected_generation=project.generation,
                    created_at=now,
                )
            )
            for ordinal, (metadata, evidence) in enumerate(rows, start=1):
                connection.execute(
                    insert(EditPackageClipRow).values(
                        id=new_id(),
                        edit_package_id=edit_package_id,
                        ordinal=ordinal,
                        candidate_clip_id=metadata.clip_id,
                        edit_plan_revision_id=evidence.edit_plan_revision_id,
                        render_job_id=evidence.render_job_id,
                        edit_plan_revision=metadata.edit_plan_revision,
                        metadata_json=metadata.model_dump(mode="json"),
                        video_asset_id=evidence.video_asset_id,
                        contact_sheet_asset_id=evidence.contact_sheet_asset_id,
                    )
                )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="edit_package",
                resource_id=edit_package_id,
            )
            connection.execute(
                insert(AuditEventRow).values(
                    id=new_id(),
                    actor_user_id=requested_by_user_id,
                    actor_username=requester_username,
                    action="edit_package.queued",
                    target_type="edit_package",
                    target_id=edit_package_id,
                    project_id=project_id,
                    before_json=None,
                    after_json={
                        "version": f"v{version:03d}",
                        "clip_count": len(rows),
                        "content": request.content,
                    },
                    correlation_id=None,
                    created_at=now,
                )
            )
            return _get_edit_package(connection, edit_package_id)

    def get_edit_package(self, edit_package_id: str) -> EditPackageSnapshot:
        with self._engine.connect() as connection:
            return _get_edit_package(connection, edit_package_id)

    def list_edit_packages(self, project_id: str) -> tuple[EditPackageSnapshot, ...]:
        with self._engine.connect() as connection:
            if connection.scalar(select(ProjectRow.id).where(ProjectRow.id == project_id)) is None:
                raise EditPackageResourceNotFound("project does not exist")
            rows = connection.execute(
                _snapshot_select()
                .where(EditPackageRow.project_id == project_id)
                .group_by(EditPackageRow.id)
                .order_by(EditPackageRow.version.desc())
            )
            return tuple(_snapshot(row) for row in rows if row.task_id is not None)

    def is_edit_package_task(self, task_id: str, target_id: str) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.scalar(
                    select(EditPackageRow.id).where(
                        EditPackageRow.id == target_id,
                        EditPackageRow.task_id == task_id,
                    )
                )
                is not None
            )

    def start_edit_package(self, lease: LeaseIdentity) -> EditPackageWork:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = _leased_package_row(connection, lease, now=now)
            if row is None:
                raise EditPackageConflict("edit package task lost its active lease")
            work = _work_from_row(connection, row)
            _assert_work_current(connection, work)
            transition_edit_package(
                EditPackageStatus(str(row.package_status)),
                EditPackageStatus.CREATING,
            )
            activated = connection.execute(
                update(EditPackageRow)
                .where(
                    EditPackageRow.id == work.edit_package_id,
                    EditPackageRow.status == EditPackageStatus.QUEUED.value,
                )
                .values(
                    status=EditPackageStatus.CREATING.value,
                    error_code=None,
                    safe_error_message=None,
                )
                .returning(EditPackageRow.id)
            ).scalar_one_or_none()
            if activated is None:
                raise EditPackageConflict("edit package is not queued")
            return work

    def assert_edit_package_current(
        self,
        lease: LeaseIdentity,
        work: EditPackageWork,
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.connect() as connection:
            task = connection.execute(
                select(TaskRow.status, TaskRow.input_fingerprint).where(
                    TaskRow.id == lease.task_id,
                    TaskRow.id == work.task_id,
                    TaskRow.target_id == work.edit_package_id,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    TaskRow.cancellation_requested_at.is_(None),
                )
            ).one_or_none()
            if (
                task is None
                or task.status != TaskStatus.RUNNING.value
                or str(task.input_fingerprint) != work.package_fingerprint
            ):
                raise EditPackageConflict("edit package task is no longer publishable")
            _assert_work_current(connection, work)

    def complete_edit_package(
        self,
        lease: LeaseIdentity,
        work: EditPackageWork,
        persistence: EditPackagePersistence,
    ) -> bool:
        now = datetime.now(UTC)
        asset_ids = [persistence.manifest_asset_id]
        if persistence.zip_asset_id is not None:
            asset_ids.append(persistence.zip_asset_id)
        if len(set(asset_ids)) != len(asset_ids):
            raise EditPackageConflict("edit package assets must be distinct")
        with begin_immediate(self._engine) as connection:
            row = _leased_package_row(connection, lease, now=now)
            if row is None or str(row.edit_package_id) != work.edit_package_id:
                return False
            try:
                _assert_work_current(connection, work)
            except EditPackageConflict:
                return False
            if str(row.input_fingerprint) != work.package_fingerprint:
                return False
            assets = connection.execute(
                select(
                    AssetRow.id,
                    AssetRow.kind,
                    AssetRow.relative_path,
                    AssetRow.input_fingerprint,
                    AssetRow.sha256,
                    AssetRow.size_bytes,
                    AssetRow.generation,
                    AssetRow.revision_epoch,
                    AssetRow.producer_attempt_id,
                    AssetRow.validation_json,
                ).where(
                    AssetRow.id.in_(asset_ids),
                    AssetRow.project_id == work.project_id,
                    AssetRow.status == AssetStatus.COMMITTED.value,
                )
            ).all()
            by_id = {str(asset.id): asset for asset in assets}
            if set(by_id) != set(asset_ids):
                raise EditPackageConflict("edit package requires committed package assets")
            attempt_ids = {
                str(asset.producer_attempt_id)
                for asset in assets
                if asset.producer_attempt_id is not None
            }
            task_ids = {
                str(value)
                for value in connection.scalars(
                    select(TaskAttemptRow.task_id).where(TaskAttemptRow.id.in_(attempt_ids))
                )
            }
            if any(asset.producer_attempt_id is None for asset in assets) or task_ids != {
                lease.task_id
            }:
                raise EditPackageConflict("edit package assets belong to another task")
            _validate_package_assets(
                by_id,
                work=work,
                persistence=persistence,
            )
            persisted_rows = connection.execute(
                _package_clip_select()
                .where(EditPackageClipRow.edit_package_id == work.edit_package_id)
                .order_by(EditPackageClipRow.ordinal)
            ).all()
            if len(persisted_rows) != len(work.clips) or len(persistence.manifest_clips) != len(
                work.clips
            ):
                raise EditPackageConflict("edit package manifest clip count changed")
            for stored, clip, manifest_clip in zip(
                persisted_rows,
                work.clips,
                persistence.manifest_clips,
                strict=True,
            ):
                _validate_manifest_clip(clip, manifest_clip)
                connection.execute(
                    update(EditPackageClipRow)
                    .where(EditPackageClipRow.id == stored.id)
                    .values(
                        video_filename=manifest_clip.video_filename,
                        subtitle_filename=manifest_clip.subtitle_filename,
                        thumbnail_filename=manifest_clip.thumbnail_filename,
                        video_sha256=manifest_clip.video_sha256,
                        subtitle_sha256=manifest_clip.subtitle_sha256,
                        thumbnail_sha256=manifest_clip.thumbnail_sha256,
                    )
                )
            transition_edit_package(
                EditPackageStatus(str(row.package_status)),
                EditPackageStatus.SUCCEEDED,
            )
            connection.execute(
                update(EditPackageRow)
                .where(
                    EditPackageRow.id == work.edit_package_id,
                    EditPackageRow.status == EditPackageStatus.CREATING.value,
                )
                .values(
                    status=EditPackageStatus.SUCCEEDED.value,
                    manifest_asset_id=persistence.manifest_asset_id,
                    zip_asset_id=persistence.zip_asset_id,
                    error_code=None,
                    safe_error_message=None,
                    completed_at=now,
                )
            )
            transition_task(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
            connection.execute(
                update(TaskRow)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                )
                .values(
                    status=TaskStatus.SUCCEEDED.value,
                    worker_id=None,
                    lease_token=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
                .values(outcome=AttemptOutcome.SUCCEEDED.value, finished_at=now)
            )
            connection.execute(
                insert(AuditEventRow).values(
                    id=new_id(),
                    actor_user_id=work.requested_by_user_id,
                    actor_username=work.requested_by_username,
                    action="edit_package.succeeded",
                    target_type="edit_package",
                    target_id=work.edit_package_id,
                    project_id=work.project_id,
                    before_json={"status": EditPackageStatus.CREATING.value},
                    after_json={
                        "status": EditPackageStatus.SUCCEEDED.value,
                        "version": f"v{work.version:03d}",
                        "clip_count": len(work.clips),
                    },
                    correlation_id=None,
                    created_at=now,
                )
            )
            return True

    def get_clip_handoff_download(self, clip_id: str) -> ClipHandoffDownload:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    CandidateClipRow.project_id,
                    CandidateClipRow.pipeline_run_id,
                    CandidateClipRow.current_revision,
                    EditPlanRevisionRow.id.label("revision_id"),
                    EditPlanRevisionRow.title,
                    PipelineRunRow.config_json,
                )
                .join(
                    EditPlanRevisionRow,
                    (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
                    & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
                )
                .join(PipelineRunRow, PipelineRunRow.id == CandidateClipRow.pipeline_run_id)
                .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
                .where(
                    CandidateClipRow.id == clip_id,
                    CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
                    CandidateClipRow.selected_for_review.is_(True),
                    ProjectRow.lifecycle != ProjectLifecycle.ARCHIVED.value,
                )
            ).one_or_none()
            if row is None:
                raise EditPackageResourceNotFound("clip does not exist")
            render = connection.execute(
                select(RenderJobRow.id, RenderJobRow.asset_id, RenderJobRow.spec_json)
                .where(
                    RenderJobRow.candidate_clip_id == clip_id,
                    RenderJobRow.edit_plan_revision_id == row.revision_id,
                    RenderJobRow.edit_plan_revision == row.current_revision,
                    RenderJobRow.kind == "proxy",
                    RenderJobRow.status == RenderStatus.SUCCEEDED.value,
                )
                .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
                .limit(1)
            ).one_or_none()
            if (
                render is None
                or render.asset_id is None
                or not is_clean_review_proxy(
                    spec=render.spec_json,
                    pipeline_config=row.config_json,
                )
            ):
                raise EditPackageConflict("clip has no current clean review video")
            asset = connection.execute(
                select(AssetRow.id, AssetRow.kind).where(
                    AssetRow.id == render.asset_id,
                    AssetRow.project_id == row.project_id,
                    AssetRow.candidate_clip_id == clip_id,
                    AssetRow.edit_plan_revision == row.current_revision,
                    AssetRow.status == AssetStatus.COMMITTED.value,
                )
            ).one_or_none()
            if asset is None or asset.kind != "review_proxy":
                raise EditPackageConflict("clip review video asset is invalid")
            captions = tuple(
                CaptionCue(
                    start_ms=int(cue.start_ms),
                    end_ms=int(cue.end_ms),
                    text=str(cue.text),
                )
                for cue in connection.execute(
                    select(CaptionCueRow.start_ms, CaptionCueRow.end_ms, CaptionCueRow.text)
                    .where(CaptionCueRow.edit_plan_revision_id == row.revision_id)
                    .order_by(CaptionCueRow.cue_index)
                )
            )
            from liveclip.domain.edit_plan import captions_to_srt

            return ClipHandoffDownload(
                project_id=str(row.project_id),
                clip_id=clip_id,
                edit_plan_revision=int(row.current_revision),
                title=str(row.title),
                video_asset_id=str(asset.id),
                subtitle_srt=captions_to_srt(captions),
            )


def _project_evidence(connection: Connection, project_id: str) -> _ProjectEvidence:
    owner = aliased(WorkspaceUserRow)
    row = connection.execute(
        select(
            ProjectRow.id,
            ProjectRow.name,
            ProjectRow.lifecycle,
            ProjectRow.current_pipeline_run_id,
            ProjectRow.current_generation,
            ProjectRow.revision_epoch,
            PipelineRunRow.status.label("run_status"),
            PipelineRunRow.config_json,
            SourceMediaRow.filename,
            SourceMediaRow.sha256,
            owner.username.label("owner_username"),
        )
        .join(PipelineRunRow, PipelineRunRow.id == ProjectRow.current_pipeline_run_id)
        .join(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
        .join(owner, owner.id == ProjectRow.owner_id)
        .where(ProjectRow.id == project_id)
    ).one_or_none()
    if row is None or row.current_pipeline_run_id is None:
        raise EditPackageResourceNotFound("project does not exist")
    if row.lifecycle == ProjectLifecycle.ARCHIVED.value:
        raise EditPackageConflict("archived projects cannot create edit packages")
    if row.run_status != PipelineRunStatus.COMPLETED.value:
        raise EditPackageConflict("project pipeline is not complete")
    if not isinstance(row.config_json, dict):
        raise EditPackageConflict("project pipeline configuration is invalid")
    return _ProjectEvidence(
        project_id=str(row.id),
        project_name=str(row.name),
        owner_username=str(row.owner_username),
        run_id=str(row.current_pipeline_run_id),
        generation=int(row.current_generation),
        revision_epoch=int(row.revision_epoch),
        pipeline_config=dict(row.config_json),
        source_filename=str(row.filename),
        source_fingerprint=str(row.sha256),
    )


def _require_active_editor(
    connection: Connection,
    *,
    project_id: str,
    user_id: str,
) -> str:
    row = connection.execute(
        select(WorkspaceUserRow.username, WorkspaceUserRow.is_active, ProjectMemberRow.role)
        .join(ProjectMemberRow, ProjectMemberRow.user_id == WorkspaceUserRow.id)
        .where(
            WorkspaceUserRow.id == user_id,
            ProjectMemberRow.project_id == project_id,
        )
    ).one_or_none()
    if row is None or not row.is_active or row.role not in {"owner", "editor"}:
        raise EditPackageConflict("requester no longer has edit-package permission")
    return str(row.username)


def _metadata_from_summary(summary: ClipSummary) -> EditPackageClipMetadata:
    return EditPackageClipMetadata(
        clip_id=summary.clip_id,
        candidate_key=summary.candidate_key,
        edit_plan_revision=summary.edit_plan_revision,
        source_start_ms=summary.source_start_ms,
        source_end_ms=summary.source_end_ms,
        score=summary.score,
        title=summary.title,
        high_impact_sentence=summary.hook,
        recommendation_reason=summary.reason,
        risk_flags=summary.risk_flags,
        captions=summary.captions,
        keywords=summary.keywords,
        review_status=summary.review_status,
    )


def _current_clip_evidence(
    connection: Connection,
    *,
    project: _ProjectEvidence,
    metadata: EditPackageClipMetadata,
    expected_proxy_asset_id: str | None,
    expected_revision_id: str | None = None,
    expected_render_job_id: str | None = None,
    expected_contact_sheet_asset_id: str | None = None,
) -> _ClipEvidence:
    row = connection.execute(
        select(
            CandidateClipRow.candidate_key,
            CandidateClipRow.current_revision,
            EditPlanRevisionRow.id.label("revision_id"),
            EditPlanRevisionRow.source_start_ms,
            EditPlanRevisionRow.source_end_ms,
            EditPlanRevisionRow.score,
            EditPlanRevisionRow.title,
            EditPlanRevisionRow.reason,
            EditPlanRevisionRow.risk_flags_json,
            EditPlanRevisionRow.plan_json,
        )
        .join(
            EditPlanRevisionRow,
            (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
            & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
        )
        .where(
            CandidateClipRow.id == metadata.clip_id,
            CandidateClipRow.project_id == project.project_id,
            CandidateClipRow.pipeline_run_id == project.run_id,
            CandidateClipRow.selected_for_review.is_(True),
            CandidateClipRow.current_revision == metadata.edit_plan_revision,
        )
    ).one_or_none()
    if row is None:
        raise EditPackageConflict("selected clip revision is no longer current")
    plan = edit_plan_from_json_data(row.plan_json)
    current_review = connection.scalar(
        select(ReviewDecisionRow.status)
        .where(ReviewDecisionRow.edit_plan_revision_id == row.revision_id)
        .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
        .limit(1)
    )
    review_status = (
        ReviewStatus(str(current_review))
        if current_review is not None
        else ReviewStatus.PENDING_REVIEW
    )
    captions = tuple(
        CaptionCue(
            start_ms=int(cue.start_ms),
            end_ms=int(cue.end_ms),
            text=str(cue.text),
        )
        for cue in connection.execute(
            select(CaptionCueRow.start_ms, CaptionCueRow.end_ms, CaptionCueRow.text)
            .where(CaptionCueRow.edit_plan_revision_id == row.revision_id)
            .order_by(CaptionCueRow.cue_index)
        )
    )
    if (
        str(row.candidate_key) != metadata.candidate_key
        or int(row.source_start_ms) != metadata.source_start_ms
        or int(row.source_end_ms) != metadata.source_end_ms
        or float(row.score) != metadata.score
        or str(row.title) != metadata.title
        or plan.hook != metadata.high_impact_sentence
        or str(row.reason) != metadata.recommendation_reason
        or tuple(str(value) for value in row.risk_flags_json) != metadata.risk_flags
        or captions != metadata.captions
        or review_status != metadata.review_status
        or (expected_revision_id is not None and str(row.revision_id) != expected_revision_id)
    ):
        raise EditPackageConflict("selected clip metadata changed")
    render = connection.execute(
        select(
            RenderJobRow.id,
            RenderJobRow.task_id,
            RenderJobRow.asset_id,
            RenderJobRow.contact_sheet_asset_id,
            RenderJobRow.spec_fingerprint,
            RenderJobRow.spec_json,
            RenderJobRow.revision_epoch,
        )
        .where(
            RenderJobRow.candidate_clip_id == metadata.clip_id,
            RenderJobRow.edit_plan_revision_id == row.revision_id,
            RenderJobRow.edit_plan_revision == metadata.edit_plan_revision,
            RenderJobRow.kind == "proxy",
            RenderJobRow.status == RenderStatus.SUCCEEDED.value,
        )
        .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
        .limit(1)
    ).one_or_none()
    if (
        render is None
        or render.asset_id is None
        or render.contact_sheet_asset_id is None
        or not is_clean_review_proxy(
            spec=render.spec_json,
            pipeline_config=project.pipeline_config,
        )
        or (expected_proxy_asset_id is not None and str(render.asset_id) != expected_proxy_asset_id)
        or (expected_render_job_id is not None and str(render.id) != expected_render_job_id)
        or (
            expected_contact_sheet_asset_id is not None
            and str(render.contact_sheet_asset_id) != expected_contact_sheet_asset_id
        )
    ):
        raise EditPackageConflict("selected clip has no current clean review render")
    asset_ids = (str(render.asset_id), str(render.contact_sheet_asset_id))
    assets = connection.execute(
        select(
            AssetRow.id,
            AssetRow.kind,
            AssetRow.relative_path,
            AssetRow.sha256,
            AssetRow.size_bytes,
            AssetRow.generation,
            AssetRow.edit_plan_revision,
            AssetRow.revision_epoch,
            AssetRow.input_fingerprint,
            AssetRow.producer_attempt_id,
            AssetRow.validation_json,
        ).where(
            AssetRow.id.in_(asset_ids),
            AssetRow.project_id == project.project_id,
            AssetRow.candidate_clip_id == metadata.clip_id,
            AssetRow.status == AssetStatus.COMMITTED.value,
        )
    ).all()
    by_id = {str(asset.id): asset for asset in assets}
    video = by_id.get(str(render.asset_id))
    contact = by_id.get(str(render.contact_sheet_asset_id))
    if video is None or contact is None:
        raise EditPackageConflict("selected clip review assets are missing")
    if any(
        not asset.sha256
        or int(asset.size_bytes or 0) <= 0
        or asset.generation is None
        or int(asset.generation) != project.generation
        or asset.edit_plan_revision is None
        or int(asset.edit_plan_revision) != metadata.edit_plan_revision
        or asset.revision_epoch is None
        or int(asset.revision_epoch) != int(render.revision_epoch)
        or asset.producer_attempt_id is None
        or not isinstance(asset.validation_json, dict)
        for asset in (video, contact)
    ):
        raise EditPackageConflict("selected clip review assets are stale or invalid")
    if int(render.revision_epoch) > project.revision_epoch:
        raise EditPackageConflict("selected clip render is ahead of the project")
    _validate_proxy_producer(
        connection,
        project=project,
        render=render,
        assets=(video, contact),
    )
    if (
        video.kind != "review_proxy"
        or video.validation_json.get("full_decode") != "passed"
        or contact.kind != "render_contact_sheet"
        or isinstance(contact.validation_json.get("frames"), bool)
        or not isinstance(contact.validation_json.get("frames"), int)
        or int(contact.validation_json["frames"]) < 3
    ):
        raise EditPackageConflict("selected clip review quality contract is invalid")
    return _ClipEvidence(
        edit_plan_revision_id=str(row.revision_id),
        render_job_id=str(render.id),
        video_asset_id=str(video.id),
        video_relative_path=str(video.relative_path),
        video_sha256=str(video.sha256),
        video_size_bytes=int(video.size_bytes),
        contact_sheet_asset_id=str(contact.id),
        contact_sheet_relative_path=str(contact.relative_path),
        contact_sheet_sha256=str(contact.sha256),
        contact_sheet_size_bytes=int(contact.size_bytes),
    )


def _validate_proxy_producer(
    connection: Connection,
    *,
    project: _ProjectEvidence,
    render: Any,
    assets: tuple[Any, Any],
) -> None:
    attempt_ids = {str(asset.producer_attempt_id) for asset in assets}
    if len(attempt_ids) != 1:
        raise EditPackageConflict("selected clip review assets have different producers")
    attempt_id = next(iter(attempt_ids))
    producer = connection.execute(
        select(
            TaskAttemptRow.id.label("attempt_id"),
            TaskAttemptRow.outcome,
            TaskRow.id.label("task_id"),
            TaskRow.kind,
            TaskRow.input_fingerprint,
            TaskRow.pipeline_run_id,
            TaskRow.status.label("task_status"),
            StageRunRow.stage,
        )
        .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
        .outerjoin(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
        .where(TaskAttemptRow.id == attempt_id)
    ).one_or_none()
    if (
        producer is None
        or str(producer.task_id) != str(render.task_id)
        or str(producer.pipeline_run_id) != project.run_id
        or producer.task_status != TaskStatus.SUCCEEDED.value
        or producer.outcome != AttemptOutcome.SUCCEEDED.value
    ):
        raise EditPackageConflict("selected clip review producer lineage is invalid")
    producer_kind = str(producer.kind)
    producer_stage = str(producer.stage) if producer.stage is not None else None
    if producer_kind == TaskKind.RENDER.value:
        if (
            producer_stage is not None
            or str(producer.input_fingerprint) != str(render.spec_fingerprint)
            or any(str(asset.input_fingerprint) != str(render.spec_fingerprint) for asset in assets)
        ):
            raise EditPackageConflict("selected manual proxy producer lineage is invalid")
    elif producer_kind == TaskKind.STAGE.value:
        if producer_stage != PipelineStage.PROXY_RENDER.value or any(
            str(asset.input_fingerprint) != str(render.spec_fingerprint) for asset in assets
        ):
            raise EditPackageConflict("selected pipeline proxy producer lineage is invalid")
    else:
        raise EditPackageConflict("selected clip review producer kind is invalid")


def _leased_package_row(
    connection: Connection,
    lease: LeaseIdentity,
    *,
    now: datetime,
) -> Any | None:
    requester = aliased(WorkspaceUserRow)
    owner = aliased(WorkspaceUserRow)
    return connection.execute(
        select(
            TaskRow.id.label("task_id"),
            TaskRow.target_id,
            TaskRow.input_fingerprint,
            TaskRow.expected_generation,
            TaskRow.expected_revision_epoch,
            EditPackageRow.id.label("edit_package_id"),
            EditPackageRow.status.label("package_status"),
            EditPackageRow.version,
            EditPackageRow.preset,
            EditPackageRow.content,
            EditPackageRow.include_zip,
            EditPackageRow.snapshot_fingerprint,
            EditPackageRow.created_at.label("package_created_at"),
            EditPackageRow.requested_by_user_id,
            requester.username.label("requester_username"),
            ProjectRow.id.label("project_id"),
            ProjectRow.name.label("project_name"),
            ProjectRow.owner_id,
            owner.username.label("owner_username"),
            ProjectRow.current_pipeline_run_id.label("run_id"),
            ProjectRow.current_generation,
            ProjectRow.revision_epoch,
            ProjectRow.lifecycle,
            PipelineRunRow.status.label("run_status"),
            PipelineRunRow.config_json,
            SourceMediaRow.filename.label("source_filename"),
            SourceMediaRow.sha256.label("source_fingerprint"),
        )
        .join(EditPackageRow, EditPackageRow.task_id == TaskRow.id)
        .join(ProjectRow, ProjectRow.id == EditPackageRow.project_id)
        .join(PipelineRunRow, PipelineRunRow.id == ProjectRow.current_pipeline_run_id)
        .join(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
        .join(requester, requester.id == EditPackageRow.requested_by_user_id)
        .join(owner, owner.id == ProjectRow.owner_id)
        .where(
            TaskRow.id == lease.task_id,
            TaskRow.kind == TaskKind.DELIVERY.value,
            TaskRow.status == TaskStatus.RUNNING.value,
            TaskRow.worker_id == lease.worker_id,
            TaskRow.lease_token == lease.lease_token,
            TaskRow.lease_expires_at > now,
            TaskRow.cancellation_requested_at.is_(None),
        )
    ).one_or_none()


def _work_from_row(connection: Connection, row: Any) -> EditPackageWork:
    project = _ProjectEvidence(
        project_id=str(row.project_id),
        project_name=str(row.project_name),
        owner_username=str(row.owner_username),
        run_id=str(row.run_id),
        generation=int(row.current_generation),
        revision_epoch=int(row.revision_epoch),
        pipeline_config=dict(row.config_json),
        source_filename=str(row.source_filename),
        source_fingerprint=str(row.source_fingerprint),
    )
    clips: list[EditPackageWorkClip] = []
    stored_rows = connection.execute(
        _package_clip_select()
        .where(EditPackageClipRow.edit_package_id == row.edit_package_id)
        .order_by(EditPackageClipRow.ordinal)
    )
    for stored in stored_rows:
        metadata = _metadata_from_stored_json(stored.metadata_json)
        evidence = _current_clip_evidence(
            connection,
            project=project,
            metadata=metadata,
            expected_proxy_asset_id=str(stored.video_asset_id),
            expected_revision_id=str(stored.edit_plan_revision_id),
            expected_render_job_id=str(stored.render_job_id),
            expected_contact_sheet_asset_id=str(stored.contact_sheet_asset_id),
        )
        clips.append(
            EditPackageWorkClip(
                ordinal=int(stored.ordinal),
                edit_plan_revision_id=evidence.edit_plan_revision_id,
                render_job_id=evidence.render_job_id,
                metadata=metadata,
                video_asset_id=evidence.video_asset_id,
                video_relative_path=evidence.video_relative_path,
                video_sha256=evidence.video_sha256,
                video_size_bytes=evidence.video_size_bytes,
                contact_sheet_asset_id=evidence.contact_sheet_asset_id,
                contact_sheet_relative_path=evidence.contact_sheet_relative_path,
                contact_sheet_sha256=evidence.contact_sheet_sha256,
                contact_sheet_size_bytes=evidence.contact_sheet_size_bytes,
            )
        )
    if not clips:
        raise EditPackageConflict("edit package selection is empty")
    return EditPackageWork(
        edit_package_id=str(row.edit_package_id),
        task_id=str(row.task_id),
        project_id=project.project_id,
        project_name=project.project_name,
        owner_username=project.owner_username,
        requested_by_user_id=str(row.requested_by_user_id),
        requested_by_username=str(row.requester_username),
        run_id=project.run_id,
        generation=project.generation,
        revision_epoch=project.revision_epoch,
        version=int(row.version),
        preset=cast(EditPackagePreset, str(row.preset)),
        content=cast(EditPackageContent, str(row.content)),
        include_zip=bool(row.include_zip),
        snapshot_fingerprint=str(row.snapshot_fingerprint),
        package_fingerprint=str(row.input_fingerprint),
        created_at=row.package_created_at,
        source_filename=project.source_filename,
        source_fingerprint=project.source_fingerprint,
        clips=tuple(clips),
    )


def _assert_work_current(connection: Connection, work: EditPackageWork) -> None:
    project = _project_evidence(connection, work.project_id)
    _require_active_editor(
        connection,
        project_id=work.project_id,
        user_id=work.requested_by_user_id,
    )
    if (
        project.run_id != work.run_id
        or project.generation != work.generation
        or project.revision_epoch != work.revision_epoch
        or project.source_fingerprint != work.source_fingerprint
    ):
        raise EditPackageConflict("project changed after edit-package selection")
    rows = connection.execute(
        _package_clip_select()
        .where(EditPackageClipRow.edit_package_id == work.edit_package_id)
        .order_by(EditPackageClipRow.ordinal)
    ).all()
    if len(rows) != len(work.clips):
        raise EditPackageConflict("edit package selection changed")
    current: list[tuple[EditPackageClipMetadata, _ClipEvidence]] = []
    for stored, clip in zip(rows, work.clips, strict=True):
        if int(stored.ordinal) != clip.ordinal:
            raise EditPackageConflict("edit package selection order changed")
        metadata = _metadata_from_stored_json(stored.metadata_json)
        evidence = _current_clip_evidence(
            connection,
            project=project,
            metadata=metadata,
            expected_proxy_asset_id=str(stored.video_asset_id),
            expected_revision_id=str(stored.edit_plan_revision_id),
            expected_render_job_id=str(stored.render_job_id),
            expected_contact_sheet_asset_id=str(stored.contact_sheet_asset_id),
        )
        current.append((metadata, evidence))
    fingerprint = _selection_fingerprint(
        project=project,
        requested_by_user_id=work.requested_by_user_id,
        preset=work.preset,
        content=work.content,
        clips=current,
    )
    if fingerprint != work.snapshot_fingerprint:
        raise EditPackageConflict("edit package selection fingerprint changed")


def _selection_fingerprint(
    *,
    project: _ProjectEvidence,
    requested_by_user_id: str,
    preset: str,
    content: str,
    clips: list[tuple[EditPackageClipMetadata, _ClipEvidence]],
) -> str:
    payload = {
        "schema_version": "edit-package-selection-v1",
        "project_id": project.project_id,
        "run_id": project.run_id,
        "generation": project.generation,
        "revision_epoch": project.revision_epoch,
        "source_fingerprint": project.source_fingerprint,
        "requested_by_user_id": requested_by_user_id,
        "preset": preset,
        "content": content,
        "clips": [
            {
                "metadata": metadata.model_dump(mode="json"),
                "revision_id": evidence.edit_plan_revision_id,
                "render_id": evidence.render_job_id,
                "video_asset_id": evidence.video_asset_id,
                "video_sha256": evidence.video_sha256,
                "contact_sheet_asset_id": evidence.contact_sheet_asset_id,
                "contact_sheet_sha256": evidence.contact_sheet_sha256,
            }
            for metadata, evidence in clips
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _metadata_from_stored_json(value: object) -> EditPackageClipMetadata:
    """Validate SQLAlchemy JSON using Pydantic's strict JSON representation rules."""

    return EditPackageClipMetadata.model_validate_json(
        json.dumps(value, sort_keys=True, separators=(",", ":"))
    )


def _package_clip_select() -> Select[Any]:
    return select(
        EditPackageClipRow.id,
        EditPackageClipRow.edit_package_id,
        EditPackageClipRow.ordinal,
        EditPackageClipRow.candidate_clip_id,
        EditPackageClipRow.edit_plan_revision_id,
        EditPackageClipRow.render_job_id,
        EditPackageClipRow.edit_plan_revision,
        EditPackageClipRow.metadata_json,
        EditPackageClipRow.video_asset_id,
        EditPackageClipRow.contact_sheet_asset_id,
    )


def _package_fingerprint(
    *,
    snapshot_fingerprint: str,
    edit_package_id: str,
    version: int,
    include_zip: bool,
    created_at: datetime,
) -> str:
    payload = {
        "schema_version": "edit-package-task-v1",
        "snapshot_fingerprint": snapshot_fingerprint,
        "edit_package_id": edit_package_id,
        "version": version,
        "include_zip": include_zip,
        "created_at": created_at.astimezone(UTC).isoformat(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _snapshot_select() -> Select[Any]:
    return select(
        EditPackageRow.id,
        EditPackageRow.project_id,
        EditPackageRow.task_id,
        EditPackageRow.requested_by_user_id,
        EditPackageRow.version,
        EditPackageRow.status,
        EditPackageRow.preset,
        EditPackageRow.content,
        EditPackageRow.manifest_asset_id,
        EditPackageRow.zip_asset_id,
        EditPackageRow.include_zip,
        EditPackageRow.error_code,
        EditPackageRow.safe_error_message,
        EditPackageRow.created_at,
        EditPackageRow.completed_at,
        func.count(EditPackageClipRow.id).label("clip_count"),
    ).outerjoin(
        EditPackageClipRow,
        EditPackageClipRow.edit_package_id == EditPackageRow.id,
    )


def _get_edit_package(connection: Connection, edit_package_id: str) -> EditPackageSnapshot:
    row = connection.execute(
        _snapshot_select().where(EditPackageRow.id == edit_package_id).group_by(EditPackageRow.id)
    ).one_or_none()
    if row is None or row.task_id is None:
        raise EditPackageResourceNotFound("edit package does not exist")
    return _snapshot(row)


def _snapshot(row: Any) -> EditPackageSnapshot:
    return EditPackageSnapshot(
        edit_package_id=str(row.id),
        project_id=str(row.project_id),
        task_id=str(row.task_id),
        requested_by_user_id=str(row.requested_by_user_id),
        version=int(row.version),
        package_version=f"v{int(row.version):03d}",
        status=EditPackageStatus(str(row.status)),
        clip_count=int(row.clip_count),
        preset=cast(EditPackagePreset, str(row.preset)),
        content=cast(EditPackageContent, str(row.content)),
        manifest_asset_id=(str(row.manifest_asset_id) if row.manifest_asset_id else None),
        zip_asset_id=str(row.zip_asset_id) if row.zip_asset_id else None,
        include_zip=bool(row.include_zip),
        error_code=str(row.error_code) if row.error_code else None,
        safe_error_message=(str(row.safe_error_message) if row.safe_error_message else None),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _validate_package_assets(
    by_id: Mapping[str, Any],
    *,
    work: EditPackageWork,
    persistence: EditPackagePersistence,
) -> None:
    manifest = by_id[persistence.manifest_asset_id]
    validation = manifest.validation_json
    if (
        manifest.kind != "edit_package_manifest"
        or manifest.relative_path != f"edit-packages/v{work.version:03d}/manifest.json"
        or manifest.input_fingerprint != work.package_fingerprint
        or not manifest.sha256
        or int(manifest.size_bytes or 0) <= 0
        or manifest.generation is None
        or int(manifest.generation) != work.generation
        or manifest.revision_epoch is None
        or int(manifest.revision_epoch) != work.revision_epoch
        or not isinstance(validation, dict)
        or validation.get("schema_version") != "liveclip.edit-package.v1"
        or validation.get("edit_package_id") != work.edit_package_id
        or validation.get("snapshot_fingerprint") != work.snapshot_fingerprint
        or validation.get("clip_count") != len(work.clips)
    ):
        raise EditPackageConflict("edit package manifest asset is invalid")
    if work.include_zip:
        if persistence.zip_asset_id is None:
            raise EditPackageConflict("edit package ZIP is missing")
        archive = by_id[persistence.zip_asset_id]
        archive_validation = archive.validation_json
        if (
            archive.kind != "edit_package_zip"
            or archive.relative_path
            != (f"edit-packages/v{work.version:03d}/liveclip-edit-package-v{work.version:03d}.zip")
            or archive.input_fingerprint != work.package_fingerprint
            or not archive.sha256
            or int(archive.size_bytes or 0) <= 0
            or archive.generation is None
            or int(archive.generation) != work.generation
            or archive.revision_epoch is None
            or int(archive.revision_epoch) != work.revision_epoch
            or not isinstance(archive_validation, dict)
            or archive_validation.get("schema_version") != "liveclip.edit-package.v1"
            or archive_validation.get("edit_package_id") != work.edit_package_id
            or archive_validation.get("snapshot_fingerprint") != work.snapshot_fingerprint
        ):
            raise EditPackageConflict("edit package ZIP asset is invalid")
    elif persistence.zip_asset_id is not None:
        raise EditPackageConflict("non-ZIP package unexpectedly has a ZIP asset")


def _validate_manifest_clip(
    work_clip: EditPackageWorkClip,
    manifest_clip: EditPackageManifestClip,
) -> None:
    metadata = work_clip.metadata
    if (
        manifest_clip.clip_id != metadata.clip_id
        or manifest_clip.ordinal != work_clip.ordinal
        or manifest_clip.edit_plan_revision != metadata.edit_plan_revision
        or manifest_clip.title != metadata.title
        or manifest_clip.thumbnail_sha256 != work_clip.contact_sheet_sha256
        or (manifest_clip.video_sha256 is not None) != (manifest_clip.video_filename is not None)
        or (manifest_clip.subtitle_sha256 is not None)
        != (manifest_clip.subtitle_filename is not None)
    ):
        raise EditPackageConflict("edit package manifest clip snapshot changed")
