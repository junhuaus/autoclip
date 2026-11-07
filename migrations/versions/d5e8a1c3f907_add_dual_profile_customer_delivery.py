"""Add immutable dual-profile imports, reviewer decisions and customer deliveries.

Stage 19 (customer delivery of dual-profile results). Imports, imported clips,
reviewer decisions and customer-delivery clips are immutable or append-only:
BEFORE UPDATE triggers reject every UPDATE, and their foreign keys use CASCADE
or NO ACTION (never SET NULL), so no referential action updates them.

Revision ID: d5e8a1c3f907
Revises: c84f5d1a702e
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e8a1c3f907"
down_revision: str | Sequence[str] | None = "c84f5d1a702e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IMMUTABLE_TABLES = (
    "dual_profile_imports",
    "dual_profile_import_clips",
    "dual_profile_clip_decisions",
    "customer_delivery_clips",
)


def upgrade() -> None:
    op.create_table(
        "dual_profile_imports",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=8), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("transcript_sha256", sa.String(length=64), nullable=False),
        sa.Column("final_result_sha256", sa.String(length=64), nullable=False),
        sa.Column("run_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("render_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=80), nullable=False),
        sa.Column("routing_policy_version", sa.String(length=80), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("prompt_hashes_json", sa.JSON(), nullable=False),
        sa.Column("clip_count", sa.Integer(), nullable=False),
        sa.Column("imported_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "algorithm_version = 'dual-profile-direct-v1'",
            name=op.f("ck_dual_profile_imports_dual_profile_import_algorithm"),
        ),
        sa.CheckConstraint(
            "routing_policy_version = 'quality-gate-risk-routing-v9'",
            name=op.f("ck_dual_profile_imports_dual_profile_import_routing"),
        ),
        sa.CheckConstraint(
            "schema_version = '1'",
            name=op.f("ck_dual_profile_imports_dual_profile_import_schema_v1"),
        ),
        sa.CheckConstraint(
            "clip_count > 0", name=op.f("ck_dual_profile_imports_dual_profile_import_clip_count")
        ),
        sa.CheckConstraint(
            "length(source_hash) = 64 AND length(transcript_sha256) = 64 AND "
            "length(final_result_sha256) = 64 AND length(run_manifest_sha256) = 64 AND "
            "length(render_manifest_sha256) = 64 AND length(snapshot_fingerprint) = 64",
            name=op.f("ck_dual_profile_imports_dual_profile_import_hash_shape"),
        ),
        sa.CheckConstraint(
            "source_hash = transcript_sha256",
            name=op.f("ck_dual_profile_imports_dual_profile_import_source"),
        ),
        sa.ForeignKeyConstraint(
            ["imported_by"],
            ["workspace_users.id"],
            name=op.f("fk_dual_profile_imports_imported_by_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_dual_profile_imports_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dual_profile_imports")),
        sa.UniqueConstraint(
            "imported_by", "snapshot_fingerprint", name="dual_profile_import_actor_snapshot"
        ),
        sa.UniqueConstraint("project_id", name="dual_profile_import_project"),
    )
    op.create_table(
        "customer_deliveries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("import_id", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("directory_relative_path", sa.String(length=500), nullable=True),
        sa.Column("manifest_asset_id", sa.String(length=32), nullable=True),
        sa.Column("zip_asset_id", sa.String(length=32), nullable=True),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("safe_error_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'creating', 'succeeded', 'failed')",
            name=op.f("ck_customer_deliveries_customer_delivery_status"),
        ),
        sa.CheckConstraint(
            "length(snapshot_fingerprint) = 64",
            name=op.f("ck_customer_deliveries_customer_delivery_fingerprint_shape"),
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_customer_deliveries_customer_delivery_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["workspace_users.id"],
            name=op.f("fk_customer_deliveries_created_by_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["dual_profile_imports.id"],
            name=op.f("fk_customer_deliveries_import_id_dual_profile_imports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_asset_id"],
            ["assets.id"],
            name=op.f("fk_customer_deliveries_manifest_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_customer_deliveries_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name=op.f("fk_customer_deliveries_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["zip_asset_id"],
            ["assets.id"],
            name=op.f("fk_customer_deliveries_zip_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_deliveries")),
        sa.UniqueConstraint(
            "manifest_asset_id", name=op.f("uq_customer_deliveries_manifest_asset_id")
        ),
        sa.UniqueConstraint("project_id", "version", name="customer_delivery_version"),
        sa.UniqueConstraint("task_id", name=op.f("uq_customer_deliveries_task_id")),
        sa.UniqueConstraint("zip_asset_id", name=op.f("uq_customer_deliveries_zip_asset_id")),
    )
    op.create_index("ix_customer_deliveries_import_id", "customer_deliveries", ["import_id"])
    op.create_index("ix_customer_deliveries_project_id", "customer_deliveries", ["project_id"])
    op.create_index("ix_customer_deliveries_status", "customer_deliveries", ["status"])

    op.create_table(
        "dual_profile_import_clips",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("import_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("candidate_id", sa.String(length=96), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("routed_status", sa.String(length=20), nullable=False),
        sa.Column("variant_group_id", sa.String(length=96), nullable=False),
        sa.Column("start_cue_id", sa.Integer(), nullable=False),
        sa.Column("end_cue_id", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("quality_flags_json", sa.JSON(), nullable=False),
        sa.Column("risk_tags_json", sa.JSON(), nullable=False),
        sa.Column("video_asset_id", sa.String(length=32), nullable=False),
        sa.Column("subtitle_asset_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "profile IN ('short_highlight', 'mini_lesson')",
            name=op.f("ck_dual_profile_import_clips_dual_profile_import_clip_profile"),
        ),
        sa.CheckConstraint(
            "routed_status IN ('selected', 'manual_review')",
            name=op.f("ck_dual_profile_import_clips_dual_profile_import_clip_status"),
        ),
        sa.CheckConstraint(
            "end_cue_id >= start_cue_id AND start_cue_id >= 1",
            name=op.f("ck_dual_profile_import_clips_dual_profile_import_clip_cues"),
        ),
        sa.CheckConstraint(
            "end_ms > start_ms AND duration_ms = end_ms - start_ms",
            name=op.f("ck_dual_profile_import_clips_dual_profile_import_clip_interval"),
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100",
            name=op.f("ck_dual_profile_import_clips_dual_profile_import_clip_score"),
        ),
        sa.CheckConstraint(
            "start_ms >= 0",
            name=op.f("ck_dual_profile_import_clips_dual_profile_import_clip_start"),
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["dual_profile_imports.id"],
            name=op.f("fk_dual_profile_import_clips_import_id_dual_profile_imports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_dual_profile_import_clips_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subtitle_asset_id"],
            ["assets.id"],
            name=op.f("fk_dual_profile_import_clips_subtitle_asset_id_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["video_asset_id"],
            ["assets.id"],
            name=op.f("fk_dual_profile_import_clips_video_asset_id_assets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dual_profile_import_clips")),
        sa.UniqueConstraint("import_id", "candidate_id", name="dual_profile_import_candidate"),
        sa.UniqueConstraint("subtitle_asset_id", name="dual_profile_import_clip_subtitle"),
        sa.UniqueConstraint("video_asset_id", name="dual_profile_import_clip_video"),
    )
    op.create_index(
        "ix_dual_profile_import_clips_import_id", "dual_profile_import_clips", ["import_id"]
    )
    op.create_index(
        "ix_dual_profile_import_clips_project_id", "dual_profile_import_clips", ["project_id"]
    )

    op.create_table(
        "customer_share_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("delivery_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoked_by IS NULL) OR "
            "(revoked_at IS NOT NULL AND revoked_by IS NOT NULL)",
            name=op.f("ck_customer_share_links_customer_share_link_revocation"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_customer_share_links_customer_share_link_expiry"),
        ),
        sa.CheckConstraint(
            "length(token_sha256) = 64",
            name=op.f("ck_customer_share_links_customer_share_link_token_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["workspace_users.id"],
            name=op.f("fk_customer_share_links_created_by_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["customer_deliveries.id"],
            name=op.f("fk_customer_share_links_delivery_id_customer_deliveries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_customer_share_links_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["workspace_users.id"],
            name=op.f("fk_customer_share_links_revoked_by_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_share_links")),
        sa.UniqueConstraint("token_sha256", name="customer_share_link_token"),
    )
    op.create_index("ix_customer_share_links_delivery_id", "customer_share_links", ["delivery_id"])
    op.create_index("ix_customer_share_links_project_id", "customer_share_links", ["project_id"])

    op.create_table(
        "dual_profile_clip_decisions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("import_clip_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("title_override", sa.String(length=200), nullable=True),
        sa.Column("hook_override", sa.Text(), nullable=True),
        sa.Column("summary_override", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.String(length=32), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "action = 'approve' OR (title_override IS NULL AND hook_override IS NULL "
            "AND summary_override IS NULL)",
            name=op.f("ck_dual_profile_clip_decisions_dual_profile_decision_override_on_approve"),
        ),
        sa.CheckConstraint(
            "action IN ('approve', 'reject', 'select', 'deselect')",
            name=op.f("ck_dual_profile_clip_decisions_dual_profile_decision_action"),
        ),
        sa.CheckConstraint(
            "sequence > 0",
            name=op.f("ck_dual_profile_clip_decisions_dual_profile_decision_sequence_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_dual_profile_clip_decisions_actor_user_id_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_clip_id"],
            ["dual_profile_import_clips.id"],
            name=op.f("fk_dual_profile_clip_decisions_import_clip_id_dual_profile_import_clips"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_dual_profile_clip_decisions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dual_profile_clip_decisions")),
        sa.UniqueConstraint("import_clip_id", "sequence", name="dual_profile_decision_sequence"),
    )
    op.create_index(
        "ix_dual_profile_clip_decisions_import_clip_id",
        "dual_profile_clip_decisions",
        ["import_clip_id"],
    )
    op.create_index(
        "ix_dual_profile_clip_decisions_project_id", "dual_profile_clip_decisions", ["project_id"]
    )

    op.create_table(
        "customer_delivery_clips",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("delivery_id", sa.String(length=32), nullable=False),
        sa.Column("import_clip_id", sa.String(length=32), nullable=False),
        sa.Column("approval_decision_id", sa.String(length=32), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("video_asset_id", sa.String(length=32), nullable=False),
        sa.Column("subtitle_asset_id", sa.String(length=32), nullable=False),
        sa.Column("video_sha256", sa.String(length=64), nullable=False),
        sa.Column("subtitle_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "profile IN ('short_highlight', 'mini_lesson')",
            name=op.f("ck_customer_delivery_clips_customer_delivery_clip_profile"),
        ),
        sa.CheckConstraint(
            "duration_ms > 0",
            name=op.f("ck_customer_delivery_clips_customer_delivery_clip_duration"),
        ),
        sa.CheckConstraint(
            "length(video_sha256) = 64 AND length(subtitle_sha256) = 64",
            name=op.f("ck_customer_delivery_clips_customer_delivery_clip_hash_shape"),
        ),
        sa.CheckConstraint(
            "ordinal > 0",
            name=op.f("ck_customer_delivery_clips_customer_delivery_clip_ordinal_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["approval_decision_id"],
            ["dual_profile_clip_decisions.id"],
            name=op.f(
                "fk_customer_delivery_clips_approval_decision_id_dual_profile_clip_decisions"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["customer_deliveries.id"],
            name=op.f("fk_customer_delivery_clips_delivery_id_customer_deliveries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["import_clip_id"],
            ["dual_profile_import_clips.id"],
            name=op.f("fk_customer_delivery_clips_import_clip_id_dual_profile_import_clips"),
        ),
        sa.ForeignKeyConstraint(
            ["subtitle_asset_id"],
            ["assets.id"],
            name=op.f("fk_customer_delivery_clips_subtitle_asset_id_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["video_asset_id"],
            ["assets.id"],
            name=op.f("fk_customer_delivery_clips_video_asset_id_assets"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_delivery_clips")),
        sa.UniqueConstraint("delivery_id", "import_clip_id", name="customer_delivery_clip_source"),
        sa.UniqueConstraint("delivery_id", "ordinal", name="customer_delivery_clip_ordinal"),
    )
    op.create_index(
        "ix_customer_delivery_clips_delivery_id", "customer_delivery_clips", ["delivery_id"]
    )
    op.create_index(
        "ix_customer_delivery_clips_import_clip_id", "customer_delivery_clips", ["import_clip_id"]
    )
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} rows are immutable'); END"
        )


def downgrade() -> None:
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable")
    op.drop_table("customer_delivery_clips")
    op.drop_table("dual_profile_clip_decisions")
    op.drop_table("customer_share_links")
    op.drop_table("dual_profile_import_clips")
    op.drop_table("customer_deliveries")
    op.drop_table("dual_profile_imports")
