from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel
from sqlalchemy import CheckConstraint, delete, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError

from liveclip.application.pipeline import (
    LeaseIdentity,
    PipelineRunConfigV10,
    PipelineRunConfigV12,
    PipelineService,
    load_persisted_pipeline_config,
)
from liveclip.application.semantic_units import SemanticUnitConflict, SemanticUnitIdentity
from liveclip.application.stage_execution import StageMutationFence
from liveclip.bootstrap import pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.db.assets import SqlAlchemyAssetStore
from liveclip.db.base import Base
from liveclip.db.engine import create_sqlite_engine
from liveclip.db.models import (
    ApiUsageRow,
    AssetRow,
    PipelineRunRow,
    SemanticUnitInvocationRow,
    StageRunRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
from liveclip.db.semantic_units import SqlAlchemySemanticInvocationStore
from liveclip.db.stage_store import SqlAlchemyStageStateStore, StageDataConflict
from liveclip.db.task_queue import SQLiteTaskQueue
from liveclip.media.artifacts import project_directory
from liveclip.pipeline.semantic_executor import SemanticUnitRequest
from liveclip.pipeline.semantic_unit_runtime import (
    SemanticRecoveryError,
    run_persisted_semantic_units,
)
from liveclip.providers.llm.structured import StructuredCallResult, StructuredProviderError
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus


class Answer(BaseModel):
    value: str


class Provider:
    provider_name = "mock"
    model_name = "fixture"
    contract_version = "fixture-v1"
    prompt_version = "fixture-v1"
    prompt_sha256 = "b" * 64

    def __init__(self, *, invalid=False, transient=False):
        self.calls = []
        self.invalid = invalid
        self.transient = transient

    def call(self, subject, phase):
        call = ProviderCallRecord(
            call_id=uuid4().hex,
            operation_key="a" * 64,
            subject_id=subject,
            provider=self.provider_name,
            model=self.model_name,
            operation=f"responses.semantic.discovery.{phase}",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            status=ProviderCallStatus.FAILED if self.transient else ProviderCallStatus.SUCCEEDED,
            failure_code="OPENAI_TIMEOUT" if self.transient else None,
            prompt_version="fixture-v1.discovery",
            prompt_sha256=self.prompt_sha256,
            called_at=datetime.now(UTC),
        )
        self.calls.append(call)
        if self.transient:
            raise StructuredProviderError("PROVIDER_TIMEOUT", (call,))
        return StructuredCallResult(
            output=Answer(value="invalid" if self.invalid else "valid"),
            call_records=(call,),
            repaired=phase == "repair",
        )

    def generate(self, *, subject_id, **_):
        return self.call(subject_id, "initial")

    def repair(self, *, subject_id, **_):
        return self.call(subject_id, "repair")


def request(index=0):
    def validate(value):
        if value.value != "valid":
            raise ValueError("complete domain error " * 300)
        return value

    return SemanticUnitRequest.snapshot(
        subject_id=f"unit.{index}",
        payload={"cue": "完整上下文"},
        response_model=Answer,
        validate=validate,
        repair_payload=lambda original, output, errors: {
            "original_request": original,
            "output": output.model_dump(),
            "errors": list(errors),
        },
    )


@pytest.fixture
def context(tmp_path, request):
    yield from _journal_context(tmp_path, request, origin=False)


@pytest.fixture
def origin_context(tmp_path, request):
    # Separate names/kind preserve the established 20-fixture/eight-fault set.
    yield from _journal_context(tmp_path, request, origin=True)


def _journal_context(tmp_path, request, *, origin):
    engine = create_sqlite_engine(tmp_path / "journal.sqlite3")
    Base.metadata.create_all(engine)
    repository = SqlAlchemyPipelineRepository(engine)
    service = PipelineService(repository)
    old = pipeline_config_from_settings(Settings(_env_file=None, ai_provider="mock"))
    raw = old.model_dump(mode="json")
    raw.update(schema_version="12", semantic_execution_contract="semantic-bounded-units-v1")
    config = PipelineRunConfigV12.model_validate_json(json.dumps(raw))
    created = service.create_project_and_run(
        source_path=tmp_path / "source.mp4", config=config, max_stage_retries=1
    )
    queue = SQLiteTaskQueue(engine, lease_seconds=60)
    claimed = queue.claim(worker_id="journal-owner", pipeline_run_id=created.run_id)
    lease = LeaseIdentity(
        task_id=claimed.task_id, worker_id=claimed.worker_id, lease_token=claimed.lease_token
    )
    work = repository.start_or_resume_stage(lease)
    fence = StageMutationFence(
        lease, work.project_id, work.run_id, work.stage_run_id, work.generation
    )
    kwargs = dict(
        work=work,
        fence=fence,
        project_dir=project_directory(tmp_path / "data", work.project_id),
        state=SqlAlchemyStageStateStore(engine),
        assets=SqlAlchemyAssetStore(engine),
        stage="discovery",
        source_sha256="c" * 64,
        model_settings={},
        concurrency=2,
        cancel_requested=lambda: False,
        redact=lambda value: value,
    )
    yield engine, kwargs
    engine.dispose()
    # Retain the exact terminal synthetic fixture for independent formal inspection.
    # A manifest is evidence of bytes, never a substitute for the corresponding test PASS.
    prefix = "semantic-origin-evidence" if origin else "semantic-unit-evidence"
    snapshot = tmp_path / f"{prefix}.sqlite3"
    with (
        closing(sqlite3.connect(f"file:{tmp_path / 'journal.sqlite3'}?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(snapshot)) as destination,
    ):
        src.backup(destination)
    files = [snapshot, *sorted(kwargs["project_dir"].glob("runs/g*/semantic-units/*/*.json"))]
    manifest = {
        "schema_version": "1",
        "kind": (
            "synthetic-semantic-origin-recovery-evidence"
            if origin
            else "synthetic-semantic-unit-recovery-evidence"
        ),
        "test_nodeid": request.node.nodeid,
        "project_id": work.project_id,
        "run_id": work.run_id,
        "config_fingerprint": config.fingerprint,
        "real_inference": False,
        "files": [
            {
                "path": str(path.relative_to(tmp_path)),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in files
        ],
    }
    (tmp_path / f"{prefix}.json").write_text(json.dumps(manifest, sort_keys=True))


def rows(engine):
    with engine.connect() as connection:
        return [
            dict(row) for row in connection.execute(select(SemanticUnitInvocationRow)).mappings()
        ]


def _next_origin_generation(engine, kwargs):
    repository = SqlAlchemyPipelineRepository(engine)
    old = kwargs["work"]
    repository.request_run_cancel(old.run_id)
    assert repository.cancel_stage(kwargs["fence"].lease)
    created = repository.create_run(
        project_id=old.project_id, config=old.config, max_stage_retries=1
    )
    claimed = SQLiteTaskQueue(engine, lease_seconds=60).claim(
        worker_id="origin-successor", pipeline_run_id=created.run_id
    )
    assert claimed is not None
    lease = LeaseIdentity(
        task_id=claimed.task_id, worker_id=claimed.worker_id, lease_token=claimed.lease_token
    )
    work = repository.start_or_resume_stage(lease)
    # Explicitly legitimate distinct input for the new generation, bound in both
    # persisted StageRun and requesting work. The old envelope stays byte-identical.
    stage_input = hashlib.sha256(f"{work.run_id}:successor-input".encode()).hexdigest()
    assert stage_input != old.input_fingerprint
    with engine.begin() as connection:
        connection.execute(
            update(StageRunRow)
            .where(StageRunRow.id == work.stage_run_id)
            .values(input_fingerprint=stage_input)
        )
    return {
        **kwargs,
        "work": work.model_copy(update={"input_fingerprint": stage_input}),
        "fence": StageMutationFence(
            lease, work.project_id, work.run_id, work.stage_run_id, work.generation
        ),
    }


def _origin_evidence(engine, project_dir):
    with engine.connect() as connection:
        usage = connection.execute(select(ApiUsageRow).order_by(ApiUsageRow.id)).all()
        assets = connection.execute(select(AssetRow).order_by(AssetRow.id)).all()
    return (
        rows(engine),
        usage,
        assets,
        {
            str(path): path.read_bytes()
            for path in project_dir.glob("runs/g*/semantic-units/*/*.json")
        },
    )


@pytest.mark.integration
@pytest.mark.parametrize("damage", ["none", "config", "stage_input"])
def test_origin_rows_independently_authenticate_every_cross_generation_outcome(
    origin_context, monkeypatch, damage
):
    engine, kwargs = origin_context
    provider = Provider(transient=True)
    run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    provider.transient = False
    first = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    old_work = kwargs["work"]
    kwargs = _next_origin_generation(engine, kwargs)
    saved = sorted(rows(engine), key=lambda row: row["invocation_number"])
    assert [row["disposition"] for row in saved] == ["transient", "succeeded"]
    if damage == "config":
        raw = old_work.config.model_dump(mode="json")
        raw["top_n"] += 1
        alternative = PipelineRunConfigV12.model_validate_json(json.dumps(raw))
        assert alternative.fingerprint != old_work.config.fingerprint
        # A valid alternative with its correct fingerprint: malformed-config
        # rejection cannot substitute for authenticating the origin envelope.
        assert load_persisted_pipeline_config(raw, alternative.fingerprint) == alternative
        with engine.begin() as connection:
            connection.execute(
                update(PipelineRunRow)
                .where(PipelineRunRow.id == old_work.run_id)
                .values(config_json=raw, config_fingerprint=alternative.fingerprint)
            )
    elif damage == "stage_input":
        with engine.begin() as connection:
            connection.execute(
                update(StageRunRow)
                .where(StageRunRow.id == old_work.stage_run_id)
                .values(input_fingerprint="d" * 64)
            )
    before = _origin_evidence(engine, kwargs["project_dir"])
    observed = []
    load = SqlAlchemySemanticInvocationStore.load_origin_identity

    def authenticate(self, fence, invocation):
        origin = load(self, fence, invocation)
        observed.append(origin)
        return origin

    monkeypatch.setattr(SqlAlchemySemanticInvocationStore, "load_origin_identity", authenticate)
    if damage == "none":
        replay = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
        assert replay.outputs == first.outputs and replay.cache_hits == {"unit.0": True}
        assert [origin.invocation_id for origin in observed] == [row["id"] for row in saved]
        assert all(
            origin.stage_input_fingerprint == old_work.input_fingerprint for origin in observed
        )
        assert all(
            origin.stage_input_fingerprint != kwargs["work"].input_fingerprint
            for origin in observed
        )
    else:
        with pytest.raises(SemanticRecoveryError) as error:
            run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
        assert error.value.code == "SEMANTIC_UNIT_EVIDENCE_INVALID"
        # Rejection occurs on the transient predecessor, before accepting success.
        assert [origin.invocation_id for origin in observed] == [saved[0]["id"]]
    assert len(provider.calls) == 2
    assert _origin_evidence(engine, kwargs["project_dir"]) == before
    assert not any(row["pipeline_run_id"] == kwargs["work"].run_id for row in rows(engine))


@pytest.mark.integration
@pytest.mark.parametrize(
    "damage", ["missing", "changed", "malformed", "malformed_invocation", "stale_fence"]
)
def test_origin_lookup_rejects_invalid_exact_invocation_or_fence(origin_context, damage):
    engine, kwargs = origin_context
    provider = Provider()
    run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    store = SqlAlchemySemanticInvocationStore(engine)
    saved_row = rows(engine)[0]
    identity = SemanticUnitIdentity(
        semantic_stage="discovery", subject_id="unit.0", request_key=saved_row["request_key"]
    )
    saved = store.load_history(kwargs["fence"], identity)[0]
    if damage == "missing":
        saved = saved.model_copy(update={"invocation_id": uuid4().hex})
    elif damage == "malformed_invocation":
        saved = saved.model_copy(update={"generation": True})
    elif damage == "changed":
        with engine.begin() as connection:
            connection.execute(
                update(SemanticUnitInvocationRow)
                .where(SemanticUnitInvocationRow.id == saved.invocation_id)
                .values(subject_id="unit.changed")
            )
    elif damage == "malformed":
        with engine.begin() as connection:
            connection.execute(
                update(StageRunRow)
                .where(StageRunRow.id == saved.stage_run_id)
                .values(input_fingerprint=None)
            )
    else:
        with engine.begin() as connection:
            connection.execute(
                update(TaskRow)
                .where(TaskRow.id == kwargs["fence"].lease.task_id)
                .values(
                    heartbeat_at=datetime.now(UTC) - timedelta(seconds=2),
                    lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
    before = _origin_evidence(engine, kwargs["project_dir"])
    expected_error = StageDataConflict if damage == "stale_fence" else SemanticUnitConflict
    with pytest.raises(expected_error):
        store.load_origin_identity(kwargs["fence"], saved)
    assert len(provider.calls) == 1 and _origin_evidence(engine, kwargs["project_dir"]) == before


@pytest.mark.integration
def test_origin_lookup_rejects_an_exact_foreign_project_invocation(origin_context):
    engine, kwargs = origin_context
    provider = Provider()
    run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    store = SqlAlchemySemanticInvocationStore(engine)
    row = rows(engine)[0]
    saved = store.load_history(
        kwargs["fence"],
        SemanticUnitIdentity(
            semantic_stage="discovery", subject_id="unit.0", request_key=row["request_key"]
        ),
    )[0]
    repository = SqlAlchemyPipelineRepository(engine)
    repository.request_run_cancel(kwargs["work"].run_id)
    assert repository.cancel_stage(kwargs["fence"].lease)
    created = repository.create_project_and_run(
        source_path=kwargs["work"].source_path,
        config=kwargs["work"].config,
        max_stage_retries=1,
    )
    claimed = SQLiteTaskQueue(engine, lease_seconds=60).claim(
        worker_id="foreign-project", pipeline_run_id=created.run_id
    )
    assert claimed is not None
    lease = LeaseIdentity(
        task_id=claimed.task_id, worker_id=claimed.worker_id, lease_token=claimed.lease_token
    )
    work = repository.start_or_resume_stage(lease)
    fence = StageMutationFence(
        lease, work.project_id, work.run_id, work.stage_run_id, work.generation
    )
    assert work.project_id != saved.project_id
    before = _origin_evidence(engine, kwargs["project_dir"])
    with pytest.raises(SemanticUnitConflict, match="origin is foreign"):
        store.load_origin_identity(fence, saved)
    assert len(provider.calls) == 1 and _origin_evidence(engine, kwargs["project_dir"]) == before


@pytest.mark.integration
def test_origin_and_exact_row_share_one_read_snapshot(origin_context, monkeypatch):
    import liveclip.db.semantic_units as journal_module

    engine, kwargs = origin_context
    provider = Provider()
    run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    store = SqlAlchemySemanticInvocationStore(engine)
    row = rows(engine)[0]
    identity = SemanticUnitIdentity(
        semantic_stage="discovery", subject_id="unit.0", request_key=row["request_key"]
    )
    saved = store.load_history(kwargs["fence"], identity)[0]
    validate = journal_module._validated
    snapshots = []

    def concurrent_change(connection, values):
        transaction = connection.get_transaction()
        assert transaction is not None
        result = validate(connection, values)
        # A second real WAL connection commits after exact-row validation, before
        # origin selection. The reader must still return the original snapshot.
        with engine.begin() as writer:
            writer.execute(
                update(StageRunRow)
                .where(StageRunRow.id == saved.stage_run_id)
                .values(input_fingerprint="e" * 64)
            )
        assert connection.get_transaction() is transaction
        snapshots.append(transaction)
        return result

    monkeypatch.setattr(journal_module, "_validated", concurrent_change)
    origin = store.load_origin_identity(kwargs["fence"], saved)
    assert len(snapshots) == 1
    assert origin.stage_input_fingerprint == kwargs["work"].input_fingerprint
    monkeypatch.setattr(journal_module, "_validated", validate)
    assert store.load_origin_identity(kwargs["fence"], saved).stage_input_fingerprint == "e" * 64
    before = _origin_evidence(engine, kwargs["project_dir"])
    with pytest.raises(SemanticRecoveryError):
        run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    assert len(provider.calls) == 1 and _origin_evidence(engine, kwargs["project_dir"]) == before


@pytest.mark.integration
def test_migrated_journal_constraints_foreign_keys_and_reservation_authority(tmp_path, monkeypatch):
    """Use shipped Alembic DDL and valid provider evidence on disposable SQLite only."""
    database = tmp_path / "migrated.sqlite3"
    monkeypatch.setenv("LIVECLIP_DATABASE_PATH", str(database))
    migration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(migration, "f3b6d9a2c841")
    engine = create_sqlite_engine(database)
    try:
        repository = SqlAlchemyPipelineRepository(engine)
        config = pipeline_config_from_settings(Settings(_env_file=None, ai_provider="mock"))
        legacy_raw = config.model_dump(mode="json")
        legacy_raw.pop("semantic_execution_contract")
        legacy_raw["schema_version"] = "10"
        legacy = PipelineRunConfigV10.model_validate_json(json.dumps(legacy_raw))
        repository.create_project_and_run(
            source_path=tmp_path / "legacy.mp4", config=legacy, max_stage_retries=0
        )
        legacy_table_names = set(inspect(engine).get_table_names())

        def existing_rows():
            with engine.connect() as connection:
                return {
                    table.name: connection.execute(
                        select(table).order_by(*table.primary_key.columns)
                    ).all()
                    for table in Base.metadata.tables.values()
                    if table.name in legacy_table_names
                }

        before_upgrade = existing_rows()
        command.upgrade(migration, "a13f9c6d2e80")
        assert existing_rows() == before_upgrade
        inspector = inspect(engine)
        table = SemanticUnitInvocationRow.__table__
        assert {
            item["name"]: item["sqltext"] for item in inspector.get_check_constraints(table.name)
        } == {
            constraint.name: str(constraint.sqltext)
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert inspector.get_indexes(table.name) == [
            {
                "name": "ix_semantic_unit_history",
                "column_names": ["pipeline_run_id", "semantic_stage", "subject_id", "request_key"],
                "unique": 0,
                "dialect_options": {},
            }
        ]
        created = repository.create_project_and_run(
            source_path=tmp_path / "source.mp4", config=config, max_stage_retries=0
        )
        claimed = SQLiteTaskQueue(engine, lease_seconds=60).claim(
            worker_id="migration-owner", pipeline_run_id=created.run_id
        )
        assert claimed is not None
        lease = LeaseIdentity(
            task_id=claimed.task_id, worker_id=claimed.worker_id, lease_token=claimed.lease_token
        )
        work = repository.start_or_resume_stage(lease)
        fence = StageMutationFence(
            lease, work.project_id, work.run_id, work.stage_run_id, work.generation
        )
        with engine.connect() as connection:
            attempt_id = connection.execute(
                select(TaskAttemptRow.id).where(
                    TaskAttemptRow.task_id == lease.task_id,
                    TaskAttemptRow.worker_id == lease.worker_id,
                    TaskAttemptRow.lease_token == lease.lease_token,
                )
            ).scalar_one()

        class ReservedProvider(Provider):
            def generate(self, *, subject_id, **kwargs):
                saved = rows(engine)
                assert len(saved) == 1 and saved[0]["completed_at"] is None
                assert saved[0]["task_id"] == lease.task_id
                # StageWork has no attempt_id. The historical test raised here
                # before Provider.call, producing INTERNAL_ERROR with zero calls.
                assert saved[0]["producer_attempt_id"] == attempt_id
                return super().generate(subject_id=subject_id, **kwargs)

        provider = ReservedProvider()
        kwargs = dict(
            work=work,
            fence=fence,
            project_dir=project_directory(tmp_path / "data", work.project_id),
            state=SqlAlchemyStageStateStore(engine),
            assets=SqlAlchemyAssetStore(engine),
            stage="discovery",
            source_sha256="c" * 64,
            provider=provider,
            model_settings={},
            requests=(request(),),
            concurrency=1,
            cancel_requested=lambda: False,
            redact=lambda value: value,
        )
        first = run_persisted_semantic_units(**kwargs)
        saved = rows(engine)[0]
        assert saved["disposition"] == "succeeded" and saved["repair_spent"] is False
        assert first.outputs == {"unit.0": Answer(value="valid")}
        raw = (kwargs["project_dir"] / saved["outcome_relative_path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == saved["outcome_sha256"]
        assert len(raw) == saved["outcome_size_bytes"]
        with engine.connect() as connection:
            calls_before = connection.execute(select(ApiUsageRow)).all()
        replay = run_persisted_semantic_units(**kwargs)
        assert replay.outputs == first.outputs and replay.cache_hits == {"unit.0": True}
        assert len(provider.calls) == len(calls_before) == 1 and rows(engine) == [saved]
        with engine.connect() as connection:
            assert connection.execute(select(ApiUsageRow)).all() == calls_before

        for invalid in (
            {"generation": 0},
            {"invocation_number": 4},
            {"execution_contract": "unknown"},
            {"disposition": "unknown"},
            {"disposition": "transient", "repair_spent": True},
            {"outcome_size_bytes": 0},
            *(
                {column: "f" * 32}
                for column in (
                    "project_id",
                    "pipeline_run_id",
                    "stage_run_id",
                    "task_id",
                    "producer_attempt_id",
                    "outcome_asset_id",
                )
            ),
        ):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(
                    update(SemanticUnitInvocationRow)
                    .where(SemanticUnitInvocationRow.id == saved["id"])
                    .values(**invalid)
                )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                insert(SemanticUnitInvocationRow).values(**{**saved, "id": uuid4().hex})
            )
        assert rows(engine) == [saved]
        with engine.begin() as connection:
            connection.execute(delete(AssetRow).where(AssetRow.id == saved["outcome_asset_id"]))
        assert rows(engine)[0]["outcome_asset_id"] is None
        assert rows(engine)[0]["outcome_sha256"] == saved["outcome_sha256"]
        with pytest.raises(SemanticUnitConflict, match="malformed"):
            run_persisted_semantic_units(**kwargs)
        assert len(provider.calls) == 1
        with engine.begin() as connection:
            connection.execute(delete(TaskRow).where(TaskRow.id == lease.task_id))
        assert rows(engine) == []
        before_downgrade = existing_rows()
        command.downgrade(migration, "f3b6d9a2c841")
        assert "semantic_unit_invocations" not in inspect(engine).get_table_names()
        assert existing_rows() == before_downgrade
        command.upgrade(migration, "a13f9c6d2e80")
        assert rows(engine) == [] and existing_rows() == before_downgrade
        command.upgrade(migration, "head")
        command.check(migration)
        assert existing_rows() == before_downgrade
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


def test_success_reuses_authenticated_journal_without_new_calls(context):
    engine, kwargs = context
    provider = Provider()
    first = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    before = rows(engine)
    second = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    assert first.outputs == second.outputs and second.cache_hits == {"unit.0": True}
    assert len(provider.calls) == 1 and rows(engine) == before
    saved = before[0]
    assert (
        saved["outcome_sha256"]
        == hashlib.sha256(
            (kwargs["project_dir"] / saved["outcome_relative_path"]).read_bytes()
        ).hexdigest()
    )


def test_fast_sibling_is_durably_committed_while_other_unit_repairs(context, monkeypatch):
    from liveclip.db.semantic_units import SqlAlchemySemanticInvocationStore

    engine, kwargs = context
    repairing, release, committed = Event(), Event(), Event()
    complete = SqlAlchemySemanticInvocationStore.complete

    def observed_complete(self, fence, invocation, **values):
        result = complete(self, fence, invocation, **values)
        if invocation.subject_id == "unit.1":
            committed.set()
        return result

    monkeypatch.setattr(SqlAlchemySemanticInvocationStore, "complete", observed_complete)

    class SlowRepair(Provider):
        def generate(self, *, subject_id, **_):
            result = self.call(subject_id, "initial")
            if subject_id.endswith("unit.0"):
                return StructuredCallResult(
                    output=Answer(value="invalid"), call_records=result.call_records, repaired=False
                )
            assert repairing.wait(10)
            return result

        def repair(self, *, subject_id, **_):
            repairing.set()
            assert release.wait(10)
            return self.call(subject_id, "repair")

    provider = SlowRepair()
    requests = (request(0), request(1))
    with ThreadPoolExecutor(max_workers=1) as owner:
        pending = owner.submit(
            run_persisted_semantic_units, **kwargs, provider=provider, requests=requests
        )
        try:
            assert repairing.wait(10) and committed.wait(10)
            saved = rows(engine)
            fast = next(row for row in saved if row["subject_id"] == "unit.1")
            slow = next(row for row in saved if row["subject_id"] == "unit.0")
            assert fast["disposition"] == "succeeded" and slow["completed_at"] is None
            assert (
                hashlib.sha256(
                    (kwargs["project_dir"] / fast["outcome_relative_path"]).read_bytes()
                ).hexdigest()
                == fast["outcome_sha256"]
            )
            with engine.connect() as connection:
                assert len(connection.execute(select(ApiUsageRow)).all()) == 1
            assert not pending.done()
        finally:
            release.set()
        batch = pending.result(timeout=15)
    assert set(batch.outputs) == {"unit.0", "unit.1"}
    assert len(provider.calls) == 3
    saved = rows(engine)
    replay = run_persisted_semantic_units(**kwargs, provider=provider, requests=requests)
    assert replay.cache_hits == {"unit.0": True, "unit.1": True}
    assert rows(engine) == saved and len(provider.calls) == 3


def test_domain_exhaustion_persists_all_calls_and_retries_spend_nothing(context):
    engine, kwargs = context
    provider = Provider(invalid=True)
    for _ in range(3):
        batch = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
        assert batch.outcomes["unit.0"].disposition == "exhausted"
        assert batch.outcomes["unit.0"].repair_spent
    assert len(provider.calls) == 2 and len(rows(engine)) == 1
    with engine.connect() as connection:
        assert len(connection.execute(select(ApiUsageRow)).all()) == 2
    saved = rows(engine)[0]
    envelope = json.loads((kwargs["project_dir"] / saved["outcome_relative_path"]).read_text())
    assert len(envelope["outcome"]["validation_events"]) == 2
    assert len(envelope["outcome"]["validation_events"][0]["error"]) > 5000


def test_transient_invocations_have_a_run_scoped_upper_bound(context):
    engine, kwargs = context
    provider = Provider(transient=True)
    for _ in range(3):
        batch = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
        assert batch.outcomes["unit.0"].disposition == "transient"
    with pytest.raises(SemanticRecoveryError, match="explicit new run") as error:
        run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    assert error.value.code == "SEMANTIC_UNIT_INVOCATIONS_EXHAUSTED"
    assert len(provider.calls) == 3
    assert [row["invocation_number"] for row in rows(engine)] == [1, 2, 3]


@pytest.mark.parametrize(
    "damage", ["none", "row", "file", "bytes", "foreign", "disposition", "number"]
)
def test_prior_generation_success_authenticates_complete_history(context, damage):
    engine, kwargs = context
    provider = Provider(transient=True)
    run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    provider.transient = False
    run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    first, success = sorted(rows(engine), key=lambda row: row["invocation_number"])
    assert first["disposition"] == "transient" and success["disposition"] == "succeeded"

    repository = SqlAlchemyPipelineRepository(engine)
    old_work, old_fence = kwargs["work"], kwargs["fence"]
    repository.request_run_cancel(old_work.run_id)
    assert repository.cancel_stage(old_fence.lease)
    created = repository.create_run(
        project_id=old_work.project_id, config=old_work.config, max_stage_retries=1
    )
    claimed = SQLiteTaskQueue(engine, lease_seconds=60).claim(
        worker_id="next-generation", pipeline_run_id=created.run_id
    )
    lease = LeaseIdentity(
        task_id=claimed.task_id, worker_id=claimed.worker_id, lease_token=claimed.lease_token
    )
    work = repository.start_or_resume_stage(lease)
    kwargs = {
        **kwargs,
        "work": work,
        "fence": StageMutationFence(
            lease, work.project_id, work.run_id, work.stage_run_id, work.generation
        ),
    }
    predecessor = kwargs["project_dir"] / first["outcome_relative_path"]
    if damage == "file":
        predecessor.unlink()
    elif damage == "bytes":
        predecessor.write_text("{}")
    elif damage != "none":
        with engine.begin() as connection:
            target = SemanticUnitInvocationRow.id == first["id"]
            if damage == "row":
                connection.execute(delete(SemanticUnitInvocationRow).where(target))
            else:
                values = {
                    "foreign": {"task_id": lease.task_id},
                    "disposition": {"disposition": "exhausted"},
                    "number": {"invocation_number": 3},
                }[damage]
                connection.execute(update(SemanticUnitInvocationRow).where(target).values(**values))
    if damage == "none":
        result = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
        assert result.cache_hits == {"unit.0": True}
        assert result.outputs["unit.0"] == Answer(value="valid")
    else:
        with pytest.raises((SemanticRecoveryError, SemanticUnitConflict)):
            run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    assert len(provider.calls) == 2
    assert not any(row["pipeline_run_id"] == created.run_id for row in rows(engine))


@pytest.mark.parametrize("rehash_asset", [False, True])
def test_tampered_outcome_cannot_become_authority_by_rehashing_asset(context, rehash_asset):
    engine, kwargs = context
    provider = Provider()
    run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    saved = rows(engine)[0]
    path = kwargs["project_dir"] / saved["outcome_relative_path"]
    data = json.loads(path.read_text())
    data["outcome"]["raw_output"]["value"] = "foreign"
    path.write_text(json.dumps(data))
    if rehash_asset:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with engine.begin() as connection:
            connection.execute(
                update(AssetRow)
                .where(AssetRow.id == saved["outcome_asset_id"])
                .values(sha256=digest, expected_sha256=digest, size_bytes=path.stat().st_size)
            )
    with pytest.raises((SemanticRecoveryError, RuntimeError)):
        run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    assert len(provider.calls) == 1
    assert rows(engine)[0]["outcome_sha256"] == saved["outcome_sha256"]


@pytest.mark.parametrize(
    "crash", ["before_call", "after_call", "before_repair", "after_repair", "after_asset"]
)
def test_crash_without_authenticated_completion_is_uncertain(context, monkeypatch, crash):
    engine, kwargs = context
    provider = Provider()
    if crash == "before_call":
        import liveclip.pipeline.semantic_executor as executor_module

        def interrupted(*_, **__):
            raise KeyboardInterrupt("crash before entering provider")

        monkeypatch.setattr(executor_module, "execute_semantic_unit", interrupted)
    elif crash in {"before_repair", "after_repair"}:
        provider.invalid = True

        def interrupted_repair(*, subject_id, **_):
            if crash == "after_repair":
                provider.call(subject_id, "repair")
            raise KeyboardInterrupt("crash around repair")

        monkeypatch.setattr(provider, "repair", interrupted_repair)
    elif crash == "after_call":
        monkeypatch.setattr(
            kwargs["assets"],
            "reserve",
            lambda *_, **__: (_ for _ in ()).throw(RuntimeError("crash after call")),
        )
    else:
        from liveclip.db.semantic_units import SqlAlchemySemanticInvocationStore

        monkeypatch.setattr(
            SqlAlchemySemanticInvocationStore,
            "complete",
            lambda *_, **__: (_ for _ in ()).throw(RuntimeError("crash after asset")),
        )
    with pytest.raises((KeyboardInterrupt, RuntimeError)):
        run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    count = len(provider.calls)
    assert len(rows(engine)) == 1 and rows(engine)[0]["completed_at"] is None
    monkeypatch.undo()
    with pytest.raises(SemanticRecoveryError) as error:
        run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    assert error.value.code == "SEMANTIC_UNIT_EXECUTION_UNCERTAIN"
    assert len(provider.calls) == count


def test_failure_association_survives_crash_before_stage_failure_manifest(context, monkeypatch):
    from liveclip.db.semantic_units import SqlAlchemySemanticInvocationStore

    engine, kwargs = context
    provider = Provider(invalid=True)
    complete = SqlAlchemySemanticInvocationStore.complete

    def interrupted(self, fence, invocation, **values):
        complete(self, fence, invocation, **values)
        raise KeyboardInterrupt("crash after durable exhaustion, before stage audit")

    monkeypatch.setattr(SqlAlchemySemanticInvocationStore, "complete", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
    monkeypatch.undo()
    before = rows(engine)
    assert before[0]["disposition"] == "exhausted" and before[0]["repair_spent"] is True
    for _ in range(2):
        result = run_persisted_semantic_units(**kwargs, provider=provider, requests=(request(),))
        assert result.outcomes["unit.0"].disposition == "exhausted"
    assert len(provider.calls) == 2 and rows(engine) == before


def test_late_result_after_lease_expiry_has_usage_but_no_committed_outcome(context):
    engine, kwargs = context
    entered, release = Event(), Event()

    class SlowProvider(Provider):
        def generate(self, *, subject_id, **_):
            value = self.call(subject_id, "initial")
            entered.set()
            assert release.wait(5)
            return value

    provider = SlowProvider()
    with ThreadPoolExecutor(max_workers=1) as owner:
        future = owner.submit(
            run_persisted_semantic_units, **kwargs, provider=provider, requests=(request(),)
        )
        try:
            assert entered.wait(5)
            with engine.begin() as connection:
                connection.execute(
                    update(TaskRow)
                    .where(TaskRow.id == kwargs["fence"].lease.task_id)
                    .values(
                        heartbeat_at=datetime.now(UTC) - timedelta(seconds=2),
                        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    )
                )
        finally:
            release.set()
        with pytest.raises(StageDataConflict):
            future.result(timeout=5)
    assert rows(engine)[0]["completed_at"] is None
    with engine.connect() as connection:
        assert len(connection.execute(select(AssetRow)).all()) == 0
        assert {row.id for row in connection.execute(select(ApiUsageRow))} == {
            provider.calls[0].call_id
        }
