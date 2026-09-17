from __future__ import annotations

import hashlib
import json

import pytest
from sqlalchemy import func, select, update

from liveclip.application.pipeline import PipelineRunConfigV9, PipelineRunConfigV11, PipelineService
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    ApiUsageRow,
    AssetRow,
    CandidateClipRow,
    EditPlanRevisionRow,
    RenderJobRow,
)
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.state_transitions import FailureClass, PipelineRunStatus, PipelineStage
from liveclip.pipeline.semantic_lineage import DiscoveryBatchOutputV5
from liveclip.pipeline.semantic_runtime_v5 import MiniLessonRoughArtifactV5, UnifiedSemanticResultV5
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.providers.llm.structured import MockStructuredLLMProvider, StructuredCallResult
from liveclip.services.demo_media import create_demo_source


@pytest.mark.integration
@pytest.mark.parametrize("version", ["9", "11", "13"])
def test_actual_lineage_zero_candidate_flow_completes_with_persisted_empty_ledger(
    tmp_path, version
):
    calls = []

    class EmptyDiscovery(MockStructuredLLMProvider):
        def generate(self, *, subject_id, payload, response_model, cancel_requested=lambda: False):
            assert response_model is DiscoveryBatchOutputV5
            calls.append(subject_id)
            raw = dict(
                schema_version="5",
                contract_version="semantic-v5-lineage-v1",
                batch_id=payload["batch_id"],
                batch_context=payload["batch_context"],
                ownership_interval=payload["ownership_interval"],
                candidates=[],
                topic_fragments=[],
                logical_windows=[
                    dict(
                        logical_window_id=window["logical_window_id"],
                        window_start_ms=window["start_ms"],
                        window_end_ms=window["end_ms"],
                        left_boundary={},
                        right_boundary={},
                        candidate_ids=[],
                        fragment_ids=[],
                    )
                    for window in payload["logical_windows"]
                ],
            )
            return StructuredCallResult(
                output=response_model.model_validate_json(json.dumps(raw)),
                call_records=(
                    super()
                    .generate(
                        subject_id=subject_id,
                        payload=payload,
                        response_model=response_model,
                        cancel_requested=cancel_requested,
                    )
                    .call_records
                    if version == "13"
                    else ()
                ),
                repaired=False,
            )

    class EmptyHandlers(PipelineStageHandlers):
        def _structured_provider(self, work, prompts):
            return EmptyDiscovery(
                prompts=prompts,
                model_name=work.config.llm_model,
                execution_contract=getattr(work.config, "semantic_execution_contract", None),
            )

    media = tmp_path / "media"
    source = media / "source.mp4"
    create_demo_source(output_path=source, duration_ms=12_000)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    data = tmp_path / "projects"
    engine = create_sqlite_engine(tmp_path / "empty.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    config = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"),
        clipping_algorithm="semantic_windowed",
        clip_profile=ClipProfile.MINI_LESSON,
    )
    if version in {"9", "11"}:
        raw_config = config.model_dump(mode="json")
        raw_config.pop("semantic_execution_contract")
        raw_config["schema_version"] = "11"
        config = PipelineRunConfigV11.model_validate_json(json.dumps(raw_config))
    if version == "9":
        raw_config = config.model_dump(mode="json")
        raw_config.pop("semantic_transport_contract")
        raw_config["schema_version"] = "9"
        config = PipelineRunConfigV9.model_validate_json(json.dumps(raw_config))
    assert config.schema_version == version
    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=30),
        repository=repository,
        pipeline_service=service,
        heartbeat_seconds=5,
        handler=EmptyHandlers(
            data_dir=data,
            allowed_media_roots=(media,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
    )
    try:
        created = service.create_project_and_run(
            source_path=source, config=config, max_stage_retries=0
        )
        result = runner.run_until_terminal(created.run_id, worker_id="empty-lineage")
        assert result.status == PipelineRunStatus.COMPLETED
        assert len(calls) == 1 and ".discovery." in calls[0]
        root = data / created.project_id / "runs/g001"
        rough = MiniLessonRoughArtifactV5.model_validate_json(
            (root / "candidates/rough-candidates.json").read_bytes()
        )
        assert not rough.candidates and not rough.semantic_v5.topic_chain_reviews
        edit = json.loads((root / "editing/edit-plans.json").read_text())
        assert edit["revisions"] == []
        final = UnifiedSemanticResultV5.model_validate_json(json.dumps(edit["semantic_v5"]))
        assert len(final.lineage.batches) == 1 and not any(
            final.lineage.counts.model_dump().values()
        )
        assert final.global_review is None and final.persistent_candidate_ids == {}
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(CandidateClipRow)) == 0
            assert connection.scalar(select(func.count()).select_from(EditPlanRevisionRow)) == 0
        assert not list(root.glob("output/**/*.mp4"))
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    "fault, expected_error",
    [
        ("rough_context", "immutable input plan differs"),
        ("rough_graph", "missing a required Link Review"),
        ("rough_slot", "slots differ from their source units"),
        ("edit_partition", "actual quality gates"),
        ("edit_plan", "selected source span"),
        ("edit_caption", "selected source span"),
    ],
)
@pytest.mark.parametrize("version", ["9", "11", "13"])
def test_rehashed_persistent_lineage_recovery_rejects_tampering(
    tmp_path, monkeypatch, fault, expected_error, version
):
    from test_persistent_mock_pipeline import MiniLessonMockHandlers

    from liveclip.application.stage_execution import StageExecutionError

    media = tmp_path / "media"
    source = media / "source.mp4"
    create_demo_source(output_path=source, duration_ms=125_000)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    data = tmp_path / "projects"
    engine = create_sqlite_engine(tmp_path / "tamper.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    state = SqlAlchemyStageStateStore(engine)
    handler = MiniLessonMockHandlers(
        data_dir=data,
        allowed_media_roots=(media,),
        assets=SqlAlchemyAssetStore(engine),
        state=state,
    )
    target = PipelineStage.CANDIDATES if fault.startswith("rough_") else PipelineStage.EDIT
    injected = False
    rejected = []
    semantic_calls = []
    before = None
    calls_before = None
    original_generate = MockStructuredLLMProvider.generate

    def generate(provider, **kwargs):
        semantic_calls.append(kwargs["subject_id"])
        return original_generate(provider, **kwargs)

    monkeypatch.setattr(MockStructuredLLMProvider, "generate", generate)

    def durable_rows():
        with engine.connect() as connection:
            return tuple(
                connection.execute(select(model.__table__).order_by(model.id)).all()
                for model in (CandidateClipRow, EditPlanRevisionRow, RenderJobRow, ApiUsageRow)
            )

    # Fail immediately if recovery attempts business writes, even idempotent ones.
    for method in ("save_candidates", "save_revisions"):
        original = getattr(state, method)

        def guarded(*args, original=original, **kwargs):
            assert not injected, "recovery attempted a downstream business write"
            return original(*args, **kwargs)

        monkeypatch.setattr(state, method, guarded)

    class TamperAfterCommit:
        def execute(self, work, lease, *, cancel_requested):
            nonlocal injected, before, calls_before
            try:
                result = handler.execute(work, lease, cancel_requested=cancel_requested)
            except StageExecutionError as exc:
                if isinstance(exc.__cause__, ValueError):
                    rejected.append(str(exc.__cause__))
                raise
            if work.stage != target or injected:
                return result
            relative = (
                "runs/g001/candidates/rough-candidates.json"
                if target == PipelineStage.CANDIDATES
                else "runs/g001/editing/edit-plans.json"
            )
            path = data / work.project_id / relative
            raw = json.loads(path.read_bytes())
            semantic = raw["semantic_v5"]
            if fault == "rough_context":
                semantic["input_plan"]["units"][0]["context_range_ms"]["end_ms"] -= 1
            elif fault == "rough_graph":
                assert semantic["link_reviews"]
                semantic["link_review_requests"] = []
                semantic["link_reviews"] = []
            elif fault == "rough_slot":
                key = next(iter(semantic["candidate_slot_map"]))
                old = semantic["candidate_slot_map"][key]
                semantic["candidate_slot_map"][key] = "forged_slot"
                for candidate in raw["candidates"]:
                    if candidate["candidate_id"] == old:
                        candidate["candidate_id"] = "forged_slot"
            elif fault == "edit_partition":
                # Keep all redundant ledger/profile accounting internally consistent;
                # only replaying the actual quality gates exposes this false exclusion.
                ledger = semantic["lineage"]
                selected = ledger["partition"]["selected"]
                ledger["partition"]["top_n_excluded"] = selected
                ledger["partition"]["selected"] = []
                ledger["counts"]["top_n_excluded"] = len(selected)
                ledger["counts"]["selected"] = 0
                for outcome in ledger["outcomes"] + ledger["chain_new_outcomes"]:
                    if outcome["unit"]["candidate_id"] in selected:
                        outcome["disposition"] = "top_n_excluded"
                for original in ledger["originals"]:
                    for terminal in original["paths"]:
                        if terminal["unit_id"] in selected:
                            terminal["disposition"] = "top_n_excluded"
                profile = semantic["profiles"]["mini_lesson"]
                profile["top_n_excluded"] = profile["selected"]
                profile["selected"] = []
                for item in profile["top_n_excluded"]:
                    item["disposition"] = "top_n_excluded"
                profile["statistics"]["selected_count"] = 0
                profile["statistics"]["top_n_excluded_count"] = len(selected)
                raw["revisions"] = []
            elif fault == "edit_plan":
                raw["revisions"][0]["revision"]["plan"]["title"] = "Changed saved title"
            else:
                raw["revisions"][0]["revision"]["captions"][0]["text"] = "Changed saved caption"
            # Establish that this is a contextual recovery regression, not merely
            # malformed JSON/schema rejection or a stale asset-hash test.
            if target == PipelineStage.CANDIDATES:
                MiniLessonRoughArtifactV5.model_validate_json(json.dumps(raw))
            else:
                UnifiedSemanticResultV5.model_validate_json(json.dumps(semantic))
            payload = json.dumps(raw, ensure_ascii=False).encode()
            path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            with engine.begin() as connection:
                changed = connection.execute(
                    update(AssetRow)
                    .where(
                        AssetRow.project_id == work.project_id,
                        AssetRow.relative_path == relative,
                    )
                    .values(sha256=digest, expected_sha256=digest, size_bytes=len(payload))
                )
                assert changed.rowcount == 1
            injected = True
            before = durable_rows()
            calls_before = tuple(semantic_calls)
            raise StageExecutionError(
                failure_class=FailureClass.TRANSIENT,
                error_code="INJECTED_AFTER_LINEAGE_COMMIT",
                safe_message="Synthetic rehashed artifact corruption after commit",
            )

    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=30),
        repository=repository,
        pipeline_service=service,
        handler=TamperAfterCommit(),
        heartbeat_seconds=5,
    )
    config = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"),
        clipping_algorithm="semantic_windowed",
        clip_profile=ClipProfile.MINI_LESSON,
    )
    if version in {"9", "11"}:
        raw_config = config.model_dump(mode="json")
        raw_config.pop("semantic_execution_contract")
        raw_config["schema_version"] = "11"
        config = PipelineRunConfigV11.model_validate_json(json.dumps(raw_config))
    if version == "9":
        raw_config = config.model_dump(mode="json")
        raw_config.pop("semantic_transport_contract")
        raw_config["schema_version"] = "9"
        config = PipelineRunConfigV9.model_validate_json(json.dumps(raw_config))
    assert config.schema_version == version
    try:
        created = service.create_project_and_run(
            source_path=source, config=config, max_stage_retries=1
        )
        result = runner.run_until_terminal(created.run_id, worker_id="tampered-lineage")
        assert injected and result.status == PipelineRunStatus.FAILED
        assert len(rejected) == 1 and expected_error in rejected[0]
        assert tuple(semantic_calls) == calls_before
        assert durable_rows() == before
        assert not list((data / created.project_id / "runs/g001/output").glob("**/*.mp4"))
        assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    finally:
        engine.dispose()
