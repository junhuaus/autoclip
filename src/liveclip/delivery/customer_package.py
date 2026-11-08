# ruff: noqa: E501, RUF001
"""Offline customer delivery package for imported dual-profile clips (Stage 19c).

The package is what an end customer (a teacher or streamer) receives: clean
MP4s, separate SRTs, a self-contained ``index.html`` and an allowlisted
``manifest.json``. Every customer-visible field comes from ``CustomerClipView``;
internal review evidence (scores, flags, risks, routing status, review reasons,
candidate IDs, prompt or source hashes, local paths) never enters the package.

``customer_index_html`` is the single page template; the Stage 19d share page
renders the same function with share-scoped links.
"""

from __future__ import annotations

import hashlib
import html
import json
import unicodedata
import uuid
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.delivery.package import (
    DeliveryError,
    copy_immutable_member,
    create_verified_zip,
    delivery_checksums_text,
    normalize_srt,
    safe_filename_component,
    validate_zip_members,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import (
    PROFILE_LABELS,
    CustomerClipView,
    CustomerText,
    customer_clip_view,
)
from liveclip.media.secure_files import (
    PinnedFileEvidence,
    SecureFileError,
    capture_pinned_file_evidence,
    create_directory_exclusive_no_follow,
    directory_identity_no_follow,
    ensure_directory_no_follow,
    hash_regular_file_no_follow,
    publish_directory_no_replace_no_follow,
    read_regular_file_no_follow,
    remove_tree_no_follow,
    write_text_immutable_no_follow,
)

CUSTOMER_MANIFEST_SCHEMA = "liveclip.customer-delivery.v1"
PROFILE_FOLDERS: dict[ClipProfile, Literal["short", "lesson"]] = {
    ClipProfile.SHORT_HIGHLIGHT: "short",
    ClipProfile.MINI_LESSON: "lesson",
}
PROFILE_ORDER = (ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON)
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; media-src 'self' file:; "
    "img-src 'none'; base-uri 'none'; form-action 'none'"
)


class CustomerPackageError(DeliveryError):
    """The customer package could not be built or verified."""


class CustomerPackageCancelled(InterruptedError):
    """The build was cancelled before publication."""


