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
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    ApiUsageRow,
    AssetRow,
    CandidateClipRow,
    EditPlanRevisionRow,
    RenderJobRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.state_transitions import (
    AssetStatus,
    FailureClass,
    PipelineRunStatus,
    PipelineStage,
    ProjectStatus,
    RenderStatus,
    TaskStatus,
)
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
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
def test_semantic_global_runs_full_discovery_review_and_no_render_plan(tmp_path: Path) -> None:
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
    config = PipelineRunConfig(
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
