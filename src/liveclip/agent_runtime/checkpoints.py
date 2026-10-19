from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.agent_runtime.models import (
    AgentArtifact,
    AgentEvent,
    AgentRunLimits,
    AgentRunResult,
    json_bytes,
    validate_json_mapping,
)
from liveclip.media.secure_files import (
    SecureFileError,
    SecureFileMissing,
    ensure_directory_no_follow,
    read_regular_text_no_follow,
    write_text_atomic_no_follow,
    write_text_immutable_no_follow,
)

_MAX_CHECKPOINT_BYTES = 64 * 1024 * 1024
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class AgentRunIdentity(BaseModel):
    """Exact immutable identity required to reuse one Agent run journal."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["2"] = "2"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    skill_version: str = Field(min_length=1, max_length=128)
    skill_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    model_settings: dict[str, object]
    task_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    initial_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    tool_definitions_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    limits: AgentRunLimits

    @model_validator(mode="after")
    def validate_model_settings(self) -> AgentRunIdentity:
        validate_json_mapping(
            self.model_settings,
            label="Agent identity model settings",
            max_bytes=64 * 1024,
        )
        return self

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json_bytes(self.model_dump(mode="json"))).hexdigest()


class AgentRunCheckpoint(BaseModel):
    """One complete post-turn snapshot; partial tool state is never accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    identity_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sequence: int = Field(ge=0, le=256)
    events: tuple[AgentEvent, ...]
    artifacts: tuple[AgentArtifact, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> AgentRunCheckpoint:
        if self.sequence != len(self.events):
            raise ValueError("Agent checkpoint sequence differs from its event count")
        expected_turns = tuple(range(1, self.sequence + 1))
        if tuple(value.turn_number for value in self.events) != expected_turns:
            raise ValueError("Agent checkpoint turns are not contiguous")
        call_ids = tuple(value.function_call_id for value in self.events)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("Agent checkpoint repeats a native function call ID")
        observation_numbers = tuple(
            int(value.observation.observation_id.removeprefix("obs_"))
            for value in self.events
            if value.observation is not None
        )
        if observation_numbers != tuple(range(1, len(observation_numbers) + 1)):
            raise ValueError("Agent checkpoint observations are not contiguous")
        artifact_ids = tuple(value.artifact_id for value in self.artifacts)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Agent checkpoint repeats an Artifact ID")
        return self


class AgentCompletedCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    identity_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result: AgentRunResult


class AgentRunJournal:
    """Symlink-safe durable snapshots for one hash-bound Agent run."""

    def __init__(self, root: Path) -> None:
        self.root = ensure_directory_no_follow(root)
        self._identity_path = self.root / "identity.json"
        self._checkpoint_path = self.root / "checkpoint.json"
        self._completed_path = self.root / "completed.json"

    def initialize(self, identity: AgentRunIdentity) -> None:
        payload = _json_text(identity)
        try:
            write_text_immutable_no_follow(
                self._identity_path,
                payload,
                max_bytes=_MAX_CHECKPOINT_BYTES,
            )
        except SecureFileError as exc:
            raise ValueError("Agent journal identity conflicts with this run") from exc
        observed = self._read(self._identity_path, AgentRunIdentity)
        if observed != identity:
            raise ValueError("Agent journal identity conflicts with this run")

    def load_checkpoint(self, identity: AgentRunIdentity) -> AgentRunCheckpoint | None:
        value = self._read_optional(self._checkpoint_path, AgentRunCheckpoint)
        if value is not None and value.identity_sha256 != identity.sha256:
            raise ValueError("Agent checkpoint belongs to a different run identity")
        return value

    def save_checkpoint(
        self,
        identity: AgentRunIdentity,
        *,
        events: tuple[AgentEvent, ...],
        artifacts: tuple[AgentArtifact, ...],
    ) -> AgentRunCheckpoint:
        value = AgentRunCheckpoint(
            identity_sha256=identity.sha256,
            sequence=len(events),
            events=events,
            artifacts=artifacts,
        )
        previous = self.load_checkpoint(identity)
        if previous is not None:
            if previous == value:
                return previous
            if previous.sequence + 1 != value.sequence:
                raise ValueError("Agent checkpoint update skipped or rewound a turn")
            if value.events[: previous.sequence] != previous.events:
                raise ValueError("Agent checkpoint history changed")
            if value.artifacts[: len(previous.artifacts)] != previous.artifacts:
                raise ValueError("Agent checkpoint Artifact history changed")
        write_text_atomic_no_follow(
            self._checkpoint_path,
            _json_text(value),
            max_bytes=_MAX_CHECKPOINT_BYTES,
        )
        observed = self._read(self._checkpoint_path, AgentRunCheckpoint)
        if observed != value:
            raise ValueError("Agent checkpoint publication is inconsistent")
        return value

    def load_completed(self, identity: AgentRunIdentity) -> AgentRunResult | None:
        value = self._read_optional(self._completed_path, AgentCompletedCheckpoint)
        if value is None:
            return None
        if value.identity_sha256 != identity.sha256:
            raise ValueError("completed Agent result belongs to a different run identity")
        if (
            value.result.run_id != identity.run_id
            or value.result.run_identity_sha256 != identity.sha256
            or value.result.skill_version != identity.skill_version
            or value.result.skill_sha256 != identity.skill_sha256
            or value.result.provider != identity.provider
            or value.result.model != identity.model
            or value.result.model_settings != identity.model_settings
            or hashlib.sha256(json_bytes(value.result.initial_context)).hexdigest()
            != identity.initial_context_sha256
        ):
            raise ValueError("completed Agent result identity is inconsistent")
        checkpoint = self.load_checkpoint(identity)
        if checkpoint is None or checkpoint.events != value.result.events:
            raise ValueError("completed Agent result lacks its exact checkpoint history")
        checkpoint_artifacts = {item.artifact_id: item for item in checkpoint.artifacts}
        if any(
            checkpoint_artifacts.get(item.artifact_id) != item for item in value.result.artifacts
        ):
            raise ValueError("completed Agent result Artifact evidence is inconsistent")
        return value.result

    def save_completed(
        self,
        identity: AgentRunIdentity,
        result: AgentRunResult,
    ) -> None:
        value = AgentCompletedCheckpoint(identity_sha256=identity.sha256, result=result)
        try:
            write_text_immutable_no_follow(
                self._completed_path,
                _json_text(value),
                max_bytes=_MAX_CHECKPOINT_BYTES,
            )
        except SecureFileError as exc:
            raise ValueError("completed Agent result conflicts with existing evidence") from exc
        if self._read(self._completed_path, AgentCompletedCheckpoint) != value:
            raise ValueError("completed Agent result publication is inconsistent")

    @staticmethod
    def _read(path: Path, model: type[_ModelT]) -> _ModelT:
        try:
            return model.model_validate_json(
                read_regular_text_no_follow(path, max_bytes=_MAX_CHECKPOINT_BYTES)
            )
        except (SecureFileError, ValueError) as exc:
            raise ValueError(f"Agent journal file is invalid: {path.name}") from exc

    @classmethod
    def _read_optional(cls, path: Path, model: type[_ModelT]) -> _ModelT | None:
        try:
            return cls._read(path, model)
        except ValueError as exc:
            if isinstance(exc.__cause__, SecureFileMissing):
                return None
            raise


def build_agent_run_identity(
    *,
    run_id: str,
    skill_version: str,
    skill_sha256: str,
    provider: str,
    model: str,
    model_settings: dict[str, object],
    task: str,
    initial_context: dict[str, object],
    tool_definitions: tuple[dict[str, object], ...],
    limits: AgentRunLimits,
) -> AgentRunIdentity:
    return AgentRunIdentity(
        run_id=run_id,
        skill_version=skill_version,
        skill_sha256=skill_sha256,
        provider=provider,
        model=model,
        model_settings=model_settings,
        task_sha256=hashlib.sha256(task.encode("utf-8")).hexdigest(),
        initial_context_sha256=hashlib.sha256(json_bytes(initial_context)).hexdigest(),
        tool_definitions_sha256=hashlib.sha256(json_bytes(tool_definitions)).hexdigest(),
        limits=limits,
    )


def _json_text(value: BaseModel) -> str:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


__all__ = [
    "AgentCompletedCheckpoint",
    "AgentRunCheckpoint",
    "AgentRunIdentity",
    "AgentRunJournal",
    "build_agent_run_identity",
]
