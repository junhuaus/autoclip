from __future__ import annotations

import math
import shutil
import subprocess
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from liveclip.domain.edit_plan import CaptionCue, CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.media.ingest import ingest_source, run_ffprobe
from liveclip.renderer.quality import full_decode, probe_media
from liveclip.renderer.service import RenderTextMode, render_edit_plan_revision


@pytest.mark.integration
@pytest.mark.parametrize("rotation_degrees", [90, 270])
def test_vfr_display_matrix_ingest_and_proxy_render(
    tmp_path: Path,
    rotation_degrees: int,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is unavailable")
    ffprobe = shutil.which("ffprobe")
    assert ffprobe is not None, "ffprobe is required when ffmpeg is available"

    source_path = tmp_path / f"vfr-rotation-{rotation_degrees}.mp4"
    _create_vfr_rotated_source(
        ffmpeg=ffmpeg,
        output_path=source_path,
        rotation_degrees=rotation_degrees,
    )

    source_probe = run_ffprobe(source_path, ffprobe_path=ffprobe)
    source_video = _stream(source_probe, "video")
    source_audio = _stream(source_probe, "audio")
    assert (source_video["index"], source_audio["index"]) == (0, 1)
    assert (source_video["codec_name"], source_audio["codec_name"]) == ("h264", "aac")
    nominal_rate = Fraction(source_video["r_frame_rate"])
    average_rate = Fraction(source_video["avg_frame_rate"])
    assert nominal_rate != average_rate
    assert nominal_rate == 30
    assert 10 < float(average_rate) < 15
    assert _display_matrix_rotation(source_video) == rotation_degrees

    source = ingest_source(
        source_path,
        allowed_roots=(tmp_path,),
        ffprobe_path=ffprobe,
    )
    assert source.video_stream_index == 0
    assert source.audio_stream_index == 1
    assert source.video_codec == "h264"
    assert source.audio_codec == "aac"
    assert source.video_rotation_degrees == rotation_degrees
    assert (source.video_width, source.video_height) == (320, 180)
    assert (source.display_width, source.display_height) == (180, 320)
    assert 3_900 <= source.duration_ms <= 4_000
    assert math.isclose(
        source.video_frame_rate,
        float(average_rate),
        rel_tol=0,
        abs_tol=1e-12,
    )

    output_path = tmp_path / "renders" / f"proxy-{rotation_degrees}.mp4"
    artifact = render_edit_plan_revision(
        source_path=source.resolved_path,
        revision=_revision(rotation_degrees),
        output_path=output_path,
        width=270,
        height=480,
        encoder="libx264",
        text_mode=RenderTextMode.TITLE_AND_CAPTIONS,
        video_stream_index=source.video_stream_index,
        audio_stream_index=source.audio_stream_index,
    )

    output_probe = probe_media(artifact.output_path, ffprobe_path=ffprobe)
    output_video = _stream(output_probe, "video")
    output_audio = _stream(output_probe, "audio")
    assert (output_video["codec_name"], output_video["width"], output_video["height"]) == (
        "h264",
        270,
        480,
    )
    assert output_audio["codec_name"] == "aac"
    assert artifact.quality.automatic_status == "passed"
    assert artifact.quality.full_decode == "passed"
    assert artifact.quality_report_path.is_file()
    assert artifact.contact_sheet_path.is_file()
    full_decode(artifact.output_path, ffmpeg_path=ffmpeg)


def _create_vfr_rotated_source(
    *,
    ffmpeg: str,
    output_path: Path,
    rotation_degrees: int,
) -> None:
    unrotated_path = output_path.with_name(f"{output_path.stem}-unrotated.mp4")
    _run(
        [
            ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:sample_rate=48000:duration=4",
            "-filter:v",
            "select='if(lt(t,2),not(mod(n,2)),not(mod(n,3)))'",
            "-fps_mode",
            "vfr",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-threads:v",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-shortest",
            str(unrotated_path),
        ],
        timeout_seconds=60,
    )
    _run(
        [
            ffmpeg,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-display_rotation:v:0",
            str(rotation_degrees),
            "-i",
            str(unrotated_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        timeout_seconds=30,
    )
    assert output_path.is_file()


def _run(argv: list[str], *, timeout_seconds: int) -> None:
    result = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        shell=False,
    )
    assert result.returncode == 0, result.stderr[-4_000:]


def _stream(payload: dict[str, Any], stream_type: str) -> dict[str, Any]:
    return next(
        stream
        for stream in payload["streams"]
        if isinstance(stream, dict) and stream.get("codec_type") == stream_type
    )


def _display_matrix_rotation(video_stream: dict[str, Any]) -> int:
    side_data = video_stream.get("side_data_list")
    assert isinstance(side_data, list)
    display_matrix = next(
        item
        for item in side_data
        if isinstance(item, dict) and item.get("side_data_type") == "Display Matrix"
    )
    return round(float(display_matrix["rotation"])) % 360


def _revision(rotation_degrees: int) -> EditPlanRevision:
    return EditPlanRevision(
        clip_id=f"clip_vfr_rotation_{rotation_degrees}",
        revision=1,
        origin=RevisionOrigin.DETERMINISTIC,
        plan=EditPlan(
            candidate_id=f"candidate_vfr_rotation_{rotation_degrees}",
            source_start_ms=0,
            source_end_ms=3_000,
            score=90.0,
            title="可变帧率方向验证",
            hook="帧间隔变化且画面方向正确",
            reason="真实媒体兼容性验证",
            layout=Layout.CENTER_CROP,
            caption_template=CaptionTemplate.CLEAN_ZH_V1,
            effect=Effect.NONE,
            risk_flags=(),
            prompt_version="integration_v1",
            model="deterministic-test",
            degraded=True,
        ),
        captions=(CaptionCue(start_ms=0, end_ms=3_000, text="画面方向正确"),),
        created_at=datetime(2026, 8, 4, tzinfo=UTC),
    )
