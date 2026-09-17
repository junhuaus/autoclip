"""Synthetic HTTP/Worker/FFmpeg recovery; no real-provider quality claim."""

import hashlib
import json
import time
import zipfile
from pathlib import Path, PurePosixPath

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from test_completion_api import api

from liveclip.api.app import create_app
from liveclip.db.completion_repository import SqlAlchemyCompletionRepository
from liveclip.db.models import (
    AssetRow,
    CompletionIntentRow,
    DeliveryRow,
    ProjectMemberRow,
    StageRunRow,
    TaskRow,
)
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    open_pinned_regular_file,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.renderer.quality import full_decode
from liveclip.services.demo_media import create_demo_source
from liveclip.worker import run_worker

pytestmark = pytest.mark.integration
__all__ = ["api"]


def rows(runtime, model):
    with runtime.engine.connect() as connection:
        return [dict(row) for row in connection.execute(select(model)).mappings()]


def drive(settings, runtime, target, timeout=100):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if rows(runtime, CompletionIntentRow)[0]["status"] == target:
            return
        assert run_worker(settings, once=True) == 0
        time.sleep(0.1)
    pytest.fail(f"independent Worker did not reach {target}")


def inspect_committed_assets(runtime):
    inspected = []
    data_root = runtime.data_dir.resolve(strict=True)
    saved_assets = rows(runtime, AssetRow)
    required_ids = {saved["id"] for saved in saved_assets}
    for saved in saved_assets:
        relative = PurePosixPath(saved["relative_path"])
        assert not relative.is_absolute()
        assert relative.parts and all(part not in {"", ".", ".."} for part in relative.parts)
        project_id = saved["project_id"]
        assert len(project_id) == 32 and all(char in "0123456789abcdef" for char in project_id)
        # Resolve only the configured root; pinned open must see every DB-owned component.
        path = data_root / project_id / Path(*relative.parts)
        with open_pinned_regular_file(path) as pinned:
            assert pinned.metadata.st_size == saved["size_bytes"]
            assert pinned.sha256() == saved["sha256"]
        if path.suffix == ".mp4":
            full_decode(path)
        if path.suffix == ".srt":
            assert load_srt_transcript(path).segments
        inspected.append({"asset_id": saved["id"], "sha256": saved["sha256"]})
    assert {item["asset_id"] for item in inspected} == required_ids
    return inspected


@pytest.mark.parametrize("empty", [False, True])
def test_disconnected_http_goal_survives_lost_responses_and_worker_restarts(
    api, monkeypatch, empty
):
    client, runtime, source = api
    settings = client.app.state.settings
    source.unlink()
    create_demo_source(output_path=source, duration_ms=32_000)
    body = {
        "job": {
            "input_path": str(source),
            "top_n": 1,
            "minimum_clip_seconds": 8,
            "maximum_clip_seconds": 12,
        },
        "options": {"selection_policy": "manual"},
    }
    headers = {"Idempotency-Key": "lost-create"}
    original_create = runtime.completion_service.create_project_and_run_with_goal

    def lose_create(**kwargs):
        original_create(**kwargs)
        raise RuntimeError("synthetic lost HTTP response after commit")

    with monkeypatch.context() as patch:
        patch.setattr(runtime.completion_service, "create_project_and_run_with_goal", lose_create)
        with TestClient(
            create_app(settings, runtime=runtime),
            raise_server_exceptions=False,
            headers=client.headers,
        ) as lost:
            assert (
                lost.post("/api/v1/completion-goals", json=body, headers=headers).status_code == 500
            )
    # The observing connection is closed while fresh Worker runtimes process all stages.
    drive(settings, runtime, "waiting_selection")
    stages = rows(runtime, StageRunRow)
    assert len(stages) == 6
    assert {stage["status"] for stage in stages} == {"succeeded"}
    tasks_before = rows(runtime, TaskRow)
    for _ in range(2):
        assert run_worker(settings, once=True) == 0
    assert rows(runtime, TaskRow) == tasks_before
    recovered = client.post("/api/v1/completion-goals", json=body, headers=headers)
    assert recovered.status_code == 202
    goal = recovered.json()["goal"]
    location = recovered.headers["Location"]
    assert recovered.json()["download_url"] is None
    clips = runtime.clip_query_service.list_project_clips(goal["project_id"])
    submission = {
        "expected_version": goal["version"],
        "selected": []
        if empty
        else [
            {"clip_id": clip.clip_id, "expected_revision": clip.edit_plan_revision}
            for clip in clips
        ],
    }
    original_select = runtime.completion_service.submit_selection

    def lose_selection(*args, **kwargs):
        original_select(*args, **kwargs)
        raise RuntimeError("synthetic lost selection response after commit")

    with monkeypatch.context() as patch:
        patch.setattr(runtime.completion_service, "submit_selection", lose_selection)
        with TestClient(
            create_app(settings, runtime=runtime),
            raise_server_exceptions=False,
            headers=client.headers,
        ) as lost:
            assert lost.post(f"{location}/selection", json=submission).status_code == 500
    checkpoint = rows(runtime, CompletionIntentRow)[0]["selection_checkpoint_json"]
    assert client.post(f"{location}/selection", json=submission).status_code == 200
    assert rows(runtime, CompletionIntentRow)[0]["selection_checkpoint_json"] == checkpoint

    if not empty:
        original_reconcile = SqlAlchemyCompletionRepository.reconcile_completion

        def lose_enqueue(self, *args, **kwargs):
            result = original_reconcile(self, *args, **kwargs)
            if rows(runtime, CompletionIntentRow)[0]["delivery_id"]:
                raise RuntimeError("synthetic lost enqueue result after atomic binding")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(SqlAlchemyCompletionRepository, "reconcile_completion", lose_enqueue)
            with pytest.raises(RuntimeError, match="lost enqueue"):
                run_worker(settings, once=True)
        bound = rows(runtime, CompletionIntentRow)[0]
        assert bound["delivery_id"] and bound["delivery_action_key"]
    drive(settings, runtime, "succeeded")
    result = client.get(location)
    final = result.json()["goal"]
    assert final["intent_id"] == goal["intent_id"]
    assert final["run_id"] == goal["run_id"]
    assert final["generation"] == goal["generation"]
    assert rows(runtime, CompletionIntentRow)[0]["selection_checkpoint_json"] == checkpoint
    assert rows(runtime, StageRunRow) == stages
    assert all(task["retry_count"] == 0 for task in rows(runtime, TaskRow))
    inspection = inspect_committed_assets(runtime)
    assert inspection
    if empty:
        assert final["outcome"] == "no_selected_clips"
        assert result.json()["download_url"] is None
        assert rows(runtime, DeliveryRow) == []
        return
    assert final["outcome"] == "delivered"
    deliveries = rows(runtime, DeliveryRow)
    assert len(deliveries) == 1
    assert final["delivery_id"] == bound["delivery_id"] == deliveries[0]["id"]
    archive = client.get(result.json()["download_url"])
    assert archive.status_code == 200
    asset = runtime.media_asset_service.resolve(
        deliveries[0]["zip_asset_id"], required_kind="delivery_zip"
    )
    assert archive.content == asset.path.read_bytes()
    with zipfile.ZipFile(asset.path) as package:
        assert package.testzip() is None
        names = package.namelist()
        assert all(
            not PurePosixPath(name).is_absolute() and ".." not in PurePosixPath(name).parts
            for name in names
        )
        assert any(name.endswith(".mp4") for name in names)
        assert any(name.endswith(".srt") for name in names)
        assert any("manifest" in name and name.endswith(".json") for name in names)
    (source.parent / "synthetic-inspection.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "goal": final,
                "checkpoint": checkpoint,
                "assets": inspection,
                "zip_members": names,
            },
            indent=2,
        )
    )
    with runtime.engine.begin() as connection:
        connection.execute(delete(ProjectMemberRow))
    assert client.get(location).status_code == 404
    assert client.get(result.json()["download_url"]).status_code == 404


