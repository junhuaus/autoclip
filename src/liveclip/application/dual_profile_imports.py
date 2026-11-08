"""Import one finished dual-profile CLI run into the review console (Stage 19a).

The import never invents single-profile lineage (no candidate_clips or
render_jobs rows). It re-verifies the run's exact evidence with
``load_verified_dual_profile_render_set``, additionally requires the frozen
routing policy, copies each verified MP4/SRT into the new project's immutable
``imports/<import_id>/<profile>/`` directory, and records one immutable import,
its immutable clips and their committed Assets in a single transaction.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from liveclip.delivery.package import DeliveryError, copy_immutable_member, source_basename
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import (
    ClipDecision,
    ClipDecisionAction,
    CustomerText,
    ImportedClipStatus,
    effective_customer_text,
    is_deliverable,
    is_selected_for_delivery,
)
from liveclip.media.secure_files import (
    SecureFileError,
    create_directory_exclusive_no_follow,
    ensure_directory_no_follow,
    remove_tree_no_follow,
)
from liveclip.pipeline.dual_profile import (
    DUAL_PROFILE_ALGORITHM_VERSION,
    DUAL_PROFILE_ROUTING_POLICY_VERSION,
)
from liveclip.services.dual_profile_delivery import (
    DualProfileDeliveryError,
    VerifiedDualProfileRenderSet,
    load_verified_dual_profile_render_set,
)

DUAL_PROFILE_VIDEO_ASSET_KIND = "dual_profile_video"
DUAL_PROFILE_SUBTITLE_ASSET_KIND = "dual_profile_subtitle"
DUAL_PROFILE_IMPORT_SOURCE_PREFIX = "dual-profile-import:"
FINAL_RESULT_FILENAME = "final-validated.json"
RUN_MANIFEST_FILENAME = "run-manifest.json"
RENDER_MANIFEST_RELATIVE = PurePosixPath("renders/render-manifest.json")
_PROJECT_ID = re.compile(r"[a-f0-9]{32}")


class DualProfileImportError(RuntimeError):
    """The run cannot be imported; the message is safe to show to an operator."""


class DualProfileDecisionConflict(RuntimeError):
    """The decision is not allowed in the clip's current review state (HTTP 409)."""


class DualProfileImportDuplicate(RuntimeError):
    """A concurrent import of the same snapshot by the same user won the race."""


@dataclass(frozen=True, slots=True)
class ImportedAssetFile:
    kind: str
    relative_path: str
    mime_type: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class NewImportedClip:
    candidate_id: str
    profile: ClipProfile
    routed_status: ImportedClipStatus
    variant_group_id: str
    start_cue_id: int
    end_cue_id: int
    start_ms: int
    end_ms: int
    duration_ms: int
    title: str
    hook: str
    summary: str
    score: float
    review_reason: str
    quality_flags: tuple[str, ...]
    risk_tags: tuple[str, ...]
    video: ImportedAssetFile
    subtitle: ImportedAssetFile


@dataclass(frozen=True, slots=True)
class NewDualProfileImport:
    project_id: str
    import_id: str
    project_name: str
    acting_user_id: str
    source_hash: str
    transcript_sha256: str
    final_result_sha256: str
    run_manifest_sha256: str
    render_manifest_sha256: str
    algorithm_version: str
    routing_policy_version: str
    snapshot_fingerprint: str
    source_filename: str
    prompt_hashes: Mapping[str, str]
    clips: tuple[NewImportedClip, ...]
    created_at: datetime

    @property
    def source_request_path(self) -> str:
        return dual_profile_import_source_request_path(self.snapshot_fingerprint)


@dataclass(frozen=True, slots=True)
class DualProfileImportResult:
    project_id: str
    import_id: str
    snapshot_fingerprint: str
    clip_count: int
    created: bool


@dataclass(frozen=True, slots=True)
class ImportedClipState:
    """One immutable imported clip plus its append-only reviewer decisions."""

    import_clip_id: str
    project_id: str
    candidate_id: str
    profile: ClipProfile
    routed_status: ImportedClipStatus
    start_ms: int
    end_ms: int
    duration_ms: int
    original_text: CustomerText
    video_asset_id: str
    subtitle_asset_id: str
    decisions: tuple[ClipDecision, ...]

    @property
    def deliverable(self) -> bool:
        return is_deliverable(self.routed_status, self.decisions)

    @property
    def selected_for_delivery(self) -> bool:
        return is_selected_for_delivery(self.routed_status, self.decisions)

    @property
    def effective_text(self) -> CustomerText:
        return effective_customer_text(self.original_text, self.decisions)


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision: ClipDecision
    actor_username: str
    actor_display_name: str
    decided_at: datetime
    acknowledge_warnings: bool = False


