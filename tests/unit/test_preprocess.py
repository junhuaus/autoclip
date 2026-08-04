from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import liveclip.media.preprocess as preprocess_module
from liveclip.media.fingerprint import stream_sha256
from liveclip.media.models import AudioChunkManifest, SilenceInterval, SourceMediaMetadata
from liveclip.media.preprocess import (
    AudioPreprocessCancelled,
    AudioPreprocessError,
    AudioPreprocessTransientError,
    ChunkWindow,
    _run_audio_extract,
    audio_chunk_cache_key,
    chunk_windows,
    detect_silence,
    parse_silencedetect,
    preprocess_audio,
)


def source_metadata(tmp_path: Path, *, duration_ms: int = 25_000) -> SourceMediaMetadata:
    source = (tmp_path / "source.mp4").resolve()
    source.write_bytes(b"read-only-source")
    return SourceMediaMetadata(
        resolved_path=source,
        filename=source.name,
        size_bytes=source.stat().st_size,
        sha256=stream_sha256(source),
        duration_ms=duration_ms,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
        video_codec="h264",
        video_stream_index=0,
        video_rotation_degrees=0,
        video_width=1280,
        video_height=720,
        video_frame_rate=30.0,
        audio_codec="aac",
        audio_stream_index=1,
        audio_sample_rate_hz=48_000,
        audio_channels=2,
        mtime_ns=source.stat().st_mtime_ns,
        inode=source.stat().st_ino,
        device=source.stat().st_dev,
    )


def test_chunk_windows_have_exact_overlap_and_short_final_window() -> None:
    windows = chunk_windows(25_000, chunk_duration_ms=10_000, overlap_ms=2_000)

    assert [(window.start_ms, window.end_ms) for window in windows] == [
        (0, 10_000),
        (8_000, 18_000),
        (16_000, 25_000),
    ]
    assert [window.duration_ms for window in windows] == [10_000, 10_000, 9_000]

    exact = chunk_windows(18_000, chunk_duration_ms=10_000, overlap_ms=2_000)
    assert [(window.start_ms, window.end_ms) for window in exact] == [
        (0, 10_000),
        (8_000, 18_000),
    ]


def test_chunk_windows_validate_timing_configuration() -> None:
    with pytest.raises(ValueError):
        chunk_windows(0, chunk_duration_ms=10_000, overlap_ms=1_000)
    with pytest.raises(ValueError):
        chunk_windows(10_000, chunk_duration_ms=10_000, overlap_ms=10_000)
    with pytest.raises(ValueError, match="half"):
        chunk_windows(60_000, chunk_duration_ms=10_000, overlap_ms=5_001)
    with pytest.raises(ValueError, match="too many"):
        chunk_windows(100_000_000, chunk_duration_ms=10_000, overlap_ms=5_000)


def test_silencedetect_parser_converts_to_absolute_milliseconds_and_closes_tail() -> None:
    stderr = """
    [silencedetect] silence_start: 0.125
    [silencedetect] silence_end: 1.875 | silence_duration: 1.750
    [silencedetect] silence_start: 4.500
    """

    intervals = parse_silencedetect(
        stderr,
        source_offset_ms=10_000,
        analysis_duration_ms=5_000,
    )

    assert intervals == (
        SilenceInterval(start_ms=10_125, end_ms=11_875),
        SilenceInterval(start_ms=14_500, end_ms=15_000),
    )


def test_audio_extract_and_silence_detection_disable_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append((argv, kwargs))
        stderr = "silence_start: 0.25\nsilence_end: 0.75 | silence_duration: 0.5"
        return subprocess.CompletedProcess(argv, 0, "", stderr)

    monkeypatch.setattr(preprocess_module, "run_cancellable_process", fake_run)
    _run_audio_extract(
        source_path=tmp_path / "source.mp4",
        window=ChunkWindow(index=0, start_ms=2_000, end_ms=7_000),
        temporary_path=tmp_path / ".private.m4a",
        sample_rate_hz=16_000,
        bitrate="48k",
        ffmpeg_path="/system/ffmpeg",
    )
    intervals = detect_silence(
        source_path=tmp_path / "source.mp4",
        source_duration_ms=1_000,
        noise_db=-35,
        minimum_duration_ms=500,
        ffmpeg_path="/system/ffmpeg",
    )

    assert len(observed) == 2
    assert all(kwargs["timeout_seconds"] > 0 for _, kwargs in observed)
    assert all("cancel_requested" in kwargs for _, kwargs in observed)
    extract_argv = observed[0][0]
    assert extract_argv[extract_argv.index("-ac") + 1] == "1"
    assert extract_argv[extract_argv.index("-c:a") + 1] == "aac"
    assert extract_argv[extract_argv.index("-map") + 1] == "0:1"
    assert intervals == (SilenceInterval(start_ms=250, end_ms=750),)


