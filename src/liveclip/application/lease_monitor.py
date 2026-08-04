from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from liveclip.application.tasks import HeartbeatResult, TaskLease


class LeaseMonitor:
    """Renew a task lease while polling cancellation independently."""

    def __init__(
        self,
        *,
        heartbeat: Callable[..., HeartbeatResult | None],
        observe: Callable[..., HeartbeatResult | None] | None,
        lease: TaskLease,
        heartbeat_seconds: int,
        cancellation_poll_seconds: float = 1.0,
        thread_name: str = "liveclip-lease-monitor",
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat interval must be positive")
        if cancellation_poll_seconds <= 0 or cancellation_poll_seconds > 5:
            raise ValueError("cancellation poll interval must be between zero and five seconds")
        self._heartbeat = heartbeat
        self._observe = observe
        self._lease = lease
        self._heartbeat_seconds = heartbeat_seconds
        self._poll_seconds = cancellation_poll_seconds
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._lost = threading.Event()
        self._last_expiry = lease.lease_expires_at
        self._operation_lock = threading.Lock()
        if lease.cancellation_requested:
            self._cancel.set()
        self._thread = threading.Thread(
            target=self._run,
            name=thread_name,
            daemon=True,
        )

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    @property
    def lost_lease(self) -> bool:
        return self._lost.is_set()

    def should_stop(self) -> bool:
        return self.cancel_requested or self.lost_lease

    def request_cancel(self) -> None:
        self._cancel.set()

    def start(self) -> None:
        self._thread.start()

    def refresh(self) -> None:
        self._invoke(self._heartbeat, extends_lease=True)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._poll_seconds + 1.0))

    def _observe_once(self) -> None:
        if self._observe is not None:
            self._invoke(self._observe, extends_lease=False)

    def _invoke(
        self,
        operation: Callable[..., HeartbeatResult | None],
        *,
        extends_lease: bool,
    ) -> None:
        with self._operation_lock:
            try:
                result = operation(self._lease)
            except Exception:
                if datetime.now(UTC) >= self._last_expiry:
                    self._lost.set()
                return
            if result is None:
                self._lost.set()
                return
            if extends_lease:
                self._last_expiry = result.lease_expires_at
            if result.cancellation_requested:
                self._cancel.set()

    def _run(self) -> None:
        next_heartbeat = time.monotonic() + self._heartbeat_seconds
        while not self._stop.wait(self._poll_seconds):
            if time.monotonic() >= next_heartbeat:
                self.refresh()
                next_heartbeat = time.monotonic() + self._heartbeat_seconds
            else:
                self._observe_once()
            if self.lost_lease:
                return
