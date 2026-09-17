from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from liveclip.application.authorization import ProjectAction
from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfig,
    PipelineService,
    load_persisted_pipeline_config,
)
from liveclip.application.stage_execution import stage_output_fingerprint
from liveclip.db.base import Base, new_id
from liveclip.db.current_project_authority import (
    CurrentProjectAccessDenied,
    CurrentProjectRunChanged,
    require_current_project_action,
)
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    ApiUsageRow,
    AssetRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    SourceMediaRow,
    StageRunRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.db.pipeline_repository import (
    DeterministicRetryRejected,
    PipelineConflict,
    SqlAlchemyPipelineRepository,
)
from liveclip.db.task_queue import SQLiteTaskQueue, TaskLease
from liveclip.domain.state_transitions import (
    AssetStatus,
    FailureClass,
    PipelineRunStatus,
    PipelineStage,
    ProjectStatus,
    ResourceClass,
    StageRunStatus,
    TaskKind,
    TaskStatus,
)

NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)

V5_SEMANTIC_GLOBAL_FIELDS = (
    "semantic_profile",
    "semantic_discovery_skill_version",
    "semantic_discovery_skill_sha256",
    "semantic_global_review_skill_version",
    "semantic_global_review_skill_sha256",
    "semantic_full_context_budget_ratio",
    "semantic_model_context_tokens",
    "semantic_tokenizer_name",
    "semantic_output_reserve_tokens",
    "semantic_safety_margin_tokens",
    "semantic_fallback_target_ms",
    "semantic_fallback_minimum_ms",
    "semantic_fallback_maximum_ms",
    "semantic_fallback_context_guard_ms",
    "semantic_global_context_ms",
    "semantic_no_render",
    "semantic_prompt_debug",
)
V6_BOUNDARY_REVIEW_FIELDS = (
    "semantic_boundary_review_skill_version",
    "semantic_boundary_review_skill_sha256",
)
V7_CLIP_PROFILE_FIELDS = (
    "clip_profile",
    "semantic_link_review_skill_version",
    "semantic_link_review_skill_sha256",
    "semantic_topic_chain_skill_version",
    "semantic_topic_chain_skill_sha256",
    "semantic_result_schema_version",
)


@pytest.fixture
def pipeline_context(tmp_path: Path) -> Iterator[tuple[Engine, PipelineService]]:
    engine = create_sqlite_engine(tmp_path / "pipeline.sqlite3")
    Base.metadata.create_all(engine)
    service = PipelineService(SqlAlchemyPipelineRepository(engine))
    try:
        yield engine, service
    finally:
        engine.dispose(close=True)


def _config() -> PipelineRunConfig:
    return PipelineRunConfig(
        provider="mock",
        top_n=3,
        minimum_clip_ms=8_000,
        maximum_clip_ms=12_000,
        chunk_duration_ms=12_000,
        chunk_overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=540,
        preview_height=960,
        video_encoder="libx264",
    )


def _create(service: PipelineService, suffix: str = "a") -> tuple[str, str]:
    created = service.create_project_and_run(
        source_path=Path(f"/allowed/source-{suffix}.mp4"),
        config=_config(),
        max_stage_retries=3,
    )
    return created.project_id, created.run_id


def test_exact_historical_v2_config_loads_as_algorithm_a() -> None:
    payload = _config().model_dump(mode="json")
    del payload["semantic_validation_contract"]
    payload["schema_version"] = "2"
    for field in (
        *V5_SEMANTIC_GLOBAL_FIELDS,
        *V6_BOUNDARY_REVIEW_FIELDS,
        *V7_CLIP_PROFILE_FIELDS,
        "clipping_algorithm",
        "semantic_skill_version",
        "semantic_skill_sha256",
        "semantic_score_threshold",
        "semantic_target_clip_ms",
        "semantic_continuous_merge_enabled",
        "semantic_consolidation_skill_version",
        "semantic_consolidation_skill_sha256",
    ):
        del payload[field]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    restored = load_persisted_pipeline_config(
        payload,
        hashlib.sha256(serialized.encode()).hexdigest(),
    )

    assert restored.schema_version == "8"
    assert restored.clipping_algorithm == "a"
    assert restored.top_n == 3


