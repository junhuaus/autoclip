from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel

from liveclip.clipping_skills.semantic_windowed_v1 import load_semantic_windowed_discovery_prompt
from liveclip.domain.semantic_validation import (
    CURRENT_SEMANTIC_EXECUTION,
    CURRENT_SEMANTIC_TRANSPORT,
)
from liveclip.media.process import ProcessCancelled
from liveclip.providers.llm import codex as codex_module
from liveclip.providers.llm import structured as module
from liveclip.providers.openai_retry import OpenAIRetryPolicy
from liveclip.providers.telemetry import ProviderCancelled, ProviderConfigurationError


class Answer(BaseModel):
    value: str


def response(text):
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "fixture",
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": None,
    }


@pytest.mark.parametrize("repair", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_actual_sdk_cancel_keeps_executed_counts_and_original_schema_call(enabled, repair):
    cancelled = Event()
    starts = []

    def handle(request):
        starts.append(datetime.now(UTC))
        assert json.loads(request.content)["tools"] == []
        if repair and len(starts) == 1:
            return httpx.Response(200, json=response('{"value":7}'))
        cancelled.set()
        return httpx.Response(200, json=response('{"value":"valid"}'))

    client = OpenAI(
        api_key="synthetic-fixture",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    provider = module.OpenAIStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="fixture",
        api_key=None,
        timeout_seconds=30,
        retry_policy=OpenAIRetryPolicy(max_retries=0),
        client=client,
        transport_contract=CURRENT_SEMANTIC_TRANSPORT,
        execution_contract=CURRENT_SEMANTIC_EXECUTION if enabled else None,
    )
    try:
        with pytest.raises(ProviderCancelled) as error:
            provider.generate(
                subject_id="fixture",
                payload={"complete": ["authority"]},
                response_model=Answer,
                cancel_requested=cancelled.is_set,
            )
    finally:
        client.close()
    assert len(starts) == (2 if repair else 1)
    calls = error.value.call_records
    assert len(calls) == (len(starts) if enabled else 0)
    for call, start in zip(calls, starts, strict=False):
        assert call.request_count == 1 and call.retry_count == 0
        assert call.called_at <= start
    if enabled and repair:
        assert [call.operation.rsplit(".", 1)[-1] for call in calls] == ["initial", "repair"]


def test_preexisting_cancel_has_no_phantom_sdk_request():
    client = OpenAI(
        api_key="synthetic-fixture",
        max_retries=0,
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("no HTTP request"))
        ),
    )
    provider = module.OpenAIStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="fixture",
        api_key=None,
        timeout_seconds=30,
        retry_policy=OpenAIRetryPolicy(max_retries=0),
        client=client,
        execution_contract=CURRENT_SEMANTIC_EXECUTION,
    )
    try:
        with pytest.raises(ProviderCancelled) as error:
            provider.generate(
                subject_id="fixture",
                payload={},
                response_model=Answer,
                cancel_requested=lambda: True,
            )
        assert not error.value.call_records
    finally:
        client.close()


@pytest.mark.parametrize("repair", [False, True])
def test_codex_cancel_preserves_process_attempts_and_call_start(monkeypatch, repair):
    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(module, "codex_cli_contract_version", lambda _: contract)
    starts = []

    def run(argv, **kwargs):
        starts.append(datetime.now(UTC))
        assert argv[argv.index("--sandbox") + 1] == "read-only"
        assert "features.shell_tool=false" in argv and "features.multi_agent=false" in argv
        assert "--ignore-user-config" in argv and "--strict-config" in argv
        if repair and len(starts) == 1:
            Path(argv[argv.index("--output-last-message") + 1]).write_text('{"value":7}')
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise ProcessCancelled("owned process cancelled")

    monkeypatch.setattr(module, "run_cancellable_process", run)
    provider = module.CodexStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
        transport_contract=CURRENT_SEMANTIC_TRANSPORT,
        execution_contract=CURRENT_SEMANTIC_EXECUTION,
    )
    with pytest.raises(ProviderCancelled) as error:
        provider.generate(subject_id="fixture", payload={}, response_model=Answer)
    assert len(error.value.call_records) == len(starts) == (2 if repair else 1)
    assert all(
        call.called_at <= start
        for call, start in zip(error.value.call_records, starts, strict=True)
    )


