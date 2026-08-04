from __future__ import annotations

import json
import math
import shutil
import stat
import subprocess
from collections.abc import Callable, Iterable
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from liveclip.domain.time import seconds_to_ms
from liveclip.media.models import SourceMediaMetadata
from liveclip.media.process import ProcessCancelled, run_cancellable_process
from liveclip.media.secure_files import SecureFileError, open_pinned_regular_file


class MediaIngestError(RuntimeError):
    """A deterministic, caller-safe source ingest failure."""


class MediaIngestTransientError(MediaIngestError):
    """A local probe execution failure that can be retried unchanged."""


class MediaIngestCancelled(MediaIngestError):
    """Source inspection stopped before metadata or fingerprint publication."""


def resolve_allowed_source(source_path: str | Path, allowed_roots: Iterable[Path]) -> Path:
    """Resolve and validate a source path against strict real allowed roots."""

    candidate = Path(source_path)
    if not candidate.is_absolute():
        raise MediaIngestError("source media path must be absolute")
    if ".." in candidate.parts:
        raise MediaIngestError("source media path must not contain parent traversal")

    roots = tuple(_resolve_allowed_root(root) for root in allowed_roots)
    if not roots:
        raise MediaIngestError("no allowed media roots are configured")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MediaIngestError("source media does not exist or cannot be resolved") from exc
    try:
        mode = resolved.stat().st_mode
    except OSError as exc:
        raise MediaIngestError("source media cannot be inspected") from exc
    if not stat.S_ISREG(mode):
        raise MediaIngestError("source media must be a regular file")
    if not any(resolved == root or root in resolved.parents for root in roots):
        raise MediaIngestError("source media is outside the configured allowed roots")
    return resolved


