from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from liveclip.application.tasks import HeartbeatResult, TaskLease

# Leases expire on the shared wall clock, but heartbeats are paced by
# ``time.monotonic``, which pauses while the host sleeps.  Two wall-clock rules
# make the heartbeat due early; renewal still goes only through the fenced
# heartbeat, so an expired lease is refused and reported lost, never resurrected.
#
# 1. When wall time advances this much more than monotonic time between two
#    polls, the host was suspended (or the clock was stepped forward) and the
#    paced heartbeat may land after expiry, so renew immediately.  A false
#    positive costs one extra heartbeat.
_WALL_CLOCK_JUMP_SECONDS = 1.0
# 2. Renew on every poll once less than this fraction of a heartbeat interval
#    of wall-clock lease remains.  This retries a failed renewal (for example a
#    locked database after many processes wake together) before expiry and
#    covers a suspend the jump rule could not see (before the first poll).
#    Settings require ``lease > 2 * heartbeat``, so a paced heartbeat always
#    finds more than one interval remaining and this never fires in normal
#    operation.
_RENEW_WITHIN_HEARTBEAT_FRACTION = 0.5


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
        # The remaining-lease rule is evaluated on the monitor's own wall clock:
        # the lease length is a difference within the queue's clock, and the
        # renewal start is read here, so an injected queue ``now`` cannot skew it.
        self._lease_seconds = (lease.lease_expires_at - lease.heartbeat_at).total_seconds()
        self._renewed_at = lease.heartbeat_at
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
        # Database operations are bounded by their adapter, but may legitimately
        # outlast the polling interval (for example while SQLite waits for a
        # writer lock).  Cleanup must not race such an in-flight operation.
        self._thread.join()
        if self._thread.is_alive():  # Defensive: join() without a timeout is a barrier.
            raise RuntimeError("lease monitor did not terminate")
        # A caller may have entered refresh() just before the stop signal. Drain
        # that operation too; queued callers will see the signal and do no work.
        # This lock is deliberately acquired only after joining the monitor.
        with self._operation_lock:
            pass

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
            # Coordinate foreground refreshes with stop as well as the monitor
            # thread.  An operation that acquired the lock before stop is
            # allowed to drain; queued operations are discarded.
            if self._stop.is_set():
                return
            started = datetime.now(UTC)
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
                self._renewed_at = started
            if result.cancellation_requested:
                self._cancel.set()

    def _run(self) -> None:
        last_wall = datetime.now(UTC)
        last_monotonic = time.monotonic()
        next_heartbeat = last_monotonic + self._heartbeat_seconds
        while not self._stop.wait(self._poll_seconds):
            wall = datetime.now(UTC)
            monotonic = time.monotonic()
            jump = (wall - last_wall).total_seconds() - (monotonic - last_monotonic)
            last_wall, last_monotonic = wall, monotonic
            remaining = self._lease_seconds - (wall - self._renewed_at).total_seconds()
            if (
                jump > _WALL_CLOCK_JUMP_SECONDS
                or remaining < self._heartbeat_seconds * _RENEW_WITHIN_HEARTBEAT_FRACTION
            ):
                # Renew now rather than one monotonic interval later.
                next_heartbeat = monotonic
            if time.monotonic() >= next_heartbeat:
                self.refresh()
                next_heartbeat = time.monotonic() + self._heartbeat_seconds
            else:
                self._observe_once()
            if self.lost_lease:
                return
