"""Test-only helpers for lease-holding tests that must survive host suspend.

Task leases expire on the shared wall clock (``datetime.now(UTC)``), which is
the only clock all worker processes agree on and which keeps running while the
host sleeps. Heartbeats are paced by ``time.monotonic``, which pauses during
macOS sleep. A suspend longer than the lease therefore correctly lets the task
be recovered (``retry_count + 1``) and executed again; that is production
behavior and is not changed here. Tests that assert exactly-once execution or
``retry_count == 0`` use a lease that outlasts realistic suspends instead of a
30 s operational lease.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import pytest

SUSPEND_TOLERANT_LEASE_SECONDS = 24 * 60 * 60
SIMULATED_SUSPEND = timedelta(hours=12)


class ShiftedWallClock:
    """Advance every LiveClip module's ``datetime.now`` without touching monotonic time."""

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
