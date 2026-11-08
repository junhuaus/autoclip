"""Index audit events by target for share-link access counts.

Stage 19d review P2-5: share-link view/download counts are derived from
``audit_events`` rows filtered by ``(target_type, target_id)``; this composite
index keeps those lookups bounded as the audit log grows.

Revision ID: a7c9e1b3d5f2
Revises: f6a1b3c5d7e9
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a7c9e1b3d5f2"
down_revision: str | Sequence[str] | None = "f6a1b3c5d7e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_audit_events_target", "audit_events", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_target", table_name="audit_events")
