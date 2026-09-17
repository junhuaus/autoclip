from __future__ import annotations

from concurrent.futures import ALL_COMPLETED, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, get_ident
from uuid import uuid4

import pytest
from pydantic import BaseModel

from liveclip.pipeline import semantic_executor as module
from liveclip.pipeline.semantic_executor import (
    SemanticUnitRequest,
    execute_semantic_unit,
    run_bounded_semantic_units,
)
from liveclip.providers.llm.structured import StructuredCallResult, StructuredProviderError
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus, ProviderCancelled


class Answer(BaseModel):
    value: str


def record(subject, *, code=None, phase="initial"):
    return ProviderCallRecord(
        call_id=uuid4().hex,
        operation_key="a" * 64,
        subject_id=subject,
        provider="mock",
        operation=f"responses.semantic.discovery.{phase}",
        model="fixture",
        request_count=1,
        retry_count=0,
        latency_ms=1,
        status=ProviderCallStatus.FAILED if code else ProviderCallStatus.SUCCEEDED,
        failure_code=code,
        called_at=datetime.now(UTC),
    )


def result(subject, value="valid", *, repaired=False):
    return StructuredCallResult(
        output=Answer(value=value),
        call_records=(record(subject, phase="repair" if repaired else "initial"),),
        repaired=repaired,
    )


def validator(value):
    if value.value != "valid":
        raise ValueError("complete invalid authority " * 250)
    return value


def request(index=0, payload=None):
    return SemanticUnitRequest.snapshot(
        subject_id=f"subject.{index}",
        payload=payload or {"nested": ["original"]},
        response_model=Answer,
        validate=validator,
        repair_payload=lambda original, output, errors: {
            "original_request": original,
            "invalid_output": output.model_dump(),
            "errors": list(errors),
        },
    )


@pytest.mark.parametrize("same_batch", [False, True])
def test_28_requests_stop_at_k_on_global_failure_and_commit_entire_batch(monkeypatch, same_batch):
    started, reserved, persisted = [], [], []
    barrier = Barrier(3)
    failure_observed = Event()
    owner = get_ident()
    original_wait = module.wait
    if same_batch:
        monkeypatch.setattr(
            module, "wait", lambda futures, **_: original_wait(futures, return_when=ALL_COMPLETED)
        )

    class Provider:
        def generate(self, *, subject_id, **_):
            started.append(subject_id)
            assert get_ident() != owner
            barrier.wait(timeout=5)
            if subject_id == "subject.0":
                raise StructuredProviderError(
                    "PROVIDER_ERROR", (record(subject_id, code="OPENAI_AUTH"),)
                )
            if not same_batch:
                assert failure_observed.wait(5)
            return result(subject_id)

        def repair(self, **_):
            pytest.fail("authentication failure must not cause semantic repair")

    def save(index, outcome):
        assert get_ident() == owner
        persisted.append((index, outcome))
        if outcome.global_failure:
            failure_observed.set()

    run_bounded_semantic_units(
        tuple(request(i) for i in range(28)),
        provider=Provider(),
        concurrency=3,
        before_submit=lambda index, _: reserved.append(index),
        on_complete=save,
        on_abandoned=lambda *_: pytest.fail("no owner or external cancellation"),
        cancel_requested=lambda: False,
    )
    assert reserved == [0, 1, 2]
    assert set(started) == {"subject.0", "subject.1", "subject.2"}
    assert {i for i, _ in persisted} == {0, 1, 2}
    assert next(o for i, o in persisted if i == 0).global_failure
    assert sum(o.disposition == "succeeded" for _, o in persisted) == 2


def test_success_before_global_failure_allows_one_replacement_then_stops():
    initial = Barrier(3)
    replacement_reserved, failure_observed = Event(), Event()
    reserved, completed = [], []

    class Provider:
        def generate(self, *, subject_id, **_):
            index = int(subject_id.rsplit(".", 1)[-1])
            if index < 3:
                initial.wait(timeout=5)
            if index == 0:
                return result(subject_id)
            if index == 1:
                assert replacement_reserved.wait(5)
                raise StructuredProviderError(
                    "PROVIDER_ERROR", (record(subject_id, code="OPENAI_AUTH"),)
                )
            assert failure_observed.wait(5)
            return result(subject_id)

    def reserve(index, _):
        assert not failure_observed.is_set(), "replacement after observed permanent failure"
        reserved.append(index)
        if index == 3:
            replacement_reserved.set()

    def save(index, outcome):
        completed.append(index)
        if outcome.global_failure:
            failure_observed.set()

    run_bounded_semantic_units(
        tuple(request(i) for i in range(28)),
        provider=Provider(),
        concurrency=3,
        before_submit=reserve,
        on_complete=save,
        on_abandoned=lambda *_: pytest.fail("no external cancellation or owner error"),
        cancel_requested=lambda: False,
    )
    assert reserved == [0, 1, 2, 3]
    assert completed[0] == 0 and set(completed) == {0, 1, 2, 3}
    assert failure_observed.is_set()


