from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.stage_execution import (
    PersistedCandidate,
    PersistedRevision,
    PreparedRevision,
    ProxyRenderIntent,
    ProxyRenderPersistence,
    StageMutationFence,
)
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AssetRow,
    AudioChunkRow,
    CandidateClipRow,
    CaptionCueRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    RenderJobRow,
    SourceMediaRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
    TranscriptRow,
    TranscriptSegmentRow,
    TranscriptWordRow,
)
from liveclip.domain.candidate import CandidateClip
from liveclip.domain.edit_plan import CaptionCue, EditPlan
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    PipelineRunStatus,
    RenderStatus,
    StageRunStatus,
    TaskStatus,
    transition_render,
)
from liveclip.domain.transcript import TranscriptDocument
from liveclip.media.models import AudioChunkManifest, SourceMediaMetadata


class StageDataConflict(RuntimeError):
    """Persisted stage data differs from the immutable retry input."""


class SqlAlchemyStageStateStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def save_source(
        self,
        fence: StageMutationFence,
        *,
        source: SourceMediaMetadata,
    ) -> str:
        payload = source.model_dump(mode="json")
        with begin_immediate(self._engine) as connection:
            _assert_mutation_fence(connection, fence)
            existing = connection.execute(
                select(SourceMediaRow.id, SourceMediaRow.probe_json).where(
                    SourceMediaRow.project_id == fence.project_id
                )
            ).one_or_none()
            if existing is not None:
                if (
                    SourceMediaMetadata.model_validate_json(json.dumps(existing.probe_json))
                    != source
                ):
                    raise StageDataConflict("persisted source media differs from retry input")
                return str(existing.id)
            source_id = new_id()
            connection.execute(
                insert(SourceMediaRow).values(
                    id=source_id,
                    project_id=fence.project_id,
                    resolved_path=str(source.resolved_path),
                    filename=source.filename,
                    sha256=source.sha256,
                    size_bytes=source.size_bytes,
                    mtime_ns=source.mtime_ns,
                    device=source.device,
                    inode=source.inode,
                    duration_ms=source.duration_ms,
                    width=source.video_width,
                    height=source.video_height,
                    video_codec=source.video_codec,
                    audio_codec=source.audio_codec,
                    frame_rate=str(source.video_frame_rate),
                    probe_json=payload,
                    created_at=datetime.now(UTC),
                )
            )
            return source_id

    def load_source(self, *, project_id: str) -> SourceMediaMetadata:
        with self._engine.connect() as connection:
            payload = connection.scalar(
                select(SourceMediaRow.probe_json).where(SourceMediaRow.project_id == project_id)
            )
        if not isinstance(payload, dict):
            raise StageDataConflict("source media is not persisted")
        return SourceMediaMetadata.model_validate_json(json.dumps(payload))

    def save_audio(
        self,
        fence: StageMutationFence,
        *,
        manifest: AudioChunkManifest,
        chunk_asset_ids: Mapping[int, str],
    ) -> None:
        if not manifest.complete:
            raise StageDataConflict("audio manifest is not complete")
        expected_indexes = {chunk.index for chunk in manifest.chunks}
        if set(chunk_asset_ids) != expected_indexes:
            raise StageDataConflict("audio chunk assets do not match the manifest")
        with begin_immediate(self._engine) as connection:
            _assert_mutation_fence(connection, fence)
            existing = connection.execute(
                select(
                    AudioChunkRow.chunk_index,
                    AudioChunkRow.asset_id,
                    AudioChunkRow.sha256,
                    AudioChunkRow.cache_key,
                    AudioChunkRow.source_start_ms,
                    AudioChunkRow.source_end_ms,
                )
                .where(AudioChunkRow.pipeline_run_id == fence.run_id)
                .order_by(AudioChunkRow.chunk_index)
            ).all()
            if existing:
                expected = [
                    (
                        chunk.index,
                        chunk_asset_ids[chunk.index],
                        chunk.sha256,
                        chunk.cache_key,
                        chunk.source_start_ms,
                        chunk.source_end_ms,
                    )
                    for chunk in manifest.chunks
                ]
                if list(existing) != expected:
                    raise StageDataConflict("persisted audio chunks differ from retry output")
                return
            now = datetime.now(UTC)
            for chunk in manifest.chunks:
                connection.execute(
                    insert(AudioChunkRow).values(
                        id=new_id(),
                        pipeline_run_id=fence.run_id,
                        stage_run_id=fence.stage_run_id,
                        asset_id=chunk_asset_ids[chunk.index],
                        chunk_index=chunk.index,
                        source_start_ms=chunk.source_start_ms,
                        source_end_ms=chunk.source_end_ms,
                        overlap_before_ms=chunk.overlap_before_ms,
                        overlap_after_ms=chunk.overlap_after_ms,
                        size_bytes=chunk.size_bytes,
                        sha256=chunk.sha256,
                        cache_key=chunk.cache_key,
                        provider_status="succeeded",
                        created_at=now,
                    )
                )

    def save_transcript(
        self,
        fence: StageMutationFence,
        *,
        transcript: TranscriptDocument,
        transcript_asset_id: str,
        fingerprint: str,
        provider: str,
        model: str,
    ) -> str:
        with begin_immediate(self._engine) as connection:
            _assert_mutation_fence(connection, fence)
            existing = connection.execute(
                select(
                    TranscriptRow.id,
                    TranscriptRow.fingerprint,
                    TranscriptRow.provider,
                    TranscriptRow.model,
                ).where(TranscriptRow.pipeline_run_id == fence.run_id)
            ).one_or_none()
            if existing is not None:
                if (existing.fingerprint, existing.provider, existing.model) != (
                    fingerprint,
                    provider,
                    model,
                ):
                    raise StageDataConflict("persisted transcript differs from retry output")
                return str(existing.id)
            transcript_id = new_id()
            connection.execute(
                insert(TranscriptRow).values(
                    id=transcript_id,
                    pipeline_run_id=fence.run_id,
                    asset_id=transcript_asset_id,
                    language=transcript.language,
                    provider=provider,
                    model=model,
                    word_timing_status=transcript.word_timing_status.value,
                    fingerprint=fingerprint,
                    created_at=datetime.now(UTC),
                )
            )
            for segment_index, segment in enumerate(transcript.segments):
                segment_id = new_id()
                connection.execute(
                    insert(TranscriptSegmentRow).values(
                        id=segment_id,
                        transcript_id=transcript_id,
                        segment_index=segment_index,
                        source_start_ms=segment.start_ms,
                        source_end_ms=segment.end_ms,
                        text=segment.text,
                        source_chunk_ids_json=list(segment.source_chunk_ids),
                    )
                )
                for word_index, word in enumerate(segment.words or ()):
                    connection.execute(
                        insert(TranscriptWordRow).values(
                            id=new_id(),
                            segment_id=segment_id,
                            word_index=word_index,
                            source_start_ms=word.start_ms,
                            source_end_ms=word.end_ms,
                            text=word.text,
                        )
                    )
            return transcript_id

    def save_candidates(
        self,
        fence: StageMutationFence,
        *,
        candidates: Sequence[CandidateClip],
    ) -> tuple[PersistedCandidate, ...]:
        if not candidates:
            raise StageDataConflict("candidate generation produced no clips")
        with begin_immediate(self._engine) as connection:
            _assert_mutation_fence(connection, fence)
            existing = self._load_candidates(connection, run_id=fence.run_id)
            if existing:
                if tuple(item.candidate for item in existing) != tuple(candidates):
                    raise StageDataConflict("persisted candidates differ from retry output")
                return existing
            now = datetime.now(UTC)
            persisted: list[PersistedCandidate] = []
            for rank, candidate in enumerate(candidates, start=1):
                candidate_id = new_id()
                connection.execute(
                    insert(CandidateClipRow).values(
                        id=candidate_id,
                        project_id=fence.project_id,
                        pipeline_run_id=fence.run_id,
                        candidate_key=candidate.candidate_id,
                        source_start_ms=candidate.source_start_ms,
                        source_end_ms=candidate.source_end_ms,
                        allowed_start_ms=candidate.allowed_start_ms,
                        allowed_end_ms=candidate.allowed_end_ms,
                        transcript_text=candidate.text,
                        context_before=candidate.context_before,
                        context_after=candidate.context_after,
                        rule_score=candidate.rule_score,
                        reasons_json=list(candidate.reasons),
                        segment_ids_json=list(candidate.segment_ids),
                        current_revision=0,
                        rank=rank,
                        selected_for_review=False,
                        created_at=now,
                    )
                )
                persisted.append(
                    PersistedCandidate(
                        candidate_id=candidate_id,
                        candidate=candidate,
                        rank=rank,
                    )
                )
            return tuple(persisted)

    def load_candidates(self, *, run_id: str) -> tuple[PersistedCandidate, ...]:
        with self._engine.connect() as connection:
            return self._load_candidates(connection, run_id=run_id)

    def save_revisions(
        self,
        fence: StageMutationFence,
        prepared: Sequence[PreparedRevision],
    ) -> tuple[PersistedRevision, ...]:
        if not prepared:
            raise StageDataConflict("editing produced no review candidates")
        with begin_immediate(self._engine) as connection:
            _assert_mutation_fence(connection, fence)
            candidate_rows = connection.execute(
                select(CandidateClipRow.id, CandidateClipRow.pipeline_run_id).where(
                    CandidateClipRow.id.in_([item.candidate_id for item in prepared])
                )
            ).all()
            if len(candidate_rows) != len(prepared):
                raise StageDataConflict("editing references an unknown candidate")
            run_ids = {str(row.pipeline_run_id) for row in candidate_rows}
            if len(run_ids) != 1:
                raise StageDataConflict("editing candidates span multiple pipeline runs")
            run_id = next(iter(run_ids))
            if run_id != fence.run_id:
                raise StageDataConflict("editing candidates do not belong to the fenced run")
            connection.execute(
                update(CandidateClipRow)
                .where(CandidateClipRow.pipeline_run_id == run_id)
                .values(selected_for_review=False)
            )
            persisted: list[PersistedRevision] = []
            for item in prepared:
                revision = item.revision
                if revision.clip_id != item.candidate_id or revision.revision != 1:
                    raise StageDataConflict("initial EditPlan revision identity is invalid")
                existing_id = connection.scalar(
                    select(EditPlanRevisionRow.id).where(
                        EditPlanRevisionRow.candidate_clip_id == item.candidate_id,
                        EditPlanRevisionRow.revision == revision.revision,
                    )
                )
                if existing_id is None:
                    revision_id = new_id()
                    plan = revision.plan
                    connection.execute(
                        insert(EditPlanRevisionRow).values(
                            id=revision_id,
                            candidate_clip_id=item.candidate_id,
                            revision=revision.revision,
                            parent_revision=revision.parent_revision,
                            origin=revision.origin.value,
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
                            created_at=revision.created_at,
                        )
                    )
                    for cue_index, cue in enumerate(revision.captions):
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
                else:
                    revision_id = str(existing_id)
                    if self._load_revision(connection, revision_id) != revision:
                        raise StageDataConflict("persisted EditPlan differs from retry output")
                connection.execute(
                    update(CandidateClipRow)
                    .where(CandidateClipRow.id == item.candidate_id)
                    .values(
                        current_revision=revision.revision,
                        rank=item.rank,
                        selected_for_review=True,
                    )
                )
                persisted.append(
                    PersistedRevision(
                        candidate_id=item.candidate_id,
                        edit_plan_revision_id=revision_id,
                        revision=revision,
                    )
                )
            return tuple(persisted)

    def load_current_revisions(self, *, run_id: str) -> tuple[PersistedRevision, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    CandidateClipRow.id,
                    EditPlanRevisionRow.id.label("revision_id"),
                )
                .join(
                    EditPlanRevisionRow,
                    (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
                    & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
                )
                .where(
                    CandidateClipRow.pipeline_run_id == run_id,
                    CandidateClipRow.selected_for_review.is_(True),
                )
                .order_by(CandidateClipRow.rank, CandidateClipRow.id)
            ).all()
            return tuple(
                PersistedRevision(
                    candidate_id=str(row.id),
                    edit_plan_revision_id=str(row.revision_id),
                    revision=self._load_revision(connection, str(row.revision_id)),
                )
                for row in rows
            )

    def start_proxy_render(
        self,
        fence: StageMutationFence,
        value: ProxyRenderIntent,
    ) -> str:
        with begin_immediate(self._engine) as connection:
            _assert_mutation_fence(connection, fence)
            _validate_proxy_intent(connection, fence, value)
            existing = connection.execute(
                select(
                    RenderJobRow.id,
                    RenderJobRow.status,
                    RenderJobRow.task_id,
                    RenderJobRow.edit_plan_revision,
                    RenderJobRow.revision_epoch,
                    RenderJobRow.width,
                    RenderJobRow.height,
                ).where(
                    RenderJobRow.candidate_clip_id == value.candidate_id,
                    RenderJobRow.edit_plan_revision_id == value.edit_plan_revision_id,
                    RenderJobRow.kind == "proxy",
                    RenderJobRow.spec_fingerprint == value.spec_fingerprint,
                )
            ).one_or_none()
            if existing is not None:
                if (
                    existing.task_id != fence.lease.task_id
                    or int(existing.edit_plan_revision) != value.edit_plan_revision
                    or int(existing.revision_epoch) != value.revision_epoch
                    or int(existing.width) != value.width
                    or int(existing.height) != value.height
                ):
                    raise StageDataConflict("persisted proxy render differs from retry intent")
                render_id = str(existing.id)
                status = RenderStatus(str(existing.status))
                if status == RenderStatus.SUCCEEDED:
                    return render_id
                if status == RenderStatus.STALE:
                    raise StageDataConflict("stale proxy render cannot be restarted")
                if status == RenderStatus.RUNNING:
                    return render_id
                if status == RenderStatus.FAILED:
                    transition_render(status, RenderStatus.QUEUED)
                    connection.execute(
                        update(RenderJobRow)
                        .where(RenderJobRow.id == render_id)
                        .values(
                            status=RenderStatus.QUEUED.value,
                            error_code=None,
                            safe_error_message=None,
                            updated_at=datetime.now(UTC),
                        )
                    )
                    status = RenderStatus.QUEUED
                transition_render(status, RenderStatus.RUNNING)
                connection.execute(
                    update(RenderJobRow)
                    .where(
                        RenderJobRow.id == render_id,
                        RenderJobRow.status == RenderStatus.QUEUED.value,
                    )
                    .values(status=RenderStatus.RUNNING.value, updated_at=datetime.now(UTC))
                )
                return render_id
            render_id = new_id()
            now = datetime.now(UTC)
            connection.execute(
                insert(RenderJobRow).values(
                    id=render_id,
                    candidate_clip_id=value.candidate_id,
                    edit_plan_revision_id=value.edit_plan_revision_id,
                    task_id=fence.lease.task_id,
                    kind="proxy",
                    status=RenderStatus.QUEUED.value,
                    edit_plan_revision=value.edit_plan_revision,
                    revision_epoch=value.revision_epoch,
                    width=value.width,
                    height=value.height,
                    spec_fingerprint=value.spec_fingerprint,
                    created_at=now,
                    updated_at=now,
                )
            )
            transition_render(RenderStatus.QUEUED, RenderStatus.RUNNING)
            connection.execute(
                update(RenderJobRow)
                .where(
                    RenderJobRow.id == render_id,
                    RenderJobRow.status == RenderStatus.QUEUED.value,
                )
                .values(status=RenderStatus.RUNNING.value, updated_at=now)
            )
            return render_id

    def save_proxy_render(
        self,
        fence: StageMutationFence,
        render_id: str,
        value: ProxyRenderPersistence,
    ) -> str:
        with begin_immediate(self._engine) as connection:
            _assert_mutation_fence(connection, fence)
            _validate_proxy_intent(
                connection,
                fence,
                ProxyRenderIntent(
                    candidate_id=value.candidate_id,
                    edit_plan_revision_id=value.edit_plan_revision_id,
                    edit_plan_revision=value.edit_plan_revision,
                    revision_epoch=value.revision_epoch,
                    width=value.width,
                    height=value.height,
                    spec_fingerprint=value.spec_fingerprint,
                ),
            )
            existing = connection.execute(
                select(
                    RenderJobRow.status,
                    RenderJobRow.task_id,
                    RenderJobRow.candidate_clip_id,
                    RenderJobRow.edit_plan_revision_id,
                    RenderJobRow.edit_plan_revision,
                    RenderJobRow.revision_epoch,
                    RenderJobRow.width,
                    RenderJobRow.height,
                    RenderJobRow.spec_fingerprint,
                    RenderJobRow.asset_id,
                    RenderJobRow.quality_report_asset_id,
                    RenderJobRow.contact_sheet_asset_id,
                ).where(RenderJobRow.id == render_id, RenderJobRow.kind == "proxy")
            ).one_or_none()
            if existing is None:
                raise StageDataConflict("proxy render was not started before completion")
            expected_spec = (
                fence.lease.task_id,
                value.candidate_id,
                value.edit_plan_revision_id,
                value.edit_plan_revision,
                value.revision_epoch,
                value.width,
                value.height,
                value.spec_fingerprint,
            )
            if tuple(existing[1:9]) != expected_spec:
                raise StageDataConflict("proxy render completion differs from its intent")
            expected_assets = (
                value.video_asset_id,
                value.quality_report_asset_id,
                value.contact_sheet_asset_id,
            )
            status = RenderStatus(str(existing.status))
            if status == RenderStatus.SUCCEEDED:
                if tuple(existing[9:12]) != expected_assets:
                    raise StageDataConflict("persisted proxy render differs from retry output")
                return render_id
            if status != RenderStatus.RUNNING:
                raise StageDataConflict("proxy render is not running")
            _validate_proxy_assets(connection, fence, value)
            transition_render(status, RenderStatus.SUCCEEDED)
            completed = connection.execute(
                update(RenderJobRow)
                .where(
                    RenderJobRow.id == render_id,
                    RenderJobRow.status == RenderStatus.RUNNING.value,
                    RenderJobRow.task_id == fence.lease.task_id,
                )
                .values(
                    status=RenderStatus.SUCCEEDED.value,
                    asset_id=value.video_asset_id,
                    quality_report_asset_id=value.quality_report_asset_id,
                    contact_sheet_asset_id=value.contact_sheet_asset_id,
                    error_code=None,
                    safe_error_message=None,
                    updated_at=datetime.now(UTC),
                )
                .returning(RenderJobRow.id)
            ).scalar_one_or_none()
            if completed is None:
                raise StageDataConflict("proxy render completion lost its lifecycle fence")
            return render_id

    @staticmethod
    def _load_candidates(connection: Connection, *, run_id: str) -> tuple[PersistedCandidate, ...]:
        rows = connection.execute(
            select(
                CandidateClipRow.id,
                CandidateClipRow.candidate_key,
                CandidateClipRow.source_start_ms,
                CandidateClipRow.source_end_ms,
                CandidateClipRow.allowed_start_ms,
                CandidateClipRow.allowed_end_ms,
                CandidateClipRow.transcript_text,
                CandidateClipRow.context_before,
                CandidateClipRow.context_after,
                CandidateClipRow.rule_score,
                CandidateClipRow.reasons_json,
                CandidateClipRow.segment_ids_json,
                CandidateClipRow.rank,
            )
            .where(CandidateClipRow.pipeline_run_id == run_id)
            .order_by(CandidateClipRow.rank, CandidateClipRow.id)
        ).mappings()
        return tuple(
            PersistedCandidate(
                candidate_id=str(row["id"]),
                candidate=CandidateClip(
                    candidate_id=str(row["candidate_key"]),
                    source_start_ms=int(row["source_start_ms"]),
                    source_end_ms=int(row["source_end_ms"]),
                    allowed_start_ms=int(row["allowed_start_ms"]),
                    allowed_end_ms=int(row["allowed_end_ms"]),
                    text=str(row["transcript_text"]),
                    context_before=str(row["context_before"]),
                    context_after=str(row["context_after"]),
                    rule_score=float(row["rule_score"]),
                    reasons=tuple(str(value) for value in row["reasons_json"]),
                    segment_ids=tuple(str(value) for value in row["segment_ids_json"]),
                ),
                rank=int(row["rank"] or 0),
            )
            for row in rows
        )

    @staticmethod
    def _load_revision(connection: Connection, revision_id: str) -> EditPlanRevision:
        row = (
            connection.execute(
                select(
                    EditPlanRevisionRow.candidate_clip_id,
                    EditPlanRevisionRow.revision,
                    EditPlanRevisionRow.parent_revision,
                    EditPlanRevisionRow.origin,
                    EditPlanRevisionRow.plan_json,
                    EditPlanRevisionRow.created_at,
                ).where(EditPlanRevisionRow.id == revision_id)
            )
            .mappings()
            .one()
        )
        cues = connection.execute(
            select(CaptionCueRow.start_ms, CaptionCueRow.end_ms, CaptionCueRow.text)
            .where(CaptionCueRow.edit_plan_revision_id == revision_id)
            .order_by(CaptionCueRow.cue_index)
        ).mappings()
        return EditPlanRevision(
            clip_id=str(row["candidate_clip_id"]),
            revision=int(row["revision"]),
            parent_revision=(
                int(row["parent_revision"]) if row["parent_revision"] is not None else None
            ),
            origin=RevisionOrigin(str(row["origin"])),
            plan=EditPlan.model_validate_json(json.dumps(row["plan_json"])),
            captions=tuple(
                CaptionCue(
                    start_ms=int(cue["start_ms"]),
                    end_ms=int(cue["end_ms"]),
                    text=str(cue["text"]),
                )
                for cue in cues
            ),
            created_at=row["created_at"],
        )


