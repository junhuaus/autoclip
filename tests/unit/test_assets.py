from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.engine import Engine

import liveclip.db.assets as assets_module
from liveclip.application.pipeline import LeaseIdentity
from liveclip.db.assets import AssetReservation, AssetReservationError, SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import AssetRow, PipelineRunRow, ProjectRow, TaskAttemptRow
from liveclip.db.task_queue import CompletionResult, SQLiteTaskQueue, TaskLease, TaskSpec
from liveclip.domain.state_transitions import (
    AssetStatus,
    AttemptOutcome,
    FailureClass,
    PipelineRunStatus,
    ResourceClass,
    TaskKind,
    TaskStatus,
)
from liveclip.media.secure_files import SecureFileError, directory_identity_no_follow
from liveclip.services.janitor import cleanup_terminal_attempt_worktrees

PROJECT_ID = "p" * 32
RUN_ID = "r" * 32
INPUT_FINGERPRINT = "a" * 64
RELATIVE_PATH = "renders/proxy/clip-01.mp4"


@dataclass(frozen=True, slots=True)
class AssetContext:
    engine: Engine
    queue: SQLiteTaskQueue
    store: SqlAlchemyAssetStore
    project_dir: Path
    claim_time: datetime


@pytest.fixture
def asset_context(tmp_path: Path) -> Iterator[AssetContext]:
    engine = create_sqlite_engine(tmp_path / "state" / "liveclip.sqlite3", busy_timeout_ms=250)
    Base.metadata.create_all(engine)
    claim_time = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=PROJECT_ID,
                name="Asset project",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                current_pipeline_run_id=RUN_ID,
                revision_epoch=0,
                created_at=claim_time,
                updated_at=claim_time,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=RUN_ID,
                project_id=PROJECT_ID,
                generation=1,
                status=PipelineRunStatus.RUNNING.value,
                config_json={"provider": "mock"},
                config_fingerprint="c" * 64,
                progress=0,
                manual_retry_count=0,
                created_at=claim_time,
                updated_at=claim_time,
            )
        )
    project_dir = tmp_path / "projects" / PROJECT_ID
    project_dir.mkdir(parents=True)
    try:
        yield AssetContext(
            engine=engine,
            queue=SQLiteTaskQueue(
                engine,
                lease_seconds=60,
                data_dir=tmp_path / "projects",
            ),
            store=SqlAlchemyAssetStore(engine),
            project_dir=project_dir,
            claim_time=claim_time,
        )
    finally:
        engine.dispose(close=True)


def _claim(
    context: AssetContext,
    *,
    worker_id: str = "worker-a",
    operation_key: str = "render:clip-01:r001:proxy",
    target_id: str = "c" * 32,
) -> TaskLease:
    context.queue.enqueue(
        TaskSpec(
            kind=TaskKind.RENDER,
            target_id=target_id,
            operation_key=operation_key,
            input_fingerprint="d" * 64,
            pipeline_run_id=RUN_ID,
            resource_class=ResourceClass.HEAVY,
            expected_generation=1,
            expected_revision=1,
            expected_revision_epoch=0,
        ),
        now=context.claim_time,
    )
    lease = context.queue.claim(worker_id=worker_id, now=context.claim_time)
    assert lease is not None
    return lease


def _identity(lease: TaskLease) -> LeaseIdentity:
    return LeaseIdentity(
        task_id=lease.task_id,
        worker_id=lease.worker_id,
        lease_token=lease.lease_token,
    )


def _reserve(
    context: AssetContext,
    lease: TaskLease,
    *,
    relative_path: str = RELATIVE_PATH,
    input_fingerprint: str = INPUT_FINGERPRINT,
    generation: int = 1,
) -> AssetReservation:
    return context.store.reserve(
        _identity(lease),
        project_id=PROJECT_ID,
        kind="review_proxy",
        relative_path=relative_path,
        mime_type="video/mp4",
        input_fingerprint=input_fingerprint,
        generation=generation,
        edit_plan_revision=1,
        revision_epoch=0,
    )


