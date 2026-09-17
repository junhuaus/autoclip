"""Pure, versioned Completion presets and safe client descriptors."""

from liveclip.application.completion_preset_contract import (
    CompletionPresetId,
    CompletionPresetSummary,
    CompletionPresetValues,
)
from liveclip.domain.clip_profile import ClipProfile, clip_profile_spec


def resolve_completion_preset(preset_id: CompletionPresetId | str) -> CompletionPresetValues:
    identity = CompletionPresetId(preset_id)
    profile = (
        ClipProfile.SHORT_HIGHLIGHT
        if identity == CompletionPresetId.SHORT_HIGHLIGHT_V1
        else ClipProfile.MINI_LESSON
    )
    spec = clip_profile_spec(profile)
    return CompletionPresetValues(
        preset_id=identity,
        clip_profile=profile,
        minimum_clip_seconds=spec.minimum_duration_ms // 1000,
        target_clip_seconds=spec.target_duration_ms // 1000,
        maximum_clip_seconds=spec.maximum_duration_ms // 1000,
        top_n=15,
        semantic_score_threshold=75.0,
        semantic_full_context_budget_ratio=0.58,
        semantic_model_context_tokens=128_000,
    )


def list_completion_presets() -> tuple[CompletionPresetSummary, ...]:
    summaries = []
    for identity, label in (
        (CompletionPresetId.SHORT_HIGHLIGHT_V1, "短高光"),
        (CompletionPresetId.MINI_LESSON_V1, "完整小课"),
    ):
        values = resolve_completion_preset(identity)
        summaries.append(
            CompletionPresetSummary(
                preset_id=identity,
                display_name_zh=label,
                clip_profile=values.clip_profile,
                minimum_clip_seconds=values.minimum_clip_seconds,
                target_clip_seconds=values.target_clip_seconds,
                maximum_clip_seconds=values.maximum_clip_seconds,
                default_selection_policy=values.default_selection_policy,
            )
        )
    return tuple(summaries)
