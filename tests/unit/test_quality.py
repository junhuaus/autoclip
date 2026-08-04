import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

import liveclip.renderer.quality as quality_module
from liveclip.renderer.quality import (
    FrameMetric,
    MediaValidationError,
    MediaValidationTransientError,
    QualityCommandDiagnostic,
    QualityReport,
    _validate_safe_bounds,
    create_contact_sheet,
    full_decode,
    probe_media,
    record_visual_inspection,
    validate_rendered_media,
    write_quality_report,
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


def test_probe_timeout_persists_bounded_path_free_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records: list[QualityCommandDiagnostic] = []

    def timeout(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            argv,
            timeout=1,
            stderr="file:///opt/liveclip/secret source.mp4 sk-super-secret-value",
        )

    monkeypatch.setattr(quality_module, "run_cancellable_process", timeout)

    with pytest.raises(MediaValidationTransientError):
        probe_media(
            tmp_path / "render.mp4",
            ffprobe_path="/system/ffprobe",
            diagnostic_records=records,
        )

    assert len(records) == 1
    assert records[0].outcome == "timeout"
    assert records[0].operation == "ffprobe"
    assert str(tmp_path) not in " ".join(records[0].logical_argv)
    assert "/opt" not in records[0].stderr_tail
    assert "secret source.mp4" not in records[0].stderr_tail
    assert "sk-super-secret-value" not in records[0].stderr_tail


def test_full_decode_nonzero_records_safe_process_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records: list[QualityCommandDiagnostic] = []

    def fail(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "/opt/liveclip/private.mp4 failed")

    monkeypatch.setattr(quality_module, "run_cancellable_process", fail)

    with pytest.raises(MediaValidationError, match="decode failed"):
        full_decode(
            tmp_path / "render.mp4",
            ffmpeg_path="/system/ffmpeg",
            diagnostic_records=records,
        )

    assert len(records) == 1
    assert records[0].outcome == "process_failed"
    assert records[0].exit_code == 1
    assert "/opt" not in records[0].stderr_tail


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


def test_quality_validation_pins_one_media_inode_and_reports_its_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "render.mp4"
    media_bytes = b"validated-media" * 1_000
    media_path.write_bytes(media_bytes)
    inherited: list[tuple[Path, tuple[int, ...], Path | None]] = []
    probe = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 540, "height": 960},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"format_name": "mov,mp4", "duration": "4.000"},
    }

    def fake_probe(path: Path, **kwargs: object) -> dict[str, object]:
        inherited.append(
            (
                path,
                kwargs["pass_fds"],  # type: ignore[arg-type]
                kwargs["logical_media_path"],  # type: ignore[arg-type]
            )
        )
        return probe

    def fake_decode(path: Path, **kwargs: object) -> None:
        inherited.append(
            (
                path,
                kwargs["pass_fds"],  # type: ignore[arg-type]
                kwargs["logical_media_path"],  # type: ignore[arg-type]
            )
        )

    def fake_frames(*, media_path: Path, output_dir: Path, **kwargs: object) -> tuple:
        inherited.append(
            (
                media_path,
                kwargs["pass_fds"],  # type: ignore[arg-type]
                kwargs["logical_media_path"],  # type: ignore[arg-type]
            )
        )
        output_dir.mkdir(parents=True)
        values = []
        for index, timestamp in enumerate((400, 2_000, 3_600)):
            path = output_dir / f"frame-{index}.png"
            Image.new("RGB", (32, 48), (20 + index * 40, 80, 160)).save(path)
            values.append((path, timestamp))
        return tuple(values)

    monkeypatch.setattr(quality_module, "probe_media", fake_probe)
    monkeypatch.setattr(quality_module, "full_decode", fake_decode)
    monkeypatch.setattr(quality_module, "extract_representative_frames", fake_frames)
    monkeypatch.setattr(
        quality_module,
        "_frame_metric",
        lambda path, timestamp: FrameMetric(
            filename=path.name,
            timestamp_ms=timestamp,
            mean_luma=100,
            luma_variance=100,
            edge_blank_sides=(),
            edge_to_center_variance_ratio=1,
        ),
    )

    report = validate_rendered_media(
        media_path=media_path,
        expected_width=540,
        expected_height=960,
        expected_duration_ms=4_000,
        output_dir=tmp_path / "quality",
    )

    assert report.media_sha256 == hashlib.sha256(media_bytes).hexdigest()
    assert len(inherited) == 3
    assert len({path for path, _fds, _logical in inherited}) == 1
    assert str(inherited[0][0]).startswith("/dev/fd/")
    assert all(fds == inherited[0][1] and logical == media_path for _, fds, logical in inherited)


