from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import openai
import pytest

from liveclip.providers.openai_retry import (
    OpenAIRetryCancelled,
    OpenAIRetryFailure,
    OpenAIRetryPolicy,
    call_openai_with_retry,
    classify_openai_error,
)


@dataclass
class _Clock:
    now: float = 10.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _status_error(
    status_code: int,
    *,
    code: str | None = None,
    retry_after: str | None = None,
    request_id: str | None = None,
) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.test/v1/responses")
    headers: dict[str, str] = {}
    if retry_after is not None:
        headers["retry-after"] = retry_after
    if request_id is not None:
        headers["x-request-id"] = request_id
    response = httpx.Response(status_code, request=request, headers=headers)
    body = {"message": "bounded test error", "type": "test_error", "code": code}
    return openai.APIStatusError("OpenAI request failed", response=response, body=body)


@pytest.mark.parametrize(
    ("error_factory", "expected"),
    [
        (
            lambda: openai.APITimeoutError(
                httpx.Request("POST", "https://api.openai.test/v1/responses")
            ),
            (True, "OPENAI_TIMEOUT"),
        ),
        (
            lambda: openai.APIConnectionError(
                request=httpx.Request("POST", "https://api.openai.test/v1/responses")
            ),
            (True, "OPENAI_CONNECTION"),
        ),
        (lambda: _status_error(408), (True, "OPENAI_HTTP_408")),
        (lambda: _status_error(409), (True, "OPENAI_HTTP_409")),
        (lambda: _status_error(429), (True, "OPENAI_RATE_LIMIT")),
        (lambda: _status_error(500), (True, "OPENAI_SERVER")),
        (lambda: _status_error(503), (True, "OPENAI_SERVER")),
        (lambda: _status_error(401), (False, "OPENAI_AUTH")),
        (lambda: _status_error(403), (False, "OPENAI_AUTH")),
        (lambda: _status_error(400), (False, "OPENAI_HTTP_400")),
        (lambda: _status_error(404), (False, "OPENAI_HTTP_404")),
        (lambda: _status_error(422), (False, "OPENAI_HTTP_422")),
        (lambda: openai.OpenAIError("unsupported request"), (False, "OPENAI_REQUEST")),
    ],
)
def test_error_classification_is_explicit(
    error_factory: Callable[[], openai.OpenAIError], expected: tuple[bool, str]
) -> None:
    assert classify_openai_error(error_factory()) == expected


@pytest.mark.parametrize(
    "code",
    [
        "credit_balance_exhausted",
        "insufficient_quota",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    ],
)
def test_quota_and_spend_limit_429_errors_are_not_retried(code: str) -> None:
    assert classify_openai_error(_status_error(429, code=code)) == (False, "OPENAI_QUOTA")


def test_transient_failures_retry_with_bounded_exponential_backoff() -> None:
    clock = _Clock()
    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise _status_error(500)
        return "completed"

    result = call_openai_with_retry(
        operation,
        policy=OpenAIRetryPolicy(
            max_retries=2,
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
        ),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        jitter=lambda: 0.0,
    )

    assert result.value == "completed"
    assert (result.request_count, result.retry_count, result.latency_ms) == (3, 2, 1_500)
    assert sum(clock.sleeps) == pytest.approx(1.5)
    assert all(0 < value <= 0.1 for value in clock.sleeps)


def test_retry_after_is_honored_but_capped_by_policy() -> None:
    clock = _Clock()
    responses: list[object] = [
        _status_error(429, retry_after="9"),
        "completed",
    ]

    def operation() -> str:
        value = responses.pop(0)
        if isinstance(value, openai.OpenAIError):
            raise value
        return str(value)

    result = call_openai_with_retry(
        operation,
        policy=OpenAIRetryPolicy(
            max_retries=1,
            base_delay_seconds=1.0,
            max_delay_seconds=2.0,
        ),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        jitter=lambda: 0.0,
    )

    assert result.value == "completed"
    assert (result.request_count, result.retry_count, result.latency_ms) == (2, 1, 2_000)
    assert sum(clock.sleeps) == pytest.approx(2.0)


def test_retry_budget_exhaustion_preserves_counts_and_request_id() -> None:
    clock = _Clock()
    request_id = "req_retry_exhausted"

    with pytest.raises(OpenAIRetryFailure) as caught:
        call_openai_with_retry(
            lambda: (_ for _ in ()).throw(_status_error(503, request_id=request_id)),
            policy=OpenAIRetryPolicy(
                max_retries=2,
                base_delay_seconds=0.2,
                max_delay_seconds=1.0,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            jitter=lambda: 0.0,
        )

    failure = caught.value
    assert failure.transient is True
    assert failure.failure_code == "OPENAI_SERVER"
    assert failure.request_id == request_id
    assert (failure.request_count, failure.retry_count) == (3, 2)
    assert sum(clock.sleeps) == pytest.approx(0.3)


def test_deterministic_failure_is_not_retried_or_slept() -> None:
    clock = _Clock()
    attempts = 0

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise _status_error(400, request_id="req_bad_request")

    with pytest.raises(OpenAIRetryFailure) as caught:
        call_openai_with_retry(
            operation,
            policy=OpenAIRetryPolicy(
                max_retries=8,
                base_delay_seconds=1.0,
                max_delay_seconds=5.0,
            ),
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert attempts == 1
    assert clock.sleeps == []
    assert caught.value.transient is False
    assert caught.value.failure_code == "OPENAI_HTTP_400"
    assert (caught.value.request_count, caught.value.retry_count) == (1, 0)


def test_cancellation_interrupts_backoff_before_another_request() -> None:
    clock = _Clock()
    attempts = 0
    cancelled = False

    def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise _status_error(500)

    def sleep_and_cancel(seconds: float) -> None:
        nonlocal cancelled
        clock.sleep(seconds)
        cancelled = True

    with pytest.raises(OpenAIRetryCancelled) as caught:
        call_openai_with_retry(
            operation,
            policy=OpenAIRetryPolicy(
                max_retries=3,
                base_delay_seconds=2.0,
                max_delay_seconds=5.0,
            ),
            cancel_requested=lambda: cancelled,
            monotonic=clock.monotonic,
            sleep=sleep_and_cancel,
            jitter=lambda: 0.0,
        )

    assert attempts == 1
    # The next request was never attempted, so its retry must not be counted.
    assert (caught.value.request_count, caught.value.retry_count) == (1, 0)
    assert caught.value.latency_ms == 100
    assert clock.sleeps == [0.1]