def _write_asset(context: AssetContext, content: bytes = b"original-bytes") -> Path:
    output = context.project_dir / Path(*RELATIVE_PATH.split("/"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    return output


@pytest.mark.parametrize(
    "relative_path",
    ["../escape.mp4", "renders/../escape.mp4", "renders\\escape.mp4"],
)
def test_reserve_rejects_traversal_and_backslashes(
    asset_context: AssetContext,
    relative_path: str,
) -> None:
    lease = _claim(asset_context)

    with pytest.raises(ValueError, match="path"):
        _reserve(asset_context, lease, relative_path=relative_path)


def test_reserve_creates_pending_asset_bound_to_current_attempt(
    asset_context: AssetContext,
) -> None:
    lease = _claim(asset_context)

    reservation = _reserve(asset_context, lease)

    assert reservation.status == AssetStatus.PENDING
    assert reservation.relative_path == RELATIVE_PATH
    assert reservation.sha256 is None and reservation.size_bytes is None
    with asset_context.engine.connect() as connection:
        row = connection.execute(
            select(
                AssetRow.status,
                AssetRow.producer_attempt_id,
                AssetRow.generation,
                AssetRow.edit_plan_revision,
            ).where(AssetRow.id == reservation.asset_id)
        ).one()
        attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == lease.lease_token)
        )
    assert row == (AssetStatus.PENDING.value, attempt_id, 1, 1)


def test_current_lease_commit_and_committed_retry_are_idempotent(
    asset_context: AssetContext,
) -> None:
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease)
    content = b"validated-video-bytes"
    _write_asset(asset_context, content)

    committed = asset_context.store.commit(
        _identity(lease),
        reservation,
        project_dir=asset_context.project_dir,
        validation={"decode": "passed"},
    )

    assert committed.status == AssetStatus.COMMITTED
    assert committed.sha256 == hashlib.sha256(content).hexdigest()
    assert committed.size_bytes == len(content)
    repeated = asset_context.store.commit(
        _identity(lease),
        reservation,
        project_dir=asset_context.project_dir,
        validation={"decode": "passed"},
    )
    assert repeated == committed
    with asset_context.engine.connect() as connection:
        row = connection.execute(
            select(AssetRow.status, AssetRow.validation_json, AssetRow.sha256).where(
                AssetRow.id == reservation.asset_id
            )
        ).one()
        count = connection.scalar(select(func.count()).select_from(AssetRow))
    assert row == (AssetStatus.COMMITTED.value, {"decode": "passed"}, committed.sha256)
    assert count == 1


def test_commit_rejects_bytes_that_differ_from_validated_render_hash(
    asset_context: AssetContext,
) -> None:
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease)
    _write_asset(asset_context, b"replacement-after-quality-validation")

    with pytest.raises(AssetReservationError, match="validated artifact"):
        asset_context.store.commit(
            _identity(lease),
            reservation,
            project_dir=asset_context.project_dir,
            validation={"decode": "passed"},
            expected_sha256=hashlib.sha256(b"original-validated-render").hexdigest(),
        )

    with asset_context.engine.connect() as connection:
        row = connection.execute(
            select(AssetRow.status, AssetRow.sha256, AssetRow.validation_json).where(
                AssetRow.id == reservation.asset_id
            )
        ).one()
    assert row == (AssetStatus.PENDING.value, None, None)


def test_committed_asset_tampering_is_rejected_even_when_size_is_unchanged(
    asset_context: AssetContext,
) -> None:
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease)
    output = _write_asset(asset_context, b"original-bytes")
    asset_context.store.commit(
        _identity(lease),
        reservation,
        project_dir=asset_context.project_dir,
        validation={"decode": "passed"},
    )
    output.write_bytes(b"tampered-bytes")

    with pytest.raises(AssetReservationError, match="bytes changed"):
        asset_context.store.commit(
            _identity(lease),
            reservation,
            project_dir=asset_context.project_dir,
            validation={"decode": "passed"},
        )


