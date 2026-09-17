"""Read-only Completion presentation. Independent Workers own execution."""

from __future__ import annotations

import json
import shutil
import sys
import time
import unicodedata
from datetime import UTC, datetime

from liveclip.bootstrap import LiveClipRuntime


def fit_line(value: str, width: int) -> str:
    """Bound terminal cells and discard controls, including escape sequences."""
    result = []
    used = 0
    for character in value[:4096]:
        if unicodedata.category(character).startswith("C"):
            continue
        cells = (
            0
            if unicodedata.combining(character)
            else (2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1)
        )
        if used + cells > max(0, width):
            break
        result.append(character)
        used += cells
    return "".join(result)


def observation(runtime: LiveClipRuntime, intent_id: str, actor: str) -> dict[str, object]:
    goal = runtime.completion_service.get(intent_id, actor_user_id=actor)
    project = runtime.pipeline_service.get_project(goal.project_id, user_id=actor)
    run = runtime.pipeline_service.get_run(goal.run_id)
    result: dict[str, object] = {
        "Project ID": goal.project_id,
        "Pipeline run ID": goal.run_id,
        "Completion intent ID": goal.intent_id,
        "status": goal.status.value,
        "outcome": goal.outcome.value if goal.outcome else None,
        "blocking_code": goal.blocking_code,
        "error": fit_line(goal.safe_error_message or "", 240),
        "stages": [
            {
                "stage": stage.stage,
                "status": stage.status.value,
                "completed": stage.completed_units,
                "total": stage.total_units,
                "unit": stage.unit_label,
                "activity_count": stage.activity_count,
            }
            for stage in run.stages
        ],
    }
    if project.current_run_id != goal.run_id or project.generation != goal.generation:
        result["notice"] = "Stale generation; this goal cannot advance the current Project."
    elif goal.status.value == "waiting_selection":
        result["notice"] = "Manual selection required: submit an authorized selection explicitly."
    elif goal.status.value in {"queued", "waiting_work"}:
        result["notice"] = (
            "Waiting for independent work. Start liveclip worker in another terminal."
        )
    elif goal.status.value == "cancelled":
        result["notice"] = "Goal cancelled; no new package was produced."
    elif goal.outcome and goal.outcome.value == "no_eligible_clips":
        result["notice"] = "No eligible candidates; no Delivery package."
    elif goal.outcome and goal.outcome.value == "no_selected_clips":
        result["notice"] = "No clips selected; no Delivery package."
    elif goal.blocking_code == "COORDINATION_RETRIES_EXHAUSTED":
        result["notice"] = "Worker retry budget exhausted; observation cannot reset retries."
    elif goal.status.value == "needs_action":
        result["notice"] = (
            f"Goal blocked: {goal.blocking_code or 'action required'}. "
            "Repair the blocker, then explicitly resume this Project."
        )
    heartbeat = run.active_task_heartbeat_at
    result["worker_heartbeat"] = heartbeat.isoformat() if heartbeat else None
    lease = run.active_task_lease_expires_at
    result["worker_lease_fresh"] = bool(lease and lease > datetime.now(UTC))
    if goal.delivery_progress:
        result["delivery"] = goal.delivery_progress.model_dump(mode="json")
    if (
        goal.status.value == "succeeded"
        and goal.outcome
        and goal.outcome.value == "delivered"
        and goal.delivery_id
    ):
        delivery = runtime.delivery_service.get(goal.delivery_id)
        if (
            delivery.project_id == goal.project_id
            and delivery.status.value == "succeeded"
            and delivery.zip_asset_id
        ):
            archive = runtime.media_asset_service.resolve(
                delivery.zip_asset_id, required_kind="delivery_zip"
            )
            if archive.project_id == goal.project_id:
                result["Delivery ZIP"] = str(archive.path)
    # Authority may have changed while reading stages or verifying the archive.
    runtime.completion_service.get(intent_id, actor_user_id=actor)
    return result


def business_identity(record: dict[str, object]) -> str:
    """Heartbeats can refresh the display without emitting another pipe record."""
    stable = dict(record)
    stable.pop("worker_heartbeat", None)
    stable.pop("worker_lease_fresh", None)
    delivery = stable.get("delivery")
    if isinstance(delivery, dict):
        stable["delivery"] = {
            key: value
            for key, value in delivery.items()
            if key not in {"worker_heartbeat_at", "lease_fresh"}
        }
    return json.dumps(stable, ensure_ascii=False, sort_keys=True)


def terminal_lines(record: dict[str, object]) -> list[str]:
    lines = [
        f"Goal: {record['Completion intent ID']}",
        f"Status: {record['status']} / {record['outcome']}",
    ]
    if record.get("notice"):
        lines.append(str(record["notice"]))
    if record.get("blocking_code"):
        lines.append(f"{record['blocking_code']}: {record['error']}")
    if record.get("Delivery ZIP"):
        lines.append(f"Delivery ZIP: {record['Delivery ZIP']}")
    stages = record.get("stages")
    if isinstance(stages, list):
        for stage in stages:
            lines.append(
                f"{stage['stage']}: {stage['status']} "
                f"{stage['completed']}/{stage['total']} {stage['unit'] or ''}"
            )
    delivery = record.get("delivery")
    if isinstance(delivery, dict):
        lines.append(
            f"Delivery: {delivery['phase']} {delivery['completed']}/"
            f"{delivery['total'] if delivery['total'] is not None else '?'} "
            f"{delivery['unit'] or ''}"
        )
        lines.append(f"Business advanced: {delivery['business_advanced_at']}")
        lines.append(
            f"Heartbeat (not progress): {delivery['worker_heartbeat_at']} "
            f"lease fresh={delivery['lease_fresh']}"
        )
    else:
        lines.append(
            f"Heartbeat (not progress): {record['worker_heartbeat']} "
            f"lease fresh={record['worker_lease_fresh']}"
        )
    return lines


def observe_completion(
    runtime: LiveClipRuntime, intent_id: str, actor: str, *, watch: bool = True
) -> None:
    tty = sys.stdout.isatty() and watch
    previous = None
    final_record = None
    if tty:
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
    try:
        while True:
            record = observation(runtime, intent_id, actor)
            identity = business_identity(record)
            if tty:
                columns, rows = shutil.get_terminal_size()
                lines = terminal_lines(record)
                sys.stdout.write(
                    "\x1b[H\x1b[2J"
                    + "\n".join(fit_line(line, columns - 1) for line in lines[: max(1, rows - 1)])
                )
            elif identity != previous:
                sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            previous = identity
            if not watch or record["status"] in {
                "succeeded",
                "cancelled",
                "needs_action",
                "waiting_selection",
            }:
                final_record = record
                break
            time.sleep(2)
    except KeyboardInterrupt:
        sys.stdout.write("\nObservation stopped; saved goal and Tasks are unchanged.\n")
    finally:
        if tty:
            sys.stdout.write("\x1b[?25h\x1b[?1049l")
            if final_record is not None:
                sys.stdout.write(json.dumps(final_record, ensure_ascii=False) + "\n")
            sys.stdout.flush()
