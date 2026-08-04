from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path

import pytest

from liveclip.media.process import run_cancellable_process
from liveclip.worker import WorkerShutdown, worker_signal_handlers


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
