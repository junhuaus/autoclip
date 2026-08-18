# ruff: noqa: RUF001 -- Chinese strings are intentional mock editorial data.
from __future__ import annotations

import importlib.util
import json
import shutil
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


def _evaluation_artifact_index() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for relative in sorted(RUNNER.REQUIRED_EVALUATION_ARTIFACTS):
        content = (RUNNER.ROOT / relative).read_bytes()
        records[relative] = {
            "sha256": RUNNER._sha256_bytes(content),
            "size_bytes": len(content),
        }
    return records


@pytest.fixture(autouse=True)
def _successful_local_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def run(command: list[str], *, cwd: Path, env: dict[str, str]):
        del cwd, env
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(RUNNER, "_run_preflight_process", run)
    evaluation_contract = tmp_path / "evaluation-contract.json"
    evaluation_contract.write_text(
        json.dumps(
            {
                "schema_version": "liveclip-highlight-evaluation-contract.iteration-2.v1",
                "contract_version": "highlight-agent-skill-v2-iteration-2-evaluation-v1",
                "iteration_id": "highlight-agent-skill-v2-iteration-2",
                "status": "frozen_before_any_iteration2_generator_output",
                "human_review_mode": "diagnostic_not_required",
                "artifacts": _evaluation_artifact_index(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(RUNNER, "EVALUATION_CONTRACT_PATH", evaluation_contract)


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
        elif name == "combined-discovery.json":
            candidates = payload["candidates_in_required_order"]
            raw = {
                "assessments": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "disposition": "assessable",
                        "unusable_reason": "none",
                        "primary_claim": "该候选表达了一个可独立分析的观点。",
                        "assessment_confidence": "high",
                        "standalone_publishability": "ready",
                        "publishability_blockers": [],
                        "editorial_value": "distinctive",
                        "editorial_value_reason": "正文具体且足以支持独立评估。",
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
                    for candidate in candidates
                ],
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
                            }
                        ],
                    }
                    for index, candidate in enumerate(candidates)
                ],
            }
        elif name == "selected-copy.json":
            selected = payload["selected_candidates_in_required_order"]
            raw = {
                "selection_summary": "为确定性入选候选生成可追溯编辑文案。",
                "copies": [
                    {
                        "candidate_id": item["candidate"]["candidate_id"],
                        "title": "可追溯高光",
                        "hook": "这段内容给出了一个明确观点。",
                        "evidence_quote": item["candidate"]["text"][:40],
                        "source_sentence": item["candidate"]["text"][:40],
                        "script_description": "供编辑审核候选内容与证据关系。",
                        "keywords": ["高光", "证据"],
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
            "usage_status": "reported",
            "started_at": "2026-08-17T00:00:00+00:00",
            "completed_at": "2026-08-17T00:00:01+00:00",
            "elapsed_seconds": 0.001,
            "unsafe_tool_event": False,
            "model_started": True,
        }
        events = (
            f'{{"type":"thread.started","thread_id":"mock-{len(counter)}"}}\n'
            '{"type":"turn.started"}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        )
        return raw, metadata, events

    return invoke


def _first_identity(prepared: Any, skill_version: str) -> tuple[str, dict[str, Any]]:
    return next(
        (pipeline_id, identity)
        for pipeline_id, identity in prepared.private_map["pipeline_id_to_identity"].items()
        if identity["skill_version"] == skill_version
    )


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

    v2_pipeline_id = next(
        pipeline_id
        for pipeline_id, identity in prepared.private_map["pipeline_id_to_identity"].items()
        if identity["skill_version"] == "v2"
        and pipeline_id
        in {item["pipeline_id"] for item in prepared.public_plan["schedule"][0]["pipelines"]}
    )
    v2_pipeline_dir = prepared.experiment_dir / "pipelines" / v2_pipeline_id
    v2_contract = json.loads(
        (v2_pipeline_dir / "pipeline-contract.json").read_text(encoding="utf-8")
    )
    v2_summary = json.loads((v2_pipeline_dir / "summary.json").read_text(encoding="utf-8"))
    assert len(v2_contract["required_call_ids"]) == 1
    assert set(v2_contract["conditional_call_ids"]) == {"nonempty_portfolio"}
    assert v2_summary["normal_model_call_count"] == 2
    assert v2_summary["total_model_attempt_count"] == 2
    assert v2_summary["completion_bound_usage_complete"] is True
    assert v2_summary["completion_bound_total_usage"]["reported_total_tokens"] == 4
    assert {
        "combined-discovery.json",
        "combined-validation.json",
        "combined-payload-capacity.json",
        "adaptive-portfolio.json",
        "repair-budget.json",
    }.issubset(path.name for path in v2_pipeline_dir.iterdir())

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
    assert len(counter) == 18

    resumed = RUNNER._run_experiment(prepared)
    assert resumed["completed_pipeline_count"] == 12
    assert len(counter) == 18

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


@pytest.mark.parametrize(
    "mutation",
    [
        "dependency",
        "stage",
        "completion_call_id",
        "completion_schema",
        "first_prompt",
        "final_status",
    ],
)
def test_completed_pipeline_rejects_coordinated_call_receipt_tamper_before_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory([]))
    RUNNER._run_experiment(prepared, sentinel=True)
    pipeline_id = prepared.public_plan["schedule"][0]["pipelines"][0]["pipeline_id"]
    pipeline_dir = prepared.experiment_dir / "pipelines" / pipeline_id
    pipeline_contract = json.loads(
        (pipeline_dir / "pipeline-contract.json").read_text(encoding="utf-8")
    )
    call_id = pipeline_contract["required_call_ids"][0]
    call_dir = prepared.experiment_dir / "calls" / call_id
    contract_path = call_dir / "call-contract.json"
    completion_path = call_dir / "complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))

    if mutation in {"dependency", "stage"}:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if mutation == "dependency":
            dependency = next(iter(contract["dependency_sha256"]))
            contract["dependency_sha256"][dependency] = "0" * 64
        else:
            contract["stage"] = "tampered-stage"
        contract_path.write_bytes(RUNNER._pretty_json_bytes(contract))
        completion["call_contract_sha256"] = RUNNER._sha256_path(contract_path)
    elif mutation == "completion_call_id":
        completion["call_id"] = "call_00000000000000000000"
    elif mutation == "completion_schema":
        completion["schema_version"] = "999"
    else:
        attempt_number = completion["successful_attempt"]
        attempt_dir = call_dir / f"attempts/{attempt_number:03d}"
        attempt_contract_path = attempt_dir / "attempt-contract.json"
        attempt_contract = json.loads(attempt_contract_path.read_text(encoding="utf-8"))
        if mutation == "first_prompt":
            attempt_contract["prompt_sha256"] = "0" * 64
        else:
            metadata_path = attempt_dir / "call-metadata.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["failure_category"] = "model_output_validation_failure"
            metadata_path.write_bytes(RUNNER._pretty_json_bytes(metadata))
            failure_path = attempt_dir / "failure.json"
            failure_path.write_bytes(
                RUNNER._pretty_json_bytes(
                    {
                        "error": "coordinated tamper",
                        "category": "model_output_validation_failure",
                        "recorded_at": "2026-08-17T00:00:01+00:00",
                    }
                )
            )
            attempt_contract["status"] = "failed"
            attempt_contract["artifact_sha256"]["call-metadata.json"] = RUNNER._sha256_path(
                metadata_path
            )
            attempt_contract["artifact_sha256"]["failure.json"] = RUNNER._sha256_path(failure_path)
        attempt_contract_path.write_bytes(RUNNER._pretty_json_bytes(attempt_contract))
        completion["successful_attempt_contract_sha256"] = RUNNER._sha256_path(
            attempt_contract_path
        )
        completion["attempt_receipts"] = RUNNER._attempt_receipt_inventory(call_dir, attempt_number)
    completion_path.write_bytes(RUNNER._pretty_json_bytes(completion))

    pipeline_completion_path = pipeline_dir / "complete.json"
    pipeline_completion = json.loads(pipeline_completion_path.read_text(encoding="utf-8"))
    for receipt in pipeline_completion["call_receipts"]:
        if receipt["call_id"] == call_id:
            receipt["call_completion_sha256"] = RUNNER._sha256_path(completion_path)
    pipeline_completion_path.write_bytes(RUNNER._pretty_json_bytes(pipeline_completion))

    resumed_model_calls = 0

    def forbidden_invoke(**_: Any):
        nonlocal resumed_model_calls
        resumed_model_calls += 1
        raise AssertionError("call receipt tamper must fail before model")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_invoke)
    with pytest.raises(RuntimeError, match="drift"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert resumed_model_calls == 0


@pytest.mark.parametrize("case", ["v1_result", "v2_result", "v2_empty_combined", "v1_numeric_type"])
def test_pipeline_resume_reconstructs_deterministic_artifacts_byte_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    if case == "v2_empty_combined":
        monkeypatch.setattr(RUNNER, "BASE_MINIMUM_QUALITY", 100.0)
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    skill_version = "v1" if case.startswith("v1") else "v2"
    pipeline_id, identity = _first_identity(prepared, skill_version)
    calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(calls))
    if skill_version == "v1":
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    else:
        RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    pipeline_dir = prepared.experiment_dir / "pipelines" / pipeline_id
    completion_path = pipeline_dir / "complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if case in {"v1_result", "v2_result"}:
        artifact_name = "result.json"
        artifact_path = pipeline_dir / artifact_name
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["selection_summary"] = "pipeline-only coordinated tamper"
    elif case == "v2_empty_combined":
        artifact_name = "combined-discovery.json"
        artifact_path = pipeline_dir / artifact_name
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["inventory_summary"] = "pipeline-only coordinated tamper"
    else:
        artifact_name = "summary.json"
        artifact_path = pipeline_dir / artifact_name
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        artifact["selected_count"] = float(artifact["selected_count"])
    artifact_path.write_bytes(RUNNER._pretty_json_bytes(artifact))
    completion["artifact_sha256"][artifact_name] = RUNNER._sha256_path(artifact_path)
    completion_path.write_bytes(RUNNER._pretty_json_bytes(completion))

    calls_before_resume = len(calls)
    with pytest.raises(RuntimeError, match="byte drift"):
        if skill_version == "v1":
            RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
        else:
            RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    assert len(calls) == calls_before_resume


def test_attempt_usage_must_match_event_evidence_after_coordinated_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory([]))
    RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    pipeline_dir = prepared.experiment_dir / "pipelines" / pipeline_id
    call_id = json.loads((pipeline_dir / "pipeline-contract.json").read_text(encoding="utf-8"))[
        "required_call_ids"
    ][0]
    call_dir = prepared.experiment_dir / "calls" / call_id
    attempt_dir = call_dir / "attempts/001"
    metadata_path = attempt_dir / "call-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["usage"] = {"input_tokens": 0, "output_tokens": 0}
    metadata_path.write_bytes(RUNNER._pretty_json_bytes(metadata))
    (call_dir / "call-metadata.json").write_bytes(metadata_path.read_bytes())

    attempt_contract_path = attempt_dir / "attempt-contract.json"
    attempt_contract = json.loads(attempt_contract_path.read_text(encoding="utf-8"))
    attempt_contract["artifact_sha256"]["call-metadata.json"] = RUNNER._sha256_path(metadata_path)
    attempt_contract_path.write_bytes(RUNNER._pretty_json_bytes(attempt_contract))
    completion_path = call_dir / "complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["successful_attempt_contract_sha256"] = RUNNER._sha256_path(attempt_contract_path)
    completion["artifact_sha256"]["call-metadata.json"] = RUNNER._sha256_path(
        call_dir / "call-metadata.json"
    )
    attempt_receipt = completion["attempt_receipts"][0]
    attempt_receipt["attempt_contract_sha256"] = RUNNER._sha256_path(attempt_contract_path)
    attempt_receipt["usage"] = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "reported_total_tokens": 0,
    }
    completion_path.write_bytes(RUNNER._pretty_json_bytes(completion))

    summary_path = pipeline_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["completion_bound_total_usage"] = dict(attempt_receipt["usage"])
    summary_path.write_bytes(RUNNER._pretty_json_bytes(summary))
    pipeline_completion_path = pipeline_dir / "complete.json"
    pipeline_completion = json.loads(pipeline_completion_path.read_text(encoding="utf-8"))
    pipeline_completion["artifact_sha256"]["summary.json"] = RUNNER._sha256_path(summary_path)
    pipeline_completion["call_receipts"][0]["call_completion_sha256"] = RUNNER._sha256_path(
        completion_path
    )
    pipeline_completion_path.write_bytes(RUNNER._pretty_json_bytes(pipeline_completion))

    resumed_calls = 0

    def forbidden_invoke(**_: Any):
        nonlocal resumed_calls
        resumed_calls += 1
        raise AssertionError("usage/event drift must fail before model")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_invoke)
    with pytest.raises(RuntimeError, match=r"turn.started evidence"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert resumed_calls == 0


def test_empty_portfolio_skips_selected_copy_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "BASE_MINIMUM_QUALITY", 100.0)
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    counter: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(counter))
    result = RUNNER._run_experiment(prepared, sentinel=True)
    assert result["completed_pipeline_count"] == 2
    assert len(counter) == 2
    assert not any("v2-selected-copy" in label for label in counter)
    summaries_by_version = {
        prepared.private_map["arm_id_to_skill_version"][summary["arm_id"]]: summary
        for summary in result["completed_pipelines"]
    }
    assert all(
        isinstance(summary["underfilled_due_to_quality"], bool)
        for summary in summaries_by_version.values()
    )
    assert summaries_by_version["v1"]["underfilled_due_to_quality"] is False
    v2_summary = summaries_by_version["v2"]
    assert v2_summary["selected_count"] == 0
    assert v2_summary["stage_success_elapsed_seconds"]["selected_copy"] == 0.0
    assert v2_summary["normal_model_call_count"] == 1
    assert v2_summary["underfilled_due_to_quality"] is True


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
    assert observed["input"] == b""
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


