from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from liveclip.application.pipeline import PipelineRunConfig, PipelineService
from liveclip.application.stage_runner import StageTaskRunner
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import AudioChunkRow, SourceMediaRow, StageRunRow, TaskRow
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.state_transitions import (
    PipelineRunStatus,
    PipelineStage,
    ProjectStatus,
    StageRunStatus,
    TaskStatus,
)
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.services.demo_media import create_demo_source


@pytest.mark.integration
def test_import_only_run_stops_after_verified_ingest(tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=10_000)
    engine = create_sqlite_engine(tmp_path / "liveclip.sqlite3")
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
    config = PipelineRunConfig(
        provider="mock",
        top_n=3,
        minimum_clip_ms=1_000,
        maximum_clip_ms=4_000,
        chunk_duration_ms=10_000,
        chunk_overlap_ms=1_000,
        max_chunk_bytes=24_000_000,
        transcription_model="mock-asr-v1",
        llm_model="mock-llm-v1",
        preview_width=270,
        preview_height=480,
        video_encoder="libx264",
    )
    try:
        created = service.import_project(
            source_path=source_path.resolve(),
            config=config,
            max_stage_retries=1,
        )

        run = runner.run_until_terminal(created.run_id, worker_id="import-worker")

        assert run.status == PipelineRunStatus.COMPLETED
        assert run.progress == 100
        assert run.stages[0].stage == PipelineStage.INGEST.value
        assert run.stages[0].status == StageRunStatus.SUCCEEDED
        assert all(stage.status == StageRunStatus.SKIPPED for stage in run.stages[1:])
        assert service.get_project(created.project_id).status == ProjectStatus.IMPORTED
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(SourceMediaRow)) == 1
            assert connection.scalar(select(func.count()).select_from(AudioChunkRow)) == 0
            assert connection.scalar(select(func.count()).select_from(TaskRow)) == 1
            assert set(connection.scalars(select(TaskRow.status))) == {TaskStatus.SUCCEEDED.value}
            assert (
                connection.scalar(
                    select(func.count())
                    .select_from(StageRunRow)
                    .where(StageRunRow.status == StageRunStatus.SKIPPED.value)
                )
                == 5
            )
    finally:
        engine.dispose(close=True)
