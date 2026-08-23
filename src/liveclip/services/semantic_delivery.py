from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.delivery.package import DeliveryClipInput, DeliveryResult, create_delivery
from liveclip.domain.edit_plan import Effect, Layout, caption_cues_from_transcript_segments
from liveclip.domain.keywords import derive_keyword_occurrences
from liveclip.domain.time import ms_to_srt
from liveclip.domain.transcript import TranscriptSegment
from liveclip.media.ingest import ingest_source
from liveclip.media.secure_files import (
    create_directory_exclusive_no_follow,
    ensure_directory_no_follow,
    hash_regular_file_no_follow,
    read_regular_text_no_follow,
    write_text_immutable_no_follow,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.renderer.ffmpeg import RenderRequest, render_clip


class SemanticDeliveryError(RuntimeError):
    """A reviewed semantic plan cannot be rendered into a safe delivery."""


class ReviewedSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    start_cue_id: int | None = Field(default=None, ge=1)
    end_cue_id: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_optional_boundary(self) -> ReviewedSelection:
        if (self.start_cue_id is None) != (self.end_cue_id is None):
            raise ValueError("reviewed cue boundaries must be supplied together")
        if (
            self.start_cue_id is not None
            and self.end_cue_id is not None
            and self.end_cue_id < self.start_cue_id
        ):
            raise ValueError("reviewed end cue must not precede start cue")
        return self


class ReviewedRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    reason: str = Field(min_length=1, max_length=1_000)


class OfflineSemanticReview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=80)
    selections: tuple[ReviewedSelection, ...] = Field(min_length=1, max_length=100)
    rejected: tuple[ReviewedRejection, ...] = Field(default_factory=tuple, max_length=100)
    notes: tuple[str, ...] = Field(default_factory=tuple, max_length=100)

    @model_validator(mode="after")
    def validate_clip_partition(self) -> OfflineSemanticReview:
        selected = [item.clip_id for item in self.selections]
        rejected = [item.clip_id for item in self.rejected]
        if len(selected) != len(set(selected)) or len(rejected) != len(set(rejected)):
            raise ValueError("offline review clip IDs must be unique")
        if set(selected) & set(rejected):
            raise ValueError("a clip cannot be both selected and rejected")
        return self


class SemanticDeliveryResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, arbitrary_types_allowed=True
    )

    project_dir: Path
    review_manifest_path: Path
    delivery: DeliveryResult
    rendered_clip_count: int = Field(gt=0)
    new_render_count: int = Field(ge=0)
    reused_render_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_render_counts(self) -> SemanticDeliveryResult:
        if self.new_render_count + self.reused_render_count != self.rendered_clip_count:
            raise ValueError("new and reused render counts must explain every delivered clip")
        return self


