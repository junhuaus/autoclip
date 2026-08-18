# ruff: noqa: RUF001 -- Chinese strings are intentional mock editorial data.
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

MODULE_PATH = Path(__file__).with_name("run_iteration.py")
SPEC = importlib.util.spec_from_file_location("highlight_v2_runner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)
_REAL_RUN_PREFLIGHT_PROCESS = RUNNER._run_preflight_process


@pytest.fixture(autouse=True)
def _successful_local_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(command: list[str], *, cwd: Path, env: dict[str, str]):
        del cwd, env
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(RUNNER, "_run_preflight_process", run)


def _payload(prompt: str) -> dict[str, Any]:
    marker = "<untrusted_frozen_input>\n"
    value = prompt.split(marker, 1)[1].split("\n</untrusted_frozen_input>", 1)[0]
    return json.loads(value)


def _mock_invoke_factory(counter: list[str]):
    def invoke(*, label: str, prompt: str, schema_path: Path):
        counter.append(label)
        payload = _payload(prompt)
        name = schema_path.name
        if name == "v1.json":
            candidate = payload["candidates"][0]
            raw = {
                "selection_summary": "选择一条可验证的基准候选。",
                "highlights": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "topic": "基准主题",
                        "title": "基准高光",
                        "highlight_sentence": candidate["text"][:40],
                        "script_description": "用于验证 fresh v1 的隔离执行路径。",
                        "score": 80,
                        "hook": "这条候选包含一个完整观点。",
                        "selection_reason": "候选结构完整，适合进入比较。",
                        "risk_flags": [],
                    }
                ],
            }
        elif name.startswith("v2-tier1-b"):
            raw = {
                "assessments": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "disposition": "assessable",
                        "unusable_reason": "none",
                        "topic_hypothesis": "自由发现主题",
                        "primary_claim": "该候选表达了一个可独立分析的观点。",
                        "assessment_reason": "正文足以支持独立评估。",
                        "assessment_confidence": "high",
                        "uncertainty_flags": [],
                        "scores": {
                            "content_value": 4,
                            "hook_strength": 3,
                            "standalone_completeness": 4,
                            "evidence_fidelity": 4,
                            "editorial_utility": 3,
                        },
                        "evidence_flags": [],
                        "content_risk_flags": [],
                        "risk_summary": "",
                    }
                    for candidate in payload["batch"]["candidates"]
                ]
            }
        elif name == "v2-tier2.json":
            raw = {
                "inventory_summary": "按冻结证据自由发现全部候选主题。",
                "topics": [
                    {
                        "topic_label": f"主题 {index + 1}",
                        "canonical_angle": "该候选具有一个独立的编辑角度。",
                        "cluster_confidence": "high",
                        "members": [
                            {
                                "candidate_id": candidate["candidate_id"],
                                "relationship": "core",
                                "member_angle": "独立观点",
                                "relationship_reason": "该候选独立构成此主题。",
                            }
                        ],
                    }
                    for index, candidate in enumerate(payload["candidates"])
                ],
            }
        elif name == "v2-tier4.json":
            selected = payload["selected_candidates_in_required_order"]
            raw = {
                "selection_summary": "为确定性入选候选生成可追溯编辑文案。",
                "copies": [
                    {
                        "candidate_id": item["candidate"]["candidate_id"],
                        "title": "可追溯高光",
                        "hook": "这段内容给出了一个明确观点。",
                        "evidence_quote": item["candidate"]["text"][:40],
                        "edited_sentence": "保留原意的编辑关键句。",
                        "script_description": "供编辑审核候选内容与证据关系。",
                        "keywords": ["高光", "证据"],
                        "selection_reason": "通过确定性质量与去重规则。",
                    }
                    for item in selected
                ],
            }
        else:
            raise AssertionError(f"unexpected mock Schema: {schema_path}")
        metadata = {
            "label": label,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "medium",
            "request_id": f"mock-{len(counter)}",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "started_at": "2026-08-17T00:00:00+00:00",
            "completed_at": "2026-08-17T00:00:01+00:00",
            "elapsed_seconds": 0.001,
            "unsafe_tool_event": False,
        }
        return raw, metadata, ""

    return invoke