def test_preflight_completion_binds_exact_contiguous_receipt_tree(
    tmp_path: Path,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    RUNNER._ensure_runtime_preflight(prepared)
    preflight_dir = prepared.experiment_dir / "infrastructure/preflight"
    receipt_path = preflight_dir / "checks/001/receipt.json"
    completion_path = preflight_dir / "complete.json"
    receipt_bytes = receipt_path.read_bytes()
    completion_bytes = completion_path.read_bytes()
    completion = json.loads(completion_bytes)
    assert completion["receipt_sha256"] == [
        {
            "relative_path": "checks/001/receipt.json",
            "sha256": RUNNER._sha256_bytes(receipt_bytes),
        }
    ]

    receipt = json.loads(receipt_bytes)
    receipt["stderr_tail"] = "schema-valid post-pass mutation"
    receipt_path.write_bytes(RUNNER._pretty_json_bytes(receipt))
    with pytest.raises(RuntimeError, match="completion receipt drift"):
        RUNNER._ensure_runtime_preflight(prepared)
    receipt_path.write_bytes(receipt_bytes)

    completion["passed_check"] = 2
    completion_path.write_bytes(RUNNER._pretty_json_bytes(completion))
    with pytest.raises(RuntimeError, match="completion receipt drift"):
        RUNNER._ensure_runtime_preflight(prepared)
    completion_path.write_bytes(completion_bytes)

    extra = preflight_dir / "extra.json"
    extra.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="root inventory drift"):
        RUNNER._ensure_runtime_preflight(prepared)
    extra.unlink()

    noncanonical = preflight_dir / "checks/1"
    noncanonical.mkdir()
    with pytest.raises(RuntimeError, match="receipt tree drift"):
        RUNNER._ensure_runtime_preflight(prepared)
    noncanonical.rmdir()

    late = preflight_dir / "checks/002"
    late.mkdir()
    late_receipt = json.loads(receipt_bytes)
    late_receipt["check_number"] = 2
    (late / "receipt.json").write_bytes(RUNNER._pretty_json_bytes(late_receipt))
    with pytest.raises(RuntimeError, match="passed receipt sequence drift"):
        RUNNER._ensure_runtime_preflight(prepared)


