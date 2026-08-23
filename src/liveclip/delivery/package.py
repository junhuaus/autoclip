from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import re
import stat
import unicodedata
import uuid
import zipfile
from collections.abc import Iterable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.keywords import KeywordOccurrence, KeywordTimingPrecision
from liveclip.domain.time import ms_to_srt
from liveclip.media.secure_files import (
    PinnedFileEvidence,
    SecureFileError,
    SecureFileHashMismatch,
    capture_pinned_file_evidence,
    create_directory_exclusive_no_follow,
    create_pinned_regular_file_no_follow,
    ensure_directory_no_follow,
    open_pinned_regular_file,
    publish_directory_no_replace_no_follow,
    publish_regular_file_immutable_no_follow,
    remove_tree_no_follow,
    write_bytes_immutable_no_follow,
    write_text_immutable_no_follow,
)


class DeliveryError(RuntimeError):
    pass


class DeliveryClipInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    edit_plan_revision: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=40)
    hook: str = Field(default="", max_length=500)
    reason: str = Field(default="", max_length=1_000)
    risk_flags: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    keywords: tuple[KeywordOccurrence, ...] = Field(default_factory=tuple, max_length=6)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0, le=100)
    review_status: str = Field(pattern=r"^(pending_review|approved|rejected)$")
    render_status: str = Field(pattern=r"^(queued|running|succeeded|failed|stale)$")
    final_video_path: Path
    final_video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subtitle_srt: str = Field(min_length=1, max_length=1_000_000)

    @model_validator(mode="after")
    def validate_interval(self) -> DeliveryClipInput:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("delivery clip end must be greater than start")
        return self


class DeliveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    delivery_id: str
    delivery_version: str
    directory: Path
    manifest_path: Path
    zip_path: Path | None
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    zip_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    member_sha256: dict[str, str]
    clip_count: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_member_hashes(self) -> DeliveryResult:
        if self.member_sha256.get("manifest.json") != self.manifest_sha256:
            raise ValueError("delivery manifest hash must match its member evidence")
        if (self.zip_path is None) != (self.zip_sha256 is None):
            raise ValueError("delivery ZIP path and hash must be present together")
        if (
            self.zip_sha256 is not None
            and self.member_sha256.get("delivery.zip") != self.zip_sha256
        ):
            raise ValueError("delivery ZIP hash must match its member evidence")
        for name, sha256 in self.member_sha256.items():
            validate_zip_members((name,))
            if not re.fullmatch(r"[a-f0-9]{64}", sha256):
                raise ValueError("delivery member hash must be lowercase SHA-256")
        return self


