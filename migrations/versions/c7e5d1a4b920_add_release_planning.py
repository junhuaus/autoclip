"""add release planning and immutable platform packages

Revision ID: c7e5d1a4b920
Revises: b95f3e6a1c27
Create Date: 2026-08-15 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e5d1a4b920"
down_revision: str | Sequence[str] | None = "b95f3e6a1c27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "release_items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("candidate_clip_id", sa.String(length=32), nullable=False),
        sa.Column("edit_plan_revision_id", sa.String(length=32), nullable=False),
        sa.Column("edit_plan_revision", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("preset_version", sa.String(length=32), nullable=False),
        sa.Column("account_label", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("title_variants_json", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("hashtags_json", sa.JSON(), nullable=False),
        sa.Column("cta", sa.String(length=200), nullable=False),
        sa.Column("caption_mode", sa.String(length=24), nullable=False),
        sa.Column("cover_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("assignee_user_id", sa.String(length=32), nullable=True),
        sa.Column("planned_publish_at", sa.DateTime(), nullable=True),
        sa.Column("approval_status", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("checklist_json", sa.JSON(), nullable=False),
        sa.Column("preflight_json", sa.JSON(), nullable=False),
        sa.Column("management_version", sa.Integer(), nullable=False),
        sa.Column("external_url", sa.String(length=1000), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("result_notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "approval_status IN ('draft', 'pending_review', 'approved', 'changes_requested')",
            name=op.f("ck_release_items_release_item_approval_allowed"),
        ),
        sa.CheckConstraint(
            "caption_mode IN ('clean_separate', 'burned')",
            name=op.f("ck_release_items_release_item_caption_mode_allowed"),
        ),
        sa.CheckConstraint(
            "cover_time_ms >= 0",
            name=op.f("ck_release_items_release_item_cover_nonnegative"),
        ),
        sa.CheckConstraint(
            "edit_plan_revision > 0",
            name=op.f("ck_release_items_release_item_revision_positive"),
        ),
        sa.CheckConstraint(
            "management_version > 0",
            name=op.f("ck_release_items_release_item_version_positive"),
        ),
        sa.CheckConstraint(
            "platform IN ('douyin', 'xiaohongshu', 'bilibili_vertical', "
            "'youtube_shorts', 'tiktok', 'generic_vertical')",
            name=op.f("ck_release_items_release_item_platform_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'scheduled_external', 'published', "
            "'failed', 'withdrawn')",
            name=op.f("ck_release_items_release_item_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_release_items_assignee_user_id_workspace_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_clip_id"],
            ["candidate_clips.id"],
            name=op.f("fk_release_items_candidate_clip_id_candidate_clips"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_release_items_created_by_user_id_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["edit_plan_revision_id"],
            ["edit_plan_revisions.id"],
            name=op.f("fk_release_items_edit_plan_revision_id_edit_plan_revisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_release_items_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_items")),
        sa.UniqueConstraint(
            "candidate_clip_id",
            "platform",
            "account_label",
            name="release_item_clip_platform_account",
        ),
    )
    op.create_index(op.f("ix_release_items_project_id"), "release_items", ["project_id"])
    op.create_index(
        op.f("ix_release_items_candidate_clip_id"),
        "release_items",
        ["candidate_clip_id"],
    )
    op.create_index(op.f("ix_release_items_platform"), "release_items", ["platform"])
    op.create_index(
        op.f("ix_release_items_assignee_user_id"),
        "release_items",
        ["assignee_user_id"],
    )
    op.create_index(
        op.f("ix_release_items_planned_publish_at"),
        "release_items",
        ["planned_publish_at"],
    )
    op.create_index(
        op.f("ix_release_items_approval_status"),
        "release_items",
        ["approval_status"],
    )
    op.create_index(op.f("ix_release_items_status"), "release_items", ["status"])
    op.create_index(
        op.f("ix_release_items_published_at"),
        "release_items",
        ["published_at"],
    )
    op.create_index(
        op.f("ix_release_items_created_by_user_id"),
        "release_items",
        ["created_by_user_id"],
    )

    op.create_table(
        "release_metric_snapshots",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("release_item_id", sa.String(length=32), nullable=False),
        sa.Column("recorded_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=False),
        sa.Column("likes", sa.BigInteger(), nullable=False),
        sa.Column("comments", sa.BigInteger(), nullable=False),
        sa.Column("shares", sa.BigInteger(), nullable=False),
        sa.Column("saves", sa.BigInteger(), nullable=False),
        sa.Column("followers_gained", sa.BigInteger(), nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "comments >= 0",
            name=op.f("ck_release_metric_snapshots_release_metric_comments_nonnegative"),
        ),
        sa.CheckConstraint(
            "followers_gained >= 0",
            name=op.f("ck_release_metric_snapshots_release_metric_followers_nonnegative"),
        ),
        sa.CheckConstraint(
            "likes >= 0",
            name=op.f("ck_release_metric_snapshots_release_metric_likes_nonnegative"),
        ),
        sa.CheckConstraint(
            "saves >= 0",
            name=op.f("ck_release_metric_snapshots_release_metric_saves_nonnegative"),
        ),
        sa.CheckConstraint(
            "shares >= 0",
            name=op.f("ck_release_metric_snapshots_release_metric_shares_nonnegative"),
        ),
        sa.CheckConstraint(
            "views >= 0",
            name=op.f("ck_release_metric_snapshots_release_metric_views_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"],
            ["workspace_users.id"],
            name=op.f(
                "fk_release_metric_snapshots_recorded_by_user_id_workspace_users"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["release_item_id"],
            ["release_items.id"],
            name=op.f("fk_release_metric_snapshots_release_item_id_release_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_metric_snapshots")),
    )
    op.create_index(
        op.f("ix_release_metric_snapshots_release_item_id"),
        "release_metric_snapshots",
        ["release_item_id"],
    )
    op.create_index(
        op.f("ix_release_metric_snapshots_recorded_by_user_id"),
        "release_metric_snapshots",
        ["recorded_by_user_id"],
    )
    op.create_index(
        op.f("ix_release_metric_snapshots_captured_at"),
        "release_metric_snapshots",
        ["captured_at"],
    )

    op.create_table(
        "release_packages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("release_item_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expected_generation", sa.Integer(), nullable=False),
        sa.Column("expected_revision_epoch", sa.BigInteger(), nullable=False),
        sa.Column("expected_release_item_version", sa.Integer(), nullable=False),
        sa.Column("preset_version", sa.String(length=32), nullable=False),
        sa.Column("caption_mode", sa.String(length=24), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("directory_relative_path", sa.String(length=500), nullable=False),
        sa.Column("source_render_job_id", sa.String(length=32), nullable=False),
        sa.Column("source_video_asset_id", sa.String(length=32), nullable=False),
        sa.Column("manifest_asset_id", sa.String(length=32), nullable=True),
        sa.Column("zip_asset_id", sa.String(length=32), nullable=True),
        sa.Column("include_zip", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("safe_error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "caption_mode IN ('clean_separate', 'burned')",
            name=op.f("ck_release_packages_release_package_caption_mode_allowed"),
        ),
        sa.CheckConstraint(
            "expected_generation > 0",
            name=op.f("ck_release_packages_release_package_generation_positive"),
        ),
        sa.CheckConstraint(
            "expected_release_item_version > 0",
            name=op.f("ck_release_packages_release_package_item_version_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'creating', 'succeeded', 'failed')",
            name=op.f("ck_release_packages_release_package_status_allowed"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_release_packages_release_package_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["manifest_asset_id"],
            ["assets.id"],
            name=op.f("fk_release_packages_manifest_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_release_packages_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_item_id"],
            ["release_items.id"],
            name=op.f("fk_release_packages_release_item_id_release_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_release_packages_requested_by_user_id_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_render_job_id"],
            ["render_jobs.id"],
            name=op.f("fk_release_packages_source_render_job_id_render_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_video_asset_id"],
            ["assets.id"],
            name=op.f("fk_release_packages_source_video_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_release_packages_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["zip_asset_id"],
            ["assets.id"],
            name=op.f("fk_release_packages_zip_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_packages")),
        sa.UniqueConstraint(
            "release_item_id",
            "version",
            name="release_item_package_version",
        ),
        sa.UniqueConstraint(
            "manifest_asset_id",
            name=op.f("uq_release_packages_manifest_asset_id"),
        ),
        sa.UniqueConstraint("task_id", name=op.f("uq_release_packages_task_id")),
        sa.UniqueConstraint("zip_asset_id", name=op.f("uq_release_packages_zip_asset_id")),
    )
    op.create_index(
        op.f("ix_release_packages_release_item_id"),
        "release_packages",
        ["release_item_id"],
    )
    op.create_index(
        op.f("ix_release_packages_project_id"),
        "release_packages",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_release_packages_requested_by_user_id"),
        "release_packages",
        ["requested_by_user_id"],
    )
    op.create_index(
        op.f("ix_release_packages_status"),
        "release_packages",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("release_packages")
    op.drop_table("release_metric_snapshots")
    op.drop_table("release_items")
