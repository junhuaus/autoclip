from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.rendering import RenderPersistence, RenderWork, render_asset_paths
from liveclip.domain.edit_plan import captions_to_srt
from liveclip.media.artifacts import (
    attempt_directory,
    project_directory,
    publish_file_no_clobber,
    write_json_no_clobber,
    write_text_no_clobber,
)
from liveclip.renderer.quality import validate_rendered_media
from liveclip.renderer.service import render_edit_plan_revision, render_revision_overlays


class RenderTaskCancelled(RuntimeError):
    """The durable render task was cancelled at a safe publication boundary."""


class RenderTaskHandler:
    def __init__(self, *, data_dir: Path, assets: AssetStore) -> None:
        self._data_dir = data_dir
        self._assets = assets

    def execute(
        self,
        work: RenderWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> RenderPersistence:
        _check_cancel(cancel_requested)
        _assert_source_identity(work)
        project_dir = project_directory(self._data_dir, work.project_id)
        attempt_dir = attempt_directory(project_dir, lease)
        paths = render_asset_paths(work)
        base_relative = str(Path(paths.video).parent)
        video_relative = paths.video
        subtitle_relative = paths.subtitle
        quality_relative = paths.quality_report
        contact_relative = paths.contact_sheet
        reservations = (
            self._reserve(
                work,
                lease,
                kind="review_proxy" if work.kind == "proxy" else "final_video",
                relative_path=video_relative,
                mime_type="video/mp4",
            ),
            self._reserve(
                work,
                lease,
                kind="clip_subtitle_srt",
                relative_path=subtitle_relative,
                mime_type="application/x-subrip",
            ),
            self._reserve(
                work,
                lease,
                kind="render_quality_report",
                relative_path=quality_relative,
                mime_type="application/json",
            ),
            self._reserve(
                work,
                lease,
                kind="render_contact_sheet",
                relative_path=contact_relative,
                mime_type="image/png",
            ),
        )
        canonical_video = project_dir / video_relative
        canonical_subtitle = project_dir / subtitle_relative
        canonical_quality = project_dir / quality_relative
        canonical_contact = project_dir / contact_relative
        if not canonical_video.is_file():
            attempt_video = attempt_dir / video_relative
            artifact = render_edit_plan_revision(
                source_path=work.source_path,
                revision=work.revision,
                output_path=attempt_video,
                width=work.width,
                height=work.height,
                encoder=work.encoder,
                font_path=work.font_path,
                cancel_requested=cancel_requested,
            )
            report_payload = json.loads(artifact.quality_report_path.read_text(encoding="utf-8"))
            _check_cancel(cancel_requested)
            _assert_source_identity(work)
            publish_file_no_clobber(artifact.output_path, canonical_video)
            publish_file_no_clobber(artifact.contact_sheet_path, canonical_contact)
            _write_canonical_quality_report(
                canonical_quality,
                report_payload,
                media_path=canonical_video,
                contact_sheet=canonical_contact,
            )
        else:
            _check_cancel(cancel_requested)
            recovery_root = attempt_dir / base_relative / "recovery"
            overlays = render_revision_overlays(
                revision=work.revision,
                output_dir=recovery_root / "overlays",
                width=work.width,
                height=work.height,
                font_path=work.font_path,
            )
            quality = validate_rendered_media(
                media_path=canonical_video,
                expected_width=work.width,
                expected_height=work.height,
                expected_duration_ms=work.revision.plan.duration_ms,
                output_dir=recovery_root / "quality",
                safe_bounds=tuple(value.safe_bounds for value in overlays),
                cancel_requested=cancel_requested,
            )
            publish_file_no_clobber(Path(quality.contact_sheet), canonical_contact)
            _write_canonical_quality_report(
                canonical_quality,
                quality.as_dict(),
                media_path=canonical_video,
                contact_sheet=canonical_contact,
            )
        _assert_source_identity(work)
        write_text_no_clobber(canonical_subtitle, captions_to_srt(work.revision.captions))
        _check_cancel(cancel_requested)
        _assert_source_identity(work)
        validations: tuple[dict[str, object], ...] = (
            {
                "schema_version": "1",
                "width": work.width,
                "height": work.height,
                "full_decode": "passed",
            },
            {
                "schema_version": "1",
                "timeline": "clip_relative_ms",
                "cue_count": len(work.revision.captions),
            },
            {"schema_version": "1", "automatic_status": "passed"},
            {"schema_version": "1", "frames": 3},
        )
        committed = tuple(
            self._assets.commit(
                lease,
                reservation,
                project_dir=project_dir,
                validation=validation,
            )
            for reservation, validation in zip(
                reservations,
                validations,
                strict=True,
            )
        )
        return RenderPersistence(
            video_asset_id=committed[0].asset_id,
            subtitle_asset_id=committed[1].asset_id,
            quality_report_asset_id=committed[2].asset_id,
            contact_sheet_asset_id=committed[3].asset_id,
        )

    def _reserve(
        self,
        work: RenderWork,
        lease: LeaseIdentity,
        *,
        kind: str,
        relative_path: str,
        mime_type: str,
    ) -> AssetReservation:
        return self._assets.reserve(
            lease,
            project_id=work.project_id,
            kind=kind,
            relative_path=relative_path,
            mime_type=mime_type,
            input_fingerprint=work.spec_fingerprint,
            generation=work.generation,
            candidate_id=work.revision.clip_id,
            edit_plan_revision=work.revision.revision,
            revision_epoch=work.revision_epoch,
        )


def _check_cancel(cancel_requested: Callable[[], bool]) -> None:
    if cancel_requested():
        raise RenderTaskCancelled("render task cancellation was requested")


def _assert_source_identity(work: RenderWork) -> None:
    try:
        if work.source_path.resolve(strict=True) != work.source_path:
            raise ValueError("source media path changed after import")
        metadata = work.source_path.stat()
    except (OSError, RuntimeError) as exc:
        raise ValueError("source media is no longer available") from exc
    observed = (
        metadata.st_size,
        metadata.st_mtime_ns,
        getattr(metadata, "st_dev", None),
        getattr(metadata, "st_ino", None),
    )
    expected = (
        work.source_size_bytes,
        work.source_mtime_ns,
        work.source_device,
        work.source_inode,
    )
    if observed != expected:
        raise ValueError("source media changed while the render was executing")


def _write_canonical_quality_report(
    path: Path,
    raw_payload: object,
    *,
    media_path: Path,
    contact_sheet: Path,
) -> None:
    if not isinstance(raw_payload, dict):
        raise ValueError("render quality report is not an object")
    payload = {str(key): value for key, value in raw_payload.items()}
    payload["media_path"] = str(media_path.resolve(strict=True))
    payload["contact_sheet"] = str(contact_sheet.resolve(strict=True))
    write_json_no_clobber(path, payload)