@dataclass(frozen=True, slots=True)
class ReviewClipRecord:
    """Internal review view of one immutable imported clip and its history."""

    import_clip_id: str
    candidate_id: str
    profile: ClipProfile
    routed_status: ImportedClipStatus
    variant_group_id: str
    start_ms: int
    end_ms: int
    duration_ms: int
    original_text: CustomerText
    score: float
    review_reason: str
    quality_flags: tuple[str, ...]
    risk_tags: tuple[str, ...]
    video_asset_id: str
    subtitle_asset_id: str
    history: tuple[DecisionRecord, ...]

    @property
    def decisions(self) -> tuple[ClipDecision, ...]:
        return tuple(value.decision for value in self.history)


@dataclass(frozen=True, slots=True)
class DualProfileReviewRecord:
    import_id: str
    project_id: str
    source_filename: str
    snapshot_fingerprint: str
    algorithm_version: str
    routing_policy_version: str
    clip_count: int
    imported_at: datetime
    imported_by: str
    clips: tuple[ReviewClipRecord, ...]


class DualProfileImportRepository(Protocol):
    def find_import(
        self,
        *,
        acting_user_id: str,
        snapshot_fingerprint: str,
    ) -> DualProfileImportResult | None: ...

    def insert_import(self, record: NewDualProfileImport) -> DualProfileImportResult: ...


def dual_profile_import_source_request_path(snapshot_fingerprint: str) -> str:
    """Project source marker: no absolute path, only the snapshot identity prefix."""

    if not re.fullmatch(r"[a-f0-9]{64}", snapshot_fingerprint):
        raise ValueError("snapshot fingerprint must be a sha256 hex digest")
    return f"{DUAL_PROFILE_IMPORT_SOURCE_PREFIX}{snapshot_fingerprint[:20]}"


def default_dual_profile_import_root(project_root: Path) -> Path:
    """The default allowed import root: ``<repo>/data/evaluations``."""

    return project_root / "data" / "evaluations"


