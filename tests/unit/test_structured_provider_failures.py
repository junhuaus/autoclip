"""Stage 16: provider failures name their real cause and fail fast after sleep.

No real model call is made: every provider process or HTTP response is a fake.
"""

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel

import liveclip.services.dual_profile_evaluation as dual_profile_module
from liveclip.clipping_skills.dual_profile_v1 import load_dual_profile_prompt
from liveclip.domain.clip_profile import ClipProfile
from liveclip.media.process import ProcessInterruptedBySleep
from liveclip.pipeline import semantic_executor
from liveclip.providers.llm import claude_cli as claude_module
from liveclip.providers.llm import codex as codex_module
from liveclip.providers.llm import structured as structured_module
from liveclip.providers.llm.claude_cli import (
    ClaudeCliRetryPolicy,
    ClaudeCliStructuredLLMProvider,
)
from liveclip.providers.llm.structured import (
    StructuredCallResult,
    StructuredProviderError,
    _structured_error_message,
)
from liveclip.providers.openai_retry import OpenAIRetryPolicy
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus

_VALIDATION_TEXT = "could not be validated"


class Answer(BaseModel):
    value: str


def _sleep_error(argv: list[str], timeout: float) -> ProcessInterruptedBySleep:
    return ProcessInterruptedBySleep(
        argv,
        timeout,
        wall_elapsed_seconds=timeout + 1.0,
        monotonic_elapsed_seconds=4.0,
        output="",
        stderr="",
    )


# --- fixed messages -------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("STRUCTURED_OUTPUT_INVALID", "structured model output could not be validated"),
        ("STRUCTURED_OUTPUT_MISSING", "structured model output was missing"),
        ("PROVIDER_TIMEOUT", "structured provider request timed out"),
        (
            "PROVIDER_INTERRUPTED_BY_SLEEP",
            "structured provider request was interrupted by system sleep",
        ),
        ("PROVIDER_ERROR", "structured provider request failed"),
        ("PROVIDER_CONFIGURATION", "structured provider configuration failed"),
        (
            "STRUCTURED_TOOL_EVENT",
            "structured provider response attempted a forbidden tool call",
        ),
        (
            "STRUCTURED_RESPONSE_REFUSED",
            "structured provider request failed (STRUCTURED_RESPONSE_REFUSED)",
        ),
        ("not a code", "structured provider request failed"),
    ],
)
def test_each_failure_code_has_a_fixed_message(code: str, message: str) -> None:
    assert _structured_error_message(code, ()) == message
    assert str(StructuredProviderError(code, ())) == message


def test_only_an_invalid_output_is_reported_as_a_validation_failure() -> None:
    codes = {
        *structured_module._PROVIDER_FAILURE_MESSAGES,
        "STRUCTURED_RESPONSE_INCOMPLETE",
        "STRUCTURED_UNEXPECTED_OUTPUT",
        "STRUCTURED_INPUT_BUDGET_EXCEEDED",
        "CODEX_CLI_REQUEST_FAILED",
        "UNLISTED_FUTURE_CODE",
    }
    flagged = {code for code in codes if _VALIDATION_TEXT in _structured_error_message(code, ())}
    assert flagged == {"STRUCTURED_OUTPUT_INVALID"}


def test_timeout_message_names_the_configured_timeout() -> None:
    assert (
        str(StructuredProviderError("PROVIDER_TIMEOUT", (), timeout_seconds=1800))
        == "structured provider request timed out after 1800 s"
    )
    assert (
        str(StructuredProviderError("PROVIDER_TIMEOUT", (), timeout_seconds=2.5))
        == "structured provider request timed out after 2.5 s"
    )
    # An unknown, zero or non-finite timeout keeps the bare fixed message.
    for value in (None, 0, float("nan"), float("inf")):
        assert (
            str(StructuredProviderError("PROVIDER_TIMEOUT", (), timeout_seconds=value))
            == "structured provider request timed out"
        )


def test_sleep_message_names_the_suspension_and_the_timeout() -> None:
    error = StructuredProviderError(
        "PROVIDER_INTERRUPTED_BY_SLEEP", (), timeout_seconds=1800, suspended_seconds=5_123.4
    )
    assert str(error) == (
        "structured provider request was interrupted by system sleep "
        "(host suspended for about 5123 s; wall-clock timeout 1800 s reached)"
    )
    assert error.timeout_seconds == 1800 and error.suspended_seconds == 5_123.4


