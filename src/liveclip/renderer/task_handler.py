from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from liveclip.application.assets import AssetReservation, AssetStore
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.rendering import RenderPersistence, RenderWork, render_asset_paths
from liveclip.domain.edit_plan import captions_to_srt
from liveclip.media.artifacts import (
    ArtifactPublicationError,
    attempt_directory,
    cleanup_attempt_worktree,
    project_directory,
    publish_file_no_clobber,
    write_json_no_clobber,
    write_text_no_clobber,
)
from liveclip.media.secure_files import (
    PinnedRegularFile,
    SecureFileError,
    cross_launch_source_stat_matches,
    hash_regular_file_no_follow,
    open_pinned_regular_file,
)
from liveclip.renderer.ffmpeg import FFmpegRenderError, render_error_diagnostics_payload
from liveclip.renderer.quality import validate_rendered_media
from liveclip.renderer.service import (
    RenderTextMode,
    render_edit_plan_revision,
    render_revision_overlays_for_mode,
)

logger = logging.getLogger(__name__)


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
        text_mode = (
            RenderTextMode.NONE if work.kind == "proxy" else RenderTextMode.TITLE_AND_CAPTIONS
        )
        attempt_diagnostics: dict[str, object]
        if not canonical_video.is_file():
            attempt_video = attempt_dir / video_relative
            try:
                with open_pinned_regular_file(work.source_path) as pinned:
                    _assert_pinned_source_content(
                        work,
                        pinned,
                        cancel_requested=cancel_requested,
                    )
                    artifact = render_edit_plan_revision(
                        source_path=pinned.process_path,
                        revision=work.revision,
                        output_path=attempt_video,
                        width=work.width,
                        height=work.height,
                        encoder=work.encoder,
                        text_mode=text_mode,
                        video_stream_index=work.video_stream_index,
                        audio_stream_index=work.audio_stream_index,
                        source_pass_fds=pinned.pass_fds,
                        font_path=work.font_path,
                        cancel_requested=cancel_requested,
                    )
                    _assert_pinned_source_binding(
                        work,
                        pinned,
                        cancel_requested=cancel_requested,
                    )
            except InterruptedError as exc:
                raise RenderTaskCancelled("render source validation was cancelled") from exc
            except FFmpegRenderError as exc:
                exc.diagnostic_relative_path = _persist_failed_render_diagnostic(
                    project_dir=project_dir,
                    attempt_dir=attempt_dir,
                    error=exc,
                )
                raise
            except SecureFileError as exc:
                raise ValueError("source media changed during render") from exc
            report_payload = artifact.quality.as_dict()
            attempt_diagnostics = artifact.diagnostic_payload
            _check_cancel(cancel_requested)
            _assert_source_identity(work)
            validated_video_sha256 = publish_file_no_clobber(
                artifact.output_path,
                canonical_video,
                expected_sha256=artifact.sha256,
            )
            validated_contact_sha256 = publish_file_no_clobber(
                artifact.contact_sheet_path,
                canonical_contact,
                expected_sha256=artifact.contact_sheet_sha256,
            )
            validated_quality_sha256 = _write_canonical_quality_report(
                canonical_quality,
                report_payload,
                media_path=canonical_video,
                contact_sheet=canonical_contact,
            )
        else:
            _check_cancel(cancel_requested)
            _assert_source_content_once(work, cancel_requested=cancel_requested)
            recovery_root = attempt_dir / base_relative / "recovery"
            overlays = render_revision_overlays_for_mode(
                revision=work.revision,
                output_dir=recovery_root / "overlays",
                width=work.width,
                height=work.height,
                font_path=work.font_path,
                text_mode=text_mode,
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
            try:
                recovery_contact_sha256, _contact_size = hash_regular_file_no_follow(
                    Path(quality.contact_sheet)
                )
            except SecureFileError as exc:
                raise ValueError("recovery contact sheet changed after validation") from exc
            validated_video_sha256 = quality.media_sha256
            validated_contact_sha256 = publish_file_no_clobber(
                Path(quality.contact_sheet),
                canonical_contact,
                expected_sha256=recovery_contact_sha256,
            )
            attempt_diagnostics = {
                "schema_version": "1",
                "attempt_count": 0,
                "recovery": "validated_existing_immutable_video",
            }
            validated_quality_sha256 = _write_canonical_quality_report(
                canonical_quality,
                quality.as_dict(),
                media_path=canonical_video,
                contact_sheet=canonical_contact,
            )
        _assert_source_identity(work)
        validated_subtitle_sha256 = write_text_no_clobber(
            canonical_subtitle,
            captions_to_srt(work.revision.captions),
        )
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
        expected_hashes = (
            validated_video_sha256,
            validated_subtitle_sha256,
            validated_quality_sha256,
            validated_contact_sha256,
        )
        committed = tuple(
            self._assets.commit(
                lease,
                reservation,
                project_dir=project_dir,
                validation=validation,
                expected_sha256=expected_sha256,
            )
            for reservation, validation, expected_sha256 in zip(
                reservations,
                validations,
                expected_hashes,
                strict=True,
            )
        )
        diagnostic_relative_path = _write_attempt_render_diagnostic(
            project_dir=project_dir,
            attempt_dir=attempt_dir,
            status="succeeded",
            renderer_diagnostics=attempt_diagnostics,
        )
        cleanup_attempt_worktree(
            project_dir,
            task_id=lease.task_id,
            lease_token=lease.lease_token,
            preserve_diagnostics=True,
        )
        return RenderPersistence(
            video_asset_id=committed[0].asset_id,
            subtitle_asset_id=committed[1].asset_id,
            quality_report_asset_id=committed[2].asset_id,
            contact_sheet_asset_id=committed[3].asset_id,
            diagnostic_relative_path=diagnostic_relative_path,
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
    if not cross_launch_source_stat_matches(
        work.source_path,
        metadata,
        expected_path=work.source_path,
        expected_size_bytes=work.source_size_bytes,
        expected_mtime_ns=work.source_mtime_ns,
        expected_inode=work.source_inode,
    ):
        raise ValueError("source media changed while the render was executing")


def _assert_source_content_once(
    work: RenderWork,
    *,
    cancel_requested: Callable[[], bool],
) -> None:
    try:
        with open_pinned_regular_file(work.source_path) as pinned:
            _assert_pinned_source_content(
                work,
                pinned,
                cancel_requested=cancel_requested,
            )
    except InterruptedError as exc:
        raise RenderTaskCancelled("render source validation was cancelled") from exc
    except SecureFileError as exc:
        raise ValueError("source media changed before render recovery") from exc


def _assert_pinned_source_content(
    work: RenderWork,
    pinned: PinnedRegularFile,
    *,
    cancel_requested: Callable[[], bool],
) -> None:
    _check_cancel(cancel_requested)
    metadata = pinned.metadata
    identity_matches = cross_launch_source_stat_matches(
        pinned.path,
        metadata,
        expected_path=work.source_path,
        expected_size_bytes=work.source_size_bytes,
        expected_mtime_ns=work.source_mtime_ns,
        expected_inode=work.source_inode,
    )
    if (
        not identity_matches
        or pinned.sha256(cancel_requested=cancel_requested) != work.source_sha256
    ):
        raise ValueError("source media content changed while the render was executing")
    pinned.validate_binding()


def _assert_pinned_source_binding(
    work: RenderWork,
    pinned: PinnedRegularFile,
    *,
    cancel_requested: Callable[[], bool],
) -> None:
    _check_cancel(cancel_requested)
    metadata = pinned.metadata
    if not cross_launch_source_stat_matches(
        pinned.path,
        metadata,
        expected_path=work.source_path,
        expected_size_bytes=work.source_size_bytes,
        expected_mtime_ns=work.source_mtime_ns,
        expected_inode=work.source_inode,
    ):
        raise ValueError("source media identity changed while the render was executing")
    pinned.validate_binding()


def _write_canonical_quality_report(
    path: Path,
    raw_payload: object,
    *,
    media_path: Path,
    contact_sheet: Path,
) -> str:
    if not isinstance(raw_payload, dict):
        raise ValueError("render quality report is not an object")
    payload = {str(key): value for key, value in raw_payload.items()}
    payload["media_path"] = str(media_path.absolute())
    payload["contact_sheet"] = str(contact_sheet.absolute())
    return write_json_no_clobber(path, payload)


def _persist_failed_render_diagnostic(
    *,
    project_dir: Path,
    attempt_dir: Path,
    error: FFmpegRenderError,
) -> str | None:
    if not error.diagnostics:
        return None
    try:
        return _write_attempt_render_diagnostic(
            project_dir=project_dir,
            attempt_dir=attempt_dir,
            status="failed",
            renderer_diagnostics=render_error_diagnostics_payload(error),
        )
    except (ArtifactPublicationError, ValueError) as exc:
        logger.warning(
            "render diagnostic persistence failed error_class=%s",
            type(exc).__name__,
        )
        return None


def _write_attempt_render_diagnostic(
    *,
    project_dir: Path,
    attempt_dir: Path,
    status: str,
    renderer_diagnostics: dict[str, object],
) -> str:
    if status not in {"succeeded", "failed"}:
        raise ValueError("render diagnostic status is invalid")
    diagnostic_path = attempt_dir / "diagnostics" / "ffmpeg-render.json"
    write_json_no_clobber(
        diagnostic_path,
        {
            "schema_version": "1",
            "status": status,
            "renderer_diagnostics": renderer_diagnostics,
        },
        max_bytes=96 * 1024,
    )
    try:
        return diagnostic_path.relative_to(project_dir).as_posix()
    except ValueError as exc:
        raise ValueError("render diagnostic escaped its project") from exc
