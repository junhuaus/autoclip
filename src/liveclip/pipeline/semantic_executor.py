"""Bound complete semantic units; only the caller thread can publish their evidence."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import suppress
from dataclasses import dataclass
from threading import Event
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.application.semantic_units import UnitDisposition
from liveclip.pipeline.semantic_transport import canonical_json
from liveclip.providers.llm.structured import (
    StructuredCallResult,
    StructuredLLMProvider,
    StructuredProviderError,
)
from liveclip.providers.telemetry import (
    ProviderCallRecord,
    ProviderCancelled,
    ProviderConfigurationError,
)

_GLOBAL_FAILURES = frozenset(
    {
        "OPENAI_AUTH",
        "OPENAI_QUOTA",
        "OPENAI_HTTP_400",
        "OPENAI_HTTP_404",
        "OPENAI_HTTP_422",
        "OPENAI_REQUEST",
        "CODEX_CLI_AUTH_FAILED",
        "CODEX_CLI_APP_SERVER_PERMISSION_DENIED",
        "CODEX_CLI_QUOTA_EXHAUSTED",
        "CODEX_CLI_MODEL_UNAVAILABLE",
        "CODEX_CLI_OUTPUT_SCHEMA_REJECTED",
        "PROVIDER_CONFIGURATION",
    }
)
_TRANSIENT_FAILURES = frozenset(
    {
        "PROVIDER_TIMEOUT",
        "STRUCTURED_PROVIDER_TIMEOUT",
        "OPENAI_TIMEOUT",
        "OPENAI_CONNECTION",
        "OPENAI_RATE_LIMIT",
        "OPENAI_SERVER",
        "OPENAI_HTTP_408",
        "OPENAI_HTTP_409",
        "CODEX_CLI_RATE_LIMITED",
        "CODEX_CLI_SERVICE_UNAVAILABLE",
        "CODEX_CLI_TIMEOUT",
    }
)


class SemanticEvidenceConflict(RuntimeError):
    """Call IDs must remain unambiguous; conflict never authorizes semantic repair."""


@dataclass(frozen=True, slots=True)
class SemanticUnitRequest:
    subject_id: str
    payload_json: str
    response_model: type[BaseModel]
    validate: Callable[[BaseModel], BaseModel]
    repair_payload: Callable[[dict[str, object], BaseModel, tuple[str, ...]], dict[str, object]]

    @classmethod
    def snapshot(
        cls,
        *,
        subject_id: str,
        payload: dict[str, object],
        response_model: type[BaseModel],
        validate: Callable[[BaseModel], BaseModel],
        repair_payload: Callable[
            [dict[str, object], BaseModel, tuple[str, ...]], dict[str, object]
        ],
    ) -> SemanticUnitRequest:
        # Snapshot before any worker starts, including caller-owned nested lists.
        return cls(subject_id, canonical_json(payload), response_model, validate, repair_payload)

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError("semantic unit request must be a JSON object")
        return value


class SemanticUnitOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["1"] = "1"
    disposition: UnitDisposition
    repair_spent: bool
    global_failure: bool = False
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")
    raw_output: dict[str, object] | None = None
    validated_output: dict[str, object] | None = None
    call_records: tuple[ProviderCallRecord, ...] = ()
    provider_attempts: tuple[dict[str, object], ...] = ()
    agent_outputs: tuple[dict[str, object], ...] = ()
    validation_events: tuple[dict[str, object], ...] = ()

    @model_validator(mode="after")
    def complete_outcome(self) -> SemanticUnitOutcome:
        if self.disposition == "succeeded":
            if (
                self.failure_code is not None
                or self.raw_output is None
                or self.validated_output is None
                or self.global_failure
            ):
                raise ValueError("semantic success requires complete validated output")
        elif self.failure_code is None or self.validated_output is not None:
            raise ValueError("semantic failure requires an explicit disposition")
        if self.disposition == "transient" and (self.repair_spent or self.global_failure):
            raise ValueError("semantic repair or global failure cannot replenish invocation budget")
        ids = [record.call_id for record in self.call_records]
        if len(ids) != len(set(ids)):
            raise ValueError("semantic outcome contains duplicate call evidence")
        return self


def execute_semantic_unit(
    request: SemanticUnitRequest,
    provider: StructuredLLMProvider,
    *,
    cancel_requested: Callable[[], bool],
) -> SemanticUnitOutcome:
    records: dict[str, ProviderCallRecord] = {}
    attempts: list[dict[str, object]] = []
    outputs: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    repair_spent = False
    raw: dict[str, object] | None = None

    def retain(calls: Sequence[ProviderCallRecord]) -> None:
        nonlocal repair_spent
        for record in calls:
            if record.call_id in records and records[record.call_id] != record:
                raise SemanticEvidenceConflict(
                    "semantic provider supplied conflicting call evidence"
                )
            records[record.call_id] = record
            repair_spent = repair_spent or record.operation.endswith(".repair")

    def failure(code: str, *, cancelled: bool = False) -> SemanticUnitOutcome:
        codes = {code, *(r.failure_code for r in records.values() if r.failure_code)}
        global_failure = bool(codes & _GLOBAL_FAILURES)
        transient = not repair_spent and not global_failure and bool(codes & _TRANSIENT_FAILURES)
        return SemanticUnitOutcome(
            disposition="cancelled" if cancelled else "transient" if transient else "exhausted",
            failure_code=code,
            repair_spent=repair_spent,
            global_failure=global_failure,
            raw_output=raw,
            call_records=tuple(records.values()),
            provider_attempts=tuple(attempts),
            agent_outputs=tuple(outputs),
            validation_events=tuple(events),
        )

    def received(result: StructuredCallResult[BaseModel], phase: str) -> BaseModel:
        nonlocal raw, repair_spent
        retain(result.call_records)
        repair_spent = repair_spent or result.repaired
        attempts.extend(result.repair_attempts)
        raw = result.output.model_dump(mode="json")
        outputs.append({"phase": phase, "repaired": result.repaired, "output": raw})
        # Domain validators cannot mutate the original model saved for sole repair.
        return request.validate(result.output.model_copy(deep=True))

    try:
        if cancel_requested():
            raise ProviderCancelled()
        result = provider.generate(
            subject_id=request.subject_id,
            payload=request.payload(),
            response_model=request.response_model,
            cancel_requested=cancel_requested,
        )
        try:
            validated = received(result, "initial_or_schema_repaired")
        except ValueError as exc:
            detail = str(exc)
            events.append({"phase": "initial", "error": detail})
            if repair_spent:
                return failure("STRUCTURED_OUTPUT_INVALID")
            if cancel_requested():
                raise ProviderCancelled() from exc
            # Reserve the sole semantic repair before calling the adapter. A failed
            # repair transport attempt never permits another initial request.
            repair_spent = True
            repaired = provider.repair(
                subject_id=request.subject_id,
                payload=request.repair_payload(
                    request.payload(), result.output.model_copy(deep=True), (detail,)
                ),
                response_model=request.response_model,
                validation_errors=(detail,),
                cancel_requested=cancel_requested,
            )
            try:
                validated = received(repaired, "domain_repair")
            except ValueError as repair_error:
                events.append({"phase": "repair", "error": str(repair_error)})
                return failure("STRUCTURED_OUTPUT_INVALID")
        return SemanticUnitOutcome(
            disposition="succeeded",
            repair_spent=repair_spent,
            raw_output=raw,
            validated_output=validated.model_dump(mode="json"),
            call_records=tuple(records.values()),
            provider_attempts=tuple(attempts),
            agent_outputs=tuple(outputs),
            validation_events=tuple(events),
        )
    except StructuredProviderError as exc:
        retain(exc.call_records)
        attempts.extend(exc.repair_attempts)
        repair_spent = (
            repair_spent
            or any(r.operation.endswith(".repair") for r in exc.call_records)
            or any(str(a.get("phase", "")).startswith("repair") for a in exc.repair_attempts)
        )
        return failure(exc.code)
    except ProviderCancelled as exc:
        retain(exc.call_records)
        return failure("PROVIDER_CANCELLED", cancelled=True)
    except ProviderConfigurationError:
        return failure("PROVIDER_CONFIGURATION")
    except Exception:
        # Preserve calls already returned by the provider even if a validator or
        # repair-payload builder fails unexpectedly. No untrusted exception text is
        # treated as configuration or as permission to make another provider call.
        return failure("SEMANTIC_UNIT_INTERNAL_ERROR")


def run_bounded_semantic_units(
    requests: Sequence[SemanticUnitRequest],
    *,
    provider: StructuredLLMProvider,
    concurrency: int,
    before_submit: Callable[[int, SemanticUnitRequest], None],
    on_complete: Callable[[int, SemanticUnitOutcome], None],
    on_abandoned: Callable[[int, SemanticUnitOutcome], None],
    cancel_requested: Callable[[], bool],
) -> None:
    """Admit at most K units and drain all owned work, even on owner failure.

    All callbacks run on the caller thread. Complete an entire observed batch before
    admission, so a success cannot conceal a simultaneous global failure. A callback
    failure stops publication; remaining results go only to historical call accounting.
    """
    if isinstance(concurrency, bool) or not 1 <= concurrency <= 32:
        raise ValueError("semantic concurrency must be between one and 32")
    units = tuple(requests)
    if len({unit.subject_id for unit in units}) != len(units):
        raise ValueError("semantic unit subjects must be unique within a batch")
    if not units:
        return
    stop = Event()
    pending: dict[Future[SemanticUnitOutcome], int] = {}
    next_index = 0
    owner_error: BaseException | None = None
    external_cancel = False

    def cancelled() -> bool:
        return stop.is_set() or cancel_requested()

    with ThreadPoolExecutor(
        max_workers=min(concurrency, len(units)), thread_name_prefix="semantic-unit"
    ) as executor:
        while next_index < len(units) or pending:
            try:
                external_cancel = external_cancel or cancel_requested()
                if external_cancel:
                    stop.set()
                while not stop.is_set() and next_index < len(units) and len(pending) < concurrency:
                    unit = units[next_index]
                    before_submit(next_index, unit)
                    pending[
                        executor.submit(
                            execute_semantic_unit, unit, provider, cancel_requested=cancelled
                        )
                    ] = next_index
                    next_index += 1
            except BaseException as exc:
                owner_error = owner_error or exc
                stop.set()
            if not pending:
                break
            done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
            if not done:
                continue
            completed: list[tuple[int, SemanticUnitOutcome]] = []
            # Inspect every result before callbacks and before any replacement.
            for future in sorted(done, key=lambda f: pending[f]):
                index = pending.pop(future)
                try:
                    outcome = future.result()
                except BaseException as exc:
                    owner_error = owner_error or exc
                    stop.set()
                    continue
                completed.append((index, outcome))
                if outcome.global_failure:
                    stop.set()
            for index, outcome in completed:
                callback = (
                    on_abandoned if owner_error is not None or external_cancel else on_complete
                )
                try:
                    callback(index, outcome)
                except BaseException as exc:
                    owner_error = owner_error or exc
                    stop.set()
                    # The failed completion may have executed calls before its fence
                    # expired. The evidence callback must use the historical fence.
                    with suppress(BaseException):
                        on_abandoned(index, outcome)
            if stop.is_set():
                # Already-running units observe cancellation through the shared flag.
                # Futures not yet entered still produce an explicit zero-call outcome.
                next_index = len(units)
    if owner_error is not None:
        raise owner_error
    if external_cancel:
        raise ProviderCancelled()
