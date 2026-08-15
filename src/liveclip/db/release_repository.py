from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from liveclip.application.authorization import (
    ProjectActionDenied,
    require_project_action,
)
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.releases import (
    MAX_RELEASE_CLOCK_SKEW,
    ReleaseApprovalCommand,
    ReleaseAssignee,
    ReleaseConflict,
    ReleaseItemCreate,
    ReleaseItemSnapshot,
    ReleaseItemUpdate,
    ReleaseMetricCreate,
    ReleaseMetricSnapshot,
    ReleasePackagePersistence,
    ReleasePackageRequest,
    ReleasePackageSnapshot,
    ReleasePackageWork,
    ReleasePublicationEvidence,
    ReleaseResourceNotFound,
)
from liveclip.application.workspace import WorkspaceRole
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    CandidateClipRow,
    CaptionCueRow,
    DeliveryClipRow,
    DeliveryRow,
    EditPackageClipRow,
    EditPackageRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    ReleaseItemRow,
    ReleaseMetricSnapshotRow,
    ReleasePackageRow,
    ReleasePublicationEvidenceRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.db.release_package_invalidation import (
    RELEASE_PACKAGE_STALE_CODE,
    invalidate_active_release_packages,
)
from liveclip.delivery.release_package import release_archive_name
from liveclip.domain.edit_plan import CaptionCue, edit_plan_from_json_data
from liveclip.domain.project_lifecycle import (
    ProjectLifecycle,
    transition_project_lifecycle,
)
from liveclip.domain.releases import (
    ReleaseApprovalStatus,
    ReleaseCaptionMode,
    ReleaseChecklist,
    ReleaseDuplicateContentMatch,
    ReleaseEditorialFacts,
    ReleaseItemStatus,
    ReleaseMediaFacts,
    ReleasePackageStatus,
    ReleasePlatform,
    ReleasePreflight,
    ReleaseTransitionError,
    evaluate_release_preflight,
    get_platform_preset,
    transition_release_approval,
    transition_release_item,
    transition_release_package,
)
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    DeliveryStatus,
    EditPackageStatus,
    PipelineRunStatus,
    PipelineStage,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    TaskKind,
    TaskStatus,
    transition_task,
)
from liveclip.media.secure_files import (
    PinnedRegularFile,
    SecureFileError,
    open_pinned_regular_file,
)
from liveclip.renderer.contracts import (
    has_current_manual_render_contract,
    is_clean_review_proxy,
)


