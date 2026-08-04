from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from liveclip.domain.candidate import CandidateClip
from liveclip.domain.edit_plan import EditPlan, validate_edit_plan_bounds
from liveclip.prompts import EditingPromptBundle, load_editing_prompts
from liveclip.providers.llm.base import (
    EditorialSuggestionWire,
    LLMDisposition,
    LLMProviderResult,
    deterministic_edit_plan,
)
from liveclip.providers.openai_retry import (
    OpenAIRetryCancelled,
    OpenAIRetryFailure,
    OpenAIRetryPolicy,
    call_openai_with_retry,
)
from liveclip.providers.telemetry import (
    ProviderCallRecord,
    ProviderCallStatus,
    ProviderCancelled,
    ProviderConfigurationError,
)

_SAFE_MODEL = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
OPENAI_LLM_CONTRACT_VERSION = "openai-responses-editorial-v1"
_REPAIRABLE_STRUCTURE_CODES = frozenset(
    {
        "OPENAI_STRUCTURED_OUTPUT_INVALID",
        "OPENAI_STRUCTURED_OUTPUT_MISSING",
    }
)


@dataclass(frozen=True, slots=True)
class _SuggestionResponse:
    suggestion: EditorialSuggestionWire | None
    disposition: LLMDisposition
    call_record: ProviderCallRecord