def test_audio_extract_timeout_is_explicitly_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["ffmpeg"], timeout=1)

    monkeypatch.setattr(preprocess_module, "run_cancellable_process", timeout)

    with pytest.raises(AudioPreprocessTransientError, match="could not be executed"):
        _run_audio_extract(
            source_path=tmp_path / "source.mp4",
            window=ChunkWindow(index=0, start_ms=0, end_ms=1_000),
            temporary_path=tmp_path / ".private.m4a",
            sample_rate_hz=16_000,
            bitrate="48k",
            ffmpeg_path="/system/ffmpeg",
        )


def test_preprocess_checkpoints_and_reuses_hash_verified_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_metadata(tmp_path)
    output_dir = tmp_path / "audio"
    extraction_calls: list[int] = []
    monkeypatch.setattr(
        preprocess_module,
        "detect_silence",
        lambda **_: (SilenceInterval(start_ms=5_000, end_ms=5_750),),
    )

    def fake_extract(*, window: ChunkWindow, temporary_path: Path, **_: object) -> None:
        extraction_calls.append(window.index)
        temporary_path.write_bytes(f"chunk-{window.index}".encode() * 100)

    monkeypatch.setattr(preprocess_module, "_run_audio_extract", fake_extract)

    first = preprocess_audio(
        source=source,
        output_dir=output_dir,
        chunk_duration_ms=10_000,
        overlap_ms=2_000,
        max_chunk_bytes=1_000_000,
        ffmpeg_path="/system/ffmpeg",
    )

    def unexpected_manifest_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a complete verified checkpoint must remain byte-for-byte stable")

    monkeypatch.setattr(preprocess_module, "_write_manifest_atomic", unexpected_manifest_write)
    second = preprocess_audio(
        source=source,
        output_dir=output_dir,
        chunk_duration_ms=10_000,
        overlap_ms=2_000,
        max_chunk_bytes=1_000_000,
        ffmpeg_path="/system/ffmpeg",
    )

    assert extraction_calls == [0, 1, 2]
    assert first.complete is True and second == first
    assert [chunk.overlap_before_ms for chunk in first.chunks] == [0, 2_000, 2_000]
    assert [chunk.overlap_after_ms for chunk in first.chunks] == [2_000, 2_000, 0]
    assert [chunk.chunk_id for chunk in first.chunks] == [
        "chunk_000000",
        "chunk_000001",
        "chunk_000002",
    ]
    stored = AudioChunkManifest.model_validate_json(
        (output_dir / "chunk-manifest.json").read_text(encoding="utf-8")
    )
    assert stored == first
    assert all(chunk.path.is_file() for chunk in first.chunks)
    assert not list(output_dir.glob("*.tmp-*.m4a"))


