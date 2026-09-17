from __future__ import annotations

import hashlib
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
from liveclip.clipping_skills import (
    load_semantic_continuous_skill,
    load_semantic_discovery_skill,
)
from liveclip.clipping_skills.semantic_global_v1 import load_semantic_global_prompt
from liveclip.clipping_skills.semantic_global_v2 import load_semantic_global_v2_review_prompt
from liveclip.clipping_skills.semantic_global_v3 import (
    load_semantic_global_v3_boundary_prompt,
    load_semantic_global_v3_review_prompt,
)
from liveclip.clipping_skills.semantic_topic_chain_v1 import (
    load_semantic_topic_chain_prompt,
)
from liveclip.clipping_skills.semantic_windowed_v1 import (
    load_semantic_windowed_discovery_prompt,
)
from liveclip.clipping_skills.semantic_windowed_v2 import (
    load_semantic_windowed_v2_discovery_prompt,
)
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    ApiUsageRow,
    AssetRow,
    CandidateClipRow,
    EditPlanRevisionRow,
    PipelineRunRow,
    RenderJobRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.state_transitions import (
    AssetStatus,
    FailureClass,
    PipelineRunStatus,
    PipelineStage,
    ProjectStatus,
    RenderStatus,
    TaskStatus,
)
from liveclip.media.secure_files import (
    read_regular_file_no_follow,
    write_bytes_immutable_no_follow,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.providers.asr.mock import MockASRProvider, MockScriptSegment
from liveclip.renderer.ffmpeg import FFmpegRenderCancelled, FFmpegRenderError
from liveclip.renderer.quality import probe_media
from liveclip.services.demo_media import create_demo_source


class FailOnceAfterProxyAssets:
    def __init__(self, delegate: PipelineStageHandlers) -> None:
        self._delegate = delegate
        self.injected = False
        self.proxy_calls = 0

    def execute(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        result = self._delegate.execute(work, lease, cancel_requested=cancel_requested)
        if work.stage == PipelineStage.PROXY_RENDER:
            self.proxy_calls += 1
            if not self.injected:
                self.injected = True
                raise StageExecutionError(
                    failure_class=FailureClass.TRANSIENT,
                    error_code="INJECTED_AFTER_ASSET_COMMIT",
                    safe_message="Injected crash window after proxy assets committed",
                )
        return result


class MiniLessonMockHandlers(PipelineStageHandlers):
    def _asr_provider(self, work: StageWork) -> MockASRProvider:
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


class FailOnceAfterLineageCommit:
    """Crash after durable candidate/edit writes, before the task reports completion."""

    def __init__(self, delegate: PipelineStageHandlers) -> None:
        self.delegate = delegate
        self.injected: set[PipelineStage] = set()
        self.calls: dict[PipelineStage, int] = {}

    def execute(
        self, work: StageWork, lease: LeaseIdentity, *, cancel_requested: Callable[[], bool]
    ) -> StageExecutionResult:
        self.calls[work.stage] = self.calls.get(work.stage, 0) + 1
        result = self.delegate.execute(work, lease, cancel_requested=cancel_requested)
        if (
            work.stage in {PipelineStage.CANDIDATES, PipelineStage.EDIT}
            and work.stage not in self.injected
        ):
            self.injected.add(work.stage)
            raise StageExecutionError(
                failure_class=FailureClass.TRANSIENT,
                error_code="INJECTED_AFTER_LINEAGE_COMMIT",
                safe_message="Synthetic crash after lineage commit",
            )
        return result


@pytest.mark.integration
@pytest.mark.parametrize("version", ["8", "9", "11", "13"])
def test_mini_lesson_runs_topic_chain_boundary_and_profile_review(
    tmp_path: Path, version: str, monkeypatch
) -> None:
    transport_stages = set()
    if version in {"11", "13"}:
        from liveclip.pipeline.semantic_transport import decode_transport
        from liveclip.providers.llm import structured as structured_module

        prepare = structured_module._prepare_transport_request

        def observe_transport(**kwargs):
            prepared = prepare(**kwargs)
            assert (
                decode_transport(prepared.payload, contract="semantic-cue-table-v1")
                == kwargs["payload"]
            )
            assert prepared.measurement.fits
            transport_stages.add(kwargs["response_model"].__name__)
            return prepared

        monkeypatch.setattr(structured_module, "_prepare_transport_request", observe_transport)
    lineage = version in {"9", "11", "13"}
    media_root = tmp_path / "media"
    source_path = media_root / "mini-lesson-source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=125_000)
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    engine = create_sqlite_engine(tmp_path / "mini-lesson.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    base_handler = MiniLessonMockHandlers(
        data_dir=data_dir,
        allowed_media_roots=(media_root,),
        assets=SqlAlchemyAssetStore(engine),
        state=SqlAlchemyStageStateStore(engine),
    )
    recovering_handler = FailOnceAfterLineageCommit(base_handler)
    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=30),
        repository=repository,
        pipeline_service=service,
        handler=recovering_handler if lineage else base_handler,
        heartbeat_seconds=5,
    )
    prompts = {
        stage: load_semantic_topic_chain_prompt(stage, "general", ClipProfile.MINI_LESSON)
        for stage in (
            "discovery",
            "link_review",
            "topic_chain",
            "boundary_review",
            "global_review",
        )
    }
    if lineage:
        from liveclip.clipping_skills.semantic_topic_chain_v2 import (
            load_semantic_topic_chain_prompt as load_lineage_prompt,
        )

        for stage in ("discovery", "topic_chain", "boundary_review"):
            prompts[stage] = load_lineage_prompt(stage, "general", ClipProfile.MINI_LESSON)
    config_model = {
        "8": PipelineRunConfig,
        "9": PipelineRunConfigV9,
        "11": PipelineRunConfigV11,
        "13": PipelineRunConfigV13,
    }[version]
    config = config_model(
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
        semantic_boundary_review_skill_version=f"{prompts['boundary_review'].version}.boundary_review",
        semantic_boundary_review_skill_sha256=prompts["boundary_review"].sha256,
        semantic_global_review_skill_version="semantic_topic_chain_v1.global_review",
        semantic_global_review_skill_sha256=prompts["global_review"].sha256,
        semantic_no_render=False,
        clip_profile=ClipProfile.MINI_LESSON,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=config,
            max_stage_retries=1,
        )
        snapshot = runner.run_until_terminal(created.run_id, worker_id="mini-lesson-integration")
        assert snapshot.status == PipelineRunStatus.COMPLETED
        if lineage:
            assert recovering_handler.injected == {PipelineStage.CANDIDATES, PipelineStage.EDIT}
            assert recovering_handler.calls[PipelineStage.CANDIDATES] == 2
            assert recovering_handler.calls[PipelineStage.EDIT] == 2
        rough = json.loads(
            (
                data_dir / created.project_id / "runs/g001/candidates/rough-candidates.json"
            ).read_text(encoding="utf-8")
        )
        semantic = rough["semantic_v5" if lineage else "semantic_v4"]
        assert semantic["topic_chains"]
        assert semantic["link_reviews"]
        assert any(review["candidates"] for review in semantic["topic_chain_reviews"])
        edit = json.loads(
            (data_dir / created.project_id / "runs/g001/editing/edit-plans.json").read_text(
                encoding="utf-8"
            )
        )["semantic_v5" if lineage else "semantic_v4"]
        if lineage:
            from liveclip.pipeline.semantic_runtime_v5 import UnifiedSemanticResultV5

            restored = UnifiedSemanticResultV5.model_validate_json(json.dumps(edit))
            assert restored.lineage.counts.originals > 0
            assert restored.lineage.counts.selected == 1
            assert all(original.paths for original in restored.lineage.originals)
            assert restored.config_fingerprint == config.fingerprint
        profile = edit["profiles"]["mini_lesson"]
        assert profile["statistics"]["selected_count"] == 1
        assert profile["statistics"]["qualified_before_top_n"] == 1
        rendered = tuple(
            (data_dir / created.project_id / "runs/g001/output/mini_lessons").glob(
                "*/r*/review.mp4"
            )
        )
        assert len(rendered) == 1
        rendered_probe = probe_media(rendered[0])
        duration_ms = round(float(rendered_probe["format"]["duration"]) * 1_000)
        assert 90_000 <= duration_ms <= 300_000
        assert config.schema_version == version
        if version in {"11", "13"}:
            assert transport_stages == {
                "DiscoveryBatchOutputV5",
                "LinkReviewV4",
                "TopicChainReviewV5",
                "BoundaryReviewV5",
                "GlobalReviewOutputV4",
            }
        assert config.semantic_validation_contract == "semantic-v4-quality-v2"
        assert edit["run_metadata"]["run_id"] == created.run_id
        assert edit["run_metadata"]["validation_contract"] == config.semantic_validation_contract
        assert edit["run_metadata"]["source_hash"] == source_hash
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash
        subtitle = rendered[0].with_suffix(".srt")
        captions = load_srt_transcript(subtitle)
        assert captions.segments
        assert all(0 <= cue.start_ms < cue.end_ms <= duration_ms for cue in captions.segments)
        quality_path = rendered[0].parent / "review-quality/quality-report.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        assert quality["automatic_status"] == quality["full_decode"] == "passed"
        assert quality["visual_inspection_status"] == "pending"
        assert quality["video_codec"] == "h264"
        assert quality["audio_codec"] == "aac"
        assert quality["actual_duration_ms"] == duration_ms
        assert quality["media_sha256"] == hashlib.sha256(rendered[0].read_bytes()).hexdigest()
        with engine.connect() as connection:
            persisted = connection.execute(
                select(PipelineRunRow.config_json, PipelineRunRow.config_fingerprint).where(
                    PipelineRunRow.id == created.run_id
                )
            ).one()
            assert persisted.config_json == config.model_dump(mode="json")
            assert persisted.config_fingerprint == config.fingerprint

        # A fixed, already-allowed Runner report root survives scratch cleanup and
        # later Playwright test-results cleanup. Only this known mock fixture is copied.
        retained = (
            Path(__file__).resolve().parents[2]
            / "apps/web/playwright-report/mini-lesson"
            / created.run_id
        )
        project_dir = data_dir / created.project_id
        artifact_paths = [
            rendered[0],
            subtitle,
            quality_path,
            quality_path.parent / "contact-sheet.png",
            project_dir / "runs/g001/candidates/rough-candidates.json",
            project_dir / "runs/g001/editing/edit-plans.json",
            project_dir / "runs/g001/transcript/transcript.json",
        ]
        retained_files = []
        for artifact_path in artifact_paths:
            payload = read_regular_file_no_follow(artifact_path, max_bytes=32 * 1024 * 1024)
            relative = artifact_path.relative_to(project_dir)
            write_bytes_immutable_no_follow(
                retained / relative, payload, max_bytes=32 * 1024 * 1024
            )
            retained_files.append(
                {
                    "path": relative.as_posix(),
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        # Export only explicit non-sensitive columns, never whole ORM rows (which
        # include lease tokens, source text and provider diagnostics).
        with engine.connect() as connection:

            def rows(statement):
                return [dict(row) for row in connection.execute(statement).mappings()]

            audit = {
                "schema_version": "1",
                "kind": "redacted-terminal-sqlite-audit",
                "project_id": created.project_id,
                "run_id": created.run_id,
                "source_sha256": source_hash,
                "config_fingerprint": config.fingerprint,
                "runs": rows(
                    select(
                        PipelineRunRow.id,
                        PipelineRunRow.generation,
                        PipelineRunRow.status,
                        PipelineRunRow.config_fingerprint,
                    ).where(PipelineRunRow.id == created.run_id)
                ),
                "stages": rows(
                    select(
                        StageRunRow.id,
                        StageRunRow.stage,
                        StageRunRow.status,
                        StageRunRow.input_fingerprint,
                        StageRunRow.output_fingerprint,
                    )
                    .where(StageRunRow.pipeline_run_id == created.run_id)
                    .order_by(StageRunRow.ordinal)
                ),
                "tasks": rows(
                    select(
                        TaskRow.id,
                        TaskRow.stage_run_id,
                        TaskRow.status,
                        TaskRow.attempt_count,
                    )
                    .where(TaskRow.pipeline_run_id == created.run_id)
                    .order_by(TaskRow.id)
                ),
                "attempts": rows(
                    select(
                        TaskAttemptRow.id,
                        TaskAttemptRow.task_id,
                        TaskAttemptRow.attempt_number,
                        TaskAttemptRow.outcome,
                    )
                    .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                    .where(TaskRow.pipeline_run_id == created.run_id)
                    .order_by(TaskAttemptRow.task_id, TaskAttemptRow.attempt_number)
                ),
                "candidates": rows(
                    select(
                        CandidateClipRow.id,
                        CandidateClipRow.candidate_key,
                        CandidateClipRow.current_revision,
                        CandidateClipRow.selected_for_review,
                        CandidateClipRow.source_start_ms,
                        CandidateClipRow.source_end_ms,
                    )
                    .where(CandidateClipRow.pipeline_run_id == created.run_id)
                    .order_by(CandidateClipRow.id)
                ),
                "revisions": rows(
                    select(
                        EditPlanRevisionRow.id,
                        EditPlanRevisionRow.candidate_clip_id,
                        EditPlanRevisionRow.revision,
                        EditPlanRevisionRow.source_start_ms,
                        EditPlanRevisionRow.source_end_ms,
                    )
                    .join(
                        CandidateClipRow,
                        CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id,
                    )
                    .where(CandidateClipRow.pipeline_run_id == created.run_id)
                    .order_by(EditPlanRevisionRow.id)
                ),
                "assets": rows(
                    select(
                        AssetRow.id,
                        AssetRow.candidate_clip_id,
                        AssetRow.producer_attempt_id,
                        AssetRow.kind,
                        AssetRow.status,
                        AssetRow.relative_path,
                        AssetRow.size_bytes,
                        AssetRow.sha256,
                        AssetRow.input_fingerprint,
                    )
                    .join(TaskAttemptRow, TaskAttemptRow.id == AssetRow.producer_attempt_id)
                    .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                    .where(TaskRow.pipeline_run_id == created.run_id)
                    .order_by(AssetRow.id)
                ),
            }
        assert audit["runs"][0]["status"] == "completed"
        assert len(audit["stages"]) == len(audit["tasks"]) == 6
        assert all(row["status"] == "succeeded" for row in audit["stages"] + audit["tasks"])
        assert {row["stage_run_id"] for row in audit["tasks"]} == {
            row["id"] for row in audit["stages"]
        }
        assert {row["candidate_clip_id"] for row in audit["revisions"]} == {
            row["id"] for row in audit["candidates"] if row["selected_for_review"]
        }
        if lineage:
            database_slots = {row["candidate_key"]: row["id"] for row in audit["candidates"]}
            assert restored.persistent_candidate_ids == {
                semantic_id: database_slots[slot]
                for semantic_id, slot in restored.candidate_slot_map.items()
            }
        asset_bindings = {row["relative_path"]: row for row in audit["assets"]}
        for retained_file in retained_files:
            binding = asset_bindings.get(retained_file["path"])
            if binding is not None:
                assert binding["status"] == "committed"
                assert (binding["sha256"], binding["size_bytes"]) == (
                    retained_file["sha256"],
                    retained_file["size"],
                )
        assert all(
            path in asset_bindings
            for path in (
                "runs/g001/candidates/rough-candidates.json",
                "runs/g001/editing/edit-plans.json",
                rendered[0].relative_to(project_dir).as_posix(),
                subtitle.relative_to(project_dir).as_posix(),
            )
        )
        audit_bytes = json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8")
        write_bytes_immutable_no_follow(
            retained / "terminal-sqlite-audit.json", audit_bytes, max_bytes=1024 * 1024
        )
        retained_files.append(
            {
                "path": "terminal-sqlite-audit.json",
                "size": len(audit_bytes),
                "sha256": hashlib.sha256(audit_bytes).hexdigest(),
            }
        )
        # The immutable manifest is published last; incomplete copies are not evidence.
        manifest = {
            "kind": "synthetic-mini-lesson-engineering-evidence",
            "project_id": created.project_id,
            "run_id": created.run_id,
            "status": snapshot.status.value,
            "source_sha256": source_hash,
            "config": persisted.config_json,
            "config_fingerprint": persisted.config_fingerprint,
            "files": retained_files,
        }
        write_bytes_immutable_no_follow(
            retained / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            max_bytes=1024 * 1024,
        )
        assert not (data_dir / created.project_id / "runs/g001/output/manual_review").exists()
        with engine.connect() as connection:
            operations = set(connection.scalars(select(ApiUsageRow.operation)))
        assert operations == {
            "responses.semantic.discovery.initial",
            "responses.semantic.link_review.initial",
            "responses.semantic.topic_chain.initial",
            "responses.semantic.boundary_review.initial",
            "responses.semantic.global_review.initial",
        }
        if lineage:
            first_edit_bytes = (project_dir / "runs/g001/editing/edit-plans.json").read_bytes()
            second = service.create_run(
                project_id=created.project_id, config=config, max_stage_retries=1
            )
            resumed = runner.run_until_terminal(second.run_id, worker_id="lineage-cache-generation")
            assert resumed.status == PipelineRunStatus.COMPLETED
            second_rough = json.loads(
                (project_dir / "runs/g002/candidates/rough-candidates.json").read_text()
            )["semantic_v5"]
            second_edit = json.loads(
                (project_dir / "runs/g002/editing/edit-plans.json").read_text()
            )["semantic_v5"]
            second_result = UnifiedSemanticResultV5.model_validate_json(json.dumps(second_edit))
            assert second_result.lineage == restored.lineage
            assert second_rough["local_discovery_outputs"] == semantic["local_discovery_outputs"]
            assert second_rough["discovery_outputs"] == semantic["discovery_outputs"]
            assert second_rough["candidate_slot_map"] == semantic["candidate_slot_map"]
            assert second_result.persistent_candidate_ids != restored.persistent_candidate_ids
            assert second_result.run_metadata["cache_hit_count"] >= 5
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(func.count())
                        .select_from(ApiUsageRow)
                        .where(
                            ApiUsageRow.pipeline_run_id == second.run_id,
                            ApiUsageRow.operation.like("responses.semantic.%"),
                        )
                    )
                    == 0
                )
            assert (
                project_dir / "runs/g001/editing/edit-plans.json"
            ).read_bytes() == first_edit_bytes
            assert hashlib.sha256(source_path.read_bytes()).hexdigest() == source_hash
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_algorithm_b_v2_consolidates_agent_windows_without_forcing_top_n(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "semantic-source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=24_000)
    engine = create_sqlite_engine(tmp_path / "semantic.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        handler=PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
        heartbeat_seconds=5,
    )
    skill = load_semantic_discovery_skill("semantic_window_v2")
    consolidation_skill = load_semantic_continuous_skill()
    semantic_config = PipelineRunConfig(
        provider="mock",
        top_n=10,
        minimum_clip_ms=4_000,
        maximum_clip_ms=8_000,
        chunk_duration_ms=12_000,
        chunk_overlap_ms=2_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=270,
        preview_height=480,
        video_encoder="libx264",
        clipping_algorithm="b_v2_experimental",
        editing_prompt_version=skill.version,
        editing_prompt_sha256=skill.sha256,
        semantic_skill_version=skill.version,
        semantic_skill_sha256=skill.sha256,
        semantic_target_clip_ms=6_000,
        semantic_continuous_merge_enabled=True,
        semantic_consolidation_skill_version=consolidation_skill.version,
        semantic_consolidation_skill_sha256=consolidation_skill.sha256,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=semantic_config,
            max_stage_retries=1,
        )

        snapshot = runner.run_until_terminal(
            created.run_id,
            worker_id="semantic-integration",
        )

        assert snapshot.status == PipelineRunStatus.COMPLETED
        with engine.connect() as connection:
            window_count = connection.scalar(select(func.count()).select_from(CandidateClipRow))
            selected_count = connection.scalar(
                select(func.count())
                .select_from(CandidateClipRow)
                .where(CandidateClipRow.selected_for_review.is_(True))
            )
            assert window_count is not None and window_count >= 2
            assert selected_count is not None and 0 < selected_count < 10
            assert selected_count <= window_count
            assert (
                connection.scalar(select(func.count()).select_from(RenderJobRow)) == selected_count
            )

        empty_run = service.create_run(
            project_id=created.project_id,
            config=semantic_config.model_copy(update={"semantic_score_threshold": 80.0}),
            max_stage_retries=1,
        )
        empty_snapshot = runner.run_until_terminal(
            empty_run.run_id,
            worker_id="semantic-empty-integration",
        )
        assert empty_snapshot.status == PipelineRunStatus.COMPLETED
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(CandidateClipRow)
                    .where(
                        CandidateClipRow.pipeline_run_id == empty_run.run_id,
                        CandidateClipRow.selected_for_review.is_(True),
                    )
                )
                == 0
            )
            assert set(
                connection.scalars(
                    select(TaskRow.status).where(TaskRow.pipeline_run_id == empty_run.run_id)
                )
            ) == {TaskStatus.SUCCEEDED.value}
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
@pytest.mark.parametrize("bounded", [False, True])
def test_semantic_global_runs_full_discovery_review_and_no_render_plan(
    tmp_path: Path, bounded: bool
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "semantic-global-source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=24_000)
    engine = create_sqlite_engine(tmp_path / "semantic-global.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        handler=PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
        heartbeat_seconds=5,
    )
    discovery = load_semantic_global_prompt("discovery", "general")
    review = load_semantic_global_prompt("global_review", "general")
    config = (PipelineRunConfigV12 if bounded else PipelineRunConfig)(
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
        clipping_algorithm="semantic_global",
        editing_prompt_version=f"{discovery.version}.discovery",
        editing_prompt_sha256=discovery.sha256,
        semantic_profile="general",
        semantic_discovery_skill_version=f"{discovery.version}.discovery",
        semantic_discovery_skill_sha256=discovery.sha256,
        semantic_global_review_skill_version=f"{review.version}.global_review",
        semantic_global_review_skill_sha256=review.sha256,
        semantic_no_render=True,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=config,
            max_stage_retries=1,
        )

        snapshot = runner.run_until_terminal(
            created.run_id,
            worker_id="semantic-global-integration",
        )

        assert snapshot.status == PipelineRunStatus.COMPLETED
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(CandidateClipRow)) == 10
            assert connection.scalar(select(func.count()).select_from(EditPlanRevisionRow)) == 1
            assert connection.scalar(select(func.count()).select_from(RenderJobRow)) == 0
            assert connection.scalar(select(func.count()).select_from(ApiUsageRow)) == 2
            operations = set(
                connection.scalars(select(ApiUsageRow.operation).order_by(ApiUsageRow.operation))
            )
            assert operations == {
                "responses.semantic.discovery.initial",
                "responses.semantic.global_review.initial",
            }
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
@pytest.mark.parametrize("bounded", [False, True])
def test_semantic_windowed_prefetch_validates_and_caches_each_batch(
    tmp_path: Path, bounded: bool
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "semantic-windowed-source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=24_000)
    engine = create_sqlite_engine(tmp_path / "semantic-windowed.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        handler=PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
        heartbeat_seconds=5,
    )
    discovery = load_semantic_windowed_discovery_prompt("general")
    review = load_semantic_global_v2_review_prompt("general")
    config = (PipelineRunConfigV12 if bounded else PipelineRunConfig)(
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
        clipping_algorithm="semantic_windowed",
        editing_prompt_version=f"{discovery.version}.discovery",
        editing_prompt_sha256=discovery.sha256,
        semantic_profile="general",
        semantic_discovery_skill_version=f"{discovery.version}.discovery",
        semantic_discovery_skill_sha256=discovery.sha256,
        semantic_global_review_skill_version=f"{review.version}.global_review",
        semantic_global_review_skill_sha256=review.sha256,
        semantic_no_render=True,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=config,
            max_stage_retries=1,
        )

        snapshot = runner.run_until_terminal(
            created.run_id,
            worker_id="semantic-windowed-integration",
        )

        assert snapshot.status == PipelineRunStatus.COMPLETED
        cache_files = tuple(
            (data_dir / created.project_id / "runs/g001/candidates/semantic-cache/discovery").glob(
                "*.json"
            )
        )
        if bounded:
            from liveclip.db.models import SemanticUnitInvocationRow

            assert not cache_files
            with engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(func.count())
                        .select_from(SemanticUnitInvocationRow)
                        .where(
                            SemanticUnitInvocationRow.semantic_stage == "discovery",
                            SemanticUnitInvocationRow.disposition == "succeeded",
                        )
                    )
                    == 1
                )
        else:
            assert len(cache_files) == 1
        with engine.connect() as connection:
            operations = tuple(
                connection.scalars(select(ApiUsageRow.operation).order_by(ApiUsageRow.operation))
            )
            assert operations == (
                "responses.semantic.discovery.initial",
                "responses.semantic.global_review.initial",
            )
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
@pytest.mark.parametrize("bounded", [False, True])
def test_semantic_windowed_v3_runs_boundary_gate_before_candidate_global_review(
    tmp_path: Path,
    bounded: bool,
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "semantic-windowed-v3-source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=24_000)
    engine = create_sqlite_engine(tmp_path / "semantic-windowed-v3.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=30),
        repository=repository,
        pipeline_service=service,
        handler=PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
        heartbeat_seconds=5,
    )
    discovery = load_semantic_windowed_v2_discovery_prompt("general")
    boundary = load_semantic_global_v3_boundary_prompt("general")
    review = load_semantic_global_v3_review_prompt("general")
    config = (PipelineRunConfigV12 if bounded else PipelineRunConfig)(
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
        clipping_algorithm="semantic_windowed",
        editing_prompt_version=f"{discovery.version}.discovery",
        editing_prompt_sha256=discovery.sha256,
        semantic_profile="general",
        semantic_discovery_skill_version=f"{discovery.version}.discovery",
        semantic_discovery_skill_sha256=discovery.sha256,
        semantic_boundary_review_skill_version=f"{boundary.version}.boundary_review",
        semantic_boundary_review_skill_sha256=boundary.sha256,
        semantic_global_review_skill_version=f"{review.version}.global_review",
        semantic_global_review_skill_sha256=review.sha256,
        semantic_no_render=True,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=config,
            max_stage_retries=1,
        )

        snapshot = runner.run_until_terminal(
            created.run_id,
            worker_id="semantic-windowed-v3-integration",
        )

        assert snapshot.status == PipelineRunStatus.COMPLETED
        rough_candidates = json.loads(
            (
                data_dir / created.project_id / "runs/g001/candidates/rough-candidates.json"
            ).read_text(encoding="utf-8")
        )
        discovery_audit = rough_candidates["semantic_global"]["prompt_debug"]["agent_outputs"]
        assert len(discovery_audit) == 1
        assert discovery_audit[0]["input_unit_id"] == "window_batch_001"
        assert discovery_audit[0]["phase"] == "initial_or_schema_repaired"
        edit_plan = json.loads(
            (data_dir / created.project_id / "runs/g001/editing/edit-plans.json").read_text(
                encoding="utf-8"
            )
        )
        semantic = edit_plan["semantic_global"]
        assert semantic["boundary_review"]["candidate_count"] == 1
        assert semantic["validated"]["statistics"]["selected_count"] == 1
        assert semantic["validated"]["statistics"]["manual_count"] == 0
        assert semantic["validated"]["statistics"]["blocked_count"] == 0
        assert len(semantic["boundary_review"]["agent_outputs"]) == 1
        assert len(semantic["global_agent_outputs"]) == 1
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(CandidateClipRow)) == 1
            operations = tuple(
                connection.scalars(select(ApiUsageRow.operation).order_by(ApiUsageRow.operation))
            )
        assert operations == (
            "responses.semantic.boundary_review.initial",
            "responses.semantic.discovery.initial",
            "responses.semantic.global_review.initial",
        )
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_persistent_mock_pipeline_reaches_pending_review_with_real_proxies(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=32_000)
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    handlers = PipelineStageHandlers(
        data_dir=data_dir,
        allowed_media_roots=(media_root,),
        assets=SqlAlchemyAssetStore(engine),
        state=SqlAlchemyStageStateStore(engine),
    )
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        handler=handlers,
        heartbeat_seconds=5,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=PipelineRunConfig(
                provider="mock",
                top_n=3,
                minimum_clip_ms=8_000,
                maximum_clip_ms=12_000,
                chunk_duration_ms=12_000,
                chunk_overlap_ms=2_000,
                max_chunk_bytes=24_000_000,
                transcription_model="mock-asr-v1",
                llm_model="mock-llm-v1",
                preview_width=270,
                preview_height=480,
                video_encoder="libx264",
            ),
            max_stage_retries=1,
        )

        snapshot = runner.run_until_terminal(
            created.run_id,
            worker_id="integration-foreground",
        )

        assert snapshot.status == PipelineRunStatus.COMPLETED
        assert snapshot.progress == 100
        assert all(stage.progress == 100 for stage in snapshot.stages)
        assert service.get_project(created.project_id).status == ProjectStatus.PENDING_REVIEW
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(TaskRow)) == 6
            assert set(connection.scalars(select(TaskRow.status))) == {TaskStatus.SUCCEEDED.value}
            assert connection.scalar(select(func.count()).select_from(CandidateClipRow)) >= 3
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(CandidateClipRow)
                    .where(CandidateClipRow.selected_for_review.is_(True))
                )
                == 3
            )
            assert connection.scalar(select(func.count()).select_from(EditPlanRevisionRow)) == 3
            renders = connection.execute(
                select(RenderJobRow.status, AssetRow.relative_path)
                .join(AssetRow, AssetRow.id == RenderJobRow.asset_id)
                .order_by(RenderJobRow.id)
            ).all()
            assert len(renders) == 3
            assert {status for status, _ in renders} == {RenderStatus.SUCCEEDED.value}
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(AssetRow)
                    .where(AssetRow.kind == "clip_subtitle_srt")
                )
                == 3
            )
            assert not any(
                value is None
                for value in connection.scalars(select(RenderJobRow.subtitle_asset_id))
            )
            assert set(connection.scalars(select(AssetRow.status))) == {AssetStatus.COMMITTED.value}
        for _, relative_path in renders:
            proxy_path = data_dir / created.project_id / str(relative_path)
            probe = probe_media(proxy_path)
            video = next(
                stream for stream in probe["streams"] if stream.get("codec_type") == "video"
            )
            assert (video["width"], video["height"]) == (270, 480)
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_proxy_stage_recovers_committed_assets_after_precheckpoint_failure(
    tmp_path: Path,
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=16_000)
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=30)
    handler = FailOnceAfterProxyAssets(
        PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        )
    )
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        handler=handler,
        heartbeat_seconds=5,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=PipelineRunConfig(
                provider="mock",
                top_n=1,
                minimum_clip_ms=8_000,
                maximum_clip_ms=12_000,
                chunk_duration_ms=12_000,
                chunk_overlap_ms=2_000,
                max_chunk_bytes=24_000_000,
                transcription_model="mock-asr-v1",
                llm_model="mock-llm-v1",
                preview_width=270,
                preview_height=480,
                video_encoder="libx264",
            ),
            max_stage_retries=1,
        )

        snapshot = runner.run_until_terminal(
            created.run_id,
            worker_id="recovery-worker",
            poll_seconds=0.01,
        )

        assert snapshot.status == PipelineRunStatus.COMPLETED
        assert handler.injected is True
        assert handler.proxy_calls == 2
        with engine.connect() as connection:
            retry_count = connection.scalar(
                select(TaskRow.retry_count)
                .join(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
                .where(
                    StageRunRow.pipeline_run_id == created.run_id,
                    StageRunRow.stage == PipelineStage.PROXY_RENDER.value,
                )
            )
            assert retry_count == 1
            assert connection.scalar(select(func.count()).select_from(RenderJobRow)) == 1
            assert set(connection.scalars(select(AssetRow.status))) == {AssetStatus.COMMITTED.value}
            attempts = connection.execute(
                select(TaskAttemptRow.outcome, TaskAttemptRow.diagnostic_relative_path)
                .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                .join(StageRunRow, StageRunRow.id == TaskRow.stage_run_id)
                .where(
                    StageRunRow.pipeline_run_id == created.run_id,
                    StageRunRow.stage == PipelineStage.PROXY_RENDER.value,
                )
                .order_by(TaskAttemptRow.attempt_number)
            ).all()
            quality_paths = tuple(
                connection.scalars(
                    select(AssetRow.relative_path).where(
                        AssetRow.project_id == created.project_id,
                        AssetRow.kind == "render_quality_report",
                    )
                )
            )
        successful_diagnostics = [
            str(path) for outcome, path in attempts if outcome == "succeeded" and path is not None
        ]
        assert len(successful_diagnostics) == 1
        diagnostic_path = data_dir / created.project_id / successful_diagnostics[0]
        diagnostic_payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
        assert diagnostic_payload["status"] == "succeeded"
        assert str(tmp_path) not in json.dumps(diagnostic_payload)
        for relative_path in quality_paths:
            quality_payload = json.loads(
                (data_dir / created.project_id / str(relative_path)).read_text(encoding="utf-8")
            )
            assert "renderer_diagnostics" not in quality_payload
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_proxy_render_lifecycle_is_running_before_io_and_failed_after_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=16_000)
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    observed: list[str] = []

    def fail_render(**_kwargs: object) -> None:
        with engine.connect() as connection:
            observed.extend(connection.scalars(select(RenderJobRow.status)))
        raise FFmpegRenderError("injected encoder failure")

    monkeypatch.setattr(stage_handlers_module, "render_edit_plan_revision", fail_render)
    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=30),
        repository=repository,
        pipeline_service=service,
        handler=PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
        heartbeat_seconds=5,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=PipelineRunConfig(
                provider="mock",
                top_n=1,
                minimum_clip_ms=8_000,
                maximum_clip_ms=12_000,
                chunk_duration_ms=12_000,
                chunk_overlap_ms=2_000,
                max_chunk_bytes=24_000_000,
                transcription_model="mock-asr-v1",
                llm_model="mock-llm-v1",
                preview_width=270,
                preview_height=480,
                video_encoder="libx264",
            ),
            max_stage_retries=0,
        )

        snapshot = runner.run_until_terminal(created.run_id, worker_id="failure-worker")

        assert snapshot.status == PipelineRunStatus.FAILED
        assert observed == [RenderStatus.RUNNING.value]
        with engine.connect() as connection:
            render = connection.execute(
                select(
                    RenderJobRow.status,
                    RenderJobRow.task_id,
                    RenderJobRow.asset_id,
                    RenderJobRow.error_code,
                )
            ).one()
        assert render.status == RenderStatus.FAILED.value
        assert render.task_id is not None
        assert render.asset_id is None
        assert render.error_code == "RENDER_TEMPORARY"
    finally:
        engine.dispose(close=True)