def test_codex_start_failure_never_invents_an_executed_call(monkeypatch):
    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(
        module,
        "run_cancellable_process",
        lambda *_, **__: (_ for _ in ()).throw(FileNotFoundError()),
    )
    provider = module.CodexStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
        execution_contract=CURRENT_SEMANTIC_EXECUTION,
    )
    with pytest.raises(ProviderConfigurationError):
        provider.generate(subject_id="fixture", payload={}, response_model=Answer)


@pytest.mark.parametrize("repair", [False, True])
def test_codex_post_launch_pipe_error_retains_all_executed_phases(monkeypatch, repair):
    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(module, "codex_cli_contract_version", lambda _: contract)
    starts = []

    def run(argv, **kwargs):
        kwargs["on_started"]()
        starts.append(datetime.now(UTC))
        if repair and len(starts) == 1:
            Path(argv[argv.index("--output-last-message") + 1]).write_text('{"value":7}')
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise OSError("synthetic post-launch pipe failure")

    monkeypatch.setattr(module, "run_cancellable_process", run)
    provider = module.CodexStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
        execution_contract=CURRENT_SEMANTIC_EXECUTION,
    )
    with pytest.raises(module.StructuredProviderError) as caught:
        provider.generate(subject_id="fixture", payload={}, response_model=Answer)
    assert caught.value.code == "PROVIDER_ERROR"
    calls = caught.value.call_records
    assert len(calls) == len(starts) == (2 if repair else 1)
    assert calls[-1].failure_code == "STRUCTURED_PROVIDER_ERROR"
    assert [call.operation.rsplit(".", 1)[-1] for call in calls] == (
        ["initial", "repair"] if repair else ["initial"]
    )
    assert all(call.called_at <= start for call, start in zip(calls, starts, strict=True))


@pytest.mark.parametrize("after_initial", [False, True])
def test_codex_preentry_cancellation_does_not_start_another_process(monkeypatch, after_initial):
    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(module, "codex_cli_contract_version", lambda _: contract)
    cancelled = Event()
    if not after_initial:
        cancelled.set()
    starts = []

    def run(argv, **kwargs):
        assert not cancelled.is_set(), "cancelled work entered the process runner"
        starts.append(datetime.now(UTC))
        Path(argv[argv.index("--output-last-message") + 1]).write_text('{"value":7}')
        cancelled.set()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(module, "run_cancellable_process", run)
    provider = module.CodexStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
        execution_contract=CURRENT_SEMANTIC_EXECUTION,
    )
    with pytest.raises(ProviderCancelled) as error:
        provider.generate(
            subject_id="fixture",
            payload={},
            response_model=Answer,
            cancel_requested=cancelled.is_set,
        )
    assert len(starts) == len(error.value.call_records) == int(after_initial)
    if after_initial:
        assert error.value.call_records[0].operation.endswith(".initial")
        assert error.value.call_records[0].called_at <= starts[0]


def test_codex_schema_repair_start_failure_retains_initial_call_in_unit_outcome(monkeypatch):
    from liveclip.pipeline.semantic_executor import SemanticUnitRequest, execute_semantic_unit

    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(module, "codex_cli_contract_version", lambda _: contract)
    starts = []

    def run(argv, **kwargs):
        if starts:
            raise FileNotFoundError("synthetic process-start failure")
        starts.append(datetime.now(UTC))
        Path(argv[argv.index("--output-last-message") + 1]).write_text('{"value":7}')
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(module, "run_cancellable_process", run)
    provider = module.CodexStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
        execution_contract=CURRENT_SEMANTIC_EXECUTION,
    )
    unit = SemanticUnitRequest.snapshot(
        subject_id="fixture",
        payload={},
        response_model=Answer,
        validate=lambda value: value,
        repair_payload=lambda original, output, errors: original,
    )
    outcome = execute_semantic_unit(unit, provider, cancel_requested=lambda: False)
    assert outcome.disposition == "exhausted" and outcome.global_failure
    assert outcome.repair_spent and outcome.failure_code == "PROVIDER_CONFIGURATION"
    assert len(outcome.call_records) == len(starts) == 1
    assert outcome.call_records[0].operation.endswith(".initial")
    assert outcome.call_records[0].called_at <= starts[0]
    assert outcome.provider_attempts[-1] == {
        "phase": "repair_not_started",
        "provider_call_executed": False,
    }