class CustomerDeliveryManifest(BaseModel):
    """The complete, allowlisted customer manifest (``extra="forbid"`` throughout)."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["liveclip.customer-delivery.v1"] = "liveclip.customer-delivery.v1"
    delivery_version: str = Field(pattern=r"^v[0-9]{3}$")
    title: str = Field(min_length=1, max_length=80)
    created_at: str = Field(min_length=10, max_length=40)
    clip_count: int = Field(ge=1)
    short_count: int = Field(ge=0)
    lesson_count: int = Field(ge=0)
    clips: tuple[CustomerClipView, ...] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_manifest(self) -> CustomerDeliveryManifest:
        if self.clip_count != len(self.clips):
            raise ValueError("manifest clip count differs from its clips")
        if [clip.ordinal for clip in self.clips] != list(range(1, len(self.clips) + 1)):
            raise ValueError("manifest ordinals must run 1..n")
        short = sum(clip.profile is ClipProfile.SHORT_HIGHLIGHT for clip in self.clips)
        if (short, len(self.clips) - short) != (self.short_count, self.lesson_count):
            raise ValueError("manifest profile counts differ from its clips")
        orders = [PROFILE_ORDER.index(clip.profile) for clip in self.clips]
        if orders != sorted(orders):
            raise ValueError("manifest clips must list short clips before lessons")
        return self

    def as_json_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class CustomerPackageClip:
    """One snapshot clip, already ordered (profile, then source start, then id)."""

    ordinal: int
    profile: ClipProfile
    text: CustomerText
    duration_ms: int
    video_path: Path
    video_sha256: str
    video_size_bytes: int
    subtitle_path: Path
    subtitle_sha256: str
    subtitle_size_bytes: int


@dataclass(frozen=True, slots=True)
class CustomerPackageResult:
    directory: Path
    directory_identity: tuple[int, int]
    manifest: CustomerDeliveryManifest
    manifest_sha256: str
    manifest_size_bytes: int
    zip_name: str
    zip_sha256: str
    zip_size_bytes: int
    member_sha256: dict[str, str]


def customer_filename_component(title: str) -> str:
    """Filename-safe title that keeps Chinese (and other) letters, marks and digits.

    ``safe_filename_component`` keeps Unicode categories L/M/N, so CJK survives;
    separators, punctuation, control characters and whitespace become ``-`` or
    are dropped, and the result is bounded to 72 UTF-8 bytes.
    """

    return safe_filename_component(unicodedata.normalize("NFC", title))


def customer_zip_name(delivery_version: str) -> str:
    return f"liveclip-customer-delivery-{delivery_version}.zip"


def customer_download_filename(title: str, delivery_version: str) -> str:
    return f"{customer_filename_component(title)}-{delivery_version}.zip"


def build_customer_manifest(
    *,
    delivery_version: str,
    title: str,
    created_at: str,
    clips: Iterable[CustomerPackageClip],
) -> CustomerDeliveryManifest:
    views: list[CustomerClipView] = []
    for clip in clips:
        stem = f"{clip.ordinal:02d}-{customer_filename_component(clip.text.title)}"
        folder = f"clips/{PROFILE_FOLDERS[clip.profile]}"
        views.append(
            customer_clip_view(
                ordinal=clip.ordinal,
                profile=clip.profile,
                text=clip.text,
                duration_ms=clip.duration_ms,
                video_href=f"{folder}/{stem}.mp4",
                subtitle_href=f"{folder}/{stem}.srt",
            )
        )
    short = sum(view.profile is ClipProfile.SHORT_HIGHLIGHT for view in views)
    return CustomerDeliveryManifest(
        delivery_version=delivery_version,
        title=title,
        created_at=created_at,
        clip_count=len(views),
        short_count=short,
        lesson_count=len(views) - short,
        clips=tuple(views),
    )


def _duration_label(duration_ms: int) -> str:
    seconds = max(0, (duration_ms + 500) // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _text(value: str) -> str:
    return html.escape(value, quote=True)


def _paragraphs(value: str) -> str:
    return "<br>".join(_text(line) for line in value.splitlines())


def _card(clip: CustomerClipView) -> str:
    title_id = f"clip-{clip.ordinal}"
    return f"""      <article class="card" aria-labelledby="{title_id}">
        <video controls preload="metadata" src="{_text(clip.video_href)}" aria-label="{_text(clip.title)}"></video>
        <div class="card-body">
          <p class="meta">{_text(clip.profile_label)} · 第 {clip.ordinal} 条 · 时长 {_duration_label(clip.duration_ms)}</p>
          <h3 id="{title_id}">{_text(clip.title)}</h3>
          <p class="hook">{_paragraphs(clip.hook)}</p>
          <p class="summary">{_paragraphs(clip.summary)}</p>
          <p class="downloads"><a href="{_text(clip.video_href)}" download>下载 MP4</a><a href="{_text(clip.subtitle_href)}" download>下载字幕（SRT）</a></p>
        </div>
      </article>
"""


def customer_index_html(
    manifest: CustomerDeliveryManifest,
    *,
    download_href: str | None = None,
) -> str:
    """Render the customer page; offline when ``download_href`` is None.

    Sections appear in the order 短片, 小课 and an empty section is omitted.
    The page has no script, no external resource and no ``<track>``; every
    text value is HTML-escaped.
    """

    sections: list[str] = []
    for profile in PROFILE_ORDER:
        clips = [clip for clip in manifest.clips if clip.profile is profile]
        if not clips:
            continue
        label = PROFILE_LABELS[profile]
        section_id = f"section-{PROFILE_FOLDERS[profile]}"
        cards = "".join(_card(clip) for clip in clips)
        sections.append(
            f"""    <section aria-labelledby="{section_id}">
      <h2 id="{section_id}">{label}（{len(clips)}）</h2>
      <div class="grid">
{cards}      </div>
    </section>
