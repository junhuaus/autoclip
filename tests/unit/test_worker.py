from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from liveclip import worker
from liveclip.application.completion_runner import ReconciliationResult
from liveclip.config import Settings
from liveclip.media.process import run_cancellable_process
from liveclip.worker import WorkerShutdown, worker_signal_handlers


def dispatch_runtime(monkeypatch, outcomes, *, stop_after=None):
    calls = []
    runtime = MagicMock()
    runtime.__enter__.return_value = runtime

    def category(index):
        def run(**kwargs):
            if stop_after is not None and len(calls) == stop_after:
                raise WorkerShutdown(signal.SIGTERM)
            calls.append(index)
            return ReconciliationResult(outcomes[index])

        return run

    for index, name in enumerate(("stage", "render", "delivery", "completion")):
        run = category(index)
        setattr(runtime, f"{name}_runner", SimpleNamespace(run_one=run, run_once=run))
    monkeypatch.setattr(worker.LiveClipRuntime, "open", lambda settings: runtime)
    return runtime, calls


def test_continuous_backlogs_rotate_within_four_handled_rounds(monkeypatch):
    runtime, calls = dispatch_runtime(monkeypatch, ["deferred"] * 4, stop_after=12)
    assert worker.run_worker(Settings(_env_file=None)) == 128 + signal.SIGTERM
    assert calls == [0, 1, 2, 3] * 3
    runtime.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "outcomes,expected",
    [
        (["busy", "idle", "busy", "deferred"], [0, 1, 2, 3]),
        (["idle"] * 4, [0, 1, 2, 3]),
        (["busy", "processed", "processed", "processed"], [0, 1]),
    ],
)
def test_once_is_one_bounded_round(monkeypatch, outcomes, expected):
    _, calls = dispatch_runtime(monkeypatch, outcomes)
    assert worker.run_worker(Settings(_env_file=None), once=True) == 0
    assert calls == expected


def test_unhandled_round_sleeps_and_preserves_cursor(monkeypatch):
    _, calls = dispatch_runtime(monkeypatch, ["busy", "idle", "busy", "idle"], stop_after=8)
    waits = []
    monkeypatch.setattr(worker.threading, "Event", lambda: SimpleNamespace(wait=waits.append))
    assert worker.run_worker(Settings(_env_file=None), poll_seconds=0.25) == 128 + signal.SIGTERM
    assert calls == [0, 1, 2, 3] * 2
    assert waits == [0.25, 0.25]


def test_completion_busy_continues_to_stage_in_same_round(monkeypatch):
    _, calls = dispatch_runtime(monkeypatch, ["processed"] * 3 + ["busy"], stop_after=8)
    assert worker.run_worker(Settings(_env_file=None)) == 128 + signal.SIGTERM
    assert calls == [0, 1, 2, 3, 0, 1, 2, 3]


def test_idle_round_preserves_nonzero_cursor(monkeypatch):
    outcomes = ["processed", "idle", "busy", "idle"]
    runtime, calls = dispatch_runtime(monkeypatch, outcomes, stop_after=9)
    original = runtime.stage_runner.run_one

    def stage(**kwargs):
        result = original(**kwargs)
        outcomes[0] = "idle"
        return result

    runtime.stage_runner.run_one = stage
    waits = []
    monkeypatch.setattr(worker.threading, "Event", lambda: SimpleNamespace(wait=waits.append))
    assert worker.run_worker(Settings(_env_file=None), poll_seconds=0.25) == 128 + signal.SIGTERM
    assert calls == [0, 1, 2, 3, 0, 1, 2, 3, 0]
    assert waits == [0.25, 0.25]


def test_worker_overrides_background_shell_ignored_sigint_and_restores_it() -> None:
    original = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        with worker_signal_handlers():
            assert signal.getsignal(signal.SIGINT) is not signal.SIG_IGN
        assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
    finally:
        signal.signal(signal.SIGINT, original)


def test_worker_signal_unwinds_and_kills_owned_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "orphan-grandchild-output"
    marker_expression = f"pathlib.Path({str(marker)!r})"
    grandchild = f"import pathlib,time;time.sleep(0.6);{marker_expression}.write_text('orphan')"
    parent = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{grandchild!r}]);"
        "time.sleep(30)"
    )
    original = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    timer = threading.Timer(0.15, os.kill, args=(os.getpid(), signal.SIGINT))
    try:
        with worker_signal_handlers():
            timer.start()
            with pytest.raises(WorkerShutdown) as caught:
                run_cancellable_process(
                    [
                        sys.executable,
                        "-c",
                        parent,
                    ],
                    timeout_seconds=3,
                    poll_seconds=0.01,
                )
            assert caught.value.signal_number == signal.SIGINT
    finally:
        timer.cancel()
        timer.join(timeout=1)
        signal.signal(signal.SIGINT, original)

    time.sleep(0.8)
    assert not marker.exists()
