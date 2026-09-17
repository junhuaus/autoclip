"""Fenced immutable invocation journal, independent of adoptable Asset metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine

from liveclip.application.pipeline import PipelineConfigInvalid, load_persisted_pipeline_config
from liveclip.application.semantic_units import (
    SemanticInvocation,
    SemanticInvocationOrigin,
    SemanticUnitConflict,
    SemanticUnitIdentity,
    UnitDisposition,
)
from liveclip.application.stage_execution import StageMutationFence
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AssetRow,
    PipelineRunRow,
    SemanticUnitInvocationRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.db.stage_store import _assert_mutation_fence
from liveclip.domain.semantic_validation import (
    CURRENT_SEMANTIC_EXECUTION,
    SEMANTIC_UNIT_MAX_INVOCATIONS,
)
from liveclip.domain.state_transitions import AssetStatus

Row = SemanticUnitInvocationRow


def _assert_context(connection: Connection, fence: StageMutationFence) -> None:
    _assert_mutation_fence(connection, fence)
    _assert_execution_config(connection, fence.run_id)


def _assert_execution_config(connection: Connection, run_id: str) -> None:
    row = connection.execute(
        select(PipelineRunRow.config_json, PipelineRunRow.config_fingerprint).where(
            PipelineRunRow.id == run_id
        )
    ).one_or_none()
    if row is None:
        raise SemanticUnitConflict("semantic invocation run is missing")
    try:
        config = load_persisted_pipeline_config(row.config_json, str(row.config_fingerprint))
    except PipelineConfigInvalid as exc:
        raise SemanticUnitConflict("semantic invocation execution config is invalid") from exc
    if getattr(config, "semantic_execution_contract", None) != CURRENT_SEMANTIC_EXECUTION:
        raise SemanticUnitConflict("semantic invocation execution config differs")


class SqlAlchemySemanticInvocationStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def load_origin_identity(
        self,
        fence: StageMutationFence,
        invocation: SemanticInvocation,
    ) -> SemanticInvocationOrigin:
        # Fence, exact journal row, immutable owner and origin are one SQLite
        # snapshot. No outcome bytes or requesting-work fingerprints supply authority.
        with self._engine.connect() as connection, connection.begin():
            _assert_context(connection, fence)
            try:
                invocation = SemanticInvocation.model_validate(invocation.model_dump())
            except ValueError as exc:
                raise SemanticUnitConflict("semantic invocation metadata is malformed") from exc
            row = (
                connection.execute(select(Row).where(Row.id == invocation.invocation_id))
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise SemanticUnitConflict("semantic invocation reservation is missing")
            saved = _validated(connection, dict(row))
            if saved != invocation:
                raise SemanticUnitConflict("semantic invocation differs from its saved row")
            if (
                saved.project_id != fence.project_id
                or saved.generation > fence.generation
                or (
                    saved.generation == fence.generation
                    and (saved.run_id, saved.stage_run_id) != (fence.run_id, fence.stage_run_id)
                )
            ):
                raise SemanticUnitConflict("semantic invocation origin is foreign")
            origin = connection.execute(
                select(PipelineRunRow.config_fingerprint, StageRunRow.input_fingerprint)
                .join(StageRunRow, StageRunRow.pipeline_run_id == PipelineRunRow.id)
                .where(
                    PipelineRunRow.id == saved.run_id,
                    PipelineRunRow.project_id == saved.project_id,
                    PipelineRunRow.generation == saved.generation,
                    StageRunRow.id == saved.stage_run_id,
                )
            ).one_or_none()
            if origin is None:
                raise SemanticUnitConflict("semantic invocation origin is missing")
            try:
                return SemanticInvocationOrigin(
                    invocation_id=saved.invocation_id,
                    project_id=saved.project_id,
                    run_id=saved.run_id,
                    stage_run_id=saved.stage_run_id,
                    generation=saved.generation,
                    config_fingerprint=origin.config_fingerprint,
                    stage_input_fingerprint=origin.input_fingerprint,
                )
            except ValueError as exc:
                raise SemanticUnitConflict("semantic invocation origin is malformed") from exc

    def load_history(
        self,
        fence: StageMutationFence,
        identity: SemanticUnitIdentity,
    ) -> tuple[SemanticInvocation, ...]:
        with self._engine.connect() as connection:
            _assert_context(connection, fence)
            return _history(connection, fence, identity)

    def load_prior_success_history(
        self,
        fence: StageMutationFence,
        identity: SemanticUnitIdentity,
    ) -> tuple[SemanticInvocation, ...]:
        with self._engine.connect() as connection:
            _assert_context(connection, fence)
            row = (
                connection.execute(
                    select(Row)
                    .where(
                        Row.project_id == fence.project_id,
                        Row.generation < fence.generation,
                        Row.semantic_stage == identity.semantic_stage,
                        Row.subject_id == identity.subject_id,
                        Row.request_key == identity.request_key,
                        Row.execution_contract == identity.execution_contract,
                        Row.disposition == "succeeded",
                    )
                    .order_by(Row.generation.desc(), Row.reserved_at.desc(), Row.id)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return ()
            success = _validated(connection, dict(row))
            history = _history(connection, fence, identity, origin=success)
            if not history or history[-1] != success:
                raise SemanticUnitConflict("prior success is not its unit's terminal invocation")
            return history

    def reserve(
        self,
        fence: StageMutationFence,
        identity: SemanticUnitIdentity,
        *,
        expected_history: tuple[str, ...],
    ) -> SemanticInvocation:
        # Validate direct callers too; dataclass/model construction is not a fence.
        identity = SemanticUnitIdentity.model_validate(identity.model_dump())
        with begin_immediate(self._engine) as connection:
            _assert_context(connection, fence)
            history = _history(connection, fence, identity)
            if tuple(row.invocation_id for row in history) != expected_history:
                raise SemanticUnitConflict("semantic invocation history changed before reservation")
            if history and (
                history[-1].disposition != "transient"
                or history[-1].repair_spent is not False
                or len(history) >= SEMANTIC_UNIT_MAX_INVOCATIONS
            ):
                raise SemanticUnitConflict("semantic invocation is uncertain or exhausted")
            attempt_id = connection.scalar(
                select(TaskAttemptRow.id).where(
                    TaskAttemptRow.task_id == fence.lease.task_id,
                    TaskAttemptRow.lease_token == fence.lease.lease_token,
                    TaskAttemptRow.worker_id == fence.lease.worker_id,
                )
            )
            if attempt_id is None:
                raise SemanticUnitConflict("semantic invocation owner is missing")
            invocation = SemanticInvocation(
                **identity.model_dump(),
                invocation_id=new_id(),
                project_id=fence.project_id,
                run_id=fence.run_id,
                stage_run_id=fence.stage_run_id,
                task_id=fence.lease.task_id,
                attempt_id=str(attempt_id),
                generation=fence.generation,
                invocation_number=len(history) + 1,
                reserved_at=datetime.now(UTC),
            )
            values = invocation.model_dump()
            values["id"] = values.pop("invocation_id")
            values["pipeline_run_id"] = values.pop("run_id")
            values["producer_attempt_id"] = values.pop("attempt_id")
            connection.execute(insert(Row).values(**values))
            return invocation

    def complete(
        self,
        fence: StageMutationFence,
        invocation: SemanticInvocation,
        *,
        outcome_asset_id: str,
        expected_sha256: str,
        expected_size_bytes: int,
        disposition: UnitDisposition,
        repair_spent: bool,
    ) -> SemanticInvocation:
        with begin_immediate(self._engine) as connection:
            _assert_context(connection, fence)
            row = (
                connection.execute(
                    select(Row).where(
                        Row.id == invocation.invocation_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise SemanticUnitConflict("semantic invocation reservation is missing")
            saved = _validated(connection, dict(row))
            if saved != invocation or saved.completed_at is not None:
                raise SemanticUnitConflict("semantic invocation completion is not append-only")
            owner = connection.scalar(
                select(TaskAttemptRow.id).where(
                    TaskAttemptRow.id == saved.attempt_id,
                    TaskAttemptRow.task_id == fence.lease.task_id,
                    TaskAttemptRow.lease_token == fence.lease.lease_token,
                    TaskAttemptRow.worker_id == fence.lease.worker_id,
                )
            )
            if owner is None or (
                saved.project_id,
                saved.run_id,
                saved.stage_run_id,
                saved.generation,
            ) != (
                fence.project_id,
                fence.run_id,
                fence.stage_run_id,
                fence.generation,
            ):
                raise SemanticUnitConflict("semantic invocation immutable owner differs")
            asset = (
                connection.execute(
                    select(AssetRow).where(
                        AssetRow.id == outcome_asset_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if asset is None:
                raise SemanticUnitConflict("semantic invocation outcome Asset is missing")
            completed = SemanticInvocation.model_validate(
                {
                    **saved.model_dump(),
                    "completed_at": datetime.now(UTC),
                    "disposition": disposition,
                    "repair_spent": repair_spent,
                    "outcome_asset_id": outcome_asset_id,
                    "outcome_sha256": expected_sha256,
                    "outcome_size_bytes": expected_size_bytes,
                    "outcome_relative_path": str(asset["relative_path"]),
                }
            )
            _check_asset(completed, dict(asset))
            connection.execute(
                update(Row)
                .where(
                    Row.id == saved.invocation_id,
                    Row.completed_at.is_(None),
                )
                .values(
                    completed_at=completed.completed_at,
                    disposition=disposition,
                    repair_spent=repair_spent,
                    outcome_asset_id=outcome_asset_id,
                    outcome_sha256=expected_sha256,
                    outcome_size_bytes=expected_size_bytes,
                    outcome_relative_path=completed.outcome_relative_path,
                )
            )
            return completed


def _history(
    connection: Connection,
    fence: StageMutationFence,
    identity: SemanticUnitIdentity,
    *,
    origin: SemanticInvocation | None = None,
) -> tuple[SemanticInvocation, ...]:
    project_id = origin.project_id if origin is not None else fence.project_id
    run_id = origin.run_id if origin is not None else fence.run_id
    stage_run_id = origin.stage_run_id if origin is not None else fence.stage_run_id
    generation = origin.generation if origin is not None else fence.generation
    rows = (
        connection.execute(
            select(Row)
            .where(
                Row.project_id == project_id,
                Row.pipeline_run_id == run_id,
                Row.stage_run_id == stage_run_id,
                Row.generation == generation,
                Row.semantic_stage == identity.semantic_stage,
                Row.subject_id == identity.subject_id,
                Row.request_key == identity.request_key,
                Row.execution_contract == identity.execution_contract,
            )
            .order_by(Row.invocation_number)
        )
        .mappings()
        .all()
    )
    values = tuple(_validated(connection, dict(row)) for row in rows)
    if tuple(row.invocation_number for row in values) != tuple(range(1, len(values) + 1)):
        raise SemanticUnitConflict("semantic invocation history is incomplete")
    if any(row.disposition != "transient" or row.repair_spent is not False for row in values[:-1]):
        raise SemanticUnitConflict("semantic invocation follows an exhausted or uncertain result")
    return values


def _validated(connection: Connection, values: dict[str, Any]) -> SemanticInvocation:
    values["invocation_id"] = values.pop("id")
    values["run_id"] = values.pop("pipeline_run_id")
    values["attempt_id"] = values.pop("producer_attempt_id")
    try:
        record = SemanticInvocation.model_validate(values)
    except ValueError as exc:
        raise SemanticUnitConflict("semantic invocation metadata is malformed") from exc
    _assert_execution_config(connection, record.run_id)
    owner = connection.execute(
        select(TaskAttemptRow.started_at, TaskAttemptRow.finished_at)
        .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
        .join(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
        .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
        .where(
            TaskAttemptRow.id == record.attempt_id,
            TaskRow.id == record.task_id,
            TaskRow.pipeline_run_id == record.run_id,
            TaskRow.stage_run_id == record.stage_run_id,
            TaskRow.expected_generation == record.generation,
            StageRunRow.pipeline_run_id == record.run_id,
            PipelineRunRow.project_id == record.project_id,
            PipelineRunRow.generation == record.generation,
        )
    ).one_or_none()
    if (
        owner is None
        or record.reserved_at < owner.started_at
        or (
            owner.finished_at is not None
            and (
                record.reserved_at > owner.finished_at
                or (record.completed_at is not None and record.completed_at > owner.finished_at)
            )
        )
    ):
        raise SemanticUnitConflict("semantic invocation attempt binding is invalid")
    if record.completed_at is not None:
        asset = (
            connection.execute(
                select(AssetRow).where(
                    AssetRow.id == record.outcome_asset_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if asset is None:
            raise SemanticUnitConflict("semantic invocation outcome Asset is missing")
        _check_asset(record, dict(asset))
    return record


def _check_asset(record: SemanticInvocation, asset: dict[str, Any]) -> None:
    expected_path = (
        f"runs/g{record.generation:03d}/semantic-units/"
        f"{record.attempt_id}/{record.invocation_id}.json"
    )
    expected = {
        "id": record.outcome_asset_id,
        "project_id": record.project_id,
        "producer_attempt_id": record.attempt_id,
        "generation": record.generation,
        "status": AssetStatus.COMMITTED.value,
        "kind": "semantic_unit_outcome",
        "input_fingerprint": record.request_key,
        "sha256": record.outcome_sha256,
        "size_bytes": record.outcome_size_bytes,
        "relative_path": expected_path,
        "mime_type": "application/json",
    }
    if record.outcome_relative_path != expected_path or any(
        asset[key] != value for key, value in expected.items()
    ):
        raise SemanticUnitConflict("semantic invocation outcome Asset binding differs")
