import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import liveclip.bootstrap as bootstrap_module
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.config.settings import Settings
from liveclip.providers.asr.mock import MOCK_ASR_CONTRACT_VERSION
from liveclip.providers.asr.openai import OPENAI_ASR_CONTRACT_VERSION
from liveclip.providers.asr.openrouter import OPENROUTER_ASR_CONTRACT_VERSION
from liveclip.providers.llm.base import MOCK_LLM_CONTRACT_VERSION
from liveclip.providers.llm.codex import CODEX_LLM_UNPROBED_CONTRACT


def test_settings_parse_path_separated_allowed_roots() -> None:
    settings = Settings(
        allowed_media_roots_raw="/tmp/media-a:/tmp/media-b",
        _env_file=None,
    )

    assert settings.allowed_media_roots == (Path("/tmp/media-a"), Path("/tmp/media-b"))


def test_real_runtime_defaults_to_openrouter_asr_and_codex_editing() -> None:
    settings = Settings(_env_file=None)

    assert settings.ai_provider == "openrouter-codex"
    assert settings.codex_executable == "codex"


def test_settings_allow_full_context_high_reasoning_timeout() -> None:
    settings = Settings(openai_request_timeout_seconds=1_200, _env_file=None)

    assert settings.openai_request_timeout_seconds == 1_200


def test_settings_reject_excessive_llm_timeout() -> None:
    with pytest.raises(ValidationError):
        Settings(openai_request_timeout_seconds=3_601, _env_file=None)


@pytest.mark.parametrize(
    "provider", ("mock", "openai", "mock-codex", "openai-codex", "openrouter-codex")
)
def test_settings_accept_explicit_provider_modes(provider: str) -> None:
    assert Settings(ai_provider=provider, _env_file=None).ai_provider == provider


def test_settings_rejects_unknown_provider_mode() -> None:
    with pytest.raises(ValidationError, match="LIVECLIP_AI_PROVIDER"):
        Settings(ai_provider="silent-fake", _env_file=None)


