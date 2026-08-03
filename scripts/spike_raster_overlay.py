from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from liveclip.domain.edit_plan import Effect, Layout
from liveclip.renderer.ffmpeg import RenderRequest, render_clip
from liveclip.renderer.quality import validate_rendered_media
from liveclip.renderer.text import render_caption_overlay, render_title_overlay


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the M0 Chinese raster-overlay spike")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = output_dir / "source.mp4"
    output = output_dir / "vertical-overlay.mp4"
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("ffmpeg and ffprobe are required")
    source_argv = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=660:sample_rate=48000",
        "-t",
        "4",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(source),
    ]
    subprocess.run(source_argv, check=True, shell=False)
    title = render_title_overlay(
        output_path=output_dir / "title.png",
        width=540,
        height=960,
        text="LiveClip 中文标题安全区",
        start_ms=0,
        end_ms=4_000,
    )
    first_caption = render_caption_overlay(
        output_path=output_dir / "caption-1.png",
        width=540,
        height=960,
        text="这是第一句中文字幕，用于验证字体与安全区域。",  # noqa: RUF001
        start_ms=0,
        end_ms=2_000,
    )
    second_caption = render_caption_overlay(
        output_path=output_dir / "caption-2.png",
        width=540,
        height=960,
        text="第二句字幕不会进入 FFmpeg 的可执行语法。",
        start_ms=2_000,
        end_ms=4_000,
    )
    result = render_clip(
        RenderRequest(
            source_path=source,
            output_path=output,
            source_start_ms=0,
            source_end_ms=4_000,
            width=540,
            height=960,
            layout=Layout.VERTICAL_BLUR_BACKGROUND,
            effect=Effect.FADE_IN_OUT,
            overlays=(title, first_caption, second_caption),
            encoder="auto",
        )
    )
    probe = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    quality = validate_rendered_media(
        media_path=output,
        expected_width=540,
        expected_height=960,
        expected_duration_ms=4_000,
        output_dir=output_dir / "quality",
        safe_bounds=(title.safe_bounds, first_caption.safe_bounds, second_caption.safe_bounds),
    )
    payload = {
        "output": str(output),
        "encoder": result.encoder,
        "attempts": result.attempts,
        "probe": json.loads(probe.stdout),
        "contact_sheet": quality.contact_sheet,
        "quality_report": str((output_dir / "quality" / "quality-report.json").resolve()),
        "safe_bounds": {
            "title": title.safe_bounds,
            "caption_1": first_caption.safe_bounds,
            "caption_2": second_caption.safe_bounds,
        },
    }
    report = output_dir / "spike-report.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
