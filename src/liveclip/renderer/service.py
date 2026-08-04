from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from liveclip.domain.edit_plan import (
    CaptionCue,
    expand_caption_cues_for_display,
    validate_caption_cues,
)
from liveclip.domain.review import EditPlanRevision
from liveclip.media.secure_files import (
    SecureFileError,
    ensure_directory_no_follow,
    hash_regular_file_no_follow,
)
from liveclip.renderer.ffmpeg import (
    FFmpegRenderError,
    RenderAttemptDiagnostic,
    RenderRequest,
    RenderResult,
    render_clip,
    render_execution_diagnostics_payload,
)
from liveclip.renderer.quality import (
    MediaValidationCancelled,
    MediaValidationError,
    MediaValidationTransientError,
    QualityCommandDiagnostic,
    QualityReport,
    validate_rendered_media,
)
from liveclip.renderer.text import (
    TextOverlay,
    render_caption_overlay,
    render_title_overlay,
)


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    output_path: Path
    quality_report_path: Path
    contact_sheet_path: Path
    sha256: str
    contact_sheet_sha256: str
    encoder: str
    attempts: int
    diagnostics: tuple[RenderAttemptDiagnostic, ...]
    diagnostic_payload: dict[str, object]
    quality: QualityReport


def render_edit_plan_revision(
    *,
    source_path: Path,
    revision: EditPlanRevision,
    output_path: Path,
    width: int,
    height: int,
    encoder: str,
    video_stream_index: int = 0,
    audio_stream_index: int = 1,
    source_pass_fds: tuple[int, ...] = (),
    font_path: Path | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> RenderedArtifact:
    validate_caption_cues(revision.captions, clip_duration_ms=revision.plan.duration_ms)
    display_cues = display_caption_cues(revision.captions)
    try:
        render_root = ensure_directory_no_follow(output_path.parent)
    except SecureFileError as exc:
        raise ValueError("render output directory is not symlink-free") from exc
    overlay_dir = render_root / f"{output_path.stem}-overlays"
    quality_dir = render_root / f"{output_path.stem}-quality"
    if overlay_dir.exists() or overlay_dir.is_symlink():
        raise ValueError("render overlay attempt directory already exists")
    try:
        ensure_directory_no_follow(overlay_dir)
    except SecureFileError as exc:
        raise ValueError("render overlay directory is not symlink-free") from exc
    overlays = render_revision_overlays(
        revision=revision,
        output_dir=overlay_dir,
        width=width,
        height=height,
        font_path=font_path,
        display_cues=display_cues,
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
            video_stream_index=video_stream_index,
            audio_stream_index=audio_stream_index,
            source_pass_fds=source_pass_fds,
            overlays=overlays,
            encoder=encoder,
        ),
        cancel_requested=cancel_requested,
    )
    quality_diagnostics: list[QualityCommandDiagnostic] = []
    try:
        quality = validate_rendered_media(
            media_path=output_path,
            expected_width=width,
            expected_height=height,
            expected_duration_ms=revision.plan.duration_ms,
            output_dir=quality_dir,
            safe_bounds=tuple(overlay.safe_bounds for overlay in overlays),
            cancel_requested=cancel_requested,
            diagnostic_records=quality_diagnostics,
        )
    except MediaValidationCancelled:
        raise
    except MediaValidationError as exc:
        raise FFmpegRenderError(
            "rendered media failed post-encode quality validation",
            diagnostics=result.diagnostics,
            quality_diagnostics=tuple(item.as_dict() for item in quality_diagnostics),
            retryable=isinstance(exc, MediaValidationTransientError),
        ) from exc
    if quality.media_sha256 != result.sha256:
        raise FFmpegRenderError(
            "rendered media changed between encode and quality validation",
            diagnostics=result.diagnostics,
            quality_diagnostics=tuple(item.as_dict() for item in quality_diagnostics),
            retryable=False,
        )
    quality_report_path = quality_dir / "quality-report.json"
    try:
        contact_sheet_sha256, _contact_sheet_size = hash_regular_file_no_follow(
            Path(quality.contact_sheet)
        )
    except SecureFileError as exc:
        raise FFmpegRenderError(
            "render contact sheet changed after quality validation",
            diagnostics=result.diagnostics,
            quality_diagnostics=tuple(item.as_dict() for item in quality_diagnostics),
            retryable=False,
        ) from exc
    return RenderedArtifact(
        output_path=output_path,
        quality_report_path=quality_report_path,
        contact_sheet_path=Path(quality.contact_sheet),
        sha256=quality.media_sha256,
        contact_sheet_sha256=contact_sheet_sha256,
        encoder=result.encoder,
        attempts=result.attempts,
        diagnostics=result.diagnostics,
        diagnostic_payload=render_execution_diagnostics_payload(
            result.diagnostics,
            tuple(item.as_dict() for item in quality_diagnostics),
        ),
        quality=quality,
    )


def render_revision_overlays(
    *,
    revision: EditPlanRevision,
    output_dir: Path,
    width: int,
    height: int,
    font_path: Path | None = None,
    display_cues: tuple[CaptionCue, ...] | None = None,
) -> tuple[TextOverlay, ...]:
    validate_caption_cues(revision.captions, clip_duration_ms=revision.plan.duration_ms)
    expected_cues = display_caption_cues(revision.captions)
    if display_cues is not None and display_cues != expected_cues:
        raise ValueError("pre-expanded caption cues do not match the domain display contract")
    effective_cues = expected_cues
    overlays: list[TextOverlay] = [
        render_title_overlay(
            output_path=output_dir / "title.png",
            width=width,
            height=height,
            text=revision.plan.title,
            start_ms=0,
            end_ms=revision.plan.duration_ms,
            font_path=font_path,
        )
    ]
    for index, cue in enumerate(effective_cues, start=1):
        overlays.append(
            render_caption_overlay(
                output_path=output_dir / f"caption-{index:03d}.png",
                width=width,
                height=height,
                text=cue.text,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                font_path=font_path,
            )
        )
    return tuple(overlays)


def display_caption_cues(cues: tuple[CaptionCue, ...]) -> tuple[CaptionCue, ...]:
    """Expose the domain display expansion at the renderer boundary."""

    return expand_caption_cues_for_display(cues)
