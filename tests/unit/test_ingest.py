from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, BinaryIO

import pytest

import liveclip.media.ingest as ingest_module
from liveclip.media.fingerprint import stream_sha256
from liveclip.media.ingest import (
    MediaIngestError,
    MediaIngestTransientError,
    ingest_source,
    parse_ffprobe_metadata,
    resolve_allowed_source,
    run_ffprobe,
)


def ffprobe_payload() -> dict[str, Any]:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "duration": "12.345",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "duration": "12.340",
            },
        ],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "12.345"},
    }


def test_allowed_source_uses_real_component_ancestry(tmp_path: Path) -> None:
    allowed = tmp_path / "media"
    allowed.mkdir()
    source = allowed / "show.mp4"
    source.write_bytes(b"source")

    assert resolve_allowed_source(source, [allowed]) == source.resolve()

    prefix_escape = tmp_path / "media-escape"
    prefix_escape.mkdir()
    outside = prefix_escape / "show.mp4"
    outside.write_bytes(b"outside")
    with pytest.raises(MediaIngestError, match="outside"):
        resolve_allowed_source(outside, [allowed])


def test_allowed_source_rejects_parent_traversal_before_resolution(tmp_path: Path) -> None:
    allowed = tmp_path / "media"
    nested = allowed / "nested"
    nested.mkdir(parents=True)
    source = allowed / "show.mp4"
    source.write_bytes(b"source")
    traversing = Path(f"{nested}/../show.mp4")

    with pytest.raises(MediaIngestError, match="parent traversal"):
        resolve_allowed_source(traversing, [allowed])


def test_allowed_source_rejects_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "media"
    outside = tmp_path / "private"
    allowed.mkdir()
    outside.mkdir()
    target = outside / "show.mp4"
    target.write_bytes(b"outside")
    link = allowed / "linked.mp4"
    try:
        link.symlink_to(target)
    except OSError as exc:  # pragma: no cover - platform capability guard
        pytest.skip(f"symlink creation is unavailable: {exc.__class__.__name__}")

    with pytest.raises(MediaIngestError, match="outside"):
        resolve_allowed_source(link, [allowed])


def test_allowed_source_requires_absolute_regular_file(tmp_path: Path) -> None:
    with pytest.raises(MediaIngestError, match="absolute"):
        resolve_allowed_source(Path("relative.mp4"), [tmp_path])
    with pytest.raises(MediaIngestError, match="regular file"):
        resolve_allowed_source(tmp_path, [tmp_path])
    with pytest.raises(MediaIngestError, match="no allowed"):
        resolve_allowed_source(tmp_path / "missing.mp4", [])


def test_stream_sha256_reads_in_bounded_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large.bin"
    content = bytes(range(251)) * 300
    source.write_bytes(content)
    real_open = Path.open
    requested_sizes: list[int] = []

    class TrackingReader:
        def __init__(self, wrapped: BinaryIO) -> None:
            self.wrapped = wrapped

        def __enter__(self) -> TrackingReader:
            return self

        def __exit__(self, *_: object) -> None:
            self.wrapped.close()

        def read(self, size: int = -1) -> bytes:
            requested_sizes.append(size)
            return self.wrapped.read(size)

    def tracking_open(path: Path, *args: Any, **kwargs: Any) -> TrackingReader:
        return TrackingReader(real_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", tracking_open)

    digest = stream_sha256(source, block_size=4096)

    assert digest == hashlib.sha256(content).hexdigest()
    assert len(requested_sizes) > 2
    assert set(requested_sizes) == {4096}


def test_parse_ffprobe_metadata_returns_strict_json_serializable_contract(
    tmp_path: Path,
) -> None:
    source = (tmp_path / "show.mp4").resolve()
    metadata = parse_ffprobe_metadata(
        ffprobe_payload(),
        resolved_path=source,
        size_bytes=123_456,
        sha256="a" * 64,
        mtime_ns=987_654,
        inode=42,
        device=7,
    )

    assert metadata.duration_ms == 12_345
    assert metadata.video_codec == "h264"
    assert (metadata.video_width, metadata.video_height) == (1920, 1080)
    assert metadata.video_frame_rate == pytest.approx(29.97002997)
    assert (metadata.audio_codec, metadata.audio_sample_rate_hz, metadata.audio_channels) == (
        "aac",
        48_000,
        2,
    )
    assert json.loads(metadata.model_dump_json())["resolved_path"] == str(source)


def test_parse_ffprobe_requires_audio_video_and_valid_duration(tmp_path: Path) -> None:
    payload = ffprobe_payload()
    payload["streams"] = [payload["streams"][0]]
    with pytest.raises(MediaIngestError, match="video and audio"):
        parse_ffprobe_metadata(
            payload,
            resolved_path=(tmp_path / "show.mp4").resolve(),
            size_bytes=1,
            sha256="b" * 64,
            mtime_ns=1,
            inode=None,
            device=None,
        )

    payload = ffprobe_payload()
    payload["format"]["duration"] = "nan"
    for stream in payload["streams"]:
        stream.pop("duration", None)
    with pytest.raises(MediaIngestError, match="duration"):
        parse_ffprobe_metadata(
            payload,
            resolved_path=(tmp_path / "show.mp4").resolve(),
            size_bytes=1,
            sha256="b" * 64,
            mtime_ns=1,
            inode=None,
            device=None,
        )


def test_ffprobe_invocation_is_argv_with_shell_disabled_and_redacted_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "sensitive-filename.mp4"
    observed: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed.update(kwargs)
        return subprocess.CompletedProcess(argv, 1, "", "private command and path detail")

    monkeypatch.setattr(ingest_module.subprocess, "run", fake_run)

    with pytest.raises(MediaIngestError) as caught:
        run_ffprobe(source, ffprobe_path="/system/ffprobe")

    assert isinstance(observed["argv"], list)
    assert observed["shell"] is False
    assert source.as_posix() not in str(caught.value)
    assert "private command" not in str(caught.value)


def test_ffprobe_timeout_is_explicitly_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["ffprobe"], timeout=1)

    monkeypatch.setattr(ingest_module.subprocess, "run", timeout)

    with pytest.raises(MediaIngestTransientError, match="could not inspect"):
        run_ffprobe(tmp_path / "source.mp4", ffprobe_path="/system/ffprobe")


def test_ingest_source_combines_validation_stream_hash_probe_and_mutation_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "show.mp4"
    content = b"stable-source-media"
    source.write_bytes(content)
    monkeypatch.setattr(ingest_module, "run_ffprobe", lambda *_args, **_kwargs: ffprobe_payload())

    metadata = ingest_source(source, allowed_roots=[tmp_path])

    assert metadata.resolved_path == source.resolve()
    assert metadata.sha256 == hashlib.sha256(content).hexdigest()
    assert metadata.size_bytes == len(content)

    def mutating_probe(path: Path, **_: object) -> dict[str, Any]:
        path.write_bytes(b"changed-during-probe")
        return ffprobe_payload()

    monkeypatch.setattr(ingest_module, "run_ffprobe", mutating_probe)
    source.write_bytes(content)
    with pytest.raises(MediaIngestError, match="changed"):
        ingest_source(source, allowed_roots=[tmp_path])
