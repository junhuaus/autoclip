"""add revision-bound clip comment threads

Revision ID: e92b7c4d1a60
Revises: d8f3a6b1c420
Create Date: 2026-08-15 23:55:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e92b7c4d1a60"
down_revision: str | Sequence[str] | None = "d8f3a6b1c420"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clip_comment_threads",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("edit_plan_revision_id", sa.String(length=32), nullable=False),
        sa.Column("source_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("clip_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("created_by_username", sa.String(length=80), nullable=False),
        sa.Column("created_by_display_name", sa.String(length=120), nullable=False),
        sa.Column("resolved_by_user_id", sa.String(length=32), nullable=True),
        sa.Column("resolved_by_username", sa.String(length=80), nullable=True),
        sa.Column("resolved_by_display_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "clip_time_ms >= 0",
            name=op.f("ck_clip_comment_threads_comment_thread_clip_time_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'open' AND resolved_by_user_id IS NULL "
            "AND resolved_by_username IS NULL AND resolved_by_display_name IS NULL "
            "AND resolved_at IS NULL) OR (status = 'resolved' "
            "AND resolved_by_username IS NOT NULL AND resolved_by_display_name IS NOT NULL "
            "AND resolved_at IS NOT NULL)",
            name=op.f("ck_clip_comment_threads_comment_thread_resolution_complete"),
        ),
        sa.CheckConstraint(
            "source_time_ms >= 0",
            name=op.f("ck_clip_comment_threads_comment_thread_source_time_nonnegative"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')",
            name=op.f("ck_clip_comment_threads_comment_thread_status_allowed"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_clip_comment_threads_comment_thread_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_clip_comment_threads_created_by_user_id_workspace_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["edit_plan_revision_id"],
            ["edit_plan_revisions.id"],
            name=op.f("fk_clip_comment_threads_edit_plan_revision_id_edit_plan_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_clip_comment_threads_resolved_by_user_id_workspace_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clip_comment_threads")),
    )
    op.create_index(
        "ix_clip_comment_threads_created_by_user_id",
        "clip_comment_threads",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_clip_comment_threads_edit_plan_revision_id",
        "clip_comment_threads",
        ["edit_plan_revision_id"],
    )
    op.create_index(
        "ix_clip_comment_threads_revision_updated",
        "clip_comment_threads",
        ["edit_plan_revision_id", "updated_at"],
    )
    op.create_index(
        "ix_clip_comment_threads_resolved_by_user_id",
        "clip_comment_threads",
        ["resolved_by_user_id"],
    )

    op.create_table(
        "clip_comments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("author_user_id", sa.String(length=32), nullable=True),
        sa.Column("author_username", sa.String(length=80), nullable=False),
        sa.Column("author_display_name", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "length(trim(body)) > 0 AND length(body) <= 2000",
            name=op.f("ck_clip_comments_clip_comment_body_length"),
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name=op.f("ck_clip_comments_clip_comment_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_clip_comments_author_user_id_workspace_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["clip_comment_threads.id"],
            name=op.f("fk_clip_comments_thread_id_clip_comment_threads"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clip_comments")),
        sa.UniqueConstraint(
            "thread_id",
            "sequence",
            name="clip_comment_thread_sequence",
        ),
    )
    op.create_index(
        "ix_clip_comments_author_user_id",
        "clip_comments",
        ["author_user_id"],
    )
    op.create_index("ix_clip_comments_thread_id", "clip_comments", ["thread_id"])

    op.create_table(
        "clip_comment_mentions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("comment_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("mention_index", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "mention_index >= 0",
            name=op.f("ck_clip_comment_mentions_clip_comment_mention_index_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["comment_id"],
            ["clip_comments.id"],
            name=op.f("fk_clip_comment_mentions_comment_id_clip_comments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["workspace_users.id"],
            name=op.f("fk_clip_comment_mentions_user_id_workspace_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clip_comment_mentions")),
        sa.UniqueConstraint(
            "comment_id",
            "mention_index",
            name="clip_comment_mention_index",
        ),
        sa.UniqueConstraint(
            "comment_id",
            "user_id",
            name="clip_comment_mentioned_user",
        ),
    )
    op.create_index(
        "ix_clip_comment_mentions_comment_id",
        "clip_comment_mentions",
        ["comment_id"],
    )
    op.create_index(
        "ix_clip_comment_mentions_user_id",
        "clip_comment_mentions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_table("clip_comment_mentions")
    op.drop_table("clip_comments")
    op.drop_table("clip_comment_threads")