def test_pending_commit_rejects_stale_lease_token(asset_context: AssetContext) -> None:
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease)
    _write_asset(asset_context)
    stale = LeaseIdentity(
        task_id=lease.task_id,
        worker_id=lease.worker_id,
        lease_token="stale-token",
    )

    with pytest.raises(AssetReservationError, match="lost its task lease"):
        asset_context.store.commit(
            stale,
            reservation,
            project_dir=asset_context.project_dir,
            validation={"decode": "passed"},
        )


def test_pending_commit_rejects_cancellation(asset_context: AssetContext) -> None:
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease)
    _write_asset(asset_context)
    asset_context.queue.request_cancel(lease.task_id, now=context_time_after_claim(asset_context))

    with pytest.raises(AssetReservationError, match="lost its task lease"):
        asset_context.store.commit(
            _identity(lease),
            reservation,
            project_dir=asset_context.project_dir,
            validation={"decode": "passed"},
        )


def test_pending_commit_rejects_outdated_project_generation(
    asset_context: AssetContext,
) -> None:
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease)
    _write_asset(asset_context)
    with asset_context.engine.begin() as connection:
        connection.execute(
            update(ProjectRow).where(ProjectRow.id == PROJECT_ID).values(current_generation=2)
        )

    with pytest.raises(AssetReservationError, match="generation"):
        asset_context.store.commit(
            _identity(lease),
            reservation,
            project_dir=asset_context.project_dir,
            validation={"decode": "passed"},
        )


def test_existing_asset_path_rejects_generation_or_revision_reuse(
    asset_context: AssetContext,
) -> None:
    lease = _claim(asset_context)
    _reserve(asset_context, lease)

    with pytest.raises(AssetReservationError, match="revision"):
        asset_context.store.reserve(
            _identity(lease),
            project_id=PROJECT_ID,
            kind="review_proxy",
            relative_path=RELATIVE_PATH,
            mime_type="video/mp4",
            input_fingerprint=INPUT_FINGERPRINT,
            generation=1,
            edit_plan_revision=2,
            revision_epoch=0,
        )
    with pytest.raises(AssetReservationError, match="generation"):
        asset_context.store.reserve(
            _identity(lease),
            project_id=PROJECT_ID,
            kind="review_proxy",
            relative_path=RELATIVE_PATH,
            mime_type="video/mp4",
            input_fingerprint=INPUT_FINGERPRINT,
            generation=None,
            edit_plan_revision=1,
            revision_epoch=0,
        )


