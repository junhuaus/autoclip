"""Build and extract one synthetic customer package for the file:// browser test.

Usage: python tests/support/build_customer_package_fixture.py <empty output dir>
Prints the absolute path of the extracted ``index.html``.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

from liveclip.delivery.customer_package import CustomerPackageClip, build_customer_package
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import CustomerText

SRT = "1\n00:00:00,000 --> 00:00:02,000\n示例字幕\n"


def _clip(root: Path, ordinal: int, profile: ClipProfile, title: str) -> CustomerPackageClip:
    video = root / f"source-{ordinal}.mp4"
    video.write_bytes(f"synthetic-video-{ordinal}".encode())
    subtitle = root / f"source-{ordinal}.srt"
    subtitle.write_text(SRT, encoding="utf-8")
    return CustomerPackageClip(
        ordinal=ordinal,
        profile=profile,
        text=CustomerText(title=title, hook=f"{title}的钩子", summary=f"{title}的摘要"),
        duration_ms=60_000 * ordinal,
        video_path=video,
        video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
        video_size_bytes=video.stat().st_size,
        subtitle_path=subtitle,
        subtitle_sha256=hashlib.sha256(subtitle.read_bytes()).hexdigest(),
        subtitle_size_bytes=subtitle.stat().st_size,
    )


def main(output: Path) -> Path:
    output = output.resolve()
    sources = output / "sources"
    project = output / "project"
    extracted = output / "extracted"
    for directory in (sources, project, extracted):
        directory.mkdir(parents=True)
    result = build_customer_package(
        project_dir=project,
        delivery_version="v001",
        title="离线交付测试",
        created_at="2026-11-07T12:00:00+00:00",
        clips=(
            _clip(sources, 1, ClipProfile.SHORT_HIGHLIGHT, "短片一"),
            _clip(sources, 2, ClipProfile.SHORT_HIGHLIGHT, "短片二"),
            _clip(sources, 3, ClipProfile.MINI_LESSON, "小课一"),
        ),
    )
    with zipfile.ZipFile(result.directory / result.zip_name) as archive:
        archive.extractall(extracted)
    return extracted / "index.html"


if __name__ == "__main__":
    print(main(Path(sys.argv[1])))
