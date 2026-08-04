from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from liveclip.bootstrap import LiveClipRuntime, local_worker_id, pipeline_config_from_settings
from liveclip.config import Settings
from liveclip.db.models import (
    ApiUsageRow,
    CandidateClipRow,
    EditPlanRevisionRow,
    TranscriptRow,
)
from liveclip.domain.state_transitions import PipelineRunStatus
from liveclip.media.ingest import MediaIngestError, resolve_allowed_source


class CloudSmokeError(RuntimeError):
    """A safe, user-actionable cloud smoke failure."""


@dataclass(frozen=True, slots=True)
class CloudSmokeResult:
    project_id: str
    run_id: str
    source_path: Path
    asr_model: str
    llm_model: str
    asr_request_ids: tuple[str, ...]
    llm_request_ids: tuple[str, ...]
    selected_clip_count: int


@dataclass(frozen=True, slots=True)
class CloudUsageEvidence:
    provider: str
    operation: str
    model: str
    request_id: str | None
    status: str


@dataclass(frozen=True, slots=True)
class CloudPlanEvidence:
    degraded: bool
    model: str


def validate_cloud_smoke_evidence(
    *,
    transcript_provider: str | None,
    usage: Sequence[CloudUsageEvidence],
    selected_plans: Sequence[CloudPlanEvidence],
    expected_asr_model: str,
    expected_llm_model: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Reject any Mock, failed, untraceable, degraded, or wrong-model success."""

    if transcript_provider != "openai":
        raise CloudSmokeError("cloud smoke failed; real OpenAI ASR evidence is missing")
    if any(row.provider != "openai" for row in usage):
        raise CloudSmokeError("cloud smoke failed; non-OpenAI provider evidence was observed")
    if any(row.status == "failed" for row in usage):
        raise CloudSmokeError("cloud smoke failed; failed provider evidence was observed")
    asr_success = tuple(
        row
        for row in usage
        if row.operation == "audio.transcriptions"
        and row.model == expected_asr_model
        and row.status == "succeeded"
    )
    llm_success = tuple(
        row
        for row in usage
        if row.operation.startswith("responses.edit.")
        and row.model == expected_llm_model
        and row.status == "succeeded"
    )
    if not asr_success or any(not row.request_id for row in asr_success):
        raise CloudSmokeError("cloud smoke failed; real OpenAI ASR evidence is missing")
    if not llm_success or any(not row.request_id for row in llm_success):
        raise CloudSmokeError("cloud smoke failed; real OpenAI Responses evidence is missing")
    if not selected_plans or any(
        row.degraded or row.model != expected_llm_model for row in selected_plans
    ):
        raise CloudSmokeError("cloud smoke failed; selected EditPlan is degraded or wrong-model")
    return (
        tuple(str(row.request_id) for row in asr_success),
        tuple(str(row.request_id) for row in llm_success),
    )


def cloud_smoke_preflight(settings: Settings, input_path: Path) -> tuple[str, ...]:
    """Return every missing/invalid prerequisite without opening DB or cloud clients."""

    issues: list[str] = []
    if settings.ai_provider != "openai":
        issues.append("LIVECLIP_AI_PROVIDER=openai")
    if not (settings.openai_api_key and settings.openai_api_key.get_secret_value().strip()):
        issues.append("OPENAI_API_KEY")
    if settings.transcription_model != "whisper-1":
        issues.append("OPENAI_TRANSCRIPTION_MODEL=whisper-1 (timestamp contract)")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", settings.llm_model):
        issues.append("OPENAI_LLM_MODEL")
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
    return tuple(issues)


def run_cloud_smoke(
    *,
    settings: Settings,
    input_path: Path,
    project_root: Path | None = None,
) -> CloudSmokeResult:
    """Run the real OpenAI pipeline and prove both providers without Mock fallback."""

    issues = cloud_smoke_preflight(settings, input_path)
    if issues:
        raise CloudSmokeError("cloud smoke not_run; missing/invalid: " + ", ".join(issues))

    config = pipeline_config_from_settings(settings, top_n=min(3, settings.default_top_n))
    if config.provider != "openai":
        raise CloudSmokeError("cloud smoke not_run; provider configuration is not OpenAI")
    with LiveClipRuntime.open(settings, project_root=project_root) as runtime:
        created = runtime.pipeline_service.create_project_and_run(
            source_path=input_path,
            config=config,
            max_stage_retries=settings.max_stage_retries,
        )
        snapshot = runtime.stage_runner.run_until_terminal(
            created.run_id,
            worker_id=local_worker_id("smoke-cloud"),
        )
        if snapshot.status != PipelineRunStatus.COMPLETED:
            code = snapshot.error_code or "CLOUD_PIPELINE_FAILED"
            raise CloudSmokeError(f"cloud smoke failed; run={created.run_id}; error={code}")

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
                ).where(ApiUsageRow.pipeline_run_id == created.run_id)
            ).all()
            selected_plans = connection.execute(
                select(
                    EditPlanRevisionRow.degraded,
                    EditPlanRevisionRow.model,
                )
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

        asr_request_ids, llm_request_ids = validate_cloud_smoke_evidence(
            transcript_provider=(
                str(transcript_provider) if transcript_provider is not None else None
            ),
            usage=tuple(
                CloudUsageEvidence(
                    provider=str(row.provider),
                    operation=str(row.operation),
                    model=str(row.model),
                    request_id=str(row.request_id) if row.request_id else None,
                    status=str(row.status),
                )
                for row in usage
            ),
            selected_plans=tuple(
                CloudPlanEvidence(degraded=bool(row.degraded), model=str(row.model))
                for row in selected_plans
            ),
            expected_asr_model=settings.transcription_model,
            expected_llm_model=settings.llm_model,
        )

        return CloudSmokeResult(
            project_id=created.project_id,
            run_id=created.run_id,
            source_path=input_path.resolve(strict=True),
            asr_model=settings.transcription_model,
            llm_model=settings.llm_model,
            asr_request_ids=asr_request_ids,
            llm_request_ids=llm_request_ids,
            selected_clip_count=len(selected_plans),
        )