@pytest.mark.integration
def test_proxy_render_cancellation_persists_failed_render_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=16_000)
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    run_id: list[str] = []

    def cancel_render(**_kwargs: object) -> None:
        service.cancel(run_id[0])
        raise FFmpegRenderCancelled("injected cancellation")

    monkeypatch.setattr(stage_handlers_module, "render_edit_plan_revision", cancel_render)
    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=30),
        repository=repository,
        pipeline_service=service,
        handler=PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        ),
        heartbeat_seconds=5,
    )
    try:
        created = service.create_project_and_run(
            source_path=source_path.resolve(),
            config=PipelineRunConfig(
                provider="mock",
                top_n=1,
                minimum_clip_ms=8_000,
                maximum_clip_ms=12_000,
                chunk_duration_ms=12_000,
                chunk_overlap_ms=2_000,
                max_chunk_bytes=24_000_000,
                transcription_model="mock-asr-v1",
                llm_model="mock-llm-v1",
                preview_width=270,
                preview_height=480,
                video_encoder="libx264",
            ),
            max_stage_retries=1,
        )
        run_id.append(created.run_id)

        snapshot = runner.run_until_terminal(created.run_id, worker_id="cancel-worker")

        assert snapshot.status == PipelineRunStatus.CANCELLED
        with engine.connect() as connection:
            render = connection.execute(select(RenderJobRow.status, RenderJobRow.error_code)).one()
        assert render == (RenderStatus.FAILED.value, "RENDER_CANCELLED")
    finally:
        engine.dispose(close=True)
