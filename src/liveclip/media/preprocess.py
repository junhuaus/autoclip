from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from liveclip.domain.time import ms_to_ffmpeg, seconds_to_ms
from liveclip.media.models import (
    AudioChunk,
    AudioChunkManifest,
    SilenceInterval,
    SourceMediaMetadata,
)
from liveclip.media.process import ProcessCancelled, run_cancellable_process
from liveclip.media.secure_files import (
    PinnedRegularFile,
    SecureFileError,
    SecureFileMissing,
    cross_launch_source_stat_matches,
    ensure_directory_no_follow,
    hash_regular_file_no_follow,
    open_pinned_regular_file,
    publish_regular_file_immutable_no_follow,
    read_regular_text_no_follow,
    write_text_atomic_no_follow,
    write_text_immutable_no_follow,
)

_ALGORITHM_VERSION = "audio-preprocess-v1"
_MAX_CHUNK_WINDOWS = 10_000
_DISK_RESERVE_BYTES = 16 * 1024 * 1024
_SILENCE_EVENT = re.compile(r"silence_(?P<event>start|end):\s*(?P<seconds>-?[0-9]+(?:\.[0-9]+)?)")


class AudioPreprocessError(RuntimeError):
    """A caller-safe deterministic preprocessing failure."""


class AudioPreprocessTransientError(AudioPreprocessError):
    """A local preprocessing execution failure that can be retried unchanged."""


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
    if overlap_ms * 2 > chunk_duration_ms:
        raise ValueError("chunk overlap must not exceed half of the chunk duration")
    step_ms = chunk_duration_ms - overlap_ms
    remaining_after_first = max(0, source_duration_ms - chunk_duration_ms)
    expected_count = 1 + (remaining_after_first + step_ms - 1) // step_ms
    if expected_count > _MAX_CHUNK_WINDOWS:
        raise ValueError("audio preprocessing would create too many chunks")
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
    if not intervals:
        return ()
    # MPEG-TS timestamp jitter can make two consecutive FFmpeg silence events
    # overlap by a few milliseconds after canonical millisecond rounding.  Silence
    # is a set of source-time intervals, so normalize it to an ordered union before
    # persisting the strict manifest instead of rejecting otherwise valid media.
    ordered = sorted(intervals, key=lambda interval: (interval.start_ms, interval.end_ms))
    merged = [ordered[0]]
    for interval in ordered[1:]:
        previous = merged[-1]
        if interval.start_ms < previous.end_ms:
            merged[-1] = SilenceInterval(
                start_ms=previous.start_ms,
                end_ms=max(previous.end_ms, interval.end_ms),
            )
        else:
            merged.append(interval)
    return tuple(merged)


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
    """Pin the imported source while extracting one recoverable audio manifest."""

    _validate_source_reference(source)
    try:
        with open_pinned_regular_file(source.resolved_path) as pinned:
            _validate_pinned_source_identity(source, pinned)

            def validate_source_content() -> None:
                _check_cancel(cancel_requested)
                try:
                    observed = pinned.sha256(cancel_requested=cancel_requested)
                except InterruptedError as exc:
                    raise AudioPreprocessCancelled(
                        "source fingerprint validation was cancelled"
                    ) from exc
                if observed != source.sha256:
                    raise AudioPreprocessError("source media content changed after import")
                pinned.validate_binding()

            validate_source_content()
            return _preprocess_audio_with_pinned_source(
                source=source,
                output_dir=output_dir,
                chunk_duration_ms=chunk_duration_ms,
                overlap_ms=overlap_ms,
                max_chunk_bytes=max_chunk_bytes,
                sample_rate_hz=sample_rate_hz,
                bitrate=bitrate,
                silence_noise_db=silence_noise_db,
                silence_min_duration_ms=silence_min_duration_ms,
                ffmpeg_path=ffmpeg_path,
                cancel_requested=cancel_requested,
                source_input_path=pinned.process_path,
                source_pass_fds=pinned.pass_fds,
                validate_source_content=validate_source_content,
            )
    except (AudioPreprocessError, AudioPreprocessCancelled):
        raise
    except (SecureFileError, OSError) as exc:
        raise AudioPreprocessError("source media changed after import") from exc