def _recover_call_after_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    successful_invoke = _mock_invoke_factory([])
    process_calls = 0

    def fail_once(*, label: str, prompt: str, schema_path: Path):
        nonlocal process_calls
        process_calls += 1
        if process_calls == 1:
            raise RUNNER.CodexProcessFailure(
                f"{label} app-server init failed",
                category="infrastructure_permission_denied",
                model_started=False,
                returncode=1,
                stderr="Operation not permitted",
            )
        return successful_invoke(label=label, prompt=prompt, schema_path=schema_path)

    monkeypatch.setattr(RUNNER, "_invoke_codex", fail_once)
    with pytest.raises(RUNNER.CodexInfrastructureUnavailable):
        RUNNER._run_experiment(prepared, sentinel=True)
    call_dir = next((prepared.experiment_dir / "calls").iterdir())
    recovered = RUNNER._run_experiment(prepared, sentinel=True)
    assert recovered["completed_pipeline_count"] == 2
    return call_dir


def test_mock_sentinel_resumes_to_full_matrix_and_detects_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    counter: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(counter))

    sentinel = RUNNER._run_experiment(prepared, sentinel=True)
    assert sentinel["status"] == "generation_partial"
    assert sentinel["completed_pipeline_count"] == 2
    assert sentinel["remaining_pipeline_count"] == 10

    first_pipeline_id = prepared.public_plan["schedule"][0]["pipelines"][0]["pipeline_id"]
    first_pipeline_dir = prepared.experiment_dir / "pipelines" / first_pipeline_id
    (first_pipeline_dir / "complete.json").unlink()
    calls_before_recovery = len(counter)
    recovered = RUNNER._run_experiment(prepared, sentinel=True)
    assert recovered["completed_pipeline_count"] == 2
    assert len(counter) == calls_before_recovery
    assert (first_pipeline_dir / "complete.json").is_file()

    complete = RUNNER._run_experiment(prepared)
    assert complete["status"] == "generation_completed"
    assert complete["completed_pipeline_count"] == 12
    assert len(counter) == 36

    resumed = RUNNER._run_experiment(prepared)
    assert resumed["completed_pipeline_count"] == 12
    assert len(counter) == 36

    pipeline_contract = json.loads(
        (first_pipeline_dir / "pipeline-contract.json").read_text(encoding="utf-8")
    )
    call_id = pipeline_contract["required_call_ids"][0]
    events_path = prepared.experiment_dir / "calls" / call_id / "events.jsonl"
    events = events_path.read_bytes()
    events_path.unlink()
    with pytest.raises(RuntimeError, match="pipeline call artifact drift"):
        RUNNER._run_experiment(prepared, sentinel=True)
    events_path.write_bytes(events)

    result_path = first_pipeline_dir / "result.json"
    result_path.write_bytes(result_path.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="artifact drift"):
        RUNNER._run_experiment(prepared, sentinel=True)


def test_empty_portfolio_skips_tier4_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "MINIMUM_QUALITY", 100.0)
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    counter: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(counter))
    result = RUNNER._run_experiment(prepared, sentinel=True)
    assert result["completed_pipeline_count"] == 2
    assert len(counter) == 5
    assert not any("v2-tier4" in label for label in counter)
    v2_summary = next(
        summary
        for summary in result["completed_pipelines"]
        if "tier_call_elapsed_seconds" in summary
    )
    assert v2_summary["selected_count"] == 0
    assert v2_summary["tier_call_elapsed_seconds"]["tier4"] == 0.0


def test_preflight_uses_stdio_transport_and_immediate_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = RUNNER._codex_preflight_command()
    listen_index = command.index("--listen")
    assert command[listen_index + 1] == "stdio://"
    assert "off" not in command

    observed: dict[str, Any] = {}

    def run(command_value: list[str], **kwargs: Any):
        observed["command"] = command_value
        observed.update(kwargs)
        return subprocess.CompletedProcess(command_value, 0, stdout="", stderr="")

    monkeypatch.setattr(RUNNER.subprocess, "run", run)
    completed = _REAL_RUN_PREFLIGHT_PROCESS(command, cwd=tmp_path, env={})
    assert completed.returncode == 0
    assert observed["command"] == command
    assert observed["input"] == ""
    assert observed["timeout"] == RUNNER.PREFLIGHT_TIMEOUT_SECONDS == 20
    assert observed["check"] is False