# --- Claude CLI provider --------------------------------------------------------


def _claude_provider(tmp_path: Path) -> ClaudeCliStructuredLLMProvider:
    # Reuse the Claude CLI fake from the provider suite for the version and
    # subscription probes; every request process is replaced below.
    from tests.unit.test_claude_cli_provider import _install_fake

    executable = _install_fake(tmp_path, [])
    return ClaudeCliStructuredLLMProvider(
        prompts=load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT),
        model_name="claude-opus-5-5",
        claude_executable=str(executable),
        timeout_seconds=30,
        reasoning_effort="medium",
        retry_policy=ClaudeCliRetryPolicy(
            max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=1.0, total_wait_seconds=9.0
        ),
        sleep=lambda _delay, _cancel: None,
        jitter=lambda: 0.5,
    )


def test_claude_cli_timeout_names_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        raise subprocess.TimeoutExpired(argv, kwargs["timeout_seconds"])

    provider = _claude_provider(tmp_path)
    monkeypatch.setattr(claude_module, "run_cancellable_process", run)
    with pytest.raises(StructuredProviderError) as caught:
        provider.generate(subject_id="s", payload={}, response_model=Answer)

    assert caught.value.code == "PROVIDER_TIMEOUT"
    assert str(caught.value) == "structured provider request timed out after 30 s"
    assert _VALIDATION_TEXT not in str(caught.value)
    (record,) = caught.value.call_records
    assert record.status == ProviderCallStatus.FAILED
    assert record.failure_code == "STRUCTURED_PROVIDER_TIMEOUT"
    assert len(calls) == 1


def test_claude_cli_sleep_interruption_has_its_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        raise _sleep_error(argv, kwargs["timeout_seconds"])

    provider = _claude_provider(tmp_path)
    monkeypatch.setattr(claude_module, "run_cancellable_process", run)
    with pytest.raises(StructuredProviderError) as caught:
        provider.generate(subject_id="s", payload={}, response_model=Answer)

    assert caught.value.code == "PROVIDER_INTERRUPTED_BY_SLEEP"
    assert str(caught.value).startswith(
        "structured provider request was interrupted by system sleep (host suspended"
    )
    assert caught.value.suspended_seconds == pytest.approx(27.0)
    (record,) = caught.value.call_records
    assert record.status == ProviderCallStatus.FAILED
    assert record.failure_code == "STRUCTURED_PROVIDER_INTERRUPTED_BY_SLEEP"
    # The provider's own rate-limit backoff never relaunches after a sleep.
    assert len(calls) == 1


# --- Codex structured provider -------------------------------------------------

_CODEX_CONTRACT = f"{codex_module.CODEX_LLM_CONTRACT_PREFIX}.0.154.0.{'a' * 64}"


def _codex_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> structured_module.CodexStructuredLLMProvider:
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _value: _CODEX_CONTRACT)
    monkeypatch.setattr(
        structured_module, "codex_cli_contract_version", lambda _value: _CODEX_CONTRACT
    )
    return structured_module.CodexStructuredLLMProvider(
        prompts=load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=45,
        contract_version=_CODEX_CONTRACT,
        reasoning_effort="medium",
    )


@pytest.mark.parametrize("slept", [False, True])
def test_codex_timeout_and_sleep_name_their_cause(
    monkeypatch: pytest.MonkeyPatch, slept: bool
) -> None:
    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if slept:
            raise _sleep_error(argv, kwargs["timeout_seconds"])
        raise subprocess.TimeoutExpired(argv, kwargs["timeout_seconds"])

    provider = _codex_provider(monkeypatch)
    monkeypatch.setattr(structured_module, "run_cancellable_process", run)
    with pytest.raises(StructuredProviderError) as caught:
        provider.generate(subject_id="s", payload={}, response_model=Answer)

    (record,) = caught.value.call_records
    if slept:
        assert caught.value.code == "PROVIDER_INTERRUPTED_BY_SLEEP"
        assert record.failure_code == "STRUCTURED_PROVIDER_INTERRUPTED_BY_SLEEP"
        assert "interrupted by system sleep" in str(caught.value)
    else:
        assert caught.value.code == "PROVIDER_TIMEOUT"
        assert record.failure_code == "STRUCTURED_PROVIDER_TIMEOUT"
        assert str(caught.value) == "structured provider request timed out after 45 s"
    assert _VALIDATION_TEXT not in str(caught.value)