@pytest.mark.parametrize(
    ("mode", "asr_model", "asr_contract"),
    (
        ("mock-codex", "mock-asr-v1", MOCK_ASR_CONTRACT_VERSION),
        ("openai-codex", "whisper-1", OPENAI_ASR_CONTRACT_VERSION),
        (
            "openrouter-codex",
            "openai/whisper-large-v3",
            OPENROUTER_ASR_CONTRACT_VERSION,
        ),
    ),
)
def test_codex_editing_modes_keep_asr_selection_explicit_and_fingerprinted(
    mode: str,
    asr_model: str,
    asr_contract: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = "codex-cli-editorial-v2.0.146.0." + "a" * 64
    monkeypatch.setattr(
        bootstrap_module,
        "codex_cli_contract_version",
        lambda _executable: contract,
    )
    settings = Settings(
        ai_provider=mode,
        llm_input_price_per_million="1",
        llm_output_price_per_million="2",
        _env_file=None,
    )

    config = pipeline_config_from_settings(settings)

    assert config.provider == mode
    assert config.transcription_model == asr_model
    assert config.asr_contract_version == asr_contract
    assert config.llm_model == "gpt-5.6-terra"
    assert config.llm_contract_version == contract
    assert config.llm_input_price_per_million is None
    assert config.llm_output_price_per_million is None


def test_mock_mode_remains_explicit_for_tests_and_demo() -> None:
    config = pipeline_config_from_settings(Settings(ai_provider="mock", _env_file=None))

    assert config.provider == "mock"
    assert config.transcription_model == "mock-asr-v1"
    assert config.llm_model == "mock-llm-v1"
    assert config.asr_contract_version == MOCK_ASR_CONTRACT_VERSION
    assert config.llm_contract_version == MOCK_LLM_CONTRACT_VERSION


def test_clipping_algorithm_b_has_an_independent_skill_fingerprint() -> None:
    classic = pipeline_config_from_settings(Settings(ai_provider="mock", _env_file=None))
    semantic = pipeline_config_from_settings(
        Settings(ai_provider="mock", _env_file=None),
        clipping_algorithm="b",
        minimum_clip_seconds=8,
        maximum_clip_seconds=60,
    )

    assert classic.clipping_algorithm == "a"
    assert classic.editing_prompt_version == "editing_v1"
    assert semantic.clipping_algorithm == "b"
    assert semantic.editing_prompt_version == "semantic_window_v1"
    assert semantic.editing_prompt_sha256 == semantic.semantic_skill_sha256
    assert semantic.semantic_target_clip_ms == 60_000
    assert semantic.semantic_continuous_merge_enabled is False
    assert semantic.semantic_consolidation_skill_version == "semantic_continuous_v1"
    assert semantic.semantic_consolidation_skill_sha256 != "0" * 64
    assert semantic.semantic_score_threshold == 75
    assert semantic.fingerprint != classic.fingerprint


def test_clipping_algorithm_b_preserves_frozen_sixty_second_v1_contract() -> None:
    semantic = pipeline_config_from_settings(
        Settings(ai_provider="mock", _env_file=None),
        clipping_algorithm="b",
    )

    assert semantic.semantic_target_clip_ms == 60_000
    assert semantic.maximum_clip_ms == 60_000


def test_semantic_global_defaults_to_full_first_vocal_duration_contract() -> None:
    semantic = pipeline_config_from_settings(
        Settings(ai_provider="mock", _env_file=None),
        clipping_algorithm="semantic_global",
        semantic_profile="vocal_coach_live",
    )

    assert semantic.minimum_clip_ms == 45_000
    assert semantic.semantic_target_clip_ms == 60_000
    assert semantic.maximum_clip_ms == 90_000
    assert semantic.semantic_full_context_budget_ratio == 0.58
    assert semantic.semantic_model_context_tokens == 128_000
    assert semantic.semantic_discovery_skill_sha256 != "0" * 64
    assert semantic.semantic_global_review_skill_sha256 != "0" * 64
    assert semantic.semantic_discovery_skill_sha256 != (
        semantic.semantic_global_review_skill_sha256
    )


def test_import_only_config_does_not_require_executing_codex_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_probe(_executable: str) -> str:
        raise AssertionError("import-only configuration must not execute Codex")

    monkeypatch.setattr(bootstrap_module, "codex_cli_contract_version", must_not_probe)

    config = pipeline_config_from_settings(
        Settings(ai_provider="openai-codex", _env_file=None),
        run_scope="import",
    )

    assert config.run_scope == "import"
    assert config.provider == "openai-codex"
    assert config.llm_contract_version == CODEX_LLM_UNPROBED_CONTRACT


def test_public_summary_never_contains_secret_values() -> None:
    editor_token = "editor-secret-token"
    settings = Settings(
        api_token="local-token-value",
        workspace_tokens_raw=json.dumps({"lin-editor": editor_token}),
        openai_api_key="cloud-key-value",
        openrouter_api_key="router-key-value",
        _env_file=None,
    )

    serialized = repr(settings.public_summary())
    assert "local-token-value" not in serialized
    assert "cloud-key-value" not in serialized
    assert "router-key-value" not in serialized
    assert editor_token not in serialized
    assert settings.public_summary()["api_token_configured"] is True
    assert settings.public_summary()["openai_configured"] is True
    assert settings.public_summary()["openrouter_configured"] is True
    assert settings.public_summary()["workspace_user_tokens_configured"] == 1


def test_settings_validates_workspace_token_map_without_exposing_tokens() -> None:
    settings = Settings(
        api_token="local-admin-token",
        workspace_tokens_raw='{"lin-editor":"editor-token-1234"}',
        _env_file=None,
    )

    assert settings.workspace_tokens == {"lin-editor": "editor-token-1234"}
    with pytest.raises(ValidationError, match="LIVECLIP_API_TOKEN"):
        Settings(
            workspace_tokens_raw='{"lin-editor":"editor-token-1234"}',
            _env_file=None,
        )
    with pytest.raises(ValidationError, match="unique"):
        Settings(
            api_token="local-admin-token",
            workspace_tokens_raw=(
                '{"lin-editor":"same-token-12345","wang-review":"same-token-12345"}'
            ),
            _env_file=None,
        )


@pytest.mark.parametrize(
    "base_url",
    (
        "http://openrouter.ai/api/v1",
        "https://openrouter.ai.evil.invalid/api/v1",
        "https://user:pass@openrouter.ai/api/v1",
    ),
)
def test_settings_rejects_unsafe_openrouter_base_url(base_url: str) -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_BASE_URL"):
        Settings(openrouter_base_url=base_url, _env_file=None)


def test_settings_reject_invalid_timing_relationships() -> None:
    with pytest.raises(ValidationError):
        Settings(asr_chunk_seconds=10, asr_chunk_overlap_seconds=10, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(asr_chunk_seconds=11, asr_chunk_overlap_seconds=6, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(worker_lease_seconds=60, worker_heartbeat_seconds=30, _env_file=None)

    with pytest.raises(ValidationError):
        Settings(
            llm_input_price_per_million="1.25",
            llm_output_price_per_million=None,
            _env_file=None,
        )

    with pytest.raises(ValidationError):
        Settings(
            llm_input_price_per_million="-1",
            llm_output_price_per_million="2",
            _env_file=None,
        )


def test_settings_read_exact_unprefixed_product_environment_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASR_CHUNK_SECONDS", "321")
    monkeypatch.setenv("DEFAULT_TOP_N", "7")
    monkeypatch.setenv("MIN_CLIP_SECONDS", "12")
    monkeypatch.setenv("MAX_CLIP_SECONDS", "48")
    monkeypatch.setenv("PREVIEW_RENDER_WIDTH", "360")
    monkeypatch.setenv("PREVIEW_RENDER_HEIGHT", "640")
    monkeypatch.setenv("WORKER_LEASE_SECONDS", "180")
    monkeypatch.setenv("WORKER_HEARTBEAT_SECONDS", "45")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)

    assert settings.asr_chunk_seconds == 321
    assert settings.default_top_n == 7
    assert settings.min_clip_seconds == 12
    assert settings.max_clip_seconds == 48
    assert (settings.preview_render_width, settings.preview_render_height) == (360, 640)
    assert (settings.worker_lease_seconds, settings.worker_heartbeat_seconds) == (180, 45)
    assert settings.log_level == "DEBUG"
