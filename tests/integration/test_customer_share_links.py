# ruff: noqa: RUF001
"""Stage 19d: expiring, revocable LAN share links served by a separate app."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from liveclip.api.app import create_app
from liveclip.api.share import RefusedClientCounter, ShareRateLimiter, create_share_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.customer_delivery_settings import DualProfileImportSettings, ShareSettings
from tests.dual_profile_fixtures import build_run

pytestmark = pytest.mark.integration
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOKENS = {
    "owner": "share-link-owner-token",
    "reviewer": "share-link-reviewer-token",
    "editor": "share-link-editor-token",
    "viewer": "share-link-viewer-token",
    "outsider": "share-link-outsider-token",
}
URL = re.compile(r"^http://127\.0\.0\.1:8766/s/(?P<token>[A-Za-z0-9_-]{43})$")


@dataclass
class Harness:
    api: TestClient
    share: TestClient
    runtime: LiveClipRuntime
    settings: Settings
    project_id: str
    clips: dict[str, str]
    delivery_id: str

    def auth(self, role: str = "owner") -> dict[str, str]:
        return {"Authorization": f"Bearer {TOKENS[role]}"}

    def create_link(self, role: str = "owner", delivery_id: str | None = None, **body: Any) -> Any:
        return self.api.post(
            f"/api/v1/projects/{self.project_id}/customer-deliveries/"
            f"{delivery_id or self.delivery_id}/share-links",
            headers=self.auth(role),
            json=body,
        )

    def token(self, **body: Any) -> str:
        response = self.create_link(**body)
        assert response.status_code == 201, response.text
        match = URL.match(response.json()["url"])
        assert match is not None, response.json()["url"]
        return match["token"]

    def links(self, delivery_id: str | None = None) -> list[dict[str, Any]]:
        response = self.api.get(
            f"/api/v1/projects/{self.project_id}/customer-deliveries/"
            f"{delivery_id or self.delivery_id}/share-links",
            headers=self.auth("viewer"),
        )
        assert response.status_code == 200, response.text
        return list(response.json())

    def new_delivery(self, title: str) -> str:
        review = self.api.get(
            f"/api/v1/projects/{self.project_id}/dual-profile-import", headers=self.auth()
        ).json()
        selected = [
            clip["import_clip_id"]
            for group in review["review"]["groups"]
            for clip in group["clips"]
            if clip["selected_for_delivery"]
        ]
        created = self.api.post(
            f"/api/v1/projects/{self.project_id}/customer-deliveries",
            headers=self.auth(),
            json={"title": title, "expected_clip_ids": selected},
        )
        assert created.status_code == 202, created.text
        delivery_id = str(created.json()["delivery"]["delivery_id"])
        built = self.runtime.delivery_runner.run_customer_delivery_until_terminal(
            delivery_id, worker_id="share-test-worker", poll_seconds=0.05
        )
        assert built.status.value == "succeeded"
        return delivery_id


def _boot(tmp_path: Path, *, limiter: ShareRateLimiter | None = None) -> Iterator[Harness]:
    base = tmp_path.resolve()
    (base / "media").mkdir()
    (base / "evaluations").mkdir()
    fixture = build_run(base, relative_paths=False)
    settings = Settings(
        data_dir=base / "projects",
        allowed_media_roots_raw=str(base / "media"),
        api_token=SecretStr(TOKENS["owner"]),
        workspace_tokens_raw=json.dumps(
            {f"share-{role}": TOKENS[role] for role in ("reviewer", "editor", "viewer", "outsider")}
        ),
        ai_provider="mock",
        _env_file=None,
    )
    share_settings = ShareSettings(host="127.0.0.1", port=8766)
    runtime = LiveClipRuntime.open(
        settings,
        project_root=PROJECT_ROOT,
        dual_profile_settings=DualProfileImportSettings(
            import_roots_raw=str(base / "evaluations"),
            transcript_roots_raw=str(base / "evaluations"),
        ),
        share_settings=share_settings,
    )
    api_app = create_app(settings, runtime=runtime, project_root=PROJECT_ROOT)
    share_app = create_share_app(
        settings, share_settings=share_settings, runtime=runtime, rate_limiter=limiter
    )
    with (
        TestClient(api_app, raise_server_exceptions=False) as api,
        TestClient(
            share_app, raise_server_exceptions=False, client=("192.168.1.30", 50000)
        ) as share,
    ):
        owner = {"Authorization": f"Bearer {TOKENS['owner']}"}
        created = api.post(
            "/api/v1/dual-profile-imports",
            headers=owner,
            json={"run_dir": str(fixture.run_dir), "transcript_path": str(fixture.transcript)},
        )
        project_id = created.json()["project_id"]
        for role in ("reviewer", "editor", "viewer"):
            api.post(
                f"/api/v1/projects/{project_id}/members",
                headers=owner,
                json={"username": f"share-{role}", "display_name": role, "role": role},
            )
        review = api.get(f"/api/v1/projects/{project_id}/dual-profile-import", headers=owner)
        clips = {
            clip["candidate_id"]: clip["import_clip_id"]
            for group in review.json()["review"]["groups"]
            for clip in group["clips"]
        }
        base_url = f"/api/v1/projects/{project_id}/dual-profile-import/clips"
        api.post(
            f"{base_url}/{clips['lesson-one']}/decisions",
            headers=owner,
            json={"action": "approve", "title": "小课 & <b>标题</b>"},
        )
        for clip in ("short-one", "lesson-one"):
            api.post(
                f"{base_url}/{clips[clip]}/decisions", headers=owner, json={"action": "select"}
            )
        harness = Harness(api, share, runtime, settings, project_id, clips, "")
        harness.delivery_id = harness.new_delivery("张老师 · 分享版")
        yield harness
    runtime.close()


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    yield from _boot(tmp_path)


SECURITY = {
    "cache-control": "no-store",
    "referrer-policy": "no-referrer",
    "x-robots-tag": "noindex, nofollow",
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
}


def _assert_security_headers(response: Any) -> None:
    for name, value in SECURITY.items():
        assert response.headers[name] == value, name
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "set-cookie" not in response.headers
    assert "access-control-allow-origin" not in response.headers


def test_link_is_shown_once_and_only_its_hash_is_stored(harness: Harness) -> None:
    created = harness.create_link(expires_in_days=7)
    assert created.status_code == 201
    payload = created.json()
    token = URL.match(payload["url"])["token"]  # type: ignore[index]
    link = payload["link"]
    assert link["status"] == "active" and link["delivery_version"] == "v001"
    listing = harness.links()
    assert [item["link_id"] for item in listing] == [link["link_id"]]
    assert token not in json.dumps(listing)
    with harness.runtime.engine.connect() as connection:
        tables = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).scalars()
        for table in tables:
            for row in connection.execute(text(f'SELECT * FROM "{table}"')):
                assert token not in str(tuple(row)), table


def test_share_page_media_and_download(harness: Harness, caplog: pytest.LogCaptureFixture) -> None:
    token = harness.token()
    caplog.set_level(logging.INFO, logger="liveclip.share")
    page = harness.share.get(f"/s/{token}")
    assert page.status_code == 200
    _assert_security_headers(page)
    html = page.text
    assert "张老师 · 分享版" in html and "短片（1）" in html and "小课（1）" in html
    assert "小课 &amp; &lt;b&gt;标题&lt;/b&gt;" in html
    assert f'src="/s/{token}/clips/1/video"' in html
    assert f'href="/s/{token}/download"' in html and "下载全部（ZIP）" in html
    assert "此分享链接将于" in html and "失效" in html
    assert "<script" not in html

    full = harness.share.get(f"/s/{token}/clips/1/video")
    assert full.status_code == 200 and full.content == b"video-short-one"
    _assert_security_headers(full)
    assert "filename*=UTF-8''" in full.headers["content-disposition"]
    partial = harness.share.get(f"/s/{token}/clips/1/video", headers={"Range": "bytes=0-4"})
    assert partial.status_code == 206 and partial.content == b"video"
    assert partial.headers["content-range"] == "bytes 0-4/15"
    unsatisfiable = harness.share.get(
        f"/s/{token}/clips/1/video", headers={"Range": "bytes=999-1000"}
    )
    assert unsatisfiable.status_code == 416
    subtitle = harness.share.get(f"/s/{token}/clips/2/subtitle")
    assert subtitle.status_code == 200 and "-->" in subtitle.text
    archive = harness.share.get(f"/s/{token}/download")
    assert archive.status_code == 200 and archive.content[:2] == b"PK"
    disposition = archive.headers["content-disposition"]
    assert unquote(disposition.split("filename*=UTF-8''", 1)[1]) == "张老师-分享版-v001.zip"

    [link] = harness.links()
    assert link["view_count"] == 1
    assert link["download_count"] == 3  # full video, subtitle and ZIP; ranges are not counted
    assert link["last_accessed_at"] is not None
    messages = [record.getMessage() for record in caplog.records]
    assert any("/s/<redacted>" in message for message in messages)
    assert all(token not in message for message in messages)
    with harness.runtime.engine.connect() as connection:
        audits = connection.execute(
            text("SELECT after_json FROM audit_events WHERE target_type = 'customer_share_link'")
        ).scalars()
        assert all(token not in str(value) for value in audits)


def test_unknown_expired_and_revoked_links_are_indistinguishable(harness: Harness) -> None:
    expired_token = harness.token(expires_in_days=1)
    revoked_token = harness.token()
    [revoked, expired] = harness.links()
    with harness.runtime.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE customer_share_links SET expires_at = '2000-01-02 00:00:00.000000', "
                "created_at = '2000-01-01 00:00:00.000000' WHERE id = :id"
            ),
            {"id": expired["link_id"]},
        )
    revoke = harness.api.post(
        f"/api/v1/projects/{harness.project_id}/share-links/{revoked['link_id']}/revoke",
        headers=harness.auth("editor"),
    )
    assert revoke.status_code == 200 and revoke.json()["status"] == "revoked"
    unknown = "A" * 43
    responses = [
        harness.share.get(f"/s/{value}{suffix}")
        for value in (unknown, expired_token, revoked_token)
        for suffix in ("", "/clips/1/video", "/download")
    ]
    assert {response.status_code for response in responses} == {404}
    first = responses[0]
    for response in responses[1:]:
        assert response.content == first.content
        assert dict(response.headers) == dict(first.headers)
    statuses = {item["link_id"]: item["status"] for item in harness.links()}
    assert statuses == {revoked["link_id"]: "revoked", expired["link_id"]: "expired"}


def test_a_token_reaches_only_its_own_delivery(harness: Harness) -> None:
    first_token = harness.token()
    harness.api.post(
        f"/api/v1/projects/{harness.project_id}/dual-profile-import/clips/"
        f"{harness.clips['lesson-one']}/decisions",
        headers=harness.auth(),
        json={"action": "deselect"},
    )
    second = harness.new_delivery("第二版")
    assert "第二版" not in harness.share.get(f"/s/{first_token}").text
    assert harness.share.get(f"/s/{first_token}/clips/2/video").status_code == 200
    second_token = harness.token(delivery_id=second)
    assert harness.share.get(f"/s/{second_token}/clips/2/video").status_code == 404
    assert "第二版" in harness.share.get(f"/s/{second_token}").text


@pytest.mark.parametrize(
    "path",
    [
        "/s/{token}/clips/abc/video",
        "/s/{token}/clips/0/video",
        "/s/{token}/clips/-1/subtitle",
        "/s/{token}/clips/1/%2E%2E/%2E%2E/download",
        "/s/{token}/clips/1/poster",
        "/s/{token}/../../api/v1/projects",
        "/s/{token}%2F..%2F..%2Fapi",
        "/api/v1/projects",
        "/api/v1/health",
        "/api/v1/media/anything",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/",
    ],
)
def test_everything_else_is_the_same_404(harness: Harness, path: str) -> None:
    token = harness.token()
    harness.share.cookies.set("liveclip_session", "anything")
    try:
        response = harness.share.get(
            path.format(token=token),
            headers={"Authorization": f"Bearer {TOKENS['owner']}"},
        )
    finally:
        harness.share.cookies.clear()
    assert response.status_code == 404
    assert response.content == harness.share.get("/s/" + "B" * 43).content
    _assert_security_headers(response)


def test_other_methods_are_refused_without_side_effects(harness: Harness) -> None:
    token = harness.token()
    for method in ("POST", "PUT", "DELETE", "PATCH"):
        assert harness.share.request(method, f"/s/{token}").status_code == 404
    assert harness.links()[0]["view_count"] == 0


def test_internal_api_authorization_for_share_links(harness: Harness) -> None:
    assert harness.create_link(role="viewer").status_code == 403
    assert harness.create_link(role="reviewer").status_code == 403
    assert harness.create_link(role="outsider").status_code == 404
    assert harness.create_link(role="editor").status_code == 201
    assert harness.create_link(expires_in_days=0).status_code == 422
    assert harness.create_link(expires_in_days=31).status_code == 422
    assert harness.create_link(delivery_id="f" * 32).status_code == 404
    [link] = harness.links()
    viewer_revoke = harness.api.post(
        f"/api/v1/projects/{harness.project_id}/share-links/{link['link_id']}/revoke",
        headers=harness.auth("viewer"),
    )
    assert viewer_revoke.status_code == 403


def test_unfinished_delivery_cannot_be_shared(harness: Harness) -> None:
    review = harness.api.get(
        f"/api/v1/projects/{harness.project_id}/dual-profile-import", headers=harness.auth()
    ).json()
    selected = [
        clip["import_clip_id"]
        for group in review["review"]["groups"]
        for clip in group["clips"]
        if clip["selected_for_delivery"]
    ]
    queued = harness.api.post(
        f"/api/v1/projects/{harness.project_id}/customer-deliveries",
        headers=harness.auth(),
        json={"title": "未完成", "expected_clip_ids": selected},
    ).json()["delivery"]
    response = harness.create_link(delivery_id=queued["delivery_id"])
    assert response.status_code == 409


def test_archived_projects_stop_sharing(harness: Harness) -> None:
    token = harness.token()
    project = harness.api.get(
        f"/api/v1/projects/{harness.project_id}", headers=harness.auth()
    ).json()
    archived = harness.api.post(
        f"/api/v1/projects/{harness.project_id}/lifecycle",
        headers=harness.auth(),
        json={
            "expected_management_version": project["management_version"],
            "target": "archived",
            "reason": "归档",
        },
    )
    assert archived.status_code == 200
    assert harness.share.get(f"/s/{token}").status_code == 404
    assert harness.create_link().status_code == 403


def test_rate_limits_answer_429_with_retry_after(tmp_path: Path) -> None:
    clock = [1000.0]
    limiter = ShareRateLimiter(
        miss_limit=3,
        miss_window_seconds=600,
        link_limit=4,
        link_window_seconds=60,
        clock=lambda: clock[0],
    )
    for harness in _boot(tmp_path, limiter=limiter):
        token = harness.token()
        for _ in range(4):
            assert harness.share.get(f"/s/{token}").status_code == 200
        limited = harness.share.get(f"/s/{token}")
        assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
        _assert_security_headers(limited)
        clock[0] += 61
        assert harness.share.get(f"/s/{token}").status_code == 200
        for _ in range(3):
            assert harness.share.get("/s/" + "C" * 43).status_code == 404
        blocked = harness.share.get(f"/s/{token}")
        assert blocked.status_code == 429
        assert 1 <= int(blocked.headers["retry-after"]) <= 601
        clock[0] += 601
        assert harness.share.get(f"/s/{token}").status_code == 200


counter = RefusedClientCounter()


def _share_client(harness: Harness, host: str) -> TestClient:
    app = create_share_app(
        harness.settings,
        share_settings=ShareSettings(host="127.0.0.1", port=8766),
        runtime=harness.runtime,
        refused_counter=counter,
    )
    return TestClient(app, raise_server_exceptions=False, client=(host, 50000))


@pytest.mark.parametrize(
    "host",
    ["8.8.8.8", "100.64.1.2", "2001:4860:4860::8888", "::ffff:8.8.8.8", "testclient", ""],
)
def test_clients_outside_the_lan_get_the_generic_404(harness: Harness, host: str) -> None:
    token = harness.token()
    before = counter.count
    with _share_client(harness, host) as client:
        responses = [
            client.get(f"/s/{token}"),
            client.get(f"/s/{token}/clips/1/video"),
            client.get(f"/s/{token}/download"),
        ]
    generic = harness.share.get("/s/" + "D" * 43)
    for response in responses:
        assert response.status_code == 404
        assert response.content == generic.content
        _assert_security_headers(response)
    assert counter.count == before + 3
    [link] = harness.links()
    assert (link["view_count"], link["download_count"]) == (0, 0)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "::1",
        "10.1.2.3",
        "172.20.0.9",
        "192.168.31.8",
        "169.254.3.4",
        "fd12:3456::1",
        "fe80::1",
        "::ffff:192.168.1.9",
    ],
)
def test_loopback_and_lan_clients_are_served(harness: Harness, host: str) -> None:
    token = harness.token()
    with _share_client(harness, host) as client:
        assert client.get(f"/s/{token}").status_code == 200


def test_an_unexpected_error_is_the_generic_404_without_details(
    harness: Harness, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = harness.token()

    def explode(value: str) -> None:
        raise RuntimeError(f"boom {value}")

    monkeypatch.setattr(harness.runtime.share_link_service, "resolve", explode)
    caplog.set_level(logging.INFO, logger="liveclip.share")
    response = harness.share.get(f"/s/{token}")
    assert response.status_code == 404
    assert response.content == harness.share.get("/s/" + "E" * 43).content
    _assert_security_headers(response)
    assert "boom" not in response.text and "Traceback" not in response.text
    messages = [record.getMessage() for record in caplog.records]
    assert any("share_request_failed error_type=RuntimeError" in value for value in messages)
    assert all(token not in value and "boom" not in value for value in messages)
    assert all(record.exc_info is None for record in caplog.records)


def test_rate_limiter_memory_is_bounded() -> None:
    clock = [0.0]
    limiter = ShareRateLimiter(
        miss_window_seconds=10, link_window_seconds=10, clock=lambda: clock[0], prune_every=8
    )
    for index in range(200):
        limiter.record_miss(f"10.0.0.{index}")
        limiter.hit_link(f"link-{index}")
    assert limiter.tracked_keys() == (200, 200)
    clock[0] += 11
    for _ in range(8):
        limiter.check_client("10.9.9.9")
    assert limiter.tracked_keys() == (0, 0)
