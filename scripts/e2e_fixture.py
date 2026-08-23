"""Create and safely remove the isolated real-browser E2E fixture."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
import stat
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from liveclip.config import Settings
from liveclip.delivery.package import read_zip_member_bounded, validate_zip_infos
from liveclip.media.secure_files import open_pinned_regular_file, remove_tree_no_follow
from liveclip.services.demo_media import create_demo_source

_ROOT_PATTERN = re.compile(r"liveclip-browser-e2e\.[A-Za-z0-9_-]{6,32}")


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


def create_fixture(root: Path, *, expected_identity: tuple[int, int]) -> Path:
    validated = validated_e2e_root(str(root), expected_identity=expected_identity)
    if any(validated.iterdir()):
        raise ValueError("browser E2E root must be empty before fixture creation")
    source_path = validated / "media" / "browser-source.mp4"
    create_demo_source(output_path=source_path, duration_ms=16_000)
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
            "SELECT id, status, progress FROM pipeline_runs WHERE project_id = ?",
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
        with open_pinned_regular_file(archive_path) as pinned:
            with (
                os.fdopen(os.dup(pinned.descriptor), mode="rb") as stream,
                zipfile.ZipFile(stream, mode="r") as archive,
            ):
                validate_zip_infos(archive.infolist())
                if archive.testzip() is not None:
                    raise ValueError("real browser E2E delivery ZIP is corrupt")
                manifest = json.loads(
                    read_zip_member_bounded(archive, "manifest.json", maximum_bytes=2_000_000)
                )
            pinned.validate_binding()
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
        with open_pinned_regular_file(release_archive_path) as pinned:
            with (
                os.fdopen(os.dup(pinned.descriptor), mode="rb") as stream,
                zipfile.ZipFile(stream, mode="r") as archive,
            ):
                validate_zip_infos(archive.infolist())
                if archive.testzip() is not None:
                    raise ValueError("real browser E2E release-package ZIP is corrupt")
                release_manifest = json.loads(
                    read_zip_member_bounded(
                        archive,
                        "manifest.json",
                        maximum_bytes=2_000_000,
                    )
                )
            pinned.validate_binding()
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
        return {
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
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("allocate")
    for name in ("create", "cleanup", "verify-config", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--expected-device", type=int, required=True)
        command.add_argument("--expected-inode", type=int, required=True)
        if name == "verify-config":
            command.add_argument("--api-port", type=int, required=True)
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
        print(create_fixture(arguments.root, expected_identity=identity))
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
                verify_completed_run(arguments.root, expected_identity=identity),
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
