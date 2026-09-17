"""Add immutable semantic invocation ownership and independent outcome hashes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a13f9c6d2e80"
down_revision: str | Sequence[str] | None = "f3b6d9a2c841"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "semantic_unit_invocations",
        sa.Column("id", sa.String(32), nullable=False),
        sa.Column("project_id", sa.String(32), nullable=False),
        sa.Column("pipeline_run_id", sa.String(32), nullable=False),
        sa.Column("stage_run_id", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("producer_attempt_id", sa.String(32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("semantic_stage", sa.String(40), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("execution_contract", sa.String(40), nullable=False),
        sa.Column("invocation_number", sa.Integer(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("disposition", sa.String(16), nullable=True),
        sa.Column("repair_spent", sa.Boolean(), nullable=True),
        sa.Column("outcome_asset_id", sa.String(32), nullable=True),
        sa.Column("outcome_sha256", sa.String(64), nullable=True),
        sa.Column("outcome_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("outcome_relative_path", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_run_id"], ["stage_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["producer_attempt_id"], ["task_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outcome_asset_id"], ["assets.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "stage_run_id",
            "semantic_stage",
            "subject_id",
            "request_key",
            "invocation_number",
            name="semantic_unit_invocation_number",
        ),
        sa.CheckConstraint("generation > 0", name="semantic_unit_generation_positive"),
        sa.CheckConstraint(
            "invocation_number BETWEEN 1 AND 3", name="semantic_unit_invocation_bound"
        ),
        sa.CheckConstraint(
            "execution_contract = 'semantic-bounded-units-v1'", name="semantic_unit_contract"
        ),
        sa.CheckConstraint(
            "disposition IS NULL OR disposition IN ('succeeded','transient','exhausted','cancelled')",
            name="semantic_unit_disposition",
        ),
        sa.CheckConstraint(
            "disposition != 'transient' OR repair_spent = 0", name="semantic_unit_repair_exhaustion"
        ),
        sa.CheckConstraint(
            "outcome_size_bytes IS NULL OR outcome_size_bytes > 0",
            name="semantic_unit_outcome_size",
        ),
    )
    op.create_index(
        "ix_semantic_unit_history",
        "semantic_unit_invocations",
        ["pipeline_run_id", "semantic_stage", "subject_id", "request_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_unit_history", table_name="semantic_unit_invocations")
    op.drop_table("semantic_unit_invocations")
