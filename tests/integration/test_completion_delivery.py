"""B2 binding evidence on disposable SQLite and synthetic local media."""

from __future__ import annotations

import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Semaphore

import pytest
from sqlalchemy import delete, insert, select, update
from test_completion_identity import NOW, OWNER, fixture, revoke
from test_completion_selection import checkpoint, ready, snapshot

from liveclip.application.completion_runner import CompletionRunner, ReconciliationResult
from liveclip.application.deliveries import DeliveryRequest
from liveclip.application.lease_monitor import LeaseMonitor
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.render_runner import RenderTaskRunner
from liveclip.application.rendering import RenderProfile, RenderService
from liveclip.application.reviewing import RenderRequest
from liveclip.config.settings import Settings
from liveclip.db import completion_repository as module
from liveclip.db import delivery_repository as delivery_module
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import new_id
from liveclip.db.completion_repository import SqlAlchemyCompletionRepository
from liveclip.db.delivery_repository import SqlAlchemyDeliveryRepository
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    AssetRow,
    CandidateClipRow,
    CaptionCueRow,
    CompletionIntentRow,
    DeliveryClipRow,
    DeliveryRow,
    EditPlanRevisionRow,
    IdempotencyRecordRow,
    ProjectRow,
    RenderJobRow,
    ReviewDecisionRow,
    SourceMediaRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.db.render_repository import SqlAlchemyRenderRepository
from liveclip.delivery.task_handler import DeliveryTaskHandler
from liveclip.domain.state_transitions import FailureClass, TaskKind
from liveclip.media.secure_files import PinnedRegularFile
from liveclip.renderer.quality import probe_media
from liveclip.renderer.task_handler import RenderTaskHandler
from liveclip.services.demo_media import create_demo_source

pytestmark = pytest.mark.integration
__all__ = ["fixture"]


def observe(fixture, at=NOW + timedelta(seconds=60), *, delivery_max_retries=None):
    return CompletionRunner(
        fixture.queue,
        SqlAlchemyCompletionRepository(
            fixture.engine,
            data_dir=fixture.root / "data",
            delivery_max_retries=delivery_max_retries,
        ),
    ).run_once(worker_id="completion", now=at)


def master(fixture, *, kind="proxy", execute=True, include_zip=True, count=1):
    goal, clips = ready(fixture, count=count, include_zip=include_zip)
    assert fixture.observe() == ReconciliationResult.DEFERRED
    source = fixture.root / "synthetic.mp4"
    create_demo_source(output_path=source, duration_ms=20_000)
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(SourceMediaRow)
            .where(SourceMediaRow.project_id == goal.project_id)
            .values(
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                size_bytes=source.stat().st_size,
                mtime_ns=source.stat().st_mtime_ns,
                device=source.stat().st_dev,
                inode=source.stat().st_ino,
                width=640,
                height=360,
                frame_rate="24",
                video_stream_index=0,
                audio_stream_index=1,
                video_rotation_degrees=0,
            )
        )
        revision = connection.scalar(
            select(EditPlanRevisionRow.id).where(EditPlanRevisionRow.candidate_clip_id == clips[0])
        )
        connection.execute(
            insert(CaptionCueRow).values(
                id=new_id(),
                edit_plan_revision_id=revision,
                cue_index=0,
                start_ms=0,
                end_ms=8000,
                text="Synthetic delivery checkpoint",
            )
        )
    repository = RenderService(
        SqlAlchemyRenderRepository(fixture.engine),
        RenderProfile(
            preview_width=270,
            preview_height=480,
            final_width=270,
            final_height=480,
            encoder="libx264",
            max_retries=1,
        ),
    )
    render = repository.enqueue(clips[0], RenderRequest(expected_revision=1, kind=kind))
    if execute:
        runner = RenderTaskRunner(
            queue=fixture.queue,
            repository=SqlAlchemyRenderRepository(fixture.engine),
            handler=RenderTaskHandler(
                data_dir=fixture.root / "data", assets=SqlAlchemyAssetStore(fixture.engine)
            ),
            heartbeat_seconds=5,
        )
        assert runner.run_one(worker_id="render").value == "succeeded"
    return goal, render


