from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from liveclip.api.schemas import CompletionPresetCreateRequest
from liveclip.application.completion_preset_contract import (
    CompletionPresetId,
    CompletionPresetSummary,
    CompletionPresetValues,
)
from liveclip.domain.clip_profile import ClipProfile


def test_high_level_request_accepts_wire_enum_strings_but_rejects_extra_fields() -> None:
    body = {
        "input_path": "/allowed/clip.ts",
        "preset_id": "mini_lesson_v1",
        "selection_policy": "manual",
    }
    parsed = CompletionPresetCreateRequest.model_validate_json(json.dumps(body))
    assert parsed.preset_id is CompletionPresetId.MINI_LESSON_V1
    assert parsed.selection_policy.value == "manual"

    with pytest.raises(ValidationError):
        CompletionPresetCreateRequest.model_validate_json(json.dumps({**body, "command": "x"}))
    with pytest.raises(ValidationError):
        CompletionPresetCreateRequest.model_validate_json(
            json.dumps({**body, "selection_policy": 1})
        )


def test_preset_values_reject_inverted_duration_contract() -> None:
    with pytest.raises(ValidationError):
        CompletionPresetValues(
            preset_id=CompletionPresetId.MINI_LESSON_V1,
            clip_profile=ClipProfile.MINI_LESSON,
            minimum_clip_seconds=300,
            target_clip_seconds=180,
            maximum_clip_seconds=90,
            top_n=15,
            semantic_score_threshold=75,
            semantic_full_context_budget_ratio=0.58,
            semantic_model_context_tokens=128_000,
        )


def test_public_summary_contains_safe_identity_and_experimental_status() -> None:
    summary = CompletionPresetSummary(
        preset_id=CompletionPresetId.SHORT_HIGHLIGHT_V1,
        display_name_zh="短高光",
        clip_profile=ClipProfile.SHORT_HIGHLIGHT,
        minimum_clip_seconds=45,
        target_clip_seconds=60,
        maximum_clip_seconds=90,
    )
    payload = summary.model_dump(mode="json")
    assert payload["acceptance_status"] == "experimental"
    assert payload["preset_id"] == "short_highlight_v1"
    assert "model_context_tokens" not in payload
    assert "input_path" not in payload
