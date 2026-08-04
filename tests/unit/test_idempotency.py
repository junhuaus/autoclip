from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import func, select

from liveclip.application.idempotency import IdempotencyConflict, build_idempotency_context
from liveclip.application.pipeline import PipelineRunConfig, PipelineService
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import IdempotencyRecordRow, PipelineRunRow, ProjectRow
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository


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
        preview_width=540,
        preview_height=960,
        video_encoder="libx264",
    )


def test_idempotent_pipeline_creation_is_atomic_and_key_is_hashed(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "idempotency.sqlite3")
    Base.metadata.create_all(engine)
    service = PipelineService(SqlAlchemyPipelineRepository(engine))
    source_path = Path("/allowed/source.mp4")
    raw_key = "request-key-that-must-not-be-persisted"
    context = build_idempotency_context(
        raw_key=raw_key,
        caller_scope="local-test",
        operation_scope="POST:/api/v1/jobs",
        request_payload={
            "source_path": str(source_path),
            "config": _config().model_dump(mode="json"),
            "max_stage_retries": 3,
        },
    )
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = tuple(
                executor.map(
                    lambda _: service.create_project_and_run(
                        source_path=source_path,
                        config=_config(),
                        max_stage_retries=3,
                        idempotency=context,
                    ),
                    range(8),
                )
            )

        assert len({result.project_id for result in results}) == 1
        assert len({result.run_id for result in results}) == 1
        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(ProjectRow)) == 1
            assert connection.scalar(select(func.count()).select_from(PipelineRunRow)) == 1
            record = connection.execute(
                select(
                    IdempotencyRecordRow.key_hash,
                    IdempotencyRecordRow.request_hash,
                    IdempotencyRecordRow.resource_id,
                )
            ).one()
            assert record.key_hash == context.key_hash
            assert raw_key not in repr(record)

        conflicting = build_idempotency_context(
            raw_key=raw_key,
            caller_scope="local-test",
            operation_scope="POST:/api/v1/jobs",
            request_payload={"source_path": "/allowed/different.mp4"},
        )
        with pytest.raises(IdempotencyConflict):
            service.create_project_and_run(
                source_path=Path("/allowed/different.mp4"),
                config=_config(),
                max_stage_retries=3,
                idempotency=conflicting,
            )
    finally:
        engine.dispose(close=True)


@pytest.mark.parametrize("raw_key", ("", "has whitespace", "含中文", "x" * 201))
def test_idempotency_key_rejects_unsafe_or_unbounded_values(raw_key: str) -> None:
    with pytest.raises(ValueError):
        build_idempotency_context(
            raw_key=raw_key,
            caller_scope="local-test",
            operation_scope="POST:/api/v1/jobs",
            request_payload={},
        )
