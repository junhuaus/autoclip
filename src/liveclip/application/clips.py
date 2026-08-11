from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from liveclip.domain.edit_plan import CaptionCue
from liveclip.domain.keywords import KeywordOccurrence
from liveclip.domain.state_transitions import RenderStatus, ReviewStatus


class ClipSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str
    candidate_key: str
    edit_plan_revision: int = Field(ge=1)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0, le=100)
    title: str
    reason: str
    risk_flags: tuple[str, ...]
    captions: tuple[CaptionCue, ...]
    keywords: tuple[KeywordOccurrence, ...]
    review_status: ReviewStatus
    proxy_status: RenderStatus | None
    proxy_asset_id: str | None
    allowed_actions: tuple[str, ...]


class ClipQueryRepository(Protocol):
    def list_project_clips(self, project_id: str) -> tuple[ClipSummary, ...]: ...


class ClipQueryService:
    def __init__(self, repository: ClipQueryRepository) -> None:
        self._repository = repository

    def list_project_clips(self, project_id: str) -> tuple[ClipSummary, ...]:
        return self._repository.list_project_clips(project_id)
