from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path

from liveclip.application.pipeline import LeaseIdentity
from liveclip.media.fingerprint import stream_sha256


class ArtifactPublicationError(RuntimeError):
    pass


def project_directory(data_dir: Path, project_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise ArtifactPublicationError("persistent project ID is invalid")
    root = data_dir.expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    target = root / project_id
    if target.is_symlink():
        raise ArtifactPublicationError("project directory must not be a symbolic link")
    target.mkdir(mode=0o700, exist_ok=True)
    if target.is_symlink():
        raise ArtifactPublicationError("project directory must not be a symbolic link")
    resolved = target.resolve(strict=True)
    if root not in resolved.parents:
        raise ArtifactPublicationError("project directory escaped the configured data root")
    return resolved


def attempt_directory(project_dir: Path, lease: LeaseIdentity) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", lease.task_id):
        raise ArtifactPublicationError("attempt task ID is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", lease.lease_token):
        raise ArtifactPublicationError("attempt lease token is invalid")
    root = project_dir.resolve(strict=True)
    attempts = root / ".attempts"
    task_root = attempts / lease.task_id
    target = task_root / lease.lease_token
    for candidate in (attempts, task_root, target):
        if candidate.is_symlink():
            raise ArtifactPublicationError("attempt directory must not contain symbolic links")
        candidate.mkdir(mode=0o700, exist_ok=True)
        if candidate.is_symlink():
            raise ArtifactPublicationError("attempt directory must not contain symbolic links")
    resolved = target.resolve(strict=True)
    if root not in resolved.parents:
        raise ArtifactPublicationError("attempt directory escaped its project")
    return resolved


def write_json_no_clobber(path: Path, payload: object) -> str:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    return publish_bytes_no_clobber(path, encoded)


def write_text_no_clobber(path: Path, value: str) -> str:
    return publish_bytes_no_clobber(path, value.encode("utf-8"))


def publish_bytes_no_clobber(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        return publish_file_no_clobber(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def publish_file_no_clobber(source: Path, destination: Path) -> str:
    if source.is_symlink() or not source.is_file() or source.stat().st_size <= 0:
        raise ArtifactPublicationError("artifact source is missing, symbolic, or empty")
    source_hash = stream_sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise ArtifactPublicationError("artifact destination is not a regular file")
        if stream_sha256(destination) != source_hash:
            raise ArtifactPublicationError("artifact destination contains different bytes")
        return source_hash
    try:
        os.link(source, destination)
    except FileExistsError:
        if (
            destination.is_symlink()
            or not destination.is_file()
            or stream_sha256(destination) != source_hash
        ):
            raise ArtifactPublicationError("artifact publication lost a no-clobber race") from None
    except OSError as exc:
        raise ArtifactPublicationError("artifact could not be published atomically") from exc
    with suppress(OSError):
        source.unlink()
    return source_hash
