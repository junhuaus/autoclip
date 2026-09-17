"""Persistent Worker wiring over disposable SQLite and synthetic owned artifacts."""

import hashlib
import json
import signal
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, insert, update
from test_completion_delivery import master
from test_completion_identity import OWNER, Fixture, context
from test_completion_selection import ready

from liveclip.application.completion_runner import CompletionRunner, ReconciliationResult
from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.reviewing import RenderRequest
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.delivery_repository import DeliveryInspectionRequired
from liveclip.db.engine import begin_immediate, create_sqlite_engine
from liveclip.db.models import (
    AssetRow,
    CompletionIntentRow,
    DeliveryRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.renderer.quality import full_decode, probe_media
from liveclip.services.demo_media import create_demo_source
from liveclip.worker import WorkerShutdown, run_worker

pytestmark = pytest.mark.integration


@pytest.fixture
def runtime_fixture(tmp_path):
    settings = Settings(
        _env_file=None,
        ai_provider="mock",
        data_dir=tmp_path / "data",
        allowed_media_roots_raw=str(tmp_path),
        max_stage_retries=5,
    )
    with LiveClipRuntime.open(settings) as runtime:
        with runtime.engine.begin() as connection:
            connection.execute(
                insert(WorkspaceUserRow).values(
                    id=OWNER,
                    username="completion-owner",
                    display_name="Owner",
                    is_active=True,
                )
            )
        yield settings, runtime, Fixture(runtime.engine, tmp_path)


def due(fixture):
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow)
            .where(TaskRow.kind == "completion")
            .values(
                not_before=datetime.now(UTC) - timedelta(seconds=1),
            )
        )


def test_runtime_delivery_retry_bound_and_generated_directory_survive_restart(runtime_fixture):
    settings, runtime, fixture = runtime_fixture
    goal, _ = master(fixture)
    due(fixture)
    assert runtime.completion_runner.run_once(worker_id="first") == "deferred"
    bound = fixture.rows(CompletionIntentRow)[0]
    delivery_id = bound["delivery_id"]
    task = next(row for row in fixture.rows(TaskRow) if row["target_id"] == delivery_id)
    assert task["max_retries"] == settings.max_stage_retries == 5
    with LiveClipRuntime.open(settings) as restarted:
        assert restarted.delivery_runner.run_one(worker_id="packager").value == "succeeded"
        due(fixture)
        assert restarted.completion_runner.run_once(worker_id="restarted") == "processed"
    assert fixture.rows(CompletionIntentRow)[0]["delivery_id"] == delivery_id
    assert len(fixture.rows(DeliveryRow)) == 1
    assert next(row for row in fixture.rows(TaskRow) if row["id"] == task["id"])["max_retries"] == 5
    assert fixture.task(goal)["retry_count"] == 0


def test_worker_completes_saved_processing_goal_without_client(runtime_fixture):
    settings, _runtime, fixture = runtime_fixture
    goal = fixture.create()
    fixture.run_status(goal, "completed")
    # Remove synthetic pending stage work: processing was committed by the departed client.
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    assert run_worker(settings, once=True) == 0
    assert fixture.rows(CompletionIntentRow)[0]["status"] == "succeeded"
    attempts = fixture.task(goal)["attempt_count"]
    assert run_worker(settings, once=True) == 0
    assert fixture.task(goal)["attempt_count"] == attempts


def test_processing_pipeline_finishes_using_only_restarted_workers(runtime_fixture):
    settings, _runtime, fixture = runtime_fixture
    create_demo_source(output_path=fixture.root / "synthetic.mp4", duration_ms=32_000)
    goal = fixture.create()
    for _ in range(20):
        assert run_worker(settings, once=True) == 0
        if fixture.rows(CompletionIntentRow)[0]["status"] == "succeeded":
            break
    assert fixture.rows(CompletionIntentRow)[0]["status"] == "succeeded"
    assert fixture.task(goal)["retry_count"] == 0
    assert fixture.rows(DeliveryRow) == []


def test_manual_waiting_has_no_recurring_attempts_across_workers(runtime_fixture):
    settings, _runtime, fixture = runtime_fixture
    goal, _ = ready(fixture, manual=True)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    assert run_worker(settings, once=True) == 0
    before = fixture.task(goal)
    assert before["status"] == "waiting"
    for _ in range(3):
        assert run_worker(settings, once=True) == 0
    assert fixture.task(goal) == before


