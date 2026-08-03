from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from liveclip.domain.time import ms_to_ffmpeg, seconds_to_ms
from liveclip.media.fingerprint import stream_sha256
from liveclip.media.models import (
    AudioChunk,
    AudioChunkManifest,
    SilenceInterval,
    SourceMediaMetadata,
)

_ALGORITHM_VERSION = "audio-preprocess-v1"
_SILENCE_EVENT = re.compile(r"silence_(?P<event>start|end):\s*(?P<seconds>-?[0-9]+(?:\.[0-9]+)?)")


class AudioPreprocessError(RuntimeError):
    """A caller-safe deterministic preprocessing failure."""


class AudioPreprocessCancelled(AudioPreprocessError):
    """Cancellation observed at a safe chunk boundary."""


@dataclass(frozen=True, slots=True)
class ChunkWindow:
    index: int
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def chunk_windows(
    source_duration_ms: int,
    *,
    chunk_duration_ms: int,
    overlap_ms: int,
) -> tuple[ChunkWindow, ...]:
    """Return deterministic source-absolute fixed windows with bounded overlap."""

    if source_duration_ms <= 0:
        raise ValueError("source duration must be positive")
    if chunk_duration_ms <= 0:
        raise ValueError("chunk duration must be positive")
    if overlap_ms < 0 or overlap_ms >= chunk_duration_ms:
        raise ValueError("chunk overlap must be nonnegative and shorter than the chunk")
    step_ms = chunk_duration_ms - overlap_ms
    windows: list[ChunkWindow] = []
    start_ms = 0
    while start_ms < source_duration_ms:
        end_ms = min(source_duration_ms, start_ms + chunk_duration_ms)
        windows.append(ChunkWindow(index=len(windows), start_ms=start_ms, end_ms=end_ms))
        if end_ms == source_duration_ms:
            break
        start_ms += step_ms
    return tuple(windows)


def parse_silencedetect(
    output: str,
    *,
    source_offset_ms: int = 0,
    analysis_duration_ms: int | None = None,
) -> tuple[SilenceInterval, ...]:
    """Parse FFmpeg silence events into source-absolute millisecond intervals."""

    if source_offset_ms < 0:
        raise ValueError("source offset must be nonnegative")
    if analysis_duration_ms is not None and analysis_duration_ms <= 0:
        raise ValueError("analysis duration must be positive when provided")
    upper_bound = (
        source_offset_ms + analysis_duration_ms if analysis_duration_ms is not None else None
    )
    pending_start_ms: int | None = None
    intervals: list[SilenceInterval] = []
    for match in _SILENCE_EVENT.finditer(output):
        relative_ms = max(0, seconds_to_ms(match.group("seconds")))
        absolute_ms = source_offset_ms + relative_ms
        if upper_bound is not None:
            absolute_ms = min(absolute_ms, upper_bound)
        if match.group("event") == "start":
            pending_start_ms = absolute_ms
        elif pending_start_ms is not None and absolute_ms > pending_start_ms:
            intervals.append(SilenceInterval(start_ms=pending_start_ms, end_ms=absolute_ms))
            pending_start_ms = None
    if pending_start_ms is not None and upper_bound is not None and upper_bound > pending_start_ms:
        intervals.append(SilenceInterval(start_ms=pending_start_ms, end_ms=upper_bound))
    return tuple(intervals)