def create_delivery(
    *,
    project_dir: Path,
    project_id: str,
    source_filename: str,
    source_fingerprint: str,
    clips: Sequence[DeliveryClipInput],
    include_zip: bool,
    expected_version: int | None = None,
    delivery_id: str | None = None,
    snapshot_fingerprint: str | None = None,
    created_at: datetime | None = None,
) -> DeliveryResult:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise DeliveryError("project ID is invalid")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", source_fingerprint):
        raise DeliveryError("source fingerprint must be SHA-256")
    if expected_version is not None and not 1 <= expected_version <= 999:
        raise DeliveryError("delivery version must be between 1 and 999")
    if delivery_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", delivery_id):
        raise DeliveryError("delivery ID is invalid")
    if snapshot_fingerprint is not None and not re.fullmatch(r"[a-f0-9]{64}", snapshot_fingerprint):
        raise DeliveryError("delivery snapshot fingerprint is invalid")
    approved = tuple(clip for clip in clips if clip.review_status == "approved")
    if not approved:
        raise DeliveryError("delivery requires at least one approved clip")
    _validate_eligible_clips(approved)

    try:
        resolved_project = ensure_directory_no_follow(project_dir)
        deliveries_dir = ensure_directory_no_follow(resolved_project / "deliveries")
    except SecureFileError as exc:
        raise DeliveryError("delivery directory is not symlink-free") from exc
    lock_path = deliveries_dir / ".delivery.lock"
    try:
        write_bytes_immutable_no_follow(
            lock_path,
            b"LiveClip delivery lock\n",
            max_bytes=64,
        )
        lock_file = open_pinned_regular_file(lock_path)
    except SecureFileError as exc:
        raise DeliveryError("delivery lock could not be opened safely") from exc
    with lock_file:
        fcntl.flock(lock_file.descriptor, fcntl.LOCK_EX)
        version_number = expected_version or _next_delivery_version(deliveries_dir)
        version = f"v{version_number:03d}"
        destination = deliveries_dir / version
        temporary = deliveries_dir / f".{version}-attempt-{uuid.uuid4().hex}"
        try:
            temporary_identity = create_directory_exclusive_no_follow(temporary)
        except SecureFileError as exc:
            raise DeliveryError("delivery attempt directory could not be created safely") from exc
        try:
            result = _build_delivery(
                temporary=temporary,
                destination=destination,
                delivery_id=delivery_id or f"{project_id}_{version}",
                project_id=project_id,
                version=version,
                source_filename=source_filename,
                source_fingerprint=source_fingerprint.lower(),
                snapshot_fingerprint=snapshot_fingerprint,
                clips=approved,
                include_zip=include_zip,
                created_at=created_at or datetime.now(UTC),
            )
            try:
                with ExitStack() as pinned_stack:
                    pinned_members = _capture_expected_members(
                        root=temporary,
                        expected_sha256=result.member_sha256,
                        stack=pinned_stack,
                    )
                    publish_directory_no_replace_no_follow(
                        temporary,
                        destination,
                        pinned_files=pinned_members,
                    )
            except SecureFileError as exc:
                raise DeliveryError("delivery directory could not be published safely") from exc
        except Exception:
            try:
                remove_tree_no_follow(
                    temporary,
                    required_ancestor=deliveries_dir,
                    expected_identity=temporary_identity,
                )
            except SecureFileError as cleanup_error:
                raise DeliveryError(
                    "delivery attempt could not be cleaned up safely"
                ) from cleanup_error
            raise
        finally:
            fcntl.flock(lock_file.descriptor, fcntl.LOCK_UN)
    return result.model_copy(
        update={
            "directory": destination,
            "manifest_path": destination / "manifest.json",
            "zip_path": destination / "delivery.zip" if include_zip else None,
        }
    )