def _preprocess_audio_with_pinned_source(
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
    source_input_path: Path,
    source_pass_fds: tuple[int, ...],
    validate_source_content: Callable[[], None],
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
        destination = ensure_directory_no_follow(destination)
    except SecureFileError as exc:
        raise AudioPreprocessError("audio output directory is not symlink-free") from exc
    except OSError as exc:
        raise AudioPreprocessTransientError("audio output directory cannot be resolved") from exc
    if not destination.is_dir():
        raise AudioPreprocessError("audio output target must be a directory")
    manifest_path = destination / "chunk-manifest.json"
    checkpoint_path = destination / "chunk-checkpoint.json"

    published = _read_manifest(manifest_path)
    if published is not None and not published.complete:
        raise AudioPreprocessError("published audio manifest is not complete")
    existing = published or _read_manifest(checkpoint_path)
    if existing is None:
        _check_cancel(cancel_requested)
        silences = detect_silence(
            source_path=source_input_path,
            source_duration_ms=source.duration_ms,
            audio_stream_index=source.audio_stream_index,
            noise_db=silence_noise_db,
            minimum_duration_ms=silence_min_duration_ms,
            ffmpeg_path=executable,
            cancel_requested=cancel_requested,
            pass_fds=source_pass_fds,
        )
        manifest = AudioChunkManifest(
            source_sha256=source.sha256,
            source_duration_ms=source.duration_ms,
            source_audio_stream_index=source.audio_stream_index,
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
        _write_manifest_atomic(manifest, checkpoint_path)
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
        audio_stream_index=source.audio_stream_index,
        overlap_ms=overlap_ms,
        sample_rate_hz=sample_rate_hz,
        bitrate=bitrate,
    )
    if manifest.complete and len(verified) == len(windows):
        _check_cancel(cancel_requested)
        _validate_source_reference(source)
        validate_source_content()
        return manifest
    _ensure_audio_disk_budget(
        destination,
        windows=tuple(window for window in windows if window.index not in verified),
        bitrate=bitrate,
    )
    for window in windows:
        _check_cancel(cancel_requested)
        if window.index in verified:
            continue
        cache_key = audio_chunk_cache_key(
            source_sha256=source.sha256,
            window=window,
            audio_stream_index=source.audio_stream_index,
            overlap_ms=overlap_ms,
            sample_rate_hz=sample_rate_hz,
            bitrate=bitrate,
        )
        final_path = _chunk_path(destination, window, cache_key)
        temporary = destination / f".{final_path.stem}.tmp-{uuid.uuid4().hex}.m4a"
        try:
            _run_audio_extract(
                source_path=source_input_path,
                window=window,
                temporary_path=temporary,
                audio_stream_index=source.audio_stream_index,
                sample_rate_hz=sample_rate_hz,
                bitrate=bitrate,
                ffmpeg_path=executable,
                cancel_requested=cancel_requested,
                pass_fds=source_pass_fds,
            )
            _check_cancel(cancel_requested)
            if not temporary.is_file() or temporary.stat().st_size <= 0:
                raise AudioPreprocessError("ffmpeg did not produce an audio chunk")
            size_bytes = temporary.stat().st_size
            if size_bytes > max_chunk_bytes:
                raise AudioPreprocessError("audio chunk exceeds the configured upload size limit")
            sha256 = _hash_audio_file(temporary)
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
            pending = dict(verified)
            pending[window.index] = chunk
            manifest = _updated_manifest(manifest, pending, complete=False)
            # Checkpoint the deterministic target and verified temporary bytes before
            # publishing. A crash can therefore leave either a missing referenced file
            # (safe to regenerate) or a referenced complete file (safe to adopt), never
            # an unreferenced canonical chunk that makes retries diverge.
            _write_manifest_atomic(manifest, checkpoint_path)
            _publish_no_clobber(temporary, final_path)
        finally:
            temporary.unlink(missing_ok=True)
        verified[window.index] = chunk

    _validate_source_reference(source)
    validate_source_content()
    completed = _updated_manifest(manifest, verified, complete=True)
    _write_complete_manifest_immutable(completed, manifest_path)
    checkpoint_path.unlink(missing_ok=True)
    return completed


def _ensure_audio_disk_budget(
    destination: Path,
    *,
    windows: tuple[ChunkWindow, ...],
    bitrate: str,
) -> None:
    if not windows:
        return
    bitrate_kbps = int(bitrate[:-1])
    encoded_bytes = sum(window.duration_ms for window in windows) * bitrate_kbps // 8
    largest_chunk_bytes = max(window.duration_ms for window in windows) * bitrate_kbps // 8
    required_bytes = (encoded_bytes * 5 + 3) // 4 + (largest_chunk_bytes * 2) + _DISK_RESERVE_BYTES
    try:
        free_bytes = shutil.disk_usage(destination).free
    except OSError as exc:
        raise AudioPreprocessTransientError("audio output disk capacity could not be read") from exc
    if free_bytes < required_bytes:
        raise AudioPreprocessTransientError(
            "audio preprocessing requires more free local disk space"
        )


def detect_silence(
    *,
    source_path: Path,
    source_duration_ms: int,
    audio_stream_index: int = 1,
    noise_db: int,
    minimum_duration_ms: int,
    ffmpeg_path: str,
    cancel_requested: Callable[[], bool] | None = None,
    pass_fds: tuple[int, ...] = (),
) -> tuple[SilenceInterval, ...]:
    if audio_stream_index < 0:
        raise ValueError("audio stream index must be nonnegative")
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
        f"0:{audio_stream_index}",
        "-vn",
        "-af",
        f"silencedetect=n={noise_db}dB:d={ms_to_ffmpeg(minimum_duration_ms)}",
        "-f",
        "null",
        "-",
    ]
    try:
        result = run_cancellable_process(
            argv,
            timeout_seconds=21_600,
            cancel_requested=cancel_requested,
            pass_fds=pass_fds,
        )
    except ProcessCancelled as exc:
        raise AudioPreprocessCancelled("silence analysis was cancelled") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioPreprocessTransientError("silence analysis could not be executed") from exc
    if result.returncode != 0:
        raise AudioPreprocessError("silence analysis failed")
    return parse_silencedetect(result.stderr, analysis_duration_ms=source_duration_ms)


