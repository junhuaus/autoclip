from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "e2e_fixture.py"
_SPEC = importlib.util.spec_from_file_location("liveclip_e2e_fixture", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_LINEAGE_SCRIPT = Path(__file__).parents[2] / "scripts" / "verify_completion_retained.py"
_LINEAGE_SPEC = importlib.util.spec_from_file_location(
    "liveclip_completion_retained", _LINEAGE_SCRIPT
)
assert _LINEAGE_SPEC is not None and _LINEAGE_SPEC.loader is not None
_LINEAGE = importlib.util.module_from_spec(_LINEAGE_SPEC)
_LINEAGE_SPEC.loader.exec_module(_LINEAGE)
allocated_e2e_root = _MODULE.allocated_e2e_root
cleanup_fixture = _MODULE.cleanup_fixture
validated_e2e_root = _MODULE.validated_e2e_root
allocate_report_scope = _MODULE.allocate_report_scope


def _scope(scenario: str = "legacy") -> dict[str, Any]:
    scope, identity = allocate_report_scope(scenario)
    return {"report_scope": scope, "report_scope_identity": identity}


def _lineage_fixture() -> tuple[dict, dict]:
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures/completion-retained-lineage-v1.json").read_text()
    )
    assert fixture["schema_version"] == "liveclip.completion-lineage-regression.v1"
    assert fixture["synthetic_mock_asr_llm"] is True
    assert len(fixture["source_manifest_sha256"]) == 64
    return fixture["durable"], fixture["evidence"]


def test_real_verifier_lineage_snapshot_rejects_wrong_existing_producer() -> None:
    durable, evidence = _lineage_fixture()
    _LINEAGE.validate_lineage(durable, evidence)

    wrong = deepcopy(durable)
    zip_id = wrong["deliveries"][0]["zip_asset_id"]
    zip_asset = next(row for row in wrong["assets"] if row["id"] == zip_id)
    stage_tasks = {row["id"] for row in wrong["tasks"] if row["kind"] == "stage"}
    other_attempt = next(
        row
        for row in wrong["attempts"]
        if row["outcome"] == "succeeded" and row["task_id"] in stage_tasks
    )
    assert zip_asset["producer_attempt_id"] != other_attempt["id"]
    zip_asset["producer_attempt_id"] = other_attempt["id"]
    with pytest.raises(ValueError, match="wrong delivery producer"):
        _LINEAGE.validate_lineage(wrong, evidence)

    wrong_run = deepcopy(durable)
    wrong_run["stages"][0]["pipeline_run_id"] = "f" * 32
    with pytest.raises(ValueError, match="stage run/status"):
        _LINEAGE.validate_lineage(wrong_run, evidence)


def test_retained_lineage_rejects_broken_stage_dependencies() -> None:
    durable, evidence = _lineage_fixture()
    stages = {row["id"]: row["stage"] for row in durable["stages"]}
    by_stage = {
        stages[row["stage_run_id"]]: row for row in durable["tasks"] if row["kind"] == "stage"
    }
    preprocess = by_stage["preprocess"]
    assert preprocess["depends_on_task_id"] == by_stage["ingest"]["id"]
    for invalid in (preprocess["id"], None, by_stage["transcribe"]["id"]):
        wrong = deepcopy(durable)
        target = next(row for row in wrong["tasks"] if row["id"] == preprocess["id"])
        target["depends_on_task_id"] = invalid
        with pytest.raises(ValueError, match="stage Task dependency graph"):
            _LINEAGE.validate_lineage(wrong, evidence)


