from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from liveclip.domain.review import EditPlanRevision
from liveclip.media.fingerprint import stream_sha256
from liveclip.renderer.ffmpeg import RenderRequest, RenderResult, render_clip
from liveclip.renderer.quality import QualityReport, validate_rendered_media
from liveclip.renderer.text import TextOverlay, render_caption_overlay, render_title_overlay


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    output_path: Path
    quality_report_path: Path
    contact_sheet_path: Path
    sha256: str
    encoder: str
    attempts: int
    quality: QualityReport


def render_edit_plan_revision(
    *,
    source_path: Path,
    revision: EditPlanRevision,
    output_path: Path,
    width: int,
    height: int,
    encoder: str,
    cancel_requested: Callable[[], bool] | None = None,
) -> RenderedArtifact:
    render_root = output_path.parent
    overlay_dir = render_root / f"{output_path.stem}-overlays"
    quality_dir = render_root / f"{output_path.stem}-quality"
    overlay_dir.mkdir(parents=True, exist_ok=False)
    overlays = render_revision_overlays(
        revision=revision,
        output_dir=overlay_dir,
        width=width,
        height=height,
    )
    result: RenderResult = render_clip(
        RenderRequest(
            source_path=source_path,
            output_path=output_path,
            source_start_ms=revision.plan.source_start_ms,
            source_end_ms=revision.plan.source_end_ms,
            width=width,
            height=height,
            layout=revision.plan.layout,
            effect=revision.plan.effect,
            overlays=overlays,
            encoder=encoder,
        ),
        cancel_requested=cancel_requested,
    )
    quality = validate_rendered_media(
        media_path=output_path,
        expected_width=width,
        expected_height=height,
        expected_duration_ms=revision.plan.duration_ms,
        output_dir=quality_dir,
        safe_bounds=tuple(overlay.safe_bounds for overlay in overlays),
        cancel_requested=cancel_requested,
    )
    quality_report_path = quality_dir / "quality-report.json"
    return RenderedArtifact(
        output_path=output_path,
        quality_report_path=quality_report_path,
        contact_sheet_path=Path(quality.contact_sheet),
        sha256=stream_sha256(output_path),
        encoder=result.encoder,
        attempts=result.attempts,
        quality=quality,
    )


def render_revision_overlays(
    *,
    revision: EditPlanRevision,
    output_dir: Path,
    width: int,
    height: int,
) -> tuple[TextOverlay, ...]:
    overlays: list[TextOverlay] = [
        render_title_overlay(
            output_path=output_dir / "title.png",
            width=width,
            height=height,
            text=revision.plan.title,
            start_ms=0,
            end_ms=revision.plan.duration_ms,
        )
    ]
    for index, cue in enumerate(revision.captions, start=1):
        overlays.append(
            render_caption_overlay(
                output_path=output_dir / f"caption-{index:03d}.png",
                width=width,
                height=height,
                text=cue.text,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
            )
        )
    return tuple(overlays)
