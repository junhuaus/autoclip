from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.rendering import (
    QueuedRender,
    RenderConflict,
    RenderPersistence,
    RenderProfile,
    RenderResourceNotFound,
    RenderWork,
    render_asset_paths,
)
from liveclip.application.reviewing import RenderRequest
from liveclip.application.tasks import validate_task_diagnostic_relative_path
from liveclip.config.fonts import detect_chinese_font
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AssetRow,
    CandidateClipRow,
    CaptionCueRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.domain.edit_plan import CaptionCue, edit_plan_from_json_data
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    PipelineRunStatus,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    TaskKind,
    TaskStatus,
    transition_render,
    transition_task,
)
from liveclip.media.fingerprint import stream_sha256
from liveclip.renderer.contracts import (
    FFMPEG_RENDERER_CONTRACT_VERSION,
    RENDER_SPEC_SCHEMA_VERSION,
    has_current_manual_render_contract,
    text_mode_for_render_kind,
)


class SqlAlchemyRenderRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def enqueue_render(
        self,
        clip_id: str,
        request: RenderRequest,
        profile: RenderProfile,
        idempotency: IdempotencyContext | None = None,
    ) -> QueuedRender:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            replay_render_id = load_idempotent_resource(
                connection, idempotency, resource_type="render"
            )
            if replay_render_id is not None:
                return _queued_render(connection, replay_render_id)
            row = _load_enqueue_context(connection, clip_id)
            revision_number = int(row.current_revision)
            if request.expected_revision != revision_number:
                raise RenderConflict("clip revision changed; reload before rendering")
            if row.run_status != PipelineRunStatus.COMPLETED.value:
                raise RenderConflict("clip pipeline is not complete")
            review_status = _latest_review_status(connection, str(row.revision_id))
            if request.kind == "final" and review_status != ReviewStatus.APPROVED:
                raise RenderConflict("final render requires approval of the current revision")
            width, height = (
                (profile.preview_width, profile.preview_height)
                if request.kind == "proxy"
                else (profile.final_width, profile.final_height)
            )
            captions = _load_captions(connection, str(row.revision_id))
            font_path = detect_chinese_font().resolve(strict=True)
            text_mode = text_mode_for_render_kind(request.kind)
            spec = {
                "schema_version": RENDER_SPEC_SCHEMA_VERSION,
                "kind": request.kind,
                "width": width,
                "height": height,
                "encoder": profile.encoder,
                "renderer": FFMPEG_RENDERER_CONTRACT_VERSION,
                "ffmpeg_argv_schema": "liveclip-ffmpeg-argv-v1",
                "overlay_renderer": "pillow-overlay-v1",
                "text_mode": text_mode,
                "revision_epoch": int(row.revision_epoch),
                "source_sha256": str(row.source_sha256),
                "source_streams": {
                    "video": int(row.video_stream_index),
                    "audio": int(row.audio_stream_index),
                },
                "source_identity": {
                    "size_bytes": int(row.source_size_bytes),
                    "mtime_ns": int(row.source_mtime_ns),
                    "device": int(row.source_device) if row.source_device is not None else None,
                    "inode": int(row.source_inode) if row.source_inode is not None else None,
                },
                "font": {
                    "filename": font_path.name,
                    "sha256": stream_sha256(font_path),
                },
                "revision": row.plan_json,
                "captions": [cue.model_dump(mode="json") for cue in captions],
            }
            spec_fingerprint = _fingerprint(spec)
            existing = connection.execute(
                select(
                    RenderJobRow.id,
                    RenderJobRow.task_id,
                    RenderJobRow.status,
                ).where(
                    RenderJobRow.candidate_clip_id == clip_id,
                    RenderJobRow.edit_plan_revision_id == row.revision_id,
                    RenderJobRow.kind == request.kind,
                    RenderJobRow.spec_fingerprint == spec_fingerprint,
                    RenderJobRow.status != RenderStatus.STALE.value,
                )
            ).one_or_none()
            if existing is not None:
                render_id = str(existing.id)
                task_id = str(existing.task_id) if existing.task_id else ""
                status = RenderStatus(str(existing.status))
                if status == RenderStatus.FAILED:
                    task_id = _requeue_failed_render(
                        connection,
                        render_id=render_id,
                        task_id=task_id,
                        clip_id=clip_id,
                        run_id=str(row.run_id),
                        generation=int(row.generation),
                        revision=revision_number,
                        revision_epoch=int(row.revision_epoch),
                        input_fingerprint=spec_fingerprint,
                        max_retries=profile.max_retries,
                        now=now,
                    )
                    status = RenderStatus.QUEUED
                if not task_id:
                    raise RenderConflict("render has no durable task owner")
                result = QueuedRender(
                    render_id=render_id,
                    task_id=task_id,
                    clip_id=clip_id,
                    edit_plan_revision=revision_number,
                    kind=request.kind,
                    status=status,
                )
                record_idempotent_resource(
                    connection,
                    idempotency,
                    resource_type="render",
                    resource_id=render_id,
                )
                return result
            render_id = new_id()
            task_id = new_id()
            connection.execute(
                insert(TaskRow).values(
                    id=task_id,
                    kind=TaskKind.RENDER.value,
                    target_id=clip_id,
                    operation_key=f"render:{render_id}",
                    input_fingerprint=spec_fingerprint,
                    resource_class=ResourceClass.HEAVY.value,
                    pipeline_run_id=row.run_id,
                    status=TaskStatus.QUEUED.value,
                    priority=800,
                    not_before=now,
                    expected_generation=row.generation,
                    expected_revision=revision_number,
                    expected_revision_epoch=row.revision_epoch,
                    attempt_count=0,
                    retry_count=0,
                    manual_retry_count=0,
                    max_retries=profile.max_retries,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(RenderJobRow).values(
                    id=render_id,
                    candidate_clip_id=clip_id,
                    edit_plan_revision_id=row.revision_id,
                    task_id=task_id,
                    kind=request.kind,
                    status=RenderStatus.QUEUED.value,
                    edit_plan_revision=revision_number,
                    revision_epoch=row.revision_epoch,
                    width=width,
                    height=height,
                    spec_fingerprint=spec_fingerprint,
                    spec_json=spec,
                    created_at=now,
                    updated_at=now,
                )
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="render",
                resource_id=render_id,
            )
            return QueuedRender(
                render_id=render_id,
                task_id=task_id,
                clip_id=clip_id,
                edit_plan_revision=revision_number,
                kind=request.kind,
                status=RenderStatus.QUEUED,
            )

    def start_render(self, lease: LeaseIdentity) -> RenderWork:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    TaskRow.id.label("task_id"),
                    TaskRow.target_id,
                    TaskRow.input_fingerprint,
                    TaskRow.expected_generation,
                    TaskRow.expected_revision,
                    TaskRow.expected_revision_epoch,
                    RenderJobRow.id.label("render_id"),
                    RenderJobRow.status.label("render_status"),
                    RenderJobRow.kind,
                    RenderJobRow.width,
                    RenderJobRow.height,
                    RenderJobRow.spec_fingerprint,
                    RenderJobRow.spec_json,
                    RenderJobRow.edit_plan_revision_id.label("revision_id"),
                    CandidateClipRow.id.label("clip_id"),
                    CandidateClipRow.current_revision,
                    CandidateClipRow.pipeline_run_id.label("run_id"),
                    EditPlanRevisionRow.plan_json,
                    EditPlanRevisionRow.parent_revision,
                    EditPlanRevisionRow.origin,
                    EditPlanRevisionRow.created_at.label("revision_created_at"),
                    PipelineRunRow.status.label("run_status"),
                    PipelineRunRow.generation,
                    ProjectRow.id.label("project_id"),
                    ProjectRow.current_pipeline_run_id,
                    ProjectRow.current_generation,
                    ProjectRow.revision_epoch,
                    SourceMediaRow.resolved_path,
                    SourceMediaRow.sha256.label("source_sha256"),
                    SourceMediaRow.size_bytes.label("source_size_bytes"),
                    SourceMediaRow.mtime_ns.label("source_mtime_ns"),
                    SourceMediaRow.device.label("source_device"),
                    SourceMediaRow.inode.label("source_inode"),
                    SourceMediaRow.video_stream_index,
                    SourceMediaRow.audio_stream_index,
                )
                .join(RenderJobRow, RenderJobRow.task_id == TaskRow.id)
                .join(CandidateClipRow, CandidateClipRow.id == RenderJobRow.candidate_clip_id)
                .join(
                    EditPlanRevisionRow,
                    EditPlanRevisionRow.id == RenderJobRow.edit_plan_revision_id,
                )
                .join(PipelineRunRow, PipelineRunRow.id == CandidateClipRow.pipeline_run_id)
                .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
                .join(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.kind == TaskKind.RENDER.value,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    TaskRow.cancellation_requested_at.is_(None),
                )
            ).one_or_none()
            if row is None:
                raise RenderConflict("render task lost its active lease")
            if (
                str(row.target_id) != str(row.clip_id)
                or str(row.run_id) != str(row.current_pipeline_run_id)
                or int(row.generation) != int(row.current_generation)
                or int(row.expected_generation) != int(row.current_generation)
                or int(row.expected_revision) != int(row.current_revision)
                or int(row.expected_revision_epoch) != int(row.revision_epoch)
                or row.run_status != PipelineRunStatus.COMPLETED.value
                or str(row.input_fingerprint) != str(row.spec_fingerprint)
            ):
                raise RenderConflict("render task is stale for the current clip revision")
            if (
                str(row.kind) == "final"
                and _latest_review_status(connection, str(row.revision_id)) != ReviewStatus.APPROVED
            ):
                raise RenderConflict("final render approval is no longer current")
            current_status = RenderStatus(str(row.render_status))
            if current_status == RenderStatus.FAILED:
                transition_render(current_status, RenderStatus.QUEUED)
                current_status = RenderStatus.QUEUED
            transition_render(current_status, RenderStatus.RUNNING)
            connection.execute(
                update(RenderJobRow)
                .where(
                    RenderJobRow.id == row.render_id,
                    RenderJobRow.status.in_([RenderStatus.QUEUED.value, RenderStatus.FAILED.value]),
                )
                .values(
                    status=RenderStatus.RUNNING.value,
                    error_code=None,
                    safe_error_message=None,
                    updated_at=now,
                )
            )
            plan = edit_plan_from_json_data(row.plan_json)
            revision = EditPlanRevision(
                clip_id=str(row.clip_id),
                revision=int(row.current_revision),
                parent_revision=(
                    int(row.parent_revision) if row.parent_revision is not None else None
                ),
                origin=RevisionOrigin(str(row.origin)),
                plan=plan,
                captions=_load_captions(connection, str(row.revision_id)),
                created_at=row.revision_created_at,
            )
            spec = row.spec_json
            if not isinstance(spec, dict) or _fingerprint(spec) != str(row.spec_fingerprint):
                raise RenderConflict("render specification is missing or changed")
            encoder = spec.get("encoder")
            if not isinstance(encoder, str):
                raise RenderConflict("render encoder specification is invalid")
            if not has_current_manual_render_contract(str(row.kind), spec):
                raise RenderConflict("render text specification is invalid")
            source_path = Path(str(row.resolved_path))
            if not _source_matches_persisted_identity(source_path, row, spec):
                raise RenderConflict("source media changed after it was imported")
            font_path = detect_chinese_font().resolve(strict=True)
            font_spec = spec.get("font")
            if (
                not isinstance(font_spec, dict)
                or font_spec.get("filename") != font_path.name
                or font_spec.get("sha256") != stream_sha256(font_path)
            ):
                raise RenderConflict("configured Chinese font changed after render enqueue")
            return RenderWork(
                render_id=str(row.render_id),
                task_id=str(row.task_id),
                project_id=str(row.project_id),
                run_id=str(row.run_id),
                generation=int(row.generation),
                revision_epoch=int(row.revision_epoch),
                source_path=source_path,
                source_size_bytes=int(row.source_size_bytes),
                source_mtime_ns=int(row.source_mtime_ns),
                source_device=(int(row.source_device) if row.source_device is not None else None),
                source_inode=int(row.source_inode) if row.source_inode is not None else None,
                source_sha256=str(row.source_sha256),
                video_stream_index=int(row.video_stream_index),
                audio_stream_index=int(row.audio_stream_index),
                font_path=font_path,
                revision=revision,
                kind=str(row.kind),
                width=int(row.width),
                height=int(row.height),
                encoder=encoder,
                spec_fingerprint=str(row.spec_fingerprint),
            )

    def get_render(self, render_id: str) -> QueuedRender:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    RenderJobRow.id,
                    RenderJobRow.task_id,
                    RenderJobRow.candidate_clip_id,
                    RenderJobRow.edit_plan_revision,
                    RenderJobRow.kind,
                    RenderJobRow.status,
                ).where(RenderJobRow.id == render_id)
            ).one_or_none()
        if row is None or row.task_id is None:
            raise RenderResourceNotFound("render does not exist")
        return QueuedRender(
            render_id=str(row.id),
            task_id=str(row.task_id),
            clip_id=str(row.candidate_clip_id),
            edit_plan_revision=int(row.edit_plan_revision),
            kind=str(row.kind),
            status=RenderStatus(str(row.status)),
        )

    def complete_render(
        self,
        lease: LeaseIdentity,
        work: RenderWork,
        persistence: RenderPersistence,
    ) -> bool:
        now = datetime.now(UTC)
        if work.task_id != lease.task_id:
            raise RenderConflict("render work belongs to another task")
        diagnostic_relative_path = validate_task_diagnostic_relative_path(
            persistence.diagnostic_relative_path
        )
        if diagnostic_relative_path is not None:
            parts = diagnostic_relative_path.split("/")
            if parts[1:3] != [lease.task_id, lease.lease_token]:
                raise RenderConflict("render diagnostic belongs to another task attempt")
        if not _source_matches_work_identity(work):
            raise RenderConflict("source media changed while the render was executing")
        asset_ids = (
            persistence.video_asset_id,
            persistence.subtitle_asset_id,
            persistence.quality_report_asset_id,
            persistence.contact_sheet_asset_id,
        )
        if len(set(asset_ids)) != len(asset_ids):
            raise RenderConflict("render completion assets must be distinct")
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    TaskRow.expected_generation,
                    TaskRow.expected_revision,
                    TaskRow.expected_revision_epoch,
                    TaskRow.pipeline_run_id.label("task_run_id"),
                    RenderJobRow.status,
                    CandidateClipRow.current_revision,
                    CandidateClipRow.pipeline_run_id,
                    ProjectRow.current_pipeline_run_id,
                    ProjectRow.current_generation,
                    ProjectRow.revision_epoch,
                )
                .join(RenderJobRow, RenderJobRow.task_id == TaskRow.id)
                .join(CandidateClipRow, CandidateClipRow.id == RenderJobRow.candidate_clip_id)
                .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    TaskRow.cancellation_requested_at.is_(None),
                    RenderJobRow.id == work.render_id,
                )
            ).one_or_none()
            if row is None:
                return False
            if (
                str(row.pipeline_run_id) != str(row.current_pipeline_run_id)
                or str(row.task_run_id) != work.run_id
                or str(row.pipeline_run_id) != work.run_id
                or int(row.expected_generation) != int(row.current_generation)
                or int(row.expected_revision) != int(row.current_revision)
                or int(row.expected_revision_epoch) != int(row.revision_epoch)
                or int(row.current_generation) != work.generation
                or int(row.revision_epoch) != work.revision_epoch
            ):
                return False
            assets = connection.execute(
                select(
                    AssetRow.id,
                    AssetRow.kind,
                    AssetRow.relative_path,
                    AssetRow.candidate_clip_id,
                    AssetRow.generation,
                    AssetRow.edit_plan_revision,
                    AssetRow.revision_epoch,
                    AssetRow.input_fingerprint,
                    AssetRow.sha256,
                    AssetRow.size_bytes,
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
                raise RenderConflict("render completion requires four committed assets")
            producer_attempt_ids = {
                str(asset.producer_attempt_id)
                for asset in assets
                if asset.producer_attempt_id is not None
            }
            producer_task_ids = set(
                str(value)
                for value in connection.scalars(
                    select(TaskAttemptRow.task_id).where(
                        TaskAttemptRow.id.in_(producer_attempt_ids)
                    )
                )
            )
            if any(asset.producer_attempt_id is None for asset in assets) or producer_task_ids != {
                lease.task_id
            }:
                raise RenderConflict("render assets belong to another task")
            for asset in assets:
                if (
                    str(asset.candidate_clip_id) != work.revision.clip_id
                    or int(asset.generation) != work.generation
                    or int(asset.edit_plan_revision) != work.revision.revision
                    or int(asset.revision_epoch) != work.revision_epoch
                    or str(asset.input_fingerprint) != work.spec_fingerprint
                    or not asset.sha256
                    or int(asset.size_bytes or 0) <= 0
                    or not isinstance(asset.validation_json, dict)
                ):
                    raise RenderConflict("render asset ownership differs from its task")
            expected_kinds = {
                persistence.video_asset_id: (
                    "review_proxy" if work.kind == "proxy" else "final_video"
                ),
                persistence.subtitle_asset_id: "clip_subtitle_srt",
                persistence.quality_report_asset_id: "render_quality_report",
                persistence.contact_sheet_asset_id: "render_contact_sheet",
            }
            if any(str(by_id[asset_id].kind) != kind for asset_id, kind in expected_kinds.items()):
                raise RenderConflict("render committed asset kinds are invalid")
            paths = render_asset_paths(work)
            expected_paths = {
                persistence.video_asset_id: paths.video,
                persistence.subtitle_asset_id: paths.subtitle,
                persistence.quality_report_asset_id: paths.quality_report,
                persistence.contact_sheet_asset_id: paths.contact_sheet,
            }
            if any(
                str(by_id[asset_id].relative_path) != path
                for asset_id, path in expected_paths.items()
            ):
                raise RenderConflict("render committed asset paths are invalid")
            video_validation = by_id[persistence.video_asset_id].validation_json
            subtitle_validation = by_id[persistence.subtitle_asset_id].validation_json
            quality_validation = by_id[persistence.quality_report_asset_id].validation_json
            contact_validation = by_id[persistence.contact_sheet_asset_id].validation_json
            if not all(
                isinstance(value, dict)
                for value in (
                    video_validation,
                    subtitle_validation,
                    quality_validation,
                    contact_validation,
                )
            ):
                raise RenderConflict("render validation metadata is missing")
            assert isinstance(video_validation, dict)
            assert isinstance(subtitle_validation, dict)
            assert isinstance(quality_validation, dict)
            assert isinstance(contact_validation, dict)
            if (
                video_validation.get("full_decode") != "passed"
                or video_validation.get("width") != work.width
                or video_validation.get("height") != work.height
            ):
                raise RenderConflict("render video validation contract is incomplete")
            if subtitle_validation.get("timeline") != "clip_relative_ms" or subtitle_validation.get(
                "cue_count"
            ) != len(work.revision.captions):
                raise RenderConflict("render subtitle validation contract is incomplete")
            if quality_validation.get("automatic_status") != "passed":
                raise RenderConflict("render quality validation contract is incomplete")
            frames = contact_validation.get("frames")
            if isinstance(frames, bool) or not isinstance(frames, int) or frames < 3:
                raise RenderConflict("render contact sheet validation contract is incomplete")
            transition_render(RenderStatus(str(row.status)), RenderStatus.SUCCEEDED)
            completed_render = connection.execute(
                update(RenderJobRow)
                .where(
                    RenderJobRow.id == work.render_id,
                    RenderJobRow.task_id == lease.task_id,
                    RenderJobRow.status == RenderStatus.RUNNING.value,
                )
                .values(
                    status=RenderStatus.SUCCEEDED.value,
                    asset_id=persistence.video_asset_id,
                    subtitle_asset_id=persistence.subtitle_asset_id,
                    quality_report_asset_id=persistence.quality_report_asset_id,
                    contact_sheet_asset_id=persistence.contact_sheet_asset_id,
                    error_code=None,
                    safe_error_message=None,
                    updated_at=now,
                )
                .returning(RenderJobRow.id)
            ).scalar_one_or_none()
            if completed_render is None:
                return False
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
                .values(
                    outcome=AttemptOutcome.SUCCEEDED.value,
                    finished_at=now,
                    diagnostic_relative_path=diagnostic_relative_path,
                )
            )
            return True


def _load_enqueue_context(connection: Connection, clip_id: str):  # type: ignore[no-untyped-def]
    row = connection.execute(
        select(
            CandidateClipRow.current_revision,
            CandidateClipRow.pipeline_run_id.label("run_id"),
            EditPlanRevisionRow.id.label("revision_id"),
            EditPlanRevisionRow.plan_json,
            PipelineRunRow.status.label("run_status"),
            PipelineRunRow.generation,
            ProjectRow.revision_epoch,
            SourceMediaRow.sha256.label("source_sha256"),
            SourceMediaRow.size_bytes.label("source_size_bytes"),
            SourceMediaRow.mtime_ns.label("source_mtime_ns"),
            SourceMediaRow.device.label("source_device"),
            SourceMediaRow.inode.label("source_inode"),
            SourceMediaRow.video_stream_index,
            SourceMediaRow.audio_stream_index,
        )
        .join(
            EditPlanRevisionRow,
            (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
            & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
        )
        .join(PipelineRunRow, PipelineRunRow.id == CandidateClipRow.pipeline_run_id)
        .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
        .join(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
        .where(
            CandidateClipRow.id == clip_id,
            CandidateClipRow.selected_for_review.is_(True),
            CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
        )
    ).one_or_none()
    if row is None:
        raise RenderResourceNotFound("clip does not exist in the current project generation")
    return row


def _queued_render(connection: Connection, render_id: str) -> QueuedRender:
    row = connection.execute(
        select(
            RenderJobRow.id,
            RenderJobRow.task_id,
            RenderJobRow.candidate_clip_id,
            RenderJobRow.edit_plan_revision,
            RenderJobRow.kind,
            RenderJobRow.status,
        ).where(RenderJobRow.id == render_id)
    ).one_or_none()
    if row is None or row.task_id is None:
        raise RenderConflict("idempotent render resource no longer exists")
    return QueuedRender(
        render_id=str(row.id),
        task_id=str(row.task_id),
        clip_id=str(row.candidate_clip_id),
        edit_plan_revision=int(row.edit_plan_revision),
        kind=str(row.kind),
        status=RenderStatus(str(row.status)),
    )


def _source_matches_persisted_identity(
    source_path: Path, row: object, spec: dict[str, object]
) -> bool:
    try:
        if source_path.resolve(strict=True) != source_path:
            return False
        metadata = source_path.stat()
    except (OSError, RuntimeError):
        return False
    identity = spec.get("source_identity")
    streams = spec.get("source_streams")
    if (
        not isinstance(identity, dict)
        or spec.get("source_sha256") != str(row.source_sha256)  # type: ignore[attr-defined]
        or streams
        != {
            "video": int(row.video_stream_index),  # type: ignore[attr-defined]
            "audio": int(row.audio_stream_index),  # type: ignore[attr-defined]
        }
    ):
        return False
    observed = {
        "size_bytes": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "device": getattr(metadata, "st_dev", None),
        "inode": getattr(metadata, "st_ino", None),
    }
    persisted = {
        "size_bytes": int(row.source_size_bytes),  # type: ignore[attr-defined]
        "mtime_ns": int(row.source_mtime_ns),  # type: ignore[attr-defined]
        "device": int(row.source_device) if row.source_device is not None else None,  # type: ignore[attr-defined]
        "inode": int(row.source_inode) if row.source_inode is not None else None,  # type: ignore[attr-defined]
    }
    return identity == persisted == observed


def _source_matches_work_identity(work: RenderWork) -> bool:
    try:
        if work.source_path.resolve(strict=True) != work.source_path:
            return False
        metadata = work.source_path.stat()
    except (OSError, RuntimeError):
        return False
    return (
        metadata.st_size == work.source_size_bytes
        and metadata.st_mtime_ns == work.source_mtime_ns
        and getattr(metadata, "st_dev", None) == work.source_device
        and getattr(metadata, "st_ino", None) == work.source_inode
    )


def _latest_review_status(connection: Connection, revision_id: str) -> ReviewStatus:
    value = connection.scalar(
        select(ReviewDecisionRow.status)
        .where(ReviewDecisionRow.edit_plan_revision_id == revision_id)
        .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
        .limit(1)
    )
    return ReviewStatus(str(value)) if value is not None else ReviewStatus.PENDING_REVIEW


def _load_captions(connection: Connection, revision_id: str) -> tuple[CaptionCue, ...]:
    return tuple(
        CaptionCue(start_ms=int(row.start_ms), end_ms=int(row.end_ms), text=str(row.text))
        for row in connection.execute(
            select(CaptionCueRow.start_ms, CaptionCueRow.end_ms, CaptionCueRow.text)
            .where(CaptionCueRow.edit_plan_revision_id == revision_id)
            .order_by(CaptionCueRow.cue_index)
        )
    )


def _fingerprint(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _requeue_failed_render(
    connection: Connection,
    *,
    render_id: str,
    task_id: str,
    clip_id: str,
    run_id: str,
    generation: int,
    revision: int,
    revision_epoch: int,
    input_fingerprint: str,
    max_retries: int,
    now: datetime,
) -> str:
    if task_id:
        task_status = connection.scalar(select(TaskRow.status).where(TaskRow.id == task_id))
        if task_status == TaskStatus.FAILED.value:
            transition_task(TaskStatus.FAILED, TaskStatus.QUEUED)
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == task_id, TaskRow.status == TaskStatus.FAILED.value)
                .values(
                    status=TaskStatus.QUEUED.value,
                    retry_count=0,
                    manual_retry_count=TaskRow.manual_retry_count + 1,
                    not_before=now,
                    failure_class=None,
                    error_code=None,
                    safe_error_message=None,
                    completed_at=None,
                    updated_at=now,
                )
            )
        elif task_status not in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}:
            task_id = ""
    if not task_id:
        task_id = new_id()
        connection.execute(
            insert(TaskRow).values(
                id=task_id,
                kind=TaskKind.RENDER.value,
                target_id=clip_id,
                operation_key=f"render:{render_id}:retry:{task_id}",
                input_fingerprint=input_fingerprint,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=run_id,
                status=TaskStatus.QUEUED.value,
                priority=800,
                not_before=now,
                expected_generation=generation,
                expected_revision=revision,
                expected_revision_epoch=revision_epoch,
                attempt_count=0,
                retry_count=0,
                manual_retry_count=1,
                max_retries=max_retries,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            update(RenderJobRow).where(RenderJobRow.id == render_id).values(task_id=task_id)
        )
    transition_render(RenderStatus.FAILED, RenderStatus.QUEUED)
    connection.execute(
        update(RenderJobRow)
        .where(RenderJobRow.id == render_id, RenderJobRow.status == RenderStatus.FAILED.value)
        .values(
            status=RenderStatus.QUEUED.value,
            error_code=None,
            safe_error_message=None,
            updated_at=now,
        )
    )
    return task_id
