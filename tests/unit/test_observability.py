from __future__ import annotations

import json
import logging

from pydantic import SecretStr

from liveclip.observability import (
    JsonLogFormatter,
    RedactingFilter,
    redact_persistent_diagnostic,
    redact_value,
)


def test_recursive_redaction_removes_credentials_signed_urls_and_local_paths() -> None:
    raw = {
        "Authorization": "Bearer super-secret-token",
        "nested": [
            "OPENAI_API_KEY=sk-test_1234567890",
            "http://127.0.0.1/media?expires=1&signature=abcdef",
            "/Users/example/private/video.mp4",
        ],
        "secret": SecretStr("must-not-appear"),
    }

    rendered = repr(redact_value(raw))
    for secret in (
        "super-secret-token",
        "sk-test_1234567890",
        "abcdef",
        "must-not-appear",
        "/Users/example/private/video.mp4",
    ):
        assert secret not in rendered
    assert "[REDACTED]" in rendered
    assert "[LOCAL_PATH]" in rendered


def test_json_log_formatter_does_not_render_exception_traceback_or_sensitive_args() -> None:
    record = logging.LogRecord(
        name="liveclip.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="request Authorization=%s source=%s",
        args=("Bearer local-token", "/private/tmp/source.mp4"),
        exc_info=None,
    )
    assert RedactingFilter().filter(record) is True
    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["level"] == "error"
    serialized = json.dumps(payload)
    assert "local-token" not in serialized
    assert "/private/tmp/source.mp4" not in serialized


def test_persistent_diagnostic_redacts_all_path_and_url_bearing_lines() -> None:
    rendered = redact_persistent_diagnostic(
        "\n".join(
            (
                "/opt/liveclip/secret name.mp4 failed",
                "file:///opt/liveclip/secret.mp4 failed",
                "relative/private.mp4 failed",
                "https://service.invalid/path?token=secret failed",
                "frame=42 speed=0.0x",
            )
        )
    )

    assert "/opt" not in rendered
    assert "relative/private.mp4" not in rendered
    assert "service.invalid" not in rendered
    assert "secret" not in rendered
    assert "frame=42 speed=0.0x" in rendered
