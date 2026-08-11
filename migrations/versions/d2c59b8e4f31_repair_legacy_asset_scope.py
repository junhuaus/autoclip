"""repair legacy asset scope columns

Revision ID: d2c59b8e4f31
Revises: a71d4f9c2e10
Create Date: 2026-08-05 20:30:00.000000

Some development databases were stamped before the initial migration's Asset
scope columns were present.  The checked-in baseline already contains these
columns, so this revision is intentionally conditional: fresh databases are a
no-op while stamped legacy databases are repaired in place.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2c59b8e4f31"
down_revision: str | Sequence[str] | None = "a71d4f9c2e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Restore the Asset candidate/revision fence expected by the current ORM."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "assets" not in tables or "candidate_clips" not in tables:
        raise RuntimeError("legacy Asset repair requires assets and candidate_clips tables")

    columns = {column["name"] for column in inspector.get_columns("assets")}
    missing_candidate = "candidate_clip_id" not in columns
    missing_epoch = "revision_epoch" not in columns
    if missing_candidate or missing_epoch:
        with op.batch_alter_table("assets", schema=None) as batch_op:
            if missing_candidate:
                batch_op.add_column(sa.Column("candidate_clip_id", sa.String(length=32)))
            if missing_epoch:
                batch_op.add_column(sa.Column("revision_epoch", sa.BigInteger()))

    _backfill_asset_scope(bind, tables)

    inspector = sa.inspect(bind)
    candidate_index_exists = any(
        tuple(index.get("column_names") or ()) == ("candidate_clip_id",)
        for index in inspector.get_indexes("assets")
    )
    candidate_fk_exists = any(
        tuple(foreign_key.get("constrained_columns") or ()) == ("candidate_clip_id",)
        and foreign_key.get("referred_table") == "candidate_clips"
        for foreign_key in inspector.get_foreign_keys("assets")
    )
    if not candidate_index_exists or not candidate_fk_exists:
        with op.batch_alter_table("assets", schema=None) as batch_op:
            if not candidate_fk_exists:
                batch_op.create_foreign_key(
                    batch_op.f("fk_assets_candidate_clip_id_candidate_clips"),
                    "candidate_clips",
                    ["candidate_clip_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            if not candidate_index_exists:
                batch_op.create_index(
                    batch_op.f("ix_assets_candidate_clip_id"),
                    ["candidate_clip_id"],
                    unique=False,
                )


def downgrade() -> None:
    """Keep the repaired baseline columns when returning to the prior revision.

    Revision ``a71d4f9c2e10`` already describes a schema containing these fields.
    Dropping them would corrupt a healthy database and make the ORM unusable.
    """


def _backfill_asset_scope(bind: sa.Connection, tables: set[str]) -> None:
    if "render_jobs" in tables:
        render_columns = {column["name"] for column in sa.inspect(bind).get_columns("render_jobs")}
        reference_columns = tuple(
            name
            for name in (
                "asset_id",
                "subtitle_asset_id",
                "quality_report_asset_id",
                "contact_sheet_asset_id",
            )
            if name in render_columns
        )
        if {"candidate_clip_id", "revision_epoch"}.issubset(render_columns) and reference_columns:
            predicate = " OR ".join(
                f"assets.id = render_jobs.{column}" for column in reference_columns
            )
            bind.execute(
                sa.text(
                    f"""
                    UPDATE assets
                    SET candidate_clip_id = COALESCE(
                            candidate_clip_id,
                            (SELECT candidate_clip_id FROM render_jobs WHERE {predicate} LIMIT 1)
                        ),
                        revision_epoch = COALESCE(
                            revision_epoch,
                            (SELECT revision_epoch FROM render_jobs WHERE {predicate} LIMIT 1)
                        )
                    WHERE candidate_clip_id IS NULL OR revision_epoch IS NULL
                    """
                )
            )

    if "deliveries" in tables:
        delivery_columns = {column["name"] for column in sa.inspect(bind).get_columns("deliveries")}
        reference_columns = tuple(
            name for name in ("manifest_asset_id", "zip_asset_id") if name in delivery_columns
        )
        if "expected_revision_epoch" in delivery_columns and reference_columns:
            predicate = " OR ".join(
                f"assets.id = deliveries.{column}" for column in reference_columns
            )
            bind.execute(
                sa.text(
                    f"""
                    UPDATE assets
                    SET revision_epoch = COALESCE(
                        revision_epoch,
                        (
                            SELECT expected_revision_epoch
                            FROM deliveries
                            WHERE {predicate}
                            LIMIT 1
                        )
                    )
                    WHERE revision_epoch IS NULL
                    """
                )
            )
