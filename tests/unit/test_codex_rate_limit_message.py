from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from liveclip.clipping_skills.dual_profile_v1 import load_dual_profile_prompt
from liveclip.domain.clip_profile import ClipProfile
from liveclip.providers.llm import codex as codex_module
from liveclip.providers.llm import structured as module
from liveclip.providers.llm.codex import _codex_process_failure_code
from liveclip.providers.llm.structured import StructuredProviderError
from liveclip.providers.telemetry import ProviderCallStatus

_CONTRACT = f"{codex_module.CODEX_LLM_CONTRACT_PREFIX}.0.154.0.{'a' * 64}"
_RATE_LIMIT_EVENT = json.dumps(
    {"type": "error", "message": "unexpected status 429 Too Many Requests: rate limit"}
)


class Answer(BaseModel):
    value: str


def _provider(monkeypatch: pytest.MonkeyPatch) -> module.CodexStructuredLLMProvider:
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _value: _CONTRACT)
    monkeypatch.setattr(module, "codex_cli_contract_version", lambda _value: _CONTRACT)
    return module.CodexStructuredLLMProvider(
        prompts=load_dual_profile_prompt("discovery", ClipProfile.SHORT_HIGHLIGHT),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=_CONTRACT,
        reasoning_effort="medium",
    )


@pytest.mark.parametrize(
    "stderr",
    [
        "Error: unexpected status 429 Too Many Requests",
        "stream error: exceeded retry limit, last status: 429",
        "http 429",
    ],
)
def test_codex_429_evidence_is_classified_as_a_rate_limit(stderr: str) -> None:
    assert _codex_process_failure_code(stderr) == "CODEX_CLI_RATE_LIMITED"


def test_codex_unrelated_numbers_are_not_mistaken_for_429() -> None:
    assert _codex_process_failure_code("processed 1429 tokens") == "CODEX_CLI_REQUEST_FAILED"


def test_codex_nonzero_exit_rate_limit_names_the_real_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "429 Too Many Requests")

    provider = _provider(monkeypatch)
    monkeypatch.setattr(module, "run_cancellable_process", run)

    with pytest.raises(StructuredProviderError) as error:
        provider.generate(subject_id="s", payload={}, response_model=Answer)

    assert error.value.code == "CODEX_CLI_RATE_LIMITED"
    assert str(error.value) == "Codex CLI rate limited (429 Too Many Requests) after 1 attempt"
    assert len(calls) == 1


def test_codex_zero_exit_without_output_but_429_event_skips_the_schema_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, _RATE_LIMIT_EVENT + "\n", "")

    provider = _provider(monkeypatch)
    monkeypatch.setattr(module, "run_cancellable_process", run)

    with pytest.raises(StructuredProviderError) as error:
        provider.generate(subject_id="s", payload={}, response_model=Answer)

    assert error.value.code == "CODEX_CLI_RATE_LIMITED"
    assert "rate limited" in str(error.value)
    assert "could not be validated" not in str(error.value)
    (record,) = error.value.call_records
    assert record.status == ProviderCallStatus.FAILED
    assert len(calls) == 1


def test_codex_invalid_output_with_unrelated_error_event_still_repairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        output = Path(argv[argv.index("--output-last-message") + 1])
        output.write_text('{"value":"ok"}' if len(calls) == 2 else '{"value":7}')
        return subprocess.CompletedProcess(argv, 0, _RATE_LIMIT_EVENT + "\n", "")

    provider = _provider(monkeypatch)
    monkeypatch.setattr(module, "run_cancellable_process", run)

    result = provider.generate(subject_id="s", payload={}, response_model=Answer)

    # Output exists, so a recovered internal 429 is not a failure; the schema
    # failure takes the ordinary single repair path.
    assert result.repaired is True
    assert result.output.value == "ok"
    assert len(calls) == 2
