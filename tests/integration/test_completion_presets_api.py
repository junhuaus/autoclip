"""Preset creation uses only disposable state and explicit Mock providers."""

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select, update

from liveclip.api.app import create_app
from liveclip.bootstrap import LiveClipRuntime
from liveclip.config import Settings
from liveclip.db.models import (
    CompletionIntentRow,
    PipelineRunRow,
    ProjectRow,
    WorkspaceUserRow,
)
from liveclip.providers.readiness import assess_provider_readiness

pytestmark = pytest.mark.integration
ROUTE = "/api/v1/completion-goals/from-preset"


@pytest.fixture
def api(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    source = media / "source.mp4"
    source.write_bytes(b"synthetic; no ingest or inference")
    settings = Settings(
        data_dir=tmp_path / "data",
        allowed_media_roots_raw=str(media),
        ai_provider="mock",
        api_token=SecretStr("synthetic-token"),
        _env_file=None,
    )
    root = Path(__file__).resolve().parents[2]
    with (
        LiveClipRuntime.open(settings, project_root=root) as runtime,
        TestClient(
            create_app(settings, runtime=runtime, project_root=root),
            headers={"Authorization": "Bearer synthetic-token"},
        ) as client,
    ):
        yield client, runtime, source


def body(source, **changes):
    return {"input_path": str(source), "preset_id": "short_highlight_v1", **changes}


def create(client, payload, key="pending"):
    return client.post(ROUTE, json=payload, headers={"Idempotency-Key": key})


def counts(runtime):
    with runtime.engine.connect() as connection:
        return tuple(
            connection.scalar(select(func.count()).select_from(row))
            for row in (
                ProjectRow,
                PipelineRunRow,
                CompletionIntentRow,
            )
        )


@pytest.mark.parametrize(
    "preset,durations",
    [
        ("short_highlight_v1", (45, 60, 90)),
        ("mini_lesson_v1", (90, 180, 300)),
    ],
)
@pytest.mark.parametrize("selection", ["default", "manual"])
def test_persisted_configuration_and_replay(api, preset, durations, selection):
    client, runtime, source = api
    payload = body(source, preset_id=preset, selection_policy=selection)
    first = create(client, payload)
    assert first.status_code == 202, first.text
    saved = first.json()
    assert first.headers["Location"].endswith(saved["goal"]["intent_id"])
    assert first.headers["Retry-After"] == "1"
    assert saved["download_url"] is None
    assert saved["goal"]["options"] == {
        "schema_version": "1",
        "target": "delivery",
        "include_zip": True,
        "selection_policy": selection,
        "preset_id": preset,
    }
    with runtime.engine.connect() as connection:
        config = connection.scalar(select(PipelineRunRow.config_json))
    for name, expected in {
        "provider": "mock",
        "clip_profile": preset.removesuffix("_v1"),
        "top_n": 15,
        "minimum_clip_ms": durations[0] * 1000,
        "semantic_target_clip_ms": durations[1] * 1000,
        "maximum_clip_ms": durations[2] * 1000,
        "clipping_algorithm": "semantic_windowed",
        "semantic_profile": "general",
        "semantic_score_threshold": 75,
        "semantic_full_context_budget_ratio": 0.58,
        "semantic_model_context_tokens": 128000,
    }.items():
        assert config[name] == expected
    assert create(client, payload).json() == saved
    other_preset = "mini_lesson_v1" if preset == "short_highlight_v1" else "short_highlight_v1"
    other_selection = "manual" if selection == "default" else "default"
    assert create(client, {**payload, "preset_id": other_preset}).status_code == 409
    assert create(client, {**payload, "selection_policy": other_selection}).status_code == 409
    assert create(client, {**payload, "input_path": str(source) + "changed"}).status_code == 409
    source.unlink()
    assert create(client, payload).json() == saved
    assert create(client, payload, "fresh").status_code == 422
    assert counts(runtime) == (1, 1, 1)


def test_validation_and_auth_before_mutation(api):
    client, runtime, source = api
    listed = client.get("/api/v1/completion-presets")
    assert listed.status_code == 200
    assert [item["display_name_zh"] for item in listed.json()["presets"]] == [
        "短高光",
        "完整小课",
    ]
    for payload in [
        body(source, top_n=1),
        body(source, preset_id="unknown"),
        body(source, selection_policy="invalid"),
        body(source, input_path=1),
    ]:
        assert create(client, payload).status_code == 422
    assert client.post(ROUTE, json=body(source)).status_code == 422
    assert create(client, body("/outside/source.mp4")).status_code == 422
    outside = source.parent.parent / "outside.mp4"
    outside.write_bytes(b"synthetic outside configured roots")
    alias = source.parent / "alias.mp4"
    alias.symlink_to(outside)
    assert create(client, body(outside)).status_code == 422
    assert create(client, body(alias)).status_code == 422
    for method, path in [("GET", "/api/v1/completion-presets"), ("POST", ROUTE)]:
        assert (
            client.request(
                method, path, headers={"Authorization": "Bearer invalid"}, json=body(source)
            ).status_code
            == 401
        )
    assert counts(runtime) == (0, 0, 0)


def test_canonical_default_and_low_level_compatibility(api):
    client, runtime, source = api
    first = create(client, body(source))
    assert first.status_code == 202
    assert create(client, body(source, selection_policy="default")).json() == first.json()
    low_level = client.post(
        "/api/v1/completion-goals",
        json={"job": {"input_path": str(source)}, "options": {}},
        headers={"Idempotency-Key": "low-level"},
    )
    assert low_level.status_code == 202
    assert low_level.json()["goal"]["options"]["preset_id"] is None
    assert low_level.json()["goal"]["intent_id"] != first.json()["goal"]["intent_id"]
    assert counts(runtime) == (2, 2, 2)


def test_readiness_replay_and_current_authority(api, monkeypatch):
    client, runtime, source = api
    first = create(client, body(source))
    assert first.status_code == 202
    settings = client.app.state.settings
    unavailable = replace(
        assess_provider_readiness(settings),
        processing_ready=False,
        blocking_issues=("SYNTHETIC_UNAVAILABLE",),
    )
    monkeypatch.setattr("liveclip.api.app.assess_provider_readiness", lambda _: unavailable)
    with TestClient(create_app(settings, runtime=runtime), headers=client.headers) as restarted:
        assert create(restarted, body(source)).json() == first.json()
        assert create(restarted, body(source), "fresh").status_code == 503
    with runtime.engine.begin() as connection:
        connection.execute(update(WorkspaceUserRow).values(is_active=False))
    assert create(client, body(source)).status_code == 404
    assert counts(runtime) == (1, 1, 1)
