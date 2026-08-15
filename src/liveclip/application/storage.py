from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from liveclip.application.identity import AdministrationDenied
from liveclip.application.workspace import WorkspaceUser


class StorageConflict(RuntimeError):
    """A storage operation conflicts with current authority, state, or scope."""


class ProjectStorageUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    project_name: str
    lifecycle: str
    actual_bytes: int = Field(ge=0)
    actual_file_count: int = Field(ge=0)
    tracked_asset_bytes: int = Field(ge=0)
    stale_render_asset_bytes: int = Field(ge=0)
    orphan_asset_bytes: int = Field(ge=0)
    pending_asset_bytes: int = Field(ge=0)
    untracked_bytes: int = Field(ge=0)
    untracked_file_count: int = Field(ge=0)
    missing_committed_asset_count: int = Field(ge=0)
    unsafe_entry_count: int = Field(ge=0)
    source_reference_bytes: int = Field(ge=0)


class StorageRetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    automatic_project_purge: Literal[False] = False
    source_media_deletion: Literal[False] = False
    safe_cleanup_committed_artifact_deletion: Literal[False] = False
    safe_cleanup_scope: Literal["terminal_attempt_worktrees_and_completed_purge_quarantine"] = (
        "terminal_attempt_worktrees_and_completed_purge_quarantine"
    )
    archive_retains_artifacts: Literal[True] = True
    destructive_project_purge_available: Literal[True] = True
    purge_requires_archived_project: Literal[True] = True
    purge_creates_database_backup: Literal[True] = True


class StorageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    scanned_at: datetime
    filesystem_capacity_bytes: int = Field(ge=0)
    filesystem_free_bytes: int = Field(ge=0)
    data_directory_bytes: int = Field(ge=0)
    database_bytes: int = Field(ge=0)
    migration_backup_bytes: int = Field(ge=0)
    database_backup_bytes: int = Field(ge=0)
    purge_quarantine_bytes: int = Field(ge=0)
    purge_quarantine_file_count: int = Field(ge=0)
    project_directory_bytes: int = Field(ge=0)
    unknown_project_directory_bytes: int = Field(ge=0)
    unknown_project_file_count: int = Field(ge=0)
    other_bytes: int = Field(ge=0)
    unsafe_entry_count: int = Field(ge=0)
    projects: tuple[ProjectStorageUsage, ...]
    policy: StorageRetentionPolicy = StorageRetentionPolicy()


class StorageCleanupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    inspected_attempts: int = Field(ge=0)
    cleaned_attempts: int = Field(ge=0)
    failed_attempts: int = Field(ge=0)
    inspected_purge_quarantines: int = Field(ge=0)
    cleaned_purge_quarantines: int = Field(ge=0)
    failed_purge_quarantines: int = Field(ge=0)
    report: StorageReport


class ProjectPurgePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    project_id: str
    project_name: str
    lifecycle: str
    management_version: int = Field(ge=1)
    generated_bytes: int = Field(ge=0)
    generated_file_count: int = Field(ge=0)
    unsafe_entry_count: int = Field(ge=0)
    source_filename: str | None
    source_media_preserved: Literal[True] = True
    active_run_count: int = Field(ge=0)
    active_task_count: int = Field(ge=0)
    blockers: tuple[str, ...]
    ready: bool
    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_phrase: str


class ProjectPurgeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    snapshot_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    project_name: str = Field(min_length=1, max_length=200)
    administrator_username: str = Field(min_length=1, max_length=80)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class ProjectPurgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    project_id: str
    project_name: str
    purged_at: datetime
    removed_generated_bytes: int = Field(ge=0)
    removed_generated_file_count: int = Field(ge=0)
    source_media_preserved: Literal[True] = True
    database_backup_filename: str
    database_backup_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    filesystem_cleanup_pending: bool


class StorageAdministrationRepository(Protocol):
    def report(self, *, actor: WorkspaceUser) -> StorageReport: ...

    def cleanup_terminal_attempts(
        self,
        *,
        actor: WorkspaceUser,
        correlation_id: str | None,
    ) -> StorageCleanupResult: ...

    def project_purge_plan(
        self,
        *,
        actor: WorkspaceUser,
        project_id: str,
    ) -> ProjectPurgePlan: ...

    def purge_project(
        self,
        *,
        actor: WorkspaceUser,
        project_id: str,
        command: ProjectPurgeCommand,
        correlation_id: str | None,
    ) -> ProjectPurgeResult: ...


class StorageAdministrationService:
    def __init__(self, repository: StorageAdministrationRepository) -> None:
        self._repository = repository

    def report(self, actor: WorkspaceUser) -> StorageReport:
        _require_administrator(actor)
        return self._repository.report(actor=actor)

    def cleanup_terminal_attempts(
        self,
        actor: WorkspaceUser,
        *,
        correlation_id: str | None = None,
    ) -> StorageCleanupResult:
        _require_administrator(actor)
        return self._repository.cleanup_terminal_attempts(
            actor=actor,
            correlation_id=correlation_id,
        )

    def project_purge_plan(
        self,
        actor: WorkspaceUser,
        project_id: str,
    ) -> ProjectPurgePlan:
        _require_administrator(actor)
        return self._repository.project_purge_plan(actor=actor, project_id=project_id)

    def purge_project(
        self,
        actor: WorkspaceUser,
        project_id: str,
        command: ProjectPurgeCommand,
        *,
        correlation_id: str | None = None,
    ) -> ProjectPurgeResult:
        _require_administrator(actor)
        return self._repository.purge_project(
            actor=actor,
            project_id=project_id,
            command=command,
            correlation_id=correlation_id,
        )


def _require_administrator(actor: WorkspaceUser) -> None:
    if actor.system_role != "administrator":
        raise AdministrationDenied("system administrator permission is required")


__all__ = [
    "ProjectPurgeCommand",
    "ProjectPurgePlan",
    "ProjectPurgeResult",
    "ProjectStorageUsage",
    "StorageAdministrationRepository",
    "StorageAdministrationService",
    "StorageCleanupResult",
    "StorageConflict",
    "StorageReport",
    "StorageRetentionPolicy",
]
