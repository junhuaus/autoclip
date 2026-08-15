from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update

from liveclip.api.app import create_app
from liveclip.application.identity import AdministrationDenied
from liveclip.application.storage import ProjectPurgeCommand
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.identity_repository import SqlAlchemyIdentityRepository
from liveclip.db.models import (
    AssetRow,
    AuditEventRow,
    AuthLoginAttemptRow,
    AuthSessionRow,
    DeliveryRow,
    ProjectMemberRow,
    TaskRow,
    WorkspaceUserRow,
)
from liveclip.domain.state_transitions import AssetStatus, DeliveryStatus


@pytest.mark.integration
def test_persisted_login_throttle_recovers_and_expired_session_is_rejected(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    settings = Settings(
        data_dir=tmp_path / "projects",
        allowed_media_roots_raw=str(tmp_path),
        ai_provider="mock",
        bootstrap_admin_password="administrator password 2026",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            credentials = {
                "username": "local-admin",
                "password": "incorrect password 2026",
            }
            for _ in range(4):
                failed = client.post("/api/v1/auth/login", json=credentials)
                assert failed.status_code == 401
                assert failed.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
            limited = client.post("/api/v1/auth/login", json=credentials)
            assert limited.status_code == 429
            assert limited.json()["error"]["code"] == "LOGIN_RATE_LIMITED"
            assert int(limited.headers["retry-after"]) >= 1
            still_limited = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "local-admin",
                    "password": "administrator password 2026",
                },
            )
            assert still_limited.status_code == 429

            past = datetime.now(UTC) - timedelta(hours=1)
            with runtime.engine.begin() as connection:
                connection.execute(
                    update(AuthLoginAttemptRow).values(
                        window_started_at=past,
                        blocked_until=past,
                        updated_at=past,
                    )
                )
            recovered = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "local-admin",
                    "password": "administrator password 2026",
                },
            )
            assert recovered.status_code == 200
            raw_session = client.cookies.get("liveclip_session")
            assert raw_session is not None
            token_hash = hashlib.sha256(raw_session.encode("utf-8")).hexdigest()
            with runtime.engine.connect() as connection:
                expires_at = connection.scalar(
                    select(AuthSessionRow.expires_at).where(AuthSessionRow.token_hash == token_hash)
                )
            assert expires_at is not None
            assert (
                SqlAlchemyIdentityRepository(runtime.engine).get_session(
                    token_hash=token_hash,
                    now=expires_at,
                )
                is None
            )
            with runtime.engine.begin() as connection:
                connection.execute(update(AuthSessionRow).values(expires_at=past))
            expired = client.get("/api/v1/session")
            assert expired.status_code == 401
            assert expired.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    finally:
        runtime.close()


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

            storage = client.get("/api/v1/admin/storage")
            assert storage.status_code == 200
            assert storage.json()["policy"] == {
                "automatic_project_purge": False,
                "source_media_deletion": False,
                "safe_cleanup_committed_artifact_deletion": False,
                "safe_cleanup_scope": ("terminal_attempt_worktrees_and_completed_purge_quarantine"),
                "archive_retains_artifacts": True,
                "destructive_project_purge_available": True,
                "purge_requires_archived_project": True,
                "purge_creates_database_backup": True,
            }
            rejected_cleanup = client.post(
                "/api/v1/admin/storage/cleanup",
                headers={"X-CSRF-Token": csrf},
                json={"confirmation": "DELETE_EVERYTHING"},
            )
            assert rejected_cleanup.status_code == 422
            safe_cleanup = client.post(
                "/api/v1/admin/storage/cleanup",
                headers={"X-CSRF-Token": csrf},
                json={"confirmation": "CLEANUP_TERMINAL_ATTEMPTS"},
            )
            assert safe_cleanup.status_code == 200
            assert safe_cleanup.json()["failed_attempts"] == 0

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

            with (
                TestClient(app, raise_server_exceptions=False) as editor_client,
                TestClient(app, raise_server_exceptions=False) as second_editor_client,
            ):
                editor_login = editor_client.post(
                    "/api/v1/auth/login",
                    json={"username": "lin-editor", "password": "editor password 2026"},
                )
                assert editor_login.status_code == 200
                second_editor_login = second_editor_client.post(
                    "/api/v1/auth/login",
                    json={"username": "lin-editor", "password": "editor password 2026"},
                )
                assert second_editor_login.status_code == 200
                assert editor_client.get("/api/v1/projects").status_code == 200
                assert editor_client.get("/api/v1/admin/users").status_code == 403
                assert editor_client.get("/api/v1/admin/storage").status_code == 403

                reset_all_sessions = client.post(
                    f"/api/v1/admin/users/{editor['user_id']}/reset-password",
                    headers={"X-CSRF-Token": csrf},
                    json={"password": "replacement editor password 2026"},
                )
                assert reset_all_sessions.status_code == 200
                assert editor_client.get("/api/v1/projects").status_code == 401
                assert second_editor_client.get("/api/v1/projects").status_code == 401
                assert (
                    editor_client.post(
                        "/api/v1/auth/login",
                        json={
                            "username": "lin-editor",
                            "password": "editor password 2026",
                        },
                    ).status_code
                    == 401
                )
                relogin = editor_client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": "lin-editor",
                        "password": "replacement editor password 2026",
                    },
                )
                assert relogin.status_code == 200

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
                    json={
                        "username": "lin-editor",
                        "password": "replacement editor password 2026",
                    },
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
            assert connection.scalar(select(func.count()).select_from(AuthSessionRow)) == 5
            assert int(connection.scalar(select(func.count()).select_from(AuditEventRow)) or 0) >= 4
    finally:
        runtime.close()