def test_codex_tool_event_is_not_a_validation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    tool_event = '{"type":"item.started","item":{"type":"command_execution"}}\n'

    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, tool_event, "")

    provider = _codex_provider(monkeypatch)
    monkeypatch.setattr(structured_module, "run_cancellable_process", run)
    with pytest.raises(StructuredProviderError) as caught:
        provider.generate(subject_id="s", payload={}, response_model=Answer)

    assert caught.value.code == "STRUCTURED_TOOL_EVENT"
    assert str(caught.value) == "structured provider response attempted a forbidden tool call"


# --- OpenAI structured provider -------------------------------------------------


def test_openai_transport_failure_is_not_a_validation_failure() -> None:
    client = OpenAI(
        api_key="synthetic-fixture",
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(500, json={}))
        ),
    )
    provider = structured_module.OpenAIStructuredLLMProvider(
        prompts=load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT),
        model_name="fixture",
        api_key=None,
        timeout_seconds=30,
        retry_policy=OpenAIRetryPolicy(max_retries=0),
        client=client,
    )
    try:
        with pytest.raises(StructuredProviderError) as caught:
            provider.generate(subject_id="s", payload={}, response_model=Answer)
    finally:
        client.close()
    assert caught.value.code == "PROVIDER_ERROR"
    assert str(caught.value) == "structured provider request failed"


# --- dual-profile semantic retry ------------------------------------------------


def _record(subject_id: str, status: ProviderCallStatus, code: str | None) -> ProviderCallRecord:
    return ProviderCallRecord(
        call_id=uuid.uuid4().hex,
        operation_key=uuid.uuid4().hex + uuid.uuid4().hex,
        subject_id=subject_id,
        provider="mock",
        operation="generate",
        model="mock-dual-v1",
        request_count=1,
        retry_count=0,
        latency_ms=5,
        status=status,
        failure_code=code,
        called_at=datetime.now(UTC),
    )


class _FailingProvider:
    """Generates fail with ``codes`` in order; an exhausted list means success."""

    contract_version = "failing-v1"
    provider_name = "mock"
    model_name = "mock-dual-v1"
    prompt_version = "v1"
    prompt_sha256 = "c" * 64

    def __init__(self, codes: list[str], *, repair_code: str | None = None) -> None:
        self.codes = codes
        self.repair_code = repair_code
        self.subjects: list[str] = []

    def generate(self, *, subject_id: str, **_kwargs: Any) -> StructuredCallResult[Answer]:
        self.subjects.append(subject_id)
        if self.codes:
            code = self.codes.pop(0)
            raise StructuredProviderError(
                code,
                (_record(subject_id, ProviderCallStatus.FAILED, f"STRUCTURED_{code}"),),
                timeout_seconds=1800,
            )
        return StructuredCallResult(
            output=Answer(value="bad"),
            call_records=(_record(subject_id, ProviderCallStatus.SUCCEEDED, None),),
            repaired=False,
        )

    def repair(self, *, subject_id: str, **_kwargs: Any) -> StructuredCallResult[Answer]:
        self.subjects.append(f"{subject_id}.repair")
        assert self.repair_code is not None
        raise StructuredProviderError(
            self.repair_code,
            (_record(subject_id, ProviderCallStatus.FAILED, "STRUCTURED_PROVIDER_ERROR"),),
        )


def _resolve(
    provider: _FailingProvider,
    validate: Any = lambda value: value,
    audit: Any = None,
) -> Any:
    return dual_profile_module._resolve_call(
        resolution_audit=audit or dual_profile_module._ResolutionAudit(refresh_stale_cache=False),
        stage="global_review",
        subject_id="short_highlight.global.001",
        payload={"profile": "short_highlight"},
        response_model=Answer,
        provider=provider,  # type: ignore[arg-type]
        profile=ClipProfile.SHORT_HIGHLIGHT,
        source_hash="f" * 64,
        window_start=0,
        window_end=1,
        cache_dir=None,
        validate=validate,
        cancel_requested=lambda: False,
    )


