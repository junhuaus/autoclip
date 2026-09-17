import pytest
from pydantic import ValidationError

from liveclip.application.completion_presets import (
    list_completion_presets,
    resolve_completion_preset,
)


@pytest.mark.parametrize(
    ("identity", "profile", "durations"),
    [
        ("short_highlight_v1", "short_highlight", (45, 60, 90)),
        ("mini_lesson_v1", "mini_lesson", (90, 180, 300)),
    ],
)
def test_exact_frozen_values(identity, profile, durations):
    values = resolve_completion_preset(identity)
    assert values.model_dump(mode="json") == {
        "schema_version": "1",
        "preset_id": identity,
        "clip_profile": profile,
        "minimum_clip_seconds": durations[0],
        "target_clip_seconds": durations[1],
        "maximum_clip_seconds": durations[2],
        "top_n": 15,
        "clipping_algorithm": "semantic_windowed",
        "semantic_profile": "general",
        "semantic_score_threshold": 75.0,
        "semantic_full_context_budget_ratio": 0.58,
        "semantic_model_context_tokens": 128000,
        "default_selection_policy": "default",
        "include_zip": True,
    }
    with pytest.raises(ValidationError):
        values.top_n = 1


def test_unknown_and_safe_summaries():
    with pytest.raises(ValueError):
        resolve_completion_preset("unknown")
    summaries = list_completion_presets()
    assert [item.display_name_zh for item in summaries] == ["短高光", "完整小课"]
    for item in summaries:
        assert set(item.model_dump()) == {
            "schema_version",
            "preset_id",
            "display_name_zh",
            "clip_profile",
            "minimum_clip_seconds",
            "target_clip_seconds",
            "maximum_clip_seconds",
            "default_selection_policy",
            "acceptance_status",
        }
        assert item.acceptance_status == "experimental"
        with pytest.raises(ValidationError):
            item.display_name_zh = "changed"