@pytest.mark.integration
def test_revoked_administrator_snapshot_cannot_use_any_administrator_service(
    tmp_path: Path,
) -> None:
    """Repository fences must reject an actor captured before a concurrent demotion."""

    project_root = Path(__file__).resolve().parents[2]
    runtime = LiveClipRuntime.open(
        Settings(
            data_dir=tmp_path / "projects",
            allowed_media_roots_raw=str(tmp_path),
            ai_provider="mock",
            bootstrap_admin_password="administrator password 2026",
            _env_file=None,
        ),
        project_root=project_root,
    )
    try:
        stale_admin = runtime.workspace_service.get_user_by_username("local-admin")
        second_admin_result = runtime.user_administration_service.create_user(
            actor=stale_admin,
            username="second-admin",
            display_name="备用管理员",
            system_role="administrator",
            password="second administrator password 2026",
        )
        second_admin = second_admin_result.user.as_workspace_user()
        target_result = runtime.user_administration_service.create_user(
            actor=stale_admin,
            username="permission-target",
            display_name="权限目标",
            system_role="member",
            password="permission target password 2026",
        )
        target = target_result.user

        runtime.user_administration_service.update_user(
            actor=second_admin,
            user_id=stale_admin.user_id,
            system_role="member",
        )
        with runtime.engine.connect() as connection:
            before_user_count = int(
                connection.scalar(select(func.count()).select_from(WorkspaceUserRow)) or 0
            )
            before_audit_count = int(
                connection.scalar(select(func.count()).select_from(AuditEventRow)) or 0
            )
            before_target = connection.execute(
                select(
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.password_hash,
                    WorkspaceUserRow.auth_version,
                ).where(WorkspaceUserRow.id == target.user_id)
            ).one()

        denied_calls = (
            lambda: runtime.user_administration_service.list_users(stale_admin),
            lambda: runtime.user_administration_service.create_user(
                actor=stale_admin,
                username="post-revocation",
                display_name="不应创建",
                system_role="member",
                password="post revocation password 2026",
            ),
            lambda: runtime.user_administration_service.update_user(
                actor=stale_admin,
                user_id=target.user_id,
                display_name="不应修改",
            ),
            lambda: runtime.user_administration_service.reset_password(
                actor=stale_admin,
                user_id=target.user_id,
                password="replacement target password 2026",
            ),
            lambda: runtime.project_governance_service.list_projects(stale_admin),
            lambda: runtime.project_governance_service.get_project(stale_admin, "a" * 32),
            lambda: runtime.project_governance_service.transfer_project_ownership(
                actor=stale_admin,
                project_id="a" * 32,
                new_owner_user_id=target.user_id,
            ),
            lambda: runtime.project_governance_service.list_audit_events(stale_admin),
            lambda: runtime.storage_administration_service.report(stale_admin),
            lambda: runtime.storage_administration_service.project_purge_plan(
                stale_admin,
                "a" * 32,
            ),
            lambda: runtime.storage_administration_service.cleanup_terminal_attempts(stale_admin),
            lambda: runtime.storage_administration_service.purge_project(
                stale_admin,
                "a" * 32,
                ProjectPurgeCommand(
                    snapshot_fingerprint="b" * 64,
                    project_name="不应清除",
                    administrator_username=stale_admin.username,
                    confirmation_phrase=f"PURGE {'a' * 32}",
                ),
            ),
        )
        for call in denied_calls:
            with pytest.raises(AdministrationDenied):
                call()

        with runtime.engine.connect() as connection:
            assert (
                int(connection.scalar(select(func.count()).select_from(WorkspaceUserRow)) or 0)
                == before_user_count
            )
            assert (
                int(connection.scalar(select(func.count()).select_from(AuditEventRow)) or 0)
                == before_audit_count
            )
            after_target = connection.execute(
                select(
                    WorkspaceUserRow.display_name,
                    WorkspaceUserRow.password_hash,
                    WorkspaceUserRow.auth_version,
                ).where(WorkspaceUserRow.id == target.user_id)
            ).one()
            assert after_target == before_target
            assert (
                connection.scalar(
                    select(WorkspaceUserRow.id).where(
                        WorkspaceUserRow.username == "post-revocation"
                    )
                )
                is None
            )
    finally:
        runtime.close()