def package(fixture, *, at=NOW + timedelta(seconds=61)):
    lease = fixture.queue.claim(worker_id="packager", task_kind=TaskKind.DELIVERY, now=at)
    assert lease is not None
    identity = LeaseIdentity(
        task_id=lease.task_id, worker_id=lease.worker_id, lease_token=lease.lease_token
    )
    repository = SqlAlchemyDeliveryRepository(fixture.engine)
    work = repository.start_delivery(identity)
    persistence = DeliveryTaskHandler(
        data_dir=fixture.root / "data", assets=SqlAlchemyAssetStore(fixture.engine)
    ).execute(work, identity, cancel_requested=lambda: False)
    assert repository.complete_delivery(identity, work, persistence)
    return work, persistence


def test_missing_master_parks_without_render_or_delivery(fixture):
    goal, _ = ready(fixture, count=1)
    fixture.observe()
    saved = checkpoint(fixture)
    assert observe(fixture) == ReconciliationResult.NEEDS_ACTION
    assert fixture.rows(CompletionIntentRow)[0]["blocking_code"] == "MASTER_MISSING"
    assert checkpoint(fixture) == saved
    assert fixture.rows(RenderJobRow) == [] and fixture.rows(DeliveryRow) == []
    before = snapshot(fixture)
    assert observe(fixture, NOW + timedelta(days=1)) == ReconciliationResult.IDLE
    assert snapshot(fixture) == before
    assert fixture.task(goal)["retry_count"] == 0


@pytest.mark.parametrize("kind", ["proxy", "final"])
def test_one_bound_version_and_inspected_package(fixture, kind):
    goal, _ = master(fixture, kind=kind)
    saved = checkpoint(fixture)
    previous = SqlAlchemyDeliveryRepository(fixture.engine).enqueue_delivery(
        goal.project_id,
        DeliveryRequest(),
        max_retries=1,
    )
    assert observe(fixture) == ReconciliationResult.DEFERRED
    bound = fixture.rows(CompletionIntentRow)[0]
    assert bound["delivery_action_key"] == f"completion-delivery:{goal.intent_id}"
    deliveries = fixture.rows(DeliveryRow)
    assert len(deliveries) == 2
    current = next(row for row in deliveries if row["id"] == bound["delivery_id"])
    assert current["version"] == previous.version + 1
    # Package the previously queued version, then the bound one.
    package(fixture)
    work, persisted = package(fixture)
    assert work.delivery_id == bound["delivery_id"]
    fixture.engine.dispose()
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.PROCESSED
    final = fixture.rows(CompletionIntentRow)[0]
    assert final["delivery_id"] == bound["delivery_id"] and final["outcome_code"] == "delivered"
    assert checkpoint(fixture) == saved
    assert persisted.manifest_asset_id and persisted.zip_asset_id
    root = fixture.root / "data" / goal.project_id / "deliveries" / f"v{work.version:03d}"
    manifest = json.loads((root / "manifest.json").read_text())
    assert len(manifest["clips"]) == 1
    with zipfile.ZipFile(root / "delivery.zip") as archive:
        assert json.loads(archive.read("manifest.json")) == manifest
        for clip in manifest["clips"]:
            assert (
                hashlib.sha256(archive.read(clip["video_filename"])).hexdigest() == clip["sha256"]
            )
            metadata = probe_media(root / clip["video_filename"])
            assert metadata["streams"]


@pytest.mark.parametrize("fault", ["final-fence", "intent-cas", "idempotency"])
def test_enqueue_transaction_fault_rolls_back_binding(fixture, monkeypatch, fault):
    master(fixture)
    lease = fixture.queue.claim_completion(worker_id="completion", now=NOW + timedelta(seconds=60))
    before = snapshot(fixture)

    def crash(*args, **kwargs):
        raise RuntimeError("injected transaction fault")

    if fault == "final-fence":
        monkeypatch.setattr(module, "finish_completion_attempt", lambda *a, **k: False)
        assert (
            fixture.repository.reconcile_completion(lease, now=NOW + timedelta(seconds=60))
            == ReconciliationResult.LOST_LEASE
        )
    else:
        if fault == "intent-cas":
            monkeypatch.setattr(SqlAlchemyCompletionRepository, "_update", crash)
        else:
            monkeypatch.setattr(delivery_module, "record_idempotent_resource", crash)
        with pytest.raises(RuntimeError):
            fixture.repository.reconcile_completion(lease, now=NOW + timedelta(seconds=60))
    assert snapshot(fixture) == before


