"""Disposable SQLite and synthetic media evidence for producer progress."""

import hashlib
import json
import multiprocessing
import os
import secrets
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from test_completion_delivery import master, observe
from test_completion_identity import NOW, OTHER, OWNER, fixture
from test_completion_worker import due, runtime_fixture

from liveclip.api.app import create_app
from liveclip.application.completion import CompletionResourceNotFound
from liveclip.application.delivery_progress import (
    DeliveryProgressEvent,
    DeliveryProgressLostLease,
    DeliveryProgressWriteFailed,
)
from liveclip.application.delivery_progress import (
    DeliveryProgressPhase as Phase,
)
from liveclip.application.delivery_progress import (
    DeliveryProgressUnit as Unit,
)
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db import delivery_repository as delivery_module
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.completion_repository import SqlAlchemyCompletionRepository
from liveclip.db.delivery_repository import SqlAlchemyDeliveryRepository
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AssetRow,
    DeliveryProgressRow,
    DeliveryRow,
    ProjectRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.delivery.task_handler import DeliveryTaskCancelled, DeliveryTaskHandler
from liveclip.domain.state_transitions import FailureClass, TaskKind
from liveclip.worker import run_worker

pytestmark = pytest.mark.integration
__all__ = ["fixture", "runtime_fixture"]


@pytest.mark.parametrize("replace", [False, True])
def test_persisted_cancel_at_real_callback_acknowledges_only_owned_lease(
    runtime_fixture, monkeypatch, replace
):
    from liveclip.application.lease_monitor import LeaseMonitor

    _, runtime, fixture = runtime_fixture
    master(fixture)
    due(fixture)
    runtime.completion_runner.run_once(worker_id="enqueue")
    factory = SqlAlchemyDeliveryRepository.progress_sink
    captured = []
    tables = (TaskRow, TaskAttemptRow, DeliveryProgressRow, DeliveryRow, AssetRow)
    # Keep the monitor's cached observation unchanged across the database race.
    monkeypatch.setattr(LeaseMonitor, "start", lambda self: None)
    monkeypatch.setattr(LeaseMonitor, "stop", lambda self: None)

    def racing(self, identity, *args, **kwargs):
        sink = factory(self, identity, *args, **kwargs)

        class Race:
            def advance(self, item):
                if item.phase == Phase.COPYING_HASHING and item.completed > 0:
                    if replace:
                        with begin_immediate(fixture.engine) as connection:
                            connection.execute(
                                update(TaskRow)
                                .where(TaskRow.id == identity.task_id)
                                .values(
                                    heartbeat_at=datetime.now(UTC) - timedelta(seconds=2),
                                    lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                                )
                            )
                        successor = fixture.queue.claim(
                            worker_id="successor", task_kind=TaskKind.DELIVERY
                        )
                        assert successor is not None
                        assert successor.lease_token != identity.lease_token
                    fixture.queue.request_cancel(identity.task_id)
                    captured.append([fixture.rows(table) for table in tables])
                sink.advance(item)

        return Race()

    monkeypatch.setattr(SqlAlchemyDeliveryRepository, "progress_sink", racing)
    assert runtime.delivery_runner.run_one(worker_id="old").value == (
        "lost_lease" if replace else "cancelled"
    )
    assert len(captured) == 1
    if replace:
        assert [fixture.rows(table) for table in tables] == captured[0]
    else:
        delivery = fixture.rows(DeliveryRow)[0]
        task = next(row for row in fixture.rows(TaskRow) if row["id"] == delivery["task_id"])
        assert task["status"] == "cancelled"
        attempts = [row for row in fixture.rows(TaskAttemptRow) if row["task_id"] == task["id"]]
        assert len(attempts) == 1 and attempts[0]["outcome"] == "cancelled"
    root = fixture.root / "data" / fixture.rows(DeliveryRow)[0]["project_id"] / "deliveries"
    assert sorted(path.name for path in root.iterdir()) == [".delivery.lock"]


