from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps, ImageStat

from liveclip.domain.time import ms_to_ffmpeg
from liveclip.media.process import ProcessCancelled, run_cancellable_process
from liveclip.media.secure_files import (
    PinnedRegularFile,
    SecureFileError,
    ensure_directory_no_follow,
    open_pinned_regular_file,
    publish_regular_file_immutable_no_follow,
    read_regular_file_no_follow,
    read_regular_text_no_follow,
    write_bytes_immutable_no_follow,
    write_text_atomic_no_follow,
    write_text_immutable_no_follow,
)
from liveclip.observability import redact_persistent_diagnostic, redact_text


class MediaValidationError(RuntimeError):
    pass


class MediaValidationTransientError(MediaValidationError):
    pass


class MediaValidationCancelled(MediaValidationError):
    pass


@dataclass(frozen=True, slots=True)
class QualityCommandDiagnostic:
    operation: str
    outcome: str
    elapsed_ms: int
    exit_code: int | None
    logical_argv: tuple[str, ...]
    stderr_tail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "outcome": self.outcome,
            "elapsed_ms": self.elapsed_ms,
            "exit_code": self.exit_code,
            "logical_argv": list(self.logical_argv),
            "stderr_tail": self.stderr_tail,
        }


@dataclass(frozen=True, slots=True)
class FrameMetric:
    filename: str
    timestamp_ms: int
    mean_luma: float
    luma_variance: float
    edge_blank_sides: tuple[str, ...]
    edge_to_center_variance_ratio: float


@dataclass(frozen=True, slots=True)
class QualityReport:
    schema_version: str
    media_path: str
    media_sha256: str
    expected_width: int
    expected_height: int
    actual_width: int
    actual_height: int
    expected_duration_ms: int
    actual_duration_ms: int
    file_size: int
    container_format: str
    video_codec: str
    audio_codec: str
    full_decode: str
    safe_area_check: str
    black_frame_check: str
    edge_and_crop_check: str
    frame_metrics: tuple[FrameMetric, ...]
    contact_sheet: str
    automatic_status: str
    visual_inspection_status: str
    visual_inspection_notes: str
    visual_inspection_at: str | None

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["frame_metrics"] = [asdict(metric) for metric in self.frame_metrics]
        return payload


def validate_rendered_media(
    *,
    media_path: Path,
    expected_width: int,
    expected_height: int,
    expected_duration_ms: int,
    output_dir: Path,
    safe_bounds: tuple[tuple[int, int, int, int], ...] = (),
    duration_tolerance_ms: int = 600,
    cancel_requested: Callable[[], bool] | None = None,
    diagnostic_records: list[QualityCommandDiagnostic] | None = None,
) -> QualityReport:
    try:
        output_dir = ensure_directory_no_follow(output_dir)
    except SecureFileError as exc:
        raise MediaValidationError("quality output directory is not symlink-free") from exc
    try:
        with open_pinned_regular_file(media_path) as pinned:
            return _validate_pinned_rendered_media(
                pinned=pinned,
                logical_media_path=media_path,
                expected_width=expected_width,
                expected_height=expected_height,
                expected_duration_ms=expected_duration_ms,
                output_dir=output_dir,
                safe_bounds=safe_bounds,
                duration_tolerance_ms=duration_tolerance_ms,
                cancel_requested=cancel_requested,
                diagnostic_records=diagnostic_records,
            )
    except SecureFileError as exc:
        raise MediaValidationError("rendered media changed during quality validation") from exc