def test_lease_cannot_reserve_or_commit_another_projects_asset(
    asset_context: AssetContext,
) -> None:
    other_project_id = "q" * 32
    other_run_id = "s" * 32
    now = asset_context.claim_time
    with asset_context.engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=other_project_id,
                name="Other project",
                source_request_path="/allowed/other.mp4",
                current_generation=1,
                current_pipeline_run_id=other_run_id,
                revision_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=other_run_id,
                project_id=other_project_id,
                generation=1,
                status=PipelineRunStatus.RUNNING.value,
                config_json={"provider": "mock"},
                config_fingerprint="e" * 64,
                progress=0,
                manual_retry_count=0,
                created_at=now,
                updated_at=now,
            )
        )
    lease = _claim(asset_context)

    with pytest.raises(AssetReservationError, match="project"):
        asset_context.store.reserve(
            _identity(lease),
            project_id=other_project_id,
            kind="review_proxy",
            relative_path=RELATIVE_PATH,
            mime_type="video/mp4",
            input_fingerprint=INPUT_FINGERPRINT,
            generation=1,
            edit_plan_revision=1,
            revision_epoch=0,
        )

    with asset_context.engine.connect() as connection:
        attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == lease.lease_token)
        )
    forged_id = "f" * 32
    with asset_context.engine.begin() as connection:
        connection.execute(
            insert(AssetRow).values(
                id=forged_id,
                project_id=other_project_id,
                producer_attempt_id=attempt_id,
                status=AssetStatus.PENDING.value,
                kind="review_proxy",
                relative_path=RELATIVE_PATH,
                mime_type="video/mp4",
                input_fingerprint=INPUT_FINGERPRINT,
                generation=1,
                edit_plan_revision=1,
                revision_epoch=0,
                created_at=now,
            )
        )
    other_dir = asset_context.project_dir.parent / other_project_id
    output = other_dir / Path(*RELATIVE_PATH.split("/"))
    output.parent.mkdir(parents=True)
    output.write_bytes(b"forged-cross-project")
    forged = AssetReservation(
        asset_id=forged_id,
        status=AssetStatus.PENDING,
        relative_path=RELATIVE_PATH,
        sha256=None,
        size_bytes=None,
    )

    with pytest.raises(AssetReservationError, match="project"):
        asset_context.store.commit(
            _identity(lease),
            forged,
            project_dir=other_dir,
            validation={"decode": "passed"},
        )


def test_pending_asset_cannot_be_adopted_by_a_different_task(
    asset_context: AssetContext,
) -> None:
    old_lease = _claim(asset_context)
    original = _reserve(asset_context, old_lease)
    failed = asset_context.queue.fail(
        old_lease,
        failure_class=FailureClass.DETERMINISTIC,
        error_code="TEST_FAILURE",
        safe_message="Test task stopped before asset publication",
        now=context_time_after_claim(asset_context),
    )
    assert failed == TaskStatus.FAILED
    new_lease = _claim(
        asset_context,
        worker_id="worker-b",
        operation_key="render:clip-01:r001:proxy:other-task",
        target_id="d" * 32,
    )

    with pytest.raises(AssetReservationError, match="different logical task"):
        _reserve(asset_context, new_lease)

    with asset_context.engine.connect() as connection:
        assert (
            connection.scalar(
                select(AssetRow.producer_attempt_id).where(AssetRow.id == original.asset_id)
            )
            is not None
        )


def test_lost_attempt_pending_asset_is_adopted_by_new_claim(
    asset_context: AssetContext,
) -> None:
    old_lease = _claim(asset_context)
    original = _reserve(asset_context, old_lease)
    with asset_context.engine.connect() as connection:
        old_attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == old_lease.lease_token)
        )

    recovery = asset_context.queue.recover_expired(now=old_lease.lease_expires_at)
    assert recovery.requeued == 1
    new_lease = asset_context.queue.claim(
        worker_id="worker-b",
        now=old_lease.lease_expires_at,
    )
    assert new_lease is not None
    adopted = _reserve(asset_context, new_lease)

    assert adopted.asset_id == original.asset_id
    assert adopted.status == AssetStatus.PENDING
    with asset_context.engine.connect() as connection:
        new_attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == new_lease.lease_token)
        )
        producer_attempt_id = connection.scalar(
            select(AssetRow.producer_attempt_id).where(AssetRow.id == original.asset_id)
        )
        old_outcome = connection.scalar(
            select(TaskAttemptRow.outcome).where(TaskAttemptRow.id == old_attempt_id)
        )
    assert producer_attempt_id == new_attempt_id
    assert producer_attempt_id != old_attempt_id
    assert old_outcome == AttemptOutcome.LOST_LEASE.value

    _write_asset(asset_context)
    committed = asset_context.store.commit(
        _identity(new_lease),
        adopted,
        project_dir=asset_context.project_dir,
        validation={"decode": "passed"},
    )
    assert committed.status == AssetStatus.COMMITTED


