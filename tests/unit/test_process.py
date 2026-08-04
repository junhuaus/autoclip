from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

import liveclip.media.process as process_module
from liveclip.media.process import ProcessCancelled, run_cancellable_process


def test_process_runner_uses_argv_without_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FinishedProcess:
        pid = 12345
        returncode = 0

        def poll(self) -> int:
            return 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            del timeout
            return "stdout", "stderr"

    def fake_popen(argv: list[str], **kwargs: object) -> FinishedProcess:
        observed["argv"] = argv
        observed.update(kwargs)
        return FinishedProcess()

    monkeypatch.setattr(process_module.subprocess, "Popen", fake_popen)

    result = run_cancellable_process(["ffmpeg", "-version"], timeout_seconds=10)

    assert result.returncode == 0
    assert observed["argv"] == ["ffmpeg", "-version"]
    assert observed["shell"] is False
    assert observed["start_new_session"] is True
    assert observed["stdin"] == subprocess.DEVNULL


def test_process_runner_terminates_a_running_child_on_cancel(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"
    cancel_at = time.monotonic() + 0.15

    started = time.monotonic()
    with pytest.raises(ProcessCancelled, match="cancellation"):
        run_cancellable_process(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,time;"
                    "time.sleep(30);"
                    f"pathlib.Path({str(marker)!r}).write_text('late')"
                ),
            ],
            timeout_seconds=10,
            cancel_requested=lambda: time.monotonic() >= cancel_at,
            poll_seconds=0.05,
        )

    assert time.monotonic() - started < 3
    assert not marker.exists()


def test_process_timeout_preserves_partial_stderr() -> None:
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_cancellable_process(
            [
                sys.executable,
                "-c",
                (
                    "import sys,time;"
                    "sys.stderr.write('progress-marker\\n');"
                    "sys.stderr.flush();"
                    "time.sleep(30)"
                ),
            ],
            timeout_seconds=0.2,
            poll_seconds=0.05,
        )

    stderr = caught.value.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8")
    assert stderr is not None and "progress-marker" in stderr
    assert time.monotonic() - started < 3
