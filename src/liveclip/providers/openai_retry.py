from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Generic, TypeVar

import openai
from pydantic import BaseModel, ConfigDict, Field

ResultT = TypeVar("ResultT")

_NON_RETRYABLE_429_CODES = frozenset(
    {
        "credit_balance_exhausted",
        "insufficient_quota",
        "organization_spend_limit_exceeded",
        "project_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    }
)


class OpenAIRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_retries: int = Field(default=2, ge=0, le=8)
    base_delay_seconds: float = Field(default=1.0, gt=0, le=60)
    max_delay_seconds: float = Field(default=30.0, gt=0, le=300)


@dataclass(frozen=True, slots=True)
class OpenAIRetryResult(Generic[ResultT]):
    value: ResultT
    request_count: int
    retry_count: int
    latency_ms: int


class OpenAIRetryFailure(RuntimeError):
    def __init__(
        self,
        *,
        cause: openai.OpenAIError,
        request_count: int,
        retry_count: int,
        latency_ms: int,
        transient: bool,
        failure_code: str,
        request_id: str | None,
    ) -> None:
        super().__init__("OpenAI request failed")
        self.cause = cause
        self.request_count = request_count
        self.retry_count = retry_count
        self.latency_ms = latency_ms
        self.transient = transient
        self.failure_code = failure_code
        self.request_id = request_id


class OpenAIRetryCancelled(RuntimeError):
    def __init__(self, *, request_count: int, retry_count: int, latency_ms: int) -> None:
        super().__init__("OpenAI request cancelled")
        self.request_count = request_count
        self.retry_count = retry_count
        self.latency_ms = latency_ms


def call_openai_with_retry(
    operation: Callable[[], ResultT],
    *,
    policy: OpenAIRetryPolicy,
    cancel_requested: Callable[[], bool] = lambda: False,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[], float] = random.random,
) -> OpenAIRetryResult[ResultT]:
    """Run one logical OpenAI request with application-owned bounded retries."""

    started = monotonic()
    request_count = 0
    retry_count = 0
    while True:
        if cancel_requested():
            raise OpenAIRetryCancelled(
                request_count=request_count,
                retry_count=retry_count,
                latency_ms=_elapsed_ms(started, monotonic),
            )
        request_count += 1
        try:
            value = operation()
        except openai.OpenAIError as exc:
            transient, failure_code = classify_openai_error(exc)
            if not transient or retry_count >= policy.max_retries:
                raise OpenAIRetryFailure(
                    cause=exc,
                    request_count=request_count,
                    retry_count=retry_count,
                    latency_ms=_elapsed_ms(started, monotonic),
                    transient=transient,
                    failure_code=failure_code,
                    request_id=_request_id_from_error(exc),
                ) from exc
            delay = _retry_delay(
                exc,
                retry_count=retry_count,
                policy=policy,
                jitter=jitter,
            )
            _sleep_with_cancellation(
                delay,
                cancel_requested=cancel_requested,
                sleep=sleep,
                request_count=request_count,
                retry_count=retry_count,
                started=started,
                monotonic=monotonic,
            )
            # A retry is counted only once the backoff completes and another request
            # can actually be attempted. Cancellation during backoff therefore keeps
            # ``retry_count < request_count`` in durable call evidence.
            retry_count += 1
            continue
        if cancel_requested():
            raise OpenAIRetryCancelled(
                request_count=request_count,
                retry_count=retry_count,
                latency_ms=_elapsed_ms(started, monotonic),
            )
        return OpenAIRetryResult(
            value=value,
            request_count=request_count,
            retry_count=retry_count,
            latency_ms=_elapsed_ms(started, monotonic),
        )


def classify_openai_error(error: openai.OpenAIError) -> tuple[bool, str]:
    if isinstance(error, openai.APITimeoutError):
        return True, "OPENAI_TIMEOUT"
    if isinstance(error, openai.APIConnectionError):
        return True, "OPENAI_CONNECTION"
    if isinstance(error, openai.APIStatusError):
        status = int(error.status_code)
        code = str(getattr(error, "code", "") or "").lower()
        if status == 429 and code in _NON_RETRYABLE_429_CODES:
            return False, "OPENAI_QUOTA"
        if status in {408, 409}:
            return True, f"OPENAI_HTTP_{status}"
        if status == 429:
            return True, "OPENAI_RATE_LIMIT"
        if status >= 500:
            return True, "OPENAI_SERVER"
        if status in {401, 403}:
            return False, "OPENAI_AUTH"
        return False, f"OPENAI_HTTP_{status}"
    return False, "OPENAI_REQUEST"


def _retry_delay(
    error: openai.OpenAIError,
    *,
    retry_count: int,
    policy: OpenAIRetryPolicy,
    jitter: Callable[[], float],
) -> float:
    random_value = max(0.0, min(1.0, float(jitter())))
    exponential = policy.base_delay_seconds * (2**retry_count)
    backoff = exponential * (0.5 + 0.5 * random_value)
    retry_after = _retry_after_seconds(error)
    requested = max(backoff, retry_after or 0.0)
    return float(min(policy.max_delay_seconds, requested))


def _retry_after_seconds(error: openai.OpenAIError) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw_value = headers.get("retry-after")
    if not raw_value:
        return None
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        try:
            instant = parsedate_to_datetime(str(raw_value))
        except (TypeError, ValueError, OverflowError):
            return None
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        return max(0.0, (instant - datetime.now(UTC)).total_seconds())


def _sleep_with_cancellation(
    delay: float,
    *,
    cancel_requested: Callable[[], bool],
    sleep: Callable[[float], None],
    request_count: int,
    retry_count: int,
    started: float,
    monotonic: Callable[[], float],
) -> None:
    remaining = delay
    while remaining > 0:
        if cancel_requested():
            raise OpenAIRetryCancelled(
                request_count=request_count,
                retry_count=retry_count,
                latency_ms=_elapsed_ms(started, monotonic),
            )
        step = min(0.1, remaining)
        sleep(step)
        remaining -= step
    if cancel_requested():
        raise OpenAIRetryCancelled(
            request_count=request_count,
            retry_count=retry_count,
            latency_ms=_elapsed_ms(started, monotonic),
        )


def _request_id_from_error(error: openai.OpenAIError) -> str | None:
    value = getattr(error, "request_id", None)
    return str(value)[:160] if value else None


def _elapsed_ms(started: float, monotonic: Callable[[], float]) -> int:
    return max(0, round((monotonic() - started) * 1_000))