"""
        )
    if download_href is None:
        package_note = (
            '<p class="note">本文件夹就是完整的交付包：视频和字幕都在 clips 文件夹里，'
            "可以直接播放、下载，或把整个文件夹转发给需要的人。</p>"
        )
    else:
        package_note = (
            f'<p class="note"><a class="all" href="{_text(download_href)}" download>'
            "下载全部（ZIP）</a></p>"
        )
    counts = f"共 {manifest.clip_count} 条"
    if manifest.short_count:
        counts += f" · 短片 {manifest.short_count} 条"
    if manifest.lesson_count:
        counts += f" · 小课 {manifest.lesson_count} 条"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>{_text(manifest.title)}</title>
  <style>
    :root {{ color-scheme: light dark; --line: #d8dee4; --muted: #5b6670; --accent: #0f766e; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; line-height: 1.6; background: #f6f8f9; color: #1f2933; }}
    header, main, footer {{ max-width: 1080px; margin: 0 auto; padding: 16px; }}
    header h1 {{ margin: 8px 0 4px; font-size: 1.6rem; }}
    .counts, .meta, .note {{ color: var(--muted); }}
    h2 {{ margin: 24px 0 12px; font-size: 1.25rem; }}
    .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); }}
    .card {{ background: #fff; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }}
    .card video {{ display: block; width: 100%; max-height: 70vh; background: #000; }}
    .card-body {{ padding: 12px 16px 16px; }}
    .card h3 {{ margin: 4px 0 8px; font-size: 1.1rem; }}
    .hook {{ font-weight: 600; margin: 0 0 8px; }}
    .summary {{ margin: 0 0 12px; }}
    .downloads a, a.all {{ display: inline-block; margin: 4px 12px 0 0; color: var(--accent); }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #111619; color: #e5e9ec; }}
      .card {{ background: #1a2125; border-color: #2c363c; }}
      .counts, .meta, .note {{ color: #9aa6ae; }}
    }}
  </style>
</head>
<body>
  <header>
    <p class="meta">交付版本 {_text(manifest.delivery_version)}</p>
    <h1>{_text(manifest.title)}</h1>
    <p class="counts">{counts}</p>
    {package_note}
  </header>
  <main>
{"".join(sections)}  </main>
  <footer><p class="note">视频为无叠加字幕的干净版本，字幕以 SRT 文件单独提供。</p></footer>
</body>
</html>
"""


def build_customer_package(
    *,
    project_dir: Path,
    delivery_version: str,
    title: str,
    created_at: str,
    clips: tuple[CustomerPackageClip, ...],
    cancel_requested: Callable[[], bool] = lambda: False,
    publication_fence: Callable[[], None] = lambda: None,
) -> CustomerPackageResult:
    """Build ``customer-deliveries/<version>`` once, deterministically.

    The package is assembled in an exclusive sibling attempt directory and
    published with a no-replace directory rename. When a previous attempt
    already published the version, the rebuild must be byte-identical (same
    member hashes) and the published directory is reused.
    """

    manifest = build_customer_manifest(
        delivery_version=delivery_version, title=title, created_at=created_at, clips=clips
    )
    try:
        parent = ensure_directory_no_follow(project_dir / "customer-deliveries")
    except SecureFileError as exc:
        raise CustomerPackageError("customer delivery directory is unsafe") from exc
    destination = parent / delivery_version
    temporary = parent / f".{delivery_version}-attempt-{uuid.uuid4().hex}"
    try:
        temporary_identity = create_directory_exclusive_no_follow(temporary)
    except SecureFileError as exc:
        raise CustomerPackageError("customer delivery attempt could not be created") from exc
    published = False
    try:
        member_sha256 = _assemble(
            temporary, manifest=manifest, clips=clips, cancel_requested=cancel_requested
        )
        zip_name = customer_zip_name(delivery_version)
        if destination.exists() or destination.is_symlink():
            _require_identical(destination, member_sha256, zip_name=zip_name)
            result_dir = destination
        else:
            _check_cancel(cancel_requested)
            publication_fence()
            with ExitStack() as stack:
                pinned = _capture(temporary, member_sha256, stack)
                publish_directory_no_replace_no_follow(temporary, destination, pinned_files=pinned)
                published = True
            result_dir = destination
    finally:
        if not published:
            try:
                remove_tree_no_follow(
                    temporary, required_ancestor=parent, expected_identity=temporary_identity
                )
            except SecureFileError as exc:  # pragma: no cover - defensive cleanup
                raise CustomerPackageError("customer delivery attempt was not cleaned") from exc
    try:
        identity = directory_identity_no_follow(result_dir)
        manifest_hash, manifest_size = hash_regular_file_no_follow(result_dir / "manifest.json")
        zip_hash, zip_size = hash_regular_file_no_follow(result_dir / zip_name)
    except SecureFileError as exc:
        raise CustomerPackageError("published customer delivery is not readable") from exc
    if manifest_hash != member_sha256["manifest.json"] or zip_hash != member_sha256[zip_name]:
        raise CustomerPackageError("published customer delivery differs from its build")
    return CustomerPackageResult(
        directory=result_dir,
        directory_identity=identity,
        manifest=manifest,
        manifest_sha256=manifest_hash,
        manifest_size_bytes=manifest_size,
        zip_name=zip_name,
        zip_sha256=zip_hash,
        zip_size_bytes=zip_size,
        member_sha256=member_sha256,
    )