def test_lost_attempt_committed_asset_is_adopted_and_old_attempt_cannot_invalidate_it(
    asset_context: AssetContext,
) -> None:
    old_lease = _claim(asset_context)
    original = _reserve(asset_context, old_lease)
    content = b"published-before-lease-handoff"
    _write_asset(asset_context, content)
    committed = asset_context.store.commit(
        _identity(old_lease),
        original,
        project_dir=asset_context.project_dir,
        validation={"decode": "passed"},
    )
    with asset_context.engine.connect() as connection:
        old_attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == old_lease.lease_token)
        )

    recovery = asset_context.queue.recover_expired(now=old_lease.lease_expires_at)
    assert recovery.requeued == 1
    new_lease = asset_context.queue.claim(
        worker_id="worker-b",
        now=old_lease.lease_expires_at,
    )
    assert new_lease is not None
    adopted = _reserve(asset_context, new_lease)

    assert adopted == committed
    with asset_context.engine.connect() as connection:
        new_attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == new_lease.lease_token)
        )
        producer_attempt_id = connection.scalar(
            select(AssetRow.producer_attempt_id).where(AssetRow.id == original.asset_id)
        )
    assert producer_attempt_id == new_attempt_id
    assert producer_attempt_id != old_attempt_id

    asset_context.store.invalidate_attempt_assets(
        _identity(old_lease),
        (original.asset_id,),
        reason="stale runner attempted withdrawal",
    )
    with asset_context.engine.connect() as connection:
        row = connection.execute(
            select(AssetRow.status, AssetRow.producer_attempt_id).where(
                AssetRow.id == original.asset_id
            )
        ).one()
    assert row == (AssetStatus.COMMITTED.value, new_attempt_id)
    assert (
        asset_context.store.commit(
            _identity(new_lease),
            adopted,
            project_dir=asset_context.project_dir,
            validation={"decode": "passed"},
        )
        == committed
    )


def test_stale_attempt_cannot_withdraw_package_adopted_by_successor(
    asset_context: AssetContext,
) -> None:
    relative_directory = "edit-packages/v001"
    relative_path = f"{relative_directory}/manifest.json"
    old_lease = _claim(asset_context)
    original = _reserve(asset_context, old_lease, relative_path=relative_path)
    package_dir = asset_context.project_dir / relative_directory
    package_dir.mkdir(parents=True)
    manifest = package_dir / "manifest.json"
    manifest.write_bytes(b'{"schema_version":"test"}\n')
    committed = asset_context.store.commit(
        _identity(old_lease),
        original,
        project_dir=asset_context.project_dir,
        validation={"schema_version": "test"},
    )
    package_identity = directory_identity_no_follow(package_dir)

    recovery = asset_context.queue.recover_expired(now=old_lease.lease_expires_at)
    assert recovery.requeued == 1
    new_lease = asset_context.queue.claim(
        worker_id="worker-b",
        now=old_lease.lease_expires_at,
    )
    assert new_lease is not None
    adopted = _reserve(asset_context, new_lease, relative_path=relative_path)
    assert adopted == committed
    assert (
        asset_context.queue.complete(
            new_lease,
            now=old_lease.lease_expires_at + timedelta(seconds=1),
        )
        == CompletionResult.COMPLETED
    )

    withdrawn = asset_context.store.withdraw_attempt_publication(
        _identity(old_lease),
        (original.asset_id,),
        project_dir=asset_context.project_dir,
        relative_directory=relative_directory,
        expected_identity=package_identity,
        reason="stale runner attempted withdrawal",
    )

    assert withdrawn is False
    assert manifest.read_bytes() == b'{"schema_version":"test"}\n'
    with asset_context.engine.connect() as connection:
        new_attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == new_lease.lease_token)
        )
        row = connection.execute(
            select(AssetRow.status, AssetRow.producer_attempt_id).where(
                AssetRow.id == original.asset_id
            )
        ).one()
    assert row == (AssetStatus.COMMITTED.value, new_attempt_id)


