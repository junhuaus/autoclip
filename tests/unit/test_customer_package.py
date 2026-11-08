# ruff: noqa: RUF001
"""Stage 19c: offline customer package (synthetic inputs only)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from liveclip.delivery.customer_package import (
    CustomerDeliveryManifest,
    CustomerPackageClip,
    CustomerPackageError,
    build_customer_manifest,
    build_customer_package,
    customer_download_filename,
    customer_filename_component,
    customer_index_html,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import CustomerText

CREATED_AT = "2026-11-07T12:00:00+00:00"
SRT = "1\r\n00:00:00,000 --> 00:00:02,000\r\n第一句\r\n"
FORBIDDEN_TOKENS = (
    "score",
    "risk",
    "manual_review",
    "review_reason",
    "routed",
    "candidate",
    "prompt",
    "/Users",
    "data/",
    "evaluations",
    "quality",
    "flag",
)
GOLDEN_MANIFEST_KEYS = {
    "schema_version",
    "delivery_version",
    "title",
    "created_at",
    "clip_count",
    "short_count",
    "lesson_count",
    "clips",
}
GOLDEN_CLIP_KEYS = {
    "ordinal",
    "profile",
    "profile_label",
    "title",
    "hook",
    "summary",
    "duration_ms",
    "video_href",
    "subtitle_href",
}


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _clip(
    tmp_path: Path,
    ordinal: int,
    profile: ClipProfile,
    title: str,
    *,
    hook: str = "高光钩子",
    summary: str = "内容摘要",
) -> CustomerPackageClip:
    source = tmp_path / "sources"
    source.mkdir(exist_ok=True)
    video = source / f"{ordinal}.mp4"
    video.write_bytes(f"video-{ordinal}".encode())
    subtitle = source / f"{ordinal}.srt"
    subtitle.write_bytes(SRT.encode())
    return CustomerPackageClip(
        ordinal=ordinal,
        profile=profile,
        text=CustomerText(title=title, hook=hook, summary=summary),
        duration_ms=61_400 if profile is ClipProfile.SHORT_HIGHLIGHT else 125_000,
        video_path=video,
        video_sha256=_sha(video.read_bytes()),
        video_size_bytes=video.stat().st_size,
        subtitle_path=subtitle,
        subtitle_sha256=_sha(subtitle.read_bytes()),
        subtitle_size_bytes=subtitle.stat().st_size,
    )


def _clips(tmp_path: Path) -> tuple[CustomerPackageClip, ...]:
    return (
        _clip(tmp_path, 1, ClipProfile.SHORT_HIGHLIGHT, "气息与共鸣：短片"),
        _clip(
            tmp_path,
            2,
            ClipProfile.MINI_LESSON,
            '<script>alert("x")</script> & 小课',
            hook="钩子 <b>粗体</b> & \"引号\" 'x'",
            summary="第一行\n第二行 <img src=x onerror=alert(1)>",
        ),
    )


def _build(tmp_path: Path, name: str = "project") -> object:
    project_dir = tmp_path / name
    project_dir.mkdir()
    return build_customer_package(
        project_dir=project_dir.resolve(),
        delivery_version="v001",
        title="张老师 · 11 月直播精选",
        created_at=CREATED_AT,
        clips=_clips(tmp_path),
    )


def _all_strings(value: object) -> list[str]:
    if isinstance(value, dict):
        return [*value.keys(), *(text for item in value.values() for text in _all_strings(item))]
    if isinstance(value, list):
        return [text for item in value for text in _all_strings(item)]
    return [str(value)]


def test_package_layout_manifest_keys_and_checksums(tmp_path: Path) -> None:
    result = _build(tmp_path)
    directory = result.directory  # type: ignore[attr-defined]
    names = sorted(
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    )
    assert names == [
        "checksums.sha256",
        "clips/lesson/02-scriptalertxscript-小课.mp4",
        "clips/lesson/02-scriptalertxscript-小课.srt",
        "clips/short/01-气息与共鸣短片.mp4",
        "clips/short/01-气息与共鸣短片.srt",
        "index.html",
        "liveclip-customer-delivery-v001.zip",
        "manifest.json",
    ]
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == GOLDEN_MANIFEST_KEYS
    assert manifest["schema_version"] == "liveclip.customer-delivery.v1"
    assert all(set(clip) == GOLDEN_CLIP_KEYS for clip in manifest["clips"])
    assert [clip["profile_label"] for clip in manifest["clips"]] == ["短片", "小课"]
    assert (directory / "clips/short/01-气息与共鸣短片.srt").read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:02,000\n第一句\n"
    )
    checksums = (directory / "checksums.sha256").read_text(encoding="utf-8").splitlines()
    for line in checksums:
        digest, name = line.split("  ", 1)
        assert _sha((directory / name).read_bytes()) == digest
    assert "liveclip-customer-delivery-v001.zip" not in "".join(checksums)


def test_no_internal_field_reaches_the_customer(tmp_path: Path) -> None:
    result = _build(tmp_path)
    directory = result.directory  # type: ignore[attr-defined]
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    index = (directory / "index.html").read_text(encoding="utf-8")
    with zipfile.ZipFile(directory / "liveclip-customer-delivery-v001.zip") as archive:
        members = archive.namelist()
    haystacks = [*_all_strings(manifest), index, *members]
    for token in FORBIDDEN_TOKENS:
        for text in haystacks:
            assert token not in text.lower(), (token, text[:80])


def test_index_is_offline_escaped_and_ordered(tmp_path: Path) -> None:
    result = _build(tmp_path)
    index = (result.directory / "index.html").read_text(encoding="utf-8")  # type: ignore[attr-defined]
    assert '<html lang="zh-CN">' in index
    assert "default-src 'none'" in index and "media-src 'self' file:" in index
    assert "<script" not in index.lower().replace("&lt;script&gt;", "")
    assert "<track" not in index and "http://" not in index and "https://" not in index
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; 小课" in index
    assert "&lt;img src=x onerror=alert(1)&gt;" in index
    assert "&#x27;x&#x27;" in index
    assert index.index("短片（1）") < index.index("小课（1）")
    assert 'src="clips/short/01-气息与共鸣短片.mp4"' in index
    assert "时长 01:01" in index and "时长 02:05" in index
    assert "本文件夹就是完整的交付包" in index and "下载全部（ZIP）" not in index
    assert index.count('<video controls preload="metadata"') == 2


def test_share_variant_links_the_zip_and_omits_empty_sections(tmp_path: Path) -> None:
    manifest = build_customer_manifest(
        delivery_version="v002",
        title="只有小课",
        created_at=CREATED_AT,
        clips=(_clip(tmp_path, 1, ClipProfile.MINI_LESSON, "唯一小课"),),
    )
    index = customer_index_html(manifest, download_href="/s/token/download")
    assert "短片（" not in index and "小课（1）" in index
    assert 'href="/s/token/download"' in index and "下载全部（ZIP）" in index


def test_zip_members_are_readable_by_the_customer(tmp_path: Path) -> None:
    result = _build(tmp_path)
    archive_path = result.directory / "liveclip-customer-delivery-v001.zip"  # type: ignore[attr-defined]
    with zipfile.ZipFile(archive_path) as archive:
        modes = {info.filename: (info.external_attr >> 16) & 0o777 for info in archive.infolist()}
        stamps = {info.date_time for info in archive.infolist()}
    assert set(modes.values()) == {0o644}
    assert stamps == {(1980, 1, 1, 0, 0, 0)}


def test_same_inputs_build_a_byte_identical_zip(tmp_path: Path) -> None:
    first = _build(tmp_path, "first")
    second = _build(tmp_path, "second")
    assert first.zip_sha256 == second.zip_sha256  # type: ignore[attr-defined]
    assert first.member_sha256 == second.member_sha256  # type: ignore[attr-defined]


def test_rebuilding_a_published_version_reuses_identical_bytes(tmp_path: Path) -> None:
    project_dir = (tmp_path / "project").resolve()
    project_dir.mkdir()
    kwargs = {
        "project_dir": project_dir,
        "delivery_version": "v001",
        "title": "交付",
        "created_at": CREATED_AT,
        "clips": _clips(tmp_path),
    }
    first = build_customer_package(**kwargs)  # type: ignore[arg-type]
    again = build_customer_package(**kwargs)  # type: ignore[arg-type]
    assert again.zip_sha256 == first.zip_sha256
    assert [path.name for path in (project_dir / "customer-deliveries").iterdir()] == ["v001"]
    with pytest.raises(CustomerPackageError, match="differs"):
        build_customer_package(**{**kwargs, "title": "另一个标题"})  # type: ignore[arg-type]


def test_tampered_input_media_is_rejected(tmp_path: Path) -> None:
    clips = _clips(tmp_path)
    clips[0].video_path.write_bytes(b"tampered")
    project_dir = (tmp_path / "project").resolve()
    project_dir.mkdir()
    with pytest.raises(CustomerPackageError):
        build_customer_package(
            project_dir=project_dir,
            delivery_version="v001",
            title="交付",
            created_at=CREATED_AT,
            clips=clips,
        )
    assert list((project_dir / "customer-deliveries").iterdir()) == []


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("气息与共鸣", "气息与共鸣"),
        ("../../etc/passwd", "etcpasswd"),
        ("a/b\\c", "abc"),
        ("换行\n制表\t控制\x07", "换行-制表-控制"),
        ("   ", "clip"),
        ("日本語ひらがな 한국어", "日本語ひらがな-한국어"),
    ],
)
def test_filenames_keep_cjk_and_drop_separators(title: str, expected: str) -> None:
    assert customer_filename_component(title) == expected


def test_download_filename_keeps_chinese() -> None:
    assert customer_download_filename("张老师 精选", "v003") == "张老师-精选-v003.zip"


def test_manifest_rejects_extra_fields_and_inconsistent_counts(tmp_path: Path) -> None:
    manifest = build_customer_manifest(
        delivery_version="v001",
        title="交付",
        created_at=CREATED_AT,
        clips=_clips(tmp_path),
    )
    payload = manifest.model_dump()
    with pytest.raises(ValidationError):
        CustomerDeliveryManifest(**{**payload, "score": 88})
    with pytest.raises(ValidationError):
        CustomerDeliveryManifest(**{**payload, "short_count": 2, "lesson_count": 0})
    with pytest.raises(ValidationError):
        CustomerDeliveryManifest(**{**payload, "clips": tuple(reversed(manifest.clips))})
