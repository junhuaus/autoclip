from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from liveclip.application.pipeline import (
    ActionNotReady,
    ActionReadiness,
    PipelineCapability,
    PipelineConfig,
)
from liveclip.config import Settings
from liveclip.providers.asr.mlx import assert_mlx_asr_ready
from liveclip.providers.llm.codex import assert_codex_cli_ready
from liveclip.providers.telemetry import ProviderConfigurationError

ProviderMode = Literal[
    "mock", "openai", "mock-codex", "openai-codex", "openrouter-codex", "mlx-codex"
]
ASRProviderName = Literal["mock", "openai", "openrouter", "mlx"]
LLMProviderName = Literal["mock", "openai", "codex_cli"]


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """Safe, credential-free processing-provider preflight evidence."""

    mode: ProviderMode
    asr_provider: ASRProviderName
    llm_provider: LLMProviderName
    asr_ready: bool
    llm_ready: bool
    processing_ready: bool
    blocking_issues: tuple[str, ...]
    warnings: tuple[str, ...]


class ProviderNotReady(RuntimeError):
    """The configured pipeline cannot truthfully start content processing."""

    def __init__(self, readiness: ProviderReadiness):
        self.readiness = readiness
        issues = ", ".join(readiness.blocking_issues) or "UNKNOWN_PROVIDER_ERROR"
        super().__init__(
            f"Provider preflight failed: {issues}. "
            "Run 'liveclip doctor'; Codex CLI edits transcripts but does not perform ASR."
        )


def assess_provider_readiness(settings: Settings) -> ProviderReadiness:
    mode = cast(ProviderMode, settings.ai_provider)
    if mode not in {
        "mock",
        "openai",
        "mock-codex",
        "openai-codex",
        "openrouter-codex",
        "mlx-codex",
    }:
        raise ValueError("unsupported provider mode")

    uses_mock_asr = mode in {"mock", "mock-codex"}
    asr_provider: ASRProviderName = (
        "mock"
        if uses_mock_asr
        else "openrouter"
        if mode == "openrouter-codex"
        else "mlx"
        if mode == "mlx-codex"
        else "openai"
    )
    llm_provider: LLMProviderName
    if mode == "mock":
        llm_provider = "mock"
    elif mode == "openai":
        llm_provider = "openai"
    else:
        llm_provider = "codex_cli"

    has_openai_key = bool(
        settings.openai_api_key and settings.openai_api_key.get_secret_value().strip()
    )
    has_openrouter_key = bool(
        settings.openrouter_api_key and settings.openrouter_api_key.get_secret_value().strip()
    )
    if asr_provider == "mlx":
        try:
            assert_mlx_asr_ready(settings.resolved_mlx_asr_model_path())
        except ProviderConfigurationError:
            asr_ready = False
        else:
            asr_ready = True
    else:
        asr_ready = uses_mock_asr or (
            has_openrouter_key if asr_provider == "openrouter" else has_openai_key
        )
    issues: list[str] = []
    warnings: list[str] = []
    if not asr_ready and asr_provider == "mlx":
        issues.append("MLX_ASR_NOT_READY")
    elif not asr_ready and asr_provider == "openrouter":
        issues.append("OPENROUTER_ASR_NOT_CONFIGURED")
    elif not asr_ready:
        issues.append("OPENAI_ASR_NOT_CONFIGURED")
    if uses_mock_asr:
        warnings.append("MOCK_ASR_SELECTED")

    if llm_provider == "mock":
        llm_ready = True
        warnings.append("MOCK_LLM_SELECTED")
    elif llm_provider == "openai":
        llm_ready = has_openai_key
        if not llm_ready:
            issues.append("OPENAI_LLM_NOT_CONFIGURED")
    else:
        try:
            assert_codex_cli_ready(settings.codex_executable)
        except ProviderConfigurationError:
            llm_ready = False
            issues.append("CODEX_CLI_NOT_READY")
        else:
            llm_ready = True

    return ProviderReadiness(
        mode=mode,
        asr_provider=asr_provider,
        llm_provider=llm_provider,
        asr_ready=asr_ready,
        llm_ready=llm_ready,
        processing_ready=asr_ready and llm_ready,
        blocking_issues=tuple(issues),
        warnings=tuple(warnings),
    )


