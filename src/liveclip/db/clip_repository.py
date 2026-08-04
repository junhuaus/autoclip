from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Engine

from liveclip.application.clips import ClipSummary
from liveclip.application.pipeline import PipelineResourceNotFound
from liveclip.db.models import (
    CandidateClipRow,
    EditPlanRevisionRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
)
from liveclip.domain.state_transitions import RenderStatus, ReviewStatus


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
                )
                .join(
                    EditPlanRevisionRow,
                    (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
                    & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
                )
                .where(
                    CandidateClipRow.project_id == project_id,
                    CandidateClipRow.pipeline_run_id == current_run_id,
                    CandidateClipRow.selected_for_review.is_(True),
                )
                .order_by(CandidateClipRow.rank, CandidateClipRow.id)
            ).mappings()
            summaries: list[ClipSummary] = []
            for row in rows:
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
                    select(RenderJobRow.status, RenderJobRow.asset_id)
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
                        select(RenderJobRow.status, RenderJobRow.asset_id)
                        .where(
                            RenderJobRow.candidate_clip_id == row["id"],
                            RenderJobRow.kind == "proxy",
                        )
                        .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
                        .limit(1)
                    ).one_or_none()
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
                        review_status=(
                            ReviewStatus(str(decision))
                            if decision is not None
                            else ReviewStatus.PENDING_REVIEW
                        ),
                        proxy_status=(RenderStatus(str(render[0])) if render else None),
                        proxy_asset_id=(
                            str(render[1])
                            if render and render[0] == RenderStatus.SUCCEEDED.value and render[1]
                            else None
                        ),
                    )
                )
            return tuple(summaries)