def test_committed_asset_inspection_fails_when_file_is_missing(api):
    client, runtime, source = api
    created = client.post(
        "/api/v1/completion-goals",
        headers={"Idempotency-Key": "missing-asset"},
        json={"job": {"input_path": str(source)}},
    )
    assert created.status_code == 202
    project_id = created.json()["goal"]["project_id"]
    (runtime.data_dir / project_id).mkdir(parents=True, exist_ok=True)
    with runtime.engine.begin() as connection:
        connection.execute(
            AssetRow.__table__.insert().values(
                id="b" * 32,
                project_id=project_id,
                status="committed",
                kind="clip_subtitle_srt",
                relative_path="artifacts/missing.srt",
                mime_type="application/x-subrip",
                input_fingerprint="c" * 64,
                sha256=hashlib.sha256(b"missing").hexdigest(),
                size_bytes=7,
            )
        )
    with pytest.raises(SecureFileMissing, match="artifact directory does not exist"):
        inspect_committed_assets(runtime)


def test_committed_asset_inspection_rejects_project_symlink_with_matching_bytes(api, tmp_path):
    client, runtime, source = api
    created = client.post(
        "/api/v1/completion-goals",
        headers={"Idempotency-Key": "symlink-asset"},
        json={"job": {"input_path": str(source)}},
    )
    assert created.status_code == 202
    project_id = created.json()["goal"]["project_id"]
    project_root = runtime.data_dir.resolve(strict=True) / project_id
    subtitle = project_root / "artifacts/matching.srt"
    subtitle.parent.mkdir(parents=True, exist_ok=True)
    content = b"1\n00:00:00,000 --> 00:00:01,000\nSynthetic subtitle\n"
    subtitle.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    with runtime.engine.begin() as connection:
        connection.execute(
            AssetRow.__table__.insert().values(
                id="d" * 32,
                project_id=project_id,
                status="committed",
                kind="clip_subtitle_srt",
                relative_path="artifacts/matching.srt",
                mime_type="application/x-subrip",
                input_fingerprint="e" * 64,
                sha256=digest,
                size_bytes=len(content),
            )
        )
    expected = [{"asset_id": "d" * 32, "sha256": digest}]
    assert inspect_committed_assets(runtime) == expected
    external = tmp_path / "external-project"
    assert not external.resolve().is_relative_to(runtime.data_dir.resolve())
    project_root.rename(external)
    project_root.symlink_to(external, target_is_directory=True)
    assert project_root.is_symlink()
    assert subtitle.read_bytes() == content
    with pytest.raises(SecureFileError, match=r"^artifact directory chain is not symlink-free$"):
        inspect_committed_assets(runtime)
    project_root.unlink()
    external.rename(project_root)
    assert inspect_committed_assets(runtime) == expected