def test_cancel_between_chunks_keeps_only_successful_checkpoint_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_metadata(tmp_path)
    output_dir = tmp_path / "audio"
    monkeypatch.setattr(preprocess_module, "detect_silence", lambda **_: ())
    extracted: list[int] = []

    def fake_extract(*, window: ChunkWindow, temporary_path: Path, **_: object) -> None:
        extracted.append(window.index)
        temporary_path.write_bytes(b"valid-audio" * 100)

    monkeypatch.setattr(preprocess_module, "_run_audio_extract", fake_extract)
    checks_after_extract = 0

    def cancel_after_first() -> bool:
        nonlocal checks_after_extract
        if not extracted:
            return False
        checks_after_extract += 1
        return checks_after_extract == 2

    with pytest.raises(AudioPreprocessCancelled, match="cancelled"):
        preprocess_audio(
            source=source,
            output_dir=output_dir,
            chunk_duration_ms=10_000,
            overlap_ms=2_000,
            max_chunk_bytes=1_000_000,
            ffmpeg_path="/system/ffmpeg",
            cancel_requested=cancel_after_first,
        )

    checkpoint = AudioChunkManifest.model_validate_json(
        (output_dir / "chunk-checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint.complete is False
    assert [chunk.index for chunk in checkpoint.chunks] == [0]
    assert not list(output_dir.glob("*.tmp-*.m4a"))

    completed = preprocess_audio(
        source=source,
        output_dir=output_dir,
        chunk_duration_ms=10_000,
        overlap_ms=2_000,
        max_chunk_bytes=1_000_000,
        ffmpeg_path="/system/ffmpeg",
    )
    assert completed.complete is True
    assert extracted == [0, 1, 2]
    assert not (output_dir / "chunk-checkpoint.json").exists()


def test_publication_failure_leaves_recoverable_precheckpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_metadata(tmp_path, duration_ms=5_000)
    output_dir = tmp_path / "audio"
    monkeypatch.setattr(preprocess_module, "detect_silence", lambda **_: ())

    def fake_extract(*, temporary_path: Path, **_: object) -> None:
        temporary_path.write_bytes(b"valid-audio" * 100)

    monkeypatch.setattr(preprocess_module, "_run_audio_extract", fake_extract)
    publication = preprocess_module._publish_no_clobber

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise AudioPreprocessTransientError("injected publication failure")

    monkeypatch.setattr(preprocess_module, "_publish_no_clobber", fail_publication)
    with pytest.raises(AudioPreprocessTransientError, match="injected"):
        preprocess_audio(
            source=source,
            output_dir=output_dir,
            chunk_duration_ms=10_000,
            overlap_ms=2_000,
            max_chunk_bytes=1_000_000,
            ffmpeg_path="/system/ffmpeg",
        )

    checkpoint = AudioChunkManifest.model_validate_json(
        (output_dir / "chunk-checkpoint.json").read_text(encoding="utf-8")
    )
    assert [chunk.index for chunk in checkpoint.chunks] == [0]
    assert not checkpoint.chunks[0].path.exists()
    assert not list(output_dir.glob("*.m4a"))

    monkeypatch.setattr(preprocess_module, "_publish_no_clobber", publication)
    completed = preprocess_audio(
        source=source,
        output_dir=output_dir,
        chunk_duration_ms=10_000,
        overlap_ms=2_000,
        max_chunk_bytes=1_000_000,
        ffmpeg_path="/system/ffmpeg",
    )
    assert completed.complete is True
    assert completed.chunks[0].path.is_file()


def test_resume_rejects_tampered_successful_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_metadata(tmp_path, duration_ms=5_000)
    monkeypatch.setattr(preprocess_module, "detect_silence", lambda **_: ())

    def fake_extract(*, temporary_path: Path, **_: object) -> None:
        temporary_path.write_bytes(b"valid-audio" * 100)

    monkeypatch.setattr(preprocess_module, "_run_audio_extract", fake_extract)
    manifest = preprocess_audio(
        source=source,
        output_dir=tmp_path / "audio",
        chunk_duration_ms=10_000,
        overlap_ms=2_000,
        max_chunk_bytes=1_000_000,
        ffmpeg_path="/system/ffmpeg",
    )
    manifest.chunks[0].path.write_bytes(b"tampered")

    with pytest.raises(AudioPreprocessError, match="hash verification"):
        preprocess_audio(
            source=source,
            output_dir=tmp_path / "audio",
            chunk_duration_ms=10_000,
            overlap_ms=2_000,
            max_chunk_bytes=1_000_000,
            ffmpeg_path="/system/ffmpeg",
        )
    assert manifest.chunks[0].path.read_bytes() == b"tampered"


def test_oversize_partial_chunk_is_never_published_or_checkpointed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_metadata(tmp_path, duration_ms=5_000)
    output_dir = tmp_path / "audio"
    monkeypatch.setattr(preprocess_module, "detect_silence", lambda **_: ())

    def fake_extract(*, temporary_path: Path, **_: object) -> None:
        temporary_path.write_bytes(b"x" * 101)

    monkeypatch.setattr(preprocess_module, "_run_audio_extract", fake_extract)

    with pytest.raises(AudioPreprocessError, match="size limit"):
        preprocess_audio(
            source=source,
            output_dir=output_dir,
            chunk_duration_ms=10_000,
            overlap_ms=2_000,
            max_chunk_bytes=100,
            ffmpeg_path="/system/ffmpeg",
        )

    checkpoint = AudioChunkManifest.model_validate_json(
        (output_dir / "chunk-checkpoint.json").read_text(encoding="utf-8")
    )
    assert checkpoint.chunks == ()
    assert checkpoint.complete is False
    assert not list(output_dir.glob("*.m4a"))


def test_preprocess_refuses_a_source_changed_after_ingest(tmp_path: Path) -> None:
    source = source_metadata(tmp_path, duration_ms=5_000)
    source.resolved_path.write_bytes(b"replacement-media")

    with pytest.raises(AudioPreprocessError, match="changed"):
        preprocess_audio(
            source=source,
            output_dir=tmp_path / "audio",
            chunk_duration_ms=10_000,
            overlap_ms=2_000,
            max_chunk_bytes=1_000_000,
            ffmpeg_path="/system/ffmpeg",
        )


def test_preprocess_rejects_symlinked_output_directory_before_any_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_metadata(tmp_path, duration_ms=5_000)
    outside = tmp_path / "outside"
    outside.mkdir()
    output_dir = tmp_path / "audio"
    output_dir.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        preprocess_module,
        "detect_silence",
        lambda **_: (_ for _ in ()).throw(AssertionError("must fail before FFmpeg")),
    )

    with pytest.raises(AudioPreprocessError, match="symlink-free"):
        preprocess_audio(
            source=source,
            output_dir=output_dir,
            chunk_duration_ms=10_000,
            overlap_ms=2_000,
            max_chunk_bytes=1_000_000,
            ffmpeg_path="/system/ffmpeg",
        )
    assert not list(outside.iterdir())


def test_preprocess_rehash_rejects_same_stat_in_place_source_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = source_metadata(tmp_path, duration_ms=5_000)
    original_stat = source.resolved_path.stat()
    replacement = b"x" * source.size_bytes
    source.resolved_path.write_bytes(replacement)
    os.utime(
        source.resolved_path,
        ns=(original_stat.st_atime_ns, source.mtime_ns),
    )
    assert source.resolved_path.stat().st_ino == source.inode
    assert source.resolved_path.stat().st_mtime_ns == source.mtime_ns
    monkeypatch.setattr(preprocess_module, "detect_silence", lambda **_: ())

    def fake_extract(*, temporary_path: Path, **_: object) -> None:
        temporary_path.write_bytes(b"valid-audio" * 100)

    monkeypatch.setattr(preprocess_module, "_run_audio_extract", fake_extract)
    with pytest.raises(AudioPreprocessError, match="content changed"):
        preprocess_audio(
            source=source,
            output_dir=tmp_path / "audio",
            chunk_duration_ms=10_000,
            overlap_ms=2_000,
            max_chunk_bytes=1_000_000,
            ffmpeg_path="/system/ffmpeg",
        )
    assert not (tmp_path / "audio" / "chunk-manifest.json").exists()


def test_audio_chunk_cache_key_is_stable_and_configuration_bound() -> None:
    window = ChunkWindow(index=0, start_ms=0, end_ms=10_000)
    first = audio_chunk_cache_key(
        source_sha256="a" * 64,
        window=window,
        overlap_ms=2_000,
        sample_rate_hz=16_000,
        bitrate="48k",
    )
    repeated = audio_chunk_cache_key(
        source_sha256="a" * 64,
        window=window,
        overlap_ms=2_000,
        sample_rate_hz=16_000,
        bitrate="48k",
    )
    changed = audio_chunk_cache_key(
        source_sha256="a" * 64,
        window=window,
        overlap_ms=2_000,
        sample_rate_hz=16_000,
        bitrate="64k",
    )

    assert first == repeated
    assert first != changed
    assert len(first) == 64


def test_audio_disk_budget_fails_before_chunk_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    windows = chunk_windows(60_000, chunk_duration_ms=30_000, overlap_ms=0)
    monkeypatch.setattr(
        preprocess_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=1_000),
    )

    with pytest.raises(AudioPreprocessTransientError, match="free local disk"):
        preprocess_module._ensure_audio_disk_budget(
            tmp_path,
            windows=windows,
            bitrate="48k",
        )
