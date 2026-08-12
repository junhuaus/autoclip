from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from liveclip.application.clips import ClipQueryService, ClipSummary
from liveclip.application.media_assets import MediaAssetService, ResolvedMediaAsset
from liveclip.application.pipeline import PipelineService, ProjectSnapshot
from liveclip.delivery.review_package import (
    OfflineReviewClipInput,
    OfflineReviewPackageResult,
    create_offline_review_package,
)
from liveclip.domain.state_transitions import RenderStatus, ReviewStatus
from liveclip.media.artifacts import project_directory
from liveclip.media.models import SourceMediaMetadata


class OfflineReviewPackageConflict(RuntimeError):
    """The current review set cannot be exported as a trustworthy offline snapshot."""


class SourceMediaReader(Protocol):
    def load_source(self, *, project_id: str) -> SourceMediaMetadata: ...


@dataclass(frozen=True, slots=True)
class OfflineReviewClipObservation:
    """The application values that a database snapshot must prove are current."""

    clip_id: str
    edit_plan_revision: int
    review_status: ReviewStatus
    proxy_asset_id: str
    proxy_sha256: str
    proxy_size_bytes: int


@dataclass(frozen=True, slots=True)
class OfflineReviewProxyLineage:
    """Persisted revision, render and asset identities for one exported proxy."""

    clip_id: str
    edit_plan_revision_id: str
    edit_plan_revision: int
    review_status: ReviewStatus
    render_job_id: str
    render_spec_fingerprint: str
    render_revision_epoch: int
    producer_task_id: str
    producer_task_kind: str
    producer_stage: str | None
    asset_id: str
    asset_input_fingerprint: str
    asset_generation: int
    asset_edit_plan_revision: int
    asset_revision_epoch: int
    asset_sha256: str
    asset_size_bytes: int


@dataclass(frozen=True, slots=True)
class OfflineReviewFenceToken:
    """A short-lived, transactionally captured publication fence."""

    project_id: str
    project_name: str
    pipeline_run_id: str
    generation: int
    revision_epoch: int
    source_filename: str
    source_fingerprint: str
    clips: tuple[OfflineReviewProxyLineage, ...]


class OfflineReviewFenceRepository(Protocol):
    def capture(
        self,
        *,
        project: ProjectSnapshot,
        source: SourceMediaMetadata,
        clips: tuple[OfflineReviewClipObservation, ...],
    ) -> OfflineReviewFenceToken: ...

    def assert_current(self, token: OfflineReviewFenceToken) -> None: ...


