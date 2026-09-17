"""Inspect the completed synthetic browser bundle after its SQLite fixture is gone."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

from liveclip.pipeline.srt import load_srt_transcript
from liveclip.services.completion_evidence_safety import (
    TEXT_ASSET_KINDS,
    reject_sensitive_text,
    scan_zip_text,
)

HEX32 = re.compile(r"[0-9a-f]{32}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
STAGE_FOR_KIND = {
    "source_metadata": "ingest",
    "audio_manifest": "preprocess",
    "audio_chunk": "preprocess",
    "transcript_json": "transcribe",
    "transcript_srt": "transcribe",
    "rough_candidates": "candidates",
    "edit_plans": "edit",
    "review_proxy": "proxy_render",
    "clip_subtitle_srt": "proxy_render",
    "render_quality_report": "proxy_render",
    "render_contact_sheet": "proxy_render",
}
RENDER_KINDS = {
    "review_proxy",
    "clip_subtitle_srt",
    "render_quality_report",
    "render_contact_sheet",
}


def _require(condition: object, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            value.update(chunk)
    return value.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    _require(isinstance(value, dict), "retained JSON is not an object")
    return cast(dict[str, Any], value)


def _safe_text(raw: bytes, *, lease_token_hashes: set[str] | frozenset[str] = frozenset()) -> None:
    """Reject credentials and signed URLs in retained text bodies."""
    reject_sensitive_text(raw, lease_token_hashes=lease_token_hashes)


def _exact_inventory(root: Path, declared_files: set[str]) -> None:
    """Enumerate the package without following links; only assets/ may be a directory."""
    _require(stat.S_ISDIR(root.lstat().st_mode), "retained root not a real directory")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for entry in root.iterdir():
        mode = entry.lstat().st_mode
        if stat.S_ISREG(mode):
            actual_files.add(entry.name)
        elif stat.S_ISDIR(mode) and entry.name == "assets":
            actual_directories.add("assets")
            for child in entry.iterdir():
                _require(stat.S_ISREG(child.lstat().st_mode), "extra directory/symlink in assets")
                actual_files.add(f"assets/{child.name}")
        else:
            raise ValueError("extra directory/symlink in retained package")
    _require(actual_directories == {"assets"}, "retained assets directory missing")
    _require(actual_files == declared_files | {"manifest.json"}, "unlisted retained file")


def validate_lineage(
    durable: dict[str, Any], evidence: dict[str, Any], *, scenario: str = "completion"
) -> None:
    """Reconstruct every Asset producer from retained IDs, including stage scope."""
    _require(scenario in {"completion", "b2"}, "unknown lineage scenario")
    _require(
        set(durable)
        == {
            "schema_version",
            "synthetic_mock_asr_llm",
            "project",
            "run",
            "intent",
            "stages",
            "tasks",
            "attempts",
            "deliveries",
            "delivery_clips",
            "assets",
            "sqlite_quick_check",
            "sqlite_foreign_key_violations",
        }
        and durable["synthetic_mock_asr_llm"] is True,
        "durable fields/synthetic flag",
    )
    _require(durable["schema_version"] == "liveclip.completion-durable-audit.v1", "durable schema")
    _require(
        durable["sqlite_quick_check"] == "ok" and durable["sqlite_foreign_key_violations"] == 0,
        "SQLite integrity",
    )
    project, run, intent = (durable[key] for key in ("project", "run", "intent"))
    _require(
        project["id"] == run["project_id"] == intent["project_id"] == evidence["project_id"],
        "project identity",
    )
    _require(run["id"] == intent["pipeline_run_id"] == evidence["run_id"], "run identity")
    _require(
        intent["id"] == evidence["intent_id"] and intent["delivery_id"] == evidence["delivery_id"],
        "intent identity",
    )
    _require(
        run["generation"]
        == intent["generation"]
        == project["current_generation"]
        == evidence["generation"]
        == 1,
        "generation",
    )
    _require(
        run["status"] == "completed"
        and run["progress"] == 100
        and intent["status"] == "succeeded"
        and intent["outcome_code"] == "delivered",
        "terminal outcome",
    )
    _require(
        intent["selection_policy"] == "manual" and intent["selection_submitted"] == 1,
        "manual selection",
    )
    selected = intent["selection_checkpoint"]["selected"]
    checkpoint = intent["selection_checkpoint"]
    _require(
        set(checkpoint)
        == {"schema_version", "intent_id", "run_id", "generation", "mode", "action_key", "selected"}
        and checkpoint["schema_version"] == "1"
        and checkpoint["intent_id"] == intent["id"]
        and checkpoint["run_id"] == run["id"]
        and checkpoint["generation"] == run["generation"]
        and checkpoint["mode"] == "manual",
        "selection checkpoint identity",
    )
    _require(
        len(selected) == 1
        and selected[0]["clip_id"] == durable["delivery_clips"][0]["candidate_clip_id"],
        "selected clip",
    )
    stages = durable["stages"]
    stage_by_id = {row["id"]: row for row in stages}
    _require(
        len(stages) == len(stage_by_id) == 6
        and {row["ordinal"] for row in stages} == set(range(6)),
        "stage identity/ordinal",
    )
    _require(
        all(row["pipeline_run_id"] == run["id"] and row["status"] == "succeeded" for row in stages),
        "stage run/status",
    )
    stage_order = ("ingest", "preprocess", "transcribe", "candidates", "edit", "proxy_render")
    ordered_stages = sorted(stages, key=lambda row: row["ordinal"])
    _require(
        tuple(row["stage"] for row in ordered_stages) == stage_order,
        "stage order",
    )
    tasks = durable["tasks"]
    task_by_id = {row["id"]: row for row in tasks}
    _require(
        len(tasks) == len(task_by_id) == 8
        and all(
            row["pipeline_run_id"] == run["id"]
            and row["status"] == "succeeded"
            and row["retry_count"] == 0
            for row in tasks
        ),
        "Task run/status",
    )
    _require(
        all(
            row["target_id"] == row["stage_run_id"] and row["stage_run_id"] in stage_by_id
            for row in tasks
            if row["kind"] == "stage"
        ),
        "stage Task target",
    )
    _require(
        all(row["stage_run_id"] is None for row in tasks if row["kind"] != "stage"),
        "nonstage Task shape",
    )
    _require([row["kind"] for row in tasks].count("stage") == 6, "stage Task count")
    stage_tasks = [row for row in tasks if row["kind"] == "stage"]
    task_by_stage_id = {row["stage_run_id"]: row for row in stage_tasks}
    _require(
        len(task_by_stage_id) == 6 and set(task_by_stage_id) == set(stage_by_id),
        "one-to-one Stage/Task binding",
    )
    for index, stage in enumerate(ordered_stages):
        expected_dependency = (
            None if index == 0 else task_by_stage_id[ordered_stages[index - 1]["id"]]["id"]
        )
        _require(
            task_by_stage_id[stage["id"]]["depends_on_task_id"] == expected_dependency,
            "stage Task dependency graph",
        )
    completion = [row for row in tasks if row["kind"] == "completion"]
    delivery_tasks = [row for row in tasks if row["kind"] == "delivery"]
    _require(
        len(completion) == len(delivery_tasks) == 1
        and completion[0]["target_id"] == intent["id"]
        and delivery_tasks[0]["target_id"] == intent["delivery_id"]
        and completion[0]["depends_on_task_id"] is None
        and delivery_tasks[0]["depends_on_task_id"] is None,
        "completion/delivery Task target",
    )
    attempts = durable["attempts"]
    attempt_by_id = {row["id"]: row for row in attempts}
    _require(
        len(attempts) == len(attempt_by_id) == evidence["attempt_count"], "attempt identity/count"
    )
    _require(
        all(
            row["task_id"] in task_by_id
            and "lease_token" not in row
            and HEX64.fullmatch(row["lease_token_sha256"])
            for row in attempts
        ),
        "attempt Task/secret",
    )
    deferred = [row for row in attempts if row["outcome"] == "deferred"]
    _require(
        len(deferred) == evidence["deferred_attempt_count"] >= 1
        and all(row["task_id"] == completion[0]["id"] for row in deferred),
        "deferred lease",
    )
    _require(
        completion[0]["attempt_count"] == len(deferred) + 1
        and sum(row["outcome"] == "succeeded" for row in attempts) == 8,
        "attempt outcomes",
    )
    _require(
        all(
            task["attempt_count"] == sum(row["task_id"] == task["id"] for row in attempts)
            for task in tasks
        ),
        "Task attempt count",
    )
    deliveries = durable["deliveries"]
    clips = durable["delivery_clips"]
    _require(len(deliveries) == len(clips) == 1, "single Delivery/clip")
    delivery = deliveries[0]
    _require(
        delivery["id"] == intent["delivery_id"]
        and delivery["project_id"] == project["id"]
        and delivery["version"] == 1
        and delivery["status"] == "succeeded",
        "Delivery identity/status",
    )
    _require(
        clips[0]["delivery_id"] == delivery["id"]
        and clips[0]["edit_plan_revision"] == selected[0]["edit_plan_revision"],
        "Delivery selection binding",
    )
    assets = durable["assets"]
    _require(
        len(assets) == evidence["asset_count"]
        and (len(assets) == 16 if scenario == "completion" else bool(assets))
        and len({row["id"] for row in assets}) == len(assets),
        "Asset inventory",
    )
    _require(
        all(type(row["size_bytes"]) is int and row["size_bytes"] > 0 for row in assets)
        and sum(row["size_bytes"] for row in assets) <= 256_000_000,
        "Asset byte bound",
    )
    for asset in assets:
        _require(
            asset["project_id"] == project["id"] and asset["status"] == "committed",
            "Asset project/status",
        )
        producer = attempt_by_id.get(asset["producer_attempt_id"])
        _require(
            producer is not None and producer["outcome"] == "succeeded", "Asset producer attempt"
        )
        assert producer is not None
        task = task_by_id[producer["task_id"]]
        kind = asset["kind"]
        if kind in {"delivery_manifest", "delivery_zip"}:
            _require(
                task["kind"] == "delivery" and task["id"] == delivery_tasks[0]["id"],
                "Asset wrong delivery producer",
            )
        else:
            stage = stage_by_id.get(task["stage_run_id"])
            _require(
                task["kind"] == "stage"
                and stage is not None
                and (
                    stage["stage"] == STAGE_FOR_KIND.get(kind)
                    or (
                        scenario == "b2"
                        and kind == "semantic_unit_outcome"
                        and stage["stage"] in {"candidates", "edit"}
                    )
                ),
                "Asset wrong stage producer",
            )
        if kind in RENDER_KINDS:
            _require(
                asset["candidate_clip_id"] == selected[0]["clip_id"]
                and asset["edit_plan_revision"] == selected[0]["edit_plan_revision"]
                and asset["revision_epoch"] == project["revision_epoch"],
                "render Asset clip/revision binding",
            )
        else:
            _require(
                asset["candidate_clip_id"] is None
                and asset["edit_plan_revision"] is None
                and (
                    asset["revision_epoch"] == project["revision_epoch"]
                    if kind in {"delivery_manifest", "delivery_zip"}
                    else asset["revision_epoch"] is None
                ),
                "nonrender Asset scope",
            )
        _require(asset["generation"] == run["generation"], "Asset generation binding")
    zip_assets = [row for row in assets if row["id"] == delivery["zip_asset_id"]]
    _require(len(zip_assets) == 1 and zip_assets[0]["kind"] == "delivery_zip", "bound ZIP Asset")


def prove_lineage_rejections(
    durable: dict[str, Any], evidence: dict[str, Any], *, scenario: str
) -> None:
    """Exercise mutations of current evidence, including real successful producers."""
    validate_lineage(durable, evidence, scenario=scenario)
    stage_by_id = {row["id"]: row for row in durable["stages"]}
    task_by_id = {row["id"]: row for row in durable["tasks"]}
    ingest_attempt = next(
        row["id"]
        for row in durable["attempts"]
        if row["outcome"] == "succeeded"
        and stage_by_id.get(task_by_id[row["task_id"]]["stage_run_id"], {}).get("stage") == "ingest"
    )
    mutations = [
        ("delivery_zip", "producer_attempt_id", ingest_attempt, "Asset wrong delivery producer"),
        ("edit_plans", "producer_attempt_id", ingest_attempt, "Asset wrong stage producer"),
        ("edit_plans", "kind", "unknown_kind", "Asset wrong stage producer"),
        ("edit_plans", "generation", -1, "Asset generation binding"),
        ("edit_plans", "candidate_clip_id", "invalid", "nonrender Asset scope"),
        ("review_proxy", "edit_plan_revision", -1, "render Asset clip/revision binding"),
    ]
    if scenario == "b2":
        mutations.append(
            (
                "semantic_unit_outcome",
                "producer_attempt_id",
                ingest_attempt,
                "Asset wrong stage producer",
            )
        )
    else:
        mutations.append(
            ("edit_plans", "kind", "semantic_unit_outcome", "Asset wrong stage producer")
        )
    for kind, field, value, reason in mutations:
        altered = copy.deepcopy(durable)
        asset = next(row for row in altered["assets"] if row["kind"] == kind)
        asset[field] = value
        try:
            validate_lineage(altered, evidence, scenario=scenario)
        except ValueError as error:
            _require(str(error) == reason, "lineage rejection reason")
        else:
            raise ValueError("tampered Asset lineage accepted")
    for duplicate in (False, True):
        altered = copy.deepcopy(durable)
        if duplicate:
            altered["assets"][0] = copy.deepcopy(altered["assets"][1])
        else:
            altered["assets"].pop()
        try:
            validate_lineage(altered, evidence, scenario=scenario)
        except ValueError as error:
            _require(str(error) == "Asset inventory", "inventory rejection reason")
        else:
            raise ValueError("tampered Asset inventory accepted")


def test_semantic_lineage_contract() -> None:
    """Focused regression using the checked-in, credential-free SQLite snapshot."""
    fixture = _json(
        Path(__file__).resolve().parents[1] / "tests/fixtures/completion-retained-lineage-v1.json"
    )
    durable, evidence = fixture["durable"], fixture["evidence"]
    prove_lineage_rejections(durable, evidence, scenario="completion")
    # Both real owning stages must work; semantic operation names are not stages.
    for index, kind in enumerate(("rough_candidates", "edit_plans"), start=1):
        semantic = copy.deepcopy(next(row for row in durable["assets"] if row["kind"] == kind))
        semantic.update(id=f"{index:032x}", kind="semantic_unit_outcome")
        durable["assets"].append(semantic)
    evidence["asset_count"] = len(durable["assets"])
    prove_lineage_rejections(durable, evidence, scenario="b2")
    try:
        validate_lineage(durable, evidence)
    except ValueError as error:
        _require(str(error) == "Asset inventory", "legacy count rejection reason")
    else:
        raise ValueError("legacy completion accepted expanded semantic inventory")


def validate_packaging(
    bundle: dict[str, Any], durable: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """Correlate real persisted pauses and browser GETs with the committed attempt."""
    _require(bundle["schema_version"] == "liveclip.b2-packaging.v1", "B2 schema")
    _require(HEX64.fullmatch(bundle["source_sha256"]), "B2 unchanged source hash")
    _require(
        bundle["config"]
        == {
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
        "B2 frozen canonical config",
    )
    created = bundle["browser"]["create"]
    for field in ("intent_id", "project_id", "run_id"):
        _require(created[field] == evidence[field], "B2 production create identity")
    _require(
        created["confirmed_before_reload"] is True
        and created["pending_cleared"] is True
        and created["modal_closed"] is True
        and created["generation"] == durable["run"]["generation"]
        and re.fullmatch(r"liveclip-web-completion-[A-Za-z0-9-]+", created["request_key"])
        and created["request_body"]["preset_id"] == "short_highlight_v1"
        and created["request_body"]["selection_policy"] == "manual",
        "B2 production create and confirmed reconnect proof",
    )
    observations = bundle["browser"]["observations"]
    _require(
        created["observed_unix_ms"] < observations[0]["observed_unix_ms"],
        "B2 confirmed identity precedes packaging reload",
    )
    _require(
        len(observations) == len(bundle["pauses"]) == len(bundle["releases"]) == 2,
        "B2 requires two actual count observations",
    )
    task = next(row for row in durable["tasks"] if row["kind"] == "delivery")
    attempt = next(row for row in durable["attempts"] if row["task_id"] == task["id"])
    final = bundle["final_progress"]
    _require(
        final["delivery_id"] == evidence["delivery_id"]
        and final["task_attempt_id"] == attempt["id"]
        and final["phase"] == "committing_assets"
        and final["completed"] == final["total"],
        "B2 final persisted progress",
    )
    previous_release = 0
    for count, (pause, release, observed) in enumerate(
        zip(
            bundle["pauses"],
            bundle["releases"],
            observations,
            strict=True,
        ),
        1,
    ):
        for row in (pause, release, observed):
            _require(
                all(
                    row[key] == evidence[key]
                    for key in (
                        "project_id",
                        "run_id",
                        "generation",
                        "delivery_id",
                    )
                ),
                "B2 paused goal identity",
            )
            _require(
                row["task_id"] == task["id"]
                and row["attempt_id"] == attempt["id"]
                and row["phase"] == "writing_metadata"
                and row["unit"] == "files"
                and row["completed"] == count
                and row["total"] == 4,
                "B2 phase/attempt identity",
            )
        _require(
            observed["intent_id"] == evidence["intent_id"]
            and observed["reloaded"] is (count == 1)
            and observed["navigated"] is (count == 2),
            "B2 reload reconnect",
        )
        progress = observed["progress"]
        _require(
            all(
                progress[key] == pause[key]
                for key in (
                    "phase",
                    "unit",
                    "completed",
                    "total",
                    "attempt_id",
                )
            )
            and progress["lease_fresh"] is True,
            "B2 authenticated GET matches persisted count",
        )
        _require(
            previous_release
            <= pause["observed_unix_ms"]
            <= observed["observed_unix_ms"]
            <= release["released_unix_ms"]
            and 0 <= release["released_unix_ms"] - pause["observed_unix_ms"] < 40000,
            "B2 pause/reload/release ordering and bound",
        )
        previous_release = release["released_unix_ms"]


def verify_bundle(
    repository_root: Path,
    *,
    removed_fixture_root: Path,
    prove_rejection: bool,
    scenario: str = "completion",
) -> dict[str, Any]:
    _require(
        removed_fixture_root.is_absolute() and not removed_fixture_root.exists(),
        "disposable fixture still exists",
    )
    _require(scenario in {"completion", "b2"}, "unknown retained scenario")
    folder = "b2-packages" if scenario == "b2" else "completion-packages"
    report_root = repository_root / "apps/web/playwright-report" / folder
    manifests = sorted(report_root.glob("*/manifest.json"))
    _require(len(manifests) == 1, "exactly one retained completion package required")
    root = manifests[0].parent
    _require(root.parent == report_root and HEX32.fullmatch(root.name), "retained run directory")
    manifest = _json(manifests[0])
    _require(
        set(manifest)
        == {"schema_version", "synthetic_mock_asr_llm", "evidence", "asset_count", "files"}
        and manifest["schema_version"] == "liveclip.completion-browser-evidence.v2"
        and manifest["synthetic_mock_asr_llm"] is True,
        "retained manifest schema",
    )
    evidence = manifest["evidence"]
    _require(
        set(evidence)
        == {
            "project_id",
            "run_id",
            "intent_id",
            "generation",
            "stage_count",
            "task_count",
            "attempt_count",
            "deferred_attempt_count",
            "asset_count",
            "delivery_id",
            "delivery_version",
            "zip_sha256",
            "browser_download_sha256",
            "observer_closed_unix_ms",
            "waiting_observed_unix_ms",
        }
        and evidence["run_id"] == root.name
        and evidence["delivery_version"] == "v001"
        and manifest["asset_count"] == evidence["asset_count"],
        "retained evidence identity",
    )
    files = manifest["files"]
    _require(
        len(files) == evidence["asset_count"] + (6 if scenario == "b2" else 5),
        "retained file count",
    )
    _require(
        all(type(entry.get("size_bytes")) is int and entry["size_bytes"] >= 0 for entry in files)
        and sum(entry["size_bytes"] for entry in files if "asset_id" in entry) <= 256_000_000,
        "retained Asset byte bound",
    )
    by_path = {}
    for entry in files:
        _require(
            set(entry)
            in ({"path", "sha256", "size_bytes"}, {"path", "asset_id", "sha256", "size_bytes"})
            and isinstance(entry["size_bytes"], int)
            and entry["size_bytes"] >= 0
            and HEX64.fullmatch(entry["sha256"]),
            "retained entry fields",
        )
        name = entry["path"]
        relative = PurePosixPath(name)
        _require(
            not relative.is_absolute()
            and relative.parts
            and all(part not in ("", ".", "..") for part in relative.parts)
            and relative.as_posix() == name
            and "\\" not in name
            and name not in by_path,
            "unsafe/duplicate retained path",
        )
        path = root.joinpath(*relative.parts)
        _require(
            stat.S_ISREG(path.lstat().st_mode) and path.resolve(strict=True).is_relative_to(root),
            "retained file not regular",
        )
        _require(
            path.stat().st_size == entry["size_bytes"] and _digest(path) == entry["sha256"],
            "retained file identity",
        )
        by_path[name] = entry
        if "asset_id" in entry:
            _require(
                HEX32.fullmatch(entry["asset_id"]) and name == f"assets/{entry['asset_id']}.bin",
                "retained Asset entry path",
            )
    _exact_inventory(root, set(by_path))
    _require(
        {
            "delivery.zip",
            "durable.json",
            "observer-closed.json",
            "waiting.json",
            "download.json",
        }.issubset(by_path),
        "required retained files",
    )
    durable = _json(root / "durable.json")
    validate_lineage(durable, evidence, scenario=scenario)
    asset_entries = [entry for entry in files if "asset_id" in entry]
    _require(
        len(asset_entries) == manifest["asset_count"]
        and {entry["asset_id"] for entry in asset_entries}
        == {asset["id"] for asset in durable["assets"]},
        "retained/SQLite Asset inventory",
    )
    if scenario == "b2":
        _require("packaging.json" in by_path, "B2 packaging evidence missing")
        packaging = _json(root / "packaging.json")
        validate_packaging(packaging, durable, evidence)
        _safe_text(
            (root / "packaging.json").read_bytes(),
            lease_token_hashes={row["lease_token_sha256"] for row in durable["attempts"]},
        )
        source_asset = next(row for row in durable["assets"] if row["kind"] == "source_metadata")
        source = _json(root / "assets" / f"{source_asset['id']}.bin")
        _require(source["sha256"] == packaging["source_sha256"], "B2 unchanged ingested source")
    project = durable["project"]
    selected = durable["intent"]["selection_checkpoint"]["selected"]
    lease_hashes = {row["lease_token_sha256"] for row in durable["attempts"]}
    for asset in durable["assets"]:
        name = f"assets/{asset['id']}.bin"
        _require(
            name in by_path
            and by_path[name]["asset_id"] == asset["id"]
            and by_path[name]["sha256"] == asset["sha256"]
            and by_path[name]["size_bytes"] == asset["size_bytes"],
            "Asset retained bytes",
        )
        if asset["kind"] in TEXT_ASSET_KINDS | {"semantic_unit_outcome"}:
            _safe_text((root / name).read_bytes(), lease_token_hashes=lease_hashes)
            if asset["kind"] in {"transcript_srt", "clip_subtitle_srt"}:
                _require(bool(load_srt_transcript(root / name).segments), "retained Asset SRT cues")
    delivery = durable["deliveries"][0]
    zip_asset = next(row for row in durable["assets"] if row["id"] == delivery["zip_asset_id"])
    archive = root / "delivery.zip"
    _require(
        archive.read_bytes() == (root / f"assets/{zip_asset['id']}.bin").read_bytes(),
        "ZIP/Asset bytes",
    )
    _require(
        _digest(archive)
        == zip_asset["sha256"]
        == evidence["zip_sha256"]
        == evidence["browser_download_sha256"],
        "ZIP/page/Asset hash",
    )
    closed, waiting, download = (
        _json(root / name) for name in ("observer-closed.json", "waiting.json", "download.json")
    )
    _require(
        set(closed)
        == {"schema_version", "project_id", "run_id", "intent_id", "generation", "closed_unix_ms"}
        and closed["schema_version"] == "liveclip.completion-observer-closed.v1"
        and set(waiting)
        == {
            "schema_version",
            "project_id",
            "run_id",
            "intent_id",
            "generation",
            "completion_task_id",
            "deferred_attempt_count",
            "observed_unix_ms",
            "observer_closed_unix_ms",
        }
        and waiting["schema_version"] == "liveclip.completion-waiting.v1"
        and set(download)
        == {
            "schema_version",
            "project_id",
            "run_id",
            "intent_id",
            "delivery_id",
            "observer_closed_unix_ms",
            "waiting_observed_unix_ms",
            "response_status",
            "content_type",
            "content_disposition",
            "size_bytes",
            "sha256",
        }
        and download["schema_version"] == "liveclip.completion-browser-download.v1",
        "marker fields/schema",
    )
    _require(
        closed["project_id"]
        == waiting["project_id"]
        == download["project_id"]
        == evidence["project_id"]
        and closed["generation"] == waiting["generation"] == evidence["generation"]
        and waiting["completion_task_id"]
        == next(row["id"] for row in durable["tasks"] if row["kind"] == "completion")
        and 1 <= waiting["deferred_attempt_count"] <= evidence["deferred_attempt_count"]
        and download["content_disposition"] == 'attachment; filename="liveclip-v001.zip"',
        "marker project/generation/Task/headers",
    )
    _require(
        closed["run_id"] == waiting["run_id"] == download["run_id"] == evidence["run_id"],
        "marker run",
    )
    _require(
        closed["intent_id"]
        == waiting["intent_id"]
        == download["intent_id"]
        == evidence["intent_id"],
        "marker intent",
    )
    _require(
        closed["closed_unix_ms"]
        == waiting["observer_closed_unix_ms"]
        == download["observer_closed_unix_ms"]
        == evidence["observer_closed_unix_ms"],
        "observer closure",
    )
    _require(
        closed["closed_unix_ms"]
        <= waiting["observed_unix_ms"]
        == download["waiting_observed_unix_ms"]
        == evidence["waiting_observed_unix_ms"],
        "waiting order",
    )
    _require(
        waiting["deferred_attempt_count"] >= 1
        and download["response_status"] == 200
        and download["content_type"] == "application/zip",
        "wait/download status",
    )
    _require(
        download["delivery_id"] == delivery["id"]
        and download["sha256"] == zip_asset["sha256"]
        and download["size_bytes"] == zip_asset["size_bytes"],
        "page download binding",
    )
    with (
        zipfile.ZipFile(archive) as package,
        tempfile.TemporaryDirectory(prefix=".liveclip-retained-", dir=report_root) as temp,
    ):
        infos = package.infolist()
        _require(
            sum(info.file_size for info in infos) <= 256_000_000
            and all(
                not info.is_dir()
                and info.file_size <= 256_000_000
                and stat.S_IFMT(info.external_attr >> 16) != stat.S_IFLNK
                for info in infos
            ),
            "ZIP member type/size",
        )
        _require(package.testzip() is None, "ZIP CRC")
        names = package.namelist()
        _require(
            len(names) == len(set(names))
            and all(
                not PurePosixPath(name).is_absolute()
                and all(part not in ("", ".", "..") for part in PurePosixPath(name).parts)
                and PurePosixPath(name).as_posix() == name
                and "\\" not in name
                for name in names
            ),
            "ZIP members",
        )
        videos = [name for name in names if name.endswith(".mp4")]
        subtitles = [name for name in names if name.endswith(".srt")]
        _require(
            len(videos) == len(subtitles) == 1,
            "ZIP media",
        )
        _require(
            set(names)
            == {
                "manifest.json",
                "index.html",
                "checksums.sha256",
                videos[0],
                subtitles[0],
            },
            "ZIP exact membership",
        )
        checksums = {}
        for line in package.read("checksums.sha256").decode("utf-8").splitlines():
            digest, separator, name = line.partition("  ")
            _require(
                separator == "  "
                and HEX64.fullmatch(digest)
                and name in names
                and name not in checksums,
                "ZIP checksum entry",
            )
            checksums[name] = digest
        _require(
            set(checksums) == set(names) - {"checksums.sha256"}
            and all(
                hashlib.sha256(package.read(name)).hexdigest() == digest
                for name, digest in checksums.items()
            ),
            "ZIP checksums",
        )
        scan_zip_text(package, lease_token_hashes=lease_hashes)
        package_manifest = json.loads(package.read("manifest.json"))
        _require(isinstance(package_manifest, dict), "ZIP manifest object")
        package_clips = package_manifest.get("clips")
        _require(
            package_manifest.get("schema_version") == "1"
            and package_manifest.get("project_id") == project["id"]
            and package_manifest.get("delivery_id") == delivery["id"]
            and package_manifest.get("delivery_version") == "v001"
            and isinstance(package_clips, list)
            and len(package_clips) == 1
            and isinstance(package_clips[0], dict),
            "ZIP manifest Delivery binding",
        )
        package_clip = package_clips[0]
        video_bytes = package.read(videos[0])
        _require(
            package_clip.get("clip_id") == selected[0]["clip_id"]
            and package_clip.get("edit_plan_revision") == selected[0]["edit_plan_revision"]
            and package_clip.get("video_filename") == videos[0]
            and package_clip.get("subtitle_filename") == subtitles[0]
            and package_clip.get("sha256") == hashlib.sha256(video_bytes).hexdigest(),
            "ZIP manifest selected clip/media binding",
        )
        masters = [asset for asset in durable["assets"] if asset["kind"] == "review_proxy"]
        _require(len(masters) == 1, "selected master Asset identity")
        master = masters[0]
        _require(
            master["candidate_clip_id"] == selected[0]["clip_id"]
            and master["edit_plan_revision"] == selected[0]["edit_plan_revision"]
            and package_clip["sha256"] == master["sha256"]
            and len(video_bytes) == master["size_bytes"]
            and video_bytes == (root / f"assets/{master['id']}.bin").read_bytes(),
            "ZIP/selected master bytes",
        )
        subtitle = Path(temp) / "clip.srt"
        subtitle_bytes = package.read(subtitles[0])
        subtitle.write_bytes(subtitle_bytes)
        _require(bool(load_srt_transcript(subtitle).segments), "ZIP SRT cues")
        clip_srt_assets = [
            asset for asset in durable["assets"] if asset["kind"] == "clip_subtitle_srt"
        ]
        _require(
            len(clip_srt_assets) == 1
            and subtitle_bytes == (root / f"assets/{clip_srt_assets[0]['id']}.bin").read_bytes(),
            "ZIP/Asset subtitle bytes",
        )
        video = Path(temp) / "clip.mp4"
        video.write_bytes(video_bytes)
        ffmpeg = shutil.which("ffmpeg")
        _require(ffmpeg is not None, "FFmpeg unavailable")
        assert ffmpeg is not None
        decoded = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-xerror",
                "-i",
                str(video),
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
        )
        _require(decoded.returncode == 0, "MP4 decode")
    for name in (
        "manifest.json",
        "durable.json",
        "observer-closed.json",
        "waiting.json",
        "download.json",
    ):
        _safe_text((root / name).read_bytes(), lease_token_hashes=lease_hashes)
    if prove_rejection:
        prove_lineage_rejections(durable, evidence, scenario=scenario)
        altered = copy.deepcopy(durable)
        zip_row = next(row for row in altered["assets"] if row["id"] == delivery["zip_asset_id"])
        wrong = next(
            row
            for row in altered["attempts"]
            if row["outcome"] == "succeeded"
            and next(task for task in altered["tasks"] if task["id"] == row["task_id"])["kind"]
            == "stage"
        )
        zip_row["producer_attempt_id"] = wrong["id"]
        try:
            validate_lineage(altered, evidence, scenario=scenario)
        except ValueError as error:
            _require("wrong delivery producer" in str(error), "wrong-producer rejection reason")
        else:
            raise ValueError("wrong existing producer attempt accepted")
    return {
        "status": "PASS",
        "run_id": evidence["run_id"],
        "manifest_sha256": _digest(manifests[0]),
        "retained_files": len(files),
        "asset_count": len(durable["assets"]),
        "attempt_count": len(durable["attempts"]),
        "deferred_attempt_count": evidence["deferred_attempt_count"],
        "wrong_existing_producer_rejected": prove_rejection,
        "fixture_removed": True,
        "full_mp4_decode": "PASS",
    }


def validate_browser_execution(report: dict[str, Any], scenario: str) -> None:
    """Require the named production scenario and one clean, unretried execution."""
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
    stats = report.get("stats", {})
    _require(
        stats.get("expected") == 1
        and all(stats.get(key) == 0 for key in ("skipped", "unexpected", "flaky"))
        and report.get("errors") == [],
        "required browser execution totals",
    )
    specs: list[dict[str, Any]] = []

    def collect(suites: list[dict[str, Any]]) -> None:
        for suite in suites:
            specs.extend(suite.get("specs", []))
            collect(suite.get("suites", []))

    collect(report.get("suites", []))
    _require(len(specs) == 1, "required browser scenario count")
    spec = specs[0]
    _require(
        spec.get("file") == filename and spec.get("title") == title and spec.get("ok") is True,
        "required browser scenario identity",
    )
    tests = spec.get("tests", [])
    _require(len(tests) == 1, "required browser test count")
    test = tests[0]
    results = test.get("results", [])
    _require(
        test.get("expectedStatus") == "passed"
        and test.get("status") == "expected"
        and len(results) == 1
        and results[0].get("status") == "passed"
        and results[0].get("retry") == 0
        and results[0].get("errors") == [],
        "required browser test must pass without retries",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--removed-fixture-root", type=Path)
    parser.add_argument("--browser-report", type=Path)
    parser.add_argument("--prove-rejection", action="store_true")
    parser.add_argument("--scenario", choices=("legacy", "completion", "b2"), default="completion")
    args = parser.parse_args()
    if args.browser_report:
        validate_browser_execution(json.loads(args.browser_report.read_text()), args.scenario)
        print("Required browser scenario execution: PASS")
        return
    if not args.root or not args.removed_fixture_root or args.scenario == "legacy":
        parser.error("bundle verification requires both roots and a completion or b2 scenario")
    result = verify_bundle(
        args.root.resolve(strict=True),
        removed_fixture_root=args.removed_fixture_root,
        prove_rejection=args.prove_rejection,
        scenario=args.scenario,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