def test_retained_lineage_rejects_same_run_wrong_stage_and_asset_scope() -> None:
    durable, evidence = _lineage_fixture()
    stages = {row["id"]: row["stage"] for row in durable["stages"]}
    edit_task = next(
        row
        for row in durable["tasks"]
        if row["kind"] == "stage" and stages[row["stage_run_id"]] == "edit"
    )
    edit_attempt = next(
        row
        for row in durable["attempts"]
        if row["task_id"] == edit_task["id"] and row["outcome"] == "succeeded"
    )
    proxy = next(row for row in durable["assets"] if row["kind"] == "review_proxy")
    assert proxy["producer_attempt_id"] != edit_attempt["id"]
    wrong_stage = deepcopy(durable)
    next(row for row in wrong_stage["assets"] if row["id"] == proxy["id"])[
        "producer_attempt_id"
    ] = edit_attempt["id"]
    with pytest.raises(ValueError, match="Asset wrong stage producer"):
        _LINEAGE.validate_lineage(wrong_stage, evidence)

    for field, message in (
        ("generation", "Asset generation binding"),
        ("edit_plan_revision", "render Asset clip/revision binding"),
        ("revision_epoch", "render Asset clip/revision binding"),
    ):
        wrong = deepcopy(durable)
        next(row for row in wrong["assets"] if row["id"] == proxy["id"])[field] = 999
        with pytest.raises(ValueError, match=message):
            _LINEAGE.validate_lineage(wrong, evidence)


def test_retained_inventory_rejects_extra_file_directory_and_symlink(tmp_path: Path) -> None:
    root = tmp_path / "package"
    (root / "assets").mkdir(parents=True)
    (root / "manifest.json").write_text("{}")
    (root / "assets" / "a.bin").write_bytes(b"asset")
    expected = {"assets/a.bin"}
    _LINEAGE._exact_inventory(root, expected)

    extra = root / "extra.txt"
    extra.write_text("hidden")
    with pytest.raises(ValueError, match="unlisted retained file"):
        _LINEAGE._exact_inventory(root, expected)
    extra.unlink()

    directory = root / "extra"
    directory.mkdir()
    with pytest.raises(ValueError, match="extra directory/symlink"):
        _LINEAGE._exact_inventory(root, expected)
    directory.rmdir()

    link = root / "extra-link"
    link.symlink_to(root / "manifest.json")
    with pytest.raises(ValueError, match="extra directory/symlink"):
        _LINEAGE._exact_inventory(root, expected)


def test_retained_text_scan_rejects_credentials_and_signed_urls() -> None:
    _LINEAGE._safe_text(b'{"lease_token_sha256":"' + b"a" * 64 + b'"}')
    raw_lease = b"b" * 64
    with pytest.raises(ValueError, match="secret/URL"):
        _LINEAGE._safe_text(raw_lease, lease_token_hashes={hashlib.sha256(raw_lease).hexdigest()})
    for raw in (
        b"Authorization: Bearer hidden",
        b"/api/v1/assets/a?signature=hidden",
        b'{"lease_token":"hidden"}',
        b"liveclip-real-browser-test-token",
        b"liveclip real browser password 2026",
        b"https://example.invalid/?X-Amz-Signature=synthetic",
    ):
        with pytest.raises(ValueError, match="secret/URL"):
            _LINEAGE._safe_text(raw)


def _archive(path: Path) -> bytes:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"project_id": "b" * 32}))
        archive.writestr("clips/review.srt", "1\n00:00:00,000 --> 00:00:01,000\n字幕\n")
    return path.read_bytes()


def test_verified_browser_zips_survive_fixture_cleanup_with_exact_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    root, identity = allocated_e2e_root()
    try:
        original = _archive(root / "delivery.zip")
        raw, inner = _MODULE._verified_archive_bytes(root / "delivery.zip")
        assert raw == original and inner == {"project_id": "b" * 32}
        evidence = {"run_id": "a" * 32, "project_id": "b" * 32, "delivery_id": "c" * 32}
        relative = _MODULE._retain_browser_packages(evidence, raw, raw, **_scope())
        assert cleanup_fixture(root, expected_identity=identity)
        manifest_path = tmp_path / relative
        manifest = json.loads(manifest_path.read_text())
        assert manifest["evidence"] == evidence
        assert manifest["synthetic_mock_asr_llm"] is True
        assert {entry["path"] for entry in manifest["files"]} == {"delivery.zip", "release.zip"}
        for entry in manifest["files"]:
            saved = (manifest_path.parent / entry["path"]).read_bytes()
            assert saved == original
            assert len(saved) == entry["size_bytes"]
            assert hashlib.sha256(saved).hexdigest() == entry["sha256"]
    finally:
        if root.exists():
            cleanup_fixture(root, expected_identity=identity)


