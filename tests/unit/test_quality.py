import subprocess
from pathlib import Path

import pytest

import liveclip.renderer.quality as quality_module
from liveclip.renderer.quality import (
    MediaValidationError,
    MediaValidationTransientError,
    _validate_safe_bounds,
    probe_media,
    validate_rendered_media,
)


def test_safe_bounds_accept_known_title_and_caption_regions() -> None:
    assert (
        _validate_safe_bounds(((32, 74, 508, 137), (28, 726, 512, 818)), width=540, height=960)
        == "passed"
    )


def test_safe_bounds_reject_text_near_video_edge(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(MediaValidationError):
        _validate_safe_bounds(((0, 0, 540, 960),), width=540, height=960)


def test_probe_timeout_is_explicitly_transient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["ffprobe"], timeout=1)

    monkeypatch.setattr(quality_module, "run_cancellable_process", timeout)

    with pytest.raises(MediaValidationTransientError, match="could not inspect"):
        probe_media(tmp_path / "render.mp4", ffprobe_path="/system/ffprobe")


@pytest.mark.parametrize(
    ("format_name", "video_codec", "audio_codec", "message"),
    (
        ("matroska,webm", "h264", "aac", "MP4 container"),
        ("mov,mp4,m4a,3gp,3g2,mj2", "hevc", "aac", "H.264 video"),
        ("mov,mp4,m4a,3gp,3g2,mj2", "h264", "mp3", "H.264 video"),
    ),
)
def test_quality_rejects_wrong_container_or_codec_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_name: str,
    video_codec: str,
    audio_codec: str,
    message: str,
) -> None:
    media_path = tmp_path / "temporary.mp4"
    media_path.write_bytes(b"not-a-real-render" * 1_000)
    probe = {
        "streams": [
            {"codec_type": "video", "codec_name": video_codec, "width": 540, "height": 960},
            {"codec_type": "audio", "codec_name": audio_codec},
        ],
        "format": {"format_name": format_name, "duration": "4.000"},
    }
    monkeypatch.setattr(quality_module, "probe_media", lambda *_args, **_kwargs: probe)

    with pytest.raises(MediaValidationError, match=message):
        validate_rendered_media(
            media_path=media_path,
            expected_width=540,
            expected_height=960,
            expected_duration_ms=4_000,
            output_dir=tmp_path / "quality",
        )
