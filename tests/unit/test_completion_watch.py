from __future__ import annotations

import io
from typing import Any

import pytest

from liveclip.cli import completion_watch


def test_terminal_width_and_untrusted_controls() -> None:
    assert completion_watch.fit_line("中文abcd", 5) == "中文a"
    assert completion_watch.fit_line("中文abcd", 2) == "中"
    assert completion_watch.fit_line("中文abcd", 0) == ""
    assert "\x1b" not in completion_watch.fit_line("\x1b[2J\n错误" * 1000, 30)
    assert completion_watch.fit_line("e\u0301a", 1) == "e\u0301"


def test_heartbeat_does_not_emit_business_advancement() -> None:
    first: dict[str, object] = {
        "status": "waiting_work",
        "worker_heartbeat": "one",
        "worker_lease_fresh": True,
        "delivery": {
            "phase": "writing_zip",
            "completed": 10,
            "total": None,
            "worker_heartbeat_at": "one",
            "lease_fresh": True,
        },
    }
    second = dict(first, worker_heartbeat="two", worker_lease_fresh=False)
    second["delivery"] = {
        "phase": "writing_zip",
        "completed": 10,
        "total": None,
        "worker_heartbeat_at": "two",
        "lease_fresh": False,
    }
    assert completion_watch.business_identity(first) == completion_watch.business_identity(second)
    second["delivery"] = {"phase": "writing_zip", "completed": 11, "total": None}
    assert completion_watch.business_identity(first) != completion_watch.business_identity(second)


def test_pipe_deduplicates_and_interrupt_only_stops_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    calls = 0

    def observe(*args: Any) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return {"status": "queued", "worker_heartbeat": str(calls)}

    monkeypatch.setattr(completion_watch.sys, "stdout", output)
    monkeypatch.setattr(completion_watch, "observation", observe)
    monkeypatch.setattr(completion_watch.time, "sleep", lambda _: None)
    completion_watch.observe_completion(None, "goal", "actor")  # type: ignore[arg-type]
    assert output.getvalue().count('"status": "queued"') == 1
    assert "Tasks are unchanged" in output.getvalue()
    assert "\x1b" not in output.getvalue()


@pytest.mark.parametrize("failure", [KeyboardInterrupt, RuntimeError])
def test_tty_resize_bounds_redraw_and_always_restores_terminal(
    monkeypatch: pytest.MonkeyPatch,
    failure: type[BaseException],
) -> None:
    import os
    import unicodedata

    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    output = Terminal()
    dimensions = iter([os.terminal_size((12, 4)), os.terminal_size((80, 24))])
    calls = 0

    def observe(*args: Any) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise failure()
        return {
            "Completion intent ID": "中文目标" * 100,
            "status": "queued",
            "outcome": None,
            "blocking_code": "ERROR",
            "error": "\x1b[2J错误\n" * 1000,
            "worker_heartbeat": str(calls),
            "worker_lease_fresh": False,
        }

    monkeypatch.setattr(completion_watch.sys, "stdout", output)
    monkeypatch.setattr(completion_watch, "observation", observe)
    monkeypatch.setattr(completion_watch.shutil, "get_terminal_size", lambda: next(dimensions))
    monkeypatch.setattr(completion_watch.time, "sleep", lambda seconds: None)
    if failure is RuntimeError:
        with pytest.raises(RuntimeError):
            completion_watch.observe_completion(None, "goal", "actor")
    else:
        completion_watch.observe_completion(None, "goal", "actor")
    rendered = output.getvalue()
    assert rendered.startswith("\x1b[?1049h\x1b[?25l")
    assert rendered.endswith("\x1b[?25h\x1b[?1049l")
    frames = rendered.split("\x1b[H\x1b[2J")[1:]
    narrow = frames[0].splitlines()
    assert len(narrow) <= 3
    assert all(
        sum(2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1 for c in line) <= 11
        for line in narrow
    )
    assert len(rendered) < 1000
    assert rendered.count("\x1b[2J") == 2


def test_phase_local_unknown_total_has_no_percent_or_eta() -> None:
    record = {
        "Completion intent ID": "goal",
        "status": "waiting_work",
        "outcome": None,
        "delivery": {
            "phase": "writing_zip",
            "completed": 17,
            "total": None,
            "unit": "bytes",
            "business_advanced_at": "one",
            "worker_heartbeat_at": "two",
            "lease_fresh": True,
        },
    }
    rendered = "\n".join(completion_watch.terminal_lines(record))
    assert "writing_zip 17/? bytes" in rendered
    assert "Heartbeat (not progress)" in rendered
    assert "%" not in rendered and "ETA" not in rendered


@pytest.mark.parametrize(
    ("status", "outcome", "code", "generation", "notice"),
    [
        ("succeeded", "no_eligible_clips", None, 1, "No eligible candidates"),
        ("succeeded", "no_selected_clips", None, 1, "No clips selected"),
        ("cancelled", "cancelled", None, 1, "Goal cancelled"),
        ("waiting_selection", None, None, 1, "Manual selection required"),
        ("needs_action", None, "COORDINATION_RETRIES_EXHAUSTED", 1, "retry budget exhausted"),
        ("queued", None, None, 2, "Stale generation"),
        ("queued", None, None, 1, "Start liveclip worker"),
    ],
)
def test_non_delivered_outcomes_are_distinct_and_never_resolve_a_package(
    status: str,
    outcome: str | None,
    code: str | None,
    generation: int,
    notice: str,
) -> None:
    from types import SimpleNamespace

    goal = SimpleNamespace(
        project_id="project",
        run_id="run",
        intent_id="intent",
        generation=1,
        status=SimpleNamespace(value=status),
        outcome=SimpleNamespace(value=outcome) if outcome else None,
        blocking_code=code,
        safe_error_message="",
        delivery_progress=None,
        options=SimpleNamespace(selection_policy=SimpleNamespace(value="default")),
    )
    checks = []

    def get(*args: Any, **kwargs: Any) -> object:
        checks.append(kwargs["actor_user_id"])
        return goal

    runtime = SimpleNamespace(
        completion_service=SimpleNamespace(get=get),
        pipeline_service=SimpleNamespace(
            get_project=lambda *args, **kwargs: SimpleNamespace(
                current_run_id="run",
                generation=generation,
            ),
            get_run=lambda _: SimpleNamespace(
                stages=[],
                active_task_heartbeat_at=None,
                active_task_lease_expires_at=None,
            ),
        ),
    )
    record = completion_watch.observation(runtime, "intent", "owner")
    assert notice in record["notice"]
    assert "Delivery ZIP" not in record
    assert checks == ["owner", "owner"]
