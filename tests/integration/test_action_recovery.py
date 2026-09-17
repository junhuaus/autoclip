from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from typer.testing import CliRunner

import liveclip.cli.app as cli
from liveclip.api.app import create_app
from liveclip.application.pipeline import PipelineConflict
from liveclip.application.stage_execution import StageExecutionError
from liveclip.bootstrap import LiveClipRuntime, pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.db.models import ApiUsageRow, PipelineRunRow, RenderJobRow
from liveclip.domain.state_transitions import FailureClass, PipelineRunStatus, PipelineStage
from liveclip.renderer.quality import probe_media
from liveclip.services.demo_media import create_demo_source

pytestmark = pytest.mark.integration


class FailAfterCheckpoint:
    def __init__(self, delegate, stage):
        self.delegate, self.stage = delegate, stage

    def execute(self, work, lease, *, cancel_requested):
        result = self.delegate.execute(work, lease, cancel_requested=cancel_requested)
        if work.stage == self.stage:
            raise StageExecutionError(
                failure_class=FailureClass.TRANSIENT,
                error_code="INJECTED_AFTER_COMMIT",
                safe_message="Synthetic checkpoint interruption",
            )
        return result


def settings(tmp_path, provider="mock"):
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        ai_provider=provider,
        allowed_media_roots_raw=str(tmp_path / "media"),
        video_encoder="libx264",
        openai_api_key=None,
        openrouter_api_key=None,
        codex_executable="/definitely/missing/codex",
    )


@pytest.mark.parametrize(
    "stage,entry",
    [
        (PipelineStage.EDIT, "service"),
        (PipelineStage.EDIT, "api"),
        (PipelineStage.PROXY_RENDER, "cli"),
    ],
)
def test_committed_processing_recovers_without_unused_providers(
    tmp_path, monkeypatch, stage, entry
):
    configured = settings(tmp_path)
    source = tmp_path / "media" / "source.mp4"
    create_demo_source(output_path=source, duration_ms=16_000)
    config = pipeline_config_from_settings(
        configured, top_n=1, minimum_clip_seconds=4, maximum_clip_seconds=8
    ).model_copy(update={"preview_width": 270, "preview_height": 480})
    with LiveClipRuntime.open(configured) as runtime:
        runtime.stage_runner._handler = FailAfterCheckpoint(runtime.stage_runner._handler, stage)
        created = runtime.pipeline_service.create_project_and_run(
            source_path=source, config=config, max_stage_retries=0
        )
        failed = runtime.stage_runner.run_until_terminal(created.run_id, worker_id="checkpoint")
        assert failed.status == PipelineRunStatus.FAILED
        assert failed.error_code == "INJECTED_AFTER_COMMIT"
        actions = runtime.pipeline_repository.recovery_actions(created.run_id)
        assert actions.required == ()
        with runtime.engine.connect() as connection:
            calls_before = tuple(connection.scalars(select(ApiUsageRow.id)))
    unavailable = settings(tmp_path, "openai")
    if entry == "cli":
        monkeypatch.setattr(cli, "get_settings", lambda: unavailable)
        result = CliRunner().invoke(cli.app, ["retry", created.run_id, "--wait"])
        assert result.exit_code == 0, result.output
    with LiveClipRuntime.open(unavailable) as runtime:
        if entry == "api":
            with TestClient(create_app(unavailable, runtime=runtime)) as client:
                assert not client.get("/api/v1/health").json()["providers"]["processing_ready"]
                result = client.post(f"/api/v1/runs/{created.run_id}/retry")
                assert result.status_code == 202, result.text
        elif entry == "service":
            runtime.pipeline_service.retry(created.run_id)
        snapshot = runtime.stage_runner.run_until_terminal(
            created.run_id, worker_id="local-recovery"
        )
        assert snapshot.status == PipelineRunStatus.COMPLETED
        with runtime.engine.connect() as connection:
            assert tuple(connection.scalars(select(ApiUsageRow.id))) == calls_before
            assert connection.scalar(select(RenderJobRow.id)) is not None
        clips = runtime.clip_query_service.list_project_clips(created.project_id)
        assert len(clips) == 1
        # Read the actual current media through the committed Asset authority.
        from liveclip.db.models import AssetRow

        with runtime.engine.connect() as connection:
            relative = connection.scalar(
                select(AssetRow.relative_path).where(AssetRow.kind == "review_proxy")
            )
        assert relative is not None
        assert probe_media(runtime.data_dir / created.project_id / relative)["streams"]


def test_stale_readiness_cannot_queue_a_changed_run(tmp_path):
    configured = settings(tmp_path)
    with LiveClipRuntime.open(configured) as runtime:
        config = pipeline_config_from_settings(configured)
        created = runtime.pipeline_service.create_project_and_run(
            source_path=tmp_path / "media" / "missing.mp4", config=config, max_stage_retries=0
        )
        actions = runtime.pipeline_repository.recovery_actions(created.run_id)
        with runtime.engine.begin() as connection:
            connection.execute(
                update(PipelineRunRow)
                .where(PipelineRunRow.id == created.run_id)
                .values(manual_retry_count=1)
            )
        with pytest.raises(PipelineConflict, match="remaining actions changed"):
            runtime.pipeline_repository.retry_failed_run(created.run_id, expected_actions=actions)
        assert runtime.pipeline_service.get_run(created.run_id).status == PipelineRunStatus.QUEUED


@pytest.mark.parametrize("mismatched_runtime", [False, True])
def test_unavailable_semantic_provider_blocks_before_any_asr_call(tmp_path, mismatched_runtime):
    configured = settings(tmp_path, "openai-codex")
    source = tmp_path / "media" / "source.mp4"
    create_demo_source(output_path=source, duration_ms=10_000)
    config = pipeline_config_from_settings(settings(tmp_path)).model_copy(
        update={"provider": "mock" if mismatched_runtime else "openai-codex"}
    )
    with LiveClipRuntime.open(configured) as runtime:
        created = runtime.pipeline_service.create_project_and_run(
            source_path=source, config=config, max_stage_retries=0
        )
        result = runtime.stage_runner.run_until_terminal(created.run_id, worker_id="preflight")
        assert result.status == PipelineRunStatus.FAILED
        assert result.error_code == "ACTION_NOT_READY"
        assert (
            "PERSISTED_PROVIDER_MISMATCH" if mismatched_runtime else "CODEX_CLI_NOT_READY"
        ) in result.safe_error_message
        with runtime.engine.connect() as connection:
            assert list(connection.scalars(select(ApiUsageRow.id))) == []
        with TestClient(create_app(configured, runtime=runtime)) as client:
            response = client.post(f"/api/v1/runs/{created.run_id}/retry")
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "ACTION_NOT_READY"
        assert runtime.pipeline_service.get_run(created.run_id).status == PipelineRunStatus.FAILED
