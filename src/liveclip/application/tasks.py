from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from liveclip.domain.state_transitions import TaskKind


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
