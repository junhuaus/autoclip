from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from liveclip.agent_runtime.models import AgentObservation, AgentToolResult, FinishArguments
from liveclip.agent_runtime.native_openai import (
    NativeAgentProviderError,
    OpenAINativeAgentTurnModel,
)
from liveclip.agent_runtime.skills import load_packaged_agent_skill
from liveclip.agent_runtime.tools import function_tool_definition
from liveclip.config.settings import Settings
from liveclip.services.agent_clipping import configured_agent_turn_model_factory


class _EchoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    value: int


class _Responses:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(dict(kwargs))
        return self._responses.pop(0)


class _Client:
    def __init__(self, responses: list[object]) -> None:
        self.responses = _Responses(responses)


def _response(*, response_id: str, call_id: str, name: str, arguments: dict[str, object]) -> object:
    return SimpleNamespace(
        id=response_id,
        status="completed",
        usage=None,
        output=(
            SimpleNamespace(
                type="function_call",
                call_id=call_id,
                name=name,
                arguments=json.dumps(arguments, ensure_ascii=False),
            ),
        ),
    )


def test_openai_native_transport_returns_function_output_by_exact_call_id() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    client = _Client(
        [
            _response(
                response_id="resp_1",
                call_id="call_echo",
                name="echo",
                arguments={"value": 7},
            ),
            _response(
                response_id="resp_2",
                call_id="call_finish",
                name="finish",
                arguments={"artifact_ids": [], "summary": "done"},
            ),
        ]
    )
    model = OpenAINativeAgentTurnModel(
        skill=skill,
        model_name_value="gpt-test",
        client=client,
    )
    definitions = (
        function_tool_definition(
            name="echo",
            description="Echo one integer.",
            arguments_model=_EchoArguments,
        ),
        function_tool_definition(
            name="finish",
            description="Finish the test.",
            arguments_model=FinishArguments,
        ),
    )

    first = model.generate_turn(
        run_id="native_test",
        turn_number=1,
        instructions=skill.instructions,
        payload={"task": "test native calls"},
        tool_definitions=definitions,
        previous_tool_result=None,
        cancel_requested=lambda: False,
    )
    second = model.generate_turn(
        run_id="native_test",
        turn_number=2,
        instructions=skill.instructions,
        payload={"ignored_after_first_turn": True},
        tool_definitions=definitions,
        previous_tool_result=AgentToolResult(
            call_id=first.call_id,
            tool="echo",
            observation=AgentObservation(
                observation_id="obs_0001",
                tool="echo",
                status="ok",
                data={"value": 7},
            ),
        ),
        cancel_requested=lambda: False,
    )

    assert first.turn.tool == "echo"
    assert first.turn.parsed_arguments() == {"value": 7}
    assert second.turn.action == "finish"
    assert second.turn.summary == "done"
    first_request, second_request = client.responses.requests
    assert first_request["store"] is False
    assert first_request["parallel_tool_calls"] is False
    assert first_request["tool_choice"] == "required"
    assert first_request["include"] == ["reasoning.encrypted_content"]
    assert first_request["tools"] == list(definitions)
    second_input = second_request["input"]
    assert isinstance(second_input, list)
    function_output = second_input[-1]
    assert isinstance(function_output, dict)
    assert function_output["type"] == "function_call_output"
    assert function_output["call_id"] == "call_echo"
    assert json.loads(str(function_output["output"]))["data"] == {"value": 7}