def test_exact_historical_v3_config_loads_without_continuous_merge() -> None:
    current = _config()
    payload = current.model_dump(mode="json")
    del payload["semantic_validation_contract"]
    payload["schema_version"] = "3"
    for field in (
        *V5_SEMANTIC_GLOBAL_FIELDS,
        *V6_BOUNDARY_REVIEW_FIELDS,
        *V7_CLIP_PROFILE_FIELDS,
        "semantic_target_clip_ms",
        "semantic_continuous_merge_enabled",
        "semantic_consolidation_skill_version",
        "semantic_consolidation_skill_sha256",
    ):
        del payload[field]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    restored = load_persisted_pipeline_config(
        payload,
        hashlib.sha256(serialized.encode()).hexdigest(),
    )

    assert restored.schema_version == "8"
    assert restored.semantic_continuous_merge_enabled is False
    assert restored.semantic_target_clip_ms == restored.maximum_clip_ms


def test_exact_experimental_v4_config_loads_without_becoming_semantic_global() -> None:
    payload = _config().model_dump(mode="json")
    del payload["semantic_validation_contract"]
    payload["schema_version"] = "4"
    for field in (
        *V5_SEMANTIC_GLOBAL_FIELDS,
        *V6_BOUNDARY_REVIEW_FIELDS,
        *V7_CLIP_PROFILE_FIELDS,
    ):
        del payload[field]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    restored = load_persisted_pipeline_config(
        payload,
        hashlib.sha256(serialized.encode()).hexdigest(),
    )

    assert restored.schema_version == "8"
    assert restored.clipping_algorithm == "a"
    assert restored.semantic_discovery_skill_sha256 == "0" * 64


def test_exact_historical_v5_config_keeps_v2_contract_when_upgraded() -> None:
    payload = _config().model_dump(mode="json")
    del payload["semantic_validation_contract"]
    payload["schema_version"] = "5"
    payload["semantic_global_review_skill_version"] = "semantic_global_v2.global_review"
    for field in (*V6_BOUNDARY_REVIEW_FIELDS, *V7_CLIP_PROFILE_FIELDS):
        del payload[field]
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    restored = load_persisted_pipeline_config(
        payload,
        hashlib.sha256(serialized.encode()).hexdigest(),
    )

    assert restored.schema_version == "8"
    assert restored.semantic_global_review_skill_version == ("semantic_global_v2.global_review")
    assert restored.semantic_boundary_review_skill_sha256 == "0" * 64


def test_pipeline_service_rechecks_data_directory_source_before_database_insert(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "state" / "pipeline.sqlite3")
    Base.metadata.create_all(engine)
    data_dir = tmp_path / "projects"
    source = data_dir / "existing-project" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"must survive cleanup")
    service = PipelineService(
        SqlAlchemyPipelineRepository(engine),
        forbidden_source_roots=(data_dir,),
    )
    try:
        with pytest.raises(ValueError, match="outside the LiveClip data"):
            service.create_project_and_run(
                source_path=source,
                config=_config(),
                max_stage_retries=3,
            )
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(ProjectRow)) == 0
        assert source.read_bytes() == b"must survive cleanup"
    finally:
        engine.dispose(close=True)


def _identity(lease: TaskLease) -> LeaseIdentity:
    return LeaseIdentity(
        task_id=lease.task_id,
        worker_id=lease.worker_id,
        lease_token=lease.lease_token,
    )


def _committed_stage_asset(
    engine: Engine,
    *,
    project_id: str,
    stage: PipelineStage,
    sha256: str = "a" * 64,
) -> tuple[str, str]:
    asset_id = new_id()
    with engine.begin() as connection:
        connection.execute(
            insert(AssetRow).values(
                id=asset_id,
                project_id=project_id,
                status=AssetStatus.COMMITTED.value,
                kind="source_metadata"
                if stage == PipelineStage.INGEST
                else f"{stage.value}_result",
                relative_path=f"stages/{stage.value}/result.json",
                mime_type="application/json",
                input_fingerprint="i" * 64,
                sha256=sha256,
                size_bytes=128,
                validation_json={"schema_version": "1"},
                generation=1,
                created_at=NOW,
                committed_at=NOW,
            )
        )
    return asset_id, sha256


