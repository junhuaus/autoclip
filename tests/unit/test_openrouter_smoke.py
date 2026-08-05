from __future__ import annotations

from pathlib import Path

import pytest

import liveclip.services.openrouter_smoke as smoke_module
from liveclip.config import Settings
from liveclip.services.openrouter_smoke import (
    OpenRouterPlanEvidence,
    OpenRouterSmokeError,
    OpenRouterUsageEvidence,
    openrouter_smoke_preflight,
    validate_openrouter_smoke_evidence,
)


def _usage(
    provider: str,
    operation: str,
    model: str,
    request_id: str | None,
    usage_json: dict[str, object] | None,
) -> OpenRouterUsageEvidence:
    return OpenRouterUsageEvidence(
        provider=provider,
        operation=operation,
        model=model,
        request_id=request_id,
        status="succeeded",
        usage_json=usage_json,
    )


def test_openrouter_smoke_preflight_stops_without_a_new_local_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"not opened")
    monkeypatch.setattr(
        smoke_module,
        "assess_provider_readiness",
        lambda _settings: type(
            "Readiness",
            (),
            {"blocking_issues": ("OPENROUTER_ASR_NOT_CONFIGURED",)},
        )(),
    )
    settings = Settings(
        ai_provider="openrouter-codex",
        openrouter_api_key=None,
        allowed_media_roots_raw=str(tmp_path),
        _env_file=None,
    )

    issues = openrouter_smoke_preflight(settings, source.absolute())

    assert "OPENROUTER_API_KEY (new, non-exposed key)" in issues
    assert "OPENROUTER_ASR_NOT_CONFIGURED" in issues


def test_openrouter_smoke_requires_generation_thread_and_positive_token_evidence() -> None:
    valid_usage = (
        _usage(
            "openrouter",
            "audio.transcriptions",
            "openai/whisper-large-v3",
            "gen_001",
            {"provider_usage": {"cost": 0.001}},
        ),
        _usage(
            "codex_cli",
            "responses.edit.initial",
            "gpt-5.6-terra",
            "thread_001",
            {"provider_usage": {"input_tokens": 100, "output_tokens": 20}},
        ),
    )
    plans = (OpenRouterPlanEvidence(degraded=False, model="gpt-5.6-terra"),)

    asr_ids, codex_ids = validate_openrouter_smoke_evidence(
        transcript_provider="openrouter",
        usage=valid_usage,
        selected_plans=plans,
        expected_asr_model="openai/whisper-large-v3",
        expected_llm_model="gpt-5.6-terra",
    )
    assert asr_ids == ("gen_001",)
    assert codex_ids == ("thread_001",)

    missing_tokens = (
        valid_usage[0],
        _usage(
            "codex_cli",
            "responses.edit.initial",
            "gpt-5.6-terra",
            "thread_001",
            {"provider_usage": {"input_tokens": 100}},
        ),
    )
    with pytest.raises(OpenRouterSmokeError, match="thread/token"):
        validate_openrouter_smoke_evidence(
            transcript_provider="openrouter",
            usage=missing_tokens,
            selected_plans=plans,
            expected_asr_model="openai/whisper-large-v3",
            expected_llm_model="gpt-5.6-terra",
        )
