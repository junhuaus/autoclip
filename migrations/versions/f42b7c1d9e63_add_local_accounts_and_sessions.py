"""add local accounts, sessions, audit events, and private visibility

Revision ID: f42b7c1d9e63
Revises: d31a6e9f4b72
Create Date: 2026-08-13 15:00:00.000000

Existing projects remain private and existing users remain members, except the
deterministic v0.1 local administrator account which becomes an administrator.
No password is synthesized during migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f42b7c1d9e63"
down_revision: str | Sequence[str] | None = "d31a6e9f4b72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCAL_ADMIN_ID = "00000000000000000000000000000001"


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    op.add_column(
        "workspace_users",
        sa.Column("system_role", sa.String(length=24), nullable=False, server_default="member"),
    )
    op.add_column("workspace_users", sa.Column("password_hash", sa.Text(), nullable=True))
    op.add_column(
        "workspace_users",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "workspace_users", sa.Column("last_login_at", sa.DateTime(), nullable=True)
    )
    op.execute(
        sa.text(
            "UPDATE workspace_users SET system_role = 'administrator' WHERE id = :user_id"
        ).bindparams(user_id=_LOCAL_ADMIN_ID)
    )

    if "projects" in existing_tables:
        op.add_column(
            "projects",
            sa.Column(
                "visibility", sa.String(length=20), nullable=False, server_default="private"
            ),
        )
    if "project_members" in existing_tables and "projects" in existing_tables:
        with op.batch_alter_table("project_members", schema=None) as batch_op:
            batch_op.drop_constraint(
                batch_op.f("ck_project_members_project_member_role_allowed"), type_="check"
            )
            batch_op.create_check_constraint(
                "project_member_role_allowed",
                "role IN ('owner', 'editor', 'reviewer', 'viewer')",
            )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_auth_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "user_auth_version >= 0", name=op.f("ck_auth_sessions_auth_version_nonnegative")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["workspace_users.id"],
            name=op.f("fk_auth_sessions_user_id_workspace_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"])
    op.create_index(op.f("ix_auth_sessions_expires_at"), "auth_sessions", ["expires_at"])

    op.create_table(
        "auth_login_attempts",
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "failed_count >= 0",
            name=op.f("ck_auth_login_attempts_login_failed_count_nonnegative"),
        ),
        sa.PrimaryKeyConstraint("identity_hash", name=op.f("pk_auth_login_attempts")),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=True),
        sa.Column("actor_username", sa.String(length=80), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=True),
        sa.Column("project_id", sa.String(length=32), nullable=True),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_audit_events_actor_user_id_workspace_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_actor_user_id"), "audit_events", ["actor_user_id"])
    op.create_index(op.f("ix_audit_events_action"), "audit_events", ["action"])
    op.create_index(op.f("ix_audit_events_project_id"), "audit_events", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    op.drop_table("audit_events")
    op.drop_table("auth_login_attempts")
    op.drop_table("auth_sessions")
    if "project_members" in existing_tables and "projects" in existing_tables:
        with op.batch_alter_table("project_members", schema=None) as batch_op:
            batch_op.drop_constraint("project_member_role_allowed", type_="check")
            batch_op.create_check_constraint(
                batch_op.f("project_member_role_allowed"),
                "role IN ('owner', 'editor', 'reviewer')",
            )
    if "projects" in existing_tables:
        op.drop_column("projects", "visibility")
    op.drop_column("workspace_users", "last_login_at")
    op.drop_column("workspace_users", "auth_version")
    op.drop_column("workspace_users", "password_hash")
    op.drop_column("workspace_users", "system_role")