class OpenAILLMProvider:
    """Stateless Responses API editor with strict parsing and one bounded repair."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = "gpt-5.6-terra",
        timeout_seconds: float = 120.0,
        retry_policy: OpenAIRetryPolicy | None = None,
        input_price_per_million: Decimal | None = None,
        output_price_per_million: Decimal | None = None,
        client: Any | None = None,
        prompts: EditingPromptBundle | None = None,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        if not _SAFE_MODEL.fullmatch(model_name):
            raise ProviderConfigurationError("OPENAI_LLM_MODEL is invalid")
        if client is None and not api_key:
            raise ProviderConfigurationError("OPENAI_API_KEY is not configured")
        if (input_price_per_million is None) != (output_price_per_million is None):
            raise ProviderConfigurationError("both optional OpenAI LLM prices must be configured")
        if any(
            price is not None and price < 0
            for price in (input_price_per_million, output_price_per_million)
        ):
            raise ProviderConfigurationError("OpenAI LLM prices must be nonnegative")
        self._model_name = model_name
        self._retry_policy = retry_policy or OpenAIRetryPolicy()
        self._input_price = input_price_per_million
        self._output_price = output_price_per_million
        self._prompts = prompts or load_editing_prompts()
        self._client: Any = client or OpenAI(
            api_key=api_key,
            max_retries=0,
            timeout=timeout_seconds,
        )
        self._monotonic = monotonic
        self._sleep = sleep
        self._jitter = jitter

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def prompt_version(self) -> str:
        return self._prompts.version

    @property
    def prompt_sha256(self) -> str:
        return self._prompts.sha256

    @property
    def contract_version(self) -> str:
        return OPENAI_LLM_CONTRACT_VERSION

    def edit_candidate(
        self,
        candidate: CandidateClip,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> LLMProviderResult:
        candidate_payload = _candidate_payload(
            candidate,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
        )
        calls: list[ProviderCallRecord] = []
        initial = self._request_suggestion(
            candidate,
            candidate_payload=candidate_payload,
            phase="initial",
            instructions=self._prompts.initial,
            cancel_requested=cancel_requested,
        )
        calls.append(initial.call_record)
        if initial.suggestion is None:
            if initial.call_record.failure_code in _REPAIRABLE_STRUCTURE_CODES:
                return self._repair_candidate(
                    candidate,
                    candidate_payload=candidate_payload,
                    validation_codes=(initial.call_record.failure_code,),
                    calls=calls,
                    source_duration_ms=source_duration_ms,
                    minimum_duration_ms=minimum_duration_ms,
                    maximum_duration_ms=maximum_duration_ms,
                    cancel_requested=cancel_requested,
                )
            return self._degraded_result(
                candidate,
                initial.disposition,
                calls,
                source_duration_ms,
                minimum_duration_ms,
                maximum_duration_ms,
            )

        try:
            plan = self._assemble_plan(
                candidate,
                initial.suggestion,
                source_duration_ms=source_duration_ms,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
            )
        except (ValidationError, ValueError) as exc:
            calls[-1] = _invalid_record(calls[-1], "OPENAI_EDIT_PLAN_INVALID")
            return self._repair_candidate(
                candidate,
                candidate_payload=candidate_payload,
                validation_codes=tuple(_validation_codes(exc)),
                calls=calls,
                source_duration_ms=source_duration_ms,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
                cancel_requested=cancel_requested,
            )

        return LLMProviderResult(
            plan=plan,
            disposition=LLMDisposition.SUCCEEDED,
            call_records=tuple(calls),
        )

    def _request_suggestion(
        self,
        candidate: CandidateClip,
        *,
        candidate_payload: dict[str, Any],
        phase: str,
        instructions: str,
        cancel_requested: Callable[[], bool],
    ) -> _SuggestionResponse:
        user_data = json.dumps(
            candidate_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        operation_key = hashlib.sha256(
            "\0".join(
                (
                    self.contract_version,
                    self.model_name,
                    self.prompt_sha256,
                    phase,
                    hashlib.sha256(user_data.encode()).hexdigest(),
                )
            ).encode()
        ).hexdigest()
        call_id = uuid.uuid4().hex
        called_at = datetime.now(UTC)
        monotonic = self._monotonic or time.monotonic
        request_started = monotonic()
        attempt_count = 0

        def request() -> object:
            nonlocal attempt_count
            attempt_count += 1
            return self._client.responses.parse(
                model=self.model_name,
                instructions=instructions,
                input=[
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_data}],
                    }
                ],
                text_format=EditorialSuggestionWire,
                tools=[],
                store=False,
                max_output_tokens=1_200,
            )

        retry_kwargs: dict[str, Any] = {}
        if self._monotonic is not None:
            retry_kwargs["monotonic"] = self._monotonic
        if self._sleep is not None:
            retry_kwargs["sleep"] = self._sleep
        if self._jitter is not None:
            retry_kwargs["jitter"] = self._jitter
        try:
            execution = call_openai_with_retry(
                request,
                policy=self._retry_policy,
                cancel_requested=cancel_requested,
                **retry_kwargs,
            )
        except OpenAIRetryCancelled as exc:
            call = (
                self._call_record(
                    call_id=call_id,
                    operation_key=operation_key,
                    candidate=candidate,
                    phase=phase,
                    called_at=called_at,
                    request_count=exc.request_count,
                    retry_count=exc.retry_count,
                    latency_ms=exc.latency_ms,
                    status=ProviderCallStatus.CANCELLED,
                    failure_code="OPENAI_CANCELLED",
                )
                if exc.request_count > 0
                else None
            )
            raise ProviderCancelled(call) from exc
        except OpenAIRetryFailure as exc:
            call = self._call_record(
                call_id=call_id,
                operation_key=operation_key,
                candidate=candidate,
                phase=phase,
                called_at=called_at,
                request_count=exc.request_count,
                retry_count=exc.retry_count,
                latency_ms=exc.latency_ms,
                status=ProviderCallStatus.FAILED,
                failure_code=exc.failure_code,
                request_id=exc.request_id,
            )
            return _SuggestionResponse(
                suggestion=None,
                disposition=LLMDisposition.PROVIDER_ERROR,
                call_record=call,
            )
        except ValidationError:
            call = self._call_record(
                call_id=call_id,
                operation_key=operation_key,
                candidate=candidate,
                phase=phase,
                called_at=called_at,
                request_count=max(1, attempt_count),
                retry_count=max(0, attempt_count - 1),
                latency_ms=max(0, round((monotonic() - request_started) * 1_000)),
                status=ProviderCallStatus.INVALID,
                failure_code="OPENAI_STRUCTURED_OUTPUT_INVALID",
            )
            return _SuggestionResponse(None, LLMDisposition.INVALID, call)

        response = execution.value
        usage = _usage_payload(response)

        def response_record(
            *,
            status: ProviderCallStatus,
            failure_code: str | None = None,
        ) -> ProviderCallRecord:
            return self._call_record(
                call_id=call_id,
                operation_key=operation_key,
                candidate=candidate,
                phase=phase,
                called_at=called_at,
                request_count=execution.request_count,
                retry_count=execution.retry_count,
                latency_ms=execution.latency_ms,
                request_id=_request_id(response),
                response_model=_response_model(response),
                usage_json=usage,
                estimated_cost=self._estimated_cost(usage),
                status=status,
                failure_code=failure_code,
            )

        status = getattr(response, "status", None)
        if status == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
            call = response_record(
                status=ProviderCallStatus.INCOMPLETE,
                failure_code=_incomplete_code(reason),
            )
            return _SuggestionResponse(None, LLMDisposition.INCOMPLETE, call)
        if status != "completed":
            call = response_record(
                status=ProviderCallStatus.INVALID,
                failure_code="OPENAI_RESPONSE_NOT_COMPLETED",
            )
            return _SuggestionResponse(None, LLMDisposition.INVALID, call)
        if _has_refusal(response):
            call = response_record(
                status=ProviderCallStatus.REFUSED,
                failure_code="OPENAI_REFUSAL",
            )
            return _SuggestionResponse(None, LLMDisposition.REFUSED, call)
        if _has_unexpected_output(response):
            call = response_record(
                status=ProviderCallStatus.INVALID,
                failure_code="OPENAI_UNEXPECTED_OUTPUT",
            )
            return _SuggestionResponse(None, LLMDisposition.INVALID, call)
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, EditorialSuggestionWire):
            call = response_record(
                status=ProviderCallStatus.INVALID,
                failure_code="OPENAI_STRUCTURED_OUTPUT_MISSING",
            )
            return _SuggestionResponse(None, LLMDisposition.INVALID, call)
        call = response_record(status=ProviderCallStatus.SUCCEEDED)
        return _SuggestionResponse(parsed, LLMDisposition.SUCCEEDED, call)

    def _repair_candidate(
        self,
        candidate: CandidateClip,
        *,
        candidate_payload: dict[str, Any],
        validation_codes: tuple[str, ...],
        calls: list[ProviderCallRecord],
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
        cancel_requested: Callable[[], bool],
    ) -> LLMProviderResult:
        try:
            repair = self._request_suggestion(
                candidate,
                candidate_payload={
                    **candidate_payload,
                    "validation_codes": list(validation_codes),
                },
                phase="repair",
                instructions=self._prompts.repair,
                cancel_requested=cancel_requested,
            )
        except ProviderCancelled as exc:
            raise ProviderCancelled(call_records=(*calls, *exc.call_records)) from exc
        calls.append(repair.call_record)
        if repair.suggestion is None:
            return self._degraded_result(
                candidate,
                repair.disposition,
                calls,
                source_duration_ms,
                minimum_duration_ms,
                maximum_duration_ms,
            )
        try:
            plan = self._assemble_plan(
                candidate,
                repair.suggestion,
                source_duration_ms=source_duration_ms,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
            )
        except (ValidationError, ValueError):
            calls[-1] = _invalid_record(calls[-1], "OPENAI_EDIT_PLAN_REPAIR_INVALID")
            return self._degraded_result(
                candidate,
                LLMDisposition.INVALID,
                calls,
                source_duration_ms,
                minimum_duration_ms,
                maximum_duration_ms,
            )
        return LLMProviderResult(
            plan=plan,
            disposition=LLMDisposition.REPAIRED,
            call_records=tuple(calls),
        )

    def _call_record(
        self,
        *,
        call_id: str,
        operation_key: str,
        candidate: CandidateClip,
        phase: str,
        called_at: datetime,
        request_count: int,
        retry_count: int,
        latency_ms: int,
        status: ProviderCallStatus,
        failure_code: str | None = None,
        request_id: str | None = None,
        response_model: str | None = None,
        usage_json: dict[str, Any] | None = None,
        estimated_cost: str | None = None,
    ) -> ProviderCallRecord:
        return ProviderCallRecord(
            call_id=call_id,
            operation_key=operation_key,
            subject_id=candidate.candidate_id,
            provider="openai",
            operation=f"responses.edit.{phase}",
            model=self.model_name,
            response_model=response_model,
            request_id=request_id,
            request_count=request_count,
            retry_count=retry_count,
            latency_ms=latency_ms,
            usage_json=usage_json,
            estimated_cost=estimated_cost,
            status=status,
            failure_code=failure_code,
            prompt_version=self.prompt_version,
            prompt_sha256=self.prompt_sha256,
            called_at=called_at,
        )

    def _assemble_plan(
        self,
        candidate: CandidateClip,
        suggestion: EditorialSuggestionWire,
        *,
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
    ) -> EditPlan:
        plan = EditPlan(
            candidate_id=candidate.candidate_id,
            source_start_ms=suggestion.source_start_ms,
            source_end_ms=suggestion.source_end_ms,
            score=suggestion.score,
            title=suggestion.title,
            hook=suggestion.hook,
            reason=suggestion.reason,
            layout=suggestion.layout,
            caption_template=suggestion.caption_template,
            effect=suggestion.effect,
            risk_flags=suggestion.risk_flags,
            prompt_version=self.prompt_version,
            model=self.model_name,
            degraded=False,
        )
        validate_edit_plan_bounds(
            plan,
            source_duration_ms=source_duration_ms,
            minimum_duration_ms=minimum_duration_ms,
            maximum_duration_ms=maximum_duration_ms,
            allowed_start_ms=candidate.allowed_start_ms,
            allowed_end_ms=candidate.allowed_end_ms,
        )
        return plan

    def _degraded_result(
        self,
        candidate: CandidateClip,
        disposition: LLMDisposition,
        calls: list[ProviderCallRecord],
        source_duration_ms: int,
        minimum_duration_ms: int,
        maximum_duration_ms: int,
    ) -> LLMProviderResult:
        flag = {
            LLMDisposition.REFUSED: "ai_refused",
            LLMDisposition.INCOMPLETE: "ai_incomplete",
            LLMDisposition.PROVIDER_ERROR: "ai_provider_error",
        }.get(disposition, "ai_invalid")
        return LLMProviderResult(
            plan=deterministic_edit_plan(
                candidate,
                source_duration_ms=source_duration_ms,
                minimum_duration_ms=minimum_duration_ms,
                maximum_duration_ms=maximum_duration_ms,
                model=self.model_name,
                prompt_version=self.prompt_version,
                degraded=True,
                risk_flags=(flag,),
            ),
            disposition=disposition,
            call_records=tuple(calls),
        )

    def _estimated_cost(self, usage: dict[str, Any] | None) -> str | None:
        if usage is None or self._input_price is None or self._output_price is None:
            return None
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if (
            not isinstance(input_tokens, int)
            or isinstance(input_tokens, bool)
            or input_tokens < 0
            or not isinstance(output_tokens, int)
            or isinstance(output_tokens, bool)
            or output_tokens < 0
        ):
            return None
        cost = (
            Decimal(input_tokens) * self._input_price + Decimal(output_tokens) * self._output_price
        ) / Decimal(1_000_000)
        return format(cost, "f")


def _candidate_payload(
    candidate: CandidateClip,
    *,
    source_duration_ms: int,
    minimum_duration_ms: int,
    maximum_duration_ms: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "candidate_id": candidate.candidate_id,
        "source_start_ms": candidate.source_start_ms,
        "source_end_ms": candidate.source_end_ms,
        "allowed_start_ms": candidate.allowed_start_ms,
        "allowed_end_ms": candidate.allowed_end_ms,
        "source_duration_ms": source_duration_ms,
        "minimum_duration_ms": minimum_duration_ms,
        "maximum_duration_ms": maximum_duration_ms,
        "candidate_transcript": candidate.text,
        "context_before": candidate.context_before,
        "context_after": candidate.context_after,
        "rule_score": candidate.rule_score,
        "rule_reasons": list(candidate.reasons),
        "audio_quality": {"additional_signals_available": False},
    }


def _validation_codes(error: ValidationError | ValueError) -> list[str]:
    if isinstance(error, ValidationError):
        codes = {
            "LOCAL_" + "_".join(str(part).upper() for part in item["loc"])
            for item in error.errors(include_url=False, include_context=False, include_input=False)
        }
        return sorted(codes)[:12] or ["LOCAL_SCHEMA"]
    return ["LOCAL_BOUNDS"]


def _invalid_record(record: ProviderCallRecord, failure_code: str) -> ProviderCallRecord:
    return record.model_copy(
        update={"status": ProviderCallStatus.INVALID, "failure_code": failure_code}
    )


def _has_refusal(response: object) -> bool:
    for output in getattr(response, "output", ()):
        if getattr(output, "type", None) != "message":
            continue
        for content in getattr(output, "content", ()):
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def _has_unexpected_output(response: object) -> bool:
    return any(
        getattr(output, "type", None) not in {"message", "reasoning"}
        for output in getattr(response, "output", ())
    )


def _incomplete_code(reason: object) -> str:
    normalized = str(reason or "unknown").upper()
    safe = re.sub(r"[^A-Z0-9]+", "_", normalized).strip("_")[:40] or "UNKNOWN"
    return f"OPENAI_INCOMPLETE_{safe}"


def _request_id(response: object) -> str | None:
    value = getattr(response, "_request_id", None)
    return str(value)[:160] if value else None


def _response_model(response: object) -> str | None:
    value = getattr(response, "model", None)
    return str(value) if value and _SAFE_MODEL.fullmatch(str(value)) else None


def _usage_payload(response: object) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    model_dump = getattr(usage, "model_dump", None)
    if not callable(model_dump):
        return None
    payload = model_dump(mode="json", exclude_none=True)
    if not isinstance(payload, dict):
        return None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return payload if len(encoded.encode()) <= 16_384 else None
