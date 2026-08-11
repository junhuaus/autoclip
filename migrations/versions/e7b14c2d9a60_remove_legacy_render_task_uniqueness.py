"""remove legacy render task uniqueness

Revision ID: e7b14c2d9a60
Revises: d2c59b8e4f31
Create Date: 2026-08-05 22:10:00.000000

Early development databases made ``render_jobs.task_id`` unique.  A pipeline
proxy-render stage owns one task but legitimately creates one RenderJob per
selected candidate, so that legacy constraint prevents the second proxy from
being persisted.  The checked-in baseline already models this relationship as
many renders to one task; fresh databases therefore need only the ordinary
lookup index.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b14c2d9a60"
down_revision: str | Sequence[str] | None = "d2c59b8e4f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Normalize legacy RenderJob task ownership to the current many-to-one model."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "render_jobs" not in set(inspector.get_table_names()):
        raise RuntimeError("render task repair requires the render_jobs table")
    columns = {column["name"] for column in inspector.get_columns("render_jobs")}
    if "task_id" not in columns:
        # Some narrowly stamped development fixtures predate task ownership
        # entirely.  There is no conflicting constraint to normalize there.
        return

    task_constraints = [
        constraint
        for constraint in inspector.get_unique_constraints("render_jobs")
        if tuple(constraint.get("column_names") or ()) == ("task_id",)
    ]
    for constraint in task_constraints:
        name = constraint.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError("legacy render task uniqueness must have a stable name")
        with op.batch_alter_table("render_jobs", schema=None) as batch_op:
            batch_op.drop_constraint(name, type_="unique")

    inspector = sa.inspect(bind)
    task_indexes = [
        index
        for index in inspector.get_indexes("render_jobs")
        if tuple(index.get("column_names") or ()) == ("task_id",)
    ]
    for index in task_indexes:
        if not index.get("unique"):
            continue
        name = index.get("name")
        if not isinstance(name, str) or not name:
            raise RuntimeError("legacy render task unique index must have a stable name")
        op.drop_index(name, table_name="render_jobs")

    inspector = sa.inspect(bind)
    has_lookup_index = any(
        tuple(index.get("column_names") or ()) == ("task_id",) and not index.get("unique")
        for index in inspector.get_indexes("render_jobs")
    )
    if not has_lookup_index:
        op.create_index("ix_render_jobs_task_id", "render_jobs", ["task_id"], unique=False)


def downgrade() -> None:
    """Keep the canonical many-to-one relationship described by the prior baseline."""
