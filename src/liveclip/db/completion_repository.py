"""Durable goal identity and process-only effects in short SQLite transactions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping

from liveclip.application.completion import (
    CompletionCheckpointClip,
    CompletionConflict,
    CompletionOptions,
    CompletionResourceNotFound,
    CompletionSelectionCheckpoint,
    CompletionSelectionSubmission,
    CompletionSnapshot,
)
from liveclip.application.completion_runner import PROCESSING_WAIT_MS, ReconciliationResult
from liveclip.application.deliveries import DeliveryRequest
from liveclip.application.delivery_progress import (
    DeliveryProgressPhase,
    DeliveryProgressSnapshot,
    DeliveryProgressUnit,
)
from liveclip.application.idempotency import (
    IdempotencyConflict,
    IdempotencyContext,
    build_idempotency_context,
)
from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.pipeline import PipelineRunConfig
from liveclip.application.reviewing import ReviewCommand, ReviewConflict, ReviewResourceNotFound
from liveclip.application.tasks import TaskLease
from liveclip.config.settings import get_settings
from liveclip.db.base import new_id
from liveclip.db.current_project_authority import (
    CurrentProjectAccessDenied,
    CurrentProjectRunChanged,
    require_current_project_action,
)
from liveclip.db.delivery_repository import (
    DeliveryInspectionRequired,
    DeliveryInspectionStopped,
    SqlAlchemyDeliveryRepository,
    current_delivery_progress_authority,
)
from liveclip.db.delivery_snapshot import DeliverySetError, load_eligible_delivery_set
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    CandidateClipRow,
    CompletionIntentRow,
    DeliveryProgressRow,
    DeliveryRow,
    PipelineRunRow,
    RenderJobRow,
    ReviewDecisionRow,
    TaskRow,
)
from liveclip.db.pipeline_repository import insert_project_and_run
from liveclip.db.review_repository import (
    invalidate_review_effects_on_connection,
    load_current_review_context,
    record_review_decision_on_connection,
)
from liveclip.db.task_queue import (
    SQLiteTaskQueue,
    cancel_completion_task,
    finish_completion_attempt,
    insert_completion_task,
    owns_completion_lease,
    wake_completion_task,
)
from liveclip.domain.completion import (
    CompletionIntentStatus,
    CompletionOutcome,
    CompletionSelectionPolicy,
    CompletionTarget,
)
from liveclip.domain.state_transitions import ResourceClass, ReviewStatus, TaskKind, TaskStatus
from liveclip.renderer.contracts import has_current_manual_render_contract, is_clean_delivery_master

_BLOCKERS = {
    "SELECTION_CHANGED": "The saved selection changed; create a new goal for a new selection.",
    "MASTER_MISSING": "A selected clip has no master; explicitly render its saved revision.",
    "MASTER_STALE": "A selected master is stale or invalid; explicitly recover its saved revision.",
    "MASTER_FAILED": "A selected master failed; explicit bounded render recovery is required.",
    "MASTER_FAILED_EXHAUSTED": "A selected master exhausted its render retry allowance.",
    "DELIVERY_FAILED": "The bound package failed; explicit delivery recovery is required.",
    "DELIVERY_BINDING_INVALID": "The saved delivery binding is inconsistent; inspect its history.",
    "DELIVERY_ARTIFACTS_INVALID": "Configure the artifact root and inspect the package hashes.",
    "PROCESSING_FAILED": "Processing failed; recover the bound run before resuming.",
    "PROCESSING_CANCELLED": "Processing was cancelled; explicit processing recovery is required.",
    "GENERATION_CHANGED": "The project has advanced beyond this goal's bound run.",
    "AUTHORIZATION_REQUIRED": "Current project action permission is required.",
    "COORDINATION_RETRIES_EXHAUSTED": (
        "Coordination lease recovery is exhausted; history is retained."
    ),
}
_TERMINAL = {CompletionIntentStatus.SUCCEEDED.value, CompletionIntentStatus.CANCELLED.value}
SELECTION_WAIT_MS = 60_000


class _LostCompletionLease(RuntimeError):
    """Abort the whole effect transaction before translating to LOST_LEASE."""


def _instant(now: datetime | None) -> datetime:
    value = now if now is not None else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("completion time must be timezone aware")
    return value.astimezone(UTC)


def _canonical(
    context: IdempotencyContext,
    *,
    actor: str,
    operation: str,
    payload: object,
) -> IdempotencyContext:
    # Never trust a supplied request hash as proof of the actual method arguments.
    encoded = json.dumps(
        {
            "context": context.model_dump(mode="json"),
            "actor": actor,
            "operation": operation,
            "arguments": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return context.model_copy(update={"request_hash": hashlib.sha256(encoded).hexdigest()})


def _load(connection: Connection, intent_id: str) -> RowMapping:
    row = (
        connection.execute(select(CompletionIntentRow).where(CompletionIntentRow.id == intent_id))
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CompletionResourceNotFound("completion goal is not accessible")
    return row


def _snapshot(row: RowMapping) -> CompletionSnapshot:
    try:
        options = CompletionOptions.model_validate_json(json.dumps(row["options_json"]))
    except (ValidationError, TypeError, ValueError):
        raise CompletionConflict("completion options identity is invalid") from None
    if options.target.value != row["target"] or (
        options.selection_policy.value != row["selection_policy"]
    ):
        raise CompletionConflict("completion options identity is invalid")
    code = row["blocking_code"] if row["blocking_code"] in _BLOCKERS else None
    return CompletionSnapshot(
        intent_id=row["id"],
        project_id=row["project_id"],
        run_id=row["pipeline_run_id"],
        generation=row["generation"],
        requester_user_id=row["requester_user_id"],
        actor_user_id=row["actor_user_id"],
        options=options,
        status=CompletionIntentStatus(row["status"]),
        version=row["version"],
        selection_submitted=row["selection_submitted"],
        delivery_id=row["delivery_id"],
        outcome=CompletionOutcome(row["outcome_code"]) if row["outcome_code"] else None,
        blocking_code=code,
        safe_error_message=_BLOCKERS.get(code) if code else None,
    )


def _delivery_progress(connection: Connection, row: RowMapping) -> DeliveryProgressSnapshot | None:
    if row["delivery_id"] is None:
        return None
    delivery = (
        connection.execute(
            select(DeliveryRow).where(
                DeliveryRow.id == row["delivery_id"],
                DeliveryRow.project_id == row["project_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if delivery is None:
        return None
    task = (
        connection.execute(
            select(TaskRow).where(
                TaskRow.id == delivery["task_id"],
                TaskRow.target_id == delivery["id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    phase = DeliveryProgressPhase.QUEUED
    if row["status"] == "cancelled" or (task is not None and task["status"] == "cancelled"):
        phase = DeliveryProgressPhase.CANCELLED
    elif delivery["status"] == "succeeded":
        phase = DeliveryProgressPhase.SUCCEEDED
    elif delivery["status"] == "failed" or (task is not None and task["status"] == "failed"):
        phase = DeliveryProgressPhase.FAILED
    empty = DeliveryProgressSnapshot(
        phase=phase,
        unit=None,
        completed=None,
        total=None,
        attempt_id=None,
        business_advanced_at=None,
        worker_heartbeat_at=None,
        lease_fresh=False,
    )
    if phase != DeliveryProgressPhase.QUEUED:
        return empty
    authority = current_delivery_progress_authority(
        connection,
        delivery["id"],
        now=datetime.now(UTC),
    )
    if authority is None:
        return empty
    _, task, attempt = authority
    event = (
        connection.execute(
            select(DeliveryProgressRow).where(
                DeliveryProgressRow.delivery_id == delivery["id"],
                DeliveryProgressRow.task_attempt_id == attempt["id"],
                DeliveryProgressRow.attempt_number == task["attempt_count"],
                DeliveryProgressRow.expected_generation == task["expected_generation"],
                DeliveryProgressRow.expected_revision_epoch == task["expected_revision_epoch"],
                DeliveryProgressRow.package_fingerprint == task["input_fingerprint"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if event is None:
        return empty.model_copy(
            update={
                "attempt_id": attempt["id"],
                "worker_heartbeat_at": task["heartbeat_at"],
                "lease_fresh": task["heartbeat_at"] is not None,
            }
        )
    return DeliveryProgressSnapshot(
        phase=DeliveryProgressPhase(event["phase"]),
        unit=DeliveryProgressUnit(event["unit"]),
        completed=event["completed"],
        total=event["total"],
        attempt_id=attempt["id"],
        business_advanced_at=event["business_advanced_at"],
        worker_heartbeat_at=task["heartbeat_at"],
        lease_fresh=task["heartbeat_at"] is not None,
    )


def _authority(
    connection: Connection,
    row: RowMapping,
    actor: str,
    *,
    read: bool = False,
) -> None:
    try:
        require_current_project_action(
            connection,
            project_id=row["project_id"],
            actor_user_id=actor,
            action="read" if read else "run_pipeline",
            expected_run_id=None if read else row["pipeline_run_id"],
            expected_generation=None if read else row["generation"],
        )
    except CurrentProjectAccessDenied as exc:
        raise CompletionResourceNotFound("completion goal is not accessible") from exc
    except CurrentProjectRunChanged as exc:
        raise CompletionConflict("completion goal generation changed") from exc
    if not read:
        _bound_run(connection, row)


def _bound_run(connection: Connection, row: RowMapping) -> RowMapping:
    run = (
        connection.execute(
            select(PipelineRunRow).where(
                PipelineRunRow.id == row["pipeline_run_id"],
                PipelineRunRow.project_id == row["project_id"],
                PipelineRunRow.generation == row["generation"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if run is None:
        raise CompletionConflict("completion run identity is invalid")
    return run


def _task(connection: Connection, row: RowMapping) -> RowMapping:
    tasks = (
        connection.execute(
            select(TaskRow).where(
                TaskRow.kind == TaskKind.COMPLETION.value,
                TaskRow.target_id == row["id"],
            )
        )
        .mappings()
        .all()
    )
    if len(tasks) != 1:
        raise CompletionConflict("completion task identity is invalid")
    task = tasks[0]
    if (
        task["pipeline_run_id"] != row["pipeline_run_id"]
        or task["expected_generation"] != row["generation"]
        or task["operation_key"] != f"completion:{row['id']}"
        or task["input_fingerprint"] != row["canonical_request_sha256"]
        or task["resource_class"] != ResourceClass.CHEAP.value
        or task["stage_run_id"] is not None
        or task["depends_on_task_id"] is not None
    ):
        raise CompletionConflict("completion task identity is invalid")
    return task


def _selection_action_key(row: RowMapping) -> str:
    return f"completion-selection:{row['id']}"


def _review_authority(connection: Connection, row: RowMapping, actor: str) -> None:
    try:
        require_current_project_action(
            connection,
            project_id=row["project_id"],
            actor_user_id=actor,
            action="review_clip",
            expected_run_id=row["pipeline_run_id"],
            expected_generation=row["generation"],
        )
    except CurrentProjectAccessDenied as exc:
        raise CompletionResourceNotFound("completion goal is not accessible") from exc
    except CurrentProjectRunChanged as exc:
        raise CompletionConflict("completion goal generation changed") from exc
    _bound_run(connection, row)


def _candidate_contexts(connection: Connection, row: RowMapping) -> tuple[RowMapping, ...]:
    ids = tuple(
        str(value)
        for value in connection.scalars(
            select(CandidateClipRow.id)
            .where(
                CandidateClipRow.project_id == row["project_id"],
                CandidateClipRow.pipeline_run_id == row["pipeline_run_id"],
                CandidateClipRow.selected_for_review.is_(True),
            )
            .order_by(CandidateClipRow.id)
        )
    )
    return tuple(load_current_review_context(connection, clip_id) for clip_id in ids)


def _latest_decision(connection: Connection, revision_id: str) -> RowMapping | None:
    return (
        connection.execute(
            select(ReviewDecisionRow)
            .where(ReviewDecisionRow.edit_plan_revision_id == revision_id)
            .order_by(ReviewDecisionRow.decided_at.desc(), ReviewDecisionRow.id.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )


def _load_checkpoint(row: RowMapping) -> CompletionSelectionCheckpoint | None:
    raw = row["selection_checkpoint_json"]
    if raw is None:
        return None
    try:
        checkpoint = CompletionSelectionCheckpoint.model_validate_json(json.dumps(raw))
    except (ValidationError, TypeError, ValueError):
        raise CompletionConflict("completion selection checkpoint is invalid") from None
    if (
        checkpoint.intent_id != row["id"]
        or checkpoint.run_id != row["pipeline_run_id"]
        or checkpoint.generation != row["generation"]
        or checkpoint.mode.value != row["selection_policy"]
        or checkpoint.action_key != _selection_action_key(row)
    ):
        raise CompletionConflict("completion selection checkpoint identity changed")
    return checkpoint


def _authenticate_checkpoint(
    connection: Connection, row: RowMapping
) -> CompletionSelectionCheckpoint:
    checkpoint = _load_checkpoint(row)
    if checkpoint is None:
        raise CompletionConflict("completion selection checkpoint is missing")
    for selected in checkpoint.selected:
        try:
            context = load_current_review_context(connection, selected.clip_id)
        except ReviewResourceNotFound as exc:
            raise CompletionConflict("completion selection checkpoint became stale") from exc
        latest = _latest_decision(connection, selected.edit_plan_revision_id)
        if (
            str(context["project_id"]) != row["project_id"]
            or str(context["run_id"]) != row["pipeline_run_id"]
            or str(context["revision_id"]) != selected.edit_plan_revision_id
            or int(context["current_revision"]) != selected.edit_plan_revision
            or latest is None
            or latest["id"] != selected.decision_id
            or latest["status"] != ReviewStatus.APPROVED.value
        ):
            raise CompletionConflict("completion selection checkpoint became stale")
    return checkpoint


def _create_checkpoint(
    connection: Connection,
    row: RowMapping,
    *,
    selected_revisions: dict[str, int] | None,
    instant: datetime,
) -> CompletionSelectionCheckpoint:
    if _load_checkpoint(row) is not None:
        return _authenticate_checkpoint(connection, row)
    contexts = _candidate_contexts(connection, row)
    known = {str(context["id"]): int(context["current_revision"]) for context in contexts}
    if selected_revisions is not None and not selected_revisions.keys() <= known.keys():
        raise CompletionConflict("manual selection contains an unknown clip ID")
    if selected_revisions is not None:
        for clip_id, revision in selected_revisions.items():
            if known.get(clip_id) != revision:
                raise CompletionConflict("manual selection revision changed")
    changed: list[str] = []
    for context in contexts:
        clip_id = str(context["id"])
        latest = _latest_decision(connection, str(context["revision_id"]))
        if selected_revisions is None:
            if latest is not None:
                continue
            status = ReviewStatus.APPROVED
        else:
            status = (
                ReviewStatus.APPROVED if clip_id in selected_revisions else ReviewStatus.REJECTED
            )
        command = ReviewCommand(
            expected_revision=int(context["current_revision"]),
            status=status,
            reason=None if status == ReviewStatus.APPROVED else "Not selected by the user",
        )
        if record_review_decision_on_connection(
            connection, context=context, command=command, decided_at=instant
        ):
            changed.append(clip_id)
    invalidate_review_effects_on_connection(
        connection,
        project_id=str(row["project_id"]),
        generation=int(row["generation"]),
        changed_clip_ids=tuple(changed),
        instant=instant,
    )
    selected: list[CompletionCheckpointClip] = []
    for context in contexts:
        latest = _latest_decision(connection, str(context["revision_id"]))
        if latest is not None and latest["status"] == ReviewStatus.APPROVED.value:
            selected.append(
                CompletionCheckpointClip(
                    clip_id=str(context["id"]),
                    edit_plan_revision_id=str(context["revision_id"]),
                    edit_plan_revision=int(context["current_revision"]),
                    decision_id=str(latest["id"]),
                )
            )
    try:
        if (
            selected_revisions is not None
            and {item.clip_id: item.edit_plan_revision for item in selected} != selected_revisions
        ):
            raise CompletionConflict("manual selection does not match current decisions")
        return CompletionSelectionCheckpoint(
            intent_id=str(row["id"]),
            run_id=str(row["pipeline_run_id"]),
            generation=int(row["generation"]),
            mode=CompletionSelectionPolicy(str(row["selection_policy"])),
            action_key=_selection_action_key(row),
            selected=tuple(selected),
        )
    except (ValidationError, ValueError):
        raise CompletionConflict("completion selection exceeds the checkpoint contract") from None


class SqlAlchemyCompletionRepository:
    def __init__(
        self,
        engine: Engine,
        *,
        data_dir: Path | None = None,
        delivery_max_retries: int | None = None,
    ) -> None:
        self._engine = engine
        self._data_dir = data_dir
        self._delivery_max_retries = (
            get_settings().max_stage_retries
            if delivery_max_retries is None
            else delivery_max_retries
        )
        if type(self._delivery_max_retries) is not int or not 0 <= self._delivery_max_retries <= 20:
            raise ValueError("delivery retry bound must be an integer between zero and twenty")

    @staticmethod
    def _replay(
        connection: Connection,
        context: IdempotencyContext,
        actor: str,
    ) -> CompletionSnapshot | None:
        row = (
            connection.execute(
                select(CompletionIntentRow).where(
                    CompletionIntentRow.requester_user_id == actor,
                    CompletionIntentRow.idempotency_key_sha256 == context.key_hash,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            if load_idempotent_resource(connection, context, resource_type="completion_intent"):
                raise CompletionConflict("completion identity is unavailable")
            return None
        _authority(connection, row, actor)
        if row["canonical_request_sha256"] != context.request_hash:
            raise CompletionConflict("completion key was used for a different request or scope")
        if (
            load_idempotent_resource(
                connection,
                context,
                resource_type="completion_intent",
            )
            != row["id"]
        ):
            raise CompletionConflict("completion request identity is invalid")
        _task(connection, row)
        return _snapshot(row)

    @staticmethod
    def _insert(
        connection: Connection,
        *,
        project_id: str,
        run_id: str,
        generation: int,
        actor: str,
        options: CompletionOptions,
        context: IdempotencyContext,
        now: datetime,
    ) -> CompletionSnapshot:
        intent_id = new_id()
        connection.execute(
            insert(CompletionIntentRow).values(
                id=intent_id,
                project_id=project_id,
                pipeline_run_id=run_id,
                generation=generation,
                requester_user_id=actor,
                actor_user_id=actor,
                target=options.target.value,
                selection_policy=options.selection_policy.value,
                options_schema_version=options.schema_version,
                options_json=options.model_dump(mode="json"),
                canonical_request_sha256=context.request_hash,
                idempotency_key_sha256=context.key_hash,
                status="queued",
                version=1,
                selection_submitted=False,
                created_at=now,
                updated_at=now,
            )
        )
        insert_completion_task(
            connection,
            intent_id=intent_id,
            run_id=run_id,
            generation=generation,
            fingerprint=context.request_hash,
            now=now,
        )
        record_idempotent_resource(
            connection,
            context,
            resource_type="completion_intent",
            resource_id=intent_id,
        )
        return _snapshot(_load(connection, intent_id))

    def create_for_existing_run(
        self,
        *,
        project_id: str,
        run_id: str,
        actor_user_id: str,
        options: CompletionOptions,
        idempotency: IdempotencyContext,
    ) -> CompletionSnapshot:
        context = _canonical(
            idempotency,
            actor=actor_user_id,
            operation="existing_run",
            payload={
                "project_id": project_id,
                "run_id": run_id,
                "options": options.model_dump(mode="json"),
            },
        )
        with begin_immediate(self._engine) as connection:
            replay = self._replay(connection, context, actor_user_id)
            if replay is not None:
                return replay
            # Check visibility before looking up run details.
            try:
                require_current_project_action(
                    connection,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    action="run_pipeline",
                    expected_run_id=run_id,
                )
            except CurrentProjectAccessDenied as exc:
                raise CompletionResourceNotFound("completion goal is not accessible") from exc
            except CurrentProjectRunChanged as exc:
                raise CompletionConflict("completion goal generation changed") from exc
            run = (
                connection.execute(
                    select(PipelineRunRow).where(
                        PipelineRunRow.id == run_id,
                        PipelineRunRow.project_id == project_id,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                raise CompletionConflict("completion run identity is invalid")
            require_current_project_action(
                connection,
                project_id=project_id,
                actor_user_id=actor_user_id,
                action="run_pipeline",
                expected_run_id=run_id,
                expected_generation=run["generation"],
            )
            return self._insert(
                connection,
                project_id=project_id,
                run_id=run_id,
                generation=run["generation"],
                actor=actor_user_id,
                options=options,
                context=context,
                now=_instant(None),
            )

    def create_project_and_run_with_goal(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        actor_user_id: str,
        options: CompletionOptions,
        idempotency: IdempotencyContext,
        fresh_source_guard: Callable[[Path], Path] | None = None,
    ) -> CompletionSnapshot:
        context = _canonical(
            idempotency,
            actor=actor_user_id,
            operation="new_project",
            payload={
                "source_path": str(source_path),
                "config": config.model_dump(mode="json"),
                "max_stage_retries": max_stage_retries,
                "options": options.model_dump(mode="json"),
            },
        )
        with begin_immediate(self._engine) as connection:
            replay = self._replay(connection, context, actor_user_id)
            if replay is not None:
                return replay
            validated_source = (
                fresh_source_guard(source_path) if fresh_source_guard is not None else source_path
            )
            now = _instant(None)
            project_id, run_id = new_id(), new_id()
            insert_project_and_run(
                connection,
                project_id=project_id,
                run_id=run_id,
                source_path=validated_source,
                config=config,
                max_stage_retries=max_stage_retries,
                owner_id=actor_user_id,
                now=now,
            )
            return self._insert(
                connection,
                project_id=project_id,
                run_id=run_id,
                generation=1,
                actor=actor_user_id,
                options=options,
                context=context,
                now=now,
            )

    def get(self, intent_id: str, *, actor_user_id: str) -> CompletionSnapshot:
        with self._engine.connect() as connection:
            row = _load(connection, intent_id)
            _authority(connection, row, actor_user_id, read=True)
            return self._observe(connection, row)

    def list_for_project(
        self, project_id: str, *, actor_user_id: str
    ) -> tuple[CompletionSnapshot, ...]:
        with self._engine.connect() as connection:
            try:
                require_current_project_action(
                    connection,
                    project_id=project_id,
                    actor_user_id=actor_user_id,
                    action="read",
                )
            except CurrentProjectAccessDenied as exc:
                raise CompletionResourceNotFound("completion goal is not accessible") from exc
            rows = connection.execute(
                select(CompletionIntentRow)
                .where(CompletionIntentRow.project_id == project_id)
                .order_by(CompletionIntentRow.id)
            ).mappings()
            return tuple(self._observe(connection, row) for row in rows)

    @staticmethod
    def _observe(connection: Connection, row: RowMapping) -> CompletionSnapshot:
        snapshot = _snapshot(row)
        snapshot = snapshot.model_copy(
            update={"delivery_progress": _delivery_progress(connection, row)}
        )
        task = _task(connection, row)
        if row["status"] not in _TERMINAL and task["status"] == TaskStatus.FAILED.value:
            # Read-only projection: observation never resets exhausted recovery.
            return snapshot.model_copy(
                update={
                    "status": CompletionIntentStatus.NEEDS_ACTION,
                    "blocking_code": "COORDINATION_RETRIES_EXHAUSTED",
                    "safe_error_message": _BLOCKERS["COORDINATION_RETRIES_EXHAUSTED"],
                }
            )
        return snapshot

    def resume(
        self,
        intent_id: str,
        *,
        actor_user_id: str,
        expected_version: int,
    ) -> CompletionSnapshot:
        with begin_immediate(self._engine) as connection:
            row = _load(connection, intent_id)
            _authority(connection, row, actor_user_id)
            self._version(row, expected_version)
            task = _task(connection, row)
            if task["status"] == TaskStatus.FAILED.value:
                raise CompletionConflict(_BLOCKERS["COORDINATION_RETRIES_EXHAUSTED"])
            parked = row["status"] in {"needs_action", "waiting_selection"}
            ongoing = row["status"] in {"queued", "waiting_work"}
            if task["cancellation_requested_at"] is not None or not (parked or ongoing):
                raise CompletionConflict("completion goal cannot resume")
            if (parked and task["status"] != TaskStatus.WAITING.value) or (
                ongoing
                and task["status"] not in {TaskStatus.QUEUED.value, TaskStatus.RUNNING.value}
            ):
                raise CompletionConflict("coordination state is inconsistent")
            now = _instant(None)
            # Adoption changes future authority, never the current owner's lease,
            # scheduled poll, or accumulated recovery history.
            if parked and not wake_completion_task(connection, task["id"], now=now):
                raise CompletionConflict("coordination is not waiting; retry history is preserved")
            self._update(
                connection,
                row,
                now=now,
                status="queued" if parked else row["status"],
                actor_user_id=actor_user_id,
                blocking_code=None,
                safe_error_message=None,
            )
            return _snapshot(_load(connection, intent_id))

    def cancel(
        self,
        intent_id: str,
        *,
        actor_user_id: str,
        expected_version: int,
    ) -> CompletionSnapshot:
        with begin_immediate(self._engine) as connection:
            row = _load(connection, intent_id)
            _authority(connection, row, actor_user_id)
            self._version(row, expected_version)
            if row["status"] in _TERMINAL:
                raise CompletionConflict("terminal completion goals cannot change")
            task = _task(connection, row)
            now = _instant(None)
            cancel_completion_task(connection, task["id"], now=now)
            self._update(
                connection,
                row,
                now=now,
                status="cancelled",
                outcome_code="cancelled",
                cancellation_requested_at=now,
                completed_at=now,
                blocking_code=None,
                safe_error_message=None,
            )
            return _snapshot(_load(connection, intent_id))

    def submit_selection(
        self,
        intent_id: str,
        submission: CompletionSelectionSubmission,
        *,
        actor_user_id: str,
    ) -> CompletionSnapshot:
        with begin_immediate(self._engine) as connection:
            row = _load(connection, intent_id)
            _review_authority(connection, row, actor_user_id)
            if (
                row["target"] != CompletionTarget.DELIVERY.value
                or row["selection_policy"] != CompletionSelectionPolicy.MANUAL.value
            ):
                raise CompletionConflict("completion goal does not accept manual selection")
            task = _task(connection, row)
            if _bound_run(connection, row)["status"] != "completed":
                raise CompletionConflict("processing must complete before selection")
            existing = _load_checkpoint(row)
            supplied = {item.clip_id: item.expected_revision for item in submission.selected}
            action = build_idempotency_context(
                raw_key=_selection_action_key(row),
                caller_scope=f"completion:{intent_id}",
                operation_scope="completion:selection",
                request_payload={
                    "actor": actor_user_id,
                    "version": submission.expected_version,
                    "run": row["pipeline_run_id"],
                    "generation": row["generation"],
                    "selected": sorted(supplied.items()),
                },
            )
            try:
                replay = load_idempotent_resource(
                    connection, action, resource_type="completion_selection"
                )
            except IdempotencyConflict as exc:
                raise CompletionConflict("completion selection replay payload changed") from exc
            if existing is not None:
                expected = {item.clip_id: item.edit_plan_revision for item in existing.selected}
                if supplied != expected or not row["selection_submitted"] or replay != intent_id:
                    raise CompletionConflict("completion selection replay payload changed")
                _authenticate_checkpoint(connection, row)
                return _snapshot(row)
            if replay is not None:
                raise CompletionConflict("completion selection checkpoint is missing")
            self._version(row, submission.expected_version)
            run = _bound_run(connection, row)
            if run["status"] != "completed":
                raise CompletionConflict("processing must complete before selection")
            if row["status"] != "waiting_selection" or task["status"] != TaskStatus.WAITING.value:
                raise CompletionConflict("completion selection is not waiting for submission")
            instant = _instant(None)
            try:
                checkpoint = _create_checkpoint(
                    connection, row, selected_revisions=supplied, instant=instant
                )
            except (ReviewConflict, ReviewResourceNotFound) as exc:
                raise CompletionConflict("manual selection conflicts with current clips") from exc
            if not wake_completion_task(connection, task["id"], now=instant):
                raise CompletionConflict("completion selection task changed")
            self._update(
                connection,
                row,
                now=instant,
                status="queued",
                actor_user_id=actor_user_id,
                selection_submitted=True,
                selection_checkpoint_json=checkpoint.model_dump(mode="json"),
            )
            record_idempotent_resource(
                connection, action, resource_type="completion_selection", resource_id=intent_id
            )
            return _snapshot(_load(connection, intent_id))

    @staticmethod
    def _version(row: RowMapping, expected_version: int) -> None:
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
            or row["version"] != expected_version
        ):
            raise CompletionConflict("completion version changed")

    @staticmethod
    def _update(
        connection: Connection, row: RowMapping, *, now: datetime, **values: object
    ) -> None:
        changed = connection.scalar(
            update(CompletionIntentRow)
            .where(
                CompletionIntentRow.id == row["id"],
                CompletionIntentRow.version == row["version"],
            )
            .values(**values, version=row["version"] + 1, updated_at=now)
            .returning(CompletionIntentRow.id)
        )
        if changed is None:
            raise CompletionConflict("completion version changed")

    def reconcile_process_only(
        self,
        lease: TaskLease,
        *,
        now: datetime | None = None,
    ) -> ReconciliationResult:
        with begin_immediate(self._engine) as connection:
            # Read the clock after acquiring the writer lock, never before a possible wait.
            instant = _instant(now)
            try:
                row = _load(connection, lease.target_id)
                _snapshot(row)
                task = _task(connection, row)
                run = _bound_run(connection, row)
            except (CompletionConflict, CompletionResourceNotFound):
                return ReconciliationResult.LOST_LEASE
            if row["target"] != CompletionTarget.PROCESS_ONLY.value or task["id"] != lease.task_id:
                return ReconciliationResult.LOST_LEASE
            if row["status"] == "cancelled":
                if finish_completion_attempt(
                    connection,
                    lease,
                    now=instant,
                    status=TaskStatus.CANCELLED,
                ):
                    return ReconciliationResult.CANCELLED
                return ReconciliationResult.LOST_LEASE
            if row["status"] not in {"queued", "waiting_work"}:
                return ReconciliationResult.LOST_LEASE
            blocker = None
            try:
                _authority(connection, row, row["actor_user_id"])
            except CompletionResourceNotFound:
                blocker = "AUTHORIZATION_REQUIRED"
            except CompletionConflict:
                blocker = "GENERATION_CHANGED"
            if blocker is None:
                blocker = {
                    "failed": "PROCESSING_FAILED",
                    "cancelled": "PROCESSING_CANCELLED",
                }.get(run["status"])
            if blocker is not None:
                goal_status, task_status = "needs_action", TaskStatus.WAITING
                result = ReconciliationResult.NEEDS_ACTION
            elif run["status"] == "completed":
                goal_status, task_status = "succeeded", TaskStatus.SUCCEEDED
                result = ReconciliationResult.PROCESSED
            elif run["status"] in {"queued", "running"}:
                goal_status, task_status = "waiting_work", TaskStatus.QUEUED
                result = ReconciliationResult.DEFERRED
            else:
                return ReconciliationResult.LOST_LEASE
            if not finish_completion_attempt(
                connection,
                lease,
                now=instant,
                status=task_status,
                wait_ms=PROCESSING_WAIT_MS if task_status == TaskStatus.QUEUED else None,
            ):
                return ReconciliationResult.LOST_LEASE
            values: dict[str, object] = {
                "status": goal_status,
                "blocking_code": blocker,
                "safe_error_message": _BLOCKERS.get(blocker) if blocker else None,
            }
            if result == ReconciliationResult.PROCESSED:
                values.update(outcome_code="processed", completed_at=instant)
            self._update(connection, row, now=instant, **values)
            return result

    def reconcile_completion(
        self, lease: TaskLease, *, now: datetime | None = None
    ) -> ReconciliationResult:
        try:
            try:
                return self._reconcile_completion_transaction(lease, now=now)
            except DeliveryInspectionRequired as inspection:
                lease_seconds = max(
                    1, int((lease.lease_expires_at - lease.heartbeat_at).total_seconds())
                )
                queue = SQLiteTaskQueue(self._engine, lease_seconds=lease_seconds)
                monitor = LeaseMonitor(
                    heartbeat=lambda owned: queue.heartbeat(owned, now=_instant(now)),
                    observe=lambda owned: queue.observe(owned, now=_instant(now)),
                    lease=lease,
                    heartbeat_seconds=max(1, lease_seconds // 3),
                    cancellation_poll_seconds=min(1.0, lease_seconds / 3),
                    thread_name=f"liveclip-completion-inspection-{lease.task_id[:8]}",
                )
                monitor.start()
                try:
                    # Hash outside the SQLite writer lock. The second transaction
                    # rechecks live authority, lease, all DB inputs and held file identities.
                    inspection.cancel_requested = monitor.should_stop
                    monitor.refresh()
                    try:
                        inspection.check_cancel()
                        inspection.inspect()
                    except DeliveryInspectionStopped:
                        pass
                    monitor.refresh()
                    if monitor.lost_lease:
                        return ReconciliationResult.LOST_LEASE
                    return self._reconcile_completion_transaction(
                        lease, now=now, inspection=inspection
                    )
                finally:
                    monitor.stop()
                    inspection.close()
        except _LostCompletionLease:
            return ReconciliationResult.LOST_LEASE

    def _reconcile_completion_transaction(
        self,
        lease: TaskLease,
        *,
        now: datetime | None,
        inspection: DeliveryInspectionRequired | None = None,
    ) -> ReconciliationResult:
        with begin_immediate(self._engine) as connection:
            instant = _instant(now)
            try:
                row = _load(connection, lease.target_id)
                _snapshot(row)
                task = _task(connection, row)
                run = _bound_run(connection, row)
            except (CompletionConflict, CompletionResourceNotFound):
                return ReconciliationResult.LOST_LEASE
            if task["id"] != lease.task_id:
                return ReconciliationResult.LOST_LEASE
            return self._reconcile_loaded(
                connection, row, run, lease, instant, now=now, inspection=inspection
            )

    def _reconcile_loaded(
        self,
        connection: Connection,
        row: RowMapping,
        run: RowMapping,
        lease: TaskLease,
        instant: datetime,
        *,
        now: datetime | None,
        inspection: DeliveryInspectionRequired | None = None,
    ) -> ReconciliationResult:
        if row["status"] == "cancelled":
            return (
                ReconciliationResult.CANCELLED
                if finish_completion_attempt(
                    connection, lease, now=instant, status=TaskStatus.CANCELLED
                )
                else ReconciliationResult.LOST_LEASE
            )
        if row["status"] not in {"queued", "waiting_work"}:
            return ReconciliationResult.LOST_LEASE
        if not owns_completion_lease(connection, lease, now=instant):
            raise _LostCompletionLease
        if row["target"] == CompletionTarget.DELIVERY.value and (
            row["selection_checkpoint_json"] is not None
            or row["delivery_id"] is not None
            or row["delivery_action_key"] is not None
        ):
            return self._reconcile_delivery(
                connection, row, run, lease, now=now, inspection=inspection
            )
        blocker = None
        try:
            if row["target"] == CompletionTarget.DELIVERY.value:
                _review_authority(connection, row, row["actor_user_id"])
            else:
                _authority(connection, row, row["actor_user_id"])
        except CompletionResourceNotFound:
            blocker = "AUTHORIZATION_REQUIRED"
        except CompletionConflict:
            blocker = "GENERATION_CHANGED"
        if blocker is None:
            blocker = {"failed": "PROCESSING_FAILED", "cancelled": "PROCESSING_CANCELLED"}.get(
                run["status"]
            )
        if blocker is not None:
            status, task_status, result = (
                "needs_action",
                TaskStatus.WAITING,
                ReconciliationResult.NEEDS_ACTION,
            )
            checkpoint = None
        elif run["status"] in {"queued", "running"}:
            status, task_status, result = (
                "waiting_work",
                TaskStatus.QUEUED,
                ReconciliationResult.DEFERRED,
            )
            checkpoint = None
        elif run["status"] != "completed":
            return ReconciliationResult.LOST_LEASE
        elif row["target"] == CompletionTarget.PROCESS_ONLY.value:
            status, task_status, result = (
                "succeeded",
                TaskStatus.SUCCEEDED,
                ReconciliationResult.PROCESSED,
            )
            checkpoint = None
        else:
            # Authenticate saved selections even if live eligibility has since vanished.
            if row["selection_checkpoint_json"] is not None:
                _authenticate_checkpoint(connection, row)
            contexts = _candidate_contexts(connection, row)
            if not contexts and row["selection_checkpoint_json"] is None:
                status, task_status, result = (
                    "succeeded",
                    TaskStatus.SUCCEEDED,
                    ReconciliationResult.PROCESSED,
                )
                checkpoint = None
            elif (
                row["selection_policy"] == CompletionSelectionPolicy.MANUAL.value
                and not row["selection_submitted"]
            ):
                status, task_status, result = (
                    "waiting_selection",
                    TaskStatus.WAITING,
                    ReconciliationResult.NEEDS_ACTION,
                )
                checkpoint = None
            else:
                checkpoint = _load_checkpoint(row)
                if checkpoint is None:
                    checkpoint = _create_checkpoint(
                        connection, row, selected_revisions=None, instant=instant
                    )
                else:
                    checkpoint = _authenticate_checkpoint(connection, row)
                if checkpoint.selected:
                    status, task_status, result = (
                        "waiting_work",
                        TaskStatus.QUEUED,
                        ReconciliationResult.DEFERRED,
                    )
                else:
                    status, task_status, result = (
                        "succeeded",
                        TaskStatus.SUCCEEDED,
                        ReconciliationResult.PROCESSED,
                    )
        wait_ms = (
            SELECTION_WAIT_MS
            if checkpoint is not None and checkpoint.selected
            else PROCESSING_WAIT_MS
            if task_status == TaskStatus.QUEUED
            else None
        )
        # Production time is read again after selection work. Explicit test times
        # remain deterministic; no pre-lock or pre-effect clock grants authority.
        instant = _instant(now)
        if not finish_completion_attempt(
            connection, lease, now=instant, status=task_status, wait_ms=wait_ms
        ):
            raise _LostCompletionLease
        values: dict[str, object] = {
            "status": status,
            "blocking_code": blocker,
            "safe_error_message": _BLOCKERS.get(blocker) if blocker else None,
        }
        if checkpoint is not None and row["selection_checkpoint_json"] is None:
            values["selection_checkpoint_json"] = checkpoint.model_dump(mode="json")
        if status == "succeeded":
            values.update(
                outcome_code=(
                    "processed"
                    if row["target"] == CompletionTarget.PROCESS_ONLY.value
                    else "no_eligible_clips"
                    if checkpoint is None
                    else "no_selected_clips"
                ),
                completed_at=instant,
            )
        self._update(connection, row, now=instant, **values)
        return result

    def _reconcile_delivery(
        self,
        connection: Connection,
        row: RowMapping,
        run: RowMapping,
        lease: TaskLease,
        *,
        now: datetime | None,
        inspection: DeliveryInspectionRequired | None = None,
    ) -> ReconciliationResult:
        blocker = None
        delivered = False
        empty = False
        binding: dict[str, object] = {}
        try:
            require_current_project_action(
                connection,
                project_id=row["project_id"],
                actor_user_id=row["actor_user_id"],
                action="deliver",
                expected_run_id=row["pipeline_run_id"],
                expected_generation=row["generation"],
            )
        except CurrentProjectAccessDenied:
            blocker = "AUTHORIZATION_REQUIRED"
        except CurrentProjectRunChanged:
            blocker = "GENERATION_CHANGED"
        if blocker is None and run["status"] != "completed":
            blocker = "GENERATION_CHANGED"
        checkpoint = None
        if blocker is None:
            try:
                checkpoint = _authenticate_checkpoint(connection, row)
                selected = tuple(
                    CompletionCheckpointClip(
                        clip_id=str(context["id"]),
                        edit_plan_revision_id=str(context["revision_id"]),
                        edit_plan_revision=int(context["current_revision"]),
                        decision_id=str(decision["id"]),
                    )
                    for context in _candidate_contexts(connection, row)
                    if (decision := _latest_decision(connection, str(context["revision_id"])))
                    is not None
                    and decision["status"] == ReviewStatus.APPROVED.value
                )
                if checkpoint.selected != selected:
                    blocker = "SELECTION_CHANGED"
            except (CompletionConflict, ReviewConflict, ReviewResourceNotFound):
                blocker = "SELECTION_CHANGED"
        if blocker is None and checkpoint is not None:
            empty = not checkpoint.selected
            if empty and (row["delivery_id"] or row["delivery_action_key"]):
                blocker = "DELIVERY_BINDING_INVALID"
            elif not empty:
                try:
                    eligible = load_eligible_delivery_set(connection, row["project_id"])
                except DeliverySetError as exc:
                    blocker = _master_blocker(connection, row, checkpoint, failed_clip=exc.clip_id)
                else:
                    projection = tuple(
                        CompletionCheckpointClip(
                            clip_id=clip.clip_id,
                            edit_plan_revision_id=clip.edit_plan_revision_id,
                            edit_plan_revision=clip.edit_plan_revision,
                            decision_id=clip.decision_id,
                        )
                        for clip in sorted(eligible.clips, key=lambda clip: clip.clip_id)
                    )
                    if (
                        projection != checkpoint.selected
                        or eligible.run_id != row["pipeline_run_id"]
                        or eligible.generation != row["generation"]
                    ):
                        blocker = "SELECTION_CHANGED"
                    else:
                        key = f"completion-delivery:{row['id']}"
                        action = build_idempotency_context(
                            raw_key=key,
                            caller_scope=f"completion:{row['id']}",
                            operation_scope="completion:delivery",
                            request_payload={
                                "checkpoint": checkpoint.model_dump(mode="json"),
                                "options": row["options_json"],
                            },
                        )
                        repository = SqlAlchemyDeliveryRepository(self._engine)
                        replay = load_idempotent_resource(
                            connection, action, resource_type="delivery"
                        )
                        if row["delivery_id"] is not None:
                            if row["delivery_action_key"] != key or replay != row["delivery_id"]:
                                blocker = "DELIVERY_BINDING_INVALID"
                            else:
                                blocker, delivered = repository.observe_bound_delivery(
                                    connection,
                                    row["delivery_id"],
                                    eligible=eligible,
                                    include_zip=_snapshot(row).options.include_zip,
                                    data_dir=self._data_dir,
                                    inspection=inspection,
                                )
                        elif row["delivery_action_key"] is not None or replay is not None:
                            blocker = "DELIVERY_BINDING_INVALID"
                        else:
                            delivery = repository.enqueue_delivery_on_connection(
                                connection,
                                row["project_id"],
                                DeliveryRequest(include_zip=_snapshot(row).options.include_zip),
                                max_retries=self._delivery_max_retries,
                                idempotency=action,
                                now=_instant(now),
                            )
                            binding = {
                                "delivery_action_key": key,
                                "delivery_id": delivery.delivery_id,
                            }
        instant = _instant(now)
        task_status = (
            TaskStatus.WAITING
            if blocker
            else TaskStatus.SUCCEEDED
            if delivered or empty
            else TaskStatus.QUEUED
        )
        if not finish_completion_attempt(
            connection,
            lease,
            now=instant,
            status=task_status,
            wait_ms=SELECTION_WAIT_MS if task_status == TaskStatus.QUEUED else None,
        ):
            raise _LostCompletionLease
        values: dict[str, object] = {
            **binding,
            "status": "needs_action"
            if blocker
            else "succeeded"
            if delivered or empty
            else "waiting_work",
            "blocking_code": blocker,
            "safe_error_message": _BLOCKERS.get(blocker) if blocker else None,
        }
        if not blocker and (delivered or empty):
            values.update(
                outcome_code="delivered" if delivered else "no_selected_clips", completed_at=instant
            )
        self._update(connection, row, now=instant, **values)
        return (
            ReconciliationResult.NEEDS_ACTION
            if blocker
            else ReconciliationResult.PROCESSED
            if delivered or empty
            else ReconciliationResult.DEFERRED
        )


def _master_blocker(
    connection: Connection,
    row: RowMapping,
    checkpoint: CompletionSelectionCheckpoint,
    *,
    failed_clip: str | None,
) -> str | None:
    """Classify unavailable masters without submitting or retrying any render."""
    if failed_clip is None:
        return "MASTER_STALE"
    run = _bound_run(connection, row)
    waiting = False
    for selected in checkpoint.selected:
        try:
            eligible = load_eligible_delivery_set(
                connection, row["project_id"], clip_id=selected.clip_id
            )
        except DeliverySetError:
            pass
        else:
            if eligible.clips:
                continue
        renders = connection.execute(
            select(
                RenderJobRow.status,
                RenderJobRow.edit_plan_revision_id,
                RenderJobRow.edit_plan_revision,
                RenderJobRow.kind,
                RenderJobRow.spec_json,
                TaskRow.status.label("task_status"),
                TaskRow.retry_count,
                TaskRow.max_retries,
                TaskRow.expected_generation,
                TaskRow.pipeline_run_id,
                TaskRow.cancellation_requested_at,
            )
            .outerjoin(TaskRow, TaskRow.id == RenderJobRow.task_id)
            .where(RenderJobRow.candidate_clip_id == selected.clip_id)
            .order_by(RenderJobRow.created_at.desc(), RenderJobRow.id.desc())
        ).all()
        current = [r for r in renders if r.edit_plan_revision_id == selected.edit_plan_revision_id]
        if not current:
            return "MASTER_STALE" if renders else "MASTER_MISSING"
        compatible = [
            render
            for render in current
            if render.edit_plan_revision == selected.edit_plan_revision
            and (
                is_clean_delivery_master(spec=render.spec_json, pipeline_config=run["config_json"])
                if render.kind == "proxy"
                else render.kind == "final"
                and has_current_manual_render_contract("final", render.spec_json)
            )
        ]
        if any(
            render.status in {"queued", "running"}
            and render.task_status in {"queued", "running"}
            and render.expected_generation == row["generation"]
            and render.pipeline_run_id == row["pipeline_run_id"]
            and render.cancellation_requested_at is None
            for render in compatible
        ):
            waiting = True
            continue
        failed = next((render for render in compatible if render.status == "failed"), None)
        if failed is not None:
            return (
                "MASTER_FAILED_EXHAUSTED"
                if failed.retry_count is not None and failed.retry_count >= failed.max_retries
                else "MASTER_FAILED"
            )
        else:
            return "MASTER_STALE"
    return None if waiting else "MASTER_STALE"
