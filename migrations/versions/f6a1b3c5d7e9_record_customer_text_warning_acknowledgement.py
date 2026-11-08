"""Record whether an approval explicitly kept customer text with warnings.

Stage 19d (customer-text meta-note guard). Adds the append-only decision
column ``acknowledge_warnings`` (NOT NULL, default false). It is added with a
plain ``ALTER TABLE … ADD COLUMN`` (no table rebuild), so the immutability and
delete-guard triggers on ``dual_profile_clip_decisions`` stay in place.

Revision ID: f6a1b3c5d7e9
Revises: e4b2c7d9a1f3
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a1b3c5d7e9"
down_revision: str | Sequence[str] | None = "e4b2c7d9a1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dual_profile_clip_decisions",
        sa.Column(
            "acknowledge_warnings",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("dual_profile_clip_decisions", "acknowledge_warnings")