def require_processing_ready(settings: Settings) -> ProviderReadiness:
    return ensure_processing_ready(assess_provider_readiness(settings))


def ensure_processing_ready(readiness: ProviderReadiness) -> ProviderReadiness:
    if not readiness.processing_ready:
        raise ProviderNotReady(readiness)
    return readiness


def require_action_readiness(
    settings: Settings,
    config: PipelineConfig,
    required: tuple[PipelineCapability, ...],
) -> ActionReadiness:
    """Probe only needed capabilities and retain the persisted provider/model identity.

    These are local configuration checks, never evidence of successful inference.
    Media, storage and artifact checks remain at their actual local action boundaries.
    """
    from liveclip.providers.asr.mock import MOCK_ASR_CONTRACT_VERSION
    from liveclip.providers.asr.openai import OPENAI_ASR_CONTRACT_VERSION
    from liveclip.providers.asr.openrouter import OPENROUTER_ASR_CONTRACT_VERSION
    from liveclip.providers.llm.base import MOCK_LLM_CONTRACT_VERSION
    from liveclip.providers.llm.openai import OPENAI_LLM_CONTRACT_VERSION

    issues: list[str] = []
    satisfied: list[PipelineCapability] = []
    if required and settings.ai_provider != config.provider:
        raise ActionNotReady(ActionReadiness(required, (), ("PERSISTED_PROVIDER_MISMATCH",)))
    for capability in required:
        issue: str | None = None
        contract: str | None = None
        if capability == "asr":
            if config.provider in {"mock", "mock-codex"}:
                contract = MOCK_ASR_CONTRACT_VERSION
            elif config.provider == "mlx-codex":
                try:
                    path = settings.resolved_mlx_asr_model_path()
                    contract = assert_mlx_asr_ready(path).contract_version
                except ProviderConfigurationError:
                    issue = "MLX_ASR_NOT_READY"
            else:
                router = config.provider == "openrouter-codex"
                key = settings.openrouter_api_key if router else settings.openai_api_key
                if key is None or not key.get_secret_value().strip():
                    issue = (
                        "OPENROUTER_ASR_NOT_CONFIGURED" if router else "OPENAI_ASR_NOT_CONFIGURED"
                    )
                contract = (
                    OPENROUTER_ASR_CONTRACT_VERSION if router else OPENAI_ASR_CONTRACT_VERSION
                )
            if issue is None and contract != config.asr_contract_version:
                issue = "PERSISTED_ASR_CONTRACT_MISMATCH"
        elif capability == "semantic":
            if config.provider == "mock":
                contract = MOCK_LLM_CONTRACT_VERSION
            elif config.provider == "openai":
                key = settings.openai_api_key
                if key is None or not key.get_secret_value().strip():
                    issue = "OPENAI_LLM_NOT_CONFIGURED"
                contract = OPENAI_LLM_CONTRACT_VERSION
            else:
                try:
                    contract = assert_codex_cli_ready(settings.codex_executable)
                except ProviderConfigurationError:
                    issue = "CODEX_CLI_NOT_READY"
            if issue is None and contract != config.llm_contract_version:
                issue = "PERSISTED_LLM_CONTRACT_MISMATCH"
        else:
            raise ValueError("unknown pipeline capability")
        if issue is None:
            satisfied.append(capability)
        else:
            issues.append(issue)
    readiness = ActionReadiness(required, tuple(satisfied), tuple(issues))
    if issues:
        raise ActionNotReady(readiness)
    return readiness
