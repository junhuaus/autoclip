from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfig,
    PipelineService,
    StageWork,
)
from liveclip.application.stage_execution import (
    StageCancelled,
    StageExecutionResult,
)
from liveclip.application.stage_runner import RunOneOutcome, StageTaskRunner
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.domain.state_transitions import PipelineRunStatus


class CancellationHandler:
    def __init__(self, *, unexpected: bool = False) -> None:
        self.started = threading.Event()
        self._unexpected = unexpected

    def execute(
        self,
        work: StageWork,
        lease: LeaseIdentity,
        *,
        cancel_requested: Callable[[], bool],
    ) -> StageExecutionResult:
        del work, lease
        self.started.set()
        while not cancel_requested():
            threading.Event().wait(0.01)
        if self._unexpected:
            raise RuntimeError("unexpected handler error after cancellation")
        raise StageCancelled("cancelled by test")


def _config() -> PipelineRunConfig:
    return PipelineRunConfig(
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
    )


@pytest.fixture
def runner_context(
    tmp_path: Path,
) -> Iterator[tuple[Engine, PipelineService, StageTaskRunner, CancellationHandler]]:
    engine = create_sqlite_engine(tmp_path / "runner.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=5)
    handler = CancellationHandler()
    runner = StageTaskRunner(
        queue=queue,
        repository=repository,
        pipeline_service=service,
        handler=handler,
        heartbeat_seconds=1,
    )
    try:
        yield engine, service, runner, handler
    finally:
        engine.dispose(close=True)


def test_running_stage_observes_durable_cancel_and_acknowledges_it(
    runner_context: tuple[Engine, PipelineService, StageTaskRunner, CancellationHandler],
) -> None:
    _, service, runner, handler = runner_context
    created = service.create_project_and_run(
        source_path=Path("/allowed/source.mp4"),
        config=_config(),
        max_stage_retries=1,
    )
    observed: list[RunOneOutcome] = []
    thread = threading.Thread(
        target=lambda: observed.append(
            runner.run_one(worker_id="foreground", pipeline_run_id=created.run_id)
        )
    )
    thread.start()
    assert handler.started.wait(timeout=3)

    requested = service.cancel(created.run_id)
    assert requested.cancellation_requested is True
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert observed == [RunOneOutcome.CANCELLED]
    snapshot = service.get_run(created.run_id)
    assert snapshot.status == PipelineRunStatus.CANCELLED
    assert all(stage.status.value == "cancelled" for stage in snapshot.stages)


def test_unexpected_handler_error_after_cancel_still_acknowledges_cancellation(
    runner_context: tuple[Engine, PipelineService, StageTaskRunner, CancellationHandler],
) -> None:
    engine, service, _, _ = runner_context
    repository = SqlAlchemyPipelineRepository(engine)
    handler = CancellationHandler(unexpected=True)
    runner = StageTaskRunner(
        queue=SQLiteTaskQueue(engine, lease_seconds=5),
        repository=repository,
        pipeline_service=service,
        handler=handler,
        heartbeat_seconds=1,
    )
    created = service.create_project_and_run(
        source_path=Path("/allowed/unexpected-cancel.mp4"),
        config=_config(),
        max_stage_retries=1,
    )
    observed: list[RunOneOutcome] = []
    thread = threading.Thread(
        target=lambda: observed.append(
            runner.run_one(worker_id="foreground", pipeline_run_id=created.run_id)
        )
    )
    thread.start()
    assert handler.started.wait(timeout=3)

    service.cancel(created.run_id)
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert observed == [RunOneOutcome.CANCELLED]
    snapshot = service.get_run(created.run_id)
    assert snapshot.status == PipelineRunStatus.CANCELLED
    assert all(stage.status.value == "cancelled" for stage in snapshot.stages)
