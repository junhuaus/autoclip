"""add user-owned saved project views

Revision ID: f3b6d9a2c841
Revises: e92b7c4d1a60
Create Date: 2026-08-16 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b6d9a2c841"
down_revision: str | Sequence[str] | None = "e92b7c4d1a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_project_views",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("name_key", sa.String(length=160), nullable=False),
        sa.Column("criteria_schema_version", sa.String(length=8), nullable=False),
        sa.Column("criteria_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_saved_project_views_saved_project_view_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["workspace_users.id"],
            name=op.f("fk_saved_project_views_user_id_workspace_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_project_views")),
        sa.UniqueConstraint(
            "user_id",
            "name_key",
            name="saved_project_view_user_name",
        ),
    )
    op.create_index(
        "ix_saved_project_views_user_id",
        "saved_project_views",
        ["user_id"],
    )
    op.create_index(
        "ix_saved_project_views_user_updated",
        "saved_project_views",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("saved_project_views")
