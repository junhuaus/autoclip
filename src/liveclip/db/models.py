from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from liveclip.db.base import Base, UTCDateTime, new_id, utc_now
from liveclip.domain.completion import (
    CompletionIntentStatus,
    CompletionOutcome,
    CompletionSelectionPolicy,
    CompletionTarget,
)
from liveclip.domain.project_lifecycle import ProjectLifecycle, ProjectPriority
from liveclip.domain.releases import (
    ReleaseApprovalStatus,
    ReleaseCaptionMode,
    ReleaseItemStatus,
    ReleasePackageStatus,
    ReleasePlatform,
)
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    DeliveryStatus,
    EditPackageStatus,
    FailureClass,
    PipelineRunStatus,
    PipelineStage,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    StageRunStatus,
    TaskKind,
    TaskStatus,
)


def _enum_sql(enum_type: type[StrEnum]) -> str:
    return ", ".join(f"'{item.value}'" for item in enum_type)


class WorkspaceUserRow(Base):
    __tablename__ = "workspace_users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    system_role: Mapped[str] = mapped_column(String(24), nullable=False, default="member")
    password_hash: Mapped[str | None] = mapped_column(Text)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("current_generation >= 0", name="current_generation_nonnegative"),
        CheckConstraint("revision_epoch >= 0", name="revision_epoch_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        default="00000000000000000000000000000001",
        server_default="00000000000000000000000000000001",
    )
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    lifecycle: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ProjectLifecycle.PROCESSING.value, index=True
    )
    lifecycle_before_archive: Mapped[str | None] = mapped_column(String(32))
    management_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assignee_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    priority: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ProjectPriority.NORMAL.value
    )
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_request_path: Mapped[str] = mapped_column(Text, nullable=False)
    current_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_pipeline_run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    revision_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class ProjectMemberRow(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="project_member_identity"),
        CheckConstraint(
            "role IN ('owner', 'editor', 'reviewer', 'viewer')",
            name="project_member_role_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class SavedProjectViewRow(Base):
    __tablename__ = "saved_project_views"
    __table_args__ = (
        UniqueConstraint("user_id", "name_key", name="saved_project_view_user_name"),
        CheckConstraint("version > 0", name="saved_project_view_version_positive"),
        Index("ix_saved_project_views_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(160), nullable=False)
    criteria_schema_version: Mapped[str] = mapped_column(String(8), nullable=False, default="1")
    criteria_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class AuthSessionRow(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (CheckConstraint("user_auth_version >= 0", name="auth_version_nonnegative"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AuthLoginAttemptRow(Base):
    __tablename__ = "auth_login_attempts"
    __table_args__ = (CheckConstraint("failed_count >= 0", name="login_failed_count_nonnegative"),)

    identity_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="SET NULL"), index=True
    )
    actor_username: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(80))
    project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class SourceMediaRow(Base):
    __tablename__ = "source_media"
    __table_args__ = (
        UniqueConstraint("project_id", name="one_source_per_project"),
        CheckConstraint("size_bytes > 0", name="source_size_positive"),
        CheckConstraint("duration_ms > 0", name="source_duration_positive"),
        CheckConstraint("width > 0 AND height > 0", name="source_dimensions_positive"),
        CheckConstraint(
            """
            (
                video_stream_index IS NULL
                AND audio_stream_index IS NULL
                AND video_rotation_degrees IS NULL
            ) OR (
                video_stream_index IS NOT NULL
                AND audio_stream_index IS NOT NULL
                AND video_rotation_degrees IS NOT NULL
            )
            """,
            name="source_stream_selection_complete",
        ),
        CheckConstraint(
            """
            video_stream_index IS NULL OR (
                video_stream_index >= 0 AND audio_stream_index >= 0
            )
            """,
            name="source_stream_indexes_nonnegative",
        ),
        CheckConstraint(
            "video_stream_index IS NULL OR video_stream_index != audio_stream_index",
            name="source_stream_indexes_distinct",
        ),
        CheckConstraint(
            """
            video_rotation_degrees IS NULL
            OR video_rotation_degrees IN (0, 90, 180, 270)
            """,
            name="source_rotation_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resolved_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    device: Mapped[int | None] = mapped_column(BigInteger)
    inode: Mapped[int | None] = mapped_column(BigInteger)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    video_stream_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_stream_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_rotation_degrees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_codec: Mapped[str] = mapped_column(String(80), nullable=False)
    audio_codec: Mapped[str] = mapped_column(String(80), nullable=False)
    frame_rate: Mapped[str] = mapped_column(String(40), nullable=False)
    probe_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class PipelineRunRow(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        UniqueConstraint("project_id", "generation", name="project_generation"),
        CheckConstraint(
            f"status IN ({_enum_sql(PipelineRunStatus)})", name="pipeline_status_allowed"
        ),
        CheckConstraint("generation > 0", name="pipeline_generation_positive"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="pipeline_progress_range"),
        CheckConstraint("manual_retry_count >= 0", name="pipeline_manual_retry_nonnegative"),
        CheckConstraint(
            f"failure_class IS NULL OR failure_class IN ({_enum_sql(FailureClass)})",
            name="pipeline_failure_class_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PipelineRunStatus.QUEUED.value, index=True
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_class: Mapped[str | None] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class StageRunRow(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "stage", name="run_stage"),
        CheckConstraint(f"stage IN ({_enum_sql(PipelineStage)})", name="pipeline_stage_allowed"),
        CheckConstraint(f"status IN ({_enum_sql(StageRunStatus)})", name="stage_status_allowed"),
        CheckConstraint("ordinal >= 0 AND ordinal < 6", name="stage_ordinal_range"),
        CheckConstraint("progress >= 0 AND progress <= 100", name="stage_progress_range"),
        CheckConstraint("retry_count >= 0", name="stage_retry_nonnegative"),
        CheckConstraint("max_retries >= 0", name="stage_max_retries_nonnegative"),
        CheckConstraint(
            f"failure_class IS NULL OR failure_class IN ({_enum_sql(FailureClass)})",
            name="stage_failure_class_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    pipeline_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StageRunStatus.QUEUED.value, index=True
    )
    input_fingerprint: Mapped[str | None] = mapped_column(String(64))
    output_fingerprint: Mapped[str | None] = mapped_column(String(64))
    checkpoint_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    skip_reason: Mapped[str | None] = mapped_column(String(200))
    failure_class: Mapped[str | None] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("operation_key", name="task_operation_key"),
        CheckConstraint(f"kind IN ({_enum_sql(TaskKind)})", name="task_kind_allowed"),
        CheckConstraint(
            f"resource_class IN ({_enum_sql(ResourceClass)})", name="task_resource_allowed"
        ),
        CheckConstraint(f"status IN ({_enum_sql(TaskStatus)})", name="task_status_allowed"),
        CheckConstraint("priority >= 0", name="task_priority_nonnegative"),
        CheckConstraint("attempt_count >= 0", name="task_attempt_nonnegative"),
        CheckConstraint("retry_count >= 0", name="task_retry_nonnegative"),
        CheckConstraint("manual_retry_count >= 0", name="task_manual_retry_nonnegative"),
        CheckConstraint("max_retries >= 0", name="task_max_retry_nonnegative"),
        CheckConstraint("retry_count <= max_retries", name="task_retry_within_limit"),
        CheckConstraint(
            "depends_on_task_id IS NULL OR depends_on_task_id <> id", name="no_self_dependency"
        ),
        CheckConstraint(
            "kind <> 'stage' OR (stage_run_id IS NOT NULL AND pipeline_run_id IS NOT NULL "
            "AND target_id = stage_run_id)",
            name="stage_task_target_matches",
        ),
        CheckConstraint(
            "kind <> 'completion' OR (pipeline_run_id IS NOT NULL AND stage_run_id IS NULL "
            "AND resource_class = 'cheap')",
            name="completion_task_shape",
        ),
        CheckConstraint(
            "status <> 'waiting' OR kind = 'completion'",
            name="waiting_task_is_completion",
        ),
        CheckConstraint(
            f"failure_class IS NULL OR failure_class IN ({_enum_sql(FailureClass)})",
            name="task_failure_class_allowed",
        ),
        CheckConstraint(
            "(status = 'running' AND worker_id IS NOT NULL AND lease_token IS NOT NULL "
            "AND heartbeat_at IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND lease_expires_at > heartbeat_at) OR "
            "(status <> 'running' AND worker_id IS NULL AND lease_token IS NULL "
            "AND heartbeat_at IS NULL AND lease_expires_at IS NULL)",
            name="task_lease_shape",
        ),
        Index("ix_tasks_claim", "status", "not_before", "priority", "created_at", "id"),
        Index("ix_tasks_expired", "status", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    operation_key: Mapped[str] = mapped_column(String(160), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_class: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ResourceClass.HEAVY.value
    )
    pipeline_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    stage_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), index=True
    )
    depends_on_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TaskStatus.QUEUED.value, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    not_before: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    expected_generation: Mapped[int | None] = mapped_column(Integer)
    expected_revision: Mapped[int | None] = mapped_column(Integer)
    expected_revision_epoch: Mapped[int | None] = mapped_column(BigInteger)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(100), index=True)
    lease_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_class: Mapped[str | None] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class TaskAttemptRow(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="task_attempt_number"),
        UniqueConstraint("lease_token", name="attempt_lease_token"),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint(
            f"outcome IN ({_enum_sql(AttemptOutcome)})", name="attempt_outcome_allowed"
        ),
        CheckConstraint(
            f"failure_class IS NULL OR failure_class IN ({_enum_sql(FailureClass)})",
            name="attempt_failure_class_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AttemptOutcome.RUNNING.value
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_class: Mapped[str | None] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    diagnostic_relative_path: Mapped[str | None] = mapped_column(String(500))
    temp_identity: Mapped[str | None] = mapped_column(String(160))


class CompletionIntentRow(Base):
    __tablename__ = "completion_intents"
    __table_args__ = (
        UniqueConstraint(
            "requester_user_id",
            "idempotency_key_sha256",
            name="completion_request_identity",
        ),
        CheckConstraint("generation > 0", name="completion_generation_positive"),
        CheckConstraint("version > 0", name="completion_version_positive"),
        CheckConstraint(
            f"target IN ({_enum_sql(CompletionTarget)})",
            name="completion_target_allowed",
        ),
        CheckConstraint(
            f"selection_policy IN ({_enum_sql(CompletionSelectionPolicy)})",
            name="completion_selection_policy_allowed",
        ),
        CheckConstraint(
            f"status IN ({_enum_sql(CompletionIntentStatus)})",
            name="completion_status_allowed",
        ),
        CheckConstraint(
            f"outcome_code IS NULL OR outcome_code IN ({_enum_sql(CompletionOutcome)})",
            name="completion_outcome_allowed",
        ),
        CheckConstraint("options_schema_version = '1'", name="completion_options_schema_v1"),
        CheckConstraint(
            "length(canonical_request_sha256) = 64 AND length(idempotency_key_sha256) = 64",
            name="completion_request_hash_shape",
        ),
        CheckConstraint(
            "target <> 'process_only' OR selection_policy = 'default'",
            name="completion_processing_selection_shape",
        ),
        CheckConstraint(
            "status <> 'waiting_selection' OR "
            "(target = 'delivery' AND selection_policy = 'manual' AND selection_submitted = 0)",
            name="completion_manual_wait_shape",
        ),
        CheckConstraint(
            "delivery_id IS NULL OR target = 'delivery'",
            name="completion_delivery_target_shape",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND outcome_code IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status = 'cancelled' AND outcome_code = 'cancelled' "
            "AND completed_at IS NOT NULL) "
            "OR (status NOT IN ('succeeded', 'cancelled') AND outcome_code IS NULL)",
            name="completion_terminal_outcome_shape",
        ),
        Index("ix_completion_project_state", "project_id", "status", "created_at"),
        Index("ix_completion_run_state", "pipeline_run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    requester_user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="RESTRICT"), nullable=False
    )
    target: Mapped[str] = mapped_column(String(20), nullable=False)
    selection_policy: Mapped[str] = mapped_column(String(20), nullable=False)
    options_schema_version: Mapped[str] = mapped_column(String(8), nullable=False, default="1")
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    canonical_request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=CompletionIntentStatus.QUEUED.value
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    selection_submitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    selection_checkpoint_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    render_action_keys_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    delivery_action_key: Mapped[str | None] = mapped_column(String(160))
    delivery_id: Mapped[str | None] = mapped_column(String(32))
    outcome_code: Mapped[str | None] = mapped_column(String(40))
    blocking_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class AssetRow(Base):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("project_id", "relative_path", name="project_asset_path"),
        CheckConstraint(f"status IN ({_enum_sql(AssetStatus)})", name="asset_status_allowed"),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="asset_size_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_clip_id: Mapped[str | None] = mapped_column(
        ForeignKey("candidate_clips.id", ondelete="SET NULL"), index=True
    )
    producer_attempt_id: Mapped[str | None] = mapped_column(
        ForeignKey("task_attempts.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AssetStatus.PENDING.value, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(String(64))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    validation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    generation: Mapped[int | None] = mapped_column(Integer)
    edit_plan_revision: Mapped[int | None] = mapped_column(Integer)
    revision_epoch: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SemanticUnitInvocationRow(Base):
    """Append-only invocation ownership; expected outcome hash is independent of Asset."""

    __tablename__ = "semantic_unit_invocations"
    __table_args__ = (
        UniqueConstraint(
            "stage_run_id",
            "semantic_stage",
            "subject_id",
            "request_key",
            "invocation_number",
            name="semantic_unit_invocation_number",
        ),
        CheckConstraint("generation > 0", name="semantic_unit_generation_positive"),
        CheckConstraint("invocation_number BETWEEN 1 AND 3", name="semantic_unit_invocation_bound"),
        CheckConstraint(
            "execution_contract = 'semantic-bounded-units-v1'",
            name="semantic_unit_contract",
        ),
        CheckConstraint(
            "disposition IS NULL OR disposition IN "
            "('succeeded','transient','exhausted','cancelled')",
            name="semantic_unit_disposition",
        ),
        CheckConstraint(
            "disposition != 'transient' OR repair_spent = 0",
            name="semantic_unit_repair_exhaustion",
        ),
        CheckConstraint(
            "outcome_size_bytes IS NULL OR outcome_size_bytes > 0",
            name="semantic_unit_outcome_size",
        ),
        Index(
            "ix_semantic_unit_history",
            "pipeline_run_id",
            "semantic_stage",
            "subject_id",
            "request_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False
    )
    stage_run_id: Mapped[str] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    producer_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("task_attempts.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_stage: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_key: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_contract: Mapped[str] = mapped_column(String(40), nullable=False)
    invocation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    disposition: Mapped[str | None] = mapped_column(String(16))
    repair_spent: Mapped[bool | None] = mapped_column(Boolean)
    outcome_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL")
    )
    outcome_sha256: Mapped[str | None] = mapped_column(String(64))
    outcome_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    outcome_relative_path: Mapped[str | None] = mapped_column(String(500))


class AudioChunkRow(Base):
    __tablename__ = "audio_chunks"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "chunk_index", name="run_chunk_index"),
        UniqueConstraint("pipeline_run_id", "cache_key", name="run_chunk_cache_key"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint("source_start_ms >= 0", name="chunk_start_nonnegative"),
        CheckConstraint("source_end_ms > source_start_ms", name="chunk_interval_valid"),
        CheckConstraint("overlap_before_ms >= 0", name="chunk_overlap_before_nonnegative"),
        CheckConstraint("overlap_after_ms >= 0", name="chunk_overlap_after_nonnegative"),
        CheckConstraint("size_bytes > 0", name="chunk_size_positive"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    pipeline_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage_run_id: Mapped[str] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    overlap_before_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    overlap_after_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class TranscriptRow(Base):
    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("pipeline_run_id", name="one_transcript_per_run"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    pipeline_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="zh")
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    word_timing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class TranscriptSegmentRow(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint("transcript_id", "segment_index", name="transcript_segment_index"),
        CheckConstraint("segment_index >= 0", name="segment_index_nonnegative"),
        CheckConstraint("source_start_ms >= 0", name="segment_start_nonnegative"),
        CheckConstraint("source_end_ms > source_start_ms", name="segment_interval_valid"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    transcript_id: Mapped[str] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class TranscriptWordRow(Base):
    __tablename__ = "transcript_words"
    __table_args__ = (
        UniqueConstraint("segment_id", "word_index", name="segment_word_index"),
        CheckConstraint("word_index >= 0", name="word_index_nonnegative"),
        CheckConstraint("source_start_ms >= 0", name="word_start_nonnegative"),
        CheckConstraint("source_end_ms > source_start_ms", name="word_interval_valid"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    segment_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    word_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(String(200), nullable=False)


class CandidateClipRow(Base):
    __tablename__ = "candidate_clips"
    __table_args__ = (
        UniqueConstraint("pipeline_run_id", "candidate_key", name="run_candidate_key"),
        CheckConstraint("source_start_ms >= 0", name="candidate_start_nonnegative"),
        CheckConstraint("source_end_ms > source_start_ms", name="candidate_interval_valid"),
        CheckConstraint("allowed_start_ms >= 0", name="candidate_allowed_start_nonnegative"),
        CheckConstraint(
            "allowed_end_ms > allowed_start_ms", name="candidate_allowed_interval_valid"
        ),
        CheckConstraint(
            "source_start_ms >= allowed_start_ms AND source_end_ms <= allowed_end_ms",
            name="candidate_inside_allowed_window",
        ),
        CheckConstraint("rule_score >= 0 AND rule_score <= 100", name="candidate_score_range"),
        CheckConstraint("current_revision >= 0", name="candidate_revision_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pipeline_run_id: Mapped[str] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allowed_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allowed_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transcript_text: Mapped[str] = mapped_column(Text, nullable=False)
    context_before: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_after: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rule_score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    segment_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    dedup_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rank: Mapped[int | None] = mapped_column(Integer)
    selected_for_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class EditPlanRevisionRow(Base):
    __tablename__ = "edit_plan_revisions"
    __table_args__ = (
        UniqueConstraint("candidate_clip_id", "revision", name="clip_edit_revision"),
        CheckConstraint("revision > 0", name="edit_revision_positive"),
        CheckConstraint(
            "(revision = 1 AND parent_revision IS NULL) OR "
            "(revision > 1 AND parent_revision = revision - 1)",
            name="edit_parent_preceding",
        ),
        CheckConstraint("source_start_ms >= 0", name="edit_start_nonnegative"),
        CheckConstraint("source_end_ms > source_start_ms", name="edit_interval_valid"),
        CheckConstraint("score >= 0 AND score <= 100", name="edit_score_range"),
        CheckConstraint("origin IN ('ai', 'deterministic', 'human')", name="edit_origin_allowed"),
        CheckConstraint(
            "layout IN ('vertical_blur_background', 'center_crop')", name="edit_layout_allowed"
        ),
        CheckConstraint("caption_template = 'clean_zh_v1'", name="edit_caption_allowed"),
        CheckConstraint("effect IN ('none', 'fade_in_out')", name="edit_effect_allowed"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    candidate_clip_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_clips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_revision: Mapped[int | None] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(String(20), nullable=False)
    source_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    hook: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str] = mapped_column(String(1_000), nullable=False)
    layout: Mapped[str] = mapped_column(String(40), nullable=False)
    caption_template: Mapped[str] = mapped_column(String(40), nullable=False)
    effect: Mapped[str] = mapped_column(String(40), nullable=False)
    risk_flags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class CaptionCueRow(Base):
    __tablename__ = "caption_cues"
    __table_args__ = (
        UniqueConstraint("edit_plan_revision_id", "cue_index", name="revision_cue_index"),
        CheckConstraint("cue_index >= 0", name="cue_index_nonnegative"),
        CheckConstraint("start_ms >= 0", name="cue_start_nonnegative"),
        CheckConstraint("end_ms > start_ms", name="cue_interval_valid"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    edit_plan_revision_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plan_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cue_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    text: Mapped[str] = mapped_column(String(500), nullable=False)


class ReviewDecisionRow(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{ReviewStatus.APPROVED.value}', '{ReviewStatus.REJECTED.value}')",
            name="review_decision_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    candidate_clip_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_clips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    edit_plan_revision_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plan_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(1_000))
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ClipCommentThreadRow(Base):
    __tablename__ = "clip_comment_threads"
    __table_args__ = (
        CheckConstraint("source_time_ms >= 0", name="comment_thread_source_time_nonnegative"),
        CheckConstraint("clip_time_ms >= 0", name="comment_thread_clip_time_nonnegative"),
        CheckConstraint("version > 0", name="comment_thread_version_positive"),
        CheckConstraint(
            "status IN ('open', 'resolved')",
            name="comment_thread_status_allowed",
        ),
        CheckConstraint(
            "(status = 'open' AND resolved_by_user_id IS NULL "
            "AND resolved_by_username IS NULL AND resolved_by_display_name IS NULL "
            "AND resolved_at IS NULL) OR (status = 'resolved' "
            "AND resolved_by_username IS NOT NULL AND resolved_by_display_name IS NOT NULL "
            "AND resolved_at IS NOT NULL)",
            name="comment_thread_resolution_complete",
        ),
        Index(
            "ix_clip_comment_threads_revision_updated",
            "edit_plan_revision_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    edit_plan_revision_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plan_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    clip_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="SET NULL"), index=True
    )
    created_by_username: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by_display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    resolved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="SET NULL"), index=True
    )
    resolved_by_username: Mapped[str | None] = mapped_column(String(80))
    resolved_by_display_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ClipCommentRow(Base):
    __tablename__ = "clip_comments"
    __table_args__ = (
        UniqueConstraint("thread_id", "sequence", name="clip_comment_thread_sequence"),
        CheckConstraint("sequence > 0", name="clip_comment_sequence_positive"),
        CheckConstraint(
            "length(trim(body)) > 0 AND length(body) <= 2000",
            name="clip_comment_body_length",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("clip_comment_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    author_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="SET NULL"), index=True
    )
    author_username: Mapped[str] = mapped_column(String(80), nullable=False)
    author_display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ClipCommentMentionRow(Base):
    __tablename__ = "clip_comment_mentions"
    __table_args__ = (
        UniqueConstraint("comment_id", "user_id", name="clip_comment_mentioned_user"),
        UniqueConstraint("comment_id", "mention_index", name="clip_comment_mention_index"),
        CheckConstraint("mention_index >= 0", name="clip_comment_mention_index_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    comment_id: Mapped[str] = mapped_column(
        ForeignKey("clip_comments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="SET NULL"), index=True
    )
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    mention_index: Mapped[int] = mapped_column(Integer, nullable=False)


class RenderJobRow(Base):
    __tablename__ = "render_jobs"
    __table_args__ = (
        UniqueConstraint(
            "candidate_clip_id",
            "edit_plan_revision_id",
            "kind",
            "spec_fingerprint",
            name="revision_render_spec",
        ),
        CheckConstraint("kind IN ('proxy', 'final')", name="render_kind_allowed"),
        CheckConstraint(f"status IN ({_enum_sql(RenderStatus)})", name="render_status_allowed"),
        CheckConstraint("width > 0 AND height > 0", name="render_dimensions_positive"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    candidate_clip_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_clips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    edit_plan_revision_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plan_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RenderStatus.QUEUED.value, index=True
    )
    edit_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    spec_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    subtitle_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    quality_report_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    contact_sheet_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class DeliveryRow(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="project_delivery_version"),
        CheckConstraint("version > 0", name="delivery_version_positive"),
        CheckConstraint("expected_generation > 0", name="delivery_generation_positive"),
        CheckConstraint(f"status IN ({_enum_sql(DeliveryStatus)})", name="delivery_status_allowed"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DeliveryStatus.QUEUED.value, index=True
    )
    expected_revision_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    directory_relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    manifest_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    zip_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    include_zip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expected_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DeliveryProgressRow(Base):
    """Last producer event for one immutable Delivery Task attempt."""

    __tablename__ = "delivery_progress"
    __table_args__ = (
        CheckConstraint("schema_version = '1'", name="delivery_progress_schema_v1"),
        CheckConstraint("attempt_number > 0", name="delivery_progress_attempt_positive"),
        CheckConstraint("expected_generation > 0", name="delivery_progress_generation_positive"),
        CheckConstraint("expected_revision_epoch >= 0", name="delivery_progress_epoch_nonnegative"),
        CheckConstraint(
            "length(package_fingerprint) = 64", name="delivery_progress_fingerprint_shape"
        ),
        CheckConstraint("completed >= 0", name="delivery_progress_completed_nonnegative"),
        CheckConstraint(
            "total IS NULL OR total >= completed", name="delivery_progress_total_bound"
        ),
        CheckConstraint(
            "(phase = 'copying_hashing' AND unit = 'bytes') OR "
            "(phase = 'writing_metadata' AND unit = 'files') OR "
            "(phase = 'writing_zip' AND unit = 'bytes') OR "
            "(phase = 'verifying_package' AND unit = 'members') OR "
            "(phase = 'committing_assets' AND unit = 'assets')",
            name="delivery_progress_phase_unit",
        ),
    )

    delivery_id: Mapped[str] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), primary_key=True
    )
    task_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("task_attempts.id", ondelete="CASCADE"), primary_key=True, unique=True
    )
    schema_version: Mapped[str] = mapped_column(String(8), nullable=False, default="1")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_revision_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    package_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    completed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    business_advanced_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now
    )


class DeliveryClipRow(Base):
    __tablename__ = "delivery_clips"
    __table_args__ = (
        UniqueConstraint("delivery_id", "ordinal", name="delivery_clip_ordinal"),
        UniqueConstraint("delivery_id", "candidate_clip_id", name="delivery_candidate"),
        CheckConstraint("ordinal > 0", name="delivery_clip_ordinal_positive"),
        CheckConstraint("source_start_ms >= 0", name="delivery_clip_start_nonnegative"),
        CheckConstraint("source_end_ms > source_start_ms", name="delivery_clip_interval_valid"),
        CheckConstraint("score >= 0 AND score <= 100", name="delivery_clip_score_range"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    delivery_id: Mapped[str] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_clip_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_clips.id", ondelete="RESTRICT"), nullable=False
    )
    edit_plan_revision_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plan_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    render_job_id: Mapped[str] = mapped_column(
        ForeignKey("render_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    edit_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    video_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    source_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class EditPackageRow(Base):
    __tablename__ = "edit_packages"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="project_edit_package_version"),
        CheckConstraint("version > 0", name="edit_package_version_positive"),
        CheckConstraint("expected_generation > 0", name="edit_package_generation_positive"),
        CheckConstraint(
            f"status IN ({_enum_sql(EditPackageStatus)})",
            name="edit_package_status_allowed",
        ),
        CheckConstraint("preset = 'clean_editing'", name="edit_package_preset_allowed"),
        CheckConstraint(
            "content IN ('full', 'metadata_only')",
            name="edit_package_content_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EditPackageStatus.QUEUED.value, index=True
    )
    expected_revision_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    directory_relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    preset: Mapped[str] = mapped_column(String(32), nullable=False, default="clean_editing")
    content: Mapped[str] = mapped_column(String(24), nullable=False, default="full")
    manifest_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    zip_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    include_zip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expected_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class EditPackageClipRow(Base):
    __tablename__ = "edit_package_clips"
    __table_args__ = (
        UniqueConstraint("edit_package_id", "ordinal", name="edit_package_clip_ordinal"),
        UniqueConstraint(
            "edit_package_id",
            "candidate_clip_id",
            name="edit_package_candidate",
        ),
        CheckConstraint("ordinal > 0", name="edit_package_clip_ordinal_positive"),
        CheckConstraint("edit_plan_revision > 0", name="edit_package_clip_revision_positive"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    edit_package_id: Mapped[str] = mapped_column(
        ForeignKey("edit_packages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_clip_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_clips.id", ondelete="RESTRICT"), nullable=False
    )
    edit_plan_revision_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plan_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    render_job_id: Mapped[str] = mapped_column(
        ForeignKey("render_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    edit_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    video_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    contact_sheet_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    video_filename: Mapped[str | None] = mapped_column(String(500))
    subtitle_filename: Mapped[str | None] = mapped_column(String(500))
    thumbnail_filename: Mapped[str | None] = mapped_column(String(500))
    video_sha256: Mapped[str | None] = mapped_column(String(64))
    subtitle_sha256: Mapped[str | None] = mapped_column(String(64))
    thumbnail_sha256: Mapped[str | None] = mapped_column(String(64))


class ReleaseItemRow(Base):
    __tablename__ = "release_items"
    __table_args__ = (
        UniqueConstraint(
            "candidate_clip_id",
            "platform",
            "account_label",
            name="release_item_clip_platform_account",
        ),
        CheckConstraint(
            f"platform IN ({_enum_sql(ReleasePlatform)})",
            name="release_item_platform_allowed",
        ),
        CheckConstraint(
            f"caption_mode IN ({_enum_sql(ReleaseCaptionMode)})",
            name="release_item_caption_mode_allowed",
        ),
        CheckConstraint(
            f"approval_status IN ({_enum_sql(ReleaseApprovalStatus)})",
            name="release_item_approval_allowed",
        ),
        CheckConstraint(
            f"status IN ({_enum_sql(ReleaseItemStatus)})",
            name="release_item_status_allowed",
        ),
        CheckConstraint("edit_plan_revision > 0", name="release_item_revision_positive"),
        CheckConstraint("management_version > 0", name="release_item_version_positive"),
        CheckConstraint("cover_time_ms >= 0", name="release_item_cover_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_clip_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_clips.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    edit_plan_revision_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plan_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    edit_plan_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    preset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    account_label: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    title_variants_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hashtags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    cta: Mapped[str] = mapped_column(String(200), nullable=False)
    caption_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    cover_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    assignee_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="SET NULL"), index=True
    )
    planned_publish_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    approval_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ReleaseApprovalStatus.DRAFT.value, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ReleaseItemStatus.DRAFT.value, index=True
    )
    checklist_json: Mapped[dict[str, bool]] = mapped_column(JSON, nullable=False)
    preflight_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    management_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    external_url: Mapped[str | None] = mapped_column(String(1_000))
    external_id: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    result_notes: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utc_now, onupdate=utc_now
    )


class ReleaseMetricSnapshotRow(Base):
    __tablename__ = "release_metric_snapshots"
    __table_args__ = (
        CheckConstraint("views >= 0", name="release_metric_views_nonnegative"),
        CheckConstraint("likes >= 0", name="release_metric_likes_nonnegative"),
        CheckConstraint("comments >= 0", name="release_metric_comments_nonnegative"),
        CheckConstraint("shares >= 0", name="release_metric_shares_nonnegative"),
        CheckConstraint("saves >= 0", name="release_metric_saves_nonnegative"),
        CheckConstraint(
            "followers_gained >= 0",
            name="release_metric_followers_nonnegative",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    release_item_id: Mapped[str] = mapped_column(
        ForeignKey("release_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recorded_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    likes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    saves: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    followers_gained: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(1_000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class ReleasePackageRow(Base):
    __tablename__ = "release_packages"
    __table_args__ = (
        UniqueConstraint("release_item_id", "version", name="release_item_package_version"),
        CheckConstraint("version > 0", name="release_package_version_positive"),
        CheckConstraint(
            "expected_generation > 0",
            name="release_package_generation_positive",
        ),
        CheckConstraint(
            "expected_release_item_version > 0",
            name="release_package_item_version_positive",
        ),
        CheckConstraint(
            f"status IN ({_enum_sql(ReleasePackageStatus)})",
            name="release_package_status_allowed",
        ),
        CheckConstraint(
            f"caption_mode IN ({_enum_sql(ReleaseCaptionMode)})",
            name="release_package_caption_mode_allowed",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    release_item_id: Mapped[str] = mapped_column(
        ForeignKey("release_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("workspace_users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), unique=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReleasePackageStatus.QUEUED.value, index=True
    )
    expected_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_revision_epoch: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_release_item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    preset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    caption_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    directory_relative_path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_render_job_id: Mapped[str] = mapped_column(
        ForeignKey("render_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    source_video_asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False
    )
    manifest_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    zip_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), unique=True
    )
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    zip_sha256: Mapped[str | None] = mapped_column(String(64))
    include_zip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    safe_error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ReleasePublicationEvidenceRow(Base):
    __tablename__ = "release_publication_evidence"
    __table_args__ = (
        CheckConstraint(
            "release_item_version > 0",
            name="release_publication_item_version_positive",
        ),
        CheckConstraint(
            "package_version > 0",
            name="release_publication_package_version_positive",
        ),
        CheckConstraint(
            "artifact_kind IN ('zip', 'manifest')",
            name="release_publication_artifact_kind_allowed",
        ),
        CheckConstraint(
            "length(video_sha256) = 64 AND length(artifact_sha256) = 64 "
            "AND length(manifest_sha256) = 64 "
            "AND (zip_sha256 IS NULL OR length(zip_sha256) = 64)",
            name="release_publication_hash_lengths",
        ),
    )

    release_item_id: Mapped[str] = mapped_column(
        ForeignKey("release_items.id", ondelete="CASCADE"), primary_key=True
    )
    release_package_id: Mapped[str] = mapped_column(
        ForeignKey("release_packages.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    release_item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    package_version: Mapped[int] = mapped_column(Integer, nullable=False)
    preset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    caption_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    video_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    zip_sha256: Mapped[str | None] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ApiUsageRow(Base):
    __tablename__ = "api_usage"
    __table_args__ = (
        CheckConstraint("request_count >= 0", name="usage_request_nonnegative"),
        CheckConstraint("retry_count >= 0", name="usage_retry_nonnegative"),
        CheckConstraint("latency_ms >= 0", name="usage_latency_nonnegative"),
        CheckConstraint("audio_seconds >= 0", name="usage_audio_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pipeline_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="SET NULL"), index=True
    )
    stage_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("stage_runs.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(160))
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    audio_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    usage_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    estimated_cost: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    called_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "caller_scope", "operation_scope", "key_hash", name="idempotency_scope_key"
        ),
        CheckConstraint("status IN ('pending', 'completed')", name="idempotency_status_allowed"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    caller_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    response_status_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
