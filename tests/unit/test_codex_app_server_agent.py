from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from liveclip.agent_runtime.codex_app_server import (
    CodexAppServerAgentTurnModel,
    CodexAppServerProviderError,
    JsonRpcId,
)
from liveclip.agent_runtime.models import (
    AgentObservation,
    AgentToolResult,
    FinishArguments,
)
from liveclip.agent_runtime.skills import load_packaged_agent_skill
from liveclip.agent_runtime.tools import function_tool_definition


class _EchoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    value: int


class _FakeAppServerClient:
    def __init__(self, messages: list[dict[str, object]]) -> None:
        self.messages = deque(messages)
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.responses: list[tuple[JsonRpcId, dict[str, object]]] = []
        self.rejections: list[tuple[JsonRpcId, int, str]] = []
        self.started = False
        self.closed = False

    @property
    def is_alive(self) -> bool:
        return self.started and not self.closed

    def start(self, *, cancel_requested: Callable[[], bool]) -> None:
        assert not cancel_requested()
        self.started = True

    def request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        cancel_requested: Callable[[], bool],
    ) -> dict[str, object]:
        assert not cancel_requested()
        values = dict(params)
        self.requests.append((method, values))
        if method == "thread/start":
            return {"thread": {"id": "thread_fixture"}}
        if method == "thread/resume":
            return {"thread": {"id": values["threadId"]}}
        if method == "turn/start":
            return {"turn": {"id": f"turn_{len(self.requests)}"}}
        raise AssertionError(f"unexpected request: {method}")

    def respond(self, request_id: JsonRpcId, result: Mapping[str, object]) -> None:
        self.responses.append((request_id, dict(result)))

    def reject(self, request_id: JsonRpcId, *, code: int, message: str) -> None:
        self.rejections.append((request_id, code, message))

    def next_message(
        self,
        *,
        cancel_requested: Callable[[], bool],
    ) -> dict[str, object]:
        assert not cancel_requested()
        if not self.messages:
            raise AssertionError("fake App Server has no next message")
        return self.messages.popleft()

    def close(self) -> None:
        self.closed = True


def _definitions() -> tuple[dict[str, object], ...]:
    return (
        function_tool_definition(
            name="echo",
            description="Echo one integer through the LiveClip Harness.",
            arguments_model=_EchoArguments,
        ),
        function_tool_definition(
            name="finish",
            description="Finish with stored artifacts.",
            arguments_model=FinishArguments,
        ),
    )


def _tool_call(
    *,
    request_id: int,
    call_id: str,
    tool: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    return {
        "method": "item/tool/call",
        "id": request_id,
        "params": {
            "threadId": "thread_fixture",
            "turnId": "turn_fixture",
            "callId": call_id,
            "namespace": None,
            "tool": tool,
            "arguments": arguments,
        },
    }


def _model(tmp_path: Path, client: _FakeAppServerClient) -> CodexAppServerAgentTurnModel:
    return CodexAppServerAgentTurnModel(
        skill=load_packaged_agent_skill("agent_clipping_v2"),
        model_name_value="gpt-5.6-sol",
        state_dir=tmp_path / "provider",
        client_factory=lambda: client,
        contract_version="codex-app-server-fixture-v1",
        monotonic=lambda: 10.0,
    )


def test_oauth_app_server_correlates_dynamic_calls_and_completion(tmp_path: Path) -> None:
    client = _FakeAppServerClient(
        [
            _tool_call(
                request_id=70,
                call_id="exec_echo",
                tool="echo",
                arguments={"value": 7},
            ),
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread_fixture",
                    "tokenUsage": {"total": {"inputTokens": 100, "outputTokens": 20}},
                },
            },
            _tool_call(
                request_id=71,
                call_id="exec_finish",
                tool="finish",
                arguments={"artifact_ids": [], "summary": "fixture complete"},
            ),
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread_fixture",
                    "tokenUsage": {"total": {"inputTokens": 140, "outputTokens": 30}},
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread_fixture",
                    "turn": {"id": "turn_fixture", "status": "completed"},
                },
            },
        ]
    )
    model = _model(tmp_path, client)
    skill = model.skill

    first = model.generate_turn(
        run_id="oauth_fixture",
        turn_number=1,
        instructions=skill.instructions,
        payload={"task": "test OAuth dynamic tools"},
        tool_definitions=_definitions(),
        previous_tool_result=None,
        cancel_requested=lambda: False,
    )

    assert first.call_id == "exec_echo"
    assert first.turn.tool == "echo"
    assert first.metadata["oauth"] is True
    thread_start = next(params for method, params in client.requests if method == "thread/start")
    dynamic_tools = thread_start["dynamicTools"]
    assert isinstance(dynamic_tools, list)
    assert {item["name"] for item in dynamic_tools} == {"echo", "finish"}
    assert thread_start["cwd"] == str(tmp_path / "provider" / "workspace")
    assert thread_start["config"]["mcp_servers"] == {}

    observation = AgentObservation(
        observation_id="obs_0001",
        tool="echo",
        status="ok",
        data={"value": 7},
    )
    second = model.generate_turn(
        run_id="oauth_fixture",
        turn_number=2,
        instructions=skill.instructions,
        payload={"ignored": True},
        tool_definitions=_definitions(),
        previous_tool_result=AgentToolResult(
            call_id="exec_echo",
            tool="echo",
            observation=observation,
        ),
        cancel_requested=lambda: False,
    )

    assert second.call_id == "exec_finish"
    assert second.turn.action == "finish"
    assert client.responses[0][0] == 70
    first_output = client.responses[0][1]
    content_items = first_output["contentItems"]
    assert isinstance(content_items, list)
    assert json.loads(content_items[0]["text"])["data"] == {"value": 7}
    completion = model.finalize_completion(
        run_id="oauth_fixture",
        call_id="exec_finish",
        cancel_requested=lambda: False,
    )
    assert completion == {
        "completion_acknowledged": True,
        "final_session_usage": {"total": {"inputTokens": 140, "outputTokens": 30}},
    }
    assert client.responses[1][0] == 71
    assert client.closed is True