@pytest.mark.parametrize("prior_version", [False, True])
def test_lost_response_recovers_same_binding(fixture, monkeypatch, prior_version):
    goal, _ = master(fixture)
    if prior_version:
        SqlAlchemyDeliveryRepository(fixture.engine).enqueue_delivery(
            goal.project_id, DeliveryRequest(), max_retries=1
        )
    original = module.begin_immediate

    @contextmanager
    def lose_response(engine):
        with original(engine) as connection:
            yield connection
        raise ConnectionError("injected response loss")

    with monkeypatch.context() as patch:
        patch.setattr(module, "begin_immediate", lose_response)
        with pytest.raises(ConnectionError):
            observe(fixture)
    bound = fixture.rows(CompletionIntentRow)[0]["delivery_id"]
    assert bound is not None
    deliveries = fixture.rows(DeliveryRow)
    assert next(row for row in deliveries if row["id"] == bound)["version"] == (
        2 if prior_version else 1
    )
    tasks = fixture.rows(TaskRow)
    records = fixture.rows(IdempotencyRecordRow)
    fixture.engine.dispose()
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.DEFERRED
    assert fixture.rows(CompletionIntentRow)[0]["delivery_id"] == bound
    assert fixture.rows(DeliveryRow) == deliveries
    assert fixture.rows(IdempotencyRecordRow) == records
    assert [t for t in fixture.rows(TaskRow) if t["kind"] == "delivery"] == [
        t for t in tasks if t["kind"] == "delivery"
    ]


@pytest.mark.parametrize("mixture", ["historical-success", "newer-failed-final"])
@pytest.mark.parametrize("missing_other", [False, True])
def test_compatible_replacement_is_not_masked(fixture, mixture, missing_other):
    goal, _ = master(fixture, execute=False, count=2 if missing_other else 1)
    active = fixture.rows(RenderJobRow)[0]
    historical = dict(active)
    historical.update(
        id=new_id(),
        task_id=None,
        spec_fingerprint="b" * 64,
        status="succeeded" if mixture == "historical-success" else "failed",
        kind="proxy" if mixture == "historical-success" else "final",
        spec_json={}
        if mixture == "historical-success"
        else {**active["spec_json"], "text_mode": "title_and_captions"},
        created_at=active["created_at"] + timedelta(seconds=1),
    )
    with begin_immediate(fixture.engine) as connection:
        connection.execute(insert(RenderJobRow).values(**historical))
    before = fixture.rows(RenderJobRow)
    assert observe(fixture) == (
        ReconciliationResult.NEEDS_ACTION if missing_other else ReconciliationResult.DEFERRED
    )
    assert fixture.rows(RenderJobRow) == before
    assert fixture.rows(DeliveryRow) == []
    assert fixture.task(goal)["retry_count"] == 0
    if missing_other:
        assert fixture.rows(CompletionIntentRow)[0]["blocking_code"] == "MASTER_MISSING"
        return
    assert fixture.task(goal)["not_before"] == NOW + timedelta(seconds=120)
    runner = RenderTaskRunner(
        queue=fixture.queue,
        repository=SqlAlchemyRenderRepository(fixture.engine),
        handler=RenderTaskHandler(
            data_dir=fixture.root / "data", assets=SqlAlchemyAssetStore(fixture.engine)
        ),
        heartbeat_seconds=5,
    )
    assert runner.run_one(worker_id="replacement").value == "succeeded"
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.DEFERRED
    bound = fixture.rows(CompletionIntentRow)[0]["delivery_id"]
    assert bound is not None
    assert observe(fixture, NOW + timedelta(seconds=180)) == ReconciliationResult.DEFERRED
    assert [row["id"] for row in fixture.rows(DeliveryRow)] == [bound]


