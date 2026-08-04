"""add render subtitle asset

Revision ID: f3d2a9b817c4
Revises: c0a0568060fb
Create Date: 2026-08-03 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3d2a9b817c4"
down_revision: str | Sequence[str] | None = "c0a0568060fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Associate revision-fenced subtitle and delivery generation state."""
    with op.batch_alter_table("render_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("spec_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("subtitle_asset_id", sa.String(length=32), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_render_jobs_subtitle_asset_id_assets"),
            "assets",
            ["subtitle_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_unique_constraint(
            batch_op.f("uq_render_jobs_subtitle_asset_id"),
            ["subtitle_asset_id"],
        )
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.add_column(sa.Column("expected_generation", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE deliveries
            SET expected_generation = COALESCE(
                (
                    SELECT pipeline_runs.generation
                    FROM tasks
                    JOIN pipeline_runs ON pipeline_runs.id = tasks.pipeline_run_id
                    WHERE tasks.id = deliveries.task_id
                ),
                (
                    SELECT projects.current_generation
                    FROM projects
                    WHERE projects.id = deliveries.project_id
                )
            )
            """
        )
    )
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.alter_column(
            "expected_generation",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_check_constraint("delivery_generation_positive", "expected_generation > 0")


def downgrade() -> None:
    """Remove revision-fenced subtitle and delivery generation state."""
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.drop_constraint("delivery_generation_positive", type_="check")
        batch_op.drop_column("expected_generation")
    with op.batch_alter_table("render_jobs", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_render_jobs_subtitle_asset_id"), type_="unique")
        batch_op.drop_constraint(
            batch_op.f("fk_render_jobs_subtitle_asset_id_assets"),
            type_="foreignkey",
        )
        batch_op.drop_column("subtitle_asset_id")
        batch_op.drop_column("spec_json")
