from __future__ import annotations

from collections.abc import Callable

from liveclip.domain.candidate import CandidateClip
from liveclip.providers.llm.base import (
    MOCK_LLM_CONTRACT_VERSION,
    LLMDisposition,
    LLMProviderResult,
    deterministic_edit_plan,
    mock_prompt_sha256,
)
from liveclip.providers.telemetry import ProviderCancelled


class MockLLMProvider:
    """Deterministic editorial adapter with no model, tool, or transcript execution."""

    def __init__(
        self,
        *,
        model_name: str = "mock-llm-v1",
        prompt_version: str = "editing_v1",
    ) -> None:
        self._model_name = model_name
        self._prompt_version = prompt_version

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def prompt_version(self) -> str:
        return self._prompt_version

    @property
    def prompt_sha256(self) -> str:
        return mock_prompt_sha256(self.prompt_version)

    @property
    def contract_version(self) -> str:
        return MOCK_LLM_CONTRACT_VERSION

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult:
        if cancel_requested():
            raise ProviderCancelled()
        return LLMProviderResult(
            plan=deterministic_edit_plan(
                candidate,
                source_duration_ms=source_duration_ms,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
                model=self.model_name,
                prompt_version=self.prompt_version,
                degraded=False,
                risk_flags=("mock_generated",),
            ),
            disposition=LLMDisposition.SUCCEEDED,
        )
