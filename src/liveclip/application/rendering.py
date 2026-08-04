from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.reviewing import RenderRequest
from liveclip.domain.review import EditPlanRevision
from liveclip.domain.state_transitions import RenderStatus


class RenderConflict(RuntimeError):
    """A render command conflicts with the current clip revision or review state."""


class RenderResourceNotFound(LookupError):
    """The requested render or current clip does not exist."""


class RenderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    preview_width: int = Field(gt=0)
    preview_height: int = Field(gt=0)
    final_width: int = Field(gt=0)
    final_height: int = Field(gt=0)
    encoder: str = Field(pattern=r"^(auto|h264_videotoolbox|libx264)$")
    max_retries: int = Field(ge=0, le=20)


class QueuedRender(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    render_id: str
    task_id: str
    clip_id: str
    edit_plan_revision: int = Field(ge=1)
    kind: str = Field(pattern=r"^(proxy|final)$")
    status: RenderStatus


@dataclass(frozen=True, slots=True)
class RenderWork:
    render_id: str
    task_id: str
    project_id: str
    run_id: str
    generation: int
    revision_epoch: int
    source_path: Path
    source_size_bytes: int
    source_mtime_ns: int
    source_device: int | None
    source_inode: int | None
    source_sha256: str
    video_stream_index: int
    audio_stream_index: int
    font_path: Path
    revision: EditPlanRevision
    kind: str
    width: int
    height: int
    encoder: str
    spec_fingerprint: str


@dataclass(frozen=True, slots=True)
class RenderPersistence:
    video_asset_id: str
    subtitle_asset_id: str
    quality_report_asset_id: str
    contact_sheet_asset_id: str
    diagnostic_relative_path: str | None = None


@dataclass(frozen=True, slots=True)
class RenderAssetPaths:
    video: str
    subtitle: str
    quality_report: str
    contact_sheet: str


def render_asset_paths(work: RenderWork) -> RenderAssetPaths:
    render_group = "proxies" if work.kind == "proxy" else "final"
    base_relative = (
        f"runs/g{work.generation:03d}/renders/{render_group}/"
        f"{work.revision.clip_id}/r{work.revision.revision:03d}/"
        f"s-{work.spec_fingerprint[:16]}/t-{work.task_id[:16]}"
    )
    video_name = "review.mp4" if work.kind == "proxy" else "final.mp4"
    return RenderAssetPaths(
        video=f"{base_relative}/{video_name}",
        subtitle=f"{base_relative}/subtitles.srt",
        quality_report=f"{base_relative}/quality/quality-report.json",
        contact_sheet=f"{base_relative}/quality/contact-sheet.png",
    )


class RenderRepository(Protocol):
    def enqueue_render(
        self,
        clip_id: str,
        request: RenderRequest,
        profile: RenderProfile,
        idempotency: IdempotencyContext | None = None,
    ) -> QueuedRender: ...

    def start_render(self, lease: LeaseIdentity) -> RenderWork: ...

    def get_render(self, render_id: str) -> QueuedRender: ...

    def complete_render(
        self,
        lease: LeaseIdentity,
        work: RenderWork,
        persistence: RenderPersistence,
    ) -> bool: ...


class RenderService:
    def __init__(self, repository: RenderRepository, profile: RenderProfile) -> None:
        self._repository = repository
        self._profile = profile

    def enqueue(
        self,
        clip_id: str,
        request: RenderRequest,
        *,
        idempotency: IdempotencyContext | None = None,
    ) -> QueuedRender:
        return self._repository.enqueue_render(
            clip_id, request, self._profile, idempotency=idempotency
        )

    def get(self, render_id: str) -> QueuedRender:
        return self._repository.get_render(render_id)
