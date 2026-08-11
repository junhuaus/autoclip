from __future__ import annotations

import math
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from liveclip.domain.edit_plan import CaptionCue, CaptionTemplate, EditPlan, Effect, Layout
from liveclip.domain.review import EditPlanRevision, RevisionOrigin
from liveclip.media.ingest import ingest_source, run_ffprobe
from liveclip.renderer.quality import full_decode, probe_media
from liveclip.renderer.service import RenderTextMode, render_edit_plan_revision

_MEAN_VOLUME_PATTERN = re.compile(r"mean_volume:\s+(-?inf|-?\d+(?:\.\d+)?) dB")


@pytest.mark.integration
def test_ingest_and_render_use_selected_non_first_media_streams(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is unavailable")
    ffprobe = shutil.which("ffprobe")
    assert ffprobe is not None, "ffprobe is required when ffmpeg is available"

    source_path = tmp_path / "multi-stream-source.mp4"
    _create_multi_stream_source(ffmpeg=ffmpeg, output_path=source_path)
    source_probe = run_ffprobe(source_path, ffprobe_path=ffprobe)
    source_streams = source_probe["streams"]
    assert [stream["index"] for stream in source_streams] == [0, 1, 2, 3]
    assert [
        (stream["index"], stream["disposition"]["default"])
        for stream in source_streams
        if stream["codec_type"] == "video"
    ] == [(0, 0), (1, 1)]
    assert [
        (stream["index"], stream["disposition"]["default"])
        for stream in source_streams
        if stream["codec_type"] == "audio"
    ] == [(2, 0), (3, 1)]

    source = ingest_source(
        source_path,
        allowed_roots=(tmp_path,),
        ffprobe_path=ffprobe,
    )
    assert source.video_stream_index == 1
    assert source.audio_stream_index == 3

    output_path = tmp_path / "renders" / "proxy.mp4"
    artifact = render_edit_plan_revision(
        source_path=source.resolved_path,
        revision=_revision(),
        output_path=output_path,
        width=270,
        height=480,
        encoder="libx264",
        text_mode=RenderTextMode.TITLE_AND_CAPTIONS,
        video_stream_index=source.video_stream_index,
        audio_stream_index=source.audio_stream_index,
    )

    output_probe = probe_media(artifact.output_path, ffprobe_path=ffprobe)
    output_streams = output_probe["streams"]
    video = next(stream for stream in output_streams if stream["codec_type"] == "video")
    audio = next(stream for stream in output_streams if stream["codec_type"] == "audio")
    assert (video["codec_name"], video["width"], video["height"]) == (
        "h264",
        270,
        480,
    )
    assert audio["codec_name"] == "aac"
    assert artifact.quality.automatic_status == "passed"
    assert artifact.quality.full_decode == "passed"
    assert artifact.contact_sheet_path.is_file()
    full_decode(artifact.output_path, ffmpeg_path=ffmpeg)

    silent_source_db = _mean_volume_db(
        ffmpeg=ffmpeg,
        media_path=source_path,
        map_specifier="0:2",
    )
    selected_source_db = _mean_volume_db(
        ffmpeg=ffmpeg,
        media_path=source_path,
        map_specifier="0:3",
    )
    rendered_db = _mean_volume_db(
        ffmpeg=ffmpeg,
        media_path=artifact.output_path,
        map_specifier="0:a:0",
    )
    assert math.isinf(silent_source_db) or silent_source_db < -70
    assert selected_source_db > -35
    assert rendered_db > -35


def _create_multi_stream_source(*, ffmpeg: str, output_path: Path) -> None:
    result = subprocess.run(
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
            "color=c=black:size=320x180:rate=24:duration=4",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=24:duration=4",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=sample_rate=48000:channel_layout=mono:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=4",
            "-map",
            "0:v:0",
            "-map",
            "1:v:0",
            "-map",
            "2:a:0",
            "-map",
            "3:a:0",
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
            "-disposition:v:0",
            "0",
            "-disposition:v:1",
            "default",
            "-disposition:a:0",
            "0",
            "-disposition:a:1",
            "default",
            "-shortest",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )
    assert result.returncode == 0, result.stderr[-4_000:]
    assert output_path.is_file()


def _revision() -> EditPlanRevision:
    return EditPlanRevision(
        clip_id="clip_stream_selection",
        revision=1,
        origin=RevisionOrigin.DETERMINISTIC,
        plan=EditPlan(
            candidate_id="candidate_stream_selection",
            source_start_ms=0,
            source_end_ms=3_000,
            score=90.0,
            title="Selected stream",
            hook="Default streams are selected",
            reason="Integration verification",
            layout=Layout.VERTICAL_BLUR_BACKGROUND,
            caption_template=CaptionTemplate.CLEAN_ZH_V1,
            effect=Effect.NONE,
            risk_flags=(),
            prompt_version="integration_v1",
            model="deterministic-test",
            degraded=True,
        ),
        captions=(CaptionCue(start_ms=0, end_ms=3_000, text="Audible track"),),
        created_at=datetime(2026, 8, 4, tzinfo=UTC),
    )


def _mean_volume_db(*, ffmpeg: str, media_path: Path, map_specifier: str) -> float:
    result = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(media_path),
            "-map",
            map_specifier,
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    assert result.returncode == 0, result.stderr[-4_000:]
    match = _MEAN_VOLUME_PATTERN.search(result.stderr)
    assert match is not None, result.stderr[-4_000:]
    value = match.group(1)
    return -math.inf if value == "-inf" else float(value)
