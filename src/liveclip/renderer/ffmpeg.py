from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from liveclip.domain.edit_plan import Effect, Layout
from liveclip.domain.time import ms_to_ffmpeg
from liveclip.media.process import ProcessCancelled, run_cancellable_process
from liveclip.media.secure_files import (
    SecureFileError,
    ensure_directory_no_follow,
    publish_regular_file_immutable_no_follow,
)
from liveclip.observability import redact_persistent_diagnostic, redact_text
from liveclip.renderer.quality import (
    MediaValidationCancelled,
    MediaValidationError,
    QualityReport,
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
    video_stream_index: int = 0
    audio_stream_index: int = 1
    source_pass_fds: tuple[int, ...] = ()
    overlays: tuple[TextOverlay, ...] = ()
    encoder: str = "auto"

    @property
    def duration_ms(self) -> int:
        return self.source_end_ms - self.source_start_ms


@dataclass(frozen=True, slots=True)
class RenderAttemptDiagnostic:
    encoder: str
    runtime_attempt: int
    outcome: Literal[
        "succeeded",
        "timeout",
        "launch_error",
        "process_failed",
        "validation_failed",
    ]
    elapsed_ms: int
    exit_code: int | None
    logical_argv: tuple[str, ...]
    stderr_tail: str


@dataclass(frozen=True, slots=True)
class RenderResult:
    output_path: Path
    sha256: str
    encoder: str
    attempts: int
    argv: tuple[str, ...]
    stderr_tail: str
    diagnostics: tuple[RenderAttemptDiagnostic, ...]


class FFmpegRenderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        diagnostics: tuple[RenderAttemptDiagnostic, ...] = (),
        quality_diagnostics: tuple[dict[str, object], ...] = (),
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics
        self.quality_diagnostics = quality_diagnostics
        self.retryable = retryable
        self.diagnostic_relative_path: str | None = None


class FFmpegRenderCancelled(FFmpegRenderError):
    pass


def build_ffmpeg_argv(
    request: RenderRequest,
    *,
    encoder: str,
    temporary_output: Path,
    ffmpeg_path: str = "ffmpeg",
    conservative_threads: bool = False,
) -> list[str]:
    _validate_request(request)
    if encoder not in {"h264_videotoolbox", "libx264"}:
        raise ValueError("unsupported deterministic video encoder")
    argv = [
        ffmpeg_path,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-filter_complex_threads",
        "1" if conservative_threads else "2",
        "-ss",
        ms_to_ffmpeg(request.source_start_ms),
        "-i",
        str(request.source_path),
    ]
    for overlay in request.overlays:
        # A PNG is a one-frame secondary input. The overlay filter holds that
        # frame explicitly, avoiding several unbounded image2 producers.
        argv.extend(["-i", str(overlay.path)])
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
        video_threads = "1" if conservative_threads else "4"
        argv.extend(["-preset", "veryfast", "-crf", "21", "-threads:v", video_threads])
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
    chains.append(
        f"[0:{request.video_stream_index}]setpts=PTS-STARTPTS,scale={width}:{height}:"
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
            "eof_action=repeat:repeatlast=1:"
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
    chains.append(f"[0:{request.audio_stream_index}]asetpts=PTS-STARTPTS,{audio_effects}[aout]")
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
    try:
        ensure_directory_no_follow(request.output_path.parent)
    except SecureFileError as exc:
        raise FFmpegRenderError("render output directory is not symlink-free") from exc
    if request.output_path.exists():
        raise FFmpegRenderError("refusing to overwrite an existing revision artifact")
    temporary = request.output_path.with_name(
        f".{request.output_path.stem}.tmp-{uuid.uuid4().hex}.mp4"
    )
    encoders = _encoder_order(request.encoder)
    diagnostic_records: list[RenderAttemptDiagnostic] = []
    attempt = 0
    try:
        for encoder in encoders:
            runtime_attempts = 2 if encoder == "libx264" else 1
            for runtime_attempt in range(1, runtime_attempts + 1):
                attempt += 1
                temporary.unlink(missing_ok=True)
                argv = build_ffmpeg_argv(
                    request,
                    encoder=encoder,
                    temporary_output=temporary,
                    ffmpeg_path=executable,
                    conservative_threads=encoder == "libx264" and runtime_attempt > 1,
                )
                logical_argv = _logical_argv(argv, request=request, temporary_output=temporary)
                attempt_started = time.monotonic()
                try:
                    result = run_ffmpeg(
                        argv,
                        timeout_seconds=_render_timeout_seconds(request),
                        cancel_requested=cancel_requested,
                        pass_fds=request.source_pass_fds,
                    )
                except ProcessCancelled as exc:
                    raise FFmpegRenderCancelled("FFmpeg rendering was cancelled") from exc
                except subprocess.TimeoutExpired as exc:
                    diagnostic_records.append(
                        RenderAttemptDiagnostic(
                            encoder=encoder,
                            runtime_attempt=runtime_attempt,
                            outcome="timeout",
                            elapsed_ms=_elapsed_ms(attempt_started),
                            exit_code=None,
                            logical_argv=logical_argv,
                            stderr_tail=_timeout_stderr(
                                exc,
                                request=request,
                                temporary_output=temporary,
                            ),
                        )
                    )
                    continue
                except OSError:
                    diagnostic_records.append(
                        RenderAttemptDiagnostic(
                            encoder=encoder,
                            runtime_attempt=runtime_attempt,
                            outcome="launch_error",
                            elapsed_ms=_elapsed_ms(attempt_started),
                            exit_code=None,
                            logical_argv=logical_argv,
                            stderr_tail="",
                        )
                    )
                    continue
                stderr_tail = _safe_stderr_tail(
                    result.stderr,
                    sensitive_values=_diagnostic_sensitive_values(request, temporary),
                )
                if (
                    result.returncode == 0
                    and temporary.is_file()
                    and temporary.stat().st_size > 1_024
                ):
                    try:
                        prepublish_quality = _validate_temporary_media(
                            temporary,
                            request,
                            cancel_requested=cancel_requested,
                        )
                    except MediaValidationCancelled as exc:
                        raise FFmpegRenderCancelled("render validation was cancelled") from exc
                    except (MediaValidationError, OSError, subprocess.TimeoutExpired) as exc:
                        diagnostic_records.append(
                            RenderAttemptDiagnostic(
                                encoder=encoder,
                                runtime_attempt=runtime_attempt,
                                outcome="validation_failed",
                                elapsed_ms=_elapsed_ms(attempt_started),
                                exit_code=result.returncode,
                                logical_argv=logical_argv,
                                stderr_tail=_safe_stderr_tail(
                                    f"{stderr_tail}\nvalidation: {exc.__class__.__name__}: {exc}",
                                    sensitive_values=_diagnostic_sensitive_values(
                                        request,
                                        temporary,
                                    ),
                                ),
                            )
                        )
                        break
                    diagnostic_records.append(
                        RenderAttemptDiagnostic(
                            encoder=encoder,
                            runtime_attempt=runtime_attempt,
                            outcome="succeeded",
                            elapsed_ms=_elapsed_ms(attempt_started),
                            exit_code=result.returncode,
                            logical_argv=logical_argv,
                            stderr_tail=stderr_tail,
                        )
                    )
                    try:
                        _publish_no_clobber(
                            temporary,
                            request.output_path,
                            expected_sha256=prepublish_quality.media_sha256,
                        )
                    except FFmpegRenderError as exc:
                        raise FFmpegRenderError(
                            str(exc),
                            diagnostics=tuple(diagnostic_records),
                            retryable=exc.retryable,
                        ) from exc
                    return RenderResult(
                        output_path=request.output_path,
                        sha256=prepublish_quality.media_sha256,
                        encoder=encoder,
                        attempts=attempt,
                        argv=tuple(argv),
                        stderr_tail=stderr_tail,
                        diagnostics=tuple(diagnostic_records),
                    )
                diagnostic_records.append(
                    RenderAttemptDiagnostic(
                        encoder=encoder,
                        runtime_attempt=runtime_attempt,
                        outcome="process_failed",
                        elapsed_ms=_elapsed_ms(attempt_started),
                        exit_code=result.returncode,
                        logical_argv=logical_argv,
                        stderr_tail=stderr_tail,
                    )
                )
                # A completed process with invalid output is deterministic for
                # this encoder. Only runtime launch/timeout failures are retried.
                break
        raise FFmpegRenderError(
            f"FFmpeg rendering failed after {attempt} bounded attempt(s)",
            diagnostics=tuple(diagnostic_records),
            retryable=any(
                item.outcome in {"timeout", "launch_error"} for item in diagnostic_records
            ),
        )
    finally:
        temporary.unlink(missing_ok=True)


def run_ffmpeg(
    argv: Sequence[str],
    *,
    timeout_seconds: float = 1_800,
    cancel_requested: Callable[[], bool] | None = None,
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[str]:
    return run_cancellable_process(
        argv,
        timeout_seconds=timeout_seconds,
        cancel_requested=cancel_requested,
        pass_fds=pass_fds,
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
    if request.layout is not Layout.CENTER_CROP:
        raise ValueError("blurred-background layouts are prohibited")
    if request.video_stream_index < 0 or request.audio_stream_index < 0:
        raise ValueError("render stream indexes must be nonnegative")
    if request.video_stream_index == request.audio_stream_index:
        raise ValueError("render video and audio streams must be distinct")
    if any(value < 0 for value in request.source_pass_fds):
        raise ValueError("render inherited file descriptors must be nonnegative")
    for overlay in request.overlays:
        if overlay.start_ms < 0 or overlay.end_ms <= overlay.start_ms:
            raise ValueError("invalid overlay interval")
        if overlay.end_ms > request.duration_ms:
            raise ValueError("overlay exceeds clip duration")


def _bounded_tail(value: str, *, maximum_lines: int = 20) -> str:
    return "\n".join(value.splitlines()[-maximum_lines:])[-4_000:]


def _safe_stderr_tail(
    value: str,
    *,
    sensitive_values: Sequence[str] = (),
) -> str:
    return redact_persistent_diagnostic(
        _bounded_tail(value),
        sensitive_values=sensitive_values,
        maximum_characters=4_000,
    )


def _timeout_stderr(
    exc: subprocess.TimeoutExpired,
    *,
    request: RenderRequest,
    temporary_output: Path,
) -> str:
    raw_value = exc.stderr
    if isinstance(raw_value, bytes):
        value = raw_value.decode("utf-8", errors="replace")
    elif isinstance(raw_value, str):
        value = raw_value
    else:
        return ""
    return _safe_stderr_tail(
        value,
        sensitive_values=_diagnostic_sensitive_values(request, temporary_output),
    )


def _diagnostic_sensitive_values(
    request: RenderRequest,
    temporary_output: Path,
) -> tuple[str, ...]:
    return (
        str(request.source_path),
        str(temporary_output),
        *(str(overlay.path) for overlay in request.overlays),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1_000))


def _logical_argv(
    argv: Sequence[str],
    *,
    request: RenderRequest,
    temporary_output: Path,
) -> tuple[str, ...]:
    replacements = {
        str(request.source_path): "<source-media>",
        str(temporary_output): "<temporary-output>",
        **{
            str(overlay.path): f"<overlay-{index}>"
            for index, overlay in enumerate(request.overlays, start=1)
        },
    }
    result: list[str] = []
    remaining_characters = 16_384
    for index, argument in enumerate(argv):
        if len(result) >= 256 or remaining_characters <= 0:
            result.append("<logical-argv-truncated>")
            break
        if index == 0:
            value = Path(argument).name or "ffmpeg"
        else:
            value = replacements.get(argument, argument)
        bounded = redact_text(value)[: min(2_048, remaining_characters)]
        result.append(bounded)
        remaining_characters -= len(bounded)
    return tuple(result)


def render_diagnostics_payload(
    diagnostics: Sequence[RenderAttemptDiagnostic],
) -> dict[str, object]:
    attempts: list[dict[str, object]] = []
    records_dropped = 0
    for item in diagnostics:
        record: dict[str, object] = {
            "encoder": item.encoder,
            "runtime_attempt": item.runtime_attempt,
            "outcome": item.outcome,
            "elapsed_ms": item.elapsed_ms,
            "exit_code": item.exit_code,
            "logical_argv": list(item.logical_argv),
            "stderr_tail": item.stderr_tail,
        }
        candidate = {
            "schema_version": "1",
            "attempt_count": len(diagnostics),
            "records_dropped": records_dropped,
            "attempts": [*attempts, record],
        }
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > 64 * 1024:
            records_dropped += 1
            continue
        attempts.append(record)
    return {
        "schema_version": "1",
        "attempt_count": len(diagnostics),
        "records_dropped": records_dropped,
        "attempts": attempts,
    }


def render_execution_diagnostics_payload(
    diagnostics: Sequence[RenderAttemptDiagnostic],
    quality_diagnostics: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    payload = {
        "schema_version": "1",
        "encode": render_diagnostics_payload(diagnostics),
        "quality": [],
        "quality_records_dropped": 0,
    }
    retained: list[dict[str, object]] = []
    dropped = 0
    for record in quality_diagnostics:
        candidate = {
            **payload,
            "quality": [*retained, record],
            "quality_records_dropped": dropped,
        }
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > 80 * 1024:
            dropped += 1
            continue
        retained.append(record)
    payload["quality"] = retained
    payload["quality_records_dropped"] = dropped
    return payload


def render_error_diagnostics_payload(error: FFmpegRenderError) -> dict[str, object]:
    return render_execution_diagnostics_payload(
        error.diagnostics,
        error.quality_diagnostics,
    )


def _validate_temporary_media(
    path: Path,
    request: RenderRequest,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> QualityReport:
    with tempfile.TemporaryDirectory(prefix=".liveclip-prepublish-", dir=path.parent) as temp_dir:
        return validate_rendered_media(
            media_path=path,
            expected_width=request.width,
            expected_height=request.height,
            expected_duration_ms=request.duration_ms,
            output_dir=Path(temp_dir),
            safe_bounds=tuple(overlay.safe_bounds for overlay in request.overlays),
            cancel_requested=cancel_requested,
        )


def _publish_no_clobber(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
) -> None:
    try:
        publish_regular_file_immutable_no_follow(
            source,
            destination,
            expected_sha256=expected_sha256,
        )
    except SecureFileError as exc:
        raise FFmpegRenderError(
            "render artifact failed its no-clobber race and safety check",
            retryable=False,
        ) from exc