def test_slow_repair_does_not_block_sibling_persistence_and_keeps_full_authority():
    repairing, release, saved = Event(), Event(), Event()
    seen = []

    class Provider:
        def generate(self, *, subject_id, **_):
            if subject_id == "subject.0":
                return result(subject_id, "invalid")
            assert repairing.wait(5)
            return result(subject_id)

        def repair(self, *, subject_id, payload, validation_errors, **_):
            seen.append(payload)
            assert len(validation_errors[0]) > 6000
            repairing.set()
            assert release.wait(5)
            return result(subject_id, repaired=True)

    completed = {}

    def persist(index, outcome):
        completed[index] = outcome
        if index == 1:
            saved.set()

    payload = {"nested": ["original"]}
    units = (request(0, payload), request(1))
    payload["nested"][0] = "caller changed after snapshot"
    with ThreadPoolExecutor(max_workers=1) as owner:
        future = owner.submit(
            run_bounded_semantic_units,
            units,
            provider=Provider(),
            concurrency=2,
            before_submit=lambda *_: None,
            on_complete=persist,
            on_abandoned=lambda *_: None,
            cancel_requested=lambda: False,
        )
        try:
            assert saved.wait(5), "successful sibling was blocked by another unit's repair"
            assert 0 not in completed and completed[1].disposition == "succeeded"
            assert seen[0]["original_request"] == {"nested": ["original"]}
        finally:
            release.set()
        future.result(timeout=5)
    assert completed[0].repair_spent and len(completed[0].call_records) == 2
    assert len(completed[0].agent_outputs) == 2
    assert len(completed[0].validation_events[0]["error"]) > 6000


def test_owner_failure_stops_new_admission_but_drains_real_call_evidence():
    release, entered = Event(), Event()
    saved, abandoned, started = [], [], []

    class Provider:
        def generate(self, *, subject_id, **_):
            started.append(subject_id)
            if subject_id == "subject.1":
                entered.set()
                assert release.wait(5)
            else:
                assert entered.wait(5)
            return result(subject_id)

    def failed_save(index, outcome):
        saved.append(index)
        release.set()
        raise RuntimeError("lease lost")

    with pytest.raises(RuntimeError, match="lease lost"):
        run_bounded_semantic_units(
            tuple(request(i) for i in range(28)),
            provider=Provider(),
            concurrency=2,
            before_submit=lambda *_: None,
            on_complete=failed_save,
            on_abandoned=lambda i, outcome: abandoned.extend(outcome.call_records),
            cancel_requested=lambda: False,
        )
    assert saved == [0]
    assert set(started) == {"subject.0", "subject.1"}
    assert {r.subject_id for r in abandoned} == set(started)


@pytest.mark.parametrize("schema_repaired,repair_error", [(True, False), (False, True)])
def test_spent_repair_is_never_transient_or_repeated(schema_repaired, repair_error):
    repairs = []

    class Provider:
        def generate(self, *, subject_id, **_):
            return result(subject_id, "invalid", repaired=schema_repaired)

        def repair(self, *, subject_id, **_):
            repairs.append(subject_id)
            raise StructuredProviderError(
                "PROVIDER_TIMEOUT", (record(subject_id, code="OPENAI_TIMEOUT", phase="repair"),)
            )

    outcome = execute_semantic_unit(request(), Provider(), cancel_requested=lambda: False)
    assert outcome.disposition == "exhausted" and outcome.repair_spent
    assert len(repairs) == int(repair_error)
    assert len(outcome.call_records) == (2 if repair_error else 1)


def test_unexpected_validator_error_retains_executed_call_and_does_not_repair():
    class Provider:
        def generate(self, *, subject_id, **_):
            return result(subject_id)

        def repair(self, **_):
            pytest.fail("unexpected local failure must not spend a semantic repair")

    unit = request()
    unit = SemanticUnitRequest(
        unit.subject_id,
        unit.payload_json,
        unit.response_model,
        lambda _: (_ for _ in ()).throw(RuntimeError("untrusted error")),
        unit.repair_payload,
    )
    outcome = execute_semantic_unit(unit, Provider(), cancel_requested=lambda: False)
    assert outcome.failure_code == "SEMANTIC_UNIT_INTERNAL_ERROR"
    assert len(outcome.call_records) == 1 and not outcome.repair_spent
    assert "untrusted error" not in outcome.model_dump_json()


def test_empty_batch_and_preexisting_cancellation_make_no_submission():
    for units in ((), (request(),)):
        with pytest.raises(ProviderCancelled) if units else __import__("contextlib").nullcontext():
            run_bounded_semantic_units(
                units,
                provider=object(),
                concurrency=2,
                before_submit=lambda *_: pytest.fail("cancelled or empty batch submitted work"),
                on_complete=lambda *_: pytest.fail("no completion expected"),
                on_abandoned=lambda *_: pytest.fail("no evidence expected"),
                cancel_requested=lambda: True,
            )
