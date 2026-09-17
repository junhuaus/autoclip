from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from openai import OpenAI
from pydantic import BaseModel, create_model

from liveclip.clipping_skills.semantic_windowed_v1 import load_semantic_windowed_discovery_prompt
from liveclip.domain.semantic_validation import CURRENT_SEMANTIC_TRANSPORT as CONTRACT
from liveclip.pipeline.semantic_global import SemanticGlobalConfig, TokenEstimator
from liveclip.pipeline.semantic_transport import decode_transport, transport_options
from liveclip.providers.llm import codex as codex_module
from liveclip.providers.llm import structured as module
from liveclip.providers.openai_retry import OpenAIRetryPolicy


class Answer(BaseModel):
    value: str


def cue(index):
    return {
        "cue_id": index,
        "segment_id": f"s{index}",
        "start_ms": index * 1000,
        "end_ms": (index + 1) * 1000,
        "original_text": "今天讲解方法。先看一个具体例子，再总结操作步骤。",  # noqa: RUF001 - exact Chinese fixture punctuation
        "normalized_text": None,
        "normalization_note": None,
    }


def payload():
    cues = [cue(i) for i in range(270)]
    return {
        "stage": "global_review",
        "candidate_contexts": [
            {"candidate_id": f"candidate_{i}", "cues": copy.deepcopy(cues)} for i in range(10)
        ],
        "literal": '\\ <untrusted_json> "保持完整" 😀',
    }


def prompts(**changes):
    return replace(load_semantic_windowed_discovery_prompt("general"), **changes)


def prepared(data, *, wire="openai", config=None, instructions="Analyze", model=Answer):
    return module._prepare_transport_request(
        payload=data,
        instructions=instructions,
        response_model=model,
        config=config or SemanticGlobalConfig(),
        model_name="fixture",
        wire=wire,
    )


def response(texts):
    return {
        "id": "resp_fixture",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "fixture",
        "output": [
            {
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": text, "annotations": []} for text in texts
                ],
            }
        ],
        "usage": None,
    }