def test_openai_native_transport_recovers_pending_response_and_reasoning(
    tmp_path: Path,
) -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    first_client = _Client(
        [
            SimpleNamespace(
                id="resp_reasoning",
                status="completed",
                usage=None,
                output=(
                    SimpleNamespace(
                        type="reasoning",
                        id="rs_1",
                        summary=[],
                        encrypted_content="opaque-reasoning",
                    ),
                    SimpleNamespace(
                        type="function_call",
                        call_id="call_echo",
                        name="echo",
                        arguments='{"value":7}',
                    ),
                ),
            )
        ]
    )
    definitions = (
        function_tool_definition(
            name="echo",
            description="Echo one integer.",
            arguments_model=_EchoArguments,
        ),
        function_tool_definition(
            name="finish",
            description="Finish the test.",
            arguments_model=FinishArguments,
        ),
    )
    first_model = OpenAINativeAgentTurnModel(
        skill=skill,
        model_name_value="gpt-test",
        client=first_client,
        state_dir=tmp_path / "provider-state",
    )
    first = first_model.generate_turn(
        run_id="native_resume",
        turn_number=1,
        instructions=skill.instructions,
        payload={"task": "persist reasoning"},
        tool_definitions=definitions,
        previous_tool_result=None,
        cancel_requested=lambda: False,
    )

    second_client = _Client(
        [
            _response(
                response_id="resp_finish",
                call_id="call_finish",
                name="finish",
                arguments={"artifact_ids": [], "summary": "resumed"},
            )
        ]
    )
    resumed_model = OpenAINativeAgentTurnModel(
        skill=skill,
        model_name_value="gpt-test",
        client=second_client,
        state_dir=tmp_path / "provider-state",
    )
    recovered = resumed_model.generate_turn(
        run_id="native_resume",
        turn_number=1,
        instructions=skill.instructions,
        payload={"task": "persist reasoning"},
        tool_definitions=definitions,
        previous_tool_result=None,
        cancel_requested=lambda: False,
    )
    assert recovered == first.model_copy(
        update={"metadata": {**first.metadata, "response_recovered": True}}
    )
    assert second_client.responses.requests == []

    resumed_model.generate_turn(
        run_id="native_resume",
        turn_number=2,
        instructions=skill.instructions,
        payload={"ignored_after_first_turn": True},
        tool_definitions=definitions,
        previous_tool_result=AgentToolResult(
            call_id="call_echo",
            tool="echo",
            observation=AgentObservation(
                observation_id="obs_0001",
                tool="echo",
                status="ok",
                data={"value": 7},
            ),
        ),
        cancel_requested=lambda: False,
    )
    replay = second_client.responses.requests[0]["input"]
    assert isinstance(replay, list)
    assert any(
        isinstance(item, dict) and item.get("encrypted_content") == "opaque-reasoning"
        for item in replay
    )
    assert replay[-1]["type"] == "function_call_output"

    changed_settings = OpenAINativeAgentTurnModel(
        skill=skill,
        model_name_value="gpt-test",
        reasoning_effort="medium",
        client=_Client([]),
        state_dir=tmp_path / "provider-state",
    )
    with pytest.raises(ValueError, match="identity differs"):
        changed_settings.generate_turn(
            run_id="native_resume",
            turn_number=1,
            instructions=skill.instructions,
            payload={"task": "persist reasoning"},
            tool_definitions=definitions,
            previous_tool_result=None,
            cancel_requested=lambda: False,
        )


def test_native_transport_rejects_multiple_function_calls() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    client = _Client(
        [
            SimpleNamespace(
                id="resp_many",
                status="completed",
                usage=None,
                output=(
                    SimpleNamespace(
                        type="function_call",
                        call_id="call_1",
                        name="echo",
                        arguments='{"value":1}',
                    ),
                    SimpleNamespace(
                        type="function_call",
                        call_id="call_2",
                        name="echo",
                        arguments='{"value":2}',
                    ),
                ),
            )
        ]
    )
    model = OpenAINativeAgentTurnModel(
        skill=skill,
        model_name_value="gpt-test",
        client=client,
    )

    with pytest.raises(NativeAgentProviderError, match="native Agent"):
        model.generate_turn(
            run_id="native_many",
            turn_number=1,
            instructions=skill.instructions,
            payload={"task": "reject parallel calls"},
            tool_definitions=(
                function_tool_definition(
                    name="echo",
                    description="Echo one integer.",
                    arguments_model=_EchoArguments,
                ),
            ),
            previous_tool_result=None,
            cancel_requested=lambda: False,
        )


def test_native_transport_rejects_mismatched_function_result_call_id() -> None:
    skill = load_packaged_agent_skill("agent_clipping_v2")
    model = OpenAINativeAgentTurnModel(
        skill=skill,
        model_name_value="gpt-test",
        client=_Client(
            [
                _response(
                    response_id="resp_1",
                    call_id="call_expected",
                    name="echo",
                    arguments={"value": 7},
                )
            ]
        ),
    )
    definitions = (
        function_tool_definition(
            name="echo",
            description="Echo one integer.",
            arguments_model=_EchoArguments,
        ),
    )
    model.generate_turn(
        run_id="native_mismatch",
        turn_number=1,
        instructions=skill.instructions,
        payload={"task": "test result identity"},
        tool_definitions=definitions,
        previous_tool_result=None,
        cancel_requested=lambda: False,
    )

    with pytest.raises(ValueError, match="pending call"):
        model.generate_turn(
            run_id="native_mismatch",
            turn_number=2,
            instructions=skill.instructions,
            payload={"ignored_after_first_turn": True},
            tool_definitions=definitions,
            previous_tool_result=AgentToolResult(
                call_id="call_wrong",
                tool="echo",
                observation=AgentObservation(
                    observation_id="obs_0001",
                    tool="echo",
                    status="ok",
                    data={"value": 7},
                ),
            ),
            cancel_requested=lambda: False,
        )


def test_native_function_definition_rejects_non_required_fields() -> None:
    class _NonStrictArguments(BaseModel):
        model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

        optional_by_default: str = ""

    with pytest.raises(ValueError, match="require every property"):
        function_tool_definition(
            name="non_strict",
            description="This schema must not reach the provider.",
            arguments_model=_NonStrictArguments,
        )


def test_configured_agent_factory_refuses_non_native_codex_transport() -> None:
    settings = Settings(
        ai_provider="openrouter-codex",
        agent_provider="openai-responses",
        _env_file=None,
    )

    with pytest.raises(ValueError, match="native function calling"):
        configured_agent_turn_model_factory(settings)
