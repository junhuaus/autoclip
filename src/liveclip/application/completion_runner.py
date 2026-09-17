"""One bounded, client-independent processing coordination step."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from liveclip.application.tasks import TaskLease, TaskQueueTransientError

PROCESSING_WAIT_MS = 10_000


class ReconciliationResult(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    DEFERRED = "deferred"
    NEEDS_ACTION = "needs_action"
    PROCESSED = "processed"
    CANCELLED = "cancelled"
    LOST_LEASE = "lost_lease"


class CompletionClaimPort(Protocol):
    def claim_completion(
        self, *, worker_id: str, now: datetime | None = None
    ) -> TaskLease | None: ...


class CompletionReconciliationPort(Protocol):
    def reconcile_completion(
        self, lease: TaskLease, *, now: datetime | None = None
    ) -> ReconciliationResult: ...


class CompletionRunner:
    def __init__(
        self, queue: CompletionClaimPort, repository: CompletionReconciliationPort
    ) -> None:
        self._queue = queue
        self._repository = repository

    def run_once(self, *, worker_id: str, now: datetime | None = None) -> ReconciliationResult:
        try:
            lease = self._queue.claim_completion(worker_id=worker_id, now=now)
        except TaskQueueTransientError:
            return ReconciliationResult.BUSY
        if lease is None:
            return ReconciliationResult.IDLE
        return self._repository.reconcile_completion(lease, now=now)
