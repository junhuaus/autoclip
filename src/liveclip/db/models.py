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
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    DeliveryStatus,
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
            "role IN ('owner', 'editor', 'reviewer')", name="project_member_role_allowed"
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
