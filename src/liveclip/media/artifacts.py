from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from liveclip.application.pipeline import LeaseIdentity
from liveclip.media.secure_files import (
    SecureFileError,
    ensure_directory_no_follow,
    publish_regular_file_immutable_no_follow,
    remove_tree_no_follow,
    require_directory_no_follow,
    write_bytes_immutable_no_follow,
)


class ArtifactPublicationError(RuntimeError):
    pass


def project_directory(data_dir: Path, project_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", project_id):
        raise ArtifactPublicationError("persistent project ID is invalid")
    try:
        root = ensure_directory_no_follow(data_dir.expanduser())
        target = ensure_directory_no_follow(root / project_id)
    except SecureFileError as exc:
        raise ArtifactPublicationError("project directory must not contain symbolic links") from exc
    if root not in target.parents:
        raise ArtifactPublicationError("project directory escaped the configured data root")
    return target


def attempt_directory(project_dir: Path, lease: LeaseIdentity) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", lease.task_id):
        raise ArtifactPublicationError("attempt task ID is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", lease.lease_token):
        raise ArtifactPublicationError("attempt lease token is invalid")
    try:
        root = require_directory_no_follow(project_dir)
        target = ensure_directory_no_follow(root / ".attempts" / lease.task_id / lease.lease_token)
    except SecureFileError as exc:
        raise ArtifactPublicationError("attempt directory must not contain symbolic links") from exc
    if root not in target.parents:
        raise ArtifactPublicationError("attempt directory escaped its project")
    return target


def write_json_no_clobber(
    path: Path,
    payload: object,
    *,
    max_bytes: int = 8 * 1024 * 1024,
) -> str:
    if max_bytes <= 0:
        raise ValueError("JSON artifact size limit must be positive")
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )
    if len(encoded) > max_bytes:
        raise ArtifactPublicationError("JSON artifact exceeds its safe size limit")
    return publish_bytes_no_clobber(path, encoded)


def write_text_no_clobber(path: Path, value: str) -> str:
    return publish_bytes_no_clobber(path, value.encode("utf-8"))


def publish_bytes_no_clobber(path: Path, value: bytes) -> str:
    if not value:
        raise ArtifactPublicationError("artifact source must not be empty")
    try:
        write_bytes_immutable_no_follow(path, value, max_bytes=len(value))
    except SecureFileError as exc:
        raise ArtifactPublicationError(
            "artifact bytes could not be published without clobbering"
        ) from exc
    return hashlib.sha256(value).hexdigest()


def publish_file_no_clobber(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str | None = None,
) -> str:
    try:
        return publish_regular_file_immutable_no_follow(
            source,
            destination,
            expected_sha256=expected_sha256,
        )
    except SecureFileError as exc:
        raise ArtifactPublicationError(
            "artifact file could not be published without clobbering"
        ) from exc


def cleanup_attempt_worktree(
    project_dir: Path,
    *,
    task_id: str,
    lease_token: str,
    preserve_diagnostics: bool,
) -> bool:
    if not re.fullmatch(r"[a-f0-9]{32}", task_id):
        raise ArtifactPublicationError("cleanup task ID is invalid")
    if not re.fullmatch(r"[a-f0-9]{64}", lease_token):
        raise ArtifactPublicationError("cleanup lease token is invalid")
    attempt_root = project_dir / ".attempts"
    target = attempt_root / task_id / lease_token
    try:
        if not preserve_diagnostics:
            return remove_tree_no_follow(target, required_ancestor=attempt_root)
        removed = False
        for worktree in ("runs", "transcript", "delivery"):
            removed = remove_tree_no_follow(target / worktree, required_ancestor=target) or removed
        return removed
    except SecureFileError as exc:
        raise ArtifactPublicationError("attempt cleanup could not be performed safely") from exc