def _process_settings(root):
    from liveclip.config import Settings

    return Settings(
        _env_file=None,
        ai_provider="mock",
        data_dir=root / "data",
        allowed_media_roots_raw=str(root),
        max_stage_retries=5,
    )


def _progress_worker(root, channel, interrupt):
    factory = SqlAlchemyDeliveryRepository.progress_sink
    paused = False

    def observed(self, *args, **kwargs):
        sink = factory(self, *args, **kwargs)

        class Barrier:
            def advance(self, item):
                nonlocal paused
                sink.advance(item)
                if not paused and item.phase == Phase.COPYING_HASHING and item.completed > 0:
                    paused = True
                    channel.send((os.getpid(), item.completed))
                    assert channel.poll(30), "parent did not release durable event"
                    assert channel.recv() == "continue"
                    if interrupt:
                        raise DeliveryProgressWriteFailed("disposable producer interruption")

        return Barrier()

    SqlAlchemyDeliveryRepository.progress_sink = observed
    try:
        assert run_worker(_process_settings(root), once=True) == 0
        assert paused
    finally:
        SqlAlchemyDeliveryRepository.progress_sink = factory
        channel.close()


def _progress_reader(root, goal_id, channel):
    from test_completion_identity import Fixture

    from liveclip.bootstrap import LiveClipRuntime

    try:
        settings = _process_settings(root).model_copy(
            update={
                "workspace_username": "completion-owner",
                "api_token": SecretStr(secrets.token_urlsafe(32)),
            }
        )
        with LiveClipRuntime.open(settings) as runtime:
            fixture = Fixture(runtime.engine, root)
            with TestClient(create_app(settings, runtime=runtime)) as client:
                response = client.get(
                    f"/api/v1/completion-goals/{goal_id}",
                    headers={"Authorization": "Bearer " + settings.api_token.get_secret_value()},
                )
                assert response.status_code == 200
                payload = response.json()
                snapshot = payload["goal"]
                snapshot["download_url"] = payload["download_url"]
                channel.send((os.getpid(), snapshot, fixture.rows(DeliveryProgressRow)))
    finally:
        channel.close()


@contextmanager
def _spawn_progress(target, *args):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    process = context.Process(target=target, args=(*args, child))
    try:
        process.start()
        child.close()
        yield process, parent
    finally:
        if process.pid is not None:
            process.join(2)
            if process.is_alive():
                process.terminate()
                process.join(5)
            if process.is_alive():
                process.kill()
                process.join(5)
            assert not process.is_alive()
            process.close()
        parent.close()
        child.close()


def _worker_entry(root, interrupt, channel):
    _progress_worker(root, channel, interrupt)


def _read_progress(root, goal_id):
    with _spawn_progress(_progress_reader, root, goal_id) as (process, channel):
        assert channel.poll(30), "fresh reader deadline"
        result = channel.recv()
        process.join(10)
        assert process.exitcode == 0
        return result