def _validate_pinned_rendered_media(
    *,
    pinned: PinnedRegularFile,
    logical_media_path: Path,
    expected_width: int,
    expected_height: int,
    expected_duration_ms: int,
    output_dir: Path,
    safe_bounds: tuple[tuple[int, int, int, int], ...],
    duration_tolerance_ms: int,
    cancel_requested: Callable[[], bool] | None,
    diagnostic_records: list[QualityCommandDiagnostic] | None,
) -> QualityReport:
    if pinned.metadata.st_size < 10_000:
        raise MediaValidationError("rendered media is missing or below the size floor")
    process_path = pinned.process_path
    probe = probe_media(
        process_path,
        pass_fds=pinned.pass_fds,
        logical_media_path=logical_media_path,
        cancel_requested=cancel_requested,
        diagnostic_records=diagnostic_records,
    )
    streams = probe.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video_stream is None or audio_stream is None:
        raise MediaValidationError("rendered media must contain both video and audio streams")
    actual_width = int(video_stream.get("width", 0))
    actual_height = int(video_stream.get("height", 0))
    if (actual_width, actual_height) != (expected_width, expected_height):
        raise MediaValidationError("rendered dimensions do not match the requested portrait output")
    format_payload = probe.get("format", {})
    container_format = str(format_payload.get("format_name", ""))
    container_names = {name.strip() for name in container_format.split(",") if name.strip()}
    if logical_media_path.suffix.lower() != ".mp4" or "mp4" not in container_names:
        raise MediaValidationError("rendered media must be an MP4 container")
    video_codec = str(video_stream.get("codec_name", "unknown"))
    audio_codec = str(audio_stream.get("codec_name", "unknown"))
    if video_codec != "h264" or audio_codec != "aac":
        raise MediaValidationError("rendered media must use H.264 video and AAC audio")
    try:
        actual_duration_ms = round(float(format_payload["duration"]) * 1_000)
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaValidationError("ffprobe did not return a valid duration") from exc
    if abs(actual_duration_ms - expected_duration_ms) > duration_tolerance_ms:
        raise MediaValidationError("rendered duration is outside tolerance")
    full_decode(
        process_path,
        pass_fds=pinned.pass_fds,
        logical_media_path=logical_media_path,
        cancel_requested=cancel_requested,
        diagnostic_records=diagnostic_records,
    )
    frames = extract_representative_frames(
        media_path=process_path,
        pass_fds=pinned.pass_fds,
        logical_media_path=logical_media_path,
        duration_ms=actual_duration_ms,
        output_dir=output_dir / "frames",
        cancel_requested=cancel_requested,
        diagnostic_records=diagnostic_records,
    )
    metrics = tuple(_frame_metric(path, timestamp_ms) for path, timestamp_ms in frames)
    if any(metric.mean_luma < 3 or metric.luma_variance < 1 for metric in metrics):
        raise MediaValidationError("representative frame appears black or blank")
    edge_status = _validate_edge_and_crop_heuristic(metrics)
    safe_status = _validate_safe_bounds(safe_bounds, width=expected_width, height=expected_height)
    contact_sheet = output_dir / "contact-sheet.png"
    create_contact_sheet(frames=frames, output_path=contact_sheet)
    media_sha256 = pinned.sha256(cancel_requested=cancel_requested)
    pinned.validate_binding()
    report = QualityReport(
        schema_version="1",
        media_path=str(logical_media_path.resolve()),
        media_sha256=media_sha256,
        expected_width=expected_width,
        expected_height=expected_height,
        actual_width=actual_width,
        actual_height=actual_height,
        expected_duration_ms=expected_duration_ms,
        actual_duration_ms=actual_duration_ms,
        file_size=pinned.metadata.st_size,
        container_format=container_format,
        video_codec=video_codec,
        audio_codec=audio_codec,
        full_decode="passed",
        safe_area_check=safe_status,
        black_frame_check="passed",
        edge_and_crop_check=edge_status,
        frame_metrics=metrics,
        contact_sheet=str(contact_sheet.resolve()),
        automatic_status="passed",
        visual_inspection_status="pending",
        visual_inspection_notes=(
            "Automatic checks passed; visual inspection has not yet been recorded."
        ),
        visual_inspection_at=None,
    )
    write_quality_report(report, output_dir / "quality-report.json")
    return report


