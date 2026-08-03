from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from liveclip.domain.edit_plan import Effect, Layout
from liveclip.domain.time import ms_to_ffmpeg
from liveclip.media.process import ProcessCancelled, run_cancellable_process
from liveclip.renderer.quality import (
    MediaValidationCancelled,
    MediaValidationError,
    validate_rendered_media,
)
from liveclip.renderer.text import TextOverlay


@dataclass(frozen=True, slots=True)
class RenderRequest:
    source_path: Path
    output_path: Path
    source_start_ms: int
    source_end_ms: int
    width: int
    height: int
    layout: Layout
    effect: Effect
    overlays: tuple[TextOverlay, ...] = ()
    encoder: str = "auto"

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


@dataclass(frozen=True, slots=True)
class RenderResult:
    output_path: Path
    encoder: str
    attempts: int
    argv: tuple[str, ...]
    stderr_tail: str


class FFmpegRenderError(RuntimeError):
    pass


class FFmpegRenderCancelled(FFmpegRenderError):
    pass


def build_ffmpeg_argv(
    request: RenderRequest,
    *,
    encoder: str,
    temporary_output: Path,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    _validate_request(request)
    if encoder not in {"h264_videotoolbox", "libx264"}:
        raise ValueError("unsupported deterministic video encoder")
    argv = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-ss",
        ms_to_ffmpeg(request.source_start_ms),
        "-i",
        str(request.source_path),
    ]
    for overlay in request.overlays:
        argv.extend(["-loop", "1", "-i", str(overlay.path)])
    argv.extend(
        [
            "-t",
            ms_to_ffmpeg(request.duration_ms),
            "-filter_complex",
            build_filtergraph(request),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            encoder,
        ]
    )
    if encoder == "h264_videotoolbox":
        bitrate = "2500k" if request.width <= 540 else "6500k"
        argv.extend(["-allow_sw", "0", "-b:v", bitrate])
    else:
        argv.extend(["-preset", "veryfast", "-crf", "21"])
    argv.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(temporary_output),
        ]
    )
    return argv


