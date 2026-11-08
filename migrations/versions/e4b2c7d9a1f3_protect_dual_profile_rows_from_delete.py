"""Reject direct DELETE of immutable dual-profile rows; keep the project-purge cascade.

Stage 19a reviewer P2-5. Imports, imported clips, reviewer decisions,
customer deliveries (immutable versions; a failed version stays as a record)
and customer-delivery clips may disappear only together with their project
(``DELETE FROM projects`` cascades through them). A BEFORE DELETE trigger
aborts any deletion while the owning project row still exists. SQLite runs
the ON DELETE CASCADE actions after the parent project row is removed, so the
cascade sees no owning project and passes.

Revision ID: e4b2c7d9a1f3
Revises: d5e8a1c3f907
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e4b2c7d9a1f3"
down_revision: str | Sequence[str] | None = "d5e8a1c3f907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNING_PROJECT = {
    "dual_profile_imports": "SELECT 1 FROM projects WHERE projects.id = OLD.project_id",
    "dual_profile_import_clips": "SELECT 1 FROM projects WHERE projects.id = OLD.project_id",
    "dual_profile_clip_decisions": "SELECT 1 FROM projects WHERE projects.id = OLD.project_id",
    "customer_deliveries": "SELECT 1 FROM projects WHERE projects.id = OLD.project_id",
    "customer_delivery_clips": (
        "SELECT 1 FROM customer_deliveries JOIN projects "
        "ON projects.id = customer_deliveries.project_id "
        "WHERE customer_deliveries.id = OLD.delivery_id"
    ),
}


def upgrade() -> None:
    for table, owner in OWNING_PROJECT.items():
        op.execute(
            f"CREATE TRIGGER {table}_delete_guard BEFORE DELETE ON {table} "
            f"WHEN EXISTS ({owner}) "
            f"BEGIN SELECT RAISE(ABORT, '{table} rows are deleted only with their project'); END"
        )


def downgrade() -> None:
    for table in OWNING_PROJECT:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_delete_guard")
