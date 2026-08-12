# ruff: noqa: E501, RUF001
from __future__ import annotations

import fcntl
import hashlib
import html
import json
import os
import re
import stat
import zipfile
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from liveclip.delivery.package import (
    hash_zip_member,
    safe_filename_component,
    validate_zip_infos,
    validate_zip_members,
)
from liveclip.domain.edit_plan import CaptionCue, captions_to_srt, reject_executable_text
from liveclip.domain.keywords import KeywordOccurrence
from liveclip.domain.state_transitions import ReviewStatus
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


class OfflineReviewPackageError(RuntimeError):
    """The offline review package could not be built or verified."""


class OfflineReviewClipInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    candidate_key: str = Field(min_length=1, max_length=64)
    edit_plan_revision: int = Field(ge=1)
    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: float = Field(ge=0, le=100)
    title: str = Field(min_length=1, max_length=40)
    high_impact_sentence: str = Field(min_length=1, max_length=80)
    recommendation_reason: str = Field(min_length=1, max_length=240)
    risk_flags: tuple[
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
        ],
        ...,
    ] = Field(max_length=8)
    captions: tuple[CaptionCue, ...]
    keywords: tuple[KeywordOccurrence, ...]
    review_status: ReviewStatus
    proxy_path: Path
    proxy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    proxy_size_bytes: int = Field(gt=0)
    proxy_render_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    proxy_asset_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    proxy_spec_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    proxy_render_revision_epoch: int = Field(ge=0)
    proxy_producer_task_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    proxy_producer_task_kind: str = Field(pattern=r"^(stage|render)$")
    proxy_producer_stage: str | None = Field(default=None, pattern=r"^proxy_render$")
    proxy_asset_input_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    proxy_asset_generation: int = Field(ge=1)
    proxy_asset_revision_epoch: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_clip(self) -> OfflineReviewClipInput:
        if self.source_end_ms <= self.source_start_ms:
            raise ValueError("offline review clip interval must be positive")
        duration_ms = self.source_end_ms - self.source_start_ms
        if not self.captions:
            raise ValueError("offline review clip must include subtitle cues")
        if any(cue.end_ms > duration_ms for cue in self.captions):
            raise ValueError("offline review subtitle exceeds the clip duration")
        if self.proxy_asset_generation < 1:
            raise ValueError("offline review proxy generation must be positive")
        if (self.proxy_producer_task_kind == "stage") != (
            self.proxy_producer_stage == "proxy_render"
        ):
            raise ValueError("offline review proxy producer lineage is inconsistent")
        if (
            self.proxy_producer_task_kind == "render"
            and self.proxy_asset_input_fingerprint != self.proxy_spec_fingerprint
        ):
            raise ValueError("manual review proxy asset and render fingerprints differ")
        if self.proxy_asset_revision_epoch != self.proxy_render_revision_epoch:
            raise ValueError("offline review proxy epochs are inconsistent")
        for value in (
            self.title,
            self.high_impact_sentence,
            self.recommendation_reason,
            *self.risk_flags,
        ):
            reject_executable_text(value)
        return self


class OfflineReviewPackageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    package_id: str
    package_version: str = Field(pattern=r"^v[0-9]{3}$")
    directory: Path
    index_path: Path
    manifest_path: Path
    zip_path: Path | None
    clip_count: int = Field(gt=0)
    project_revision_epoch: int = Field(ge=0)
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    zip_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    member_sha256: dict[str, str]

    @model_validator(mode="after")
    def validate_result_evidence(self) -> OfflineReviewPackageResult:
        if self.member_sha256.get("manifest.json") != self.manifest_sha256:
            raise ValueError("offline review manifest evidence is inconsistent")
        has_zip_path = self.zip_path is not None
        has_zip_hash = self.zip_sha256 is not None
        has_zip_member = "offline-review.zip" in self.member_sha256
        if len({has_zip_path, has_zip_hash, has_zip_member}) != 1:
            raise ValueError("offline review ZIP evidence is incomplete")
        if has_zip_hash and self.member_sha256.get("offline-review.zip") != self.zip_sha256:
            raise ValueError("offline review ZIP evidence is inconsistent")
        try:
            validate_zip_members(self.member_sha256)
        except Exception as exc:
            raise ValueError("offline review member evidence is invalid") from exc
        if any(
            re.fullmatch(r"[a-f0-9]{64}", value) is None for value in self.member_sha256.values()
        ):
            raise ValueError("offline review member hash is invalid")
        return self


