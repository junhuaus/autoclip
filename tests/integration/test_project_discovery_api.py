from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, insert, update

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.models import (
    CandidateClipRow,
    EditPlanRevisionRow,
    ProjectRow,
    ReleaseItemRow,
    SavedProjectViewRow,
    WorkspaceUserRow,
)

pytestmark = pytest.mark.integration


def _settings(tmp_path: Path, media_root: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "projects",
        allowed_media_roots_raw=str(media_root),
        api_token=SecretStr("discovery-owner-token"),
        workspace_tokens_raw=json.dumps(
            {
                "lin-editor": "discovery-editor-token",
                "workspace-viewer": "discovery-viewer-token",
            }
        ),
        ai_provider="mock",
        _env_file=None,
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _import_project(
    client: TestClient,
    *,
    owner_auth: dict[str, str],
    source: Path,
) -> tuple[str, str]:
    response = client.post(
        "/api/v1/projects/import",
        headers=owner_auth,
        json={"input_path": str(source)},
    )
    assert response.status_code == 202, response.text
    return response.json()["project_id"], response.json()["run_id"]


def _add_current_clip_and_release(
    runtime: LiveClipRuntime,
    *,
    project_id: str,
    run_id: str,
    owner_id: str,
) -> None:
    candidate_id = "c" * 32
    first_revision_id = "d" * 32
    current_revision_id = "e" * 32
    with runtime.engine.begin() as connection:
        connection.execute(
            insert(CandidateClipRow).values(
                id=candidate_id,
                project_id=project_id,
                pipeline_run_id=run_id,
                candidate_key="discovery-candidate",
                source_start_ms=1_000,
                source_end_ms=31_000,
                allowed_start_ms=0,
                allowed_end_ms=40_000,
                transcript_text="真实直播内容包含增长飞轮与用户留存",
                context_before="",
                context_after="",
                rule_score=88.0,
                reasons_json=["test"],
                segment_ids_json=[],
                current_revision=2,
                rank=1,
                selected_for_review=True,
            )
        )
        common = {
            "candidate_clip_id": candidate_id,
            "origin": "human",
            "source_start_ms": 1_000,
            "source_end_ms": 31_000,
            "score": 91.0,
            "reason": "搜索当前 revision",
            "layout": "center_crop",
            "caption_template": "clean_zh_v1",
            "effect": "none",
            "risk_flags_json": [],
            "prompt_version": "test-v1",
            "model": "test",
            "degraded": False,
            "plan_json": {},
        }
        connection.execute(
            insert(EditPlanRevisionRow).values(
                **common,
                id=first_revision_id,
                revision=1,
                parent_revision=None,
                title="已经废弃的旧标题",
                hook="旧 Hook",
            )
        )
        connection.execute(
            insert(EditPlanRevisionRow).values(
                **common,
                id=current_revision_id,
                revision=2,
                parent_revision=1,
                title="增长飞轮实战",
                hook="三十秒看懂留存",
            )
        )
        connection.execute(
            insert(ReleaseItemRow).values(
                id="r" * 32,
                project_id=project_id,
                candidate_clip_id=candidate_id,
                edit_plan_revision_id=current_revision_id,
                edit_plan_revision=2,
                platform="douyin",
                preset_version="2026-08-01.1",
                account_label="品牌主账号",
                title="增长飞轮发布标题",
                title_variants_json=[],
                description="发布说明",
                hashtags_json=["增长", "只在标签"],
                cta="关注账号",
                caption_mode="clean_separate",
                cover_time_ms=2_000,
                assignee_user_id=None,
                planned_publish_at=None,
                approval_status="draft",
                status="draft",
                checklist_json={},
                preflight_json={},
                management_version=1,
                created_by_user_id=owner_id,
            )
        )


def test_authorized_server_search_matches_current_content_and_uses_keyset_paging(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    settings = _settings(tmp_path, media_root)
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    owner_auth = _auth("discovery-owner-token")
    viewer_auth = _auth("discovery-viewer-token")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            projects: list[tuple[str, str]] = []
            names = ("ABC 直播增长", "100%_安全\\计划", "同名项目", "同名项目")
            shared_updated_at = datetime.now(UTC) - timedelta(hours=2)
            shared_due_at = datetime.now(UTC) - timedelta(days=1)
            for index, name in enumerate(names):
                source = media_root / (
                    "私密独有词.mp4" if index == 3 else f"source-{index}-alpha.mp4"
                )
                source.write_bytes(f"source-{index}".encode())
                project_id, run_id = _import_project(
                    client,
                    owner_auth=owner_auth,
                    source=source,
                )
                projects.append((project_id, run_id))
                with runtime.engine.begin() as connection:
                    connection.execute(
                        update(ProjectRow)
                        .where(ProjectRow.id == project_id)
                        .values(
                            name=name,
                            visibility="private" if index == 3 else "workspace",
                            assignee_user_id=None,
                            priority=("urgent" if index == 0 else "normal"),
                            due_at=(shared_due_at if index < 2 else None),
                            updated_at=shared_updated_at,
                        )
                    )

            owner = runtime.workspace_service.get_user_by_username("local-admin")
            with runtime.engine.begin() as connection:
                connection.execute(
                    update(ProjectRow)
                    .where(ProjectRow.id == projects[0][0])
                    .values(assignee_user_id=owner.user_id)
                )
            _add_current_clip_and_release(
                runtime,
                project_id=projects[0][0],
                run_id=projects[0][1],
                owner_id=owner.user_id,
            )

            private_probe = client.get(
                "/api/v1/projects/search",
                headers=viewer_auth,
                params={"q": "私密独有词"},
            )
            assert private_probe.status_code == 200, private_probe.text
            assert private_probe.json()["total_count"] == 0
            assert private_probe.json()["items"] == []
            assert private_probe.json()["summary"]["visible_total"] == 3

            viewer_role = client.get(
                "/api/v1/projects/search",
                headers=viewer_auth,
                params={"role": "viewer", "visibility": "workspace"},
            ).json()
            assert viewer_role["total_count"] == 3
            assert {item["project"]["current_user_role"] for item in viewer_role["items"]} == {
                "viewer"
            }

            assigned = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"assignee": "user", "assignee_user_id": owner.user_id},
            ).json()
            assert [item["project"]["project_id"] for item in assigned["items"]] == [projects[0][0]]
            invalid_assignee = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"assignee": "user", "assignee_user_id": "../outside"},
            )
            assert invalid_assignee.status_code == 422
            duplicate_filter = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params=[("lifecycle", "draft"), ("lifecycle", "draft")],
            )
            assert duplicate_filter.status_code == 422

            fullwidth = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "ＡＢＣ"},  # noqa: RUF001 - intentional NFKC coverage
            ).json()
            assert [item["project"]["project_id"] for item in fullwidth["items"]] == [
                projects[0][0]
            ]
            assert fullwidth["query_fingerprint"]
            assert fullwidth["evaluated_at"]

            literal_symbols = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "%_安全\\"},
            ).json()
            assert [item["project"]["project_id"] for item in literal_symbols["items"]] == [
                projects[1][0]
            ]

            source_match = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "source-0-alpha.mp4"},
            ).json()
            assert source_match["items"][0]["matches"][0]["scope"] == "source"

            current_title = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "增长飞轮实战"},
            ).json()
            assert current_title["items"][0]["matches"][0]["scope"] == "clip_title"
            assert (
                client.get(
                    "/api/v1/projects/search",
                    headers=owner_auth,
                    params={"q": "已经废弃的旧标题"},
                ).json()["total_count"]
                == 0
            )
            transcript = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "用户留存"},
            ).json()
            assert transcript["items"][0]["matches"][0]["scope"] == "transcript"
            platform = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "抖音", "platform": "douyin"},
            ).json()
            assert platform["items"][0]["matches"][0]["scope"] == "platform"
            hashtag = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "只在标签"},
            ).json()
            assert hashtag["items"][0]["matches"][0]["scope"] == "platform"

            disabled_editor = runtime.workspace_service.get_user_by_username("lin-editor")
            with runtime.engine.begin() as connection:
                connection.execute(
                    update(ProjectRow)
                    .where(ProjectRow.id == projects[1][0])
                    .values(assignee_user_id=disabled_editor.user_id)
                )
                connection.execute(
                    update(WorkspaceUserRow)
                    .where(WorkspaceUserRow.id == disabled_editor.user_id)
                    .values(is_active=False)
                )
            disabled_assignee_query = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "lin-editor"},
            ).json()
            assert disabled_assignee_query["total_count"] == 0
            disabled_assignee_filter = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={
                    "assignee": "user",
                    "assignee_user_id": disabled_editor.user_id,
                },
            ).json()
            assert disabled_assignee_filter["total_count"] == 0
            operationally_unassigned = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"assignee": "unassigned"},
            ).json()
            assert projects[1][0] in {
                item["project"]["project_id"] for item in operationally_unassigned["items"]
            }
            disabled_project = next(
                item["project"]
                for item in operationally_unassigned["items"]
                if item["project"]["project_id"] == projects[1][0]
            )
            assert disabled_project["assignee"] is None

            ordered_updated_at = datetime.now(UTC)
            with runtime.engine.begin() as connection:
                for index, (project_id, _) in enumerate(projects):
                    connection.execute(
                        update(ProjectRow)
                        .where(ProjectRow.id == project_id)
                        .values(updated_at=ordered_updated_at - timedelta(minutes=index))
                    )

            overdue = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"due": "overdue", "priority": "urgent"},
            ).json()
            assert [item["project"]["project_id"] for item in overdue["items"]] == [projects[0][0]]

            expected_by_sort = {
                "updated_desc": [project_id for project_id, _ in projects],
                "due_asc": [
                    *sorted((projects[0][0], projects[1][0])),
                    *sorted((projects[2][0], projects[3][0])),
                ],
                "priority_desc": [project_id for project_id, _ in projects],
                "name_asc": [
                    projects[1][0],
                    projects[0][0],
                    *sorted((projects[2][0], projects[3][0])),
                ],
            }
            for sort, expected_order in expected_by_sort.items():
                seen: list[str] = []
                cursor: str | None = None
                while True:
                    params = {"sort": sort, "limit": "1"}
                    if cursor is not None:
                        params["cursor"] = cursor
                    page = client.get(
                        "/api/v1/projects/search",
                        headers=owner_auth,
                        params=params,
                    )
                    assert page.status_code == 200, page.text
                    payload = page.json()
                    seen.extend(item["project"]["project_id"] for item in payload["items"])
                    cursor = payload["next_cursor"]
                    if cursor is None:
                        break
                assert len(seen) == 4, sort
                assert len(set(seen)) == 4, sort
                assert seen == expected_order, sort

            owner_cursor = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"sort": "name_asc", "limit": 1},
            ).json()["next_cursor"]
            cross_user = client.get(
                "/api/v1/projects/search",
                headers=viewer_auth,
                params={"sort": "name_asc", "limit": 1, "cursor": owner_cursor},
            )
            assert cross_user.status_code == 422
    finally:
        runtime.close()


