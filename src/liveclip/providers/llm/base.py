from __future__ import annotations

from typing import Protocol

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.edit_plan import EditPlan


class LLMProvider(Protocol):
    """Editorial provider port. Implementations receive data, never executable hooks."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
    ) -> EditPlan: ...