def test_browser_retention_refuses_existing_run_and_preserves_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    raw = _archive(tmp_path / "input.zip")
    evidence = {"run_id": "a" * 32}
    scope = _scope()
    relative = _MODULE._retain_browser_packages(evidence, raw, raw, **scope)
    before = (tmp_path / relative).read_bytes()
    with pytest.raises(ValueError, match="already holds a retained run"):
        _MODULE._retain_browser_packages(evidence, b"different", b"different", **scope)
    assert (tmp_path / relative).read_bytes() == before
    assert (tmp_path / relative).parent.joinpath("delivery.zip").read_bytes() == raw
    # A later invocation retains the same synthetic run ID into its own scope.
    later = _MODULE._retain_browser_packages(evidence, raw, raw, **_scope())
    assert Path(later).parent.name == "a" * 32 and later != relative
    assert (tmp_path / relative).read_bytes() == before


def test_completion_browser_retains_every_asset_and_durable_evidence_create_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    raw = _archive(tmp_path / "input.zip")
    project_id = "d" * 32
    asset_id = "e" * 32
    project_root = tmp_path / "project"
    source = project_root / "artifacts/review.srt"
    source.parent.mkdir(parents=True)
    source_bytes = b"1\n00:00:00,000 --> 00:00:01,000\nSynthetic\n"
    source.write_bytes(source_bytes)
    asset = {
        "id": asset_id,
        "project_id": project_id,
        "relative_path": "artifacts/review.srt",
        "size_bytes": len(source_bytes),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    logs = tmp_path / "logs"
    logs.mkdir()
    markers = {}
    for name in ("observer-closed.json", "waiting.json", "download.json"):
        path = logs / name
        document = {"schema_version": name, "project_id": project_id}
        path.write_text(json.dumps(document))
        markers[name] = (path, document)
    durable = {"schema_version": "liveclip.completion-durable-audit.v1", "assets": [asset]}
    evidence = {
        "run_id": "b" * 32,
        "intent_id": "c" * 32,
        "project_id": project_id,
        "asset_count": 1,
    }
    scope = _scope("completion")
    relative = _MODULE._retain_completion_package(
        evidence,
        raw,
        project_root=project_root,
        assets=[asset],
        durable=durable,
        markers=markers,
        **scope,
    )
    assert Path(relative).parts[:5] == (
        "apps",
        "web",
        "playwright-report",
        "completion-packages",
        scope["report_scope"].name,
    )
    manifest_path = tmp_path / relative
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema_version"] == "liveclip.completion-browser-evidence.v2"
    assert manifest["evidence"] == evidence
    assert manifest["asset_count"] == 1
    assert {entry["path"] for entry in manifest["files"]} == {
        "delivery.zip",
        "durable.json",
        "observer-closed.json",
        "waiting.json",
        "download.json",
        f"assets/{asset_id}.bin",
    }
    for entry in manifest["files"]:
        retained = (manifest_path.parent / entry["path"]).read_bytes()
        assert len(retained) == entry["size_bytes"]
        assert hashlib.sha256(retained).hexdigest() == entry["sha256"]
    assert json.loads((manifest_path.parent / "durable.json").read_text()) == durable
    assert (manifest_path.parent / f"assets/{asset_id}.bin").read_bytes() == source_bytes
    assert (manifest_path.parent / "delivery.zip").read_bytes() == raw
    with pytest.raises(ValueError, match="already holds a retained run"):
        _MODULE._retain_completion_package(
            evidence,
            b"different",
            project_root=project_root,
            assets=[asset],
            durable=durable,
            markers=markers,
            **scope,
        )
    assert (manifest_path.parent / "delivery.zip").read_bytes() == raw


def test_completion_retention_refuses_bad_asset_without_complete_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    project_id = "d" * 32
    asset_id = "e" * 32
    project_root = tmp_path / "project"
    source = project_root / "artifacts/review.srt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"actual")
    asset = {
        "id": asset_id,
        "project_id": project_id,
        "relative_path": "artifacts/review.srt",
        "size_bytes": 6,
        "sha256": hashlib.sha256(b"altered").hexdigest(),
    }
    markers = {}
    for name in ("observer-closed.json", "waiting.json", "download.json"):
        path = tmp_path / name
        document = {"project_id": project_id}
        path.write_text(json.dumps(document))
        markers[name] = (path, document)
    evidence = {"run_id": "b" * 32, "project_id": project_id, "asset_count": 1}
    scope = _scope("completion")
    with pytest.raises(ValueError, match="retained Asset hash differs"):
        _MODULE._retain_completion_package(
            evidence,
            _archive(tmp_path / "delivery.zip"),
            project_root=project_root,
            assets=[asset],
            durable={"assets": [asset]},
            markers=markers,
            **scope,
        )
    retained = scope["report_scope"] / ("b" * 32)
    assert retained.is_dir()
    assert not (retained / "manifest.json").exists()


def test_completion_wait_marker_requires_persisted_deferred_lease() -> None:
    root, identity = allocated_e2e_root()
    try:
        (root / "logs").mkdir()
        projects = root / "projects"
        projects.mkdir()
        database_path = projects / "liveclip.sqlite3"
        with sqlite3.connect(database_path) as connection:
            connection.executescript(
                "CREATE TABLE completion_intents (id TEXT, project_id TEXT, "
                "pipeline_run_id TEXT, generation INTEGER, status TEXT, "
                "selection_submitted INTEGER, delivery_id TEXT);"
                "CREATE TABLE pipeline_runs (id TEXT, project_id TEXT, generation INTEGER, "
                "status TEXT, progress INTEGER);"
                "CREATE TABLE stage_runs (pipeline_run_id TEXT, status TEXT);"
                "CREATE TABLE tasks (id TEXT, kind TEXT, target_id TEXT, status TEXT);"
                "CREATE TABLE task_attempts (task_id TEXT, outcome TEXT);"
            )
            connection.execute(
                "INSERT INTO completion_intents VALUES (?, ?, ?, 1, 'queued', 0, NULL)",
                ("a" * 32, "b" * 32, "c" * 32),
            )
            connection.execute(
                "INSERT INTO pipeline_runs VALUES (?, ?, 1, 'running', 80)",
                ("c" * 32, "b" * 32),
            )
            connection.executemany(
                "INSERT INTO stage_runs VALUES (?, 'succeeded')",
                [("c" * 32,)] * 6,
            )
            connection.execute(
                "INSERT INTO tasks VALUES (?, 'completion', ?, 'waiting')",
                ("d" * 32, "a" * 32),
            )
        assert _MODULE._completion_waiting_snapshot(database_path) is None
        closed_ms = int(time.time() * 1_000)
        (root / "logs/completion-observer-closed.json").write_text(
            json.dumps(
                {
                    "schema_version": "liveclip.completion-observer-closed.v1",
                    "project_id": "b" * 32,
                    "run_id": "c" * 32,
                    "intent_id": "a" * 32,
                    "generation": 1,
                    "closed_unix_ms": closed_ms,
                }
            )
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(
                _MODULE.watch_completion_waiting, root, expected_identity=identity
            )
            time.sleep(0.4)
            with sqlite3.connect(database_path) as connection:
                connection.execute("UPDATE completion_intents SET status = 'waiting_selection'")
                connection.execute("UPDATE pipeline_runs SET status = 'completed', progress = 100")
                connection.execute("INSERT INTO task_attempts VALUES (?, 'deferred')", ("d" * 32,))
            marker = waiting.result(timeout=3)
        assert marker["intent_id"] == "a" * 32
        assert marker["completion_task_id"] == "d" * 32
        assert marker["deferred_attempt_count"] == 1
        assert marker["observer_closed_unix_ms"] == closed_ms
        assert json.loads((root / "logs/completion-waiting.json").read_text()) == marker
    finally:
        if root.exists():
            cleanup_fixture(root, expected_identity=identity)


def test_browser_retention_refuses_symlink_report_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    web = tmp_path / "apps/web"
    web.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (web / "playwright-report").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        allocate_report_scope("legacy")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("scenario", ["legacy", "completion"])
def test_retention_refuses_report_parent_symlinked_after_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    scope = _scope(scenario)
    report = tmp_path / "apps/web/playwright-report"
    moved = tmp_path / "moved-playwright-report"
    report.rename(moved)
    report.symlink_to(moved, target_is_directory=True)
    # The scope path and identity still resolve, but only through the link.
    assert scope["report_scope"].is_dir()
    evidence = {"run_id": "a" * 32, "project_id": "d" * 32, "asset_count": 1}
    with pytest.raises(OSError):
        if scenario == "legacy":
            _MODULE._retain_browser_packages(evidence, b"one", b"two", **scope)
        else:
            markers = {
                name: (tmp_path / name, {})
                for name in ("observer-closed.json", "waiting.json", "download.json")
            }
            _MODULE._retain_completion_package(
                evidence,
                b"zip",
                project_root=tmp_path / "project",
                assets=[{"id": "e" * 32}],
                durable={"assets": []},
                markers=markers,
                **scope,
            )
    folder = moved / scope["report_scope"].parent.name
    assert list((folder / scope["report_scope"].name).iterdir()) == []


def test_report_scope_identity_is_read_from_held_handle_not_trusted_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What this proves: allocation takes the scope identity by fstat on the
    # O_NOFOLLOW handle it holds, so a by-name swap *after* that open is not
    # trusted and retention into the replacement is refused. What it does not
    # prove: the window between mkdir and open is not closed (POSIX has no
    # mkdirat returning a handle); that residual race is an accepted risk.
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    folder = tmp_path / "apps/web/playwright-report/browser-packages"
    real_open = os.open
    swapped: list[Path] = []

    def swapping_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        descriptor = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if isinstance(path, str) and re.fullmatch(r"[a-f0-9]{32}", path) and not swapped:
            # Replace the new scope by name after the handle was opened.
            (folder / path).rename(folder / f".{path}.original")
            (folder / path).mkdir()
            swapped.append(folder / path)
        return descriptor

    monkeypatch.setattr(_MODULE.os, "open", swapping_open)
    scope, identity = allocate_report_scope("legacy")
    monkeypatch.setattr(_MODULE.os, "open", real_open)
    assert swapped == [scope]
    original = os.stat(folder / f".{scope.name}.original", follow_symlinks=False)
    replacement = os.stat(scope, follow_symlinks=False)
    assert (
        identity
        == (original.st_dev, original.st_ino)
        != (
            replacement.st_dev,
            replacement.st_ino,
        )
    )
    with pytest.raises(ValueError, match="allocated by this run"):
        _MODULE._retain_browser_packages(
            {"run_id": "a" * 32},
            b"one",
            b"two",
            report_scope=scope,
            report_scope_identity=identity,
        )
    assert list(scope.iterdir()) == []


def test_incomplete_browser_retention_never_publishes_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    scope = _scope()
    real_open = os.open

    def failing_open(path: object, *args: object, **kwargs: object) -> int:
        if path == "release.zip":
            raise OSError("injected retention disk failure")
        return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_MODULE.os, "open", failing_open)
    with pytest.raises(OSError, match="injected retention"):
        _MODULE._retain_browser_packages({"run_id": "a" * 32}, b"one", b"two", **scope)
    retained = scope["report_scope"] / ("a" * 32)
    assert (retained / "delivery.zip").read_bytes() == b"one"
    assert not (retained / "manifest.json").exists()


@pytest.mark.parametrize("run_id", ["../outside", "/absolute", "a" * 31, 12])
def test_browser_retention_rejects_non_run_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_id: object
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    scope = _scope()
    with pytest.raises(ValueError, match="run ID"):
        _MODULE._retain_browser_packages({"run_id": run_id}, b"one", b"two", **scope)
    assert list(scope["report_scope"].iterdir()) == []


def test_report_scopes_are_fresh_and_preserve_prior_invocation_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    folder = tmp_path / "apps/web/playwright-report/browser-packages"
    # Both the pre-scope flat layout and an earlier scoped run must survive.
    flat = folder / ("a" * 32)
    flat.mkdir(parents=True)
    (flat / "manifest.json").write_bytes(b"earlier flat run")
    earlier = _MODULE._retain_browser_packages({"run_id": "a" * 32}, b"old", b"old", **_scope())
    earlier_bytes = (tmp_path / earlier).read_bytes()
    first, second = _scope(), _scope()
    names = {first["report_scope"].name, second["report_scope"].name}
    assert len(names) == 2 and all(re.fullmatch(r"[a-f0-9]{32}", name) for name in names)
    for scope in (first, second):
        assert scope["report_scope"].parent == folder
        assert list(scope["report_scope"].iterdir()) == []
    current = _MODULE._retain_browser_packages({"run_id": "a" * 32}, b"new", b"new", **first)
    assert Path(current).parent.parent == first["report_scope"].relative_to(tmp_path)
    assert (flat / "manifest.json").read_bytes() == b"earlier flat run"
    assert (tmp_path / earlier).read_bytes() == earlier_bytes
    assert (tmp_path / earlier).parent.joinpath("delivery.zip").read_bytes() == b"old"
    assert list(second["report_scope"].iterdir()) == []


def test_report_scope_rejects_foreign_traversal_symlink_and_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_MODULE, "_REPOSITORY_ROOT", tmp_path)
    scope = _scope()
    path, identity = scope["report_scope"], scope["report_scope_identity"]
    evidence = {"run_id": "a" * 32}
    (path.parent / "latest").mkdir()
    for foreign in (
        path.relative_to(tmp_path),
        path.parent / ".." / "browser-packages" / path.name,
        path.parent / "latest",
        tmp_path / "apps/web/playwright-report/completion-packages" / path.name,
    ):
        with pytest.raises(ValueError, match="generated invocation directory"):
            _MODULE._retain_browser_packages(
                evidence, b"one", b"two", report_scope=foreign, report_scope_identity=identity
            )
    # A legacy scope can never receive completion or B2 evidence.
    for scenario in ("completion", "b2"):
        with pytest.raises(ValueError, match="generated invocation directory"):
            _MODULE._open_report_scope(path, scenario=scenario, expected_identity=identity)
    link = path.parent / ("f" * 32)
    link.symlink_to(path, target_is_directory=True)
    with pytest.raises(OSError):
        _MODULE._retain_browser_packages(
            evidence, b"one", b"two", report_scope=link, report_scope_identity=identity
        )
    aside = path.with_name(f".{path.name}.aside")
    path.rename(aside)
    path.mkdir()
    with pytest.raises(ValueError, match="allocated by this run"):
        _MODULE._retain_browser_packages(evidence, b"one", b"two", **scope)
    assert list(path.iterdir()) == [] and list(aside.iterdir()) == []
    path.rmdir()
    aside.rename(path)
    folder = path.parent
    real_folder = folder.with_name("real-browser-packages")
    folder.rename(real_folder)
    folder.symlink_to(real_folder, target_is_directory=True)
    with pytest.raises(OSError):
        _MODULE._retain_browser_packages(evidence, b"one", b"two", **scope)
    assert list((real_folder / path.name).iterdir()) == []
    folder.unlink()
    real_folder.rename(folder)
    assert _MODULE._retain_browser_packages(evidence, b"one", b"two", **scope)