@pytest.mark.parametrize("limit", [0, 7])
@pytest.mark.parametrize("explicit", [False, True])
def test_delivery_retry_configuration_survives_restart_and_failed_polling(
    fixture, monkeypatch, limit, explicit
):
    monkeypatch.setattr(module, "get_settings", lambda: Settings(max_stage_retries=limit))
    goal, _ = master(fixture)
    assert observe(fixture, delivery_max_retries=limit if explicit else None) == (
        ReconciliationResult.DEFERRED
    )
    delivery_task = next(t for t in fixture.rows(TaskRow) if t["kind"] == "delivery")
    assert delivery_task["max_retries"] == limit
    fixture.engine.dispose()
    assert observe(fixture, NOW + timedelta(seconds=120), delivery_max_retries=2) == (
        ReconciliationResult.DEFERRED
    )
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(TaskRow)
            .where(TaskRow.id == delivery_task["id"])
            .values(status="failed", retry_count=limit)
        )
    assert observe(fixture, NOW + timedelta(seconds=180)) == ReconciliationResult.NEEDS_ACTION
    assert observe(fixture, NOW + timedelta(days=1)) == ReconciliationResult.IDLE
    task = next(t for t in fixture.rows(TaskRow) if t["id"] == delivery_task["id"])
    assert task["max_retries"] == task["retry_count"] == limit
    saved = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    fixture.service.resume(goal.intent_id, actor_user_id=OWNER, expected_version=saved.version)
    assert observe(fixture, NOW + timedelta(days=2)) == ReconciliationResult.NEEDS_ACTION
    assert next(t for t in fixture.rows(TaskRow) if t["id"] == delivery_task["id"]) == task
    assert fixture.task(goal)["retry_count"] == 0


@pytest.mark.parametrize(
    "state,code",
    [
        ("queued", None),
        ("running", None),
        ("failed", "MASTER_FAILED"),
        ("exhausted", "MASTER_FAILED_EXHAUSTED"),
        ("stale", "MASTER_STALE"),
        ("stale-run", "MASTER_STALE"),
        ("cancelled", "MASTER_STALE"),
        ("failed-task", "MASTER_STALE"),
        ("stale-spec", "MASTER_STALE"),
    ],
)
def test_master_states_never_reset_render_budget(fixture, state, code):
    goal, _ = master(fixture, execute=False)
    render = fixture.rows(RenderJobRow)[0]
    with begin_immediate(fixture.engine) as connection:
        if state in {"failed", "exhausted"}:
            connection.execute(update(RenderJobRow).values(status="failed"))
        elif state == "running":
            connection.execute(update(RenderJobRow).values(status="running"))
        elif state == "stale-spec":
            connection.execute(update(RenderJobRow).values(spec_json={}))
        if state == "stale":
            connection.execute(
                update(TaskRow).where(TaskRow.id == render["task_id"]).values(expected_generation=2)
            )
        elif state in {"stale-run", "cancelled", "failed-task"}:
            values = {
                "stale-run": {"pipeline_run_id": None},
                "cancelled": {"cancellation_requested_at": NOW},
                "failed-task": {"status": "failed"},
            }[state]
            connection.execute(
                update(TaskRow).where(TaskRow.id == render["task_id"]).values(**values)
            )
        elif state == "exhausted":
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == render["task_id"])
                .values(status="failed", retry_count=1)
            )
    renders = fixture.rows(RenderJobRow)
    task = next(t for t in fixture.rows(TaskRow) if t["id"] == render["task_id"])
    assert observe(fixture) == (
        ReconciliationResult.NEEDS_ACTION if code else ReconciliationResult.DEFERRED
    )
    assert fixture.rows(CompletionIntentRow)[0]["blocking_code"] == code
    assert fixture.rows(RenderJobRow) == renders
    assert next(t for t in fixture.rows(TaskRow) if t["id"] == render["task_id"]) == task
    assert fixture.rows(DeliveryRow) == []
    assert fixture.task(goal)["retry_count"] == 0
    if code is None:
        assert fixture.task(goal)["not_before"] == NOW + timedelta(seconds=120)


@pytest.mark.parametrize("mode", ["removed", "disabled", "archived", "downgraded"])
@pytest.mark.parametrize("bound", [False, True])
def test_live_authority_before_enqueue_and_bound_replay(fixture, mode, bound):
    goal, _ = master(fixture)
    if bound:
        observe(fixture)
    with begin_immediate(fixture.engine) as connection:
        revoke(connection, goal, mode)
    deliveries = fixture.rows(DeliveryRow)
    saved = fixture.rows(CompletionIntentRow)[0]
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.NEEDS_ACTION
    current = fixture.rows(CompletionIntentRow)[0]
    assert current["blocking_code"] == "AUTHORIZATION_REQUIRED"
    for field in ("delivery_id", "delivery_action_key", "selection_checkpoint_json"):
        assert current[field] == saved[field]
    assert fixture.rows(DeliveryRow) == deliveries


