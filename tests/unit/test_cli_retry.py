from __future__ import annotations

import threading
from contextlib import contextmanager
from io import StringIO
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import liveclip.cli.app as cli_module
from liveclip.application.pipeline import RunSnapshot, StageSnapshot
from liveclip.domain.state_transitions import (
    PipelineRunStatus,
    PipelineStage,
    ProjectStatus,
    StageRunStatus,
)


def _snapshot(
    *,
    run_id: str,
    project_id: str = "9" * 32,
    run_status: PipelineRunStatus,
    progress: int,
    stage_name: str,
    stage_status: StageRunStatus,
    retry_count: int = 0,
) -> RunSnapshot:
    return RunSnapshot(
        run_id=run_id,
        project_id=project_id,
        status=run_status,
        progress=progress,
        cancellation_requested=False,
        stages=(
            StageSnapshot(
                stage=stage_name,
                status=stage_status,
                progress=100 if stage_status == StageRunStatus.SUCCEEDED else 0,
                retry_count=retry_count,
            ),
        ),
    )


def test_cli_retry_wait_resumes_the_same_run(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = "1" * 32
    project_id = "2" * 32
    calls: list[tuple[str, str]] = []
    queued = _snapshot(
        run_id=run_id,
        project_id=project_id,
        run_status=PipelineRunStatus.QUEUED,
        progress=50,
        stage_name="candidates",
        stage_status=StageRunStatus.QUEUED,
    )
    completed = _snapshot(
        run_id=run_id,
        project_id=project_id,
        run_status=PipelineRunStatus.COMPLETED,
        progress=100,
        stage_name="candidates",
        stage_status=StageRunStatus.SUCCEEDED,
    )

    class PipelineService:
        def retry(self, value: str) -> object:
            calls.append(("retry", value))
            return queued

        def get_project(self, value: str) -> object:
            calls.append(("project", value))
            return SimpleNamespace(status=ProjectStatus.PENDING_REVIEW)

    class StageRunner:
        def run_until_terminal(self, value: str, *, worker_id: str) -> object:
            calls.append(("run", value))
            assert worker_id.startswith("foreground-retry:")
            return completed

    runtime = SimpleNamespace(
        pipeline_service=PipelineService(),
        stage_runner=StageRunner(),
    )

    @contextmanager
    def open_runtime(_settings: object):
        yield runtime

    monkeypatch.setattr(cli_module, "get_settings", lambda: object())
    monkeypatch.setattr(
        cli_module,
        "require_processing_ready",
        lambda _settings: None,
    )
    monkeypatch.setattr(
        cli_module,
        "LiveClipRuntime",
        SimpleNamespace(open=open_runtime),
    )

    result = CliRunner().invoke(cli_module.app, ["retry", run_id, "--wait"])

    assert result.exit_code == 0, result.output
    assert f"Project ID: {project_id}" in result.output
    assert f"Pipeline run ID: {run_id}" in result.output
    assert "Pipeline status: completed" in result.output
    assert "Project status: pending_review" in result.output
    assert "Progress: 100%" in result.output
    assert calls == [("retry", run_id), ("run", run_id), ("project", project_id)]


def test_foreground_wait_reports_stage_liveness_while_runner_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "3" * 32
    queued = _snapshot(
        run_id=run_id,
        run_status=PipelineRunStatus.RUNNING,
        progress=50,
        stage_name="candidates",
        stage_status=StageRunStatus.QUEUED,
    )
    running = _snapshot(
        run_id=run_id,
        run_status=PipelineRunStatus.RUNNING,
        progress=50,
        stage_name="candidates",
        stage_status=StageRunStatus.RUNNING,
        retry_count=1,
    )
    completed = _snapshot(
        run_id=run_id,
        run_status=PipelineRunStatus.COMPLETED,
        progress=100,
        stage_name="candidates",
        stage_status=StageRunStatus.SUCCEEDED,
    )
    lines: list[str] = []

    class PipelineService:
        def get_run(self, value: str) -> object:
            assert value == run_id
            return running

    class StageRunner:
        def run_until_terminal(self, value: str, *, worker_id: str) -> object:
            assert value == run_id
            assert worker_id == "foreground"
            threading.Event().wait(0.04)
            return completed

    monkeypatch.setattr(cli_module, "_PROGRESS_REPORT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(cli_module.typer, "echo", lambda value: lines.append(str(value)))

    result = cli_module._run_pipeline_with_progress(
        pipeline_service=PipelineService(),  # type: ignore[arg-type]
        stage_runner=StageRunner(),  # type: ignore[arg-type]
        initial_snapshot=queued,  # type: ignore[arg-type]
        worker_id="foreground",
    )

    assert result is completed
    assert "LiveClip 自动切片" in lines[0]
    assert "候选发现" in lines[0]
    assert any("候选发现" in line and "重试 1" in line for line in lines)
    assert "选择切片并生成交付包" in lines[-1]


def test_interactive_dashboard_redraws_one_terminal_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InteractiveOutput(StringIO):
        def isatty(self) -> bool:
            return True

    output = InteractiveOutput()
    monkeypatch.setattr(cli_module.sys, "stdout", output)
    dashboard = cli_module._TerminalDashboard()

    dashboard.open()
    dashboard.show("first\nsecond")
    dashboard.show("updated\nframe")
    dashboard.close()

    rendered = output.getvalue()
    assert rendered.startswith("\x1b[?25l\x1b[Jfirst\nsecond\n")
    assert "\x1b[2F\x1b[Jupdated\nframe\n" in rendered
    assert rendered.endswith("\x1b[?25h")


def test_foreground_interrupt_records_durable_run_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "4" * 32
    cancelled: list[str] = []
    queued = _snapshot(
        run_id=run_id,
        run_status=PipelineRunStatus.RUNNING,
        progress=33,
        stage_name="transcribe",
        stage_status=StageRunStatus.RUNNING,
    )

    class PipelineService:
        def cancel(self, value: str) -> object:
            cancelled.append(value)
            return object()

    class StageRunner:
        def run_until_terminal(self, value: str, *, worker_id: str) -> object:
            assert value == run_id
            assert worker_id == "foreground"
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        cli_module._run_pipeline_with_progress(
            pipeline_service=PipelineService(),  # type: ignore[arg-type]
            stage_runner=StageRunner(),  # type: ignore[arg-type]
            initial_snapshot=queued,  # type: ignore[arg-type]
            worker_id="foreground",
        )

    assert cancelled == [run_id]


def test_named_stage_execution_stops_after_the_requested_stage() -> None:
    run_id = "5" * 32
    queued = _snapshot(
        run_id=run_id,
        run_status=PipelineRunStatus.RUNNING,
        progress=33,
        stage_name="transcribe",
        stage_status=StageRunStatus.QUEUED,
    )
    succeeded = _snapshot(
        run_id=run_id,
        run_status=PipelineRunStatus.RUNNING,
        progress=50,
        stage_name="transcribe",
        stage_status=StageRunStatus.SUCCEEDED,
    )
    calls: list[tuple[str, str]] = []

    class PipelineService:
        def get_run(self, value: str) -> RunSnapshot:
            assert value == run_id
            return succeeded if calls else queued

    class StageRunner:
        def run_one(self, *, worker_id: str, pipeline_run_id: str) -> object:
            calls.append((worker_id, pipeline_run_id))
            return object()

    result = cli_module._run_until_stage(
        pipeline_service=PipelineService(),  # type: ignore[arg-type]
        stage_runner=StageRunner(),  # type: ignore[arg-type]
        run_id=run_id,
        target=PipelineStage.TRANSCRIBE,
        worker_id="foreground-transcribe",
    )

    assert result == succeeded
    assert calls == [("foreground-transcribe", run_id)]


@pytest.mark.parametrize(
    ("profile", "durations"),
    [("short_highlight", (45_000, 60_000, 90_000)), ("mini_lesson", (90_000, 180_000, 300_000))],
)
def test_auto_submits_canonical_durable_request_without_foreground_work(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    durations: tuple[int, int, int],
) -> None:
    from liveclip.config.settings import Settings

    calls: list[dict[str, object]] = []
    observed: list[tuple[object, ...]] = []
    messages: list[str] = []
    echo = cli_module.typer.echo

    def record_echo(message: object, **kwargs: object) -> None:
        messages.append(str(message))
        echo(message, **kwargs)

    def create(**kwargs: object) -> object:
        # The recovery identity must already be visible if this response is lost.
        assert "Request key: recover-me" in messages[-1]
        calls.append(kwargs)
        return SimpleNamespace(intent_id="saved-goal")

    def forbidden(**kwargs: object) -> None:
        pytest.fail("auto invoked foreground pipeline work")

    runtime = SimpleNamespace(
        workspace_service=SimpleNamespace(
            get_user_by_username=lambda _: SimpleNamespace(user_id="caller")
        ),
        completion_service=SimpleNamespace(create_project_and_run_with_goal=create),
    )

    @contextmanager
    def open_runtime(settings: object):
        yield runtime

    monkeypatch.setattr(cli_module, "get_settings", lambda: Settings(ai_provider="mock"))
    monkeypatch.setattr(cli_module.typer, "echo", record_echo)
    monkeypatch.setattr(cli_module.LiveClipRuntime, "open", open_runtime)
    monkeypatch.setattr(cli_module, "run_pipeline", forbidden)
    monkeypatch.setattr(cli_module, "run_worker", forbidden)
    monkeypatch.setattr(
        cli_module,
        "observe_completion",
        lambda *args, **kwargs: observed.append((*args, kwargs)),
    )
    args = [
        "auto",
        "/Users/test/input/live.ts",
        "--clip-profile",
        profile,
        "--request-key",
        "recover-me",
        "--no-watch",
    ]
    for _ in range(2):
        result = CliRunner().invoke(cli_module.app, args)
        assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert calls[0]["idempotency"] == calls[1]["idempotency"]
    config = calls[0]["config"]
    assert (
        config.minimum_clip_ms,
        config.semantic_target_clip_ms,
        config.maximum_clip_ms,
    ) == durations
    assert config.clip_profile.value == profile
    assert config.top_n == 15
    assert config.clipping_algorithm == "semantic_windowed"
    assert config.semantic_profile == "general"
    assert config.semantic_score_threshold == 75.0
    assert config.semantic_full_context_budget_ratio == 0.58
    assert config.semantic_model_context_tokens == 128_000
    options = calls[0]["options"]
    assert options.preset_id == f"{profile}_v1"
    assert options.selection_policy.value == "default"
    assert options.include_zip is True
    assert observed == [(runtime, "saved-goal", "caller", {"watch": False})] * 2


def test_finish_requires_a_foreground_rendering_run() -> None:
    result = CliRunner().invoke(
        cli_module.app,
        ["run", "--input", "/Users/test/input/live.ts", "--finish"],
    )

    assert result.exit_code == 2
    assert "--finish requires --wait" in result.output