def test_preflight_invalid_utf8_is_a_bounded_zero_model_failure_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    model_calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(model_calls))

    def invalid_utf8(command: list[str], *, cwd: Path, env: dict[str, str]):
        del cwd, env
        return subprocess.CompletedProcess(command, 0, stdout=b"\xff", stderr=b"")

    monkeypatch.setattr(RUNNER, "_run_preflight_process", invalid_utf8)
    with pytest.raises(RUNNER.CodexInfrastructureUnavailable, match="preflight failed"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert model_calls == []
    receipt_path = prepared.experiment_dir / "infrastructure/preflight/checks/001/receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["category"] == "infrastructure_preflight_invalid_utf8"
    assert receipt["returncode"] is None
    assert receipt["model_started"] is False

    def ready(command: list[str], *, cwd: Path, env: dict[str, str]):
        del cwd, env
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(RUNNER, "_run_preflight_process", ready)
    RUNNER._run_experiment(prepared, sentinel=True)
    assert model_calls
    assert (prepared.experiment_dir / "infrastructure/preflight/complete.json").is_file()


def test_preflight_receipt_rejects_unknown_category_and_returncode_semantics(
    tmp_path: Path,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    policy = prepared.manifest["immutable_contract"]["runtime_preflight"]
    base = {
        "schema_version": "1",
        "policy_version": RUNNER.PREFLIGHT_POLICY_VERSION,
        "experiment_id": prepared.experiment_id,
        "experiment_contract_sha256": prepared.contract_sha256,
        "check_number": 1,
        "status": "failed",
        "category": "infrastructure_permission_denied",
        "command_sha256": policy["command_sha256"],
        "returncode": 1,
        "model_started": False,
        "model_attempt_consumed": False,
        "stdout_tail": "",
        "stderr_tail": "permission denied",
        "recorded_at": "2026-08-17T00:00:00+00:00",
    }
    invalid_semantics = (
        ("infrastructure_unknown", 1),
        ("infrastructure_permission_denied", None),
        ("infrastructure_preflight_timeout", 1),
        ("infrastructure_preflight_process_failure", 0),
    )
    for category, returncode in invalid_semantics:
        receipt = {**base, "category": category, "returncode": returncode}
        with pytest.raises(RuntimeError, match="preflight receipt drift"):
            RUNNER._validate_preflight_receipt(receipt, prepared, 1)


def test_preflight_completion_hashes_the_same_receipt_snapshot_it_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    original_receipt = RUNNER._ensure_runtime_preflight(prepared)
    receipt_path = prepared.experiment_dir / "infrastructure/preflight/checks/001/receipt.json"
    original_bytes = receipt_path.read_bytes()
    completion_path = prepared.experiment_dir / "infrastructure/preflight/complete.json"
    original_completion = json.loads(completion_path.read_text(encoding="utf-8"))
    assert original_completion["receipt_sha256"][0]["sha256"] == (
        RUNNER._sha256_bytes(original_bytes)
    )
    real_validate = RUNNER._validate_preflight_receipt
    staged = False

    def validate_then_swap(receipt: dict[str, Any], current: Any, check_number: int) -> None:
        nonlocal staged
        real_validate(receipt, current, check_number)
        if not staged:
            staged = True
            receipt_path.write_bytes(
                RUNNER._pretty_json_bytes(
                    {
                        **receipt,
                        "status": "failed",
                        "category": "infrastructure_preflight_timeout",
                        "returncode": None,
                    }
                )
            )

    process_calls = 0

    def forbidden_preflight(*_: Any, **__: Any):
        nonlocal process_calls
        process_calls += 1
        raise AssertionError("completed preflight must not launch another process")

    monkeypatch.setattr(RUNNER, "_validate_preflight_receipt", validate_then_swap)
    monkeypatch.setattr(RUNNER, "_run_preflight_process", forbidden_preflight)
    resumed = RUNNER._ensure_runtime_preflight(prepared)
    assert staged is True
    assert resumed == original_receipt
    assert completion_path.read_bytes() == RUNNER._pretty_json_bytes(original_completion)
    assert process_calls == 0


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


def test_call_infrastructure_receipt_rejects_unknown_category_and_rc_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    process_attempts = 0

    def fail_before_model(**_: Any):
        nonlocal process_attempts
        process_attempts += 1
        raise RUNNER.CodexProcessFailure(
            "pre-model permission failure",
            category="infrastructure_permission_denied",
            model_started=False,
            returncode=1,
        )

    monkeypatch.setattr(RUNNER, "_invoke_codex", fail_before_model)
    with pytest.raises(RUNNER.CodexInfrastructureUnavailable):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    contract = json.loads((call_dir / "call-contract.json").read_text(encoding="utf-8"))
    receipt_path = call_dir / "infrastructure-failures/001/receipt.json"
    original = json.loads(receipt_path.read_text(encoding="utf-8"))
    invalid_semantics = (
        ("infrastructure_unknown", 1),
        ("infrastructure_permission_denied", None),
        ("infrastructure_process_timeout", 1),
        ("infrastructure_no_model_turn", 1),
    )
    for category, returncode in invalid_semantics:
        receipt_path.write_bytes(
            RUNNER._pretty_json_bytes({**original, "category": category, "returncode": returncode})
        )
        with pytest.raises(RuntimeError, match="infrastructure receipt drift"):
            RUNNER._validated_call_infrastructure_failure_count(call_dir, contract)
    assert process_attempts == 1


def test_completed_call_costs_bind_validated_infrastructure_receipt_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_dir = _recover_call_after_infrastructure_failure(tmp_path, monkeypatch)
    receipt_path = call_dir / "infrastructure-failures/001/receipt.json"
    original_bytes = receipt_path.read_bytes()
    original_receipt = json.loads(original_bytes)
    completion = json.loads((call_dir / "complete.json").read_text(encoding="utf-8"))
    assert completion["infrastructure_failure_receipts"][0]["sha256"] == (
        RUNNER._sha256_bytes(original_bytes)
    )
    real_semantics = RUNNER._valid_call_infrastructure_semantics
    staged = False

    def validate_then_swap(category: Any, returncode: Any) -> bool:
        nonlocal staged
        valid = real_semantics(category, returncode)
        if not staged:
            staged = True
            receipt_path.write_bytes(
                RUNNER._pretty_json_bytes(
                    {
                        **original_receipt,
                        "category": "infrastructure_no_model_turn",
                        "returncode": 0,
                        "stderr_tail": "STAGED_AFTER_SEMANTIC_VALIDATION",
                    }
                )
            )
        return valid

    model_calls = 0

    def forbidden_model(**_: Any):
        nonlocal model_calls
        model_calls += 1
        raise AssertionError("completed call verification must not invoke a model")

    monkeypatch.setattr(RUNNER, "_valid_call_infrastructure_semantics", validate_then_swap)
    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_model)
    snapshot = RUNNER._verified_call_snapshot(call_dir)
    costs = RUNNER._pipeline_attempt_costs_from_snapshots([snapshot])
    assert staged is True
    assert snapshot["completion"]["infrastructure_failure_receipts"] == [
        {
            "relative_path": "infrastructure-failures/001/receipt.json",
            "sha256": RUNNER._sha256_bytes(original_bytes),
        }
    ]
    assert costs["normal_model_call_count"] == 1
    assert costs["total_model_attempt_count"] == 1
    assert costs["completion_bound_total_usage"]["reported_total_tokens"] == 2
    assert model_calls == 0


@pytest.mark.parametrize("mutation", ["tamper", "stage", "delete", "extra"])
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
    elif mutation == "stage":
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["stage"] = "v2-selected-copy"
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

    resumed_model_calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(resumed_model_calls))
    with pytest.raises(RuntimeError, match="infrastructure"):
        RUNNER._run_experiment(RUNNER._prepare_experiment(tmp_path / "experiments"), sentinel=True)
    assert resumed_model_calls == []


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
                "usage_status": "reported",
                "started_at": "2026-08-17T00:00:00+00:00",
                "completed_at": "2026-08-17T00:00:01+00:00",
                "elapsed_seconds": 0.001,
                "unsafe_tool_event": False,
                "model_started": True,
            },
            f'{{"type":"thread.started","thread_id":"invalid-{len(model_calls)}"}}\n'
            '{"type":"turn.started"}\n'
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',
        )

    monkeypatch.setattr(RUNNER, "_invoke_codex", invalid)
    with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert len(model_calls) == 2
    call_dir = next((prepared.experiment_dir / "calls").iterdir())
    assert sorted(path.name for path in (call_dir / "attempts").iterdir()) == [
        "001",
        "002",
    ]
    assert not (call_dir / "infrastructure-failures").exists()
    terminal_path = call_dir / "terminal.json"
    terminal_bytes = terminal_path.read_bytes()
    terminal = json.loads(terminal_bytes)
    assert terminal["status"] == "exhausted"
    assert terminal["failure_category"] == "model_attempts_exhausted"
    assert terminal["terminal_attempt"] == RUNNER.MAX_MODEL_ATTEMPTS
    assert terminal["total_model_attempt_count"] == 2
    assert terminal["completion_bound_total_usage"]["reported_total_tokens"] == 4
    assert not (call_dir / "complete.json").exists()

    with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert len(model_calls) == 2
    assert terminal_path.read_bytes() == terminal_bytes

    terminal["failure_category"] = "pipeline_repair_budget_exhausted"
    terminal_path.write_bytes(RUNNER._pretty_json_bytes(terminal))
    with pytest.raises(RuntimeError, match="category/attempt drift"):
        RUNNER._validate_terminal_call(call_dir)
    terminal_path.write_bytes(terminal_bytes)

    terminal = json.loads(terminal_bytes)
    terminal["completion_bound_total_elapsed_seconds"] += 1
    terminal_path.write_bytes(RUNNER._pretty_json_bytes(terminal))
    with pytest.raises(RuntimeError, match="terminal call receipt drift"):
        RUNNER._validate_terminal_call(call_dir)


