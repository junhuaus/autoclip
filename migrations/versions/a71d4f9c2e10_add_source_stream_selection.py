"""add source stream selection

Revision ID: a71d4f9c2e10
Revises: f3d2a9b817c4
Create Date: 2026-08-04 06:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a71d4f9c2e10"
down_revision: str | Sequence[str] | None = "f3d2a9b817c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist verified stream selection without inventing values for legacy rows."""
    with op.batch_alter_table("source_media", schema=None) as batch_op:
        batch_op.add_column(sa.Column("video_stream_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("audio_stream_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("video_rotation_degrees", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "source_stream_selection_complete",
            """
            (
                video_stream_index IS NULL
                AND audio_stream_index IS NULL
                AND video_rotation_degrees IS NULL
            ) OR (
                video_stream_index IS NOT NULL
                AND audio_stream_index IS NOT NULL
                AND video_rotation_degrees IS NOT NULL
            )
            """,
        )
        batch_op.create_check_constraint(
            "source_stream_indexes_nonnegative",
            """
            video_stream_index IS NULL OR (
                video_stream_index >= 0 AND audio_stream_index >= 0
            )
            """,
        )
        batch_op.create_check_constraint(
            "source_stream_indexes_distinct",
            "video_stream_index IS NULL OR video_stream_index != audio_stream_index",
        )
        batch_op.create_check_constraint(
            "source_rotation_allowed",
            """
            video_rotation_degrees IS NULL
            OR video_rotation_degrees IN (0, 90, 180, 270)
            """,
        )


def downgrade() -> None:
    """Remove persisted stream-selection metadata."""
    with op.batch_alter_table("source_media", schema=None) as batch_op:
        batch_op.drop_constraint("source_rotation_allowed", type_="check")
        batch_op.drop_constraint("source_stream_indexes_distinct", type_="check")
        batch_op.drop_constraint("source_stream_indexes_nonnegative", type_="check")
        batch_op.drop_constraint("source_stream_selection_complete", type_="check")
        batch_op.drop_column("video_rotation_degrees")
        batch_op.drop_column("audio_stream_index")
        batch_op.drop_column("video_stream_index")
