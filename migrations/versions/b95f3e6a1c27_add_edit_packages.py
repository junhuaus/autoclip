"""add immutable selective editor packages

Revision ID: b95f3e6a1c27
Revises: a84e2d7c9f10
Create Date: 2026-08-13 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b95f3e6a1c27"
down_revision: str | Sequence[str] | None = "a84e2d7c9f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "edit_packages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expected_revision_epoch", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("directory_relative_path", sa.String(length=500), nullable=False),
        sa.Column("preset", sa.String(length=32), nullable=False),
        sa.Column("content", sa.String(length=24), nullable=False),
        sa.Column("manifest_asset_id", sa.String(length=32), nullable=True),
        sa.Column("zip_asset_id", sa.String(length=32), nullable=True),
        sa.Column("include_zip", sa.Boolean(), nullable=False),
        sa.Column("expected_generation", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("safe_error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "content IN ('full', 'metadata_only')",
            name=op.f("ck_edit_packages_edit_package_content_allowed"),
        ),
        sa.CheckConstraint(
            "expected_generation > 0",
            name=op.f("ck_edit_packages_edit_package_generation_positive"),
        ),
        sa.CheckConstraint(
            "preset = 'clean_editing'",
            name=op.f("ck_edit_packages_edit_package_preset_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'creating', 'succeeded', 'failed')",
            name=op.f("ck_edit_packages_edit_package_status_allowed"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_edit_packages_edit_package_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["manifest_asset_id"],
            ["assets.id"],
            name=op.f("fk_edit_packages_manifest_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_edit_packages_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_edit_packages_requested_by_user_id_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_edit_packages_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["zip_asset_id"],
            ["assets.id"],
            name=op.f("fk_edit_packages_zip_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edit_packages")),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="project_edit_package_version",
        ),
        sa.UniqueConstraint("task_id", name=op.f("uq_edit_packages_task_id")),
        sa.UniqueConstraint("manifest_asset_id", name=op.f("uq_edit_packages_manifest_asset_id")),
        sa.UniqueConstraint("zip_asset_id", name=op.f("uq_edit_packages_zip_asset_id")),
    )
    op.create_index(op.f("ix_edit_packages_project_id"), "edit_packages", ["project_id"])
    op.create_index(
        op.f("ix_edit_packages_requested_by_user_id"),
        "edit_packages",
        ["requested_by_user_id"],
    )
    op.create_index(op.f("ix_edit_packages_status"), "edit_packages", ["status"])

    op.create_table(
        "edit_package_clips",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("edit_package_id", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("candidate_clip_id", sa.String(length=32), nullable=False),
        sa.Column("edit_plan_revision_id", sa.String(length=32), nullable=False),
        sa.Column("render_job_id", sa.String(length=32), nullable=False),
        sa.Column("edit_plan_revision", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("video_asset_id", sa.String(length=32), nullable=False),
        sa.Column("contact_sheet_asset_id", sa.String(length=32), nullable=False),
        sa.Column("video_filename", sa.String(length=500), nullable=True),
        sa.Column("subtitle_filename", sa.String(length=500), nullable=True),
        sa.Column("thumbnail_filename", sa.String(length=500), nullable=True),
        sa.Column("video_sha256", sa.String(length=64), nullable=True),
        sa.Column("subtitle_sha256", sa.String(length=64), nullable=True),
        sa.Column("thumbnail_sha256", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "edit_plan_revision > 0",
            name=op.f("ck_edit_package_clips_edit_package_clip_revision_positive"),
        ),
        sa.CheckConstraint(
            "ordinal > 0",
            name=op.f("ck_edit_package_clips_edit_package_clip_ordinal_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_clip_id"],
            ["candidate_clips.id"],
            name=op.f("fk_edit_package_clips_candidate_clip_id_candidate_clips"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contact_sheet_asset_id"],
            ["assets.id"],
            name=op.f("fk_edit_package_clips_contact_sheet_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["edit_package_id"],
            ["edit_packages.id"],
            name=op.f("fk_edit_package_clips_edit_package_id_edit_packages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["edit_plan_revision_id"],
            ["edit_plan_revisions.id"],
            name=op.f("fk_edit_package_clips_edit_plan_revision_id_edit_plan_revisions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["render_job_id"],
            ["render_jobs.id"],
            name=op.f("fk_edit_package_clips_render_job_id_render_jobs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["video_asset_id"],
            ["assets.id"],
            name=op.f("fk_edit_package_clips_video_asset_id_assets"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edit_package_clips")),
        sa.UniqueConstraint(
            "edit_package_id",
            "candidate_clip_id",
            name="edit_package_candidate",
        ),
        sa.UniqueConstraint(
            "edit_package_id",
            "ordinal",
            name="edit_package_clip_ordinal",
        ),
    )
    op.create_index(
        op.f("ix_edit_package_clips_edit_package_id"),
        "edit_package_clips",
        ["edit_package_id"],
    )


def downgrade() -> None:
    op.drop_table("edit_package_clips")
    op.drop_table("edit_packages")
