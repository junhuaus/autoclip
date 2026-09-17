"""Exercise both complete browser-evidence verifiers on disposable real bytes."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import sqlite3
import subprocess
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "completion_e2e_fixture", _ROOT / "scripts/e2e_fixture.py"
)
_RETAINED_SPEC = importlib.util.spec_from_file_location(
    "completion_retained_verifier", _ROOT / "scripts/verify_completion_retained.py"
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
assert _RETAINED_SPEC is not None and _RETAINED_SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_FIXTURE_SPEC)
_RETAINED = importlib.util.module_from_spec(_RETAINED_SPEC)
_FIXTURE_SPEC.loader.exec_module(_FIXTURE)
_RETAINED_SPEC.loader.exec_module(_RETAINED)

_SRT = b"1\n00:00:00,000 --> 00:00:00,900\nSynthetic cue\n"


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _package(members: dict[str, bytes], *, with_checksums: bool = True) -> bytes:
    values = dict(members)
    assert "checksums.sha256" not in values
    if with_checksums:
        values["checksums.sha256"] = "".join(
            f"{_digest(raw)}  {name}\n" for name, raw in sorted(values.items())
        ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(values.items()):
            archive.writestr(name, raw)
    return output.getvalue()


def _media(path: Path, *, color: str = "blue") -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=64x96:r=6:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0
    decoded = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-f",
            "null",
            "-",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert decoded.returncode == 0
    return path.read_bytes()


def _insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    fields = tuple(rows[0])
    quoted = ", ".join(f'"{field}"' for field in fields)
    declarations = ", ".join(f'"{field}" BLOB' for field in fields)
    connection.execute(f'CREATE TABLE "{table}" ({declarations})')
    connection.executemany(
        f'INSERT INTO "{table}" ({quoted}) VALUES ({", ".join("?" for _ in fields)})',
        [tuple(row[field] for field in fields) for row in rows],
    )


@pytest.fixture
def completion_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    repository = tmp_path.resolve(strict=True)
    monkeypatch.setattr(_FIXTURE, "_REPOSITORY_ROOT", repository)
    monkeypatch.setenv("LIVECLIP_E2E_TOKEN", "liveclip-real-browser-test-token")
    monkeypatch.setenv("LIVECLIP_E2E_PASSWORD", "liveclip real browser password 2026")
    source = json.loads((_ROOT / "tests/fixtures/completion-retained-lineage-v1.json").read_text())
    durable = deepcopy(source["durable"])
    run_id = durable["run"]["id"]
    project_id = durable["project"]["id"]
    delivery_id = durable["deliveries"][0]["id"]
    selected = durable["intent"]["selection_checkpoint"]["selected"][0]
    video = _media(repository / "tiny.mp4")
    manifest = {
        "schema_version": "1",
        "project_id": project_id,
        "delivery_id": delivery_id,
        "delivery_version": "v001",
        "clips": [
            {
                "clip_id": selected["clip_id"],
                "edit_plan_revision": selected["edit_plan_revision"],
                "video_filename": "clips/clip.mp4",
                "subtitle_filename": "subtitles/clip.srt",
                "sha256": _digest(video),
            }
        ],
    }
    delivery_bytes = _package(
        {
            "clips/clip.mp4": video,
            "subtitles/clip.srt": _SRT,
            "manifest.json": _json_bytes(manifest),
            "index.html": b"<!doctype html><title>Synthetic</title>",
        }
    )
    root, identity = _FIXTURE.allocated_e2e_root()
    project_root = root / "projects" / project_id
    project_root.mkdir(parents=True)
    lease_tokens = []
    for index, row in enumerate(durable["attempts"]):
        raw = _digest(f"synthetic-lease-{index}".encode())
        lease_tokens.append(raw)
        row["lease_token_sha256"] = _digest(raw.encode())
    text = {
        "transcript_srt": _SRT,
        "clip_subtitle_srt": _SRT,
        "delivery_manifest": _json_bytes(manifest),
    }
    binary = {"review_proxy": video, "delivery_zip": delivery_bytes}
    for asset in durable["assets"]:
        kind = asset["kind"]
        if kind in text:
            raw = text[kind]
        elif kind in binary:
            raw = binary[kind]
        elif kind in {"audio_chunk", "render_contact_sheet"}:
            raw = f"synthetic-binary-{kind}-{asset['id']}".encode()
        else:
            raw = _json_bytes({"synthetic_kind": kind, "asset_id": asset["id"]})
        target = project_root / asset["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        asset["sha256"], asset["size_bytes"] = _digest(raw), len(raw)
    evidence = deepcopy(source["evidence"])
    evidence["zip_sha256"] = evidence["browser_download_sha256"] = _digest(delivery_bytes)
    closed = {
        "schema_version": "liveclip.completion-observer-closed.v1",
        "project_id": project_id,
        "run_id": run_id,
        "intent_id": durable["intent"]["id"],
        "generation": 1,
        "closed_unix_ms": evidence["observer_closed_unix_ms"],
    }
    waiting = {
        "schema_version": "liveclip.completion-waiting.v1",
        "project_id": project_id,
        "run_id": run_id,
        "intent_id": durable["intent"]["id"],
        "generation": 1,
        "completion_task_id": next(
            row["id"] for row in durable["tasks"] if row["kind"] == "completion"
        ),
        "deferred_attempt_count": 2,
        "observed_unix_ms": evidence["waiting_observed_unix_ms"],
        "observer_closed_unix_ms": evidence["observer_closed_unix_ms"],
    }
    download = {
        "schema_version": "liveclip.completion-browser-download.v1",
        "project_id": project_id,
        "run_id": run_id,
        "intent_id": durable["intent"]["id"],
        "delivery_id": delivery_id,
        "observer_closed_unix_ms": evidence["observer_closed_unix_ms"],
        "waiting_observed_unix_ms": evidence["waiting_observed_unix_ms"],
        "response_status": 200,
        "content_type": "application/zip",
        "content_disposition": 'attachment; filename="liveclip-v001.zip"',
        "size_bytes": len(delivery_bytes),
        "sha256": _digest(delivery_bytes),
    }
    logs = root / "logs"
    logs.mkdir()
    for name, value in (
        ("completion-observer-closed.json", closed),
        ("completion-waiting.json", waiting),
        ("completion-browser-download.json", download),
    ):
        (logs / name).write_bytes(_json_bytes(value))
    database = root / "projects/liveclip.sqlite3"
    with sqlite3.connect(database) as connection:
        _insert_rows(connection, "projects", [durable["project"]])
        _insert_rows(connection, "pipeline_runs", [durable["run"]])
        intent = deepcopy(durable["intent"])
        intent["selection_checkpoint_json"] = json.dumps(intent.pop("selection_checkpoint"))
        _insert_rows(connection, "completion_intents", [intent])
        _insert_rows(connection, "stage_runs", durable["stages"])
        _insert_rows(connection, "tasks", durable["tasks"])
        attempts = []
        for row, raw in zip(durable["attempts"], lease_tokens, strict=True):
            attempt = dict(row)
            attempt.pop("lease_token_sha256")
            attempt["lease_token"] = raw
            attempts.append(attempt)
        _insert_rows(connection, "task_attempts", attempts)
        _insert_rows(connection, "deliveries", durable["deliveries"])
        _insert_rows(connection, "delivery_clips", durable["delivery_clips"])
        _insert_rows(connection, "assets", durable["assets"])
    sample = {
        "repository": repository,
        "root": root,
        "identity": identity,
        "database": database,
        "durable": durable,
        "evidence": evidence,
        "lease_token": lease_tokens[0],
    }
    try:
        yield sample
    finally:
        if root.exists():
            _FIXTURE.cleanup_fixture(root, expected_identity=identity)


def _verified_run(sample: dict, *, retain: bool = False) -> dict:
    return _FIXTURE.verify_completion_run(
        sample["root"], expected_identity=sample["identity"], retain_packages=retain
    )


def test_complete_sqlite_verifier_rejects_dependency_producer_and_scope(
    completion_sample: dict,
) -> None:
    sample = completion_sample
    assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]
    stages = {row["id"]: row["stage"] for row in sample["durable"]["stages"]}
    stage_tasks = [row for row in sample["durable"]["tasks"] if row["kind"] == "stage"]
    preprocess = next(row for row in stage_tasks if stages[row["stage_run_id"]] == "preprocess")
    edit = next(row for row in stage_tasks if stages[row["stage_run_id"]] == "edit")
    edit_attempt = next(
        row
        for row in sample["durable"]["attempts"]
        if row["task_id"] == edit["id"] and row["outcome"] == "succeeded"
    )
    proxy = next(row for row in sample["durable"]["assets"] if row["kind"] == "review_proxy")
    mutations = (
        ("tasks", "depends_on_task_id", preprocess["id"], preprocess["id"], "stage/Task lineage"),
        ("assets", "producer_attempt_id", proxy["id"], edit_attempt["id"], "wrong Task/stage"),
        ("assets", "generation", proxy["id"], 999, "Asset generation"),
        ("assets", "edit_plan_revision", proxy["id"], 999, "render Asset revision"),
    )
    with sqlite3.connect(sample["database"]) as connection:
        for table, field, row_id, invalid, message in mutations:
            original = connection.execute(
                f'SELECT "{field}" FROM "{table}" WHERE id = ?', (row_id,)
            ).fetchone()[0]
            connection.execute(
                f'UPDATE "{table}" SET "{field}" = ? WHERE id = ?', (invalid, row_id)
            )
            connection.commit()
            with pytest.raises(ValueError, match=message):
                _verified_run(sample)
            connection.execute(
                f'UPDATE "{table}" SET "{field}" = ? WHERE id = ?', (original, row_id)
            )
            connection.commit()
            assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]


def test_complete_sqlite_verifier_refuses_sensitive_retention(
    completion_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = completion_sample
    assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]
    monkeypatch.setenv("LIVECLIP_E2E_TOKEN", "configured-synthetic-token")
    monkeypatch.setenv("LIVECLIP_E2E_PASSWORD", "configured synthetic password")
    source = next(row for row in sample["durable"]["assets"] if row["kind"] == "source_metadata")
    path = sample["root"] / "projects" / source["project_id"] / source["relative_path"]
    original_bytes = path.read_bytes()
    with sqlite3.connect(sample["database"]) as connection:
        original_row = connection.execute(
            "SELECT sha256, size_bytes FROM assets WHERE id = ?", (source["id"],)
        ).fetchone()
        for leaked in (
            sample["lease_token"],
            "configured-synthetic-token",
            "configured synthetic password",
        ):
            assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]
            contaminated = _json_bytes({"note": leaked})
            path.write_bytes(contaminated)
            connection.execute(
                "UPDATE assets SET sha256 = ?, size_bytes = ? WHERE id = ?",
                (_digest(contaminated), len(contaminated), source["id"]),
            )
            connection.commit()
            with pytest.raises(ValueError, match="secret/URL"):
                _verified_run(sample, retain=True)
            _repository, folder = _bundle_paths(sample)
            assert not folder.exists()
            path.write_bytes(original_bytes)
            connection.execute(
                "UPDATE assets SET sha256 = ?, size_bytes = ? WHERE id = ?",
                (*original_row, source["id"]),
            )
            connection.commit()
            assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]
    _verified_run(sample, retain=True)
    assert _FIXTURE.cleanup_fixture(sample["root"], expected_identity=sample["identity"])
    assert _verified_bundle(sample)["status"] == "PASS"
    _repository, folder = _bundle_paths(sample)
    assert folder.is_dir()


def test_complete_sqlite_verifier_refuses_signed_zip_retention(
    completion_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = completion_sample
    assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]
    monkeypatch.setenv("LIVECLIP_E2E_TOKEN", "configured-synthetic-token")
    monkeypatch.setenv("LIVECLIP_E2E_PASSWORD", "configured synthetic password")
    zip_asset = next(row for row in sample["durable"]["assets"] if row["kind"] == "delivery_zip")
    path = sample["root"] / "projects" / zip_asset["project_id"] / zip_asset["relative_path"]
    original_bytes = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        members = {
            name: archive.read(name) for name in archive.namelist() if name != "checksums.sha256"
        }
    videos = [name for name in members if name.endswith(".mp4")]
    assert len(videos) == 1
    replacement_video = _media(sample["repository"] / "pre-retention-replacement.mp4", color="red")
    assert _digest(replacement_video) != _digest(members[videos[0]])
    wrong_master = json.loads(members["manifest.json"])
    wrong_master["clips"][0]["sha256"] = _digest(replacement_video)
    marker_path = sample["root"] / "logs/completion-browser-download.json"
    original_marker = marker_path.read_bytes()
    variants = (
        ({**members, "index.html": b"configured-synthetic-token"}, "secret/URL"),
        ({**members, "index.html": b"configured synthetic password"}, "secret/URL"),
        (
            {**members, "index.html": b"https://example.invalid/?X-Amz-Signature=synthetic"},
            "secret/URL",
        ),
        (
            {**members, videos[0]: replacement_video, "manifest.json": _json_bytes(wrong_master)},
            "ZIP video differs from selected master bytes",
        ),
    )
    for mutated_members, message in variants:
        assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]
        changed = _package(mutated_members)
        path.write_bytes(changed)
        with sqlite3.connect(sample["database"]) as connection:
            connection.execute(
                "UPDATE assets SET sha256 = ?, size_bytes = ? WHERE id = ?",
                (_digest(changed), len(changed), zip_asset["id"]),
            )
        marker = json.loads(original_marker)
        marker["sha256"], marker["size_bytes"] = _digest(changed), len(changed)
        marker_path.write_bytes(_json_bytes(marker))
        with pytest.raises(ValueError, match=message):
            _verified_run(sample, retain=True)
        _repository, folder = _bundle_paths(sample)
        assert not folder.exists()
        path.write_bytes(original_bytes)
        with sqlite3.connect(sample["database"]) as connection:
            connection.execute(
                "UPDATE assets SET sha256 = ?, size_bytes = ? WHERE id = ?",
                (_digest(original_bytes), len(original_bytes), zip_asset["id"]),
            )
        marker_path.write_bytes(original_marker)
        assert _verified_run(sample)["run_id"] == sample["durable"]["run"]["id"]
    _verified_run(sample, retain=True)
    assert _FIXTURE.cleanup_fixture(sample["root"], expected_identity=sample["identity"])
    assert _verified_bundle(sample)["status"] == "PASS"


def _bundle_paths(sample: dict) -> tuple[Path, Path]:
    repository = sample["repository"]
    run_id = sample["durable"]["run"]["id"]
    folder = repository / "apps/web/playwright-report/completion-packages" / run_id
    return repository, folder


def _verified_bundle(sample: dict) -> dict:
    return _RETAINED.verify_bundle(
        sample["repository"], removed_fixture_root=sample["root"], prove_rejection=True
    )


def _rehash(folder: Path, *names: str) -> None:
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for name in names:
        entry = next(row for row in manifest["files"] if row["path"] == name)
        raw = (folder / name).read_bytes()
        entry["sha256"], entry["size_bytes"] = _digest(raw), len(raw)
    manifest_path.write_bytes(_json_bytes(manifest))


def test_complete_retained_verifier_rejects_rehashed_mutations(
    completion_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = completion_sample
    monkeypatch.setenv("LIVECLIP_E2E_TOKEN", "configured-synthetic-token")
    monkeypatch.setenv("LIVECLIP_E2E_PASSWORD", "configured synthetic password")
    _verified_run(sample, retain=True)
    assert _FIXTURE.cleanup_fixture(sample["root"], expected_identity=sample["identity"])
    assert _verified_bundle(sample)["status"] == "PASS"
    _repository, folder = _bundle_paths(sample)

    extra = folder / "unlisted.txt"
    extra.write_text("unlisted")
    with pytest.raises(ValueError, match="unlisted retained file"):
        _verified_bundle(sample)
    extra.unlink()
    assert _verified_bundle(sample)["status"] == "PASS"

    durable_path = folder / "durable.json"
    original_durable = durable_path.read_bytes()
    durable = json.loads(original_durable)
    stage_tasks = [row for row in durable["tasks"] if row["kind"] == "stage"]
    stage_tasks[1]["depends_on_task_id"] = stage_tasks[1]["id"]
    durable_path.write_bytes(_json_bytes(durable))
    _rehash(folder, "durable.json")
    with pytest.raises(ValueError, match="stage Task dependency graph"):
        _verified_bundle(sample)
    durable_path.write_bytes(original_durable)
    _rehash(folder, "durable.json")
    assert _verified_bundle(sample)["status"] == "PASS"

    durable = json.loads(original_durable)
    source_asset = next(row for row in durable["assets"] if row["kind"] == "source_metadata")
    asset_name = f"assets/{source_asset['id']}.bin"
    asset_path = folder / asset_name
    original_asset = asset_path.read_bytes()
    for leaked in (
        sample["lease_token"],
        "liveclip-real-browser-test-token",
        "liveclip real browser password 2026",
        "configured-synthetic-token",
        "configured synthetic password",
    ):
        contaminated = _json_bytes({"note": leaked})
        asset_path.write_bytes(contaminated)
        source_asset["sha256"], source_asset["size_bytes"] = (
            _digest(contaminated),
            len(contaminated),
        )
        durable_path.write_bytes(_json_bytes(durable))
        _rehash(folder, asset_name, "durable.json")
        with pytest.raises(ValueError, match="secret/URL"):
            _verified_bundle(sample)
        asset_path.write_bytes(original_asset)
        durable_path.write_bytes(original_durable)
        _rehash(folder, asset_name, "durable.json")
        assert _verified_bundle(sample)["status"] == "PASS"

    durable = json.loads(original_durable)
    srt_asset = next(row for row in durable["assets"] if row["kind"] == "transcript_srt")
    srt_name = f"assets/{srt_asset['id']}.bin"
    srt_path = folder / srt_name
    original_srt = srt_path.read_bytes()
    bad_srt = b"not a timestamped subtitle"
    srt_path.write_bytes(bad_srt)
    srt_asset["sha256"], srt_asset["size_bytes"] = _digest(bad_srt), len(bad_srt)
    durable_path.write_bytes(_json_bytes(durable))
    _rehash(folder, srt_name, "durable.json")
    with pytest.raises(ValueError, match="valid SRT"):
        _verified_bundle(sample)
    srt_path.write_bytes(original_srt)
    durable_path.write_bytes(original_durable)
    _rehash(folder, srt_name, "durable.json")
    assert _verified_bundle(sample)["status"] == "PASS"

    archive_path = folder / "delivery.zip"
    original_archive = archive_path.read_bytes()
    zip_asset = next(
        row for row in durable["assets"] if row["id"] == durable["deliveries"][0]["zip_asset_id"]
    )
    zip_asset_path = folder / f"assets/{zip_asset['id']}.bin"
    original_zip_asset = zip_asset_path.read_bytes()
    marker_path = folder / "download.json"
    original_marker = marker_path.read_bytes()
    manifest_path = folder / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original_archive)) as archive:
        members = {
            name: archive.read(name) for name in archive.namelist() if name != "checksums.sha256"
        }
    videos = [name for name in members if name.endswith(".mp4")]
    subtitles = [name for name in members if name.endswith(".srt")]
    assert len(videos) == len(subtitles) == 1
    replacement_video = _media(sample["repository"] / "replacement.mp4", color="red")
    assert _digest(replacement_video) != _digest(members[videos[0]])
    wrong_delivery = json.loads(members["manifest.json"])
    wrong_delivery["delivery_id"] = "f" * 32
    wrong_clip = json.loads(members["manifest.json"])
    wrong_clip["clips"][0]["clip_id"] = "f" * 32
    wrong_master = json.loads(members["manifest.json"])
    wrong_master["clips"][0]["sha256"] = _digest(replacement_video)
    variants = (
        (
            {key: raw for key, raw in members.items() if key != "index.html"},
            "ZIP exact membership",
            True,
        ),
        (
            {key: raw for key, raw in members.items() if key != "manifest.json"},
            "ZIP exact membership",
            True,
        ),
        (
            {key: raw for key, raw in members.items() if key != videos[0]},
            "ZIP media",
            True,
        ),
        (
            {key: raw for key, raw in members.items() if key != subtitles[0]},
            "ZIP media",
            True,
        ),
        (members, "ZIP exact membership", False),
        ({**members, "notes.md": b"benign supported text"}, "ZIP exact membership", True),
        ({**members, "payload.bin": b"unsupported binary"}, "ZIP exact membership", True),
        (
            {**members, "manifest.json": _json_bytes(wrong_delivery)},
            "ZIP manifest Delivery binding",
            True,
        ),
        (
            {**members, "manifest.json": _json_bytes(wrong_clip)},
            "ZIP manifest selected clip/media binding",
            True,
        ),
        (
            {
                **members,
                videos[0]: replacement_video,
                "manifest.json": _json_bytes(wrong_master),
            },
            "ZIP/selected master bytes",
            True,
        ),
        ({**members, "index.html": b"configured-synthetic-token"}, "secret/URL", True),
        ({**members, "index.html": b"configured synthetic password"}, "secret/URL", True),
        (
            {**members, "index.html": b"https://example.invalid/?X-Amz-Signature=synthetic"},
            "secret/URL",
            True,
        ),
    )
    for mutated_members, message, with_checksums in variants:
        assert _verified_bundle(sample)["status"] == "PASS"
        changed = _package(mutated_members, with_checksums=with_checksums)
        durable = json.loads(original_durable)
        bound_zip = next(
            row
            for row in durable["assets"]
            if row["id"] == durable["deliveries"][0]["zip_asset_id"]
        )
        bound_zip["sha256"], bound_zip["size_bytes"] = _digest(changed), len(changed)
        archive_path.write_bytes(changed)
        zip_asset_path.write_bytes(changed)
        durable_path.write_bytes(_json_bytes(durable))
        marker = json.loads(original_marker)
        marker["sha256"], marker["size_bytes"] = _digest(changed), len(changed)
        marker_path.write_bytes(_json_bytes(marker))
        manifest = json.loads(original_manifest)
        manifest["evidence"]["zip_sha256"] = _digest(changed)
        manifest["evidence"]["browser_download_sha256"] = _digest(changed)
        manifest_path.write_bytes(_json_bytes(manifest))
        _rehash(
            folder,
            "delivery.zip",
            f"assets/{zip_asset['id']}.bin",
            "durable.json",
            "download.json",
        )
        with pytest.raises(ValueError, match=message):
            _verified_bundle(sample)
        archive_path.write_bytes(original_archive)
        zip_asset_path.write_bytes(original_zip_asset)
        durable_path.write_bytes(original_durable)
        marker_path.write_bytes(original_marker)
        manifest_path.write_bytes(original_manifest)
        assert _verified_bundle(sample)["status"] == "PASS"