def test_actual_sqlite_claim_conflict_returns_busy_then_recovers(runtime_fixture):
    _settings, runtime, fixture = runtime_fixture
    fixture.create()
    engine = create_sqlite_engine(runtime.database_path, busy_timeout_ms=10)
    runner = CompletionRunner(
        SQLiteTaskQueue(engine, lease_seconds=30), runtime.completion_runner._repository
    )
    try:
        with begin_immediate(runtime.engine):
            assert runner.run_once(worker_id="contender") == ReconciliationResult.BUSY
        assert runner.run_once(worker_id="contender") == ReconciliationResult.DEFERRED
    finally:
        engine.dispose()


def test_monitor_stop_waits_for_real_sqlite_completion_heartbeat(runtime_fixture):
    _settings, runtime, fixture = runtime_fixture
    goal, _ = master(fixture)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    due(fixture)
    lease = runtime.task_queue.claim_completion(worker_id="lock-test")
    assert lease is not None

    attempted = threading.Event()
    completed = threading.Event()
    stopped = threading.Event()

    def record_begin(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            threading.current_thread().name == "blocked-completion-heartbeat"
            and statement.lstrip().upper().startswith("BEGIN IMMEDIATE")
        ):
            attempted.set()

    event.listen(runtime.engine, "before_cursor_execute", record_begin)
    monitor = LeaseMonitor(
        heartbeat=runtime.task_queue.heartbeat,
        observe=None,
        lease=lease,
        heartbeat_seconds=30,
        thread_name="completion-lock-monitor",
    )
    monitor.start()

    def refresh():
        monitor.refresh()
        completed.set()

    refresher = threading.Thread(target=refresh, name="blocked-completion-heartbeat")
    stopper = threading.Thread(target=lambda: (monitor.stop(), stopped.set()))
    try:
        with begin_immediate(runtime.engine):
            refresher.start()
            assert attempted.wait(timeout=1)
            stopper.start()
            assert monitor._stop.wait(timeout=1)
            time.sleep(2.1)  # Exceed the former stop() join deadline.
            assert not completed.is_set()
            assert not stopped.is_set()
        refresher.join(timeout=5)
        stopper.join(timeout=5)
        assert completed.is_set()
        assert stopped.is_set()
        assert not monitor._thread.is_alive()
        heartbeat_at = fixture.task(goal)["heartbeat_at"]
        monitor.refresh()
        assert fixture.task(goal)["heartbeat_at"] == heartbeat_at
    finally:
        event.remove(runtime.engine, "before_cursor_execute", record_begin)
        # Bounded cleanup keeps a failed assertion from leaking either helper.
        monitor._stop.set()
        refresher.join(timeout=6)
        monitor.stop()
        stopper.join(timeout=1)


def test_completion_progresses_while_another_worker_owns_heavy_work(runtime_fixture, monkeypatch):
    settings, runtime, fixture = runtime_fixture
    goal = fixture.create()
    heavy = runtime.task_queue.claim(worker_id="other-worker")
    assert heavy is not None

    @contextmanager
    def opened(settings):
        yield runtime

    monkeypatch.setattr(LiveClipRuntime, "open", opened)
    assert run_worker(settings, once=True) == 0
    assert fixture.task(goal)["attempt_count"] == 1
    assert fixture.task(goal)["retry_count"] == 0
    assert runtime.task_queue.observe(heavy) is not None


def test_real_ready_categories_each_receive_a_worker_turn(runtime_fixture, monkeypatch):
    settings, runtime, fixture = runtime_fixture
    goal, render = master(fixture)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    due(fixture)
    assert runtime.completion_runner.run_once(worker_id="enqueue") == "deferred"
    runtime.render_service.enqueue(render.clip_id, RenderRequest(expected_revision=1, kind="final"))
    fixture.create(idempotency=context("independent-stage"))
    due(fixture)
    handled = []

    def wrapped(name, execute):
        def run(**kwargs):
            if len(handled) == 4:
                raise WorkerShutdown(signal.SIGTERM)
            result = execute(**kwargs)
            if result.value not in {"idle", "busy"}:
                handled.append((name, result.value))
            return result

        return run

    for name in ("stage", "render", "delivery", "completion"):
        runner = getattr(runtime, f"{name}_runner")
        method = "run_once" if name == "completion" else "run_one"
        monkeypatch.setattr(runner, method, wrapped(name, getattr(runner, method)))

    @contextmanager
    def opened(settings):
        yield runtime

    monkeypatch.setattr(LiveClipRuntime, "open", opened)
    assert run_worker(settings) == 128 + signal.SIGTERM
    assert handled == [
        ("stage", "succeeded"),
        ("render", "succeeded"),
        ("delivery", "succeeded"),
        ("completion", "processed"),
    ]
    assert fixture.task(goal)["retry_count"] == 0


