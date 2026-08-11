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
from sqlalchemy.exc import OperationalError

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.domain.state_transitions import DeliveryStatus, PipelineRunStatus, RenderStatus
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
    settings = Settings(
        data_dir=data_dir,
        allowed_media_roots_raw=str(media_root),
        api_token=SecretStr(token),
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
            proxy_url = str(clip_summary["proxy_media_url"])
            assert token not in proxy_url
            proxy_range = client.get(proxy_url, headers={"Range": "bytes=0-99"})
            assert proxy_range.status_code == 206
            assert len(proxy_range.content) == 100
            assert proxy_range.headers["content-range"].startswith("bytes 0-99/")
            invalid_range = client.get(proxy_url, headers={"Range": "bytes=0-1,3-4"})
            assert invalid_range.status_code == 416
            assert invalid_range.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"

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

            def busy_failure() -> None:
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

            def secret_failure() -> None:
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