def _assemble(
    root: Path,
    *,
    manifest: CustomerDeliveryManifest,
    clips: tuple[CustomerPackageClip, ...],
    cancel_requested: Callable[[], bool],
) -> dict[str, str]:
    member_sha256: dict[str, str] = {}
    for view, clip in zip(manifest.clips, clips, strict=True):
        _check_cancel(cancel_requested)
        video = PurePosixPath(view.video_href)
        subtitle = PurePosixPath(view.subtitle_href)
        try:
            ensure_directory_no_follow(root / Path(*video.parent.parts))
            observed = copy_immutable_member(
                clip.video_path, root / Path(*video.parts), expected_sha256=clip.video_sha256
            )
        except (DeliveryError, SecureFileError) as exc:
            raise CustomerPackageError("customer clip video could not be copied safely") from exc
        member_sha256[video.as_posix()] = observed
        member_sha256[subtitle.as_posix()] = _write_text(
            root / Path(*subtitle.parts), _verified_subtitle(clip), max_bytes=4_000_000
        )
    manifest_dict = manifest.as_json_dict()
    manifest_text = json.dumps(manifest_dict, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    member_sha256["manifest.json"] = _write_text(
        root / "manifest.json", manifest_text, max_bytes=8_000_000
    )
    member_sha256["index.html"] = _write_text(
        root / "index.html", customer_index_html(manifest), max_bytes=8_000_000
    )
    member_sha256["checksums.sha256"] = _write_text(
        root / "checksums.sha256", delivery_checksums_text(member_sha256), max_bytes=2_000_000
    )
    _check_cancel(cancel_requested)
    zip_name = customer_zip_name(manifest.delivery_version)
    try:
        member_sha256[zip_name] = create_verified_zip(
            root=root,
            output_path=root / zip_name,
            members=tuple(PurePosixPath(name) for name in sorted(member_sha256)),
            manifest=manifest_dict,
            expected_sha256=dict(member_sha256),
            member_mode=0o644,
        )
    except DeliveryError as exc:
        raise CustomerPackageError("customer delivery ZIP could not be verified") from exc
    validate_zip_members(member_sha256)
    return member_sha256


def _verified_subtitle(clip: CustomerPackageClip) -> str:
    try:
        payload = read_regular_file_no_follow(clip.subtitle_path, max_bytes=4_000_000)
    except SecureFileError as exc:
        raise CustomerPackageError("customer clip subtitle could not be read safely") from exc
    if (
        hashlib.sha256(payload).hexdigest() != clip.subtitle_sha256
        or len(payload) != clip.subtitle_size_bytes
    ):
        raise CustomerPackageError("customer clip subtitle differs from its committed hash")
    try:
        return normalize_srt(payload.decode("utf-8"))
    except (UnicodeDecodeError, DeliveryError) as exc:
        raise CustomerPackageError("customer clip subtitle is not valid UTF-8 SRT") from exc


def _write_text(path: Path, payload: str, *, max_bytes: int) -> str:
    try:
        write_text_immutable_no_follow(path, payload, max_bytes=max_bytes)
    except SecureFileError as exc:
        raise CustomerPackageError("customer delivery text could not be written safely") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _capture(
    root: Path, member_sha256: dict[str, str], stack: ExitStack
) -> dict[str, PinnedFileEvidence]:
    pinned: dict[str, PinnedFileEvidence] = {}
    for name in validate_zip_members(member_sha256):
        try:
            evidence = capture_pinned_file_evidence(
                root / Path(*PurePosixPath(name).parts), expected_sha256=member_sha256[name]
            )
        except SecureFileError as exc:
            raise CustomerPackageError("customer delivery member changed before publish") from exc
        stack.callback(evidence.pinned.close)
        pinned[name] = evidence
    return pinned


def _require_identical(destination: Path, member_sha256: dict[str, str], *, zip_name: str) -> None:
    for name, expected in member_sha256.items():
        try:
            observed, _ = hash_regular_file_no_follow(
                destination / Path(*PurePosixPath(name).parts)
            )
        except SecureFileError as exc:
            raise CustomerPackageError("published customer delivery is incomplete") from exc
        if observed != expected:
            raise CustomerPackageError("published customer delivery differs from this version")
    if zip_name not in member_sha256:  # pragma: no cover - always built
        raise CustomerPackageError("customer delivery ZIP is missing")


def _check_cancel(cancel_requested: Callable[[], bool]) -> None:
    if cancel_requested():
        raise CustomerPackageCancelled("customer delivery build was cancelled")


__all__ = [
    "CONTENT_SECURITY_POLICY",
    "CUSTOMER_MANIFEST_SCHEMA",
    "CustomerDeliveryManifest",
    "CustomerPackageCancelled",
    "CustomerPackageClip",
    "CustomerPackageError",
    "CustomerPackageResult",
    "build_customer_manifest",
    "build_customer_package",
    "customer_download_filename",
    "customer_filename_component",
    "customer_index_html",
    "customer_zip_name",
]
