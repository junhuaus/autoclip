from __future__ import annotations

import copy
import json
from importlib.resources import files

import pytest
from test_semantic_lineage import ledger_inputs
from test_semantic_profiles import _global_review

from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.semantic_lineage import build_lineage_ledger_v5
from liveclip.pipeline.semantic_profiles import (
    BoundaryReviewV4,
    ChainCandidateV4,
    GlobalReviewOutputV4,
    ProfileStatisticsV4,
    PublishStatusV4,
    ValidatedProfileResultV4,
    validate_profile_global_review_v4,
)
from liveclip.pipeline.semantic_runtime_v5 import (
    MiniLessonRoughArtifactV5,
    UnifiedSemanticResultV5,
    final_partition_v5,
    lineage_profile_v5,
    project_quality_v4,
)


@pytest.mark.parametrize(
    "name,model",
    [
        ("rough-artifact-v5.schema.json", MiniLessonRoughArtifactV5),
        ("final-result-v5.schema.json", UnifiedSemanticResultV5),
    ],
)
def test_frozen_runtime_schema_matches_exact_persisted_model(name, model):
    schema = json.loads(files("liveclip").joinpath("schemas/semantic_v5", name).read_text())
    assert schema == model.model_json_schema(mode="validation")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "5"


def mixed_result():
    values = ledger_inputs()
    units = tuple(unit for review in values["reviews"] for unit in review.candidates)
    candidates = tuple(project_quality_v4(ChainCandidateV4, unit) for unit in units)
    global_output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=tuple(
            _global_review(
                unit,
                score=90 if unit.candidate_id == "u1" else 80,
                publish_status=PublishStatusV4.MANUAL
                if unit.candidate_id == "u2"
                else PublishStatusV4.BLOCKED
                if unit.candidate_id == "u3"
                else PublishStatusV4.AUTO,
            )
            for unit in candidates
        ),
    )
    quality = validate_profile_global_review_v4(
        global_output,
        candidates=candidates,
        boundary_reviews=tuple(
            project_quality_v4(BoundaryReviewV4, boundary) for boundary in values["boundaries"]
        ),
        transcript=values["transcript"],
        profile=ClipProfile.MINI_LESSON,
        top_n=1,
        validation_contract="semantic-v4-quality-v2",
    )
    assert final_partition_v5(quality) == values["partition"]
    ledger = build_lineage_ledger_v5(**{**values, "partition": final_partition_v5(quality)})
    return UnifiedSemanticResultV5(
        run_id="a" * 32,
        project_id="b" * 32,
        config_fingerprint="c" * 64,
        source_hash="d" * 64,
        run_metadata={},
        profiles={ClipProfile.MINI_LESSON: lineage_profile_v5(quality, ledger)},
        lineage=ledger,
        candidate_slot_map={unit.candidate_id: "slot_" + unit.candidate_id for unit in units},
        persistent_candidate_ids={
            unit.candidate_id: f"{index:032x}" for index, unit in enumerate(units, 1)
        },
        global_review=global_output,
        stage_audits={},
    )


def test_actual_quality_partition_survives_full_many_to_many_v5_roundtrip():
    result = mixed_result()
    restored = UnifiedSemanticResultV5.model_validate_json(result.model_dump_json())
    assert restored == result
    assert restored.lineage.counts.originals == 3
    assert restored.lineage.counts.units == 5
    assert restored.lineage.counts.chain_new_units == 1
    assert [
        len(getattr(restored.lineage.partition, field))
        for field in ("selected", "manual", "blocked", "rejected", "top_n_excluded")
    ] == [1, 1, 1, 1, 1]
    original_a = next(
        item for item in restored.lineage.originals if item.original.candidate_id == "A"
    )
    assert {path.disposition for path in original_a.paths} == {"selected", "manual", "blocked"}
    assert all(
        item.authority.risks and item.boundary.risk_treatments for item in restored.lineage.outcomes
    )
    stats = restored.profiles[ClipProfile.MINI_LESSON].statistics
    assert stats.original_candidate_count == 3 and stats.derived_unit_count == 4
    assert "discovery_candidate_count" not in stats.model_dump()


@pytest.mark.parametrize(
    "fault",
    [
        "missing_origin",
        "missing_outcome",
        "wrong_partition",
        "wrong_group",
        "wrong_count",
        "missing_slot",
        "slot_collision",
        "missing_persistent_id",
        "id_collision",
        "global_missing",
        "global_changed",
        "global_duplicate",
    ],
)
def test_saved_v5_result_rejects_inconsistent_accounting(fault):
    raw = copy.deepcopy(mixed_result().model_dump(mode="json"))
    if fault == "missing_origin":
        raw["lineage"]["outcomes"][0]["unit"]["original_candidate_ids"] = []
    elif fault == "missing_outcome":
        raw["lineage"]["outcomes"].pop()
    elif fault == "wrong_partition":
        raw["profiles"]["mini_lesson"]["selected"] = []
    elif fault == "wrong_group":
        raw["profiles"]["mini_lesson"]["selected"][0]["disposition"] = "manual"
    elif fault == "wrong_count":
        raw["profiles"]["mini_lesson"]["statistics"]["original_candidate_count"] = 5
    elif fault == "missing_slot":
        raw["candidate_slot_map"].pop("u1")
    elif fault == "slot_collision":
        raw["candidate_slot_map"]["u2"] = raw["candidate_slot_map"]["u1"]
    elif fault == "missing_persistent_id":
        raw["persistent_candidate_ids"].pop("u1")
    elif fault == "id_collision":
        raw["persistent_candidate_ids"]["u2"] = raw["persistent_candidate_ids"]["u1"]
    elif fault == "global_missing":
        raw["global_review"] = None
    elif fault == "global_changed":
        raw["global_review"]["reviews"][0]["title"] = "Changed after selection"
    else:
        raw["global_review"]["reviews"].append(raw["global_review"]["reviews"][0])
    with pytest.raises(ValueError):
        UnifiedSemanticResultV5.model_validate_json(json.dumps(raw))


