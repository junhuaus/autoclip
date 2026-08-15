"""add immutable release publication evidence and completed package hashes

Revision ID: d8f3a6b1c420
Revises: c7e5d1a4b920
Create Date: 2026-08-15 18:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f3a6b1c420"
down_revision: str | Sequence[str] | None = "c7e5d1a4b920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "release_packages",
        sa.Column("manifest_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "release_packages",
        sa.Column("zip_sha256", sa.String(length=64), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE release_packages SET "
            "manifest_sha256 = (SELECT assets.sha256 FROM assets "
            "WHERE assets.id = release_packages.manifest_asset_id), "
            "zip_sha256 = (SELECT assets.sha256 FROM assets "
            "WHERE assets.id = release_packages.zip_asset_id) "
            "WHERE status = 'succeeded'"
        )
    )
    op.create_table(
        "release_publication_evidence",
        sa.Column("release_item_id", sa.String(length=32), nullable=False),
        sa.Column("release_package_id", sa.String(length=32), nullable=False),
        sa.Column("release_item_version", sa.Integer(), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("preset_version", sa.String(length=32), nullable=False),
        sa.Column("caption_mode", sa.String(length=24), nullable=False),
        sa.Column("video_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_kind", sa.String(length=16), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("zip_sha256", sa.String(length=64), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "artifact_kind IN ('zip', 'manifest')",
            name=op.f("ck_release_publication_evidence_release_publication_artifact_kind_allowed"),
        ),
        sa.CheckConstraint(
            "length(video_sha256) = 64 AND length(artifact_sha256) = 64 "
            "AND length(manifest_sha256) = 64 "
            "AND (zip_sha256 IS NULL OR length(zip_sha256) = 64)",
            name=op.f("ck_release_publication_evidence_release_publication_hash_lengths"),
        ),
        sa.CheckConstraint(
            "release_item_version > 0",
            name=op.f("ck_release_publication_evidence_release_publication_item_version_positive"),
        ),
        sa.CheckConstraint(
            "package_version > 0",
            name=op.f(
                "ck_release_publication_evidence_release_publication_package_version_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["release_item_id"],
            ["release_items.id"],
            name=op.f("fk_release_publication_evidence_release_item_id_release_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["release_package_id"],
            ["release_packages.id"],
            name=op.f("fk_release_publication_evidence_release_package_id_release_packages"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "release_item_id",
            name=op.f("pk_release_publication_evidence"),
        ),
        sa.UniqueConstraint(
            "release_package_id",
            name=op.f("uq_release_publication_evidence_release_package_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("release_publication_evidence")
    op.drop_column("release_packages", "zip_sha256")
    op.drop_column("release_packages", "manifest_sha256")