def test_worker_shutdown_during_inspection_closes_resources_and_recovers(
    runtime_fixture, monkeypatch
):
    settings, runtime, fixture = runtime_fixture
    goal, _ = master(fixture)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    due(fixture)
    assert runtime.completion_runner.run_once(worker_id="enqueue") == "deferred"
    assert runtime.delivery_runner.run_one(worker_id="package").value == "succeeded"
    before = fixture.rows(CompletionIntentRow)[0]
    inspected = []
    original = DeliveryInspectionRequired.inspect

    def interrupted(self):
        original(self)
        inspected.append(self)
        raise WorkerShutdown(signal.SIGTERM)

    due(fixture)
    with monkeypatch.context() as patch:
        patch.setattr(DeliveryInspectionRequired, "inspect", interrupted)
        assert run_worker(settings, once=True) == 128 + signal.SIGTERM
    assert fixture.rows(CompletionIntentRow)[0] == before
    assert fixture.task(goal)["status"] == "running"
    assert inspected and all(not item.still_valid() for item in inspected)
    import threading

    assert not any(
        thread.name.startswith("liveclip-completion-inspection-")
        for thread in threading.enumerate()
    )
    runtime.task_queue.recover_expired(
        now=datetime.now(UTC) + timedelta(seconds=settings.worker_lease_seconds + 1)
    )
    due(fixture)
    assert run_worker(settings, once=True) == 0
    after = fixture.rows(CompletionIntentRow)[0]
    assert after["status"] == "succeeded"
    for field in (
        "id",
        "pipeline_run_id",
        "generation",
        "selection_checkpoint_json",
        "delivery_id",
        "delivery_action_key",
    ):
        assert after[field] == before[field]
    assert fixture.task(goal)["retry_count"] == 1
    assert len(fixture.rows(DeliveryRow)) == 1