@dataclass(frozen=True, slots=True)
class _ProjectEvidence:
    project_id: str
    project_name: str
    run_id: str
    generation: int
    revision_epoch: int
    lifecycle: ProjectLifecycle
    management_version: int
    pipeline_config: dict[str, Any]
    source_filename: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class _ReleaseArtifactContext:
    project_name: str
    requested_by_username: str
    source_preflight: ReleasePreflight

    def as_payload(self) -> dict[str, object]:
        return {
            "project_name": self.project_name,
            "requested_by_username": self.requested_by_username,
            "source_preflight": self.source_preflight.model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class _RenderEvidence:
    render_job_id: str
    video_asset_id: str
    video_relative_path: str
    video_sha256: str
    video_size_bytes: int
    video_input_fingerprint: str
    subtitle_asset_id: str | None
    subtitle_sha256: str | None
    subtitle_size_bytes: int | None
    quality_asset_id: str
    quality_sha256: str
    quality_size_bytes: int
    contact_sheet_asset_id: str
    contact_sheet_sha256: str
    contact_sheet_size_bytes: int
    producer_task_id: str
    producer_attempt_id: str
    render_spec_fingerprint: str
    width: int
    height: int
    revision_epoch: int


@dataclass(frozen=True, slots=True)
class _PinnedPackageArtifact:
    label: str
    asset_id: str
    kind: str
    relative_path: str
    path: Path
    pinned: PinnedRegularFile
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _PackageArtifactHashes:
    manifest_sha256: str | None
    zip_sha256: str | None
    pinned: tuple[_PinnedPackageArtifact, ...] = ()

    def validate_final_binding(self) -> None:
        for artifact in self.pinned:
            try:
                artifact.pinned.validate_at(artifact.path)
            except (OSError, SecureFileError) as exc:
                raise ReleaseConflict(
                    "release package artifact bytes changed before publication committed"
                ) from exc
            if artifact.pinned.metadata.st_size != artifact.size_bytes:
                raise ReleaseConflict(
                    "release package artifact bytes changed before publication committed"
                )


class SqlAlchemyReleaseRepository:
    """SQLite adapter for auditable release planning and immutable package work."""

    def __init__(self, engine: Engine, *, data_dir: Path) -> None:
        self._engine = engine
        self._data_dir = data_dir.resolve(strict=True)

    def create_item(
        self,
        *,
        project_id: str,
        acting_user_id: str,
        command: ReleaseItemCreate,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleaseItemSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            _require_release_actor(
                connection,
                project_id=project_id,
                user_id=acting_user_id,
                approval=False,
            )
            replay_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="release_item",
            )
            if replay_id is not None:
                return _get_item(connection, replay_id)
            project = _project_evidence(connection, project_id)
            clip = _current_clip(connection, project=project, clip_id=command.clip_id)
            if int(clip.current_revision) != command.expected_revision:
                raise ReleaseConflict("clip revision changed before release item creation")
            if command.assignee_user_id is not None:
                _require_active_project_member(
                    connection,
                    project_id=project_id,
                    user_id=command.assignee_user_id,
                )
            duplicate = connection.scalar(
                select(ReleaseItemRow.id).where(
                    ReleaseItemRow.candidate_clip_id == command.clip_id,
                    ReleaseItemRow.platform == command.platform.value,
                    ReleaseItemRow.account_label == command.account_label,
                )
            )
            if duplicate is not None:
                raise ReleaseConflict(
                    "a release item already exists for this clip, platform and account"
                )
            preset = get_platform_preset(command.platform)
            plan = edit_plan_from_json_data(clip.plan_json)
            checklist = ReleaseChecklist()
            release_item_id = new_id()
            preflight = _evaluate_preflight(
                connection,
                project=project,
                clip_id=command.clip_id,
                revision_id=str(clip.revision_id),
                selected_revision=int(clip.current_revision),
                platform=command.platform,
                preset_version=preset.version,
                caption_mode=command.caption_mode,
                title=plan.title,
                description=plan.reason,
                hashtags=(),
                cover_time_ms=0,
                approval_status=ReleaseApprovalStatus.DRAFT,
                checklist=checklist,
            )
            connection.execute(
                insert(ReleaseItemRow).values(
                    id=release_item_id,
                    project_id=project_id,
                    candidate_clip_id=command.clip_id,
                    edit_plan_revision_id=str(clip.revision_id),
                    edit_plan_revision=int(clip.current_revision),
                    platform=command.platform.value,
                    preset_version=preset.version,
                    account_label=command.account_label,
                    title=plan.title,
                    title_variants_json=[],
                    description=plan.reason,
                    hashtags_json=[],
                    cta="",
                    caption_mode=command.caption_mode.value,
                    cover_time_ms=0,
                    assignee_user_id=command.assignee_user_id,
                    planned_publish_at=command.planned_publish_at,
                    approval_status=ReleaseApprovalStatus.DRAFT.value,
                    status=ReleaseItemStatus.DRAFT.value,
                    checklist_json=checklist.model_dump(mode="json"),
                    preflight_json=preflight.model_dump(mode="json"),
                    management_version=1,
                    created_by_user_id=acting_user_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="release_item",
                resource_id=release_item_id,
                response_status_code=201,
            )
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action="release_item.created",
                release_item_id=release_item_id,
                project_id=project_id,
                before=None,
                after={
                    "clip_id": command.clip_id,
                    "edit_plan_revision": command.expected_revision,
                    "platform": command.platform.value,
                    "account_label": command.account_label,
                    "management_version": 1,
                },
                correlation_id=correlation_id,
                now=now,
            )
            return _get_item(connection, release_item_id)

    def update_item(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseItemUpdate,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = _item_row(connection, release_item_id)
            _require_release_actor(
                connection,
                project_id=str(row.project_id),
                user_id=acting_user_id,
                approval=False,
            )
            if int(row.management_version) != command.expected_management_version:
                raise ReleaseConflict("release item management version changed")
            if ReleaseItemStatus(str(row.status)) in {
                ReleaseItemStatus.PUBLISHED,
                ReleaseItemStatus.WITHDRAWN,
            }:
                raise ReleaseConflict("published or withdrawn release items are immutable")
            project = _project_evidence(connection, str(row.project_id))
            clip = _current_clip(connection, project=project, clip_id=str(row.candidate_clip_id))
            if command.edit_plan_revision != int(clip.current_revision):
                raise ReleaseConflict("release item must bind the current clip revision")
            if command.assignee_user_id is not None:
                _require_active_project_member(
                    connection,
                    project_id=str(row.project_id),
                    user_id=command.assignee_user_id,
                )
            checklist = command.checklist
            before = _editable_values(row)
            after = {
                "edit_plan_revision": command.edit_plan_revision,
                "title": command.title,
                "title_variants": list(command.title_variants),
                "description": command.description,
                "hashtags": list(command.hashtags),
                "cta": command.cta,
                "caption_mode": command.caption_mode.value,
                "cover_time_ms": command.cover_time_ms,
                "assignee_user_id": command.assignee_user_id,
                "planned_publish_at": _timestamp(command.planned_publish_at),
                "checklist": checklist.model_dump(mode="json"),
            }
            if before == after:
                raise ReleaseConflict("release item update does not change any field")
            material_changed = any(
                before[key] != after[key]
                for key in (
                    "edit_plan_revision",
                    "title",
                    "title_variants",
                    "description",
                    "hashtags",
                    "cta",
                    "caption_mode",
                    "cover_time_ms",
                    "checklist",
                )
            )
            approval_status = (
                ReleaseApprovalStatus.DRAFT
                if material_changed
                else ReleaseApprovalStatus(str(row.approval_status))
            )
            status = ReleaseItemStatus(str(row.status))
            if material_changed or not checklist.complete:
                status = ReleaseItemStatus.DRAFT
            if (
                status is ReleaseItemStatus.SCHEDULED_EXTERNAL
                and command.planned_publish_at is None
            ):
                raise ReleaseConflict(
                    "an externally scheduled release requires a planned publish time"
                )
            preflight = _evaluate_preflight(
                connection,
                project=project,
                clip_id=str(row.candidate_clip_id),
                revision_id=str(clip.revision_id),
                selected_revision=command.edit_plan_revision,
                platform=ReleasePlatform(str(row.platform)),
                preset_version=str(row.preset_version),
                caption_mode=command.caption_mode,
                title=command.title,
                description=command.description,
                hashtags=command.hashtags,
                cover_time_ms=command.cover_time_ms,
                approval_status=approval_status,
                checklist=checklist,
            )
            changed = connection.execute(
                update(ReleaseItemRow)
                .where(
                    ReleaseItemRow.id == release_item_id,
                    ReleaseItemRow.management_version == command.expected_management_version,
                )
                .values(
                    edit_plan_revision_id=str(clip.revision_id),
                    edit_plan_revision=command.edit_plan_revision,
                    title=command.title,
                    title_variants_json=list(command.title_variants),
                    description=command.description,
                    hashtags_json=list(command.hashtags),
                    cta=command.cta,
                    caption_mode=command.caption_mode.value,
                    cover_time_ms=command.cover_time_ms,
                    assignee_user_id=command.assignee_user_id,
                    planned_publish_at=command.planned_publish_at,
                    approval_status=approval_status.value,
                    status=status.value,
                    checklist_json=checklist.model_dump(mode="json"),
                    preflight_json=preflight.model_dump(mode="json"),
                    management_version=ReleaseItemRow.management_version + 1,
                    external_url=None if material_changed else row.external_url,
                    external_id=None if material_changed else row.external_id,
                    published_at=None if material_changed else row.published_at,
                    result_notes=None if material_changed else row.result_notes,
                    updated_at=now,
                )
                .returning(ReleaseItemRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise ReleaseConflict("release item management version changed")
            _invalidate_active_release_packages(
                connection,
                release_item_id=release_item_id,
                acting_user_id=acting_user_id,
                correlation_id=correlation_id,
                instant=now,
            )
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action="release_item.updated",
                release_item_id=release_item_id,
                project_id=str(row.project_id),
                before={
                    **before,
                    "approval_status": str(row.approval_status),
                    "status": str(row.status),
                },
                after={
                    **after,
                    "approval_status": approval_status.value,
                    "status": status.value,
                    "management_version": command.expected_management_version + 1,
                },
                correlation_id=correlation_id,
                now=now,
            )
            return _get_item(connection, release_item_id)

    def transition_approval(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseApprovalCommand,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = _item_row(connection, release_item_id)
            current = ReleaseApprovalStatus(str(row.approval_status))
            _require_release_actor(
                connection,
                project_id=str(row.project_id),
                user_id=acting_user_id,
                approval=(
                    current is ReleaseApprovalStatus.APPROVED
                    or command.target
                    in {
                        ReleaseApprovalStatus.APPROVED,
                        ReleaseApprovalStatus.CHANGES_REQUESTED,
                    }
                ),
            )
            if int(row.management_version) != command.expected_management_version:
                raise ReleaseConflict("release item management version changed")
            if ReleaseItemStatus(str(row.status)) in {
                ReleaseItemStatus.PUBLISHED,
                ReleaseItemStatus.WITHDRAWN,
            }:
                raise ReleaseConflict("published or withdrawn release approval is immutable")
            try:
                transition_release_approval(current, command.target)
            except ReleaseTransitionError as exc:
                raise ReleaseConflict(str(exc)) from exc
            status = ReleaseItemStatus(str(row.status))
            if command.target is not ReleaseApprovalStatus.APPROVED:
                status = ReleaseItemStatus.DRAFT
            project = _project_evidence(connection, str(row.project_id))
            preflight = _evaluate_preflight_from_row(
                connection,
                project=project,
                row=row,
                approval_status=command.target,
            )
            changed = connection.execute(
                update(ReleaseItemRow)
                .where(
                    ReleaseItemRow.id == release_item_id,
                    ReleaseItemRow.management_version == command.expected_management_version,
                )
                .values(
                    approval_status=command.target.value,
                    status=status.value,
                    preflight_json=preflight.model_dump(mode="json"),
                    management_version=ReleaseItemRow.management_version + 1,
                    updated_at=now,
                )
                .returning(ReleaseItemRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise ReleaseConflict("release item management version changed")
            _invalidate_active_release_packages(
                connection,
                release_item_id=release_item_id,
                acting_user_id=acting_user_id,
                correlation_id=correlation_id,
                instant=now,
            )
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action="release_item.approval_changed",
                release_item_id=release_item_id,
                project_id=str(row.project_id),
                before={"approval_status": current.value, "status": str(row.status)},
                after={
                    "approval_status": command.target.value,
                    "status": status.value,
                    "reason": command.reason,
                    "management_version": command.expected_management_version + 1,
                },
                correlation_id=correlation_id,
                now=now,
            )
            return _get_item(connection, release_item_id)

    def transition_status(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: Any,
        correlation_id: str | None = None,
    ) -> ReleaseItemSnapshot:
        # ``Any`` is narrowed here to avoid a circular annotation import at runtime.
        from liveclip.application.releases import ReleaseStatusCommand

        if not isinstance(command, ReleaseStatusCommand):
            raise TypeError("release status command is invalid")
        now = datetime.now(UTC)
        artifact_stack = ExitStack()
        publication_artifacts: _PackageArtifactHashes | None = None
        try:
            if command.target is ReleaseItemStatus.PUBLISHED:
                if command.release_package_id is None:
                    raise ReleaseConflict("publication requires the exact platform package")
                with self._engine.connect() as read_connection:
                    prepared_item = _item_row(read_connection, release_item_id)
                    _require_release_actor(
                        read_connection,
                        project_id=str(prepared_item.project_id),
                        user_id=acting_user_id,
                        approval=False,
                    )
                    if int(prepared_item.management_version) != command.expected_management_version:
                        raise ReleaseConflict("release item management version changed")
                    try:
                        transition_release_item(
                            ReleaseItemStatus(str(prepared_item.status)),
                            command.target,
                        )
                    except ReleaseTransitionError as exc:
                        raise ReleaseConflict(str(exc)) from exc
                    _, publication_artifacts = _publication_evidence_from_package(
                        read_connection,
                        item=prepared_item,
                        release_package_id=command.release_package_id,
                        now=now,
                        data_dir=self._data_dir,
                        artifact_stack=artifact_stack,
                    )
        except Exception:
            artifact_stack.close()
            raise
        with artifact_stack, begin_immediate(self._engine) as connection:
            row = _item_row(connection, release_item_id)
            _require_release_actor(
                connection,
                project_id=str(row.project_id),
                user_id=acting_user_id,
                approval=False,
            )
            if int(row.management_version) != command.expected_management_version:
                raise ReleaseConflict("release item management version changed")
            current = ReleaseItemStatus(str(row.status))
            try:
                transition_release_item(current, command.target)
            except ReleaseTransitionError as exc:
                raise ReleaseConflict(str(exc)) from exc
            project = _project_evidence(connection, str(row.project_id))
            preflight = _evaluate_preflight_from_row(
                connection,
                project=project,
                row=row,
                approval_status=ReleaseApprovalStatus(str(row.approval_status)),
            )
            if (
                command.target
                in {
                    ReleaseItemStatus.READY,
                    ReleaseItemStatus.SCHEDULED_EXTERNAL,
                    ReleaseItemStatus.PUBLISHED,
                }
                and not preflight.passed
            ):
                raise ReleaseConflict(
                    "release preflight must pass before advancing publication status"
                )
            if (
                command.target is ReleaseItemStatus.SCHEDULED_EXTERNAL
                and row.planned_publish_at is None
            ):
                raise ReleaseConflict("external scheduling requires a planned publish time")
            if command.target is ReleaseItemStatus.PUBLISHED and project.lifecycle not in {
                ProjectLifecycle.READY_TO_PUBLISH,
                ProjectLifecycle.PUBLISHED,
            }:
                raise ReleaseConflict("project must be ready to publish before publication")
            publication_evidence = None
            if command.target is ReleaseItemStatus.PUBLISHED:
                if command.release_package_id is None:
                    raise ReleaseConflict("publication requires the exact platform package")
                if (
                    command.published_at is None
                    or _release_observed_utc(command.published_at, "published time")
                    > now + MAX_RELEASE_CLOCK_SKEW
                ):
                    raise ReleaseConflict("published time cannot be in the future")
                publication_evidence, publication_artifacts = _publication_evidence_from_package(
                    connection,
                    item=row,
                    release_package_id=command.release_package_id,
                    now=now,
                    expected_artifacts=publication_artifacts,
                )
            values: dict[str, object | None] = {
                "status": command.target.value,
                "preflight_json": preflight.model_dump(mode="json"),
                "management_version": ReleaseItemRow.management_version + 1,
                "updated_at": now,
            }
            if command.target is ReleaseItemStatus.PUBLISHED:
                values.update(
                    external_url=command.external_url,
                    external_id=command.external_id,
                    published_at=command.published_at,
                    result_notes=command.result_notes,
                )
            elif command.target is ReleaseItemStatus.FAILED:
                values.update(result_notes=command.result_notes)
            elif command.target is ReleaseItemStatus.DRAFT:
                values.update(
                    external_url=None,
                    external_id=None,
                    published_at=None,
                    result_notes=None,
                )
            elif command.target is ReleaseItemStatus.WITHDRAWN and command.result_notes:
                values.update(result_notes=command.result_notes)
            changed = connection.execute(
                update(ReleaseItemRow)
                .where(
                    ReleaseItemRow.id == release_item_id,
                    ReleaseItemRow.management_version == command.expected_management_version,
                )
                .values(**values)
                .returning(ReleaseItemRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise ReleaseConflict("release item management version changed")
            _invalidate_active_release_packages(
                connection,
                release_item_id=release_item_id,
                acting_user_id=acting_user_id,
                correlation_id=correlation_id,
                instant=now,
            )
            if publication_evidence is not None:
                connection.execute(
                    insert(ReleasePublicationEvidenceRow).values(
                        release_item_id=release_item_id,
                        release_package_id=publication_evidence.release_package_id,
                        release_item_version=publication_evidence.release_item_version,
                        package_version=int(publication_evidence.package_version[1:]),
                        preset_version=publication_evidence.preset_version,
                        caption_mode=publication_evidence.caption_mode.value,
                        video_sha256=publication_evidence.video_sha256,
                        artifact_kind=publication_evidence.artifact_kind,
                        artifact_sha256=publication_evidence.artifact_sha256,
                        manifest_sha256=publication_evidence.manifest_sha256,
                        zip_sha256=publication_evidence.zip_sha256,
                        recorded_at=publication_evidence.recorded_at,
                    )
                )
            if (
                command.target is ReleaseItemStatus.PUBLISHED
                and project.lifecycle is ProjectLifecycle.READY_TO_PUBLISH
            ):
                transition_project_lifecycle(
                    project.lifecycle,
                    ProjectLifecycle.PUBLISHED,
                )
                project_changed = connection.execute(
                    update(ProjectRow)
                    .where(
                        ProjectRow.id == project.project_id,
                        ProjectRow.lifecycle == ProjectLifecycle.READY_TO_PUBLISH.value,
                        ProjectRow.management_version == project.management_version,
                    )
                    .values(
                        lifecycle=ProjectLifecycle.PUBLISHED.value,
                        management_version=ProjectRow.management_version + 1,
                        updated_at=now,
                    )
                    .returning(ProjectRow.id)
                ).scalar_one_or_none()
                if project_changed is None:
                    raise ReleaseConflict("project lifecycle changed during publication")
                _audit_project_publication(
                    connection,
                    actor_user_id=acting_user_id,
                    project_id=project.project_id,
                    release_item_id=release_item_id,
                    management_version=project.management_version,
                    correlation_id=correlation_id,
                    now=now,
                )
            _audit(
                connection,
                actor_user_id=acting_user_id,
                action="release_item.status_changed",
                release_item_id=release_item_id,
                project_id=str(row.project_id),
                before={"status": current.value},
                after={
                    "status": command.target.value,
                    "external_url": command.external_url,
                    "external_id": command.external_id,
                    "published_at": _timestamp(command.published_at),
                    "result_notes": command.result_notes,
                    "publication_evidence": (
                        publication_evidence.model_dump(mode="json")
                        if publication_evidence is not None
                        else None
                    ),
                    "management_version": command.expected_management_version + 1,
                },
                correlation_id=correlation_id,
                now=now,
            )
            result = _get_item(connection, release_item_id)
            if publication_artifacts is not None:
                publication_artifacts.validate_final_binding()
            return result

    def add_metric(
        self,
        release_item_id: str,
        *,
        acting_user_id: str,
        command: ReleaseMetricCreate,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleaseItemSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = _item_row(connection, release_item_id)
            username = _require_release_actor(
                connection,
                project_id=str(row.project_id),
                user_id=acting_user_id,
                approval=False,
            )
            replay_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="release_metric",
            )
            if replay_id is not None:
                replay_item_id = connection.scalar(
                    select(ReleaseMetricSnapshotRow.release_item_id).where(
                        ReleaseMetricSnapshotRow.id == replay_id
                    )
                )
                if replay_item_id is None or str(replay_item_id) != release_item_id:
                    raise ReleaseConflict("idempotent release metric no longer exists")
                return _get_item(connection, release_item_id)
            status = ReleaseItemStatus(str(row.status))
            if status not in {ReleaseItemStatus.PUBLISHED, ReleaseItemStatus.WITHDRAWN}:
                raise ReleaseConflict("metrics require recorded publication evidence")
            if row.published_at is None:
                raise ReleaseConflict("metrics require a recorded publication time")
            captured_at = _release_observed_utc(command.captured_at, "metric capture time")
            published_at = _release_observed_utc(row.published_at, "published time")
            if captured_at > now + MAX_RELEASE_CLOCK_SKEW:
                raise ReleaseConflict("metric capture time cannot be in the future")
            if captured_at < published_at:
                raise ReleaseConflict("metric capture time cannot precede publication")
            metric_id = new_id()
            connection.execute(
                insert(ReleaseMetricSnapshotRow).values(
                    id=metric_id,
                    release_item_id=release_item_id,
                    recorded_by_user_id=acting_user_id,
                    captured_at=command.captured_at,
                    views=command.views,
                    likes=command.likes,
                    comments=command.comments,
                    shares=command.shares,
                    saves=command.saves,
                    followers_gained=command.followers_gained,
                    notes=command.notes,
                    created_at=now,
                )
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="release_metric",
                resource_id=metric_id,
                response_status_code=201,
            )
            connection.execute(
                insert(AuditEventRow).values(
                    id=new_id(),
                    actor_user_id=acting_user_id,
                    actor_username=username,
                    action="release_metric.recorded",
                    target_type="release_metric",
                    target_id=metric_id,
                    project_id=str(row.project_id),
                    before_json=None,
                    after_json={
                        "release_item_id": release_item_id,
                        "captured_at": command.captured_at.astimezone(UTC).isoformat(),
                        "views": command.views,
                        "likes": command.likes,
                        "comments": command.comments,
                        "shares": command.shares,
                        "saves": command.saves,
                        "followers_gained": command.followers_gained,
                    },
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
            return _get_item(connection, release_item_id)

    def get_item(self, release_item_id: str) -> ReleaseItemSnapshot:
        with self._engine.connect() as connection:
            return _get_item(connection, release_item_id)

    def list_items(self, project_id: str) -> tuple[ReleaseItemSnapshot, ...]:
        with self._engine.connect() as connection:
            if connection.scalar(select(ProjectRow.id).where(ProjectRow.id == project_id)) is None:
                raise ReleaseResourceNotFound("project does not exist")
            item_ids = tuple(
                str(value)
                for value in connection.scalars(
                    select(ReleaseItemRow.id)
                    .where(ReleaseItemRow.project_id == project_id)
                    .order_by(
                        ReleaseItemRow.planned_publish_at.is_(None),
                        ReleaseItemRow.planned_publish_at,
                        ReleaseItemRow.created_at,
                        ReleaseItemRow.id,
                    )
                )
            )
            return tuple(_get_item(connection, item_id) for item_id in item_ids)

    def enqueue_package(
        self,
        release_item_id: str,
        *,
        requested_by_user_id: str,
        request: ReleasePackageRequest,
        max_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> ReleasePackageSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            item = _item_row(connection, release_item_id)
            requester_username = _require_release_actor(
                connection,
                project_id=str(item.project_id),
                user_id=requested_by_user_id,
                approval=False,
            )
            replay_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="release_package",
            )
            if replay_id is not None:
                return _get_package(connection, replay_id)
            if int(item.management_version) != request.expected_release_item_version:
                raise ReleaseConflict("release item management version changed")
            if ReleaseItemStatus(str(item.status)) not in {
                ReleaseItemStatus.READY,
                ReleaseItemStatus.SCHEDULED_EXTERNAL,
            }:
                raise ReleaseConflict("release item must be ready before package creation")
            active_package_id = connection.scalar(
                select(ReleasePackageRow.id).where(
                    ReleasePackageRow.release_item_id == release_item_id,
                    ReleasePackageRow.status.in_(
                        [
                            ReleasePackageStatus.QUEUED.value,
                            ReleasePackageStatus.CREATING.value,
                        ]
                    ),
                )
            )
            if active_package_id is not None:
                raise ReleaseConflict("a release package is already queued or creating")
            project = _project_evidence(connection, str(item.project_id))
            payload, preflight, render, captions = _release_package_payload(
                connection,
                project=project,
                item=item,
                requested_by_user_id=requested_by_user_id,
                requested_by_username=requester_username,
            )
            if not preflight.passed:
                raise ReleaseConflict("release preflight changed before package creation")
            current_version = connection.scalar(
                select(func.max(ReleasePackageRow.version)).where(
                    ReleasePackageRow.release_item_id == release_item_id
                )
            )
            version = int(current_version or 0) + 1
            if version > 999:
                raise ReleaseConflict("release package version space is exhausted")
            release_package_id = new_id()
            task_id = new_id()
            snapshot_fingerprint = _canonical_fingerprint(payload)
            package_fingerprint = _release_package_task_fingerprint(
                snapshot_fingerprint=snapshot_fingerprint,
                release_package_id=release_package_id,
                version=version,
                include_zip=request.include_zip,
                created_at=now,
            )
            connection.execute(
                insert(TaskRow).values(
                    id=task_id,
                    kind=TaskKind.DELIVERY.value,
                    target_id=release_package_id,
                    operation_key=f"release-package:{release_package_id}",
                    input_fingerprint=package_fingerprint,
                    resource_class=ResourceClass.HEAVY.value,
                    pipeline_run_id=project.run_id,
                    status=TaskStatus.QUEUED.value,
                    priority=660,
                    not_before=now,
                    expected_generation=project.generation,
                    expected_revision_epoch=project.revision_epoch,
                    attempt_count=0,
                    retry_count=0,
                    manual_retry_count=0,
                    max_retries=max_retries,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(ReleasePackageRow).values(
                    id=release_package_id,
                    release_item_id=release_item_id,
                    project_id=project.project_id,
                    requested_by_user_id=requested_by_user_id,
                    task_id=task_id,
                    version=version,
                    status=ReleasePackageStatus.QUEUED.value,
                    expected_generation=project.generation,
                    expected_revision_epoch=project.revision_epoch,
                    expected_release_item_version=int(item.management_version),
                    preset_version=str(item.preset_version),
                    caption_mode=str(item.caption_mode),
                    snapshot_fingerprint=snapshot_fingerprint,
                    snapshot_json=payload,
                    directory_relative_path=(f"release-packages/{release_item_id}/v{version:03d}"),
                    source_render_job_id=render.render_job_id,
                    source_video_asset_id=render.video_asset_id,
                    include_zip=request.include_zip,
                    created_at=now,
                )
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="release_package",
                resource_id=release_package_id,
            )
            _audit(
                connection,
                actor_user_id=requested_by_user_id,
                action="release_package.queued",
                release_item_id=release_item_id,
                project_id=project.project_id,
                before=None,
                after={
                    "release_package_id": release_package_id,
                    "version": f"v{version:03d}",
                    "caption_mode": str(item.caption_mode),
                    "include_zip": request.include_zip,
                    "caption_count": len(captions),
                    "requested_by": requester_username,
                },
                correlation_id=None,
                now=now,
            )
            return _get_package(connection, release_package_id)

    def get_package(self, release_package_id: str) -> ReleasePackageSnapshot:
        with self._engine.connect() as connection:
            return _get_package(connection, release_package_id)

    def is_release_package_task(self, task_id: str, target_id: str) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.scalar(
                    select(ReleasePackageRow.id).where(
                        ReleasePackageRow.id == target_id,
                        ReleasePackageRow.task_id == task_id,
                    )
                )
                is not None
            )

    def start_release_package(self, lease: LeaseIdentity) -> ReleasePackageWork:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = _leased_release_package_row(connection, lease, now=now)
            if row is None:
                raise ReleaseConflict("release package task lost its active lease")
            work = _release_package_work(connection, row)
            _assert_release_package_work_current(connection, work)
            transition_release_package(
                ReleasePackageStatus(str(row.package_status)),
                ReleasePackageStatus.CREATING,
            )
            changed = connection.execute(
                update(ReleasePackageRow)
                .where(
                    ReleasePackageRow.id == work.release_package_id,
                    ReleasePackageRow.status == ReleasePackageStatus.QUEUED.value,
                )
                .values(
                    status=ReleasePackageStatus.CREATING.value,
                    error_code=None,
                    safe_error_message=None,
                )
                .returning(ReleasePackageRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise ReleaseConflict("release package is not queued")
            return work

    def assert_release_package_current(
        self,
        lease: LeaseIdentity,
        work: ReleasePackageWork,
    ) -> None:
        now = datetime.now(UTC)
        with self._engine.connect() as connection:
            task = connection.execute(
                select(TaskRow.status, TaskRow.input_fingerprint).where(
                    TaskRow.id == lease.task_id,
                    TaskRow.id == work.task_id,
                    TaskRow.target_id == work.release_package_id,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    TaskRow.cancellation_requested_at.is_(None),
                )
            ).one_or_none()
            if (
                task is None
                or task.status != TaskStatus.RUNNING.value
                or str(task.input_fingerprint) != work.package_fingerprint
            ):
                raise ReleaseConflict("release package task is no longer publishable")
            _assert_release_package_work_current(connection, work)

    def complete_release_package(
        self,
        lease: LeaseIdentity,
        work: ReleasePackageWork,
        persistence: ReleasePackagePersistence,
    ) -> bool:
        now = datetime.now(UTC)
        asset_ids = [persistence.manifest_asset_id]
        if persistence.zip_asset_id is not None:
            asset_ids.append(persistence.zip_asset_id)
        if len(set(asset_ids)) != len(asset_ids):
            raise ReleaseConflict("release package assets must be distinct")
        with begin_immediate(self._engine) as connection:
            row = _leased_release_package_row(connection, lease, now=now)
            if row is None or str(row.release_package_id) != work.release_package_id:
                return False
            try:
                _assert_release_package_work_current(connection, work)
            except ReleaseConflict:
                return False
            if str(row.input_fingerprint) != work.package_fingerprint:
                return False
            assets = connection.execute(
                select(
                    AssetRow.id,
                    AssetRow.kind,
                    AssetRow.relative_path,
                    AssetRow.input_fingerprint,
                    AssetRow.sha256,
                    AssetRow.size_bytes,
                    AssetRow.generation,
                    AssetRow.revision_epoch,
                    AssetRow.producer_attempt_id,
                    AssetRow.validation_json,
                ).where(
                    AssetRow.id.in_(asset_ids),
                    AssetRow.project_id == work.project_id,
                    AssetRow.status == AssetStatus.COMMITTED.value,
                )
            ).all()
            by_id = {str(asset.id): asset for asset in assets}
            if set(by_id) != set(asset_ids):
                raise ReleaseConflict("release package requires committed package assets")
            attempt_ids = {
                str(asset.producer_attempt_id)
                for asset in assets
                if asset.producer_attempt_id is not None
            }
            task_ids = {
                str(value)
                for value in connection.scalars(
                    select(TaskAttemptRow.task_id).where(TaskAttemptRow.id.in_(attempt_ids))
                )
            }
            if any(asset.producer_attempt_id is None for asset in assets) or task_ids != {
                lease.task_id
            }:
                raise ReleaseConflict("release package assets belong to another task")
            _validate_release_package_assets(
                by_id,
                work=work,
                persistence=persistence,
            )
            transition_release_package(
                ReleasePackageStatus(str(row.package_status)),
                ReleasePackageStatus.SUCCEEDED,
            )
            changed = connection.execute(
                update(ReleasePackageRow)
                .where(
                    ReleasePackageRow.id == work.release_package_id,
                    ReleasePackageRow.status == ReleasePackageStatus.CREATING.value,
                )
                .values(
                    status=ReleasePackageStatus.SUCCEEDED.value,
                    manifest_asset_id=persistence.manifest_asset_id,
                    zip_asset_id=persistence.zip_asset_id,
                    manifest_sha256=persistence.manifest_sha256,
                    zip_sha256=persistence.zip_sha256,
                    error_code=None,
                    safe_error_message=None,
                    completed_at=now,
                )
            )
            if changed.rowcount != 1:
                return False
            transition_task(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
            connection.execute(
                update(TaskRow)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                )
                .values(
                    status=TaskStatus.SUCCEEDED.value,
                    worker_id=None,
                    lease_token=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                update(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
                .values(outcome=AttemptOutcome.SUCCEEDED.value, finished_at=now)
            )
            _audit(
                connection,
                actor_user_id=work.requested_by_user_id,
                action="release_package.succeeded",
                release_item_id=work.release_item_id,
                project_id=work.project_id,
                before={"status": ReleasePackageStatus.CREATING.value},
                after={
                    "release_package_id": work.release_package_id,
                    "status": ReleasePackageStatus.SUCCEEDED.value,
                    "version": f"v{work.version:03d}",
                },
                correlation_id=None,
                now=now,
            )
            return True


def _release_package_payload(
    connection: Connection,
    *,
    project: _ProjectEvidence,
    item: Any,
    requested_by_user_id: str,
    requested_by_username: str | None = None,
    frozen_artifact_context: _ReleaseArtifactContext | None = None,
) -> tuple[dict[str, object], ReleasePreflight, _RenderEvidence, tuple[CaptionCue, ...]]:
    preflight = _evaluate_preflight_from_row(
        connection,
        project=project,
        row=item,
        approval_status=ReleaseApprovalStatus(str(item.approval_status)),
    )
    render = _trusted_render(
        connection,
        project=project,
        clip_id=str(item.candidate_clip_id),
        revision_id=str(item.edit_plan_revision_id),
        revision=int(item.edit_plan_revision),
        caption_mode=ReleaseCaptionMode(str(item.caption_mode)),
    )
    if render is None:
        raise ReleaseConflict("release package has no trusted current source render")
    captions = _captions(connection, str(item.edit_plan_revision_id))
    revision = connection.execute(
        select(
            EditPlanRevisionRow.source_start_ms,
            EditPlanRevisionRow.source_end_ms,
            EditPlanRevisionRow.score,
            EditPlanRevisionRow.plan_json,
            EditPlanRevisionRow.risk_flags_json,
        ).where(EditPlanRevisionRow.id == item.edit_plan_revision_id)
    ).one_or_none()
    if revision is None:
        raise ReleaseConflict("release package edit-plan revision is missing")
    plan = edit_plan_from_json_data(revision.plan_json)
    artifact_context = frozen_artifact_context
    if artifact_context is None:
        if requested_by_username is None:
            raise ReleaseConflict("release package requester snapshot is missing")
        artifact_context = _ReleaseArtifactContext(
            project_name=project.project_name,
            requested_by_username=requested_by_username,
            source_preflight=preflight,
        )
    payload: dict[str, object] = {
        "schema_version": "liveclip.release-package-snapshot.v1",
        "release_item_id": str(item.id),
        "release_item_management_version": int(item.management_version),
        "requested_by_user_id": requested_by_user_id,
        "artifact_context": artifact_context.as_payload(),
        "project": {
            "project_id": project.project_id,
            "run_id": project.run_id,
            "generation": project.generation,
            "revision_epoch": project.revision_epoch,
            "source_filename": project.source_filename,
            "source_fingerprint": project.source_fingerprint,
        },
        "release": {
            "clip_id": str(item.candidate_clip_id),
            "edit_plan_revision_id": str(item.edit_plan_revision_id),
            "edit_plan_revision": int(item.edit_plan_revision),
            "platform": str(item.platform),
            "preset_version": str(item.preset_version),
            "account_label": str(item.account_label),
            "title": str(item.title),
            "title_variants": list(item.title_variants_json),
            "description": str(item.description),
            "hashtags": list(item.hashtags_json),
            "cta": str(item.cta),
            "caption_mode": str(item.caption_mode),
            "cover_time_ms": int(item.cover_time_ms),
            "source_start_ms": int(revision.source_start_ms),
            "source_end_ms": int(revision.source_end_ms),
            "score": float(revision.score),
            "high_impact_sentence": plan.hook,
            "risk_flags": [str(value) for value in revision.risk_flags_json],
            "planned_publish_at": _timestamp(item.planned_publish_at),
            "checklist": _checklist(item.checklist_json).model_dump(mode="json"),
            # Duplicate-content evidence is live advisory state. It must remain
            # visible to operators without invalidating an otherwise exact
            # immutable package when another clip is exported later.
            "preflight": _material_package_preflight(preflight).model_dump(mode="json"),
        },
        "render": {
            "render_job_id": render.render_job_id,
            "render_spec_fingerprint": render.render_spec_fingerprint,
            "producer_task_id": render.producer_task_id,
            "producer_attempt_id": render.producer_attempt_id,
            "video_asset_id": render.video_asset_id,
            "video_relative_path": render.video_relative_path,
            "video_sha256": render.video_sha256,
            "video_size_bytes": render.video_size_bytes,
            "video_input_fingerprint": render.video_input_fingerprint,
            "subtitle_asset_id": render.subtitle_asset_id,
            "subtitle_sha256": render.subtitle_sha256,
            "subtitle_size_bytes": render.subtitle_size_bytes,
            "quality_asset_id": render.quality_asset_id,
            "quality_sha256": render.quality_sha256,
            "quality_size_bytes": render.quality_size_bytes,
            "contact_sheet_asset_id": render.contact_sheet_asset_id,
            "contact_sheet_sha256": render.contact_sheet_sha256,
            "contact_sheet_size_bytes": render.contact_sheet_size_bytes,
            "width": render.width,
            "height": render.height,
            "revision_epoch": render.revision_epoch,
        },
        "captions": [caption.model_dump(mode="json") for caption in captions],
    }
    return payload, preflight, render, captions


def _material_package_preflight(preflight: ReleasePreflight) -> ReleasePreflight:
    checks = tuple(check for check in preflight.checks if check.code != "duplicate_content")
    blockers = sum(check.outcome == "blocked" for check in checks)
    warnings = sum(check.outcome == "warning" for check in checks)
    return preflight.model_copy(
        update={
            "checks": checks,
            "passed": blockers == 0,
            "blocker_count": blockers,
            "warning_count": warnings,
        }
    )


def _release_package_task_fingerprint(
    *,
    snapshot_fingerprint: str,
    release_package_id: str,
    version: int,
    include_zip: bool,
    created_at: datetime,
) -> str:
    return _canonical_fingerprint(
        {
            "schema_version": "liveclip.release-package-task.v1",
            "snapshot_fingerprint": snapshot_fingerprint,
            "release_package_id": release_package_id,
            "version": version,
            "include_zip": include_zip,
            "created_at": created_at.astimezone(UTC).isoformat(),
        }
    )


def _canonical_fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _leased_release_package_row(
    connection: Connection,
    lease: LeaseIdentity,
    *,
    now: datetime,
) -> Any | None:
    requester = aliased(WorkspaceUserRow)
    return connection.execute(
        select(
            TaskRow.id.label("task_id"),
            TaskRow.target_id,
            TaskRow.input_fingerprint,
            TaskRow.expected_generation,
            TaskRow.expected_revision_epoch,
            ReleasePackageRow.id.label("release_package_id"),
            ReleasePackageRow.release_item_id,
            ReleasePackageRow.project_id,
            ReleasePackageRow.requested_by_user_id,
            ReleasePackageRow.version,
            ReleasePackageRow.status.label("package_status"),
            ReleasePackageRow.expected_generation.label("package_generation"),
            ReleasePackageRow.expected_revision_epoch.label("package_revision_epoch"),
            ReleasePackageRow.expected_release_item_version,
            ReleasePackageRow.preset_version,
            ReleasePackageRow.caption_mode,
            ReleasePackageRow.snapshot_fingerprint,
            ReleasePackageRow.snapshot_json,
            ReleasePackageRow.source_render_job_id,
            ReleasePackageRow.source_video_asset_id,
            ReleasePackageRow.include_zip,
            ReleasePackageRow.created_at.label("package_created_at"),
            requester.username.label("requester_username"),
        )
        .join(ReleasePackageRow, ReleasePackageRow.task_id == TaskRow.id)
        .join(requester, requester.id == ReleasePackageRow.requested_by_user_id)
        .where(
            TaskRow.id == lease.task_id,
            TaskRow.kind == TaskKind.DELIVERY.value,
            TaskRow.status == TaskStatus.RUNNING.value,
            TaskRow.worker_id == lease.worker_id,
            TaskRow.lease_token == lease.lease_token,
            TaskRow.lease_expires_at > now,
            TaskRow.cancellation_requested_at.is_(None),
        )
    ).one_or_none()


def _release_package_work(connection: Connection, row: Any) -> ReleasePackageWork:
    item = _item_row(connection, str(row.release_item_id))
    project = _project_evidence(connection, str(row.project_id))
    _require_release_actor(
        connection,
        project_id=project.project_id,
        user_id=str(row.requested_by_user_id),
        approval=False,
    )
    stored_snapshot = _json_object(row.snapshot_json, label="release package snapshot")
    artifact_context = _release_artifact_context(stored_snapshot)
    payload, live_preflight, render, captions = _release_package_payload(
        connection,
        project=project,
        item=item,
        requested_by_user_id=str(row.requested_by_user_id),
        frozen_artifact_context=artifact_context,
    )
    if not live_preflight.passed:
        raise ReleaseConflict("release package preflight changed")
    snapshot_fingerprint = _canonical_fingerprint(payload)
    if stored_snapshot != payload or snapshot_fingerprint != str(row.snapshot_fingerprint):
        raise ReleaseConflict("release package snapshot changed")
    package_fingerprint = _release_package_task_fingerprint(
        snapshot_fingerprint=snapshot_fingerprint,
        release_package_id=str(row.release_package_id),
        version=int(row.version),
        include_zip=bool(row.include_zip),
        created_at=row.package_created_at,
    )
    if package_fingerprint != str(row.input_fingerprint):
        raise ReleaseConflict("release package task fingerprint changed")
    return ReleasePackageWork(
        release_package_id=str(row.release_package_id),
        release_item_id=str(row.release_item_id),
        task_id=str(row.task_id),
        project_id=project.project_id,
        project_name=artifact_context.project_name,
        requested_by_user_id=str(row.requested_by_user_id),
        requested_by_username=artifact_context.requested_by_username,
        run_id=project.run_id,
        generation=project.generation,
        revision_epoch=project.revision_epoch,
        release_item_version=int(item.management_version),
        version=int(row.version),
        preset=get_platform_preset(
            ReleasePlatform(str(item.platform)),
            version=str(item.preset_version),
        ),
        caption_mode=ReleaseCaptionMode(str(item.caption_mode)),
        include_zip=bool(row.include_zip),
        snapshot_fingerprint=snapshot_fingerprint,
        package_fingerprint=package_fingerprint,
        snapshot=payload,
        created_at=row.package_created_at,
        source_filename=project.source_filename,
        source_fingerprint=project.source_fingerprint,
        source_render_job_id=render.render_job_id,
        source_video_asset_id=render.video_asset_id,
        source_video_relative_path=render.video_relative_path,
        source_video_sha256=render.video_sha256,
        source_video_size_bytes=render.video_size_bytes,
        clip_id=str(item.candidate_clip_id),
        edit_plan_revision=int(item.edit_plan_revision),
        source_start_ms=_release_int(payload, "source_start_ms"),
        source_end_ms=_release_int(payload, "source_end_ms"),
        score=_release_float(payload, "score"),
        high_impact_sentence=str(_release_value(payload, "high_impact_sentence")),
        risk_flags=tuple(str(value) for value in _release_list(payload, "risk_flags")),
        account_label=str(item.account_label),
        planned_publish_at=item.planned_publish_at,
        title=str(item.title),
        description=str(item.description),
        title_variants=tuple(str(value) for value in item.title_variants_json),
        hashtags=tuple(str(value) for value in item.hashtags_json),
        cta=str(item.cta),
        cover_time_ms=int(item.cover_time_ms),
        captions=captions,
        preflight=artifact_context.source_preflight,
        checklist=_checklist(item.checklist_json),
    )


def _assert_release_package_work_current(
    connection: Connection,
    work: ReleasePackageWork,
) -> None:
    package = _release_package_row(connection, work.release_package_id)
    if (
        package.task_id is None
        or str(package.task_id) != work.task_id
        or int(package.version) != work.version
        or int(package.expected_release_item_version) != work.release_item_version
        or str(package.source_render_job_id) != work.source_render_job_id
        or str(package.source_video_asset_id) != work.source_video_asset_id
        or package.status
        not in {
            ReleasePackageStatus.QUEUED.value,
            ReleasePackageStatus.CREATING.value,
        }
    ):
        raise ReleaseConflict("release package persistence fence changed")
    item = _item_row(connection, work.release_item_id)
    if int(item.management_version) != work.release_item_version or ReleaseItemStatus(
        str(item.status)
    ) not in {ReleaseItemStatus.READY, ReleaseItemStatus.SCHEDULED_EXTERNAL}:
        raise ReleaseConflict("release item changed after package selection")
    project = _project_evidence(connection, work.project_id)
    if (
        project.run_id != work.run_id
        or project.generation != work.generation
        or project.revision_epoch != work.revision_epoch
        or project.source_fingerprint != work.source_fingerprint
        or int(package.expected_generation) != work.generation
        or int(package.expected_revision_epoch) != work.revision_epoch
    ):
        raise ReleaseConflict("project changed after release-package selection")
    _require_release_actor(
        connection,
        project_id=work.project_id,
        user_id=work.requested_by_user_id,
        approval=False,
    )
    payload, preflight, render, captions = _release_package_payload(
        connection,
        project=project,
        item=item,
        requested_by_user_id=work.requested_by_user_id,
        frozen_artifact_context=_release_artifact_context(work.snapshot),
    )
    if not preflight.passed:
        raise ReleaseConflict("release preflight changed after package selection")
    if (
        payload != work.snapshot
        or _canonical_fingerprint(payload) != work.snapshot_fingerprint
        or render.render_job_id != work.source_render_job_id
        or render.video_asset_id != work.source_video_asset_id
        or render.video_sha256 != work.source_video_sha256
        or render.video_size_bytes != work.source_video_size_bytes
        or captions != work.captions
    ):
        raise ReleaseConflict("release package source evidence changed")
    task = connection.execute(
        select(TaskRow.target_id, TaskRow.input_fingerprint).where(
            TaskRow.id == work.task_id,
            TaskRow.kind == TaskKind.DELIVERY.value,
        )
    ).one_or_none()
    if (
        task is None
        or str(task.target_id) != work.release_package_id
        or str(task.input_fingerprint) != work.package_fingerprint
    ):
        raise ReleaseConflict("release package task evidence changed")


def _validate_release_package_assets(
    by_id: Mapping[str, Any],
    *,
    work: ReleasePackageWork,
    persistence: ReleasePackagePersistence,
) -> None:
    base = f"release-packages/{work.release_item_id}/v{work.version:03d}"
    manifest = by_id[persistence.manifest_asset_id]
    validation = manifest.validation_json
    if (
        manifest.kind != "release_package_manifest"
        or manifest.relative_path != f"{base}/manifest.json"
        or manifest.input_fingerprint != work.package_fingerprint
        or manifest.sha256 != persistence.manifest_sha256
        or int(manifest.size_bytes or 0) <= 0
        or manifest.generation is None
        or int(manifest.generation) != work.generation
        or manifest.revision_epoch is None
        or int(manifest.revision_epoch) != work.revision_epoch
        or not isinstance(validation, dict)
        or validation.get("schema_version") != "liveclip.release-package.v1"
        or validation.get("release_package_id") != work.release_package_id
        or validation.get("snapshot_fingerprint") != work.snapshot_fingerprint
    ):
        raise ReleaseConflict("release package manifest asset is invalid")
    if work.include_zip:
        if persistence.zip_asset_id is None or persistence.zip_sha256 is None:
            raise ReleaseConflict("release package ZIP is missing")
        archive = by_id[persistence.zip_asset_id]
        archive_validation = archive.validation_json
        if (
            archive.kind != "release_package_zip"
            or archive.relative_path != f"{base}/{release_archive_name(work)}"
            or archive.input_fingerprint != work.package_fingerprint
            or archive.sha256 != persistence.zip_sha256
            or int(archive.size_bytes or 0) <= 0
            or archive.generation is None
            or int(archive.generation) != work.generation
            or archive.revision_epoch is None
            or int(archive.revision_epoch) != work.revision_epoch
            or not isinstance(archive_validation, dict)
            or archive_validation.get("schema_version") != "liveclip.release-package.v1"
            or archive_validation.get("release_package_id") != work.release_package_id
            or archive_validation.get("snapshot_fingerprint") != work.snapshot_fingerprint
        ):
            raise ReleaseConflict("release package ZIP asset is invalid")
    elif persistence.zip_asset_id is not None or persistence.zip_sha256 is not None:
        raise ReleaseConflict("non-ZIP release package unexpectedly has a ZIP asset")


def _release_package_select() -> Select[Any]:
    return select(
        ReleasePackageRow.id,
        ReleasePackageRow.release_item_id,
        ReleasePackageRow.project_id,
        ReleasePackageRow.requested_by_user_id,
        ReleasePackageRow.task_id,
        ReleasePackageRow.version,
        ReleasePackageRow.status,
        ReleasePackageRow.expected_generation,
        ReleasePackageRow.expected_revision_epoch,
        ReleasePackageRow.expected_release_item_version,
        ReleasePackageRow.preset_version,
        ReleasePackageRow.caption_mode,
        ReleasePackageRow.snapshot_fingerprint,
        ReleasePackageRow.snapshot_json,
        ReleasePackageRow.directory_relative_path,
        ReleasePackageRow.source_render_job_id,
        ReleasePackageRow.source_video_asset_id,
        ReleasePackageRow.manifest_asset_id,
        ReleasePackageRow.zip_asset_id,
        ReleasePackageRow.manifest_sha256,
        ReleasePackageRow.zip_sha256,
        ReleasePackageRow.include_zip,
        ReleasePackageRow.error_code,
        ReleasePackageRow.safe_error_message,
        ReleasePackageRow.created_at,
        ReleasePackageRow.completed_at,
    )


def _release_package_row(connection: Connection, release_package_id: str) -> Any:
    row = connection.execute(
        _release_package_select().where(ReleasePackageRow.id == release_package_id)
    ).one_or_none()
    if row is None:
        raise ReleaseResourceNotFound("release package does not exist")
    return row


def _get_package(
    connection: Connection,
    release_package_id: str,
) -> ReleasePackageSnapshot:
    row = _release_package_row(connection, release_package_id)
    if row.task_id is None:
        raise ReleaseResourceNotFound("release package does not exist")
    published_package_id = connection.scalar(
        select(ReleasePublicationEvidenceRow.release_package_id).where(
            ReleasePublicationEvidenceRow.release_item_id == row.release_item_id
        )
    )
    return _package_snapshot(
        connection,
        row,
        published_package_id=(
            str(published_package_id) if published_package_id is not None else None
        ),
    )


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ReleaseConflict(f"{label} is invalid")
    return dict(value)


def _release_value(payload: dict[str, object], key: str) -> object:
    release = payload.get("release")
    if not isinstance(release, dict) or key not in release:
        raise ReleaseConflict("release package snapshot metadata is invalid")
    return release[key]


def _release_list(payload: dict[str, object], key: str) -> list[object]:
    value = _release_value(payload, key)
    if not isinstance(value, list):
        raise ReleaseConflict("release package snapshot list is invalid")
    return value


def _release_int(payload: dict[str, object], key: str) -> int:
    value = _release_value(payload, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReleaseConflict("release package snapshot integer is invalid")
    return value


def _release_float(payload: dict[str, object], key: str) -> float:
    value = _release_value(payload, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReleaseConflict("release package snapshot score is invalid")
    return float(value)


def _release_artifact_context(payload: dict[str, object]) -> _ReleaseArtifactContext:
    raw = payload.get("artifact_context")
    if not isinstance(raw, dict):
        raise ReleaseConflict("release package artifact context is missing")
    project_name = raw.get("project_name")
    requested_by_username = raw.get("requested_by_username")
    source_preflight = raw.get("source_preflight")
    if (
        not isinstance(project_name, str)
        or not project_name.strip()
        or not isinstance(requested_by_username, str)
        or not requested_by_username.strip()
        or not isinstance(source_preflight, dict)
    ):
        raise ReleaseConflict("release package artifact context is invalid")
    try:
        preflight = ReleasePreflight.model_validate_json(
            json.dumps(source_preflight, ensure_ascii=False)
        )
    except ValueError as exc:
        raise ReleaseConflict("release package artifact preflight is invalid") from exc
    return _ReleaseArtifactContext(
        project_name=project_name,
        requested_by_username=requested_by_username,
        source_preflight=preflight,
    )


def _project_evidence(
    connection: Connection,
    project_id: str,
    *,
    require_mutable: bool = True,
) -> _ProjectEvidence:
    row = connection.execute(
        select(
            ProjectRow.id,
            ProjectRow.name,
            ProjectRow.lifecycle,
            ProjectRow.management_version,
            ProjectRow.current_pipeline_run_id,
            ProjectRow.current_generation,
            ProjectRow.revision_epoch,
            PipelineRunRow.status.label("run_status"),
            PipelineRunRow.config_json,
            SourceMediaRow.filename,
            SourceMediaRow.sha256,
        )
        .join(PipelineRunRow, PipelineRunRow.id == ProjectRow.current_pipeline_run_id)
        .join(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
        .where(ProjectRow.id == project_id)
    ).one_or_none()
    if row is None or row.current_pipeline_run_id is None:
        raise ReleaseResourceNotFound("project does not exist")
    if require_mutable and row.lifecycle == ProjectLifecycle.ARCHIVED.value:
        raise ReleaseConflict("archived projects cannot be used for release planning")
    if require_mutable and row.run_status != PipelineRunStatus.COMPLETED.value:
        raise ReleaseConflict("project pipeline is not complete")
    if not isinstance(row.config_json, dict):
        raise ReleaseConflict("project pipeline configuration is invalid")
    return _ProjectEvidence(
        project_id=str(row.id),
        project_name=str(row.name),
        run_id=str(row.current_pipeline_run_id),
        generation=int(row.current_generation),
        revision_epoch=int(row.revision_epoch),
        lifecycle=ProjectLifecycle(str(row.lifecycle)),
        management_version=int(row.management_version),
        pipeline_config=dict(row.config_json),
        source_filename=str(row.filename),
        source_fingerprint=str(row.sha256),
    )


def _current_clip(
    connection: Connection,
    *,
    project: _ProjectEvidence,
    clip_id: str,
) -> Any:
    row = connection.execute(
        select(
            CandidateClipRow.id,
            CandidateClipRow.current_revision,
            EditPlanRevisionRow.id.label("revision_id"),
            EditPlanRevisionRow.plan_json,
            EditPlanRevisionRow.source_start_ms,
            EditPlanRevisionRow.source_end_ms,
        )
        .join(
            EditPlanRevisionRow,
            (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
            & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
        )
        .where(
            CandidateClipRow.id == clip_id,
            CandidateClipRow.project_id == project.project_id,
            CandidateClipRow.pipeline_run_id == project.run_id,
            CandidateClipRow.selected_for_review.is_(True),
        )
    ).one_or_none()
    if row is None:
        raise ReleaseResourceNotFound("clip does not exist in the current project run")
    return row


def _require_release_actor(
    connection: Connection,
    *,
    project_id: str,
    user_id: str,
    approval: bool,
) -> str:
    row = connection.execute(
        select(
            WorkspaceUserRow.username,
            WorkspaceUserRow.is_active,
            ProjectMemberRow.role,
            ProjectRow.lifecycle,
        )
        .join(ProjectMemberRow, ProjectMemberRow.user_id == WorkspaceUserRow.id)
        .join(ProjectRow, ProjectRow.id == ProjectMemberRow.project_id)
        .where(
            WorkspaceUserRow.id == user_id,
            ProjectMemberRow.project_id == project_id,
        )
    ).one_or_none()
    if row is None or not row.is_active:
        raise ReleaseConflict("requester no longer has release permission")
    try:
        require_project_action(
            cast(WorkspaceRole, str(row.role)),
            "approve_release" if approval else "manage_release",
            archived=str(row.lifecycle) == ProjectLifecycle.ARCHIVED.value,
        )
    except ProjectActionDenied as exc:
        raise ReleaseConflict("requester no longer has release permission") from exc
    return str(row.username)


def _require_active_project_member(
    connection: Connection,
    *,
    project_id: str,
    user_id: str,
) -> None:
    member = connection.execute(
        select(ProjectMemberRow.id, ProjectMemberRow.role)
        .join(WorkspaceUserRow, WorkspaceUserRow.id == ProjectMemberRow.user_id)
        .where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.user_id == user_id,
            WorkspaceUserRow.is_active.is_(True),
        )
    ).one_or_none()
    if member is None:
        raise ReleaseConflict("release assignee must be an active project member")
    try:
        require_project_action(
            cast(WorkspaceRole, str(member.role)),
            "manage_release",
            archived=False,
        )
    except ProjectActionDenied as exc:
        raise ReleaseConflict("release assignee must be a project owner or editor") from exc


def _item_row(connection: Connection, release_item_id: str) -> Any:
    row = connection.execute(
        select(
            ReleaseItemRow.id,
            ReleaseItemRow.project_id,
            ReleaseItemRow.candidate_clip_id,
            ReleaseItemRow.edit_plan_revision_id,
            ReleaseItemRow.edit_plan_revision,
            ReleaseItemRow.platform,
            ReleaseItemRow.preset_version,
            ReleaseItemRow.account_label,
            ReleaseItemRow.title,
            ReleaseItemRow.title_variants_json,
            ReleaseItemRow.description,
            ReleaseItemRow.hashtags_json,
            ReleaseItemRow.cta,
            ReleaseItemRow.caption_mode,
            ReleaseItemRow.cover_time_ms,
            ReleaseItemRow.assignee_user_id,
            ReleaseItemRow.planned_publish_at,
            ReleaseItemRow.approval_status,
            ReleaseItemRow.status,
            ReleaseItemRow.checklist_json,
            ReleaseItemRow.preflight_json,
            ReleaseItemRow.management_version,
            ReleaseItemRow.external_url,
            ReleaseItemRow.external_id,
            ReleaseItemRow.published_at,
            ReleaseItemRow.result_notes,
            ReleaseItemRow.created_by_user_id,
            ReleaseItemRow.created_at,
            ReleaseItemRow.updated_at,
        ).where(ReleaseItemRow.id == release_item_id)
    ).one_or_none()
    if row is None:
        raise ReleaseResourceNotFound("release item does not exist")
    return row


def _captions(connection: Connection, revision_id: str) -> tuple[CaptionCue, ...]:
    return tuple(
        CaptionCue(
            start_ms=int(row.start_ms),
            end_ms=int(row.end_ms),
            text=str(row.text),
        )
        for row in connection.execute(
            select(CaptionCueRow.start_ms, CaptionCueRow.end_ms, CaptionCueRow.text)
            .where(CaptionCueRow.edit_plan_revision_id == revision_id)
            .order_by(CaptionCueRow.cue_index)
        )
    )


def _review_approved(connection: Connection, revision_id: str) -> bool:
    status = connection.scalar(
        select(ReviewDecisionRow.status)
        .where(ReviewDecisionRow.edit_plan_revision_id == revision_id)
        .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
        .limit(1)
    )
    return status == ReviewStatus.APPROVED.value


def _trusted_render(
    connection: Connection,
    *,
    project: _ProjectEvidence,
    clip_id: str,
    revision_id: str,
    revision: int,
    caption_mode: ReleaseCaptionMode,
) -> _RenderEvidence | None:
    kind = "proxy" if caption_mode is ReleaseCaptionMode.CLEAN_SEPARATE else "final"
    renders = connection.execute(
        select(
            RenderJobRow.id,
            RenderJobRow.task_id,
            RenderJobRow.asset_id,
            RenderJobRow.subtitle_asset_id,
            RenderJobRow.quality_report_asset_id,
            RenderJobRow.contact_sheet_asset_id,
            RenderJobRow.width,
            RenderJobRow.height,
            RenderJobRow.revision_epoch,
            RenderJobRow.spec_fingerprint,
            RenderJobRow.spec_json,
        )
        .where(
            RenderJobRow.candidate_clip_id == clip_id,
            RenderJobRow.edit_plan_revision_id == revision_id,
            RenderJobRow.edit_plan_revision == revision,
            RenderJobRow.kind == kind,
            RenderJobRow.status == RenderStatus.SUCCEEDED.value,
            RenderJobRow.asset_id.is_not(None),
        )
        .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
    ).all()
    for render in renders:
        contract_ok = (
            is_clean_review_proxy(
                spec=render.spec_json,
                pipeline_config=project.pipeline_config,
            )
            if kind == "proxy"
            else has_current_manual_render_contract("final", render.spec_json)
        )
        if (
            not contract_ok
            or render.task_id is None
            or render.asset_id is None
            or render.quality_report_asset_id is None
            or render.contact_sheet_asset_id is None
        ):
            continue
        asset_ids = {
            str(render.asset_id),
            str(render.quality_report_asset_id),
            str(render.contact_sheet_asset_id),
        }
        if render.subtitle_asset_id is not None:
            asset_ids.add(str(render.subtitle_asset_id))
        assets = connection.execute(
            select(
                AssetRow.id,
                AssetRow.kind,
                AssetRow.relative_path,
                AssetRow.sha256,
                AssetRow.size_bytes,
                AssetRow.generation,
                AssetRow.edit_plan_revision,
                AssetRow.revision_epoch,
                AssetRow.input_fingerprint,
                AssetRow.producer_attempt_id,
                AssetRow.validation_json,
            ).where(
                AssetRow.id.in_(asset_ids),
                AssetRow.project_id == project.project_id,
                AssetRow.candidate_clip_id == clip_id,
                AssetRow.status == AssetStatus.COMMITTED.value,
            )
        ).all()
        by_id = {str(asset.id): asset for asset in assets}
        if set(by_id) != asset_ids:
            continue
        asset = by_id[str(render.asset_id)]
        quality = by_id[str(render.quality_report_asset_id)]
        contact = by_id[str(render.contact_sheet_asset_id)]
        subtitle = (
            by_id[str(render.subtitle_asset_id)] if render.subtitle_asset_id is not None else None
        )
        expected_kind = "review_proxy" if kind == "proxy" else "final_video"
        if (
            asset.kind != expected_kind
            or not asset.sha256
            or int(asset.size_bytes or 0) <= 0
            or asset.generation is None
            or int(asset.generation) != project.generation
            or asset.edit_plan_revision is None
            or int(asset.edit_plan_revision) != revision
            or asset.revision_epoch is None
            or int(asset.revision_epoch) != int(render.revision_epoch)
            or int(render.revision_epoch) > project.revision_epoch
            or asset.producer_attempt_id is None
            or not isinstance(asset.validation_json, dict)
            or asset.validation_json.get("full_decode") != "passed"
            or asset.validation_json.get("width") != int(render.width)
            or asset.validation_json.get("height") != int(render.height)
            or quality.kind != "render_quality_report"
            or not isinstance(quality.validation_json, dict)
            or quality.validation_json.get("automatic_status") != "passed"
            or contact.kind != "render_contact_sheet"
            or not isinstance(contact.validation_json, dict)
            or isinstance(contact.validation_json.get("frames"), bool)
            or not isinstance(contact.validation_json.get("frames"), int)
            or int(contact.validation_json["frames"]) < 3
            or (subtitle is not None and subtitle.kind != "clip_subtitle_srt")
            or (
                subtitle is not None
                and (
                    not isinstance(subtitle.validation_json, dict)
                    or subtitle.validation_json.get("timeline") != "clip_relative_ms"
                )
            )
        ):
            continue
        evidence_assets = tuple(by_id.values())
        if any(
            not item.sha256
            or int(item.size_bytes or 0) <= 0
            or item.generation is None
            or int(item.generation) != project.generation
            or item.edit_plan_revision is None
            or int(item.edit_plan_revision) != revision
            or item.revision_epoch is None
            or int(item.revision_epoch) != int(render.revision_epoch)
            or item.producer_attempt_id is None
            for item in evidence_assets
        ):
            continue
        producer_attempt_ids = {str(item.producer_attempt_id) for item in evidence_assets}
        if len(producer_attempt_ids) != 1:
            continue
        producer = connection.execute(
            select(
                TaskAttemptRow.outcome,
                TaskRow.id.label("task_id"),
                TaskRow.kind,
                TaskRow.status.label("task_status"),
                TaskRow.pipeline_run_id,
                TaskRow.input_fingerprint,
                StageRunRow.stage,
            )
            .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
            .outerjoin(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
            .where(TaskAttemptRow.id == next(iter(producer_attempt_ids)))
        ).one_or_none()
        if (
            producer is None
            or str(producer.task_id) != str(render.task_id)
            or str(producer.pipeline_run_id) != project.run_id
            or producer.task_status != TaskStatus.SUCCEEDED.value
            or producer.outcome != AttemptOutcome.SUCCEEDED.value
            or any(
                str(producer.input_fingerprint) != str(item.input_fingerprint)
                for item in evidence_assets
            )
        ):
            continue
        if producer.kind == TaskKind.RENDER.value:
            if (
                subtitle is None
                or producer.stage is not None
                or str(producer.input_fingerprint) != str(render.spec_fingerprint)
            ):
                continue
        elif producer.kind == TaskKind.STAGE.value:
            if kind != "proxy" or producer.stage != PipelineStage.PROXY_RENDER.value:
                continue
        else:
            continue
        return _RenderEvidence(
            render_job_id=str(render.id),
            video_asset_id=str(asset.id),
            video_relative_path=str(asset.relative_path),
            video_sha256=str(asset.sha256),
            video_size_bytes=int(asset.size_bytes),
            video_input_fingerprint=str(asset.input_fingerprint),
            subtitle_asset_id=str(subtitle.id) if subtitle is not None else None,
            subtitle_sha256=str(subtitle.sha256) if subtitle is not None else None,
            subtitle_size_bytes=(int(subtitle.size_bytes) if subtitle is not None else None),
            quality_asset_id=str(quality.id),
            quality_sha256=str(quality.sha256),
            quality_size_bytes=int(quality.size_bytes),
            contact_sheet_asset_id=str(contact.id),
            contact_sheet_sha256=str(contact.sha256),
            contact_sheet_size_bytes=int(contact.size_bytes),
            producer_task_id=str(producer.task_id),
            producer_attempt_id=next(iter(producer_attempt_ids)),
            render_spec_fingerprint=str(render.spec_fingerprint),
            width=int(render.width),
            height=int(render.height),
            revision_epoch=int(render.revision_epoch),
        )
    return None


def _duplicate_content_matches(
    connection: Connection,
    *,
    project_id: str,
    source_start_ms: int,
    source_end_ms: int,
    text: str,
    exclude_release_item_id: str | None = None,
) -> tuple[ReleaseDuplicateContentMatch, ...]:
    """Find prior exports/publications that substantially repeat this clip.

    The check is advisory. It intentionally spans immutable editor packages,
    formal deliveries and the exact immutable snapshots of platform packages.
    """

    current_ngrams = _content_ngrams(text)
    matches: list[ReleaseDuplicateContentMatch] = []
    published_package_ids = {
        str(value)
        for value in connection.scalars(select(ReleasePublicationEvidenceRow.release_package_id))
    }
    release_package_query = select(
        ReleasePackageRow.id,
        ReleasePackageRow.version,
        ReleasePackageRow.snapshot_json,
    ).where(
        ReleasePackageRow.project_id == project_id,
        ReleasePackageRow.status == ReleasePackageStatus.SUCCEEDED.value,
    )
    if exclude_release_item_id is not None:
        # The item's own immutable package history is already shown alongside
        # the task. Treating it as duplicate content would make every newly
        # completed package warn about itself and obscure true cross-task reuse.
        release_package_query = release_package_query.where(
            ReleasePackageRow.release_item_id != exclude_release_item_id
        )
    release_packages = connection.execute(release_package_query).all()
    for row in release_packages:
        try:
            payload = _json_object(row.snapshot_json, label="release package snapshot")
            platform = ReleasePlatform(str(_release_value(payload, "platform")))
            account_label = str(_release_value(payload, "account_label"))
            title = str(_release_value(payload, "title"))
            description = str(_release_value(payload, "description"))
            hook = str(_release_value(payload, "high_impact_sentence"))
            package_start_ms = _release_int(payload, "source_start_ms")
            package_end_ms = _release_int(payload, "source_end_ms")
        except (ReleaseConflict, ValueError):
            continue
        raw_captions = payload.get("captions")
        caption_text = (
            " ".join(str(cue.get("text", "")) for cue in raw_captions if isinstance(cue, dict))
            if isinstance(raw_captions, list)
            else ""
        )
        package_id = str(row.id)
        _append_duplicate_match(
            matches,
            current_start_ms=source_start_ms,
            current_end_ms=source_end_ms,
            current_ngrams=current_ngrams,
            other_start_ms=package_start_ms,
            other_end_ms=package_end_ms,
            other_text=" ".join((title, description, hook, caption_text)),
            reference_id=package_id,
            reference_label=(f"{platform.value} · {account_label} · v{int(row.version):03d}")[:160],
            evidence_kind=(
                "published" if package_id in published_package_ids else "release_package"
            ),
        )

    edit_rows = connection.execute(
        select(
            EditPackageRow.id,
            EditPackageRow.version,
            EditPlanRevisionRow.source_start_ms,
            EditPlanRevisionRow.source_end_ms,
            EditPlanRevisionRow.title,
            EditPlanRevisionRow.hook,
            EditPlanRevisionRow.reason,
            CandidateClipRow.transcript_text,
        )
        .select_from(EditPackageClipRow)
        .join(EditPackageRow, EditPackageRow.id == EditPackageClipRow.edit_package_id)
        .join(
            EditPlanRevisionRow,
            EditPlanRevisionRow.id == EditPackageClipRow.edit_plan_revision_id,
        )
        .join(CandidateClipRow, CandidateClipRow.id == EditPackageClipRow.candidate_clip_id)
        .where(
            EditPackageRow.project_id == project_id,
            EditPackageRow.status == EditPackageStatus.SUCCEEDED.value,
        )
    ).all()
    for row in edit_rows:
        _append_duplicate_match(
            matches,
            current_start_ms=source_start_ms,
            current_end_ms=source_end_ms,
            current_ngrams=current_ngrams,
            other_start_ms=int(row.source_start_ms),
            other_end_ms=int(row.source_end_ms),
            other_text=" ".join(
                (str(row.title), str(row.hook), str(row.reason), str(row.transcript_text))
            ),
            reference_id=str(row.id),
            reference_label=f"剪辑交接包 v{int(row.version):03d}",
            evidence_kind="edit_package",
        )

    delivery_rows = connection.execute(
        select(
            DeliveryRow.id,
            DeliveryRow.version,
            DeliveryClipRow.source_start_ms,
            DeliveryClipRow.source_end_ms,
            DeliveryClipRow.title,
            EditPlanRevisionRow.hook,
            EditPlanRevisionRow.reason,
            CandidateClipRow.transcript_text,
        )
        .select_from(DeliveryClipRow)
        .join(DeliveryRow, DeliveryRow.id == DeliveryClipRow.delivery_id)
        .join(
            EditPlanRevisionRow,
            EditPlanRevisionRow.id == DeliveryClipRow.edit_plan_revision_id,
        )
        .join(CandidateClipRow, CandidateClipRow.id == DeliveryClipRow.candidate_clip_id)
        .where(
            DeliveryRow.project_id == project_id,
            DeliveryRow.status == DeliveryStatus.SUCCEEDED.value,
        )
    ).all()
    for row in delivery_rows:
        _append_duplicate_match(
            matches,
            current_start_ms=source_start_ms,
            current_end_ms=source_end_ms,
            current_ngrams=current_ngrams,
            other_start_ms=int(row.source_start_ms),
            other_end_ms=int(row.source_end_ms),
            other_text=" ".join(
                (str(row.title), str(row.hook), str(row.reason), str(row.transcript_text))
            ),
            reference_id=str(row.id),
            reference_label=f"正式交付 v{int(row.version):03d}",
            evidence_kind="delivery",
        )
    matches.sort(
        key=lambda item: (item.source_overlap_ratio, item.text_similarity),
        reverse=True,
    )
    return tuple(matches[:5])


def _append_duplicate_match(
    matches: list[ReleaseDuplicateContentMatch],
    *,
    current_start_ms: int,
    current_end_ms: int,
    current_ngrams: frozenset[str],
    other_start_ms: int,
    other_end_ms: int,
    other_text: str,
    reference_id: str,
    reference_label: str,
    evidence_kind: Literal[
        "release_package",
        "published",
        "edit_package",
        "delivery",
    ],
) -> None:
    overlap = _source_overlap_ratio(
        current_start_ms,
        current_end_ms,
        other_start_ms,
        other_end_ms,
    )
    other_ngrams = _content_ngrams(other_text)
    similarity = (
        len(current_ngrams & other_ngrams) / len(current_ngrams | other_ngrams)
        if current_ngrams and other_ngrams
        else 0.0
    )
    if overlap < 0.6 and similarity < 0.72:
        return
    matches.append(
        ReleaseDuplicateContentMatch(
            reference_id=reference_id,
            reference_label=reference_label,
            evidence_kind=evidence_kind,
            source_overlap_ratio=float(overlap),
            text_similarity=float(similarity),
        )
    )


def _source_overlap_ratio(
    start_ms: int,
    end_ms: int,
    other_start_ms: int,
    other_end_ms: int,
) -> float:
    overlap = max(0, min(end_ms, other_end_ms) - max(start_ms, other_start_ms))
    shorter = min(end_ms - start_ms, other_end_ms - other_start_ms)
    return overlap / shorter if shorter > 0 else 0.0


def _content_ngrams(value: str) -> frozenset[str]:
    normalized = re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)
    if len(normalized) < 4:
        return frozenset()
    return frozenset(normalized[index : index + 2] for index in range(len(normalized) - 1))


def _evaluate_preflight(
    connection: Connection,
    *,
    project: _ProjectEvidence,
    clip_id: str,
    revision_id: str,
    selected_revision: int,
    platform: ReleasePlatform,
    preset_version: str,
    caption_mode: ReleaseCaptionMode,
    title: str,
    description: str,
    hashtags: tuple[str, ...],
    cover_time_ms: int,
    approval_status: ReleaseApprovalStatus,
    checklist: ReleaseChecklist,
    exclude_release_item_id: str | None = None,
) -> ReleasePreflight:
    current = connection.execute(
        select(
            CandidateClipRow.current_revision,
            CandidateClipRow.pipeline_run_id,
            CandidateClipRow.project_id,
            CandidateClipRow.selected_for_review,
            CandidateClipRow.transcript_text,
        ).where(CandidateClipRow.id == clip_id)
    ).one_or_none()
    if current is None:
        raise ReleaseResourceNotFound("release clip does not exist")
    current_project_run = (
        str(current.project_id) == project.project_id
        and str(current.pipeline_run_id) == project.run_id
        and bool(current.selected_for_review)
    )
    revision = connection.execute(
        select(
            EditPlanRevisionRow.source_start_ms,
            EditPlanRevisionRow.source_end_ms,
            EditPlanRevisionRow.risk_flags_json,
            EditPlanRevisionRow.title,
            EditPlanRevisionRow.hook,
            EditPlanRevisionRow.reason,
        ).where(
            EditPlanRevisionRow.id == revision_id,
            EditPlanRevisionRow.candidate_clip_id == clip_id,
            EditPlanRevisionRow.revision == selected_revision,
        )
    ).one_or_none()
    if revision is None:
        raise ReleaseConflict("release edit-plan revision no longer exists")
    captions = _captions(connection, revision_id)
    duration_ms = int(revision.source_end_ms) - int(revision.source_start_ms)
    render = (
        _trusted_render(
            connection,
            project=project,
            clip_id=clip_id,
            revision_id=revision_id,
            revision=selected_revision,
            caption_mode=caption_mode,
        )
        if current_project_run
        else None
    )
    available = render is not None
    media = ReleaseMediaFacts(
        available=available,
        trusted_render_contract=available,
        container="mp4" if available else "",
        video_codec="h264" if available else "",
        audio_codec="aac" if available else "",
        pixel_format="yuv420p" if available else "",
        progressive=available,
        fast_start=available,
        full_decode=available,
        width=render.width if render else 0,
        height=render.height if render else 0,
        duration_ms=duration_ms,
        size_bytes=render.video_size_bytes if render else 0,
        separate_subtitle_available=bool(captions),
        format_evidence=("trusted_render_contract" if available else "unavailable"),
    )
    editorial = ReleaseEditorialFacts(
        selected_revision=selected_revision,
        current_revision=int(current.current_revision),
        clip_review_approved=_review_approved(connection, revision_id),
        release_approval=approval_status,
        title=title,
        description=description,
        hashtags=hashtags,
        cover_time_ms=cover_time_ms,
        caption_mode=caption_mode,
        captions=captions,
        risk_flags=tuple(str(value) for value in revision.risk_flags_json),
        checklist=checklist,
        current_project_run=current_project_run,
        duplicate_content_matches=_duplicate_content_matches(
            connection,
            project_id=project.project_id,
            source_start_ms=int(revision.source_start_ms),
            source_end_ms=int(revision.source_end_ms),
            text=" ".join(
                (
                    title,
                    description,
                    str(revision.title),
                    str(revision.hook),
                    str(revision.reason),
                    str(current.transcript_text),
                )
            ),
            exclude_release_item_id=exclude_release_item_id,
        ),
    )
    return evaluate_release_preflight(
        preset=get_platform_preset(platform, version=preset_version),
        media=media,
        editorial=editorial,
    )


def _evaluate_preflight_from_row(
    connection: Connection,
    *,
    project: _ProjectEvidence,
    row: Any,
    approval_status: ReleaseApprovalStatus,
) -> ReleasePreflight:
    return _evaluate_preflight(
        connection,
        project=project,
        clip_id=str(row.candidate_clip_id),
        revision_id=str(row.edit_plan_revision_id),
        selected_revision=int(row.edit_plan_revision),
        platform=ReleasePlatform(str(row.platform)),
        preset_version=str(row.preset_version),
        caption_mode=ReleaseCaptionMode(str(row.caption_mode)),
        title=str(row.title),
        description=str(row.description),
        hashtags=tuple(str(value) for value in row.hashtags_json),
        cover_time_ms=int(row.cover_time_ms),
        approval_status=approval_status,
        checklist=_checklist(row.checklist_json),
        exclude_release_item_id=str(row.id),
    )


def _get_item(connection: Connection, release_item_id: str) -> ReleaseItemSnapshot:
    row = _item_row(connection, release_item_id)
    project = _project_evidence(
        connection,
        str(row.project_id),
        require_mutable=False,
    )
    current_revision = connection.scalar(
        select(CandidateClipRow.current_revision).where(
            CandidateClipRow.id == row.candidate_clip_id
        )
    )
    if current_revision is None:
        raise ReleaseResourceNotFound("release clip does not exist")
    revision = connection.execute(
        select(
            EditPlanRevisionRow.source_start_ms,
            EditPlanRevisionRow.source_end_ms,
            EditPlanRevisionRow.plan_json,
            EditPlanRevisionRow.risk_flags_json,
        ).where(EditPlanRevisionRow.id == row.edit_plan_revision_id)
    ).one_or_none()
    if revision is None:
        raise ReleaseResourceNotFound("release edit-plan revision does not exist")
    plan = edit_plan_from_json_data(revision.plan_json)
    checklist = _checklist(row.checklist_json)
    preflight = _evaluate_preflight_from_row(
        connection,
        project=project,
        row=row,
        approval_status=ReleaseApprovalStatus(str(row.approval_status)),
    )
    current_project_run = (
        next(check for check in preflight.checks if check.code == "current_project_run").outcome
        == "passed"
    )
    preview_render = (
        _trusted_render(
            connection,
            project=project,
            clip_id=str(row.candidate_clip_id),
            revision_id=str(row.edit_plan_revision_id),
            revision=int(row.edit_plan_revision),
            caption_mode=ReleaseCaptionMode(str(row.caption_mode)),
        )
        if current_project_run
        else None
    )
    assignee = None
    if row.assignee_user_id is not None:
        user = connection.execute(
            select(
                WorkspaceUserRow.id,
                WorkspaceUserRow.username,
                WorkspaceUserRow.display_name,
            ).where(WorkspaceUserRow.id == row.assignee_user_id)
        ).one_or_none()
        if user is not None:
            assignee = ReleaseAssignee(
                user_id=str(user.id),
                username=str(user.username),
                display_name=str(user.display_name),
            )
    metrics = _metrics(connection, release_item_id)
    publication_evidence = _publication_evidence(connection, release_item_id)
    packages = _packages(
        connection,
        release_item_id,
        published_package_id=(
            publication_evidence.release_package_id if publication_evidence is not None else None
        ),
    )
    stale_reason: Literal["revision_changed", "project_run_changed"] | None = None
    if not current_project_run:
        stale_reason = "project_run_changed"
    elif int(row.edit_plan_revision) != int(current_revision):
        stale_reason = "revision_changed"
    return ReleaseItemSnapshot(
        release_item_id=release_item_id,
        project_id=str(row.project_id),
        clip_id=str(row.candidate_clip_id),
        edit_plan_revision=int(row.edit_plan_revision),
        current_edit_plan_revision=int(current_revision),
        stale=stale_reason is not None,
        stale_reason=stale_reason,
        platform=ReleasePlatform(str(row.platform)),
        preset_version=str(row.preset_version),
        account_label=str(row.account_label),
        title=str(row.title),
        title_variants=tuple(str(value) for value in row.title_variants_json),
        description=str(row.description),
        hashtags=tuple(str(value) for value in row.hashtags_json),
        cta=str(row.cta),
        caption_mode=ReleaseCaptionMode(str(row.caption_mode)),
        cover_time_ms=int(row.cover_time_ms),
        clip_duration_ms=int(revision.source_end_ms) - int(revision.source_start_ms),
        high_impact_sentence=plan.hook,
        risk_flags=tuple(str(value) for value in revision.risk_flags_json),
        preview_asset_id=(preview_render.video_asset_id if preview_render is not None else None),
        assignee=assignee,
        planned_publish_at=row.planned_publish_at,
        approval_status=ReleaseApprovalStatus(str(row.approval_status)),
        status=ReleaseItemStatus(str(row.status)),
        checklist=checklist,
        preflight=preflight,
        management_version=int(row.management_version),
        external_url=str(row.external_url) if row.external_url is not None else None,
        external_id=str(row.external_id) if row.external_id is not None else None,
        published_at=row.published_at,
        result_notes=str(row.result_notes) if row.result_notes is not None else None,
        publication_evidence=publication_evidence,
        metrics=metrics,
        packages=packages,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _metrics(
    connection: Connection,
    release_item_id: str,
) -> tuple[ReleaseMetricSnapshot, ...]:
    recorder = aliased(WorkspaceUserRow)
    rows = connection.execute(
        select(
            ReleaseMetricSnapshotRow.id,
            ReleaseMetricSnapshotRow.captured_at,
            ReleaseMetricSnapshotRow.views,
            ReleaseMetricSnapshotRow.likes,
            ReleaseMetricSnapshotRow.comments,
            ReleaseMetricSnapshotRow.shares,
            ReleaseMetricSnapshotRow.saves,
            ReleaseMetricSnapshotRow.followers_gained,
            ReleaseMetricSnapshotRow.notes,
            ReleaseMetricSnapshotRow.created_at,
            recorder.username,
        )
        .join(recorder, recorder.id == ReleaseMetricSnapshotRow.recorded_by_user_id)
        .where(ReleaseMetricSnapshotRow.release_item_id == release_item_id)
        .order_by(
            ReleaseMetricSnapshotRow.captured_at.desc(),
            ReleaseMetricSnapshotRow.id.desc(),
        )
    )
    return tuple(
        ReleaseMetricSnapshot(
            metric_id=str(row.id),
            captured_at=row.captured_at,
            views=int(row.views),
            likes=int(row.likes),
            comments=int(row.comments),
            shares=int(row.shares),
            saves=int(row.saves),
            followers_gained=int(row.followers_gained),
            notes=str(row.notes) if row.notes is not None else None,
            recorded_by_username=str(row.username),
            created_at=row.created_at,
        )
        for row in rows
    )


def _packages(
    connection: Connection,
    release_item_id: str,
    *,
    published_package_id: str | None,
) -> tuple[ReleasePackageSnapshot, ...]:
    rows = connection.execute(
        select(
            ReleasePackageRow.id,
            ReleasePackageRow.release_item_id,
            ReleasePackageRow.project_id,
            ReleasePackageRow.requested_by_user_id,
            ReleasePackageRow.task_id,
            ReleasePackageRow.version,
            ReleasePackageRow.expected_generation,
            ReleasePackageRow.expected_revision_epoch,
            ReleasePackageRow.expected_release_item_version,
            ReleasePackageRow.status,
            ReleasePackageRow.preset_version,
            ReleasePackageRow.caption_mode,
            ReleasePackageRow.snapshot_fingerprint,
            ReleasePackageRow.snapshot_json,
            ReleasePackageRow.manifest_asset_id,
            ReleasePackageRow.zip_asset_id,
            ReleasePackageRow.manifest_sha256,
            ReleasePackageRow.zip_sha256,
            ReleasePackageRow.include_zip,
            ReleasePackageRow.error_code,
            ReleasePackageRow.safe_error_message,
            ReleasePackageRow.created_at,
            ReleasePackageRow.completed_at,
        )
        .where(ReleasePackageRow.release_item_id == release_item_id)
        .order_by(ReleasePackageRow.version.desc())
    )
    return tuple(
        _package_snapshot(
            connection,
            row,
            published_package_id=published_package_id,
        )
        for row in rows
        if row.task_id is not None
    )


def _package_snapshot(
    connection: Connection,
    row: Any,
    *,
    published_package_id: str | None,
) -> ReleasePackageSnapshot:
    artifact_hashes = _package_artifact_hashes(connection, row)
    published_artifact = str(row.id) == published_package_id
    return ReleasePackageSnapshot(
        release_package_id=row.id,
        release_item_id=row.release_item_id,
        project_id=row.project_id,
        task_id=str(row.task_id),
        requested_by_user_id=row.requested_by_user_id,
        version=row.version,
        package_version=f"v{row.version:03d}",
        release_item_version=int(row.expected_release_item_version),
        current=_release_package_matches_current_content(connection, row) or published_artifact,
        published_artifact=published_artifact,
        status=ReleasePackageStatus(row.status),
        preset_version=row.preset_version,
        caption_mode=ReleaseCaptionMode(row.caption_mode),
        manifest_asset_id=row.manifest_asset_id,
        zip_asset_id=row.zip_asset_id,
        video_sha256=_package_video_sha256(row.snapshot_json),
        manifest_sha256=artifact_hashes.manifest_sha256,
        zip_sha256=artifact_hashes.zip_sha256,
        include_zip=row.include_zip,
        error_code=row.error_code,
        safe_error_message=row.safe_error_message,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _publication_evidence(
    connection: Connection,
    release_item_id: str,
) -> ReleasePublicationEvidence | None:
    row = connection.execute(
        select(
            ReleasePublicationEvidenceRow.release_package_id,
            ReleasePublicationEvidenceRow.release_item_version,
            ReleasePublicationEvidenceRow.package_version,
            ReleasePublicationEvidenceRow.preset_version,
            ReleasePublicationEvidenceRow.caption_mode,
            ReleasePublicationEvidenceRow.video_sha256,
            ReleasePublicationEvidenceRow.artifact_kind,
            ReleasePublicationEvidenceRow.artifact_sha256,
            ReleasePublicationEvidenceRow.manifest_sha256,
            ReleasePublicationEvidenceRow.zip_sha256,
            ReleasePublicationEvidenceRow.recorded_at,
        ).where(ReleasePublicationEvidenceRow.release_item_id == release_item_id)
    ).one_or_none()
    if row is None:
        return None
    return ReleasePublicationEvidence(
        release_package_id=str(row.release_package_id),
        package_version=f"v{int(row.package_version):03d}",
        release_item_version=int(row.release_item_version),
        preset_version=str(row.preset_version),
        caption_mode=ReleaseCaptionMode(str(row.caption_mode)),
        video_sha256=str(row.video_sha256),
        artifact_kind=_publication_artifact_kind(row.artifact_kind),
        artifact_sha256=str(row.artifact_sha256),
        manifest_sha256=str(row.manifest_sha256),
        zip_sha256=str(row.zip_sha256) if row.zip_sha256 is not None else None,
        recorded_at=row.recorded_at,
    )


def _publication_evidence_from_package(
    connection: Connection,
    *,
    item: Any,
    release_package_id: str,
    now: datetime,
    data_dir: Path | None = None,
    artifact_stack: ExitStack | None = None,
    expected_artifacts: _PackageArtifactHashes | None = None,
) -> tuple[ReleasePublicationEvidence, _PackageArtifactHashes]:
    package = _release_package_row(connection, release_package_id)
    if (
        str(package.release_item_id) != str(item.id)
        or package.task_id is None
        or ReleasePackageStatus(str(package.status)) is not ReleasePackageStatus.SUCCEEDED
    ):
        raise ReleaseConflict("publication package is not a successful package for this item")
    if not _release_package_matches_current_content(connection, package):
        raise ReleaseConflict("publication package does not match current release content")
    if str(package.preset_version) != str(item.preset_version) or str(package.caption_mode) != str(
        item.caption_mode
    ):
        raise ReleaseConflict("publication package does not match the current release settings")
    artifact_hashes = _package_artifact_hashes(
        connection,
        package,
        data_dir=data_dir,
        artifact_stack=artifact_stack,
        expected=expected_artifacts,
    )
    manifest_sha256 = artifact_hashes.manifest_sha256
    zip_sha256 = artifact_hashes.zip_sha256
    if manifest_sha256 is None:
        raise ReleaseConflict("publication package manifest evidence is missing")
    if bool(package.include_zip):
        if zip_sha256 is None:
            raise ReleaseConflict("publication package ZIP evidence is missing")
        artifact_kind: Literal["zip", "manifest"] = "zip"
        artifact_sha256 = zip_sha256
    else:
        artifact_kind = "manifest"
        artifact_sha256 = manifest_sha256
    return (
        ReleasePublicationEvidence(
            release_package_id=str(package.id),
            package_version=f"v{int(package.version):03d}",
            release_item_version=int(package.expected_release_item_version),
            preset_version=str(package.preset_version),
            caption_mode=ReleaseCaptionMode(str(package.caption_mode)),
            video_sha256=_package_video_sha256(package.snapshot_json),
            artifact_kind=artifact_kind,
            artifact_sha256=artifact_sha256,
            manifest_sha256=manifest_sha256,
            zip_sha256=zip_sha256,
            recorded_at=now,
        ),
        artifact_hashes,
    )


def _package_video_sha256(snapshot: object) -> str:
    payload = _json_object(snapshot, label="release package snapshot")
    render = payload.get("render")
    if not isinstance(render, dict):
        raise ReleaseConflict("release package video evidence is missing")
    digest = render.get("video_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        raise ReleaseConflict("release package video evidence is invalid")
    return digest


def _publication_artifact_kind(value: object) -> Literal["zip", "manifest"]:
    if value == "zip":
        return "zip"
    if value == "manifest":
        return "manifest"
    raise ReleaseConflict("release publication artifact kind is invalid")


def _release_package_matches_current_content(
    connection: Connection,
    package: Any,
) -> bool:
    try:
        item = _item_row(connection, str(package.release_item_id))
        project = _project_evidence(connection, str(package.project_id))
        stored = _json_object(package.snapshot_json, label="release package snapshot")
        payload, preflight, _render, _captions = _release_package_payload(
            connection,
            project=project,
            item=item,
            requested_by_user_id=str(package.requested_by_user_id),
            frozen_artifact_context=_release_artifact_context(stored),
        )
        if not preflight.passed:
            return False
        payload["release_item_management_version"] = int(package.expected_release_item_version)
        return (
            int(package.expected_generation) == project.generation
            and int(package.expected_revision_epoch) == project.revision_epoch
            and payload == stored
            and _canonical_fingerprint(stored) == str(package.snapshot_fingerprint)
        )
    except (LookupError, ReleaseConflict):
        return False


def _package_artifact_hashes(
    connection: Connection,
    package: Any,
    *,
    data_dir: Path | None = None,
    artifact_stack: ExitStack | None = None,
    expected: _PackageArtifactHashes | None = None,
) -> _PackageArtifactHashes:
    if (data_dir is None) != (artifact_stack is None):
        raise RuntimeError(
            "release artifact data directory and pin stack must be provided together"
        )
    if expected is not None and data_dir is not None:
        raise RuntimeError("release artifact verification modes cannot be combined")
    requested: dict[str, tuple[str, str]] = {}
    if package.manifest_asset_id is not None:
        requested[str(package.manifest_asset_id)] = (
            "manifest",
            "release_package_manifest",
        )
    if package.zip_asset_id is not None:
        requested[str(package.zip_asset_id)] = ("zip", "release_package_zip")
    if not requested:
        if expected is not None and expected.pinned:
            raise ReleaseConflict("release package artifact evidence changed before publication")
        return _PackageArtifactHashes(manifest_sha256=None, zip_sha256=None)
    rows = connection.execute(
        select(
            AssetRow.id,
            AssetRow.kind,
            AssetRow.status,
            AssetRow.sha256,
            AssetRow.relative_path,
            AssetRow.size_bytes,
        ).where(
            AssetRow.id.in_(requested),
            AssetRow.project_id == package.project_id,
        )
    ).all()
    by_id = {str(row.id): row for row in rows}
    if set(by_id) != set(requested):
        raise ReleaseConflict("release package artifact evidence is missing")
    hashes: dict[str, str] = {}
    pinned_artifacts: list[_PinnedPackageArtifact] = []
    expected_by_id = (
        {artifact.asset_id: artifact for artifact in expected.pinned}
        if expected is not None
        else {}
    )
    if expected is not None and set(expected_by_id) != set(requested):
        raise ReleaseConflict("release package artifact evidence changed before publication")
    for asset_id, (label, kind) in requested.items():
        asset = by_id[asset_id]
        digest = asset.sha256
        relative_path = str(asset.relative_path)
        size_bytes = asset.size_bytes
        if (
            asset.status != AssetStatus.COMMITTED.value
            or asset.kind != kind
            or not isinstance(digest, str)
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
            or not isinstance(size_bytes, int)
            or size_bytes <= 0
        ):
            raise ReleaseConflict("release package artifact evidence is invalid")
        if expected is not None:
            prior = expected_by_id[asset_id]
            if (
                prior.label != label
                or prior.kind != kind
                or prior.relative_path != relative_path
                or prior.sha256 != digest
                or prior.size_bytes != size_bytes
            ):
                raise ReleaseConflict(
                    "release package artifact evidence changed before publication"
                )
        if data_dir is not None:
            assert artifact_stack is not None
            path = _release_artifact_path(
                data_dir,
                project_id=str(package.project_id),
                relative_path=relative_path,
            )
            try:
                pinned = artifact_stack.enter_context(open_pinned_regular_file(path))
                observed_digest = pinned.sha256()
                observed_size = pinned.metadata.st_size
            except (OSError, SecureFileError) as exc:
                raise ReleaseConflict(
                    "release package artifact bytes are missing or unsafe"
                ) from exc
            if observed_digest != digest or observed_size != size_bytes:
                raise ReleaseConflict("release package artifact bytes changed after completion")
            pinned_artifacts.append(
                _PinnedPackageArtifact(
                    label=label,
                    asset_id=asset_id,
                    kind=kind,
                    relative_path=relative_path,
                    path=path,
                    pinned=pinned,
                    sha256=digest,
                    size_bytes=size_bytes,
                )
            )
        hashes[label] = digest
    manifest_sha256 = hashes.get("manifest")
    zip_sha256 = hashes.get("zip")
    if ReleasePackageStatus(str(package.status)) is ReleasePackageStatus.SUCCEEDED and (
        manifest_sha256 is None
        or manifest_sha256 != package.manifest_sha256
        or (bool(package.include_zip) and zip_sha256 != package.zip_sha256)
        or (not bool(package.include_zip) and package.zip_sha256 is not None)
    ):
        raise ReleaseConflict("release package artifact evidence changed after completion")
    return _PackageArtifactHashes(
        manifest_sha256=manifest_sha256,
        zip_sha256=zip_sha256,
        pinned=(expected.pinned if expected is not None else tuple(pinned_artifacts)),
    )


def _release_artifact_path(
    data_dir: Path,
    *,
    project_id: str,
    relative_path: str,
) -> Path:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id) is None or "\\" in relative_path:
        raise ReleaseConflict("release package artifact path is invalid")
    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ReleaseConflict("release package artifact path is invalid")
    return data_dir / project_id / Path(*relative.parts)


def _checklist(value: object) -> ReleaseChecklist:
    return ReleaseChecklist.model_validate_json(
        json.dumps(value, sort_keys=True, separators=(",", ":"))
    )


def _editable_values(row: Any) -> dict[str, object]:
    return {
        "edit_plan_revision": int(row.edit_plan_revision),
        "title": str(row.title),
        "title_variants": list(row.title_variants_json),
        "description": str(row.description),
        "hashtags": list(row.hashtags_json),
        "cta": str(row.cta),
        "caption_mode": str(row.caption_mode),
        "cover_time_ms": int(row.cover_time_ms),
        "assignee_user_id": (
            str(row.assignee_user_id) if row.assignee_user_id is not None else None
        ),
        "planned_publish_at": _timestamp(row.planned_publish_at),
        "checklist": _checklist(row.checklist_json).model_dump(mode="json"),
    }


def _invalidate_active_release_packages(
    connection: Connection,
    *,
    release_item_id: str,
    acting_user_id: str,
    correlation_id: str | None,
    instant: datetime,
) -> None:
    invalidated = invalidate_active_release_packages(
        connection,
        instant=instant,
        release_item_ids=(release_item_id,),
    )
    for item in invalidated:
        _audit(
            connection,
            actor_user_id=acting_user_id,
            action="release_package.invalidated",
            release_item_id=release_item_id,
            project_id=item.project_id,
            before={
                "release_package_id": item.release_package_id,
                "status": item.previous_status.value,
            },
            after={
                "release_package_id": item.release_package_id,
                "status": ReleasePackageStatus.FAILED.value,
                "error_code": RELEASE_PACKAGE_STALE_CODE,
            },
            correlation_id=correlation_id,
            now=instant,
        )


def _audit(
    connection: Connection,
    *,
    actor_user_id: str,
    action: str,
    release_item_id: str,
    project_id: str,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    correlation_id: str | None,
    now: datetime,
) -> None:
    username = connection.scalar(
        select(WorkspaceUserRow.username).where(WorkspaceUserRow.id == actor_user_id)
    )
    connection.execute(
        insert(AuditEventRow).values(
            id=new_id(),
            actor_user_id=actor_user_id,
            actor_username=str(username) if username is not None else None,
            action=action,
            target_type="release_item",
            target_id=release_item_id,
            project_id=project_id,
            before_json=before,
            after_json=after,
            correlation_id=correlation_id,
            created_at=now,
        )
    )


def _audit_project_publication(
    connection: Connection,
    *,
    actor_user_id: str,
    project_id: str,
    release_item_id: str,
    management_version: int,
    correlation_id: str | None,
    now: datetime,
) -> None:
    username = connection.scalar(
        select(WorkspaceUserRow.username).where(WorkspaceUserRow.id == actor_user_id)
    )
    connection.execute(
        insert(AuditEventRow).values(
            id=new_id(),
            actor_user_id=actor_user_id,
            actor_username=str(username) if username is not None else None,
            action="project.published",
            target_type="project",
            target_id=project_id,
            project_id=project_id,
            before_json={
                "lifecycle": ProjectLifecycle.READY_TO_PUBLISH.value,
                "management_version": management_version,
            },
            after_json={
                "lifecycle": ProjectLifecycle.PUBLISHED.value,
                "release_item_id": release_item_id,
                "management_version": management_version + 1,
            },
            correlation_id=correlation_id,
            created_at=now,
        )
    )


def _timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _release_observed_utc(value: datetime, label: str) -> datetime:
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise ReleaseConflict(f"release {label} is outside the supported datetime range") from exc


__all__ = ["SqlAlchemyReleaseRepository"]
