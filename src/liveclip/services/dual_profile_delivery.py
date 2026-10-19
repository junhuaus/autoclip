from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.delivery.dual_profile_review import (
    DualProfileReviewClipInput,
    DualProfileReviewPackageError,
    DualProfileReviewPackageInput,
    DualProfileReviewPackageResult,
    DualProfileRunProvenance,
    create_dual_profile_review_package,
)
from liveclip.delivery.package import DeliveryError, normalize_srt, source_basename
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.edit_plan import captions_to_srt
from liveclip.domain.keywords import derive_keyword_occurrences
from liveclip.media.secure_files import (
    SecureFileError,
    hash_regular_file_no_follow,
    read_regular_text_no_follow,
)
from liveclip.pipeline.dual_profile import (
    DUAL_PROFILE_ALGORITHM_VERSION,
    CandidateDisposition,
    DualProfileFinalResult,
    DualProfileRunManifest,
    FinalProfileCandidate,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.services.captions import captions_for_clip


class DualProfileDeliveryError(RuntimeError):
    """Validated dual-profile evidence cannot be exported for offline review."""


class DualProfileRenderClipRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    profile: ClipProfile
    variant_group_id: str = Field(default="", max_length=96, pattern=r"^[A-Za-z0-9_-]*$")
    review_status: CandidateDisposition
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    video_path: Path
    video_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subtitle_path: Path
    subtitle_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality_report_path: Path
    contact_sheet_path: Path
    contact_sheet_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    encoder: str = Field(min_length=1, max_length=80)
    render_attempts: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_record(self) -> DualProfileRenderClipRecord:
        if self.end_ms <= self.start_ms or self.duration_ms != self.end_ms - self.start_ms:
            raise ValueError("rendered clip duration is inconsistent")
        if self.review_status not in {
            CandidateDisposition.SELECTED,
            CandidateDisposition.MANUAL_REVIEW,
        }:
            raise ValueError("only selected/manual candidates can be packaged")
        return self


class DualProfileRenderManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(pattern=r"^1$")
    algorithm_version: str = Field(pattern=r"^dual-profile-direct-v1$")
    source_video: str = Field(min_length=1, max_length=255)
    profiles: tuple[ClipProfile, ...] = Field(min_length=1)
    candidate_filter: tuple[str, ...] | None = None
    clip_count: int = Field(ge=1, le=200)
    clips: tuple[DualProfileRenderClipRecord, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_manifest(self) -> DualProfileRenderManifest:
        if self.clip_count != len(self.clips):
            raise ValueError("render manifest clip count is inconsistent")
        identities = [value.candidate_id for value in self.clips]
        if len(identities) != len(set(identities)):
            raise ValueError("render manifest repeats a candidate")
        if len(self.profiles) != len(set(self.profiles)):
            raise ValueError("render manifest repeats a Profile")
        if any(value.profile not in self.profiles for value in self.clips):
            raise ValueError("render manifest contains an undeclared Profile")
        if self.candidate_filter is not None and set(self.candidate_filter) != set(identities):
            raise ValueError("render manifest filter differs from rendered clips")
        return self


def export_dual_profile_review_package(
    *,
    transcript_path: Path,
    final_result_path: Path,
    run_manifest_path: Path,
    render_manifest_path: Path,
    output_dir: Path,
    include_zip: bool = True,
    package_version: str = "v001",
    package_title: str = "LiveClip 双轨切分人工审核",
) -> DualProfileReviewPackageResult:
    """Join exact run/render evidence and publish a friendly offline-review package."""

    try:
        final_text = read_regular_text_no_follow(
            final_result_path,
            max_bytes=128 * 1024 * 1024,
        )
        final = DualProfileFinalResult.model_validate_json(final_text)
        run_text = read_regular_text_no_follow(run_manifest_path, max_bytes=16 * 1024 * 1024)
        run_manifest = DualProfileRunManifest.model_validate_json(run_text)
        run_manifest.validate_against(final)
        render_text = read_regular_text_no_follow(
            render_manifest_path,
            max_bytes=16 * 1024 * 1024,
        )
        render_manifest = DualProfileRenderManifest.model_validate_json(render_text)
    except (SecureFileError, ValueError) as exc:
        raise DualProfileDeliveryError("dual-profile package evidence is invalid") from exc
    if final.algorithm_version != render_manifest.algorithm_version:
        raise DualProfileDeliveryError("render manifest algorithm differs from final result")
    if render_manifest.profiles != final.executed_profiles:
        raise DualProfileDeliveryError("render manifest Profiles differ from executed Profiles")

    transcript_sha256, _ = _hash_file(transcript_path, label="transcript")
    if transcript_sha256 != final.source_hash:
        raise DualProfileDeliveryError("transcript hash differs from the evaluated source")
    try:
        transcript = load_srt_transcript(transcript_path)
    except (SecureFileError, ValueError) as exc:
        raise DualProfileDeliveryError("dual-profile transcript is invalid") from exc

    final_sha256, _ = _hash_file(final_result_path, label="final result")
    render_sha256, _ = _hash_file(render_manifest_path, label="render manifest")
    run_sha256, _ = _hash_file(run_manifest_path, label="run manifest")
    render_root = _safe_render_root(render_manifest_path)
    candidates = _eligible_candidate_map(final)
    package_clips: list[DualProfileReviewClipInput] = []
    profile_order = {profile: index for index, profile in enumerate(final.executed_profiles)}
    ordered_renders = sorted(
        render_manifest.clips,
        key=lambda value: (profile_order[value.profile], value.start_ms, value.candidate_id),
    )
    for rendered in ordered_renders:
        candidate = candidates.get(rendered.candidate_id)
        if candidate is None:
            raise DualProfileDeliveryError(
                f"rendered candidate is not selected/manual final evidence: {rendered.candidate_id}"
            )
        _validate_candidate_binding(candidate, rendered)
        video_path = _confined_file(rendered.video_path, root=render_root, label="video")
        subtitle_path = _confined_file(rendered.subtitle_path, root=render_root, label="subtitle")
        contact_path = _confined_file(
            rendered.contact_sheet_path,
            root=render_root,
            label="contact sheet",
        )
        quality_path = _confined_file(
            rendered.quality_report_path,
            root=render_root,
            label="quality report",
        )
        video_hash, video_size = _hash_file(video_path, label="video")
        subtitle_hash, subtitle_size = _hash_file(subtitle_path, label="subtitle")
        contact_hash, contact_size = _hash_file(contact_path, label="contact sheet")
        quality_hash, quality_size = _hash_file(quality_path, label="quality report")
        if video_hash != rendered.video_sha256:
            raise DualProfileDeliveryError("rendered video differs from its manifest hash")
        if subtitle_hash != rendered.subtitle_sha256:
            raise DualProfileDeliveryError("rendered subtitle differs from its manifest hash")
        if contact_hash != rendered.contact_sheet_sha256:
            raise DualProfileDeliveryError("contact sheet differs from its manifest hash")

        captions = captions_for_clip(
            transcript.segments,
            source_start_ms=candidate.start_ms,
            source_end_ms=candidate.end_ms,
        )
        try:
            subtitle_text = read_regular_text_no_follow(subtitle_path, max_bytes=2 * 1024 * 1024)
            if normalize_srt(subtitle_text) != normalize_srt(captions_to_srt(captions)):
                raise DualProfileDeliveryError("rendered subtitle differs from transcript evidence")
        except (SecureFileError, DeliveryError) as exc:
            raise DualProfileDeliveryError("rendered subtitle is invalid") from exc
        _validate_quality_report(quality_path, expected_video_sha256=video_hash)
        keywords = derive_keyword_occurrences(
            captions,
            source_start_ms=candidate.start_ms,
            source_end_ms=candidate.end_ms,
            title=candidate.title,
            hook=candidate.hook,
            reason=candidate.review_reason,
            segments=transcript.segments,
        )
        package_clips.append(
            DualProfileReviewClipInput(
                candidate_id=candidate.candidate_id,
                profile=candidate.profile,
                variant_group_id=candidate.variant_group_id,
                source_candidate_ids=candidate.source_candidate_ids,
                source_window_ids=candidate.source_window_ids,
                start_cue_id=candidate.start_cue_id,
                end_cue_id=candidate.end_cue_id,
                start_ms=candidate.start_ms,
                end_ms=candidate.end_ms,
                duration_ms=candidate.duration_ms,
                title=candidate.title,
                hook=candidate.hook,
                summary=candidate.summary,
                review_reason=candidate.review_reason,
                score=candidate.score,
                review_status=cast(
                    Literal["selected", "manual_review"],
                    candidate.review_status.value,
                ),
                quality_flags=tuple(value.value for value in candidate.quality_flags),
                risk_tags=tuple(value.value for value in candidate.risk_tags),
                evidence_cue_ids=candidate.evidence_cue_ids,
                keywords=keywords,
                subtitle_text=normalize_srt(subtitle_text),
                video_path=video_path,
                video_sha256=video_hash,
                video_size_bytes=video_size,
                subtitle_path=subtitle_path,
                subtitle_sha256=subtitle_hash,
                subtitle_size_bytes=subtitle_size,
                contact_sheet_path=contact_path,
                contact_sheet_sha256=contact_hash,
                contact_sheet_size_bytes=contact_size,
                quality_report_path=quality_path,
                quality_report_sha256=quality_hash,
                quality_report_size_bytes=quality_size,
            )
        )

    snapshot_fingerprint = _snapshot_fingerprint(
        final=final,
        final_sha256=final_sha256,
        render_sha256=render_sha256,
        run_sha256=run_sha256,
        clips=tuple(package_clips),
    )
    package = DualProfileReviewPackageInput(
        package_id=f"dual_profile_review_{snapshot_fingerprint[:20]}",
        package_version=package_version,
        package_title=package_title,
        source_filename=source_basename(render_manifest.source_video),
        source_hash=final.source_hash,
        algorithm_version=DUAL_PROFILE_ALGORITHM_VERSION,
        requested_profiles=final.requested_profiles,
        executed_profiles=final.executed_profiles,
        snapshot_fingerprint=snapshot_fingerprint,
        final_result_sha256=final_sha256,
        render_manifest_sha256=render_sha256,
        run_manifest_sha256=run_sha256,
        candidate_filter=render_manifest.candidate_filter,
        run_provenance=DualProfileRunProvenance(
            provider=run_manifest.provider,
            model=run_manifest.model,
            prompt_hashes=run_manifest.prompt_hashes,
            calls=run_manifest.calls,
            input_tokens=run_manifest.input_tokens,
            output_tokens=run_manifest.output_tokens,
            latency_ms=run_manifest.latency_ms,
            cache_hits=run_manifest.cache_hits,
            retry_count=run_manifest.retry_count,
            repair_count=run_manifest.repair_count,
        ),
        clips=tuple(package_clips),
    )
    try:
        return create_dual_profile_review_package(
            output_dir=output_dir,
            package=package,
            final_result_path=final_result_path,
            render_manifest_path=render_manifest_path,
            run_manifest_path=run_manifest_path,
            include_zip=include_zip,
        )
    except DualProfileReviewPackageError as exc:
        raise DualProfileDeliveryError(
            "dual-profile review package could not be published"
        ) from exc


def _eligible_candidate_map(
    final: DualProfileFinalResult,
) -> dict[str, FinalProfileCandidate]:
    values = {
        candidate.candidate_id: candidate
        for profile in final.executed_profiles
        for candidate in (
            *final.profiles[profile].selected,
            *final.profiles[profile].manual_review,
        )
    }
    expected = sum(
        len(final.profiles[profile].selected) + len(final.profiles[profile].manual_review)
        for profile in final.executed_profiles
    )
    if len(values) != expected:
        raise DualProfileDeliveryError("eligible candidate IDs are not globally unique")
    return values


def _validate_candidate_binding(
    candidate: FinalProfileCandidate,
    rendered: DualProfileRenderClipRecord,
) -> None:
    expected = (
        candidate.profile,
        candidate.variant_group_id,
        candidate.review_status,
        candidate.start_ms,
        candidate.end_ms,
        candidate.duration_ms,
    )
    observed = (
        rendered.profile,
        rendered.variant_group_id,
        rendered.review_status,
        rendered.start_ms,
        rendered.end_ms,
        rendered.duration_ms,
    )
    if observed != expected:
        raise DualProfileDeliveryError(
            f"render evidence differs from final candidate: {candidate.candidate_id}"
        )


def _safe_render_root(render_manifest_path: Path) -> Path:
    try:
        root = render_manifest_path.parent.resolve(strict=True)
    except OSError as exc:
        raise DualProfileDeliveryError("render manifest directory is unavailable") from exc
    if not root.is_dir():
        raise DualProfileDeliveryError("render manifest parent is not a directory")
    return root


def _confined_file(path: Path, *, root: Path, label: str) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise DualProfileDeliveryError(f"{label} path is not an absolute system path")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise DualProfileDeliveryError(f"{label} path escapes the render directory") from exc
    if not resolved.is_file():
        raise DualProfileDeliveryError(f"{label} path is not a regular file")
    return path


def _hash_file(path: Path, *, label: str) -> tuple[str, int]:
    try:
        return hash_regular_file_no_follow(path)
    except SecureFileError as exc:
        raise DualProfileDeliveryError(f"{label} could not be verified safely") from exc


def _validate_quality_report(path: Path, *, expected_video_sha256: str) -> None:
    try:
        payload = json.loads(read_regular_text_no_follow(path, max_bytes=4 * 1024 * 1024))
    except (SecureFileError, json.JSONDecodeError) as exc:
        raise DualProfileDeliveryError("render quality report is invalid") from exc
    if not isinstance(payload, dict):
        raise DualProfileDeliveryError("render quality report must be an object")
    if payload.get("media_sha256") != expected_video_sha256:
        raise DualProfileDeliveryError("quality report refers to different video bytes")
    if payload.get("automatic_status") != "passed" or payload.get("full_decode") != "passed":
        raise DualProfileDeliveryError("only automatically validated renders can be packaged")


def _snapshot_fingerprint(
    *,
    final: DualProfileFinalResult,
    final_sha256: str,
    render_sha256: str,
    run_sha256: str,
    clips: tuple[DualProfileReviewClipInput, ...],
) -> str:
    payload = {
        "schema_version": "liveclip.dual-profile-offline-review-snapshot.v1",
        "source_hash": final.source_hash,
        "requested_profiles": [value.value for value in final.requested_profiles],
        "executed_profiles": [value.value for value in final.executed_profiles],
        "final_result_sha256": final_sha256,
        "render_manifest_sha256": render_sha256,
        "run_manifest_sha256": run_sha256,
        "clips": [
            {
                "candidate_id": clip.candidate_id,
                "profile": clip.profile.value,
                "start_ms": clip.start_ms,
                "end_ms": clip.end_ms,
                "review_status": clip.review_status,
                "video_sha256": clip.video_sha256,
                "subtitle_sha256": clip.subtitle_sha256,
                "contact_sheet_sha256": clip.contact_sheet_sha256,
                "quality_report_sha256": clip.quality_report_sha256,
            }
            for clip in clips
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "DualProfileDeliveryError",
    "DualProfileRenderClipRecord",
    "DualProfileRenderManifest",
    "export_dual_profile_review_package",
]
