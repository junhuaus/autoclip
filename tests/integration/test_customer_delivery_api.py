"""Stage 19c: immutable customer deliveries from imported dual-profile clips."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.customer_delivery_settings import DualProfileImportSettings
from tests.dual_profile_fixtures import build_run

pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOKENS = {
    "owner": "customer-delivery-owner-token",
    "reviewer": "customer-delivery-reviewer-token",
    "editor": "customer-delivery-editor-token",
    "viewer": "customer-delivery-viewer-token",
    "outsider": "customer-delivery-outsider-token",
}
FORBIDDEN_TOKENS = (
    "score",
    "risk",
    "manual_review",
    "review_reason",
    "routed",
    "candidate",
    "prompt",
    "/users",
    "data/",
    "evaluations",
    "quality",
    "flag",
)


@dataclass
class Harness:
    client: TestClient
    runtime: LiveClipRuntime
    base: Path
    project_id: str
    clips: dict[str, str]
    source_hash: str

    def auth(self, role: str = "owner", **extra: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKENS[role]}", **extra}

    def decide(self, clip: str, action: str, role: str = "owner", **body: Any) -> Any:
        return self.client.post(
            f"/api/v1/projects/{self.project_id}/dual-profile-import/clips/"
            f"{self.clips[clip]}/decisions",
            headers=self.auth(role),
            json={"action": action, **body},
        )

    def selected_ids(self) -> list[str]:
        review = self.client.get(
            f"/api/v1/projects/{self.project_id}/dual-profile-import", headers=self.auth()
        ).json()
        return [
            clip["import_clip_id"]
            for group in review["review"]["groups"]
            for clip in group["clips"]
            if clip["selected_for_delivery"]
        ]

    def create(self, role: str = "owner", **body: Any) -> Any:
        payload = {"title": "张老师 · 精选", "expected_clip_ids": self.selected_ids(), **body}
        return self.client.post(
            f"/api/v1/projects/{self.project_id}/customer-deliveries",
            headers=self.auth(role),
            json=payload,
        )

    def build(self, delivery_id: str) -> Any:
        return self.runtime.delivery_runner.run_customer_delivery_until_terminal(
            delivery_id, worker_id="customer-delivery-test", poll_seconds=0.05
        )

    def listing(self, role: str = "owner") -> list[dict[str, Any]]:
        response = self.client.get(
            f"/api/v1/projects/{self.project_id}/customer-deliveries", headers=self.auth(role)
        )
        assert response.status_code == 200, response.text
        return list(response.json())

    def download(self, url: str) -> Any:
        return self.client.get(url)


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    base = tmp_path.resolve()
    (base / "media").mkdir()
    (base / "evaluations").mkdir()
    fixture = build_run(base, relative_paths=False)
    settings = Settings(
        data_dir=base / "projects",
        allowed_media_roots_raw=str(base / "media"),
        api_token=SecretStr(TOKENS["owner"]),
        workspace_tokens_raw=json.dumps(
            {
                "cd-reviewer": TOKENS["reviewer"],
                "cd-editor": TOKENS["editor"],
                "cd-viewer": TOKENS["viewer"],
                "cd-outsider": TOKENS["outsider"],
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
        owner = {"Authorization": f"Bearer {TOKENS['owner']}"}
        created = client.post(
            "/api/v1/dual-profile-imports",
            headers=owner,
            json={"run_dir": str(fixture.run_dir), "transcript_path": str(fixture.transcript)},
        )
        assert created.status_code == 201, created.text
        project_id = created.json()["project_id"]
        for role in ("reviewer", "editor", "viewer"):
            assert (
                client.post(
                    f"/api/v1/projects/{project_id}/members",
                    headers=owner,
                    json={"username": f"cd-{role}", "display_name": role, "role": role},
                ).status_code
                == 200
            )
        review = client.get(
            f"/api/v1/projects/{project_id}/dual-profile-import", headers=owner
        ).json()
        clips = {
            clip["candidate_id"]: clip["import_clip_id"]
            for group in review["review"]["groups"]
            for clip in group["clips"]
        }
        source_hash = json.loads(fixture.final.read_text(encoding="utf-8"))["source_hash"]
        yield Harness(client, runtime, base, project_id, clips, source_hash)
    runtime.close()


def _select_both(harness: Harness, *, title: str = "给客户的小课标题") -> None:
    assert harness.decide("lesson-one", "approve", role="reviewer", title=title).status_code == 200
    assert harness.decide("lesson-one", "select", role="editor").status_code == 200
    assert harness.decide("short-one", "select", role="editor").status_code == 200


def _zip(harness: Harness, entry: dict[str, Any]) -> tuple[Any, zipfile.ZipFile]:
    response = harness.download(entry["download_url"])
    assert response.status_code == 200, response.text
    return response, zipfile.ZipFile(io.BytesIO(response.content))


def test_create_build_list_and_download_a_customer_delivery(harness: Harness) -> None:
    _select_both(harness)
    created = harness.create()
    assert created.status_code == 202, created.text
    delivery = created.json()["delivery"]
    assert delivery["delivery_version"] == "v001" and delivery["status"] == "queued"
    assert (delivery["clip_count"], delivery["short_count"], delivery["lesson_count"]) == (
        1 + 1,
        1,
        1,
    )
    assert created.json()["download_url"] is None

    built = harness.build(delivery["delivery_id"])
    assert built.status.value == "succeeded", built
    [entry] = harness.listing(role="viewer")
    assert entry["delivery"]["status"] == "succeeded"
    response, archive = _zip(harness, entry)
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]) == "张老师-精选-v001.zip"
    names = sorted(archive.namelist())
    assert names == [
        "checksums.sha256",
        "clips/lesson/02-给客户的小课标题.mp4",
        "clips/lesson/02-给客户的小课标题.srt",
        "clips/short/01-短片教学.mp4",
        "clips/short/01-短片教学.srt",
        "index.html",
        "manifest.json",
    ]
    manifest = json.loads(archive.read("manifest.json"))
    assert [clip["title"] for clip in manifest["clips"]] == ["短片教学", "给客户的小课标题"]
    index = archive.read("index.html").decode("utf-8")
    assert "给客户的小课标题" in index and "小课教学</h3>" not in index
    texts = [json.dumps(manifest, ensure_ascii=False).lower(), index.lower(), *names]
    for token in (*FORBIDDEN_TOKENS, harness.source_hash, str(harness.base).lower()):
        assert all(token not in text for text in texts), token
    assert archive.read("clips/short/01-短片教学.mp4") == b"video-short-one"


def test_later_decisions_never_change_v001_and_v002_reflects_them(harness: Harness) -> None:
    _select_both(harness)
    first = harness.create().json()["delivery"]
    harness.build(first["delivery_id"])
    [v001] = harness.listing()
    _, first_zip = _zip(harness, v001)
    first_manifest = json.loads(first_zip.read("manifest.json"))

    assert harness.decide("lesson-one", "reject", role="reviewer").status_code == 200
    assert (
        harness.decide("short-one", "approve", role="reviewer", title="改过的短片").status_code
        == 200
    )
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    second = harness.create(title="第二版").json()["delivery"]
    assert second["delivery_version"] == "v002" and second["clip_count"] == 1
    harness.build(second["delivery_id"])

    listing = {item["delivery"]["delivery_version"]: item for item in harness.listing()}
    _, again = _zip(harness, listing["v001"])
    assert json.loads(again.read("manifest.json")) == first_manifest
    _, v002 = _zip(harness, listing["v002"])
    second_manifest = json.loads(v002.read("manifest.json"))
    assert [clip["title"] for clip in second_manifest["clips"]] == ["改过的短片"]
    assert second_manifest["lesson_count"] == 0


def test_nothing_selected_or_stale_selection_is_a_conflict(harness: Harness) -> None:
    empty = harness.create()
    assert empty.status_code == 409 and "no deliverable clip" in empty.json()["error"]["message"]

    assert harness.decide("short-one", "select", role="editor").status_code == 200
    not_deliverable = harness.create(expected_clip_ids=[harness.clips["lesson-one"]])
    assert not_deliverable.status_code == 409
    assert "not deliverable" in not_deliverable.json()["error"]["message"]
    stale = harness.create(expected_clip_ids=[])
    assert stale.status_code == 409 and "selection changed" in stale.json()["error"]["message"]
    exact = harness.create(expected_clip_ids=[harness.clips["short-one"]])
    assert exact.status_code == 202


@pytest.mark.parametrize(
    ("role", "expected"),
    [("owner", 202), ("editor", 202), ("reviewer", 403), ("viewer", 403), ("outsider", 404)],
)
def test_creation_requires_deliver(harness: Harness, role: str, expected: int) -> None:
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    assert harness.create(role=role).status_code == expected


def test_archived_project_cannot_create_deliveries(harness: Harness) -> None:
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    project = harness.client.get(
        f"/api/v1/projects/{harness.project_id}", headers=harness.auth()
    ).json()
    archived = harness.client.post(
        f"/api/v1/projects/{harness.project_id}/lifecycle",
        headers=harness.auth(),
        json={
            "expected_management_version": project["management_version"],
            "target": "archived",
            "reason": "归档",
        },
    )
    assert archived.status_code == 200
    assert harness.create().status_code == 403


def test_idempotency_key_replays_the_same_version(harness: Harness) -> None:
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    headers = harness.auth(**{"Idempotency-Key": "customer-delivery-0001"})
    url = f"/api/v1/projects/{harness.project_id}/customer-deliveries"
    body = {"title": "交付", "expected_clip_ids": harness.selected_ids()}
    first = harness.client.post(url, headers=headers, json=body)
    second = harness.client.post(url, headers=headers, json=body)
    assert first.status_code == second.status_code == 202
    assert first.json()["delivery"]["delivery_id"] == second.json()["delivery"]["delivery_id"]
    conflict = harness.client.post(url, headers=headers, json={**body, "title": "不同标题"})
    assert conflict.status_code == 409
    assert len(harness.listing()) == 1


@pytest.mark.parametrize("title", ["", " ", "x" * 81, "含\x00控制"])
def test_invalid_titles_are_rejected(harness: Harness, title: str) -> None:
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    assert harness.create(title=title).status_code == 422


def test_expected_clip_ids_are_required(harness: Harness) -> None:
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    response = harness.client.post(
        f"/api/v1/projects/{harness.project_id}/customer-deliveries",
        headers=harness.auth(),
        json={"title": "交付"},
    )
    assert response.status_code == 422


def test_download_requires_access_and_a_finished_build(harness: Harness) -> None:
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    delivery = harness.create().json()["delivery"]
    url = f"/api/v1/customer-deliveries/{delivery['delivery_id']}/download"
    assert harness.client.get(url, headers=harness.auth()).status_code == 409
    harness.build(delivery["delivery_id"])
    assert harness.client.get(url, headers=harness.auth("outsider")).status_code == 404
    assert harness.client.get(url, headers=harness.auth("viewer")).status_code == 200


def test_tampered_imported_media_fails_the_build_without_publishing(harness: Harness) -> None:
    assert harness.decide("short-one", "select", role="editor").status_code == 200
    delivery = harness.create().json()["delivery"]
    project_dir = harness.base / "projects" / harness.project_id
    [video] = list(project_dir.glob("imports/*/short_highlight/short-one.mp4"))
    video.chmod(0o600)
    video.write_bytes(b"tampered after import")

    built = harness.build(delivery["delivery_id"])

    assert built.status.value == "failed"
    assert built.error_code == "CUSTOMER_DELIVERY_VALIDATION_FAILED"
    [entry] = harness.listing()
    assert entry["download_url"] is None
    assert not (project_dir / "customer-deliveries" / "v001").exists()


def test_a_stale_worker_cannot_commit_after_its_lease_expired(harness: Harness) -> None:
    from datetime import UTC, datetime, timedelta

    from liveclip.application.pipeline import LeaseIdentity
    from liveclip.db.customer_delivery_repository import SqlAlchemyCustomerDeliveryRepository
    from liveclip.delivery.customer_delivery_task_handler import CustomerDeliveryTaskHandler
    from liveclip.domain.state_transitions import TaskKind

    assert harness.decide("short-one", "select", role="editor").status_code == 200
    delivery = harness.create().json()["delivery"]
    queue = harness.runtime.task_queue
    repository = SqlAlchemyCustomerDeliveryRepository(harness.runtime.engine)
    handler = CustomerDeliveryTaskHandler(
        data_dir=harness.base / "projects",
        publication_fence=repository.assert_customer_delivery_current,
    )
    stale = queue.claim(worker_id="stale-worker", task_kind=TaskKind.DELIVERY)
    assert stale is not None
    stale_identity = LeaseIdentity(
        task_id=stale.task_id, worker_id=stale.worker_id, lease_token=stale.lease_token
    )
    work = repository.start_customer_delivery(stale_identity)
    persistence = handler.execute(work, stale_identity, cancel_requested=lambda: False)

    later = datetime.now(UTC) + timedelta(hours=2)
    fresh = queue.claim(worker_id="fresh-worker", task_kind=TaskKind.DELIVERY, now=later)
    assert fresh is not None and fresh.task_id == stale.task_id
    assert fresh.lease_token != stale.lease_token

    assert repository.complete_customer_delivery(stale_identity, work, persistence) is False
    snapshot = repository.get_customer_delivery(delivery["delivery_id"])
    assert snapshot.status.value != "succeeded" and snapshot.zip_asset_id is None
    with pytest.raises(Exception, match="no longer publishable"):
        repository.assert_customer_delivery_current(stale_identity, work)


def test_purge_removes_a_project_with_a_built_customer_delivery(harness: Harness) -> None:
    from liveclip.application.storage import ProjectPurgeCommand

    assert harness.decide("short-one", "select", role="editor").status_code == 200
    delivery = harness.create().json()["delivery"]
    assert harness.build(delivery["delivery_id"]).status.value == "succeeded"
    project_dir = harness.base / "projects" / harness.project_id
    assert (project_dir / "customer-deliveries" / "v001" / "manifest.json").is_file()
    project = harness.client.get(
        f"/api/v1/projects/{harness.project_id}", headers=harness.auth()
    ).json()
    assert (
        harness.client.post(
            f"/api/v1/projects/{harness.project_id}/lifecycle",
            headers=harness.auth(),
            json={
                "expected_management_version": project["management_version"],
                "target": "archived",
                "reason": "清理",
            },
        ).status_code
        == 200
    )
    admin = harness.runtime.workspace_service.get_user_by_username("local-admin")
    service = harness.runtime.storage_administration_service
    plan = service.project_purge_plan(admin, harness.project_id)
    assert plan.ready is True, plan.blockers
    service.purge_project(
        admin,
        harness.project_id,
        ProjectPurgeCommand(
            snapshot_fingerprint=plan.snapshot_fingerprint,
            project_name=plan.project_name,
            administrator_username=admin.username,
            confirmation_phrase=plan.confirmation_phrase,
        ),
    )
    assert not project_dir.exists()
    with harness.runtime.engine.connect() as connection:
        for table in (
            "customer_deliveries",
            "customer_delivery_clips",
            "dual_profile_imports",
            "assets",
            "projects",
        ):
            count = connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()
            assert count == 0, table


def test_auto_selected_clips_with_reviewer_notes_need_an_explicit_keep(tmp_path: Path) -> None:
    from liveclip.db.dual_profile_repository import SqlAlchemyDualProfileImportRepository
    from liveclip.domain.customer_delivery import ClipDecisionAction

    for harness in _flagged_harness(tmp_path):
        refused = harness.decide("short-one", "select", role="editor")
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "CUSTOMER_TEXT_WARNING"
        kept = harness.decide("short-one", "select", role="editor", acknowledge_warnings=True)
        assert kept.status_code == 200, kept.text
        short = next(
            clip
            for group in kept.json()["review"]["groups"]
            for clip in group["clips"]
            if clip["candidate_id"] == "short-one"
        )
        assert short["selected_for_delivery"] is True
        assert short["decisions"][-1]["acknowledge_warnings"] is True
        assert harness.create().status_code == 202

        # Defense in depth: a selection that bypassed the service gate is still
        # refused when the customer delivery is created.
        harness.decide("short-one", "deselect", role="editor")
        repository = SqlAlchemyDualProfileImportRepository(harness.runtime.engine)
        editor = harness.runtime.workspace_service.get_user_by_username("local-admin")
        from datetime import UTC, datetime

        repository.append_decision(
            project_id=harness.project_id,
            import_clip_id=harness.clips["short-one"],
            acting_user_id=editor.user_id,
            action=ClipDecisionAction.SELECT,
            require_deliverable=True,
            now=datetime.now(UTC),
        )
        blocked = harness.create(title="第二版")
        assert blocked.status_code == 409
        error = blocked.json()["error"]
        assert error["code"] == "CUSTOMER_TEXT_WARNING"
        assert error["details"][0]["location"][0] == harness.clips["short-one"]
        assert harness.decide("short-one", "reject", acknowledge_warnings=True).status_code == 422


def _flagged_harness(tmp_path: Path) -> Iterator[Harness]:
    base = tmp_path.resolve()
    (base / "media").mkdir()
    (base / "evaluations").mkdir()
    fixture = build_run(
        base, relative_paths=False, short_summary="老师示范打哈欠。“那口腔”疑为转写错误。"
    )
    settings = Settings(
        data_dir=base / "projects",
        allowed_media_roots_raw=str(base / "media"),
        api_token=SecretStr(TOKENS["owner"]),
        workspace_tokens_raw=json.dumps({"customer-delivery-editor": TOKENS["editor"]}),
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
        owner = {"Authorization": f"Bearer {TOKENS['owner']}"}
        created = client.post(
            "/api/v1/dual-profile-imports",
            headers=owner,
            json={"run_dir": str(fixture.run_dir), "transcript_path": str(fixture.transcript)},
        )
        project_id = created.json()["project_id"]
        client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=owner,
            json={
                "username": "customer-delivery-editor",
                "display_name": "editor",
                "role": "editor",
            },
        )
        review = client.get(f"/api/v1/projects/{project_id}/dual-profile-import", headers=owner)
        clips = {
            clip["candidate_id"]: clip["import_clip_id"]
            for group in review.json()["review"]["groups"]
            for clip in group["clips"]
        }
        yield Harness(client, runtime, base, project_id, clips, "")
    runtime.close()
