from __future__ import annotations

import hashlib
import json

import pytest

from liveclip.application.pipeline import (
    PipelineConfigInvalid,
    _PipelineRunConfigV6,
    _PipelineRunConfigV7,
    load_persisted_pipeline_config,
)
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt
from liveclip.config.settings import Settings
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.semantic_validation import (
    CURRENT_SEMANTIC_VALIDATION,
    LEGACY_SEMANTIC_VALIDATION,
)
from liveclip.pipeline.semantic_cache import semantic_validation_cache_settings


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_v7_profile_and_all_prompt_hashes_survive_exact_in_memory_upgrade(profile):
    current = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"),
        clipping_algorithm="semantic_windowed",
        clip_profile=profile,
    )
    raw = current.model_dump(mode="json")
    # Author the historical V7 fixture with its original prompts; new mini requests
    # now intentionally select V13 and must not be relabeled as historical snapshots.
    raw.pop("semantic_lineage_contract", None)
    raw.pop("semantic_transport_contract", None)
    raw.pop("semantic_execution_contract", None)
    raw["semantic_result_schema_version"] = "4"
    if profile == ClipProfile.MINI_LESSON:
        for stage in (
            "discovery",
            "link_review",
            "topic_chain",
            "boundary_review",
            "global_review",
        ):
            prompt = load_semantic_topic_chain_prompt(stage, "general", profile)
            raw[f"semantic_{stage}_skill_version"] = f"{prompt.version}.{stage}"
            raw[f"semantic_{stage}_skill_sha256"] = prompt.sha256
        raw["editing_prompt_version"] = raw["semantic_discovery_skill_version"]
        raw["editing_prompt_sha256"] = raw["semantic_discovery_skill_sha256"]
    raw.pop("semantic_validation_contract")
    raw["schema_version"] = "7"
    old = _PipelineRunConfigV7.model_validate_json(json.dumps(raw))
    before = json.dumps(raw, sort_keys=True)
    restored = load_persisted_pipeline_config(raw, old.fingerprint)
    assert restored.schema_version == "8"
    assert restored.semantic_validation_contract == LEGACY_SEMANTIC_VALIDATION
    projected = restored.model_dump(mode="json")
    projected.pop("semantic_validation_contract")
    projected["schema_version"] = "7"
    assert projected == raw
    assert json.dumps(raw, sort_keys=True) == before
    assert current.semantic_validation_contract == CURRENT_SEMANTIC_VALIDATION
    assert current.fingerprint != restored.fingerprint


def test_v6_wire_remains_exact_and_v8_contract_is_fingerprint_bound():
    current = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"), clipping_algorithm="semantic_windowed"
    )
    raw = current.model_dump(mode="json")
    v6 = {key: raw[key] for key in _PipelineRunConfigV6.model_fields}
    v6["schema_version"] = "6"
    old = _PipelineRunConfigV6.model_validate_json(json.dumps(v6))
    assert load_persisted_pipeline_config(v6, old.fingerprint).semantic_validation_contract == (
        LEGACY_SEMANTIC_VALIDATION
    )
    assert load_persisted_pipeline_config(raw, current.fingerprint) == current
    raw["semantic_validation_contract"] = LEGACY_SEMANTIC_VALIDATION
    with pytest.raises(PipelineConfigInvalid, match="fingerprint"):
        load_persisted_pipeline_config(raw, current.fingerprint)
    raw["semantic_validation_contract"] = "unknown-contract"
    with pytest.raises(PipelineConfigInvalid):
        load_persisted_pipeline_config(raw, current.fingerprint)


@pytest.mark.parametrize(
    "stage", ["discovery", "link_review", "topic_chain", "boundary_review", "global_review"]
)
def test_validation_cache_settings_preserve_legacy_and_unaffected_stages(stage):
    settings = {"model": "fixture", "clip_profile": "mini_lesson"}
    old = semantic_validation_cache_settings(
        settings, stage=stage, contract=LEGACY_SEMANTIC_VALIDATION
    )
    new = semantic_validation_cache_settings(
        settings, stage=stage, contract=CURRENT_SEMANTIC_VALIDATION
    )
    assert old == settings
    if stage in {"boundary_review", "global_review"}:
        assert new == {**settings, "validation_contract": CURRENT_SEMANTIC_VALIDATION}
    else:
        assert new == settings
    assert "validation_contract" not in settings


def test_v8_missing_contract_is_not_silently_defaulted_on_persisted_load():
    current = pipeline_config_from_settings(Settings(_env_file=None, ai_provider="mock"))
    raw = current.model_dump(mode="json")
    raw.pop("semantic_validation_contract")
    fingerprint = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(PipelineConfigInvalid, match="incomplete"):
        load_persisted_pipeline_config(raw, fingerprint)
