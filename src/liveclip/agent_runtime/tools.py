from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from liveclip.agent_runtime.models import AgentObservation, json_bytes


class AgentToolError(ValueError):
    """Expected, safe tool rejection returned to the Agent as an observation."""


ToolHandler = Callable[[BaseModel], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    arguments_model: type[BaseModel]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self, *, max_observation_bytes: int = 512 * 1024) -> None:
        if not 1_024 <= max_observation_bytes <= 4 * 1024 * 1024:
            raise ValueError("tool observation limit is out of bounds")
        self._max_observation_bytes = max_observation_bytes
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        if not tool.name or len(tool.name) > 96:
            raise ValueError("tool name is invalid")
        if not tool.description or len(tool.description) > 2_000:
            raise ValueError("tool description is invalid")
        self._tools[tool.name] = tool

    def descriptions(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "name": tool.name,
                "description": tool.description,
                "arguments_schema": tool.arguments_model.model_json_schema(mode="validation"),
            }
            for tool in self._tools.values()
        )

    def function_definitions(self) -> tuple[dict[str, object], ...]:
        """Return strict Responses API function definitions for registered tools."""

        return tuple(
            function_tool_definition(
                name=tool.name,
                description=tool.description,
                arguments_model=tool.arguments_model,
            )
            for tool in self._tools.values()
        )

    def invoke(
        self,
        *,
        observation_number: int,
        tool_name: str,
        arguments: dict[str, object],
    ) -> AgentObservation:
        observation_id = f"obs_{observation_number:04d}"
        tool = self._tools.get(tool_name)
        if tool is None:
            return AgentObservation(
                observation_id=observation_id,
                tool="tool_registry",
                status="error",
                message=f"unknown tool: {tool_name}",
                data={"requested_tool": tool_name},
            )
        try:
            resolved = tool.arguments_model.model_validate(arguments)
            data = dict(tool.handler(resolved))
            if len(json_bytes(data)) > self._max_observation_bytes:
                raise AgentToolError("tool observation exceeds the configured size limit")
        except ValidationError as exc:
            return AgentObservation(
                observation_id=observation_id,
                tool=tool.name,
                status="error",
                message="tool arguments failed validation",
                data={
                    "errors": [
                        {
                            "location": [str(part) for part in item["loc"]],
                            "message": item["msg"],
                            "code": item["type"],
                        }
                        for item in exc.errors(include_input=False, include_url=False)
                    ]
                },
            )
        except AgentToolError as exc:
            return AgentObservation(
                observation_id=observation_id,
                tool=tool.name,
                status="error",
                message=str(exc),
            )
        return AgentObservation(
            observation_id=observation_id,
            tool=tool.name,
            status="ok",
            data=data,
        )


def function_tool_definition(
    *,
    name: str,
    description: str,
    arguments_model: type[BaseModel],
) -> dict[str, object]:
    schema = arguments_model.model_json_schema(mode="validation")
    _require_closed_object_schemas(schema)
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": schema,
        "strict": True,
    }


def _require_closed_object_schemas(value: object) -> None:
    if isinstance(value, dict):
        if value.get("type") == "object":
            if value.get("additionalProperties") is not False:
                raise ValueError(
                    "native function argument objects must forbid additional properties"
                )
            properties = value.get("properties", {})
            required = value.get("required")
            if not isinstance(properties, dict) or not isinstance(required, list):
                raise ValueError("native function argument objects must require every property")
            if set(required) != set(properties):
                raise ValueError("native function argument objects must require every property")
        for item in value.values():
            _require_closed_object_schemas(item)
    elif isinstance(value, list):
        for item in value:
            _require_closed_object_schemas(item)


__all__ = [
    "AgentToolError",
    "ToolHandler",
    "ToolRegistry",
    "ToolSpec",
    "function_tool_definition",
]
