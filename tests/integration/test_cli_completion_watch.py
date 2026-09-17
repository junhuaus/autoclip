"""Disposable durable CLI identity and authorized observation regressions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from typer.testing import CliRunner

from liveclip.application.completion import CompletionResourceNotFound
from liveclip.bootstrap import LiveClipRuntime
from liveclip.cli.app import app
from liveclip.config.settings import get_settings
from liveclip.db.models import CompletionIntentRow, ProjectMemberRow, ProjectRow, TaskRow

pytestmark = pytest.mark.integration


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    media = tmp_path / "source.mp4"
    media.write_bytes(b"synthetic read-only reference; never processed by this test")
    monkeypatch.setenv("LIVECLIP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LIVECLIP_ALLOWED_MEDIA_ROOTS", str(tmp_path))
    monkeypatch.setenv("LIVECLIP_AI_PROVIDER", "mock")
    get_settings.cache_clear()
    try:
        yield media
    finally:
        get_settings.cache_clear()


def saved(output: str) -> dict[str, str]:
    return json.loads(next(line for line in output.splitlines() if line.startswith("{")))


@pytest.mark.parametrize("profile", ["short_highlight", "mini_lesson"])
def test_auto_replays_saved_identity_and_rejects_changed_selection(
    source: Path, profile: str
) -> None:
    runner = CliRunner()
    arguments = [
        "auto",
        str(source),
        "--no-watch",
        "--request-key",
        "replay-me",
        "--clip-profile",
        profile,
    ]
    first = runner.invoke(app, arguments)
    assert first.exit_code == 0, first.output
    assert first.output.index("Request key: replay-me") < first.output.index('"Project ID"')
    second = runner.invoke(app, arguments)
    assert second.exit_code == 0, second.output
    assert saved(first.output) == saved(second.output)
    changed = runner.invoke(app, [*arguments, "--selection-policy", "manual"])
    assert changed.exit_code == 1
    with LiveClipRuntime.open(get_settings()) as runtime:
        actor = runtime.workspace_service.get_user_by_username(get_settings().workspace_username)
        goals = runtime.completion_service.list_for_project(
            saved(first.output)["Project ID"], actor_user_id=actor.user_id
        )
        assert len(goals) == 1
        assert goals[0].options.preset_id == f"{profile}_v1"
        assert goals[0].options.selection_policy.value == "default"
        with runtime.engine.connect() as connection:
            assert len(connection.execute(select(ProjectRow.id)).all()) == 1
            tasks = connection.execute(select(TaskRow.status)).scalars().all()
            assert tasks and set(tasks) == {"queued"}
    assert source.read_bytes().startswith(b"synthetic read-only reference")


def test_lookup_matches_get_has_no_writes_and_checks_empty_project_authority(source: Path) -> None:
    result = CliRunner().invoke(app, ["auto", str(source), "--no-watch"])
    assert result.exit_code == 0, result.output
    project_id = saved(result.output)["Project ID"]
    with LiveClipRuntime.open(get_settings()) as runtime:
        actor = runtime.workspace_service.get_user_by_username(get_settings().workspace_username)
        service = runtime.completion_service
        with runtime.engine.connect() as connection:
            before = connection.execute(select(TaskRow)).all()
        goals = service.list_for_project(project_id, actor_user_id=actor.user_id)
        assert goals == tuple(
            service.get(goal.intent_id, actor_user_id=actor.user_id) for goal in goals
        )
        with runtime.engine.connect() as connection:
            assert connection.execute(select(TaskRow)).all() == before
        with runtime.engine.begin() as connection:
            # Removing the intent gives an authorized empty Project without allocating another.
            connection.execute(delete(TaskRow).where(TaskRow.target_id == goals[0].intent_id))
            connection.execute(delete(CompletionIntentRow))
        assert service.list_for_project(project_id, actor_user_id=actor.user_id) == ()
        with runtime.engine.begin() as connection:
            connection.execute(
                delete(ProjectMemberRow).where(ProjectMemberRow.project_id == project_id)
            )
        with pytest.raises(CompletionResourceNotFound):
            service.list_for_project(project_id, actor_user_id=actor.user_id)


def test_resume_rejects_wrong_project_intent_without_allocating(source: Path) -> None:
    runner = CliRunner()
    first = runner.invoke(app, ["auto", str(source), "--no-watch"])
    second = runner.invoke(app, ["auto", str(source), "--no-watch"])
    assert first.exit_code == second.exit_code == 0
    result = runner.invoke(
        app,
        [
            "resume",
            saved(first.output)["Project ID"],
            "--no-watch",
            "--intent-id",
            saved(second.output)["Completion intent ID"],
        ],
    )
    assert result.exit_code == 2
    assert "ambiguous or empty" in result.output


def test_lost_create_response_replays_and_rejects_changed_body(
    source: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from liveclip.application.completion_service import CompletionService

    original = CompletionService.create_project_and_run_with_goal
    calls = 0

    def lose_response(self, **kwargs):
        nonlocal calls
        goal = original(self, **kwargs)
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated response loss after commit")
        return goal

    monkeypatch.setattr(CompletionService, "create_project_and_run_with_goal", lose_response)
    runner = CliRunner()
    args = ["auto", str(source), "--no-watch", "--request-key", "lost-response"]
    first = runner.invoke(app, args)
    assert first.exit_code == 1
    assert "Request key: lost-response" in first.output
    recovered = runner.invoke(app, args)
    assert recovered.exit_code == 0, recovered.output
    other = source.with_name("other.mp4")
    other.write_bytes(source.read_bytes())
    for changed in (
        [*args, "--clip-profile", "mini_lesson"],
        [*args, "--selection-policy", "manual"],
        ["auto", str(other), "--no-watch", "--request-key", "lost-response"],
    ):
        assert runner.invoke(app, changed).exit_code == 1
    with (
        LiveClipRuntime.open(get_settings()) as runtime,
        runtime.engine.connect() as connection,
    ):
        assert len(connection.execute(select(ProjectRow)).all()) == 1
        goals = connection.execute(select(CompletionIntentRow)).mappings().all()
        assert len(goals) == 1
        assert goals[0]["id"] == saved(recovered.output)["Completion intent ID"]


@pytest.mark.parametrize("blocker", ["authority", "processing"])
def test_resume_repairs_real_manual_blocker_without_resetting_history(
    source: Path,
    blocker: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy import insert, update

    from liveclip.application.completion import CompletionConflict
    from liveclip.application.completion_runner import ReconciliationResult
    from liveclip.db.models import PipelineRunRow, TaskAttemptRow

    runner = CliRunner()
    result = runner.invoke(app, ["auto", str(source), "--no-watch", "--selection-policy", "manual"])
    assert result.exit_code == 0, result.output
    ids = saved(result.output)
    with LiveClipRuntime.open(get_settings()) as runtime:
        actor = runtime.workspace_service.get_user_by_username(get_settings().workspace_username)
        intent = ids["Completion intent ID"]
        with runtime.engine.begin() as connection:
            members = [
                dict(row)
                for row in connection.execute(
                    select(ProjectMemberRow).where(ProjectMemberRow.project_id == ids["Project ID"])
                ).mappings()
            ]
            if blocker == "authority":
                connection.execute(
                    delete(ProjectMemberRow).where(ProjectMemberRow.project_id == ids["Project ID"])
                )
            else:
                connection.execute(
                    update(PipelineRunRow)
                    .where(PipelineRunRow.id == ids["Pipeline run ID"])
                    .values(status="failed")
                )
            connection.execute(
                update(TaskRow)
                .where(TaskRow.target_id == intent)
                .values(
                    retry_count=1,
                    attempt_count=3,
                )
            )
        assert runtime.completion_runner.run_once(worker_id="blocker-test") == (
            ReconciliationResult.NEEDS_ACTION
        )
        if blocker == "authority":
            denied = runner.invoke(app, ["resume", ids["Project ID"], "--no-watch"])
            assert denied.exit_code == 1
            assert intent not in denied.output
        with runtime.engine.begin() as connection:
            if blocker == "authority":
                connection.execute(insert(ProjectMemberRow), members)
            else:
                connection.execute(
                    update(PipelineRunRow)
                    .where(PipelineRunRow.id == ids["Pipeline run ID"])
                    .values(status="queued")
                )
        before = runtime.completion_service.get(intent, actor_user_id=actor.user_id)
        assert before.blocking_code == (
            "AUTHORIZATION_REQUIRED" if blocker == "authority" else "PROCESSING_FAILED"
        )
        from liveclip.cli.completion_watch import observation

        observed = observation(runtime, intent, actor.user_id)
        assert before.blocking_code in observed["notice"]
        assert "Manual selection required" not in observed["notice"]
        with runtime.engine.connect() as connection:
            tasks = (
                connection.execute(select(TaskRow).where(TaskRow.target_id == intent))
                .mappings()
                .one()
            )
            attempts = connection.execute(select(TaskAttemptRow)).all()

        def forbidden(*args, **kwargs):
            raise AssertionError("CLI must not run a Worker")

        monkeypatch.setattr(
            "liveclip.application.completion_runner.CompletionRunner.run_once", forbidden
        )
        resumed = runner.invoke(app, ["resume", ids["Project ID"], "--no-watch"])
        assert resumed.exit_code == 0, resumed.output
        after = runtime.completion_service.get(intent, actor_user_id=actor.user_id)
        assert after.version == before.version + 1
        assert after.status.value == "queued"
        assert not after.selection_submitted
        for field in ("intent_id", "project_id", "run_id", "generation"):
            assert getattr(after, field) == getattr(before, field)
        with runtime.engine.connect() as connection:
            task = (
                connection.execute(select(TaskRow).where(TaskRow.target_id == intent))
                .mappings()
                .one()
            )
            assert task["id"] == tasks["id"]
            assert (task["retry_count"], task["attempt_count"]) == (1, 4)
            assert connection.execute(select(TaskAttemptRow)).all() == attempts
        with pytest.raises(CompletionConflict):
            runtime.completion_service.resume(
                intent,
                actor_user_id=actor.user_id,
                expected_version=before.version,
            )


def completion_records(runtime: LiveClipRuntime) -> dict[str, list[dict[str, object]]]:
    """Include full selection checkpoints, decisions and every task attempt."""
    from liveclip.db.models import (
        CandidateClipRow,
        DeliveryRow,
        PipelineRunRow,
        ReviewDecisionRow,
        StageRunRow,
        TaskAttemptRow,
    )

    with runtime.engine.connect() as connection:
        return {
            table.__tablename__: [
                dict(row) for row in connection.execute(select(table).order_by(table.id)).mappings()
            ]
            for table in (
                CompletionIntentRow,
                CandidateClipRow,
                ReviewDecisionRow,
                PipelineRunRow,
                StageRunRow,
                TaskRow,
                TaskAttemptRow,
                DeliveryRow,
            )
        }


def test_resume_leaves_genuine_selection_wait_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from liveclip.application.completion import CompletionOptions, CompletionSelectionPolicy
    from liveclip.application.idempotency import build_idempotency_context
    from liveclip.bootstrap import pipeline_config_from_settings
    from liveclip.services.demo_media import create_demo_source

    media = tmp_path / "manual.mp4"
    create_demo_source(output_path=media, duration_ms=32_000)
    for key, value in {
        "LIVECLIP_DATA_DIR": str(tmp_path / "data"),
        "LIVECLIP_ALLOWED_MEDIA_ROOTS": str(tmp_path),
        "LIVECLIP_AI_PROVIDER": "mock",
        "PREVIEW_RENDER_WIDTH": "270",
        "PREVIEW_RENDER_HEIGHT": "480",
        "FINAL_RENDER_WIDTH": "360",
        "FINAL_RENDER_HEIGHT": "640",
        "LIVECLIP_VIDEO_ENCODER": "libx264",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        with LiveClipRuntime.open(get_settings()) as runtime:
            actor = runtime.workspace_service.get_user_by_username(
                get_settings().workspace_username
            )
            goal = runtime.completion_service.create_project_and_run_with_goal(
                source_path=media,
                config=pipeline_config_from_settings(
                    get_settings(),
                    top_n=1,
                    minimum_clip_seconds=8,
                    maximum_clip_seconds=12,
                    semantic_target_clip_seconds=10,
                ),
                max_stage_retries=2,
                actor_user_id=actor.user_id,
                options=CompletionOptions(selection_policy=CompletionSelectionPolicy.MANUAL),
                idempotency=build_idempotency_context(
                    raw_key="genuine-manual-wait",
                    caller_scope=f"cli:{actor.user_id}",
                    operation_scope="completion:create",
                    request_payload={"fixture": "manual"},
                ),
                readiness_guard=lambda: None,
            )
            processed = runtime.stage_runner.run_until_terminal(
                goal.run_id, worker_id="manual-test"
            )
            assert processed.status.value == "completed"
            runtime.completion_runner.run_once(worker_id="manual-test")
            waiting = runtime.completion_service.get(goal.intent_id, actor_user_id=actor.user_id)
            assert waiting.status.value == "waiting_selection"
            assert not waiting.selection_submitted
            before = completion_records(runtime)
            assert before["candidate_clips"]
            assert before["task_attempts"]
            task = next(row for row in before["tasks"] if row["target_id"] == goal.intent_id)
            assert task["status"] == "waiting"
            resumed = CliRunner().invoke(app, ["resume", goal.project_id, "--no-watch"])
            assert resumed.exit_code == 0, resumed.output
            assert "Manual selection required" in resumed.output
            assert completion_records(runtime) == before
    finally:
        get_settings.cache_clear()


def test_resume_leaves_genuinely_exhausted_coordination_unchanged(source: Path) -> None:
    from datetime import UTC, datetime, timedelta

    runner = CliRunner()
    result = runner.invoke(app, ["auto", str(source), "--no-watch", "--selection-policy", "manual"])
    assert result.exit_code == 0, result.output
    ids = saved(result.output)
    with LiveClipRuntime.open(get_settings()) as runtime:
        with runtime.engine.connect() as connection:
            initial = (
                connection.execute(
                    select(TaskRow).where(TaskRow.target_id == ids["Completion intent ID"])
                )
                .mappings()
                .one()
            )
        instant = datetime.now(UTC)
        attempt_ids = []
        for attempt in range(initial["max_retries"] + 1):
            lease = runtime.task_queue.claim_completion(worker_id="lost-worker", now=instant)
            assert lease is not None
            assert lease.task_id == initial["id"]
            instant += timedelta(seconds=get_settings().worker_lease_seconds + 1)
            recovered = runtime.task_queue.recover_expired(now=instant)
            assert recovered.failed == int(attempt == initial["max_retries"])
            assert recovered.requeued == int(attempt < initial["max_retries"])
            records = completion_records(runtime)
            history = [row for row in records["task_attempts"] if row["task_id"] == initial["id"]]
            assert len(history) == attempt + 1
            assert all(row["outcome"] == "lost_lease" for row in history)
            attempt_ids = [row["id"] for row in history]
        assert len(set(attempt_ids)) == initial["max_retries"] + 1
        assert runtime.task_queue.claim_completion(worker_id="observer", now=instant) is None
        before = completion_records(runtime)
        task = next(row for row in before["tasks"] if row["id"] == initial["id"])
        assert task["status"] == "failed"
        assert task["retry_count"] == initial["max_retries"]
        assert task["attempt_count"] == initial["max_retries"] + 1
        resumed = runner.invoke(app, ["resume", ids["Project ID"], "--no-watch"])
        assert resumed.exit_code == 0, resumed.output
        assert "retry budget exhausted" in resumed.output
        assert saved(resumed.output)["status"] == "needs_action"
        assert saved(resumed.output)["blocking_code"] == "COORDINATION_RETRIES_EXHAUSTED"
        assert completion_records(runtime) == before


def test_independent_worker_survives_cli_exit_and_watch_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import os
    import subprocess
    import sys
    import time
    import zipfile

    from liveclip.application.completion import CompletionOptions
    from liveclip.application.idempotency import build_idempotency_context
    from liveclip.bootstrap import pipeline_config_from_settings
    from liveclip.cli import completion_watch
    from liveclip.services.demo_media import create_demo_source

    media = tmp_path / "synthetic.mp4"
    create_demo_source(output_path=media, duration_ms=32_000)
    digest = hashlib.sha256(media.read_bytes()).hexdigest()
    for key, value in {
        "LIVECLIP_DATA_DIR": str(tmp_path / "data"),
        "LIVECLIP_ALLOWED_MEDIA_ROOTS": str(tmp_path),
        "LIVECLIP_AI_PROVIDER": "mock",
        "PREVIEW_RENDER_WIDTH": "270",
        "PREVIEW_RENDER_HEIGHT": "480",
        "FINAL_RENDER_WIDTH": "360",
        "FINAL_RENDER_HEIGHT": "640",
        "LIVECLIP_VIDEO_ENCODER": "libx264",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    worker = None
    try:
        # Use the supported short synthetic pipeline for real Worker/FFmpeg evidence;
        # canonical auto preset requests are covered independently above.
        with LiveClipRuntime.open(get_settings()) as runtime:
            actor = runtime.workspace_service.get_user_by_username(
                get_settings().workspace_username
            )
            goal = runtime.completion_service.create_project_and_run_with_goal(
                source_path=media,
                config=pipeline_config_from_settings(
                    get_settings(),
                    top_n=1,
                    minimum_clip_seconds=8,
                    maximum_clip_seconds=12,
                    semantic_target_clip_seconds=10,
                ),
                max_stage_retries=2,
                actor_user_id=actor.user_id,
                options=CompletionOptions(),
                idempotency=build_idempotency_context(
                    raw_key="independent-worker",
                    caller_scope=f"cli:{actor.user_id}",
                    operation_scope="completion:create",
                    request_payload={"fixture": "worker"},
                ),
                readiness_guard=lambda: None,
            )
        result = CliRunner().invoke(app, ["resume", goal.project_id, "--no-watch"])
        assert result.exit_code == 0, result.output
        ids = saved(result.output)
        environment = dict(os.environ, PYTHONPATH=str(Path("src").resolve()))
        with (tmp_path / "worker.log").open("wb") as log:
            worker = subprocess.Popen(
                [sys.executable, "-m", "liveclip.worker"],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                shell=False,
            )
            deadline = time.monotonic() + 300
            with LiveClipRuntime.open(get_settings()) as runtime:
                actor = runtime.workspace_service.get_user_by_username(
                    get_settings().workspace_username
                )
                while time.monotonic() < deadline:
                    with runtime.engine.connect() as connection:
                        running = connection.execute(
                            select(TaskRow.id).where(TaskRow.status == "running")
                        ).first()
                    if running:
                        break
                    assert worker.poll() is None
                    time.sleep(0.05)
                assert running is not None, "independent Worker never claimed work"

                def interrupt(_: float) -> None:
                    raise KeyboardInterrupt

                with monkeypatch.context() as patch:
                    patch.setattr(completion_watch.time, "sleep", interrupt)
                    stopped = CliRunner().invoke(app, ["resume", ids["Project ID"]])
                assert stopped.exit_code == 0, stopped.output
                assert "Tasks are unchanged" in stopped.output
                assert worker.poll() is None
                while time.monotonic() < deadline:
                    goal = runtime.completion_service.get(
                        ids["Completion intent ID"],
                        actor_user_id=actor.user_id,
                    )
                    if goal.status.value in {"succeeded", "needs_action", "cancelled"}:
                        break
                    assert worker.poll() is None
                    time.sleep(0.2)
                assert goal.status.value == "succeeded", goal.blocking_code
                assert goal.outcome and goal.outcome.value == "delivered"
                final = completion_watch.observation(runtime, goal.intent_id, actor.user_id)
                archive = Path(str(final["Delivery ZIP"]))
                with zipfile.ZipFile(archive) as package:
                    assert package.testzip() is None
                    assert any(name.endswith(".mp4") for name in package.namelist())
                    assert any(name.endswith(".srt") for name in package.namelist())
                with runtime.engine.connect() as connection:
                    assert len(connection.execute(select(CompletionIntentRow)).all()) == 1
                    assert len(connection.execute(select(ProjectRow)).all()) == 1
                    tasks = connection.execute(select(TaskRow)).mappings().all()
                    assert all(task["cancellation_requested_at"] is None for task in tasks)
                    assert all(task["retry_count"] == 0 for task in tasks)
                assert hashlib.sha256(media.read_bytes()).hexdigest() == digest
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
        get_settings.cache_clear()


def test_ambiguous_project_requires_exact_intent_and_lookup_is_read_only(source: Path) -> None:
    from liveclip.application.completion import CompletionOptions
    from liveclip.application.idempotency import build_idempotency_context

    runner = CliRunner()
    result = runner.invoke(app, ["auto", str(source), "--no-watch"])
    assert result.exit_code == 0, result.output
    ids = saved(result.output)
    with LiveClipRuntime.open(get_settings()) as runtime:
        actor = runtime.workspace_service.get_user_by_username(get_settings().workspace_username)
        second = runtime.completion_service.create_for_existing_run(
            project_id=ids["Project ID"],
            run_id=ids["Pipeline run ID"],
            actor_user_id=actor.user_id,
            options=CompletionOptions(),
            idempotency=build_idempotency_context(
                raw_key="second-goal",
                caller_scope=f"cli:{actor.user_id}",
                operation_scope="completion:create",
                request_payload={"goal": "second"},
            ),
        )
        with runtime.engine.connect() as connection:
            before = [
                connection.execute(select(table)).all()
                for table in (
                    ProjectRow,
                    CompletionIntentRow,
                    TaskRow,
                )
            ]
        ambiguous = runner.invoke(app, ["resume", ids["Project ID"], "--no-watch"])
        assert ambiguous.exit_code == 2, ambiguous.output
        assert "--intent-id" in ambiguous.output
        exact = runner.invoke(
            app,
            [
                "resume",
                ids["Project ID"],
                "--intent-id",
                second.intent_id,
                "--no-watch",
            ],
        )
        assert exact.exit_code == 0, exact.output
        assert saved(exact.output)["Completion intent ID"] == second.intent_id
        with runtime.engine.connect() as connection:
            after = [
                connection.execute(select(table)).all()
                for table in (
                    ProjectRow,
                    CompletionIntentRow,
                    TaskRow,
                )
            ]
        assert after == before
