from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Protocol

from liveclip.domain.state_transitions import TaskKind


class TaskQueueTransientError(RuntimeError):
    """A queue operation could not acquire SQLite briefly and may be polled again."""


def validate_task_diagnostic_relative_path(value: str | None) -> str | None:
    """Validate one project-relative, attempt-owned diagnostic artifact path."""

    if value is None:
        return None
    if not value or len(value) > 500 or "\\" in value:
        raise ValueError("task diagnostic path is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValueError("task diagnostic path contains control characters")
    path = PurePosixPath(value)
    if path.is_absolute() or path.as_posix() != value:
        raise ValueError("task diagnostic path must be normalized and relative")
    if len(path.parts) < 5 or path.parts[0] != ".attempts":
        raise ValueError("task diagnostic path must belong to an attempt")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("task diagnostic path escapes its attempt")
    return value


@dataclass(frozen=True, slots=True)
class TaskLease:
    task_id: str
    kind: TaskKind
    target_id: str
    worker_id: str
    lease_token: str
    heartbeat_at: datetime
    lease_expires_at: datetime
    attempt_number: int
    cancellation_requested: bool


@dataclass(frozen=True, slots=True)
class HeartbeatResult:
    lease_expires_at: datetime
    cancellation_requested: bool


class TaskQueuePort(Protocol):
    def claim(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        pipeline_run_id: str | None = None,
        task_kind: TaskKind | None = None,
    ) -> TaskLease | None: ...

    def heartbeat(
        self,
        lease: TaskLease,
        *,
        now: datetime | None = None,
    ) -> HeartbeatResult | None: ...

    def observe(
        self,
        lease: TaskLease,
        *,
        now: datetime | None = None,
    ) -> HeartbeatResult | None: ...