def audio_chunk_cache_key(
    *,
    source_sha256: str,
    window: ChunkWindow,
    audio_stream_index: int = 1,
    overlap_ms: int,
    sample_rate_hz: int,
    bitrate: str,
) -> str:
    if audio_stream_index < 0:
        raise ValueError("audio stream index must be nonnegative")
    payload = {
        "algorithm": _ALGORITHM_VERSION,
        "audio_codec": "aac",
        "audio_format": "m4a",
        "bitrate": bitrate,
        "channels": 1,
        "overlap_ms": overlap_ms,
        "sample_rate_hz": sample_rate_hz,
        "source_audio_stream_index": audio_stream_index,
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
    audio_stream_index: int = 1,
    sample_rate_hz: int,
    bitrate: str,
    ffmpeg_path: str,
    cancel_requested: Callable[[], bool] | None = None,
    pass_fds: tuple[int, ...] = (),
) -> None:
    if audio_stream_index < 0:
        raise ValueError("audio stream index must be nonnegative")
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
        f"0:{audio_stream_index}",
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
        result = run_cancellable_process(
            argv,
            timeout_seconds=1_800,
            cancel_requested=cancel_requested,
            pass_fds=pass_fds,
        )
    except ProcessCancelled as exc:
        raise AudioPreprocessCancelled("audio extraction was cancelled") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioPreprocessTransientError("audio extraction could not be executed") from exc
    if result.returncode != 0:
        raise AudioPreprocessError("audio extraction failed")


