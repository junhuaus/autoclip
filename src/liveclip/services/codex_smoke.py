# ruff: noqa: RUF001
from __future__ import annotations

from dataclasses import dataclass

from liveclip.config import Settings
from liveclip.domain.candidate import CandidateClip
from liveclip.providers.llm.base import LLMDisposition
from liveclip.providers.llm.codex import CodexCLILLMProvider
from liveclip.providers.telemetry import ProviderCallStatus


class CodexSmokeError(RuntimeError):
    """The real Codex CLI editorial check did not complete successfully."""


@dataclass(frozen=True, slots=True)
class CodexSmokeResult:
    provider: str
    model: str
    thread_id: str
    input_tokens: int
    output_tokens: int
    score: float
    title: str
    source_start_ms: int
    source_end_ms: int


def run_codex_smoke(settings: Settings) -> CodexSmokeResult:
    """Make one real, tool-disabled Codex call; never substitute a Mock result."""

    provider = CodexCLILLMProvider(
        model_name=settings.llm_model,
        codex_executable=settings.codex_executable,
        timeout_seconds=settings.openai_request_timeout_seconds,
    )
    candidate = CandidateClip(
        candidate_id="codex_smoke",
        source_start_ms=10_000,
        source_end_ms=60_000,
        allowed_start_ms=10_000,
        allowed_end_ms=60_000,
        text=(
            "很多人以为直播只要信息量大就够了，其实开头三秒必须先告诉观众为什么"
            "值得继续看，然后用一个完整例子闭合观点。"
        ),
        context_before="主持人正在讨论如何提高直播内容的完播率。",
        context_after="随后进入下一个独立话题。",
        rule_score=86.0,
        reasons=("开头有价值承诺", "表达闭合"),
        segment_ids=("codex_smoke_segment",),
    )
    result = provider.edit_candidate(
        candidate,
        source_duration_ms=90_000,
        minimum_duration_ms=30_000,
        maximum_duration_ms=50_000,
    )
    record = result.call_records[-1] if result.call_records else None
    usage = record.usage_json if record is not None else None
    input_tokens = _required_positive_int(
        usage.get("input_tokens") if isinstance(usage, dict) else None
    )
    output_tokens = _required_positive_int(
        usage.get("output_tokens") if isinstance(usage, dict) else None
    )
    if (
        result.disposition not in {LLMDisposition.SUCCEEDED, LLMDisposition.REPAIRED}
        or result.plan.degraded
        or record is None
        or record.provider != "codex_cli"
        or record.status != ProviderCallStatus.SUCCEEDED
        or not record.request_id
        or input_tokens is None
        or output_tokens is None
    ):
        code = (
            result.call_records[-1].failure_code
            if result.call_records
            else "CODEX_CLI_NO_CALL_EVIDENCE"
        )
        raise CodexSmokeError(f"Codex smoke failed without Mock fallback: {code}")
    return CodexSmokeResult(
        provider=record.provider,
        model=result.plan.model,
        thread_id=record.request_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        score=result.plan.score,
        title=result.plan.title,
        source_start_ms=result.plan.source_start_ms,
        source_end_ms=result.plan.source_end_ms,
    )


def _required_positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None
