"""stale legacy text-bearing review proxies

Revision ID: b81e3c7a4d20
Revises: e7b14c2d9a60
Create Date: 2026-08-11 12:10:00.000000

Review proxies became deliberately text-free in the clean-proxy-v1 contract.
Legacy succeeded rows must not remain visible as if they satisfied that promise.
Manual render rows prove the contract through spec_json; pipeline-stage rows from
older schemas stored no spec_json and are therefore fenced by their immutable
Pipeline config contract.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "b81e3c7a4d20"
down_revision: str | Sequence[str] | None = "e7b14c2d9a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLEAN_PIPELINE_CONTRACT = "edit-plan-v1.caption-v2.clean-proxy-v1"


def upgrade() -> None:
    """Fail closed for every proxy whose no-text render contract is ambiguous."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    required_tables = {"render_jobs", "candidate_clips", "pipeline_runs", "tasks"}
    if not required_tables.issubset(inspector.get_table_names()):
        # Narrow development databases stamped at an intermediate revision may
        # contain only the table under repair. They cannot expose a review API
        # without the current Pipeline/Task schema and therefore have no row we
        # can safely classify here.
        return

    rows = tuple(
        bind.execute(
            sa.text(
                """
                SELECT
                    render_jobs.id AS render_id,
                    render_jobs.task_id AS task_id,
                    render_jobs.spec_json AS spec_json,
                    pipeline_runs.config_json AS config_json,
                    tasks.status AS task_status
                FROM render_jobs
                JOIN candidate_clips
                  ON candidate_clips.id = render_jobs.candidate_clip_id
                JOIN pipeline_runs
                  ON pipeline_runs.id = candidate_clips.pipeline_run_id
                LEFT JOIN tasks
                  ON tasks.id = render_jobs.task_id
                WHERE render_jobs.kind = 'proxy'
                  AND render_jobs.status <> 'stale'
                """
            )
        ).mappings()
    )
    now = datetime.now(UTC)
    stale_task_statuses: dict[str, str] = {}
    for row in rows:
        if _is_clean_proxy(row["spec_json"], row["config_json"]):
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
                        safe_error_message = 'Review proxy must be regenerated without text',
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
                        safe_error_message = 'Review proxy must be regenerated without text',
                        updated_at = :updated_at
                    WHERE id = :task_id AND status = 'running'
                    """
                ),
                {"task_id": task_id, "updated_at": now},
            )


def downgrade() -> None:
    """Do not resurrect media whose visual contract was already invalidated."""


def _is_clean_proxy(spec_value: object, config_value: object) -> bool:
    spec = _json_mapping(spec_value)
    if spec is not None:
        return (
            spec.get("schema_version") == "3"
            and spec.get("renderer") == "ffmpeg-renderer-v2"
            and spec.get("text_mode") == "none"
        )
    config = _json_mapping(config_value)
    return config is not None and (
        config.get("edit_plan_schema_version") == _CLEAN_PIPELINE_CONTRACT
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
