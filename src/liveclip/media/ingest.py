from __future__ import annotations

import json
import math
import shutil
import stat
import subprocess
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from liveclip.domain.time import seconds_to_ms
from liveclip.media.fingerprint import stream_sha256
from liveclip.media.models import SourceMediaMetadata


class MediaIngestError(RuntimeError):
    """A deterministic, caller-safe source ingest failure."""


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


def run_ffprobe(path: Path, *, ffprobe_path: str | None = None) -> dict[str, Any]:
    executable = ffprobe_path or shutil.which("ffprobe")
    if executable is None:
        raise MediaIngestError("ffprobe is not available")
    try:
        result = subprocess.run(
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
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaIngestError("ffprobe could not inspect source media") from exc
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
    video = next((item for item in streams if _stream_type(item) == "video"), None)
    audio = next((item for item in streams if _stream_type(item) == "audio"), None)
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
            video_codec=_required_text(video, "codec_name", "video codec"),
            video_width=_positive_int(video, "width", "video width"),
            video_height=_positive_int(video, "height", "video height"),
            video_frame_rate=frame_rate,
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
) -> SourceMediaMetadata:
    """Validate, fingerprint, probe, and mutation-check a read-only source."""

    resolved = resolve_allowed_source(source_path, allowed_roots)
    before = _stat_identity(resolved)
    try:
        fingerprint = stream_sha256(resolved)
    except OSError as exc:
        raise MediaIngestError("source media could not be fingerprinted") from exc
    payload = run_ffprobe(resolved, ffprobe_path=ffprobe_path)
    after = _stat_identity(resolved)
    try:
        still_resolved = resolved.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MediaIngestError("source media changed while it was being imported") from exc
    if before != after or still_resolved != resolved:
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


def _stat_identity(path: Path) -> tuple[int, int, int | None, int | None]:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise MediaIngestError("source media cannot be inspected") from exc
    return (
        metadata.st_size,
        metadata.st_mtime_ns,
        getattr(metadata, "st_ino", None),
        getattr(metadata, "st_dev", None),
    )


def _stream_type(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    stream_type = value.get("codec_type")
    return stream_type if isinstance(stream_type, str) else None


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
