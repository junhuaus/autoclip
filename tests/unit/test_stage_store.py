from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from liveclip.application.pipeline import LeaseIdentity, PipelineRunConfig, PipelineService
from liveclip.application.stage_execution import StageMutationFence
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import SourceMediaRow
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore, StageDataConflict
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.media.fingerprint import stream_sha256
from liveclip.media.models import SourceMediaMetadata


def test_stale_lease_cannot_write_stage_domain_rows(tmp_path: Path) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source-bytes")
    stat = source_path.stat()
    engine = create_sqlite_engine(tmp_path / "state.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    queue = SQLiteTaskQueue(engine, lease_seconds=1)
    try:
        service.create_project_and_run(
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
        lease = queue.claim(worker_id="stale-worker")
        assert lease is not None
        identity = LeaseIdentity(
            task_id=lease.task_id,
            worker_id=lease.worker_id,
            lease_token=lease.lease_token,
        )
        work = repository.start_or_resume_stage(identity)
        fence = StageMutationFence(
            lease=identity,
            project_id=work.project_id,
            run_id=work.run_id,
            stage_run_id=work.stage_run_id,
            generation=work.generation,
        )
        assert queue.recover_expired(now=lease.lease_expires_at).failed == 1
        source = SourceMediaMetadata(
            resolved_path=source_path.resolve(),
            filename=source_path.name,
            size_bytes=stat.st_size,
            sha256=stream_sha256(source_path),
            duration_ms=10_000,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            video_codec="h264",
            video_width=1280,
            video_height=720,
            video_frame_rate=30.0,
            audio_codec="aac",
            audio_sample_rate_hz=48_000,
            audio_channels=2,
            mtime_ns=stat.st_mtime_ns,
            inode=stat.st_ino,
            device=stat.st_dev,
        )

        with pytest.raises(StageDataConflict, match="lost its task lease"):
            SqlAlchemyStageStateStore(engine).save_source(fence, source=source)

        with engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(SourceMediaRow)) == 0
    finally:
        engine.dispose(close=True)