def test_simultaneous_reconcile_has_one_binding_and_attempt(fixture):
    master(fixture)
    lease = fixture.queue.claim_completion(worker_id="completion", now=NOW + timedelta(seconds=60))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                fixture.repository.reconcile_completion, lease, now=NOW + timedelta(seconds=60)
            )
            for _ in range(2)
        ]
        outcomes = [future.result(timeout=10) for future in futures]
    assert sorted(outcomes) == sorted(
        [ReconciliationResult.DEFERRED, ReconciliationResult.LOST_LEASE]
    )
    assert len(fixture.rows(DeliveryRow)) == 1
    assert len(fixture.rows(TaskAttemptRow)) == 3  # selection, render, binding


def test_failed_packaging_parks_without_retry_reset(fixture):
    master(fixture)
    observe(fixture)
    lease = fixture.queue.claim(
        worker_id="packager", task_kind=TaskKind.DELIVERY, now=NOW + timedelta(seconds=61)
    )
    assert lease is not None
    fixture.queue.fail(
        lease,
        failure_class=FailureClass.DETERMINISTIC,
        error_code="INJECTED_PACKAGE_FAILURE",
        safe_message="Synthetic failure",
        now=NOW + timedelta(seconds=62),
    )
    delivery = fixture.rows(DeliveryRow)[0]
    task = next(t for t in fixture.rows(TaskRow) if t["id"] == lease.task_id)
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.NEEDS_ACTION
    assert fixture.rows(CompletionIntentRow)[0]["blocking_code"] == "DELIVERY_FAILED"
    assert fixture.rows(DeliveryRow)[0] == delivery
    assert next(t for t in fixture.rows(TaskRow) if t["id"] == lease.task_id) == task
    assert observe(fixture, NOW + timedelta(days=1)) == ReconciliationResult.IDLE


@pytest.mark.parametrize("target", ["manifest", "zip", "media", "zero-clips", "task-only"])
def test_task_success_or_tampered_artifacts_cannot_complete_goal(fixture, target):
    goal, _ = master(fixture)
    observe(fixture)
    if target == "task-only":
        with begin_immediate(fixture.engine) as connection:
            connection.execute(
                update(TaskRow).where(TaskRow.kind == "delivery").values(status="succeeded")
            )
    else:
        work, _ = package(fixture)
        root = fixture.root / "data" / goal.project_id / "deliveries" / f"v{work.version:03d}"
        if target == "zero-clips":
            with begin_immediate(fixture.engine) as connection:
                connection.execute(delete(DeliveryClipRow))
        else:
            manifest = json.loads((root / "manifest.json").read_text())
            path = {
                "manifest": root / "manifest.json",
                "zip": root / "delivery.zip",
                "media": root / manifest["clips"][0]["video_filename"],
            }[target]
            path.write_bytes(b"injected artifact corruption")
    bound = fixture.rows(CompletionIntentRow)[0]["delivery_id"]
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.NEEDS_ACTION
    row = fixture.rows(CompletionIntentRow)[0]
    assert row["delivery_id"] == bound and row["outcome_code"] is None
    assert len(fixture.rows(DeliveryRow)) == 1


def test_cancelled_completion_preserves_bound_package_and_lease_history(fixture):
    goal, _ = master(fixture)
    observe(fixture)
    current = fixture.service.get(goal.intent_id, actor_user_id=OWNER)
    fixture.service.cancel(goal.intent_id, actor_user_id=OWNER, expected_version=current.version)
    deliveries = fixture.rows(DeliveryRow)
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.IDLE
    assert fixture.rows(DeliveryRow) == deliveries
    assert fixture.rows(CompletionIntentRow)[0]["delivery_id"] == current.delivery_id