@pytest.mark.parametrize("outcome", ["completed_attempt_two", "terminal_attempt_two"])
def test_attempt_two_prompt_chain_tamper_fails_before_resume_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    calls: list[str] = []
    base = _mock_invoke_factory(calls)

    def repaired_or_terminal(*, label: str, prompt: str, schema_path: Path):
        raw, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        if outcome == "terminal_attempt_two" or len(calls) == 1:
            raw = {}
        return raw, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", repaired_or_terminal)
    if outcome == "completed_attempt_two":
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    else:
        with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
            RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert len(calls) == 2
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    attempt_contract_path = call_dir / "attempts/002/attempt-contract.json"
    attempt_contract = json.loads(attempt_contract_path.read_text(encoding="utf-8"))
    attempt_contract["prompt_sha256"] = "0" * 64
    attempt_contract_path.write_bytes(RUNNER._pretty_json_bytes(attempt_contract))

    if outcome == "completed_attempt_two":
        receipt_path = call_dir / "complete.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["successful_attempt_contract_sha256"] = RUNNER._sha256_path(attempt_contract_path)
        receipt["attempt_receipts"] = RUNNER._attempt_receipt_inventory(call_dir, 2)
        receipt_path.write_bytes(RUNNER._pretty_json_bytes(receipt))
        pipeline_completion_path = (
            prepared.experiment_dir / "pipelines" / pipeline_id / "complete.json"
        )
        pipeline_completion = json.loads(pipeline_completion_path.read_text(encoding="utf-8"))
        pipeline_completion["call_receipts"][0]["call_completion_sha256"] = RUNNER._sha256_path(
            receipt_path
        )
        pipeline_completion_path.write_bytes(RUNNER._pretty_json_bytes(pipeline_completion))
    else:
        receipt_path = call_dir / "terminal.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["terminal_attempt_contract_sha256"] = RUNNER._sha256_path(attempt_contract_path)
        receipt["attempt_receipts"] = RUNNER._attempt_receipt_inventory(call_dir, 2)
        receipt_path.write_bytes(RUNNER._pretty_json_bytes(receipt))

    calls_before_resume = len(calls)
    with pytest.raises(RuntimeError, match="prompt chain drift"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert len(calls) == calls_before_resume


@pytest.mark.parametrize("mutation", ["only_002", "extra_003", "junk", "symlink"])
def test_incomplete_attempt_inventory_fails_before_resume_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    base = _mock_invoke_factory([])
    setup_calls = 0

    def leave_one_failed_attempt(*, label: str, prompt: str, schema_path: Path):
        nonlocal setup_calls
        setup_calls += 1
        if setup_calls == 2:
            raise KeyboardInterrupt
        _, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        return {}, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", leave_one_failed_attempt)
    with pytest.raises(KeyboardInterrupt):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    attempts = call_dir / "attempts"
    if mutation == "only_002":
        (attempts / "001").rename(attempts / "002")
    elif mutation == "extra_003":
        (attempts / "003").mkdir()
    elif mutation == "junk":
        (attempts / "junk.txt").write_text("junk", encoding="utf-8")
    else:
        (attempts / "002").symlink_to(attempts / "001", target_is_directory=True)

    resume_calls = 0

    def forbidden_invoke(**_: Any):
        nonlocal resume_calls
        resume_calls += 1
        raise AssertionError("attempt inventory drift must fail before invoke")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_invoke)
    with pytest.raises(RuntimeError, match=r"attempt (inventory|sequence) drift"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert resume_calls == 0


def test_unsafe_tool_event_is_persisted_hard_failure_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    model_calls: list[str] = []
    unsafe_events = (
        '{"type":"thread.started","thread_id":"unsafe-test"}\n'
        '{"type":"turn.started"}\n'
        '{"type":"item.started","item":{"type":"command_execution"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":0}}\n'
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
            attempt_metadata={
                "label": label,
                "model": "gpt-5.6-sol",
                "reasoning_effort": "medium",
                "request_id": "unsafe-test",
                "usage": {"input_tokens": 1, "output_tokens": 0},
                "usage_status": "reported",
                "started_at": "2026-08-17T00:00:00+00:00",
                "completed_at": "2026-08-17T00:00:01+00:00",
                "elapsed_seconds": 0.001,
                "unsafe_tool_event": True,
                "model_started": True,
                "failure_category": "model_safety_tool_event",
            },
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
    assert attempt_contract["status"] == "terminal_failed"
    assert failure["category"] == "model_safety_tool_event"
    assert (attempt_dir / "events.jsonl").read_text(encoding="utf-8") == unsafe_events
    terminal = json.loads((call_dir / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["status"] == "terminal_failed"
    assert terminal["failure_category"] == "model_safety_tool_event"

    with pytest.raises(RuntimeError, match="persisted terminal model failure"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert len(model_calls) == 1
    assert sorted(path.name for path in (call_dir / "attempts").iterdir()) == ["001"]

    metadata_path = attempt_dir / "call-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["failure_category"] = "model_process_failure"
    metadata_path.write_bytes(RUNNER._pretty_json_bytes(metadata))
    failure["category"] = "model_process_failure"
    (attempt_dir / "failure.json").write_bytes(RUNNER._pretty_json_bytes(failure))
    attempt_contract["status"] = "failed"
    attempt_contract["artifact_sha256"]["call-metadata.json"] = RUNNER._sha256_path(metadata_path)
    attempt_contract["artifact_sha256"]["failure.json"] = RUNNER._sha256_path(
        attempt_dir / "failure.json"
    )
    (attempt_dir / "attempt-contract.json").write_bytes(RUNNER._pretty_json_bytes(attempt_contract))
    with pytest.raises(RuntimeError, match=r"turn.started evidence"):
        RUNNER._attempt_receipt(attempt_dir, 1)


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


def test_post_turn_invalid_utf8_persists_attempt_evidence_and_terminal_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    process_calls = 0
    events = (
        '{"type":"thread.started","thread_id":"utf8-test"}\n'
        '{"type":"turn.started"}\n'
        '{"type":"turn.completed","usage":{"input_tokens":2,"output_tokens":1}}\n'
    )

    def invalid_utf8(command: list[str], **_: Any):
        nonlocal process_calls
        process_calls += 1
        output_index = command.index("--output-last-message") + 1
        Path(command[output_index]).write_bytes(b"\xff")
        return subprocess.CompletedProcess(command, 0, stdout=events, stderr="")

    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(RUNNER.subprocess, "run", invalid_utf8)
    with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert process_calls == 2
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    for number in (1, 2):
        attempt_dir = call_dir / f"attempts/{number:03d}"
        metadata = json.loads((attempt_dir / "call-metadata.json").read_text(encoding="utf-8"))
        failure = json.loads((attempt_dir / "failure.json").read_text(encoding="utf-8"))
        assert metadata["failure_category"] == "model_output_invalid_utf8"
        assert failure["category"] == "model_output_invalid_utf8"
        assert (attempt_dir / "events.jsonl").read_text(encoding="utf-8") == events
    terminal = json.loads((call_dir / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["total_model_attempt_count"] == 2
    assert terminal["completion_bound_total_usage"]["reported_total_tokens"] == 6

    with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert process_calls == 2


def test_incomplete_event_usage_is_unavailable_not_reported_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    events = b'{"type":"turn.started"}\n{"type":"turn.completed","usage":{"total_tokens":99}}\n'

    def incomplete_usage(command: list[str], **_: Any):
        output_index = command.index("--output-last-message") + 1
        Path(command[output_index]).write_bytes(b"\xff")
        return subprocess.CompletedProcess(command, 0, stdout=events, stderr=b"")

    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(RUNNER.subprocess, "run", incomplete_usage)
    with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    for number in (1, 2):
        metadata = json.loads(
            (call_dir / f"attempts/{number:03d}/call-metadata.json").read_text(encoding="utf-8")
        )
        assert metadata["usage"] is None
        assert metadata["usage_status"] == "unavailable"
    terminal = json.loads((call_dir / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["completion_bound_usage_complete"] is False
    assert terminal["completion_bound_total_usage"]["reported_total_tokens"] == 0


@pytest.mark.parametrize("event_failure", ["json_primitive", "invalid_utf8"])
def test_post_turn_event_stream_anomalies_preserve_bounded_cost_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_failure: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    process_calls = 0
    if event_failure == "json_primitive":
        stdout = (
            b'{"type":"turn.started"}\nnull\n'
            b'{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        )
        expected_category = "model_output_missing"
    else:
        stdout = (
            b'{"type":"turn.started"}\n\xff\n'
            b'{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        )
        expected_category = "model_event_stream_invalid_utf8"

    def anomalous_events(command: list[str], **_: Any):
        nonlocal process_calls
        process_calls += 1
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(RUNNER.subprocess, "run", anomalous_events)
    with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert process_calls == 2
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    for number in (1, 2):
        attempt_dir = call_dir / f"attempts/{number:03d}"
        metadata = json.loads((attempt_dir / "call-metadata.json").read_text(encoding="utf-8"))
        failure = json.loads((attempt_dir / "failure.json").read_text(encoding="utf-8"))
        assert metadata["model_started"] is True
        assert metadata["failure_category"] == expected_category
        assert failure["category"] == expected_category
        assert '"type":"turn.started"' in (attempt_dir / "events.jsonl").read_text(encoding="utf-8")
    terminal = json.loads((call_dir / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["total_model_attempt_count"] == 2
    assert terminal["completion_bound_total_usage"]["reported_total_tokens"] == 4


@pytest.mark.parametrize("failure_mode", ["no_turn", "invalid_utf8", "timeout"])
def test_unsafe_item_is_model_started_and_dominates_process_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    process_calls = 0
    unsafe_line = b'{"type":"item.started","item":{"type":"command_execution"}}\n'

    def unsafe_process(command: list[str], **_: Any):
        nonlocal process_calls
        process_calls += 1
        if failure_mode == "timeout":
            raise subprocess.TimeoutExpired(command, 1, output=unsafe_line, stderr=b"timeout")
        stdout = unsafe_line + (b"\xff\n" if failure_mode == "invalid_utf8" else b"")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(RUNNER.subprocess, "run", unsafe_process)
    with pytest.raises(RuntimeError, match="unsafe tool event"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert process_calls == 1
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    attempt = json.loads(
        (call_dir / "attempts/001/attempt-contract.json").read_text(encoding="utf-8")
    )
    terminal = json.loads((call_dir / "terminal.json").read_text(encoding="utf-8"))
    assert attempt["status"] == "terminal_failed"
    assert terminal["failure_category"] == "model_safety_tool_event"
    assert terminal["completion_bound_usage_complete"] is False


def test_failed_arbitrary_json_output_can_resume_same_stage_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    base = _mock_invoke_factory([])
    setup_calls = 0

    def list_then_interrupt(*, label: str, prompt: str, schema_path: Path):
        nonlocal setup_calls
        setup_calls += 1
        if setup_calls == 2:
            raise KeyboardInterrupt
        _, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        return [], metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", list_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    assert json.loads((call_dir / "attempts/001/result.raw.json").read_text()) == []

    resumed_calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(resumed_calls))
    summary = RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    assert summary["total_model_attempt_count"] == 2
    assert len(resumed_calls) == 1
    completion = json.loads((call_dir / "complete.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in completion["attempt_receipts"]] == [
        "failed",
        "validated",
    ]


@pytest.mark.parametrize(
    ("hostile_output", "expected_category"),
    [
        ("lone_surrogate", "model_output_invalid_unicode"),
        ("oversized_integer", "model_output_invalid_json_resource"),
        ("surrogate_request_id", "model_output_invalid_utf8"),
    ],
)
def test_hostile_json_and_event_text_still_persist_terminal_costs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hostile_output: str,
    expected_category: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    if hostile_output == "lone_surrogate":
        output_bytes = b'{"selection_summary":"\\ud800","highlights":[]}'
        thread_line = b'{"type":"thread.started","thread_id":"safe"}\n'
    elif hostile_output == "oversized_integer":
        output_bytes = b'{"value":' + (b"9" * 5000) + b"}"
        thread_line = b'{"type":"thread.started","thread_id":"safe"}\n'
    else:
        output_bytes = b"\xff"
        thread_line = b'{"type":"thread.started","thread_id":"\\ud800"}\n'
    events = (
        thread_line
        + b'{"type":"turn.started"}\n'
        + b'{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
    )

    def hostile(command: list[str], **_: Any):
        output_index = command.index("--output-last-message") + 1
        Path(command[output_index]).write_bytes(output_bytes)
        return subprocess.CompletedProcess(command, 0, stdout=events, stderr=b"")

    monkeypatch.setattr(RUNNER.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(RUNNER.subprocess, "run", hostile)
    with pytest.raises(RuntimeError, match="exhausted 2 same-stage attempts"):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    call_dir = prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v1-generation")
    for number in (1, 2):
        attempt_dir = call_dir / f"attempts/{number:03d}"
        metadata = json.loads((attempt_dir / "call-metadata.json").read_text(encoding="utf-8"))
        failure = json.loads((attempt_dir / "failure.json").read_text(encoding="utf-8"))
        assert metadata["failure_category"] == expected_category
        assert failure["category"] == expected_category
        if hostile_output == "surrogate_request_id":
            assert metadata["request_id"] is None
    terminal = json.loads((call_dir / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["total_model_attempt_count"] == 2


def test_evaluation_contract_is_raw_byte_bound_and_changes_experiment_identity(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "experiments"
    source_path = RUNNER.EVALUATION_CONTRACT_PATH
    original = source_path.read_bytes()
    first = RUNNER._prepare_experiment(output_root)
    assert first.manifest["immutable_contract"]["evaluation_contract_sha256"] == (
        RUNNER._sha256_bytes(original)
    )
    assert first.manifest["immutable_contract"]["evaluation_contract_version"] == (
        "highlight-agent-skill-v2-iteration-2-evaluation-v1"
    )
    assert (first.experiment_dir / "frozen/evaluation-contract.json").read_bytes() == original

    parsed = json.loads(original)
    source_path.write_text(
        json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    second = RUNNER._prepare_experiment(output_root)
    assert second.experiment_id != first.experiment_id
    assert (first.experiment_dir / "experiment-manifest.json").is_file()
    assert second.manifest["immutable_contract"]["evaluation_contract_sha256"] == (
        RUNNER._sha256_path(source_path)
    )


def test_evaluation_contract_rejects_indexed_artifact_hash_drift() -> None:
    source_path = RUNNER.EVALUATION_CONTRACT_PATH
    contract = json.loads(source_path.read_text(encoding="utf-8"))
    relative = "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/contracts.py"
    contract["artifacts"][relative]["sha256"] = "0" * 64
    source_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="evaluation artifact hash drift"):
        RUNNER._load_evaluation_contract()


def test_prepare_uses_captured_evaluation_materials_after_runtime_paths_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    materials = RUNNER._load_evaluation_materials()
    hostile_root = tmp_path / "hostile-working-tree"
    hostile_agent = hostile_root / "agent"
    (hostile_agent / "references").mkdir(parents=True)
    marker = tmp_path / "hostile-module-executed"
    hostile_module = f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n"
    hostile_contracts = hostile_root / "contracts.py"
    hostile_input_gate = hostile_root / "input_gate.py"
    hostile_contracts.write_text(hostile_module, encoding="utf-8")
    hostile_input_gate.write_text(hostile_module, encoding="utf-8")
    hostile_v1_skill = hostile_root / "v1-skill.md"
    hostile_v1_skill.write_text("---\nname: hostile\n---\nHOSTILE_V1\n", encoding="utf-8")
    hostile_v1_schema = hostile_root / "v1-schema.json"
    hostile_v1_schema.write_text("{}\n", encoding="utf-8")
    (hostile_agent / "SKILL.md").write_text(
        "---\nname: hostile\n---\nHOSTILE_AGENT\n", encoding="utf-8"
    )
    for reference in (
        "atomic-scoring.md",
        "combined-discovery.md",
        "risk-and-repair.md",
        "selected-copy.md",
    ):
        (hostile_agent / "references" / reference).write_text(
            f"HOSTILE_REFERENCE_{reference}\n", encoding="utf-8"
        )

    monkeypatch.setattr(RUNNER, "CONTRACTS_PATH", hostile_contracts)
    monkeypatch.setattr(RUNNER, "INPUT_GATE_PATH", hostile_input_gate)
    monkeypatch.setattr(RUNNER, "V1_SKILL_PATH", hostile_v1_skill)
    monkeypatch.setattr(RUNNER, "V1_SCHEMA_PATH", hostile_v1_schema)
    monkeypatch.setattr(RUNNER, "V2_SKILL_DIR", hostile_agent)
    model_calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(model_calls))

    prepared = RUNNER._prepare_experiment(tmp_path / "experiments", evaluation_materials=materials)
    assert not marker.exists()
    assert model_calls == []
    assert (prepared.experiment_dir / "frozen/gates/contracts.py").read_bytes() == (
        materials.artifact_bytes[RUNNER.CONTRACTS_RELATIVE_PATH]
    )
    assert (prepared.experiment_dir / "frozen/gates/input_gate.py").read_bytes() == (
        materials.artifact_bytes[RUNNER.INPUT_GATE_RELATIVE_PATH]
    )
    assert all("HOSTILE_" not in bundle for bundle in prepared.stage_bundles.values())
    RUNNER._load_experiment_contracts(prepared.experiment_dir)
    RUNNER._load_experiment_input_gate(prepared.experiment_dir)
    assert RUNNER._dry_run_summary(prepared)["model_calls"] == 0
    assert not marker.exists()
    assert model_calls == []


@pytest.mark.parametrize(
    "artifact_kind",
    ["contracts", "input_gate", "v1_skill", "v2_reference_bundle", "v1_schema"],
)
def test_frozen_runtime_material_tamper_fails_before_module_or_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_kind: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    source_id = next(iter(prepared.sources))
    relative_by_kind = {
        "contracts": "frozen/gates/contracts.py",
        "input_gate": "frozen/gates/input_gate.py",
        "v1_skill": "frozen/runtime/v1-skill.md",
        "v2_reference_bundle": "frozen/runtime/v2-combined-discovery-bundle.md",
        "v1_schema": f"frozen/schemas/{source_id}/v1.json",
    }
    target = prepared.experiment_dir / relative_by_kind[artifact_kind]
    marker = tmp_path / f"{artifact_kind}-executed"
    if artifact_kind in {"contracts", "input_gate"}:
        hostile_suffix = (
            f"\nopen({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n"
        ).encode()
    else:
        hostile_suffix = b"\nHOSTILE_RUNTIME_SWAP\n"
    target.write_bytes(target.read_bytes() + hostile_suffix)
    model_calls = 0

    def forbidden_model(**_: Any):
        nonlocal model_calls
        model_calls += 1
        raise AssertionError("untrusted frozen material must fail before a model call")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_model)
    with pytest.raises(RuntimeError, match=r"digest|receipt|artifact"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert model_calls == 0
    assert not marker.exists()


def test_expected_call_dependencies_use_one_source_input_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    pipeline_contract = RUNNER._expected_pipeline_contract(prepared, pipeline_id, identity)
    source_id = identity["source_id"]
    relative = f"frozen/inputs/{source_id}.json"
    input_path = prepared.experiment_dir / relative
    original_bytes = input_path.read_bytes()
    staged_value = json.loads(original_bytes)
    staged_value["source"]["filename"] = "STAGED-SWAP-UNTRUSTED.mp4"
    staged_bytes = RUNNER._pretty_json_bytes(staged_value)
    real_verified = RUNNER._verified_indexed_experiment_bytes
    staged = False

    def verify_then_swap(
        experiment_dir: Path,
        manifest: dict[str, Any],
        relative_name: str,
        label: str,
        *,
        expected_sha256: str,
        expected_size_bytes: int | None = None,
    ) -> bytes:
        nonlocal staged
        content = real_verified(
            experiment_dir,
            manifest,
            relative_name,
            label,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size_bytes,
        )
        if relative_name == relative and not staged:
            input_path.write_bytes(staged_bytes)
            staged = True
        return content

    monkeypatch.setattr(RUNNER, "_verified_indexed_experiment_bytes", verify_then_swap)
    model_calls = 0

    def forbidden_model(**_: Any):
        nonlocal model_calls
        model_calls += 1
        raise AssertionError("dependency reconstruction must not invoke a model")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_model)
    schema_relative, schema_sha, dependencies, prompt_sha, prompt = (
        RUNNER._expected_call_dependencies(
            prepared.experiment_dir, pipeline_contract, "v1-generation"
        )
    )
    assert staged is True
    assert input_path.read_bytes() == staged_bytes
    assert _payload(prompt) == prepared.sources[source_id]
    assert "STAGED-SWAP-UNTRUSTED.mp4" not in prompt
    assert dependencies["input"] == RUNNER._sha256_bytes(original_bytes)
    assert prompt_sha == RUNNER._sha256_bytes(prompt.encode())
    assert schema_relative.endswith("/v1.json")
    assert (
        schema_sha
        == prepared.manifest["immutable_contract"]["sources"][
            list(prepared.sources).index(source_id)
        ]["schema_sha256"]["v1"]
    )
    assert model_calls == 0


def test_attempt_snapshot_drives_repair_from_captured_bytes_after_staged_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    base = _mock_invoke_factory([])
    invocations = 0

    def fail_then_interrupt(*, label: str, prompt: str, schema_path: Path):
        nonlocal invocations
        invocations += 1
        if invocations == 2:
            raise KeyboardInterrupt
        _, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        return {}, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", fail_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    attempt_dir = (
        prepared.experiment_dir
        / "calls"
        / RUNNER._call_id(pipeline_id, "v1-generation")
        / "attempts/001"
    )
    original_failure = json.loads((attempt_dir / "failure.json").read_text(encoding="utf-8"))
    original_raw = json.loads((attempt_dir / "result.raw.json").read_text(encoding="utf-8"))
    real_receipt = RUNNER._attempt_receipt

    def verify_then_swap(directory: Path, attempt_number: int):
        receipt = real_receipt(directory, attempt_number)
        (directory / "failure.json").write_bytes(
            RUNNER._pretty_json_bytes(
                {
                    **original_failure,
                    "error": "STAGED_FAILURE_MUST_NOT_STEER_REPAIR",
                }
            )
        )
        (directory / "result.raw.json").write_bytes(
            RUNNER._pretty_json_bytes({"staged": "untrusted"})
        )
        return receipt

    monkeypatch.setattr(RUNNER, "_attempt_receipt", verify_then_swap)
    model_calls = 0

    def forbidden_model(**_: Any):
        nonlocal model_calls
        model_calls += 1
        raise AssertionError("attempt snapshot inspection must not invoke a model")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_model)
    snapshot = RUNNER._verified_attempt_snapshot(attempt_dir, 1)
    repair_prompt = RUNNER._repair_prompt(
        "BASE", snapshot.get("result.raw.json"), snapshot["failure.json"]["error"]
    )
    assert snapshot["result.raw.json"] == original_raw
    assert snapshot["failure.json"] == original_failure
    assert "STAGED_FAILURE_MUST_NOT_STEER_REPAIR" not in repair_prompt
    assert model_calls == 0


def test_verified_pipeline_payload_survives_post_reconstruction_file_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v1")
    model_calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(model_calls))
    RUNNER._run_v1_pipeline(prepared, pipeline_id, identity)
    pipeline_dir = prepared.experiment_dir / "pipelines" / pipeline_id
    expected_contract = json.loads(
        (pipeline_dir / "pipeline-contract.json").read_text(encoding="utf-8")
    )
    original_result = json.loads((pipeline_dir / "result.json").read_text(encoding="utf-8"))
    real_reconstruct = RUNNER._reconstruct_pipeline
    staged_result = {"attacker": "post-reconstruction-swap"}

    def reconstruct_then_swap(directory: Path, contract: dict[str, Any]):
        reconstructed = real_reconstruct(directory, contract)
        (directory / "result.json").write_bytes(RUNNER._pretty_json_bytes(staged_result))
        return reconstructed

    monkeypatch.setattr(RUNNER, "_reconstruct_pipeline", reconstruct_then_swap)
    calls_before = len(model_calls)
    payload = RUNNER._verified_pipeline_payload(pipeline_dir, expected_contract)
    assert payload is not None
    assert payload["result"] == original_result
    assert payload["artifacts"]["result.json"] == original_result
    assert payload["call_ids"] == [RUNNER._call_id(pipeline_id, "v1-generation")]
    assert payload["call_receipts"]
    assert RUNNER._is_sha256(payload["pipeline_completion_sha256"])
    assert json.loads((pipeline_dir / "result.json").read_text()) == staged_result
    assert len(model_calls) == calls_before


def test_combined_capacity_fails_before_any_model_or_experiment_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_calls: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(model_calls))
    monkeypatch.setattr(
        RUNNER,
        "_combined_discovery_payload",
        lambda evidence: {
            "candidate_count": len(evidence["candidates"]),
            "oversize": "x" * (128 * 1024),
        },
    )
    output_root = tmp_path / "capacity-experiments"
    with pytest.raises(ValueError, match="exceeds the frozen capacity"):
        RUNNER._prepare_experiment(output_root)
    assert model_calls == []
    assert not output_root.exists()


def test_one_pipeline_repair_total_and_all_attempt_costs_are_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    observed: list[str] = []
    base = _mock_invoke_factory(observed)
    stage_counts = {"combined-discovery.json": 0, "selected-copy.json": 0}

    def fail_once_per_v2_stage(*, label: str, prompt: str, schema_path: Path):
        raw, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        if schema_path.name in stage_counts:
            stage_counts[schema_path.name] += 1
            if stage_counts[schema_path.name] == 1:
                raw = {}
        return raw, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", fail_once_per_v2_stage)
    with pytest.raises(RuntimeError, match="pipeline repair budget exhausted"):
        RUNNER._run_experiment(prepared, sentinel=True)
    assert stage_counts == {"combined-discovery.json": 2, "selected-copy.json": 1}

    v2_identity = next(
        identity
        for identity in prepared.private_map["pipeline_id_to_identity"].values()
        if identity["skill_version"] == "v2"
    )
    v2_pipeline_id = next(
        pipeline_id
        for pipeline_id, identity in prepared.private_map["pipeline_id_to_identity"].items()
        if identity is v2_identity
    )
    combined_call_id = RUNNER._call_id(v2_pipeline_id, "v2-combined-discovery")
    combined_dir = prepared.experiment_dir / "calls" / combined_call_id
    completion = json.loads((combined_dir / "complete.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in completion["attempt_receipts"]] == [
        "failed",
        "validated",
    ]
    assert all(item["model_attempt_consumed"] for item in completion["attempt_receipts"])
    assert all(item["usage_status"] == "reported" for item in completion["attempt_receipts"])

    selected_call_id = RUNNER._call_id(v2_pipeline_id, "v2-selected-copy")
    selected_dir = prepared.experiment_dir / "calls" / selected_call_id
    selected_terminal = json.loads((selected_dir / "terminal.json").read_text(encoding="utf-8"))
    assert selected_terminal["status"] == "exhausted"
    assert selected_terminal["failure_category"] == "pipeline_repair_budget_exhausted"
    assert selected_terminal["terminal_attempt"] == 1
    assert selected_terminal["total_model_attempt_count"] == 1
    calls_before_resume = len(observed)
    with pytest.raises(RuntimeError, match="pipeline repair budget exhausted"):
        RUNNER._run_v2_pipeline(prepared, v2_pipeline_id, v2_identity)
    assert len(observed) == calls_before_resume

    failed_metadata = combined_dir / "attempts/001/call-metadata.json"
    failed_metadata.write_bytes(failed_metadata.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="attempt artifact drift"):
        RUNNER._verify_call_evidence(combined_dir)


def test_pipeline_budget_terminal_requires_combined_discovery_attempt_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v2")
    calls: list[str] = []
    base = _mock_invoke_factory(calls)
    selected_attempts = 0

    def selected_repair(*, label: str, prompt: str, schema_path: Path):
        nonlocal selected_attempts
        raw, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        if schema_path.name == "selected-copy.json":
            selected_attempts += 1
            if selected_attempts == 1:
                raw = {}
        return raw, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", selected_repair)
    RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    combined_dir = (
        prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v2-combined-discovery")
    )
    selected_dir = (
        prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v2-selected-copy")
    )
    combined_completion_path = combined_dir / "complete.json"
    combined_completion_bytes = combined_completion_path.read_bytes()
    assert json.loads(combined_completion_bytes)["successful_attempt"] == 1

    (selected_dir / "complete.json").unlink()
    for relative in (
        "result.raw.json",
        "result.json",
        "validation.json",
        "call-metadata.json",
        "events.jsonl",
    ):
        (selected_dir / relative).unlink()
    shutil.rmtree(selected_dir / "attempts/002")
    selected_contract = json.loads(
        (selected_dir / "call-contract.json").read_text(encoding="utf-8")
    )

    real_verify = RUNNER._verify_call_evidence
    real_snapshot = RUNNER._verified_call_snapshot
    monkeypatch.setattr(RUNNER, "_verify_call_evidence", lambda _: "forging-test-only")

    def forged_snapshot(directory: Path):
        if directory == combined_dir:
            return {
                "result.json": json.loads((directory / "result.json").read_text(encoding="utf-8"))
            }
        return real_snapshot(directory)

    monkeypatch.setattr(RUNNER, "_verified_call_snapshot", forged_snapshot)
    forged_combined = json.loads(combined_completion_bytes)
    forged_combined["successful_attempt"] = 2
    combined_completion_path.write_bytes(RUNNER._pretty_json_bytes(forged_combined))
    forged_terminal = RUNNER._terminal_call_receipt(
        call_dir=selected_dir,
        call_contract=selected_contract,
        terminal_attempt=1,
        status="exhausted",
        failure_category="pipeline_repair_budget_exhausted",
    )
    combined_completion_path.write_bytes(combined_completion_bytes)
    monkeypatch.setattr(RUNNER, "_verify_call_evidence", real_verify)
    monkeypatch.setattr(RUNNER, "_verified_call_snapshot", real_snapshot)
    (selected_dir / "terminal.json").write_bytes(RUNNER._pretty_json_bytes(forged_terminal))
    (prepared.experiment_dir / "pipelines" / pipeline_id / "complete.json").unlink()

    calls_before_resume = len(calls)
    with pytest.raises(RuntimeError, match="lacks a consumed combined-discovery repair"):
        RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    assert len(calls) == calls_before_resume


def test_completed_pipeline_rejects_two_repaired_stages_before_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_repair_budget = RUNNER.RepairBudget
    monkeypatch.setattr(RUNNER, "MAX_PIPELINE_REPAIRS", 2)
    monkeypatch.setattr(
        RUNNER,
        "RepairBudget",
        lambda: original_repair_budget(maximum_repairs=2),
    )
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v2")
    calls: list[str] = []
    base = _mock_invoke_factory(calls)
    stage_counts = {"combined-discovery.json": 0, "selected-copy.json": 0}

    def repair_both(*, label: str, prompt: str, schema_path: Path):
        raw, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        if schema_path.name in stage_counts:
            stage_counts[schema_path.name] += 1
            if stage_counts[schema_path.name] == 1:
                raw = {}
        return raw, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", repair_both)
    summary = RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    assert summary["repair_budget"]["repairs_used"] == 2
    assert stage_counts == {"combined-discovery.json": 2, "selected-copy.json": 2}

    monkeypatch.setattr(RUNNER, "MAX_PIPELINE_REPAIRS", 1)
    monkeypatch.setattr(RUNNER, "RepairBudget", original_repair_budget)
    resumed_calls = 0

    def forbidden_invoke(**_: Any):
        nonlocal resumed_calls
        resumed_calls += 1
        raise AssertionError("cross-stage repair drift must fail before model")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_invoke)
    with pytest.raises(RuntimeError, match="repair budget drift"):
        RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    assert resumed_calls == 0


@pytest.mark.parametrize("borrowed_field", ["evidence_quote", "source_sentence"])
def test_selected_copy_cross_candidate_evidence_is_terminal_without_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    borrowed_field: str,
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v2")
    calls: list[str] = []
    base = _mock_invoke_factory(calls)

    def borrow(*, label: str, prompt: str, schema_path: Path):
        raw, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        if schema_path.name == "selected-copy.json":
            payload = _payload(prompt)
            selected = payload["selected_candidates_in_required_order"]
            assert len(selected) >= 2
            donor_text = selected[1]["candidate"]["text"][:40]
            raw["copies"][0][borrowed_field] = donor_text
        return raw, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", borrow)
    with pytest.raises(RuntimeError, match="permanent identity violation"):
        RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    assert len(calls) == 2
    selected_dir = (
        prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v2-selected-copy")
    )
    terminal = json.loads((selected_dir / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["failure_category"] == "cross_candidate_evidence"
    assert terminal["terminal_attempt"] == 1

    with pytest.raises(RuntimeError, match="persisted terminal model failure"):
        RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    assert len(calls) == 2


def test_short_invalid_own_evidence_remains_repairable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    pipeline_id, identity = _first_identity(prepared, "v2")
    calls: list[str] = []
    base = _mock_invoke_factory(calls)
    selected_attempts = 0

    def short_then_valid(*, label: str, prompt: str, schema_path: Path):
        nonlocal selected_attempts
        raw, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        if schema_path.name == "selected-copy.json":
            selected_attempts += 1
            if selected_attempts == 1:
                raw["copies"][0]["evidence_quote"] = "无效短句"
                raw["copies"][0]["source_sentence"] = "无效短句"
        return raw, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", short_then_valid)
    summary = RUNNER._run_v2_pipeline(prepared, pipeline_id, identity)
    assert summary["total_model_attempt_count"] == 3
    assert selected_attempts == 2
    selected_dir = (
        prepared.experiment_dir / "calls" / RUNNER._call_id(pipeline_id, "v2-selected-copy")
    )
    assert not (selected_dir / "terminal.json").exists()
    completion = json.loads((selected_dir / "complete.json").read_text(encoding="utf-8"))
    assert [item["status"] for item in completion["attempt_receipts"]] == [
        "failed",
        "validated",
    ]


def test_unknown_candidate_id_is_terminal_and_never_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    v2_pipeline_id, v2_identity = next(
        (pipeline_id, identity)
        for pipeline_id, identity in prepared.private_map["pipeline_id_to_identity"].items()
        if identity["skill_version"] == "v2"
    )
    calls: list[str] = []
    base = _mock_invoke_factory(calls)

    def unknown(*, label: str, prompt: str, schema_path: Path):
        raw, metadata, events = base(label=label, prompt=prompt, schema_path=schema_path)
        if schema_path.name == "combined-discovery.json":
            raw["assessments"][0]["candidate_id"] = "candidate_deadbeefdeadbeef"
        return raw, metadata, events

    monkeypatch.setattr(RUNNER, "_invoke_codex", unknown)
    with pytest.raises(RuntimeError, match="permanent identity violation"):
        RUNNER._run_v2_pipeline(prepared, v2_pipeline_id, v2_identity)
    assert len(calls) == 1
    call_dir = (
        prepared.experiment_dir / "calls" / RUNNER._call_id(v2_pipeline_id, "v2-combined-discovery")
    )
    attempt_contract = json.loads(
        (call_dir / "attempts/001/attempt-contract.json").read_text(encoding="utf-8")
    )
    assert attempt_contract["status"] == "terminal_failed"
    terminal = json.loads((call_dir / "terminal.json").read_text(encoding="utf-8"))
    assert terminal["failure_category"] == "model_output_unknown_candidate_id"
    with pytest.raises(RuntimeError, match="persisted terminal model failure"):
        RUNNER._run_v2_pipeline(prepared, v2_pipeline_id, v2_identity)
    assert len(calls) == 1


def test_preflight_only_writes_zero_model_receipt_and_never_starts_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")

    def forbidden_generator(**_: Any):
        raise AssertionError("preflight-only must not invoke a generator")

    monkeypatch.setattr(RUNNER, "_invoke_codex", forbidden_generator)
    result = RUNNER._preflight_only_summary(prepared)
    assert result["model_calls"] == 0
    assert result["model_started"] is False
    assert result["preflight_receipt"]["model_attempt_consumed"] is False
    assert not (prepared.experiment_dir / "calls").exists()
    receipt = prepared.experiment_dir / "infrastructure/preflight/checks/001/receipt.json"
    assert json.loads(receipt.read_text(encoding="utf-8"))["model_started"] is False
