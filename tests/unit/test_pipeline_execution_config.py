from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter

from liveclip.application.pipeline import (
    PipelineConfig,
    PipelineConfigInvalid,
    PipelineRunConfigV10,
    PipelineRunConfigV11,
    PipelineRunConfigV12,
    PipelineRunConfigV13,
    load_persisted_pipeline_config,
)
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.domain.clip_profile import ClipProfile


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_execution_identity_is_additive_and_exact_for_all_new_runs(profile):
    current = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"),
        clipping_algorithm="semantic_windowed",
        clip_profile=profile,
    )
    mini = profile == ClipProfile.MINI_LESSON
    assert type(current) is (PipelineRunConfigV13 if mini else PipelineRunConfigV12)
    old_model = PipelineRunConfigV11 if mini else PipelineRunConfigV10
    assert set(type(current).model_fields) == set(old_model.model_fields) | {
        "semantic_execution_contract"
    }
    assert current.semantic_execution_contract == "semantic-bounded-units-v1"
    raw = current.model_dump(mode="json")
    assert TypeAdapter(PipelineConfig).validate_json(json.dumps(raw)) == current
    assert load_persisted_pipeline_config(raw, current.fingerprint) == current
    raw.pop("semantic_execution_contract")
    raw["schema_version"] = "11" if mini else "10"
    old = old_model.model_validate_json(json.dumps(raw))
    assert load_persisted_pipeline_config(raw, old.fingerprint) == old
    assert old.fingerprint != current.fingerprint
    for mutate in ("remove", "unknown", "relabel"):
        invalid = current.model_dump(mode="json")
        if mutate == "remove":
            invalid.pop("semantic_execution_contract")
        elif mutate == "unknown":
            invalid["semantic_execution_contract"] = "unknown"
        else:
            invalid["schema_version"] = old.schema_version
        with pytest.raises(PipelineConfigInvalid):
            load_persisted_pipeline_config(invalid, current.fingerprint)