def _build_delivery(
    *,
    temporary: Path,
    destination: Path,
    delivery_id: str,
    project_id: str,
    version: str,
    source_filename: str,
    source_fingerprint: str,
    snapshot_fingerprint: str | None,
    clips: Sequence[DeliveryClipInput],
    include_zip: bool,
    created_at: datetime,
) -> DeliveryResult:
    clips_dir = temporary / "clips"
    subtitles_dir = temporary / "subtitles"
    try:
        ensure_directory_no_follow(clips_dir)
        ensure_directory_no_follow(subtitles_dir)
    except SecureFileError as exc:
        raise DeliveryError("delivery member directories are not symlink-free") from exc
    manifest_clips: list[dict[str, object]] = []
    archive_members: list[PurePosixPath] = []
    member_sha256: dict[str, str] = {}
    for index, clip in enumerate(clips, start=1):
        stem = f"{index:02d}-{safe_filename_component(clip.title)}"
        video_relative = PurePosixPath("clips") / f"{stem}.mp4"
        subtitle_relative = PurePosixPath("subtitles") / f"{stem}.srt"
        video_target = temporary / Path(*video_relative.parts)
        subtitle_target = temporary / Path(*subtitle_relative.parts)
        video_hash = _copy_no_clobber(
            clip.final_video_path,
            video_target,
            expected_sha256=clip.final_video_sha256,
        )
        normalized_subtitle = normalize_srt(clip.subtitle_srt)
        subtitle_payload = normalized_subtitle.encode("utf-8")
        subtitle_hash = hashlib.sha256(subtitle_payload).hexdigest()
        try:
            write_text_immutable_no_follow(
                subtitle_target,
                normalized_subtitle,
                max_bytes=1_000_000,
            )
        except SecureFileError as exc:
            raise DeliveryError("delivery subtitle could not be published safely") from exc
        manifest_clips.append(
            {
                "clip_id": clip.clip_id,
                "edit_plan_revision": clip.edit_plan_revision,
                "title": clip.title,
                "hook": clip.hook,
                "reason": clip.reason,
                "risk_flags": list(dict.fromkeys(clip.risk_flags)),
                "keywords": [keyword.model_dump(mode="json") for keyword in clip.keywords],
                "video_filename": video_relative.as_posix(),
                "subtitle_filename": subtitle_relative.as_posix(),
                "source_start": round(clip.source_start_ms / 1_000, 3),
                "source_end": round(clip.source_end_ms / 1_000, 3),
                "duration": round((clip.source_end_ms - clip.source_start_ms) / 1_000, 3),
                "score": clip.score,
                "review_status": clip.review_status,
                "sha256": video_hash,
            }
        )
        archive_members.extend((video_relative, subtitle_relative))
        member_sha256[video_relative.as_posix()] = video_hash
        member_sha256[subtitle_relative.as_posix()] = subtitle_hash

    manifest: dict[str, object] = {
        "schema_version": "1",
        "project_id": project_id,
        "delivery_id": delivery_id,
        "delivery_version": version,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "source_filename": _source_basename(source_filename),
        "source_fingerprint": source_fingerprint,
        "clips": manifest_clips,
    }
    if snapshot_fingerprint is not None:
        manifest["snapshot_fingerprint"] = snapshot_fingerprint
    manifest_path = temporary / "manifest.json"
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_sha256 = hashlib.sha256(manifest_payload).hexdigest()
    try:
        write_bytes_immutable_no_follow(
            manifest_path,
            manifest_payload,
            max_bytes=2_000_000,
        )
    except SecureFileError as exc:
        raise DeliveryError("delivery manifest could not be published safely") from exc
    archive_members.append(PurePosixPath("manifest.json"))
    member_sha256["manifest.json"] = manifest_sha256

    index_payload = delivery_index_html(manifest).encode("utf-8")
    index_sha256 = hashlib.sha256(index_payload).hexdigest()
    try:
        write_bytes_immutable_no_follow(
            temporary / "index.html",
            index_payload,
            max_bytes=4_000_000,
        )
    except SecureFileError as exc:
        raise DeliveryError("delivery index could not be published safely") from exc
    archive_members.append(PurePosixPath("index.html"))
    member_sha256["index.html"] = index_sha256

    checksums_payload = delivery_checksums_text(member_sha256).encode("utf-8")
    checksums_sha256 = hashlib.sha256(checksums_payload).hexdigest()
    try:
        write_bytes_immutable_no_follow(
            temporary / "checksums.sha256",
            checksums_payload,
            max_bytes=2_000_000,
        )
    except SecureFileError as exc:
        raise DeliveryError("delivery checksums could not be published safely") from exc
    archive_members.append(PurePosixPath("checksums.sha256"))
    member_sha256["checksums.sha256"] = checksums_sha256
    zip_path: Path | None = None
    zip_sha256: str | None = None
    if include_zip:
        zip_path = temporary / "delivery.zip"
        zip_sha256 = _create_and_verify_zip(
            root=temporary,
            output_path=zip_path,
            members=tuple(archive_members),
            manifest=manifest,
            expected_sha256=member_sha256,
        )
        member_sha256["delivery.zip"] = zip_sha256
    return DeliveryResult(
        delivery_id=delivery_id,
        delivery_version=version,
        directory=destination,
        manifest_path=destination / "manifest.json",
        zip_path=destination / "delivery.zip" if include_zip else None,
        manifest_sha256=manifest_sha256,
        zip_sha256=zip_sha256,
        member_sha256=member_sha256,
        clip_count=len(clips),
    )


def safe_filename_component(value: str, *, maximum_utf8_bytes: int = 72) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    characters: list[str] = []
    previous_dash = False
    for character in normalized:
        category = unicodedata.category(character)
        if character.isspace() or character in {"_", "-"}:
            if characters and not previous_dash:
                characters.append("-")
                previous_dash = True
            continue
        if category[0] in {"L", "M", "N"}:
            characters.append(character)
            previous_dash = False
    candidate = "".join(characters).strip("-.") or "clip"
    bounded: list[str] = []
    byte_count = 0
    for character in candidate:
        encoded_size = len(character.encode("utf-8"))
        if byte_count + encoded_size > maximum_utf8_bytes:
            break
        bounded.append(character)
        byte_count += encoded_size
    return "".join(bounded).rstrip("-.") or "clip"


