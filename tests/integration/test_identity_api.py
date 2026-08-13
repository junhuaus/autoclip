from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    AuthSessionRow,
    DeliveryRow,
    ProjectMemberRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.domain.state_transitions import AssetStatus, DeliveryStatus


@pytest.mark.integration
def test_admin_login_user_management_session_revocation_and_audit(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    data_dir = tmp_path / "projects"
    settings = Settings(
        data_dir=data_dir,
        allowed_media_roots_raw=str(tmp_path),
        ai_provider="mock",
        bootstrap_admin_password="administrator password 2026",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.get("/api/v1/session").status_code == 401
            login = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "local-admin",
                    "password": "administrator password 2026",
                },
            )
            assert login.status_code == 200
            assert "HttpOnly" in login.headers["set-cookie"]
            assert "SameSite=strict" in login.headers["set-cookie"]
            csrf = login.json()["csrf_token"]
            assert "password" not in login.text.lower()

            missing_csrf = client.post(
                "/api/v1/admin/users",
                json={
                    "username": "lin-editor",
                    "display_name": "林编辑",
                    "password": "editor password 2026",
                    "system_role": "member",
                },
            )
            assert missing_csrf.status_code == 401

            created = client.post(
                "/api/v1/admin/users",
                headers={"X-CSRF-Token": csrf},
                json={
                    "username": "lin-editor",
                    "display_name": "林编辑",
                    "password": "editor password 2026",
                    "system_role": "member",
                },
            )
            assert created.status_code == 201
            editor = next(
                item for item in created.json()["users"] if item["username"] == "lin-editor"
            )
            assert editor["password_configured"] is True

            update_role = client.patch(
                f"/api/v1/admin/users/{editor['user_id']}",
                headers={"X-CSRF-Token": csrf},
                json={"display_name": "林主编", "system_role": "administrator"},
            )
            assert update_role.status_code == 200
            changed = next(
                item for item in update_role.json()["users"] if item["user_id"] == editor["user_id"]
            )
            assert (changed["display_name"], changed["system_role"]) == (
                "林主编",
                "administrator",
            )
            restored_member = client.patch(
                f"/api/v1/admin/users/{editor['user_id']}",
                headers={"X-CSRF-Token": csrf},
                json={"system_role": "member"},
            )
            assert restored_member.status_code == 200

            with TestClient(app, raise_server_exceptions=False) as editor_client:
                editor_login = editor_client.post(
                    "/api/v1/auth/login",
                    json={"username": "lin-editor", "password": "editor password 2026"},
                )
                assert editor_login.status_code == 200
                assert editor_client.get("/api/v1/projects").status_code == 200
                assert editor_client.get("/api/v1/admin/users").status_code == 403

                disabled = client.delete(
                    f"/api/v1/admin/users/{editor['user_id']}",
                    headers={"X-CSRF-Token": csrf},
                )
                assert disabled.status_code == 200
                assert editor_client.get("/api/v1/projects").status_code == 401

            sole_admin = client.delete(
                "/api/v1/admin/users/00000000000000000000000000000001",
                headers={"X-CSRF-Token": csrf},
            )
            assert sole_admin.status_code == 409

            source = tmp_path / "private-source.mp4"
            source.write_bytes(b"private project import is not leased in this test")
            private_project = client.post(
                "/api/v1/projects/import",
                headers={"X-CSRF-Token": csrf},
                json={"input_path": str(source)},
            )
            assert private_project.status_code == 202
            project_id = private_project.json()["project_id"]
            assert client.get(f"/api/v1/projects/{project_id}").json()["visibility"] == "private"

            asset_id = "private-review-proxy"
            delivery_asset_id = "private-delivery-zip"
            delivery_id = "private-delivery"
            asset_dir = data_dir / project_id / "test-assets"
            asset_dir.mkdir(parents=True, exist_ok=True)
            media_bytes = b"private project media bytes"
            delivery_bytes = b"private project delivery bytes"
            (asset_dir / "proxy.mp4").write_bytes(media_bytes)
            (asset_dir / "delivery.zip").write_bytes(delivery_bytes)
            now = datetime.now(UTC)
            with runtime.engine.begin() as connection:
                task_id = connection.scalar(
                    select(TaskRow.id).where(
                        TaskRow.pipeline_run_id == private_project.json()["run_id"]
                    )
                )
                assert task_id is not None
                connection.execute(
                    insert(AssetRow),
                    [
                        {
                            "id": asset_id,
                            "project_id": project_id,
                            "status": AssetStatus.COMMITTED.value,
                            "kind": "review_proxy",
                            "relative_path": "test-assets/proxy.mp4",
                            "mime_type": "video/mp4",
                            "input_fingerprint": "a" * 64,
                            "sha256": hashlib.sha256(media_bytes).hexdigest(),
                            "size_bytes": len(media_bytes),
                            "committed_at": now,
                            "created_at": now,
                        },
                        {
                            "id": delivery_asset_id,
                            "project_id": project_id,
                            "status": AssetStatus.COMMITTED.value,
                            "kind": "delivery_zip",
                            "relative_path": "test-assets/delivery.zip",
                            "mime_type": "application/zip",
                            "input_fingerprint": "b" * 64,
                            "sha256": hashlib.sha256(delivery_bytes).hexdigest(),
                            "size_bytes": len(delivery_bytes),
                            "committed_at": now,
                            "created_at": now,
                        },
                    ],
                )
                connection.execute(
                    insert(DeliveryRow).values(
                        id=delivery_id,
                        project_id=project_id,
                        task_id=task_id,
                        version=1,
                        status=DeliveryStatus.SUCCEEDED.value,
                        expected_revision_epoch=0,
                        expected_generation=1,
                        snapshot_fingerprint="c" * 64,
                        directory_relative_path="deliveries/v001",
                        zip_asset_id=delivery_asset_id,
                        include_zip=True,
                        created_at=now,
                        completed_at=now,
                    )
                )
            assert client.get(f"/api/v1/media/{asset_id}").content == media_bytes
            assert (
                client.get(f"/api/v1/deliveries/{delivery_id}/download").content == delivery_bytes
            )

            client.patch(
                f"/api/v1/admin/users/{editor['user_id']}",
                headers={"X-CSRF-Token": csrf},
                json={"is_active": True},
            )
            with TestClient(app, raise_server_exceptions=False) as outsider:
                outsider_login = outsider.post(
                    "/api/v1/auth/login",
                    json={"username": "lin-editor", "password": "editor password 2026"},
                )
                assert outsider_login.status_code == 200
                assert outsider.get("/api/v1/projects").json() == []
                hidden = outsider.get(f"/api/v1/projects/{project_id}")
                assert hidden.status_code == 404
                assert outsider.get(f"/api/v1/media/{asset_id}").status_code == 404
                assert outsider.get(f"/api/v1/deliveries/{delivery_id}/download").status_code == 404

            with runtime.engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(func.count())
                        .select_from(ProjectMemberRow)
                        .where(ProjectMemberRow.project_id == project_id)
                    )
                    == 1
                )

        with runtime.engine.connect() as connection:
            stored_password = connection.scalar(
                select(WorkspaceUserRow.password_hash).where(
                    WorkspaceUserRow.username == "lin-editor"
                )
            )
            assert stored_password is not None and stored_password.startswith("$argon2id$")
            assert "editor password 2026" not in stored_password
            assert connection.scalar(select(func.count()).select_from(AuthSessionRow)) == 3
            assert int(connection.scalar(select(func.count()).select_from(AuditEventRow)) or 0) >= 4
    finally:
        runtime.close()
