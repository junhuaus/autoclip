from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import (
    CreatedPipeline,
    DeterministicRetryRejected,
    LeaseIdentity,
    PipelineConflict,
    PipelineResourceNotFound,
    PipelineRunConfig,
    ProjectSnapshot,
    RunSnapshot,
    StageLeaseLost,
    StageSnapshot,
    StageWork,
    load_persisted_pipeline_config,
)
from liveclip.application.stage_execution import stage_output_fingerprint
from liveclip.db.base import new_id
from liveclip.db.delivery_snapshot import DeliverySetError, load_eligible_delivery_set
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AssetRow,
    AudioChunkRow,
    CandidateClipRow,
    DeliveryRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
    TranscriptRow,
    TranscriptSegmentRow,
)
from liveclip.domain.state_transitions import (
    PIPELINE_STAGE_ORDER,
    AssetStatus,
    AttemptOutcome,
    DeliveryStatus,
    FailureClass,
    PipelineRunStatus,
    PipelineStage,
    ProjectStateFacts,
    RenderStatus,
    ResourceClass,
    ReviewStatus,
    StageRunStatus,
    TaskKind,
    TaskStatus,
    derive_project_status,
    transition_pipeline_run,
    transition_render,
    transition_stage_run,
)


class StageFenceLost(PipelineConflict, StageLeaseLost):
    pass


class SqlAlchemyPipelineRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_project_and_run(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline:
        now = datetime.now(UTC)
        project_id = new_id()
        run_id = new_id()
        with begin_immediate(self._engine) as connection:
            replay_run_id = load_idempotent_resource(
                connection, idempotency, resource_type="pipeline_run"
            )
            if replay_run_id is not None:
                replay_project_id = connection.scalar(
                    select(PipelineRunRow.project_id).where(PipelineRunRow.id == replay_run_id)
                )
                if replay_project_id is None:
                    raise PipelineConflict("idempotent pipeline resource no longer exists")
                return CreatedPipeline(project_id=str(replay_project_id), run_id=replay_run_id)
            connection.execute(
                insert(ProjectRow).values(
                    id=project_id,
                    name=source_path.stem[:200] or "LiveClip project",
                    source_request_path=str(source_path),
                    current_generation=1,
                    current_pipeline_run_id=run_id,
                    revision_epoch=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            _insert_pipeline_run(
                connection,
                project_id=project_id,
                run_id=run_id,
                generation=1,
                source_path=source_path,
                config=config,
                max_stage_retries=max_stage_retries,
                now=now,
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="pipeline_run",
                resource_id=run_id,
            )
        return CreatedPipeline(project_id=project_id, run_id=run_id)

    def create_run(
        self,
        *,
        project_id: str,
        config: PipelineRunConfig,
        max_stage_retries: int,
        idempotency: IdempotencyContext | None = None,
    ) -> CreatedPipeline:
        now = datetime.now(UTC)
        run_id = new_id()
        with begin_immediate(self._engine) as connection:
            replay_run_id = load_idempotent_resource(
                connection, idempotency, resource_type="pipeline_run"
            )
            if replay_run_id is not None:
                replay_project_id = connection.scalar(
                    select(PipelineRunRow.project_id).where(PipelineRunRow.id == replay_run_id)
                )
                if replay_project_id is None or str(replay_project_id) != project_id:
                    raise PipelineConflict("idempotent pipeline resource no longer matches project")
                return CreatedPipeline(project_id=project_id, run_id=replay_run_id)
            project = connection.execute(
                select(
                    ProjectRow.source_request_path,
                    ProjectRow.current_pipeline_run_id,
                    ProjectRow.current_generation,
                    ProjectRow.revision_epoch,
                ).where(ProjectRow.id == project_id)
            ).one_or_none()
            if project is None:
                raise PipelineResourceNotFound("project does not exist")
            current_run_id = project.current_pipeline_run_id
            if current_run_id is not None:
                current_status = connection.scalar(
                    select(PipelineRunRow.status).where(PipelineRunRow.id == current_run_id)
                )
                if current_status in {
                    PipelineRunStatus.QUEUED.value,
                    PipelineRunStatus.RUNNING.value,
                }:
                    raise PipelineConflict("project already has an active pipeline run")
                active_work = connection.scalar(
                    select(func.count())
                    .select_from(TaskRow)
                    .where(
                        TaskRow.pipeline_run_id == current_run_id,
                        TaskRow.status.in_([TaskStatus.QUEUED.value, TaskStatus.RUNNING.value]),
                    )
                )
                if active_work:
                    raise PipelineConflict("project still has active render or delivery work")
                for current in (
                    RenderStatus.QUEUED,
                    RenderStatus.RUNNING,
                    RenderStatus.SUCCEEDED,
                    RenderStatus.FAILED,
                ):
                    transition_render(current, RenderStatus.STALE)
                connection.execute(
                    update(RenderJobRow)
                    .where(
                        RenderJobRow.candidate_clip_id.in_(
                            select(CandidateClipRow.id).where(
                                CandidateClipRow.pipeline_run_id == current_run_id
                            )
                        ),
                        RenderJobRow.status != RenderStatus.STALE.value,
                    )
                    .values(status=RenderStatus.STALE.value, updated_at=now)
                )
            generation = int(project.current_generation) + 1
            revision_epoch = int(project.revision_epoch) + 1
            connection.execute(
                update(ProjectRow)
                .where(ProjectRow.id == project_id)
                .values(
                    current_generation=generation,
                    current_pipeline_run_id=run_id,
                    revision_epoch=revision_epoch,
                    updated_at=now,
                )
            )
            _insert_pipeline_run(
                connection,
                project_id=project_id,
                run_id=run_id,
                generation=generation,
                source_path=Path(str(project.source_request_path)),
                config=config,
                max_stage_retries=max_stage_retries,
                now=now,
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="pipeline_run",
                resource_id=run_id,
            )
        return CreatedPipeline(project_id=project_id, run_id=run_id)

    def list_projects(self) -> tuple[ProjectSnapshot, ...]:
        with self._engine.connect() as connection:
            project_ids = tuple(
                str(value)
                for value in connection.scalars(
                    select(ProjectRow.id).order_by(ProjectRow.created_at.desc(), ProjectRow.id)
                )
            )
        return tuple(self.get_project(project_id) for project_id in project_ids)

    def get_run(self, run_id: str) -> RunSnapshot:
        with self._engine.connect() as connection:
            run = (
                connection.execute(
                    select(
                        PipelineRunRow.id,
                        PipelineRunRow.project_id,
                        PipelineRunRow.status,
                        PipelineRunRow.progress,
                        PipelineRunRow.cancellation_requested_at,
                        PipelineRunRow.error_code,
                        PipelineRunRow.safe_error_message,
                    ).where(PipelineRunRow.id == run_id)
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                raise PipelineResourceNotFound("pipeline run does not exist")
            stages = connection.execute(
                select(
                    StageRunRow.stage,
                    StageRunRow.status,
                    StageRunRow.progress,
                    StageRunRow.retry_count,
                    StageRunRow.error_code,
                    StageRunRow.safe_error_message,
                )
                .where(StageRunRow.pipeline_run_id == run_id)
                .order_by(StageRunRow.ordinal)
            ).mappings()
            stage_snapshots = tuple(
                StageSnapshot(
                    stage=str(stage["stage"]),
                    status=StageRunStatus(str(stage["status"])),
                    progress=int(stage["progress"]),
                    retry_count=int(stage["retry_count"]),
                    error_code=_optional_string(stage["error_code"]),
                    safe_error_message=_optional_string(stage["safe_error_message"]),
                )
                for stage in stages
            )
        return RunSnapshot(
            run_id=str(run["id"]),
            project_id=str(run["project_id"]),
            status=PipelineRunStatus(str(run["status"])),
            progress=int(run["progress"]),
            cancellation_requested=run["cancellation_requested_at"] is not None,
            error_code=_optional_string(run["error_code"]),
            safe_error_message=_optional_string(run["safe_error_message"]),
            stages=stage_snapshots,
        )

    def get_project(self, project_id: str) -> ProjectSnapshot:
        with self._engine.connect() as connection:
            project = (
                connection.execute(
                    select(
                        ProjectRow.id,
                        ProjectRow.name,
                        ProjectRow.source_request_path,
                        ProjectRow.current_pipeline_run_id,
                        ProjectRow.current_generation,
                        ProjectRow.revision_epoch,
                    ).where(ProjectRow.id == project_id)
                )
                .mappings()
                .one_or_none()
            )
            if project is None or project["current_pipeline_run_id"] is None:
                raise PipelineResourceNotFound("project does not exist")
            run_id = str(project["current_pipeline_run_id"])
            run_facts = connection.execute(
                select(
                    PipelineRunRow.status,
                    PipelineRunRow.config_json,
                    PipelineRunRow.config_fingerprint,
                ).where(PipelineRunRow.id == run_id)
            ).one_or_none()
            if run_facts is None:
                raise PipelineResourceNotFound("project current run does not exist")
            run_status = PipelineRunStatus(str(run_facts.status))
            run_config = load_persisted_pipeline_config(
                run_facts.config_json,
                str(run_facts.config_fingerprint),
            )
            review_statuses, render_statuses, approved_final_count = _current_clip_facts(
                connection, project_id, run_id
            )
            latest_delivery = connection.execute(
                select(
                    DeliveryRow.status,
                    DeliveryRow.expected_revision_epoch,
                    DeliveryRow.expected_generation,
                    DeliveryRow.snapshot_fingerprint,
                )
                .where(DeliveryRow.project_id == project_id)
                .order_by(DeliveryRow.version.desc())
                .limit(1)
            ).one_or_none()
            delivery_status = (
                DeliveryStatus(str(latest_delivery[0])) if latest_delivery is not None else None
            )
            try:
                current_delivery_fingerprint = load_eligible_delivery_set(
                    connection, project_id
                ).fingerprint
            except DeliverySetError:
                current_delivery_fingerprint = None
            latest_attempt_matches_current = bool(
                latest_delivery is not None
                and current_delivery_fingerprint is not None
                and int(latest_delivery[1]) == int(project["revision_epoch"])
                and int(latest_delivery[2]) == int(project["current_generation"])
                and str(latest_delivery[3]) == current_delivery_fingerprint
            )
            latest_delivery_current = False
            if current_delivery_fingerprint is not None:
                succeeded_deliveries = connection.execute(
                    select(
                        DeliveryRow.expected_revision_epoch,
                        DeliveryRow.expected_generation,
                        DeliveryRow.snapshot_fingerprint,
                    ).where(
                        DeliveryRow.project_id == project_id,
                        DeliveryRow.status == DeliveryStatus.SUCCEEDED.value,
                    )
                )
                latest_delivery_current = any(
                    int(value.expected_revision_epoch) == int(project["revision_epoch"])
                    and int(value.expected_generation) == int(project["current_generation"])
                    and str(value.snapshot_fingerprint) == current_delivery_fingerprint
                    for value in succeeded_deliveries
                )
            persisted_source_filename = connection.scalar(
                select(SourceMediaRow.filename).where(SourceMediaRow.project_id == project_id)
            )
            source_filename = (
                persisted_source_filename or Path(str(project["source_request_path"])).name
            )
        project_status = derive_project_status(
            ProjectStateFacts(
                source_imported=True,
                has_completed_pipeline=(
                    run_status == PipelineRunStatus.COMPLETED and run_config.run_scope == "full"
                ),
                pipeline_status=run_status,
                render_statuses=render_statuses,
                delivery_status=delivery_status,
                review_statuses=review_statuses,
                approved_current_final_count=approved_final_count,
                has_unrecovered_failure=(
                    run_status == PipelineRunStatus.FAILED
                    or RenderStatus.FAILED in render_statuses
                    or (
                        delivery_status == DeliveryStatus.FAILED
                        and latest_attempt_matches_current
                        and not latest_delivery_current
                    )
                ),
                latest_delivery_matches_current=latest_delivery_current,
            )
        )
        return ProjectSnapshot(
            project_id=str(project["id"]),
            name=str(project["name"]),
            source_filename=str(source_filename),
            status=project_status,
            current_run_id=run_id,
            generation=int(project["current_generation"]),
        )

    def request_run_cancel(self, run_id: str) -> RunSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            status_value = connection.scalar(
                select(PipelineRunRow.status).where(PipelineRunRow.id == run_id)
            )
            if status_value is None:
                raise PipelineResourceNotFound("pipeline run does not exist")
            current = PipelineRunStatus(str(status_value))
            if current == PipelineRunStatus.QUEUED:
                transition_pipeline_run(current, PipelineRunStatus.CANCELLED)
                connection.execute(
                    update(PipelineRunRow)
                    .where(PipelineRunRow.id == run_id)
                    .values(
                        status=PipelineRunStatus.CANCELLED.value,
                        cancellation_requested_at=now,
                        finished_at=now,
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(StageRunRow)
                    .where(
                        StageRunRow.pipeline_run_id == run_id,
                        StageRunRow.status == StageRunStatus.QUEUED.value,
                    )
                    .values(status=StageRunStatus.CANCELLED.value, finished_at=now, updated_at=now)
                )
                connection.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.pipeline_run_id == run_id,
                        TaskRow.status == TaskStatus.QUEUED.value,
                    )
                    .values(
                        status=TaskStatus.CANCELLED.value,
                        cancellation_requested_at=now,
                        completed_at=now,
                        updated_at=now,
                    )
                )
            elif current == PipelineRunStatus.RUNNING:
                connection.execute(
                    update(PipelineRunRow)
                    .where(PipelineRunRow.id == run_id)
                    .values(cancellation_requested_at=now, updated_at=now)
                )
                connection.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.pipeline_run_id == run_id,
                        TaskRow.status == TaskStatus.QUEUED.value,
                    )
                    .values(
                        status=TaskStatus.CANCELLED.value,
                        cancellation_requested_at=now,
                        completed_at=now,
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(StageRunRow)
                    .where(
                        StageRunRow.pipeline_run_id == run_id,
                        StageRunRow.status == StageRunStatus.QUEUED.value,
                    )
                    .values(
                        status=StageRunStatus.CANCELLED.value,
                        finished_at=now,
                        updated_at=now,
                    )
                )
                connection.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.pipeline_run_id == run_id,
                        TaskRow.status == TaskStatus.RUNNING.value,
                    )
                    .values(cancellation_requested_at=now, updated_at=now)
                )
                running_tasks = connection.scalar(
                    select(func.count())
                    .select_from(TaskRow)
                    .where(
                        TaskRow.pipeline_run_id == run_id,
                        TaskRow.status == TaskStatus.RUNNING.value,
                    )
                )
                if running_tasks == 0:
                    connection.execute(
                        update(StageRunRow)
                        .where(
                            StageRunRow.pipeline_run_id == run_id,
                            StageRunRow.status.in_(
                                [StageRunStatus.QUEUED.value, StageRunStatus.RUNNING.value]
                            ),
                        )
                        .values(
                            status=StageRunStatus.CANCELLED.value,
                            finished_at=now,
                            updated_at=now,
                        )
                    )
                    connection.execute(
                        update(PipelineRunRow)
                        .where(PipelineRunRow.id == run_id)
                        .values(
                            status=PipelineRunStatus.CANCELLED.value,
                            finished_at=now,
                            updated_at=now,
                        )
                    )
        return self.get_run(run_id)

    def retry_failed_run(self, run_id: str) -> RunSnapshot:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            run = connection.execute(
                select(PipelineRunRow.status, PipelineRunRow.failure_class).where(
                    PipelineRunRow.id == run_id
                )
            ).one_or_none()
            if run is None:
                raise PipelineResourceNotFound("pipeline run does not exist")
            current = PipelineRunStatus(str(run[0]))
            if current != PipelineRunStatus.FAILED:
                raise PipelineConflict("only a failed pipeline run can be retried")
            if run[1] == FailureClass.DETERMINISTIC.value:
                raise DeterministicRetryRejected(
                    "deterministic failure requires changed input or configuration and a new run"
                )
            transition_pipeline_run(current, PipelineRunStatus.QUEUED)
            failed_stage_id = connection.scalar(
                select(StageRunRow.id)
                .where(
                    StageRunRow.pipeline_run_id == run_id,
                    StageRunRow.status == StageRunStatus.FAILED.value,
                )
                .order_by(StageRunRow.ordinal)
                .limit(1)
            )
            if failed_stage_id is None:
                raise PipelineConflict("failed pipeline has no failed stage to retry")
            connection.execute(
                update(PipelineRunRow)
                .where(PipelineRunRow.id == run_id)
                .values(
                    status=PipelineRunStatus.QUEUED.value,
                    manual_retry_count=PipelineRunRow.manual_retry_count + 1,
                    cancellation_requested_at=None,
                    failure_class=None,
                    error_code=None,
                    safe_error_message=None,
                    finished_at=None,
                    updated_at=now,
                )
            )
            connection.execute(
                update(StageRunRow)
                .where(StageRunRow.id == failed_stage_id)
                .values(
                    status=StageRunStatus.QUEUED.value,
                    failure_class=None,
                    error_code=None,
                    safe_error_message=None,
                    finished_at=None,
                    updated_at=now,
                )
            )
            retried = connection.execute(
                update(TaskRow)
                .where(
                    TaskRow.stage_run_id == failed_stage_id,
                    TaskRow.status == TaskStatus.FAILED.value,
                )
                .values(
                    status=TaskStatus.QUEUED.value,
                    retry_count=0,
                    manual_retry_count=TaskRow.manual_retry_count + 1,
                    not_before=now,
                    failure_class=None,
                    error_code=None,
                    safe_error_message=None,
                    completed_at=None,
                    updated_at=now,
                )
                .returning(TaskRow.id)
            ).scalar_one_or_none()
            if retried is None:
                raise PipelineConflict("failed stage has no failed task to retry")
        return self.get_run(run_id)

    def start_or_resume_stage(self, lease: LeaseIdentity) -> StageWork:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = (
                connection.execute(
                    select(
                        TaskRow.id.label("task_id"),
                        TaskRow.cancellation_requested_at.label("task_cancel"),
                        TaskRow.expected_generation,
                        StageRunRow.id.label("stage_run_id"),
                        StageRunRow.stage,
                        StageRunRow.status.label("stage_status"),
                        StageRunRow.input_fingerprint,
                        StageRunRow.output_fingerprint,
                        StageRunRow.checkpoint_json,
                        PipelineRunRow.id.label("run_id"),
                        PipelineRunRow.status.label("run_status"),
                        PipelineRunRow.config_json,
                        PipelineRunRow.config_fingerprint,
                        PipelineRunRow.cancellation_requested_at.label("run_cancel"),
                        ProjectRow.id.label("project_id"),
                        ProjectRow.source_request_path,
                        ProjectRow.current_generation,
                        ProjectRow.revision_epoch,
                    )
                    .join(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
                    .join(PipelineRunRow, PipelineRunRow.id == StageRunRow.pipeline_run_id)
                    .join(ProjectRow, ProjectRow.id == PipelineRunRow.project_id)
                    .where(
                        TaskRow.id == lease.task_id,
                        TaskRow.status == TaskStatus.RUNNING.value,
                        TaskRow.worker_id == lease.worker_id,
                        TaskRow.lease_token == lease.lease_token,
                        TaskRow.lease_expires_at > now,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise StageFenceLost("stage task lease is no longer valid")
            expected_generation = row["expected_generation"]
            if expected_generation is not None and int(expected_generation) != int(
                row["current_generation"]
            ):
                raise StageFenceLost("stage task belongs to an outdated project generation")
            stage_status = StageRunStatus(str(row["stage_status"]))
            run_status = PipelineRunStatus(str(row["run_status"]))
            already_succeeded = stage_status in {
                StageRunStatus.SUCCEEDED,
                StageRunStatus.SKIPPED,
            }
            if not already_succeeded:
                transition_stage_run(stage_status, StageRunStatus.RUNNING)
                connection.execute(
                    update(StageRunRow)
                    .where(StageRunRow.id == row["stage_run_id"])
                    .values(
                        status=StageRunStatus.RUNNING.value,
                        started_at=func.coalesce(StageRunRow.started_at, now),
                        updated_at=now,
                    )
                )
            if run_status == PipelineRunStatus.QUEUED:
                transition_pipeline_run(run_status, PipelineRunStatus.RUNNING)
                connection.execute(
                    update(PipelineRunRow)
                    .where(PipelineRunRow.id == row["run_id"])
                    .values(
                        status=PipelineRunStatus.RUNNING.value,
                        started_at=func.coalesce(PipelineRunRow.started_at, now),
                        updated_at=now,
                    )
                )
            elif run_status != PipelineRunStatus.RUNNING and not already_succeeded:
                raise PipelineConflict("stage cannot start for a terminal pipeline run")
            raw_checkpoint = row["checkpoint_json"]
            checkpoint = dict(raw_checkpoint) if isinstance(raw_checkpoint, dict) else None
            return StageWork(
                task_id=str(row["task_id"]),
                stage_run_id=str(row["stage_run_id"]),
                run_id=str(row["run_id"]),
                project_id=str(row["project_id"]),
                stage=PipelineStage(str(row["stage"])),
                source_path=Path(str(row["source_request_path"])),
                config=load_persisted_pipeline_config(
                    row["config_json"],
                    str(row["config_fingerprint"]),
                ),
                input_fingerprint=str(row["input_fingerprint"]),
                generation=int(row["current_generation"]),
                revision_epoch=int(row["revision_epoch"]),
                already_succeeded=already_succeeded,
                output_fingerprint=_optional_string(row["output_fingerprint"]),
                checkpoint=checkpoint,
                cancellation_requested=row["task_cancel"] is not None
                or row["run_cancel"] is not None,
            )

    def complete_stage(
        self,
        lease: LeaseIdentity,
        *,
        output_fingerprint: str,
        checkpoint: dict[str, object],
    ) -> bool:
        if not re.fullmatch(r"[a-f0-9]{64}", output_fingerprint):
            raise ValueError("stage output fingerprint must be a lowercase SHA-256")
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    TaskRow.stage_run_id,
                    TaskRow.pipeline_run_id,
                    TaskRow.expected_generation,
                    StageRunRow.status,
                    StageRunRow.stage,
                    StageRunRow.ordinal,
                    StageRunRow.output_fingerprint,
                    PipelineRunRow.project_id,
                    PipelineRunRow.config_fingerprint,
                    PipelineRunRow.config_json,
                    ProjectRow.current_generation,
                )
                .join(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
                .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
                .join(ProjectRow, ProjectRow.id == PipelineRunRow.project_id)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    TaskRow.cancellation_requested_at.is_(None),
                    PipelineRunRow.cancellation_requested_at.is_(None),
                )
            ).one_or_none()
            if row is None:
                return False
            if row.expected_generation is not None and int(row.expected_generation) != int(
                row.current_generation
            ):
                return False
            checkpoint_assets = _validate_checkpoint_assets(
                connection,
                checkpoint=checkpoint,
                project_id=str(row.project_id),
                generation=int(row.current_generation),
            )
            _validate_stage_checkpoint(
                connection,
                stage=PipelineStage(str(row.stage)),
                checkpoint=checkpoint,
                assets=checkpoint_assets,
                project_id=str(row.project_id),
                pipeline_run_id=str(row.pipeline_run_id),
                stage_run_id=str(row.stage_run_id),
            )
            expected_output_fingerprint = stage_output_fingerprint(
                PipelineStage(str(row.stage)), checkpoint_assets.hashes
            )
            if output_fingerprint != expected_output_fingerprint:
                raise PipelineConflict(
                    "stage output fingerprint does not match its committed assets"
                )
            current_stage = StageRunStatus(str(row.status))
            if current_stage in {StageRunStatus.SUCCEEDED, StageRunStatus.SKIPPED}:
                if row.output_fingerprint != output_fingerprint:
                    raise PipelineConflict(
                        "succeeded stage fingerprint does not match recovery output"
                    )
            else:
                transition_stage_run(current_stage, StageRunStatus.SUCCEEDED)
                connection.execute(
                    update(StageRunRow)
                    .where(StageRunRow.id == row.stage_run_id)
                    .values(
                        status=StageRunStatus.SUCCEEDED.value,
                        output_fingerprint=output_fingerprint,
                        checkpoint_json=checkpoint,
                        progress=100,
                        failure_class=None,
                        error_code=None,
                        safe_error_message=None,
                        finished_at=now,
                        updated_at=now,
                    )
                )
            completed_task = connection.execute(
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
                    failure_class=None,
                    error_code=None,
                    safe_error_message=None,
                    completed_at=now,
                    updated_at=now,
                )
                .returning(TaskRow.id)
            ).scalar_one_or_none()
            if completed_task is None:
                raise StageFenceLost("stage completion lost its task lease")
            connection.execute(
                update(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
                .values(outcome=AttemptOutcome.SUCCEEDED.value, finished_at=now)
            )
            next_ordinal = int(row.ordinal) + 1
            run_config = load_persisted_pipeline_config(
                row.config_json,
                str(row.config_fingerprint),
            )
            import_complete = (
                run_config.run_scope == "import"
                and PipelineStage(str(row.stage)) == PipelineStage.INGEST
            )
            if import_complete:
                transition_stage_run(StageRunStatus.QUEUED, StageRunStatus.SKIPPED)
                connection.execute(
                    update(StageRunRow)
                    .where(
                        StageRunRow.pipeline_run_id == row.pipeline_run_id,
                        StageRunRow.ordinal > int(row.ordinal),
                        StageRunRow.status == StageRunStatus.QUEUED.value,
                    )
                    .values(
                        status=StageRunStatus.SKIPPED.value,
                        progress=100,
                        finished_at=now,
                        updated_at=now,
                    )
                )
            elif next_ordinal < len(PIPELINE_STAGE_ORDER):
                next_stage = PIPELINE_STAGE_ORDER[next_ordinal]
                next_stage_id = connection.scalar(
                    select(StageRunRow.id).where(
                        StageRunRow.pipeline_run_id == row.pipeline_run_id,
                        StageRunRow.ordinal == next_ordinal,
                    )
                )
                if next_stage_id is None:
                    raise PipelineConflict("pipeline is missing its next stage")
                next_input_fingerprint = _next_stage_input_fingerprint(
                    output_fingerprint=output_fingerprint,
                    config_fingerprint=str(row.config_fingerprint),
                    stage=next_stage,
                )
                connection.execute(
                    update(StageRunRow)
                    .where(
                        StageRunRow.id == next_stage_id,
                        StageRunRow.status == StageRunStatus.QUEUED.value,
                    )
                    .values(input_fingerprint=next_input_fingerprint, updated_at=now)
                )
                existing_next_task = connection.scalar(
                    select(TaskRow.id).where(
                        TaskRow.operation_key
                        == f"run:{row.pipeline_run_id}:stage:{next_stage.value}"
                    )
                )
                if existing_next_task is None:
                    next_max_retries = connection.scalar(
                        select(StageRunRow.max_retries).where(StageRunRow.id == next_stage_id)
                    )
                    assert isinstance(next_max_retries, int)
                    connection.execute(
                        insert(TaskRow).values(
                            id=new_id(),
                            kind=TaskKind.STAGE.value,
                            target_id=next_stage_id,
                            operation_key=(f"run:{row.pipeline_run_id}:stage:{next_stage.value}"),
                            input_fingerprint=next_input_fingerprint,
                            resource_class=ResourceClass.HEAVY.value,
                            pipeline_run_id=row.pipeline_run_id,
                            stage_run_id=next_stage_id,
                            depends_on_task_id=lease.task_id,
                            status=TaskStatus.QUEUED.value,
                            priority=1_000 - next_ordinal,
                            not_before=now,
                            expected_generation=row.expected_generation,
                            attempt_count=0,
                            retry_count=0,
                            manual_retry_count=0,
                            max_retries=next_max_retries,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            total_stages = connection.scalar(
                select(func.count())
                .select_from(StageRunRow)
                .where(StageRunRow.pipeline_run_id == row.pipeline_run_id)
            )
            finished_stages = connection.scalar(
                select(func.count())
                .select_from(StageRunRow)
                .where(
                    StageRunRow.pipeline_run_id == row.pipeline_run_id,
                    StageRunRow.status.in_(
                        [StageRunStatus.SUCCEEDED.value, StageRunStatus.SKIPPED.value]
                    ),
                )
            )
            assert isinstance(total_stages, int) and isinstance(finished_stages, int)
            progress = int(finished_stages * 100 / total_stages)
            run_values: dict[str, object] = {"progress": progress, "updated_at": now}
            if finished_stages == total_stages:
                run_values.update(
                    {
                        "status": PipelineRunStatus.COMPLETED.value,
                        "progress": 100,
                        "finished_at": now,
                    }
                )
            connection.execute(
                update(PipelineRunRow)
                .where(PipelineRunRow.id == row.pipeline_run_id)
                .values(**run_values)
            )
            return True

    def fail_stage(
        self,
        lease: LeaseIdentity,
        *,
        failure_class: FailureClass,
        error_code: str,
        safe_message: str,
        retry_delay_ms: int,
    ) -> TaskStatus | None:
        _validate_failure(error_code, safe_message, retry_delay_ms)
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(
                    TaskRow.stage_run_id,
                    TaskRow.pipeline_run_id,
                    TaskRow.retry_count,
                    TaskRow.max_retries,
                    TaskRow.cancellation_requested_at.label("task_cancel"),
                    PipelineRunRow.cancellation_requested_at.label("run_cancel"),
                )
                .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                )
            ).one_or_none()
            if row is None:
                return None
            if row.task_cancel is not None or row.run_cancel is not None:
                _cancel_owned_stage(
                    connection,
                    lease,
                    stage_run_id=str(row.stage_run_id),
                    pipeline_run_id=str(row.pipeline_run_id),
                    now=now,
                )
                return TaskStatus.CANCELLED
            retryable = failure_class == FailureClass.TRANSIENT and int(row.retry_count) < int(
                row.max_retries
            )
            target = TaskStatus.QUEUED if retryable else TaskStatus.FAILED
            _fail_owned_renders(
                connection,
                task_id=lease.task_id,
                error_code=error_code,
                safe_message=safe_message,
                now=now,
            )
            task_values: dict[str, object] = {
                "status": target.value,
                "worker_id": None,
                "lease_token": None,
                "heartbeat_at": None,
                "lease_expires_at": None,
                "failure_class": failure_class.value,
                "error_code": error_code,
                "safe_error_message": safe_message,
                "updated_at": now,
            }
            if retryable:
                task_values["retry_count"] = int(row.retry_count) + 1
                task_values["not_before"] = now + timedelta(milliseconds=retry_delay_ms)
            else:
                task_values["completed_at"] = now
            connection.execute(
                update(TaskRow).where(TaskRow.id == lease.task_id).values(**task_values)
            )
            connection.execute(
                update(TaskAttemptRow)
                .where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                    TaskAttemptRow.outcome == AttemptOutcome.RUNNING.value,
                )
                .values(
                    outcome=AttemptOutcome.FAILED.value,
                    finished_at=now,
                    failure_class=failure_class.value,
                    error_code=error_code,
                    safe_error_message=safe_message,
                )
            )
            stage_values: dict[str, object] = {
                "retry_count": int(row.retry_count) + (1 if retryable else 0),
                "failure_class": failure_class.value,
                "error_code": error_code,
                "safe_error_message": safe_message,
                "updated_at": now,
            }
            if not retryable:
                stage_values.update({"status": StageRunStatus.FAILED.value, "finished_at": now})
            connection.execute(
                update(StageRunRow).where(StageRunRow.id == row.stage_run_id).values(**stage_values)
            )
            if not retryable:
                connection.execute(
                    update(PipelineRunRow)
                    .where(PipelineRunRow.id == row.pipeline_run_id)
                    .values(
                        status=PipelineRunStatus.FAILED.value,
                        failure_class=failure_class.value,
                        error_code=error_code,
                        safe_error_message=safe_message,
                        finished_at=now,
                        updated_at=now,
                    )
                )
            return target

    def cancel_stage(self, lease: LeaseIdentity) -> bool:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            row = connection.execute(
                select(TaskRow.stage_run_id, TaskRow.pipeline_run_id)
                .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
                .where(
                    TaskRow.id == lease.task_id,
                    TaskRow.status == TaskStatus.RUNNING.value,
                    TaskRow.worker_id == lease.worker_id,
                    TaskRow.lease_token == lease.lease_token,
                    TaskRow.lease_expires_at > now,
                    or_(
                        TaskRow.cancellation_requested_at.is_not(None),
                        PipelineRunRow.cancellation_requested_at.is_not(None),
                    ),
                )
            ).one_or_none()
            if row is None:
                return False
            _cancel_owned_stage(
                connection,
                lease,
                stage_run_id=str(row.stage_run_id),
                pipeline_run_id=str(row.pipeline_run_id),
                now=now,
            )
            return True


def _cancel_owned_stage(
    connection: Connection,
    lease: LeaseIdentity,
    *,
    stage_run_id: str,
    pipeline_run_id: str,
    now: datetime,
) -> None:
    _fail_owned_renders(
        connection,
        task_id=lease.task_id,
        error_code="RENDER_CANCELLED",
        safe_message="The render stopped because its pipeline was cancelled",
        now=now,
    )
    connection.execute(
        update(TaskRow)
        .where(
            TaskRow.id == lease.task_id,
            TaskRow.status == TaskStatus.RUNNING.value,
            TaskRow.worker_id == lease.worker_id,
            TaskRow.lease_token == lease.lease_token,
        )
        .values(
            status=TaskStatus.CANCELLED.value,
            worker_id=None,
            lease_token=None,
            heartbeat_at=None,
            lease_expires_at=None,
            cancellation_requested_at=func.coalesce(TaskRow.cancellation_requested_at, now),
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
        .values(outcome=AttemptOutcome.CANCELLED.value, finished_at=now)
    )
    connection.execute(
        update(StageRunRow)
        .where(StageRunRow.id == stage_run_id)
        .values(
            status=StageRunStatus.CANCELLED.value,
            finished_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        update(PipelineRunRow)
        .where(PipelineRunRow.id == pipeline_run_id)
        .values(
            status=PipelineRunStatus.CANCELLED.value,
            cancellation_requested_at=func.coalesce(PipelineRunRow.cancellation_requested_at, now),
            finished_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        update(TaskRow)
        .where(
            TaskRow.pipeline_run_id == pipeline_run_id,
            TaskRow.status == TaskStatus.QUEUED.value,
        )
        .values(
            status=TaskStatus.CANCELLED.value,
            cancellation_requested_at=func.coalesce(TaskRow.cancellation_requested_at, now),
            completed_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        update(StageRunRow)
        .where(
            StageRunRow.pipeline_run_id == pipeline_run_id,
            StageRunRow.status == StageRunStatus.QUEUED.value,
        )
        .values(
            status=StageRunStatus.CANCELLED.value,
            finished_at=now,
            updated_at=now,
        )
    )


def _fail_owned_renders(
    connection: Connection,
    *,
    task_id: str,
    error_code: str,
    safe_message: str,
    now: datetime,
) -> None:
    transition_render(RenderStatus.RUNNING, RenderStatus.FAILED)
    connection.execute(
        update(RenderJobRow)
        .where(
            RenderJobRow.task_id == task_id,
            RenderJobRow.status == RenderStatus.RUNNING.value,
        )
        .values(
            status=RenderStatus.FAILED.value,
            error_code=error_code,
            safe_error_message=safe_message,
            updated_at=now,
        )
    )


def _current_clip_facts(
    connection: Connection, project_id: str, run_id: str
) -> tuple[tuple[ReviewStatus, ...], tuple[RenderStatus, ...], int]:
    candidates = connection.execute(
        select(CandidateClipRow.id, CandidateClipRow.current_revision).where(
            CandidateClipRow.project_id == project_id,
            CandidateClipRow.pipeline_run_id == run_id,
            CandidateClipRow.selected_for_review.is_(True),
        )
    ).all()
    reviews: list[ReviewStatus] = []
    renders: list[RenderStatus] = []
    approved_final_count = 0
    for candidate_id, current_revision in candidates:
        revision_id = connection.scalar(
            select(EditPlanRevisionRow.id).where(
                EditPlanRevisionRow.candidate_clip_id == candidate_id,
                EditPlanRevisionRow.revision == current_revision,
            )
        )
        if revision_id is None:
            reviews.append(ReviewStatus.PENDING_REVIEW)
            continue
        decision = connection.scalar(
            select(ReviewDecisionRow.status)
            .where(ReviewDecisionRow.edit_plan_revision_id == revision_id)
            .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
            .limit(1)
        )
        review_status = (
            ReviewStatus(str(decision)) if decision is not None else ReviewStatus.PENDING_REVIEW
        )
        reviews.append(review_status)
        current_renders = connection.execute(
            select(RenderJobRow.status, RenderJobRow.kind).where(
                RenderJobRow.candidate_clip_id == candidate_id,
                RenderJobRow.edit_plan_revision_id == revision_id,
            )
        ).all()
        renders.extend(RenderStatus(str(row[0])) for row in current_renders)
    if ReviewStatus.APPROVED in reviews:
        try:
            approved_final_count = len(load_eligible_delivery_set(connection, project_id).clips)
        except DeliverySetError:
            approved_final_count = 0
    return tuple(reviews), tuple(renders), approved_final_count


def _insert_pipeline_run(
    connection: Connection,
    *,
    project_id: str,
    run_id: str,
    generation: int,
    source_path: Path,
    config: PipelineRunConfig,
    max_stage_retries: int,
    now: datetime,
) -> None:
    connection.execute(
        insert(PipelineRunRow).values(
            id=run_id,
            project_id=project_id,
            generation=generation,
            status=PipelineRunStatus.QUEUED.value,
            config_json=config.model_dump(mode="json"),
            config_fingerprint=config.fingerprint,
            progress=0,
            manual_retry_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    for ordinal, stage in enumerate(PIPELINE_STAGE_ORDER):
        stage_id = new_id()
        stage_fingerprint = (
            _ingest_input_fingerprint(config.fingerprint, source_path)
            if stage == PipelineStage.INGEST
            else None
        )
        connection.execute(
            insert(StageRunRow).values(
                id=stage_id,
                pipeline_run_id=run_id,
                stage=stage.value,
                ordinal=ordinal,
                status=StageRunStatus.QUEUED.value,
                input_fingerprint=stage_fingerprint,
                progress=0,
                retry_count=0,
                max_retries=max_stage_retries,
                created_at=now,
                updated_at=now,
            )
        )
        if stage != PipelineStage.INGEST:
            continue
        connection.execute(
            insert(TaskRow).values(
                id=new_id(),
                kind=TaskKind.STAGE.value,
                target_id=stage_id,
                operation_key=f"run:{run_id}:stage:{stage.value}",
                input_fingerprint=stage_fingerprint,
                resource_class=ResourceClass.HEAVY.value,
                pipeline_run_id=run_id,
                stage_run_id=stage_id,
                depends_on_task_id=None,
                status=TaskStatus.QUEUED.value,
                priority=1_000,
                not_before=now,
                expected_generation=generation,
                attempt_count=0,
                retry_count=0,
                manual_retry_count=0,
                max_retries=max_stage_retries,
                created_at=now,
                updated_at=now,
            )
        )


def _ingest_input_fingerprint(config_fingerprint: str, source_path: Path) -> str:
    return hashlib.sha256(f"{config_fingerprint}\0{source_path}\0ingest-v1".encode()).hexdigest()


def _next_stage_input_fingerprint(
    *, output_fingerprint: str, config_fingerprint: str, stage: PipelineStage
) -> str:
    return hashlib.sha256(
        f"{output_fingerprint}\0{config_fingerprint}\0{stage.value}\0stage-v1".encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class _CheckpointAssets:
    ids: tuple[str, ...]
    hashes: tuple[str, ...]
    kinds: dict[str, str]


def _validate_checkpoint_assets(
    connection: Connection,
    *,
    checkpoint: dict[str, object],
    project_id: str,
    generation: int,
) -> _CheckpointAssets:
    raw_asset_ids = checkpoint.get("asset_ids")
    if (
        not isinstance(raw_asset_ids, list)
        or not raw_asset_ids
        or any(not isinstance(value, str) for value in raw_asset_ids)
    ):
        raise PipelineConflict("stage checkpoint must reference committed assets")
    asset_ids = tuple(dict.fromkeys(raw_asset_ids))
    if len(asset_ids) != len(raw_asset_ids):
        raise PipelineConflict("stage checkpoint contains duplicate assets")
    assets = connection.execute(
        select(AssetRow.id, AssetRow.sha256, AssetRow.kind).where(
            AssetRow.id.in_(asset_ids),
            AssetRow.project_id == project_id,
            AssetRow.generation == generation,
            AssetRow.status == AssetStatus.COMMITTED.value,
        )
    ).all()
    hashes_by_id = {str(asset_id): str(sha256) for asset_id, sha256, _kind in assets if sha256}
    if set(hashes_by_id) != set(asset_ids):
        raise PipelineConflict("stage checkpoint references missing or uncommitted assets")
    kinds = {str(asset_id): str(kind) for asset_id, _sha256, kind in assets}
    return _CheckpointAssets(
        ids=asset_ids,
        hashes=tuple(hashes_by_id[asset_id] for asset_id in asset_ids),
        kinds=kinds,
    )


def _validate_stage_checkpoint(
    connection: Connection,
    *,
    stage: PipelineStage,
    checkpoint: dict[str, object],
    assets: _CheckpointAssets,
    project_id: str,
    pipeline_run_id: str,
    stage_run_id: str,
) -> None:
    expected_keys = {
        PipelineStage.INGEST: {"asset_ids", "source_media_id"},
        PipelineStage.PREPROCESS: {"asset_ids", "chunk_count"},
        PipelineStage.TRANSCRIBE: {"asset_ids", "transcript_id", "segment_count"},
        PipelineStage.CANDIDATES: {"asset_ids", "candidate_count"},
        PipelineStage.EDIT: {"asset_ids", "clip_ids", "selected_count"},
        PipelineStage.PROXY_RENDER: {"asset_ids", "render_ids", "proxy_count"},
    }[stage]
    if set(checkpoint) != expected_keys:
        raise PipelineConflict(f"{stage.value} checkpoint fields are invalid")
    kind_counts: dict[str, int] = {}
    for kind in assets.kinds.values():
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    if stage == PipelineStage.INGEST:
        _require_asset_kinds(kind_counts, {"source_metadata": 1}, stage)
        source_media_id = _checkpoint_id(checkpoint, "source_media_id")
        exists = connection.scalar(
            select(SourceMediaRow.id).where(
                SourceMediaRow.id == source_media_id,
                SourceMediaRow.project_id == project_id,
            )
        )
        if exists is None:
            raise PipelineConflict("ingest checkpoint does not reference persisted source media")
        return

    if stage == PipelineStage.PREPROCESS:
        chunk_count = _checkpoint_count(checkpoint, "chunk_count")
        expected_kinds = {"audio_manifest": 1, "audio_chunk": chunk_count}
        _require_asset_kinds(kind_counts, expected_kinds, stage)
        chunk_asset_ids = set(
            connection.scalars(
                select(AudioChunkRow.asset_id).where(
                    AudioChunkRow.pipeline_run_id == pipeline_run_id,
                    AudioChunkRow.stage_run_id == stage_run_id,
                )
            )
        )
        checkpoint_chunk_ids = {
            asset_id for asset_id, kind in assets.kinds.items() if kind == "audio_chunk"
        }
        if len(chunk_asset_ids) != chunk_count or chunk_asset_ids != checkpoint_chunk_ids:
            raise PipelineConflict("preprocess checkpoint does not match persisted audio chunks")
        return

    if stage == PipelineStage.TRANSCRIBE:
        _require_asset_kinds(
            kind_counts,
            {"transcript_json": 1, "transcript_srt": 1},
            stage,
        )
        transcript_id = _checkpoint_id(checkpoint, "transcript_id")
        segment_count = _checkpoint_count(checkpoint, "segment_count")
        transcript = connection.execute(
            select(TranscriptRow.id, TranscriptRow.asset_id).where(
                TranscriptRow.id == transcript_id,
                TranscriptRow.pipeline_run_id == pipeline_run_id,
            )
        ).one_or_none()
        transcript_json_ids = {
            asset_id for asset_id, kind in assets.kinds.items() if kind == "transcript_json"
        }
        if transcript is None or str(transcript.asset_id) not in transcript_json_ids:
            raise PipelineConflict("transcribe checkpoint does not match its transcript asset")
        actual_segments = connection.scalar(
            select(func.count())
            .select_from(TranscriptSegmentRow)
            .where(TranscriptSegmentRow.transcript_id == transcript_id)
        )
        if actual_segments != segment_count:
            raise PipelineConflict("transcribe checkpoint segment count is inconsistent")
        audio_chunk_count = connection.scalar(
            select(func.count())
            .select_from(AudioChunkRow)
            .where(AudioChunkRow.pipeline_run_id == pipeline_run_id)
        )
        succeeded_chunk_count = connection.scalar(
            select(func.count())
            .select_from(AudioChunkRow)
            .where(
                AudioChunkRow.pipeline_run_id == pipeline_run_id,
                AudioChunkRow.provider_status == "succeeded",
            )
        )
        if not audio_chunk_count or succeeded_chunk_count != audio_chunk_count:
            raise PipelineConflict("transcribe checkpoint has incomplete audio chunk outcomes")
        return

    if stage == PipelineStage.CANDIDATES:
        _require_asset_kinds(kind_counts, {"rough_candidates": 1}, stage)
        candidate_count = _checkpoint_count(checkpoint, "candidate_count")
        actual_candidates = connection.scalar(
            select(func.count())
            .select_from(CandidateClipRow)
            .where(CandidateClipRow.pipeline_run_id == pipeline_run_id)
        )
        if actual_candidates != candidate_count:
            raise PipelineConflict("candidate checkpoint count is inconsistent")
        return

    if stage == PipelineStage.EDIT:
        _require_asset_kinds(kind_counts, {"edit_plans": 1}, stage)
        clip_ids = _checkpoint_ids(checkpoint, "clip_ids")
        selected_count = _checkpoint_count(checkpoint, "selected_count")
        if len(clip_ids) != selected_count:
            raise PipelineConflict("edit checkpoint selected count is inconsistent")
        candidates = connection.execute(
            select(CandidateClipRow.id, CandidateClipRow.current_revision).where(
                CandidateClipRow.id.in_(clip_ids),
                CandidateClipRow.pipeline_run_id == pipeline_run_id,
                CandidateClipRow.selected_for_review.is_(True),
                CandidateClipRow.current_revision > 0,
            )
        ).all()
        if {str(row.id) for row in candidates} != set(clip_ids):
            raise PipelineConflict("edit checkpoint does not match selected candidates")
        for candidate in candidates:
            revision = connection.scalar(
                select(EditPlanRevisionRow.id).where(
                    EditPlanRevisionRow.candidate_clip_id == candidate.id,
                    EditPlanRevisionRow.revision == candidate.current_revision,
                )
            )
            if revision is None:
                raise PipelineConflict("edit checkpoint candidate has no current revision")
        return

    _require_proxy_checkpoint(
        connection,
        checkpoint=checkpoint,
        assets=assets,
        kind_counts=kind_counts,
        pipeline_run_id=pipeline_run_id,
    )


def _require_proxy_checkpoint(
    connection: Connection,
    *,
    checkpoint: dict[str, object],
    assets: _CheckpointAssets,
    kind_counts: dict[str, int],
    pipeline_run_id: str,
) -> None:
    render_ids = _checkpoint_ids(checkpoint, "render_ids")
    proxy_count = _checkpoint_count(checkpoint, "proxy_count")
    if len(render_ids) != proxy_count:
        raise PipelineConflict("proxy checkpoint count is inconsistent")
    _require_asset_kinds(
        kind_counts,
        {
            "review_proxy": proxy_count,
            "render_quality_report": proxy_count,
            "render_contact_sheet": proxy_count,
        },
        PipelineStage.PROXY_RENDER,
    )
    renders = connection.execute(
        select(
            RenderJobRow.id,
            RenderJobRow.asset_id,
            RenderJobRow.quality_report_asset_id,
            RenderJobRow.contact_sheet_asset_id,
        )
        .join(CandidateClipRow, CandidateClipRow.id == RenderJobRow.candidate_clip_id)
        .where(
            RenderJobRow.id.in_(render_ids),
            RenderJobRow.kind == "proxy",
            RenderJobRow.status == RenderStatus.SUCCEEDED.value,
            CandidateClipRow.pipeline_run_id == pipeline_run_id,
            CandidateClipRow.selected_for_review.is_(True),
            RenderJobRow.edit_plan_revision == CandidateClipRow.current_revision,
        )
    ).all()
    if {str(row.id) for row in renders} != set(render_ids):
        raise PipelineConflict("proxy checkpoint does not match current successful renders")
    render_asset_ids = {
        str(asset_id)
        for row in renders
        for asset_id in (row.asset_id, row.quality_report_asset_id, row.contact_sheet_asset_id)
        if asset_id is not None
    }
    if render_asset_ids != set(assets.ids):
        raise PipelineConflict("proxy checkpoint assets do not match persisted renders")


def _require_asset_kinds(
    actual: dict[str, int],
    expected: dict[str, int],
    stage: PipelineStage,
) -> None:
    if actual != expected:
        raise PipelineConflict(f"{stage.value} checkpoint asset kinds are inconsistent")


def _checkpoint_id(checkpoint: dict[str, object], key: str) -> str:
    value = checkpoint.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise PipelineConflict(f"stage checkpoint {key} is invalid")
    return value


def _checkpoint_ids(checkpoint: dict[str, object], key: str) -> tuple[str, ...]:
    raw = checkpoint.get(key)
    if not isinstance(raw, list) or not raw:
        raise PipelineConflict(f"stage checkpoint {key} is invalid")
    values = tuple(raw)
    if any(
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value) for value in values
    ):
        raise PipelineConflict(f"stage checkpoint {key} is invalid")
    if len(set(values)) != len(values):
        raise PipelineConflict(f"stage checkpoint {key} contains duplicates")
    return values


def _checkpoint_count(checkpoint: dict[str, object], key: str) -> int:
    value = checkpoint.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PipelineConflict(f"stage checkpoint {key} is invalid")
    return value


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _validate_failure(error_code: str, safe_message: str, retry_delay_ms: int) -> None:
    if not re.fullmatch(r"[A-Z0-9_]{1,80}", error_code):
        raise ValueError("error code is invalid")
    if (
        not safe_message
        or len(safe_message) > 500
        or any(character in safe_message for character in "\r\n")
    ):
        raise ValueError("safe error message is invalid")
    if retry_delay_ms < 0:
        raise ValueError("retry delay must be nonnegative")
