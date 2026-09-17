from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile
import threading
from codecs import getincrementaldecoder
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SECRET_NAME = re.compile(
    r"(?:API_?KEY|ACCESS_?KEY|AUTHORIZATION|COOKIE|CREDENTIAL|PASSWORD|PRIVATE_?KEY|SECRET|TOKEN)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"(?ix)"
    r"(?:\b(?:bearer|basic)\s+[^\s,;]+)"
    r"|(?:\bsk-(?:or-v1-|proj-)?[A-Za-z0-9._-]{8,})"
    r"|(?:\b(?:api_?key|authorization|cookie|credential|password|private_?key|secret|token)"
    r"\s*[:=]\s*[^\s,;]+)"
    r"|(?:[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@)"
)
PROXY_NAMES = {"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"}


@dataclass(frozen=True)
class CapturedProcess:
    returncode: int
    output: str
    session_id: str | None
    timed_out: bool
    output_truncated: bool = False


def redact(value: str) -> str:
    result = value
    for secret in _sensitive_env_values():
        result = result.replace(secret, "[REDACTED]")
    return SECRET_VALUE.sub("[REDACTED]", result)


def bounded_redacted(value: str, limit_bytes: int) -> str:
    payload = redact(value).encode("utf-8", errors="replace")
    return payload[-limit_bytes:].decode("utf-8", errors="ignore")


def safe_child_env() -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if upper.startswith(("LIVECLIP_", "OPENAI_", "OPENROUTER_")):
            continue
        if SECRET_NAME.search(upper) or upper in {
            "GIT_ASKPASS",
            "GPG_AGENT_INFO",
            "SSH_ASKPASS",
            "SSH_AUTH_SOCK",
        }:
            continue
        if upper in PROXY_NAMES and _proxy_has_credentials(value):
            continue
        safe[key] = value
    safe["PYTHONDONTWRITEBYTECODE"] = "1"
    return safe


def run_bounded(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    limit_bytes: int,
    input_bytes: bytes | None = None,
    capture_session: bool = False,
) -> CapturedProcess:
    tail = bytearray()
    redactor = _StreamingRedactor(tail, limit_bytes)
    pending = bytearray()
    observed_session: list[str] = []
    read_error: list[BaseException] = []
    output_bytes = 0

    with tempfile.TemporaryFile() as input_handle:
        if input_bytes is not None:
            input_handle.write(input_bytes)
            input_handle.seek(0)
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=input_handle if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            shell=False,
        )
        assert process.stdout is not None
        stdout = process.stdout

        def drain() -> None:
            nonlocal output_bytes
            try:
                while chunk := stdout.read(65_536):
                    output_bytes += len(chunk)
                    redactor.feed(chunk)
                    if capture_session and not observed_session:
                        _observe_session(chunk, pending, observed_session, limit_bytes)
            except BaseException as exc:  # pragma: no cover - defensive pipe failure
                read_error.append(exc)

        reader = threading.Thread(target=drain, name="loop-output-drain", daemon=True)
        reader.start()
        timed_out = False
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_group(process)
            returncode = process.wait()
        reader.join(timeout=1)
        if reader.is_alive():  # pragma: no cover - pipe should close with the process group
            _terminate_process_group(process, force=True)
            reader.join(timeout=5)
        stdout.close()
    if read_error:
        raise OSError(f"failed to capture child output: {read_error[0]}")
    redactor.finish()
    output = tail.decode("utf-8", errors="ignore")
    return CapturedProcess(
        returncode=returncode,
        output=output,
        session_id=observed_session[0] if observed_session else None,
        timed_out=timed_out,
        output_truncated=output_bytes > limit_bytes or redactor.truncated,
    )


def _proxy_has_credentials(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return True
    return parsed.username is not None or parsed.password is not None


def _sensitive_env_values() -> list[str]:
    values: set[str] = set()
    for key, value in os.environ.items():
        upper = key.upper()
        sensitive = (
            upper.startswith(("LIVECLIP_", "OPENAI_", "OPENROUTER_"))
            or SECRET_NAME.search(upper) is not None
            or upper in {"GIT_ASKPASS", "GPG_AGENT_INFO", "SSH_ASKPASS", "SSH_AUTH_SOCK"}
            or (upper in PROXY_NAMES and _proxy_has_credentials(value))
        )
        if sensitive and 4 <= len(value) <= 4096:
            values.add(value)
    return sorted(values, key=len, reverse=True)


def _observe_session(
    chunk: bytes,
    pending: bytearray,
    observed: list[str],
    limit_bytes: int,
) -> None:
    pending.extend(chunk)
    while b"\n" in pending:
        raw_line, _, remainder = pending.partition(b"\n")
        pending[:] = remainder
        if len(raw_line) > limit_bytes:
            continue
        try:
            event = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        session_id = _event_session_id(event)
        if session_id:
            observed.append(session_id)
            return
    if len(pending) > limit_bytes:
        del pending[:]


def _event_session_id(event: Any) -> str | None:
    if not isinstance(event, dict):
        return None
    for key in ("thread_id", "session_id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    thread = event.get("thread")
    if isinstance(thread, dict):
        value = thread.get("id")
        if isinstance(value, str) and value:
            return value
    return None


def _terminate_process_group(process: subprocess.Popen[bytes], *, force: bool = False) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError:
        return
    if force:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _terminate_process_group(process, force=True)


class _StreamingRedactor:
    """Redact before retaining a bounded tail, including across pipe chunks."""

    def __init__(self, tail: bytearray, limit_bytes: int) -> None:
        self.truncated = False
        self._tail = tail
        self._limit_bytes = limit_bytes
        self._decoder = getincrementaldecoder("utf-8")(errors="replace")
        self._pending = ""
        self._discarding_overlong_line = False
        self._line_limit = min(max(limit_bytes * 4, 4096), 1_048_576)

    def feed(self, chunk: bytes) -> None:
        text = self._decoder.decode(chunk)
        if self._discarding_overlong_line:
            newline = text.find("\n")
            if newline < 0:
                return
            self._discarding_overlong_line = False
            text = text[newline + 1 :]
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._append(redact(line + "\n"))
        if len(self._pending) > self._line_limit:
            self.truncated = True
            self._append("[REDACTED OVERLONG LINE]\n")
            self._pending = ""
            self._discarding_overlong_line = True

    def finish(self) -> None:
        self._pending += self._decoder.decode(b"", final=True)
        if not self._discarding_overlong_line:
            self._append(redact(self._pending))
        self._pending = ""

    def _append(self, value: str) -> None:
        self._tail.extend(value.encode("utf-8", errors="replace"))
        if len(self._tail) > self._limit_bytes:
            self.truncated = True
            del self._tail[: len(self._tail) - self._limit_bytes]
