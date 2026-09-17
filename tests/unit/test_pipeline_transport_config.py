from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineConfig,
    PipelineConfigInvalid,
    PipelineRunConfig,
    PipelineRunConfigV9,
    PipelineRunConfigV10,
    PipelineRunConfigV11,
    PipelineService,
    StageWork,
    load_persisted_pipeline_config,
)
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.clipping_skills.semantic_windowed_v1 import load_semantic_windowed_discovery_prompt
from liveclip.config import Settings
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.semantic_validation import CURRENT_SEMANTIC_TRANSPORT as CONTRACT
from liveclip.pipeline.semantic_cache import semantic_stage_cache_key
from liveclip.pipeline.semantic_global import DiscoveryOutput
from liveclip.pipeline.stage_handlers import PipelineStageHandlers, _semantic_model_settings


def config(profile):
    current = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"),
        clipping_algorithm="semantic_windowed",
        clip_profile=profile,
    )
    raw = current.model_dump(mode="json")
    raw.pop("semantic_execution_contract")
    mini = profile == ClipProfile.MINI_LESSON
    raw["schema_version"] = "11" if mini else "10"
    model = PipelineRunConfigV11 if mini else PipelineRunConfigV10
    return model.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_new_versions_add_exactly_one_field_and_preserve_historical_snapshot(profile):
    current = config(profile)
    mini = profile == ClipProfile.MINI_LESSON
    old_model = PipelineRunConfigV9 if mini else PipelineRunConfig
    assert type(current) is (PipelineRunConfigV11 if mini else PipelineRunConfigV10)
    assert current.semantic_transport_contract == CONTRACT
    assert set(type(current).model_fields) == set(old_model.model_fields) | {
        "semantic_transport_contract"
    }
    raw = current.model_dump(mode="json")
    assert TypeAdapter(PipelineConfig).validate_json(json.dumps(raw)) == current
    assert load_persisted_pipeline_config(raw, current.fingerprint) == current
    raw.pop("semantic_transport_contract")
    raw["schema_version"] = "9" if mini else "8"
    historical = old_model.model_validate_json(json.dumps(raw))
    assert (
        load_persisted_pipeline_config(raw, historical.fingerprint).model_dump(mode="json") == raw
    )
    assert historical.fingerprint != current.fingerprint
    assert "semantic_transport_contract" not in type(historical).model_fields


@pytest.mark.parametrize("profile", list(ClipProfile))
@pytest.mark.parametrize("mutation", ["missing", "unknown", "downgrade"])
def test_persisted_transport_cannot_be_injected_removed_or_relabelled(profile, mutation):
    current = config(profile)
    raw = current.model_dump(mode="json")
    if mutation == "missing":
        raw.pop("semantic_transport_contract")
    elif mutation == "unknown":
        raw["semantic_transport_contract"] = "future"
    else:
        raw["schema_version"] = "9" if profile == ClipProfile.MINI_LESSON else "8"
    with pytest.raises(PipelineConfigInvalid):
        load_persisted_pipeline_config(raw, current.fingerprint)


def test_v10_cannot_skip_mini_lineage_contract():
    current = config(ClipProfile.MINI_LESSON).model_dump(mode="json")
    current.pop("semantic_lineage_contract")
    current["schema_version"] = "10"
    current["semantic_result_schema_version"] = "4"
    with pytest.raises(ValidationError):
        PipelineRunConfigV10.model_validate_json(json.dumps(current))