def delivery_index_html(manifest: dict[str, object]) -> str:
    """Build a deterministic, file-only gallery from trusted manifest structure."""

    raw_clips = manifest.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise DeliveryError("delivery index requires manifest clips")
    cards: list[str] = []
    for ordinal, raw_clip in enumerate(raw_clips, start=1):
        if not isinstance(raw_clip, dict):
            raise DeliveryError("delivery index clip is invalid")
        try:
            title = html.escape(str(raw_clip["title"]), quote=True)
            video = html.escape(str(raw_clip["video_filename"]), quote=True)
            subtitle = html.escape(str(raw_clip["subtitle_filename"]), quote=True)
            score = float(raw_clip["score"])
            duration = float(raw_clip["duration"])
            hook = html.escape(str(raw_clip.get("hook", "")), quote=True)
            reason = html.escape(str(raw_clip.get("reason", "")), quote=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise DeliveryError("delivery index clip fields are invalid") from exc
        if not 0 <= score <= 100 or duration <= 0:
            raise DeliveryError("delivery index numeric fields are invalid")
        raw_keywords = raw_clip.get("keywords", [])
        if not isinstance(raw_keywords, list):
            raise DeliveryError("delivery index keywords are invalid")
        try:
            keywords = tuple(_manifest_keyword(value) for value in raw_keywords)
        except (TypeError, ValueError) as exc:
            raise DeliveryError("delivery index keywords are invalid") from exc
        keyword_html = (
            "".join(
                '<li class="keyword">'
                f"<strong>{html.escape(keyword.text)}</strong>"
                f"<span>片内 {_display_time(keyword.clip_start_ms)}&ndash;"
                f"{_display_time(keyword.clip_end_ms)}</span>"
                "<span>"
                f"{'词级时间' if keyword.timing_precision.value == 'word' else '转写段时间窗'}"
                "</span>"
                f"<span>源 {_display_time(keyword.source_start_ms)}&ndash;"
                f"{_display_time(keyword.source_end_ms)}</span>"
                "</li>"
                for keyword in keywords
            )
            or '<li class="empty">暂无可定位的编辑关键词</li>'
        )
        hook_html = hook or "暂无高光语句"
        reason_html = f'<p class="reason">{reason}</p>' if reason else ""
        cards.append(
            "\n".join(
                (
                    '<article class="clip">',
                    f"<header><span>{ordinal:02d}</span><h2>{title}</h2></header>",
                    f'<video controls preload="metadata" src="{video}">'
                    "浏览器不支持视频播放。</video>",
                    '<div class="content">',
                    '<section class="highlight"><div class="section-title">'
                    "<h3>高光语句</h3><span>推荐上屏</span></div>",
                    f"<blockquote>{hook_html}</blockquote>{reason_html}</section>",
                    '<section class="keywords"><div class="section-title">'
                    "<h3>编辑关键词</h3><span>仅供编辑定位</span></div>",
                    f'<ul aria-label="{title} 编辑关键词">{keyword_html}</ul></section>',
                    '<div class="meta">',
                    f"<span>评分 {score:.1f}</span><span>时长 {duration:.3f} 秒</span>",
                    f'<a href="{video}" download>下载 MP4</a>',
                    f'<a href="{subtitle}" download>下载 SRT</a>',
                    "</div>",
                    "</div>",
                    "</article>",
                )
            )
        )
    project_id = html.escape(str(manifest.get("project_id", "")), quote=True)
    version = html.escape(str(manifest.get("delivery_version", "")), quote=True)
    source = html.escape(str(manifest.get("source_filename", "")), quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'unsafe-inline'; media-src 'self';">
  <title>LiveClip 交付包 {version}</title>
  <style>
    :root {{ color-scheme:dark; font-family:-apple-system, BlinkMacSystemFont,
      "Segoe UI", sans-serif; background:#071416; color:#eef8f6; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; }}
    main {{ width:min(1180px, calc(100% - 32px)); margin:0 auto; padding:40px 0 64px; }}
    .hero {{ margin-bottom:28px; }}
    h1 {{ margin:.25rem 0; font-size:clamp(2rem, 5vw, 3.6rem); }}
    .hero p {{ color:#9ab8b4; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:20px; }}
    .clip {{ overflow:hidden; border:1px solid #244447; border-radius:18px;
      background:#0c2023; box-shadow:0 18px 42px #0006; }}
    .clip header {{ display:flex; gap:12px; align-items:baseline; padding:18px 18px 12px; }}
    .clip header span {{ color:#5ee0c2; font-weight:800; }}
    h2 {{ margin:0; font-size:1.05rem; }}
    video {{ display:block; width:100%; aspect-ratio:9/16; background:#000;
      object-fit:contain; max-height:68vh; }}
    .content {{ padding:16px 18px 18px; }}
    .highlight, .keywords {{ margin-bottom:16px; }}
    .section-title {{ display:flex; align-items:center; justify-content:space-between;
      gap:12px; margin-bottom:8px; }}
    .section-title h3 {{ margin:0; font-size:.92rem; color:#d9efeb; }}
    .section-title span {{ color:#6f9691; font-size:.75rem; }}
    blockquote {{ margin:0; padding:13px 14px; border-left:3px solid #5ee0c2;
      border-radius:8px; background:#102b2e; line-height:1.65; color:#f4fffd; }}
    .reason {{ margin:9px 0 0; color:#9ab8b4; line-height:1.55; font-size:.86rem; }}
    .keywords ul {{ display:flex; flex-wrap:wrap; gap:8px; margin:0; padding:0; list-style:none; }}
    .keyword {{ display:grid; gap:3px; min-width:142px; padding:8px 10px;
      border:1px solid #2c5255; border-radius:10px; background:#10282b; }}
    .keyword strong {{ color:#eafffa; }}
    .keyword span, .empty {{ color:#86aaa5; font-size:.74rem; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center;
      padding:0; color:#a9c4c0; font-size:.9rem; }}
    .meta a {{ color:#071416; background:#5ee0c2; border-radius:999px;
      padding:7px 11px; text-decoration:none; font-weight:750; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <p>LiveClip · 项目 {project_id}</p><h1>交付包 {version}</h1>
      <p>{source} · 已选 {len(cards)} 条</p>
    </section>
    <section class="grid">{" ".join(cards)}</section>
  </main>
</body>
</html>
"""


def _display_time(value_ms: int) -> str:
    return ms_to_srt(value_ms).replace(",", ".")


def _manifest_keyword(value: object) -> KeywordOccurrence:
    if not isinstance(value, dict):
        raise ValueError("keyword must be an object")
    payload = dict(value)
    raw_precision = payload.get("timing_precision")
    if not isinstance(raw_precision, str):
        raise ValueError("keyword timing precision must be text")
    payload["timing_precision"] = KeywordTimingPrecision(raw_precision)
    return KeywordOccurrence.model_validate(payload)


def delivery_checksums_text(member_sha256: dict[str, str]) -> str:
    names = validate_zip_members(member_sha256)
    return "".join(f"{member_sha256[name]}  {name}\n" for name in sorted(names))


def validate_zip_members(names: Iterable[str]) -> tuple[str, ...]:
    checked: list[str] = []
    seen: set[str] = set()
    normalized_seen: set[str] = set()
    for name in names:
        if "\\" in name or "\x00" in name:
            raise DeliveryError("ZIP member uses a backslash")
        if any(unicodedata.category(character).startswith("C") for character in name):
            raise DeliveryError("ZIP member contains a control character")
        if re.match(r"^[A-Za-z]:", name):
            raise DeliveryError("ZIP member uses a drive-qualified path")
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise DeliveryError("ZIP member is not a safe relative path")
        canonical = path.as_posix()
        if canonical != name or canonical in seen:
            raise DeliveryError("ZIP member is non-canonical or duplicated")
        normalized = unicodedata.normalize("NFKC", canonical).casefold()
        if normalized in normalized_seen:
            raise DeliveryError("ZIP member has a Unicode-normalized collision")
        seen.add(canonical)
        normalized_seen.add(normalized)
        checked.append(canonical)
    return tuple(checked)


def validate_zip_infos(
    infos: Iterable[zipfile.ZipInfo],
    *,
    maximum_members: int = 205,
    maximum_member_bytes: int = 512 * 1024 * 1024,
    maximum_total_bytes: int = 10 * 1024 * 1024 * 1024,
) -> tuple[str, ...]:
    values = tuple(infos)
    if not values or len(values) > maximum_members:
        raise DeliveryError("ZIP member count is outside its resource budget")
    names = validate_zip_members(info.filename for info in values)
    total = 0
    for info in values:
        unix_mode = info.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        if info.is_dir() or file_type not in {0, stat.S_IFREG}:
            raise DeliveryError("ZIP contains a non-regular member")
        if info.flag_bits & 0x1:
            raise DeliveryError("ZIP contains an encrypted member")
        if info.file_size < 0 or info.file_size > maximum_member_bytes:
            raise DeliveryError("ZIP member exceeds its size budget")
        total += info.file_size
        if total > maximum_total_bytes:
            raise DeliveryError("ZIP uncompressed size exceeds its resource budget")
        if (
            info.file_size > 1024 * 1024
            and info.compress_size > 0
            and info.file_size / info.compress_size > 1_000
        ):
            raise DeliveryError("ZIP member compression ratio is unsafe")
    return names


def read_zip_member_bounded(
    archive: zipfile.ZipFile,
    name: str,
    *,
    maximum_bytes: int,
) -> bytes:
    if maximum_bytes <= 0:
        raise ValueError("ZIP read limit must be positive")
    with archive.open(name, mode="r") as source:
        payload = source.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        raise DeliveryError("ZIP member exceeds its bounded read limit")
    return payload


def hash_zip_member(archive: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with archive.open(name, mode="r") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _validate_eligible_clips(clips: Sequence[DeliveryClipInput]) -> None:
    identifiers: set[str] = set()
    for clip in clips:
        if clip.clip_id in identifiers:
            raise DeliveryError("delivery clip IDs must be unique")
        identifiers.add(clip.clip_id)
        if clip.render_revision != clip.edit_plan_revision:
            raise DeliveryError("approved clip has a stale final render")
        if clip.render_status != "succeeded":
            raise DeliveryError("approved clip final render is not succeeded")
        if not clip.final_video_sha256:
            raise DeliveryError("approved clip final render hash is missing")


def _next_delivery_version(deliveries_dir: Path) -> int:
    existing: list[int] = []
    for child in deliveries_dir.iterdir():
        match = re.fullmatch(r"v(\d{3})", child.name)
        if match is None:
            continue
        if child.is_symlink() or not child.is_dir():
            raise DeliveryError("delivery version entry is not a safe directory")
        existing.append(int(match.group(1)))
    value = max(existing, default=0) + 1
    if value > 999:
        raise DeliveryError("delivery version space is exhausted")
    return value


def _copy_no_clobber(source: Path, destination: Path, *, expected_sha256: str) -> str:
    try:
        observed = publish_regular_file_immutable_no_follow(
            source,
            destination,
            remove_source=False,
            expected_sha256=expected_sha256,
        )
    except SecureFileHashMismatch as exc:
        raise DeliveryError("delivery source video differs from its committed hash") from exc
    except SecureFileError as exc:
        raise DeliveryError("delivery video could not be copied safely") from exc
    if observed != expected_sha256:  # pragma: no cover - enforced by the secure primitive
        raise DeliveryError("delivery source video differs from its committed hash")
    return observed


def normalize_srt(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in normalized or "-->" not in normalized:
        raise DeliveryError("subtitle content is not a valid bounded SRT payload")
    return normalized + "\n"


def copy_immutable_member(source: Path, destination: Path, *, expected_sha256: str) -> str:
    """Copy one committed input without following links or replacing a destination."""

    return _copy_no_clobber(source, destination, expected_sha256=expected_sha256)


def source_basename(value: str) -> str:
    """Return a platform-neutral source basename for package metadata."""

    return _source_basename(value)


def create_verified_zip(
    *,
    root: Path,
    output_path: Path,
    members: tuple[PurePosixPath, ...],
    manifest: dict[str, object],
    expected_sha256: dict[str, str],
) -> str:
    """Stream pinned package members into a verified immutable ZIP."""

    return _create_and_verify_zip(
        root=root,
        output_path=output_path,
        members=members,
        manifest=manifest,
        expected_sha256=expected_sha256,
    )


def _source_basename(value: str) -> str:
    normalized = value.replace("\\", "/")
    name = PurePosixPath(normalized).name
    return name or "source-media"


def _create_and_verify_zip(
    *,
    root: Path,
    output_path: Path,
    members: tuple[PurePosixPath, ...],
    manifest: dict[str, object],
    expected_sha256: dict[str, str],
) -> str:
    names = validate_zip_members(member.as_posix() for member in members)
    if set(names) != set(expected_sha256):
        raise DeliveryError("ZIP members differ from their expected hashes")
    try:
        with ExitStack() as stack:
            pinned_members = _capture_expected_members(
                root=root,
                expected_sha256=expected_sha256,
                stack=stack,
            )
            output = stack.enter_context(create_pinned_regular_file_no_follow(output_path))
            with (
                os.fdopen(os.dup(output.descriptor), mode="w+b") as output_stream,
                zipfile.ZipFile(
                    output_stream,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as archive,
            ):
                for name in names:
                    _write_pinned_zip_member(archive, name, pinned_members[name])
            output.seal_after_write()
            zip_sha256 = output.sha256()
            verify_pinned_zip_members(
                PinnedFileEvidence(
                    pinned=output,
                    sha256=zip_sha256,
                    size_bytes=output.metadata.st_size,
                ),
                expected_sha256=expected_sha256,
                expected_manifest=manifest,
                expected_sizes={name: value.size_bytes for name, value in pinned_members.items()},
            )
            return zip_sha256
    except SecureFileError as exc:
        raise DeliveryError("ZIP could not be created from stable local members") from exc


def _capture_expected_members(
    *,
    root: Path,
    expected_sha256: dict[str, str],
    stack: ExitStack,
) -> dict[str, PinnedFileEvidence]:
    names = validate_zip_members(expected_sha256)
    pinned: dict[str, PinnedFileEvidence] = {}
    for name in names:
        relative = PurePosixPath(name)
        path = root / Path(*relative.parts)
        try:
            evidence = capture_pinned_file_evidence(
                path,
                expected_sha256=expected_sha256[name],
            )
        except SecureFileError as exc:
            raise DeliveryError("delivery member differs from its expected bytes") from exc
        stack.callback(evidence.pinned.close)
        pinned[name] = evidence
    return pinned


def _write_pinned_zip_member(
    archive: zipfile.ZipFile,
    name: str,
    evidence: PinnedFileEvidence,
) -> None:
    info = zipfile.ZipInfo(filename=name)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    digest = hashlib.sha256()
    offset = 0
    with archive.open(info, mode="w", force_zip64=True) as writer:
        while offset < evidence.size_bytes:
            block = os.pread(
                evidence.pinned.descriptor,
                min(1024 * 1024, evidence.size_bytes - offset),
                offset,
            )
            if not block:
                break
            writer.write(block)
            digest.update(block)
            offset += len(block)
    if offset != evidence.size_bytes or digest.hexdigest() != evidence.sha256:
        raise DeliveryError("ZIP member changed while streaming from its pinned source")
    evidence.pinned.validate_binding()


def verify_pinned_zip_members(
    zip_evidence: PinnedFileEvidence,
    *,
    expected_sha256: dict[str, str],
    expected_manifest: dict[str, object],
    expected_sizes: dict[str, int] | None = None,
) -> None:
    """Verify every ZIP member from a held archive FD against exact hashes."""

    names = validate_zip_members(expected_sha256)
    try:
        with (
            os.fdopen(os.dup(zip_evidence.pinned.descriptor), mode="rb") as input_stream,
            zipfile.ZipFile(input_stream, mode="r") as archive,
        ):
            infos = archive.infolist()
            actual_names = validate_zip_infos(infos)
            if set(actual_names) != set(names):
                raise DeliveryError("ZIP member list changed during creation")
            info_by_name = {info.filename: info for info in infos}
            for name in names:
                if expected_sizes is not None and (
                    info_by_name[name].file_size != expected_sizes[name]
                ):
                    raise DeliveryError("ZIP member size differs from its pinned source")
                if hash_zip_member(archive, name) != expected_sha256[name]:
                    raise DeliveryError("ZIP member hash differs from its pinned source")
            archived_manifest = json.loads(
                read_zip_member_bounded(
                    archive,
                    "manifest.json",
                    maximum_bytes=2_000_000,
                )
            )
            if archived_manifest != expected_manifest:
                raise DeliveryError("ZIP manifest differs from the verified manifest")
        zip_evidence.pinned.validate_binding()
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        raise DeliveryError("ZIP is not a stable valid delivery archive") from exc
