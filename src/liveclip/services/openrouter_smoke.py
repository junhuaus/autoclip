from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from liveclip.bootstrap import LiveClipRuntime, local_worker_id, pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.db.models import ApiUsageRow, CandidateClipRow, EditPlanRevisionRow, TranscriptRow
from liveclip.domain.state_transitions import PipelineRunStatus
from liveclip.media.ingest import MediaIngestError, resolve_allowed_source
from liveclip.providers.readiness import assess_provider_readiness


class OpenRouterSmokeError(RuntimeError):
    """The real OpenRouter ASR + Codex editorial chain was not proven."""


@dataclass(frozen=True, slots=True)
class OpenRouterSmokeResult:
    project_id: str
    run_id: str
    source_path: Path
    asr_model: str
    llm_model: str
    asr_generation_ids: tuple[str, ...]
    codex_thread_ids: tuple[str, ...]
    selected_clip_count: int


@dataclass(frozen=True, slots=True)
class OpenRouterUsageEvidence:
    provider: str
    operation: str
    model: str
    request_id: str | None
    status: str
    usage_json: Mapping[str, Any] | None


@dataclass(frozen=True, slots=True)
class OpenRouterPlanEvidence:
    degraded: bool
    model: str


def validate_openrouter_smoke_evidence(
    *,
    transcript_provider: str | None,
    usage: Sequence[OpenRouterUsageEvidence],
    selected_plans: Sequence[OpenRouterPlanEvidence],
    expected_asr_model: str,
    expected_llm_model: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if transcript_provider != "openrouter":
        raise OpenRouterSmokeError("OpenRouter smoke failed; real ASR transcript is missing")
    if any(row.provider not in {"openrouter", "codex_cli"} for row in usage):
        raise OpenRouterSmokeError("OpenRouter smoke failed; Mock or unexpected provider observed")

    asr_success = tuple(
        row
        for row in usage
        if row.provider == "openrouter"
        and row.operation == "audio.transcriptions"
        and row.model == expected_asr_model
        and row.status == "succeeded"
    )
    codex_success = tuple(
        row
        for row in usage
        if row.provider == "codex_cli"
        and row.operation.startswith("responses.edit.")
        and row.model == expected_llm_model
        and row.status == "succeeded"
    )
    if not asr_success or any(not row.request_id for row in asr_success):
        raise OpenRouterSmokeError(
            "OpenRouter smoke failed; X-Generation-Id ASR evidence is missing"
        )
    if not codex_success or any(
        not row.request_id or not _has_positive_codex_usage(row.usage_json) for row in codex_success
    ):
        raise OpenRouterSmokeError(
            "OpenRouter smoke failed; Codex thread/token evidence is missing"
        )
    if not selected_plans or any(
        row.degraded or row.model != expected_llm_model for row in selected_plans
    ):
        raise OpenRouterSmokeError(
            "OpenRouter smoke failed; selected EditPlan is degraded or wrong-model"
        )
    return (
        tuple(str(row.request_id) for row in asr_success),
        tuple(str(row.request_id) for row in codex_success),
    )


def openrouter_smoke_preflight(settings: Settings, input_path: Path) -> tuple[str, ...]:
    issues: list[str] = []
    if settings.ai_provider != "openrouter-codex":
        issues.append("LIVECLIP_AI_PROVIDER=openrouter-codex")
    if not (settings.openrouter_api_key and settings.openrouter_api_key.get_secret_value().strip()):
        issues.append("OPENROUTER_API_KEY (new, non-exposed key)")
    readiness = assess_provider_readiness(settings)
    issues.extend(readiness.blocking_issues)
    if not settings.allowed_media_roots:
        issues.append("LIVECLIP_ALLOWED_MEDIA_ROOTS")
    if not input_path.is_absolute() or ".." in input_path.parts:
        issues.append("INPUT must be an absolute path without '..'")
    elif not input_path.is_file():
        issues.append("INPUT must be an existing regular file")
    elif settings.allowed_media_roots:
        try:
            resolve_allowed_source(input_path, settings.allowed_media_roots)
        except MediaIngestError:
            issues.append("INPUT must be a readable media file inside an allowed root")
    return tuple(dict.fromkeys(issues))


def run_openrouter_smoke(
    *,
    settings: Settings,
    input_path: Path,
    project_root: Path | None = None,
) -> OpenRouterSmokeResult:
    """Run the real OpenRouter ASR + Codex chain without any Mock fallback."""

    issues = openrouter_smoke_preflight(settings, input_path)
    if issues:
        raise OpenRouterSmokeError(
            "OpenRouter smoke not_run; missing/invalid: " + ", ".join(issues)
        )

    config = pipeline_config_from_settings(settings, top_n=min(3, settings.default_top_n))
    if config.provider != "openrouter-codex":
        raise OpenRouterSmokeError("OpenRouter smoke not_run; provider mode changed unexpectedly")
    with LiveClipRuntime.open(settings, project_root=project_root) as runtime:
        created = runtime.pipeline_service.create_project_and_run(
            source_path=input_path,
            config=config,
            max_stage_retries=settings.max_stage_retries,
        )
        snapshot = runtime.stage_runner.run_until_terminal(
            created.run_id,
            worker_id=local_worker_id("smoke-openrouter"),
        )
        if snapshot.status != PipelineRunStatus.COMPLETED:
            code = snapshot.error_code or "OPENROUTER_PIPELINE_FAILED"
            raise OpenRouterSmokeError(
                f"OpenRouter smoke failed; run={created.run_id}; error={code}"
            )

        with runtime.engine.connect() as connection:
            transcript_provider = connection.scalar(
                select(TranscriptRow.provider).where(
                    TranscriptRow.pipeline_run_id == created.run_id
                )
            )
            usage = connection.execute(
                select(
                    ApiUsageRow.provider,
                    ApiUsageRow.operation,
                    ApiUsageRow.model,
                    ApiUsageRow.request_id,
                    ApiUsageRow.status,
                    ApiUsageRow.usage_json,
                ).where(ApiUsageRow.pipeline_run_id == created.run_id)
            ).all()
            selected_plans = connection.execute(
                select(EditPlanRevisionRow.degraded, EditPlanRevisionRow.model)
                .join(
                    CandidateClipRow,
                    CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id,
                )
                .where(
                    CandidateClipRow.pipeline_run_id == created.run_id,
                    CandidateClipRow.selected_for_review.is_(True),
                    EditPlanRevisionRow.revision == CandidateClipRow.current_revision,
                )
            ).all()

        asr_ids, codex_ids = validate_openrouter_smoke_evidence(
            transcript_provider=(
                str(transcript_provider) if transcript_provider is not None else None
            ),
            usage=tuple(
                OpenRouterUsageEvidence(
                    provider=str(row.provider),
                    operation=str(row.operation),
                    model=str(row.model),
                    request_id=str(row.request_id) if row.request_id else None,
                    status=str(row.status),
                    usage_json=row.usage_json if isinstance(row.usage_json, dict) else None,
                )
                for row in usage
            ),
            selected_plans=tuple(
                OpenRouterPlanEvidence(degraded=bool(row.degraded), model=str(row.model))
                for row in selected_plans
            ),
            expected_asr_model=settings.openrouter_asr_model,
            expected_llm_model=settings.llm_model,
        )
        return OpenRouterSmokeResult(
            project_id=created.project_id,
            run_id=created.run_id,
            source_path=input_path.resolve(strict=True),
            asr_model=settings.openrouter_asr_model,
            llm_model=settings.llm_model,
            asr_generation_ids=asr_ids,
            codex_thread_ids=codex_ids,
            selected_clip_count=len(selected_plans),
        )


def _has_positive_codex_usage(value: Mapping[str, Any] | None) -> bool:
    provider_usage = value.get("provider_usage") if value is not None else None
    if not isinstance(provider_usage, Mapping):
        return False
    return all(
        isinstance(provider_usage.get(name), int)
        and not isinstance(provider_usage.get(name), bool)
        and provider_usage[name] > 0
        for name in ("input_tokens", "output_tokens")
    )