def test_preflight_failure_uses_zero_model_calls_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    model_calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(model_calls))

    def denied(command: list[str], *, cwd: Path, env: dict[str, str]):
        del cwd, env
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr=(
                "Error: failed to initialize in-process app-server client: "
                "Operation not permitted (os error 1)"
            ),
        )

    monkeypatch.setattr(RUNNER, "_run_preflight_process", denied)
    with pytest.raises(RUNNER.CodexInfrastructureUnavailable, match="preflight failed"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert model_calls == []
    first_receipt_path = (
        prepared.experiment_dir / "infrastructure/preflight/checks/001/receipt.json"
    )
    first_receipt_bytes = first_receipt_path.read_bytes()
    first_receipt = json.loads(first_receipt_bytes)
    assert first_receipt["category"] == "infrastructure_permission_denied"
    assert first_receipt["model_started"] is False
    assert first_receipt["model_attempt_consumed"] is False
    assert not (prepared.experiment_dir / "calls").exists()

    def ready(command: list[str], *, cwd: Path, env: dict[str, str]):
        del cwd, env
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(RUNNER, "_run_preflight_process", ready)
    recovered = RUNNER._run_experiment(prepared, sentinel=True)
    assert recovered["status"] == "generation_partial"
    assert model_calls
    assert first_receipt_path.read_bytes() == first_receipt_bytes
    second_receipt = json.loads(
        (prepared.experiment_dir / "infrastructure/preflight/checks/002/receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert second_receipt["status"] == "passed"


def test_pre_model_call_failure_has_infrastructure_receipt_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    successful_calls: list[str] = []
    successful_invoke = _mock_invoke_factory(successful_calls)
    infrastructure_calls = 0

    def fail_once(*, label: str, prompt: str, schema_path: Path):
        nonlocal infrastructure_calls
        infrastructure_calls += 1
        if infrastructure_calls == 1:
            raise RUNNER.CodexProcessFailure(
                f"{label} app-server init failed",
                category="infrastructure_permission_denied",
                model_started=False,
                returncode=1,
                stderr="Operation not permitted",
            )
        return successful_invoke(label=label, prompt=prompt, schema_path=schema_path)

    monkeypatch.setattr(RUNNER, "_invoke_codex", fail_once)
    with pytest.raises(RUNNER.CodexInfrastructureUnavailable, match="before any model turn"):
        RUNNER._run_experiment(prepared, sentinel=True)
    call_dirs = list((prepared.experiment_dir / "calls").iterdir())
    assert len(call_dirs) == 1
    call_dir = call_dirs[0]
    receipt_path = call_dir / "infrastructure-failures/001/receipt.json"
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt["model_started"] is False
    assert receipt["model_attempt_consumed"] is False
    assert not (call_dir / "attempts").exists()

    recovered = RUNNER._run_experiment(prepared, sentinel=True)
    assert recovered["completed_pipeline_count"] == 2
    assert receipt_path.read_bytes() == receipt_bytes
    assert (call_dir / "attempts/001/attempt-contract.json").is_file()


@pytest.mark.parametrize("mutation", ["tamper", "delete", "extra"])
def test_completed_call_binds_all_infrastructure_failure_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    call_dir = _recover_call_after_infrastructure_failure(tmp_path, monkeypatch)
    receipt_path = call_dir / "infrastructure-failures/001/receipt.json"
    completion = json.loads((call_dir / "complete.json").read_text(encoding="utf-8"))
    assert completion["infrastructure_failure_receipts"] == [
        {
            "relative_path": "infrastructure-failures/001/receipt.json",
            "sha256": RUNNER._sha256_path(receipt_path),
        }
    ]

    if mutation == "tamper":
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["stderr_tail"] = "tampered after call completion"
        receipt_path.write_bytes(RUNNER._pretty_json_bytes(receipt))
    elif mutation == "delete":
        receipt_path.unlink()
    else:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["failure_number"] = 2
        extra_path = call_dir / "infrastructure-failures/002/receipt.json"
        extra_path.parent.mkdir(parents=True)
        extra_path.write_bytes(RUNNER._pretty_json_bytes(receipt))

    contract = json.loads((call_dir / "call-contract.json").read_text(encoding="utf-8"))

    def should_not_revalidate(_: dict[str, Any]):
        raise AssertionError("receipt drift must fail before model output validation")

    with pytest.raises(RuntimeError, match="infrastructure"):
        RUNNER._validate_completed_call(call_dir, contract, should_not_revalidate)
    with pytest.raises(RuntimeError, match="infrastructure"):
        RUNNER._verify_call_evidence(call_dir)


def test_model_schema_attempts_remain_bounded_at_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    model_calls: list[str] = []

    def invalid(*, label: str, prompt: str, schema_path: Path):
        del prompt, schema_path
        model_calls.append(label)
        return (
            {},
            {
                "label": label,
                "model": "gpt-5.6-sol",
                "reasoning_effort": "medium",
                "request_id": f"invalid-{len(model_calls)}",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "started_at": "2026-08-17T00:00:00+00:00",
                "completed_at": "2026-08-17T00:00:01+00:00",
                "elapsed_seconds": 0.001,
                "unsafe_tool_event": False,
                "model_started": True,
            },
            '{"type":"turn.started"}\n',
        )

    monkeypatch.setattr(RUNNER, "_invoke_codex", invalid)
    with pytest.raises(RuntimeError, match="exhausted 2 same-tier attempts"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert len(model_calls) == 2
    call_dir = next((prepared.experiment_dir / "calls").iterdir())
    assert sorted(path.name for path in (call_dir / "attempts").iterdir()) == [
        "001",
        "002",
    ]
    assert not (call_dir / "infrastructure-failures").exists()

    with pytest.raises(RuntimeError, match="exhausted 2 same-tier attempts"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert len(model_calls) == 2


def test_unsafe_tool_event_is_persisted_hard_failure_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    model_calls: list[str] = []
    unsafe_events = (
        '{"type":"turn.started"}\n{"type":"item.started","item":{"type":"command_execution"}}\n'
    )

    def unsafe(*, label: str, prompt: str, schema_path: Path):
        del prompt, schema_path
        model_calls.append(label)
        raise RUNNER.CodexProcessFailure(
            f"{label} emitted a forbidden tool event",
            category="model_safety_tool_event",
            model_started=True,
            returncode=0,
            stdout=unsafe_events,
        )

    monkeypatch.setattr(RUNNER, "_invoke_codex", unsafe)
    with pytest.raises(RuntimeError, match="unsafe tool event"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert len(model_calls) == 1

    call_dir = next((prepared.experiment_dir / "calls").iterdir())
    attempt_dir = call_dir / "attempts/001"
    attempt_contract = json.loads(
        (attempt_dir / "attempt-contract.json").read_text(encoding="utf-8")
    )
    failure = json.loads((attempt_dir / "failure.json").read_text(encoding="utf-8"))
    assert attempt_contract["status"] == "safety_failed"
    assert failure["category"] == "model_safety_tool_event"
    assert (attempt_dir / "events.jsonl").read_text(encoding="utf-8") == unsafe_events

    with pytest.raises(RuntimeError, match="persisted unsafe tool event"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert len(model_calls) == 1
    assert sorted(path.name for path in (call_dir / "attempts").iterdir()) == ["001"]


def test_pre_model_infrastructure_retries_are_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    process_calls = 0

    def unavailable(*, label: str, prompt: str, schema_path: Path):
        nonlocal process_calls
        del prompt, schema_path
        process_calls += 1
        raise RUNNER.CodexProcessFailure(
            f"{label} app-server init failed",
            category="infrastructure_permission_denied",
            model_started=False,
            returncode=1,
            stderr="Operation not permitted",
        )

    monkeypatch.setattr(RUNNER, "_invoke_codex", unavailable)
    for _ in range(RUNNER.MAX_CALL_INFRASTRUCTURE_FAILURES):
        with pytest.raises(RUNNER.CodexInfrastructureUnavailable):
            RUNNER._run_experiment(prepared, sentinel=True)
    assert process_calls == RUNNER.MAX_CALL_INFRASTRUCTURE_FAILURES
    with pytest.raises(RUNNER.CodexInfrastructureUnavailable, match="bounded pre-model"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert process_calls == RUNNER.MAX_CALL_INFRASTRUCTURE_FAILURES


def test_codex_process_classifies_pre_turn_permission_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text("{}", encoding="utf-8")

    def denied(*args: Any, **kwargs: Any):
        del args, kwargs
        return subprocess.CompletedProcess(
            ["codex"],
            1,
            stdout="",
            stderr=(
                "Error: failed to initialize in-process app-server client: "
                "Operation not permitted (os error 1)"
            ),
        )

    monkeypatch.setattr(RUNNER.subprocess, "run", denied)
    with pytest.raises(RUNNER.CodexProcessFailure) as captured:
        RUNNER._invoke_codex(label="offline-classifier", prompt="{}", schema_path=schema)
    assert captured.value.category == "infrastructure_permission_denied"
    assert captured.value.model_started is False
