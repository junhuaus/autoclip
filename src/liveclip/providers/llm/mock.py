# ruff: noqa: RUF001
from __future__ import annotations

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.edit_plan import (
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    validate_edit_plan_bounds,
)


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

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
    ) -> EditPlan:
        title, hook = _editorial_labels(candidate.text)
        plan = EditPlan(
            candidate_id=candidate.candidate_id,
            source_start_ms=candidate.source_start_ms,
            source_end_ms=candidate.source_end_ms,
            score=round(candidate.rule_score, 3),
            title=title,
            hook=hook,
            reason="规则候选边界完整、表达紧凑，适合作为本地演示高光。",
            layout=Layout.VERTICAL_BLUR_BACKGROUND,
            caption_template=CaptionTemplate.CLEAN_ZH_V1,
            effect=Effect.FADE_IN_OUT,
            risk_flags=("mock_generated",),
            prompt_version=self.prompt_version,
            model=self.model_name,
            degraded=False,
        )
        validate_edit_plan_bounds(
            plan,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
            allowed_start_ms=candidate.allowed_start_ms,
            allowed_end_ms=candidate.allowed_end_ms,
        )
        return plan


def _editorial_labels(untrusted_transcript: str) -> tuple[str, str]:
    """Classify bounded content without copying untrusted instructions into EditPlan."""

    if "误区" in untrusted_transcript or "很多人" in untrusted_transcript:
        return "常见表达误区", "这个常见误区，可能正在悄悄赶走你的观众。"
    if "方法" in untrusted_transcript or "步骤" in untrusted_transcript:
        return "三个实用表达方法", "掌握这几个方法，直播表达会立刻更清楚。"
    if "为什么" in untrusted_transcript or "？" in untrusted_transcript:
        return "关键问题解析", "先看清关键问题，再决定怎样行动。"
    return "直播核心观点", "用一个完整片段讲清这场直播的核心观点。"