def build_filtergraph(request: RenderRequest) -> str:
    _validate_request(request)
    width = request.width
    height = request.height
    chains: list[str] = []
    if request.layout == Layout.VERTICAL_BLUR_BACKGROUND:
        chains.extend(
            [
                "[0:v]setpts=PTS-STARTPTS,split=2[bgsrc][fgsrc]",
                f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},boxblur=20:2[bg]",
                f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease[fg]",
                "[bg][fg]overlay=(W-w)/2:(H-h)/2:shortest=1[base]",
            ]
        )
    else:
        chains.append(
            f"[0:v]setpts=PTS-STARTPTS,scale={width}:{height}:"
            f"force_original_aspect_ratio=increase,crop={width}:{height}[base]"
        )
    previous = "base"
    for index, overlay in enumerate(request.overlays, start=1):
        relative_start = max(0, overlay.start_ms)
        relative_end = min(request.duration_ms, overlay.end_ms)
        chains.append(f"[{index}:v]format=rgba,setpts=PTS-STARTPTS[overlay{index}]")
        output_label = f"composite{index}"
        chains.append(
            f"[{previous}][overlay{index}]overlay=0:0:"
            f"enable='between(t,{ms_to_ffmpeg(relative_start)},{ms_to_ffmpeg(relative_end)})'"
            f"[{output_label}]"
        )
        previous = output_label
    if request.effect == Effect.FADE_IN_OUT and request.duration_ms >= 1_000:
        fade_ms = min(300, request.duration_ms // 4)
        fade_out_start = request.duration_ms - fade_ms
        chains.append(
            f"[{previous}]fade=t=in:st=0:d={ms_to_ffmpeg(fade_ms)},"
            f"fade=t=out:st={ms_to_ffmpeg(fade_out_start)}:d={ms_to_ffmpeg(fade_ms)},"
            "format=yuv420p[vout]"
        )
        audio_effects = (
            "loudnorm=I=-16:LRA=11:TP=-1.5,"
            f"afade=t=in:st=0:d={ms_to_ffmpeg(fade_ms)},"
            f"afade=t=out:st={ms_to_ffmpeg(fade_out_start)}:d={ms_to_ffmpeg(fade_ms)}"
        )
    else:
        chains.append(f"[{previous}]format=yuv420p[vout]")
        audio_effects = "loudnorm=I=-16:LRA=11:TP=-1.5"
    chains.append(f"[0:a]asetpts=PTS-STARTPTS,{audio_effects}[aout]")
    return ";".join(chains)


def render_clip(
    request: RenderRequest,
    *,
    ffmpeg_path: str | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> RenderResult:
    _validate_request(request)
    executable = ffmpeg_path or shutil.which("ffmpeg")
    if executable is None:
        raise FFmpegRenderError("ffmpeg is not available")
    request.output_path.parent.mkdir(parents=True, exist_ok=True)
    if request.output_path.exists():
        raise FFmpegRenderError("refusing to overwrite an existing revision artifact")
    temporary = request.output_path.with_name(
        f".{request.output_path.stem}.tmp-{uuid.uuid4().hex}.mp4"
    )
    encoders = _encoder_order(request.encoder)
    diagnostics: list[str] = []
    try:
        for attempt, encoder in enumerate(encoders, start=1):
            temporary.unlink(missing_ok=True)
            argv = build_ffmpeg_argv(
                request, encoder=encoder, temporary_output=temporary, ffmpeg_path=executable
            )
            try:
                result = run_ffmpeg(
                    argv,
                    timeout_seconds=_render_timeout_seconds(request),
                    cancel_requested=cancel_requested,
                )
            except ProcessCancelled as exc:
                raise FFmpegRenderCancelled("FFmpeg rendering was cancelled") from exc
            except (OSError, subprocess.TimeoutExpired) as exc:
                diagnostics.append(f"{encoder} runtime: {exc.__class__.__name__}")
                continue
            stderr_tail = _bounded_tail(result.stderr)
            diagnostics.append(f"{encoder}: {stderr_tail}")
            if result.returncode == 0 and temporary.is_file() and temporary.stat().st_size > 1_024:
                try:
                    _validate_temporary_media(
                        temporary,
                        request,
                        cancel_requested=cancel_requested,
                    )
                except MediaValidationCancelled as exc:
                    raise FFmpegRenderCancelled("render validation was cancelled") from exc
                except (MediaValidationError, OSError, subprocess.TimeoutExpired) as exc:
                    diagnostics.append(f"{encoder} validation: {exc.__class__.__name__}: {exc}")
                    continue
                _publish_no_clobber(temporary, request.output_path)
                return RenderResult(
                    output_path=request.output_path,
                    encoder=encoder,
                    attempts=attempt,
                    argv=tuple(argv),
                    stderr_tail=stderr_tail,
                )
        raise FFmpegRenderError("FFmpeg rendering failed: " + " | ".join(diagnostics))
    finally:
        temporary.unlink(missing_ok=True)


def run_ffmpeg(
    argv: Sequence[str],
    *,
    timeout_seconds: float = 1_800,
    cancel_requested: Callable[[], bool] | None = None,
) -> subprocess.CompletedProcess[str]:
    return run_cancellable_process(
        argv,
        timeout_seconds=timeout_seconds,
        cancel_requested=cancel_requested,
    )


def _render_timeout_seconds(request: RenderRequest) -> float:
    """Bound a hung encoder without penalizing normal high-resolution final renders."""

    duration_seconds = request.duration_ms / 1_000
    pixel_scale = max(1.0, (request.width * request.height) / (540 * 960))
    return min(1_800.0, max(120.0, duration_seconds * 8 * pixel_scale))


def _encoder_order(configured: str) -> tuple[str, ...]:
    if configured == "auto":
        return ("h264_videotoolbox", "libx264")
    if configured in {"h264_videotoolbox", "libx264"}:
        return (configured,) if configured == "libx264" else (configured, "libx264")
    raise ValueError("encoder must be auto, h264_videotoolbox, or libx264")


def _validate_request(request: RenderRequest) -> None:
    if request.source_start_ms < 0 or request.source_end_ms <= request.source_start_ms:
        raise ValueError("invalid source interval")
    if request.width <= 0 or request.height <= 0 or request.width % 2 or request.height % 2:
        raise ValueError("render dimensions must be positive even integers")
    if request.width >= request.height:
        raise ValueError("LiveClip render output must be portrait")
    for overlay in request.overlays:
        if overlay.start_ms < 0 or overlay.end_ms <= overlay.start_ms:
            raise ValueError("invalid overlay interval")
        if overlay.end_ms > request.duration_ms:
            raise ValueError("overlay exceeds clip duration")


def _bounded_tail(value: str, *, maximum_lines: int = 20) -> str:
    return "\n".join(value.splitlines()[-maximum_lines:])[-4_000:]


def _validate_temporary_media(
    path: Path,
    request: RenderRequest,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix=".liveclip-prepublish-", dir=path.parent) as temp_dir:
        validate_rendered_media(
            media_path=path,
            expected_width=request.width,
            expected_height=request.height,
            expected_duration_ms=request.duration_ms,
            output_dir=Path(temp_dir),
            safe_bounds=tuple(overlay.safe_bounds for overlay in request.overlays),
            cancel_requested=cancel_requested,
        )


def _publish_no_clobber(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise FFmpegRenderError("render artifact publication lost a no-clobber race") from exc
    except OSError as exc:
        raise FFmpegRenderError("render artifact could not be published atomically") from exc
    with suppress(OSError):
        # The destination is already a complete hard link. The outer cleanup gets
        # another chance to remove the private temporary name.
        source.unlink()
