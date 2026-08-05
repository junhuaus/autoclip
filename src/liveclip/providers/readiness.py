from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

from liveclip.config import Settings
from liveclip.providers.llm.codex import assert_codex_cli_ready
from liveclip.providers.telemetry import ProviderConfigurationError

ProviderMode = Literal["mock", "openai", "mock-codex", "openai-codex", "openrouter-codex"]
ASRProviderName = Literal["mock", "openai", "openrouter"]
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
    if mode not in {"mock", "openai", "mock-codex", "openai-codex", "openrouter-codex"}:
        raise ValueError("unsupported provider mode")

    uses_mock_asr = mode in {"mock", "mock-codex"}
    asr_provider: ASRProviderName = (
        "mock" if uses_mock_asr else "openrouter" if mode == "openrouter-codex" else "openai"
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
    asr_ready = uses_mock_asr or (
        has_openrouter_key if asr_provider == "openrouter" else has_openai_key
    )
    issues: list[str] = []
    warnings: list[str] = []
    if not asr_ready and asr_provider == "openrouter":
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
