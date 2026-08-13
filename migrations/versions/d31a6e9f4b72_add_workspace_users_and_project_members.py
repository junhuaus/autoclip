"""add workspace users and project memberships

Revision ID: d31a6e9f4b72
Revises: c91f4e2a7b63
Create Date: 2026-08-13 09:00:00.000000

Existing local projects are assigned to one default local administrator. This
keeps upgrades deterministic while establishing the ownership boundary needed
for per-user project visibility.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "d31a6e9f4b72"
down_revision: str | Sequence[str] | None = "c91f4e2a7b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCAL_ADMIN_ID = "00000000000000000000000000000001"


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    op.create_table(
        "workspace_users",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_users")),
        sa.UniqueConstraint("username", name=op.f("uq_workspace_users_username")),
    )
    now = datetime.now(UTC)
    users = sa.table(
        "workspace_users",
        sa.column("id", sa.String),
        sa.column("username", sa.String),
        sa.column("display_name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        users,
        [
            {
                "id": _LOCAL_ADMIN_ID,
                "username": "local-admin",
                "display_name": "本机管理员",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    if "projects" in existing_tables:
        op.add_column(
            "projects",
            sa.Column(
                "owner_id",
                sa.String(length=32),
                nullable=False,
                server_default=_LOCAL_ADMIN_ID,
            ),
        )
        op.create_index(op.f("ix_projects_owner_id"), "projects", ["owner_id"], unique=False)
        op.execute(
            sa.text("UPDATE projects SET owner_id = :owner_id WHERE owner_id IS NULL").bindparams(
                owner_id=_LOCAL_ADMIN_ID
            )
        )
    op.create_table(
        "project_members",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'editor', 'reviewer')",
            name=op.f("ck_project_members_project_member_role_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_members_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["workspace_users.id"],
            name=op.f("fk_project_members_user_id_workspace_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_members")),
        sa.UniqueConstraint("project_id", "user_id", name="project_member_identity"),
    )
    with op.batch_alter_table("project_members", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_project_members_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_project_members_user_id"), ["user_id"], unique=False
        )
    project_ids = (
        tuple(bind.execute(sa.text("SELECT id FROM projects")).scalars())
        if "projects" in existing_tables
        else ()
    )
    for project_id in project_ids:
        bind.execute(
            sa.text(
                """
                INSERT INTO project_members (id, project_id, user_id, role, created_at)
                VALUES (:id, :project_id, :user_id, 'owner', :created_at)
                """
            ),
            {
                "id": _membership_id(str(project_id)),
                "project_id": project_id,
                "user_id": _LOCAL_ADMIN_ID,
                "created_at": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    op.drop_table("project_members")
    if "projects" in existing_tables:
        op.drop_index(op.f("ix_projects_owner_id"), table_name="projects")
        op.drop_column("projects", "owner_id")
    op.drop_table("workspace_users")


def _membership_id(project_id: str) -> str:
    import hashlib

    return hashlib.sha256(f"liveclip-owner:{project_id}".encode()).hexdigest()[:32]
