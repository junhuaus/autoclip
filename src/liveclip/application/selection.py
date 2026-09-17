from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from liveclip.application.clips import ClipQueryService, ClipSummary
from liveclip.application.reviewing import (
    BatchReviewCommand,
    BatchReviewItem,
    ReviewService,
)
from liveclip.domain.state_transitions import ReviewStatus


class SelectionConflict(RuntimeError):
    """The requested clip selection does not match the current candidate set."""


class SelectionMode(StrEnum):
    DEFAULT = "default"
    MANUAL = "manual"


class SelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    mode: SelectionMode
    candidate_count: int = Field(ge=0)
    selected_clip_ids: tuple[str, ...]
    excluded_clip_ids: tuple[str, ...]
    unchanged_clip_ids: tuple[str, ...]


class SelectionService:
    """Apply one atomic user selection over the current candidate revisions.

    The database retains its historical approved/rejected vocabulary as a
    compatibility detail. Product-facing callers use selected/excluded.
    """

    def __init__(
        self,
        clip_query_service: ClipQueryService,
        review_service: ReviewService,
    ) -> None:
        self._clips = clip_query_service
        self._reviews = review_service

    def select(
        self,
        project_id: str,
        *,
        mode: SelectionMode,
        selected_clip_ids: Sequence[str] = (),
    ) -> SelectionResult:
        clips = self._clips.list_project_clips(project_id)
        if not clips:
            raise SelectionConflict("the project has no clips available for selection")
        ordered_ids = tuple(clip.clip_id for clip in clips)
        known_ids = set(ordered_ids)
        selected = tuple(dict.fromkeys(selected_clip_ids))
        unknown = tuple(value for value in selected if value not in known_ids)
        if unknown:
            raise SelectionConflict("manual selection contains an unknown clip ID")

        if mode == SelectionMode.DEFAULT:
            if selected:
                raise SelectionConflict("default selection does not accept explicit clip IDs")
            decisions = tuple(
                BatchReviewItem(
                    clip_id=clip.clip_id,
                    expected_revision=clip.edit_plan_revision,
                    status=ReviewStatus.APPROVED,
                )
                for clip in clips
                if clip.review_status == ReviewStatus.PENDING_REVIEW
            )
        else:
            selected_set = set(selected)
            decisions = tuple(
                BatchReviewItem(
                    clip_id=clip.clip_id,
                    expected_revision=clip.edit_plan_revision,
                    status=(
                        ReviewStatus.APPROVED
                        if clip.clip_id in selected_set
                        else ReviewStatus.REJECTED
                    ),
                    reason=(None if clip.clip_id in selected_set else "Not selected by the user"),
                )
                for clip in clips
            )

        if decisions:
            self._reviews.review_clips_batch(
                project_id,
                BatchReviewCommand(items=decisions),
            )
        current = self._clips.list_project_clips(project_id)
        return _selection_result(project_id, mode=mode, clips=current)


def _selection_result(
    project_id: str,
    *,
    mode: SelectionMode,
    clips: Sequence[ClipSummary],
) -> SelectionResult:
    selected = tuple(clip.clip_id for clip in clips if clip.review_status == ReviewStatus.APPROVED)
    excluded = tuple(clip.clip_id for clip in clips if clip.review_status == ReviewStatus.REJECTED)
    unchanged = tuple(
        clip.clip_id for clip in clips if clip.review_status == ReviewStatus.PENDING_REVIEW
    )
    return SelectionResult(
        project_id=project_id,
        mode=mode,
        candidate_count=len(clips),
        selected_clip_ids=selected,
        excluded_clip_ids=excluded,
        unchanged_clip_ids=unchanged,
    )
