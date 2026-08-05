from __future__ import annotations

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
