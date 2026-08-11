from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.engine import Engine

from liveclip.application.clips import ClipSummary
from liveclip.application.pipeline import PipelineResourceNotFound
from liveclip.db.models import (
    CandidateClipRow,
    CaptionCueRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    TranscriptRow,
    TranscriptSegmentRow,
    TranscriptWordRow,
)
from liveclip.domain.edit_plan import CaptionCue, edit_plan_from_json_data
from liveclip.domain.keywords import derive_keyword_occurrences
from liveclip.domain.state_transitions import RenderStatus, ReviewStatus
from liveclip.domain.transcript import TranscriptSegment, TranscriptWord
from liveclip.renderer.contracts import is_clean_review_proxy


class SqlAlchemyClipQueryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_project_clips(self, project_id: str) -> tuple[ClipSummary, ...]:
        with self._engine.connect() as connection:
            current_run_id = connection.scalar(
                select(ProjectRow.current_pipeline_run_id).where(ProjectRow.id == project_id)
            )
            if current_run_id is None:
                raise PipelineResourceNotFound("project does not exist")
            rows = connection.execute(
                select(
                    CandidateClipRow.id,
                    CandidateClipRow.candidate_key,
                    CandidateClipRow.current_revision,
                    CandidateClipRow.rank,
                    EditPlanRevisionRow.id.label("revision_id"),
                    EditPlanRevisionRow.source_start_ms,
                    EditPlanRevisionRow.source_end_ms,
                    EditPlanRevisionRow.score,
                    EditPlanRevisionRow.title,
                    EditPlanRevisionRow.reason,
                    EditPlanRevisionRow.risk_flags_json,
                    EditPlanRevisionRow.plan_json,
                    PipelineRunRow.config_json,
                )
                .join(
                    EditPlanRevisionRow,
                    (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
                    & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
                )
                .join(PipelineRunRow, PipelineRunRow.id == CandidateClipRow.pipeline_run_id)
                .where(
                    CandidateClipRow.project_id == project_id,
                    CandidateClipRow.pipeline_run_id == current_run_id,
                    CandidateClipRow.selected_for_review.is_(True),
                )
                .order_by(CandidateClipRow.rank, CandidateClipRow.id)
            ).mappings()
            segment_rows = tuple(
                connection.execute(
                    select(
                        TranscriptSegmentRow.id,
                        TranscriptSegmentRow.source_start_ms,
                        TranscriptSegmentRow.source_end_ms,
                        TranscriptSegmentRow.text,
                    )
                    .join(TranscriptRow, TranscriptRow.id == TranscriptSegmentRow.transcript_id)
                    .where(TranscriptRow.pipeline_run_id == current_run_id)
                    .order_by(TranscriptSegmentRow.segment_index)
                )
            )
            words_by_segment: defaultdict[str, list[TranscriptWord]] = defaultdict(list)
            for word_row in connection.execute(
                select(
                    TranscriptWordRow.segment_id,
                    TranscriptWordRow.source_start_ms,
                    TranscriptWordRow.source_end_ms,
                    TranscriptWordRow.text,
                )
                .join(
                    TranscriptSegmentRow,
                    TranscriptSegmentRow.id == TranscriptWordRow.segment_id,
                )
                .join(TranscriptRow, TranscriptRow.id == TranscriptSegmentRow.transcript_id)
                .where(TranscriptRow.pipeline_run_id == current_run_id)
                .order_by(
                    TranscriptWordRow.segment_id,
                    TranscriptWordRow.word_index,
                )
            ):
                words_by_segment[str(word_row.segment_id)].append(
                    TranscriptWord(
                        start_ms=int(word_row.source_start_ms),
                        end_ms=int(word_row.source_end_ms),
                        text=str(word_row.text),
                    )
                )
            segments = tuple(
                TranscriptSegment(
                    segment_id=str(row.id),
                    start_ms=int(row.source_start_ms),
                    end_ms=int(row.source_end_ms),
                    text=str(row.text),
                    words=(
                        tuple(words_by_segment[str(row.id)])
                        if words_by_segment[str(row.id)]
                        else None
                    ),
                )
                for row in segment_rows
            )
            summaries: list[ClipSummary] = []
            for row in rows:
                captions = tuple(
                    CaptionCue(
                        start_ms=int(cue.start_ms),
                        end_ms=int(cue.end_ms),
                        text=str(cue.text),
                    )
                    for cue in connection.execute(
                        select(CaptionCueRow.start_ms, CaptionCueRow.end_ms, CaptionCueRow.text)
                        .where(CaptionCueRow.edit_plan_revision_id == row["revision_id"])
                        .order_by(CaptionCueRow.cue_index)
                    )
                )
                plan = edit_plan_from_json_data(row["plan_json"])
                decision = connection.scalar(
                    select(ReviewDecisionRow.status)
                    .where(ReviewDecisionRow.edit_plan_revision_id == row["revision_id"])
                    .order_by(
                        ReviewDecisionRow.decided_at.desc(),
                        ReviewDecisionRow.id.desc(),
                    )
                    .limit(1)
                )
                render = connection.execute(
                    select(
                        RenderJobRow.status,
                        RenderJobRow.asset_id,
                        RenderJobRow.spec_json,
                    )
                    .where(
                        RenderJobRow.candidate_clip_id == row["id"],
                        RenderJobRow.edit_plan_revision_id == row["revision_id"],
                        RenderJobRow.kind == "proxy",
                    )
                    .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
                    .limit(1)
                ).one_or_none()
                if render is None:
                    render = connection.execute(
                        select(
                            RenderJobRow.status,
                            RenderJobRow.asset_id,
                            RenderJobRow.spec_json,
                        )
                        .where(
                            RenderJobRow.candidate_clip_id == row["id"],
                            RenderJobRow.kind == "proxy",
                        )
                        .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
                        .limit(1)
                    ).one_or_none()
                proxy_is_clean = bool(
                    render
                    and is_clean_review_proxy(
                        spec=render[2],
                        pipeline_config=row["config_json"],
                    )
                )
                proxy_status = RenderStatus(str(render[0])) if render else None
                if proxy_status == RenderStatus.SUCCEEDED and not proxy_is_clean:
                    proxy_status = RenderStatus.STALE
                summaries.append(
                    ClipSummary(
                        clip_id=str(row["id"]),
                        candidate_key=str(row["candidate_key"]),
                        edit_plan_revision=int(row["current_revision"]),
                        source_start_ms=int(row["source_start_ms"]),
                        source_end_ms=int(row["source_end_ms"]),
                        score=float(row["score"]),
                        title=str(row["title"]),
                        reason=str(row["reason"]),
                        risk_flags=tuple(str(value) for value in row["risk_flags_json"]),
                        captions=captions,
                        keywords=derive_keyword_occurrences(
                            captions,
                            source_start_ms=int(row["source_start_ms"]),
                            source_end_ms=int(row["source_end_ms"]),
                            title=str(row["title"]),
                            hook=plan.hook,
                            reason=str(row["reason"]),
                            segments=segments,
                        ),
                        review_status=(
                            ReviewStatus(str(decision))
                            if decision is not None
                            else ReviewStatus.PENDING_REVIEW
                        ),
                        proxy_status=proxy_status,
                        proxy_asset_id=(
                            str(render[1])
                            if render
                            and proxy_status == RenderStatus.SUCCEEDED
                            and proxy_is_clean
                            and render[1]
                            else None
                        ),
                        allowed_actions=(
                            ("edit", "approve", "reject")
                            if plan.layout.value == "center_crop"
                            else ("edit", "reject")
                        ),
                    )
                )
            return tuple(summaries)
