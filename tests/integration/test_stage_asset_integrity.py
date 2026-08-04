from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine

import liveclip.pipeline.stage_handlers as stage_handlers_module
from liveclip.application.pipeline import PipelineRunConfig, PipelineService
from liveclip.application.stage_runner import RunOneOutcome, StageTaskRunner
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import AssetRow
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.stage_store import SqlAlchemyStageStateStore
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.pipeline.stage_handlers import PipelineStageHandlers
from liveclip.services.demo_media import create_demo_source


@dataclass(frozen=True, slots=True)
class _PipelineContext:
    engine: Engine
    service: PipelineService
    runner: StageTaskRunner
    run_id: str
    project_dir: Path


def _pipeline(tmp_path: Path) -> _PipelineContext:
    media_root = tmp_path / "media"
    source_path = media_root / "source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=16_000)
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
    return _PipelineContext(
        engine=engine,
        service=service,
        runner=runner,
        run_id=created.run_id,
        project_dir=data_dir / created.project_id,
    )


def _advance(context: _PipelineContext, count: int) -> None:
    for index in range(count):
        assert (
            context.runner.run_one(
                worker_id=f"integrity-worker-{index}",
                pipeline_run_id=context.run_id,
            )
            == RunOneOutcome.SUCCEEDED
        )


def _asset_path(context: _PipelineContext, kind: str) -> Path:
    with context.engine.connect() as connection:
        relative_path = connection.scalar(
            select(AssetRow.relative_path).where(
                AssetRow.kind == kind,
                AssetRow.project_id == context.project_dir.name,
            )
        )
    assert isinstance(relative_path, str)
    return context.project_dir / relative_path


@pytest.mark.integration
def test_tampered_audio_manifest_cannot_redirect_asr_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _pipeline(tmp_path)
    try:
        _advance(context, 2)
        manifest_path = _asset_path(context, "audio_manifest")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        secret = tmp_path / "must-not-upload.m4a"
        secret.write_bytes(b"private-local-audio" * 1_000)
        payload["chunks"][0]["path"] = str(secret.resolve())
        payload["chunks"][0]["size_bytes"] = secret.stat().st_size
        payload["chunks"][0]["sha256"] = hashlib.sha256(secret.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        provider_called = False

        def forbidden_asr(*_args: object, **_kwargs: object) -> object:
            nonlocal provider_called
            provider_called = True
            raise AssertionError("ASR received a dependency that did not match its Asset SHA")

        monkeypatch.setattr(stage_handlers_module, "transcribe_chunks_detailed", forbidden_asr)

        assert (
            context.runner.run_one(
                worker_id="tampered-manifest",
                pipeline_run_id=context.run_id,
            )
            == RunOneOutcome.FAILED
        )
        assert provider_called is False
        snapshot = context.service.get_run(context.run_id)
        assert snapshot.error_code == "TRANSCRIBE_OUTPUT_INVALID"
    finally:
        context.engine.dispose(close=True)


@pytest.mark.integration
def test_symlinked_transcript_dependency_is_rejected_before_candidate_logic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _pipeline(tmp_path)
    try:
        _advance(context, 3)
        transcript_path = _asset_path(context, "transcript_json")
        outside = tmp_path / "outside-transcript.json"
        outside.write_bytes(transcript_path.read_bytes())
        transcript_path.unlink()
        transcript_path.symlink_to(outside)
        candidate_logic_called = False

        def forbidden_candidates(*_args: object, **_kwargs: object) -> object:
            nonlocal candidate_logic_called
            candidate_logic_called = True
            raise AssertionError("candidate generation received a symbolic dependency")

        monkeypatch.setattr(stage_handlers_module, "generate_candidates", forbidden_candidates)

        assert (
            context.runner.run_one(
                worker_id="symlinked-transcript",
                pipeline_run_id=context.run_id,
            )
            == RunOneOutcome.FAILED
        )
        assert candidate_logic_called is False
        snapshot = context.service.get_run(context.run_id)
        assert snapshot.error_code == "CANDIDATES_OUTPUT_INVALID"
    finally:
        context.engine.dispose(close=True)


@pytest.mark.integration
def test_tampered_committed_edit_plan_is_rejected_before_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _pipeline(tmp_path)
    try:
        _advance(context, 5)
        edit_plan_path = _asset_path(context, "edit_plans")
        payload = json.loads(edit_plan_path.read_text(encoding="utf-8"))
        payload["revisions"][0]["revision"]["plan"]["title"] = "篡改后的标题"
        edit_plan_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        renderer_called = False

        def forbidden_render(**_kwargs: object) -> object:
            nonlocal renderer_called
            renderer_called = True
            raise AssertionError("renderer received a tampered committed EditPlan")

        monkeypatch.setattr(stage_handlers_module, "render_edit_plan_revision", forbidden_render)

        assert (
            context.runner.run_one(
                worker_id="tampered-edit-plan",
                pipeline_run_id=context.run_id,
            )
            == RunOneOutcome.FAILED
        )
        assert renderer_called is False
        snapshot = context.service.get_run(context.run_id)
        assert snapshot.error_code == "PROXY_RENDER_OUTPUT_INVALID"
    finally:
        context.engine.dispose(close=True)