def provider(wire, monkeypatch, captured, outputs, *, config=None, bundle=None, on_call=None):
    bundle = bundle or prompts()
    if wire == "openai":

        def handler(request):
            captured.append(request.content.decode())
            if on_call:
                on_call()
            return httpx.Response(200, json=response(outputs.pop(0)))

        client = OpenAI(
            api_key="synthetic-local-fixture",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        return module.OpenAIStructuredLLMProvider(
            prompts=bundle,
            model_name="fixture",
            api_key=None,
            timeout_seconds=30,
            retry_policy=OpenAIRetryPolicy(max_retries=0),
            client=client,
            semantic_budget=config,
            transport_contract=CONTRACT,
        )
    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(module, "codex_cli_contract_version", lambda _: contract)

    def run(argv, **kwargs):
        prompt = kwargs["stdin_stream"].read().decode()
        schema = Path(argv[argv.index("--output-schema") + 1]).read_text()
        captured.append(prompt + "\n\n" + schema)
        assert argv[argv.index("--sandbox") + 1] == "read-only"
        assert "features.shell_tool=false" in argv and "features.multi_agent=false" in argv
        assert "--ignore-user-config" in argv and "--strict-config" in argv
        if on_call:
            on_call()
        Path(argv[argv.index("--output-last-message") + 1]).write_text(outputs.pop(0)[0])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(module, "run_cancellable_process", run)
    return module.CodexStructuredLLMProvider(
        prompts=bundle,
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
        semantic_budget=config,
        transport_contract=CONTRACT,
    )


@pytest.mark.parametrize("wire", ["openai", "codex"])
def test_ten_270_second_contexts_are_lossless_and_fit_complete_budget(wire):
    data = payload()
    request = prepared(data, wire=wire)
    assert request.payload["representation"] == "cue_table"
    assert request.measurement.fits
    assert decode_transport(request.payload, contract=CONTRACT) == data
    counter = TokenEstimator("o200k_base")
    object_tokens = counter.count(module._untrusted_payload(transport_options(data)[0]))
    assert object_tokens > 140_000
    assert request.measurement.input_tokens < object_tokens / 4
    print(
        json.dumps(
            {
                "wire": wire,
                "object_input_tokens": object_tokens,
                "schema_tokens": counter.count(request.schema_text),
                **request.measurement.diagnostics(),
            },
            sort_keys=True,
        )
    )


@pytest.mark.parametrize("wire", ["openai", "codex"])
def test_exact_actual_wire_and_schema_match_measured_bytes(wire, monkeypatch):
    data, sent = payload(), []
    bundle = prompts()
    expected = prepared(data, wire=wire, instructions=bundle.instructions)
    llm = provider(wire, monkeypatch, sent, [['{"value":"完整答案"}']], bundle=bundle)
    result = llm.generate(subject_id="wire", payload=data, response_model=Answer)
    assert result.output.value == "完整答案" and len(result.call_records) == 1
    assert sent == [expected.measurement.serialized_request]
    assert expected.measurement.input_tokens == TokenEstimator("o200k_base").count(sent[0])


@pytest.mark.parametrize("wire", ["openai", "codex"])
@pytest.mark.parametrize("phase", ["initial", "repair"])
@pytest.mark.parametrize("excess", [0, 1])
def test_actual_calls_respect_inclusive_exact_budget(wire, phase, excess, monkeypatch):
    data, sent = {"cues": [cue(99)]}, []
    bundle = prompts(instructions="Analyze", repair="Repair")
    # A .5 ratio makes the integer threshold exact and avoids floating-point ambiguity.
    config = SemanticGlobalConfig(full_context_budget_ratio=0.5)
    actual_data = data if phase == "initial" else {**data, "validation_errors": ["full error"]}
    expected = prepared(
        actual_data,
        wire=wire,
        config=config,
        instructions=bundle.instructions if phase == "initial" else bundle.repair,
    )
    config = config.model_copy(
        update={"model_context_tokens": 2 * (expected.measurement.total_tokens - excess)}
    )
    llm = provider(wire, monkeypatch, sent, [['{"value":"ok"}']], config=config, bundle=bundle)
    kwargs = dict(subject_id="threshold", payload=data, response_model=Answer)
    if phase == "repair":
        kwargs["validation_errors"] = ("full error",)
    call = llm.generate if phase == "initial" else llm.repair
    if excess:
        with pytest.raises(module.StructuredProviderError) as caught:
            call(**kwargs)
        assert not caught.value.call_records and not sent
        evidence = caught.value.repair_attempts[0]
        assert evidence["phase"] == phase + "_budget"
        assert evidence["estimated_total_tokens"] == evidence["budget_tokens"] + 1
        assert evidence["provider_call_executed"] is False
    else:
        assert call(**kwargs).output.value == "ok"
        assert len(sent) == 1


@pytest.mark.parametrize("wire", ["openai", "codex"])
@pytest.mark.parametrize("huge", ["instructions", "schema", "chain"])
def test_complete_large_authority_rejects_before_model_io(wire, huge, monkeypatch):
    data, sent, bundle, model = {"cues": [cue(1)]}, [], prompts(), Answer
    if huge == "instructions":
        bundle = prompts(instructions="完整指令 " * 30_000)
    elif huge == "schema":
        model = create_model("LargeSchema", **{f"field_{i}": (str, ...) for i in range(7000)})
    else:
        data["chains"] = [{"id": i, "authority": "不得丢弃 " * 20} for i in range(3000)]
    llm = provider(wire, monkeypatch, sent, [], bundle=bundle)
    with pytest.raises(module.StructuredProviderError) as caught:
        llm.generate(subject_id="too-large", payload=data, response_model=model)
    assert caught.value.code == "STRUCTURED_INPUT_BUDGET_EXCEEDED"
    assert not sent and not caught.value.call_records


@pytest.mark.parametrize("wire", ["openai", "codex"])
def test_sole_repair_keeps_caller_snapshot_and_more_than_200_errors(wire, monkeypatch):
    model = create_model("ManyErrors", **{f"field_{i}": (str, ...) for i in range(225)})
    good = json.dumps({f"field_{i}": "ok" for i in range(225)})
    data, sent, requests = {"cues": [cue(1)], "source_ids": ["original"]}, [], []
    before = copy.deepcopy(data)
    prepare = module._prepare_transport_request

    def observe(**kwargs):
        result = prepare(**kwargs)
        requests.append(result)
        return result

    monkeypatch.setattr(module, "_prepare_transport_request", observe)
    llm = provider(
        wire,
        monkeypatch,
        sent,
        [["{}"], [good]],
        on_call=lambda: data["source_ids"].append("caller-mutation"),
    )
    result = llm.generate(subject_id="repair", payload=data, response_model=model)
    assert result.repaired and len(result.call_records) == 2 and len(sent) == 2
    repair = decode_transport(requests[1].payload, contract=CONTRACT)
    assert repair["immutable_request"] == before
    assert len(repair["validation_errors"]) == 225
    assert sent == [request.measurement.serialized_request for request in requests]


def test_multipart_safety_precedence_retains_all_parts_without_repair(monkeypatch):
    data, sent = {"cues": [cue(1)]}, []
    parts = ['{"value":"' + ("完整内容 " * 30_000) + '"}', '{"value":"second"}']
    llm = provider("openai", monkeypatch, sent, [parts])
    with pytest.raises(module.StructuredProviderError) as caught:
        llm.generate(subject_id="multipart", payload=data, response_model=Answer)
    assert caught.value.code == "STRUCTURED_UNEXPECTED_OUTPUT"
    assert len(sent) == len(caught.value.call_records) == 1
    evidence = caught.value.repair_attempts[0]
    assert [item["output_text"] for item in evidence["business_output_parts"]] == parts
    # An explicitly supplied repair request still measures every indexed part and error.
    repair_data = {
        "immutable_request": data,
        "invalid_output": evidence["business_output_parts"],
        "validation_errors": [f"indexed_error_{i}" for i in range(225)],
    }
    with pytest.raises(module.StructuredProviderError) as budget:
        llm.repair(
            subject_id="multipart-explicit",
            payload=repair_data,
            response_model=Answer,
            validation_errors=tuple(repair_data["validation_errors"]),
        )
    assert budget.value.code == "STRUCTURED_REPAIR_BUDGET_EXCEEDED"
    assert not budget.value.call_records and len(sent) == 1
    assert budget.value.repair_attempts[0]["invalid_output"] == repair_data["invalid_output"]
    assert len(budget.value.repair_attempts[0]["validation_errors"]) == 226


@pytest.mark.parametrize("wire", ["openai", "codex"])
def test_oversize_single_invalid_output_preserves_initial_attempt_without_second_call(
    wire, monkeypatch
):
    data, sent = {"cues": [cue(1)]}, []
    invalid = json.dumps({"value": ["完整内容 " * 22_000]})
    llm = provider(wire, monkeypatch, sent, [[invalid]])
    with pytest.raises(module.StructuredProviderError) as caught:
        llm.generate(subject_id="single-huge", payload=data, response_model=Answer)
    assert caught.value.code == "STRUCTURED_REPAIR_BUDGET_EXCEEDED"
    assert len(sent) == len(caught.value.call_records) == 1
    assert caught.value.repair_attempts[-1]["invalid_output"] == json.loads(invalid)


def test_object_representation_wins_when_table_overhead_is_larger():
    request = prepared({"cues": [cue(1)]})
    assert request.payload["representation"] == "object"
    assert request.measurement.output_allocation_tokens == 16_000
    small_reserve = SemanticGlobalConfig(output_reserve_tokens=2000)
    assert prepared({}, config=small_reserve).measurement.output_allocation_tokens == 16_000
    assert (
        prepared({}, wire="codex", config=small_reserve).measurement.output_allocation_tokens
        == 2000
    )