def _assert_mutation_fence(connection: Connection, fence: StageMutationFence) -> None:
    now = datetime.now(UTC)
    owner = connection.scalar(
        select(TaskRow.id)
        .join(TaskAttemptRow, TaskAttemptRow.task_id == TaskRow.id)
        .join(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
        .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
        .join(ProjectRow, ProjectRow.id == PipelineRunRow.project_id)
        .where(
            TaskRow.id == fence.lease.task_id,
            TaskRow.worker_id == fence.lease.worker_id,
            TaskRow.lease_token == fence.lease.lease_token,
            TaskRow.status == TaskStatus.RUNNING.value,
            TaskRow.lease_expires_at > now,
            TaskRow.cancellation_requested_at.is_(None),
            TaskRow.pipeline_run_id == fence.run_id,
            TaskRow.stage_run_id == fence.stage_run_id,
            TaskRow.expected_generation == fence.generation,
            TaskAttemptRow.lease_token == fence.lease.lease_token,
            TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
            StageRunRow.status == StageRunStatus.RUNNING.value,
            PipelineRunRow.id == fence.run_id,
            PipelineRunRow.status == PipelineRunStatus.RUNNING.value,
            PipelineRunRow.generation == fence.generation,
            PipelineRunRow.cancellation_requested_at.is_(None),
            ProjectRow.id == fence.project_id,
            ProjectRow.current_generation == fence.generation,
            ProjectRow.current_pipeline_run_id == fence.run_id,
        )
    )
    if owner is None:
        raise StageDataConflict("stage mutation lost its task lease or project generation fence")


def _validate_proxy_intent(
    connection: Connection,
    fence: StageMutationFence,
    value: ProxyRenderIntent,
) -> None:
    if (
        value.edit_plan_revision <= 0
        or value.revision_epoch < 0
        or value.width <= 0
        or value.height <= 0
        or value.width >= value.height
        or not re.fullmatch(r"[a-f0-9]{64}", value.spec_fingerprint)
    ):
        raise StageDataConflict("proxy render intent is invalid")
    revision = connection.scalar(
        select(EditPlanRevisionRow.id)
        .join(CandidateClipRow, CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id)
        .where(
            CandidateClipRow.id == value.candidate_id,
            CandidateClipRow.project_id == fence.project_id,
            CandidateClipRow.pipeline_run_id == fence.run_id,
            CandidateClipRow.current_revision == value.edit_plan_revision,
            CandidateClipRow.selected_for_review.is_(True),
            EditPlanRevisionRow.id == value.edit_plan_revision_id,
            EditPlanRevisionRow.revision == value.edit_plan_revision,
        )
    )
    current_epoch = connection.scalar(
        select(ProjectRow.revision_epoch).where(ProjectRow.id == fence.project_id)
    )
    if revision is None or current_epoch is None or int(current_epoch) != value.revision_epoch:
        raise StageDataConflict("proxy render intent is not current for its project")


def _validate_proxy_assets(
    connection: Connection,
    fence: StageMutationFence,
    value: ProxyRenderPersistence,
) -> None:
    expected = {
        value.video_asset_id: "review_proxy",
        value.quality_report_asset_id: "render_quality_report",
        value.contact_sheet_asset_id: "render_contact_sheet",
    }
    if len(expected) != 3:
        raise StageDataConflict("proxy render assets must be distinct")
    rows = connection.execute(
        select(AssetRow.id, AssetRow.kind).where(
            AssetRow.id.in_(expected),
            AssetRow.project_id == fence.project_id,
            AssetRow.candidate_clip_id == value.candidate_id,
            AssetRow.status == AssetStatus.COMMITTED.value,
            AssetRow.generation == fence.generation,
            AssetRow.edit_plan_revision == value.edit_plan_revision,
            AssetRow.revision_epoch == value.revision_epoch,
        )
    ).all()
    actual = {str(asset_id): str(kind) for asset_id, kind in rows}
    if actual != expected:
        raise StageDataConflict("proxy render assets do not match its current revision")
