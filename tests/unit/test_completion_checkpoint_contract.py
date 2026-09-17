from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from liveclip.application.completion import CompletionSelectionCheckpoint
from liveclip.domain.completion import CompletionSelectionPolicy


def test_selection_checkpoint_roundtrip_preserves_explicit_empty_and_rejects_ambiguity() -> None:
    base = {
        "schema_version": "1",
        "intent_id": "a" * 32,
        "run_id": "b" * 32,
        "generation": 1,
        "mode": CompletionSelectionPolicy.MANUAL.value,
        "action_key": "completion:" + "a" * 32 + ":selection:v1",
        "selected": [],
    }
    checkpoint = CompletionSelectionCheckpoint.model_validate_json(json.dumps(base))
    assert (
        CompletionSelectionCheckpoint.model_validate_json(checkpoint.model_dump_json())
        == checkpoint
    )
    assert checkpoint.selected == ()

    clip = {
        "clip_id": "c" * 32,
        "edit_plan_revision_id": "d" * 32,
        "edit_plan_revision": 2,
        "decision_id": "e" * 32,
    }
    with pytest.raises(ValidationError):
        CompletionSelectionCheckpoint.model_validate_json(
            json.dumps({**base, "selected": [clip, clip]})
        )
    with pytest.raises(ValidationError):
        CompletionSelectionCheckpoint.model_validate_json(
            json.dumps(
                {
                    **base,
                    "selected": [
                        {key: value for key, value in clip.items() if key != "decision_id"}
                    ],
                }
            )
        )