@pytest.mark.parametrize("profile", [ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON])
@pytest.mark.parametrize("import_only", [False, True])
def test_new_transport_survives_sqlite_import_lease_and_stagework(tmp_path, profile, import_only):
    engine = create_sqlite_engine(tmp_path / "transport.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    current = config(profile)
    try:
        method = service.import_project if import_only else service.create_project_and_run
        created = method(source_path=tmp_path / "input.mp4", config=current, max_stage_retries=1)
        lease = SQLiteTaskQueue(engine, lease_seconds=30).claim(
            worker_id="transport-config",
            pipeline_run_id=created.run_id,
        )
        work = repository.start_or_resume_stage(
            LeaseIdentity(
                task_id=lease.task_id,
                worker_id=lease.worker_id,
                lease_token=lease.lease_token,
            )
        )
        restored = StageWork.model_validate_json(work.model_dump_json())
        assert restored.config.semantic_transport_contract == CONTRACT
        assert restored.config.schema_version == current.schema_version
        assert restored.config.run_scope == ("import" if import_only else "full")
        assert restored.config.fingerprint == work.config.fingerprint
    finally:
        engine.dispose()


def test_shared_provider_factory_and_all_stage_cache_keys_bind_transport_and_budget():
    current = config(ClipProfile.SHORT_HIGHLIGHT)
    raw = current.model_dump(mode="json")
    raw.pop("semantic_transport_contract")
    raw["schema_version"] = "8"
    old = PipelineRunConfig.model_validate_json(json.dumps(raw))
    handlers = object.__new__(PipelineStageHandlers)
    prompt = load_semantic_windowed_discovery_prompt("general")
    keys = []
    for value in (
        old,
        current,
        current.model_copy(update={"semantic_full_context_budget_ratio": 0.6}),
    ):
        work = SimpleNamespace(config=value)
        provider = handlers._structured_provider(work, prompt)
        settings = _semantic_model_settings(work, provider)
        if value is old:
            assert provider._transport_contract is None
            assert "semantic_transport_contract" not in settings
            assert "full_context_budget_ratio" not in settings
        else:
            assert (
                provider._transport_contract == settings["semantic_transport_contract"] == CONTRACT
            )
            assert (
                provider._semantic_budget.full_context_budget_ratio
                == settings["full_context_budget_ratio"]
            )
        keys.append(
            tuple(
                semantic_stage_cache_key(
                    stage=stage,
                    payload={"cues": []},
                    provider=provider,
                    model_settings=settings,
                    output_model=DiscoveryOutput,
                )
                for stage in (
                    "discovery",
                    "link_review",
                    "topic_chain",
                    "boundary_review",
                    "global_review",
                )
            )
        )
    assert all(len({row[index] for row in keys}) == 3 for index in range(5))


def test_new_transport_preserves_configured_budget_even_with_legacy_validator():
    current = config(ClipProfile.SHORT_HIGHLIGHT).model_copy(
        update={
            "semantic_validation_contract": "semantic-v4-validation-v1",
            "semantic_model_context_tokens": 256_000,
            "semantic_full_context_budget_ratio": 0.6,
        }
    )
    provider = object.__new__(PipelineStageHandlers)._structured_provider(
        SimpleNamespace(config=current),
        load_semantic_windowed_discovery_prompt("general"),
    )
    assert provider._semantic_budget.model_context_tokens == 256_000
    assert provider._semantic_budget.full_context_budget_ratio == 0.6
    assert provider._transport_contract == CONTRACT


@pytest.mark.parametrize("profile", [ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON])
def test_stage_domain_repair_retains_complete_errors_and_authority(tmp_path, profile):
    from test_semantic_lineage_provider import case

    from liveclip.application.stage_execution import StageMutationFence
    from liveclip.domain.state_transitions import PipelineStage
    from liveclip.providers.llm.structured import MockStructuredLLMProvider, StructuredCallResult

    payload, output, prompt = case("discovery")
    errors = " | ".join(f"error_{index}: " + "完整错误" * 400 for index in range(225))
    calls = []

    class Provider(MockStructuredLLMProvider):
        def generate(self, **kwargs):
            return StructuredCallResult(output=output, call_records=(), repaired=False)

        def repair(self, **kwargs):
            calls.append(kwargs)
            return StructuredCallResult(output=output, call_records=(), repaired=True)

    current = (
        config(profile).model_copy(
            update={"semantic_validation_contract": "semantic-v4-validation-v1"}
        )
        if profile == ClipProfile.SHORT_HIGHLIGHT
        else config(profile)
    )
    handler = PipelineStageHandlers(
        data_dir=tmp_path,
        allowed_media_roots=(tmp_path,),
        assets=None,
        state=SimpleNamespace(record_provider_calls=lambda *args, **kwargs: None),
    )
    work = StageWork(
        task_id="a" * 32,
        stage_run_id="b" * 32,
        run_id="c" * 32,
        project_id="d" * 32,
        stage=PipelineStage.CANDIDATES,
        source_path=tmp_path / "input.mp4",
        config=current,
        input_fingerprint="e" * 64,
        generation=1,
        revision_epoch=0,
        already_succeeded=False,
        cancellation_requested=False,
    )
    fence = StageMutationFence(
        lease=LeaseIdentity(task_id=work.task_id, worker_id="fixture", lease_token="f" * 64),
        project_id=work.project_id,
        run_id=work.run_id,
        stage_run_id=work.stage_run_id,
        generation=1,
    )

    def validate(value):
        if not calls:
            raise ValueError(errors)
        return value

    resolved, audit = handler._run_v4_requests(
        work,
        fence=fence,
        project_dir=tmp_path / work.project_id,
        generation_dir=tmp_path / work.project_id / "runs/g001",
        stage="discovery",
        provider=Provider(prompts=prompt, model_name="fixture"),
        response_model=type(output),
        requests=((output.batch_id, payload, validate),),
        cancel_requested=lambda: False,
    )
    assert resolved == {output.batch_id: output} and len(calls) == 1
    assert calls[0]["validation_errors"] == (errors,)
    assert calls[0]["payload"]["validation_errors"] == [errors]
    assert calls[0]["payload"]["immutable_request"] == payload
    assert audit["validation_events"][0]["error"] == errors


def test_v3_stage_repair_keeps_historical_shape_and_full_new_request():
    from test_semantic_lineage_provider import case

    from liveclip.pipeline.semantic_global import semantic_repair_payload
    from liveclip.pipeline.stage_handlers import _semantic_error_detail, _semantic_repair_request

    payload, output, _ = case("discovery")
    payload["outside_old_repair_projection"] = {"source_ids": ["source_999"], "risk": "保留"}
    error = ValueError("完整错误" * 500)
    current = config(ClipProfile.SHORT_HIGHLIGHT)
    old_raw = current.model_dump(mode="json")
    old_raw.pop("semantic_transport_contract")
    old_raw["schema_version"] = "8"
    old = PipelineRunConfig.model_validate_json(json.dumps(old_raw))
    for value in (old, current):
        work = SimpleNamespace(config=value)
        detail = _semantic_error_detail(work, error, legacy_limit=240)
        result = _semantic_repair_request(work, payload, output, validation_errors=(detail,))
        if value is old:
            assert len(detail) == 240
            assert result == semantic_repair_payload(payload, output, validation_errors=(detail,))
        else:
            assert detail == str(error)
            assert result["immutable_request"] == payload
            assert result["invalid_output"] == output.model_dump(mode="json")
            assert result["validation_errors"] == [str(error)]
