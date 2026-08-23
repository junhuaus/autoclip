from __future__ import annotations

import io
import json
import logging
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from liveclip.api.app import create_app
from liveclip.application.edit_packages import EditPackageConflict
from liveclip.application.pipeline import LeaseIdentity
from liveclip.application.storage import ProjectPurgeCommand
from liveclip.application.workspace import WorkspaceUser
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.edit_package_repository import SqlAlchemyEditPackageRepository
from liveclip.db.models import ProjectRow, WorkspaceUserRow
from liveclip.domain.project_lifecycle import ProjectLifecycle
from liveclip.domain.state_transitions import (
    DeliveryStatus,
    EditPackageStatus,
    FailureClass,
    PipelineRunStatus,
    RenderStatus,
    TaskKind,
    TaskStatus,
)
from liveclip.services.demo_media import create_demo_source

pytestmark = pytest.mark.integration


def test_api_reports_and_blocks_unconfigured_real_processing_providers(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    import_source = media_root / "deferred-ingest.mp4"
    import_source.write_bytes(b"not probed until the leased ingest task runs")
    settings = Settings(
        data_dir=tmp_path / "projects",
        allowed_media_roots_raw=str(media_root),
        ai_provider="openai-codex",
        openai_api_key=None,
        codex_executable="/definitely/missing/codex",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            health = client.get("/api/v1/health")
            assert health.status_code == 200
            assert health.json()["providers"]["processing_ready"] is False
            assert health.json()["providers"]["blocking_issues"] == [
                "OPENAI_ASR_NOT_CONFIGURED",
                "CODEX_CLI_NOT_READY",
            ]

            rejected = client.post(
                "/api/v1/jobs",
                json={"input_path": "/not/an/allowed/source.mp4"},
            )
            assert rejected.status_code == 503
            assert rejected.json()["error"]["code"] == "PROVIDER_NOT_READY"
            assert "OPENAI_API_KEY" not in rejected.text

            imported = client.post(
                "/api/v1/projects/import",
                json={"input_path": str(import_source)},
            )
            assert imported.status_code == 202
            assert imported.json()["status"] == "queued"
            assert len(client.get("/api/v1/projects").json()) == 1
    finally:
        runtime.close()


def test_idempotency_replay_survives_provider_becoming_unavailable(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = media_root / "idempotent-source.mp4"
    source.write_bytes(b"leased ingest has not started")
    data_dir = tmp_path / "projects"
    body = {"input_path": str(source), "top_n": 2}
    headers = {"Idempotency-Key": "provider-readiness-replay-001"}

    ready_settings = Settings(
        data_dir=data_dir,
        allowed_media_roots_raw=str(media_root),
        ai_provider="mock",
        _env_file=None,
    )
    ready_runtime = LiveClipRuntime.open(ready_settings, project_root=project_root)
    try:
        with TestClient(
            create_app(ready_settings, runtime=ready_runtime, project_root=project_root),
            raise_server_exceptions=False,
        ) as client:
            created = client.post("/api/v1/jobs", headers=headers, json=body)
            assert created.status_code == 202
            original = created.json()
    finally:
        ready_runtime.close()

    unavailable_settings = Settings(
        data_dir=data_dir,
        allowed_media_roots_raw=str(media_root),
        ai_provider="openrouter-codex",
        openrouter_api_key=None,
        codex_executable="/definitely/missing/codex",
        _env_file=None,
    )
    unavailable_runtime = LiveClipRuntime.open(unavailable_settings, project_root=project_root)
    try:
        with TestClient(
            create_app(
                unavailable_settings,
                runtime=unavailable_runtime,
                project_root=project_root,
            ),
            raise_server_exceptions=False,
        ) as client:
            replay = client.post("/api/v1/jobs", headers=headers, json=body)
            assert replay.status_code == 202
            assert replay.json()["project_id"] == original["project_id"]
            assert replay.json()["run_id"] == original["run_id"]

            conflict = client.post(
                "/api/v1/jobs",
                headers=headers,
                json={**body, "top_n": 3},
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

            new_request = client.post("/api/v1/jobs", json=body)
            assert new_request.status_code == 503
            assert new_request.json()["error"]["code"] == "PROVIDER_NOT_READY"
    finally:
        unavailable_runtime.close()


def test_workspace_members_only_see_assigned_projects(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = media_root / "team-source.mp4"
    source.write_bytes(b"pipeline task is intentionally not leased")
    admin_token = "admin-workspace-token"
    editor_token = "editor-workspace-token"
    outsider_token = "outsider-workspace-token"
    settings = Settings(
        data_dir=tmp_path / "projects",
        allowed_media_roots_raw=str(media_root),
        api_token=SecretStr(admin_token),
        workspace_tokens_raw=json.dumps(
            {
                "lin-editor": editor_token,
                "wang-review": outsider_token,
            }
        ),
        ai_provider="mock",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    admin_auth = {"Authorization": f"Bearer {admin_token}"}
    editor_auth = {"Authorization": f"Bearer {editor_token}"}
    outsider_auth = {"Authorization": f"Bearer {outsider_token}"}
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            created = client.post(
                "/api/v1/projects/import",
                headers=admin_auth,
                json={"input_path": str(source)},
            )
            assert created.status_code == 202
            project_id = str(created.json()["project_id"])
            assert (
                client.get("/api/v1/session", headers=editor_auth).json()["user"]["username"]
                == "lin-editor"
            )
            assert client.get("/api/v1/projects", headers=editor_auth).json() == []
            editor_project = client.get(f"/api/v1/projects/{project_id}", headers=editor_auth)
            assert editor_project.status_code == 404

            added = client.post(
                f"/api/v1/projects/{project_id}/members",
                headers=admin_auth,
                json={
                    "username": "lin-editor",
                    "display_name": "林编辑",
                    "role": "editor",
                },
            )
            assert added.status_code == 200
            assert [member["role"] for member in added.json()["members"]] == [
                "owner",
                "editor",
            ]
            editor_projects = client.get("/api/v1/projects", headers=editor_auth)
            assert editor_projects.status_code == 200
            assert [item["project_id"] for item in editor_projects.json()] == [project_id]
            assert editor_projects.json()[0]["current_user_role"] == "editor"
            assert editor_projects.json()[0]["allowed_actions"] == [
                "read",
                "run_pipeline",
                "edit_clip",
                "comment",
                "render",
                "export",
                "deliver",
                "manage_release",
            ]
            assert client.get("/api/v1/projects", headers=outsider_auth).json() == []

            forbidden = client.post(
                f"/api/v1/projects/{project_id}/members",
                headers=editor_auth,
                json={
                    "username": "wang-review",
                    "display_name": "王审核",
                    "role": "reviewer",
                },
            )
            assert forbidden.status_code == 403
            assert forbidden.json()["error"]["code"] == "PROJECT_ACTION_DENIED"

            transferred = client.post(
                f"/api/v1/projects/{project_id}/ownership-transfer",
                headers=admin_auth,
                json={"new_owner_user_id": added.json()["members"][1]["user_id"]},
            )
            assert transferred.status_code == 200
            assert [member["role"] for member in transferred.json()["members"]] == [
                "owner",
                "editor",
            ]
            transferred_project = client.get(f"/api/v1/projects/{project_id}", headers=editor_auth)
            assert transferred_project.json()["current_user_role"] == "owner"
            assert transferred_project.json()["owner"]["username"] == "lin-editor"
    finally:
        runtime.close()


def test_authenticated_mock_api_review_render_delivery_and_range_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    source_path = media_root / "api-source.mp4"
    data_dir = tmp_path / "projects"
    create_demo_source(output_path=source_path, duration_ms=16_000)
    token = "test-api-token-never-return"
    outsider_token = "test-outsider-token-never-return"
    release_editor_token = "test-release-editor-token-never-return"
    settings = Settings(
        data_dir=data_dir,
        allowed_media_roots_raw=str(media_root),
        api_token=SecretStr(token),
        workspace_tokens_raw=json.dumps(
            {
                "outsider": outsider_token,
                "release-editor": release_editor_token,
            }
        ),
        ai_provider="mock",
        min_clip_seconds=8,
        max_clip_seconds=12,
        preview_render_width=270,
        preview_render_height=480,
        final_render_width=360,
        final_render_height=640,
        video_encoder="libx264",
        worker_lease_seconds=30,
        worker_heartbeat_seconds=5,
        max_stage_retries=1,
        cors_origins_raw="http://127.0.0.1:5173",
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    auth = {"Authorization": f"Bearer {token}"}
    outsider_auth = {"Authorization": f"Bearer {outsider_token}"}
    release_editor_auth = {"Authorization": f"Bearer {release_editor_token}"}
    idempotency_key = "api-job-once-001"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            health = client.get("/api/v1/health")
            assert health.status_code == 200
            assert health.json()["database"] == "ok"
            assert health.json()["providers"] == {
                "mode": "mock",
                "asr_provider": "mock",
                "llm_provider": "mock",
                "asr_ready": True,
                "llm_ready": True,
                "processing_ready": True,
                "blocking_issues": [],
                "warnings": ["MOCK_ASR_SELECTED", "MOCK_LLM_SELECTED"],
            }

            unauthorized = client.get("/api/v1/projects")
            assert unauthorized.status_code == 401
            assert unauthorized.headers["www-authenticate"] == "Bearer"
            assert unauthorized.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

            preflight = client.options(
                "/api/v1/jobs",
                headers={
                    "Origin": "http://127.0.0.1:5173",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,idempotency-key,content-type",
                },
            )
            assert preflight.status_code == 200
            assert preflight.headers["access-control-allow-origin"] == ("http://127.0.0.1:5173")
            rejected_preflight = client.options(
                "/api/v1/jobs",
                headers={
                    "Origin": "https://untrusted.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert rejected_preflight.status_code == 400
            assert rejected_preflight.json()["error"]["code"] == "CORS_PREFLIGHT_REJECTED"
            assert (
                rejected_preflight.json()["error"]["correlation_id"]
                == (rejected_preflight.headers["x-request-id"])
            )
            assert "access-control-allow-origin" not in rejected_preflight.headers

            unknown_route = client.get("/api/v1/does-not-exist", headers=auth)
            assert unknown_route.status_code == 404
            assert unknown_route.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
            assert (
                unknown_route.json()["error"]["correlation_id"]
                == unknown_route.headers["x-request-id"]
            )
            wrong_method = client.put("/api/v1/health")
            assert wrong_method.status_code == 405
            assert wrong_method.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
            assert (
                wrong_method.json()["error"]["correlation_id"]
                == wrong_method.headers["x-request-id"]
            )

            body = {
                "input_path": str(source_path.resolve()),
                "top_n": 1,
                "minimum_clip_seconds": 8,
                "maximum_clip_seconds": 12,
            }
            created = client.post(
                "/api/v1/jobs",
                headers={**auth, "Idempotency-Key": idempotency_key},
                json=body,
            )
            assert created.status_code == 202
            assert created.headers["location"] == created.json()["status_url"]
            assert created.headers["retry-after"] == "1"
            assert created.json()["status"] == "queued"
            project_id = str(created.json()["project_id"])
            run_id = str(created.json()["run_id"])
            release_editor = client.post(
                f"/api/v1/projects/{project_id}/members",
                headers=auth,
                json={
                    "username": "release-editor",
                    "display_name": "发布编辑",
                    "role": "editor",
                },
            )
            assert release_editor.status_code == 200
            release_editor_user_id = next(
                member["user_id"]
                for member in release_editor.json()["members"]
                if member["username"] == "release-editor"
            )

            completed = runtime.stage_runner.run_until_terminal(
                run_id,
                worker_id="api-pipeline-worker",
            )
            assert completed.status == PipelineRunStatus.COMPLETED

            replay = client.post(
                "/api/v1/jobs",
                headers={**auth, "Idempotency-Key": idempotency_key},
                json=body,
            )
            assert replay.status_code == 202
            assert replay.json()["project_id"] == project_id
            assert replay.json()["run_id"] == run_id
            assert replay.json()["status"] == "completed"
            conflict = client.post(
                "/api/v1/jobs",
                headers={**auth, "Idempotency-Key": idempotency_key},
                json={**body, "top_n": 2},
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

            job = client.get(f"/api/v1/jobs/{run_id}", headers=auth)
            run = client.get(f"/api/v1/runs/{run_id}", headers=auth)
            assert job.json() == run.json()
            assert run.json()["progress"] == 100
            assert {stage["status"] for stage in run.json()["stages"]} == {"succeeded"}
            projects = client.get("/api/v1/projects", headers=auth)
            assert projects.status_code == 200
            assert [item["project_id"] for item in projects.json()] == [project_id]
            transcript = client.get(
                f"/api/v1/projects/{project_id}/transcript",
                headers=auth,
            )
            assert transcript.status_code == 200
            assert len(transcript.json()["segments"]) >= 3

            clips = client.get(f"/api/v1/projects/{project_id}/clips", headers=auth)
            assert clips.status_code == 200
            assert len(clips.json()) == 1
            clip_summary = clips.json()[0]
            clip_id = str(clip_summary["clip"]["clip_id"])
            detail = client.get(f"/api/v1/clips/{clip_id}", headers=auth)
            assert detail.status_code == 200
            assert clip_summary["clip"]["hook"] == detail.json()["clip"]["plan"]["hook"]
            assert clip_summary["clip"]["captions"]
            assert clip_summary["clip"]["keywords"]
            for keyword in clip_summary["clip"]["keywords"]:
                assert keyword["timing_precision"] in {"word", "segment"}
                assert keyword["source_start_ms"] == (
                    clip_summary["clip"]["source_start_ms"] + keyword["clip_start_ms"]
                )
                assert keyword["source_end_ms"] == (
                    clip_summary["clip"]["source_start_ms"] + keyword["clip_end_ms"]
                )
            proxy_url = str(clip_summary["proxy_media_url"])
            assert token not in proxy_url
            proxy_range = client.get(proxy_url, headers={"Range": "bytes=0-99"})
            assert proxy_range.status_code == 206
            assert len(proxy_range.content) == 100
            assert proxy_range.headers["content-range"].startswith("bytes 0-99/")
            invalid_range = client.get(proxy_url, headers={"Range": "bytes=0-1,3-4"})
            assert invalid_range.status_code == 416
            assert invalid_range.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"

            # Selection-first delivery: the persisted review status is the single
            # source of truth for which clips may enter a package.
            initial_selection = client.post(
                f"/api/v1/projects/{project_id}/reviews/batch",
                headers={**auth, "Idempotency-Key": "api-initial-selection-001"},
                json={
                    "items": [
                        {
                            "clip_id": clip_id,
                            "expected_revision": 1,
                            "status": "approved",
                        }
                    ]
                },
            )
            assert initial_selection.status_code == 200

            initial_package_body = {
                "items": [{"clip_id": clip_id, "expected_revision": 1}],
                "preset": "clean_editing",
                "content": "full",
                "include_zip": True,
            }
            initial_package = client.post(
                f"/api/v1/projects/{project_id}/edit-packages",
                headers={**auth, "Idempotency-Key": "api-initial-edit-package-001"},
                json=initial_package_body,
            )
            assert initial_package.status_code == 202, initial_package.text
            completed_initial_package = runtime.delivery_runner.run_edit_package_until_terminal(
                str(initial_package.json()["resource_id"]),
                worker_id="api-initial-edit-package-worker",
            )
            assert completed_initial_package.status == EditPackageStatus.SUCCEEDED
            initial_package_replay = client.post(
                f"/api/v1/projects/{project_id}/edit-packages",
                headers={**auth, "Idempotency-Key": "api-initial-edit-package-001"},
                json=initial_package_body,
            )
            assert initial_package_replay.status_code == 202
            assert (
                initial_package_replay.json()["resource_id"]
                == initial_package.json()["resource_id"]
            )
            initial_package_conflict = client.post(
                f"/api/v1/projects/{project_id}/edit-packages",
                headers={**auth, "Idempotency-Key": "api-initial-edit-package-001"},
                json={**initial_package_body, "content": "metadata_only"},
            )
            assert initial_package_conflict.status_code == 409

            database = sqlite3.connect(runtime.database_path)
            try:
                proxy_row = database.execute(
                    """
                    SELECT id, spec_json
                    FROM render_jobs
                    WHERE candidate_clip_id = ? AND kind = 'proxy'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (clip_id,),
                ).fetchone()
                assert proxy_row is not None
                proxy_render_id, clean_spec_json = proxy_row
                database.execute(
                    "UPDATE render_jobs SET spec_json = ? WHERE id = ?",
                    (
                        json.dumps(
                            {
                                "schema_version": "2",
                                "renderer": "ffmpeg-renderer-v1",
                            }
                        ),
                        proxy_render_id,
                    ),
                )
                database.commit()

                legacy_summary = client.get(
                    f"/api/v1/projects/{project_id}/clips", headers=auth
                ).json()[0]
                assert legacy_summary["clip"]["proxy_status"] == "stale"
                assert legacy_summary["proxy_media_url"] is None
                legacy_detail = client.get(f"/api/v1/clips/{clip_id}", headers=auth).json()
                legacy_render = next(
                    item
                    for item in legacy_detail["clip"]["renders"]
                    if item["render_id"] == proxy_render_id
                )
                assert legacy_render["status"] == "stale"
                assert legacy_render["video_asset_id"] is None
                assert legacy_render["contact_sheet_asset_id"] is None
                assert legacy_detail["asset_urls"] == {}

                database.execute(
                    "UPDATE render_jobs SET spec_json = ? WHERE id = ?",
                    (clean_spec_json, proxy_render_id),
                )
                database.commit()
            finally:
                database.close()

            clip = client.get(f"/api/v1/clips/{clip_id}", headers=auth)
            assert clip.status_code == 200
            assert clip.json()["clip"]["current_revision"] == 1
            original_clip = clip.json()["clip"]
            empty_captions = client.patch(
                f"/api/v1/clips/{clip_id}",
                headers=auth,
                json={"expected_revision": 1, "captions": []},
            )
            assert empty_captions.status_code == 422
            assert empty_captions.json()["error"]["code"] == "INVALID_REQUEST"
            nul_caption = client.patch(
                f"/api/v1/clips/{clip_id}",
                headers=auth,
                json={
                    "expected_revision": 1,
                    "captions": [{"start_ms": 0, "end_ms": 1_000, "text": "bad\x00cue"}],
                },
            )
            assert nul_caption.status_code == 422
            assert nul_caption.json()["error"]["code"] == "DOMAIN_VALIDATION_FAILED"
            assert (
                client.get(f"/api/v1/clips/{clip_id}", headers=auth).json()["clip"][
                    "current_revision"
                ]
                == 1
            )
            old_start = int(original_clip["plan"]["source_start_ms"])
            old_end = int(original_clip["plan"]["source_end_ms"])
            shift_ms = 100 if old_end + 100 <= int(original_clip["allowed_end_ms"]) else -100
            new_start = old_start + shift_ms
            new_end = old_end + shift_ms
            edited = client.patch(
                f"/api/v1/clips/{clip_id}",
                headers=auth,
                json={
                    "expected_revision": 1,
                    "source_start_ms": new_start,
                    "source_end_ms": new_end,
                    "title": "API 编辑草稿",
                },
            )
            assert edited.status_code == 200
            assert edited.json()["clip"]["current_revision"] == 2
            assert edited.json()["clip"]["review"]["status"] == "pending_review"
            expected_captions = [
                {
                    "start_ms": max(int(segment["start_ms"]), new_start) - new_start,
                    "end_ms": min(int(segment["end_ms"]), new_end) - new_start,
                    "text": segment["text"],
                }
                for segment in transcript.json()["segments"]
                if int(segment["end_ms"]) > new_start
                and int(segment["start_ms"]) < new_end
                and min(int(segment["end_ms"]), new_end) - max(int(segment["start_ms"]), new_start)
                >= 250
            ]
            assert edited.json()["clip"]["captions"] == expected_captions
            assert all(
                int(cue["end_ms"]) - int(cue["start_ms"]) >= 250
                for cue in edited.json()["clip"]["captions"]
            )
            reviewed = client.post(
                f"/api/v1/clips/{clip_id}/review",
                headers=auth,
                json={
                    "expected_revision": 2,
                    "status": "approved",
                    "title": "API 人工确认高光",
                },
            )
            assert reviewed.status_code == 200
            assert reviewed.json()["clip"]["current_revision"] == 3
            assert reviewed.json()["clip"]["review"]["status"] == "approved"
            assert {item["status"] for item in reviewed.json()["clip"]["renders"]} == {"stale"}
            batch_review = client.post(
                f"/api/v1/projects/{project_id}/reviews/batch",
                headers={**auth, "Idempotency-Key": "api-batch-review-001"},
                json={
                    "items": [
                        {
                            "clip_id": clip_id,
                            "expected_revision": 3,
                            "status": "approved",
                        }
                    ]
                },
            )
            assert batch_review.status_code == 200
            assert batch_review.json()["clips"][0]["clip"]["review"]["status"] == "approved"
            assert (
                client.post(
                    f"/api/v1/projects/{project_id}/reviews/batch",
                    headers={**auth, "Idempotency-Key": "api-batch-review-001"},
                    json={
                        "items": [
                            {
                                "clip_id": clip_id,
                                "expected_revision": 3,
                                "status": "rejected",
                                "reason": "同一幂等键不能改变请求",
                            }
                        ]
                    },
                ).status_code
                == 409
            )
            stale_patch = client.patch(
                f"/api/v1/clips/{clip_id}",
                headers=auth,
                json={"expected_revision": 1, "title": "过期修改"},
            )
            assert stale_patch.status_code == 409

            render_body = {"expected_revision": 3, "kind": "final"}
            queued_render = client.post(
                f"/api/v1/clips/{clip_id}/render",
                headers={**auth, "Idempotency-Key": "api-final-render-001"},
                json=render_body,
            )
            assert queued_render.status_code == 202
            render_id = str(queued_render.json()["resource_id"])
            assert queued_render.headers["location"] == f"/api/v1/renders/{render_id}"
            final = runtime.render_runner.run_until_terminal(
                render_id,
                worker_id="api-render-worker",
            )
            assert final.status == RenderStatus.SUCCEEDED
            render_status = client.get(f"/api/v1/renders/{render_id}", headers=auth)
            assert render_status.json()["status"] == "succeeded"

            queued_proxy = client.post(
                f"/api/v1/clips/{clip_id}/render",
                headers={**auth, "Idempotency-Key": "api-clean-proxy-r3-001"},
                json={"expected_revision": 3, "kind": "proxy"},
            )
            assert queued_proxy.status_code == 202
            proxy_render = runtime.render_runner.run_until_terminal(
                str(queued_proxy.json()["resource_id"]),
                worker_id="api-clean-proxy-worker",
            )
            assert proxy_render.status == RenderStatus.SUCCEEDED
            current_summary = client.get(
                f"/api/v1/projects/{project_id}/clips",
                headers=auth,
            ).json()[0]
            assert current_summary["clip"]["proxy_status"] == "succeeded"
            assert current_summary["download_video_url"]
            assert current_summary["download_subtitle_url"]
            downloaded_clip = client.get(
                current_summary["download_video_url"],
                headers={"Range": "bytes=0-99"},
            )
            assert downloaded_clip.status_code == 206
            assert len(downloaded_clip.content) == 100
            assert downloaded_clip.headers["content-disposition"].endswith('.mp4"')
            downloaded_srt = client.get(current_summary["download_subtitle_url"])
            assert downloaded_srt.status_code == 200
            assert not downloaded_srt.content.startswith(b"\xef\xbb\xbf")
            assert b"-->" in downloaded_srt.content

            queued_package = client.post(
                f"/api/v1/projects/{project_id}/edit-packages",
                headers={**auth, "Idempotency-Key": "api-edit-package-001"},
                json={
                    "items": [{"clip_id": clip_id, "expected_revision": 3}],
                    "preset": "clean_editing",
                    "content": "full",
                    "include_zip": True,
                },
            )
            assert queued_package.status_code == 202
            assert queued_package.json()["resource_type"] == "edit_package"
            package_id = str(queued_package.json()["resource_id"])
            completed_package = runtime.delivery_runner.run_edit_package_until_terminal(
                package_id,
                worker_id="api-edit-package-worker",
            )
            assert completed_package.status == EditPackageStatus.SUCCEEDED
            package_detail = client.get(
                f"/api/v1/edit-packages/{package_id}",
                headers=auth,
            )
            assert package_detail.status_code == 200
            assert (
                client.get(
                    f"/api/v1/edit-packages/{package_id}",
                    headers=outsider_auth,
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"/api/v1/edit-packages/{package_id}/download",
                    headers=outsider_auth,
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"/api/v1/clips/{clip_id}/download/video",
                    headers=outsider_auth,
                ).status_code
                == 404
            )
            package_zip = client.get(package_detail.json()["download_url"])
            assert package_zip.status_code == 200
            assert package_zip.headers["content-disposition"].endswith(
                'filename="liveclip-edit-package-v002.zip"'
            )
            with zipfile.ZipFile(io.BytesIO(package_zip.content)) as archive:
                assert archive.testzip() is None
                package_names = set(archive.namelist())
                assert "manifest.json" in package_names
                assert "metadata/clips.json" in package_names
                assert "metadata/clips.csv" in package_names
                assert "metadata/README-导入剪映.txt" in package_names
                assert any(
                    name.startswith("media/") and name.endswith(".mp4") for name in package_names
                )
                assert any(
                    name.startswith("subtitles/") and name.endswith(".srt")
                    for name in package_names
                )
                package_manifest = json.loads(archive.read("manifest.json"))
                assert package_manifest["schema_version"] == "liveclip.edit-package.v1"
                assert package_manifest["clips"][0]["high_impact_sentence"]
                assert package_manifest["clips"][0]["keywords"]
                subtitle_name = str(package_manifest["clips"][0]["subtitle_filename"])
                assert not archive.read(subtitle_name).startswith(b"\xef\xbb\xbf")
            package_list = client.get(
                f"/api/v1/projects/{project_id}/edit-packages",
                headers=auth,
            )
            assert [item["edit_package"]["edit_package_id"] for item in package_list.json()] == [
                package_id,
                initial_package.json()["resource_id"],
            ]

            delivery = client.post(
                f"/api/v1/projects/{project_id}/deliveries",
                headers={**auth, "Idempotency-Key": "api-delivery-001"},
                json={"include_zip": True},
            )
            assert delivery.status_code == 202
            delivery_id = str(delivery.json()["resource_id"])
            completed_delivery = runtime.delivery_runner.run_until_terminal(
                delivery_id,
                worker_id="api-delivery-worker",
            )
            assert completed_delivery.status == DeliveryStatus.SUCCEEDED
            delivery_detail = client.get(
                f"/api/v1/deliveries/{delivery_id}",
                headers=auth,
            )
            assert delivery_detail.status_code == 200
            download_url = str(delivery_detail.json()["download_url"])
            assert token not in download_url
            downloaded = client.get(download_url)
            assert downloaded.status_code == 200
            assert downloaded.headers["content-disposition"].endswith(
                'filename="liveclip-v001.zip"'
            )
            with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
                assert archive.testzip() is None
                names = set(archive.namelist())
                assert "manifest.json" in names
                manifest = json.loads(archive.read("manifest.json"))
                assert manifest["project_id"] == project_id
            zip_asset_id = delivery_detail.json()["delivery"]["zip_asset_id"]
            unscoped_zip = client.get(f"/api/v1/media/{zip_asset_id}", headers=auth)
            assert unscoped_zip.status_code == 404
            deliveries = client.get(
                f"/api/v1/projects/{project_id}/deliveries",
                headers=auth,
            )
            assert len(deliveries.json()) == 1
            project = client.get(f"/api/v1/projects/{project_id}", headers=auth)
            assert project.json()["status"] == "delivered"

            presets = client.get("/api/v1/release-presets", headers=auth)
            assert presets.status_code == 200
            assert {item["platform"] for item in presets.json()["presets"]} == {
                "douyin",
                "xiaohongshu",
                "bilibili_vertical",
                "youtube_shorts",
                "tiktok",
                "generic_vertical",
            }
            assert presets.json()["current_versions"]["generic_vertical"] == "2026-08-15.1"
            release_created = client.post(
                f"/api/v1/projects/{project_id}/releases",
                headers={**auth, "Idempotency-Key": "api-release-item-001"},
                json={
                    "clip_id": clip_id,
                    "expected_revision": 3,
                    "platform": "generic_vertical",
                    "account_label": "官方主账号",
                    "caption_mode": "burned",
                    "assignee_user_id": None,
                    "planned_publish_at": "2026-08-16T12:00:00+08:00",
                },
            )
            assert release_created.status_code == 201
            release_id = str(release_created.json()["release_item_id"])
            assert release_created.headers["location"] == f"/api/v1/releases/{release_id}"
            release_replay = client.post(
                f"/api/v1/projects/{project_id}/releases",
                headers={**auth, "Idempotency-Key": "api-release-item-001"},
                json={
                    "clip_id": clip_id,
                    "expected_revision": 3,
                    "platform": "generic_vertical",
                    "account_label": "官方主账号",
                    "caption_mode": "burned",
                    "assignee_user_id": None,
                    "planned_publish_at": "2026-08-16T12:00:00+08:00",
                },
            )
            assert release_replay.status_code == 201
            assert release_replay.json()["release_item_id"] == release_id
            illegal_release = client.post(
                f"/api/v1/releases/{release_id}/status",
                headers=auth,
                json={
                    "expected_management_version": release_created.json()["management_version"],
                    "target": "published",
                    "release_package_id": "not-yet-created",
                    "external_id": "must-not-skip-workflow",
                    "published_at": "2026-08-15T08:05:00+00:00",
                },
            )
            assert illegal_release.status_code == 409
            assert illegal_release.json()["error"]["code"] == "STATE_CONFLICT"
            assert (
                client.get(f"/api/v1/releases/{release_id}", headers=outsider_auth).status_code
                == 404
            )

            release = release_created.json()
            release_updated = client.patch(
                f"/api/v1/releases/{release_id}",
                headers=auth,
                json={
                    "expected_management_version": release["management_version"],
                    "edit_plan_revision": 3,
                    "title": "API 发布高光",
                    "title_variants": ["API 发布高光备选"],
                    "description": "这是准备发布到短视频平台的完整说明。",
                    "hashtags": ["直播", "高光"],
                    "cta": "关注获取更多内容",
                    "caption_mode": "burned",
                    "cover_time_ms": 1_000,
                    "assignee_user_id": None,
                    "planned_publish_at": "2026-08-16T12:00:00+08:00",
                    "checklist": {
                        "hook_confirmed": True,
                        "first_frame_confirmed": True,
                        "subtitles_confirmed": True,
                        "music_rights_confirmed": True,
                        "likeness_confirmed": True,
                        "personal_data_confirmed": True,
                        "claims_confirmed": True,
                        "sponsorship_confirmed": True,
                        "platform_policy_confirmed": True,
                    },
                },
            )
            assert release_updated.status_code == 200
            release = release_updated.json()
            assert release["preflight"]["blocker_count"] == 1
            assert (
                next(
                    check
                    for check in release["preflight"]["checks"]
                    if check["code"] == "release_approval"
                )["outcome"]
                == "blocked"
            )

            pending_approval = client.post(
                f"/api/v1/releases/{release_id}/approval",
                headers=auth,
                json={
                    "expected_management_version": release["management_version"],
                    "target": "pending_review",
                    "reason": "提交发布审核",
                },
            )
            assert pending_approval.status_code == 200
            approved_release = client.post(
                f"/api/v1/releases/{release_id}/approval",
                headers=auth,
                json={
                    "expected_management_version": pending_approval.json()["management_version"],
                    "target": "approved",
                    "reason": "发布审核通过",
                },
            )
            assert approved_release.status_code == 200
            assert approved_release.json()["preflight"]["passed"] is True
            editor_revoke = client.post(
                f"/api/v1/releases/{release_id}/approval",
                headers=release_editor_auth,
                json={
                    "expected_management_version": approved_release.json()["management_version"],
                    "target": "draft",
                    "reason": "编辑者不能绕过发布审核人撤销批准",
                },
            )
            assert editor_revoke.status_code == 403
            assert editor_revoke.json()["error"]["code"] == "PROJECT_ACTION_DENIED"
            ready_release = client.post(
                f"/api/v1/releases/{release_id}/status",
                headers=auth,
                json={
                    "expected_management_version": approved_release.json()["management_version"],
                    "target": "ready",
                },
            )
            assert ready_release.status_code == 200
            scheduled_release = client.post(
                f"/api/v1/releases/{release_id}/status",
                headers=auth,
                json={
                    "expected_management_version": ready_release.json()["management_version"],
                    "target": "scheduled_external",
                },
            )
            assert scheduled_release.status_code == 200

            release_package = client.post(
                f"/api/v1/releases/{release_id}/packages",
                headers={**auth, "Idempotency-Key": "api-release-package-001"},
                json={
                    "expected_release_item_version": scheduled_release.json()["management_version"],
                    "include_zip": True,
                },
            )
            assert release_package.status_code == 202
            assert release_package.json()["resource_type"] == "release_package"
            release_package_id = str(release_package.json()["resource_id"])
            completed_release_package = runtime.delivery_runner.run_release_package_until_terminal(
                release_package_id,
                worker_id="api-release-package-worker",
            )
            assert completed_release_package.status.value == "succeeded"
            release_package_detail = client.get(
                f"/api/v1/release-packages/{release_package_id}",
                headers=auth,
            )
            assert release_package_detail.status_code == 200
            assert release_package_detail.json()["download_kind"] == "zip"
            release_zip = client.get(release_package_detail.json()["download_url"])
            assert release_zip.status_code == 200, (
                release_zip.text,
                caplog.text,
            )
            with zipfile.ZipFile(io.BytesIO(release_zip.content)) as archive:
                assert archive.testzip() is None
                names = set(archive.namelist())
                assert "manifest.json" in names
                assert "metadata/release-copy.txt" in names
                assert "metadata/checklist.json" in names
                assert "cover/API-发布高光-cover.png" in names
                assert any(name.startswith("media/") for name in names)

            manifest_only = client.post(
                f"/api/v1/releases/{release_id}/packages",
                headers={**auth, "Idempotency-Key": "api-release-package-002"},
                json={
                    "expected_release_item_version": scheduled_release.json()["management_version"],
                    "include_zip": False,
                },
            )
            assert manifest_only.status_code == 422

            managed_project = client.get(
                f"/api/v1/projects/{project_id}",
                headers=auth,
            ).json()
            if managed_project["lifecycle"] == "editorial_review":
                managed_project = client.post(
                    f"/api/v1/projects/{project_id}/lifecycle",
                    headers=auth,
                    json={
                        "expected_management_version": managed_project["management_version"],
                        "target": "approval",
                        "reason": "剪辑已完成, 进入发布审批",
                    },
                ).json()
            if managed_project["lifecycle"] == "approval":
                managed_project = client.post(
                    f"/api/v1/projects/{project_id}/lifecycle",
                    headers=auth,
                    json={
                        "expected_management_version": managed_project["management_version"],
                        "target": "ready_to_publish",
                        "reason": "发布资产与平台包均已确认",
                    },
                ).json()
            assert managed_project["lifecycle"] == "ready_to_publish"
            future_publication = client.post(
                f"/api/v1/releases/{release_id}/status",
                headers=auth,
                json={
                    "expected_management_version": scheduled_release.json()["management_version"],
                    "target": "published",
                    "release_package_id": release_package_id,
                    "external_id": "future-must-be-rejected",
                    "published_at": "2100-01-01T00:00:00+00:00",
                },
            )
            assert future_publication.status_code == 422
            assert future_publication.json()["error"]["code"] == "INVALID_REQUEST"
            published_release = client.post(
                f"/api/v1/releases/{release_id}/status",
                headers=auth,
                json={
                    "expected_management_version": scheduled_release.json()["management_version"],
                    "target": "published",
                    "release_package_id": release_package_id,
                    "external_url": "https://example.com/posts/liveclip-api",
                    "external_id": "external-liveclip-api-001",
                    "published_at": "2026-08-15T08:05:00+00:00",
                    "result_notes": "已由运营人员在外部平台发布",
                },
            )
            assert published_release.status_code == 200
            assert published_release.json()["status"] == "published"
            assert (
                published_release.json()["publication_evidence"]["release_package_id"]
                == release_package_id
            )
            assert published_release.json()["publication_evidence"]["video_sha256"]
            assert (
                client.get(f"/api/v1/projects/{project_id}", headers=auth).json()["lifecycle"]
                == "published"
            )
            early_metric = client.post(
                f"/api/v1/releases/{release_id}/metrics",
                headers={**auth, "Idempotency-Key": "api-release-metric-too-early"},
                json={"captured_at": "1900-01-01T00:00:00+00:00", "views": 1},
            )
            assert early_metric.status_code == 409
            assert early_metric.json()["error"]["code"] == "STATE_CONFLICT"
            oversized_metric = client.post(
                f"/api/v1/releases/{release_id}/metrics",
                headers={**auth, "Idempotency-Key": "api-release-metric-too-large"},
                json={
                    "captured_at": "2026-08-15T09:00:00+00:00",
                    "views": 9_223_372_036_854_775_808,
                },
            )
            assert oversized_metric.status_code == 422
            assert oversized_metric.json()["error"]["code"] == "INVALID_REQUEST"
            for index, captured_at in enumerate(
                (
                    "9999-12-31T23:59:59-23:00",
                    "0001-01-01T00:00:00+23:00",
                )
            ):
                out_of_range_metric = client.post(
                    f"/api/v1/releases/{release_id}/metrics",
                    headers={
                        **auth,
                        "Idempotency-Key": f"api-release-metric-out-of-range-{index}",
                    },
                    json={"captured_at": captured_at, "views": 1},
                )
                assert out_of_range_metric.status_code == 422
                assert out_of_range_metric.json()["error"]["code"] == "INVALID_REQUEST"
            metric_body = {
                "captured_at": "2026-08-15T09:00:00+00:00",
                "views": 12_345,
                "likes": 678,
                "comments": 45,
                "shares": 32,
                "saves": 88,
                "followers_gained": 21,
                "notes": "发布后 24 小时快照",
            }
            metric = client.post(
                f"/api/v1/releases/{release_id}/metrics",
                headers={**auth, "Idempotency-Key": "api-release-metric-001"},
                json=metric_body,
            )
            assert metric.status_code == 201
            assert metric.json()["metrics"][0]["views"] == 12_345
            metric_replay = client.post(
                f"/api/v1/releases/{release_id}/metrics",
                headers={**auth, "Idempotency-Key": "api-release-metric-001"},
                json=metric_body,
            )
            assert metric_replay.status_code == 201
            assert len(metric_replay.json()["metrics"]) == 1
            release_list = client.get(
                f"/api/v1/projects/{project_id}/releases",
                headers=auth,
            )
            assert release_list.status_code == 200
            assert [item["release_item_id"] for item in release_list.json()["releases"]] == [
                release_id
            ]
            preview_asset_id = published_release.json()["preview_asset_id"]
            assert preview_asset_id is not None
            assert (
                f"/api/v1/media/{preview_asset_id}"
                in release_list.json()["preview_media_urls"][release_id]
            )

            imported = client.post(
                "/api/v1/projects/import",
                headers={**auth, "Idempotency-Key": "api-import-001"},
                json=body,
            )
            assert imported.status_code == 202
            imported_project_id = str(imported.json()["project_id"])
            imported_run_id = str(imported.json()["run_id"])
            imported_run = runtime.stage_runner.run_until_terminal(
                imported_run_id,
                worker_id="api-import-worker",
            )
            assert imported_run.status == PipelineRunStatus.COMPLETED
            assert [stage.status.value for stage in imported_run.stages] == [
                "succeeded",
                "skipped",
                "skipped",
                "skipped",
                "skipped",
                "skipped",
            ]
            imported_project = client.get(
                f"/api/v1/projects/{imported_project_id}",
                headers=auth,
            )
            assert imported_project.json()["status"] == "imported"
            second_run = client.post(
                f"/api/v1/projects/{imported_project_id}/runs",
                headers={**auth, "Idempotency-Key": "api-second-run-001"},
                json={
                    "top_n": 1,
                    "minimum_clip_seconds": 8,
                    "maximum_clip_seconds": 12,
                },
            )
            assert second_run.status_code == 202
            second_run_id = str(second_run.json()["run_id"])
            cancelled = client.post(
                f"/api/v1/runs/{second_run_id}/cancel",
                headers=auth,
            )
            assert cancelled.status_code == 202
            assert cancelled.json()["status"] == "cancelled"

            permission_package = client.post(
                f"/api/v1/projects/{project_id}/edit-packages",
                headers={
                    **release_editor_auth,
                    "Idempotency-Key": "api-edit-package-permission-fence-001",
                },
                json={
                    "items": [{"clip_id": clip_id, "expected_revision": 3}],
                    "preset": "clean_editing",
                    "content": "metadata_only",
                    "include_zip": True,
                },
            )
            assert permission_package.status_code == 202
            claimed_permission_package = runtime.task_queue.claim(
                worker_id="api-permission-fence-worker",
                task_kind=TaskKind.DELIVERY,
            )
            assert claimed_permission_package is not None
            assert claimed_permission_package.target_id == permission_package.json()["resource_id"]
            permission_lease = LeaseIdentity(
                task_id=claimed_permission_package.task_id,
                worker_id=claimed_permission_package.worker_id,
                lease_token=claimed_permission_package.lease_token,
            )
            edit_package_repository = SqlAlchemyEditPackageRepository(runtime.engine)
            permission_work = edit_package_repository.start_edit_package(permission_lease)
            removed_release_editor = client.delete(
                f"/api/v1/projects/{project_id}/members/{release_editor_user_id}",
                headers=auth,
            )
            assert removed_release_editor.status_code == 200
            with pytest.raises(EditPackageConflict, match=r"no longer has.*permission"):
                edit_package_repository.assert_edit_package_current(
                    permission_lease,
                    permission_work,
                )
            failed_permission_task = runtime.task_queue.fail(
                claimed_permission_package,
                failure_class=FailureClass.DETERMINISTIC,
                error_code="EDIT_PACKAGE_PERMISSION_REVOKED",
                safe_message="Edit-package permission was revoked during export",
            )
            assert failed_permission_task is TaskStatus.FAILED
            assert (
                edit_package_repository.get_edit_package(permission_work.edit_package_id).status
                is EditPackageStatus.FAILED
            )

            stale_package = client.post(
                f"/api/v1/projects/{project_id}/edit-packages",
                headers={**auth, "Idempotency-Key": "api-edit-package-stale-001"},
                json={
                    "items": [{"clip_id": clip_id, "expected_revision": 3}],
                    "preset": "clean_editing",
                    "content": "metadata_only",
                    "include_zip": True,
                },
            )
            assert stale_package.status_code == 202
            stale_package_id = str(stale_package.json()["resource_id"])
            changed_after_selection = client.patch(
                f"/api/v1/clips/{clip_id}",
                headers=auth,
                json={"expected_revision": 3, "title": "交接选择后发生修改"},
            )
            assert changed_after_selection.status_code == 200
            assert changed_after_selection.json()["clip"]["current_revision"] == 4
            stale_result = runtime.delivery_runner.run_edit_package_until_terminal(
                stale_package_id,
                worker_id="api-stale-edit-package-worker",
            )
            assert stale_result.status == EditPackageStatus.FAILED
            assert stale_result.error_code == "EDIT_PACKAGE_STATE_INVALID"
            assert stale_result.zip_asset_id is None

            missing = client.get("/api/v1/clips/does-not-exist", headers=auth)
            assert missing.status_code == 404
            assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"

            visible_payloads = "\n".join(
                response.text
                for response in (
                    created,
                    replay,
                    conflict,
                    projects,
                    transcript,
                    clips,
                    clip,
                    edited,
                    reviewed,
                    delivery_detail,
                    imported,
                    imported_project,
                    second_run,
                    cancelled,
                    missing,
                )
            )
            assert token not in visible_payloads
            assert str(data_dir.resolve()) not in visible_payloads
            assert idempotency_key.encode() not in runtime.database_path.read_bytes()

            with runtime.engine.begin() as connection:
                administrator = connection.execute(
                    select(
                        WorkspaceUserRow.id,
                        WorkspaceUserRow.username,
                        WorkspaceUserRow.display_name,
                    ).where(WorkspaceUserRow.username == "local-admin")
                ).one()
                connection.execute(
                    update(ProjectRow)
                    .where(ProjectRow.id == project_id)
                    .values(
                        lifecycle=ProjectLifecycle.ARCHIVED.value,
                        lifecycle_before_archive=ProjectLifecycle.READY_TO_PUBLISH.value,
                        archived_at=ProjectRow.updated_at,
                        management_version=ProjectRow.management_version + 1,
                    )
                )
            storage_actor = WorkspaceUser(
                user_id=str(administrator.id),
                username=str(administrator.username),
                display_name=str(administrator.display_name),
                system_role="administrator",
            )
            rich_purge_plan = runtime.storage_administration_service.project_purge_plan(
                storage_actor,
                project_id,
            )
            assert rich_purge_plan.ready is True
            rich_purge = runtime.storage_administration_service.purge_project(
                storage_actor,
                project_id,
                ProjectPurgeCommand(
                    snapshot_fingerprint=rich_purge_plan.snapshot_fingerprint,
                    project_name=rich_purge_plan.project_name,
                    administrator_username=storage_actor.username,
                    confirmation_phrase=rich_purge_plan.confirmation_phrase,
                ),
            )
            assert rich_purge.source_media_preserved is True
            assert source_path.is_file()
            assert client.get(f"/api/v1/projects/{project_id}", headers=auth).status_code == 404

            def busy_failure(*, user_id: str | None = None) -> None:
                del user_id
                raise OperationalError(
                    "SELECT secret FROM local_state",
                    {},
                    sqlite3.OperationalError("database is locked"),
                )

            monkeypatch.setattr(runtime.pipeline_service, "list_projects", busy_failure)
            busy = client.get("/api/v1/projects", headers=auth)
            assert busy.status_code == 503
            assert busy.headers["retry-after"] == "1"
            assert busy.json()["error"]["code"] == "LOCAL_STORAGE_BUSY"
            assert busy.json()["error"]["retryable"] is True
            assert "SELECT secret" not in busy.text

            def secret_failure(*, user_id: str | None = None) -> None:
                del user_id
                raise RuntimeError(f"Authorization: Bearer {token} at {source_path}")

            caplog.set_level(logging.ERROR, logger="liveclip.api.app")
            monkeypatch.setattr(runtime.pipeline_service, "list_projects", secret_failure)
            redacted = client.get("/api/v1/projects", headers=auth)
            assert redacted.status_code == 500
            assert redacted.json()["error"]["code"] == "INTERNAL_ERROR"
            assert token not in redacted.text
            assert str(source_path) not in redacted.text
            assert token not in caplog.text
            assert str(source_path) not in caplog.text
    finally:
        runtime.close()