def test_zero_candidate_result_has_explicit_zero_lineage_and_no_global_call():
    values = ledger_inputs()
    empty = type(values["partition"])(
        selected=(), manual=(), blocked=(), rejected=(), top_n_excluded=()
    )
    ledger = build_lineage_ledger_v5(
        batches=(),
        chains=(),
        reviews=(),
        boundaries=(),
        partition=empty,
        transcript=values["transcript"],
    )
    quality = ValidatedProfileResultV4(
        statistics=ProfileStatisticsV4(
            discovery_candidate_count=0,
            boundary_candidate_count=0,
            qualified_before_top_n=0,
            selected_count=0,
            manual_count=0,
            blocked_count=0,
            rejected_count=0,
            top_n_excluded_count=0,
        )
    )
    result = UnifiedSemanticResultV5(
        run_id="a" * 32,
        project_id="b" * 32,
        config_fingerprint="c" * 64,
        source_hash="d" * 64,
        run_metadata={},
        profiles={ClipProfile.MINI_LESSON: lineage_profile_v5(quality, ledger)},
        lineage=ledger,
        candidate_slot_map={},
        persistent_candidate_ids={},
        global_review=None,
        stage_audits={},
    )
    assert UnifiedSemanticResultV5.model_validate_json(result.model_dump_json()) == result
    assert not any(result.lineage.counts.model_dump().values())


@pytest.mark.parametrize("fault", ["window", "ownership"])
def test_stage_cache_keeps_local_ids_and_revalidates_rehashed_context(tmp_path, fault):
    from types import SimpleNamespace

    from test_pipeline_lineage_config import mini_config
    from test_semantic_lineage import transcript
    from test_semantic_lineage_provider import Responses, case, provider, replace_fixture_ids

    from liveclip.application.pipeline import LeaseIdentity, StageWork
    from liveclip.application.stage_execution import StageMutationFence
    from liveclip.domain.state_transitions import PipelineStage
    from liveclip.pipeline.semantic_cache import _canonical_sha256
    from liveclip.pipeline.semantic_lineage import validate_discovery_batch_v5
    from liveclip.pipeline.stage_handlers import PipelineStageHandlers
    from liveclip.providers.llm.semantic_lineage import prepare_lineage_context

    payload, output, prompts = case("discovery")
    responses = Responses([output.model_dump_json()])
    llm = provider(prompts, responses)
    context = prepare_lineage_context(payload, type(output), prompts=prompts)
    assert context is not None
    validations = []

    def validate(value):
        validations.append(value)
        return validate_discovery_batch_v5(
            value,
            expected_batch_id=context.batch_id,
            expected_context=context.batch_context,
            expected_ownership=context.ownership,
            expected_windows=context.windows,
            transcript=transcript(),
        )

    config = mini_config()
    handler = PipelineStageHandlers(
        data_dir=tmp_path,
        allowed_media_roots=(tmp_path,),
        assets=None,
        state=SimpleNamespace(record_provider_calls=lambda *args, **kwargs: None),
    )
    project = tmp_path / ("b" * 32)

    def invoke(generation):
        work = StageWork(
            task_id="c" * 32,
            stage_run_id="d" * 32,
            run_id=f"{generation:032x}",
            project_id="b" * 32,
            stage=PipelineStage.CANDIDATES,
            source_path=tmp_path / "source.mp4",
            config=config,
            input_fingerprint="e" * 64,
            generation=generation,
            revision_epoch=0,
            already_succeeded=False,
            cancellation_requested=False,
        )
        fence = StageMutationFence(
            lease=LeaseIdentity(task_id=work.task_id, worker_id="fixture", lease_token="f" * 64),
            project_id=work.project_id,
            run_id=work.run_id,
            stage_run_id=work.stage_run_id,
            generation=generation,
        )
        return handler._run_v4_requests(
            work,
            fence=fence,
            project_dir=project,
            generation_dir=project / f"runs/g{generation:03d}",
            stage="discovery",
            provider=llm,
            response_model=type(output),
            requests=((output.batch_id, payload, validate),),
            cancel_requested=lambda: False,
        )

    first, initial = invoke(1)
    repeated, replay = invoke(1)
    reused, later = invoke(2)
    assert first == repeated == reused == {output.batch_id: output}
    assert (
        initial["cache_hit_count"] == 0
        and replay["cache_hit_count"] == later["cache_hit_count"] == 1
    )
    assert len(responses.calls) == 1 and len(validations) == 3
    cache = next((project / "runs/g001/semantic-cache/discovery").glob("*.json"))
    raw = json.loads(cache.read_text())
    if fault == "window":
        old = raw["output"]["logical_windows"][0]["logical_window_id"]
        raw["output"] = replace_fixture_ids(raw["output"], {old: "renamed"})
    else:
        raw["output"]["ownership_interval"]["end_ms"] -= 1
    raw["output_sha256"] = _canonical_sha256(raw["output"])
    cache.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="immutable_request_mismatch"):
        invoke(3)
    assert len(responses.calls) == 1
