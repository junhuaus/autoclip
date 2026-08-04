from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from contextlib import suppress


class ProcessCancelled(RuntimeError):
    """A subprocess was terminated after its owning task requested cancellation."""


def run_cancellable_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    cancel_requested: Callable[[], bool] | None = None,
    poll_seconds: float = 0.25,
) -> subprocess.CompletedProcess[str]:
    """Run an argv-only child in its own process group with bounded cancellation."""

    arguments = list(argv)
    if not arguments or not all(isinstance(value, str) and value for value in arguments):
        raise ValueError("process argv must contain nonempty strings")
    if timeout_seconds <= 0:
        raise ValueError("process timeout must be positive")
    if poll_seconds <= 0 or poll_seconds > 5:
        raise ValueError("process poll interval must be between zero and five seconds")

    process = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        start_new_session=True,
    )
    started = time.monotonic()
    partial_stdout: str | bytes | None = None
    partial_stderr: str | bytes | None = None
    try:
        while True:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                return subprocess.CompletedProcess(
                    arguments,
                    process.returncode,
                    stdout,
                    stderr,
                )
            if cancel_requested is not None and cancel_requested():
                raise ProcessCancelled("subprocess cancellation was requested")
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(
                    arguments,
                    timeout_seconds,
                    output=partial_stdout,
                    stderr=partial_stderr,
                )
            try:
                stdout, stderr = process.communicate(timeout=min(poll_seconds, remaining))
            except subprocess.TimeoutExpired as exc:
                if exc.output is not None:
                    partial_stdout = exc.output
                if exc.stderr is not None:
                    partial_stderr = exc.stderr
                continue
            return subprocess.CompletedProcess(
                arguments,
                process.returncode,
                stdout,
                stderr,
            )
    except BaseException:
        _terminate_process_group(process)
        raise


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.communicate()
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.communicate(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
