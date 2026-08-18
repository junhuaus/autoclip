from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("run_judges.py")


@pytest.fixture(scope="module")
def harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("liveclip_run_judges_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: Any) -> bytes:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _sha(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _generator_call(experiment_dir: Path, call_id: str, pipeline_id: str) -> dict[str, str]:
    call_dir = experiment_dir / "calls" / call_id
    contract = _write_json(
        call_dir / "call-contract.json",
        {
            "schema_version": "1",
            "experiment_id": "exp_test_anonymous",
            "experiment_contract_sha256": "c" * 64,
            "call_id": call_id,
            "pipeline_id": pipeline_id,
            "stage": "test-stage",
        },
    )
    attempt_contract = _write_json(
        call_dir / "attempts" / "001" / "attempt-contract.json",
        {"schema_version": "1", "call_id": call_id, "attempt": 1},
    )
    artifacts = {
        "result.raw.json": _write_json(call_dir / "result.raw.json", {"ok": True}),
        "result.json": _write_json(call_dir / "result.json", {"ok": True}),
        "validation.json": _write_json(call_dir / "validation.json", {"status": "succeeded"}),
        "call-metadata.json": _write_json(
            call_dir / "call-metadata.json", {"model": "generator-secret"}
        ),
        "events.jsonl": b'{"type":"turn.completed"}\n',
    }
    (call_dir / "events.jsonl").write_bytes(artifacts["events.jsonl"])
    completion = {
        "schema_version": "1",
        "call_id": call_id,
        "call_contract_sha256": _sha(contract),
        "successful_attempt": 1,
        "successful_attempt_contract_sha256": _sha(attempt_contract),
        "artifact_sha256": {name: _sha(payload) for name, payload in artifacts.items()},
        "infrastructure_failure_receipts": [],
    }
    completion_bytes = _write_json(call_dir / "complete.json", completion)
    return {
        "call_id": call_id,
        "call_completion_sha256": _sha(completion_bytes),
    }


def _generator_pipeline(
    experiment_dir: Path,
    pipeline_id: str,
    source_id: str,
    candidate_id: str,
    variant: int,
    source_input_sha256: str,
) -> None:
    pipeline_dir = experiment_dir / "pipelines" / pipeline_id
    contract = {
        "schema_version": "1",
        "pipeline_id": pipeline_id,
        "source_id": source_id,
        "arm_id": f"arm_SECRET_{variant % 2}",
        "skill_version": "v2" if variant % 2 else "v1",
        "model": "gpt-generator-secret",
        "input_sha256": source_input_sha256,
        "experiment_contract_sha256": "c" * 64,
        "fresh_generation": True,
    }
    contract_bytes = _write_json(pipeline_dir / "pipeline-contract.json", contract)
    highlight = {
        "candidate_id": candidate_id,
        "topic": "气息与高音",
        "title": f"候选标题 {variant}",
        "hook": "为什么高音总是卡住?",
        "highlight_sentence": "高音稳定来自正确的气息通道。",
        "edited_sentence": "高音稳定来自正确的气息通道。",
        "script_description": "解释常见问题并给出可执行练习。",
        "risk_flags": [],
        "score": 0.93751,
        "quality_score_x100": 93751,
        "scores": {"self_score": "SELF_SCORE_SECRET"},
        "evidence_receipt": {"generator": "GENERATOR_RECEIPT_SECRET"},
    }
    result = {
        "schema_version": "generator-result",
        "highlights": [highlight],
        "selection_summary": {
            "model": "gpt-generator-secret",
            "effort": "medium",
            "tokens": 999999,
            "latency": 123.456,
        },
    }
    result_bytes = _write_json(pipeline_dir / "result.json", result)
    validation_bytes = _write_json(pipeline_dir / "validation.json", {"status": "succeeded"})
    summary_bytes = _write_json(
        pipeline_dir / "summary.json", {"pipeline_id": pipeline_id, "selected_count": 1}
    )
    receipt = _generator_call(experiment_dir, f"call_{pipeline_id}", pipeline_id)
    completion = {
        "schema_version": "1",
        "pipeline_id": pipeline_id,
        "pipeline_contract_sha256": _sha(contract_bytes),
        "artifact_sha256": {
            "result.json": _sha(result_bytes),
            "validation.json": _sha(validation_bytes),
            "summary.json": _sha(summary_bytes),
        },
        "call_receipts": [receipt],
    }
    _write_json(pipeline_dir / "complete.json", completion)


def _make_experiment(tmp_path: Path) -> tuple[Path, list[str]]:
    experiment_dir = tmp_path / "exp_test_anonymous"
    sources = ["src_alpha", "src_beta", "src_gamma"]
    schedule: list[dict[str, Any]] = []
    pipeline_ids: list[str] = []
    source_payloads: dict[str, bytes] = {}
    pair_sequence = 0
    variant = 0
    for source_index, source_id in enumerate(sources, start=1):
        candidates = [
            {
                "candidate_id": f"candidate_{source_index}_a",
                "source_start_ms": 10_000,
                "source_end_ms": 55_000,
                "text": "先解释问题, 再说明气息路径和练习方法。",
                "context_before": "观众询问高音为什么不稳定。",
                "context_after": "老师继续演示正确与错误的区别。",
            },
            {
                "candidate_id": f"candidate_{source_index}_b",
                "source_start_ms": 80_000,
                "source_end_ms": 135_000,
                "text": "舌头放松和口腔空间会影响高音通道。",
                "context_before": "观众问舌头应该放在哪里。",
                "context_after": "老师给出放松检测方法。",
            },
        ]
        source_payload = {
            "source": {
                "filename": f"source-{source_index}.ts",
                "duration_ms": 180_000,
                "source_sha256": f"{source_index}" * 64,
                "candidate_count": len(candidates),
            },
            "candidates": candidates,
        }
        source_payloads[source_id] = _write_json(
            experiment_dir / "frozen" / "inputs" / f"{source_id}.json",
            source_payload,
        )
        for repeat in (1, 2):
            pair_sequence += 1
            pair_pipelines: list[dict[str, Any]] = []
            for arm_index in (1, 2):
                variant += 1
                pipeline_id = f"pipeline_SECRET_{source_index}_{repeat}_{arm_index}"
                pipeline_ids.append(pipeline_id)
                pair_pipelines.append(
                    {
                        "within_pair_sequence": arm_index,
                        "pipeline_id": pipeline_id,
                        "arm_id": f"arm_SECRET_{arm_index}",
                    }
                )
                candidate_id = candidates[(variant + repeat) % 2]["candidate_id"]
                _generator_pipeline(
                    experiment_dir,
                    pipeline_id,
                    source_id,
                    candidate_id,
                    variant,
                    _sha(source_payloads[source_id]),
                )
            schedule.append(
                {
                    "pair_sequence": pair_sequence,
                    "pair_id": f"pair_{source_index}_{repeat}",
                    "source_id": source_id,
                    "repeat": repeat,
                    "candidate_order": "original",
                    "pipelines": pair_pipelines,
                }
            )
    public_plan = {
        "schema_version": "1",
        "pipeline_count": 12,
        "unique_source_count": 3,
        "repeats_per_source": 2,
        "model": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
        "schedule": schedule,
    }
    public_bytes = _write_json(experiment_dir / "frozen" / "public-plan.json", public_plan)
    artifact_index: dict[str, dict[str, Any]] = {
        "frozen/public-plan.json": {
            "sha256": _sha(public_bytes),
            "size_bytes": len(public_bytes),
        }
    }
    for source_id, payload in source_payloads.items():
        artifact_index[f"frozen/inputs/{source_id}.json"] = {
            "sha256": _sha(payload),
            "size_bytes": len(payload),
        }
    _write_json(
        experiment_dir / "experiment-manifest.json",
        {
            "schema_version": "1",
            "experiment_id": "exp_test_anonymous",
            "contract_sha256": "c" * 64,
            "immutable_contract": {"test": True},
            "artifact_index": artifact_index,
        },
    )
    return experiment_dir, pipeline_ids


def _input_from_prompt(prompt: str) -> dict[str, Any]:
    start = prompt.index("<untrusted_judge_input")
    start = prompt.index(">", start) + 1
    end = prompt.index("</untrusted_judge_input>", start)
    return json.loads(prompt[start:end].strip())


def _valid_answer(payload: dict[str, Any]) -> dict[str, Any]:
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for system in payload["anonymous_systems"]:
        for highlight in system["highlights"]:
            by_candidate.setdefault(highlight["candidate_id"], []).append(
                {
                    "anonymous_system_id": system["anonymous_system_id"],
                    "highlight_id": highlight["highlight_id"],
                    "candidate_id": highlight["candidate_id"],
                    "event_match_x4": 4,
                    "editorial_value_x4": 3,
                    "hook_x4": 3,
                    "completeness_x4": 4,
                    "evidence_fidelity_x4": 4,
                    "usability_x4": 3,
                    "assessment": "内容完整且能够由候选证据支持。",
                }
            )
    clusters = [
        {
            "cluster_id": f"topic_{index:03d}",
            "canonical_topic": f"自由发现话题 {index}",
            "alignment_confidence": "high",
            "members": members,
            "topic_assessment": "这些高光讨论同一件事情, 可以直接横向比较。",
        }
        for index, members in enumerate(by_candidate.values(), start=1)
    ]
    system_ids = [item["anonymous_system_id"] for item in payload["anonymous_systems"]]
    evaluations = [
        {
            "anonymous_system_id": system_id,
            "discovery_x4": 3,
            "coverage_x4": 4,
            "precision_x4": 3,
            "stability_x4": 3,
            "editorial_readiness_x4": 3,
            "strengths": ["选题清楚"],
            "weaknesses": ["仍需人工复核"],
        }
        for system_id in system_ids
    ]
    return {
        "schema_version": "1",
        "topic_clusters": clusters,
        "system_evaluations": evaluations,
        "preferred_system_ids": [system_ids[0]],
        "overall_verdict": "四份组合均可比较, 首选组合的内容覆盖更集中。",
        "limitations": ["本次评审只使用转写证据, 没有查看视频画面。"],
    }


def _mock_invoke(
    counter: list[int],
    event_mutator: Callable[[list[dict[str, Any]]], None] | None = None,
) -> Callable[..., tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    def invoke(
        label: str,
        prompt: str,
        schema_path: Path,
        config: dict[str, str],
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        del schema_path
        counter.append(1)
        answer = _valid_answer(_input_from_prompt(prompt))
        events = [
            {"type": "thread.started", "thread_id": f"mock-{len(counter)}"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "agent_message"}},
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 10,
                    "output_tokens": 50,
                },
            },
        ]
        if event_mutator is not None:
            event_mutator(events)
        metadata = {
            "schema_version": "1",
            "label": label,
            "model": config["model"],
            "reasoning_effort": config["reasoning_effort"],
        }
        return json.dumps(answer, ensure_ascii=False), metadata, events

    return invoke