def run_ffprobe(
    path: Path,
    *,
    ffprobe_path: str | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    pass_fds: tuple[int, ...] = (),
) -> dict[str, Any]:
    executable = ffprobe_path or shutil.which("ffprobe")
    if executable is None:
        raise MediaIngestError("ffprobe is not available")
    try:
        result = run_cancellable_process(
            [
                executable,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            timeout_seconds=120,
            cancel_requested=cancel_requested,
            pass_fds=pass_fds,
        )
    except ProcessCancelled as exc:
        raise MediaIngestCancelled("source media inspection was cancelled") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaIngestTransientError("ffprobe could not inspect source media") from exc
    if result.returncode != 0:
        raise MediaIngestError("ffprobe rejected source media")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaIngestError("ffprobe returned invalid media metadata") from exc
    if not isinstance(payload, dict):
        raise MediaIngestError("ffprobe returned an unexpected media response")
    return payload


def parse_ffprobe_metadata(
    payload: dict[str, Any],
    *,
    resolved_path: Path,
    size_bytes: int,
    sha256: str,
    mtime_ns: int,
    inode: int | None,
    device: int | None,
) -> SourceMediaMetadata:
    streams = payload.get("streams")
    format_payload = payload.get("format")
    if not isinstance(streams, list) or not isinstance(format_payload, dict):
        raise MediaIngestError("ffprobe metadata is missing streams or format")
    video = _select_stream(streams, "video", exclude_attached_picture=True)
    audio = _select_stream(streams, "audio", exclude_attached_picture=False)
    if not isinstance(video, dict) or not isinstance(audio, dict):
        raise MediaIngestError("source media must contain video and audio streams")

    duration_ms = _duration_ms(format_payload, streams)
    frame_rate = _frame_rate(video)
    format_name = _required_text(format_payload, "format_name", "container format")
    try:
        return SourceMediaMetadata(
            resolved_path=resolved_path,
            filename=resolved_path.name,
            size_bytes=size_bytes,
            sha256=sha256,
            duration_ms=duration_ms,
            format_name=format_name,
            video_stream_index=_stream_index(video, streams),
            video_codec=_required_text(video, "codec_name", "video codec"),
            video_width=_positive_int(video, "width", "video width"),
            video_height=_positive_int(video, "height", "video height"),
            video_frame_rate=frame_rate,
            video_rotation_degrees=_rotation_degrees(video),
            audio_stream_index=_stream_index(audio, streams),
            audio_codec=_required_text(audio, "codec_name", "audio codec"),
            audio_sample_rate_hz=_positive_int(audio, "sample_rate", "audio sample rate"),
            audio_channels=_positive_int(audio, "channels", "audio channel count"),
            mtime_ns=mtime_ns,
            inode=inode,
            device=device,
        )
    except ValidationError as exc:
        raise MediaIngestError("ffprobe metadata failed source validation") from exc


def ingest_source(
    source_path: str | Path,
    *,
    allowed_roots: Iterable[Path],
    ffprobe_path: str | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> SourceMediaMetadata:
    """Validate, fingerprint, probe, and mutation-check a read-only source."""

    resolved = resolve_allowed_source(source_path, allowed_roots)
    try:
        with open_pinned_regular_file(resolved) as pinned:
            before = _stat_identity_from_result(pinned.metadata)
            try:
                fingerprint = pinned.sha256(cancel_requested=cancel_requested)
            except InterruptedError as exc:
                raise MediaIngestCancelled("source media fingerprint was cancelled") from exc
            payload = run_ffprobe(
                pinned.process_path,
                ffprobe_path=ffprobe_path,
                cancel_requested=cancel_requested,
                pass_fds=pinned.pass_fds,
            )
            repeated_fingerprint = pinned.sha256(cancel_requested=cancel_requested)
            pinned.validate_binding()
    except MediaIngestCancelled:
        raise
    except (SecureFileError, OSError) as exc:
        raise MediaIngestError("source media changed while it was being imported") from exc
    except InterruptedError as exc:
        raise MediaIngestCancelled("source media fingerprint was cancelled") from exc
    try:
        still_resolved = resolved.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MediaIngestError("source media changed while it was being imported") from exc
    if fingerprint != repeated_fingerprint or still_resolved != resolved:
        raise MediaIngestError("source media changed while it was being imported")
    return parse_ffprobe_metadata(
        payload,
        resolved_path=resolved,
        size_bytes=before[0],
        sha256=fingerprint,
        mtime_ns=before[1],
        inode=before[2],
        device=before[3],
    )


def _resolve_allowed_root(root: Path) -> Path:
    candidate = Path(root)
    if not candidate.is_absolute():
        raise MediaIngestError("allowed media roots must be absolute")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MediaIngestError("an allowed media root does not exist") from exc
    if not resolved.is_dir():
        raise MediaIngestError("allowed media roots must be directories")
    return resolved


def _stream_type(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    stream_type = value.get("codec_type")
    return stream_type if isinstance(stream_type, str) else None


def _select_stream(
    streams: list[object],
    stream_type: str,
    *,
    exclude_attached_picture: bool,
) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for position, value in enumerate(streams):
        if not isinstance(value, dict) or _stream_type(value) != stream_type:
            continue
        disposition = value.get("disposition")
        attached = isinstance(disposition, dict) and disposition.get("attached_pic") in {1, "1"}
        if exclude_attached_picture and attached:
            continue
        candidates.append((position, value))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            0 if _is_default_stream(item[1]) else 1,
            _stream_index(item[1], streams, fallback=item[0]),
        )
    )
    return candidates[0][1]


def _is_default_stream(stream: dict[str, Any]) -> bool:
    disposition = stream.get("disposition")
    return isinstance(disposition, dict) and disposition.get("default") in {1, "1"}


def _stream_index(
    stream: dict[str, Any],
    streams: list[object],
    *,
    fallback: int | None = None,
) -> int:
    raw = stream.get("index")
    if isinstance(raw, bool):
        raw = None
    try:
        parsed = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None and parsed >= 0:
        return parsed
    if fallback is not None:
        return fallback
    return streams.index(stream)


def _rotation_degrees(video: dict[str, Any]) -> Literal[0, 90, 180, 270]:
    values: list[object] = []
    side_data = video.get("side_data_list")
    if isinstance(side_data, list):
        values.extend(item.get("rotation") for item in side_data if isinstance(item, dict))
    tags = video.get("tags")
    if isinstance(tags, dict):
        values.append(tags.get("rotate"))
    for raw in values:
        try:
            rotation = int(float(str(raw))) % 360
        except (TypeError, ValueError):
            continue
        if rotation in {0, 90, 180, 270}:
            return cast("Literal[0, 90, 180, 270]", rotation)
    return 0


def _stat_identity_from_result(
    metadata: Any,
) -> tuple[int, int, int | None, int | None]:
    return (
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        getattr(metadata, "st_ino", None),
        getattr(metadata, "st_dev", None),
    )


def _duration_ms(format_payload: dict[str, Any], streams: list[object]) -> int:
    candidates: list[Decimal] = []
    for value in [
        format_payload.get("duration"),
        *[stream.get("duration") for stream in streams if isinstance(stream, dict)],
    ]:
        try:
            duration = Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        if duration.is_finite() and duration > 0:
            candidates.append(duration)
    if not candidates:
        raise MediaIngestError("ffprobe did not report a valid media duration")
    duration_ms = seconds_to_ms(max(candidates))
    if duration_ms <= 0:
        raise MediaIngestError("source media duration must be positive")
    return duration_ms


def _frame_rate(video: dict[str, Any]) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = video.get(key)
        if not isinstance(value, str):
            continue
        try:
            rate = Fraction(value)
        except (ValueError, ZeroDivisionError):
            continue
        result = float(rate)
        if math.isfinite(result) and result > 0:
            return result
    raise MediaIngestError("ffprobe did not report a valid video frame rate")


def _positive_int(payload: dict[str, Any], key: str, label: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise MediaIngestError(f"ffprobe did not report a valid {label}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MediaIngestError(f"ffprobe did not report a valid {label}") from exc
    if parsed <= 0:
        raise MediaIngestError(f"ffprobe did not report a valid {label}")
    return parsed


def _required_text(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MediaIngestError(f"ffprobe did not report a valid {label}")
    return value.strip()
