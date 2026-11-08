"""Stage 19b: dual-profile import and internal review API."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.customer_delivery_settings import DualProfileImportSettings
from tests.dual_profile_fixtures import RunFixture, build_run

pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOKENS = {
    "owner": "dual-owner-token",
    "reviewer": "dual-reviewer-token",
    "editor": "dual-editor-token",
    "viewer": "dual-viewer-token",
    "outsider": "dual-outsider-token",
}


@dataclass
class ApiHarness:
    client: TestClient
    base: Path
    fixture: RunFixture
    runtime: LiveClipRuntime
    settings: Settings

    def auth(self, role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKENS[role]}"}

    def import_run(self, role: str = "owner", **overrides: Any) -> Any:
        body = {
            "run_dir": str(self.fixture.run_dir),
            "transcript_path": str(self.fixture.transcript),
            **overrides,
        }
        return self.client.post("/api/v1/dual-profile-imports", headers=self.auth(role), json=body)

    def review(self, project_id: str, role: str = "owner") -> Any:
        return self.client.get(
            f"/api/v1/projects/{project_id}/dual-profile-import", headers=self.auth(role)
        )

    def decide(self, project_id: str, clip_id: str, role: str = "owner", **body: Any) -> Any:
        return self.client.post(
            f"/api/v1/projects/{project_id}/dual-profile-import/clips/{clip_id}/decisions",
            headers=self.auth(role),
            json=body,
        )


@pytest.fixture
def api(tmp_path: Path) -> Iterator[ApiHarness]:
    base = tmp_path.resolve()
    media_root = base / "media"
    media_root.mkdir()
    (base / "evaluations").mkdir()
    fixture = build_run(base, relative_paths=False)
    settings = Settings(
        data_dir=base / "projects",
        allowed_media_roots_raw=str(media_root),
        api_token=SecretStr(TOKENS["owner"]),
        workspace_tokens_raw=json.dumps(
            {
                "dual-reviewer": TOKENS["reviewer"],
                "dual-editor": TOKENS["editor"],
                "dual-viewer": TOKENS["viewer"],
                "dual-outsider": TOKENS["outsider"],
            }
        ),
        ai_provider="mock",
        _env_file=None,
    )
    runtime = LiveClipRuntime.open(
        settings,
        project_root=PROJECT_ROOT,
        dual_profile_settings=DualProfileImportSettings(
            import_roots_raw=str(base / "evaluations"),
            transcript_roots_raw=str(base / "evaluations"),
        ),
    )
    app = create_app(settings, runtime=runtime, project_root=PROJECT_ROOT)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield ApiHarness(
            client=client, base=base, fixture=fixture, runtime=runtime, settings=settings
        )


def _imported_project(api: ApiHarness) -> str:
    created = api.import_run()
    assert created.status_code == 201, created.text
    project_id = str(created.json()["project_id"])
    for role in ("reviewer", "editor", "viewer"):
        added = api.client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=api.auth("owner"),
            json={"username": f"dual-{role}", "display_name": f"{role}成员", "role": role},
        )
        assert added.status_code == 200, added.text
    return project_id


def _clips(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        clip["candidate_id"]: clip
        for group in payload["review"]["groups"]
        for clip in group["clips"]
    }


def test_import_creates_a_listed_runless_project_and_is_idempotent(api: ApiHarness) -> None:
    created = api.import_run()
    assert created.status_code == 201
    body = created.json()
    assert body["created"] is True and body["clip_count"] == 2 and len(body["snapshot"]) == 20
    again = api.import_run()
    assert again.status_code == 200
    assert again.json()["project_id"] == body["project_id"] and again.json()["created"] is False

    project = api.client.get(f"/api/v1/projects/{body['project_id']}", headers=api.auth("owner"))
    assert project.status_code == 200
    snapshot = project.json()
    assert snapshot["source_kind"] == "dual_profile_import"
    assert snapshot["current_run_id"] == "" and snapshot["generation"] == 0
    assert snapshot["lifecycle"] == "editorial_review"
    assert snapshot["status"] == "pending_review"
    assert snapshot["source_filename"] == "直播源.ts"

    listed = api.client.get("/api/v1/projects", headers=api.auth("owner"))
    assert listed.status_code == 200
    assert [item["project_id"] for item in listed.json()] == [body["project_id"]]
    searched = api.client.get("/api/v1/projects/search", headers=api.auth("owner"))
    assert searched.status_code == 200, searched.text
    assert [item["project"]["project_id"] for item in searched.json()["items"]] == [
        body["project_id"]
    ]
    run_endpoint = api.client.get("/api/v1/runs/", headers=api.auth("owner"))
    assert run_endpoint.status_code == 404


def test_review_groups_internal_fields_and_signed_media(api: ApiHarness) -> None:
    project_id = _imported_project(api)
    response = api.review(project_id, role="viewer")
    assert response.status_code == 200
    payload = response.json()
    review = payload["review"]
    assert [
        (group["profile"], group["label"], len(group["clips"])) for group in review["groups"]
    ] == [
        ("short_highlight", "短片", 1),
        ("mini_lesson", "小课", 1),
    ]
    clips = _clips(payload)
    short, lesson = clips["short-one"], clips["lesson-one"]
    assert short["routed_status"] == "selected" and short["deliverable"] is True
    assert lesson["routed_status"] == "manual_review" and lesson["deliverable"] is False
    assert lesson["review_state"] == "pending" and lesson["score"] == 88
    assert lesson["review_reason"] == "小课教学内部审核理由"
    assert review["deliverable_count"] == 1 and review["selected_count"] == 0
    url = payload["asset_urls"][lesson["video_asset_id"]]
    assert url.startswith(f"/api/v1/media/{lesson['video_asset_id']}?")
    media = api.client.get(url)
    assert media.status_code == 200 and media.content == b"video-lesson-one"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(api.base) not in serialized
    assert "evaluations" not in serialized


@pytest.mark.parametrize(
    ("role", "action", "expected"),
    [
        ("viewer", "approve", 403),
        ("viewer", "reject", 403),
        ("viewer", "select", 403),
        ("viewer", "deselect", 403),
        ("reviewer", "approve", 200),
        ("reviewer", "reject", 200),
        ("reviewer", "select", 403),
        ("reviewer", "deselect", 403),
        ("editor", "approve", 403),
        ("editor", "reject", 403),
        ("editor", "select", 200),
        ("editor", "deselect", 200),
        ("owner", "approve", 200),
        ("owner", "select", 200),
        ("outsider", "approve", 404),
        ("outsider", "select", 404),
    ],
)
def test_decision_authorization_matrix(
    api: ApiHarness, role: str, action: str, expected: int
) -> None:
    project_id = _imported_project(api)
    short = _clips(api.review(project_id).json())["short-one"]

    response = api.decide(project_id, short["import_clip_id"], role=role, action=action)

    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["error"]["code"] == "PROJECT_ACTION_DENIED"


def test_outsiders_and_other_projects_cannot_see_or_reach_clips(api: ApiHarness) -> None:
    project_id = _imported_project(api)
    clip_id = _clips(api.review(project_id).json())["short-one"]["import_clip_id"]
    other = build_run(api.base, name="run-2", relative_paths=False)
    second = api.client.post(
        "/api/v1/dual-profile-imports",
        headers=api.auth("outsider"),
        json={"run_dir": str(other.run_dir), "transcript_path": str(other.transcript)},
    )
    assert second.status_code == 201, second.text
    other_project = second.json()["project_id"]

    assert api.review(project_id, role="outsider").status_code == 404
    assert api.review(other_project, role="owner").status_code == 404
    crossed = api.decide(other_project, clip_id, role="outsider", action="approve")
    assert crossed.status_code == 404
    assert api.decide(project_id, "f" * 32, action="approve").status_code == 404


def test_select_is_refused_until_the_clip_is_deliverable(api: ApiHarness) -> None:
    project_id = _imported_project(api)
    lesson_id = _clips(api.review(project_id).json())["lesson-one"]["import_clip_id"]

    refused = api.decide(project_id, lesson_id, role="editor", action="select")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "STATE_CONFLICT"

    assert api.decide(project_id, lesson_id, role="reviewer", action="approve").status_code == 200
    selected = api.decide(project_id, lesson_id, role="editor", action="select")
    assert _clips(selected.json())["lesson-one"]["selected_for_delivery"] is True

    rejected = api.decide(project_id, lesson_id, role="reviewer", action="reject")
    lesson = _clips(rejected.json())["lesson-one"]
    assert lesson["deliverable"] is False and lesson["selected_for_delivery"] is False
    assert api.decide(project_id, lesson_id, role="editor", action="select").status_code == 409

    reapproved = api.decide(project_id, lesson_id, role="reviewer", action="approve")
    assert _clips(reapproved.json())["lesson-one"]["selected_for_delivery"] is False


def test_override_flow_and_reapproval_with_prefilled_text(api: ApiHarness) -> None:
    project_id = _imported_project(api)
    lesson_id = _clips(api.review(project_id).json())["lesson-one"]["import_clip_id"]

    approved = api.decide(
        project_id,
        lesson_id,
        role="reviewer",
        action="approve",
        title="审核后的小课标题",
        hook="审核后的钩子",
    )
    assert approved.status_code == 200
    lesson = _clips(approved.json())["lesson-one"]
    assert lesson["effective"] == {
        "title": "审核后的小课标题",
        "hook": "审核后的钩子",
        "summary": "小课教学内容摘要",
    }
    assert lesson["original"]["title"] == "小课教学" and lesson["has_override"] is True
    assert lesson["decisions"][0]["actor_username"] == "dual-reviewer"
    assert lesson["decisions"][0]["title_override"] == "审核后的小课标题"

    api.decide(project_id, lesson_id, role="reviewer", action="reject")
    prefilled = lesson["effective"]
    reapproved = api.decide(project_id, lesson_id, role="reviewer", action="approve", **prefilled)
    assert _clips(reapproved.json())["lesson-one"]["effective"] == prefilled

    plain = api.decide(project_id, lesson_id, role="reviewer", action="approve")
    assert _clips(plain.json())["lesson-one"]["effective"]["title"] == "小课教学"
    assert [value["action"] for value in _clips(plain.json())["lesson-one"]["decisions"]] == [
        "approve",
        "reject",
        "approve",
        "approve",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "reject", "title": "拒绝不能改写"},
        {"action": "select", "summary": "选择不能改写"},
        {"action": "approve", "title": " 首尾空格 "},
        {"action": "approve", "title": "x" * 121},
        {"action": "approve", "hook": "含\x00字符"},
        {"action": "publish"},
    ],
)
def test_invalid_decisions_are_rejected(api: ApiHarness, body: dict[str, Any]) -> None:
    project_id = _imported_project(api)
    lesson_id = _clips(api.review(project_id).json())["lesson-one"]["import_clip_id"]

    response = api.decide(project_id, lesson_id, role="owner", **body)

    assert response.status_code == 422, response.text
    assert _clips(api.review(project_id).json())["lesson-one"]["decisions"] == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_dir": "/definitely/not/allowed/run"},
        {"run_dir": "evaluations/../outside"},
        {"transcript_path": "/etc/hosts"},
        {"run_dir": "relative/missing/run"},
    ],
)
def test_import_errors_do_not_leak_paths(api: ApiHarness, overrides: dict[str, str]) -> None:
    response = api.import_run(**overrides)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "DUAL_PROFILE_IMPORT_INVALID"
    serialized = json.dumps(response.json(), ensure_ascii=False)
    for fragment in (str(api.base), "/definitely", "/etc", "../outside", "relative/missing"):
        assert fragment not in serialized


def test_tampered_import_reports_a_safe_reason(api: ApiHarness) -> None:
    video = api.fixture.run_dir / "renders" / "short_highlight" / "short-one.mp4"
    video.write_bytes(b"tampered")

    response = api.import_run()

    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert "differs from its manifest hash" in message and str(api.base) not in message
    assert api.client.get("/api/v1/projects", headers=api.auth("owner")).json() == []


IMPORTED_OWNER_ACTIONS = [
    "read",
    "manage_members",
    "manage_project",
    "review_clip",
    "comment",
    "deliver",
]


def _guarded_requests(project_id: str) -> list[tuple[str, str, dict[str, Any], dict[str, str]]]:
    clip = "c" * 32
    return [
        (
            "runs",
            f"/api/v1/projects/{project_id}/runs",
            {"clipping_algorithm": "a"},
            {"Idempotency-Key": "imported-run-0001"},
        ),
        (
            "reviews-batch",
            f"/api/v1/projects/{project_id}/reviews/batch",
            {"items": [{"clip_id": clip, "expected_revision": 1, "status": "approved"}]},
            {"Idempotency-Key": "imported-batch-0001"},
        ),
        (
            "deliveries",
            f"/api/v1/projects/{project_id}/deliveries",
            {"include_zip": True},
            {"Idempotency-Key": "imported-delivery-0001"},
        ),
        (
            "edit-packages",
            f"/api/v1/projects/{project_id}/edit-packages",
            {"items": [{"clip_id": clip, "expected_revision": 1}]},
            {"Idempotency-Key": "imported-edit-0001"},
        ),
        (
            "releases",
            f"/api/v1/projects/{project_id}/releases",
            {
                "clip_id": clip,
                "expected_revision": 1,
                "platform": "douyin",
                "account_label": "主账号",
            },
            {"Idempotency-Key": "imported-release-0001"},
        ),
    ]


@pytest.mark.parametrize(
    "name", ["runs", "reviews-batch", "deliveries", "edit-packages", "releases"]
)
def test_pipeline_actions_are_refused_on_imported_projects(api: ApiHarness, name: str) -> None:
    project_id = _imported_project(api)
    _, path, body, headers = next(
        value for value in _guarded_requests(project_id) if value[0] == name
    )

    response = api.client.post(path, headers={**api.auth("owner"), **headers}, json=body)

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STATE_CONFLICT"
    assert "imported dual-profile projects" in response.json()["error"]["message"]
    project = api.client.get(f"/api/v1/projects/{project_id}", headers=api.auth("owner")).json()
    assert project["source_kind"] == "dual_profile_import"
    assert project["current_run_id"] == "" and project["generation"] == 0
    assert project["lifecycle"] == "editorial_review"
    with api.runtime.engine.connect() as connection:
        for table in ("pipeline_runs", "deliveries", "edit_packages", "release_items", "tasks"):
            count = connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
            assert count == 0, table
    assert api.review(project_id).status_code == 200


def test_imported_project_exposes_only_supported_actions(api: ApiHarness) -> None:
    project_id = _imported_project(api)
    owner = api.client.get(f"/api/v1/projects/{project_id}", headers=api.auth("owner")).json()
    assert owner["allowed_actions"] == IMPORTED_OWNER_ACTIONS
    editor = api.client.get(f"/api/v1/projects/{project_id}", headers=api.auth("editor")).json()
    assert editor["allowed_actions"] == ["read", "comment", "deliver"]
    reviewer = api.client.get(f"/api/v1/projects/{project_id}", headers=api.auth("reviewer")).json()
    assert reviewer["allowed_actions"] == ["read", "review_clip", "comment"]


def test_create_run_repository_refuses_imported_projects(api: ApiHarness) -> None:
    from liveclip.application.pipeline import PipelineConflict
    from liveclip.bootstrap import pipeline_config_from_settings

    project_id = _imported_project(api)
    with pytest.raises(PipelineConflict, match="imported dual-profile projects"):
        api.runtime.pipeline_service.create_run(
            project_id=project_id,
            config=pipeline_config_from_settings(api.settings),
            max_stage_retries=1,
        )
    snapshot = api.runtime.pipeline_service.get_project(project_id)
    assert snapshot.source_kind == "dual_profile_import"


def test_archived_imported_project_blocks_decisions(api: ApiHarness) -> None:
    project_id = _imported_project(api)
    lesson_id = _clips(api.review(project_id).json())["lesson-one"]["import_clip_id"]
    project = api.client.get(f"/api/v1/projects/{project_id}", headers=api.auth("owner")).json()
    archived = api.client.post(
        f"/api/v1/projects/{project_id}/lifecycle",
        headers=api.auth("owner"),
        json={
            "expected_management_version": project["management_version"],
            "target": "archived",
            "reason": "归档导入项目",
        },
    )
    assert archived.status_code == 200, archived.text

    for role, action in (("owner", "approve"), ("reviewer", "reject"), ("editor", "select")):
        response = api.decide(project_id, lesson_id, role=role, action=action)
        assert response.status_code == 403, response.text
    assert api.review(project_id).status_code == 200


def test_storage_purge_removes_an_imported_project(api: ApiHarness) -> None:
    from liveclip.application.storage import ProjectPurgeCommand

    project_id = _imported_project(api)
    lesson_id = _clips(api.review(project_id).json())["lesson-one"]["import_clip_id"]
    assert api.decide(project_id, lesson_id, role="reviewer", action="approve").status_code == 200
    project_dir = api.base / "projects" / project_id
    assert project_dir.is_dir()
    project = api.client.get(f"/api/v1/projects/{project_id}", headers=api.auth("owner")).json()
    archived = api.client.post(
        f"/api/v1/projects/{project_id}/lifecycle",
        headers=api.auth("owner"),
        json={
            "expected_management_version": project["management_version"],
            "target": "archived",
            "reason": "清理导入项目",
        },
    )
    assert archived.status_code == 200, archived.text
    admin = api.runtime.workspace_service.get_user_by_username("local-admin")
    service = api.runtime.storage_administration_service
    plan = service.project_purge_plan(admin, project_id)
    assert plan.ready is True

    service.purge_project(
        admin,
        project_id,
        ProjectPurgeCommand(
            snapshot_fingerprint=plan.snapshot_fingerprint,
            project_name=plan.project_name,
            administrator_username=admin.username,
            confirmation_phrase=plan.confirmation_phrase,
        ),
    )

    assert not project_dir.exists()
    with api.runtime.engine.connect() as connection:
        for table in (
            "projects",
            "dual_profile_imports",
            "dual_profile_import_clips",
            "dual_profile_clip_decisions",
            "assets",
        ):
            count = connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
            assert count == 0, table
    assert (api.fixture.run_dir / "final-validated.json").is_file()
    assert (
        api.client.get(f"/api/v1/projects/{project_id}", headers=api.auth("owner")).status_code
        == 404
    )
