from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

from liveclip.agent_runtime.artifacts import ArtifactStore
from liveclip.agent_runtime.checkpoints import AgentRunJournal
from liveclip.agent_runtime.codex_app_server import CodexAppServerAgentTurnModel
from liveclip.agent_runtime.harness import AgentHarness
from liveclip.agent_runtime.models import AgentRunLimits, AgentRunResult, AgentTurnModel
from liveclip.agent_runtime.native_openai import OpenAINativeAgentTurnModel
from liveclip.agent_runtime.skills import LoadedAgentSkill, load_packaged_agent_skill
from liveclip.agent_tools.clipping import (
    ClippingTechnicalConfig,
    build_clipping_tool_registry,
    validate_clipping_artifacts,
)
from liveclip.agent_tools.subtitle_calibration import SubtitleCalibrationBackend
from liveclip.config.settings import Settings
from liveclip.media.secure_files import (
    ensure_directory_no_follow,
    hash_regular_file_no_follow,
    write_text_immutable_no_follow,
)
from liveclip.pipeline.srt import load_srt_transcript
from liveclip.providers.openai_retry import OpenAIRetryPolicy

AgentTurnModelFactory = Callable[[LoadedAgentSkill], AgentTurnModel]
AgentReasoningEffort = Literal["low", "medium", "high", "xhigh"]


def configured_agent_turn_model_factory(
    settings: Settings,
    *,
    reasoning_effort: AgentReasoningEffort = "high",
    state_dir: Path | None = None,
) -> AgentTurnModelFactory:
    if settings.agent_provider == "codex-app-server":

        def create_codex_app_server(skill: LoadedAgentSkill) -> AgentTurnModel:
            return CodexAppServerAgentTurnModel(
                skill=skill,
                model_name_value=settings.llm_model,
                codex_executable=settings.codex_executable,
                timeout_seconds=settings.openai_request_timeout_seconds,
                reasoning_effort=reasoning_effort,
                state_dir=state_dir,
            )

        return create_codex_app_server
    if settings.agent_provider != "openai-responses" or settings.ai_provider != "openai":
        raise ValueError(
            "prompt-first Agent native function calling currently requires "
            "LIVECLIP_AGENT_PROVIDER=codex-app-server with ChatGPT OAuth, or "
            "LIVECLIP_AGENT_PROVIDER=openai-responses and LIVECLIP_AI_PROVIDER=openai"
        )
    key = settings.openai_api_key

    def create(skill: LoadedAgentSkill) -> AgentTurnModel:
        return OpenAINativeAgentTurnModel(
            skill=skill,
            model_name_value=settings.llm_model,
            api_key=key.get_secret_value() if key is not None else None,
            timeout_seconds=settings.openai_request_timeout_seconds,
            retry_policy=OpenAIRetryPolicy(
                max_retries=settings.openai_max_request_retries,
                base_delay_seconds=settings.openai_retry_base_seconds,
                max_delay_seconds=settings.openai_retry_max_seconds,
            ),
            reasoning_effort=reasoning_effort,
            state_dir=state_dir,
        )

    return create


def run_agent_clipping_v2(
    *,
    transcript_path: Path,
    run_id: str,
    task: str,
    model_factory: AgentTurnModelFactory,
    initial_context: Mapping[str, object] | None = None,
    skill_id: str = "agent_clipping_v2",
    limits: AgentRunLimits | None = None,
    subtitle_calibration: SubtitleCalibrationBackend | None = None,
    checkpoint_dir: Path | None = None,
    resume_extra_turns: int = 0,
    cancel_requested: Callable[[], bool] = lambda: False,
) -> AgentRunResult:
    """Run the prompt-first clipping vertical slice over timestamped SRT evidence."""

    skill = load_packaged_agent_skill(skill_id)
    config = ClippingTechnicalConfig.model_validate(dict(skill.configuration))
    transcript = load_srt_transcript(transcript_path)
    transcript_sha256, transcript_size = hash_regular_file_no_follow(
        transcript_path,
        cancel_requested=cancel_requested,
    )
    resolved_limits = limits or AgentRunLimits()
    artifacts = ArtifactStore(max_artifacts=resolved_limits.max_artifacts)
    tools = build_clipping_tool_registry(
        transcript=transcript,
        config=config,
        artifacts=artifacts,
        subtitle_calibration=subtitle_calibration,
        cancel_requested=cancel_requested,
    )
    model = model_factory(skill)
    harness = AgentHarness(
        skill=skill,
        model=model,
        tools=tools,
        artifacts=artifacts,
        limits=resolved_limits,
        artifact_validator=lambda values: validate_clipping_artifacts(
            values,
            transcript=transcript,
            config=config,
        ),
        journal=AgentRunJournal(checkpoint_dir / "journal") if checkpoint_dir is not None else None,
    )
    caller_context = dict(initial_context or {})
    caller_context["source"] = {
        "transcript_sha256": transcript_sha256,
        "transcript_size_bytes": transcript_size,
        "source_duration_ms": transcript.source_duration_ms,
        "cue_count": len(transcript.segments),
        "language": transcript.language,
    }
    try:
        return harness.run(
            run_id=run_id,
            task=task,
            initial_context=caller_context,
            resume_extra_turns=resume_extra_turns,
            cancel_requested=cancel_requested,
        )
    finally:
        close_model = getattr(model, "close", None)
        if callable(close_model):
            close_model()


def write_agent_run_result(path: Path, result: AgentRunResult) -> str:
    """Persist one immutable Agent result and return its exact SHA-256."""

    parent = ensure_directory_no_follow(path.parent.resolve(strict=True))
    destination = parent / path.name
    payload = (
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    write_text_immutable_no_follow(destination, payload, max_bytes=64 * 1024 * 1024)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "AgentReasoningEffort",
    "AgentTurnModelFactory",
    "configured_agent_turn_model_factory",
    "run_agent_clipping_v2",
    "write_agent_run_result",
]