def test_worker_background_inspection_contention_shutdown_and_recovery(
    runtime_fixture, monkeypatch
):
    settings, runtime, fixture = runtime_fixture
    settings = settings.model_copy(
        update={"worker_lease_seconds": 15, "worker_heartbeat_seconds": 5}
    )
    goal, _ = master(fixture)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    due(fixture)
    assert runtime.completion_runner.run_once(worker_id="enqueue") == "deferred"
    assert runtime.delivery_runner.run_one(worker_id="package").value == "succeeded"
    due(fixture)

    def snapshot():
        assets = fixture.rows(AssetRow)
        for asset in assets:
            assert asset["project_id"] == goal.project_id
            path = fixture.root / "data" / goal.project_id / asset["relative_path"]
            assert path.resolve().is_relative_to((fixture.root / "data").resolve())
            assert path.stat().st_size == asset["size_bytes"] > 0
            assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
        return {
            "intent": fixture.rows(CompletionIntentRow)[0],
            "task": fixture.task(goal),
            "attempts": {row["id"]: row for row in fixture.rows(TaskAttemptRow)},
            "deliveries": fixture.rows(DeliveryRow),
            "assets": assets,
        }

    before = snapshot()
    entered = threading.Event()
    release_inspection = threading.Event()
    blocked = threading.Event()
    stopping = threading.Event()
    returned = threading.Event()
    writer_held = threading.Event()
    events = []
    errors = []
    captured = {}
    renewals = []

    def record(name):
        events.append((name, time.monotonic()))

    original_start = LeaseMonitor.start
    original_stop = LeaseMonitor.stop
    original_inspect = DeliveryInspectionRequired.inspect
    original_close = DeliveryInspectionRequired.close
    original_open = LiveClipRuntime.open
    original_runtime_close = LiveClipRuntime.close

    def runtime_close(worker_runtime):
        original_runtime_close(worker_runtime)
        if worker_runtime.engine is captured.get("engine"):
            record("runtime-closed")

    def start(monitor):
        if monitor._lease.task_id == before["task"]["id"]:
            assert monitor._thread.name.startswith("liveclip-completion-inspection-")
            assert monitor._heartbeat_seconds == 5
            captured["monitor"] = monitor
            heartbeat = monitor._heartbeat
            observe = monitor._observe
            join = monitor._thread.join

            def operation(callback, lease):
                background = threading.current_thread() is monitor._thread
                try:
                    assert "stop-return" not in [name for name, _ in events]
                    result = callback(lease)
                    if background and callback is heartbeat:
                        assert result is not None
                        renewals.append(result)
                        record("heartbeat-complete")
                    return result
                except BaseException as exc:
                    errors.append(exc)
                    raise

            def joined(*args, **kwargs):
                result = join(*args, **kwargs)
                # The foreground drain can mask a timed background join. Observe
                # this boundary as well as the externally visible stop barrier.
                if monitor._thread.is_alive():
                    errors.append(AssertionError("background join returned before termination"))
                else:
                    record("monitor-terminated")
                return result

            patch.setattr(monitor, "_heartbeat", lambda lease: operation(heartbeat, lease))
            patch.setattr(monitor, "_observe", lambda lease: operation(observe, lease))
            patch.setattr(monitor._thread, "join", joined)
        original_start(monitor)

    def stop(monitor):
        if monitor is captured.get("monitor"):
            record("stop-entry")
            stopping.set()
            original_stop(monitor)
            record("stop-return")
        else:
            original_stop(monitor)

    def inspect(inspection):
        captured["inspection"] = inspection
        captured["initial_heartbeat"] = fixture.task(goal)["heartbeat_at"]
        entered.set()
        assert release_inspection.wait(12), "inspection gate timed out"
        original_inspect(inspection)
        raise WorkerShutdown(signal.SIGTERM)

    def close(inspection):
        original_close(inspection)
        if inspection is captured.get("inspection"):
            record("inspection-closed")

    def sql_boundary(_connection, cursor, statement, _parameters, _context, _many):
        monitor = captured.get("monitor")
        if monitor and threading.current_thread() is monitor._thread:
            assert "stop-return" not in [name for name, _ in events]
            if statement == "BEGIN IMMEDIATE":
                assert writer_held.is_set()
                captured["busy_seconds"] = (
                    cursor.execute("PRAGMA busy_timeout").fetchone()[0] / 1000
                )
                record("heartbeat-begin")
                blocked.set()

    @contextmanager
    def opened(config):
        with original_open(config) as worker_runtime:
            captured["engine"] = worker_runtime.engine
            event.listen(worker_runtime.engine, "before_cursor_execute", sql_boundary)
            dispose = worker_runtime.engine.dispose

            def disposed(*args, **kwargs):
                record("dispose-entry")
                result = dispose(*args, **kwargs)
                record("engine-disposed")
                return result

            patch.setattr(worker_runtime.engine, "dispose", disposed)
            try:
                yield worker_runtime
            finally:
                record("runtime-exit-entry")

    def work():
        try:
            captured["exit"] = run_worker(settings, once=True)
            record("worker-return")
        except BaseException as exc:
            errors.append(exc)
        finally:
            returned.set()

    worker = threading.Thread(target=work, name="contended-inspection-worker", daemon=True)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(LeaseMonitor, "start", start)
            patch.setattr(LeaseMonitor, "stop", stop)
            patch.setattr(DeliveryInspectionRequired, "inspect", inspect)
            patch.setattr(DeliveryInspectionRequired, "close", close)
            patch.setattr(LiveClipRuntime, "open", opened)
            patch.setattr(LiveClipRuntime, "close", runtime_close)
            try:
                worker.start()
                assert entered.wait(10)
                with begin_immediate(fixture.engine):
                    writer_held.set()
                    assert blocked.wait(7), "actual background heartbeat did not enter SQLite"
                    release_inspection.set()
                    assert stopping.wait(1)
                    stop_at = dict(events)["stop-entry"]
                    deadline = stop_at + 2.2
                    while time.monotonic() < deadline:
                        assert not returned.wait(min(0.02, deadline - time.monotonic()))
                        names = [name for name, _ in events]
                        assert not {
                            "stop-return",
                            "inspection-closed",
                            "dispose-entry",
                            "runtime-exit-entry",
                        }.intersection(names)
                    assert time.monotonic() - stop_at > 2.1
                    assert (
                        time.monotonic() - dict(events)["heartbeat-begin"]
                        < captured["busy_seconds"]
                    )
                    assert not renewals
                    record("writer-release")
                writer_held.clear()
                assert returned.wait(7)
            finally:
                release_inspection.set()
                writer_held.clear()
                worker.join(timeout=8)
                monitor = captured.get("monitor")
                if monitor is not None:
                    monitor._stop.set()
                    monitor._thread.join(timeout=6)
                engine = captured.get("engine")
                if engine is not None:
                    event.remove(engine, "before_cursor_execute", sql_boundary)
            assert not worker.is_alive()
            assert not captured["monitor"]._thread.is_alive()
            assert not errors, repr(errors)
            assert captured["exit"] == 143
            order = [name for name, _ in events]
            expected = [
                "heartbeat-begin",
                "stop-entry",
                "writer-release",
                "heartbeat-complete",
                "monitor-terminated",
                "stop-return",
                "inspection-closed",
                "runtime-exit-entry",
                "dispose-entry",
                "engine-disposed",
                "runtime-closed",
                "worker-return",
            ]
            assert [order.index(name) for name in expected] == sorted(
                order.index(name) for name in expected
            )
            assert not captured["inspection"].still_valid()
            assert len(renewals) == 1
            interrupted = snapshot()
            assert interrupted["task"]["heartbeat_at"] > captured["initial_heartbeat"]
            assert interrupted["task"]["lease_expires_at"] == renewals[0].lease_expires_at
            captured["monitor"].refresh()
            captured["monitor"]._observe_once()
            assert not errors, repr(errors)
            assert snapshot() == interrupted

        assert interrupted["intent"] == before["intent"]
        assert interrupted["task"]["status"] == "running"
        assert interrupted["task"]["retry_count"] == before["task"]["retry_count"]
        new_ids = interrupted["attempts"].keys() - before["attempts"].keys()
        assert len(new_ids) == 1
        interrupted_id = new_ids.pop()
        attempt = interrupted["attempts"][interrupted_id]
        assert attempt["outcome"] == "running" and attempt["finished_at"] is None
        expiry = interrupted["task"]["lease_expires_at"]
        deadline = time.monotonic() + 20
        while datetime.now(UTC) <= expiry:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert run_worker(settings, once=True) == 0
        recovered = snapshot()
        assert recovered["intent"]["status"] == "succeeded"
        for field in (
            "id",
            "project_id",
            "pipeline_run_id",
            "generation",
            "selection_checkpoint_json",
            "delivery_action_key",
            "delivery_id",
        ):
            assert recovered["intent"][field] == before["intent"][field]
        for field in (
            "id",
            "operation_key",
            "max_retries",
            "expected_generation",
            "pipeline_run_id",
        ):
            assert recovered["task"][field] == before["task"][field]
        assert recovered["task"]["retry_count"] == before["task"]["retry_count"] + 1
        assert recovered["task"]["retry_count"] <= recovered["task"]["max_retries"]
        lost = recovered["attempts"][interrupted_id]
        assert lost["outcome"] == "lost_lease" and lost["error_code"] == "LEASE_EXPIRED"
        recovery_ids = recovered["attempts"].keys() - interrupted["attempts"].keys()
        assert len(recovery_ids) == 1
        assert recovered["attempts"][recovery_ids.pop()]["outcome"] == "succeeded"
        for identity, historical in before["attempts"].items():
            assert (
                interrupted["attempts"][identity] == recovered["attempts"][identity] == historical
            )
        for field in ("deliveries", "assets"):
            assert before[field] == interrupted[field] == recovered[field]
        assert len(recovered["deliveries"]) == 1
        directory = (
            fixture.root
            / "data"
            / goal.project_id
            / "deliveries"
            / f"v{before['deliveries'][0]['version']:03d}"
        )
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["clips"]
        with zipfile.ZipFile(directory / "delivery.zip") as archive:
            assert archive.testzip() is None
            assert json.loads(archive.read("manifest.json")) == manifest
            for clip in manifest["clips"]:
                video = directory / clip["video_filename"]
                assert (
                    hashlib.sha256(archive.read(clip["video_filename"])).hexdigest()
                    == clip["sha256"]
                )
                assert probe_media(video)["streams"]
                full_decode(video)
            subtitles = list(directory.rglob("*.srt"))
            assert subtitles
            for subtitle in subtitles:
                assert (
                    archive.read(subtitle.relative_to(directory).as_posix())
                    == subtitle.read_bytes()
                )
                parsed = load_srt_transcript(subtitle)
                assert parsed.segments and parsed.source_duration_ms == 8000
                assert "00:00:00,000 --> 00:00:08,000" in subtitle.read_text()
                assert "Synthetic delivery checkpoint" in subtitle.read_text()
    finally:
        evidence = {
            "events": events,
            "errors": [repr(error) for error in errors],
            "before": before,
            "sqlite_busy_timeout_seconds": captured.get("busy_seconds"),
            "worker_exit": captured.get("exit"),
            "worker_alive_after_cleanup": worker.is_alive(),
            "renewal_expiries": [result.lease_expires_at for result in renewals],
        }
        for name in ("interrupted", "recovered"):
            if name in locals():
                evidence[name] = locals()[name]
        (fixture.root / "inspection-contention-evidence.json").write_text(
            json.dumps(evidence, default=str, indent=2)
        )
