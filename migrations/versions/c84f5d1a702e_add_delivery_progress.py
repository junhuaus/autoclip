"""Persist real phase-local Delivery work per fenced Task attempt.

Revision ID: c84f5d1a702e
Revises: b71d4c9a20e5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c84f5d1a702e"
down_revision = "b71d4c9a20e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_progress",
        sa.Column("delivery_id", sa.String(length=32), nullable=False),
        sa.Column("task_attempt_id", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=8), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("expected_generation", sa.Integer(), nullable=False),
        sa.Column("expected_revision_epoch", sa.BigInteger(), nullable=False),
        sa.Column("package_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("completed", sa.BigInteger(), nullable=False),
        sa.Column("total", sa.BigInteger()),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("business_advanced_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("delivery_id", "task_attempt_id"),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_attempt_id"], ["task_attempts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("task_attempt_id"),
        sa.CheckConstraint("schema_version = '1'", name="delivery_progress_schema_v1"),
        sa.CheckConstraint("attempt_number > 0", name="delivery_progress_attempt_positive"),
        sa.CheckConstraint("expected_generation > 0", name="delivery_progress_generation_positive"),
        sa.CheckConstraint(
            "expected_revision_epoch >= 0", name="delivery_progress_epoch_nonnegative"
        ),
        sa.CheckConstraint(
            "length(package_fingerprint) = 64", name="delivery_progress_fingerprint_shape"
        ),
        sa.CheckConstraint("completed >= 0", name="delivery_progress_completed_nonnegative"),
        sa.CheckConstraint(
            "total IS NULL OR total >= completed", name="delivery_progress_total_bound"
        ),
        sa.CheckConstraint(
            "(phase = 'copying_hashing' AND unit = 'bytes') OR "
            "(phase = 'writing_metadata' AND unit = 'files') OR "
            "(phase = 'writing_zip' AND unit = 'bytes') OR "
            "(phase = 'verifying_package' AND unit = 'members') OR "
            "(phase = 'committing_assets' AND unit = 'assets')",
            name="delivery_progress_phase_unit",
        ),
    )


def downgrade() -> None:
    op.drop_table("delivery_progress")