def preprocess_audio(
    *,
    source: SourceMediaMetadata,
    output_dir: Path,
    chunk_duration_ms: int,
    overlap_ms: int,
    max_chunk_bytes: int,
    sample_rate_hz: int = 16_000,
    bitrate: str = "48k",
    silence_noise_db: int = -35,
    silence_min_duration_ms: int = 500,
    ffmpeg_path: str | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> AudioChunkManifest:
    """Extract resumable mono AAC chunks and an atomic checkpoint manifest."""

    if max_chunk_bytes <= 0:
        raise ValueError("maximum chunk size must be positive")
    if sample_rate_hz <= 0:
        raise ValueError("sample rate must be positive")
    if not re.fullmatch(r"[1-9][0-9]*k", bitrate):
        raise ValueError("bitrate must be a positive integer followed by 'k'")
    if silence_min_duration_ms <= 0:
        raise ValueError("minimum silence duration must be positive")
    if not -100 <= silence_noise_db <= 0:
        raise ValueError("silence threshold must be between -100 and 0 dB")
    _validate_source_reference(source)

    executable = ffmpeg_path or shutil.which("ffmpeg")
    if executable is None:
        raise AudioPreprocessError("ffmpeg is not available")
    windows = chunk_windows(
        source.duration_ms,
        chunk_duration_ms=chunk_duration_ms,
        overlap_ms=overlap_ms,
    )
    destination = Path(output_dir)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        destination = destination.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise AudioPreprocessError("audio output directory cannot be resolved") from exc
    if not destination.is_dir():
        raise AudioPreprocessError("audio output target must be a directory")
    manifest_path = destination / "chunk-manifest.json"

    existing = _read_manifest(manifest_path)
    if existing is None:
        _check_cancel(cancel_requested)
        silences = detect_silence(
            source_path=source.resolved_path,
            source_duration_ms=source.duration_ms,
            noise_db=silence_noise_db,
            minimum_duration_ms=silence_min_duration_ms,
            ffmpeg_path=executable,
        )
        manifest = AudioChunkManifest(
            source_sha256=source.sha256,
            source_duration_ms=source.duration_ms,
            chunk_duration_ms=chunk_duration_ms,
            chunk_overlap_ms=overlap_ms,
            sample_rate_hz=sample_rate_hz,
            bitrate=bitrate,
            silence_noise_db=silence_noise_db,
            silence_min_duration_ms=silence_min_duration_ms,
            max_chunk_bytes=max_chunk_bytes,
            expected_chunk_count=len(windows),
            silences=silences,
        )
        _write_manifest_atomic(manifest, manifest_path)
    else:
        manifest = existing
        _validate_resume_contract(
            manifest,
            source=source,
            windows=windows,
            chunk_duration_ms=chunk_duration_ms,
            overlap_ms=overlap_ms,
            sample_rate_hz=sample_rate_hz,
            bitrate=bitrate,
            silence_noise_db=silence_noise_db,
            silence_min_duration_ms=silence_min_duration_ms,
            max_chunk_bytes=max_chunk_bytes,
        )

    verified = _verified_resume_chunks(
        manifest,
        destination=destination,
        windows=windows,
        source_sha256=source.sha256,
        overlap_ms=overlap_ms,
        sample_rate_hz=sample_rate_hz,
        bitrate=bitrate,
    )
    for window in windows:
        _check_cancel(cancel_requested)
        if window.index in verified:
            continue
        cache_key = audio_chunk_cache_key(
            source_sha256=source.sha256,
            window=window,
            overlap_ms=overlap_ms,
            sample_rate_hz=sample_rate_hz,
            bitrate=bitrate,
        )
        final_path = _chunk_path(destination, window, cache_key)
        if final_path.exists():
            raise AudioPreprocessError("an unverified audio chunk already occupies its target")
        temporary = destination / f".{final_path.stem}.tmp-{uuid.uuid4().hex}.m4a"
        try:
            _run_audio_extract(
                source_path=source.resolved_path,
                window=window,
                temporary_path=temporary,
                sample_rate_hz=sample_rate_hz,
                bitrate=bitrate,
                ffmpeg_path=executable,
            )
            _check_cancel(cancel_requested)
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise AudioPreprocessError("ffmpeg did not produce an audio chunk")
            size_bytes = temporary.stat().st_size
            if size_bytes > max_chunk_bytes:
                raise AudioPreprocessError("audio chunk exceeds the configured upload size limit")
            sha256 = _hash_audio_file(temporary)
            _publish_no_clobber(temporary, final_path)
            chunk = AudioChunk(
                index=window.index,
                chunk_id=f"chunk_{window.index:06d}",
                source_start_ms=window.start_ms,
                source_end_ms=window.end_ms,
                duration_ms=window.duration_ms,
                overlap_before_ms=_overlap_before(windows, window.index),
                overlap_after_ms=_overlap_after(windows, window.index),
                path=final_path,
                size_bytes=size_bytes,
                sha256=sha256,
                cache_key=cache_key,
            )
        finally:
            temporary.unlink(missing_ok=True)
        verified[window.index] = chunk
        manifest = _updated_manifest(manifest, verified, complete=False)
        _write_manifest_atomic(manifest, manifest_path)

    _validate_source_reference(source)
    completed = _updated_manifest(manifest, verified, complete=True)
    _write_manifest_atomic(completed, manifest_path)
    return completed


def detect_silence(
    *,
    source_path: Path,
    source_duration_ms: int,
    noise_db: int,
    minimum_duration_ms: int,
    ffmpeg_path: str,
) -> tuple[SilenceInterval, ...]:
    argv = [
        ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        str(source_path),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        f"silencedetect=n={noise_db}dB:d={ms_to_ffmpeg(minimum_duration_ms)}",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=21_600,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioPreprocessError("silence analysis could not be executed") from exc
    if result.returncode != 0:
        raise AudioPreprocessError("silence analysis failed")
    return parse_silencedetect(result.stderr, analysis_duration_ms=source_duration_ms)


def audio_chunk_cache_key(
    *,
    source_sha256: str,
    window: ChunkWindow,
    overlap_ms: int,
    sample_rate_hz: int,
    bitrate: str,
) -> str:
    payload = {
        "algorithm": _ALGORITHM_VERSION,
        "audio_codec": "aac",
        "audio_format": "m4a",
        "bitrate": bitrate,
        "channels": 1,
        "overlap_ms": overlap_ms,
        "sample_rate_hz": sample_rate_hz,
        "source_end_ms": window.end_ms,
        "source_sha256": source_sha256,
        "source_start_ms": window.start_ms,
    }
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_audio_extract(
    *,
    source_path: Path,
    window: ChunkWindow,
    temporary_path: Path,
    sample_rate_hz: int,
    bitrate: str,
    ffmpeg_path: str,
) -> None:
    argv = [
        ffmpeg_path,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-ss",
        ms_to_ffmpeg(window.start_ms),
        "-i",
        str(source_path),
        "-t",
        ms_to_ffmpeg(window.duration_ms),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate_hz),
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-map_metadata",
        "-1",
        "-movflags",
        "+faststart",
        str(temporary_path),
    ]
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=1_800,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioPreprocessError("audio extraction could not be executed") from exc
    if result.returncode != 0:
        raise AudioPreprocessError("audio extraction failed")


def _read_manifest(path: Path) -> AudioChunkManifest | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise AudioPreprocessError("audio checkpoint is not a regular file")
    try:
        return AudioChunkManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise AudioPreprocessError("audio checkpoint is invalid") from exc


def _write_manifest_atomic(manifest: AudioChunkManifest, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    payload = manifest.model_dump_json(indent=2) + "\n"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise AudioPreprocessError("audio checkpoint could not be written") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _validate_resume_contract(
    manifest: AudioChunkManifest,
    *,
    source: SourceMediaMetadata,
    windows: tuple[ChunkWindow, ...],
    chunk_duration_ms: int,
    overlap_ms: int,
    sample_rate_hz: int,
    bitrate: str,
    silence_noise_db: int,
    silence_min_duration_ms: int,
    max_chunk_bytes: int,
) -> None:
    expected = (
        manifest.algorithm_version == _ALGORITHM_VERSION
        and manifest.source_sha256 == source.sha256
        and manifest.source_duration_ms == source.duration_ms
        and manifest.chunk_duration_ms == chunk_duration_ms
        and manifest.chunk_overlap_ms == overlap_ms
        and manifest.sample_rate_hz == sample_rate_hz
        and manifest.bitrate == bitrate
        and manifest.silence_noise_db == silence_noise_db
        and manifest.silence_min_duration_ms == silence_min_duration_ms
        and manifest.max_chunk_bytes == max_chunk_bytes
        and manifest.expected_chunk_count == len(windows)
    )
    if not expected:
        raise AudioPreprocessError("audio checkpoint does not match this preprocessing request")


def _verified_resume_chunks(
    manifest: AudioChunkManifest,
    *,
    destination: Path,
    windows: tuple[ChunkWindow, ...],
    source_sha256: str,
    overlap_ms: int,
    sample_rate_hz: int,
    bitrate: str,
) -> dict[int, AudioChunk]:
    verified: dict[int, AudioChunk] = {}
    by_index = {window.index: window for window in windows}
    for chunk in manifest.chunks:
        window = by_index[chunk.index]
        cache_key = audio_chunk_cache_key(
            source_sha256=source_sha256,
            window=window,
            overlap_ms=overlap_ms,
            sample_rate_hz=sample_rate_hz,
            bitrate=bitrate,
        )
        expected_path = _chunk_path(destination, window, cache_key)
        contract_matches = (
            chunk.source_start_ms == window.start_ms
            and chunk.source_end_ms == window.end_ms
            and chunk.duration_ms == window.duration_ms
            and chunk.overlap_before_ms == _overlap_before(windows, window.index)
            and chunk.overlap_after_ms == _overlap_after(windows, window.index)
            and chunk.cache_key == cache_key
            and chunk.path == expected_path
        )
        if not contract_matches:
            raise AudioPreprocessError("an audio checkpoint chunk has invalid metadata")
        if not expected_path.exists():
            continue
        if expected_path.is_symlink() or not expected_path.is_file():
            raise AudioPreprocessError("a checkpoint audio chunk is not a regular file")
        size_bytes = expected_path.stat().st_size
        if size_bytes != chunk.size_bytes or _hash_audio_file(expected_path) != chunk.sha256:
            raise AudioPreprocessError("a checkpoint audio chunk failed hash verification")
        verified[chunk.index] = chunk
    return verified


def _updated_manifest(
    manifest: AudioChunkManifest,
    chunks: dict[int, AudioChunk],
    *,
    complete: bool,
) -> AudioChunkManifest:
    payload = manifest.model_dump()
    payload["chunks"] = tuple(chunks[index] for index in sorted(chunks))
    payload["complete"] = complete
    return AudioChunkManifest.model_validate(payload)


def _chunk_path(destination: Path, window: ChunkWindow, cache_key: str) -> Path:
    filename = (
        f"chunk-{window.index:04d}-{window.start_ms:012d}-{window.end_ms:012d}-{cache_key[:12]}.m4a"
    )
    return destination / filename


def _overlap_before(windows: tuple[ChunkWindow, ...], index: int) -> int:
    if index == 0:
        return 0
    return max(0, windows[index - 1].end_ms - windows[index].start_ms)


def _overlap_after(windows: tuple[ChunkWindow, ...], index: int) -> int:
    if index + 1 >= len(windows):
        return 0
    return max(0, windows[index].end_ms - windows[index + 1].start_ms)


def _publish_no_clobber(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise AudioPreprocessError("audio chunk publication lost a no-clobber race") from exc
    except OSError as exc:
        raise AudioPreprocessError("audio chunk could not be published atomically") from exc
    with suppress(OSError):
        temporary.unlink()


def _check_cancel(callback: Callable[[], bool] | None) -> None:
    if callback is not None and callback():
        raise AudioPreprocessCancelled("audio preprocessing was cancelled")


def _validate_source_reference(source: SourceMediaMetadata) -> None:
    try:
        current_path = source.resolved_path.resolve(strict=True)
        current = current_path.stat()
    except (OSError, RuntimeError) as exc:
        raise AudioPreprocessError("source media is no longer available") from exc
    identity_matches = (
        current_path == source.resolved_path
        and current_path.is_file()
        and current.st_size == source.size_bytes
        and current.st_mtime_ns == source.mtime_ns
        and (source.inode is None or current.st_ino == source.inode)
        and (source.device is None or current.st_dev == source.device)
    )
    if not identity_matches:
        raise AudioPreprocessError("source media changed after import")


def _hash_audio_file(path: Path) -> str:
    try:
        return stream_sha256(path)
    except OSError as exc:
        raise AudioPreprocessError("audio chunk could not be fingerprinted") from exc
