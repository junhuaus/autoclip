from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from liveclip.application.pipeline import (
    PipelineRunConfigV10,
    PipelineRunConfigV11,
    PipelineService,
)
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import ApiUsageRow, AssetRow, StageRunRow, TaskAttemptRow, TaskRow
from liveclip.db.pipeline_repository import DeterministicRetryRejected, SqlAlchemyPipelineRepository
from liveclip.db.semantic_units import SqlAlchemySemanticInvocationStore
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.state_transitions import AssetStatus, PipelineRunStatus, PipelineStage
from liveclip.pipeline import stage_handlers as stage_module
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.providers.llm import structured as structured_module
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus
from liveclip.services.demo_media import create_demo_source


def execution_config(settings, *, bounded, **kwargs):
    current = pipeline_config_from_settings(settings, **kwargs)
    if bounded:
        return current
    raw = current.model_dump(mode="json")
    raw.pop("semantic_execution_contract")
    mini = current.clip_profile == ClipProfile.MINI_LESSON
    raw["schema_version"] = "11" if mini else "10"
    model = PipelineRunConfigV11 if mini else PipelineRunConfigV10
    return model.model_validate_json(json.dumps(raw))


@pytest.mark.integration
@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize(
    "profile, mixed, path",
    [
        (profile, mixed, "existing")
        for profile in ClipProfile
        for mixed in (
            None,
            ("initial", False),
            ("initial", True),
            ("repair", False),
            ("repair", True),
        )
    ]
    + [
        (ClipProfile.SHORT_HIGHLIGHT, (phase, first), path)
        for path in ("discovery", "bridge")
        for phase in ("initial", "repair")
        for first in (False, True)
    ],
)
def test_initial_budget_is_durable_deterministic_and_never_retried(
    tmp_path, monkeypatch, profile, mixed, path, bounded
):
    completed = []
    original_calls = []
    mixed_calls = []
    provider_metadata = {}

    class Output(BaseModel):
        value: str

    # Release the second request only after the first failure was consumed by the
    # real aggregator. Both actual completion orders are deterministic without sleeps.
    release_second = Event()
    as_completed = stage_module.as_completed

    def ordered_completions(pending):
        for future in as_completed(pending):
            try:
                yield future
            finally:
                if len(pending) == 2:
                    release_second.set()

    if mixed and not bounded:
        monkeypatch.setattr(stage_module, "as_completed", ordered_completions)
    elif mixed:
        complete = SqlAlchemySemanticInvocationStore.complete

        def ordered_commit(self, fence, invocation, **values):
            result = complete(self, fence, invocation, **values)
            if invocation.subject_id.rsplit(".", 1)[-1].lstrip("0") == "1":
                release_second.set()
            return result

        monkeypatch.setattr(SqlAlchemySemanticInvocationStore, "complete", ordered_commit)

    def mixed_generate(**kwargs):
        index = int(kwargs["subject_id"].rsplit(".", 1)[-1]) - 1
        if index == 1:
            assert release_second.wait(10), "first failure was not consumed"
        phase, budget_first = mixed
        budget = index == (0 if budget_first else 1)
        code = f"STRUCTURED_{'INPUT' if phase == 'initial' else 'REPAIR'}_BUDGET_EXCEEDED"
        code = code if budget else "PROVIDER_TIMEOUT"
        records = ()
        if not budget or phase == "repair":
            record = ProviderCallRecord(
                call_id=str(index + 1) * 32,
                operation_key=str(index + 1) * 64,
                subject_id=kwargs["subject_id"],
                provider="mock",
                model=provider_metadata["model"] if bounded else "fixture",
                operation=(
                    f"responses.semantic.{kwargs['subject_id'].split('.')[1]}.initial"
                    if bounded
                    else "responses.semantic.discovery"
                ),
                prompt_version=(
                    f"{provider_metadata['version']}.{kwargs['subject_id'].split('.')[1]}"
                    if bounded
                    else None
                ),
                prompt_sha256=provider_metadata.get("sha") if bounded else None,
                request_count=1,
                retry_count=0,
                latency_ms=1,
                status=ProviderCallStatus.FAILED,
                failure_code="STRUCTURED_OUTPUT_INVALID" if budget else code,
                called_at=datetime.now(UTC),
            )
            original_calls.append(record.call_id)
            mixed_calls.append(record.call_id)
            records = (record,)
        completed.append(code)
        raise structured_module.StructuredProviderError(
            code,
            records,
            repair_attempts=(
                {
                    "phase": phase + "_budget" if budget else "initial",
                    "semantic_stage": "discovery",
                    "failure_code": code,
                    "validation_errors": [f"error-{i}" for i in range(225)],
                    "estimated_total_tokens": 2,
                    "budget_tokens": 1,
                    "provider_call_executed": not budget,
                },
            ),
        )

    if path in {"discovery", "bridge"}:
        planner = stage_module.plan_semantic_windowed_input
        bridge_units = []

        def two_requests(*args, **kwargs):
            plan = planner(*args, **kwargs)
            units = tuple(plan.units[0].model_copy(update={"unit_id": str(i)}) for i in (1, 2))
            bridge_units.extend(units)
            return plan.model_copy(update={"units": units}) if path == "discovery" else plan

        monkeypatch.setattr(stage_module, "plan_semantic_windowed_input", two_requests)
        monkeypatch.setattr(
            stage_module, "plan_boundary_bridge_units", lambda *a, **k: tuple(bridge_units)
        )

    class OversizedInstructions(PipelineStageHandlers):
        def _candidates(self, work, lease, cancel_requested):
            if not mixed or path in {"discovery", "bridge"}:
                return super()._candidates(work, lease, cancel_requested)
            project_dir = stage_module.project_directory(self._data_dir, work.project_id)
            generation_dir = project_dir / "runs/g001"
            fence = stage_module._mutation_fence(work, lease)
            prompts = stage_module.load_semantic_global_v3_boundary_prompt(
                work.config.semantic_profile
            )
            provider = super()._structured_provider(work, prompts)
            provider_metadata.update(
                model=provider.model_name,
                version=provider.prompt_version,
                sha=provider.prompt_sha256,
            )
            monkeypatch.setattr(provider, "generate", mixed_generate)
            if profile == ClipProfile.MINI_LESSON:
                return self._run_v4_requests(
                    work,
                    fence=fence,
                    project_dir=project_dir,
                    generation_dir=generation_dir,
                    stage="discovery",
                    provider=provider,
                    response_model=Output,
                    requests=tuple((str(i), {"index": i}, lambda value: value) for i in (1, 2)),
                    cancel_requested=cancel_requested,
                )
            monkeypatch.setattr(self, "_structured_provider", lambda *args: provider)
            monkeypatch.setattr(
                stage_module,
                "build_boundary_review_payload_v3",
                lambda *args, **kwargs: {"index": kwargs["output_index"]},
            )
            monkeypatch.setattr(stage_module, "boundary_review_response_model_v3", lambda _: Output)
            return self._boundary_reviews_v3(
                work,
                fence=fence,
                project_dir=project_dir,
                generation_dir=generation_dir,
                transcript=None,
                discovery_outputs=(None, None),
                semantic_config=stage_module._semantic_global_config(work),
                cancel_requested=cancel_requested,
            )

        def _structured_provider(self, work, prompts):
            if path in {"discovery", "bridge"}:
                provider = super()._structured_provider(work, prompts)
                generate = provider.generate
                provider_metadata.update(
                    model=provider.model_name,
                    version=provider.prompt_version,
                    sha=provider.prompt_sha256,
                )

                def generate_or_fail(**kwargs):
                    if kwargs["subject_id"].rsplit(".", 1)[-1] in {"1", "2"}:
                        return mixed_generate(**kwargs)
                    result = generate(**kwargs)
                    original_calls.extend(record.call_id for record in result.call_records)
                    return result

                monkeypatch.setattr(provider, "generate", generate_or_fail)
                return provider
            return super()._structured_provider(
                work, replace(prompts, instructions=prompts.instructions + "完整指令 " * 30_000)
            )

    model_calls = []

    def forbidden_response(*args, **kwargs):
        if path == "bridge":
            payload, model = args
            assert model is stage_module.DiscoveryOutput
            return {
                "source_id": payload["source_id"],
                "source_range": payload["source_range"],
                "topic_units": [
                    {
                        "topic_id": "base-topic",
                        **payload["source_range"],
                        "summary": "Synthetic setup for bridge failure",
                        "value_density": "low",
                        "candidate_status": "no_candidate",
                        "no_candidate_reason_code": "no_general_value",
                    }
                ],
                "candidates": [],
            }
        model_calls.append(True)
        raise AssertionError("budget rejection must precede Mock response generation")

    monkeypatch.setattr(structured_module, "_mock_payload", forbidden_response)
    source = tmp_path / "media/source.mp4"
    create_demo_source(output_path=source, duration_ms=12_000)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    engine = create_sqlite_engine(tmp_path / "budget.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    config = execution_config(
        Settings(_env_file=None, ai_provider="mock"),
        bounded=bounded,
        clipping_algorithm="semantic_windowed",
        clip_profile=profile,
    )
    data_dir = tmp_path / "projects"
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        heartbeat_seconds=5,
        handler=OversizedInstructions(
            data_dir=data_dir,
            allowed_media_roots=(source.parent,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
    )
    try:
        created = service.create_project_and_run(
            source_path=source, config=config, max_stage_retries=3
        )
        result = runner.run_until_terminal(created.run_id, worker_id="budget-fixture")
        assert result.status == PipelineRunStatus.FAILED
        expected_code = (
            "CANDIDATES_REPAIR_BUDGET_EXCEEDED"
            if mixed and mixed[0] == "repair"
            else "CANDIDATES_INPUT_BUDGET_EXCEEDED"
        )
        assert result.error_code == expected_code
        assert (
            "no repair call ran" if mixed and mixed[0] == "repair" else "no model call ran"
        ) in result.safe_error_message
        assert not model_calls
        with engine.connect() as connection:
            stage = (
                connection.execute(
                    select(StageRunRow.__table__).where(
                        StageRunRow.pipeline_run_id == created.run_id,
                        StageRunRow.stage == PipelineStage.CANDIDATES.value,
                    )
                )
                .mappings()
                .one()
            )
            task = (
                connection.execute(
                    select(TaskRow.__table__).where(
                        TaskRow.stage_run_id == stage["id"],
                    )
                )
                .mappings()
                .one()
            )
            attempts = (
                connection.execute(
                    select(TaskAttemptRow.__table__).where(
                        TaskAttemptRow.task_id == task["id"],
                    )
                )
                .mappings()
                .all()
            )
            assert stage["failure_class"] == task["failure_class"] == "deterministic"
            assert stage["retry_count"] == task["retry_count"] == 0
            assert len(attempts) == task["attempt_count"] == 1
            assert connection.scalar(
                select(func.count())
                .select_from(ApiUsageRow)
                .where(ApiUsageRow.operation.like("responses.semantic.%"))
            ) == len(original_calls)
            diagnostic = attempts[0]["diagnostic_relative_path"]
            assert diagnostic and diagnostic.startswith(".attempts/")
            asset = (
                connection.execute(
                    select(AssetRow.__table__).where(
                        AssetRow.project_id == created.project_id,
                        AssetRow.relative_path == diagnostic,
                        AssetRow.status == AssetStatus.COMMITTED.value,
                    )
                )
                .mappings()
                .one()
            )
            assert asset["producer_attempt_id"] == attempts[0]["id"]
        raw = (data_dir / created.project_id / diagnostic).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == asset["sha256"]
        audit = json.loads(raw)
        if bounded or profile == ClipProfile.MINI_LESSON:
            assert audit["audit_contract"] == "semantic-failure-audit-v1"
            failure_path = audit["failed_subjects"][0]["relative_path"]
            subjects = [
                json.loads((data_dir / created.project_id / item["relative_path"]).read_bytes())
                for item in audit["failed_subjects"]
            ]
            audit = json.loads((data_dir / created.project_id / failure_path).read_bytes())
            if mixed:
                assert len(subjects) == 2
                audit = {
                    "provider_attempts": [
                        a for item in subjects for a in item["provider_attempts"]
                    ],
                    "call_ids": [cid for item in subjects for cid in item["call_ids"]],
                }
        else:
            assert audit["audit_contract"] == "semantic-budget-audit-v1"
        budget = next(
            item
            for item in audit["provider_attempts"]
            if item.get("phase") == (mixed[0] if mixed else "initial") + "_budget"
        )
        assert budget["semantic_stage"] == "discovery"
        if mixed:
            budget_code = (
                "STRUCTURED_"
                + ("INPUT" if mixed[0] == "initial" else "REPAIR")
                + "_BUDGET_EXCEEDED"
            )
            assert completed == (
                [budget_code, "PROVIDER_TIMEOUT"] if mixed[1] else ["PROVIDER_TIMEOUT", budget_code]
            )
            assert {
                item["failure_code"]
                for item in audit["provider_attempts"]
                if "failure_code" in item
            } == set(completed)
            assert all(
                len(item["validation_errors"]) == 225
                for item in audit["provider_attempts"]
                if "validation_errors" in item
            )
        assert budget["estimated_total_tokens"] > budget["budget_tokens"]
        assert budget["provider_call_executed"] is False and sorted(audit["call_ids"]) == sorted(
            mixed_calls if bounded and path == "bridge" else original_calls
        )
        if bounded:
            from liveclip.db.models import SemanticUnitInvocationRow

            with engine.connect() as connection:
                journal = (
                    connection.execute(
                        select(SemanticUnitInvocationRow).where(
                            SemanticUnitInvocationRow.pipeline_run_id == created.run_id,
                        )
                    )
                    .mappings()
                    .all()
                )
            saved_calls = []
            for invocation in journal:
                outcome_bytes = (
                    data_dir / created.project_id / invocation["outcome_relative_path"]
                ).read_bytes()
                assert hashlib.sha256(outcome_bytes).hexdigest() == invocation["outcome_sha256"]
                envelope = json.loads(outcome_bytes)
                assert envelope["config_fingerprint"] == config.fingerprint
                saved_calls.extend(call["call_id"] for call in envelope["outcome"]["call_records"])
            # The failed-subject audit and successful earlier bridge setup have
            # distinct immutable outcomes; every actual call remains authenticated.
            assert sorted(saved_calls) == sorted(original_calls)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        with pytest.raises(DeterministicRetryRejected):
            service.retry(created.run_id)
        assert service.get_run(created.run_id).error_code == expected_code
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize(
    "case,algorithm,profile",
    [
        ("planning", "semantic_global", ClipProfile.SHORT_HIGHLIGHT),
        ("planning", "semantic_windowed", ClipProfile.SHORT_HIGHLIGHT),
        ("planning", "semantic_windowed", ClipProfile.MINI_LESSON),
        ("global_planning", "semantic_windowed", ClipProfile.SHORT_HIGHLIGHT),
        ("domain_discovery", "semantic_global", ClipProfile.SHORT_HIGHLIGHT),
        ("domain_global", "semantic_windowed", ClipProfile.SHORT_HIGHLIGHT),
    ],
)
def test_actual_planning_and_serial_domain_repair_keep_attempt_audit(
    tmp_path, monkeypatch, case, algorithm, profile, bounded
):
    from liveclip.providers.asr.mock import MockASRProvider, MockScriptSegment

    target_stage = PipelineStage.EDIT if "global" in case else PipelineStage.CANDIDATES
    semantic_stage = "global_review" if "global" in case else "discovery"
    original_outputs = []
    target_calls = []
    target_constructions = []
    all_calls = []
    full_validation = " | ".join(f"business-error-{i}:" + "完整错误" * 8 for i in range(225))
    if case.startswith("domain"):

        def invalid_business_output(*args, **kwargs):
            raise ValueError(full_validation)

        monkeypatch.setattr(
            stage_module,
            "validate_global_review_v3" if case == "domain_global" else "validate_discovery_output",
            invalid_business_output,
        )

    original_config = stage_module._semantic_global_config
    if case == "global_planning":

        def planning_config(work):
            config = original_config(work)
            if work.stage == target_stage:
                return config.model_copy(update={"model_context_tokens": 32_768})
            return config

        monkeypatch.setattr(stage_module, "_semantic_global_config", planning_config)
        # Exercise the actual Global builder with a complete oversized trusted prompt.
        load_prompt = stage_module.load_installed_global_review_prompt
        monkeypatch.setattr(
            stage_module,
            "load_installed_global_review_prompt",
            lambda *a, **k: replace(load_prompt(*a, **k), instructions="完整全局指令 " * 8_000),
        )

    class BudgetHandlers(PipelineStageHandlers):
        def _asr_provider(self, work):
            if case == "planning":
                return MockASRProvider(
                    tuple(
                        MockScriptSegment(
                            script_id=f"rich_{i}",
                            source_start_ms=i * 300,
                            source_end_ms=(i + 1) * 300,
                            text="声乐教学内容与练习条件" * 200,
                        )
                        for i in range(40)
                    )
                )
            return super()._asr_provider(work)

        def _structured_provider(self, work, prompts):
            is_target = work.stage == target_stage and prompts.stage == semantic_stage
            if is_target:
                target_constructions.append(prompts.stage)
            if is_target and case.startswith("domain"):
                prompts = replace(prompts, repair=prompts.repair + "完整修复指令 " * 30_000)
            provider = super()._structured_provider(work, prompts)
            generate = provider.generate

            def observed_generate(**kwargs):
                result = generate(**kwargs)
                all_calls.extend(record.call_id for record in result.call_records)
                if is_target:
                    target_calls.extend(record.call_id for record in result.call_records)
                    original_outputs.append(result.output.model_dump(mode="json"))
                return result

            monkeypatch.setattr(provider, "generate", observed_generate)
            return provider

    source = tmp_path / "media/source.mp4"
    create_demo_source(output_path=source, duration_ms=12_000)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    engine = create_sqlite_engine(tmp_path / "planning.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    config = execution_config(
        Settings(_env_file=None, ai_provider="mock"),
        bounded=bounded,
        clipping_algorithm=algorithm,
        clip_profile=profile,
    )
    if case == "planning":
        config = config.model_copy(update={"semantic_model_context_tokens": 32_768})
    elif "global" in case:
        config = config.model_copy(
            update={
                "minimum_clip_ms": 1_000,
                "maximum_clip_ms": 12_000,
                "semantic_target_clip_ms": 10_000,
            }
        )
    data_dir = tmp_path / "projects"
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        heartbeat_seconds=5,
        handler=BudgetHandlers(
            data_dir=data_dir,
            allowed_media_roots=(source.parent,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
    )
    try:
        created = service.create_project_and_run(
            source_path=source, config=config, max_stage_retries=3
        )
        result = runner.run_until_terminal(created.run_id, worker_id="planning-budget-fixture")
        suffix = "REPAIR" if case.startswith("domain") else "INPUT"
        expected = f"{target_stage.value.upper()}_{suffix}_BUDGET_EXCEEDED"
        assert result.status == PipelineRunStatus.FAILED
        assert result.error_code == expected
        with engine.connect() as conn:
            stage = (
                conn.execute(
                    select(StageRunRow.__table__).where(
                        StageRunRow.pipeline_run_id == created.run_id,
                        StageRunRow.stage == target_stage.value,
                    )
                )
                .mappings()
                .one()
            )
            task = (
                conn.execute(select(TaskRow.__table__).where(TaskRow.stage_run_id == stage["id"]))
                .mappings()
                .one()
            )
            attempts = (
                conn.execute(
                    select(TaskAttemptRow.__table__).where(TaskAttemptRow.task_id == task["id"])
                )
                .mappings()
                .all()
            )
            assert stage["failure_class"] == task["failure_class"] == "deterministic"
            assert stage["retry_count"] == task["retry_count"] == 0
            assert len(attempts) == task["attempt_count"] == 1
            diagnostic = attempts[0]["diagnostic_relative_path"]
            asset = (
                conn.execute(
                    select(AssetRow.__table__).where(
                        AssetRow.project_id == created.project_id,
                        AssetRow.relative_path == diagnostic,
                        AssetRow.status == AssetStatus.COMMITTED.value,
                    )
                )
                .mappings()
                .one()
            )
            assert asset["producer_attempt_id"] == attempts[0]["id"]
            assert conn.scalar(
                select(func.count())
                .select_from(ApiUsageRow)
                .where(ApiUsageRow.operation.like("responses.semantic.%"))
            ) == len(all_calls)
        raw = (data_dir / created.project_id / diagnostic).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == asset["sha256"]
        audit = json.loads(raw)
        if bounded and case.startswith("domain"):
            assert audit["audit_contract"] == "semantic-failure-audit-v1"
            assert len(audit["failed_subjects"]) == 1
            audit = json.loads(
                (
                    data_dir / created.project_id / audit["failed_subjects"][0]["relative_path"]
                ).read_bytes()
            )
            assert audit["audit_contract"] == "semantic-failure-audit-v1"
        else:
            assert audit["audit_contract"] == "semantic-budget-audit-v1"
        assert (
            audit["run_id"] == created.run_id and audit["config_fingerprint"] == config.fingerprint
        )
        assert audit["call_ids"] == target_calls
        budget = next(
            item
            for item in audit["provider_attempts"]
            if item.get("phase") == ("repair_budget" if suffix == "REPAIR" else "initial_budget")
        )
        assert budget["semantic_stage"] == semantic_stage
        assert budget["estimated_total_tokens"] > budget["budget_tokens"]
        if case.startswith("domain"):
            assert len(target_calls) == len(set(target_calls)) == 1
            validation = (
                audit
                if bounded
                else next(
                    item
                    for item in audit["provider_attempts"]
                    if item.get("phase") == "stage_validation"
                )
            )
            assert validation["agent_outputs"][0]["output"] == original_outputs[0]
            assert validation["validation_events"][0]["error"] == full_validation
            assert budget["repair_call_executed"] is False
        else:
            assert not target_constructions and not target_calls
            assert budget["measurement_basis"] == "semantic_planning_estimate"
            assert budget["provider_call_executed"] is False
            assert "for that request" in result.safe_error_message
        with pytest.raises(DeterministicRetryRejected):
            service.retry(created.run_id)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    finally:
        engine.dispose()