def create_offline_review_package(
    *,
    project_dir: Path,
    project_id: str,
    project_name: str,
    source_filename: str,
    source_fingerprint: str,
    pipeline_run_id: str,
    generation: int,
    project_revision_epoch: int,
    project_status: str,
    snapshot_fingerprint: str,
    clips: Sequence[OfflineReviewClipInput],
    include_zip: bool,
    created_at: datetime | None = None,
    publication_fence: Callable[[], None] | None = None,
) -> OfflineReviewPackageResult:
    _validate_package_input(
        project_id=project_id,
        source_fingerprint=source_fingerprint,
        pipeline_run_id=pipeline_run_id,
        generation=generation,
        project_revision_epoch=project_revision_epoch,
        snapshot_fingerprint=snapshot_fingerprint,
        clips=clips,
    )
    try:
        resolved_project = ensure_directory_no_follow(project_dir)
        packages_dir = ensure_directory_no_follow(resolved_project / "offline-review-packages")
    except SecureFileError as exc:
        raise OfflineReviewPackageError("offline review directory is unsafe") from exc

    lock_path = packages_dir / ".offline-review.lock"
    try:
        write_bytes_immutable_no_follow(
            lock_path,
            b"LiveClip offline review package lock\n",
            max_bytes=64,
        )
        lock_file = open_pinned_regular_file(lock_path)
    except SecureFileError as exc:
        raise OfflineReviewPackageError("offline review lock is unavailable") from exc

    with lock_file:
        fcntl.flock(lock_file.descriptor, fcntl.LOCK_EX)
        _cleanup_orphan_attempts(packages_dir)
        version = f"v{_next_version(packages_dir):03d}"
        package_id = f"offline-review-{project_id}-{version}"
        destination = packages_dir / version
        temporary = packages_dir / f".{version}-attempt-{os.urandom(12).hex()}"
        try:
            temporary_identity = create_directory_exclusive_no_follow(temporary)
        except SecureFileError as exc:
            raise OfflineReviewPackageError("offline review attempt could not be created") from exc
        published = False
        try:
            built = _build_package(
                temporary=temporary,
                package_id=package_id,
                version=version,
                project_id=project_id,
                project_name=project_name,
                source_filename=source_filename,
                source_fingerprint=source_fingerprint,
                pipeline_run_id=pipeline_run_id,
                generation=generation,
                project_revision_epoch=project_revision_epoch,
                project_status=project_status,
                snapshot_fingerprint=snapshot_fingerprint,
                clips=clips,
                include_zip=include_zip,
                created_at=(created_at or datetime.now(UTC)).astimezone(UTC),
            )
            with ExitStack() as stack:
                pinned = _capture_members(
                    root=temporary,
                    expected_sha256=built.member_sha256,
                    stack=stack,
                )
                try:
                    if publication_fence is not None:
                        publication_fence()
                    publish_directory_no_replace_no_follow(
                        temporary,
                        destination,
                        pinned_files=pinned,
                    )
                    published = True
                    if publication_fence is not None:
                        publication_fence()
                except SecureFileError as exc:
                    raise OfflineReviewPackageError(
                        "offline review package could not be published atomically"
                    ) from exc
        except Exception:
            try:
                remove_tree_no_follow(
                    destination if published else temporary,
                    required_ancestor=packages_dir,
                    expected_identity=temporary_identity,
                )
            except SecureFileError as cleanup_error:
                raise OfflineReviewPackageError(
                    "failed offline review attempt could not be cleaned safely"
                ) from cleanup_error
            raise
        finally:
            fcntl.flock(lock_file.descriptor, fcntl.LOCK_UN)

    return built.model_copy(
        update={
            "directory": destination,
            "index_path": destination / "index.html",
            "manifest_path": destination / "manifest.json",
            "zip_path": destination / "offline-review.zip" if include_zip else None,
        }
    )


