from __future__ import annotations

import pickle
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

import liveclip.media.process as process_module
from liveclip.media.process import ProcessCancelled, run_cancellable_process


def test_process_runner_bounds_stdout_head_and_stderr_tail() -> None:
    result = run_cancellable_process(
        [
            sys.executable,
            "-c",
            (
                "import os;"
                "chunk=b'x'*65536;"
                "[os.write(1,chunk) for _ in range(256)];"
                "os.write(1,b'stdout-final-marker');"
                "[os.write(2,chunk) for _ in range(256)];"
                "os.write(2,b'stderr-final-marker')"
            ),
        ],
        timeout_seconds=10,
        poll_seconds=0.01,
    )

    assert result.returncode == 0
    assert len(result.stdout.encode()) <= process_module._MAX_STDOUT_BYTES
    assert result.stdout.startswith("x")
    assert "[liveclip: stdout truncated]" in result.stdout
    assert "stdout-final-marker" not in result.stdout
    assert len(result.stderr.encode()) <= process_module._MAX_STDERR_BYTES
    assert result.stderr.startswith("[liveclip: stderr truncated]")
    assert result.stderr.endswith("stderr-final-marker")


def test_process_start_observer_distinguishes_missing_executable(tmp_path: Path) -> None:
    starts = []
    with pytest.raises(FileNotFoundError):
        run_cancellable_process(
            [str(tmp_path / "missing-executable")],
            timeout_seconds=5,
            on_started=lambda: starts.append(True),
        )
    assert not starts


def test_process_start_observer_survives_post_launch_pipe_error(monkeypatch) -> None:
    starts = []
    read = process_module._PipeReader._read

    def failing_reader(self):
        if self._thread.name.endswith("stdout"):
            try:
                assert self._stream.read(1) == b"x"
                self._error = OSError("synthetic post-launch pipe error")
            finally:
                self._done.set()
        else:
            read(self)

    monkeypatch.setattr(process_module._PipeReader, "_read", failing_reader)
    with pytest.raises(OSError, match="synthetic post-launch"):
        run_cancellable_process(
            [sys.executable, "-u", "-c", "import time;print('x');time.sleep(30)"],
            timeout_seconds=5,
            poll_seconds=0.01,
            on_started=lambda: starts.append(True),
        )
    assert starts == [True]


