from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence

from liveclip.agent_runtime.artifacts import ArtifactStore
from liveclip.agent_runtime.checkpoints import (
    AgentRunIdentity,
    AgentRunJournal,
    build_agent_run_identity,
)
from liveclip.agent_runtime.context import build_agent_payload
from liveclip.agent_runtime.models import (
    AgentArtifact,
    AgentEvent,
    AgentObservation,
    AgentRunLimits,
    AgentRunResult,
    AgentToolResult,
    AgentTurnModel,
    FinishArguments,
    json_bytes,
    validate_json_mapping,
)
from liveclip.agent_runtime.skills import LoadedAgentSkill
from liveclip.agent_runtime.tools import ToolRegistry, function_tool_definition

ArtifactValidator = Callable[[Sequence[AgentArtifact]], Sequence[str]]


class AgentRunCancelled(RuntimeError):
    def __init__(self, events: tuple[AgentEvent, ...]) -> None:
        super().__init__("Agent run was cancelled")
        self.events = events


class AgentRunLimitError(RuntimeError):
    def __init__(self, message: str, events: tuple[AgentEvent, ...]) -> None:
        super().__init__(message)
        self.events = events


class AgentHarness:
    """Bounded action/observation Harness with no editorial policy."""

    def __init__(
        self,
        *,
        skill: LoadedAgentSkill,
        model: AgentTurnModel,
        tools: ToolRegistry,
        artifacts: ArtifactStore,
        limits: AgentRunLimits | None = None,
        artifact_validator: ArtifactValidator | None = None,
        journal: AgentRunJournal | None = None,
    ) -> None:
        self._skill = skill
        self._model = model
        self._tools = tools
        self._artifacts = artifacts
        self._limits = limits or AgentRunLimits()
        self._artifact_validator = artifact_validator
        self._journal = journal

    def run(
        self,
        *,
        run_id: str,
        task: str,
        initial_context: Mapping[str, object],
        resume_extra_turns: int = 0,
        cancel_requested: Callable[[], bool] = lambda: False,
    ) -> AgentRunResult:
        if resume_extra_turns < 0:
            raise ValueError("resume_extra_turns must be non-negative")
        tool_definitions = (
            *self._tools.function_definitions(),
            function_tool_definition(
                name="finish",
                description=(
                    "Finish the Agent run with immutable Artifact IDs already stored by tools. "
                    "The Harness performs final technical validation before accepting completion."
                ),
                arguments_model=FinishArguments,
            ),
        )
        context = dict(initial_context)
        model_settings = _model_identity_settings(self._model)
        identity = build_agent_run_identity(
            run_id=run_id,
            skill_version=self._skill.version,
            skill_sha256=self._skill.sha256,
            provider=self._model.provider_name,
            model=self._model.model_name,
            model_settings=model_settings,
            task=task,
            initial_context=context,
            tool_definitions=tool_definitions,
            limits=self._limits,
        )
        events: list[AgentEvent] = []
        if self._journal is not None:
            self._journal.initialize(identity)
            completed = self._journal.load_completed(identity)
            if completed is not None:
                return completed
            checkpoint = self._journal.load_checkpoint(identity)
            if checkpoint is not None:
                for artifact in checkpoint.artifacts:
                    self._artifacts.add(artifact)
                events.extend(checkpoint.events)
        if resume_extra_turns and not events:
            raise ValueError("resume_extra_turns requires an existing Agent checkpoint")
        (
            previous_action_hash,
            repeated_action_count,
            observation_number,
            previous_tool_result,
            seen_call_ids,
        ) = self._restore_loop_state(events)
        recovered = self._recover_completed_result(
            identity=identity,
            events=events,
            run_id=run_id,
            initial_context=context,
            model_settings=model_settings,
        )
        if recovered is not None:
            return recovered
        turn_limit = self._limits.max_turns + resume_extra_turns
        for turn_number in range(len(events) + 1, turn_limit + 1):
            if cancel_requested():
                raise AgentRunCancelled(tuple(events))
            payload = build_agent_payload(
                task=task,
                turn_number=turn_number,
                skill=self._skill,
                initial_context=context,
                tool_descriptions=self._tools.descriptions(),
                events=events,
                artifacts=self._artifacts.all(),
                limits=self._limits,
            )
            response = self._model.generate_turn(
                run_id=run_id,
                turn_number=turn_number,
                instructions=self._skill.instructions,
                payload=payload,
                tool_definitions=tool_definitions,
                previous_tool_result=previous_tool_result,
                cancel_requested=cancel_requested,
            )
            if response.call_id in seen_call_ids:
                raise AgentRunLimitError(
                    "Agent provider reused a native function call ID",
                    tuple(events),
                )
            seen_call_ids.add(response.call_id)
            action = response.turn
            action_hash = hashlib.sha256(json_bytes(action.model_dump(mode="json"))).hexdigest()
            if action_hash == previous_action_hash:
                repeated_action_count += 1
            else:
                previous_action_hash = action_hash
                repeated_action_count = 1
            if repeated_action_count > self._limits.max_repeated_action:
                raise AgentRunLimitError(
                    "Agent repeated the same action beyond the configured limit",
                    tuple(events),
                )
            if action.action == "call_tool":
                assert action.tool is not None
                observation_number += 1
                observation = self._tools.invoke(
                    observation_number=observation_number,
                    tool_name=action.tool,
                    arguments=action.parsed_arguments(),
                )
                event = AgentEvent(
                    turn_number=turn_number,
                    function_call_id=response.call_id,
                    action=action,
                    observation=observation,
                    model_metadata=response.metadata,
                )
                events.append(event)
                self._save_checkpoint(identity, events)
                previous_tool_result = AgentToolResult(
                    call_id=response.call_id,
                    tool=action.tool,
                    observation=observation,
                )
                continue
            errors: tuple[str, ...]
            try:
                finished_artifacts = self._artifacts.resolve(action.artifact_ids)
            except ValueError as exc:
                errors = (str(exc),)
            else:
                errors = tuple(
                    self._artifact_validator(finished_artifacts)
                    if self._artifact_validator is not None
                    else ()
                )
            if errors:
                observation_number += 1
                observation = AgentObservation(
                    observation_id=f"obs_{observation_number:04d}",
                    tool="finish_validation",
                    status="error",
                    message="finished artifacts failed technical validation",
                    data={"errors": list(errors)},
                )
                event = AgentEvent(
                    turn_number=turn_number,
                    function_call_id=response.call_id,
                    action=action,
                    observation=observation,
                    model_metadata=response.metadata,
                )
                events.append(event)
                self._save_checkpoint(identity, events)
                previous_tool_result = AgentToolResult(
                    call_id=response.call_id,
                    tool="finish",
                    observation=observation,
                )
                continue
            final_metadata = dict(response.metadata)
            finalize_completion = getattr(self._model, "finalize_completion", None)
            if callable(finalize_completion):
                completion_metadata = finalize_completion(
                    run_id=run_id,
                    call_id=response.call_id,
                    cancel_requested=cancel_requested,
                )
                if not isinstance(completion_metadata, dict):
                    raise ValueError("Agent model completion metadata must be a JSON object")
                validate_json_mapping(
                    completion_metadata,
                    label="Agent model completion metadata",
                    max_bytes=64 * 1024,
                )
                final_metadata["completion"] = completion_metadata
            event = AgentEvent(
                turn_number=turn_number,
                function_call_id=response.call_id,
                action=action,
                model_metadata=final_metadata,
            )
            events.append(event)
            self._save_checkpoint(identity, events)
            result = AgentRunResult(
                run_id=run_id,
                run_identity_sha256=identity.sha256,
                skill_version=self._skill.version,
                skill_sha256=self._skill.sha256,
                provider=self._model.provider_name,
                model=self._model.model_name,
                model_settings=model_settings,
                initial_context=context,
                events=tuple(events),
                artifacts=finished_artifacts,
                summary=action.summary,
            )
            if self._journal is not None:
                self._journal.save_completed(identity, result)
            return result
        raise AgentRunLimitError("Agent exhausted its turn budget", tuple(events))

    def _save_checkpoint(
        self,
        identity: AgentRunIdentity,
        events: list[AgentEvent],
    ) -> None:
        if self._journal is not None:
            self._journal.save_checkpoint(
                identity,
                events=tuple(events),
                artifacts=self._artifacts.all(),
            )

    def _recover_completed_result(
        self,
        *,
        identity: AgentRunIdentity,
        events: list[AgentEvent],
        run_id: str,
        initial_context: dict[str, object],
        model_settings: dict[str, object],
    ) -> AgentRunResult | None:
        if not events:
            return None
        final_event = events[-1]
        if final_event.action.action != "finish" or final_event.observation is not None:
            return None
        finished_artifacts = self._artifacts.resolve(final_event.action.artifact_ids)
        errors = tuple(
            self._artifact_validator(finished_artifacts)
            if self._artifact_validator is not None
            else ()
        )
        if errors:
            raise ValueError("completed Agent checkpoint fails current technical validation")
        result = AgentRunResult(
            run_id=run_id,
            run_identity_sha256=identity.sha256,
            skill_version=self._skill.version,
            skill_sha256=self._skill.sha256,
            provider=self._model.provider_name,
            model=self._model.model_name,
            model_settings=model_settings,
            initial_context=initial_context,
            events=tuple(events),
            artifacts=finished_artifacts,
            summary=final_event.action.summary,
        )
        if self._journal is not None:
            self._journal.save_completed(identity, result)
        return result

    def _restore_loop_state(
        self,
        events: Sequence[AgentEvent],
    ) -> tuple[str | None, int, int, AgentToolResult | None, set[str]]:
        previous_action_hash: str | None = None
        repeated_action_count = 0
        observation_number = 0
        seen_call_ids: set[str] = set()
        for event in events:
            if event.function_call_id in seen_call_ids:
                raise ValueError("Agent checkpoint repeats a native function call ID")
            seen_call_ids.add(event.function_call_id)
            action_hash = hashlib.sha256(
                json_bytes(event.action.model_dump(mode="json"))
            ).hexdigest()
            if action_hash == previous_action_hash:
                repeated_action_count += 1
            else:
                previous_action_hash = action_hash
                repeated_action_count = 1
            if repeated_action_count > self._limits.max_repeated_action:
                raise ValueError("Agent checkpoint exceeds the repeated-action limit")
            observation_number += int(event.observation is not None)
        previous_tool_result: AgentToolResult | None = None
        if events and events[-1].observation is not None:
            final_event = events[-1]
            tool = final_event.action.tool if final_event.action.action == "call_tool" else "finish"
            assert tool is not None
            assert final_event.observation is not None
            previous_tool_result = AgentToolResult(
                call_id=final_event.function_call_id,
                tool=tool,
                observation=final_event.observation,
            )
        return (
            previous_action_hash,
            repeated_action_count,
            observation_number,
            previous_tool_result,
            seen_call_ids,
        )


def _model_identity_settings(model: AgentTurnModel) -> dict[str, object]:
    raw = getattr(model, "identity_settings", {})
    value = raw() if callable(raw) else raw
    if not isinstance(value, Mapping):
        raise ValueError("Agent model identity settings must be a JSON object")
    settings = dict(value)
    validate_json_mapping(
        settings,
        label="Agent model identity settings",
        max_bytes=64 * 1024,
    )
    return settings


__all__ = [
    "AgentHarness",
    "AgentRunCancelled",
    "AgentRunLimitError",
    "ArtifactValidator",
]
