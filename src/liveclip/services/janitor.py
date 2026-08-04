from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine

from liveclip.db.models import PipelineRunRow, TaskAttemptRow, TaskRow
from liveclip.domain.state_transitions import AttemptOutcome
from liveclip.media.artifacts import ArtifactPublicationError, cleanup_attempt_worktree


@dataclass(frozen=True, slots=True)
class AttemptCleanupReport:
    inspected: int
    cleaned: int
    failed: int


def cleanup_terminal_attempt_worktrees(
    engine: Engine,
    *,
    data_dir: Path,
) -> AttemptCleanupReport:
    """Remove terminal attempt worktrees while retaining referenced diagnostics."""

    with engine.connect() as connection:
        rows = connection.execute(
            select(
                PipelineRunRow.project_id,
                TaskAttemptRow.task_id,
                TaskAttemptRow.lease_token,
                TaskAttemptRow.diagnostic_relative_path,
            )
            .join(TaskRow, TaskRow.id == TaskAttemptRow.task_id)
            .join(PipelineRunRow, PipelineRunRow.id == TaskRow.pipeline_run_id)
            .where(TaskAttemptRow.outcome != AttemptOutcome.RUNNING.value)
        ).all()
    cleaned = 0
    failed = 0
    for row in rows:
        try:
            changed = cleanup_attempt_worktree(
                data_dir / str(row.project_id),
                task_id=str(row.task_id),
                lease_token=str(row.lease_token),
                preserve_diagnostics=row.diagnostic_relative_path is not None,
            )
        except ArtifactPublicationError:
            failed += 1
        else:
            cleaned += int(changed)
    return AttemptCleanupReport(inspected=len(rows), cleaned=cleaned, failed=failed)
