from __future__ import annotations

import re
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
        prompt_sha256: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._prompt_version = prompt_version
        self._prompt_sha256 = prompt_sha256

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
        return self._prompt_sha256 or mock_prompt_sha256(self.prompt_version)

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
        if self.prompt_version in {
            "semantic_window_v1",
            "semantic_window_v2",
            "semantic_continuous_v1",
        }:
            candidate = _bounded_semantic_mock_candidate(
                candidate,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
            )
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


def _bounded_semantic_mock_candidate(
    candidate: CandidateClip,
    *,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
) -> CandidateClip:
    timestamps = tuple(
        (int(start), int(end)) for start, end in re.findall(r"\[(\d+),(\d+)\]", candidate.text)
    )
    if not timestamps:
        return candidate
    start_ms = timestamps[0][0]
    legal_ends = tuple(
        end for _, end in timestamps if minimum_duration_ms <= end - start_ms <= maximum_duration_ms
    )
    if not legal_ends:
        return candidate
    return candidate.model_copy(
        update={
            "source_start_ms": start_ms,
            "source_end_ms": legal_ends[-1],
        }
    )
