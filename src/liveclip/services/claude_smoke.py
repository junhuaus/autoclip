# ruff: noqa: RUF001
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from liveclip.clipping_skills.semantic_global_v1 import SemanticGlobalPromptBundle
from liveclip.config import Settings
from liveclip.providers.llm.claude_cli import (
    ClaudeCliRetryPolicy,
    ClaudeCliStructuredLLMProvider,
    assert_claude_cli_ready,
)
from liveclip.providers.llm.structured import StructuredProviderError
from liveclip.providers.telemetry import ProviderCallStatus

_SMOKE_INSTRUCTIONS = (
    "你是直播切片编辑。阅读候选片段，判断它是否适合作为短视频高光，"
    "并给出 0 到 100 的分数、简短标题、开场钩子和完整表达的起止毫秒。"
    "起止时间必须位于 allowed_start_ms 与 allowed_end_ms 之间，时长 30 到 50 秒。"
)
_SMOKE_REPAIR = "上一次输出未通过结构校验。只返回符合 schema 的完整对象。"


class ClaudeSmokeSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_start_ms: int = Field(ge=0)
    source_end_ms: int = Field(gt=0)
    score: int = Field(ge=0, le=100)
    title: str = Field(min_length=1, max_length=40)
    hook: str = Field(min_length=1, max_length=80)


class ClaudeSmokeError(RuntimeError):
    """The real Claude CLI structured check did not complete successfully."""


@dataclass(frozen=True, slots=True)
class ClaudeSmokeResult:
    provider: str
    model: str
    response_model: str
    auth_method: str
    contract: str
    latency_ms: int
    request_count: int
    input_tokens: int
    output_tokens: int
    score: int
    title: str
    source_start_ms: int
    source_end_ms: int


def run_claude_smoke(settings: Settings) -> ClaudeSmokeResult:
    """Make one real, tool-free Claude CLI structured call; never substitute a Mock."""

    contract, auth = assert_claude_cli_ready(settings.claude_executable)
    prompts = SemanticGlobalPromptBundle(
        version="claude_smoke_v1",
        stage="discovery",
        profile="general",
        instructions=_SMOKE_INSTRUCTIONS,
        repair=_SMOKE_REPAIR,
        sha256=hashlib.sha256(
            f"claude_smoke_v1\0{_SMOKE_INSTRUCTIONS}\0{_SMOKE_REPAIR}".encode()
        ).hexdigest(),
        loaded_files=(),
    )
    provider = ClaudeCliStructuredLLMProvider(
        prompts=prompts,
        model_name=settings.claude_model,
        claude_executable=settings.claude_executable,
        timeout_seconds=settings.claude_request_timeout_seconds,
        contract_version=contract,
        reasoning_effort="medium",
        retry_policy=ClaudeCliRetryPolicy(
            max_attempts=settings.claude_max_attempts,
            base_delay_seconds=settings.claude_retry_base_seconds,
            max_delay_seconds=settings.claude_retry_max_seconds,
            total_wait_seconds=settings.claude_retry_total_wait_seconds,
        ),
    )
    payload: dict[str, object] = {
        "candidate_id": "claude_smoke",
        "allowed_start_ms": 10_000,
        "allowed_end_ms": 60_000,
        "candidate_transcript": (
            "很多人以为直播只要信息量大就够了，其实开头三秒必须先告诉观众为什么"
            "值得继续看，然后用一个完整例子闭合观点。"
        ),
        "context_before": "主持人正在讨论如何提高直播内容的完播率。",
        "context_after": "随后进入下一个独立话题。",
    }
    try:
        result = provider.generate(
            subject_id="claude_smoke",
            payload=payload,
            response_model=ClaudeSmokeSuggestion,
        )
    except StructuredProviderError as exc:
        raise ClaudeSmokeError(f"Claude smoke failed without Mock fallback: {exc}") from exc
    record = result.call_records[-1] if result.call_records else None
    usage = record.usage_json if record is not None else None
    input_tokens = _required_positive_int(
        usage.get("input_tokens") if isinstance(usage, dict) else None
    )
    output_tokens = _required_positive_int(
        usage.get("output_tokens") if isinstance(usage, dict) else None
    )
    output = result.output
    if (
        record is None
        or record.provider != "claude_cli"
        or record.status != ProviderCallStatus.SUCCEEDED
        or record.response_model != settings.claude_model
        or input_tokens is None
        or output_tokens is None
        or not 10_000 <= output.source_start_ms < output.source_end_ms <= 60_000
    ):
        code = record.failure_code if record is not None else "CLAUDE_CLI_NO_CALL_EVIDENCE"
        raise ClaudeSmokeError(f"Claude smoke failed without Mock fallback: {code}")
    return ClaudeSmokeResult(
        provider=record.provider,
        model=record.model,
        response_model=record.response_model or "",
        auth_method=auth.auth_method or "unknown",
        contract=contract,
        latency_ms=record.latency_ms,
        request_count=record.request_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        score=output.score,
        title=output.title,
        source_start_ms=output.source_start_ms,
        source_end_ms=output.source_end_ms,
    )


def _required_positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None