def test_current_attempt_withdrawal_quarantines_package_before_invalidating_asset(
    asset_context: AssetContext,
) -> None:
    relative_directory = "edit-packages/v001"
    relative_path = f"{relative_directory}/manifest.json"
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease, relative_path=relative_path)
    package_dir = asset_context.project_dir / relative_directory
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.json").write_bytes(b'{"schema_version":"test"}\n')
    committed = asset_context.store.commit(
        _identity(lease),
        reservation,
        project_dir=asset_context.project_dir,
        validation={"schema_version": "test"},
    )

    assert asset_context.store.withdraw_attempt_publication(
        _identity(lease),
        (committed.asset_id,),
        project_dir=asset_context.project_dir,
        relative_directory=relative_directory,
        expected_identity=directory_identity_no_follow(package_dir),
        reason="current package completion fence failed",
    )

    assert not package_dir.exists()
    with asset_context.engine.connect() as connection:
        row = connection.execute(
            select(AssetRow.status, AssetRow.validation_json).where(
                AssetRow.id == committed.asset_id
            )
        ).one()
    assert row == (
        AssetStatus.INVALID.value,
        {
            "publication_withdrawn": True,
            "reason": "current package completion fence failed",
        },
    )


def test_withdrawal_restores_exact_package_inode_when_asset_update_fails(
    asset_context: AssetContext,
) -> None:
    relative_directory = "edit-packages/v001"
    relative_path = f"{relative_directory}/manifest.json"
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease, relative_path=relative_path)
    package_dir = asset_context.project_dir / relative_directory
    package_dir.mkdir(parents=True)
    manifest = package_dir / "manifest.json"
    manifest.write_bytes(b'{"schema_version":"test"}\n')
    committed = asset_context.store.commit(
        _identity(lease),
        reservation,
        project_dir=asset_context.project_dir,
        validation={"schema_version": "test"},
    )
    original_identity = directory_identity_no_follow(package_dir)

    def fail_invalidation(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.lstrip().startswith("UPDATE assets SET status="):
            raise RuntimeError("simulated Asset update failure")

    event.listen(asset_context.engine, "before_cursor_execute", fail_invalidation)
    try:
        with pytest.raises(RuntimeError, match="Asset update failure"):
            asset_context.store.withdraw_attempt_publication(
                _identity(lease),
                (committed.asset_id,),
                project_dir=asset_context.project_dir,
                relative_directory=relative_directory,
                expected_identity=original_identity,
                reason="completion fence failed",
            )
    finally:
        event.remove(asset_context.engine, "before_cursor_execute", fail_invalidation)

    assert directory_identity_no_follow(package_dir) == original_identity
    assert manifest.read_bytes() == b'{"schema_version":"test"}\n'
    with asset_context.engine.connect() as connection:
        row = connection.execute(
            select(AssetRow.status, AssetRow.producer_attempt_id).where(
                AssetRow.id == committed.asset_id
            )
        ).one()
        attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == lease.lease_token)
        )
    assert row == (AssetStatus.COMMITTED.value, attempt_id)


