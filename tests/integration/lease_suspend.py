"""Test-only helpers for lease-holding tests that must survive host suspend.

Task leases expire on the shared wall clock (``datetime.now(UTC)``), which is
the only clock all worker processes agree on and which keeps running while the
host sleeps. Heartbeats are paced by ``time.monotonic``, which pauses during
macOS sleep. The last renewal sets ``expiry = renewal + lease`` and the next one
is due one heartbeat interval of monotonic time later, so before Stage 6, in the
worst case (the host sleeps just before a due heartbeat), a holder lost its
lease once a suspend exceeded ``lease - heartbeat interval``, not only
``lease``. With the production defaults (120 s lease, 30 s heartbeat) a sleep of
about 90 s or more could cost a retry, and with ``max_stage_retries=3`` repeated
sleeps could fail a stage. Stage 6: ``LeaseMonitor`` now detects a wall-clock
versus monotonic jump and renews immediately while the lease is still
unexpired (see ``test_lease_monitor_suspend.py``). A suspend longer than the
remaining lease still loses it: the fenced heartbeat refuses an expired lease,
and the task is correctly recovered (``retry_count + 1``) and executed again.

Tests that assert exactly-once execution or ``retry_count == 0`` use a lease
that outlasts realistic suspends instead of the 30 s lease these tests
previously used.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import pytest

SUSPEND_TOLERANT_LEASE_SECONDS = 24 * 60 * 60
SIMULATED_SUSPEND = timedelta(hours=12)


class ShiftedWallClock:
    """Advance ``datetime.now`` in every already-imported LiveClip module that binds
    ``datetime``, without touching monotonic time."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.offset = timedelta(0)
        clock = self
        real = datetime

        class ShiftedDatetime(real):
            @classmethod
            def now(cls, tz=None):  # type: ignore[no-untyped-def,override]
                return real.now(tz) + clock.offset

        for name, module in list(sys.modules.items()):
            if (name == "liveclip" or name.startswith("liveclip.")) and getattr(
                module, "datetime", None
            ) is real:
                monkeypatch.setattr(module, "datetime", ShiftedDatetime)

    def suspend(self, duration: timedelta = SIMULATED_SUSPEND) -> None:
        """Jump wall time forward as a host suspend does; monotonic time stays put."""
        self.offset += duration
