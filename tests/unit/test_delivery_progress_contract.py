"""The public progress value rejects fabricated or ambiguous counts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from liveclip.application.delivery_progress import (
    DeliveryProgressEvent,
    DeliveryProgressPhase,
    DeliveryProgressSnapshot,
    DeliveryProgressUnit,
)


def test_copy_hash_counter_has_exact_unit_and_optional_total() -> None:
    event = DeliveryProgressEvent(
        phase=DeliveryProgressPhase.COPYING_HASHING,
        unit=DeliveryProgressUnit.BYTES,
        completed=4096,
        total=None,
    )
    assert event.model_dump(mode="json") == {
        "phase": "copying_hashing",
        "unit": "bytes",
        "completed": 4096,
        "total": None,
    }
    with pytest.raises(ValidationError):
        DeliveryProgressEvent(
            phase=DeliveryProgressPhase.COPYING_HASHING,
            unit=DeliveryProgressUnit.FILES,
            completed=1,
            total=2,
        )
    with pytest.raises(ValidationError):
        DeliveryProgressEvent(
            phase=DeliveryProgressPhase.WRITING_ZIP,
            unit=DeliveryProgressUnit.BYTES,
            completed=3,
            total=2,
        )


def test_snapshot_separates_live_lease_from_business_advance() -> None:
    now = datetime(2026, 9, 14, tzinfo=UTC)
    snapshot = DeliveryProgressSnapshot(
        phase=DeliveryProgressPhase.WRITING_ZIP,
        unit=DeliveryProgressUnit.BYTES,
        completed=7,
        total=11,
        attempt_id="a" * 32,
        business_advanced_at=None,
        worker_heartbeat_at=now,
        lease_fresh=True,
    )
    assert snapshot.business_advanced_at is None
    assert snapshot.worker_heartbeat_at == now
    assert snapshot.model_dump(mode="json")["schema_version"] == "1"
    with pytest.raises(ValidationError):
        DeliveryProgressSnapshot(
            phase=DeliveryProgressPhase.QUEUED,
            unit=DeliveryProgressUnit.BYTES,
            completed=7,
            total=11,
            attempt_id=None,
            business_advanced_at=None,
            worker_heartbeat_at=None,
            lease_fresh=False,
        )