def render_reviewed_semantic_delivery(
    *,
    source_path: Path,
    transcript_path: Path,
    plan_path: Path,
    review_path: Path,
    output_dir: Path,
    allowed_media_roots: tuple[Path, ...],
    reuse_render_manifest_path: Path | None = None,
    minimum_duration_ms: int = 45_000,
    maximum_duration_ms: int = 90_000,
) -> SemanticDeliveryResult:
    """Apply an auditable human/agent review to a plan, render, and package it.

    Boundary overrides are data in the review artifact. The implementation only
    validates cue identity, duration, source bounds, and review completeness; it
    contains no source-specific semantic or timestamp rules.
    """

    if minimum_duration_ms <= 0 or maximum_duration_ms < minimum_duration_ms:
        raise SemanticDeliveryError("delivery duration limits are invalid")
    transcript = load_srt_transcript(transcript_path)
    plan_sha256, _ = hash_regular_file_no_follow(plan_path)
    plan = _load_json_object(plan_path, label="semantic plan")
    review_raw = read_regular_text_no_follow(review_path, max_bytes=4 * 1024 * 1024)
    review = OfflineSemanticReview.model_validate_json(review_raw)
    if review.plan_sha256 != plan_sha256:
        raise SemanticDeliveryError("offline review does not match the exact semantic plan")

    plan_items = _plan_items(plan)
    known_ids = set(plan_items)
    classified_ids = {item.clip_id for item in review.selections} | {
        item.clip_id for item in review.rejected
    }
    if classified_ids != known_ids:
        missing = sorted(known_ids - classified_ids)
        unknown = sorted(classified_ids - known_ids)
        raise SemanticDeliveryError(
            f"offline review must classify every kept clip (missing={missing}, unknown={unknown})"
        )

    source = ingest_source(source_path, allowed_roots=allowed_media_roots)
    reusable = _load_reusable_renders(
        reuse_render_manifest_path,
        source_sha256=source.sha256,
    )
    create_directory_exclusive_no_follow(output_dir)
    renders_dir = ensure_directory_no_follow(output_dir / "renders")
    ensure_directory_no_follow(output_dir / "deliveries")
    cue_by_id = {index: cue for index, cue in enumerate(transcript.segments, start=1)}
    rendered: list[DeliveryClipInput] = []
    audit_clips: list[dict[str, object]] = []
    reused_render_count = 0
    for review_item in review.selections:
        planned = plan_items[review_item.clip_id]
        clip_payload = _required_object(planned, "clip")
        planned_start = _required_int(clip_payload, "start_cue_id")
        planned_end = _required_int(clip_payload, "end_cue_id")
        start_cue_id = review_item.start_cue_id or planned_start
        end_cue_id = review_item.end_cue_id or planned_end
        try:
            start_cue = cue_by_id[start_cue_id]
            end_cue = cue_by_id[end_cue_id]
        except KeyError as exc:
            raise SemanticDeliveryError("reviewed boundary references an unknown cue") from exc
        start_ms = start_cue.start_ms
        end_ms = end_cue.end_ms
        duration_ms = end_ms - start_ms
        if not minimum_duration_ms <= duration_ms <= maximum_duration_ms:
            raise SemanticDeliveryError(
                f"reviewed clip {review_item.clip_id} violates delivery duration limits"
            )
        if end_ms > source.duration_ms:
            raise SemanticDeliveryError("reviewed clip exceeds source media duration")
        title = review_item.title or _required_text(clip_payload, "title")
        hook = _optional_text(clip_payload, "hook") or title
        reason = _optional_text(clip_payload, "review_reason") or review_item.reason
        risk_flags = _risk_flag_types(clip_payload)
        score = _required_number(planned, "final_score")
        reusable_item = reusable.get(review_item.clip_id)
        reused_from: str | None = None
        if reusable_item is not None and reusable_item[0:2] == (start_ms, end_ms):
            reused_path, expected_sha256, encoder = reusable_item[2:5]
            actual_sha256, _ = hash_regular_file_no_follow(reused_path)
            if actual_sha256 != expected_sha256:
                raise SemanticDeliveryError("reusable render no longer matches its audit hash")
            final_video_path = reused_path
            final_video_sha256 = actual_sha256
            reused_from = str(reuse_render_manifest_path)
            reused_render_count += 1
        else:
            output_path = renders_dir / f"{review_item.clip_id}.mp4"
            result = render_clip(
                RenderRequest(
                    source_path=source.resolved_path,
                    output_path=output_path,
                    source_start_ms=start_ms,
                    source_end_ms=end_ms,
                    width=source.display_width,
                    height=source.display_height,
                    layout=Layout.CENTER_CROP,
                    effect=Effect.NONE,
                    video_stream_index=source.video_stream_index,
                    audio_stream_index=source.audio_stream_index,
                )
            )
            final_video_path = result.output_path
            final_video_sha256 = result.sha256
            encoder = result.encoder
        subtitle = _clip_srt(
            transcript_segments=transcript.segments,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        captions = caption_cues_from_transcript_segments(
            transcript.segments,
            source_start_ms=start_ms,
            source_end_ms=end_ms,
        )
        keywords = derive_keyword_occurrences(
            captions,
            source_start_ms=start_ms,
            source_end_ms=end_ms,
            title=title,
            hook=hook,
            reason=reason,
            segments=transcript.segments,
        )
        revision = 2 if (start_cue_id, end_cue_id) != (planned_start, planned_end) else 1
        rendered.append(
            DeliveryClipInput(
                clip_id=review_item.clip_id,
                edit_plan_revision=revision,
                render_revision=revision,
                title=title,
                hook=hook,
                reason=reason,
                risk_flags=risk_flags,
                keywords=keywords,
                source_start_ms=start_ms,
                source_end_ms=end_ms,
                score=score,
                review_status="approved",
                render_status="succeeded",
                final_video_path=final_video_path,
                final_video_sha256=final_video_sha256,
                subtitle_srt=subtitle,
            )
        )
        audit_clips.append(
            {
                "clip_id": review_item.clip_id,
                "title": title,
                "hook": hook,
                "reason": reason,
                "risk_flags": list(risk_flags),
                "keywords": [keyword.model_dump(mode="json") for keyword in keywords],
                "source_start_ms": start_ms,
                "source_end_ms": end_ms,
                "duration_ms": duration_ms,
                "planned_start_cue_id": planned_start,
                "planned_end_cue_id": planned_end,
                "reviewed_start_cue_id": start_cue_id,
                "reviewed_end_cue_id": end_cue_id,
                "boundary_changed": (start_cue_id, end_cue_id) != (planned_start, planned_end),
                "review_reason": review_item.reason,
                "render_sha256": final_video_sha256,
                "encoder": encoder,
                "reused_from": reused_from,
            }
        )

    review_sha256, _ = hash_regular_file_no_follow(review_path)
    delivery = create_delivery(
        project_dir=output_dir,
        project_id="semantic_review",
        source_filename=source.filename,
        source_fingerprint=source.sha256,
        clips=tuple(rendered),
        include_zip=True,
        snapshot_fingerprint=review_sha256,
    )
    review_manifest_path = output_dir / "reviewed-render-manifest.json"
    manifest = {
        "schema_version": "1",
        "created_at": datetime.now(UTC).isoformat(),
        "source_filename": source.filename,
        "source_sha256": source.sha256,
        "transcript_sha256": hash_regular_file_no_follow(transcript_path)[0],
        "plan_sha256": plan_sha256,
        "review_sha256": review_sha256,
        "reviewer": review.reviewer,
        "clips": audit_clips,
        "rejected": [item.model_dump(mode="json") for item in review.rejected],
        "notes": list(review.notes),
        "delivery": {
            "directory": str(delivery.directory),
            "manifest_path": str(delivery.manifest_path),
            "zip_path": str(delivery.zip_path) if delivery.zip_path else None,
            "manifest_sha256": delivery.manifest_sha256,
            "zip_sha256": delivery.zip_sha256,
        },
    }
    write_text_immutable_no_follow(
        review_manifest_path,
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        max_bytes=4 * 1024 * 1024,
    )
    return SemanticDeliveryResult(
        project_dir=output_dir,
        review_manifest_path=review_manifest_path,
        delivery=delivery,
        rendered_clip_count=len(rendered),
        new_render_count=len(rendered) - reused_render_count,
        reused_render_count=reused_render_count,
    )


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    raw = read_regular_text_no_follow(path, max_bytes=32 * 1024 * 1024)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SemanticDeliveryError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SemanticDeliveryError(f"{label} must be a JSON object")
    return payload


def _load_reusable_renders(
    manifest_path: Path | None,
    *,
    source_sha256: str,
) -> dict[str, tuple[int, int, Path, str, str]]:
    if manifest_path is None:
        return {}
    manifest = _load_json_object(manifest_path, label="reusable render manifest")
    if manifest.get("source_sha256") != source_sha256:
        raise SemanticDeliveryError("reusable renders belong to a different source")
    raw_clips = manifest.get("clips")
    if not isinstance(raw_clips, list):
        raise SemanticDeliveryError("reusable render manifest clips must be an array")
    render_root = manifest_path.parent / "renders"
    result: dict[str, tuple[int, int, Path, str, str]] = {}
    for raw_clip in raw_clips:
        if not isinstance(raw_clip, dict):
            raise SemanticDeliveryError("reusable render entry must be an object")
        clip_id = _required_text(raw_clip, "clip_id")
        if clip_id in result:
            raise SemanticDeliveryError("reusable render clip IDs must be unique")
        sha256 = _required_text(raw_clip, "render_sha256")
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise SemanticDeliveryError("reusable render hash must be lowercase SHA-256")
        result[clip_id] = (
            _required_int(raw_clip, "source_start_ms"),
            _required_int(raw_clip, "source_end_ms"),
            render_root / f"{clip_id}.mp4",
            sha256,
            _required_text(raw_clip, "encoder"),
        )
    return result


def _plan_items(plan: dict[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for group_name in ("selected", "manual_review"):
        raw_group = plan.get(group_name)
        if not isinstance(raw_group, list):
            raise SemanticDeliveryError(f"semantic plan {group_name} must be an array")
        for raw_item in raw_group:
            if not isinstance(raw_item, dict):
                raise SemanticDeliveryError("semantic plan clip must be an object")
            clip = _required_object(raw_item, "clip")
            clip_id = _required_text(clip, "clip_id")
            if clip_id in result:
                raise SemanticDeliveryError("semantic plan clip IDs must be unique")
            result[clip_id] = raw_item
    if not result:
        raise SemanticDeliveryError("semantic plan has no kept clips")
    return result


def _clip_srt(
    *, transcript_segments: tuple[TranscriptSegment, ...], start_ms: int, end_ms: int
) -> str:
    rows: list[str] = []
    index = 0
    for segment in transcript_segments:
        segment_start = segment.start_ms
        segment_end = segment.end_ms
        if segment_end <= start_ms or segment_start >= end_ms:
            continue
        index += 1
        relative_start = max(segment_start, start_ms) - start_ms
        relative_end = min(segment_end, end_ms) - start_ms
        rows.extend(
            [
                str(index),
                f"{ms_to_srt(relative_start)} --> {ms_to_srt(relative_end)}",
                segment.text,
                "",
            ]
        )
    if not rows:
        raise SemanticDeliveryError("reviewed clip has no subtitle cues")
    return "\n".join(rows)


def _required_object(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise SemanticDeliveryError(f"{key} must be an object")
    return value


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SemanticDeliveryError(f"{key} must be non-empty text")
    return value


def _optional_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def _risk_flag_types(payload: dict[str, object]) -> tuple[str, ...]:
    raw_risks = payload.get("risks", [])
    if not isinstance(raw_risks, list):
        return ()
    values: list[str] = []
    for raw_risk in raw_risks:
        if isinstance(raw_risk, str) and raw_risk.strip():
            values.append(raw_risk.strip())
        elif isinstance(raw_risk, dict):
            risk_type = raw_risk.get("type")
            if isinstance(risk_type, str) and risk_type.strip():
                values.append(risk_type.strip())
    return tuple(dict.fromkeys(values))


def _required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SemanticDeliveryError(f"{key} must be an integer")
    return value


def _required_number(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SemanticDeliveryError(f"{key} must be a number")
    return float(value)


__all__ = [
    "OfflineSemanticReview",
    "ReviewedRejection",
    "ReviewedSelection",
    "SemanticDeliveryError",
    "SemanticDeliveryResult",
    "render_reviewed_semantic_delivery",
]
