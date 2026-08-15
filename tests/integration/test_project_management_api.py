from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings

pytestmark = pytest.mark.integration


def test_private_visibility_management_lifecycle_archive_and_activity(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = media_root / "managed-project.mp4"
    source.write_bytes(b"the pipeline task is intentionally not leased")
    admin_token = "project-owner-token"
    editor_token = "assigned-editor-token"
    outsider_token = "workspace-viewer-token"
    settings = Settings(
        data_dir=tmp_path / "projects",
        allowed_media_roots_raw=str(media_root),
        api_token=SecretStr(admin_token),
        workspace_tokens_raw=json.dumps(
            {"lin-editor": editor_token, "workspace-viewer": outsider_token}
        ),
        ai_provider="mock",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    owner_auth = {"Authorization": f"Bearer {admin_token}"}
    editor_auth = {"Authorization": f"Bearer {editor_token}"}
    outsider_auth = {"Authorization": f"Bearer {outsider_token}"}
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            created = client.post(
                "/api/v1/projects/import",
                headers=owner_auth,
                json={"input_path": str(source)},
            )
            assert created.status_code == 202
            project_id = created.json()["project_id"]
            run_id = created.json()["run_id"]
            initial = client.get(f"/api/v1/projects/{project_id}", headers=owner_auth).json()
            assert initial["visibility"] == "private"
            assert initial["lifecycle"] == "processing"
            assert initial["assignee"]["username"] == "local-admin"
            assert "manage_project" in initial["allowed_actions"]
            assert client.get("/api/v1/projects", headers=outsider_auth).json() == []

            added = client.post(
                f"/api/v1/projects/{project_id}/members",
                headers=owner_auth,
                json={
                    "username": "lin-editor",
                    "display_name": "林编辑",
                    "role": "editor",
                },
            )
            editor_id = next(
                item["user_id"]
                for item in added.json()["members"]
                if item["username"] == "lin-editor"
            )
            managed = client.patch(
                f"/api/v1/projects/{project_id}/management",
                headers=owner_auth,
                json={
                    "expected_management_version": initial["management_version"],
                    "visibility": "workspace",
                    "assignee_user_id": editor_id,
                    "priority": "urgent",
                    "due_at": "2026-08-20T18:00:00+08:00",
                },
            )
            assert managed.status_code == 200
            managed_project = managed.json()
            assert managed_project["assignee"]["username"] == "lin-editor"
            assert managed_project["priority"] == "urgent"
            assert managed_project["visibility"] == "workspace"

            assigned_remove = client.delete(
                f"/api/v1/projects/{project_id}/members/{editor_id}",
                headers=owner_auth,
            )
            assert assigned_remove.status_code == 409
            assert assigned_remove.json()["error"]["code"] == "STATE_CONFLICT"

            stale = client.patch(
                f"/api/v1/projects/{project_id}/management",
                headers=owner_auth,
                json={
                    "expected_management_version": initial["management_version"],
                    "visibility": "private",
                    "assignee_user_id": editor_id,
                    "priority": "normal",
                    "due_at": None,
                },
            )
            assert stale.status_code == 409

            visible = client.get("/api/v1/projects", headers=outsider_auth)
            assert [item["project_id"] for item in visible.json()] == [project_id]
            shared_project = client.get(
                f"/api/v1/projects/{project_id}", headers=outsider_auth
            ).json()
            assert shared_project["current_user_role"] == "viewer"
            assert shared_project["allowed_actions"] == ["read"]
            forbidden = client.patch(
                f"/api/v1/projects/{project_id}/management",
                headers=editor_auth,
                json={
                    "expected_management_version": managed_project["management_version"],
                    "visibility": "private",
                    "assignee_user_id": editor_id,
                    "priority": "normal",
                    "due_at": None,
                },
            )
            assert forbidden.status_code == 403

            archive_active = client.post(
                f"/api/v1/projects/{project_id}/lifecycle",
                headers=owner_auth,
                json={
                    "expected_management_version": managed_project["management_version"],
                    "target": "archived",
                    "reason": "归档测试",
                },
            )
            assert archive_active.status_code == 409

            cancelled = client.post(f"/api/v1/runs/{run_id}/cancel", headers=owner_auth)
            assert cancelled.status_code == 202
            current = client.get(f"/api/v1/projects/{project_id}", headers=owner_auth).json()
            assert current["lifecycle"] == "needs_attention"
            lifecycle_path = (
                "editorial_review",
                "approval",
                "ready_to_publish",
                "published",
                "archived",
            )
            for target in lifecycle_path:
                changed = client.post(
                    f"/api/v1/projects/{project_id}/lifecycle",
                    headers=owner_auth,
                    json={
                        "expected_management_version": current["management_version"],
                        "target": target,
                        "reason": f"进入 {target}",
                    },
                )
                assert changed.status_code == 200, changed.text
                current = changed.json()

            assert current["allowed_actions"] == ["read", "manage_project"]
            assert current["allowed_lifecycle_transitions"] == ["published"]
            assert (
                client.post(
                    f"/api/v1/projects/{project_id}/runs",
                    headers=owner_auth,
                    json={},
                ).status_code
                == 403
            )
            restored = client.post(
                f"/api/v1/projects/{project_id}/lifecycle",
                headers=owner_auth,
                json={
                    "expected_management_version": current["management_version"],
                    "target": "published",
                    "reason": "恢复已发布项目",
                },
            )
            assert restored.status_code == 200
            assert restored.json()["lifecycle"] == "published"
            activity = client.get(f"/api/v1/projects/{project_id}/activity", headers=outsider_auth)
            assert activity.status_code == 200
            actions = [event["action"] for event in activity.json()["events"]]
            assert "project.management_updated" in actions
            assert "project.lifecycle_changed" in actions
            assert "project.restored" in actions
            assert "pipeline.cancelled" in actions
    finally:
        runtime.close()
