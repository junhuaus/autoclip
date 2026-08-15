"""add professional project lifecycle and management metadata

Revision ID: a84e2d7c9f10
Revises: f42b7c1d9e63
Create Date: 2026-08-13 17:00:00.000000

Existing technical results are conservatively mapped into editorial lifecycle
states. A successful Delivery means ready to publish, not published.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a84e2d7c9f10"
down_revision: str | Sequence[str] | None = "f42b7c1d9e63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "projects" not in existing_tables:
        # A deliberately partial legacy repair fixture can be stamped mid-chain.
        # This migration has no applicable state when the parent table is absent.
        return
    # Use SQLite's additive ALTER TABLE form. Rebuilding this parent table
    # would require dropping it while project_members still references it.
    # Typed domain models and compare-and-swap repositories enforce values.
    op.add_column(
        "projects",
        sa.Column("lifecycle", sa.String(length=32), nullable=False, server_default="processing"),
    )
    op.add_column("projects", sa.Column("lifecycle_before_archive", sa.String(length=32)))
    op.add_column(
        "projects",
        sa.Column("management_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("projects", sa.Column("assignee_user_id", sa.String(length=32)))
    op.add_column(
        "projects",
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
    )
    op.add_column("projects", sa.Column("due_at", sa.DateTime()))
    op.add_column("projects", sa.Column("archived_at", sa.DateTime()))

    op.execute(sa.text("UPDATE projects SET assignee_user_id = owner_id"))
    op.execute(
        sa.text(
            """
            UPDATE projects
            SET lifecycle = CASE
                WHEN EXISTS (
                    SELECT 1 FROM deliveries
                    WHERE deliveries.project_id = projects.id
                      AND deliveries.status = 'succeeded'
                ) THEN 'ready_to_publish'
                WHEN EXISTS (
                    SELECT 1 FROM pipeline_runs
                    WHERE pipeline_runs.id = projects.current_pipeline_run_id
                      AND pipeline_runs.status IN ('failed', 'cancelled')
                ) THEN 'needs_attention'
                WHEN EXISTS (
                    SELECT 1 FROM pipeline_runs
                    WHERE pipeline_runs.id = projects.current_pipeline_run_id
                      AND pipeline_runs.status IN ('queued', 'running')
                ) THEN 'processing'
                WHEN EXISTS (
                    SELECT 1 FROM candidate_clips
                    WHERE candidate_clips.pipeline_run_id = projects.current_pipeline_run_id
                      AND candidate_clips.selected_for_review = 1
                ) THEN 'editorial_review'
                ELSE 'draft'
            END
            """
        )
    )
    op.create_index(op.f("ix_projects_lifecycle"), "projects", ["lifecycle"])
    op.create_index(op.f("ix_projects_assignee_user_id"), "projects", ["assignee_user_id"])
    op.create_index(op.f("ix_projects_due_at"), "projects", ["due_at"])


def downgrade() -> None:
    if "projects" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index(op.f("ix_projects_due_at"), table_name="projects")
    op.drop_index(op.f("ix_projects_assignee_user_id"), table_name="projects")
    op.drop_index(op.f("ix_projects_lifecycle"), table_name="projects")
    op.drop_column("projects", "archived_at")
    op.drop_column("projects", "due_at")
    op.drop_column("projects", "priority")
    op.drop_column("projects", "assignee_user_id")
    op.drop_column("projects", "management_version")
    op.drop_column("projects", "lifecycle_before_archive")
    op.drop_column("projects", "lifecycle")