def test_quality_validation_rejects_endpoint_replacement_after_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "render.mp4"
    original = b"original-media" * 1_100
    replacement = b"replaced-media" * 1_100
    media_path.write_bytes(original)
    frame_values = []
    for index, timestamp in enumerate((400, 2_000, 3_600)):
        frame = tmp_path / f"replacement-frame-{index}.png"
        Image.new("RGB", (32, 48), (40 + index * 30, 90, 150)).save(frame)
        frame_values.append((frame, timestamp))
    probe = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 540, "height": 960},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"format_name": "mov,mp4", "duration": "4.000"},
    }

    def replace_after_probe(*_args: object, **_kwargs: object) -> dict[str, object]:
        old = tmp_path / "old-render.mp4"
        media_path.rename(old)
        media_path.write_bytes(replacement)
        return probe

    monkeypatch.setattr(quality_module, "probe_media", replace_after_probe)
    monkeypatch.setattr(quality_module, "full_decode", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        quality_module,
        "extract_representative_frames",
        lambda **_kwargs: tuple(frame_values),
    )
    monkeypatch.setattr(
        quality_module,
        "_frame_metric",
        lambda path, timestamp: FrameMetric(
            filename=path.name,
            timestamp_ms=timestamp,
            mean_luma=100,
            luma_variance=100,
            edge_blank_sides=(),
            edge_to_center_variance_ratio=1,
        ),
    )

    with pytest.raises(MediaValidationError, match="changed during quality validation"):
        validate_rendered_media(
            media_path=media_path,
            expected_width=540,
            expected_height=960,
            expected_duration_ms=4_000,
            output_dir=tmp_path / "quality",
        )


def test_contact_sheet_refuses_symbolic_link_output_endpoint(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (32, 48), "blue").save(frame)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside-must-remain-unchanged")
    output = tmp_path / "contact-sheet.png"
    output.symlink_to(outside)

    with pytest.raises(MediaValidationError, match="published safely"):
        create_contact_sheet(frames=((frame, 0),), output_path=output)

    assert outside.read_bytes() == b"outside-must-remain-unchanged"


def test_quality_report_publication_and_visual_update_reject_symbolic_links(
    tmp_path: Path,
) -> None:
    report = QualityReport(
        schema_version="1",
        media_path="<local-media>",
        media_sha256="a" * 64,
        expected_width=540,
        expected_height=960,
        actual_width=540,
        actual_height=960,
        expected_duration_ms=1_000,
        actual_duration_ms=1_000,
        file_size=10_000,
        container_format="mp4",
        video_codec="h264",
        audio_codec="aac",
        full_decode="passed",
        safe_area_check="passed",
        black_frame_check="passed",
        edge_and_crop_check="passed",
        frame_metrics=(),
        contact_sheet="contact-sheet.png",
        automatic_status="passed",
        visual_inspection_status="pending",
        visual_inspection_notes="pending",
        visual_inspection_at=None,
    )
    path = tmp_path / "quality-report.json"
    write_quality_report(report, path)
    record_visual_inspection(report_path=path, notes="人工检查通过")
    assert json.loads(path.read_text(encoding="utf-8"))["visual_inspection_status"] == (
        "viewed_passed"
    )

    outside = tmp_path / "outside.json"
    outside.write_text('{"safe": true}\n', encoding="utf-8")
    unsafe_path = tmp_path / "unsafe-report.json"
    unsafe_path.symlink_to(outside)
    with pytest.raises(MediaValidationError, match="published safely"):
        write_quality_report(report, unsafe_path)
    with pytest.raises(ValueError, match="read safely"):
        record_visual_inspection(report_path=unsafe_path, notes="must fail")
    assert outside.read_text(encoding="utf-8") == '{"safe": true}\n'