def test_spawned_worker_durable_progress_and_independent_recovery(runtime_fixture, monkeypatch):
    import test_completion_delivery as delivery_fixture_module

    from liveclip.renderer.quality import full_decode, probe_media

    _, runtime, fixture = runtime_fixture
    original_profile = delivery_fixture_module.RenderProfile

    def large_synthetic_profile(**kwargs):
        kwargs.update(preview_width=2160, preview_height=3840)
        return original_profile(**kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(delivery_fixture_module, "RenderProfile", large_synthetic_profile)
        goal, _ = master(fixture)
    source = fixture.root / "synthetic.mp4"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert probe_media(source)["streams"]
    full_decode(source)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    due(fixture)
    runtime.completion_runner.run_once(worker_id="enqueue")
    delivery = fixture.rows(DeliveryRow)[0]
    task_id = delivery["task_id"]
    pids = []
    with _spawn_progress(_worker_entry, fixture.root, True) as (worker, channel):
        assert channel.poll(60), "Worker A durable event deadline"
        pid, count = channel.recv()
        pids.append(pid)
        assert pid == worker.pid and count > 0 and worker.is_alive()
        reader_pid, snapshot, history = _read_progress(fixture.root, goal.intent_id)
        pids.append(reader_pid)
        assert worker.is_alive()
        progress = snapshot["delivery_progress"]
        assert progress["completed"] == count
        assert progress["total"] is None or count < progress["total"]
        old_attempt = progress["attempt_id"]
        assert old_attempt is not None
        assert not snapshot.get("download_url")
        channel.send("continue")
        worker.join(30)
        assert worker.exitcode == 0
    reader_pid, interrupted, retained = _read_progress(fixture.root, goal.intent_id)
    pids.append(reader_pid)
    assert retained == history
    assert interrupted["delivery_progress"]["completed"] is None
    assert not interrupted.get("download_url")
    root = fixture.root / "data" / goal.project_id / "deliveries"
    assert sorted(path.name for path in root.iterdir()) == [".delivery.lock"]
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == task_id)
            .values(not_before=datetime.now(UTC) - timedelta(seconds=1))
        )
    with _spawn_progress(_worker_entry, fixture.root, False) as (worker, channel):
        assert channel.poll(60), "Worker B durable event deadline"
        pid, count = channel.recv()
        pids.append(pid)
        reader_pid, snapshot, _ = _read_progress(fixture.root, goal.intent_id)
        pids.append(reader_pid)
        assert worker.is_alive()
        assert snapshot["delivery_progress"]["attempt_id"] != old_attempt
        assert snapshot["delivery_progress"]["completed"] == count
        assert not snapshot.get("download_url")
        channel.send("continue")
        worker.join(30)
        assert worker.exitcode == 0
    assert len(set(pids)) == len(pids) and os.getpid() not in pids
    attempts = [row for row in fixture.rows(TaskAttemptRow) if row["task_id"] == task_id]
    assert sorted(row["attempt_number"] for row in attempts) == [1, 2]
    successor = next(row for row in attempts if row["attempt_number"] == 2)
    assert successor["id"] != old_attempt and successor["outcome"] == "succeeded"
    delivery = fixture.rows(DeliveryRow)[0]
    assert delivery["status"] == "succeeded"
    package = fixture.root / "data" / goal.project_id / delivery["directory_relative_path"]
    manifest = json.loads((package / "manifest.json").read_text())
    assert manifest["project_id"] == goal.project_id
    assert manifest["delivery_id"] == delivery["id"]
    assert manifest["delivery_version"] == f"v{delivery['version']:03d}"
    assert manifest["snapshot_fingerprint"] == delivery["snapshot_fingerprint"]
    assert (
        sum((package / clip["video_filename"]).stat().st_size for clip in manifest["clips"])
        > progress["completed"]
    )
    with zipfile.ZipFile(package / "delivery.zip") as archive:
        assert set(archive.namelist()) == {
            path.relative_to(package).as_posix()
            for path in package.rglob("*")
            if path.is_file() and path.name != "delivery.zip"
        }
        for name in archive.namelist():
            assert archive.read(name) == (package / name).read_bytes()
            assert archive.getinfo(name).file_size == (package / name).stat().st_size
        checksums = {}
        for line in (package / "checksums.sha256").read_text(encoding="utf-8").splitlines():
            digest, name = line.split("  ", 1)
            assert name not in checksums
            checksums[name] = digest
        assert set(checksums) == set(archive.namelist()) - {"checksums.sha256"}
        for name, digest in checksums.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        for clip in manifest["clips"]:
            video = package / clip["video_filename"]
            assert hashlib.sha256(video.read_bytes()).hexdigest() == clip["sha256"]
            assert probe_media(video)["streams"]
            full_decode(video)
            assert "-->" in (package / clip["subtitle_filename"]).read_text(encoding="utf-8")
    for asset in fixture.rows(AssetRow):
        if asset["kind"].startswith("delivery_"):
            path = fixture.root / "data" / goal.project_id / asset["relative_path"]
            assert asset["status"] == "committed"
            assert path.parent == package
            assert (
                asset["id"]
                == delivery[
                    "zip_asset_id" if asset["kind"] == "delivery_zip" else "manifest_asset_id"
                ]
            )
            assert asset["producer_attempt_id"] == successor["id"]
            assert path.stat().st_size == asset["size_bytes"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    (fixture.root / "process-progress-evidence.json").write_text(
        json.dumps(
            {
                "process_ids": pids,
                "old_attempt_id": old_attempt,
                "successor_attempt_id": successor["id"],
                "attempt_numbers": [1, 2],
                "observed_while_worker_a_alive": progress,
                "observed_after_worker_a_exit": interrupted["delivery_progress"],
                "observed_while_worker_b_alive": snapshot["delivery_progress"],
                "source_sha256": source_hash,
                "package_relative_path": delivery["directory_relative_path"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def active(fixture, *, include_zip=True):
    goal, _ = master(fixture, include_zip=include_zip)
    observe(fixture)
    lease = fixture.queue.claim(
        worker_id="progress-worker",
        task_kind=TaskKind.DELIVERY,
        now=NOW + timedelta(seconds=61),
    )
    assert lease is not None
    identity = LeaseIdentity(
        task_id=lease.task_id,
        worker_id=lease.worker_id,
        lease_token=lease.lease_token,
    )
    repository = SqlAlchemyDeliveryRepository(fixture.engine)
    work = repository.start_delivery(identity)
    sink = repository.progress_sink(identity, work, attempt_number=lease.attempt_number)
    return goal, lease, identity, repository, work, sink


def event(completed, total=None, phase=Phase.COPYING_HASHING, unit=Unit.BYTES):
    return DeliveryProgressEvent(phase=phase, unit=unit, completed=completed, total=total)


def test_worker_producer_events_visible_through_get_and_retained_bytes(
    runtime_fixture, monkeypatch
):
    import test_completion_delivery as delivery_fixture_module

    settings, runtime, fixture = runtime_fixture
    settings = settings.model_copy(
        update={
            "workspace_username": "completion-owner",
            "api_token": SecretStr(secrets.token_urlsafe(32)),
        }
    )
    original_profile = delivery_fixture_module.RenderProfile

    def large_synthetic_profile(**kwargs):
        kwargs.update(preview_width=2160, preview_height=3840)
        return original_profile(**kwargs)

    monkeypatch.setattr(delivery_fixture_module, "RenderProfile", large_synthetic_profile)
    goal, _ = master(fixture)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    due(fixture)
    runtime.completion_runner.run_once(worker_id="enqueue")
    due(fixture)
    original_sink = SqlAlchemyDeliveryRepository.progress_sink
    events = []
    with TestClient(
        create_app(settings, runtime=runtime),
        headers={"Authorization": "Bearer " + settings.api_token.get_secret_value()},
    ) as client:
        url = f"/api/v1/completion-goals/{goal.intent_id}"

        def observed_sink(self, *args, **kwargs):
            sink = original_sink(self, *args, **kwargs)

            class Observed:
                def advance(self, event):
                    sink.advance(event)
                    response = client.get(url)
                    assert response.status_code == 200
                    payload = response.json()
                    projected = payload.get("goal", payload)["delivery_progress"]
                    assert projected["phase"] == event.phase.value
                    assert projected["completed"] == event.completed
                    assert projected["total"] == event.total
                    events.append(event)

            return Observed()

        monkeypatch.setattr(SqlAlchemyDeliveryRepository, "progress_sink", observed_sink)
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(run_worker, settings, once=True).result(timeout=60) == 0
    assert fixture.rows(DeliveryRow)[0]["status"] == "succeeded"
    for phase in (Phase.COPYING_HASHING, Phase.WRITING_ZIP):
        counts = [item.completed for item in events if item.phase == phase]
        assert len(set(counts)) > 3 and counts == sorted(counts)
    delivery = fixture.rows(DeliveryRow)[0]
    root = fixture.root / "data" / goal.project_id / delivery["directory_relative_path"]
    manifest = json.loads((root / "manifest.json").read_text())
    with zipfile.ZipFile(root / "delivery.zip") as archive:
        for name in archive.namelist():
            assert archive.read(name) == (root / name).read_bytes()
        for clip in manifest["clips"]:
            assert (
                hashlib.sha256(archive.read(clip["video_filename"])).hexdigest() == clip["sha256"]
            )
    for asset in fixture.rows(AssetRow):
        if asset["kind"].startswith("delivery_"):
            path = fixture.root / "data" / goal.project_id / asset["relative_path"]
            assert path.stat().st_size == asset["size_bytes"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]


def test_durable_monotonic_progress_and_authorized_read_only_observation(fixture):
    goal, lease, _, _, _, sink = active(fixture)
    repository = SqlAlchemyCompletionRepository(fixture.engine)
    for completed in (0, 4, 12):
        sink.advance(event(completed))
        fixture.engine.dispose()
        assert (
            repository.get(goal.intent_id, actor_user_id=OWNER).delivery_progress.completed
            == completed
        )
    sink.advance(event(12, 12))
    before = fixture.rows(DeliveryProgressRow)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == lease.task_id)
            .values(
                heartbeat_at=NOW + timedelta(seconds=62),
            )
        )
    assert (
        repository.get(goal.intent_id, actor_user_id=OWNER).delivery_progress.business_advanced_at
        == before[0]["business_advanced_at"]
    )
    sink.advance(event(12, 12))
    assert fixture.rows(DeliveryProgressRow) == before
    for invalid in (event(11, 12), event(12, 13), event(12)):
        with pytest.raises(ValueError):
            sink.advance(invalid)
    sink.advance(event(0, 2, Phase.COMMITTING_ASSETS, Unit.ASSETS))
    with pytest.raises(ValueError):
        sink.advance(event(12, 12))
    before = [fixture.rows(table) for table in (DeliveryProgressRow, TaskRow, DeliveryRow)]
    for _ in range(3):
        repository.get(goal.intent_id, actor_user_id=OWNER)
    with pytest.raises(CompletionResourceNotFound):
        repository.get(goal.intent_id, actor_user_id=OTHER)
    assert [fixture.rows(table) for table in (DeliveryProgressRow, TaskRow, DeliveryRow)] == before


def test_progress_transient_database_failure_is_distinct_from_invalid_event(fixture, monkeypatch):
    _, _, _, _, _, sink = active(fixture)
    sink.advance(event(0))
    before = fixture.rows(DeliveryProgressRow)

    @contextmanager
    def busy(engine):
        raise OperationalError("BEGIN IMMEDIATE", {}, RuntimeError("database is locked"))
        yield  # pragma: no cover

    with monkeypatch.context() as patch:
        patch.setattr(delivery_module, "begin_immediate", busy)
        with pytest.raises(DeliveryProgressWriteFailed):
            sink.advance(event(1))
    assert fixture.rows(DeliveryProgressRow) == before
    sink.advance(event(1, 2))
    with pytest.raises(ValueError):
        sink.advance(event(1, 3))


@pytest.mark.parametrize("failure", ["lost", "transient"])
def test_runner_classifies_progress_failure_and_cleans_only_temporary_work(
    runtime_fixture,
    monkeypatch,
    failure,
):
    _, runtime, fixture = runtime_fixture
    master(fixture)
    due(fixture)
    runtime.completion_runner.run_once(worker_id="enqueue")
    due(fixture)
    factory = SqlAlchemyDeliveryRepository.progress_sink
    failed = False

    def faulty(self, *args, **kwargs):
        sink = factory(self, *args, **kwargs)

        class Fault:
            def advance(self, item):
                nonlocal failed
                if not failed and item.phase == Phase.COPYING_HASHING and item.completed > 0:
                    failed = True
                    if failure == "lost":
                        raise DeliveryProgressLostLease("injected owner change")
                    raise DeliveryProgressWriteFailed("injected database contention")
                sink.advance(item)

        return Fault()

    monkeypatch.setattr(SqlAlchemyDeliveryRepository, "progress_sink", faulty)
    outcome = runtime.delivery_runner.run_one(worker_id="first")
    assert outcome.value == ("lost_lease" if failure == "lost" else "retry_scheduled")
    delivery = fixture.rows(DeliveryRow)[0]
    task = next(row for row in fixture.rows(TaskRow) if row["id"] == delivery["task_id"])
    assert task["status"] == ("running" if failure == "lost" else "queued")
    assert task["retry_count"] == (0 if failure == "lost" else 1)
    root = fixture.root / "data" / delivery["project_id"] / "deliveries"
    assert sorted(path.name for path in root.iterdir()) == [".delivery.lock"]
    if failure == "transient":
        with begin_immediate(fixture.engine) as connection:
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == task["id"])
                .values(
                    not_before=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        assert runtime.delivery_runner.run_one(worker_id="retry").value == "succeeded"
        assert len(fixture.rows(DeliveryProgressRow)) == 2


def test_no_zip_delivery_reports_only_work_performed(fixture):
    goal, _, identity, repository, work, sink = active(fixture, include_zip=False)
    events = []

    class Record:
        def advance(self, item):
            sink.advance(item)
            events.append(item)

    result = DeliveryTaskHandler(
        data_dir=fixture.root / "data",
        assets=SqlAlchemyAssetStore(fixture.engine),
    ).execute(work, identity, cancel_requested=lambda: False, progress=Record())
    assert all(item.phase != Phase.WRITING_ZIP for item in events)
    assert events[-1].completed == events[-1].total == 1
    assert result.zip_asset_id is None
    assert repository.complete_delivery(identity, work, result)
    assert (
        fixture.repository.get(goal.intent_id, actor_user_id=OWNER).delivery_progress.completed
        is None
    )


@pytest.mark.parametrize("failure", ["zip", "cancel"])
def test_producer_failure_never_publishes_and_preserves_source(fixture, monkeypatch, failure):
    from liveclip.delivery import package as package_module

    _, _, identity, _, work, sink = active(fixture)
    root = fixture.root / "data" / work.project_id
    source = root / work.clips[0].video_relative_path
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    cancelled = False
    events = []

    class Record:
        def advance(self, item):
            nonlocal cancelled
            sink.advance(item)
            events.append(item)
            if failure == "cancel" and item.phase == Phase.COPYING_HASHING and item.completed:
                cancelled = True

    def broken_zip(*args, **kwargs):
        raise OSError("injected ZIP writer failure")

    if failure == "zip":
        monkeypatch.setattr(package_module, "_write_pinned_zip_member", broken_zip)
    with pytest.raises(OSError if failure == "zip" else DeliveryTaskCancelled):
        DeliveryTaskHandler(
            data_dir=fixture.root / "data",
            assets=SqlAlchemyAssetStore(fixture.engine),
        ).execute(work, identity, cancel_requested=lambda: cancelled, progress=Record())
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert sorted(path.name for path in (root / "deliveries").iterdir()) == [".delivery.lock"]
    assert all(item.phase != Phase.COMMITTING_ASSETS for item in events)
    assert fixture.rows(DeliveryRow)[0]["status"] != "succeeded"


@pytest.mark.parametrize(
    "fault",
    [
        "worker",
        "token",
        "expiry",
        "attempt",
        "target",
        "link",
        "generation",
        "epoch",
        "fingerprint",
    ],
)
def test_each_authority_fence_rejects_late_callback_and_hides_counts(fixture, fault):
    goal, lease, _, _, work, sink = active(fixture)
    sink.advance(event(1))
    table, key, values = TaskRow, TaskRow.id == lease.task_id, {}
    if fault == "worker":
        values = {"worker_id": "successor"}
    elif fault == "token":
        values = {"lease_token": "f" * 64}
    elif fault == "expiry":
        values = {
            "heartbeat_at": datetime.now(UTC) - timedelta(seconds=2),
            "lease_expires_at": datetime.now(UTC) - timedelta(seconds=1),
        }
    elif fault == "attempt":
        values = {"attempt_count": lease.attempt_number + 1}
    elif fault == "target":
        values = {"target_id": "f" * 32}
    elif fault == "link":
        table, key = DeliveryRow, DeliveryRow.id == work.delivery_id
        values = {"task_id": None}
    elif fault in {"generation", "epoch"}:
        table, key = ProjectRow, ProjectRow.id == work.project_id
        values = (
            {"current_generation": work.generation + 1}
            if fault == "generation"
            else {"revision_epoch": work.revision_epoch + 1}
        )
    else:
        values = {"input_fingerprint": "f" * 64}
    with begin_immediate(fixture.engine) as connection:
        connection.execute(update(table).where(key).values(**values))
    before = fixture.rows(DeliveryProgressRow)
    with pytest.raises(DeliveryProgressLostLease):
        sink.advance(event(2))
    assert fixture.rows(DeliveryProgressRow) == before
    progress = fixture.repository.get(goal.intent_id, actor_user_id=OWNER).delivery_progress
    assert progress.completed is None and not progress.lease_fresh


@pytest.mark.parametrize("committed_count", [1, 2])
def test_post_commit_failure_retains_assets_and_retry_only_reports_adoption(
    fixture, committed_count
):
    goal, lease, identity, repository, work, sink = active(fixture)
    handler = DeliveryTaskHandler(
        data_dir=fixture.root / "data",
        assets=SqlAlchemyAssetStore(fixture.engine),
    )

    class FailAfterCommit:
        def advance(self, event):
            if event.phase == Phase.COMMITTING_ASSETS and event.completed == committed_count:
                raise DeliveryProgressWriteFailed("injected required write failure")
            sink.advance(event)

    with pytest.raises(DeliveryProgressWriteFailed):
        handler.execute(work, identity, cancel_requested=lambda: False, progress=FailAfterCommit())
    assets = [row for row in fixture.rows(AssetRow) if row["kind"].startswith("delivery_")]
    assert sum(row["status"] == "committed" for row in assets) == committed_count
    assert fixture.rows(DeliveryRow)[0]["status"] != "succeeded"
    fixture.queue.fail(
        lease,
        failure_class=FailureClass.TRANSIENT,
        error_code="DELIVERY_PROGRESS_WRITE_TEMPORARY",
        safe_message="Injected progress failure",
        retry_delay_ms=0,
        now=NOW + timedelta(seconds=62),
    )
    retry = fixture.queue.claim(
        worker_id="retry",
        task_kind=TaskKind.DELIVERY,
        now=NOW + timedelta(seconds=63),
    )
    assert retry is not None and retry.attempt_number == lease.attempt_number + 1
    identity = LeaseIdentity(
        task_id=retry.task_id,
        worker_id=retry.worker_id,
        lease_token=retry.lease_token,
    )
    work = repository.start_delivery(identity)
    fresh_sink = repository.progress_sink(identity, work, attempt_number=retry.attempt_number)
    events = []

    class Record:
        def advance(self, event):
            fresh_sink.advance(event)
            events.append(event)

    with pytest.raises(DeliveryProgressLostLease):
        sink.advance(event(999999))
    result = handler.execute(work, identity, cancel_requested=lambda: False, progress=Record())
    assert {item.phase for item in events} == {Phase.VERIFYING_PACKAGE, Phase.COMMITTING_ASSETS}
    assert repository.complete_delivery(identity, work, result)
    progress = fixture.repository.get(goal.intent_id, actor_user_id=OWNER).delivery_progress
    assert progress.phase == Phase.SUCCEEDED and progress.completed is None
    assert len(fixture.rows(DeliveryProgressRow)) == 2