def _passing_preflight(
    counter: list[int] | None = None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        del cwd, env
        if counter is not None:
            counter.append(1)
        assert "app-server" in command
        assert "skills" not in command
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _pre_model_failure_invoke(
    harness: ModuleType, counter: list[int]
) -> Callable[..., tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    def invoke(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        del args, kwargs
        counter.append(1)
        raise harness.CodexProcessFailure(
            "Error: Unknown feature flag: stale_flag",
            category="infrastructure_configuration",
            model_started=False,
            returncode=1,
            stderr="Error: Unknown feature flag: stale_flag",
        )

    return invoke


def test_blind_inputs_strip_all_generator_identity_and_bind_after_filter(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, pipeline_ids = _make_experiment(tmp_path)
    prepared = harness.prepare_judge_run(experiment_dir)

    for call in prepared.calls.values():
        serialized = harness._canonical_bytes(call.input_payload).decode()
        assert call.input_sha256 == _sha(serialized.encode())
        assert all(pipeline_id not in serialized for pipeline_id in pipeline_ids)
        for forbidden in (
            "arm_SECRET",
            "gpt-5.6-sol",
            "gpt-generator-secret",
            "SELF_SCORE_SECRET",
            "GENERATOR_RECEIPT_SECRET",
            "reasoning_effort",
            "quality_score_x100",
            '"score"',
            '"tokens"',
            '"latency"',
        ):
            assert forbidden not in serialized
        assert call.binding_sha256 == _sha(harness._canonical_bytes(call.binding))
        assert "anonymous_system_to_pipeline" not in serialized
    with pytest.raises(harness.IntegrityError, match="identity metadata"):
        harness._assert_no_generator_identity_markers(
            [{"title": "generated by gpt-generator-secret"}]
        )


def test_old_judge_run_is_immutable_and_runner_change_uses_new_id(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    old_run = experiment_dir / "judge-runs" / "judge_da09efc4a848e5c8fc005b50"
    _write_json(old_run / "judge-run-manifest.json", {"runner_sha256": "old"})
    (old_run / "sources" / "old" / "failure.txt").parent.mkdir(parents=True)
    (old_run / "sources" / "old" / "failure.txt").write_text(
        "Unknown feature flag: skills\n", encoding="utf-8"
    )
    before = _tree_hashes(old_run)

    prepared = harness.prepare_judge_run(experiment_dir)

    assert prepared.run_dir.name != old_run.name
    assert prepared.run_dir.is_dir()
    assert _tree_hashes(old_run) == before


def test_unknown_feature_preflight_is_zero_model_then_resumes_at_attempt_one(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    model_counter: list[int] = []
    preflight_counter: list[int] = []

    def unknown_feature(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env
        preflight_counter.append(1)
        assert "skills" not in command
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Error: Unknown feature flag: stale_flag\n",
        )

    with pytest.raises(
        harness.CodexInfrastructureUnavailable,
        match="infrastructure_configuration",
    ):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(model_counter),
            preflight=unknown_feature,
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    receipt = json.loads(
        (
            prepared.run_dir / "infrastructure" / "preflight" / "checks" / "001" / "receipt.json"
        ).read_text(encoding="utf-8")
    )
    assert receipt["category"] == "infrastructure_configuration"
    assert receipt["model_started"] is False
    assert receipt["model_attempt_consumed"] is False
    assert model_counter == []
    assert not (prepared.run_dir / "sources").exists()

    harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=_mock_invoke(model_counter),
        preflight=_passing_preflight(preflight_counter),
    )
    assert model_counter == [1, 1]
    assert preflight_counter == [1, 1]
    for judge_id in harness.JUDGES:
        call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / judge_id
        assert (call_dir / "attempts" / "attempt_01").is_dir()
        assert not (call_dir / "attempts" / "attempt_02").exists()

    def preflight_must_resume(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"passed preflight must resume: {args!r} {kwargs!r}")

    harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=_mock_invoke(model_counter),
        preflight=preflight_must_resume,
    )
    assert model_counter == [1, 1]


def test_pre_model_call_failure_has_independent_receipt_and_resumes_attempt_one(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    process_counter: list[int] = []
    with pytest.raises(harness.CodexInfrastructureUnavailable, match="before a model turn"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_pre_model_failure_invoke(harness, process_counter),
            preflight=_passing_preflight(),
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    receipt_path = call_dir / "infrastructure-failures" / "001" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["model_attempt_consumed"] is False
    assert not (call_dir / "attempts").exists()

    model_counter: list[int] = []
    harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=_mock_invoke(model_counter),
        preflight=_passing_preflight(),
    )
    assert (call_dir / "attempts" / "attempt_01").is_dir()
    assert not (call_dir / "attempts" / "attempt_02").exists()
    completion = json.loads((call_dir / "complete.json").read_text(encoding="utf-8"))
    assert completion["infrastructure_failure_receipts"] == [
        {
            "relative_path": "infrastructure-failures/001/receipt.json",
            "sha256": _sha(receipt_path.read_bytes()),
        }
    ]
    assert process_counter == [1]


def test_pre_model_call_failure_budget_is_bounded_without_attempts(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    process_counter: list[int] = []
    invoke = _pre_model_failure_invoke(harness, process_counter)
    preflight = _passing_preflight()
    for _ in range(harness.MAX_CALL_INFRASTRUCTURE_FAILURES):
        with pytest.raises(harness.CodexInfrastructureUnavailable):
            harness.run_judges(
                experiment_dir,
                sentinel=True,
                invoke=invoke,
                preflight=preflight,
            )
    with pytest.raises(harness.CodexInfrastructureUnavailable, match="failure limit"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=invoke,
            preflight=preflight,
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    assert process_counter == [1] * harness.MAX_CALL_INFRASTRUCTURE_FAILURES
    assert not (call_dir / "attempts").exists()
    assert sorted(path.name for path in (call_dir / "infrastructure-failures").iterdir()) == [
        "001",
        "002",
        "003",
    ]


@pytest.mark.parametrize("mutation", ["tamper", "delete", "extra"])
def test_passed_preflight_receipt_tamper_delete_or_extra_fails_closed(
    tmp_path: Path, harness: ModuleType, mutation: str
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    model_counter: list[int] = []
    prepared = harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=_mock_invoke(model_counter),
        preflight=_passing_preflight(),
    )
    receipt_path = (
        prepared.run_dir / "infrastructure" / "preflight" / "checks" / "001" / "receipt.json"
    )
    if mutation == "tamper":
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["stderr_tail"] = "tampered after readiness"
        _write_json(receipt_path, receipt)
    elif mutation == "delete":
        receipt_path.unlink()
    else:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt.update(
            {
                "check_number": 2,
                "status": "failed",
                "category": "infrastructure_configuration",
                "returncode": 1,
                "stderr_tail": "late extra receipt",
                "recorded_at": "2026-08-18T00:00:00Z",
            }
        )
        _write_json(
            prepared.run_dir / "infrastructure" / "preflight" / "checks" / "002" / "receipt.json",
            receipt,
        )
    before = len(model_counter)

    with pytest.raises(harness.IntegrityError, match="preflight"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(model_counter),
            preflight=_passing_preflight(),
        )
    assert len(model_counter) == before


def test_attempt_sequence_hole_fails_before_invocation(tmp_path: Path, harness: ModuleType) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    _write_json(
        call_dir / "attempts" / "attempt_02" / "attempt-contract.json",
        {"invalid": True},
    )
    model_counter: list[int] = []

    with pytest.raises(harness.IntegrityError, match="sequence"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(model_counter),
            preflight=_passing_preflight(),
        )
    assert model_counter == []
    assert not (call_dir / "attempts" / "attempt_01").exists()


@pytest.mark.parametrize("mutation", ["tamper", "delete", "extra"])
def test_completed_judge_binds_all_call_infrastructure_receipts(
    tmp_path: Path, harness: ModuleType, mutation: str
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    process_counter: list[int] = []
    with pytest.raises(harness.CodexInfrastructureUnavailable):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_pre_model_failure_invoke(harness, process_counter),
            preflight=_passing_preflight(),
        )
    model_counter: list[int] = []
    prepared = harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=_mock_invoke(model_counter),
        preflight=_passing_preflight(),
    )
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    receipt_path = call_dir / "infrastructure-failures" / "001" / "receipt.json"
    if mutation == "tamper":
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["stderr_tail"] = "tampered after completion"
        _write_json(receipt_path, receipt)
    elif mutation == "delete":
        receipt_path.unlink()
    else:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["failure_number"] = 2
        receipt["recorded_at"] = "2026-08-18T00:00:00Z"
        _write_json(
            call_dir / "infrastructure-failures" / "002" / "receipt.json",
            receipt,
        )
    before = len(model_counter)

    with pytest.raises(harness.IntegrityError, match="infrastructure"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(model_counter),
            preflight=_passing_preflight(),
        )
    assert len(model_counter) == before


def test_incomplete_generator_matrix_refuses_before_any_model_call(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, pipeline_ids = _make_experiment(tmp_path)
    (experiment_dir / "pipelines" / pipeline_ids[-1] / "complete.json").unlink()
    counter: list[int] = []

    with pytest.raises(harness.GeneratorMatrixIncomplete, match="no judge calls"):
        harness.run_judges(
            experiment_dir,
            invoke=_mock_invoke(counter),
            preflight=_passing_preflight(),
        )

    assert counter == []
    assert not (experiment_dir / "judge-runs").exists()


@pytest.mark.parametrize("mutation", ["tamper", "extra"])
def test_generator_preflight_rejects_tampered_or_extra_infrastructure_receipt(
    tmp_path: Path, harness: ModuleType, mutation: str
) -> None:
    experiment_dir, pipeline_ids = _make_experiment(tmp_path)
    pipeline_id = pipeline_ids[0]
    call_id = f"call_{pipeline_id}"
    call_dir = experiment_dir / "calls" / call_id
    contract_path = call_dir / "call-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    receipt_path = call_dir / "infrastructure-failures" / "001" / "receipt.json"
    receipt = {
        "schema_version": "1",
        "experiment_id": contract["experiment_id"],
        "experiment_contract_sha256": contract["experiment_contract_sha256"],
        "call_id": call_id,
        "pipeline_id": pipeline_id,
        "stage": contract["stage"],
        "failure_number": 1,
        "category": "infrastructure_permission_denied",
        "returncode": 1,
        "model_started": False,
        "model_attempt_consumed": False,
        "call_contract_sha256": _sha(contract_path.read_bytes()),
        "stdout_tail": "",
        "stderr_tail": "permission denied",
        "recorded_at": "2026-08-17T00:00:00Z",
    }
    receipt_bytes = _write_json(receipt_path, receipt)
    if mutation == "tamper":
        completion_path = call_dir / "complete.json"
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        completion["infrastructure_failure_receipts"] = [
            {
                "relative_path": "infrastructure-failures/001/receipt.json",
                "sha256": _sha(receipt_bytes),
            }
        ]
        completion_bytes = _write_json(completion_path, completion)
        pipeline_completion_path = experiment_dir / "pipelines" / pipeline_id / "complete.json"
        pipeline_completion = json.loads(pipeline_completion_path.read_text(encoding="utf-8"))
        pipeline_completion["call_receipts"][0]["call_completion_sha256"] = _sha(completion_bytes)
        _write_json(pipeline_completion_path, pipeline_completion)
        receipt["stderr_tail"] = "tampered after completion"
        _write_json(receipt_path, receipt)

    with pytest.raises(harness.GeneratorMatrixIncomplete, match="infrastructure receipt"):
        harness.prepare_judge_run(experiment_dir)


def test_partial_refusal_gets_only_one_same_tier_repair(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    counter: list[int] = []
    valid = _mock_invoke(counter)

    def refuse_once(*args: Any, **kwargs: Any) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        if not counter:
            counter.append(1)
            return (
                json.dumps({"refusal": "cannot judge"}),
                {"schema_version": "1"},
                [{"type": "turn.started"}, {"type": "turn.completed", "usage": {}}],
            )
        return valid(*args, **kwargs)

    prepared = harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=refuse_once,
        preflight=_passing_preflight(),
    )

    assert len(counter) == 3
    first_call = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    assert (first_call / "attempts" / "attempt_01" / "failure.json").is_file()
    assert (first_call / "attempts" / "attempt_02" / "result.raw.txt").is_file()


def test_membership_gate_rejects_duplicate_and_missing_highlights(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.prepare_judge_run(experiment_dir)
    call = next(iter(prepared.calls.values()))
    valid = _valid_answer(call.input_payload)

    duplicate = json.loads(json.dumps(valid))
    duplicate["topic_clusters"][0]["members"].append(duplicate["topic_clusters"][0]["members"][0])
    with pytest.raises(harness.JudgeValidationError, match="coverage gate"):
        harness._validate_judge_result(duplicate, call)

    missing = json.loads(json.dumps(valid))
    missing["topic_clusters"][0]["members"].pop()
    if not missing["topic_clusters"][0]["members"]:
        missing["topic_clusters"].pop(0)
    with pytest.raises(harness.JudgeValidationError, match="coverage gate"):
        harness._validate_judge_result(missing, call)


def test_sentinel_resume_then_full_run_and_receipt_tamper_detection(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    counter: list[int] = []
    invoke = _mock_invoke(counter)

    preflight_counter: list[int] = []
    preflight = _passing_preflight(preflight_counter)
    prepared = harness.run_judges(experiment_dir, sentinel=True, invoke=invoke, preflight=preflight)
    assert len(counter) == 2
    harness.run_judges(experiment_dir, sentinel=True, invoke=invoke, preflight=preflight)
    assert len(counter) == 2
    harness.run_judges(experiment_dir, invoke=invoke, preflight=preflight)
    assert len(counter) == 6
    assert len(preflight_counter) == 1

    first_call = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    events_path = first_call / "events.jsonl"
    events_path.write_bytes(events_path.read_bytes() + b"\n")
    with pytest.raises(harness.IntegrityError, match="hash mismatch"):
        harness.run_judges(experiment_dir, sentinel=True, invoke=invoke, preflight=preflight)
    assert len(counter) == 6


def test_unsafe_tool_event_hard_fails_without_repair(tmp_path: Path, harness: ModuleType) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    counter: list[int] = []

    def add_unsafe_event(events: list[dict[str, Any]]) -> None:
        events.insert(
            2,
            {
                "type": "item.completed",
                "item": {"type": "command_execution", "command": "forbidden"},
            },
        )

    with pytest.raises(harness.UnsafeToolEvent):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(counter, add_unsafe_event),
            preflight=_passing_preflight(),
        )

    assert len(counter) == 1
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    assert (call_dir / "attempts" / "attempt_01" / "events.jsonl").is_file()
    assert (call_dir / "attempts" / "attempt_01" / "call-metadata.json").is_file()
    assert not (call_dir / "attempts" / "attempt_02").exists()
    with pytest.raises(harness.UnsafeToolEvent):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(counter, add_unsafe_event),
            preflight=_passing_preflight(),
        )
    assert len(counter) == 1


def test_real_invoke_unsafe_event_is_persisted_and_resume_never_invokes(
    tmp_path: Path, harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    process_counter: list[int] = []

    def unsafe_process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        process_counter.append(1)
        stdout = "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "unsafe-thread"}),
                json.dumps({"type": "turn.started"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "command_execution", "command": "forbidden"},
                    }
                ),
            )
        )
        return subprocess.CompletedProcess(args[0], 0, stdout=stdout, stderr="")

    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(harness.subprocess, "run", unsafe_process)
    with pytest.raises(harness.UnsafeToolEvent):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=harness._invoke_codex,
            preflight=_passing_preflight(),
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    events_path = call_dir / "attempts" / "attempt_01" / "events.jsonl"
    assert "command_execution" in events_path.read_text(encoding="utf-8")
    assert (call_dir / "attempts" / "attempt_01" / "call-metadata.json").is_file()
    assert not (call_dir / "attempts" / "attempt_02").exists()

    with pytest.raises(harness.UnsafeToolEvent):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=harness._invoke_codex,
            preflight=_passing_preflight(),
        )
    assert process_counter == [1]
    assert not (call_dir / "attempts" / "attempt_02").exists()


@pytest.mark.parametrize(
    ("stdout", "expected_started", "expected_category"),
    [
        ("", False, "infrastructure_process_timeout"),
        ('{"type":"turn.started"}\n', True, "model_process_timeout"),
    ],
)
def test_invoke_timeout_is_classified_by_turn_started(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
    expected_started: bool,
    expected_category: str,
) -> None:
    def timeout(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise subprocess.TimeoutExpired(
            cmd="codex",
            timeout=3600,
            output=stdout,
            stderr="",
        )

    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(harness.subprocess, "run", timeout)
    with pytest.raises(harness.CodexProcessFailure) as caught:
        harness._invoke_codex(
            "timeout-test",
            "prompt",
            tmp_path / "schema.json",
            harness.JUDGES["judge_01"],
        )
    assert caught.value.model_started is expected_started
    assert caught.value.category == expected_category


def test_model_output_read_failure_is_receipted_as_model_attempt(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    process_counter: list[int] = []

    def invalid_output_process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        command = args[0]
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_bytes(b"\xff")
        process_counter.append(1)
        stdout = "\n".join(
            (
                json.dumps({"type": "thread.started", "thread_id": "read-failure-thread"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": "turn.completed", "usage": {}}),
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(harness.subprocess, "run", invalid_output_process)
    with pytest.raises(harness.JudgeValidationError, match="exhausted its repair budget"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=harness._invoke_codex,
            preflight=_passing_preflight(),
        )

    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / next(iter(harness.JUDGES))
    for attempt in ("attempt_01", "attempt_02"):
        receipt = json.loads(
            (call_dir / "attempts" / attempt / "failure.json").read_text(encoding="utf-8")
        )
        assert receipt["failure_kind"] == "model_process_or_output"
        assert "model_output_read_failure" in receipt["error"]
        assert (call_dir / "attempts" / attempt / "events.jsonl").is_file()
    assert process_counter == [1, 1]
