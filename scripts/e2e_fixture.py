"""Create and safely remove the isolated real-browser E2E fixture."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import socket
import sqlite3
import stat
import tempfile
import time
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from liveclip.config import Settings
from liveclip.delivery.package import read_zip_member_bounded, validate_zip_infos
from liveclip.media.secure_files import (
    SecureFileMissing,
    open_pinned_regular_file,
    remove_tree_no_follow,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.renderer.quality import full_decode
from liveclip.services.completion_evidence_safety import (
    TEXT_ASSET_KINDS,
    reject_sensitive_text,
    scan_zip_text,
)
from liveclip.services.demo_media import create_demo_source

_ROOT_PATTERN = re.compile(r"liveclip-browser-e2e\.[A-Za-z0-9_-]{6,32}")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_MAX_RETAINED_ZIP_BYTES = 64_000_000
_MAX_RETAINED_ASSET_BYTES = 256_000_000


def _verified_archive_bytes(path: Path) -> tuple[bytes, object]:
    """Validate the same immutable ZIP bytes later retained for independent review."""
    with open_pinned_regular_file(path) as pinned:
        with os.fdopen(os.dup(pinned.descriptor), mode="rb") as stream:
            raw = stream.read(_MAX_RETAINED_ZIP_BYTES + 1)
        pinned.validate_binding()
    if len(raw) > _MAX_RETAINED_ZIP_BYTES:
        raise ValueError("browser E2E ZIP exceeds the retained fixture size limit")
    with zipfile.ZipFile(io.BytesIO(raw), mode="r") as archive:
        validate_zip_infos(archive.infolist())
        if archive.testzip() is not None:
            raise ValueError("browser E2E ZIP is corrupt")
        manifest = json.loads(
            read_zip_member_bounded(archive, "manifest.json", maximum_bytes=2_000_000)
        )
    return raw, manifest


def _retain_browser_packages(evidence: dict[str, object], delivery: bytes, release: bytes) -> str:
    """Publish only verified synthetic ZIPs; a manifest marks a complete retained set."""
    run_id = evidence.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("browser E2E retained run ID is invalid")
    if any(len(raw) > _MAX_RETAINED_ZIP_BYTES for raw in (delivery, release)):
        raise ValueError("browser E2E ZIP exceeds the retained fixture size limit")
    relative = Path("apps/web/playwright-report/browser-packages") / run_id
    directory = os.open(_REPOSITORY_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=directory)
            except FileExistsError:
                if part == run_id:
                    raise ValueError("browser E2E retained run already exists") from None
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        entries = []
        for name, raw in (("delivery.zip", delivery), ("release.zip", release)):
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            entries.append(
                {"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            )
        manifest = {
            "schema_version": "liveclip.browser-evidence.v1",
            "synthetic_mock_asr_llm": True,
            "evidence": evidence,
            "files": entries,
        }
        raw_manifest = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        descriptor = os.open(
            ".manifest.pending",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw_manifest)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(
            ".manifest.pending",
            "manifest.json",
            src_dir_fd=directory,
            dst_dir_fd=directory,
            follow_symlinks=False,
        )
        os.unlink(".manifest.pending", dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(directory)
    return (relative / "manifest.json").as_posix()


def allocated_e2e_root() -> tuple[Path, tuple[int, int]]:
    root = Path(tempfile.mkdtemp(prefix="liveclip-browser-e2e."))
    metadata = os.stat(root, follow_symlinks=False)
    return root.resolve(strict=True), (metadata.st_dev, metadata.st_ino)


def validated_e2e_root(value: str, *, expected_identity: tuple[int, int]) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("browser E2E root must be an absolute normalized path")
    temporary_parent = Path(tempfile.gettempdir()).resolve(strict=True)
    raw_parent = candidate.parent.resolve(strict=True)
    if raw_parent != temporary_parent or not _ROOT_PATTERN.fullmatch(candidate.name):
        raise ValueError("browser E2E root must be a generated direct child of the temp directory")
    metadata = candidate.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or candidate.is_symlink():
        raise ValueError("browser E2E root must be a real directory")
    if (metadata.st_dev, metadata.st_ino) != expected_identity:
        raise ValueError("browser E2E root is not the directory allocated by this run")
    resolved = candidate.resolve(strict=True)
    if resolved.parent != temporary_parent:
        raise ValueError("browser E2E root escaped the temp directory")
    return resolved


def create_fixture(
    root: Path, *, expected_identity: tuple[int, int], scenario: str = "legacy"
) -> Path:
    validated = validated_e2e_root(str(root), expected_identity=expected_identity)
    if any(validated.iterdir()):
        raise ValueError("browser E2E root must be empty before fixture creation")
    if scenario not in {"legacy", "completion", "b2"}:
        raise ValueError("unknown browser E2E scenario")
    source_path = validated / "media" / "browser-source.mp4"
    create_demo_source(
        output_path=source_path,
        duration_ms={"legacy": 16_000, "completion": 32_000, "b2": 64_000}[scenario],
    )
    if scenario == "b2":
        with open_pinned_regular_file(source_path) as pinned:
            (validated / "source-before.json").write_text(json.dumps({"sha256": pinned.sha256()}))
    return source_path.resolve(strict=True)


def cleanup_fixture(root: Path, *, expected_identity: tuple[int, int]) -> bool:
    validated = validated_e2e_root(str(root), expected_identity=expected_identity)
    return remove_tree_no_follow(
        validated,
        required_ancestor=validated.parent,
        expected_identity=expected_identity,
    )


def assert_ports_available(api_port: int, web_port: int) -> None:
    ports = (api_port, web_port)
    if any(port < 1 or port > 65_535 for port in ports) or api_port == web_port:
        raise ValueError("browser E2E ports must be distinct valid TCP ports")
    with ExitStack() as stack:
        for port in ports:
            listener = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            listener.bind(("127.0.0.1", port))


def verify_runtime_config(
    root: Path,
    *,
    api_port: int,
    expected_identity: tuple[int, int],
) -> None:
    validated = validated_e2e_root(str(root), expected_identity=expected_identity)
    settings = Settings()
    expected_data = (validated / "projects").resolve(strict=False)
    expected_media = (validated / "media").resolve(strict=True)
    actual_media = tuple(path.resolve(strict=True) for path in settings.allowed_media_roots)
    if (
        settings.resolved_data_dir() != expected_data
        or actual_media != (expected_media,)
        or settings.ai_provider != "mock"
        or settings.api_host != "127.0.0.1"
        or settings.api_port != api_port
        or (settings.openai_api_key and settings.openai_api_key.get_secret_value())
    ):
        raise ValueError("browser E2E settings escaped their isolated Mock runtime")


def verify_completed_run(
    root: Path,
    *,
    expected_identity: tuple[int, int],
    retain_packages: bool = False,
) -> dict[str, object]:
    validated = validated_e2e_root(str(root), expected_identity=expected_identity)
    database_path = validated / "projects" / "liveclip.sqlite3"
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        projects = connection.execute("SELECT id, lifecycle FROM projects").fetchall()
        if len(projects) != 1:
            raise ValueError("real browser E2E must create exactly one isolated project")
        project_id = str(projects[0]["id"])
        if not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise ValueError("real browser E2E project ID is invalid")
        if str(projects[0]["lifecycle"]) != "published":
            raise ValueError("real browser E2E did not record the Project publication")
        runs = connection.execute(
            "SELECT id, status, progress, config_fingerprint "
            "FROM pipeline_runs WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        if len(runs) != 1 or (runs[0]["status"], runs[0]["progress"]) != ("completed", 100):
            raise ValueError("real browser E2E pipeline did not complete")
        run_id = str(runs[0]["id"])
        stages = connection.execute(
            "SELECT stage, status FROM stage_runs WHERE pipeline_run_id = ? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
        if len(stages) != 6 or {str(row["status"]) for row in stages} != {"succeeded"}:
            raise ValueError("real browser E2E did not succeed all six stages")
        tasks = connection.execute(
            "SELECT id, kind, status FROM tasks ORDER BY created_at, id"
        ).fetchall()
        attempts = connection.execute(
            "SELECT task_id, worker_id, lease_token, outcome FROM task_attempts"
        ).fetchall()
        task_ids = {str(row["id"]) for row in tasks}
        attempt_task_ids = {str(row["task_id"]) for row in attempts}
        lease_tokens = {str(row["lease_token"]) for row in attempts}
        task_kinds = [str(row["kind"]) for row in tasks]
        if (
            len(tasks) != 9
            or task_kinds.count("stage") != 6
            or task_kinds.count("render") != 1
            or task_kinds.count("delivery") != 2
            or {str(row["status"]) for row in tasks} != {"succeeded"}
            or len(attempts) != 9
            or task_ids != attempt_task_ids
            or any(not str(row["worker_id"]).startswith("worker:") for row in attempts)
            or any(str(row["outcome"]) != "succeeded" for row in attempts)
            or len(lease_tokens) != 9
            or any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in lease_tokens)
        ):
            raise ValueError("real browser E2E task lease evidence is incomplete")
        renders = connection.execute(
            "SELECT kind, edit_plan_revision, status FROM render_jobs ORDER BY edit_plan_revision"
        ).fetchall()
        render_evidence = {
            (str(row["kind"]), int(row["edit_plan_revision"]), str(row["status"]))
            for row in renders
        }
        if render_evidence != {("proxy", 1, "stale"), ("proxy", 2, "succeeded")}:
            raise ValueError("real browser E2E render revision evidence is incorrect")
        edit_packages = connection.execute("SELECT id FROM edit_packages").fetchall()
        if edit_packages:
            raise ValueError(
                "selection-first real browser E2E unexpectedly created an edit package"
            )
        deliveries = connection.execute(
            "SELECT id, version, status, directory_relative_path FROM deliveries"
        ).fetchall()
        if len(deliveries) != 1 or (
            int(deliveries[0]["version"]),
            str(deliveries[0]["status"]),
        ) != (1, "succeeded"):
            raise ValueError("real browser E2E delivery did not succeed as v001")
        delivery_id = str(deliveries[0]["id"])
        delivery_clips = connection.execute(
            "SELECT edit_plan_revision FROM delivery_clips WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchall()
        if len(delivery_clips) != 1 or int(delivery_clips[0]["edit_plan_revision"]) != 2:
            raise ValueError("real browser E2E delivery did not snapshot revision 2")
        relative = PurePosixPath(str(deliveries[0]["directory_relative_path"]))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("real browser E2E delivery path is invalid")
        archive_path = validated / "projects" / project_id / Path(*relative.parts) / "delivery.zip"
        delivery_bytes, manifest = _verified_archive_bytes(archive_path)
        clips = manifest.get("clips") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("project_id") != project_id
            or manifest.get("delivery_version") != "v001"
            or not isinstance(clips, list)
            or len(clips) != 1
            or clips[0].get("edit_plan_revision") != 2
        ):
            raise ValueError("real browser E2E ZIP manifest is not the delivered revision")
        release_items = connection.execute(
            """
            SELECT id, platform, caption_mode, approval_status, status, external_id
            FROM release_items
            """
        ).fetchall()
        if len(release_items) != 1 or (
            str(release_items[0]["platform"]),
            str(release_items[0]["caption_mode"]),
            str(release_items[0]["approval_status"]),
            str(release_items[0]["status"]),
            str(release_items[0]["external_id"]),
        ) != ("douyin", "clean_separate", "approved", "published", "douyin-e2e-001"):
            raise ValueError("real browser E2E release item evidence is incomplete")
        release_item_id = str(release_items[0]["id"])
        release_metrics = connection.execute(
            "SELECT views, likes FROM release_metric_snapshots WHERE release_item_id = ?",
            (release_item_id,),
        ).fetchall()
        if len(release_metrics) != 1 or (
            int(release_metrics[0]["views"]),
            int(release_metrics[0]["likes"]),
        ) != (1_200, 88):
            raise ValueError("real browser E2E release metrics are incomplete")
        release_packages = connection.execute(
            """
            SELECT id, version, status, directory_relative_path
            FROM release_packages WHERE release_item_id = ?
            """,
            (release_item_id,),
        ).fetchall()
        if len(release_packages) != 1 or (
            int(release_packages[0]["version"]),
            str(release_packages[0]["status"]),
        ) != (1, "succeeded"):
            raise ValueError("real browser E2E release package did not succeed as v001")
        release_package_id = str(release_packages[0]["id"])
        release_relative = PurePosixPath(str(release_packages[0]["directory_relative_path"]))
        if release_relative.is_absolute() or any(
            part in {"", ".", ".."} for part in release_relative.parts
        ):
            raise ValueError("real browser E2E release package path is invalid")
        release_directory = validated / "projects" / project_id / Path(*release_relative.parts)
        release_archives = tuple(release_directory.glob("*.zip"))
        if len(release_archives) != 1:
            raise ValueError("real browser E2E release package must contain exactly one ZIP")
        release_archive_path = release_archives[0]
        if (
            not release_archive_path.name.startswith("liveclip-release-douyin-")
            or f"-{release_item_id[:8]}-v001.zip" not in release_archive_path.name
        ):
            raise ValueError("real browser E2E release-package ZIP name is not stable and unique")
        release_bytes, release_manifest = _verified_archive_bytes(release_archive_path)
        if (
            not isinstance(release_manifest, dict)
            or release_manifest.get("schema_version") != "liveclip.release-package.v1"
            or release_manifest.get("release_package_id") != release_package_id
            or release_manifest.get("release_item_id") != release_item_id
            or release_manifest.get("project_id") != project_id
            or release_manifest.get("package_version") != "v001"
            or release_manifest.get("platform") != "douyin"
            or release_manifest.get("caption_mode") != "clean_separate"
            or release_manifest.get("edit_plan_revision") != 2
            or not isinstance(release_manifest.get("package_preflight"), dict)
            or release_manifest["package_preflight"].get("passed") is not True
        ):
            raise ValueError("real browser E2E release-package ZIP snapshot is invalid")
        evidence: dict[str, object] = {
            "project_id": project_id,
            "run_id": run_id,
            "stage_count": len(stages),
            "task_count": len(tasks),
            "attempt_count": len(attempts),
            "delivery_id": delivery_id,
            "delivery_version": "v001",
            "release_item_id": release_item_id,
            "release_package_id": release_package_id,
            "release_package_version": "v001",
        }
        if retain_packages:
            evidence["config_fingerprint"] = str(runs[0]["config_fingerprint"])
            with open_pinned_regular_file(validated / "media/browser-source.mp4") as pinned:
                with os.fdopen(os.dup(pinned.descriptor), "rb") as stream:
                    evidence["source_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
                pinned.validate_binding()
            retained = _retain_browser_packages(evidence, delivery_bytes, release_bytes)
            return {**evidence, "retained_manifest": retained}
        return evidence
    finally:
        connection.close()


def _completion_waiting_snapshot(database_path: Path) -> dict[str, object] | None:
    """Read durable waiting/lease evidence without claiming or changing a Task."""
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        intents = connection.execute(
            "SELECT id, project_id, pipeline_run_id, generation, status, "
            "selection_submitted, delivery_id FROM completion_intents"
        ).fetchall()
        if len(intents) != 1:
            return None
        intent = intents[0]
        if (
            intent["status"] != "waiting_selection"
            or intent["selection_submitted"]
            or intent["delivery_id"] is not None
        ):
            return None
        run = connection.execute(
            "SELECT project_id, generation, status, progress FROM pipeline_runs WHERE id = ?",
            (intent["pipeline_run_id"],),
        ).fetchone()
        if (
            run is None
            or run["project_id"] != intent["project_id"]
            or int(run["generation"]) != int(intent["generation"])
            or (run["status"], int(run["progress"])) != ("completed", 100)
        ):
            return None
        stages = connection.execute(
            "SELECT status FROM stage_runs WHERE pipeline_run_id = ?",
            (intent["pipeline_run_id"],),
        ).fetchall()
        if len(stages) != 6 or {row["status"] for row in stages} != {"succeeded"}:
            return None
        tasks = connection.execute(
            "SELECT id, status FROM tasks WHERE kind = 'completion' AND target_id = ?",
            (intent["id"],),
        ).fetchall()
        if len(tasks) != 1 or tasks[0]["status"] != "waiting":
            return None
        deferred = connection.execute(
            "SELECT COUNT(*) FROM task_attempts WHERE task_id = ? AND outcome = 'deferred'",
            (tasks[0]["id"],),
        ).fetchone()[0]
        if deferred < 1:
            return None
        return {
            "schema_version": "liveclip.completion-waiting.v1",
            "project_id": str(intent["project_id"]),
            "run_id": str(intent["pipeline_run_id"]),
            "intent_id": str(intent["id"]),
            "generation": int(intent["generation"]),
            "completion_task_id": str(tasks[0]["id"]),
            "deferred_attempt_count": int(deferred),
            "observed_unix_ms": int(time.time() * 1_000),
        }
    finally:
        connection.close()


def _assert_completion_before_waiting(database_path: Path, closed: dict[str, object]) -> None:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        intents = connection.execute(
            "SELECT id, project_id, pipeline_run_id, generation, status, delivery_id "
            "FROM completion_intents"
        ).fetchall()
        if len(intents) != 1:
            raise ValueError("completion browser closure lacks one durable goal")
        intent = intents[0]
        run = connection.execute(
            "SELECT status FROM pipeline_runs WHERE id = ?", (intent["pipeline_run_id"],)
        ).fetchone()
        if (
            (
                intent["project_id"],
                intent["pipeline_run_id"],
                intent["id"],
                int(intent["generation"]),
            )
            != (closed["project_id"], closed["run_id"], closed["intent_id"], closed["generation"])
            or intent["status"] not in {"queued", "waiting_work"}
            or intent["delivery_id"] is not None
            or run is None
            or run["status"] not in {"queued", "running"}
        ):
            raise ValueError("completion browser was not disconnected before processing finished")
    finally:
        connection.close()


def _is_hex32(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) is not None


def watch_completion_waiting(
    root: Path, *, expected_identity: tuple[int, int]
) -> dict[str, object]:
    """Publish one atomic fixture marker only after independent SQLite evidence."""
    validated = validated_e2e_root(str(root), expected_identity=expected_identity)
    database_path = validated / "projects" / "liveclip.sqlite3"
    logs = validated / "logs"
    if not logs.is_dir() or logs.is_symlink():
        raise ValueError("completion browser log directory is not owned")
    deadline = time.monotonic() + 160
    closed: dict[str, object] | None = None
    while time.monotonic() < deadline:
        if closed is None:
            try:
                observed = _read_completion_fixture_json(logs / "completion-observer-closed.json")
            except (SecureFileMissing, json.JSONDecodeError):
                time.sleep(0.2)
                continue
            if (
                set(observed)
                != {
                    "schema_version",
                    "project_id",
                    "run_id",
                    "intent_id",
                    "generation",
                    "closed_unix_ms",
                }
                or observed["schema_version"] != "liveclip.completion-observer-closed.v1"
                or any(
                    not _is_hex32(observed[field])
                    for field in ("project_id", "run_id", "intent_id")
                )
                or not isinstance(observed["generation"], int)
                or observed["generation"] < 1
                or not isinstance(observed["closed_unix_ms"], int)
            ):
                raise ValueError("completion browser closure marker is invalid")
            _assert_completion_before_waiting(database_path, observed)
            closed = observed
        try:
            snapshot = _completion_waiting_snapshot(database_path)
        except sqlite3.OperationalError:
            snapshot = None
        if snapshot is not None:
            observed_unix_ms = snapshot["observed_unix_ms"]
            closed_unix_ms = closed["closed_unix_ms"]
            if (
                snapshot["project_id"],
                snapshot["run_id"],
                snapshot["intent_id"],
                snapshot["generation"],
            ) != (
                closed["project_id"],
                closed["run_id"],
                closed["intent_id"],
                closed["generation"],
            ) or (
                not isinstance(observed_unix_ms, int)
                or not isinstance(closed_unix_ms, int)
                or observed_unix_ms < closed_unix_ms
            ):
                raise ValueError("completion waiting evidence predates browser disconnection")
            snapshot["observer_closed_unix_ms"] = closed_unix_ms
            raw = (json.dumps(snapshot, sort_keys=True, indent=2) + "\n").encode()
            directory = os.open(logs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                descriptor = os.open(
                    ".completion-waiting.pending",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory,
                )
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(
                    ".completion-waiting.pending",
                    "completion-waiting.json",
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
                os.unlink(".completion-waiting.pending", dir_fd=directory)
                os.fsync(directory)
            finally:
                os.close(directory)
            return snapshot
        time.sleep(0.2)
    raise TimeoutError("completion browser did not persist manual waiting evidence")


def _retain_completion_package(
    evidence: dict[str, object],
    delivery: bytes,
    *,
    project_root: Path,
    assets: list[sqlite3.Row],
    durable: dict[str, object],
    markers: dict[str, tuple[Path, dict[str, object]]],
) -> str:
    """Retain all verified synthetic evidence before fixture cleanup, manifest last."""
    run_id = evidence.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("completion browser retained run ID is invalid")
    if len(delivery) > _MAX_RETAINED_ZIP_BYTES:
        raise ValueError("completion browser ZIP exceeds retained fixture limit")
    if set(markers) not in (
        {"observer-closed.json", "waiting.json", "download.json"},
        {"observer-closed.json", "waiting.json", "download.json", "packaging.json"},
    ):
        raise ValueError("completion browser retained markers are incomplete")
    if len(assets) != evidence.get("asset_count") or not assets:
        raise ValueError("completion browser retained Asset inventory is incomplete")
    folder = "b2-packages" if "packaging.json" in markers else "completion-packages"
    relative = Path("apps/web/playwright-report") / folder / run_id
    if (_REPOSITORY_ROOT / relative).exists():
        raise ValueError("completion browser retained run already exists")
    attempt_rows = durable.get("attempts", [])
    if not isinstance(attempt_rows, list):
        raise ValueError("completion browser retained attempts are invalid")
    lease_hashes = {
        str(row["lease_token_sha256"])
        for row in attempt_rows
        if isinstance(row, dict) and "lease_token_sha256" in row
    }
    durable_bytes = (json.dumps(durable, sort_keys=True, indent=2) + "\n").encode()
    reject_sensitive_text(durable_bytes, lease_token_hashes=lease_hashes)
    for source, _expected in markers.values():
        with open_pinned_regular_file(source) as pinned:
            reject_sensitive_text(
                pinned.read_bytes(max_bytes=8_192), lease_token_hashes=lease_hashes
            )
    with zipfile.ZipFile(io.BytesIO(delivery)) as archive:
        validate_zip_infos(archive.infolist())
        scan_zip_text(archive, lease_token_hashes=lease_hashes)
    for asset in assets:
        if "kind" in asset.keys() and asset["kind"] in (  # noqa: SIM118
            TEXT_ASSET_KINDS | {"semantic_unit_outcome"}
        ):
            relative_asset = PurePosixPath(str(asset["relative_path"]))
            if (
                relative_asset.is_absolute()
                or not relative_asset.parts
                or any(part in {"", ".", ".."} for part in relative_asset.parts)
            ):
                raise ValueError("completion browser retained Asset path is unsafe")
            asset_path = project_root / Path(*relative_asset.parts)
            with open_pinned_regular_file(asset_path) as pinned:
                reject_sensitive_text(
                    pinned.read_bytes(max_bytes=_MAX_RETAINED_ASSET_BYTES),
                    lease_token_hashes=lease_hashes,
                )
    directory = os.open(_REPOSITORY_ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts:
            try:
                os.mkdir(part, mode=0o755, dir_fd=directory)
            except FileExistsError:
                if part == run_id:
                    raise ValueError("completion browser retained run already exists") from None
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        entries: list[dict[str, object]] = []

        def write_bytes(name: str, raw: bytes) -> None:
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            entries.append(
                {
                    "path": name,
                    "size_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )

        write_bytes("delivery.zip", delivery)
        for name in sorted(markers):
            source, expected = markers[name]
            with open_pinned_regular_file(source) as pinned:
                raw = pinned.read_bytes(max_bytes=8_192)
            if json.loads(raw) != expected:
                raise ValueError("completion browser marker changed before retention")
            write_bytes(name, raw)
        if len(durable_bytes) > 2_000_000:
            raise ValueError("completion browser durable evidence exceeds limit")
        write_bytes("durable.json", durable_bytes)

        os.mkdir("assets", mode=0o700, dir_fd=directory)
        asset_directory = os.open(
            "assets", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
        )
        try:
            total_bytes = 0
            for asset in sorted(assets, key=lambda row: str(row["id"])):
                asset_id = str(asset["id"])
                path = PurePosixPath(str(asset["relative_path"]))
                size = asset["size_bytes"]
                if (
                    not re.fullmatch(r"[a-f0-9]{32}", asset_id)
                    or asset["project_id"] != evidence["project_id"]
                    or path.is_absolute()
                    or not path.parts
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or not isinstance(size, int)
                    or size < 0
                    or not re.fullmatch(r"[a-f0-9]{64}", str(asset["sha256"]))
                ):
                    raise ValueError("completion browser retained Asset metadata is unsafe")
                total_bytes += size
                if total_bytes > _MAX_RETAINED_ASSET_BYTES:
                    raise ValueError("completion browser retained Assets exceed limit")
                filename = f"{asset_id}.bin"
                copied = 0
                copied_hash = hashlib.sha256()
                with open_pinned_regular_file(project_root / Path(*path.parts)) as pinned:
                    descriptor = os.open(
                        filename,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=asset_directory,
                    )
                    with (
                        os.fdopen(os.dup(pinned.descriptor), "rb") as source_stream,
                        os.fdopen(descriptor, "wb") as target,
                    ):
                        while chunk := source_stream.read(1_048_576):
                            copied += len(chunk)
                            if copied > size:
                                raise ValueError("completion browser Asset grew during retention")
                            copied_hash.update(chunk)
                            target.write(chunk)
                        target.flush()
                        os.fsync(target.fileno())
                    pinned.validate_binding()
                if copied != size or copied_hash.hexdigest() != asset["sha256"]:
                    raise ValueError("completion browser retained Asset hash differs")
                entries.append(
                    {
                        "path": f"assets/{filename}",
                        "asset_id": asset_id,
                        "size_bytes": copied,
                        "sha256": copied_hash.hexdigest(),
                    }
                )
            os.fsync(asset_directory)
        finally:
            os.close(asset_directory)
        manifest = {
            "schema_version": "liveclip.completion-browser-evidence.v2",
            "synthetic_mock_asr_llm": True,
            "evidence": evidence,
            "asset_count": len(assets),
            "files": entries,
        }
        raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
        descriptor = os.open(
            ".manifest.pending",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(
            ".manifest.pending",
            "manifest.json",
            src_dir_fd=directory,
            dst_dir_fd=directory,
            follow_symlinks=False,
        )
        os.unlink(".manifest.pending", dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(directory)
    return (relative / "manifest.json").as_posix()


def _read_completion_fixture_json(path: Path) -> dict[str, object]:
    with open_pinned_regular_file(path) as pinned:
        raw = pinned.read_bytes(max_bytes=8_192)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("completion browser fixture receipt is not an object")
    return value


def verify_completion_run(
    root: Path,
    *,
    expected_identity: tuple[int, int],
    retain_packages: bool = False,
    scenario: str = "completion",
) -> dict[str, object]:
    """Verify the isolated manual-selection goal without weakening the legacy case."""
    if scenario not in {"completion", "b2"}:
        raise ValueError("unknown completion browser scenario")
    validated = validated_e2e_root(str(root), expected_identity=expected_identity)
    if (validated / "b2-pauses").exists() != (scenario == "b2"):
        raise ValueError("completion browser scenario/fixture mismatch")
    database_path = validated / "projects" / "liveclip.sqlite3"
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        projects = connection.execute(
            "SELECT id, current_generation, revision_epoch FROM projects"
        ).fetchall()
        runs = connection.execute(
            "SELECT id, project_id, generation, status, progress FROM pipeline_runs"
        ).fetchall()
        intents = connection.execute(
            "SELECT id, project_id, pipeline_run_id, generation, status, version, target, "
            "selection_policy, selection_submitted, selection_checkpoint_json, delivery_id, "
            "outcome_code FROM completion_intents"
        ).fetchall()
        if len(projects) != 1 or len(runs) != 1 or len(intents) != 1:
            raise ValueError("completion browser must create exactly one project, run and goal")
        project, run, intent = projects[0], runs[0], intents[0]
        project_id, run_id, intent_id = str(project["id"]), str(run["id"]), str(intent["id"])
        if any(not re.fullmatch(r"[a-f0-9]{32}", item) for item in (project_id, run_id, intent_id)):
            raise ValueError("completion browser identities are invalid")
        if (
            run["project_id"] != project_id
            or intent["project_id"] != project_id
            or intent["pipeline_run_id"] != run_id
            or int(project["current_generation"]) != int(run["generation"])
            or int(intent["generation"]) != int(run["generation"])
            or (run["status"], int(run["progress"])) != ("completed", 100)
            or (
                intent["status"],
                intent["target"],
                intent["selection_policy"],
                intent["outcome_code"],
            )
            != ("succeeded", "delivery", "manual", "delivered")
            or not intent["selection_submitted"]
            or int(intent["version"]) < 3
            or not intent["delivery_id"]
        ):
            raise ValueError("completion browser goal/run state is incomplete")
        stages = connection.execute(
            "SELECT id, pipeline_run_id, ordinal, stage, status FROM stage_runs "
            "WHERE pipeline_run_id = ? ORDER BY ordinal",
            (run_id,),
        ).fetchall()
        if len(stages) != 6 or {row["status"] for row in stages} != {"succeeded"}:
            raise ValueError("completion browser did not finish all six stages")
        checkpoint = json.loads(str(intent["selection_checkpoint_json"]))
        selected = checkpoint.get("selected") if isinstance(checkpoint, dict) else None
        if (
            not isinstance(checkpoint, dict)
            or checkpoint.get("schema_version") != "1"
            or checkpoint.get("intent_id") != intent_id
            or checkpoint.get("run_id") != run_id
            or checkpoint.get("generation") != int(run["generation"])
            or checkpoint.get("mode") != "manual"
            or not isinstance(selected, list)
            or len(selected) != 1
        ):
            raise ValueError("completion browser manual selection checkpoint is invalid")
        tasks = connection.execute(
            "SELECT id, kind, target_id, pipeline_run_id, stage_run_id, "
            "depends_on_task_id, status, retry_count, attempt_count, "
            "manual_retry_count, max_retries, not_before FROM tasks"
        ).fetchall()
        attempts = connection.execute(
            "SELECT id, task_id, attempt_number, worker_id, lease_token, outcome, "
            "started_at, heartbeat_at, lease_expires_at, finished_at FROM task_attempts "
            "ORDER BY task_id, attempt_number"
        ).fetchall()
        kinds = [str(row["kind"]) for row in tasks]
        task_ids = {str(row["id"]) for row in tasks}
        completion_tasks = [row for row in tasks if row["kind"] == "completion"]
        delivery_tasks = [row for row in tasks if row["kind"] == "delivery"]
        if (
            len(tasks) != 8
            or kinds.count("stage") != 6
            or len(completion_tasks) != 1
            or len(delivery_tasks) != 1
            or completion_tasks[0]["target_id"] != intent_id
            or delivery_tasks[0]["target_id"] != intent["delivery_id"]
            or any(row["status"] != "succeeded" or int(row["retry_count"]) != 0 for row in tasks)
            or {str(row["task_id"]) for row in attempts} != task_ids
            or any(not str(row["worker_id"]).startswith("worker:") for row in attempts)
            or len({str(row["lease_token"]) for row in attempts}) != len(attempts)
            or any(not re.fullmatch(r"[a-f0-9]{64}", str(row["lease_token"])) for row in attempts)
            or any(row["outcome"] not in {"succeeded", "deferred"} for row in attempts)
            or any(
                int(task["attempt_count"])
                != sum(attempt["task_id"] == task["id"] for attempt in attempts)
                for task in tasks
            )
            or not any(
                row["task_id"] == completion_tasks[0]["id"] and row["outcome"] == "deferred"
                for row in attempts
            )
            or sum(row["outcome"] == "succeeded" for row in attempts) != 8
        ):
            raise ValueError("completion browser task/lease evidence is incomplete")
        deliveries = connection.execute(
            "SELECT id, project_id, version, status, zip_asset_id, directory_relative_path "
            "FROM deliveries"
        ).fetchall()
        clips = connection.execute(
            "SELECT delivery_id, candidate_clip_id, edit_plan_revision FROM delivery_clips"
        ).fetchall()
        if (
            len(deliveries) != 1
            or len(clips) != 1
            or deliveries[0]["id"] != intent["delivery_id"]
            or deliveries[0]["project_id"] != project_id
            or (int(deliveries[0]["version"]), deliveries[0]["status"]) != (1, "succeeded")
            or not deliveries[0]["zip_asset_id"]
            or clips[0]["delivery_id"] != deliveries[0]["id"]
            or clips[0]["candidate_clip_id"] != selected[0].get("clip_id")
            or int(clips[0]["edit_plan_revision"]) != selected[0].get("edit_plan_revision")
        ):
            raise ValueError("completion browser Delivery is not bound to selection")
        assets = connection.execute(
            "SELECT id, project_id, candidate_clip_id, producer_attempt_id, "
            "generation, edit_plan_revision, revision_epoch, kind, status, relative_path, "
            "sha256, size_bytes FROM assets"
        ).fetchall()
        if not assets or any(row["status"] != "committed" for row in assets):
            raise ValueError("completion browser has uncommitted Assets")
        if (
            (scenario == "completion" and len(assets) != 16)
            or len({row["id"] for row in assets}) != len(assets)
            or any(row["size_bytes"] is None or row["size_bytes"] <= 0 for row in assets)
            or sum(row["size_bytes"] for row in assets) > _MAX_RETAINED_ASSET_BYTES
        ):
            raise ValueError("completion browser Asset inventory is invalid")
        stage_by_id = {str(row["id"]): row for row in stages}
        task_by_id = {str(row["id"]): row for row in tasks}
        attempt_by_id = {str(row["id"]): row for row in attempts}
        expected_stage = {
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
        stage_order = ("ingest", "preprocess", "transcribe", "candidates", "edit", "proxy_render")
        ordered_stages = sorted(stages, key=lambda row: int(row["ordinal"]))
        stage_tasks = [row for row in tasks if row["kind"] == "stage"]
        task_by_stage_id = {str(row["stage_run_id"]): row for row in stage_tasks}
        if (
            len(stage_by_id) != 6
            or len(task_by_id) != 8
            or len(attempt_by_id) != len(attempts)
            or len(task_by_stage_id) != 6
            or set(task_by_stage_id) != set(stage_by_id)
            or tuple(row["ordinal"] for row in ordered_stages) != tuple(range(6))
            or tuple(row["stage"] for row in ordered_stages) != stage_order
            or any(row["pipeline_run_id"] != run_id for row in stages)
            or any(row["pipeline_run_id"] != run_id for row in tasks)
            or any(
                (row["stage_run_id"] not in stage_by_id or row["target_id"] != row["stage_run_id"])
                if row["kind"] == "stage"
                else row["stage_run_id"] is not None
                for row in tasks
            )
            or any(
                task_by_stage_id[str(stage["id"])]["depends_on_task_id"]
                != (
                    None
                    if index == 0
                    else task_by_stage_id[str(ordered_stages[index - 1]["id"])]["id"]
                )
                for index, stage in enumerate(ordered_stages)
            )
            or completion_tasks[0]["depends_on_task_id"] is not None
            or delivery_tasks[0]["depends_on_task_id"] is not None
        ):
            raise ValueError("completion browser stage/Task lineage is incomplete")
        for asset in assets:
            producer = attempt_by_id.get(str(asset["producer_attempt_id"]))
            task = task_by_id.get(str(producer["task_id"])) if producer is not None else None
            if producer is None or task is None or producer["outcome"] != "succeeded":
                raise ValueError("completion browser Asset producer attempt is missing")
            kind = str(asset["kind"])
            if kind in {"delivery_manifest", "delivery_zip"}:
                valid = task["kind"] == "delivery" and task["target_id"] == intent["delivery_id"]
            else:
                stage = stage_by_id.get(str(task["stage_run_id"]))
                valid = (
                    task["kind"] == "stage"
                    and stage is not None
                    and (
                        stage["stage"] == expected_stage.get(kind)
                        or (
                            scenario == "b2"
                            and kind == "semantic_unit_outcome"
                            and stage["stage"] in {"candidates", "edit"}
                        )
                    )
                )
            if not valid:
                raise ValueError("completion browser Asset producer belongs to wrong Task/stage")
            render_kind = kind in {
                "review_proxy",
                "clip_subtitle_srt",
                "render_quality_report",
                "render_contact_sheet",
            }
            if asset["generation"] != run["generation"]:
                raise ValueError("completion browser Asset generation differs")
            if render_kind:
                if (
                    asset["candidate_clip_id"] != selected[0]["clip_id"]
                    or asset["edit_plan_revision"] != selected[0]["edit_plan_revision"]
                    or asset["revision_epoch"] != project["revision_epoch"]
                ):
                    raise ValueError("completion browser render Asset revision/clip differs")
            elif (
                asset["candidate_clip_id"] is not None
                or asset["edit_plan_revision"] is not None
                or (
                    asset["revision_epoch"] != project["revision_epoch"]
                    if kind in {"delivery_manifest", "delivery_zip"}
                    else asset["revision_epoch"] is not None
                )
            ):
                raise ValueError("completion browser nonrender Asset scope differs")
        by_id = {str(row["id"]): row for row in assets}
        zip_asset = by_id.get(str(deliveries[0]["zip_asset_id"]))
        if zip_asset is None or zip_asset["kind"] != "delivery_zip":
            raise ValueError("completion browser Delivery lacks its ZIP Asset")
        decoded_mp4 = decoded_srt = False
        zip_path: Path | None = None
        for asset in assets:
            relative = PurePosixPath(str(asset["relative_path"]))
            if (
                asset["project_id"] != project_id
                or relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or not re.fullmatch(r"[a-f0-9]{64}", str(asset["sha256"]))
            ):
                raise ValueError("completion browser Asset path/hash is invalid")
            path = validated / "projects" / project_id / Path(*relative.parts)
            with open_pinned_regular_file(path) as pinned:
                size_bytes = pinned.metadata.st_size
                digest = pinned.sha256()
                if asset["kind"] in TEXT_ASSET_KINDS | {"semantic_unit_outcome"}:
                    reject_sensitive_text(
                        pinned.read_bytes(max_bytes=_MAX_RETAINED_ASSET_BYTES),
                        lease_token_hashes={
                            hashlib.sha256(str(row["lease_token"]).encode()).hexdigest()
                            for row in attempts
                        },
                    )
            if digest != asset["sha256"] or size_bytes != asset["size_bytes"]:
                raise ValueError("completion browser Asset bytes changed")
            if asset["kind"] == "review_proxy":
                full_decode(path)
                decoded_mp4 = True
            if asset["kind"] == "clip_subtitle_srt":
                if not load_srt_transcript(path).segments:
                    raise ValueError("completion browser SRT has no cues")
                decoded_srt = True
            if asset["id"] == zip_asset["id"]:
                zip_path = path
        if not decoded_mp4 or not decoded_srt or zip_path is None:
            raise ValueError("completion browser MP4/SRT/ZIP Asset is missing")
        delivery_bytes, manifest = _verified_archive_bytes(zip_path)
        manifest_clips = manifest.get("clips") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("project_id") != project_id
            or manifest.get("delivery_id") != intent["delivery_id"]
            or manifest.get("delivery_version") != "v001"
            or not isinstance(manifest_clips, list)
            or len(manifest_clips) != 1
            or manifest_clips[0].get("clip_id") != selected[0].get("clip_id")
            or manifest_clips[0].get("edit_plan_revision") != selected[0].get("edit_plan_revision")
        ):
            raise ValueError("completion browser ZIP manifest differs from bound selection")
        masters = [asset for asset in assets if asset["kind"] == "review_proxy"]
        if len(masters) != 1:
            raise ValueError("completion browser selected master Asset is not unique")
        master = masters[0]
        master_relative = PurePosixPath(str(master["relative_path"]))
        master_path = validated / "projects" / project_id / Path(*master_relative.parts)
        video_name = manifest_clips[0].get("video_filename")
        if not isinstance(video_name, str):
            raise ValueError("completion browser ZIP video filename is invalid")
        with zipfile.ZipFile(io.BytesIO(delivery_bytes)) as archive:
            video_bytes = read_zip_member_bounded(
                archive, video_name, maximum_bytes=_MAX_RETAINED_ASSET_BYTES
            )
        with open_pinned_regular_file(master_path) as pinned:
            with os.fdopen(os.dup(pinned.descriptor), mode="rb") as stream:
                master_bytes = stream.read(_MAX_RETAINED_ASSET_BYTES + 1)
            pinned.validate_binding()
        if (
            master["candidate_clip_id"] != selected[0]["clip_id"]
            or master["edit_plan_revision"] != selected[0]["edit_plan_revision"]
            or len(master_bytes) > _MAX_RETAINED_ASSET_BYTES
            or manifest_clips[0].get("sha256") != master["sha256"]
            or len(video_bytes) != master["size_bytes"]
            or video_bytes != master_bytes
        ):
            raise ValueError("completion browser ZIP video differs from selected master bytes")
        closure = _read_completion_fixture_json(validated / "logs/completion-observer-closed.json")
        if (
            set(closure)
            != {
                "schema_version",
                "project_id",
                "run_id",
                "intent_id",
                "generation",
                "closed_unix_ms",
            }
            or closure["schema_version"] != "liveclip.completion-observer-closed.v1"
            or (
                closure["project_id"],
                closure["run_id"],
                closure["intent_id"],
                closure["generation"],
            )
            != (project_id, run_id, intent_id, int(run["generation"]))
            or not isinstance(closure["closed_unix_ms"], int)
        ):
            raise ValueError("completion browser closure marker differs from durable goal")
        waiting = _read_completion_fixture_json(validated / "logs/completion-waiting.json")
        if (
            set(waiting)
            != {
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
            or waiting["schema_version"] != "liveclip.completion-waiting.v1"
            or (waiting["project_id"], waiting["run_id"], waiting["intent_id"])
            != (project_id, run_id, intent_id)
            or waiting["generation"] != int(run["generation"])
            or waiting["completion_task_id"] != completion_tasks[0]["id"]
            or not isinstance(waiting["deferred_attempt_count"], int)
            or waiting["deferred_attempt_count"] < 1
            or not isinstance(waiting["observed_unix_ms"], int)
            or waiting["observer_closed_unix_ms"] != closure["closed_unix_ms"]
            or waiting["observed_unix_ms"] < closure["closed_unix_ms"]
        ):
            raise ValueError("completion browser waiting marker differs from durable goal")
        download = _read_completion_fixture_json(
            validated / "logs/completion-browser-download.json"
        )
        archive_sha256 = hashlib.sha256(delivery_bytes).hexdigest()
        if (
            set(download)
            != {
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
            or download["schema_version"] != "liveclip.completion-browser-download.v1"
            or (
                download["project_id"],
                download["run_id"],
                download["intent_id"],
                download["delivery_id"],
            )
            != (project_id, run_id, intent_id, intent["delivery_id"])
            or not isinstance(download["observer_closed_unix_ms"], int)
            or download["observer_closed_unix_ms"] != closure["closed_unix_ms"]
            or download["waiting_observed_unix_ms"] != waiting["observed_unix_ms"]
            or download["observer_closed_unix_ms"] > waiting["observed_unix_ms"]
            or download["response_status"] != 200
            or download["content_type"] != "application/zip"
            or download["content_disposition"] != 'attachment; filename="liveclip-v001.zip"'
            or download["size_bytes"] != len(delivery_bytes)
            or download["sha256"] != archive_sha256
            or zip_asset["sha256"] != archive_sha256
        ):
            raise ValueError("completion browser download differs from bound ZIP Asset")
        evidence: dict[str, object] = {
            "project_id": project_id,
            "run_id": run_id,
            "intent_id": intent_id,
            "generation": int(run["generation"]),
            "stage_count": len(stages),
            "task_count": len(tasks),
            "attempt_count": len(attempts),
            "deferred_attempt_count": sum(row["outcome"] == "deferred" for row in attempts),
            "asset_count": len(assets),
            "delivery_id": str(intent["delivery_id"]),
            "delivery_version": "v001",
            "zip_sha256": archive_sha256,
            "browser_download_sha256": str(download["sha256"]),
            "observer_closed_unix_ms": int(download["observer_closed_unix_ms"]),
            "waiting_observed_unix_ms": int(waiting["observed_unix_ms"]),
        }
        if retain_packages:
            quick_check = [row[0] for row in connection.execute("PRAGMA quick_check")]
            foreign_key_violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if quick_check != ["ok"] or foreign_key_violations:
                raise ValueError("completion browser SQLite integrity differs")
            durable: dict[str, object] = {
                "schema_version": "liveclip.completion-durable-audit.v1",
                "synthetic_mock_asr_llm": True,
                "project": dict(project),
                "run": dict(run),
                "intent": {
                    **{
                        key: value
                        for key, value in dict(intent).items()
                        if key != "selection_checkpoint_json"
                    },
                    "selection_checkpoint": checkpoint,
                },
                "stages": [dict(row) for row in stages],
                "tasks": [dict(row) for row in tasks],
                "attempts": [
                    {
                        **{key: value for key, value in dict(row).items() if key != "lease_token"},
                        "lease_token_sha256": hashlib.sha256(
                            str(row["lease_token"]).encode()
                        ).hexdigest(),
                    }
                    for row in attempts
                ],
                "deliveries": [dict(row) for row in deliveries],
                "delivery_clips": [dict(row) for row in clips],
                "assets": [dict(row) for row in assets],
                "sqlite_quick_check": "ok",
                "sqlite_foreign_key_violations": 0,
            }
            logs = validated / "logs"
            extra_markers: dict[str, tuple[Path, dict[str, object]]] = {}
            if (validated / "b2-pauses").exists():
                pauses = validated / "b2-pauses"
                with open_pinned_regular_file(validated / "media/browser-source.mp4") as source:
                    source_hash = source.sha256()
                if _read_completion_fixture_json(validated / "source-before.json") != {
                    "sha256": source_hash
                }:
                    raise ValueError("B2 source bytes changed")
                config = json.loads(
                    connection.execute(
                        "SELECT config_json FROM pipeline_runs WHERE id = ?", (run_id,)
                    ).fetchone()[0]
                )
                final_progress = connection.execute(
                    "SELECT * FROM delivery_progress WHERE delivery_id = ?",
                    (intent["delivery_id"],),
                ).fetchall()
                if len(final_progress) != 1:
                    raise ValueError("B2 requires one persisted Delivery progress attempt")
                packaging: dict[str, object] = {
                    "schema_version": "liveclip.b2-packaging.v1",
                    "source_sha256": source_hash,
                    "config": {
                        key: config[key]
                        for key in (
                            "provider",
                            "clip_profile",
                            "clipping_algorithm",
                            "minimum_clip_ms",
                            "semantic_target_clip_ms",
                            "maximum_clip_ms",
                            "top_n",
                            "semantic_score_threshold",
                            "semantic_full_context_budget_ratio",
                            "semantic_model_context_tokens",
                        )
                    },
                    "pauses": [
                        _read_completion_fixture_json(pauses / f"pause-{n}.json") for n in (1, 2)
                    ],
                    "releases": [
                        _read_completion_fixture_json(pauses / f"released-{n}.json") for n in (1, 2)
                    ],
                    "browser": _read_completion_fixture_json(pauses / "browser.json"),
                    "final_progress": dict(final_progress[0]),
                }
                marker_path = logs / "packaging.json"
                marker_path.write_text(json.dumps(packaging, sort_keys=True))
                extra_markers["packaging.json"] = (marker_path, packaging)
            evidence["retained_manifest"] = _retain_completion_package(
                evidence,
                delivery_bytes,
                project_root=validated / "projects" / project_id,
                assets=assets,
                durable=durable,
                markers={
                    **extra_markers,
                    "observer-closed.json": (
                        logs / "completion-observer-closed.json",
                        closure,
                    ),
                    "waiting.json": (logs / "completion-waiting.json", waiting),
                    "download.json": (logs / "completion-browser-download.json", download),
                },
            )
        return evidence
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("allocate")
    for name in ("create", "cleanup", "verify-config", "verify", "watch-completion"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--expected-device", type=int, required=True)
        command.add_argument("--expected-inode", type=int, required=True)
        if name == "verify-config":
            command.add_argument("--api-port", type=int, required=True)
        if name == "verify":
            command.add_argument("--retain-packages", action="store_true")
        if name in {"create", "verify"}:
            command.add_argument(
                "--scenario", choices=("legacy", "completion", "b2"), default="legacy"
            )
    ports = subparsers.add_parser("check-ports")
    ports.add_argument("--api-port", type=int, required=True)
    ports.add_argument("--web-port", type=int, required=True)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    if arguments.command == "allocate":
        root, identity = allocated_e2e_root()
        print(f"{root}\t{identity[0]}\t{identity[1]}")
        return 0
    if arguments.command == "check-ports":
        assert_ports_available(arguments.api_port, arguments.web_port)
        print("ports available")
        return 0
    identity = (arguments.expected_device, arguments.expected_inode)
    if arguments.command == "create":
        print(
            create_fixture(arguments.root, expected_identity=identity, scenario=arguments.scenario)
        )
    elif arguments.command == "watch-completion":
        print(json.dumps(watch_completion_waiting(arguments.root, expected_identity=identity)))
    elif arguments.command == "cleanup":
        removed = cleanup_fixture(arguments.root, expected_identity=identity)
        print("removed" if removed else "already absent")
    elif arguments.command == "verify-config":
        verify_runtime_config(
            arguments.root,
            api_port=arguments.api_port,
            expected_identity=identity,
        )
        print("isolated Mock settings verified")
    else:
        print(
            json.dumps(
                (
                    verify_completion_run
                    if arguments.scenario in {"completion", "b2"}
                    else verify_completed_run
                )(
                    arguments.root,
                    expected_identity=identity,
                    retain_packages=arguments.retain_packages,
                    **(
                        {"scenario": arguments.scenario}
                        if arguments.scenario in {"completion", "b2"}
                        else {}
                    ),
                ),
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