@pytest.mark.parametrize("mutation", ["legacy", "missing-field", "fingerprint-mismatch"])
def test_stage_resume_rejects_legacy_or_tampered_config_snapshot_before_handler(
    pipeline_context: tuple[Engine, PipelineService], mutation: str
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    with engine.begin() as connection:
        row = connection.execute(
            select(PipelineRunRow.config_json).where(PipelineRunRow.id == run_id)
        ).one()
        payload = dict(row.config_json)
        if mutation == "legacy":
            payload["schema_version"] = "1"
        elif mutation == "missing-field":
            del payload["editing_prompt_sha256"]
        else:
            payload["top_n"] = int(payload["top_n"]) + 1
        connection.execute(
            update(PipelineRunRow).where(PipelineRunRow.id == run_id).values(config_json=payload)
        )
    queue = SQLiteTaskQueue(engine, lease_seconds=60)
    lease = queue.claim(worker_id="config-audit", pipeline_run_id=run_id)
    assert lease is not None

    with pytest.raises(PipelineConflict, match=r"legacy|incomplete|fingerprint"):
        SqlAlchemyPipelineRepository(engine).start_or_resume_stage(_identity(lease))

    # Claiming establishes the running lease before repository integrity loading;
    # the caller must classify this deterministic config failure and close the task.


def test_configured_price_snapshot_round_trips_before_stage_start(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    config = _config().model_copy(
        update={
            "llm_input_price_per_million": Decimal("1.25"),
            "llm_output_price_per_million": Decimal("5.50"),
        }
    )
    created = service.create_project_and_run(
        source_path=Path("/allowed/priced-source.mp4"),
        config=config,
        max_stage_retries=0,
    )
    queue = SQLiteTaskQueue(engine, lease_seconds=60)
    lease = queue.claim(worker_id="price-roundtrip", pipeline_run_id=created.run_id)
    assert lease is not None

    work = SqlAlchemyPipelineRepository(engine).start_or_resume_stage(_identity(lease))

    assert work.config == config
    assert work.config.llm_input_price_per_million == Decimal("1.25")


def test_create_project_run_stages_and_dependency_tasks_atomically(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    project_id, run_id = _create(service)

    snapshot = service.get_run(run_id)
    project = service.get_project(project_id)
    assert snapshot.status == PipelineRunStatus.QUEUED
    assert [stage.stage for stage in snapshot.stages] == [
        "ingest",
        "preprocess",
        "transcribe",
        "candidates",
        "edit",
        "proxy_render",
    ]
    assert all(stage.status == StageRunStatus.QUEUED for stage in snapshot.stages)
    assert project.status == ProjectStatus.PROCESSING
    assert project.source_filename == "source-a.mp4"

    with engine.connect() as connection:
        tasks = connection.execute(
            select(TaskRow.id, TaskRow.depends_on_task_id).order_by(TaskRow.priority.desc())
        ).all()
        assert connection.scalar(select(func.count()).select_from(StageRunRow)) == 6
    assert len(tasks) == 1
    assert tasks[0][1] is None


def test_cancel_queued_run_is_immediately_terminal(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)

    snapshot = service.cancel(run_id)

    assert snapshot.status == PipelineRunStatus.CANCELLED
    assert snapshot.cancellation_requested is True
    assert all(stage.status == StageRunStatus.CANCELLED for stage in snapshot.stages)
    with engine.connect() as connection:
        statuses = connection.scalars(select(TaskRow.status)).all()
    assert set(statuses) == {TaskStatus.CANCELLED.value}


def _insert_completion_task(
    engine: Engine, run_id: str, *, status: TaskStatus = TaskStatus.QUEUED
) -> str:
    task_id = new_id()
    lease = status == TaskStatus.RUNNING
    with engine.begin() as connection:
        connection.execute(
            insert(TaskRow).values(
                id=task_id,
                kind=TaskKind.COMPLETION.value,
                target_id=new_id(),
                operation_key=f"completion:{task_id}",
                input_fingerprint="f" * 64,
                resource_class=ResourceClass.CHEAP.value,
                pipeline_run_id=run_id,
                status=status.value,
                priority=50,
                not_before=NOW,
                expected_generation=1,
                attempt_count=int(lease),
                retry_count=0,
                manual_retry_count=0,
                max_retries=3,
                worker_id="completion-worker" if lease else None,
                lease_token="completion-lease" if lease else None,
                heartbeat_at=NOW if lease else None,
                lease_expires_at=NOW + timedelta(seconds=30) if lease else None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
    return task_id


@pytest.mark.parametrize("status", [TaskStatus.QUEUED, TaskStatus.WAITING])
def test_processing_cancel_preserves_completion_goal_task(
    pipeline_context: tuple[Engine, PipelineService], status: TaskStatus
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    task_id = _insert_completion_task(engine, run_id, status=status)

    assert service.cancel(run_id).status == PipelineRunStatus.CANCELLED
    with engine.connect() as connection:
        actual = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(TaskRow.id == task_id)
        ).one()
    assert actual == (status.value, None)


def test_running_completion_does_not_delay_processing_cancel(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    with engine.begin() as connection:
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(status=PipelineRunStatus.RUNNING.value, started_at=NOW)
        )
    task_id = _insert_completion_task(engine, run_id, status=TaskStatus.RUNNING)

    assert service.cancel(run_id).status == PipelineRunStatus.CANCELLED
    with engine.connect() as connection:
        actual = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(TaskRow.id == task_id)
        ).one()
    assert actual == (TaskStatus.RUNNING.value, None)


def test_new_generation_ignores_old_completion_coordination(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    project_id, run_id = _create(service)
    with engine.begin() as connection:
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(status=PipelineRunStatus.COMPLETED.value, progress=100)
        )
        connection.execute(
            update(TaskRow)
            .where(TaskRow.pipeline_run_id == run_id)
            .values(status=TaskStatus.SUCCEEDED.value, completed_at=NOW)
        )
    task_id = _insert_completion_task(engine, run_id)

    next_run = service.create_run(project_id=project_id, config=_config(), max_stage_retries=3)

    assert next_run.run_id != run_id
    with engine.connect() as connection:
        old_task = connection.scalar(select(TaskRow.status).where(TaskRow.id == task_id))
    assert old_task == TaskStatus.QUEUED.value


def test_completion_effect_authority_rechecks_current_role_and_run(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    project_id, run_id = _create(service)
    with engine.connect() as connection:
        actor_id = connection.scalar(select(ProjectRow.owner_id).where(ProjectRow.id == project_id))
    assert actor_id is not None

    def check(action: ProjectAction) -> None:
        with engine.begin() as connection:
            require_current_project_action(
                connection,
                project_id=project_id,
                actor_user_id=actor_id,
                action=action,
                expected_run_id=run_id,
                expected_generation=1,
            )

    check("review_clip")
    with engine.begin() as connection:
        connection.execute(
            update(ProjectMemberRow)
            .where(ProjectMemberRow.project_id == project_id)
            .values(role="editor")
        )
    check("deliver")
    with pytest.raises(CurrentProjectAccessDenied):
        check("review_clip")

    with engine.begin() as connection:
        connection.execute(
            update(WorkspaceUserRow).where(WorkspaceUserRow.id == actor_id).values(is_active=False)
        )
    with pytest.raises(CurrentProjectAccessDenied):
        check("deliver")

    with engine.begin() as connection:
        connection.execute(
            update(WorkspaceUserRow).where(WorkspaceUserRow.id == actor_id).values(is_active=True)
        )
        connection.execute(
            update(ProjectRow).where(ProjectRow.id == project_id).values(current_generation=2)
        )
    with pytest.raises(CurrentProjectRunChanged):
        check("deliver")


def test_cancel_running_run_remains_requested_until_owner_acknowledges(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    with engine.begin() as connection:
        first_stage = connection.execute(
            select(StageRunRow.id)
            .where(StageRunRow.pipeline_run_id == run_id)
            .order_by(StageRunRow.ordinal)
            .limit(1)
        ).scalar_one()
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(status=PipelineRunStatus.RUNNING.value, started_at=NOW)
        )
        connection.execute(
            update(StageRunRow)
            .where(StageRunRow.id == first_stage)
            .values(status=StageRunStatus.RUNNING.value, started_at=NOW)
        )
        connection.execute(
            update(TaskRow)
            .where(TaskRow.stage_run_id == first_stage)
            .values(
                status=TaskStatus.RUNNING.value,
                worker_id="worker-a",
                lease_token="lease-a",
                heartbeat_at=NOW,
                lease_expires_at=NOW + timedelta(seconds=30),
            )
        )

    snapshot = service.cancel(run_id)

    assert snapshot.status == PipelineRunStatus.RUNNING
    assert snapshot.cancellation_requested is True
    assert snapshot.stages[0].status == StageRunStatus.RUNNING
    assert all(stage.status == StageRunStatus.CANCELLED for stage in snapshot.stages[1:])
    with engine.connect() as connection:
        running = connection.execute(
            select(TaskRow.status, TaskRow.cancellation_requested_at).where(
                TaskRow.stage_run_id == first_stage
            )
        ).one()
    assert running[0] == TaskStatus.RUNNING.value
    assert running[1] is not None


def test_transient_failed_run_can_be_manually_retried_with_fresh_budget(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    with engine.begin() as connection:
        first_stage = connection.scalar(
            select(StageRunRow.id)
            .where(StageRunRow.pipeline_run_id == run_id)
            .order_by(StageRunRow.ordinal)
            .limit(1)
        )
        assert first_stage is not None
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(
                status=PipelineRunStatus.FAILED.value,
                failure_class=FailureClass.TRANSIENT.value,
                error_code="LEASE_EXPIRED",
            )
        )
        connection.execute(
            update(StageRunRow)
            .where(StageRunRow.id == first_stage)
            .values(
                status=StageRunStatus.FAILED.value,
                failure_class=FailureClass.TRANSIENT.value,
            )
        )
        connection.execute(
            update(TaskRow)
            .where(TaskRow.stage_run_id == first_stage)
            .values(
                status=TaskStatus.FAILED.value,
                retry_count=3,
                failure_class=FailureClass.TRANSIENT.value,
            )
        )

    snapshot = service.retry(run_id)

    assert snapshot.status == PipelineRunStatus.QUEUED
    assert snapshot.stages[0].status == StageRunStatus.QUEUED
    with engine.connect() as connection:
        task = connection.execute(
            select(TaskRow.status, TaskRow.retry_count, TaskRow.manual_retry_count).where(
                TaskRow.stage_run_id == first_stage
            )
        ).one()
    assert task == (TaskStatus.QUEUED.value, 0, 1)


def test_deterministic_failed_run_requires_a_new_generation(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    with engine.begin() as connection:
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(
                status=PipelineRunStatus.FAILED.value,
                failure_class=FailureClass.DETERMINISTIC.value,
            )
        )

    with pytest.raises(DeterministicRetryRejected, match="new run"):
        service.retry(run_id)


@pytest.mark.parametrize(
    "error_code",
    [
        "UNEXPECTED_STAGE_ERROR",
        "CANDIDATES_OUTPUT_INVALID",
        "EDIT_OUTPUT_INVALID",
        "PROXY_RENDER_OUTPUT_INVALID",
        "CANDIDATES_CODEX_NESTED_SESSION",
        "EDIT_CODEX_NESTED_SESSION",
    ],
)
def test_local_implementation_failure_can_be_manually_retried_after_repair(
    pipeline_context: tuple[Engine, PipelineService],
    error_code: str,
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    with engine.begin() as connection:
        first_stage = connection.scalar(
            select(StageRunRow.id)
            .where(StageRunRow.pipeline_run_id == run_id)
            .order_by(StageRunRow.ordinal)
            .limit(1)
        )
        assert first_stage is not None
        failure_values = {
            "failure_class": FailureClass.DETERMINISTIC.value,
            "error_code": error_code,
        }
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(status=PipelineRunStatus.FAILED.value, **failure_values)
        )
        connection.execute(
            update(StageRunRow)
            .where(StageRunRow.id == first_stage)
            .values(status=StageRunStatus.FAILED.value, **failure_values)
        )
        connection.execute(
            update(TaskRow)
            .where(TaskRow.stage_run_id == first_stage)
            .values(status=TaskStatus.FAILED.value, retry_count=3, **failure_values)
        )

    snapshot = service.retry(run_id)

    assert snapshot.status == PipelineRunStatus.QUEUED
    assert snapshot.stages[0].status == StageRunStatus.QUEUED
    with engine.connect() as connection:
        task = connection.execute(
            select(TaskRow.status, TaskRow.retry_count, TaskRow.manual_retry_count).where(
                TaskRow.stage_run_id == first_stage
            )
        ).one()
    assert task == (TaskStatus.QUEUED.value, 0, 1)


def test_legacy_asr_response_invalid_can_be_retried_from_provider_evidence(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    project_id, run_id = _create(service)
    with engine.begin() as connection:
        failed_stage = connection.scalar(
            select(StageRunRow.id).where(
                StageRunRow.pipeline_run_id == run_id,
                StageRunRow.stage == PipelineStage.TRANSCRIBE.value,
            )
        )
        assert failed_stage is not None
        task_id = connection.scalar(
            select(TaskRow.id).where(TaskRow.pipeline_run_id == run_id).limit(1)
        )
        assert task_id is not None
        failure_values = {
            "failure_class": FailureClass.DETERMINISTIC.value,
            "error_code": "TRANSCRIBE_PROVIDER_INVALID",
        }
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(status=PipelineRunStatus.FAILED.value, **failure_values)
        )
        connection.execute(
            update(StageRunRow)
            .where(StageRunRow.id == failed_stage)
            .values(status=StageRunStatus.FAILED.value, **failure_values)
        )
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == task_id)
            .values(
                target_id=failed_stage,
                stage_run_id=failed_stage,
                status=TaskStatus.FAILED.value,
                retry_count=3,
                **failure_values,
            )
        )
        connection.execute(
            insert(ApiUsageRow).values(
                id=new_id(),
                project_id=project_id,
                pipeline_run_id=run_id,
                stage_run_id=failed_stage,
                provider="openrouter",
                operation="audio.transcriptions",
                model="openai/whisper-large-v3",
                request_id="gen_legacy_invalid_001",
                request_count=1,
                retry_count=0,
                latency_ms=25,
                audio_seconds=90.0,
                usage_json={"failure_code": "OPENROUTER_ASR_RESPONSE_INVALID"},
                status="invalid",
                called_at=NOW,
            )
        )

    snapshot = service.retry(run_id)

    assert snapshot.status == PipelineRunStatus.QUEUED
    assert snapshot.stages[0].status == StageRunStatus.QUEUED


def test_provider_invalid_without_response_evidence_still_requires_new_run(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    with engine.begin() as connection:
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(
                status=PipelineRunStatus.FAILED.value,
                failure_class=FailureClass.DETERMINISTIC.value,
                error_code="TRANSCRIBE_PROVIDER_INVALID",
            )
        )

    with pytest.raises(DeterministicRetryRejected, match="new run"):
        service.retry(run_id)


def test_completed_pipeline_without_decisions_is_pending_review(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    project_id, run_id = _create(service)
    with engine.begin() as connection:
        connection.execute(
            update(PipelineRunRow)
            .where(PipelineRunRow.id == run_id)
            .values(status=PipelineRunStatus.COMPLETED.value, progress=100)
        )
        connection.execute(
            update(StageRunRow)
            .where(StageRunRow.pipeline_run_id == run_id)
            .values(status=StageRunStatus.SUCCEEDED.value, progress=100)
        )

    assert service.get_project(project_id).status == ProjectStatus.PENDING_REVIEW


def test_stage_start_and_completion_atomically_finish_task_and_attempt(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    repository = SqlAlchemyPipelineRepository(engine)
    queue = SQLiteTaskQueue(engine, lease_seconds=120)
    lease = queue.claim(worker_id="worker-a")
    assert lease is not None
    identity = _identity(lease)

    work = repository.start_or_resume_stage(identity)
    assert work.stage.value == "ingest"
    assert work.already_succeeded is False
    assert service.get_run(run_id).status == PipelineRunStatus.RUNNING

    asset_id, asset_sha = _committed_stage_asset(
        engine, project_id=work.project_id, stage=work.stage
    )
    source_media_id = "1" * 32
    with engine.begin() as connection:
        connection.execute(
            insert(SourceMediaRow).values(
                id=source_media_id,
                project_id=work.project_id,
                resolved_path="/allowed/source-a.mp4",
                filename="source-a.mp4",
                sha256="b" * 64,
                size_bytes=1_024,
                mtime_ns=1,
                duration_ms=10_000,
                width=1280,
                height=720,
                video_codec="h264",
                audio_codec="aac",
                frame_rate="30.0",
                probe_json={"schema_version": "test"},
                created_at=NOW,
            )
        )
    completed = repository.complete_stage(
        identity,
        output_fingerprint=stage_output_fingerprint(work.stage, (asset_sha,)),
        checkpoint={"source_media_id": source_media_id, "asset_ids": [asset_id]},
    )

    assert completed is True
    snapshot = service.get_run(run_id)
    assert snapshot.stages[0].status == StageRunStatus.SUCCEEDED
    assert snapshot.progress == 16
    with engine.connect() as connection:
        task_status = connection.scalar(select(TaskRow.status).where(TaskRow.id == lease.task_id))
    assert task_status == TaskStatus.SUCCEEDED.value
    next_lease = queue.claim(worker_id="worker-b")
    assert next_lease is not None and next_lease.target_id != lease.target_id


def test_ingest_completion_rejects_asset_without_persisted_source_media(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, _ = _create(service)
    repository = SqlAlchemyPipelineRepository(engine)
    queue = SQLiteTaskQueue(engine, lease_seconds=120)
    lease = queue.claim(worker_id="worker-a")
    assert lease is not None
    identity = _identity(lease)
    work = repository.start_or_resume_stage(identity)
    asset_id, asset_sha = _committed_stage_asset(
        engine, project_id=work.project_id, stage=work.stage
    )

    with pytest.raises(PipelineConflict, match="persisted source media"):
        repository.complete_stage(
            identity,
            output_fingerprint=stage_output_fingerprint(work.stage, (asset_sha,)),
            checkpoint={"source_media_id": "1" * 32, "asset_ids": [asset_id]},
        )

    assert service.get_run(work.run_id).stages[0].status == StageRunStatus.RUNNING


def test_stage_completion_rejects_missing_or_uncommitted_assets(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, _ = _create(service)
    repository = SqlAlchemyPipelineRepository(engine)
    queue = SQLiteTaskQueue(engine, lease_seconds=120)
    lease = queue.claim(worker_id="worker-a")
    assert lease is not None
    identity = _identity(lease)
    work = repository.start_or_resume_stage(identity)

    with pytest.raises(PipelineConflict, match="missing or uncommitted"):
        repository.complete_stage(
            identity,
            output_fingerprint="f" * 64,
            checkpoint={"asset_ids": ["missing"]},
        )

    assert service.get_run(work.run_id).stages[0].status == StageRunStatus.RUNNING


def test_cancel_wins_before_atomic_stage_completion(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    repository = SqlAlchemyPipelineRepository(engine)
    queue = SQLiteTaskQueue(engine, lease_seconds=120)
    lease = queue.claim(worker_id="worker-a")
    assert lease is not None
    identity = _identity(lease)
    repository.start_or_resume_stage(identity)

    service.cancel(run_id)

    assert (
        repository.complete_stage(
            identity,
            output_fingerprint="f" * 64,
            checkpoint={"late": True},
        )
        is False
    )
    assert repository.cancel_stage(identity) is True
    assert service.get_run(run_id).status == PipelineRunStatus.CANCELLED


def test_stage_failure_retries_transient_and_terminals_deterministic(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service)
    repository = SqlAlchemyPipelineRepository(engine)
    queue = SQLiteTaskQueue(engine, lease_seconds=120)
    transient = queue.claim(worker_id="worker-a")
    assert transient is not None
    repository.start_or_resume_stage(_identity(transient))

    assert (
        repository.fail_stage(
            _identity(transient),
            failure_class=FailureClass.TRANSIENT,
            error_code="TEMPORARY_MEDIA_ERROR",
            safe_message="Temporary media operation failed",
            retry_delay_ms=0,
        )
        == TaskStatus.QUEUED
    )
    assert service.get_run(run_id).stages[0].status == StageRunStatus.RUNNING

    retry = queue.claim(worker_id="worker-b")
    assert retry is not None and retry.task_id == transient.task_id
    assert (
        repository.fail_stage(
            _identity(retry),
            failure_class=FailureClass.DETERMINISTIC,
            error_code="SOURCE_CHANGED",
            safe_message="Source media changed after import",
            retry_delay_ms=0,
        )
        == TaskStatus.FAILED
    )
    snapshot = service.get_run(run_id)
    assert snapshot.status == PipelineRunStatus.FAILED
    assert snapshot.stages[0].status == StageRunStatus.FAILED


def test_cancel_after_transient_requeue_terminally_cancels_stage_and_run(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service, "retry-cancel")
    repository = SqlAlchemyPipelineRepository(engine)
    queue = SQLiteTaskQueue(engine, lease_seconds=120)
    lease = queue.claim(worker_id="worker-a")
    assert lease is not None
    repository.start_or_resume_stage(_identity(lease))
    assert (
        repository.fail_stage(
            _identity(lease),
            failure_class=FailureClass.TRANSIENT,
            error_code="TEMPORARY_MEDIA_ERROR",
            safe_message="Temporary media operation failed",
            retry_delay_ms=30_000,
        )
        == TaskStatus.QUEUED
    )

    snapshot = service.cancel(run_id)

    assert snapshot.status == PipelineRunStatus.CANCELLED
    assert all(stage.status == StageRunStatus.CANCELLED for stage in snapshot.stages)
    with engine.connect() as connection:
        assert set(connection.scalars(select(TaskRow.status))) == {TaskStatus.CANCELLED.value}

    resumed = service.retry(run_id)

    assert resumed.status == PipelineRunStatus.QUEUED
    assert all(stage.status == StageRunStatus.QUEUED for stage in resumed.stages)
    with engine.connect() as connection:
        task = connection.execute(
            select(
                TaskRow.status,
                TaskRow.retry_count,
                TaskRow.manual_retry_count,
                TaskRow.cancellation_requested_at,
            )
        ).one()
    assert task.status == TaskStatus.QUEUED.value
    assert task.retry_count == 0
    assert task.manual_retry_count == 1
    assert task.cancellation_requested_at is None


def test_stage_claim_and_exhausted_lease_recovery_keep_aggregate_consistent(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    created = service.create_project_and_run(
        source_path=Path("/allowed/source-expiry.mp4"),
        config=_config(),
        max_stage_retries=0,
    )
    queue = SQLiteTaskQueue(engine, lease_seconds=10)
    claimed_at = datetime.now(UTC) + timedelta(seconds=1)

    lease = queue.claim(worker_id="worker-expiry", now=claimed_at)
    assert lease is not None
    running = service.get_run(created.run_id)
    assert running.status == PipelineRunStatus.RUNNING
    assert running.stages[0].status == StageRunStatus.RUNNING

    recovered = queue.recover_expired(now=claimed_at + timedelta(seconds=10))

    assert recovered.failed == 1
    failed = service.get_run(created.run_id)
    assert failed.status == PipelineRunStatus.FAILED
    assert failed.stages[0].status == StageRunStatus.FAILED
    assert failed.stages[0].error_code == "LEASE_EXPIRED"


def test_cancelled_stage_owner_expiry_cancels_run_and_descendants(
    pipeline_context: tuple[Engine, PipelineService],
) -> None:
    engine, service = pipeline_context
    _, run_id = _create(service, "cancel-expiry")
    queue = SQLiteTaskQueue(engine, lease_seconds=10)
    claimed_at = datetime.now(UTC) + timedelta(seconds=1)
    lease = queue.claim(worker_id="worker-cancel", now=claimed_at)
    assert lease is not None

    requested = service.cancel(run_id)
    assert requested.status == PipelineRunStatus.RUNNING
    assert requested.cancellation_requested is True

    recovered = queue.recover_expired(now=claimed_at + timedelta(seconds=10))

    assert recovered.cancelled == 1
    cancelled = service.get_run(run_id)
    assert cancelled.status == PipelineRunStatus.CANCELLED
    assert all(stage.status == StageRunStatus.CANCELLED for stage in cancelled.stages)
