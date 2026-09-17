"""Public JSON completion commands against disposable migrated SQLite."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, event, func, select, update

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    CompletionIntentRow,
    PipelineRunRow,
    ProjectMemberRow,
    ProjectRow,
    TaskAttemptRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.providers.readiness import assess_provider_readiness
from liveclip.worker import run_worker

pytestmark = pytest.mark.integration


@pytest.fixture
def api(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic source; ingest is deliberately not run")
    settings = Settings(
        data_dir=tmp_path / "data",
        allowed_media_roots_raw=str(tmp_path),
        ai_provider="mock",
        api_token=SecretStr("synthetic-completion-token"),
        _env_file=None,
    )
    root = Path(__file__).resolve().parents[2]
    runtime = LiveClipRuntime.open(settings, project_root=root)
    try:
        with TestClient(
            create_app(settings, runtime=runtime, project_root=root),
            headers={"Authorization": "Bearer synthetic-completion-token"},
        ) as client:
            yield client, runtime, source
    finally:
        runtime.close()


def create(client, source, key="goal", **options):
    return client.post(
        "/api/v1/completion-goals",
        headers={"Idempotency-Key": key},
        json={"job": {"input_path": str(source)}, "options": options},
    )


def counts(runtime):
    with runtime.engine.connect() as connection:
        return tuple(
            connection.scalar(select(func.count()).select_from(row))
            for row in (
                ProjectRow,
                PipelineRunRow,
                CompletionIntentRow,
                TaskAttemptRow,
            )
        )


def test_create_replay_concurrent_and_read_only_polling(api):
    client, runtime, source = api
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: create(client, source), range(4)))
    assert {r.status_code for r in results} == {202}
    assert len({r.json()["goal"]["intent_id"] for r in results}) == 1
    first = results[0]
    assert first.headers["Retry-After"] == "1"
    assert first.json()["download_url"] is None
    assert counts(runtime) == (1, 1, 1, 0)
    for _ in range(5):
        assert client.get(first.headers["Location"]).json() == first.json()
    source.unlink()
    assert create(client, source).json() == first.json()
    assert create(client, source, top_n=2).status_code == 422
    assert create(client, source, include_zip=False).status_code == 409
    assert create(client, source, key="fresh").status_code == 422
    assert counts(runtime) == (1, 1, 1, 0)


@pytest.mark.parametrize(
    "options",
    [
        {"target": "process_only", "include_zip": False},
        {"target": "delivery", "selection_policy": "manual"},
        {"target": "delivery", "selection_policy": "default"},
    ],
)
def test_explicit_json_enums(api, options):
    client, _, source = api
    result = create(client, source, **options)
    assert result.status_code == 202, result.text
    assert all(result.json()["goal"]["options"][key] == value for key, value in options.items())


@pytest.mark.parametrize(
    "body",
    [
        {"job": {"input_path": "/abs.mp4"}, "actor_user_id": "injected"},
        {"job": {"input_path": "/abs.mp4", "project_id": "injected"}},
        {"job": {"input_path": "/abs.mp4"}, "options": {"schema_version": "2"}},
        {"job": {"input_path": "/abs.mp4"}, "options": {"include_zip": 1}},
        {"job": {"input_path": "/abs.mp4"}, "options": {"target": "unknown"}},
    ],
)
def test_invalid_json_has_no_effect(api, body):
    client, runtime, _ = api
    assert (
        client.post(
            "/api/v1/completion-goals", json=body, headers={"Idempotency-Key": "invalid"}
        ).status_code
        == 422
    )
    assert counts(runtime) == (0, 0, 0, 0)


@pytest.mark.parametrize("key", [None, "", "has space", "x" * 201])
def test_required_valid_key(api, key):
    client, runtime, source = api
    headers = {} if key is None else {"Idempotency-Key": key}
    result = client.post(
        "/api/v1/completion-goals", headers=headers, json={"job": {"input_path": str(source)}}
    )
    assert result.status_code == 422
    assert counts(runtime) == (0, 0, 0, 0)


def test_existing_run_and_versioned_commands(api):
    client, runtime, source = api
    run = client.post("/api/v1/jobs", json={"input_path": str(source)}).json()
    path = f"/api/v1/runs/{run['run_id']}/completion-goals"
    headers = {"Idempotency-Key": "existing"}
    assert client.post(path, json={}).status_code == 422
    created = client.post(path, headers=headers, json={"options": {"selection_policy": "manual"}})
    assert created.status_code == 202, created.text
    assert (
        client.post(path, headers=headers, json={"options": {"selection_policy": "manual"}}).json()
        == created.json()
    )
    assert counts(runtime) == (1, 1, 1, 0)
    location = created.headers["Location"]
    assert client.get(location).status_code == 200
    for suffix in ("resume", "cancel", "selection"):
        body = {"expected_version": 999}
        if suffix == "selection":
            body["selected"] = []
        result = client.post(f"{location}/{suffix}", json=body)
        assert result.status_code == 409, result.text
        assert result.json()["error"]["code"] == "COMPLETION_CONFLICT"
    for version in (True, "1", 0, -1, 1.0):
        assert (
            client.post(f"{location}/cancel", json={"expected_version": version}).status_code == 422
        )
    cancelled = client.post(f"{location}/cancel", json={"expected_version": 1})
    assert cancelled.status_code == 200
    assert cancelled.json()["goal"]["status"] == "cancelled"
    assert runtime.pipeline_service.get_run(run["run_id"]).status.value == "queued"
    assert client.get("/api/v1/completion-goals/missing").status_code == 404


def test_replay_skips_fresh_guard_with_changed_symlink_and_readiness(api, monkeypatch):
    client, runtime, source = api
    alias = source.parent / "alias.mp4"
    alias.symlink_to(source)
    first = create(client, alias)
    assert first.status_code == 202
    alias.unlink()
    alias.symlink_to(source.parent / "missing.mp4")

    def forbidden(_readiness):
        pytest.fail("replay invoked fresh readiness guard")

    monkeypatch.setattr("liveclip.api.app.ensure_processing_ready", forbidden)
    assert create(client, alias).json() == first.json()
    assert counts(runtime) == (1, 1, 1, 0)


def test_unavailable_readiness_rolls_back_new_create_and_allows_replay(api, monkeypatch):
    client, runtime, source = api
    first = create(client, source)
    settings = client.app.state.settings
    unavailable = replace(
        assess_provider_readiness(settings),
        processing_ready=False,
        blocking_issues=("SYNTHETIC_UNAVAILABLE",),
    )
    monkeypatch.setattr("liveclip.api.app.assess_provider_readiness", lambda _: unavailable)
    with TestClient(create_app(settings, runtime=runtime), headers=client.headers) as restarted:
        assert create(restarted, source).json() == first.json()
        result = create(restarted, source, key="new")
        assert result.status_code == 503
    assert counts(runtime) == (1, 1, 1, 0)


def test_same_key_is_scoped_to_authenticated_caller(tmp_path):
    source = tmp_path / "synthetic.mp4"
    source.write_bytes(b"synthetic; no worker")
    settings = Settings(
        data_dir=tmp_path / "data",
        allowed_media_roots_raw=str(tmp_path),
        ai_provider="mock",
        api_token=SecretStr("synthetic-owner-token"),
        workspace_tokens_raw=json.dumps({"outsider": "synthetic-outsider-token"}),
        _env_file=None,
    )
    with (
        LiveClipRuntime.open(settings) as runtime,
        TestClient(create_app(settings, runtime=runtime)) as client,
    ):
        body = {"job": {"input_path": str(source)}}
        owner = {"Authorization": "Bearer synthetic-owner-token", "Idempotency-Key": "same"}
        outsider = {
            "Authorization": "Bearer synthetic-outsider-token",
            "Idempotency-Key": "same",
        }
        first = client.post("/api/v1/completion-goals", headers=owner, json=body)
        second = client.post("/api/v1/completion-goals", headers=outsider, json=body)
        assert first.status_code == second.status_code == 202
        assert first.json()["goal"]["intent_id"] != second.json()["goal"]["intent_id"]
        assert client.get(first.headers["Location"], headers=outsider).status_code == 404
        assert (
            client.post(
                f"/api/v1/runs/{first.json()['goal']['run_id']}/completion-goals",
                headers=outsider,
                json={},
            ).status_code
            == 404
        )
        assert counts(runtime) == (2, 2, 2, 0)


def test_resume_is_explicit_and_versioned(api):
    client, runtime, source = api
    first = create(client, source)
    path = first.headers["Location"]
    resumed = client.post(f"{path}/resume", json={"expected_version": 1})
    assert resumed.status_code == 200
    assert resumed.json()["goal"]["version"] == 2
    assert client.post(f"{path}/resume", json={"expected_version": 1}).status_code == 409
    assert counts(runtime) == (1, 1, 1, 0)


def test_zero_candidates_is_a_safe_outcome_without_a_zip(api):
    client, runtime, source = api
    first = create(client, source)
    # Synthetic persisted processing boundary: no candidates were discovered.
    with runtime.engine.begin() as connection:
        connection.execute(update(PipelineRunRow).values(status="completed"))
        connection.execute(
            update(TaskRow).where(TaskRow.kind == "stage").values(status="cancelled")
        )
    assert run_worker(client.app.state.settings, once=True) == 0
    observed = client.get(first.headers["Location"])
    assert observed.status_code == 200
    assert observed.json()["goal"]["outcome"] == "no_eligible_clips"
    assert observed.json()["goal"]["delivery_id"] is None
    assert observed.json()["download_url"] is None


@pytest.mark.parametrize("change", ["revoke", "downgrade", "archive", "generation", "disable"])
def test_current_authority_and_generation_fence_commands(api, change):
    client, runtime, source = api
    first = create(client, source)
    goal = first.json()["goal"]
    location = first.headers["Location"]
    with runtime.engine.begin() as connection:
        if change == "revoke":
            connection.execute(delete(ProjectMemberRow))
        elif change == "downgrade":
            connection.execute(update(ProjectMemberRow).values(role="viewer"))
        elif change == "archive":
            connection.execute(update(ProjectRow).values(lifecycle="archived"))
        elif change == "generation":
            connection.execute(update(ProjectRow).values(current_generation=2))
        else:
            connection.execute(update(WorkspaceUserRow).values(is_active=False))
    expected = 409 if change == "generation" else 404
    for suffix in ("resume", "cancel", "selection"):
        body = {"expected_version": goal["version"]}
        if suffix == "selection":
            body["selected"] = []
        result = client.post(f"{location}/{suffix}", json=body)
        assert result.status_code == expected, result.text
    assert create(client, source).status_code == expected
    with runtime.engine.connect() as connection:
        saved = connection.execute(select(CompletionIntentRow)).mappings().one()
    assert saved["version"] == goal["version"]
    assert saved["status"] == goal["status"]
    assert saved["delivery_id"] is None
    if change == "revoke":
        inaccessible = client.get(location)
        unknown = client.get("/api/v1/completion-goals/unknown")
        assert inaccessible.status_code == unknown.status_code == 404
        assert inaccessible.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_replay_rechecks_authority_after_waiting_for_sqlite_writer(api):
    client, runtime, source = api
    first = create(client, source)
    attempted = Event()

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if statement == "BEGIN IMMEDIATE":
            attempted.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with begin_immediate(runtime.engine) as connection:
            event.listen(runtime.engine, "before_cursor_execute", observe)
            try:
                replay = pool.submit(create, client, source)
                assert attempted.wait(5)
                connection.execute(delete(ProjectMemberRow))
            finally:
                event.remove(runtime.engine, "before_cursor_execute", observe)
        assert replay.result(timeout=10).status_code == 404
    assert counts(runtime) == (1, 1, 1, 0)
    with runtime.engine.connect() as connection:
        assert (
            connection.scalar(select(CompletionIntentRow.version))
            == first.json()["goal"]["version"]
        )