def test_deferred_withdrawal_quarantine_is_removed_by_attempt_janitor(
    asset_context: AssetContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative_directory = "edit-packages/v001"
    relative_path = f"{relative_directory}/manifest.json"
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease, relative_path=relative_path)
    package_dir = asset_context.project_dir / relative_directory
    package_dir.mkdir(parents=True)
    (package_dir / "manifest.json").write_bytes(b'{"schema_version":"test"}\n')
    committed = asset_context.store.commit(
        _identity(lease),
        reservation,
        project_dir=asset_context.project_dir,
        validation={"schema_version": "test"},
    )
    original_remove = assets_module.remove_tree_no_follow

    def defer_cleanup(*_args: object, **_kwargs: object) -> bool:
        raise SecureFileError("simulated deferred recursive cleanup")

    monkeypatch.setattr(assets_module, "remove_tree_no_follow", defer_cleanup)
    assert asset_context.store.withdraw_attempt_publication(
        _identity(lease),
        (committed.asset_id,),
        project_dir=asset_context.project_dir,
        relative_directory=relative_directory,
        expected_identity=directory_identity_no_follow(package_dir),
        reason="completion fence failed",
    )
    monkeypatch.setattr(assets_module, "remove_tree_no_follow", original_remove)

    attempt_root = asset_context.project_dir / ".attempts" / lease.task_id / lease.lease_token
    assert not package_dir.exists()
    assert tuple((attempt_root / "withdrawals").iterdir())
    assert (
        asset_context.queue.fail(
            lease,
            failure_class=FailureClass.DETERMINISTIC,
            error_code="PACKAGE_COMPLETION_FAILED",
            safe_message="The package completion fence failed",
            now=context_time_after_claim(asset_context),
        )
        == TaskStatus.FAILED
    )

    report = cleanup_terminal_attempt_worktrees(
        asset_context.engine,
        data_dir=asset_context.project_dir.parent,
    )

    assert report.failed == 0
    assert report.cleaned == 1
    assert not attempt_root.exists()


def test_withdrawn_asset_is_reset_and_reowned_by_same_task_retry(
    asset_context: AssetContext,
) -> None:
    first_lease = _claim(asset_context)
    original = _reserve(asset_context, first_lease)
    content = b"published-then-withdrawn"
    _write_asset(asset_context, content)
    committed = asset_context.store.commit(
        _identity(first_lease),
        original,
        project_dir=asset_context.project_dir,
        validation={"decode": "passed"},
    )
    asset_context.store.invalidate_attempt_assets(
        _identity(first_lease),
        (committed.asset_id,),
        reason="package publication was withdrawn",
    )
    retry_at = context_time_after_claim(asset_context)
    assert (
        asset_context.queue.fail(
            first_lease,
            failure_class=FailureClass.TRANSIENT,
            error_code="PACKAGE_COMMIT_TEMPORARY",
            safe_message="Retry the package commit",
            retry_delay_ms=0,
            now=retry_at,
        )
        == TaskStatus.QUEUED
    )
    retry_lease = asset_context.queue.claim(worker_id="worker-b", now=retry_at)
    assert retry_lease is not None

    retried = _reserve(asset_context, retry_lease)
    assert retried == AssetReservation(
        asset_id=original.asset_id,
        status=AssetStatus.PENDING,
        relative_path=RELATIVE_PATH,
        sha256=None,
        size_bytes=None,
    )
    with asset_context.engine.connect() as connection:
        producer_attempt_id = connection.scalar(
            select(AssetRow.producer_attempt_id).where(AssetRow.id == original.asset_id)
        )
        retry_attempt_id = connection.scalar(
            select(TaskAttemptRow.id).where(TaskAttemptRow.lease_token == retry_lease.lease_token)
        )
    assert producer_attempt_id == retry_attempt_id
    recommitted = asset_context.store.commit(
        _identity(retry_lease),
        retried,
        project_dir=asset_context.project_dir,
        validation={"decode": "passed"},
    )
    assert recommitted.status == AssetStatus.COMMITTED
    assert recommitted.sha256 == hashlib.sha256(content).hexdigest()


def test_same_path_with_different_input_fingerprint_conflicts(
    asset_context: AssetContext,
) -> None:
    lease = _claim(asset_context)
    reservation = _reserve(asset_context, lease)

    with pytest.raises(AssetReservationError, match="different input"):
        _reserve(asset_context, lease, input_fingerprint="b" * 64)

    with asset_context.engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(AssetRow))
    assert reservation.status == AssetStatus.PENDING
    assert count == 1


def context_time_after_claim(context: AssetContext) -> datetime:
    return context.claim_time + timedelta(seconds=1)
