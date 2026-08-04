from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from liveclip.application.pipeline import LeaseIdentity
from liveclip.domain.state_transitions import AssetStatus


class AssetReservationError(RuntimeError):
    """A caller-safe artifact reservation or publication conflict."""


@dataclass(frozen=True, slots=True)
class AssetReservation:
    asset_id: str
    status: AssetStatus
    relative_path: str
    sha256: str | None
    size_bytes: int | None


class AssetStore(Protocol):
    def reserve(
        self,
        lease: LeaseIdentity,
        *,
        project_id: str,
        kind: str,
        relative_path: str,
        mime_type: str,
        input_fingerprint: str,
        generation: int | None = None,
        candidate_id: str | None = None,
        edit_plan_revision: int | None = None,
        revision_epoch: int | None = None,
    ) -> AssetReservation: ...

    def commit(
        self,
        lease: LeaseIdentity,
        reservation: AssetReservation,
        *,
        project_dir: Path,
        validation: dict[str, object],
        expected_sha256: str | None = None,
    ) -> AssetReservation: ...
