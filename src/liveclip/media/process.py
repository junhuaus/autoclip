from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from typing import BinaryIO, Literal

_READ_CHUNK_BYTES = 64 * 1024
_MAX_STDOUT_BYTES = 4 * 1024 * 1024
_MAX_STDERR_BYTES = 256 * 1024
_TERMINATE_GRACE_SECONDS = 5.0
_KILL_GRACE_SECONDS = 5.0


class ProcessCancelled(RuntimeError):
    """A subprocess was terminated after its owning task requested cancellation."""


# A wall-clock lead over the monotonic clock beyond this many seconds at the time
# a timeout fires means the host was suspended (system sleep) while the child was
# running, not that the child used its whole budget.
SLEEP_DETECTION_GAP_SECONDS = 60.0


class ProcessInterruptedBySleep(subprocess.TimeoutExpired):
    """The wall-clock deadline expired while the host was suspended.

    A subclass of ``TimeoutExpired`` so every existing caller keeps its timeout
    semantics; a caller that can tell the two apart catches this class first.
    Raised only when the monotonic budget was *not* exhausted and the wall clock
    ran more than ``SLEEP_DETECTION_GAP_SECONDS`` ahead of the monotonic clock.
    """

    def __init__(
        self,
        cmd: Sequence[str],
        timeout: float,
        *,
        wall_elapsed_seconds: float = 0.0,
        monotonic_elapsed_seconds: float = 0.0,
        output: str | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(cmd, timeout, output=output, stderr=stderr)
        self.wall_elapsed_seconds = wall_elapsed_seconds
        self.monotonic_elapsed_seconds = monotonic_elapsed_seconds

    @property
    def suspended_seconds(self) -> float:
        return max(0.0, self.wall_elapsed_seconds - self.monotonic_elapsed_seconds)

    def __str__(self) -> str:
        return (
            f"Command timed out after {self.timeout} seconds of wall-clock time while the "
            f"host was suspended for about {round(self.suspended_seconds)} seconds"
        )


class _BoundedCapture:
    """Continuously drain one pipe while retaining only a bounded prefix or tail."""

    def __init__(self, *, maximum_bytes: int, retain: Literal["head", "tail"], label: str):
        self._maximum_bytes = maximum_bytes
        self._retain = retain
        self._marker = f"[liveclip: {label} truncated]\n".encode()
        self._buffer = bytearray()
        self._truncated = False
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            if self._retain == "head":
                available = self._maximum_bytes - len(self._buffer)
                if available > 0:
                    self._buffer.extend(chunk[:available])
                if len(chunk) > available:
                    self._truncated = True
                return

            combined_size = len(self._buffer) + len(chunk)
            if combined_size > self._maximum_bytes:
                self._truncated = True
                if len(chunk) >= self._maximum_bytes:
                    self._buffer[:] = chunk[-self._maximum_bytes :]
                    return
                overflow = combined_size - self._maximum_bytes
                del self._buffer[:overflow]
            self._buffer.extend(chunk)

    def text(self) -> str:
        with self._lock:
            payload = bytes(self._buffer)
            truncated = self._truncated
        if truncated:
            retained_bytes = max(0, self._maximum_bytes - len(self._marker))
            if self._retain == "head":
                payload = payload[:retained_bytes] + self._marker
            else:
                payload = self._marker + payload[-retained_bytes:]
        return payload.decode("utf-8", errors="replace")


class _PipeReader:
    def __init__(self, stream: BinaryIO, capture: _BoundedCapture, *, name: str):
        self._stream = stream
        self._capture = capture
        self._done = threading.Event()
        self._error: OSError | None = None
        self._thread = threading.Thread(target=self._read, name=name, daemon=True)

    @property
    def done(self) -> bool:
        return self._done.is_set()

    @property
    def error(self) -> OSError | None:
        return self._error

    def start(self) -> None:
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    def _read(self) -> None:
        try:
            descriptor = self._stream.fileno()
            while chunk := os.read(descriptor, _READ_CHUNK_BYTES):
                self._capture.append(chunk)
        except OSError as exc:
            self._error = exc
        finally:
            self._done.set()


def run_cancellable_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    cancel_requested: Callable[[], bool] | None = None,
    poll_seconds: float = 0.25,
    pass_fds: Sequence[int] = (),
    stdin_stream: BinaryIO | None = None,
    env: Mapping[str, str] | None = None,
    on_started: Callable[[], None] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an argv-only child with bounded output, timeout, and cancellation."""

    arguments = list(argv)
    if not arguments or not all(isinstance(value, str) and value for value in arguments):
        raise ValueError("process argv must contain nonempty strings")
    if timeout_seconds <= 0:
        raise ValueError("process timeout must be positive")
    if poll_seconds <= 0 or poll_seconds > 5:
        raise ValueError("process poll interval must be between zero and five seconds")
    inherited_fds = tuple(pass_fds)
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in inherited_fds
    ):
        raise ValueError("inherited file descriptors must be nonnegative integers")
    if len(set(inherited_fds)) != len(inherited_fds):
        raise ValueError("inherited file descriptors must be unique")

    process = subprocess.Popen(
        arguments,
        stdin=stdin_stream if stdin_stream is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        text=False,
        shell=False,
        start_new_session=True,
        pass_fds=inherited_fds,
        env=dict(env) if env is not None else None,
        cwd=cwd,
    )
    if on_started is not None:
        try:
            on_started()
        except BaseException:
            try:
                _terminate_process_group(process)
            finally:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            raise
    stdout_pipe = getattr(process, "stdout", None)
    stderr_pipe = getattr(process, "stderr", None)
    if stdout_pipe is None or stderr_pipe is None:
        # Real Popen instances always expose both requested pipes. This narrow
        # compatibility path supports completed Popen protocol doubles without
        # weakening the production runner's bounded pipe handling.
        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(
            arguments,
            process.returncode,
            _decode_output(stdout),
            _decode_output(stderr),
        )

    stdout_capture = _BoundedCapture(
        maximum_bytes=_MAX_STDOUT_BYTES,
        retain="head",
        label="stdout",
    )
    stderr_capture = _BoundedCapture(
        maximum_bytes=_MAX_STDERR_BYTES,
        retain="tail",
        label="stderr",
    )
    readers = (
        _PipeReader(stdout_pipe, stdout_capture, name="liveclip-process-stdout"),
        _PipeReader(stderr_pipe, stderr_capture, name="liveclip-process-stderr"),
    )
    for reader in readers:
        reader.start()

    started = time.monotonic()
    wall_started = time.time()
    try:
        while process.poll() is None or not all(reader.done for reader in readers):
            for reader in readers:
                if reader.error is not None:
                    raise reader.error
            if cancel_requested is not None and cancel_requested():
                _terminate_process_group(process)
                _join_readers(readers)
                raise ProcessCancelled("subprocess cancellation was requested")
            # Some macOS monotonic clocks do not advance for the full duration
            # of system sleep. A provider request started before sleep must not
            # receive a fresh timeout budget after wake, so enforce the larger
            # of monotonic and wall-clock elapsed time. A backwards wall-clock
            # correction cannot weaken the monotonic deadline.
            monotonic_elapsed = time.monotonic() - started
            wall_elapsed = time.time() - wall_started
            elapsed = max(monotonic_elapsed, wall_elapsed)
            remaining = timeout_seconds - elapsed
            if remaining <= 0:
                _terminate_process_group(process)
                _join_readers(readers)
                # Only the wall-clock deadline fired and the wall clock ran far
                # ahead of the monotonic clock: the host slept through the call.
                if (
                    monotonic_elapsed < timeout_seconds
                    and wall_elapsed - monotonic_elapsed > SLEEP_DETECTION_GAP_SECONDS
                ):
                    raise ProcessInterruptedBySleep(
                        arguments,
                        timeout_seconds,
                        wall_elapsed_seconds=wall_elapsed,
                        monotonic_elapsed_seconds=monotonic_elapsed,
                        output=stdout_capture.text(),
                        stderr=stderr_capture.text(),
                    )
                raise subprocess.TimeoutExpired(
                    arguments,
                    timeout_seconds,
                    output=stdout_capture.text(),
                    stderr=stderr_capture.text(),
                )
            time.sleep(min(poll_seconds, remaining))

        _join_readers(readers)
        for reader in readers:
            if reader.error is not None:
                raise reader.error
        return subprocess.CompletedProcess(
            arguments,
            process.returncode,
            stdout_capture.text(),
            stderr_capture.text(),
        )
    except BaseException:
        if process.poll() is None or not all(reader.done for reader in readers):
            _terminate_process_group(process)
        _join_readers(readers)
        raise


def _join_readers(readers: tuple[_PipeReader, _PipeReader]) -> None:
    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    for reader in readers:
        reader.join(max(0.0, deadline - time.monotonic()))


def _decode_output(value: str | bytes) -> str:
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