def test_package_retention_requires_this_invocation_scope(tmp_path: Path) -> None:
    for verify, extra in (
        (_MODULE.verify_completed_run, {}),
        (_MODULE.verify_completion_run, {"scenario": "completion"}),
        (_MODULE.verify_completion_run, {"scenario": "b2"}),
    ):
        for partial in ({}, {"report_scope": tmp_path}, {"report_scope_identity": (1, 2)}):
            with pytest.raises(ValueError, match="require this invocation's report scope"):
                verify(tmp_path, expected_identity=(1, 2), retain_packages=True, **extra, **partial)


def test_real_browser_harness_binds_one_fresh_scope_to_retention_and_verifier() -> None:
    script = (Path(__file__).parents[2] / "scripts/run_real_browser_e2e.sh").read_text()
    allocation = script.index('allocate-report-scope --scenario "${E2E_SCENARIO}"')
    retention = script.index("--retain-packages")
    retained_check = script.index("--prove-rejection")
    assert script.count("allocate-report-scope") == 1
    assert allocation < retention < retained_check
    assert script.count('--report-scope "${E2E_REPORT_SCOPE}"') == 2
    assert script.count('--report-scope-device "${E2E_REPORT_SCOPE_DEVICE}"') == 1
    assert script.count('--report-scope-inode "${E2E_REPORT_SCOPE_INODE}"') == 1
    assert script.count('--expected-scope-device "${E2E_REPORT_SCOPE_DEVICE}"') == 1
    assert script.count('--expected-scope-inode "${E2E_REPORT_SCOPE_INODE}"') == 1


