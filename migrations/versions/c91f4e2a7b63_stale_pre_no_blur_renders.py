"""stale renders that predate the no-blur contract

Revision ID: c91f4e2a7b63
Revises: b81e3c7a4d20
Create Date: 2026-08-11 13:30:00.000000

LiveClip no longer permits blurred-background/duplicated-foreground video.
Every older review proxy is ambiguous because its renderer contract allowed that
composition. Any render whose EditPlan explicitly selected the removed layout
is also invalid regardless of kind.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "c91f4e2a7b63"
down_revision: str | Sequence[str] | None = "b81e3c7a4d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NO_BLUR_PIPELINE_CONTRACT = "edit-plan-v1.caption-v2.clean-proxy-v2.no-blur-v1"
_NO_BLUR_RENDERER_CONTRACT = "ffmpeg-renderer-v3.no-blur"
_RENDER_SPEC_SCHEMA_VERSION = "4"


def upgrade() -> None:
    """Fail closed for media not proven to use the single-layer layout."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    required_tables = {
        "render_jobs",
        "candidate_clips",
        "edit_plan_revisions",
        "pipeline_runs",
        "tasks",
    }
    if not required_tables.issubset(inspector.get_table_names()):
        return

    rows = tuple(
        bind.execute(
            sa.text(
                """
                SELECT
                    render_jobs.id AS render_id,
                    render_jobs.kind AS kind,
                    render_jobs.task_id AS task_id,
                    render_jobs.spec_json AS spec_json,
                    edit_plan_revisions.layout AS layout,
                    pipeline_runs.config_json AS config_json,
                    tasks.status AS task_status
                FROM render_jobs
                JOIN candidate_clips
                  ON candidate_clips.id = render_jobs.candidate_clip_id
                LEFT JOIN edit_plan_revisions
                  ON edit_plan_revisions.id = render_jobs.edit_plan_revision_id
                JOIN pipeline_runs
                  ON pipeline_runs.id = candidate_clips.pipeline_run_id
                LEFT JOIN tasks
                  ON tasks.id = render_jobs.task_id
                WHERE render_jobs.status <> 'stale'
                """
            )
        ).mappings()
    )
    now = datetime.now(UTC)
    stale_task_statuses: dict[str, str] = {}
    for row in rows:
        is_current_proxy = row["kind"] == "proxy" and _is_no_blur_proxy(
            row["spec_json"], row["config_json"]
        )
        uses_removed_layout = row["layout"] != "center_crop"
        if not uses_removed_layout and (row["kind"] != "proxy" or is_current_proxy):
            continue
        bind.execute(
            sa.text(
                """
                UPDATE render_jobs
                SET status = 'stale', updated_at = :updated_at
                WHERE id = :render_id AND status <> 'stale'
                """
            ),
            {"render_id": row["render_id"], "updated_at": now},
        )
        task_id = row["task_id"]
        task_status = row["task_status"]
        if isinstance(task_id, str) and isinstance(task_status, str):
            stale_task_statuses[task_id] = task_status

    for task_id, task_status in stale_task_statuses.items():
        if task_status == "queued":
            bind.execute(
                sa.text(
                    """
                    UPDATE tasks
                    SET status = 'cancelled',
                        cancellation_requested_at = :updated_at,
                        failure_class = 'deterministic',
                        error_code = 'RENDER_CONTRACT_STALE',
                        safe_error_message = 'Video must be regenerated without blurred background',
                        completed_at = :updated_at,
                        updated_at = :updated_at
                    WHERE id = :task_id AND status = 'queued'
                    """
                ),
                {"task_id": task_id, "updated_at": now},
            )
        elif task_status == "running":
            bind.execute(
                sa.text(
                    """
                    UPDATE tasks
                    SET cancellation_requested_at = :updated_at,
                        failure_class = 'deterministic',
                        error_code = 'RENDER_CONTRACT_STALE',
                        safe_error_message = 'Video must be regenerated without blurred background',
                        updated_at = :updated_at
                    WHERE id = :task_id AND status = 'running'
                    """
                ),
                {"task_id": task_id, "updated_at": now},
            )


def downgrade() -> None:
    """Never resurrect media that violated the current visual contract."""


def _is_no_blur_proxy(spec_value: object, config_value: object) -> bool:
    spec = _json_mapping(spec_value)
    if spec is not None:
        return (
            spec.get("schema_version") == _RENDER_SPEC_SCHEMA_VERSION
            and spec.get("renderer") == _NO_BLUR_RENDERER_CONTRACT
            and spec.get("text_mode") == "none"
        )
    config = _json_mapping(config_value)
    return config is not None and (
        config.get("edit_plan_schema_version") == _NO_BLUR_PIPELINE_CONTRACT
    )


def _json_mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, Mapping) else None