class OfflineReviewPackageService:
    """Export current clean review proxies without changing review or Project state."""

    def __init__(
        self,
        *,
        pipeline: PipelineService,
        clips: ClipQueryService,
        source_media: SourceMediaReader,
        media_assets: MediaAssetService,
        fence_repository: OfflineReviewFenceRepository,
        data_dir: Path,
    ) -> None:
        self._pipeline = pipeline
        self._clips = clips
        self._source_media = source_media
        self._media_assets = media_assets
        self._fence_repository = fence_repository
        self._data_dir = data_dir

    def create(self, project_id: str, *, include_zip: bool = True) -> OfflineReviewPackageResult:
        project = self._pipeline.get_project(project_id)
        source = self._source_media.load_source(project_id=project_id)
        summaries = self._clips.list_project_clips(project_id)
        if not summaries:
            raise OfflineReviewPackageConflict("project has no current review clips")

        resolved: list[tuple[ClipSummary, ResolvedMediaAsset]] = []
        for clip in summaries:
            asset = self._resolve_current_proxy(project, clip)
            resolved.append((clip, asset))

        fence_token = self._fence_repository.capture(
            project=project,
            source=source,
            clips=tuple(
                OfflineReviewClipObservation(
                    clip_id=clip.clip_id,
                    edit_plan_revision=clip.edit_plan_revision,
                    review_status=clip.review_status,
                    proxy_asset_id=asset.asset_id,
                    proxy_sha256=asset.sha256,
                    proxy_size_bytes=asset.size_bytes,
                )
                for clip, asset in resolved
            ),
        )
        lineage_by_clip = {item.clip_id: item for item in fence_token.clips}
        package_clips: list[OfflineReviewClipInput] = []
        for clip, asset in resolved:
            lineage = lineage_by_clip[clip.clip_id]
            package_clips.append(
                OfflineReviewClipInput(
                    clip_id=clip.clip_id,
                    candidate_key=clip.candidate_key,
                    edit_plan_revision=clip.edit_plan_revision,
                    source_start_ms=clip.source_start_ms,
                    source_end_ms=clip.source_end_ms,
                    score=clip.score,
                    title=clip.title,
                    high_impact_sentence=clip.hook,
                    recommendation_reason=clip.reason,
                    risk_flags=clip.risk_flags,
                    captions=clip.captions,
                    keywords=clip.keywords,
                    review_status=clip.review_status,
                    proxy_path=asset.path,
                    proxy_sha256=asset.sha256,
                    proxy_size_bytes=asset.size_bytes,
                    proxy_render_id=lineage.render_job_id,
                    proxy_asset_id=lineage.asset_id,
                    proxy_spec_fingerprint=lineage.render_spec_fingerprint,
                    proxy_render_revision_epoch=lineage.render_revision_epoch,
                    proxy_producer_task_id=lineage.producer_task_id,
                    proxy_producer_task_kind=lineage.producer_task_kind,
                    proxy_producer_stage=lineage.producer_stage,
                    proxy_asset_input_fingerprint=lineage.asset_input_fingerprint,
                    proxy_asset_generation=lineage.asset_generation,
                    proxy_asset_revision_epoch=lineage.asset_revision_epoch,
                )
            )

        snapshot_fingerprint = _snapshot_fingerprint(
            project=project,
            source=source,
            clips=tuple(package_clips),
            revision_epoch=fence_token.revision_epoch,
        )

        def assert_snapshot_is_current() -> None:
            self._fence_repository.assert_current(fence_token)
            if self._pipeline.get_project(project_id) != project:
                raise OfflineReviewPackageConflict(
                    "project state changed while the offline review package was being built"
                )

        return create_offline_review_package(
            project_dir=project_directory(self._data_dir, project_id),
            project_id=project_id,
            project_name=project.name,
            source_filename=source.filename,
            source_fingerprint=source.sha256,
            pipeline_run_id=project.current_run_id,
            generation=project.generation,
            project_revision_epoch=fence_token.revision_epoch,
            project_status=project.status.value,
            snapshot_fingerprint=snapshot_fingerprint,
            clips=tuple(package_clips),
            include_zip=include_zip,
            publication_fence=assert_snapshot_is_current,
        )

    def _resolve_current_proxy(
        self,
        project: ProjectSnapshot,
        clip: ClipSummary,
    ) -> ResolvedMediaAsset:
        if clip.proxy_status != RenderStatus.SUCCEEDED or clip.proxy_asset_id is None:
            raise OfflineReviewPackageConflict(
                f"clip {clip.clip_id} has no successful current clean review proxy"
            )
        asset = self._media_assets.resolve(
            clip.proxy_asset_id,
            required_kind="review_proxy",
        )
        if asset.project_id != project.project_id:
            raise OfflineReviewPackageConflict("review proxy belongs to another project")
        return asset


def _snapshot_fingerprint(
    *,
    project: ProjectSnapshot,
    source: SourceMediaMetadata,
    clips: tuple[OfflineReviewClipInput, ...],
    revision_epoch: int,
) -> str:
    payload = {
        "schema_version": "liveclip.offline-review-snapshot.v2",
        "project_id": project.project_id,
        "pipeline_run_id": project.current_run_id,
        "generation": project.generation,
        "revision_epoch": revision_epoch,
        "source_sha256": source.sha256,
        "clips": [
            {
                key: value
                for key, value in clip.model_dump(mode="json").items()
                if key != "proxy_path"
            }
            for clip in clips
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