def test_publication_crash_and_expired_worker_recover_same_immutable_package(fixture, monkeypatch):
    goal, _ = master(fixture)
    observe(fixture)
    bound = fixture.rows(CompletionIntentRow)[0]["delivery_id"]

    def crash(*args, **kwargs):
        raise ConnectionError("crash after atomic publication before asset commit")

    with monkeypatch.context() as patch:
        patch.setattr(SqlAlchemyAssetStore, "commit", crash)
        with pytest.raises(ConnectionError):
            package(fixture)
    directory = fixture.root / "data" / goal.project_id / "deliveries" / "v001"
    before = {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }
    assert "manifest.json" in before and "delivery.zip" in before
    assert fixture.rows(CompletionIntentRow)[0]["outcome_code"] is None
    assert any(a["outcome"] == "running" for a in fixture.rows(TaskAttemptRow))
    fixture.engine.dispose()
    recovered = fixture.queue.recover_expired(now=NOW + timedelta(seconds=100))
    assert recovered.requeued == 1
    work, _ = package(fixture, at=NOW + timedelta(seconds=101))
    assert work.delivery_id == bound and work.version == 1
    after = {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert len(fixture.rows(DeliveryRow)) == 1
    attempts = fixture.rows(TaskAttemptRow)
    assert any(a["outcome"] == "lost_lease" for a in attempts)
    delivery_task = next(t for t in fixture.rows(TaskRow) if t["target_id"] == bound)
    assert delivery_task["retry_count"] == 1
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.PROCESSED
    assert next(t for t in fixture.rows(TaskRow) if t["target_id"] == bound)["retry_count"] == 1


def test_shutdown_before_completion_commit_restarts_with_same_task(fixture):
    goal, _ = master(fixture)
    lease = fixture.queue.claim_completion(worker_id="stopped", now=NOW + timedelta(seconds=60))
    assert lease is not None
    before = fixture.rows(CompletionIntentRow)[0]
    fixture.engine.dispose()
    assert fixture.rows(CompletionIntentRow)[0] == before
    fixture.queue.recover_expired(now=NOW + timedelta(seconds=100))
    assert observe(fixture, NOW + timedelta(seconds=101)) == ReconciliationResult.DEFERRED
    bound = fixture.rows(CompletionIntentRow)[0]
    assert bound["delivery_id"] and bound["delivery_action_key"]
    assert fixture.task(goal)["id"] == lease.task_id
    assert fixture.task(goal)["retry_count"] == 1
    assert len(fixture.rows(DeliveryRow)) == 1
    assert fixture.repository.reconcile_completion(lease, now=NOW + timedelta(seconds=102)) == (
        ReconciliationResult.LOST_LEASE
    )


def test_newer_project_delivery_never_replaces_bound_id(fixture):
    goal, _ = master(fixture)
    observe(fixture)
    bound = fixture.rows(CompletionIntentRow)[0]["delivery_id"]
    later = SqlAlchemyDeliveryRepository(fixture.engine).enqueue_delivery(
        goal.project_id,
        DeliveryRequest(),
        max_retries=1,
    )
    assert later.delivery_id != bound and later.version == 2
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.DEFERRED
    assert fixture.rows(CompletionIntentRow)[0]["delivery_id"] == bound
    assert len(fixture.rows(DeliveryRow)) == 2


def test_non_zip_goal_requires_manifest_and_media_only(fixture):
    goal, _ = master(fixture, include_zip=False)
    observe(fixture)
    work, persistence = package(fixture)
    assert not work.include_zip and persistence.zip_asset_id is None
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.PROCESSED
    assert list((fixture.root / "data" / goal.project_id).rglob("*.zip")) == []


@pytest.mark.parametrize("drift", ["generation", "run", "revision", "decision", "membership"])
def test_bound_checkpoint_drift_never_rebinds(fixture, drift):
    goal, _ = master(fixture)
    observe(fixture)
    saved = fixture.rows(CompletionIntentRow)[0]
    selected = checkpoint(fixture).selected[0]
    with begin_immediate(fixture.engine) as connection:
        if drift in {"generation", "run"}:
            connection.execute(
                update(ProjectRow)
                .where(ProjectRow.id == goal.project_id)
                .values(
                    **(
                        {"current_generation": 2}
                        if drift == "generation"
                        else {"current_pipeline_run_id": None}
                    )
                )
            )
        elif drift == "decision":
            connection.execute(
                insert(ReviewDecisionRow).values(
                    id=new_id(),
                    candidate_clip_id=selected.clip_id,
                    edit_plan_revision_id=selected.edit_plan_revision_id,
                    status="approved",
                    decided_at=NOW + timedelta(seconds=90),
                )
            )
        else:
            connection.execute(
                update(CandidateClipRow)
                .where(CandidateClipRow.id == selected.clip_id)
                .values(
                    **(
                        {"current_revision": 2}
                        if drift == "revision"
                        else {"selected_for_review": False}
                    )
                )
            )
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.NEEDS_ACTION
    current = fixture.rows(CompletionIntentRow)[0]
    for field in ("delivery_id", "delivery_action_key", "selection_checkpoint_json"):
        assert current[field] == saved[field]
    assert current["blocking_code"] in {"GENERATION_CHANGED", "SELECTION_CHANGED"}
    assert len(fixture.rows(DeliveryRow)) == 1


def test_missing_checkpoint_cannot_reselect_an_already_bound_intent(fixture):
    goal, _ = master(fixture)
    observe(fixture)
    saved = fixture.rows(CompletionIntentRow)[0]
    with begin_immediate(fixture.engine) as connection:
        connection.execute(
            update(CompletionIntentRow)
            .where(CompletionIntentRow.id == goal.intent_id)
            .values(selection_checkpoint_json=None)
        )
    assert observe(fixture, NOW + timedelta(seconds=120)) == ReconciliationResult.NEEDS_ACTION
    current = fixture.rows(CompletionIntentRow)[0]
    assert current["selection_checkpoint_json"] is None
    assert current["delivery_id"] == saved["delivery_id"]
    assert current["delivery_action_key"] == saved["delivery_action_key"]
    assert current["blocking_code"] == "SELECTION_CHANGED"
    assert len(fixture.rows(DeliveryRow)) == 1


@pytest.mark.parametrize("race", ["revoked", "generation", "file", "asset", "expired", "shutdown"])
def test_inspection_releases_writer_and_refences_authority_files_and_lease(
    fixture, monkeypatch, race
):
    goal, _ = master(fixture)
    observe(fixture)
    work, persistence = package(fixture)
    before = fixture.rows(CompletionIntentRow)[0]
    clock = NOW + timedelta(seconds=120)
    original = delivery_module.DeliveryInspectionRequired.inspect

    def inspect_then_race(self):
        nonlocal clock
        original(self)
        if race in {"revoked", "generation", "asset"}:
            # This independent writer must be able to commit during inspection.
            with begin_immediate(fixture.engine) as connection:
                if race == "revoked":
                    revoke(connection, goal, "removed")
                elif race == "generation":
                    connection.execute(
                        update(ProjectRow)
                        .where(ProjectRow.id == goal.project_id)
                        .values(current_generation=2)
                    )
                else:
                    connection.execute(
                        update(AssetRow)
                        .where(AssetRow.id == persistence.manifest_asset_id)
                        .values(sha256="0" * 64)
                    )
        elif race == "file":
            path = (
                fixture.root
                / "data"
                / goal.project_id
                / "deliveries"
                / f"v{work.version:03d}"
                / "manifest.json"
            )
            path.write_bytes(b"changed after hashing")
        elif race == "expired":
            clock += timedelta(seconds=31)
        else:
            raise KeyboardInterrupt("simulated process shutdown during inspection")

    monkeypatch.setattr(delivery_module.DeliveryInspectionRequired, "inspect", inspect_then_race)
    monkeypatch.setattr(module, "_instant", lambda _: clock)
    if race == "shutdown":
        with pytest.raises(KeyboardInterrupt):
            observe(fixture, clock)
    else:
        assert observe(fixture, clock) == (
            ReconciliationResult.LOST_LEASE
            if race == "expired"
            else ReconciliationResult.NEEDS_ACTION
        )
    current = fixture.rows(CompletionIntentRow)[0]
    assert current["delivery_id"] == before["delivery_id"] and current["outcome_code"] is None
    if race in {"shutdown", "expired"}:
        assert current == before
        assert fixture.task(goal)["status"] == "running"


def test_inspection_renews_across_multiple_lease_periods_without_retry(fixture, monkeypatch):
    goal, _ = master(fixture)
    observe(fixture)
    package(fixture)
    bound = fixture.rows(CompletionIntentRow)[0]["delivery_id"]
    clock = NOW + timedelta(seconds=120)
    ticks, renewed = Semaphore(0), Semaphore(0)
    monitors = []

    class DrivenMonitor(LeaseMonitor):
        # Only scheduling is controlled: renewals use the real SQLite heartbeat
        # on the actual background thread, updating both persisted lease rows.
        def _run(self):
            monitors.append(self)
            while not self._stop.is_set():
                if ticks.acquire(timeout=0.01):
                    self.refresh()
                    renewed.release()

    original = delivery_module.DeliveryInspectionRequired.inspect

    def slow_inspection(self):
        nonlocal clock
        for _ in range(6):
            clock += timedelta(seconds=20)
            ticks.release()
            assert renewed.acquire(timeout=5)
            task = fixture.task(goal)
            assert task["lease_expires_at"] == clock + timedelta(seconds=30)
            attempt = next(
                a
                for a in fixture.rows(TaskAttemptRow)
                if a["task_id"] == task["id"] and a["outcome"] == "running"
            )
            assert attempt["lease_expires_at"] == task["lease_expires_at"]
            recovered = fixture.queue.recover_expired(now=clock)
            assert recovered.requeued == recovered.failed == recovered.cancelled == 0
        original(self)

    monkeypatch.setattr(module, "LeaseMonitor", DrivenMonitor)
    monkeypatch.setattr(module, "_instant", lambda _: clock)
    monkeypatch.setattr(delivery_module.DeliveryInspectionRequired, "inspect", slow_inspection)
    assert observe(fixture, clock) == ReconciliationResult.PROCESSED
    task = fixture.task(goal)
    assert task["retry_count"] == 0 and task["attempt_count"] == 3
    assert [a["outcome"] for a in fixture.rows(TaskAttemptRow) if a["task_id"] == task["id"]] == [
        "deferred",
        "deferred",
        "succeeded",
    ]
    assert fixture.rows(CompletionIntentRow)[0]["delivery_id"] == bound
    assert len(fixture.rows(DeliveryRow)) == 1
    assert monitors and all(not monitor._thread.is_alive() for monitor in monitors)


@pytest.mark.parametrize("stage", ["file", "zip"])
@pytest.mark.parametrize("reason", ["cancel", "lost"])
def test_inspection_stops_streaming_on_cancel_or_lease_loss(fixture, monkeypatch, stage, reason):
    goal, _ = master(fixture)
    observe(fixture)
    package(fixture)
    before = fixture.rows(CompletionIntentRow)[0]
    interrupted = []
    monitor_instances = []

    class RecordingMonitor(LeaseMonitor):
        def start(self):
            monitor_instances.append(self)
            super().start()

    def interrupt():
        if interrupted:
            return
        interrupted.append(True)
        if reason == "cancel":
            fixture.service.cancel(
                goal.intent_id, actor_user_id=OWNER, expected_version=before["version"]
            )
        else:
            with begin_immediate(fixture.engine) as connection:
                connection.execute(
                    update(TaskRow)
                    .where(TaskRow.target_id == goal.intent_id)
                    .values(lease_token="f" * 64)
                )
        monitor_instances[0].refresh()

    original_hash = PinnedRegularFile.sha256
    original_read = zipfile.ZipExtFile.read
    reads = []

    def hash_file(self, *args, **kwargs):
        if kwargs.get("cancel_requested") is not None:
            interrupt()
        return original_hash(self, *args, **kwargs)

    def read_zip(self, *args, **kwargs):
        reads.append(True)
        interrupt()
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(module, "LeaseMonitor", RecordingMonitor)
    if stage == "file":
        monkeypatch.setattr(PinnedRegularFile, "sha256", hash_file)
    else:
        monkeypatch.setattr(zipfile.ZipExtFile, "read", read_zip)
    assert observe(fixture, at=NOW + timedelta(seconds=120)) == (
        ReconciliationResult.CANCELLED if reason == "cancel" else ReconciliationResult.LOST_LEASE
    )
    assert interrupted
    if stage == "zip":
        assert len(reads) == 1  # Stop before decompressing the next bounded block.
    current = fixture.rows(CompletionIntentRow)[0]
    assert current["delivery_id"] == before["delivery_id"]
    assert current["blocking_code"] is None
    assert current["outcome_code"] == ("cancelled" if reason == "cancel" else None)
    assert all(not monitor._thread.is_alive() for monitor in monitor_instances)