def test_oauth_app_server_recovers_pending_call_without_repeating_it(tmp_path: Path) -> None:
    first_client = _FakeAppServerClient(
        [
            _tool_call(
                request_id=80,
                call_id="exec_once",
                tool="echo",
                arguments={"value": 9},
            )
        ]
    )
    first_model = _model(tmp_path, first_client)
    skill = first_model.skill
    original = first_model.generate_turn(
        run_id="oauth_resume",
        turn_number=1,
        instructions=skill.instructions,
        payload={"task": "recover"},
        tool_definitions=_definitions(),
        previous_tool_result=None,
        cancel_requested=lambda: False,
    )
    first_model.close()

    resumed_client = _FakeAppServerClient(
        [
            _tool_call(
                request_id=81,
                call_id="exec_finish_after_resume",
                tool="finish",
                arguments={"artifact_ids": [], "summary": "resumed"},
            )
        ]
    )
    resumed_model = _model(tmp_path, resumed_client)
    recovered = resumed_model.generate_turn(
        run_id="oauth_resume",
        turn_number=1,
        instructions=skill.instructions,
        payload={"task": "recover"},
        tool_definitions=_definitions(),
        previous_tool_result=None,
        cancel_requested=lambda: False,
    )

    assert recovered.call_id == original.call_id
    assert recovered.metadata["response_recovered"] is True
    assert resumed_client.started is False

    observation = AgentObservation(
        observation_id="obs_0001",
        tool="echo",
        status="ok",
        data={"value": 9},
    )
    finish = resumed_model.generate_turn(
        run_id="oauth_resume",
        turn_number=2,
        instructions=skill.instructions,
        payload={"ignored": True},
        tool_definitions=_definitions(),
        previous_tool_result=AgentToolResult(
            call_id="exec_once",
            tool="echo",
            observation=observation,
        ),
        cancel_requested=lambda: False,
    )

    assert finish.call_id == "exec_finish_after_resume"
    assert [method for method, _params in resumed_client.requests] == [
        "thread/resume",
        "turn/start",
    ]
    turn_params = resumed_client.requests[-1][1]
    assert turn_params["input"] == []
    tool_output = turn_params["toolOutput"]
    assert json.loads(tool_output["output"])["data"] == {"value": 9}


def test_oauth_app_server_fails_closed_on_builtin_tool_item(tmp_path: Path) -> None:
    client = _FakeAppServerClient(
        [
            {
                "method": "item/started",
                "params": {
                    "threadId": "thread_fixture",
                    "turnId": "turn_fixture",
                    "item": {"type": "commandExecution", "id": "unsafe"},
                },
            }
        ]
    )
    model = _model(tmp_path, client)

    with pytest.raises(CodexAppServerProviderError) as exc_info:
        model.generate_turn(
            run_id="oauth_forbidden",
            turn_number=1,
            instructions=model.skill.instructions,
            payload={"task": "must fail"},
            tool_definitions=_definitions(),
            previous_tool_result=None,
            cancel_requested=lambda: False,
        )

    assert exc_info.value.code == "CODEX_BUILTIN_TOOL_FORBIDDEN"
