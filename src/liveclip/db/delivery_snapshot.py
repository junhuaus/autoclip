from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Connection

from liveclip.db.models import (
    AssetRow,
    CandidateClipRow,
    EditPlanRevisionRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
)
from liveclip.domain.state_transitions import AssetStatus, RenderStatus, ReviewStatus


class DeliverySetError(RuntimeError):
    """The current approved clip set is incomplete or not deliverable."""


@dataclass(frozen=True, slots=True)
class EligibleDeliveryClip:
    clip_id: str
    edit_plan_revision_id: str
    render_job_id: str
    render_spec_fingerprint: str
    edit_plan_revision: int
    title: str
    source_start_ms: int
    source_end_ms: int
    score: float
    decision_id: str
    video_asset_id: str
    video_relative_path: str
    video_sha256: str
    subtitle_asset_id: str
    subtitle_relative_path: str
    subtitle_sha256: str


@dataclass(frozen=True, slots=True)
class EligibleDeliverySet:
    project_id: str
    run_id: str
    generation: int
    revision_epoch: int
    source_filename: str
    source_fingerprint: str
    fingerprint: str
    clips: tuple[EligibleDeliveryClip, ...]


def load_eligible_delivery_set(
    connection: Connection,
    project_id: str,
) -> EligibleDeliverySet:
    project = connection.execute(
        select(
            ProjectRow.current_pipeline_run_id,
            ProjectRow.current_generation,
            ProjectRow.revision_epoch,
            SourceMediaRow.filename,
            SourceMediaRow.sha256,
        )
        .join(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
        .where(ProjectRow.id == project_id)
    ).one_or_none()
    if project is None or project.current_pipeline_run_id is None:
        raise DeliverySetError("project source and current run are not available")
    run_id = str(project.current_pipeline_run_id)
    candidates = connection.execute(
        select(
            CandidateClipRow.id,
            CandidateClipRow.current_revision,
            CandidateClipRow.rank,
            EditPlanRevisionRow.id.label("revision_id"),
            EditPlanRevisionRow.title,
            EditPlanRevisionRow.source_start_ms,
            EditPlanRevisionRow.source_end_ms,
            EditPlanRevisionRow.score,
        )
        .join(
            EditPlanRevisionRow,
            (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
            & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
        )
        .where(
            CandidateClipRow.project_id == project_id,
            CandidateClipRow.pipeline_run_id == run_id,
            CandidateClipRow.selected_for_review.is_(True),
        )
        .order_by(CandidateClipRow.rank, CandidateClipRow.id)
    ).all()
    eligible: list[EligibleDeliveryClip] = []
    for candidate in candidates:
        decision = connection.execute(
            select(ReviewDecisionRow.id, ReviewDecisionRow.status)
            .where(ReviewDecisionRow.edit_plan_revision_id == candidate.revision_id)
            .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
            .limit(1)
        ).one_or_none()
        if decision is None or decision.status != ReviewStatus.APPROVED.value:
            continue
        render = connection.execute(
            select(
                RenderJobRow.id,
                RenderJobRow.spec_fingerprint,
                RenderJobRow.revision_epoch,
                RenderJobRow.asset_id,
                RenderJobRow.subtitle_asset_id,
                RenderJobRow.quality_report_asset_id,
                RenderJobRow.contact_sheet_asset_id,
            )
            .where(
                RenderJobRow.candidate_clip_id == candidate.id,
                RenderJobRow.edit_plan_revision_id == candidate.revision_id,
                RenderJobRow.edit_plan_revision == candidate.current_revision,
                RenderJobRow.kind == "final",
                RenderJobRow.status == RenderStatus.SUCCEEDED.value,
            )
            .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
            .limit(1)
        ).one_or_none()
        if (
            render is None
            or render.asset_id is None
            or render.subtitle_asset_id is None
            or render.quality_report_asset_id is None
            or render.contact_sheet_asset_id is None
        ):
            raise DeliverySetError("an approved clip lacks its current successful final render")
        asset_ids = (
            str(render.asset_id),
            str(render.subtitle_asset_id),
            str(render.quality_report_asset_id),
            str(render.contact_sheet_asset_id),
        )
        assets = connection.execute(
            select(
                AssetRow.id,
                AssetRow.kind,
                AssetRow.relative_path,
                AssetRow.sha256,
                AssetRow.size_bytes,
                AssetRow.generation,
                AssetRow.candidate_clip_id,
                AssetRow.edit_plan_revision,
                AssetRow.revision_epoch,
                AssetRow.input_fingerprint,
                AssetRow.validation_json,
            ).where(
                AssetRow.id.in_(asset_ids),
                AssetRow.project_id == project_id,
                AssetRow.status == AssetStatus.COMMITTED.value,
            )
        ).all()
        by_id = {str(asset.id): asset for asset in assets}
        video = by_id.get(str(render.asset_id))
        subtitle = by_id.get(str(render.subtitle_asset_id))
        quality = by_id.get(str(render.quality_report_asset_id))
        contact = by_id.get(str(render.contact_sheet_asset_id))
        if video is None or subtitle is None or quality is None or contact is None:
            raise DeliverySetError("an approved clip has missing final render assets")
        expected_kinds = {
            str(render.asset_id): "final_video",
            str(render.subtitle_asset_id): "clip_subtitle_srt",
            str(render.quality_report_asset_id): "render_quality_report",
            str(render.contact_sheet_asset_id): "render_contact_sheet",
        }
        if any(
            str(asset.kind) != expected_kinds[str(asset.id)]
            or not asset.sha256
            or int(asset.size_bytes or 0) <= 0
            or asset.generation is None
            or int(asset.generation) != int(project.current_generation)
            or str(asset.candidate_clip_id) != str(candidate.id)
            or asset.edit_plan_revision is None
            or int(asset.edit_plan_revision) != int(candidate.current_revision)
            or asset.revision_epoch is None
            or int(asset.revision_epoch) != int(render.revision_epoch)
            or str(asset.input_fingerprint) != str(render.spec_fingerprint)
            or not isinstance(asset.validation_json, dict)
            for asset in (video, subtitle, quality, contact)
        ):
            raise DeliverySetError("an approved clip final render assets are stale or invalid")
        if (
            video.validation_json.get("full_decode") != "passed"
            or subtitle.validation_json.get("timeline") != "clip_relative_ms"
            or quality.validation_json.get("automatic_status") != "passed"
            or isinstance(contact.validation_json.get("frames"), bool)
            or not isinstance(contact.validation_json.get("frames"), int)
            or int(contact.validation_json["frames"]) < 3
        ):
            raise DeliverySetError("an approved clip final render quality contract is invalid")
        eligible.append(
            EligibleDeliveryClip(
                clip_id=str(candidate.id),
                edit_plan_revision_id=str(candidate.revision_id),
                render_job_id=str(render.id),
                render_spec_fingerprint=str(render.spec_fingerprint),
                edit_plan_revision=int(candidate.current_revision),
                title=str(candidate.title),
                source_start_ms=int(candidate.source_start_ms),
                source_end_ms=int(candidate.source_end_ms),
                score=float(candidate.score),
                decision_id=str(decision.id),
                video_asset_id=str(video.id),
                video_relative_path=str(video.relative_path),
                video_sha256=str(video.sha256),
                subtitle_asset_id=str(subtitle.id),
                subtitle_relative_path=str(subtitle.relative_path),
                subtitle_sha256=str(subtitle.sha256),
            )
        )
    if not eligible:
        raise DeliverySetError("delivery requires at least one approved clip")
    payload = {
        "schema_version": "delivery-set-v2",
        "manifest_schema_version": "1",
        "packager": "liveclip-delivery-v1",
        "project_id": project_id,
        "run_id": run_id,
        "generation": int(project.current_generation),
        "source_filename": str(project.filename),
        "source_fingerprint": str(project.sha256),
        "clips": [
            {
                "clip_id": clip.clip_id,
                "revision_id": clip.edit_plan_revision_id,
                "revision": clip.edit_plan_revision,
                "decision_id": clip.decision_id,
                "title": clip.title,
                "source_start_ms": clip.source_start_ms,
                "source_end_ms": clip.source_end_ms,
                "score": clip.score,
                "render_id": clip.render_job_id,
                "render_spec_fingerprint": clip.render_spec_fingerprint,
                "video_asset_id": clip.video_asset_id,
                "video_sha256": clip.video_sha256,
                "subtitle_asset_id": clip.subtitle_asset_id,
                "subtitle_sha256": clip.subtitle_sha256,
            }
            for clip in eligible
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return EligibleDeliverySet(
        project_id=project_id,
        run_id=run_id,
        generation=int(project.current_generation),
        revision_epoch=int(project.revision_epoch),
        source_filename=str(project.filename),
        source_fingerprint=str(project.sha256),
        fingerprint=fingerprint,
        clips=tuple(eligible),
    )