def test_failed_start_observer_terminates_its_launched_process(monkeypatch) -> None:
    processes = []
    popen = subprocess.Popen

    def track(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    def fail():
        raise RuntimeError("synthetic observer failure")

    monkeypatch.setattr(process_module.subprocess, "Popen", track)
    with pytest.raises(RuntimeError, match="synthetic observer"):
        run_cancellable_process(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            timeout_seconds=5,
            on_started=fail,
        )
    assert len(processes) == 1 and processes[0].poll() is not None


def test_process_timeout_preserves_bounded_stdout_and_stderr_evidence() -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_cancellable_process(
            [
                sys.executable,
                "-c",
                (
                    "import os,time;"
                    "os.write(1,b'probe-json-prefix');"
                    "os.write(2,b'ffmpeg-progress-tail');"
                    "time.sleep(30)"
                ),
            ],
            timeout_seconds=0.2,
            poll_seconds=0.01,
        )

    assert caught.value.stdout == "probe-json-prefix"
    assert caught.value.stderr == "ffmpeg-progress-tail"
    assert len(caught.value.stdout.encode()) <= process_module._MAX_STDOUT_BYTES
    assert len(caught.value.stderr.encode()) <= process_module._MAX_STDERR_BYTES
    assert time.monotonic() - started < 3


def test_process_timeout_counts_wall_time_when_monotonic_clock_stalls(monkeypatch) -> None:
    real_monotonic = time.monotonic
    frozen = real_monotonic()
    monkeypatch.setattr(process_module.time, "monotonic", lambda: frozen)

    started = real_monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_cancellable_process(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            timeout_seconds=0.2,
            poll_seconds=0.01,
        )

    assert real_monotonic() - started < 3


def _wall_clock_jump(
    monkeypatch: pytest.MonkeyPatch, *, wall_jump: float, monotonic_jump: float = 0.0
) -> Any:
    """Advance the clocks once the runner has started its deadline bookkeeping.

    The jump is armed by the first cancellation poll, which runs after both start
    times were read, so it models a host that slept during the request.
    """

    real_time = time.time
    real_monotonic = time.monotonic
    state = {"armed": False}
    monkeypatch.setattr(
        process_module.time, "time", lambda: real_time() + (wall_jump if state["armed"] else 0)
    )
    monkeypatch.setattr(
        process_module.time,
        "monotonic",
        lambda: real_monotonic() + (monotonic_jump if state["armed"] else 0),
    )

    def cancel_requested() -> bool:
        state["armed"] = True
        return False

    return cancel_requested


def test_process_timeout_after_system_sleep_is_classified_as_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 16: the wall clock ran 120 s ahead of the monotonic clock, and only the
    wall-clock deadline fired, so the host slept through the child."""

    cancel_requested = _wall_clock_jump(monkeypatch, wall_jump=120.0)
    started = time.perf_counter()
    with pytest.raises(process_module.ProcessInterruptedBySleep) as caught:
        run_cancellable_process(
            [sys.executable, "-c", "import os,time;os.write(2,b'partial');time.sleep(30)"],
            timeout_seconds=60,
            poll_seconds=0.01,
            cancel_requested=cancel_requested,
        )

    error = caught.value
    # Still a TimeoutExpired, so every existing caller keeps its timeout semantics.
    assert isinstance(error, subprocess.TimeoutExpired)
    assert error.timeout == 60
    assert error.wall_elapsed_seconds >= 120
    assert error.monotonic_elapsed_seconds < 60
    assert 60 < error.suspended_seconds <= 125
    assert "host was suspended" in str(error)
    assert time.perf_counter() - started < 15
    restored = pickle.loads(pickle.dumps(error))
    assert type(restored) is process_module.ProcessInterruptedBySleep
    assert restored.suspended_seconds == error.suspended_seconds


def test_process_wall_clock_timeout_below_the_sleep_gap_stays_a_plain_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_requested = _wall_clock_jump(monkeypatch, wall_jump=45.0)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_cancellable_process(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            timeout_seconds=40,
            poll_seconds=0.01,
            cancel_requested=cancel_requested,
        )
    assert type(caught.value) is subprocess.TimeoutExpired


def test_process_timeout_whose_monotonic_budget_is_spent_is_not_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large wall-clock lead does not hide a genuine timeout: the monotonic clock
    alone had already used the whole budget."""

    cancel_requested = _wall_clock_jump(monkeypatch, wall_jump=1_200.0, monotonic_jump=1_000.0)
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_cancellable_process(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            timeout_seconds=600,
            poll_seconds=0.01,
            cancel_requested=cancel_requested,
        )
    assert type(caught.value) is subprocess.TimeoutExpired


def test_process_real_timeout_is_a_plain_timeout() -> None:
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_cancellable_process(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            timeout_seconds=0.2,
            poll_seconds=0.01,
        )
    assert type(caught.value) is subprocess.TimeoutExpired


def test_process_runner_terminates_process_group_on_cancellation(tmp_path: Path) -> None:
    marker = tmp_path / "late-grandchild-output"
    cancel_at = time.monotonic() + 0.15

    with pytest.raises(ProcessCancelled, match="cancellation"):
        run_cancellable_process(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess,sys,time;"
                    "subprocess.Popen([sys.executable,'-c',"
                    f'"import pathlib,time;time.sleep(0.5);pathlib.Path({str(marker)!r})'
                    ".write_text('late')\"]);"
                    "time.sleep(30)"
                ),
            ],
            timeout_seconds=10,
            cancel_requested=lambda: time.monotonic() >= cancel_at,
            poll_seconds=0.01,
        )

    time.sleep(0.6)
    assert not marker.exists()


def test_process_runner_uses_literal_argv_and_disables_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    observed: dict[str, Any] = {}

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        observed.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(process_module.subprocess, "Popen", recording_popen)
    literal = "value; echo shell-was-used"
    result = run_cancellable_process(
        [sys.executable, "-c", "import sys;print(sys.argv[1])", literal],
        timeout_seconds=10,
    )

    assert result.stdout.strip() == literal
    assert observed["shell"] is False
    assert observed["start_new_session"] is True
    assert observed["stdin"] == subprocess.DEVNULL


def test_process_runner_accepts_explicit_stdin_and_bounded_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    observed: dict[str, Any] = {}

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        observed.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(process_module.subprocess, "Popen", recording_popen)
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("untrusted transcript", encoding="utf-8")
    with prompt_path.open("rb") as prompt_stream:
        result = run_cancellable_process(
            [
                sys.executable,
                "-c",
                "import os,sys;print(sys.stdin.read());print(os.environ.get('SAFE_VALUE'))",
            ],
            timeout_seconds=10,
            stdin_stream=prompt_stream,
            env={"SAFE_VALUE": "bounded"},
        )

    assert result.stdout.splitlines() == ["untrusted transcript", "bounded"]
    assert observed["stdin"] is not subprocess.DEVNULL
    assert observed["env"] == {"SAFE_VALUE": "bounded"}
    assert observed["shell"] is False
