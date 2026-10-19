from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

_NAME_PATTERN = r"^[a-z][a-z0-9_.-]{0,95}$"
_ARTIFACT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
_MAX_JSON_BYTES = 512 * 1024


def json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Agent value must be finite JSON data") from exc


def validate_json_mapping(
    value: Mapping[str, object],
    *,
    label: str,
    max_bytes: int = _MAX_JSON_BYTES,
) -> None:
    encoded = json_bytes(dict(value))
    if len(encoded) > max_bytes:
        raise ValueError(f"{label} exceeds the {max_bytes}-byte limit")


class AgentArtifact(BaseModel):
    """Generic immutable output created through a registered tool."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    artifact_id: str = Field(pattern=_ARTIFACT_ID_PATTERN)
    artifact_type: str = Field(pattern=_NAME_PATTERN)
    data: dict[str, object] = Field(default_factory=dict)
    evidence: tuple[dict[str, object], ...] = Field(default_factory=tuple, max_length=256)

    @model_validator(mode="after")
    def validate_json_data(self) -> AgentArtifact:
        validate_json_mapping(self.data, label="artifact data")
        for index, item in enumerate(self.evidence):
            validate_json_mapping(item, label=f"artifact evidence {index}", max_bytes=64 * 1024)
        if len(json_bytes(self.model_dump(mode="json"))) > _MAX_JSON_BYTES:
            raise ValueError("artifact exceeds the serialized size limit")
        return self


class AgentTurn(BaseModel):
    """Stable audit form derived from one native model function call."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    action: Literal["call_tool", "finish"]
    tool: str | None = Field(default=None, pattern=_NAME_PATTERN)
    arguments_json: str = Field(default="{}", min_length=2, max_length=256 * 1024)
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=256)
    summary: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_action_shape(self) -> AgentTurn:
        arguments = self.parsed_arguments()
        if self.action == "call_tool":
            if self.tool is None:
                raise ValueError("call_tool requires a tool name")
            if self.artifact_ids:
                raise ValueError("call_tool cannot finish artifacts")
        else:
            if self.tool is not None or arguments:
                raise ValueError("finish cannot contain a tool call")
            if len(set(self.artifact_ids)) != len(self.artifact_ids):
                raise ValueError("finish artifact IDs must be unique")
        return self

    def parsed_arguments(self) -> dict[str, object]:
        try:
            value = json.loads(self.arguments_json, object_pairs_hook=_unique_json_object)
        except (TypeError, ValueError) as exc:
            raise ValueError("arguments_json must contain one JSON object") from exc
        if not isinstance(value, dict):
            raise ValueError("arguments_json must contain one JSON object")
        validate_json_mapping(value, label="tool arguments", max_bytes=256 * 1024)
        return value


class AgentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    observation_id: str = Field(pattern=r"^obs_[0-9]{4}$")
    tool: str = Field(pattern=_NAME_PATTERN)
    status: Literal["ok", "error"]
    data: dict[str, object] = Field(default_factory=dict)
    message: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_json_data(self) -> AgentObservation:
        validate_json_mapping(self.data, label="tool observation", max_bytes=512 * 1024)
        return self


class AgentModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    call_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    turn: AgentTurn
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metadata(self) -> AgentModelResponse:
        validate_json_mapping(self.metadata, label="model metadata", max_bytes=256 * 1024)
        return self


class AgentToolResult(BaseModel):
    """One Harness-owned function result returned to the model by call ID."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    call_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    tool: str = Field(pattern=_NAME_PATTERN)
    observation: AgentObservation


class FinishArguments(BaseModel):
    """Native finish function arguments; completion is still validated by Harness."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    artifact_ids: list[str] = Field(max_length=256)
    summary: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_artifact_ids(self) -> FinishArguments:
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("finish artifact IDs must be unique")
        return self


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    turn_number: int = Field(ge=1)
    function_call_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,160}$")
    action: AgentTurn
    observation: AgentObservation | None = None
    model_metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metadata(self) -> AgentEvent:
        validate_json_mapping(self.model_metadata, label="event metadata", max_bytes=256 * 1024)
        if self.action.action == "call_tool" and self.observation is None:
            raise ValueError("tool action event requires an observation")
        if (
            self.action.action == "finish"
            and self.observation is not None
            and self.observation.tool != "finish_validation"
        ):
            raise ValueError("finish event can only carry finish validation feedback")
        return self


class AgentRunLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_turns: int = Field(default=24, ge=1, le=256)
    max_repeated_action: int = Field(default=3, ge=1, le=10)
    max_context_bytes: int = Field(default=2 * 1024 * 1024, ge=16 * 1024, le=8 * 1024 * 1024)
    max_initial_context_bytes: int = Field(
        default=512 * 1024,
        ge=1_024,
        le=4 * 1024 * 1024,
    )
    max_artifacts: int = Field(default=256, ge=1, le=2_000)


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["4"] = "4"
    run_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    status: Literal["completed"] = "completed"
    run_identity_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_version: str = Field(min_length=1, max_length=128)
    skill_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    model_settings: dict[str, object] = Field(default_factory=dict)
    initial_context: dict[str, object]
    events: tuple[AgentEvent, ...]
    artifacts: tuple[AgentArtifact, ...]
    summary: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_initial_context(self) -> AgentRunResult:
        validate_json_mapping(
            self.model_settings,
            label="completed Agent model settings",
            max_bytes=64 * 1024,
        )
        validate_json_mapping(
            self.initial_context,
            label="completed Agent initial Context",
            max_bytes=4 * 1024 * 1024,
        )
        return self


class AgentTurnModel(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def generate_turn(
        self,
        *,
        run_id: str,
        turn_number: int,
        instructions: str,
        payload: dict[str, object],
        tool_definitions: tuple[dict[str, object], ...],
        previous_tool_result: AgentToolResult | None,
        cancel_requested: Callable[[], bool],
    ) -> AgentModelResponse: ...


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


__all__ = [
    "AgentArtifact",
    "AgentEvent",
    "AgentModelResponse",
    "AgentObservation",
    "AgentRunLimits",
    "AgentRunResult",
    "AgentToolResult",
    "AgentTurn",
    "AgentTurnModel",
    "FinishArguments",
    "json_bytes",
    "validate_json_mapping",
]
