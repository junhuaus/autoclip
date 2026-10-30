"""Stage 11: persisted pipeline edit stages repair or block guard-tripping model text.

Every run uses the mock structured provider only. A Global Review output whose
title or reason trips the unchanged ``reject_executable_text`` guard is sent back
through the existing repair loop; a rewrite that still trips it blocks only that
candidate, and the rest of the run completes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import func, select

import liveclip.pipeline.stage_handlers as stage_handlers_module
from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfig,
    PipelineRunConfigV9,
    PipelineRunConfigV11,
    PipelineRunConfigV12,
    PipelineRunConfigV13,
    PipelineService,
    StageWork,
)
from liveclip.application.stage_execution import StageExecutionError, StageExecutionResult
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.clipping_skills.semantic_global_v3 import (
    load_semantic_global_v3_boundary_prompt,
    load_semantic_global_v3_review_prompt,
)
from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt
from liveclip.clipping_skills.semantic_topic_chain_v2 import (
    load_semantic_topic_chain_prompt as load_lineage_prompt,
)
from liveclip.clipping_skills.semantic_windowed_v2 import (
    load_semantic_windowed_v2_discovery_prompt,
)
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import EditPlanRevisionRow
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.edit_plan import reject_executable_text
from liveclip.domain.state_transitions import FailureClass, PipelineRunStatus, PipelineStage
from liveclip.pipeline.edit_text_guard import (
    TEXT_GUARD_BLOCK_NOTE,
    TEXT_GUARD_ERROR_PREFIX,
    TEXT_GUARD_REJECT_NOTE,
)
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.providers.asr.mock import MockASRProvider, MockScriptSegment
from liveclip.providers.llm.structured import MockStructuredLLMProvider, StructuredCallResult
from liveclip.renderer.quality import MediaValidationTransientError
from liveclip.services.demo_media import create_demo_source

# Plain English "make" (the cold-27 false positive) and a tool name in a title.
UNSAFE = {
    "reason": "These practice steps make a complete and closed lesson.",
    "title": "ffmpeg 入门",
}
SAFE = {
    "reason": "这几步练习构成一个完整闭合的小课。",
    "title": "发声练习入门",
}
_SOURCE_FIELD = {"reason": "review_reason", "title": "title"}


def _rewrite(raw: dict[str, object], field: str, text: str) -> None:
    rows = raw.get("reviews", raw.get("clips"))
    assert isinstance(rows, list) and rows
    for row in rows:
        row[_SOURCE_FIELD[field]] = text


def _guard_provider(
    field: str, mode: str, phases: list[str], repair_errors: list[str]
) -> type[MockStructuredLLMProvider]:
    requests: dict[str, dict[str, object]] = {}

    class GuardTextProvider(MockStructuredLLMProvider):
        def generate(self, *, subject_id, payload, response_model, cancel_requested=lambda: False):
            if self._prompts.stage == "global_review":
                requests[subject_id] = payload
            return super().generate(
                subject_id=subject_id,
                payload=payload,
                response_model=response_model,
                cancel_requested=cancel_requested,
            )

        def repair(
            self,
            *,
            subject_id,
            payload,
            response_model,
            validation_errors,
            cancel_requested=lambda: False,
        ):
            assert self._prompts.stage == "global_review"
            repair_errors.extend(validation_errors)
            # The mock answers the immutable request; the rewrite below models the
            # Agent correcting only the rejected text field.
            return super().repair(
                subject_id=subject_id,
                payload=requests[subject_id],
                response_model=response_model,
                validation_errors=validation_errors,
                cancel_requested=cancel_requested,
            )

        def _generate(self, *, subject_id, payload, response_model, cancel_requested, phase):
            result = super()._generate(
                subject_id=subject_id,
                payload=payload,
                response_model=response_model,
                cancel_requested=cancel_requested,
                phase=phase,
            )
            if self._prompts.stage != "global_review":
                return result
            phases.append(phase)
            unsafe = phase == "initial" or mode == "blocked"
            raw = result.output.model_dump(mode="json")
            _rewrite(raw, field, UNSAFE[field] if unsafe else SAFE[field])
            return StructuredCallResult(
                output=response_model.model_validate_json(json.dumps(raw, ensure_ascii=False)),
                call_records=result.call_records,
                repaired=result.repaired,
            )

    return GuardTextProvider


class _Handlers(PipelineStageHandlers):
    provider_class: type[MockStructuredLLMProvider] = MockStructuredLLMProvider
    mini_lesson_asr = False

    def _structured_provider(self, work, prompts):
        provider = super()._structured_provider(work, prompts)
        assert type(provider) is MockStructuredLLMProvider
        provider.__class__ = self.provider_class
        return provider

    def _asr_provider(self, work):
        if not self.mini_lesson_asr:
            return super()._asr_provider(work)
        return MockASRProvider(
            tuple(
                MockScriptSegment(
                    script_id=f"lesson_{index:02d}",
                    source_start_ms=index * 10_000,
                    source_end_ms=(index + 1) * 10_000,
                    text=f"教学步骤{index + 1}提供不同的解释与练习证据。",
                )
                for index in range(12)
            ),
            model_name=work.config.transcription_model,
        )


class _Wrapper:
    """Optionally crash once after the EDIT commit (replay) or before it (cache)."""

    def __init__(self, delegate: PipelineStageHandlers, *, crash_after_edit: bool) -> None:
        self.delegate = delegate
        self.crash_after_edit = crash_after_edit
        self.edit_calls = 0

    def execute(
        self, work: StageWork, lease: LeaseIdentity, *, cancel_requested: Callable[[], bool]
    ) -> StageExecutionResult:
        result = self.delegate.execute(work, lease, cancel_requested=cancel_requested)
        if work.stage == PipelineStage.EDIT:
            self.edit_calls += 1
            if self.crash_after_edit and self.edit_calls == 1:
                raise StageExecutionError(
                    failure_class=FailureClass.TRANSIENT,
                    error_code="INJECTED_AFTER_EDIT_COMMIT",
                    safe_message="Synthetic crash after the EditPlan commit",
                )
        return result


def _fail_edit_write_once(monkeypatch) -> list[str]:
    """Fail the first EditPlan artifact write after Global Review was persisted."""

    failures: list[str] = []
    original = stage_handlers_module.write_json_no_clobber

    def write(path, *args, **kwargs):
        if str(path).endswith("editing/edit-plans.json") and not failures:
            failures.append(str(path))
            raise MediaValidationTransientError("synthetic failure before the EditPlan commit")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(stage_handlers_module, "write_json_no_clobber", write)
    return failures


def _mini_lesson_config(version: str):
    prompts = {
        stage: load_semantic_topic_chain_prompt(stage, "general", ClipProfile.MINI_LESSON)
        for stage in ("discovery", "link_review", "topic_chain", "boundary_review", "global_review")
    }
    if version != "8":
        for stage in ("discovery", "topic_chain", "boundary_review"):
            prompts[stage] = load_lineage_prompt(stage, "general", ClipProfile.MINI_LESSON)
    model = {
        "8": PipelineRunConfig,
        "9": PipelineRunConfigV9,
        "11": PipelineRunConfigV11,
        "13": PipelineRunConfigV13,
    }[version]
    return model(
        provider="mock",
        top_n=3,
        minimum_clip_ms=90_000,
        semantic_target_clip_ms=180_000,
        maximum_clip_ms=300_000,
        chunk_duration_ms=12_000,
        chunk_overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=270,
        preview_height=480,
        video_encoder="libx264",
        clipping_algorithm="semantic_windowed",
        editing_prompt_version=f"{prompts['discovery'].version}.discovery",
        editing_prompt_sha256=prompts["discovery"].sha256,
        semantic_profile="general",
        semantic_discovery_skill_version=f"{prompts['discovery'].version}.discovery",
        semantic_discovery_skill_sha256=prompts["discovery"].sha256,
        semantic_link_review_skill_version="semantic_topic_chain_v1.link_review",
        semantic_link_review_skill_sha256=prompts["link_review"].sha256,
        semantic_topic_chain_skill_version=f"{prompts['topic_chain'].version}.topic_chain",
        semantic_topic_chain_skill_sha256=prompts["topic_chain"].sha256,
        semantic_boundary_review_skill_version=(
            f"{prompts['boundary_review'].version}.boundary_review"
        ),
        semantic_boundary_review_skill_sha256=prompts["boundary_review"].sha256,
        semantic_global_review_skill_version="semantic_topic_chain_v1.global_review",
        semantic_global_review_skill_sha256=prompts["global_review"].sha256,
        semantic_no_render=True,
        clip_profile=ClipProfile.MINI_LESSON,
    )


def _semantic_global_config(contract: str, bounded: bool):
    common = dict(
        provider="mock",
        top_n=10,
        minimum_clip_ms=4_000,
        semantic_target_clip_ms=6_000,
        maximum_clip_ms=8_000,
        chunk_duration_ms=12_000,
        chunk_overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=270,
        preview_height=480,
        video_encoder="libx264",
        semantic_profile="general",
        semantic_no_render=True,
    )
    model = PipelineRunConfigV12 if bounded else PipelineRunConfig
    if contract == "v3":
        discovery = load_semantic_windowed_v2_discovery_prompt("general")
        boundary = load_semantic_global_v3_boundary_prompt("general")
        review = load_semantic_global_v3_review_prompt("general")
        return model(
            **common,
            clipping_algorithm="semantic_windowed",
            editing_prompt_version=f"{discovery.version}.discovery",
            editing_prompt_sha256=discovery.sha256,
            semantic_discovery_skill_version=f"{discovery.version}.discovery",
            semantic_discovery_skill_sha256=discovery.sha256,
            semantic_boundary_review_skill_version=f"{boundary.version}.boundary_review",
            semantic_boundary_review_skill_sha256=boundary.sha256,
            semantic_global_review_skill_version=f"{review.version}.global_review",
            semantic_global_review_skill_sha256=review.sha256,
        )
    discovery = load_semantic_global_prompt("discovery", "general")
    review = load_semantic_global_prompt("global_review", "general")
    return model(
        **common,
        clipping_algorithm="semantic_global",
        editing_prompt_version=f"{discovery.version}.discovery",
        editing_prompt_sha256=discovery.sha256,
        semantic_discovery_skill_version=f"{discovery.version}.discovery",
        semantic_discovery_skill_sha256=discovery.sha256,
        semantic_global_review_skill_version=f"{review.version}.global_review",
        semantic_global_review_skill_sha256=review.sha256,
    )


def _run(tmp_path: Path, config, *, field, mode, mini_lesson, crash_after_edit, duration_ms):
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=duration_ms)
    engine = create_sqlite_engine(tmp_path / "guard.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    phases: list[str] = []
    repair_errors: list[str] = []
    handler = _Handlers(
        data_dir=data_dir,
        allowed_media_roots=(media_root,),
        assets=SqlAlchemyAssetStore(engine),
        state=SqlAlchemyStageStateStore(engine),
    )
    handler.provider_class = _guard_provider(field, mode, phases, repair_errors)
    handler.mini_lesson_asr = mini_lesson
    wrapper = _Wrapper(handler, crash_after_edit=crash_after_edit)
    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=30),
        repository=repository,
        pipeline_service=service,
        handler=wrapper,
        heartbeat_seconds=5,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(), config=config, max_stage_retries=1
        )
        snapshot = runner.run_until_terminal(created.run_id, worker_id="text-guard")
        edit = json.loads(
            (data_dir / created.project_id / "runs/g001/editing/edit-plans.json").read_text(
                encoding="utf-8"
            )
        )
        with engine.connect() as connection:
            revision_rows = connection.scalar(select(func.count()).select_from(EditPlanRevisionRow))
        # The guard error, not an unrelated validation error, drove the one repair.
        assert repair_errors and all(
            error.startswith(TEXT_GUARD_ERROR_PREFIX) for error in repair_errors
        )
        return snapshot, edit, revision_rows, phases, wrapper.edit_calls
    finally:
        engine.dispose(close=True)


def _events(audit: dict[str, object]) -> list[dict[str, object]]:
    events = audit.get("validation_events", [])
    assert isinstance(events, list)
    return events


@pytest.mark.integration
@pytest.mark.parametrize("version", ["8", "9", "11", "13"])
@pytest.mark.parametrize("field", ["reason", "title"])
@pytest.mark.parametrize("mode", ["repaired", "blocked"])
def test_mini_lesson_edit_repairs_or_blocks_guard_tripping_text(
    tmp_path: Path, version: str, field: str, mode: str
) -> None:
    with pytest.raises(ValueError, match="executable"):
        reject_executable_text(UNSAFE[field])
    lineage = version != "8"
    snapshot, edit, revision_rows, phases, edit_calls = _run(
        tmp_path,
        _mini_lesson_config(version),
        field=field,
        mode=mode,
        mini_lesson=True,
        crash_after_edit=lineage,
        duration_ms=125_000,
    )
    # The rest of the run completes in both outcomes.
    assert snapshot.status == PipelineRunStatus.COMPLETED
    # One initial Global Review call and exactly one repair through the existing loop.
    assert phases == ["initial", "repair"]
    if lineage:
        # The crash after commit forces the persisted-plan replay of the same gate.
        assert edit_calls == 2
    semantic = edit["semantic_v5" if lineage else "semantic_v4"]
    profile = semantic["profiles"]["mini_lesson"]
    audit = semantic["stage_audits"]["global_review"]
    events = _events(audit)
    assert events and events[0].get("deferred") is True
    if mode == "repaired":
        assert revision_rows == 1
        (revision,) = edit["revisions"]
        plan = revision["revision"]["plan"]
        expected = SAFE[field]
        assert (plan["reason"] if field == "reason" else plan["title"]) == expected
        assert profile["statistics"]["selected_count"] == 1
        assert not profile["blocked"]
        assert all(event.get("phase") != "repair" for event in events)
    else:
        assert revision_rows == 0 and edit["revisions"] == []
        assert profile["selected"] == []
        (blocked,) = profile["blocked"]
        assert blocked["disposition"] == "blocked"
        assert blocked["validation_notes"][-1] == TEXT_GUARD_BLOCK_NOTE
        # Python never rewrites model text; the persisted review keeps the original.
        assert blocked["review"][_SOURCE_FIELD[field]] == UNSAFE[field]
        assert profile["statistics"]["selected_count"] == 0
        assert profile["statistics"]["blocked_count"] == 1
        assert profile["statistics"]["qualified_before_top_n"] == 0
        assert [event.get("deferred") for event in events] == [True, True]
        if lineage:
            assert semantic["lineage"]["partition"]["blocked"] == [
                blocked["review"]["candidate_id"]
            ]
        else:
            coverage = [
                value
                for value in semantic["coverage_decisions"]
                if value["source_id"] == blocked["review"]["candidate_id"]
                and value["disposition"] == "blocked"
            ]
            assert coverage and TEXT_GUARD_BLOCK_NOTE in coverage[0]["reason"]


@pytest.mark.integration
@pytest.mark.parametrize("version", ["8", "9", "13"])
def test_mini_lesson_retry_blocks_cached_guard_text_without_new_calls(
    tmp_path: Path, version: str, monkeypatch
) -> None:
    """Cache/durable-outcome paths have no repair left and must block, not crash."""

    failures = _fail_edit_write_once(monkeypatch)
    snapshot, edit, revision_rows, phases, _ = _run(
        tmp_path,
        _mini_lesson_config(version),
        field="reason",
        mode="blocked",
        mini_lesson=True,
        crash_after_edit=False,
        duration_ms=125_000,
    )
    assert failures and snapshot.status == PipelineRunStatus.COMPLETED
    # The retry resolves Global Review from the cache or the durable outcome.
    assert phases == ["initial", "repair"]
    assert revision_rows == 0 and edit["revisions"] == []
    profile = edit["semantic_v4" if version == "8" else "semantic_v5"]["profiles"]["mini_lesson"]
    assert profile["blocked"][0]["validation_notes"][-1] == TEXT_GUARD_BLOCK_NOTE


@pytest.mark.integration
@pytest.mark.parametrize("contract", ["v3", "legacy"])
@pytest.mark.parametrize("bounded", [False, True])
@pytest.mark.parametrize(
    ("field", "mode"),
    [("reason", "repaired"), ("title", "repaired"), ("reason", "blocked"), ("title", "blocked")],
)
def test_semantic_global_edit_repairs_or_blocks_guard_tripping_text(
    tmp_path: Path, contract: str, bounded: bool, field: str, mode: str
) -> None:
    snapshot, edit, revision_rows, phases, _ = _run(
        tmp_path,
        _semantic_global_config(contract, bounded),
        field=field,
        mode=mode,
        mini_lesson=False,
        crash_after_edit=False,
        duration_ms=24_000,
    )
    assert snapshot.status == PipelineRunStatus.COMPLETED
    assert phases == ["initial", "repair"]
    semantic = edit["semantic_global"]
    validated = semantic["validated"]
    events = semantic["prompt_debug"]["validation_events"]
    assert events and events[0].get("deferred") is True
    if mode == "repaired":
        assert revision_rows == 1
        (revision,) = edit["revisions"]
        plan = revision["revision"]["plan"]
        assert (plan["reason"] if field == "reason" else plan["title"]) == SAFE[field]
        assert len(events) == 1
        return
    assert revision_rows == 0 and edit["revisions"] == []
    assert validated["selected"] == []
    assert [event.get("deferred") for event in events] == [True, True]
    if contract == "v3":
        (blocked,) = validated["blocked"]
        assert blocked["publish_status"] == "blocked"
        assert blocked["validation_notes"][-1] == TEXT_GUARD_BLOCK_NOTE
        assert blocked["review"][_SOURCE_FIELD[field]] == UNSAFE[field]
        assert validated["statistics"]["blocked_count"] == 1
        assert validated["statistics"]["selected_count"] == 0
    else:
        rejected = [
            value
            for value in validated["rejected"]
            if value["validation_notes"][-1:] == [TEXT_GUARD_REJECT_NOTE]
        ]
        assert len(rejected) == 1
        assert rejected[0]["clip"][_SOURCE_FIELD[field]] == UNSAFE[field]
        assert validated["manual_review"] == []
        assert validated["global_review_summary"]["kept_clip_count"] == 0


@pytest.mark.integration
@pytest.mark.parametrize("bounded", [False, True])
def test_semantic_global_retry_blocks_cached_guard_text_without_new_calls(
    tmp_path: Path, bounded: bool, monkeypatch
) -> None:
    failures = _fail_edit_write_once(monkeypatch)
    snapshot, edit, revision_rows, phases, _ = _run(
        tmp_path,
        _semantic_global_config("v3", bounded),
        field="title",
        mode="blocked",
        mini_lesson=False,
        crash_after_edit=False,
        duration_ms=24_000,
    )
    assert failures and snapshot.status == PipelineRunStatus.COMPLETED
    assert phases == ["initial", "repair"]
    assert revision_rows == 0 and edit["revisions"] == []
    blocked = edit["semantic_global"]["validated"]["blocked"]
    assert blocked and blocked[0]["validation_notes"][-1] == TEXT_GUARD_BLOCK_NOTE