def test_browser_archive_read_rejects_corruption_symlink_and_oversize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "input.zip"
    archive.write_bytes(b"not a ZIP")
    with pytest.raises(zipfile.BadZipFile):
        _MODULE._verified_archive_bytes(archive)
    _archive(archive)
    link = tmp_path / "link.zip"
    link.symlink_to(archive)
    with pytest.raises((OSError, ValueError)):
        _MODULE._verified_archive_bytes(link)
    monkeypatch.setattr(_MODULE, "_MAX_RETAINED_ZIP_BYTES", 10)
    with pytest.raises(ValueError, match="size limit"):
        _MODULE._verified_archive_bytes(archive)


def test_e2e_root_validation_and_cleanup_use_allocation_identity() -> None:
    root, identity = allocated_e2e_root()
    try:
        assert validated_e2e_root(str(root), expected_identity=identity) == root
        with pytest.raises(ValueError, match="allocated by this run"):
            validated_e2e_root(
                str(root),
                expected_identity=(identity[0], identity[1] + 1),
            )
        assert cleanup_fixture(root, expected_identity=identity)
        assert not root.exists()
    finally:
        if root.exists():
            current = os.stat(root, follow_symlinks=False)
            cleanup_fixture(
                root,
                expected_identity=(current.st_dev, current.st_ino),
            )


def test_e2e_cleanup_refuses_replaced_root() -> None:
    root, identity = allocated_e2e_root()
    detached = root.with_name(f".{root.name}.detached")
    replacement_created = False
    try:
        root.rename(detached)
        root.mkdir(mode=0o700)
        replacement_created = True

        with pytest.raises(ValueError, match="allocated by this run"):
            cleanup_fixture(root, expected_identity=identity)

        assert root.is_dir()
        assert detached.is_dir()
        root.rmdir()
        replacement_created = False
        detached.rename(root)
        assert cleanup_fixture(root, expected_identity=identity)
    finally:
        if replacement_created and root.is_dir():
            root.rmdir()
        if detached.is_dir():
            detached.rename(root)
        if root.is_dir():
            cleanup_fixture(root, expected_identity=identity)