class DualProfileImportService:
    def __init__(
        self,
        repository: DualProfileImportRepository,
        *,
        data_dir: Path,
        allowed_run_roots: Iterable[Path],
        allowed_transcript_roots: Iterable[Path],
        relative_path_base: Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._data_dir = data_dir
        self._allowed_run_roots = tuple(allowed_run_roots)
        self._allowed_transcript_roots = tuple(allowed_transcript_roots)
        if not self._allowed_run_roots or not self._allowed_transcript_roots:
            raise ValueError("dual-profile import needs at least one allowed root")
        if not relative_path_base.is_absolute():
            raise ValueError("relative path base must be absolute")
        self._relative_path_base = relative_path_base
        self._now = now or (lambda: datetime.now(UTC))

    def import_run(
        self,
        *,
        acting_user_id: str,
        run_dir: Path,
        transcript_path: Path,
        project_name: str | None = None,
    ) -> DualProfileImportResult:
        """Verify, copy and record one dual-profile run; idempotent per user and snapshot."""

        base = _resolve_existing(self._relative_path_base, label="relative path base")
        run_roots = _resolve_roots(self._allowed_run_roots)
        resolved_run = self._resolve_confined(run_dir, base=base, roots=run_roots, label="run")
        if not resolved_run.is_dir():
            raise DualProfileImportError("run directory is not a directory")
        transcript = self._resolve_confined(
            transcript_path,
            base=base,
            roots=_resolve_roots(self._allowed_transcript_roots),
            label="transcript",
        )
        final_path = _evidence_file(resolved_run, PurePosixPath(FINAL_RESULT_FILENAME))
        run_manifest_path = _evidence_file(resolved_run, PurePosixPath(RUN_MANIFEST_FILENAME))
        render_manifest_path = _evidence_file(resolved_run, RENDER_MANIFEST_RELATIVE)
        try:
            verified = load_verified_dual_profile_render_set(
                transcript_path=transcript,
                final_result_path=final_path,
                run_manifest_path=run_manifest_path,
                render_manifest_path=render_manifest_path,
                relative_render_path_base=base,
            )
        except DualProfileDeliveryError as exc:
            raise DualProfileImportError(f"dual-profile evidence is invalid: {exc}") from exc
        _validate_frozen_contract(verified)

        existing = self._repository.find_import(
            acting_user_id=acting_user_id,
            snapshot_fingerprint=verified.snapshot_fingerprint,
        )
        if existing is not None:
            return existing

        project_id = uuid.uuid4().hex
        import_id = uuid.uuid4().hex
        data_root = _resolve_existing(self._data_dir, label="data directory")
        project_dir = data_root / project_id
        try:
            identity = create_directory_exclusive_no_follow(project_dir)
        except SecureFileError as exc:
            raise DualProfileImportError("project directory could not be created") from exc
        try:
            clips = _copy_clips(
                verified,
                project_dir=project_dir,
                import_id=import_id,
            )
            record = NewDualProfileImport(
                project_id=project_id,
                import_id=import_id,
                project_name=_project_name(project_name, verified),
                acting_user_id=acting_user_id,
                source_hash=verified.final.source_hash,
                transcript_sha256=verified.transcript_sha256,
                final_result_sha256=verified.final_sha256,
                run_manifest_sha256=verified.run_sha256,
                render_manifest_sha256=verified.render_sha256,
                algorithm_version=verified.final.algorithm_version,
                routing_policy_version=DUAL_PROFILE_ROUTING_POLICY_VERSION,
                snapshot_fingerprint=verified.snapshot_fingerprint,
                source_filename=source_basename(verified.render_manifest.source_video),
                prompt_hashes=dict(verified.run_manifest.prompt_hashes),
                clips=clips,
                created_at=self._now(),
            )
            return self._repository.insert_import(record)
        except DualProfileImportDuplicate:
            _remove_project_dir(project_dir, data_root=data_root, identity=identity)
            raced = self._repository.find_import(
                acting_user_id=acting_user_id,
                snapshot_fingerprint=verified.snapshot_fingerprint,
            )
            if raced is None:  # pragma: no cover - the unique constraint guarantees a row
                raise DualProfileImportError("concurrent import could not be resolved") from None
            return raced
        except BaseException:
            _remove_project_dir(project_dir, data_root=data_root, identity=identity)
            raise

    def _resolve_confined(
        self,
        path: Path,
        *,
        base: Path,
        roots: tuple[Path, ...],
        label: str,
    ) -> Path:
        """Resolve a requested path inside the allowed roots, outside the managed data dir.

        Containment is checked before existence, and the same message covers
        "outside" and "missing outside", so the import cannot be used to probe
        whether paths outside the allowed roots exist. Like ``POST /jobs``
        (``forbidden_roots=(data_dir,)``), the application's managed data
        directory (``data/projects``) is never an import source, even when an
        allowed root contains it.
        """

        if ".." in path.parts:
            raise DualProfileImportError(f"{label} path must not contain '..'")
        candidate = (path if path.is_absolute() else base / path).expanduser()
        forbidden = self._data_dir.expanduser().resolve(strict=False)
        outside = DualProfileImportError(f"{label} path is outside the allowed import roots")
        try:
            lexical = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise outside from exc
        if not _confined(lexical, roots, forbidden):
            raise outside
        resolved = _resolve_existing(candidate, label=f"{label} path")
        if not _confined(resolved, roots, forbidden):
            raise outside
        return resolved


def _confined(path: Path, roots: tuple[Path, ...], forbidden: Path) -> bool:
    if path == forbidden or forbidden in path.parents:
        return False
    return any(path == root or root in path.parents for root in roots)


def _validate_frozen_contract(verified: VerifiedDualProfileRenderSet) -> None:
    if verified.final.algorithm_version != DUAL_PROFILE_ALGORITHM_VERSION:
        raise DualProfileImportError("dual-profile algorithm version is not the frozen one")
    if verified.final.routing_policy_version != DUAL_PROFILE_ROUTING_POLICY_VERSION:
        raise DualProfileImportError("dual-profile routing policy is not the frozen one")
    if verified.transcript_sha256 != verified.final.source_hash:  # pragma: no cover
        raise DualProfileImportError("transcript hash differs from the evaluated source")


def _resolve_existing(path: Path, *, label: str) -> Path:
    try:
        return path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DualProfileImportError(f"{label} does not exist") from exc


def _resolve_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for root in roots:
        try:
            resolved.append(root.expanduser().resolve(strict=True))
        except (OSError, RuntimeError):
            continue
    if not resolved:
        raise DualProfileImportError("no allowed import root is available")
    return tuple(resolved)


def _evidence_file(run_dir: Path, relative: PurePosixPath) -> Path:
    """An exact evidence file inside the run: no symbolic-link component may redirect it."""

    candidate = run_dir.joinpath(*relative.parts)
    resolved = _resolve_existing(candidate, label=f"run evidence {relative.as_posix()}")
    if resolved != candidate:
        raise DualProfileImportError(
            f"run evidence {relative.as_posix()} must not be reached through a symbolic link"
        )
    return candidate


def _copy_clips(
    verified: VerifiedDualProfileRenderSet,
    *,
    project_dir: Path,
    import_id: str,
) -> tuple[NewImportedClip, ...]:
    clips: list[NewImportedClip] = []
    for clip in verified.clips:
        relative_dir = PurePosixPath("imports", import_id, clip.profile.value)
        try:
            ensure_directory_no_follow(project_dir.joinpath(*relative_dir.parts))
        except SecureFileError as exc:
            raise DualProfileImportError("import directory could not be created") from exc
        video_relative = relative_dir / f"{clip.candidate_id}.mp4"
        subtitle_relative = relative_dir / f"{clip.candidate_id}.srt"
        try:
            copy_immutable_member(
                clip.video_path,
                project_dir.joinpath(*video_relative.parts),
                expected_sha256=clip.video_sha256,
            )
            copy_immutable_member(
                clip.subtitle_path,
                project_dir.joinpath(*subtitle_relative.parts),
                expected_sha256=clip.subtitle_sha256,
            )
        except DeliveryError as exc:
            raise DualProfileImportError("rendered media could not be copied safely") from exc
        clips.append(
            NewImportedClip(
                candidate_id=clip.candidate_id,
                profile=clip.profile,
                routed_status=ImportedClipStatus(clip.review_status),
                variant_group_id=clip.variant_group_id,
                start_cue_id=clip.start_cue_id,
                end_cue_id=clip.end_cue_id,
                start_ms=clip.start_ms,
                end_ms=clip.end_ms,
                duration_ms=clip.duration_ms,
                title=clip.title,
                hook=clip.hook,
                summary=clip.summary,
                score=clip.score,
                review_reason=clip.review_reason,
                quality_flags=clip.quality_flags,
                risk_tags=clip.risk_tags,
                video=ImportedAssetFile(
                    kind=DUAL_PROFILE_VIDEO_ASSET_KIND,
                    relative_path=video_relative.as_posix(),
                    mime_type="video/mp4",
                    sha256=clip.video_sha256,
                    size_bytes=clip.video_size_bytes,
                ),
                subtitle=ImportedAssetFile(
                    kind=DUAL_PROFILE_SUBTITLE_ASSET_KIND,
                    relative_path=subtitle_relative.as_posix(),
                    mime_type="application/x-subrip",
                    sha256=clip.subtitle_sha256,
                    size_bytes=clip.subtitle_size_bytes,
                ),
            )
        )
    return tuple(clips)


def _project_name(requested: str | None, verified: VerifiedDualProfileRenderSet) -> str:
    if requested is not None:
        name = requested.strip()
        if not name or len(name) > 200 or any(ord(value) < 32 for value in name):
            raise DualProfileImportError("project name must be 1-200 printable characters")
        return name
    stem = PurePosixPath(source_basename(verified.render_manifest.source_video)).stem
    return f"{stem or '直播'} 双轨结果"[:200]


def _remove_project_dir(
    project_dir: Path,
    *,
    data_root: Path,
    identity: tuple[int, int],
) -> None:
    if not _PROJECT_ID.fullmatch(project_dir.name):  # pragma: no cover - generated locally
        return
    # Best-effort cleanup of a tree no committed row references.
    with contextlib.suppress(SecureFileError):
        remove_tree_no_follow(project_dir, required_ancestor=data_root, expected_identity=identity)


def clip_decision_from_values(
    *,
    sequence: int,
    action: str,
    title_override: str | None,
    hook_override: str | None,
    summary_override: str | None,
    acknowledge_warnings: bool = False,
) -> ClipDecision:
    return ClipDecision(
        sequence=sequence,
        action=ClipDecisionAction(action),
        title_override=title_override,
        hook_override=hook_override,
        summary_override=summary_override,
        acknowledge_warnings=acknowledge_warnings,
    )


__all__ = [
    "DUAL_PROFILE_IMPORT_SOURCE_PREFIX",
    "DUAL_PROFILE_SUBTITLE_ASSET_KIND",
    "DUAL_PROFILE_VIDEO_ASSET_KIND",
    "DecisionRecord",
    "DualProfileDecisionConflict",
    "DualProfileImportDuplicate",
    "DualProfileImportError",
    "DualProfileImportRepository",
    "DualProfileImportResult",
    "DualProfileImportService",
    "DualProfileReviewRecord",
    "ImportedAssetFile",
    "ImportedClipState",
    "NewDualProfileImport",
    "NewImportedClip",
    "ReviewClipRecord",
    "clip_decision_from_values",
    "default_dual_profile_import_root",
    "dual_profile_import_source_request_path",
]
