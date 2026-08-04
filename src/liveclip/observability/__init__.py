"""Structured local logs with recursive credential and path redaction."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|cookie|api[_-]?key|token|signature)\b(\s*[:=]\s*)([^\s,;&]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_SIGNED_QUERY = re.compile(r"(?i)([?&](?:signature|token|api_key)=)[^&#\s]+")
_LOCAL_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:Users|private|tmp|var|Volumes|home)/[^\s\"']+")


def redact_text(value: str) -> str:
    redacted = _BEARER.sub("Bearer [REDACTED]", value)
    redacted = _OPENAI_KEY.sub("[REDACTED_API_KEY]", redacted)
    redacted = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)
    redacted = _SIGNED_QUERY.sub(r"\1[REDACTED]", redacted)
    return _LOCAL_PATH.sub("[LOCAL_PATH]", redacted)


def redact_persistent_diagnostic(
    value: str,
    *,
    sensitive_values: Iterable[str] = (),
    maximum_characters: int = 4_000,
) -> str:
    """Aggressively redact untrusted subprocess text before durable storage."""

    if maximum_characters <= 0:
        raise ValueError("diagnostic character limit must be positive")
    sanitized = value[-maximum_characters:]
    for sensitive in sorted(
        (item for item in sensitive_values if item),
        key=len,
        reverse=True,
    ):
        sanitized = sanitized.replace(sensitive, "[LOCAL_PATH]")
    safe_lines: list[str] = []
    for raw_line in sanitized.splitlines()[-20:]:
        line = "".join(character if ord(character) >= 32 else "�" for character in raw_line)
        if _line_contains_path_or_url(line):
            safe_lines.append("[REDACTED_PATH_BEARING_DIAGNOSTIC]")
        else:
            safe_lines.append(redact_text(line))
    return "\n".join(safe_lines)[-maximum_characters:]


def _line_contains_path_or_url(value: str) -> bool:
    for token in value.replace('"', " ").replace("'", " ").split():
        if "://" in token:
            return True
        if token.startswith(("/", "./", "../", "~", "\\")):
            return True
        if "/" in token or "\\" in token:
            return True
        if token.lower().rstrip(".,:;").endswith((".mp4", ".mov", ".m4a", ".png", ".srt", ".json")):
            return True
    return False


def redact_value(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if re.search(r"(?i)(authorization|cookie|api[_-]?key|token|signature)", str(key))
                else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except (TypeError, ValueError):
            rendered = str(redact_value(record.msg))
        record.msg = redact_text(rendered)
        record.args = ()
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": redact_text(record.getMessage()),
        }
        if record.exc_info is not None:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception_type"] = exception_type.__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    """Install one idempotent JSON handler and redact all existing handlers."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    redactor = RedactingFilter()
    if not any(getattr(handler, "_liveclip_json", False) for handler in root.handlers):
        created_handler = logging.StreamHandler()
        created_handler.setLevel(numeric_level)
        created_handler.setFormatter(JsonLogFormatter())
        created_handler.addFilter(redactor)
        created_handler._liveclip_json = True  # type: ignore[attr-defined]
        root.addHandler(created_handler)
    for existing_handler in root.handlers:
        if not any(isinstance(item, RedactingFilter) for item in existing_handler.filters):
            existing_handler.addFilter(redactor)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        for existing_handler in logger.handlers:
            if not any(isinstance(item, RedactingFilter) for item in existing_handler.filters):
                existing_handler.addFilter(redactor)


__all__ = [
    "JsonLogFormatter",
    "RedactingFilter",
    "configure_logging",
    "redact_persistent_diagnostic",
    "redact_text",
    "redact_value",
]