def _validate_package_input(
    *,
    project_id: str,
    source_fingerprint: str,
    pipeline_run_id: str,
    generation: int,
    project_revision_epoch: int,
    snapshot_fingerprint: str,
    clips: Sequence[OfflineReviewClipInput],
) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise OfflineReviewPackageError("project ID is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", source_fingerprint):
        raise OfflineReviewPackageError("source fingerprint is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pipeline_run_id):
        raise OfflineReviewPackageError("pipeline run ID is invalid")
    if generation <= 0:
        raise OfflineReviewPackageError("pipeline generation is invalid")
    if project_revision_epoch < 0:
        raise OfflineReviewPackageError("project revision epoch is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", snapshot_fingerprint):
        raise OfflineReviewPackageError("review snapshot fingerprint is invalid")
    if not clips:
        raise OfflineReviewPackageError("offline review package requires at least one clip")
    if len(clips) > 100:
        raise OfflineReviewPackageError("offline review package supports at most 100 clips")
    if any(clip.proxy_asset_generation != generation for clip in clips):
        raise OfflineReviewPackageError(
            "offline review proxy asset generation differs from the export generation"
        )
    if any(clip.proxy_render_revision_epoch > project_revision_epoch for clip in clips):
        raise OfflineReviewPackageError(
            "offline review proxy revision epoch is ahead of the project"
        )
    identifiers = [clip.clip_id for clip in clips]
    if len(identifiers) != len(set(identifiers)):
        raise OfflineReviewPackageError("offline review clip IDs must be unique")


def _build_package(
    *,
    temporary: Path,
    package_id: str,
    version: str,
    project_id: str,
    project_name: str,
    source_filename: str,
    source_fingerprint: str,
    pipeline_run_id: str,
    generation: int,
    project_revision_epoch: int,
    project_status: str,
    snapshot_fingerprint: str,
    clips: Sequence[OfflineReviewClipInput],
    include_zip: bool,
    created_at: datetime,
) -> OfflineReviewPackageResult:
    clips_dir = ensure_directory_no_follow(temporary / "clips")
    subtitles_dir = ensure_directory_no_follow(temporary / "subtitles")
    descriptions_dir = ensure_directory_no_follow(temporary / "descriptions")
    member_sha256: dict[str, str] = {}
    manifest_clips: list[dict[str, object]] = []
    description_sections: list[str] = []

    for ordinal, clip in enumerate(clips, start=1):
        stem = f"{ordinal:02d}-{safe_filename_component(clip.title)}"
        video_relative = PurePosixPath("clips") / f"{stem}.mp4"
        subtitle_relative = PurePosixPath("subtitles") / f"{stem}.srt"
        description_relative = PurePosixPath("descriptions") / f"{stem}.md"

        video_hash = _copy_verified_video(
            clip.proxy_path,
            clips_dir / video_relative.name,
            expected_sha256=clip.proxy_sha256,
            expected_size=clip.proxy_size_bytes,
        )
        subtitle_payload = captions_to_srt(clip.captions).strip() + "\n"
        description_payload = _clip_markdown(ordinal, clip)
        subtitle_hash = _write_text(
            subtitles_dir / subtitle_relative.name,
            subtitle_payload,
            max_bytes=1_000_000,
        )
        description_hash = _write_text(
            descriptions_dir / description_relative.name,
            description_payload,
            max_bytes=1_000_000,
        )
        member_sha256[video_relative.as_posix()] = video_hash
        member_sha256[subtitle_relative.as_posix()] = subtitle_hash
        member_sha256[description_relative.as_posix()] = description_hash
        description_sections.append(description_payload.rstrip())

        manifest_clips.append(
            {
                "ordinal": ordinal,
                "clip_id": clip.clip_id,
                "candidate_key": clip.candidate_key,
                "edit_plan_revision": clip.edit_plan_revision,
                "title": clip.title,
                "high_impact_sentence": clip.high_impact_sentence,
                "recommendation_reason": clip.recommendation_reason,
                "risk_flags": list(clip.risk_flags),
                "score": clip.score,
                "review_status": clip.review_status.value,
                "source_start_ms": clip.source_start_ms,
                "source_end_ms": clip.source_end_ms,
                "duration_ms": clip.source_end_ms - clip.source_start_ms,
                "source_start": round(clip.source_start_ms / 1_000, 3),
                "source_end": round(clip.source_end_ms / 1_000, 3),
                "duration": round((clip.source_end_ms - clip.source_start_ms) / 1_000, 3),
                "video_filename": video_relative.as_posix(),
                "subtitle_filename": subtitle_relative.as_posix(),
                "description_filename": description_relative.as_posix(),
                "video_sha256": video_hash,
                "video_size_bytes": clip.proxy_size_bytes,
                "proxy_lineage": {
                    "render_job_id": clip.proxy_render_id,
                    "asset_id": clip.proxy_asset_id,
                    "render_spec_fingerprint": clip.proxy_spec_fingerprint,
                    "render_revision_epoch": clip.proxy_render_revision_epoch,
                    "producer_task_id": clip.proxy_producer_task_id,
                    "producer_task_kind": clip.proxy_producer_task_kind,
                    "producer_stage": clip.proxy_producer_stage,
                    "asset_input_fingerprint": clip.proxy_asset_input_fingerprint,
                    "asset_generation": clip.proxy_asset_generation,
                    "asset_edit_plan_revision": clip.edit_plan_revision,
                    "asset_revision_epoch": clip.proxy_asset_revision_epoch,
                },
                "subtitle_sha256": subtitle_hash,
                "description_sha256": description_hash,
                "captions": [cue.model_dump(mode="json") for cue in clip.captions],
                "editor_keywords": [keyword.model_dump(mode="json") for keyword in clip.keywords],
            }
        )

    manifest: dict[str, object] = {
        "schema_version": "liveclip.offline-review-package.v2",
        "package_type": "offline_review",
        "package_id": package_id,
        "package_version": version,
        "created_at": created_at.isoformat(),
        "project_id": project_id,
        "project_name": project_name,
        "project_status_at_export": project_status,
        "pipeline_run_id": pipeline_run_id,
        "generation": generation,
        "project_revision_epoch": project_revision_epoch,
        "snapshot_fingerprint": snapshot_fingerprint,
        "source_filename": Path(source_filename.replace("\\", "/")).name,
        "source_fingerprint": source_fingerprint,
        "clip_count": len(clips),
        "notice": (
            "这是待审核离线快照，不代表切片已批准，也不是 LiveClip 正式最终交付。"
            "视频为无 LiveClip 文字叠加的当前审核代理。"
        ),
        "clips": manifest_clips,
    }

    descriptions_payload = "# LiveClip 高光时刻说明\n\n" + "\n\n---\n\n".join(description_sections)
    readme_payload = _readme(
        project_name=project_name,
        source_filename=Path(source_filename.replace("\\", "/")).name,
        clip_count=len(clips),
        project_revision_epoch=project_revision_epoch,
        version=version,
        project_status=project_status,
    )
    index_payload = _offline_html(
        project_name=project_name,
        source_filename=Path(source_filename.replace("\\", "/")).name,
        package_version=version,
        project_status=project_status,
        clips=tuple(manifest_clips),
    )
    manifest_payload = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    for name, payload, limit in (
        ("README.md", readme_payload, 1_000_000),
        ("descriptions.md", descriptions_payload, 4_000_000),
        ("index.html", index_payload, 4_000_000),
        ("manifest.json", manifest_payload, 4_000_000),
    ):
        member_sha256[name] = _write_text(temporary / name, payload, max_bytes=limit)

    checksums_payload = "".join(
        f"{sha256}  {name}\n" for name, sha256 in sorted(member_sha256.items())
    )
    member_sha256["checksums.sha256"] = _write_text(
        temporary / "checksums.sha256",
        checksums_payload,
        max_bytes=1_000_000,
    )
    manifest_sha256 = member_sha256["manifest.json"]

    zip_sha256: str | None = None
    if include_zip:
        zip_sha256 = _create_verified_zip(
            root=temporary,
            output_path=temporary / "offline-review.zip",
            expected_sha256=dict(member_sha256),
        )
        member_sha256["offline-review.zip"] = zip_sha256

    return OfflineReviewPackageResult(
        package_id=package_id,
        package_version=version,
        directory=temporary,
        index_path=temporary / "index.html",
        manifest_path=temporary / "manifest.json",
        zip_path=temporary / "offline-review.zip" if include_zip else None,
        clip_count=len(clips),
        project_revision_epoch=project_revision_epoch,
        snapshot_fingerprint=snapshot_fingerprint,
        manifest_sha256=manifest_sha256,
        zip_sha256=zip_sha256,
        member_sha256=member_sha256,
    )


def _copy_verified_video(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
) -> str:
    try:
        observed = publish_regular_file_immutable_no_follow(
            source,
            destination,
            remove_source=False,
            expected_sha256=expected_sha256,
        )
    except SecureFileHashMismatch as exc:
        raise OfflineReviewPackageError("review proxy differs from its committed hash") from exc
    except SecureFileError as exc:
        raise OfflineReviewPackageError("review proxy could not be copied safely") from exc
    try:
        size = destination.stat(follow_symlinks=False).st_size
    except OSError as exc:
        raise OfflineReviewPackageError("copied review proxy cannot be inspected") from exc
    if observed != expected_sha256 or size != expected_size:
        raise OfflineReviewPackageError("copied review proxy differs from committed metadata")
    return observed


def _write_text(path: Path, payload: str, *, max_bytes: int) -> str:
    encoded = payload.encode("utf-8")
    if not encoded:
        raise OfflineReviewPackageError("offline review text member cannot be empty")
    try:
        write_text_immutable_no_follow(path, payload, max_bytes=max_bytes)
    except SecureFileError as exc:
        raise OfflineReviewPackageError("offline review text member could not be written") from exc
    return hashlib.sha256(encoded).hexdigest()


def _clip_markdown(ordinal: int, clip: OfflineReviewClipInput) -> str:
    risks = "、".join(clip.risk_flags) if clip.risk_flags else "无"
    keywords = (
        "\n".join(
            f"- {_markdown_text(keyword.text)}：片内 "
            f"{_display_time(keyword.clip_start_ms)}–{_display_time(keyword.clip_end_ms)}；"
            f"源视频 {_display_time(keyword.source_start_ms)}–"
            f"{_display_time(keyword.source_end_ms)}；精度 "
            f"{_markdown_text(keyword.timing_precision.value)}"
            for keyword in clip.keywords
        )
        or "- 无"
    )
    captions = "\n".join(
        f"- {_display_time(cue.start_ms)}–{_display_time(cue.end_ms)}　{_markdown_text(cue.text)}"
        for cue in clip.captions
    )
    return (
        f"# {ordinal:02d}. {_markdown_text(clip.title)}\n\n"
        f"- 高光语句：{_markdown_text(clip.high_impact_sentence)}\n"
        f"- 推荐理由：{_markdown_text(clip.recommendation_reason)}\n"
        f"- 分数：{clip.score:g}\n"
        f"- 源视频位置：{_display_time(clip.source_start_ms)}–"
        f"{_display_time(clip.source_end_ms)}\n"
        f"- 时长：{(clip.source_end_ms - clip.source_start_ms) / 1_000:.3f} 秒\n"
        f"- 审核状态：{clip.review_status.value}\n"
        f"- 风险标签：{_markdown_text(risks)}\n\n"
        "## 编辑关键词（仅供编辑定位）\n\n"
        f"{keywords}\n\n"
        "## 字幕（切片相对时间）\n\n"
        f"{captions}\n"
    )


def _readme(
    *,
    project_name: str,
    source_filename: str,
    clip_count: int,
    project_revision_epoch: int,
    version: str,
    project_status: str,
) -> str:
    return f"""# LiveClip 离线审核包

项目：{_markdown_text(project_name)}

源视频：{_markdown_text(source_filename)}

版本：{version}

切片数量：{clip_count}

项目修订纪元：{project_revision_epoch}

导出时项目状态：{project_status}

## 如何查看

1. 解压后保持目录结构不变。
2. 双击 `index.html`，即可离线播放全部切片并查看标题、高光语句、推荐理由、风险标签、编辑关键词和字幕。
3. `descriptions.md` 汇总全部说明；`descriptions/` 是逐段说明。
4. `subtitles/` 是逐段 SRT；`manifest.json` 供自动化读取；`checksums.sha256` 用于校验文件。

## 状态说明

这是审核代理的离线快照。包内视频没有 LiveClip 生成的标题或字幕叠加；描述和字幕作为独立文件提供。`pending_review` 不等于已批准，本包也不改变 LiveClip 中的审核状态或正式交付状态。
"""


def _offline_html(
    *,
    project_name: str,
    source_filename: str,
    package_version: str,
    project_status: str,
    clips: tuple[dict[str, object], ...],
) -> str:
    rows = "\n".join(_clip_html(clip) for clip in clips)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; media-src 'self' file: blob:; style-src 'unsafe-inline'; img-src 'self' data:">
  <title>{html.escape(project_name)} · LiveClip 离线审核</title>
  <style>
    :root {{ color-scheme: dark; font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif; background: #0b0d12; color: #f5f7fb; }}
    * {{ box-sizing: border-box; }} body {{ margin: 0; }}
    header {{ position: sticky; top: 0; z-index: 2; padding: 22px max(24px, calc((100vw - 1380px)/2)); background: rgba(11,13,18,.94); border-bottom: 1px solid #2a2e39; backdrop-filter: blur(14px); }}
    h1 {{ margin: 0 0 8px; font-size: clamp(24px, 3vw, 40px); }}
    .meta, .muted {{ color: #aeb6c7; }} .notice {{ margin-top: 12px; color: #ffcf70; }}
    main {{ max-width: 1380px; margin: auto; padding: 26px 24px 80px; }}
    article {{ margin-bottom: 28px; padding: 22px; border: 1px solid #2a2e39; border-radius: 18px; background: #151821; }}
    .grid {{ display: grid; grid-template-columns: minmax(280px, 430px) minmax(0, 1fr); gap: 26px; align-items: start; }}
    video {{ width: 100%; max-height: 700px; border-radius: 12px; background: #000; }}
    h2 {{ margin: 0 0 14px; font-size: 25px; }} h3 {{ margin: 22px 0 9px; font-size: 16px; color: #d9deea; }}
    .hook {{ padding: 14px 16px; border-left: 4px solid #7c9cff; background: #1c2335; font-size: 18px; line-height: 1.55; }}
    .facts {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 15px 0; }} .pill {{ padding: 5px 10px; border-radius: 999px; background: #252a36; color: #dce2ef; }}
    p {{ line-height: 1.65; }} .keywords {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .keyword {{ padding: 7px 10px; border-radius: 8px; background: #27304a; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }} td {{ padding: 9px 10px; border-top: 1px solid #303543; vertical-align: top; line-height: 1.5; }} td:first-child {{ width: 190px; color: #9eabc1; white-space: nowrap; }}
    @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} header {{ position: static; }} article {{ padding: 16px; }} td:first-child {{ width: 120px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>{html.escape(project_name)} · 高光时刻</h1>
    <div class="meta">源视频：{html.escape(source_filename)}　包版本：{html.escape(package_version)}　导出状态：{html.escape(project_status)}</div>
    <div class="notice">离线审核快照：切片尚未因此获得批准，视频内没有 LiveClip 生成文字。</div>
  </header>
  <main>{rows}</main>
</body>
</html>
"""


def _clip_html(clip: dict[str, object]) -> str:
    ordinal = cast(int, clip["ordinal"])
    title = html.escape(str(clip["title"]))
    video = html.escape(str(clip["video_filename"]), quote=True)
    hook = html.escape(str(clip["high_impact_sentence"]))
    reason = html.escape(str(clip["recommendation_reason"]))
    review_status = html.escape(str(clip["review_status"]))
    score = cast(float, clip["score"])
    source_start_ms = cast(int, clip["source_start_ms"])
    source_end_ms = cast(int, clip["source_end_ms"])
    risks = cast(list[str], clip["risk_flags"])
    keywords = cast(list[dict[str, object]], clip["editor_keywords"])
    captions = cast(list[dict[str, object]], clip["captions"])
    risk_html = (
        "".join(f'<span class="pill">{html.escape(str(value))}</span>' for value in risks)
        or '<span class="pill">无风险标签</span>'
    )
    keyword_html = (
        "".join(
            f'<span class="keyword">{html.escape(str(value["text"]))} · 片内 '
            f"{_display_time(cast(int, value['clip_start_ms']))}–"
            f"{_display_time(cast(int, value['clip_end_ms']))} · 源视频 "
            f"{_display_time(cast(int, value['source_start_ms']))}–"
            f"{_display_time(cast(int, value['source_end_ms']))} · "
            f"{html.escape(str(value['timing_precision']))}</span>"
            for value in keywords
        )
        or '<span class="muted">无</span>'
    )
    caption_html = "".join(
        f"<tr><td>{_display_time(cast(int, value['start_ms']))}–"
        f"{_display_time(cast(int, value['end_ms']))}</td>"
        f"<td>{html.escape(str(value['text']))}</td></tr>"
        for value in captions
    )
    return f"""
    <article id="clip-{ordinal:02d}">
      <div class="grid">
        <video controls preload="metadata" src="{video}"></video>
        <section>
          <h2>{ordinal:02d}. {title}</h2>
          <div class="hook"><strong>高光语句</strong><br>{hook}</div>
          <div class="facts">
            <span class="pill">评分 {score:g}</span>
            <span class="pill">{review_status}</span>
            <span class="pill">源视频 {_display_time(source_start_ms)}–{_display_time(source_end_ms)}</span>
            <span class="pill">时长 {(source_end_ms - source_start_ms) / 1000:.3f} 秒</span>
          </div>
          <h3>推荐理由</h3><p>{reason}</p>
          <h3>风险标签</h3><div class="facts">{risk_html}</div>
          <h3>编辑关键词（仅供编辑定位）</h3><div class="keywords">{keyword_html}</div>
        </section>
      </div>
      <section><h3>字幕（切片相对时间）</h3><table><tbody>{caption_html}</tbody></table></section>
    </article>"""


def _display_time(value_ms: int) -> str:
    return ms_to_srt(value_ms).replace(",", ".")


def _markdown_text(value: str) -> str:
    """Render untrusted editorial/transcript text inert in common Markdown viewers."""

    escaped = html.escape(value, quote=False)
    for character in "\\`*_{}[]()#+-.!|":
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _next_version(packages_dir: Path) -> int:
    versions: list[int] = []
    for child in packages_dir.iterdir():
        match = re.fullmatch(r"v([0-9]{3})", child.name)
        if match is None:
            continue
        if child.is_symlink() or not child.is_dir():
            raise OfflineReviewPackageError("offline review version entry is unsafe")
        versions.append(int(match.group(1)))
    value = max(versions, default=0) + 1
    if value > 999:
        raise OfflineReviewPackageError("offline review version space is exhausted")
    return value


def _cleanup_orphan_attempts(packages_dir: Path) -> None:
    """Remove only abandoned attempt directories while holding the package lock."""

    pattern = re.compile(r"^\.v[0-9]{3}-attempt-[a-f0-9]{24}$")
    for child in packages_dir.iterdir():
        if pattern.fullmatch(child.name) is None:
            continue
        try:
            metadata = child.stat(follow_symlinks=False)
        except OSError as exc:
            raise OfflineReviewPackageError(
                "offline review orphan attempt cannot be inspected"
            ) from exc
        if child.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise OfflineReviewPackageError("offline review orphan attempt entry is unsafe")
        try:
            removed = remove_tree_no_follow(
                child,
                required_ancestor=packages_dir,
                expected_identity=(metadata.st_dev, metadata.st_ino),
            )
        except SecureFileError as exc:
            raise OfflineReviewPackageError(
                "offline review orphan attempt could not be cleaned safely"
            ) from exc
        if not removed:
            raise OfflineReviewPackageError("offline review orphan attempt changed during cleanup")


def _create_verified_zip(
    *,
    root: Path,
    output_path: Path,
    expected_sha256: dict[str, str],
) -> str:
    names = validate_zip_members(expected_sha256)
    try:
        with ExitStack() as stack:
            pinned = _capture_members(root=root, expected_sha256=expected_sha256, stack=stack)
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
                    _write_zip_member(archive, name, pinned[name])
            output.seal_after_write()
            zip_sha256 = output.sha256()
            _verify_zip(
                PinnedFileEvidence(
                    pinned=output,
                    sha256=zip_sha256,
                    size_bytes=output.metadata.st_size,
                ),
                expected_sha256=expected_sha256,
                expected_sizes={name: evidence.size_bytes for name, evidence in pinned.items()},
            )
            return zip_sha256
    except SecureFileError as exc:
        raise OfflineReviewPackageError("offline review ZIP could not be created safely") from exc


def _capture_members(
    *,
    root: Path,
    expected_sha256: dict[str, str],
    stack: ExitStack,
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
            raise OfflineReviewPackageError(
                "offline review member differs from its expected bytes"
            ) from exc
        stack.callback(evidence.pinned.close)
        pinned[name] = evidence
    return pinned


def _write_zip_member(
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
        raise OfflineReviewPackageError("offline review ZIP member changed while streaming")
    evidence.pinned.validate_binding()


def _verify_zip(
    evidence: PinnedFileEvidence,
    *,
    expected_sha256: dict[str, str],
    expected_sizes: dict[str, int],
) -> None:
    names = validate_zip_members(expected_sha256)
    try:
        with (
            os.fdopen(os.dup(evidence.pinned.descriptor), mode="rb") as input_stream,
            zipfile.ZipFile(input_stream, mode="r") as archive,
        ):
            infos = archive.infolist()
            actual_names = validate_zip_infos(infos, maximum_members=305)
            if actual_names != names:
                raise OfflineReviewPackageError("offline review ZIP member list is inconsistent")
            info_by_name = {info.filename: info for info in infos}
            for name in names:
                if info_by_name[name].file_size != expected_sizes[name]:
                    raise OfflineReviewPackageError(
                        "offline review ZIP member size is inconsistent"
                    )
                if hash_zip_member(archive, name) != expected_sha256[name]:
                    raise OfflineReviewPackageError(
                        "offline review ZIP member hash is inconsistent"
                    )
        evidence.pinned.validate_binding()
    except (OSError, zipfile.BadZipFile) as exc:
        raise OfflineReviewPackageError("offline review ZIP is invalid") from exc
