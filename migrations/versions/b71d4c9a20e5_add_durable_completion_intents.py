"""Add durable completion goals and completion-only task deferral.

Revision ID: b71d4c9a20e5
Revises: a13f9c6d2e80

The migration connection in env.py disables SQLite FK actions before its one
BEGIN IMMEDIATE and validates every FK before commit. Ordinary batch rebuilds
with FK actions enabled can delete task attempts, Assets and invocation rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b71d4c9a20e5"
down_revision = "a13f9c6d2e80"
branch_labels = None
depends_on = None


def _task_checks(*, completion: bool) -> None:
    kinds = (
        "'stage', 'render', 'delivery', 'completion'"
        if completion
        else ("'stage', 'render', 'delivery'")
    )
    statuses = (
        "'queued', 'waiting', 'running', 'succeeded', 'failed', 'cancelled'"
        if completion
        else "'queued', 'running', 'succeeded', 'failed', 'cancelled'"
    )
    with op.batch_alter_table("tasks", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_tasks_task_kind_allowed"), type_="check")
        batch.drop_constraint(op.f("ck_tasks_task_status_allowed"), type_="check")
        if not completion:
            batch.drop_constraint(op.f("ck_tasks_completion_task_shape"), type_="check")
            batch.drop_constraint(op.f("ck_tasks_waiting_task_is_completion"), type_="check")
        batch.create_check_constraint(op.f("ck_tasks_task_kind_allowed"), f"kind IN ({kinds})")
        batch.create_check_constraint(
            op.f("ck_tasks_task_status_allowed"), f"status IN ({statuses})"
        )
        if completion:
            batch.create_check_constraint(
                op.f("ck_tasks_completion_task_shape"),
                "kind <> 'completion' OR (pipeline_run_id IS NOT NULL "
                "AND stage_run_id IS NULL AND resource_class = 'cheap')",
            )
            batch.create_check_constraint(
                op.f("ck_tasks_waiting_task_is_completion"),
                "status <> 'waiting' OR kind = 'completion'",
            )


def _attempt_check(*, completion: bool) -> None:
    outcomes = (
        "'running', 'succeeded', 'deferred', 'failed', 'cancelled', 'lost_lease'"
        if completion
        else "'running', 'succeeded', 'failed', 'cancelled', 'lost_lease'"
    )
    with op.batch_alter_table("task_attempts", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_task_attempts_attempt_outcome_allowed"), type_="check")
        batch.create_check_constraint(
            op.f("ck_task_attempts_attempt_outcome_allowed"),
            f"outcome IN ({outcomes})",
        )


def upgrade() -> None:
    _task_checks(completion=True)
    _attempt_check(completion=True)
    op.create_table(
        "completion_intents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("pipeline_run_id", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("requester_user_id", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.String(length=32), nullable=False),
        sa.Column("target", sa.String(length=20), nullable=False),
        sa.Column("selection_policy", sa.String(length=20), nullable=False),
        sa.Column("options_schema_version", sa.String(length=8), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("canonical_request_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("selection_submitted", sa.Boolean(), nullable=False),
        sa.Column("selection_checkpoint_json", sa.JSON()),
        sa.Column("render_action_keys_json", sa.JSON()),
        sa.Column("delivery_action_key", sa.String(length=160)),
        sa.Column("delivery_id", sa.String(length=32)),
        sa.Column("outcome_code", sa.String(length=40)),
        sa.Column("blocking_code", sa.String(length=80)),
        sa.Column("safe_error_message", sa.String(length=500)),
        sa.Column("cancellation_requested_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_completion_intents")),
        sa.UniqueConstraint(
            "requester_user_id",
            "idempotency_key_sha256",
            name="completion_request_identity",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_completion_intents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_run_id"],
            ["pipeline_runs.id"],
            name=op.f("fk_completion_intents_pipeline_run_id_pipeline_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_completion_intents_requester_user_id_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["workspace_users.id"],
            name=op.f("fk_completion_intents_actor_user_id_workspace_users"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "generation > 0", name=op.f("ck_completion_intents_completion_generation_positive")
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_completion_intents_completion_version_positive")
        ),
        sa.CheckConstraint(
            "target IN ('process_only', 'delivery')",
            name=op.f("ck_completion_intents_completion_target_allowed"),
        ),
        sa.CheckConstraint(
            "selection_policy IN ('default', 'manual')",
            name=op.f("ck_completion_intents_completion_selection_policy_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'waiting_work', 'waiting_selection', 'needs_action', "
            "'succeeded', 'cancelled')",
            name=op.f("ck_completion_intents_completion_status_allowed"),
        ),
        sa.CheckConstraint(
            "outcome_code IS NULL OR outcome_code IN "
            "('processed', 'delivered', 'no_eligible_clips', 'no_selected_clips', 'cancelled')",
            name=op.f("ck_completion_intents_completion_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "options_schema_version = '1'",
            name=op.f("ck_completion_intents_completion_options_schema_v1"),
        ),
        sa.CheckConstraint(
            "length(canonical_request_sha256) = 64 AND length(idempotency_key_sha256) = 64",
            name=op.f("ck_completion_intents_completion_request_hash_shape"),
        ),
        sa.CheckConstraint(
            "target <> 'process_only' OR selection_policy = 'default'",
            name=op.f("ck_completion_intents_completion_processing_selection_shape"),
        ),
        sa.CheckConstraint(
            "status <> 'waiting_selection' OR "
            "(target = 'delivery' AND selection_policy = 'manual' AND selection_submitted = 0)",
            name=op.f("ck_completion_intents_completion_manual_wait_shape"),
        ),
        sa.CheckConstraint(
            "delivery_id IS NULL OR target = 'delivery'",
            name=op.f("ck_completion_intents_completion_delivery_target_shape"),
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND outcome_code IS NOT NULL AND completed_at IS NOT NULL) "
            "OR (status = 'cancelled' AND outcome_code = 'cancelled' "
            "AND completed_at IS NOT NULL) "
            "OR (status NOT IN ('succeeded', 'cancelled') AND outcome_code IS NULL)",
            name=op.f("ck_completion_intents_completion_terminal_outcome_shape"),
        ),
    )
    op.create_index(
        "ix_completion_project_state",
        "completion_intents",
        ["project_id", "status", "created_at"],
    )
    op.create_index(
        "ix_completion_run_state",
        "completion_intents",
        ["pipeline_run_id", "status"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    active = connection.exec_driver_sql("SELECT COUNT(*) FROM completion_intents").scalar_one()
    completion_tasks = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM tasks WHERE kind='completion' OR status='waiting'"
    ).scalar_one()
    deferred = connection.exec_driver_sql(
        "SELECT COUNT(*) FROM task_attempts WHERE outcome='deferred'"
    ).scalar_one()
    if active or completion_tasks or deferred:
        raise RuntimeError("cannot downgrade durable completion history; restore a backup")
    op.drop_index("ix_completion_run_state", table_name="completion_intents")
    op.drop_index("ix_completion_project_state", table_name="completion_intents")
    op.drop_table("completion_intents")
    _attempt_check(completion=False)
    _task_checks(completion=False)