def test_saved_project_views_are_private_idempotent_and_version_fenced(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    settings = _settings(tmp_path, media_root)
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    owner_auth = _auth("discovery-owner-token")
    viewer_auth = _auth("discovery-viewer-token")
    body = {
        "name": "  Ｍｙ　Ｖｉｅｗ  ",  # noqa: RUF001 - intentional NFKC coverage
        "criteria": {
            "query": "直播",
            "priorities": ["urgent"],
            "sort": "priority_desc",
        },
    }
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            invalid_saved_assignee = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-invalid-assignee"},
                json={
                    "name": "非法执行人",
                    "criteria": {"assignee": "user", "assignee_user_id": "../outside"},
                },
            )
            assert invalid_saved_assignee.status_code == 422

            created = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-create-1"},
                json=body,
            )
            assert created.status_code == 201, created.text
            view = created.json()
            assert view["name"] == "My View"
            assert view["criteria_schema_version"] == "1"
            assert view["version"] == 1

            replayed = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-create-1"},
                json=body,
            )
            assert replayed.status_code == 201
            assert replayed.json()["view_id"] == view["view_id"]
            conflict = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-create-1"},
                json={**body, "name": "不同名称"},
            )
            assert conflict.status_code == 409
            assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

            duplicate = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-create-2"},
                json={**body, "name": "my view"},
            )
            assert duplicate.status_code == 409

            assert client.get("/api/v1/project-views", headers=viewer_auth).json()["views"] == []
            hidden = client.patch(
                f"/api/v1/project-views/{view['view_id']}",
                headers=viewer_auth,
                json={
                    "expected_version": 1,
                    "name": "越权修改",
                    "criteria": {},
                },
            )
            assert hidden.status_code == 404

            updated = client.patch(
                f"/api/v1/project-views/{view['view_id']}",
                headers=owner_auth,
                json={
                    "expected_version": 1,
                    "name": "待我处理",
                    "criteria": {"due": "overdue", "assignee": "me"},
                },
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["version"] == 2
            stale = client.patch(
                f"/api/v1/project-views/{view['view_id']}",
                headers=owner_auth,
                json={
                    "expected_version": 1,
                    "name": "过期修改",
                    "criteria": {},
                },
            )
            assert stale.status_code == 409
            assert (
                client.delete(
                    f"/api/v1/project-views/{view['view_id']}",
                    headers=owner_auth,
                    params={"expected_version": 1},
                ).status_code
                == 409
            )
            assert (
                client.delete(
                    f"/api/v1/project-views/{view['view_id']}",
                    headers=owner_auth,
                    params={"expected_version": 2},
                ).status_code
                == 204
            )
            assert client.get("/api/v1/project-views", headers=owner_auth).json()["views"] == []
    finally:
        runtime.close()


def test_search_refuses_concurrent_visibility_and_revision_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    source = media_root / "concurrent-search.mp4"
    source.write_bytes(b"search-race")
    settings = _settings(tmp_path, media_root)
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    owner_auth = _auth("discovery-owner-token")
    viewer_auth = _auth("discovery-viewer-token")
    repository = runtime.project_discovery_service._repository
    original_search = repository.search_projects
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            project_id, run_id = _import_project(
                client,
                owner_auth=owner_auth,
                source=source,
            )
            with runtime.engine.begin() as connection:
                connection.execute(
                    update(ProjectRow)
                    .where(ProjectRow.id == project_id)
                    .values(name="并发权限项目", visibility="workspace")
                )

            visibility_calls = 0

            def revoke_after_first_search(**kwargs: object):
                nonlocal visibility_calls
                selection = original_search(**kwargs)
                visibility_calls += 1
                if visibility_calls == 1:
                    with runtime.engine.begin() as connection:
                        connection.execute(
                            update(ProjectRow)
                            .where(ProjectRow.id == project_id)
                            .values(visibility="private")
                        )
                return selection

            monkeypatch.setattr(repository, "search_projects", revoke_after_first_search)
            revoked = client.get(
                "/api/v1/projects/search",
                headers=viewer_auth,
                params={"q": "并发权限项目"},
            )
            assert revoked.status_code == 409
            assert "并发权限项目" not in revoked.text

            monkeypatch.setattr(repository, "search_projects", original_search)
            owner = runtime.workspace_service.get_user_by_username("local-admin")
            _add_current_clip_and_release(
                runtime,
                project_id=project_id,
                run_id=run_id,
                owner_id=owner.user_id,
            )
            revision_calls = 0

            def revise_after_first_search(**kwargs: object):
                nonlocal revision_calls
                selection = original_search(**kwargs)
                revision_calls += 1
                if revision_calls == 1:
                    with runtime.engine.begin() as connection:
                        connection.execute(
                            update(CandidateClipRow)
                            .where(CandidateClipRow.project_id == project_id)
                            .values(current_revision=1)
                        )
                return selection

            monkeypatch.setattr(repository, "search_projects", revise_after_first_search)
            revised = client.get(
                "/api/v1/projects/search",
                headers=owner_auth,
                params={"q": "增长飞轮实战"},
            )
            assert revised.status_code == 409
            assert "增长飞轮实战" not in revised.text
    finally:
        runtime.close()


def test_saved_project_view_limit_and_damaged_row_isolation(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    media_root = tmp_path / "media"
    media_root.mkdir()
    settings = _settings(tmp_path, media_root)
    runtime = LiveClipRuntime.open(settings, project_root=project_root)
    app = create_app(settings, runtime=runtime, project_root=project_root)
    owner_auth = _auth("discovery-owner-token")
    owner = runtime.workspace_service.get_user_by_username("local-admin")
    now = datetime.now(UTC)
    damaged_id = "f" * 32
    try:
        with runtime.engine.begin() as connection:
            connection.execute(
                insert(SavedProjectViewRow).values(
                    id=damaged_id,
                    user_id=owner.user_id,
                    name="旧版损坏视图",
                    name_key="旧版损坏视图",
                    criteria_schema_version="999",
                    criteria_json={},
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(SavedProjectViewRow),
                [
                    {
                        "id": f"{index:032x}",
                        "user_id": owner.user_id,
                        "name": f"视图 {index:02d}",
                        "name_key": f"视图 {index:02d}",
                        "criteria_schema_version": "1",
                        "criteria_json": {},
                        "version": 1,
                        "created_at": now,
                        "updated_at": now + timedelta(seconds=index),
                    }
                    for index in range(49)
                ],
            )

        with TestClient(app, raise_server_exceptions=False) as client:
            listed = client.get("/api/v1/project-views", headers=owner_auth)
            assert listed.status_code == 200, listed.text
            assert len(listed.json()["views"]) == 49
            assert all(view["name"] != "旧版损坏视图" for view in listed.json()["views"])

            at_raw_row_limit = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-limit"},
                json={"name": "第 50 个有效视图", "criteria": {}},
            )
            assert at_raw_row_limit.status_code == 409

            with runtime.engine.begin() as connection:
                connection.execute(
                    delete(SavedProjectViewRow).where(SavedProjectViewRow.id == damaged_id)
                )

            created = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-limit-valid"},
                json={"name": "第 50 个有效视图", "criteria": {}},
            )
            assert created.status_code == 201, created.text
            over_limit = client.post(
                "/api/v1/project-views",
                headers={**owner_auth, "Idempotency-Key": "saved-view-limit-over"},
                json={"name": "超出限制", "criteria": {}},
            )
            assert over_limit.status_code == 409
    finally:
        runtime.close()
