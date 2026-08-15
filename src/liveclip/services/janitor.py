from __future__ import annotations

import fcntl
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine

from liveclip.db.engine import begin_immediate
from liveclip.db.models import (
    PipelineRunRow,
    ProjectRow,
    SourceMediaRow,
    TaskAttemptRow,
    TaskRow,
)
from liveclip.domain.state_transitions import AttemptOutcome
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    cleanup_tree_identity_no_follow,
    directory_identity_no_follow,
    ensure_directory_no_follow,
    interrupted_tree_cleanup_path,
    open_pinned_regular_file,
    publish_directory_no_replace_no_follow,
    remove_directory_children_except_no_follow,
    remove_tree_no_follow,
    write_bytes_immutable_no_follow,
)


@dataclass(frozen=True, slots=True)
class AttemptCleanupReport:
    inspected: int
    cleaned: int
    failed: int


def cleanup_terminal_attempt_worktrees(
    engine: Engine,
    *,
    data_dir: Path,
    authorize: Callable[[Connection], None] | None = None,
) -> AttemptCleanupReport:
    """Remove terminal attempt worktrees while retaining referenced diagnostics."""

    quarantine_root = ensure_directory_no_follow(data_dir / ".attempt-cleanup-quarantine")
    lock_path = quarantine_root / ".janitor.lock"
    write_bytes_immutable_no_follow(
        lock_path,
        b"LiveClip attempt janitor lock\n",
        max_bytes=64,
    )
    with open_pinned_regular_file(lock_path) as janitor_lock:
        fcntl.flock(janitor_lock.descriptor, fcntl.LOCK_EX)
        try:
            return _cleanup_terminal_attempt_worktrees_locked(
                engine,
                data_dir=data_dir,
                quarantine_root=quarantine_root,
                authorize=authorize,
            )
        finally:
            fcntl.flock(janitor_lock.descriptor, fcntl.LOCK_UN)


def _cleanup_terminal_attempt_worktrees_locked(
    engine: Engine,
    *,
    data_dir: Path,
    quarantine_root: Path,
    authorize: Callable[[Connection], None] | None,
) -> AttemptCleanupReport:
    with engine.connect() as connection:
        if authorize is not None:
            authorize(connection)
        rows = connection.execute(
            select(TaskAttemptRow.id)
            .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
            .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
            .where(TaskAttemptRow.outcome != AttemptOutcome.RUNNING.value)
        ).all()
    cleaned = 0
    failed = 0
    for row in rows:
        quarantine = quarantine_root / str(row.id)
        original: Path | None = None
        original_cleanup_root: Path | None = None
        identity: tuple[int, int] | None = None
        preserve_diagnostics = False
        claimed = False
        cleanup_interrupted_at_original = False
        try:
            # The writer lock covers only the final authorization/reference
            # fence and one O(1) inode-bound rename. Recursive deletion happens
            # after this transaction commits, so worker heartbeats stay live.
            with begin_immediate(engine) as connection:
                if authorize is not None:
                    authorize(connection)
                current = connection.execute(
                    select(
                        PipelineRunRow.project_id,
                        TaskAttemptRow.task_id,
                        TaskAttemptRow.lease_token,
                        TaskAttemptRow.diagnostic_relative_path,
                        TaskAttemptRow.temp_identity,
                    )
                    .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
                    .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
                    .where(
                        TaskAttemptRow.id == row.id,
                        TaskAttemptRow.outcome != AttemptOutcome.RUNNING.value,
                    )
                ).one_or_none()
                if current is None:
                    failed += 1
                    continue
                identity = _parse_attempt_identity(current.temp_identity)
                if identity is None:
                    failed += 1
                    continue
                original = (
                    data_dir
                    / str(current.project_id)
                    / ".attempts"
                    / str(current.task_id)
                    / str(current.lease_token)
                )
                original_cleanup_root = data_dir / str(current.project_id) / ".attempts"
                if any(
                    _source_within_cleanup_target(source, target)
                    for source in _source_references(connection)
                    for target in (
                        original,
                        interrupted_tree_cleanup_path(original),
                        quarantine,
                        interrupted_tree_cleanup_path(quarantine),
                    )
                ):
                    failed += 1
                    continue
                original_exact_identity = _optional_directory_identity(original)
                original_identity = cleanup_tree_identity_no_follow(original)
                quarantine_identity = cleanup_tree_identity_no_follow(quarantine)
                if original_identity is not None and quarantine_identity is not None:
                    raise SecureFileError("attempt cleanup has two competing endpoints")
                if original_identity is not None:
                    if original_identity != identity:
                        raise SecureFileError("attempt directory differs from recorded identity")
                    if original_exact_identity is None:
                        if preserve_diagnostics:
                            raise SecureFileError(
                                "diagnostic-preserving cleanup has an unexpected tree quarantine"
                            )
                        cleanup_interrupted_at_original = True
                    else:
                        publish_directory_no_replace_no_follow(
                            original,
                            quarantine,
                            expected_identity=identity,
                        )
                    claimed = True
                elif quarantine_identity is not None:
                    if quarantine_identity != identity:
                        raise SecureFileError("attempt quarantine differs from recorded identity")
                    claimed = True
                preserve_diagnostics = current.diagnostic_relative_path is not None
            if not claimed or original is None or original_cleanup_root is None or identity is None:
                continue
            if preserve_diagnostics:
                changed = remove_directory_children_except_no_follow(
                    quarantine,
                    preserve_names=frozenset({"diagnostics"}),
                    expected_identity=identity,
                )
                publish_directory_no_replace_no_follow(
                    quarantine,
                    original,
                    expected_identity=identity,
                )
            else:
                cleanup_target = original if cleanup_interrupted_at_original else quarantine
                cleanup_root = (
                    original_cleanup_root if cleanup_interrupted_at_original else quarantine_root
                )
                changed = remove_tree_no_follow(
                    cleanup_target,
                    required_ancestor=cleanup_root,
                    expected_identity=identity,
                )
        except SecureFileError:
            failed += 1
        else:
            cleaned += int(changed)
    return AttemptCleanupReport(inspected=len(rows), cleaned=cleaned, failed=failed)


def _optional_directory_identity(path: Path) -> tuple[int, int] | None:
    try:
        return directory_identity_no_follow(path)
    except SecureFileMissing:
        return None


def _source_references(connection: Connection) -> tuple[Path, ...]:
    rows = connection.execute(
        select(
            ProjectRow.source_request_path,
            SourceMediaRow.resolved_path,
        ).outerjoin(SourceMediaRow, SourceMediaRow.project_id == ProjectRow.id)
    ).all()
    return tuple(
        Path(str(value))
        for row in rows
        for value in (row.source_request_path, row.resolved_path)
        if value is not None
    )


def _parse_attempt_identity(value: str | None) -> tuple[int, int] | None:
    if value is None:
        return None
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    device, inode = (int(part) for part in parts)
    if device < 0 or inode <= 0:
        return None
    return device, inode


def _source_within_cleanup_target(source: Path, cleanup_target: Path) -> bool:
    """Fail closed when a project source may be inside automatic cleanup scope."""

    try:
        source_real = source.expanduser().resolve(strict=False)
        target_real = cleanup_target.resolve(strict=False)
        source_real.relative_to(target_real)
    except ValueError:
        return False
    except (OSError, RuntimeError):
        return True
    return True