def _read_manifest(path: Path) -> AudioChunkManifest | None:
    try:
        payload = read_regular_text_no_follow(path, max_bytes=8_000_000)
    except SecureFileMissing:
        return None
    except SecureFileError as exc:
        raise AudioPreprocessError("audio checkpoint is not a safe regular file") from exc
    try:
        return AudioChunkManifest.model_validate_json(payload)
    except ValidationError as exc:
        raise AudioPreprocessError("audio checkpoint is invalid") from exc


def _write_manifest_atomic(manifest: AudioChunkManifest, path: Path) -> None:
    payload = manifest.model_dump_json(indent=2) + "\n"
    try:
        write_text_atomic_no_follow(path, payload, max_bytes=8_000_000)
    except SecureFileError as exc:
        raise AudioPreprocessTransientError("audio checkpoint could not be written") from exc


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
        and manifest.source_audio_stream_index == source.audio_stream_index
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
    audio_stream_index: int,
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
            audio_stream_index=audio_stream_index,
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
        try:
            observed_sha256, size_bytes = hash_regular_file_no_follow(expected_path)
        except SecureFileMissing:
            continue
        except SecureFileError as exc:
            raise AudioPreprocessError(
                "a checkpoint audio chunk is not a safe regular file"
            ) from exc
        if size_bytes != chunk.size_bytes or observed_sha256 != chunk.sha256:
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
        publish_regular_file_immutable_no_follow(temporary, destination)
    except SecureFileError as exc:
        raise AudioPreprocessTransientError(
            "audio chunk could not be published atomically"
        ) from exc


def _check_cancel(callback: Callable[[], bool] | None) -> None:
    if callback is not None and callback():
        raise AudioPreprocessCancelled("audio preprocessing was cancelled")


def _validate_source_reference(source: SourceMediaMetadata) -> None:
    try:
        current_path = source.resolved_path.resolve(strict=True)
        current = current_path.stat()
    except (OSError, RuntimeError) as exc:
        raise AudioPreprocessError("source media is no longer available") from exc
    identity_matches = cross_launch_source_stat_matches(
        current_path,
        current,
        expected_path=source.resolved_path,
        expected_size_bytes=source.size_bytes,
        expected_mtime_ns=source.mtime_ns,
        expected_inode=source.inode,
    )
    if not identity_matches:
        raise AudioPreprocessError("source media changed after import")


def _validate_pinned_source_identity(
    source: SourceMediaMetadata,
    pinned: PinnedRegularFile,
) -> None:
    metadata = pinned.metadata
    if not cross_launch_source_stat_matches(
        pinned.path,
        metadata,
        expected_path=source.resolved_path,
        expected_size_bytes=source.size_bytes,
        expected_mtime_ns=source.mtime_ns,
        expected_inode=source.inode,
    ):
        raise AudioPreprocessError("source media changed after import")
    pinned.validate_binding()


def _write_complete_manifest_immutable(manifest: AudioChunkManifest, path: Path) -> None:
    if not manifest.complete:
        raise AudioPreprocessError("only a complete audio manifest can be published")
    payload = manifest.model_dump_json(indent=2) + "\n"
    try:
        write_text_immutable_no_follow(path, payload, max_bytes=8_000_000)
    except SecureFileError as exc:
        raise AudioPreprocessError("complete audio manifest could not be published safely") from exc


def _hash_audio_file(path: Path) -> str:
    try:
        value, _size = hash_regular_file_no_follow(path)
        return value
    except SecureFileError as exc:
        raise AudioPreprocessTransientError("audio chunk could not be fingerprinted") from exc
