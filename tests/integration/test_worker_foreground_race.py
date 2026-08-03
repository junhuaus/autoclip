from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfig,
    PipelineService,
    StageWork,
)
from liveclip.application.stage_execution import StageExecutionResult
from liveclip.application.stage_runner import RunOneOutcome, StageTaskRunner
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.state_transitions import PipelineRunStatus, PipelineStage
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.services.demo_media import create_demo_source


class BlockingCountingHandler:
    def __init__(self, delegate: PipelineStageHandlers) -> None:
        self._delegate = delegate
        self._lock = threading.Lock()
        self.ingest_started = threading.Event()
        self.release_ingest = threading.Event()
        self.counts: Counter[PipelineStage] = Counter()

    def execute(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        with self._lock:
            self.counts[work.stage] += 1
        if work.stage == PipelineStage.INGEST:
            self.ingest_started.set()
            if not self.release_ingest.wait(timeout=5):
                raise RuntimeError("test did not release ingest")
        return self._delegate.execute(work, lease, cancel_requested=cancel_requested)


@pytest.mark.integration
def test_foreground_and_worker_share_one_lease_and_execute_each_stage_once(
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
    handler = BlockingCountingHandler(
        PipelineStageHandlers(
            data_dir=data_dir,
            allowed_media_roots=(media_root,),
            assets=SqlAlchemyAssetStore(engine),
            state=SqlAlchemyStageStateStore(engine),
        )
    )
    foreground = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        handler=handler,
        heartbeat_seconds=5,
    )
    worker = StageTaskRunner(
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
        snapshots: list[PipelineRunStatus] = []
        failures: list[BaseException] = []

        def run_foreground() -> None:
            try:
                snapshots.append(
                    foreground.run_until_terminal(
                        created.run_id,
                        worker_id="cli-foreground",
                        poll_seconds=0.01,
                    ).status
                )
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=run_foreground)
        thread.start()
        assert handler.ingest_started.wait(timeout=5)

        assert (
            worker.run_one(worker_id="independent-worker", pipeline_run_id=created.run_id)
            == RunOneOutcome.IDLE
        )
        handler.release_ingest.set()
        thread.join(timeout=60)

        assert not thread.is_alive()
        assert failures == []
        assert snapshots == [PipelineRunStatus.COMPLETED]
        assert handler.counts == Counter({stage: 1 for stage in PipelineStage})
    finally:
        handler.release_ingest.set()
        engine.dispose(close=True)
