# ruff: noqa: E501, RUF001
from __future__ import annotations

import hashlib
import html
import json
import re
import uuid
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.delivery.package import (
    DeliveryError,
    copy_immutable_member,
    create_verified_zip,
    safe_filename_component,
    validate_zip_members,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.keywords import KeywordOccurrence
from liveclip.domain.time import ms_to_srt
from liveclip.media.secure_files import (
    PinnedFileEvidence,
    SecureFileError,
    capture_pinned_file_evidence,
    create_directory_exclusive_no_follow,
    ensure_directory_no_follow,
    publish_directory_no_replace_no_follow,
    remove_tree_no_follow,
    write_text_immutable_no_follow,
)


class DualProfileReviewPackageError(RuntimeError):
    """A dual-profile offline-review package could not be built safely."""


class DualProfileRunProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=120)
    prompt_hashes: dict[str, str]
    calls: dict[str, int]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    repair_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_hashes_and_counts(self) -> DualProfileRunProvenance:
        if any(
            re.fullmatch(r"[a-f0-9]{64}", value) is None for value in self.prompt_hashes.values()
        ):
            raise ValueError("run provenance contains an invalid Prompt hash")
        if any(not key or value < 0 for key, value in self.calls.items()):
            raise ValueError("run provenance contains an invalid call count")
        return self


class DualProfileReviewClipInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    profile: ClipProfile
    variant_group_id: str = Field(default="", max_length=96, pattern=r"^[A-Za-z0-9_-]*$")
    source_candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    source_window_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    start_cue_id: int = Field(ge=1)
    end_cue_id: int = Field(ge=1)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=120)
    hook: str = Field(min_length=1, max_length=600)
    summary: str = Field(min_length=1, max_length=1_200)
    review_reason: str = Field(min_length=1, max_length=2_000)
    score: float = Field(ge=0, le=100)
    review_status: Literal["selected", "manual_review"]
    quality_flags: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    risk_tags: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    evidence_cue_ids: tuple[int, ...] = Field(min_length=1, max_length=200)
    keywords: tuple[KeywordOccurrence, ...] = Field(default_factory=tuple, max_length=6)
    subtitle_text: str = Field(min_length=1, max_length=2_000_000)
    video_path: Path
    video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    video_size_bytes: int = Field(gt=0)
    subtitle_path: Path
    subtitle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subtitle_size_bytes: int = Field(gt=0)
    contact_sheet_path: Path
    contact_sheet_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    contact_sheet_size_bytes: int = Field(gt=0)
    quality_report_path: Path
    quality_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality_report_size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_clip(self) -> DualProfileReviewClipInput:
        if self.end_ms <= self.start_ms or self.duration_ms != self.end_ms - self.start_ms:
            raise ValueError("review clip interval is inconsistent")
        if self.end_cue_id < self.start_cue_id:
            raise ValueError("review clip cue interval is reversed")
        if "-->" not in self.subtitle_text or "\x00" in self.subtitle_text:
            raise ValueError("review clip subtitle is not a bounded SRT payload")
        return self


class DualProfileReviewPackageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    package_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    package_version: str = Field(default="v001", pattern=r"^v[0-9]{3}$")
    package_title: str = Field(default="LiveClip 双轨切分人工审核", min_length=1, max_length=120)
    source_filename: str = Field(min_length=1, max_length=255)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    algorithm_version: str = Field(min_length=1, max_length=80)
    requested_profiles: tuple[ClipProfile, ...] = Field(min_length=1)
    executed_profiles: tuple[ClipProfile, ...] = Field(min_length=1)
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    final_result_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    render_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    run_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    candidate_filter: tuple[str, ...] | None = None
    run_provenance: DualProfileRunProvenance | None = None
    clips: tuple[DualProfileReviewClipInput, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_identity(self) -> DualProfileReviewPackageInput:
        if len(set(self.requested_profiles)) != len(self.requested_profiles):
            raise ValueError("requested Profiles are duplicated")
        if len(set(self.executed_profiles)) != len(self.executed_profiles):
            raise ValueError("executed Profiles are duplicated")
        if not set(self.executed_profiles).issubset(self.requested_profiles):
            raise ValueError("executed Profiles were not requested")
        identities = [clip.candidate_id for clip in self.clips]
        if len(identities) != len(set(identities)):
            raise ValueError("review package repeats a candidate")
        if any(clip.profile not in self.executed_profiles for clip in self.clips):
            raise ValueError("review package contains an unexecuted Profile")
        if self.candidate_filter is not None and set(self.candidate_filter) != set(identities):
            raise ValueError("candidate filter differs from packaged clips")
        return self


class DualProfileReviewPackageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    package_id: str
    package_version: str
    directory: Path
    index_path: Path
    manifest_path: Path
    zip_path: Path | None
    clip_count: int = Field(gt=0)
    profile_counts: dict[ClipProfile, int]
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    zip_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    member_sha256: dict[str, str]

    @model_validator(mode="after")
    def validate_evidence(self) -> DualProfileReviewPackageResult:
        if self.member_sha256.get("manifest.json") != self.manifest_sha256:
            raise ValueError("review package manifest evidence is inconsistent")
        archive_name = f"liveclip-dual-profile-offline-review-{self.package_version}.zip"
        if (self.zip_path is None) != (self.zip_sha256 is None):
            raise ValueError("review package ZIP evidence is incomplete")
        if self.zip_sha256 is not None and self.member_sha256.get(archive_name) != self.zip_sha256:
            raise ValueError("review package ZIP evidence is inconsistent")
        validate_zip_members(self.member_sha256)
        return self


def create_dual_profile_review_package(
    *,
    output_dir: Path,
    package: DualProfileReviewPackageInput,
    final_result_path: Path,
    render_manifest_path: Path,
    run_manifest_path: Path | None,
    include_zip: bool = True,
    created_at: datetime | None = None,
) -> DualProfileReviewPackageResult:
    """Create one immutable, browsable package without changing review state."""

    if output_dir.exists() or output_dir.is_symlink():
        raise DualProfileReviewPackageError("review package output already exists")
    try:
        parent = ensure_directory_no_follow(output_dir.parent.resolve(strict=True))
    except (OSError, SecureFileError) as exc:
        raise DualProfileReviewPackageError("review package parent is unsafe") from exc
    destination = parent / output_dir.name
    temporary = parent / f".{output_dir.name}-attempt-{uuid.uuid4().hex}"
    try:
        temporary_identity = create_directory_exclusive_no_follow(temporary)
    except SecureFileError as exc:
        raise DualProfileReviewPackageError("review package attempt could not be created") from exc
    published = False
    try:
        result = _build_package(
            temporary=temporary,
            destination=destination,
            package=package,
            final_result_path=final_result_path,
            render_manifest_path=render_manifest_path,
            run_manifest_path=run_manifest_path,
            include_zip=include_zip,
            created_at=(created_at or datetime.now(UTC)).astimezone(UTC),
        )
        with ExitStack() as stack:
            pinned = _capture_members(
                root=temporary,
                expected_sha256=result.member_sha256,
                stack=stack,
            )
            publish_directory_no_replace_no_follow(
                temporary,
                destination,
                pinned_files=pinned,
            )
            published = True
    except Exception:
        if not published:
            try:
                remove_tree_no_follow(
                    temporary,
                    required_ancestor=parent,
                    expected_identity=temporary_identity,
                )
            except SecureFileError as cleanup_error:
                raise DualProfileReviewPackageError(
                    "failed review package attempt could not be cleaned safely"
                ) from cleanup_error
        raise
    archive_name = f"liveclip-dual-profile-offline-review-{package.package_version}.zip"
    return result.model_copy(
        update={
            "directory": destination,
            "index_path": destination / "index.html",
            "manifest_path": destination / "manifest.json",
            "zip_path": destination / archive_name if include_zip else None,
        }
    )


def _build_package(
    *,
    temporary: Path,
    destination: Path,
    package: DualProfileReviewPackageInput,
    final_result_path: Path,
    render_manifest_path: Path,
    run_manifest_path: Path | None,
    include_zip: bool,
    created_at: datetime,
) -> DualProfileReviewPackageResult:
    for name in ("clips", "subtitles", "descriptions", "quality", "audit"):
        ensure_directory_no_follow(temporary / name)
    for profile in package.executed_profiles:
        for name in ("clips", "subtitles", "descriptions", "quality"):
            ensure_directory_no_follow(temporary / name / profile.value)

    member_sha256: dict[str, str] = {}
    manifest_clips: list[dict[str, object]] = []
    description_sections: list[str] = []
    for ordinal, clip in enumerate(package.clips, start=1):
        stem = f"{ordinal:02d}-{safe_filename_component(clip.title)}"
        profile_name = clip.profile.value
        video_relative = PurePosixPath("clips") / profile_name / f"{stem}.mp4"
        subtitle_relative = PurePosixPath("subtitles") / profile_name / f"{stem}.srt"
        description_relative = PurePosixPath("descriptions") / profile_name / f"{stem}.md"
        contact_relative = PurePosixPath("quality") / profile_name / f"{stem}-contact-sheet.png"
        quality_relative = PurePosixPath("quality") / profile_name / f"{stem}-quality-report.json"

        for source, relative, expected_hash, expected_size in (
            (clip.video_path, video_relative, clip.video_sha256, clip.video_size_bytes),
            (clip.subtitle_path, subtitle_relative, clip.subtitle_sha256, clip.subtitle_size_bytes),
            (
                clip.contact_sheet_path,
                contact_relative,
                clip.contact_sheet_sha256,
                clip.contact_sheet_size_bytes,
            ),
            (
                clip.quality_report_path,
                quality_relative,
                clip.quality_report_sha256,
                clip.quality_report_size_bytes,
            ),
        ):
            _copy_verified_member(
                source=source,
                destination=temporary / Path(*relative.parts),
                expected_sha256=expected_hash,
                expected_size=expected_size,
            )
            member_sha256[relative.as_posix()] = expected_hash

        description = _clip_markdown(ordinal, clip)
        member_sha256[description_relative.as_posix()] = _write_text(
            temporary / Path(*description_relative.parts),
            description,
            max_bytes=2_000_000,
        )
        description_sections.append(description.rstrip())
        manifest_clips.append(
            {
                "ordinal": ordinal,
                "candidate_id": clip.candidate_id,
                "profile": profile_name,
                "variant_group_id": clip.variant_group_id,
                "source_candidate_ids": list(clip.source_candidate_ids),
                "source_window_ids": list(clip.source_window_ids),
                "start_cue_id": clip.start_cue_id,
                "end_cue_id": clip.end_cue_id,
                "start_ms": clip.start_ms,
                "end_ms": clip.end_ms,
                "duration_ms": clip.duration_ms,
                "title": clip.title,
                "hook": clip.hook,
                "summary": clip.summary,
                "review_reason": clip.review_reason,
                "score": clip.score,
                "review_status": clip.review_status,
                "quality_flags": list(clip.quality_flags),
                "risk_tags": list(clip.risk_tags),
                "evidence_cue_ids": list(clip.evidence_cue_ids),
                "editor_keywords": [value.model_dump(mode="json") for value in clip.keywords],
                "subtitle_text": clip.subtitle_text,
                "video_filename": video_relative.as_posix(),
                "subtitle_filename": subtitle_relative.as_posix(),
                "description_filename": description_relative.as_posix(),
                "contact_sheet_filename": contact_relative.as_posix(),
                "quality_report_filename": quality_relative.as_posix(),
                "video_sha256": clip.video_sha256,
                "subtitle_sha256": clip.subtitle_sha256,
                "contact_sheet_sha256": clip.contact_sheet_sha256,
                "quality_report_sha256": clip.quality_report_sha256,
            }
        )

    audit_sources = (
        (final_result_path, "audit/final-validated.json", package.final_result_sha256),
        (render_manifest_path, "audit/render-manifest.json", package.render_manifest_sha256),
    )
    for source, name, expected_hash in audit_sources:
        _copy_verified_member(
            source=source,
            destination=temporary / Path(*PurePosixPath(name).parts),
            expected_sha256=expected_hash,
            expected_size=source.stat(follow_symlinks=False).st_size,
        )
        member_sha256[name] = expected_hash
    if run_manifest_path is not None and package.run_manifest_sha256 is not None:
        name = "audit/run-manifest.json"
        _copy_verified_member(
            source=run_manifest_path,
            destination=temporary / Path(*PurePosixPath(name).parts),
            expected_sha256=package.run_manifest_sha256,
            expected_size=run_manifest_path.stat(follow_symlinks=False).st_size,
        )
        member_sha256[name] = package.run_manifest_sha256

    counts = Counter(clip.profile for clip in package.clips)
    manifest: dict[str, object] = {
        "schema_version": "liveclip.dual-profile-offline-review-package.v1",
        "package_type": "dual_profile_offline_review",
        "package_id": package.package_id,
        "package_version": package.package_version,
        "created_at": created_at.isoformat(),
        "package_title": package.package_title,
        "source_filename": package.source_filename,
        "source_hash": package.source_hash,
        "algorithm_version": package.algorithm_version,
        "requested_profiles": [value.value for value in package.requested_profiles],
        "executed_profiles": [value.value for value in package.executed_profiles],
        "snapshot_fingerprint": package.snapshot_fingerprint,
        "candidate_filter": list(package.candidate_filter) if package.candidate_filter else None,
        "clip_count": len(package.clips),
        "profile_counts": {profile.value: counts[profile] for profile in package.executed_profiles},
        "notice": (
            "这是待人工审核的双轨切分快照，不代表候选已批准或可直接发布；"
            "包内视频为当前无 LiveClip 文字叠加的审核成片。"
        ),
        "input_evidence": {
            "final_result_sha256": package.final_result_sha256,
            "render_manifest_sha256": package.render_manifest_sha256,
            "run_manifest_sha256": package.run_manifest_sha256,
        },
        "clips": manifest_clips,
    }
    if package.run_provenance is not None:
        manifest["run_provenance"] = package.run_provenance.model_dump(mode="json")

    readme = _readme(package=package, counts=counts)
    descriptions = "# LiveClip 双轨切分逐条说明\n\n" + "\n\n---\n\n".join(description_sections)
    index = _offline_html(package=package, manifest_clips=manifest_clips, counts=counts)
    manifest_payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for name, payload, limit in (
        ("README.md", readme, 1_000_000),
        ("descriptions.md", descriptions, 8_000_000),
        ("index.html", index, 8_000_000),
        ("manifest.json", manifest_payload, 8_000_000),
    ):
        member_sha256[name] = _write_text(temporary / name, payload, max_bytes=limit)

    checksums = "".join(f"{digest}  {name}\n" for name, digest in sorted(member_sha256.items()))
    member_sha256["checksums.sha256"] = _write_text(
        temporary / "checksums.sha256",
        checksums,
        max_bytes=2_000_000,
    )
    archive_name = f"liveclip-dual-profile-offline-review-{package.package_version}.zip"
    zip_sha256: str | None = None
    if include_zip:
        try:
            zip_sha256 = create_verified_zip(
                root=temporary,
                output_path=temporary / archive_name,
                members=tuple(PurePosixPath(name) for name in member_sha256),
                manifest=manifest,
                expected_sha256=dict(member_sha256),
            )
        except DeliveryError as exc:
            raise DualProfileReviewPackageError("review package ZIP could not be verified") from exc
        member_sha256[archive_name] = zip_sha256

    return DualProfileReviewPackageResult(
        package_id=package.package_id,
        package_version=package.package_version,
        directory=destination,
        index_path=destination / "index.html",
        manifest_path=destination / "manifest.json",
        zip_path=destination / archive_name if include_zip else None,
        clip_count=len(package.clips),
        profile_counts={profile: counts[profile] for profile in package.executed_profiles},
        snapshot_fingerprint=package.snapshot_fingerprint,
        manifest_sha256=member_sha256["manifest.json"],
        zip_sha256=zip_sha256,
        member_sha256=member_sha256,
    )


def _copy_verified_member(
    *, source: Path, destination: Path, expected_sha256: str, expected_size: int
) -> None:
    try:
        observed = copy_immutable_member(source, destination, expected_sha256=expected_sha256)
        size = destination.stat(follow_symlinks=False).st_size
    except (DeliveryError, OSError) as exc:
        raise DualProfileReviewPackageError(
            "review package input could not be copied safely"
        ) from exc
    if observed != expected_sha256 or size != expected_size:
        raise DualProfileReviewPackageError("review package input differs from committed metadata")


def _write_text(path: Path, payload: str, *, max_bytes: int) -> str:
    encoded = payload.encode("utf-8")
    if not encoded:
        raise DualProfileReviewPackageError("review package text member cannot be empty")
    try:
        write_text_immutable_no_follow(path, payload, max_bytes=max_bytes)
    except SecureFileError as exc:
        raise DualProfileReviewPackageError(
            "review package text could not be written safely"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _capture_members(
    *, root: Path, expected_sha256: dict[str, str], stack: ExitStack
) -> dict[str, PinnedFileEvidence]:
    pinned: dict[str, PinnedFileEvidence] = {}
    for name in validate_zip_members(expected_sha256):
        relative = PurePosixPath(name)
        try:
            evidence = capture_pinned_file_evidence(
                root / Path(*relative.parts),
                expected_sha256=expected_sha256[name],
            )
        except SecureFileError as exc:
            raise DualProfileReviewPackageError(
                "review package member differs from its expected bytes"
            ) from exc
        stack.callback(evidence.pinned.close)
        pinned[name] = evidence
    return pinned


def _readme(*, package: DualProfileReviewPackageInput, counts: Counter[ClipProfile]) -> str:
    return f"""# LiveClip 双轨切分离线审核包

来源：{_markdown_text(package.source_filename)}

版本：{package.package_version}

短片：{counts[ClipProfile.SHORT_HIGHLIGHT]} 条

长片：{counts[ClipProfile.MINI_LESSON]} 条

## 如何查看

1. 解压后保持目录结构不变。
2. 双击 `index.html`，即可按短片和长片分组离线播放。
3. 每条卡片显示标题、高光语句、推荐理由、分数、状态、风险、编辑关键词和字幕。
4. `descriptions.md` 汇总全部说明；`descriptions/` 是逐条说明。
5. `clips/`、`subtitles/`、`quality/` 分别保存视频、字幕和质量证据。
6. `manifest.json` 供自动化读取；`checksums.sha256` 用于文件校验。

## 状态说明

这是待人工审核快照，不是正式 Delivery，不会批准候选，也不表示视频可直接发布。
请重点检查开头能否独立理解、结尾是否闭环、是否存在无关补时、字幕错字、音画同步、
音乐/参与者声音版权以及健康或绝对化表述。
"""


def _clip_markdown(ordinal: int, clip: DualProfileReviewClipInput) -> str:
    risks = "、".join(clip.risk_tags) if clip.risk_tags else "无"
    quality = "、".join(clip.quality_flags) if clip.quality_flags else "无"
    keywords = (
        "\n".join(
            f"- {_markdown_text(value.text)}：片内 {_display_time(value.clip_start_ms)}–"
            f"{_display_time(value.clip_end_ms)}；源视频 {_display_time(value.source_start_ms)}–"
            f"{_display_time(value.source_end_ms)}；精度 {value.timing_precision.value}"
            for value in clip.keywords
        )
        or "- 无"
    )
    subtitle = "\n".join(f"    {line}" for line in clip.subtitle_text.rstrip().splitlines())
    return (
        f"# {ordinal:02d}. {_markdown_text(clip.title)}\n\n"
        f"- Profile：`{clip.profile.value}`\n"
        f"- 高光语句：{_markdown_text(clip.hook)}\n"
        f"- 内容摘要：{_markdown_text(clip.summary)}\n"
        f"- 推荐理由：{_markdown_text(clip.review_reason)}\n"
        f"- 分数：{clip.score:g}\n"
        f"- 源视频位置：{_display_time(clip.start_ms)}–{_display_time(clip.end_ms)}\n"
        f"- 时长：{clip.duration_ms / 1_000:.3f} 秒\n"
        f"- 审核状态：`{clip.review_status}`\n"
        f"- 质量标记：{_markdown_text(quality)}\n"
        f"- 风险标签：{_markdown_text(risks)}\n"
        f"- 变体组：`{clip.variant_group_id or '无'}`\n\n"
        "## 编辑关键词（仅供定位）\n\n"
        f"{keywords}\n\n"
        "## 字幕（切片相对时间）\n\n"
        f"{subtitle}\n"
    )


def _offline_html(
    *,
    package: DualProfileReviewPackageInput,
    manifest_clips: list[dict[str, object]],
    counts: Counter[ClipProfile],
) -> str:
    groups: list[str] = []
    for profile in package.executed_profiles:
        values = [value for value in manifest_clips if value["profile"] == profile.value]
        cards = "\n".join(_clip_html(value) for value in values)
        label = (
            "短片 short_highlight" if profile == ClipProfile.SHORT_HIGHLIGHT else "长片 mini_lesson"
        )
        groups.append(
            f'<section class="profile" id="{profile.value}"><div class="profile-title">'
            f"<h2>{html.escape(label)}</h2><span>{len(values)} 条</span></div>"
            f'<div class="grid">{cards}</div></section>'
        )
    title = html.escape(package.package_title)
    source = html.escape(package.source_filename)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; media-src 'self' file: blob:; style-src 'unsafe-inline'; img-src 'self' data:">
  <title>{title}</title>
  <style>
    :root {{ color-scheme:dark; font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; background:#081416; color:#eef8f6; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; }}
    header {{ position:sticky; top:0; z-index:2; padding:20px max(22px,calc((100vw - 1440px)/2)); background:#081416f2; border-bottom:1px solid #284548; backdrop-filter:blur(14px); }}
    h1 {{ margin:0 0 8px; font-size:clamp(25px,3vw,42px); }} .meta {{ color:#9ab8b4; line-height:1.65; }}
    .notice {{ margin-top:10px; color:#ffd37a; }} nav {{ margin-top:12px; display:flex; gap:10px; flex-wrap:wrap; }}
    nav a,.download {{ color:#071416; background:#5ee0c2; border-radius:999px; padding:7px 11px; text-decoration:none; font-weight:750; }}
    main {{ max-width:1440px; margin:auto; padding:28px 22px 72px; }} .profile {{ margin-bottom:44px; }}
    .profile-title {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:16px; }} .profile-title h2 {{ margin:0; font-size:1.55rem; }}
    .profile-title span {{ color:#5ee0c2; }} .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:22px; }}
    article {{ overflow:hidden; border:1px solid #284548; border-radius:18px; background:#0e2225; box-shadow:0 18px 42px #0006; }}
    article header {{ position:static; padding:16px 18px 12px; background:transparent; border:0; backdrop-filter:none; }}
    .ordinal {{ color:#5ee0c2; font-weight:850; }} article h3 {{ margin:5px 0 0; font-size:1.12rem; }}
    video {{ display:block; width:100%; aspect-ratio:9/16; max-height:68vh; object-fit:contain; background:#000; }}
    .content {{ padding:16px 18px 20px; }} .badges,.actions,.keywords {{ display:flex; flex-wrap:wrap; gap:8px; }}
    .badge,.keyword {{ padding:6px 9px; border-radius:9px; background:#163438; color:#cce8e4; font-size:.78rem; }}
    .status {{ color:#ffd37a; }} blockquote {{ margin:15px 0 9px; padding:13px 14px; border-left:3px solid #5ee0c2; border-radius:8px; background:#123034; line-height:1.65; }}
    .summary,.reason,.source {{ color:#a8c4c0; line-height:1.6; font-size:.88rem; }} .reason {{ margin-bottom:15px; }}
    .section-title {{ margin:16px 0 8px; color:#e6f7f4; font-size:.9rem; font-weight:750; }}
    .quality-image {{ display:block; width:100%; max-height:280px; object-fit:contain; background:#071416; border-radius:10px; }}
    .actions {{ margin-top:15px; }} details {{ margin-top:15px; border-top:1px solid #284548; padding-top:12px; }}
    summary {{ cursor:pointer; color:#5ee0c2; }} pre {{ white-space:pre-wrap; word-break:break-word; color:#c8dcda; font-size:.76rem; line-height:1.55; }}
  </style>
</head>
<body>
  <header><h1>{title}</h1><div class="meta">{source} · {package.package_version} · {len(package.clips)} 条（短片 {counts[ClipProfile.SHORT_HIGHLIGHT]} / 长片 {counts[ClipProfile.MINI_LESSON]}）</div>
  <div class="notice">待人工审核快照，不代表已批准或可直接发布。</div>
  <nav><a href="#short_highlight">查看短片</a><a href="#mini_lesson">查看长片</a></nav></header>
  <main>{"".join(groups)}</main>
</body>
</html>
"""


def _clip_html(clip: dict[str, object]) -> str:
    title = html.escape(str(clip["title"]), quote=True)
    hook = html.escape(str(clip["hook"]), quote=True)
    summary = html.escape(str(clip["summary"]), quote=True)
    reason = html.escape(str(clip["review_reason"]), quote=True)
    video = html.escape(str(clip["video_filename"]), quote=True)
    subtitle = html.escape(str(clip["subtitle_filename"]), quote=True)
    description = html.escape(str(clip["description_filename"]), quote=True)
    contact = html.escape(str(clip["contact_sheet_filename"]), quote=True)
    quality_report = html.escape(str(clip["quality_report_filename"]), quote=True)
    keyword_html = _keyword_html(clip.get("editor_keywords"))
    risks = _string_list(clip.get("risk_tags"), label="risk tags")
    quality = _string_list(clip.get("quality_flags"), label="quality flags")
    risk_html = "".join(
        f'<span class="badge">风险 {html.escape(str(value))}</span>' for value in risks
    )
    quality_html = "".join(
        f'<span class="badge">质量 {html.escape(str(value))}</span>' for value in quality
    )
    profile = html.escape(str(clip["profile"]))
    status = html.escape(str(clip["review_status"]))
    ordinal = _integer(clip.get("ordinal"), label="ordinal")
    score = _number(clip.get("score"), label="score")
    duration = _integer(clip.get("duration_ms"), label="duration") / 1_000
    source_range = (
        f"{_display_time(_integer(clip.get('start_ms'), label='start'))}–"
        f"{_display_time(_integer(clip.get('end_ms'), label='end'))}"
    )
    subtitle_text = html.escape(str(clip["subtitle_text"]))
    return f"""<article>
      <header><span class="ordinal">{ordinal:02d}</span><h3>{title}</h3></header>
      <video controls preload="metadata" src="{video}">浏览器不支持视频播放。</video>
      <div class="content">
        <div class="badges"><span class="badge">{profile}</span><span class="badge status">{status}</span><span class="badge">评分 {score:g}</span><span class="badge">{duration:.3f}s</span>{quality_html}{risk_html}</div>
        <blockquote>{hook}</blockquote><p class="summary">{summary}</p><p class="reason">{reason}</p>
        <p class="source">源视频 {source_range}</p>
        <div class="section-title">编辑关键词（仅供定位）</div><div class="keywords">{keyword_html}</div>
        <div class="section-title">开始 / 中间 / 结束画面</div><a href="{contact}"><img class="quality-image" src="{contact}" alt="{title} 质量联系表"></a>
        <div class="actions"><a class="download" href="{video}" download>下载 MP4</a><a class="download" href="{subtitle}" download>下载 SRT</a><a class="download" href="{description}">逐条说明</a><a class="download" href="{quality_report}">质量报告</a></div>
        <details><summary>查看字幕</summary><pre data-subtitle-path="{subtitle}">{subtitle_text}</pre></details>
      </div>
    </article>"""


def _keyword_html(value: object) -> str:
    if not isinstance(value, list):
        raise DualProfileReviewPackageError("review package keyword list is invalid")
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            raise DualProfileReviewPackageError("review package keyword is invalid")
        text = html.escape(str(item.get("text", "")))
        start = _integer(item.get("clip_start_ms"), label="keyword start")
        parts.append(f'<span class="keyword">{text} · {_display_time(start)}</span>')
    return "".join(parts) or '<span class="keyword">暂无可定位关键词</span>'


def _string_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DualProfileReviewPackageError(f"review package {label} are invalid")
    return value


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DualProfileReviewPackageError(f"review package {label} is invalid")
    return value


def _number(value: object, *, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DualProfileReviewPackageError(f"review package {label} is invalid")
    return float(value)


def _display_time(value_ms: int) -> str:
    return ms_to_srt(value_ms).replace(",", ".")


def _markdown_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("\n", " ").strip()


__all__ = [
    "DualProfileReviewClipInput",
    "DualProfileReviewPackageError",
    "DualProfileReviewPackageInput",
    "DualProfileReviewPackageResult",
    "DualProfileRunProvenance",
    "create_dual_profile_review_package",
]
