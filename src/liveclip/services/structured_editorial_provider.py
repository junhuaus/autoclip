from __future__ import annotations

from typing import Literal, Protocol

from liveclip.clipping_skills.semantic_global_v1 import SemanticGlobalPromptBundle
from liveclip.config.settings import Settings
from liveclip.providers.llm.codex import codex_cli_contract_version
from liveclip.providers.llm.structured import (
    CodexStructuredLLMProvider,
    OpenAIStructuredLLMProvider,
    StructuredLLMProvider,
)
from liveclip.providers.openai_retry import OpenAIRetryPolicy

ReasoningEffort = Literal["low", "medium", "high", "xhigh"]


class StructuredEditorialProviderFactory(Protocol):
    def __call__(
        self,
        prompt: SemanticGlobalPromptBundle,
        reasoning_effort: ReasoningEffort,
    ) -> StructuredLLMProvider: ...


def configured_structured_editorial_provider_factory(
    settings: Settings,
) -> StructuredEditorialProviderFactory:
    """Create a generic structured provider factory with no editorial stage policy."""

    if settings.ai_provider in {
        "mock-codex",
        "openai-codex",
        "openrouter-codex",
        "mlx-codex",
    }:
        contract = codex_cli_contract_version(settings.codex_executable)

        def codex_factory(
            prompt: SemanticGlobalPromptBundle,
            reasoning_effort: ReasoningEffort,
        ) -> StructuredLLMProvider:
            return CodexStructuredLLMProvider(
                prompts=prompt,
                model_name=settings.llm_model,
                codex_executable=settings.codex_executable,
                timeout_seconds=settings.openai_request_timeout_seconds,
                contract_version=contract,
                reasoning_effort=reasoning_effort,
            )

        return codex_factory
    if settings.ai_provider == "openai":

        def openai_factory(
            prompt: SemanticGlobalPromptBundle,
            reasoning_effort: ReasoningEffort,
        ) -> StructuredLLMProvider:
            del reasoning_effort
            key = settings.openai_api_key
            return OpenAIStructuredLLMProvider(
                prompts=prompt,
                model_name=settings.llm_model,
                api_key=key.get_secret_value() if key is not None else None,
                timeout_seconds=settings.openai_request_timeout_seconds,
                retry_policy=OpenAIRetryPolicy(
                    max_retries=settings.openai_max_request_retries,
                    base_delay_seconds=settings.openai_retry_base_seconds,
                    max_delay_seconds=settings.openai_retry_max_seconds,
                ),
            )

        return openai_factory
    raise ValueError("prompt-first Agent requires a real structured editorial provider")


__all__ = [
    "ReasoningEffort",
    "StructuredEditorialProviderFactory",
    "configured_structured_editorial_provider_factory",
]
