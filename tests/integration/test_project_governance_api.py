from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.models import AuditEventRow, ProjectMemberRow, ProjectRow, WorkspaceUserRow

pytestmark = pytest.mark.integration


def test_explicit_admin_governance_sees_disabled_owner_and_transfers_project(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = media_root / "private-governance-source.mp4"
    source.write_bytes(b"ingest remains queued during the governance test")
    settings = Settings(
        data_dir=tmp_path / "projects",
        allowed_media_roots_raw=str(media_root),
        ai_provider="mock",
        bootstrap_admin_password="bootstrap administrator 2026",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    try:
        with (
            TestClient(app, raise_server_exceptions=False) as admin,
            TestClient(app, raise_server_exceptions=False) as owner,
            TestClient(app, raise_server_exceptions=False) as successor,
            TestClient(app, raise_server_exceptions=False) as viewer,
            TestClient(app, raise_server_exceptions=False) as second_admin,
        ):
            admin_login = admin.post(
                "/api/v1/auth/login",
                json={
                    "username": "local-admin",
                    "password": "bootstrap administrator 2026",
                },
            )
            assert admin_login.status_code == 200
            admin_csrf = admin_login.json()["csrf_token"]

            owner_user = _create_user(
                admin,
                admin_csrf,
                username="project-creator",
                display_name="项目创建者",
            )
            successor_user = _create_user(
                admin,
                admin_csrf,
                username="successor-editor",
                display_name="接任编辑",
            )
            _create_user(
                admin,
                admin_csrf,
                username="project-viewer",
                display_name="项目观察者",
            )
            second_admin_user = _create_user(
                admin,
                admin_csrf,
                username="second-admin",
                display_name="备用管理员",
                system_role="administrator",
            )

            owner_login = owner.post(
                "/api/v1/auth/login",
                json={"username": "project-creator", "password": "member password 2026"},
            )
            assert owner_login.status_code == 200
            created = owner.post(
                "/api/v1/projects/import",
                headers={"X-CSRF-Token": owner_login.json()["csrf_token"]},
                json={"input_path": str(source)},
            )
            assert created.status_code == 202
            project_id = str(created.json()["project_id"])
            added_viewer = owner.post(
                f"/api/v1/projects/{project_id}/members",
                headers={"X-CSRF-Token": owner_login.json()["csrf_token"]},
                json={
                    "username": "project-viewer",
                    "display_name": "项目观察者",
                    "role": "viewer",
                },
            )
            assert added_viewer.status_code == 200
            viewer_login = viewer.post(
                "/api/v1/auth/login",
                json={"username": "project-viewer", "password": "member password 2026"},
            )
            assert viewer_login.status_code == 200

            # System administration is an explicit context, not an implicit
            # Project membership or ordinary editing override.
            assert admin.get("/api/v1/projects").json() == []
            assert admin.get(f"/api/v1/projects/{project_id}").status_code == 404
            governed = admin.get("/api/v1/admin/projects")
            assert governed.status_code == 200
            governed_project = governed.json()["projects"][0]
            assert governed_project["project_id"] == project_id
            assert governed_project["administrative_context"] is True
            assert governed_project["allowed_governance_actions"] == [
                "view",
                "transfer_ownership",
            ]
            assert governed_project["owner"]["user_id"] == owner_user["user_id"]
            assert governed_project["owner"]["is_active"] is True

            successor_login = successor.post(
                "/api/v1/auth/login",
                json={"username": "successor-editor", "password": "member password 2026"},
            )
            assert successor_login.status_code == 200
            assert successor.get("/api/v1/admin/projects").status_code == 403
            assert successor.get("/api/v1/admin/audit-events").status_code == 403
            assert successor.get("/api/v1/projects").json() == []

            disabled = admin.delete(
                f"/api/v1/admin/users/{owner_user['user_id']}",
                headers={"X-CSRF-Token": admin_csrf},
            )
            assert disabled.status_code == 200
            assert owner.get("/api/v1/projects").status_code == 401
            viewer_project = viewer.get(f"/api/v1/projects/{project_id}")
            assert viewer_project.status_code == 200
            assert viewer_project.json()["current_user_role"] == "viewer"
            assert viewer_project.json()["owner"]["user_id"] == owner_user["user_id"]
            disabled_owner_project = admin.get(f"/api/v1/admin/projects/{project_id}").json()[
                "project"
            ]
            assert disabled_owner_project["owner"]["user_id"] == owner_user["user_id"]
            assert disabled_owner_project["owner"]["is_active"] is False

            transferred = admin.post(
                f"/api/v1/admin/projects/{project_id}/ownership-transfer",
                headers={"X-CSRF-Token": admin_csrf},
                json={"new_owner_user_id": successor_user["user_id"]},
            )
            assert transferred.status_code == 200
            transferred_project = transferred.json()["project"]
            assert transferred_project["owner"]["user_id"] == successor_user["user_id"]
            assert transferred_project["owner"]["role"] == "owner"
            assert (
                next(
                    member
                    for member in transferred_project["members"]
                    if member["user_id"] == owner_user["user_id"]
                )["role"]
                == "editor"
            )
            assert transferred_project["management_version"] == 2

            successor_projects = successor.get("/api/v1/projects")
            assert successor_projects.status_code == 200
            assert successor_projects.json()[0]["project_id"] == project_id
            assert successor_projects.json()[0]["current_user_role"] == "owner"
            assert "manage_members" in successor_projects.json()[0]["allowed_actions"]

            audit = admin.get(
                "/api/v1/admin/audit-events",
                params={"project_id": project_id},
            )
            assert audit.status_code == 200
            transfer_event = next(
                event
                for event in audit.json()["events"]
                if event["action"] == "project.ownership_transferred_by_administrator"
            )
            assert transfer_event["actor_username"] == "local-admin"
            assert transfer_event["before"]["owner_user_id"] == owner_user["user_id"]
            assert transfer_event["after"]["owner_user_id"] == successor_user["user_id"]
            assert transfer_event["after"]["administrative_context"] is True

            # A concurrent system-role change revokes the original session;
            # the old administrator cannot continue using governance routes.
            second_login = second_admin.post(
                "/api/v1/auth/login",
                json={"username": "second-admin", "password": "member password 2026"},
            )
            assert second_login.status_code == 200
            demoted = second_admin.patch(
                "/api/v1/admin/users/00000000000000000000000000000001",
                headers={"X-CSRF-Token": second_login.json()["csrf_token"]},
                json={"system_role": "member"},
            )
            assert demoted.status_code == 200
            assert admin.get("/api/v1/admin/projects").status_code == 401

            with runtime.engine.connect() as connection:
                assert (
                    connection.scalar(
                        select(func.count())
                        .select_from(ProjectMemberRow)
                        .where(
                            ProjectMemberRow.project_id == project_id,
                            ProjectMemberRow.role == "owner",
                        )
                    )
                    == 1
                )
                project = connection.execute(
                    select(ProjectRow.owner_id, ProjectRow.management_version).where(
                        ProjectRow.id == project_id
                    )
                ).one()
                assert str(project.owner_id) == successor_user["user_id"]
                assert int(project.management_version) == 2
                assert (
                    connection.scalar(
                        select(func.count())
                        .select_from(AuditEventRow)
                        .where(
                            AuditEventRow.project_id == project_id,
                            AuditEventRow.action
                            == "project.ownership_transferred_by_administrator",
                        )
                    )
                    == 1
                )
                assert (
                    connection.scalar(
                        select(WorkspaceUserRow.system_role).where(
                            WorkspaceUserRow.id == second_admin_user["user_id"]
                        )
                    )
                    == "administrator"
                )
    finally:
        runtime.close()


def _create_user(
    client: TestClient,
    csrf_token: str,
    *,
    username: str,
    display_name: str,
    system_role: str = "member",
) -> dict[str, object]:
    response = client.post(
        "/api/v1/admin/users",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "username": username,
            "display_name": display_name,
            "system_role": system_role,
            "password": "member password 2026",
        },
    )
    assert response.status_code == 201
    return next(user for user in response.json()["users"] if user["username"] == username)
