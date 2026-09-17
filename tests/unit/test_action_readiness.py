from __future__ import annotations

import pytest

import liveclip.providers.readiness as readiness
from liveclip.application.pipeline import ActionNotReady, required_pipeline_capabilities
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.domain.state_transitions import PipelineStage


def config():
    return pipeline_config_from_settings(Settings(_env_file=None, ai_provider="mock"))


def test_local_only_recovery_probes_no_unused_provider(monkeypatch):
    def forbidden(*_):
        pytest.fail("unused provider was probed")

    monkeypatch.setattr(readiness, "assert_codex_cli_ready", forbidden)
    monkeypatch.setattr(readiness, "assert_mlx_asr_ready", forbidden)
    settings = Settings(_env_file=None, ai_provider="mlx-codex")
    result = readiness.require_action_readiness(settings, config(), ())
    assert result.required == result.satisfied == result.blocking_issues == ()


def test_semantic_only_does_not_require_completed_asr(monkeypatch):
    stored = config().model_copy(
        update={"provider": "openrouter-codex", "llm_contract_version": "fixture-v1"}
    )
    monkeypatch.setattr(readiness, "assert_codex_cli_ready", lambda _: "fixture-v1")
    settings = Settings(_env_file=None, ai_provider="openrouter-codex", openrouter_api_key=None)
    result = readiness.require_action_readiness(settings, stored, ("semantic",))
    assert result.satisfied == ("semantic",)
    with pytest.raises(ActionNotReady) as error:
        readiness.require_action_readiness(settings, stored, ("asr", "semantic"))
    assert error.value.readiness.blocking_issues == ("OPENROUTER_ASR_NOT_CONFIGURED",)


def test_needed_provider_and_installed_contract_cannot_replace_stored_identity(monkeypatch):
    with pytest.raises(ActionNotReady, match="PERSISTED_PROVIDER_MISMATCH"):
        readiness.require_action_readiness(
            Settings(_env_file=None, ai_provider="openai"), config(), ("semantic",)
        )
    stored = config().model_copy(
        update={"provider": "mock-codex", "llm_contract_version": "old-v1"}
    )
    monkeypatch.setattr(readiness, "assert_codex_cli_ready", lambda _: "changed-v2")
    with pytest.raises(ActionNotReady, match="PERSISTED_LLM_CONTRACT_MISMATCH"):
        readiness.require_action_readiness(
            Settings(_env_file=None, ai_provider="mock-codex"), stored, ("semantic",)
        )


def test_required_actions_use_actual_stage_and_committed_edit_checkpoint():
    stored = config()
    stages = (
        PipelineStage.TRANSCRIBE,
        PipelineStage.CANDIDATES,
        PipelineStage.EDIT,
        PipelineStage.PROXY_RENDER,
    )
    assert required_pipeline_capabilities(stored, stages) == ("asr", "semantic")
    assert required_pipeline_capabilities(stored, stages[2:]) == ("semantic",)
    assert required_pipeline_capabilities(stored, stages[2:], edit_committed=True) == ()
    assert required_pipeline_capabilities(stored, stages[3:]) == ()
    assert (
        required_pipeline_capabilities(stored.model_copy(update={"run_scope": "import"}), stages)
        == ()
    )


def test_preflight_reports_all_missing_capabilities_without_provider_details(monkeypatch):
    def unavailable(_):
        raise readiness.ProviderConfigurationError("sensitive local fixture detail")

    monkeypatch.setattr(readiness, "assert_codex_cli_ready", unavailable)
    stored = config().model_copy(update={"provider": "openai-codex"})
    settings = Settings(_env_file=None, ai_provider="openai-codex", openai_api_key=None)
    with pytest.raises(ActionNotReady) as error:
        readiness.require_action_readiness(settings, stored, ("asr", "semantic"))
    assert error.value.readiness.blocking_issues == (
        "OPENAI_ASR_NOT_CONFIGURED",
        "CODEX_CLI_NOT_READY",
    )
    assert "sensitive" not in str(error.value)