def probe_media(
    media_path: Path,
    *,
    ffprobe_path: str | None = None,
    pass_fds: tuple[int, ...] = (),
    logical_media_path: Path | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    diagnostic_records: list[QualityCommandDiagnostic] | None = None,
) -> dict[str, Any]:
    executable = ffprobe_path or shutil.which("ffprobe")
    if executable is None:
        raise MediaValidationError("ffprobe is not available")
    argv = [
        executable,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(media_path),
    ]
    sensitive_paths = tuple(dict.fromkeys((media_path, logical_media_path or media_path)))
    started = time.monotonic()
    try:
        result = run_cancellable_process(
            argv,
            timeout_seconds=60,
            cancel_requested=cancel_requested,
            pass_fds=pass_fds,
        )
    except ProcessCancelled as exc:
        raise MediaValidationCancelled("ffprobe inspection was cancelled") from exc
    except subprocess.TimeoutExpired as exc:
        _record_quality_exception(
            diagnostic_records,
            operation="ffprobe",
            outcome="timeout",
            argv=argv,
            started=started,
            sensitive_paths=sensitive_paths,
            stderr=exc.stderr,
        )
        raise MediaValidationTransientError("ffprobe could not inspect rendered media") from exc
    except OSError as exc:
        _record_quality_exception(
            diagnostic_records,
            operation="ffprobe",
            outcome="launch_error",
            argv=argv,
            started=started,
            sensitive_paths=sensitive_paths,
        )
        raise MediaValidationTransientError("ffprobe could not inspect rendered media") from exc
    _record_quality_result(
        diagnostic_records,
        operation="ffprobe",
        result=result,
        started=started,
        sensitive_paths=sensitive_paths,
        succeeded=result.returncode == 0,
    )
    if result.returncode != 0:
        raise MediaValidationError("ffprobe failed to inspect rendered media")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaValidationError("ffprobe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise MediaValidationError("ffprobe returned an unexpected response")
    return payload


def full_decode(
    media_path: Path,
    *,
    ffmpeg_path: str | None = None,
    pass_fds: tuple[int, ...] = (),
    logical_media_path: Path | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    diagnostic_records: list[QualityCommandDiagnostic] | None = None,
) -> None:
    executable = ffmpeg_path or shutil.which("ffmpeg")
    if executable is None:
        raise MediaValidationError("ffmpeg is not available")
    argv = [executable, "-v", "error", "-i", str(media_path), "-f", "null", "-"]
    sensitive_paths = tuple(dict.fromkeys((media_path, logical_media_path or media_path)))
    started = time.monotonic()
    try:
        result = run_cancellable_process(
            argv,
            timeout_seconds=1_800,
            cancel_requested=cancel_requested,
            pass_fds=pass_fds,
        )
    except ProcessCancelled as exc:
        raise MediaValidationCancelled("full media decode was cancelled") from exc
    except subprocess.TimeoutExpired as exc:
        _record_quality_exception(
            diagnostic_records,
            operation="full_decode",
            outcome="timeout",
            argv=argv,
            started=started,
            sensitive_paths=sensitive_paths,
            stderr=exc.stderr,
        )
        raise MediaValidationTransientError("full media decode could not be executed") from exc
    except OSError as exc:
        _record_quality_exception(
            diagnostic_records,
            operation="full_decode",
            outcome="launch_error",
            argv=argv,
            started=started,
            sensitive_paths=sensitive_paths,
        )
        raise MediaValidationTransientError("full media decode could not be executed") from exc
    succeeded = result.returncode == 0 and not result.stderr.strip()
    _record_quality_result(
        diagnostic_records,
        operation="full_decode",
        result=result,
        started=started,
        sensitive_paths=sensitive_paths,
        succeeded=succeeded,
    )
    if not succeeded:
        raise MediaValidationError("full media decode failed")


def extract_representative_frames(
    *,
    media_path: Path,
    duration_ms: int,
    output_dir: Path,
    ffmpeg_path: str | None = None,
    pass_fds: tuple[int, ...] = (),
    logical_media_path: Path | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    diagnostic_records: list[QualityCommandDiagnostic] | None = None,
) -> tuple[tuple[Path, int], ...]:
    executable = ffmpeg_path or shutil.which("ffmpeg")
    if executable is None:
        raise MediaValidationError("ffmpeg is not available")
    try:
        output_dir = ensure_directory_no_follow(output_dir)
    except SecureFileError as exc:
        raise MediaValidationError("frame output directory is not symlink-free") from exc
    sensitive_media_paths = tuple(dict.fromkeys((media_path, logical_media_path or media_path)))
    margin_ms = min(500, max(0, duration_ms // 10))
    timestamps = (margin_ms, duration_ms // 2, max(margin_ms, duration_ms - margin_ms))
    labels = ("beginning", "middle", "ending")
    frames: list[tuple[Path, int]] = []
    for label, timestamp_ms in zip(labels, timestamps, strict=True):
        target = output_dir / f"{label}.png"
        temporary = output_dir / f".{label}.{uuid.uuid4().hex}.png"
        argv = [
            executable,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            ms_to_ffmpeg(timestamp_ms),
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            str(temporary),
        ]
        started = time.monotonic()
        try:
            result = run_cancellable_process(
                argv,
                timeout_seconds=60,
                cancel_requested=cancel_requested,
                pass_fds=pass_fds,
            )
        except ProcessCancelled as exc:
            temporary.unlink(missing_ok=True)
            raise MediaValidationCancelled(f"{label} frame extraction was cancelled") from exc
        except subprocess.TimeoutExpired as exc:
            temporary.unlink(missing_ok=True)
            _record_quality_exception(
                diagnostic_records,
                operation=f"extract_frame_{label}",
                outcome="timeout",
                argv=argv,
                started=started,
                sensitive_paths=(*sensitive_media_paths, temporary, target),
                stderr=exc.stderr,
            )
            raise MediaValidationTransientError(f"could not extract the {label} frame") from exc
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            _record_quality_exception(
                diagnostic_records,
                operation=f"extract_frame_{label}",
                outcome="launch_error",
                argv=argv,
                started=started,
                sensitive_paths=(*sensitive_media_paths, temporary, target),
            )
            raise MediaValidationTransientError(f"could not extract the {label} frame") from exc
        succeeded = result.returncode == 0 and temporary.is_file()
        _record_quality_result(
            diagnostic_records,
            operation=f"extract_frame_{label}",
            result=result,
            started=started,
            sensitive_paths=(*sensitive_media_paths, temporary, target),
            succeeded=succeeded,
        )
        if not succeeded:
            temporary.unlink(missing_ok=True)
            raise MediaValidationError(f"failed to extract {label} frame")
        try:
            publish_regular_file_immutable_no_follow(temporary, target)
        except SecureFileError as exc:
            temporary.unlink(missing_ok=True)
            raise MediaValidationError(
                "representative frame could not be published safely"
            ) from exc
        frames.append((target, timestamp_ms))
    return tuple(frames)


def create_contact_sheet(*, frames: tuple[tuple[Path, int], ...], output_path: Path) -> None:
    thumb_width = 270
    thumb_height = 480
    header_height = 34
    canvas = Image.new(
        "RGB", (thumb_width * len(frames), thumb_height + header_height), (24, 28, 36)
    )
    draw = ImageDraw.Draw(canvas)
    for index, (frame_path, timestamp_ms) in enumerate(frames):
        try:
            frame_bytes = read_regular_file_no_follow(frame_path, max_bytes=64 * 1024 * 1024)
        except SecureFileError as exc:
            raise MediaValidationError("contact sheet source frame is unsafe") from exc
        with Image.open(BytesIO(frame_bytes)) as source:
            thumbnail = ImageOps.contain(source.convert("RGB"), (thumb_width, thumb_height))
        x = index * thumb_width + (thumb_width - thumbnail.width) // 2
        y = header_height + (thumb_height - thumbnail.height) // 2
        canvas.paste(thumbnail, (x, y))
        draw.text((index * thumb_width + 8, 9), f"t={timestamp_ms / 1000:.3f}s", fill="white")
    try:
        ensure_directory_no_follow(output_path.parent)
    except SecureFileError as exc:
        raise MediaValidationError("contact sheet directory is not symlink-free") from exc
    buffer = BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    try:
        write_bytes_immutable_no_follow(
            output_path,
            buffer.getvalue(),
            max_bytes=32 * 1024 * 1024,
        )
    except SecureFileError as exc:
        raise MediaValidationError("contact sheet could not be published safely") from exc


def record_visual_inspection(
    *, report_path: Path, notes: str, status: str = "viewed_passed"
) -> dict[str, object]:
    if status not in {"viewed_passed", "viewed_failed"}:
        raise ValueError("visual inspection status is invalid")
    if len(notes) > 4_000:
        raise ValueError("visual inspection notes exceed the safe size limit")
    try:
        report_text = read_regular_text_no_follow(report_path, max_bytes=1024 * 1024)
    except SecureFileError as exc:
        raise ValueError("quality report could not be read safely") from exc
    raw_payload = json.loads(report_text)
    if not isinstance(raw_payload, dict):
        raise ValueError("quality report is not a JSON object")
    payload: dict[str, object] = {str(key): value for key, value in raw_payload.items()}
    payload["visual_inspection_status"] = status
    payload["visual_inspection_notes"] = notes
    payload["visual_inspection_at"] = datetime.now(UTC).isoformat()
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        write_text_atomic_no_follow(report_path, serialized, max_bytes=1024 * 1024)
    except SecureFileError as exc:
        raise ValueError("quality report could not be updated safely") from exc
    return payload


def write_quality_report(report: QualityReport, output_path: Path) -> None:
    serialized = json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n"
    try:
        write_text_immutable_no_follow(output_path, serialized, max_bytes=1024 * 1024)
    except SecureFileError as exc:
        raise MediaValidationError("quality report could not be published safely") from exc


def _frame_metric(path: Path, timestamp_ms: int) -> FrameMetric:
    try:
        image_bytes = read_regular_file_no_follow(path, max_bytes=64 * 1024 * 1024)
    except SecureFileError as exc:
        raise MediaValidationError("representative frame could not be read safely") from exc
    with Image.open(BytesIO(image_bytes)) as image:
        grayscale = image.convert("L")
        statistics = ImageStat.Stat(grayscale)
        width, height = grayscale.size
        band_width = max(2, width // 20)
        band_height = max(2, height // 20)
        regions = {
            "left": grayscale.crop((0, 0, band_width, height)),
            "right": grayscale.crop((width - band_width, 0, width, height)),
            "top": grayscale.crop((0, 0, width, band_height)),
            "bottom": grayscale.crop((0, height - band_height, width, height)),
        }
        edge_stats = {name: ImageStat.Stat(region) for name, region in regions.items()}
        center = grayscale.crop((width // 5, height // 5, width * 4 // 5, height * 4 // 5))
        center_variance = float(ImageStat.Stat(center).var[0])
        blank_sides = tuple(
            name
            for name, edge_stat in edge_stats.items()
            if float(edge_stat.var[0]) < 1
            and (float(edge_stat.mean[0]) < 3 or float(edge_stat.mean[0]) > 252)
        )
        maximum_edge_variance = max(float(edge_stat.var[0]) for edge_stat in edge_stats.values())
    return FrameMetric(
        filename=path.name,
        timestamp_ms=timestamp_ms,
        mean_luma=round(float(statistics.mean[0]), 3),
        luma_variance=round(float(statistics.var[0]), 3),
        edge_blank_sides=blank_sides,
        edge_to_center_variance_ratio=round(maximum_edge_variance / max(center_variance, 1.0), 3),
    )


def _validate_edge_and_crop_heuristic(metrics: tuple[FrameMetric, ...]) -> str:
    if not metrics:
        raise MediaValidationError("no representative frames were available for edge checks")
    persistently_blank = set(metrics[0].edge_blank_sides)
    for metric in metrics[1:]:
        persistently_blank.intersection_update(metric.edge_blank_sides)
    if persistently_blank:
        sides = ", ".join(sorted(persistently_blank))
        raise MediaValidationError(f"persistent blank frame edge detected: {sides}")
    if all(metric.edge_to_center_variance_ratio > 20 for metric in metrics):
        raise MediaValidationError("representative frames show extreme edge-biased detail")
    return "passed_edge_activity_and_crop_heuristic"


def _validate_safe_bounds(
    bounds: tuple[tuple[int, int, int, int], ...], *, width: int, height: int
) -> str:
    for left, top, right, bottom in bounds:
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise MediaValidationError("text bounds exceed the video frame")
        if left < width * 0.04 or right > width * 0.96:
            raise MediaValidationError("text bounds exceed horizontal safe margins")
        if top < height * 0.04 or bottom > height * 0.90:
            raise MediaValidationError("text bounds exceed vertical safe margins")
    return "passed" if bounds else "not_applicable"


def _record_quality_result(
    records: list[QualityCommandDiagnostic] | None,
    *,
    operation: str,
    result: subprocess.CompletedProcess[str],
    started: float,
    sensitive_paths: tuple[Path, ...],
    succeeded: bool,
) -> None:
    if records is None:
        return
    records.append(
        QualityCommandDiagnostic(
            operation=operation,
            outcome="succeeded" if succeeded else "process_failed",
            elapsed_ms=max(0, int((time.monotonic() - started) * 1_000)),
            exit_code=result.returncode,
            logical_argv=_quality_logical_argv(result.args, sensitive_paths=sensitive_paths),
            stderr_tail=redact_persistent_diagnostic(
                result.stderr,
                sensitive_values=(str(path) for path in sensitive_paths),
                maximum_characters=2_000,
            ),
        )
    )


def _record_quality_exception(
    records: list[QualityCommandDiagnostic] | None,
    *,
    operation: str,
    outcome: str,
    argv: list[str],
    started: float,
    sensitive_paths: tuple[Path, ...],
    stderr: str | bytes | None = None,
) -> None:
    if records is None:
        return
    if isinstance(stderr, bytes):
        stderr_text = stderr.decode("utf-8", errors="replace")
    else:
        stderr_text = stderr or ""
    records.append(
        QualityCommandDiagnostic(
            operation=operation,
            outcome=outcome,
            elapsed_ms=max(0, int((time.monotonic() - started) * 1_000)),
            exit_code=None,
            logical_argv=_quality_logical_argv(argv, sensitive_paths=sensitive_paths),
            stderr_tail=redact_persistent_diagnostic(
                stderr_text,
                sensitive_values=(str(path) for path in sensitive_paths),
                maximum_characters=2_000,
            ),
        )
    )


def _quality_logical_argv(
    argv: object,
    *,
    sensitive_paths: tuple[Path, ...],
) -> tuple[str, ...]:
    if not isinstance(argv, (list, tuple)):
        return ("<unavailable>",)
    replacements = {
        str(path): f"<local-media-{index}>" for index, path in enumerate(sensitive_paths)
    }
    result: list[str] = []
    for index, argument in enumerate(argv):
        value = str(argument)
        value = Path(value).name if index == 0 else replacements.get(value, value)
        result.append(redact_text(value)[:2_048])
        if len(result) >= 64:
            result.append("<logical-argv-truncated>")
            break
    return tuple(result)
