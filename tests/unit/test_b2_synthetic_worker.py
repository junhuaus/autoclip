from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from liveclip.bootstrap import LiveClipRuntime
from liveclip.cli.app import app
from liveclip.config import Settings, get_settings
from liveclip.providers.asr.mock import DEFAULT_MOCK_SCRIPT
from scripts.b2_synthetic_worker import LONG_SCRIPT, PackagingPause, validate_fixture
from scripts.e2e_fixture import (
    allocated_e2e_root,
    assert_ports_available,
    cleanup_fixture,
    create_fixture,
)
from scripts.verify_completion_retained import validate_browser_execution


def test_browser_harness_clears_cloud_credentials_before_any_process() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/run_real_browser_e2e.sh").read_text()
    active_lines = [
        line.strip()
        for line in script.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    # A fixed startup prefix excludes conditionals, functions and subprocesses
    # before the exports, including the first path lookup and browser check.
    exports = [
        'export LIVECLIP_AI_PROVIDER="mock"',
        'export OPENAI_API_KEY=""',
        'export OPENROUTER_API_KEY=""',
    ]
    assert active_lines[:4] == ["set -Eeuo pipefail", *exports]
    for export in exports:
        assert active_lines.count(export) == 1


def test_nested_b2_overrides_inherited_completion_ports() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts/run_real_browser_e2e.sh").read_text()
    nested = script.split('if [[ "${E2E_SCENARIO}" == "completion" ]]; then\n')[1]
    words = shlex.split(nested.replace("\\\n", ""), comments=True)
    assignments = dict(word.split("=", 1) for word in words[: words.index("bash")])
    assert assignments == {
        "LIVECLIP_E2E_API_PORT": "18767",
        "LIVECLIP_E2E_WEB_PORT": "15176",
        "LIVECLIP_E2E_SCENARIO": "b2",
    }
    b2_ports = {int(assignments[f"LIVECLIP_E2E_{kind}_PORT"]) for kind in ("API", "WEB")}
    legacy_ports = {
        int(port) for port in re.findall(r"LIVECLIP_E2E_(?:API|WEB)_PORT:-(\d+)", script)
    }
    package = json.loads((root / "apps/web/package.json").read_text())
    completion_ports = {
        int(port)
        for port in re.findall(
            r"LIVECLIP_E2E_(?:API|WEB)_PORT=(\d+)", package["scripts"]["e2e:real"]
        )
    }
    assert len(legacy_ports) == len(completion_ports) == len(b2_ports) == 2
    assert b2_ports.isdisjoint(legacy_ports | completion_ports)
    assert words[words.index("bash") + 1 :] == [
        "${PROJECT_DIR}/scripts/run_real_browser_e2e.sh",
        "fi",
    ]


@pytest.mark.parametrize("ports", [(0, 15176), (18767, 65536), (18767, 18767)])
def test_browser_ports_fail_closed_on_invalid_pair(ports: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="distinct valid TCP ports"):
        assert_ports_available(*ports)


@pytest.mark.parametrize("occupied_api", [True, False])
def test_browser_ports_fail_closed_on_occupied_listener(occupied_api: bool) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        occupied = listener.getsockname()[1]
        other = 15176 if occupied != 15176 else 18767
        ports = (occupied, other) if occupied_api else (other, occupied)
        with pytest.raises(OSError):
            assert_ports_available(*ports)


@pytest.mark.parametrize("scenario", ["legacy", "completion", "b2"])
def test_browser_execution_requires_named_unretried_case(scenario: str) -> None:
    filename, title = (
        (
            "review-delivery-real.spec.ts",
            "drives the real API, leased Worker and FFmpeg through delivered",
        )
        if scenario == "legacy"
        else (
            "completion-goal-real.spec.ts",
            "browser disconnect preserves a manual completion and its one signed ZIP",
        )
    )
    report = {
        "stats": {"expected": 1, "skipped": 0, "unexpected": 0, "flaky": 0},
        "errors": [],
        "suites": [
            {
                "suites": [
                    {
                        "specs": [
                            {
                                "file": filename,
                                "title": title,
                                "ok": True,
                                "tests": [
                                    {
                                        "expectedStatus": "passed",
                                        "status": "expected",
                                        "results": [{"status": "passed", "retry": 0, "errors": []}],
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ],
    }
    validate_browser_execution(report, scenario)
    # Aggregate PASS cannot substitute a different case or hide retries/skips.
    for mutation in (
        "wrong_file",
        "wrong_title",
        "missing",
        "duplicate",
        "skip",
        "retry",
        "expected_failure",
        "flaky",
        "error",
    ):
        changed = json.loads(json.dumps(report))
        specs = changed["suites"][0]["suites"][0]["specs"]
        test = specs[0]["tests"][0]
        if mutation == "wrong_file":
            specs[0]["file"] = "unrelated.spec.ts"
        elif mutation == "wrong_title":
            specs[0]["title"] = "unrelated smoke test"
        elif mutation == "missing":
            specs.clear()
        elif mutation == "duplicate":
            specs.append(specs[0])
        elif mutation == "skip":
            test["results"][0]["status"] = "skipped"
        elif mutation == "retry":
            test["results"][0]["retry"] = 1
        elif mutation == "expected_failure":
            test["expectedStatus"] = "failed"
        elif mutation == "flaky":
            changed["stats"]["flaky"] = 1
        else:
            changed["errors"] = [{"message": "fixture failed"}]
        with pytest.raises(ValueError, match="required browser"):
            validate_browser_execution(changed, scenario)


def test_long_script_does_not_change_installed_contract() -> None:
    assert DEFAULT_MOCK_SCRIPT[-1].source_end_ms == 32_000
    assert LONG_SCRIPT[-1].source_end_ms == 64_000
    assert [s.text for s in LONG_SCRIPT] == [s.text for s in DEFAULT_MOCK_SCRIPT]


def test_pause_bounds_and_symlink_confinement(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="half the lease"):
        PackagingPause(tmp_path, timeout=15, lease_seconds=30)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        PackagingPause(link, timeout=1, lease_seconds=30)


def test_fixture_rejects_non_mock_and_wrong_identity() -> None:
    root, identity = allocated_e2e_root()
    try:
        (root / "media").mkdir()
        settings = Settings(
            _env_file=None,
            ai_provider="mock",
            openai_api_key=SecretStr(""),
            openrouter_api_key=SecretStr(""),
            data_dir=root / "projects",
            allowed_media_roots_raw=str(root / "media"),
        )
        assert validate_fixture(settings, root, identity) == root
        for key in ("openai_api_key", "openrouter_api_key"):
            with pytest.raises(ValueError, match="owned disposable Mock"):
                validate_fixture(
                    settings.model_copy(update={key: SecretStr("synthetic-test-key")}),
                    root,
                    identity,
                )
        with pytest.raises(ValueError, match="owned disposable Mock"):
            validate_fixture(settings.model_copy(update={"ai_provider": "openai"}), root, identity)
        with pytest.raises(ValueError, match="owned disposable Mock"):
            validate_fixture(settings, root, (identity[0], identity[1] + 1))
    finally:
        cleanup_fixture(root, expected_identity=identity)


def test_canonical_independent_worker_commits_two_real_pauses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No HTTP simulation: verify the same test Worker/SQLite/FFmpeg path locally."""
    root, identity = allocated_e2e_root()
    worker = None
    try:
        media = create_fixture(root, expected_identity=identity, scenario="b2")
        for key, value in {
            "LIVECLIP_DATA_DIR": str(root / "projects"),
            "LIVECLIP_ALLOWED_MEDIA_ROOTS": str(root / "media"),
            "LIVECLIP_AI_PROVIDER": "mock",
            "OPENAI_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "PREVIEW_RENDER_WIDTH": "270",
            "PREVIEW_RENDER_HEIGHT": "480",
            "FINAL_RENDER_WIDTH": "360",
            "FINAL_RENDER_HEIGHT": "640",
            "LIVECLIP_VIDEO_ENCODER": "libx264",
            "WORKER_LEASE_SECONDS": "120",
            "WORKER_HEARTBEAT_SECONDS": "5",
        }.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        created = CliRunner().invoke(app, ["auto", str(media), "--no-watch"])
        assert created.exit_code == 0, created.output
        with LiveClipRuntime.open(get_settings()) as runtime:
            actor = runtime.workspace_service.get_user_by_username(
                get_settings().workspace_username
            )
            intent_id = json.loads(
                next(line for line in created.output.splitlines() if line.startswith("{"))
            )["Completion intent ID"]
            with (root / "worker.log").open("wb") as log:
                worker = subprocess.Popen(
                    [
                        sys.executable,
                        "scripts/b2_synthetic_worker.py",
                        "--root",
                        str(root),
                        "--expected-device",
                        str(identity[0]),
                        "--expected-inode",
                        str(identity[1]),
                    ],
                    env=dict(os.environ, PYTHONPATH=str(Path("src").resolve())),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    shell=False,
                )
                pauses = []
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
                    goal = runtime.completion_service.get(intent_id, actor_user_id=actor.user_id)
                    for count in (1, 2):
                        marker = root / "b2-pauses" / f"pause-{count}.json"
                        if marker.exists() and len(pauses) == count - 1:
                            value = json.loads(marker.read_text())
                            goal = runtime.completion_service.get(
                                intent_id, actor_user_id=actor.user_id
                            )
                            assert goal.delivery_progress is not None
                            assert goal.delivery_progress.completed == count
                            assert goal.delivery_progress.total == 4
                            assert goal.delivery_progress.attempt_id == value["attempt_id"]
                            if count == 1:
                                heartbeat = goal.delivery_progress.worker_heartbeat_at
                                time.sleep(6)
                                fresh = runtime.completion_service.get(
                                    intent_id, actor_user_id=actor.user_id
                                )
                                assert fresh.delivery_progress.completed == 1
                                assert (
                                    fresh.delivery_progress.business_advanced_at
                                    == goal.delivery_progress.business_advanced_at
                                )
                                assert fresh.delivery_progress.worker_heartbeat_at > heartbeat
                                assert fresh.delivery_progress.lease_fresh
                            pauses.append(value)
                            (root / "b2-pauses" / f"release-{count}.json").write_text(
                                json.dumps(
                                    {
                                        "attempt_id": value["attempt_id"],
                                        "completed": count,
                                    }
                                )
                            )
                    if goal.status.value in {"succeeded", "needs_action", "failed", "cancelled"}:
                        break
                    assert worker.poll() is None, (root / "worker.log").read_text()[-2000:]
                    time.sleep(0.1)
                assert goal.status.value == "succeeded", (goal.status, goal.safe_error_message)
                assert len(pauses) == 2
                assert pauses[0]["attempt_id"] == pauses[1]["attempt_id"]
    finally:
        if worker is not None:
            worker.terminate()
            worker.wait(timeout=15)
        get_settings.cache_clear()
        cleanup_fixture(root, expected_identity=identity)


@pytest.mark.parametrize("release_kind", ["absent", "mismatch", "fifo"])
def test_timeout_keeps_receipt_and_removes_release_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    release_kind: str,
) -> None:
    from contextlib import nullcontext
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from liveclip.application.delivery_progress import (
        DeliveryProgressEvent,
        DeliveryProgressPhase,
        DeliveryProgressUnit,
    )
    from scripts import b2_synthetic_worker as fixture

    row = {
        "phase": "writing_metadata",
        "unit": "files",
        "completed": 1,
        "total": 4,
        "business_advanced_at": datetime.now(UTC),
    }
    connection = SimpleNamespace(
        execute=lambda _: SimpleNamespace(
            mappings=lambda: SimpleNamespace(one=lambda: row),
        )
    )
    monkeypatch.setattr(
        fixture,
        "current_delivery_progress_authority",
        lambda *a, **kw: (
            {},
            {"id": "task", "lease_token": "owned"},
            {"id": "attempt"},
        ),
    )
    sink = SimpleNamespace(
        _engine=SimpleNamespace(connect=lambda: nullcontext(connection)),
        _lease=SimpleNamespace(task_id="task", lease_token="owned"),
        _work=SimpleNamespace(
            delivery_id="delivery", project_id="project", run_id="run", generation=1
        ),
    )
    pause = PackagingPause(tmp_path, timeout=0.01, lease_seconds=30)
    if release_kind == "mismatch":
        (tmp_path / "release-1.json").write_text('{"attempt_id": "wrong", "completed": 1}')
    elif release_kind == "fifo":
        os.mkfifo(tmp_path / "release-1.json")
    expected = TimeoutError if release_kind == "absent" else ValueError
    try:
        with pytest.raises(expected):
            pause.after_commit(
                sink,
                DeliveryProgressEvent(
                    phase=DeliveryProgressPhase.WRITING_METADATA,
                    unit=DeliveryProgressUnit.FILES,
                    completed=1,
                    total=4,
                ),
            )
        assert (tmp_path / "pause-1.json").exists()
        assert not (tmp_path / "release-1.json").exists()
        assert not (tmp_path / "released-1.json").exists()
    finally:
        pause.close()


@pytest.mark.parametrize(
    "mutation", ["count", "attempt", "timeout", "config", "reload", "navigation", "create"]
)
def test_packaging_receipt_rejects_uncorrelated_observations(mutation: str) -> None:
    from scripts.verify_completion_retained import validate_packaging

    identity = {"project_id": "p", "run_id": "r", "generation": 1, "delivery_id": "d"}
    evidence = {**identity, "intent_id": "i"}
    durable = {
        "run": {"generation": 1},
        "tasks": [{"id": "t", "kind": "delivery"}],
        "attempts": [{"id": "a", "task_id": "t"}],
    }
    pauses = [
        {
            **identity,
            "task_id": "t",
            "attempt_id": "a",
            "phase": "writing_metadata",
            "unit": "files",
            "completed": n,
            "total": 4,
            "observed_unix_ms": n * 1000,
        }
        for n in (1, 2)
    ]
    observations = [
        {
            **p,
            "intent_id": "i",
            "reloaded": p["completed"] == 1,
            "navigated": p["completed"] == 2,
            "observed_unix_ms": p["observed_unix_ms"] + 100,
            "progress": {**p, "lease_fresh": True},
        }
        for p in pauses
    ]
    releases = [{**p, "released_unix_ms": p["observed_unix_ms"] + 200} for p in pauses]
    bundle = {
        "schema_version": "liveclip.b2-packaging.v1",
        "source_sha256": "a" * 64,
        "config": {
            "provider": "mock",
            "clip_profile": "short_highlight",
            "clipping_algorithm": "semantic_windowed",
            "minimum_clip_ms": 45000,
            "semantic_target_clip_ms": 60000,
            "maximum_clip_ms": 90000,
            "top_n": 15,
            "semantic_score_threshold": 75.0,
            "semantic_full_context_budget_ratio": 0.58,
            "semantic_model_context_tokens": 128000,
        },
        "pauses": pauses,
        "releases": releases,
        "browser": {
            "observations": observations,
            "create": {
                **evidence,
                "confirmed_before_reload": True,
                "pending_cleared": True,
                "modal_closed": True,
                "request_key": "liveclip-web-completion-fixture",
                "request_body": {
                    "preset_id": "short_highlight_v1",
                    "selection_policy": "manual",
                },
                "observed_unix_ms": 500,
            },
        },
        "final_progress": {
            "delivery_id": "d",
            "task_attempt_id": "a",
            "phase": "committing_assets",
            "completed": 5,
            "total": 5,
        },
    }
    validate_packaging(bundle, durable, evidence)
    if mutation == "count":
        observations[1]["progress"]["completed"] = 1
    elif mutation == "attempt":
        observations[1]["attempt_id"] = "another-attempt"
    elif mutation == "timeout":
        releases[1]["released_unix_ms"] = 60000
    elif mutation == "config":
        bundle["config"]["minimum_clip_ms"] = 8000
    elif mutation == "reload":
        observations[0]["reloaded"] = False
    elif mutation == "navigation":
        observations[1]["navigated"] = False
    else:
        bundle["browser"]["create"]["pending_cleared"] = False
    with pytest.raises(ValueError, match="B2"):
        validate_packaging(bundle, durable, evidence)