def test_a_sleep_interruption_is_never_semantically_retried() -> None:
    provider = _FailingProvider(["PROVIDER_INTERRUPTED_BY_SLEEP"])
    audit = dual_profile_module._ResolutionAudit(refresh_stale_cache=False)
    with pytest.raises(dual_profile_module.DualProfileProviderFailureError) as caught:
        _resolve(provider, audit=audit)

    assert provider.subjects == ["short_highlight.global.001"]
    error = caught.value
    assert error.failure_code == "PROVIDER_INTERRUPTED_BY_SLEEP"
    assert error.phase == "initial"
    assert [record.subject_id for record in error.records] == ["short_highlight.global.001"]
    assert isinstance(error.__cause__, StructuredProviderError)
    assert audit.unit_failures() == (error,)
    assert audit.completed_records() == ()


def test_a_timeout_is_retried_once_then_wrapped_with_both_records() -> None:
    provider = _FailingProvider(["PROVIDER_TIMEOUT", "PROVIDER_TIMEOUT"])
    with pytest.raises(dual_profile_module.DualProfileProviderFailureError) as caught:
        _resolve(provider)

    assert provider.subjects == [
        "short_highlight.global.001",
        "short_highlight.global.001.semantic_retry_1",
    ]
    error = caught.value
    assert error.failure_code == "PROVIDER_TIMEOUT"
    assert error.provider_message == "structured provider request timed out after 1800 s"
    assert [record.subject_id for record in error.records] == provider.subjects
    assert str(error) == (
        "structured provider request timed out after 1800 s [PROVIDER_TIMEOUT] in "
        "short_highlight global_review (short_highlight.global.001) during initial"
    )
    assert error.failure_file_name == "failed-short_highlight-global_review.json"


def test_a_repair_provider_failure_keeps_the_initial_attempt_and_records() -> None:
    provider = _FailingProvider([], repair_code="PROVIDER_ERROR")

    def validate(value: Answer) -> Answer:
        raise ValueError(f"deterministic rule rejects {value.value}")

    with pytest.raises(dual_profile_module.DualProfileProviderFailureError) as caught:
        _resolve(provider, validate)

    error = caught.value
    assert (error.phase, error.failure_code) == ("repair", "PROVIDER_ERROR")
    assert [value.phase for value in error.attempts] == ["initial"]
    assert error.attempts[0].error == "deterministic rule rejects bad"
    assert [record.status for record in error.records] == [
        ProviderCallStatus.SUCCEEDED,
        ProviderCallStatus.FAILED,
    ]


def test_provider_failure_summary_is_bounded_and_names_code_unit_and_evidence() -> None:
    error = dual_profile_module.DualProfileProviderFailureError(
        stage="global_review",
        profile="mini_lesson",
        subject_id="mini_lesson.global.002",
        cache_key="d" * 64,
        phase="initial",
        provider_error=StructuredProviderError("PROVIDER_TIMEOUT", (), timeout_seconds=1800),
        attempts=(),
        records=(),
    )
    error.evidence_file = "/runs/x/failed-mini_lesson-global_review.json"
    summary = error.summary()
    assert summary == (
        "dual Profile provider failure PROVIDER_TIMEOUT in mini_lesson global_review "
        "(mini_lesson.global.002) during initial; evidence: "
        "/runs/x/failed-mini_lesson-global_review.json; cause: structured provider "
        "request timed out after 1800 s"
    )
    error.add_note("y" * 2_000)
    bounded = error.summary()
    assert len(bounded) <= 480
    # Only the cause is trimmed; code, unit and evidence path always survive.
    assert "PROVIDER_TIMEOUT" in bounded
    assert "evidence: /runs/x/failed-mini_lesson-global_review.json" in bounded


def test_job_pipelines_keep_classifying_a_sleep_interruption_as_transient() -> None:
    # Before Stage 16 the same failure was PROVIDER_TIMEOUT, which is transient.
    assert {
        "PROVIDER_TIMEOUT",
        "PROVIDER_INTERRUPTED_BY_SLEEP",
        "STRUCTURED_PROVIDER_INTERRUPTED_BY_SLEEP",
    } <= semantic_executor._TRANSIENT_FAILURES
