from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import liveclip.services.codex_smoke as smoke_module
from liveclip.config import Settings
from liveclip.domain.edit_plan import CaptionTemplate, EditPlan, Effect, Layout
from liveclip.providers.llm.base import LLMDisposition, LLMProviderResult
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus
from liveclip.services.codex_smoke import CodexSmokeError, run_codex_smoke


def _record(
    *,
    thread_id: str | None = "thread_001",
    usage: dict[str, Any] | None = None,
) -> ProviderCallRecord:
    return ProviderCallRecord(
        call_id="a" * 32,
        operation_key="b" * 64,
        subject_id="codex_smoke",
        provider="codex_cli",
        operation="responses.edit.initial",
        model="gpt-5.6-terra",
        response_model="gpt-5.6-terra",
        request_id=thread_id,
        request_count=1,
        retry_count=0,
        latency_ms=1,
        usage_json=usage,
        status=ProviderCallStatus.SUCCEEDED,
        prompt_version="editing_v1",
        prompt_sha256="c" * 64,
        called_at=datetime.now(UTC),
    )


def _result(record: ProviderCallRecord) -> LLMProviderResult:
    return LLMProviderResult(
        plan=EditPlan(
            candidate_id="codex_smoke",
            source_start_ms=10_000,
            source_end_ms=60_000,
            score=90.0,
            title="真实证据",
            hook="真实证据",
            reason="存在线程与 token 证据",
            layout=Layout.CENTER_CROP,
            caption_template=CaptionTemplate.CLEAN_ZH_V1,
            effect=Effect.NONE,
            risk_flags=(),
            prompt_version="editing_v1",
            model="gpt-5.6-terra",
            degraded=False,
        ),
        disposition=LLMDisposition.SUCCEEDED,
        call_records=(record,),
    )


@pytest.mark.parametrize(
    "record",
    (
        _record(thread_id=None, usage={"input_tokens": 10, "output_tokens": 5}),
        _record(usage=None),
        _record(usage={"input_tokens": 0, "output_tokens": 5}),
        _record(usage={"input_tokens": 10, "output_tokens": 0}),
    ),
)
def test_codex_smoke_rejects_missing_thread_or_positive_usage(
    monkeypatch: pytest.MonkeyPatch,
    record: ProviderCallRecord,
) -> None:
    class FakeProvider:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def edit_candidate(self, *_args: object, **_kwargs: object) -> LLMProviderResult:
            return _result(record)

    monkeypatch.setattr(smoke_module, "CodexCLILLMProvider", FakeProvider)

    with pytest.raises(CodexSmokeError, match="without Mock fallback"):
        run_codex_smoke(Settings(ai_provider="mock", _env_file=None))


def test_codex_smoke_returns_required_thread_and_token_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record(usage={"input_tokens": 10, "output_tokens": 5})

    class FakeProvider:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def edit_candidate(self, *_args: object, **_kwargs: object) -> LLMProviderResult:
            return _result(record)

    monkeypatch.setattr(smoke_module, "CodexCLILLMProvider", FakeProvider)
    result = run_codex_smoke(Settings(ai_provider="mock", _env_file=None))

    assert result.thread_id == "thread_001"
    assert result.input_tokens == 10
    assert result.output_tokens == 5
