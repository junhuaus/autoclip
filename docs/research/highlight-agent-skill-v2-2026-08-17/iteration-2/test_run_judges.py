from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("run_judges.py")


def _legacy_pipeline_reconstructor(
    pipeline_dir: Path, expected_contract: dict[str, Any]
) -> dict[str, Any]:
    """Isolate old synthetic fixtures from the production reconstruction verifier."""

    completion_bytes = (pipeline_dir / "complete.json").read_bytes()
    completion = json.loads(completion_bytes)
    summary = json.loads((pipeline_dir / "summary.json").read_text(encoding="utf-8"))
    artifacts = {
        relative: json.loads((pipeline_dir / relative).read_text(encoding="utf-8"))
        for relative in completion["artifact_sha256"]
        if relative != "summary.json"
    }
    call_ids = list(expected_contract["required_call_ids"])
    conditional = expected_contract["conditional_call_ids"]
    if expected_contract["skill_version"] == "v2" and summary["selected_count"] > 0:
        call_ids.append(conditional["nonempty_portfolio"])
    return {
        "result": artifacts["result.json"],
        "summary": summary,
        "artifacts": artifacts,
        "call_ids": sorted(call_ids),
        "call_receipts": completion["call_receipts"],
        "pipeline_completion_sha256": _sha(completion_bytes),
    }


class _SyntheticHarnessAdapter:
    """Explicitly route only legacy fixture calls through their synthetic verifier."""

    def __init__(self, module: ModuleType) -> None:
        object.__setattr__(self, "_module", module)

    def __getattr__(self, name: str) -> Any:
        module = object.__getattribute__(self, "_module")
        if name == "prepare_judge_run":
            return lambda experiment_dir: module._prepare_judge_run(
                experiment_dir, _legacy_pipeline_reconstructor
            )
        if name == "run_judges":
            return lambda experiment_dir, **kwargs: module._run_judges(
                experiment_dir,
                pipeline_reconstructor=_legacy_pipeline_reconstructor,
                **kwargs,
            )
        return getattr(module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_module"), name, value)


def _real_generator_experiment(
    tmp_path: Path,
    harness: _SyntheticHarnessAdapter,
    *,
    empty_v2: bool,
) -> tuple[Path, ModuleType]:
    """Create genuine run_iteration receipts using its established model stub."""

    support_path = Path(__file__).with_name("test_run_iteration.py")
    module_name = f"liveclip_generator_support_{_sha(str(tmp_path).encode())}_{empty_v2}"
    spec = importlib.util.spec_from_file_location(module_name, support_path)
    assert spec is not None and spec.loader is not None
    support = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = support
    spec.loader.exec_module(support)
    runner = support.RUNNER

    evaluation_path = harness.EVALUATION_CONTRACT_PATH
    runner.EVALUATION_CONTRACT_PATH = evaluation_path
    materials = runner._load_evaluation_materials()
    input_gate = runner._load_input_gate(materials)
    sources: list[dict[str, Any]] = []
    for source_spec in runner.SOURCE_SPECS:
        evidence, _ = runner._validate_frozen_source(source_spec, input_gate)
        evidence_bytes = runner._pretty_json_bytes(evidence)
        sources.append(
            {
                "source_id": source_spec.source_id,
                "source_sha256": source_spec.expected_source_sha256,
                "frozen_input_sha256": _sha(evidence_bytes),
                "candidate_count": source_spec.expected_candidate_count,
            }
        )
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    evaluation["generator"]["sources"] = sources
    _write_json(evaluation_path, evaluation)

    runner._codex_identity = lambda: {
        "path": "/test/bin/codex",
        "version": "codex-test-version",
    }
    runner._codex_preflight_command = lambda: ["codex", "test-preflight"]
    runner._run_preflight_process = lambda command, **kwargs: subprocess.CompletedProcess(
        command, 0, stdout=b"", stderr=b""
    )
    if empty_v2:
        runner.BASE_MINIMUM_QUALITY = 100.0
    prepared = runner._prepare_experiment(tmp_path / "generator-experiments")
    runner._invoke_codex = support._mock_invoke_factory([])
    summary = runner._run_experiment(prepared)
    assert summary["completed_pipeline_count"] == 12
    return prepared.experiment_dir, runner


@pytest.fixture(scope="module")
def harness() -> _SyntheticHarnessAdapter:
    spec = importlib.util.spec_from_file_location("liveclip_run_judges_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return _SyntheticHarnessAdapter(module)


@pytest.fixture(autouse=True)
def frozen_evaluation_materials(
    tmp_path: Path, harness: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluation_dir = tmp_path / "evaluation-materials"
    rubric_path = SCRIPT_PATH.with_name("judge-rubric.md")
    contract_path = evaluation_dir / "evaluation-contract.json"
    waiver_payload = {
        "frozen_before_generator_output": True,
        "mode": "diagnostic_not_required",
        "reason": (
            "Human review is diagnostic only for exposed development regression; "
            "semantic acceptance uses the frozen dual-Judge contract."
        ),
    }
    waiver_commitment = _sha(
        json.dumps(
            waiver_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    _write_json(
        contract_path,
        {
            "schema_version": "liveclip-highlight-evaluation-contract.iteration-2.v1",
            "contract_version": "highlight-agent-skill-v2-iteration-2-evaluation-v1",
            "iteration_id": "highlight-agent-skill-v2-iteration-2",
            "status": "frozen_before_any_iteration2_generator_output",
            "human_review_mode": "diagnostic_not_required",
            "human_feedback_waiver": {
                **waiver_payload,
                "commitment_sha256": waiver_commitment,
            },
            "artifacts": {
                relative: {
                    "sha256": _sha((harness.REPOSITORY_ROOT / relative).read_bytes()),
                    "size_bytes": (harness.REPOSITORY_ROOT / relative).stat().st_size,
                }
                for relative in sorted(harness.EXPECTED_EVALUATION_ARTIFACTS)
            },
            "generator": {"sources": []},
            "judge": harness._expected_judge_contract(),
            "aggregation": harness.EXPECTED_AGGREGATION_CONTRACT,
            "acceptance_gates": harness.EXPECTED_ACCEPTANCE_GATES,
            "outcomes": {},
        },
    )
    monkeypatch.setattr(harness, "EVALUATION_CONTRACT_PATH", contract_path)
    monkeypatch.setattr(harness, "JUDGE_RUBRIC_PATH", rubric_path)


def _write_json(path: Path, value: Any) -> bytes:
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _sha(payload: bytes) -> str:
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _generator_call(
    experiment_dir: Path,
    call_id: str,
    pipeline_id: str,
    experiment_id: str,
    experiment_contract_sha256: str,
) -> dict[str, str]:
    call_dir = experiment_dir / "calls" / call_id
    contract = _write_json(
        call_dir / "call-contract.json",
        {
            "schema_version": "1",
            "experiment_id": experiment_id,
            "experiment_contract_sha256": experiment_contract_sha256,
            "call_id": call_id,
            "pipeline_id": pipeline_id,
            "stage": "test-stage",
            "prompt_sha256": _sha(b"frozen generator prompt"),
            "maximum_attempts": 2,
        },
    )
    attempt_dir = call_dir / "attempts" / "001"
    attempt_raw = _write_json(attempt_dir / "result.raw.json", {"ok": True})
    attempt_metadata = _write_json(
        attempt_dir / "call-metadata.json",
        {
            "model_started": True,
            "elapsed_seconds": 1.25,
            "usage_status": "reported",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "output_tokens": 5,
                "reasoning_output_tokens": 1,
            },
        },
    )
    attempt_events = b'{"type":"turn.started"}\n{"type":"turn.completed"}\n'
    (attempt_dir / "events.jsonl").write_bytes(attempt_events)
    attempt_contract = _write_json(
        attempt_dir / "attempt-contract.json",
        {
            "schema_version": "2",
            "prompt_sha256": _sha(b"frozen generator prompt"),
            "status": "validated",
            "model_started": True,
            "model_attempt_consumed": True,
            "artifact_sha256": {
                "result.raw.json": _sha(attempt_raw),
                "call-metadata.json": _sha(attempt_metadata),
                "events.jsonl": _sha(attempt_events),
            },
        },
    )
    artifacts = {
        "result.raw.json": attempt_raw,
        "result.json": _write_json(call_dir / "result.json", {"ok": True}),
        "validation.json": _write_json(call_dir / "validation.json", {"status": "succeeded"}),
        "call-metadata.json": attempt_metadata,
        "events.jsonl": attempt_events,
    }
    (call_dir / "result.raw.json").write_bytes(artifacts["result.raw.json"])
    (call_dir / "call-metadata.json").write_bytes(artifacts["call-metadata.json"])
    (call_dir / "events.jsonl").write_bytes(artifacts["events.jsonl"])
    completion = {
        "schema_version": "1",
        "call_id": call_id,
        "call_contract_sha256": _sha(contract),
        "successful_attempt": 1,
        "successful_attempt_contract_sha256": _sha(attempt_contract),
        "attempt_receipts": [
            {
                "attempt": 1,
                "status": "validated",
                "attempt_contract_sha256": _sha(attempt_contract),
                "model_started": True,
                "model_attempt_consumed": True,
                "elapsed_seconds": 1.25,
                "usage_status": "reported",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "output_tokens": 5,
                    "reasoning_output_tokens": 1,
                    "reported_total_tokens": 15,
                },
            }
        ],
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
    experiment_id: str,
    experiment_contract_sha256: str,
    repeat: int,
) -> None:
    pipeline_dir = experiment_dir / "pipelines" / pipeline_id
    skill_version = "v2" if variant % 2 else "v1"
    primary_call_id = f"call_{pipeline_id}"
    selected_copy_call_id = f"{primary_call_id}_copy"
    contract = {
        "schema_version": "1",
        "pipeline_id": pipeline_id,
        "source_id": source_id,
        "repeat": repeat,
        "arm_id": f"arm_SECRET_{variant % 2}",
        "skill_version": skill_version,
        "model": "gpt-generator-secret",
        "input_sha256": source_input_sha256,
        "experiment_contract_sha256": experiment_contract_sha256,
        "fresh_generation": True,
        "required_call_ids": [primary_call_id],
        "conditional_call_ids": (
            {"nonempty_portfolio": selected_copy_call_id} if skill_version == "v2" else {}
        ),
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
    artifact_bytes = {
        "result.json": _write_json(pipeline_dir / "result.json", result),
        "validation.json": _write_json(pipeline_dir / "validation.json", {"status": "succeeded"}),
        "summary.json": _write_json(
            pipeline_dir / "summary.json", {"pipeline_id": pipeline_id, "selected_count": 1}
        ),
    }
    if skill_version == "v2":
        for relative in (
            "combined-discovery.json",
            "combined-validation.json",
            "combined-payload-capacity.json",
            "adaptive-portfolio.json",
            "would-escalate.json",
            "repair-budget.json",
        ):
            artifact_bytes[relative] = _write_json(
                pipeline_dir / relative,
                {"schema_version": "test", "pipeline_id": pipeline_id},
            )
    call_ids = [primary_call_id]
    if skill_version == "v2":
        call_ids.append(selected_copy_call_id)
    receipts = [
        _generator_call(
            experiment_dir,
            call_id,
            pipeline_id,
            experiment_id,
            experiment_contract_sha256,
        )
        for call_id in sorted(call_ids)
    ]
    completion = {
        "schema_version": "1",
        "pipeline_id": pipeline_id,
        "pipeline_contract_sha256": _sha(contract_bytes),
        "artifact_sha256": {
            relative: _sha(payload) for relative, payload in artifact_bytes.items()
        },
        "call_receipts": receipts,
    }
    _write_json(pipeline_dir / "complete.json", completion)


def _make_experiment(tmp_path: Path) -> tuple[Path, list[str]]:
    experiment_dir = tmp_path / "exp_test_anonymous"
    sources = ["src_alpha", "src_beta", "src_gamma"]
    source_payloads: dict[str, bytes] = {}
    candidates_by_source: dict[str, list[dict[str, Any]]] = {}
    evaluation_sources: list[dict[str, Any]] = []
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
        payload = _write_json(
            experiment_dir / "frozen" / "inputs" / f"{source_id}.json",
            source_payload,
        )
        source_payloads[source_id] = payload
        candidates_by_source[source_id] = candidates
        evaluation_sources.append(
            {
                "source_id": source_id,
                "source_sha256": source_payload["source"]["source_sha256"],
                "frozen_input_sha256": _sha(payload),
                "candidate_count": len(candidates),
            }
        )

    contract_path = tmp_path / "evaluation-materials" / "evaluation-contract.json"
    evaluation_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    evaluation_contract["generator"]["sources"] = evaluation_sources
    evaluation_bytes = _write_json(contract_path, evaluation_contract)
    (experiment_dir / "frozen" / "evaluation-contract.json").write_bytes(evaluation_bytes)
    immutable_contract = {
        "test": True,
        "evaluation_contract_sha256": _sha(evaluation_bytes),
    }
    contract_sha256 = _sha(
        json.dumps(
            immutable_contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    experiment_id = f"exp_{contract_sha256[:20]}"

    schedule: list[dict[str, Any]] = []
    pipeline_ids: list[str] = []
    pair_sequence = 0
    variant = 0
    for source_index, source_id in enumerate(sources, start=1):
        candidates = candidates_by_source[source_id]
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
                    experiment_id,
                    contract_sha256,
                    repeat,
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
        },
        "frozen/evaluation-contract.json": {
            "sha256": _sha(evaluation_bytes),
            "size_bytes": len(evaluation_bytes),
        },
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
            "experiment_id": experiment_id,
            "contract_sha256": contract_sha256,
            "immutable_contract": immutable_contract,
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
            "valuable_discovery_x4": 3,
            "judge_semantic_opportunity_coverage_x4": 2,
            "precision_x4": 4,
            "portfolio_coherence_x4": 3,
            "editorial_readiness_x4": 3,
            "strengths": ["选题清楚"],
            "weaknesses": ["仍需人工复核"],
        }
        for system_id in system_ids
    ]
    return {
        "schema_version": payload["schema_version"],
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


def test_frozen_contract_rubric_anchors_and_exact_six_call_manifest(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    contract_bytes = (tmp_path / "evaluation-materials" / "evaluation-contract.json").read_bytes()
    rubric_bytes = harness.JUDGE_RUBRIC_PATH.read_bytes()

    prepared = harness.prepare_judge_run(experiment_dir)

    assert prepared.evaluation.contract_sha256 == _sha(contract_bytes)
    assert prepared.evaluation.rubric_sha256 == _sha(rubric_bytes)
    assert prepared.manifest["evaluation_contract_version"] == (
        "highlight-agent-skill-v2-iteration-2-evaluation-v1"
    )
    assert prepared.manifest["evaluation_contract_sha256"] == _sha(contract_bytes)
    assert prepared.manifest["judge_rubric_sha256"] == _sha(rubric_bytes)
    assert prepared.manifest["protocol"]["expected_judge_call_count"] == 6
    assert prepared.manifest["protocol"]["adaptive_third_judge"] is False
    assert list(harness.JUDGES) == ["judge_01", "judge_02"]
    assert len(prepared.calls) == 6
    assert (
        prepared.run_dir / "evaluation" / "evaluation-contract.json"
    ).read_bytes() == contract_bytes
    assert (prepared.run_dir / "evaluation" / "judge-rubric.md").read_bytes() == rubric_bytes

    for call in prepared.calls.values():
        assert call.evaluation_contract_sha256 == _sha(contract_bytes)
        assert call.judge_rubric_sha256 == _sha(rubric_bytes)
        call_contract = harness._call_contract(call)
        assert call_contract["evaluation_contract_sha256"] == _sha(contract_bytes)
        assert call_contract["judge_rubric_sha256"] == _sha(rubric_bytes)
        prompt = harness._judge_prompt(call)
        assert f'<trusted_judge_rubric sha256="{_sha(rubric_bytes)}">' in prompt

        member_properties = call.schema["properties"]["topic_clusters"]["items"]["properties"][
            "members"
        ]["items"]["properties"]
        system_properties = call.schema["properties"]["system_evaluations"]["items"]["properties"]
        for field in harness.MEMBER_SCORE_FIELDS:
            score_schema = member_properties[field]
            assert score_schema["x-liveclip-field"] == field
            assert set(score_schema["x-liveclip-anchors"]) == {"0", "1", "2", "3", "4"}
            assert all(f"{score}=" in score_schema["description"] for score in range(5))
        for field in harness.SYSTEM_SCORE_FIELDS:
            score_schema = system_properties[field]
            assert score_schema["x-liveclip-field"] == field
            assert set(score_schema["x-liveclip-anchors"]) == {"0", "1", "2", "3", "4"}
            assert all(f"{score}=" in score_schema["description"] for score in range(5))
        assert "coverage_x4" not in system_properties
        assert "discovery_x4" not in system_properties
        assert "stability_x4" not in system_properties


def test_counterbalance_reverses_judge_order_rotates_sources_and_preserves_highlights(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.prepare_judge_run(experiment_dir)

    for source_id in prepared.source_ids:
        judge_01 = prepared.calls[(source_id, "judge_01")]
        judge_02 = prepared.calls[(source_id, "judge_02")]

        def disclosed_order(call: Any) -> list[str]:
            mapping = call.binding["anonymous_system_to_pipeline"]
            return [
                mapping[system["anonymous_system_id"]]
                for system in call.input_payload["anonymous_systems"]
            ]

        assert disclosed_order(judge_02) == list(reversed(disclosed_order(judge_01)))

    pipeline_ids = ("pipeline-a", "pipeline-b", "pipeline-c", "pipeline-d")
    rotations = [
        harness._counterbalanced_system_order(pipeline_ids, "src_rotation", position, "judge_01")
        for position in range(4)
    ]
    assert rotations == [rotations[0][position:] + rotations[0][:position] for position in range(4)]
    for position, order in enumerate(rotations):
        assert harness._counterbalanced_system_order(
            pipeline_ids, "src_rotation", position, "judge_02"
        ) == list(reversed(order))

    candidates = [
        {
            "candidate_id": "candidate_a",
            "source_start_ms": 1_000,
            "source_end_ms": 2_000,
            "text": "第一段证据",
            "context_before": "前文",
            "context_after": "后文",
        },
        {
            "candidate_id": "candidate_b",
            "source_start_ms": 3_000,
            "source_end_ms": 4_000,
            "text": "第二段证据",
            "context_before": "前文",
            "context_after": "后文",
        },
    ]
    highlight_a = {
        "candidate_id": "candidate_a",
        "title": "第一条",
        "hook": "第一条开场",
        "highlight_sentence": "第一条正文",
    }
    highlight_b = {
        "candidate_id": "candidate_b",
        "title": "第二条",
        "hook": "第二条开场",
        "highlight_sentence": "第二条正文",
    }
    ordered_pipeline_ids = ("generator-a", "generator-b", "generator-c", "generator-d")
    bundle = harness.SourceBundle(
        source_id="src_order",
        source_sha256="f" * 64,
        source_payload={
            "source": {
                "source_sha256": "e" * 64,
                "duration_ms": 5_000,
                "candidate_count": 2,
            },
            "candidates": candidates,
        },
        pipeline_ids=ordered_pipeline_ids,
        results_by_pipeline={
            pipeline_id: {"highlights": [highlight_a, highlight_b]}
            for pipeline_id in ordered_pipeline_ids
        },
    )
    call = harness._build_blind_call(
        bundle,
        "judge_01",
        0,
        harness._load_evaluation_materials(),
    )
    for system in call.input_payload["anonymous_systems"]:
        assert [item["position"] for item in system["highlights"]] == [1, 2]
        assert [item["candidate_id"] for item in system["highlights"]] == [
            "candidate_a",
            "candidate_b",
        ]


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (0, 0, 0),
        (0, 10, 0),
        (1, 3, 1),
        (2, 5, 2),
        (13, 20, 3),
        (17, 20, 4),
    ],
)
def test_fraction_bucket_boundaries(
    harness: ModuleType, numerator: int, denominator: int, expected: int
) -> None:
    assert harness._fraction_bucket(numerator, denominator) == expected


def test_qualified_predicate_derived_buckets_and_exact_system_fraction(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    call = next(iter(harness.prepare_judge_run(experiment_dir).calls.values()))
    answer = _valid_answer(call.input_payload)
    first_evaluation = answer["system_evaluations"][0]
    first_evaluation["valuable_discovery_x4"] = 4
    first_evaluation["portfolio_coherence_x4"] = 2

    _, validation = harness._validate_judge_result(answer, call)

    system_id = first_evaluation["anonymous_system_id"]
    assert validation["derived_system_metrics"][system_id]["semantic_opportunity_coverage"] == {
        "numerator": 1,
        "denominator": 2,
        "bucket_x4": 2,
    }
    assert validation["derived_system_metrics"][system_id]["precision"] == {
        "numerator": 1,
        "denominator": 1,
        "bucket_x4": 4,
    }
    assert validation["computed_system_quality"][system_id] == {
        "weighted_numerator": 315,
        "denominator": 4,
    }
    assert harness._qualified_member(
        {
            "event_match_x4": 3,
            "editorial_value_x4": 3,
            "hook_x4": 0,
            "completeness_x4": 0,
            "evidence_fidelity_x4": 3,
            "usability_x4": 2,
        }
    )
    for failed_field, failed_value in (
        ("event_match_x4", 2),
        ("editorial_value_x4", 2),
        ("evidence_fidelity_x4", 2),
        ("usability_x4", 1),
    ):
        member = {
            "event_match_x4": 3,
            "editorial_value_x4": 3,
            "evidence_fidelity_x4": 3,
            "usability_x4": 2,
        }
        member[failed_field] = failed_value
        assert not harness._qualified_member(member)

    inconsistent = _valid_answer(call.input_payload)
    inconsistent["system_evaluations"][0]["judge_semantic_opportunity_coverage_x4"] = 3
    with pytest.raises(harness.JudgeValidationError, match="coverage bucket mismatch"):
        harness._validate_judge_result(inconsistent, call)


def test_evaluation_contract_binding_uses_raw_file_bytes(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    contract_path = tmp_path / "evaluation-materials" / "evaluation-contract.json"
    frozen_bytes = contract_path.read_bytes()
    contract_path.write_bytes(frozen_bytes + b"\n")
    assert _sha(contract_path.read_bytes()) != _sha(frozen_bytes)

    with pytest.raises(harness.IntegrityError, match="evaluation contract"):
        harness.prepare_judge_run(experiment_dir)


def test_evaluation_contract_rejects_any_indexed_artifact_hash_drift(
    tmp_path: Path, harness: ModuleType
) -> None:
    contract_path = tmp_path / "evaluation-materials" / "evaluation-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    target = f"{harness.ITERATION_REPO_PREFIX}/analyze_iteration.py"
    assert contract["artifacts"][target]["sha256"] != "0" * 64
    contract["artifacts"][target]["sha256"] = "0" * 64
    _write_json(contract_path, contract)

    with pytest.raises(harness.IntegrityError, match="artifact hash drifted"):
        harness._load_evaluation_materials()


def test_preflight_only_freezes_six_calls_and_never_invokes_a_judge(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    model_counter: list[int] = []
    preflight_counter: list[int] = []

    prepared = harness.run_judges(
        experiment_dir,
        preflight_only=True,
        invoke=_mock_invoke(model_counter),
        preflight=_passing_preflight(preflight_counter),
    )

    assert len(prepared.calls) == 6
    assert model_counter == []
    assert preflight_counter == [1]
    assert not (prepared.run_dir / "sources").exists()
    assert not (prepared.run_dir / "unblind").exists()


def test_preflight_only_incomplete_matrix_fails_before_preflight_or_judge(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, pipeline_ids = _make_experiment(tmp_path)
    (experiment_dir / "pipelines" / pipeline_ids[-1] / "complete.json").unlink()
    model_counter: list[int] = []
    preflight_counter: list[int] = []

    with pytest.raises(harness.GeneratorMatrixIncomplete, match="no judge calls"):
        harness.run_judges(
            experiment_dir,
            preflight_only=True,
            invoke=_mock_invoke(model_counter),
            preflight=_passing_preflight(preflight_counter),
        )

    assert model_counter == []
    assert preflight_counter == []
    assert not (experiment_dir / "judge-runs").exists()


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
    assert not (prepared.run_dir / "unblind").exists()
    with pytest.raises(harness.IntegrityError, match="all six"):
        harness.load_verified_global_unblind(prepared)
    for source_id in prepared.source_ids:
        for judge_id in harness.JUDGES:
            call_dir = prepared.run_dir / "sources" / source_id / judge_id
            assert not (call_dir / "mapping.disclosed-after-judging.json").exists()
    harness.run_judges(experiment_dir, sentinel=True, invoke=invoke, preflight=preflight)
    assert len(counter) == 2
    harness.run_judges(experiment_dir, invoke=invoke, preflight=preflight)
    assert len(counter) == 6
    assert len(preflight_counter) == 1
    unblind = harness.load_verified_global_unblind(prepared)
    assert unblind["completed_judge_call_count"] == 6
    assert len(unblind["bindings"]) == 6
    assert unblind["evaluation_contract_sha256"] == prepared.evaluation.contract_sha256
    assert unblind["feedback_commitment"] == {
        "mode": "diagnostic_not_required",
        "status": "waived",
        "waiver_commitment_sha256": prepared.evaluation.contract["human_feedback_waiver"][
            "commitment_sha256"
        ],
        "reason": prepared.evaluation.contract["human_feedback_waiver"]["reason"],
    }
    assert sorted(path.name for path in (prepared.run_dir / "unblind").iterdir()) == [
        "global-unblind-manifest.json"
    ]
    for source_id in prepared.source_ids:
        for judge_id in harness.JUDGES:
            call_dir = prepared.run_dir / "sources" / source_id / judge_id
            assert not (call_dir / "mapping.disclosed-after-judging.json").exists()

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
        assert "model_output_invalid_utf8" in receipt["error"]
        assert (call_dir / "attempts" / attempt / "events.jsonl").is_file()
    assert process_counter == [1, 1]


def _rebind_evaluation_contract(
    experiment_dir: Path,
    contract_path: Path,
    contract: dict[str, Any],
) -> None:
    evaluation_bytes = _write_json(contract_path, contract)
    frozen_path = experiment_dir / "frozen" / "evaluation-contract.json"
    frozen_path.write_bytes(evaluation_bytes)
    manifest_path = experiment_dir / "experiment-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["immutable_contract"]["evaluation_contract_sha256"] = _sha(evaluation_bytes)
    manifest["contract_sha256"] = _sha(
        json.dumps(
            manifest["immutable_contract"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    manifest["artifact_index"]["frozen/evaluation-contract.json"] = {
        "sha256": _sha(evaluation_bytes),
        "size_bytes": len(evaluation_bytes),
    }
    _write_json(manifest_path, manifest)


def _second_attempt_completed_call(
    experiment_dir: Path,
    harness: ModuleType,
) -> tuple[Any, Path]:
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
    source_id = prepared.source_ids[0]
    judge_id = next(iter(harness.JUDGES))
    call = prepared.calls[(source_id, judge_id)]
    return call, prepared.run_dir / "sources" / source_id / judge_id


def test_generator_manifest_immutable_contract_hash_is_recomputed_before_judging(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    manifest_path = experiment_dir / "experiment-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["immutable_contract"]["tampered_after_prepare"] = True
    _write_json(manifest_path, manifest)

    with pytest.raises(harness.IntegrityError, match="immutable contract hash drifted"):
        harness.prepare_judge_run(experiment_dir)
    assert not (experiment_dir / "judge-runs").exists()


def test_global_unblind_revalidates_generator_immutable_contract(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.run_judges(
        experiment_dir,
        invoke=_mock_invoke([]),
        preflight=_passing_preflight(),
    )
    manifest_path = experiment_dir / "experiment-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["immutable_contract"]["tampered_before_unblind_read"] = True
    _write_json(manifest_path, manifest)

    with pytest.raises(harness.IntegrityError, match="immutable contract hash drifted"):
        harness.load_verified_global_unblind(prepared)


def test_global_unblind_rejects_new_generator_snapshot_with_same_ids(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.run_judges(
        experiment_dir,
        invoke=_mock_invoke([]),
        preflight=_passing_preflight(),
    )
    pipeline_id = prepared.source_bundles[0].pipeline_ids[0]
    pipeline_dir = experiment_dir / "pipelines" / pipeline_id
    result_path = pipeline_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["highlights"][0]["title"] = "coordinated replacement snapshot"
    result_bytes = _write_json(result_path, result)
    completion_path = pipeline_dir / "complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["artifact_sha256"]["result.json"] = _sha(result_bytes)
    _write_json(completion_path, completion)

    with pytest.raises(harness.IntegrityError, match="generator snapshot commitments"):
        harness.load_verified_global_unblind(prepared)


def test_global_unblind_consumes_passed_judge_snapshots_without_reopening_calls(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.run_judges(
        experiment_dir,
        invoke=_mock_invoke([]),
        preflight=_passing_preflight(),
    )
    snapshots = {
        key: harness._verify_completed_call(
            prepared.run_dir / "sources" / key[0] / key[1],
            call,
        )
        for key, call in prepared.calls.items()
    }
    first_key = sorted(snapshots)[0]
    result_path = prepared.run_dir / "sources" / first_key[0] / first_key[1] / "result.json"
    result_path.write_bytes(b'{"post_snapshot_score_swap":true}\n')

    def forbidden_reopen(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"Judge calls must not be reopened: {args!r} {kwargs!r}")

    monkeypatch.setattr(harness, "_verify_completed_call", forbidden_reopen)
    unblind = harness.load_verified_global_unblind(
        prepared,
        call_snapshots=snapshots,
    )

    assert unblind["judge_call_completion_sha256"] == {
        f"{source_id}/{judge_id}": snapshot.completion_sha256
        for (source_id, judge_id), snapshot in sorted(snapshots.items())
    }


def test_global_unblind_rejects_mutated_prepared_generator_snapshot(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.run_judges(
        experiment_dir,
        invoke=_mock_invoke([]),
        preflight=_passing_preflight(),
    )
    bundle = prepared.source_bundles[0]
    pipeline_id = bundle.pipeline_ids[0]
    bundle.results_by_pipeline[pipeline_id]["highlights"][0]["title"] = "memory mutation"

    with pytest.raises(harness.IntegrityError, match="generator snapshot commitments"):
        harness.load_verified_global_unblind(prepared)


def test_generator_source_set_must_exactly_match_evaluation_contract(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    contract_path = tmp_path / "evaluation-materials" / "evaluation-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["generator"]["sources"][0]["candidate_count"] += 1
    _rebind_evaluation_contract(experiment_dir, contract_path, contract)

    with pytest.raises(harness.IntegrityError, match="source set differs"):
        harness.prepare_judge_run(experiment_dir)
    assert not (experiment_dir / "judge-runs").exists()


@pytest.mark.parametrize(
    "mutation",
    ["extra_key", "not_frozen", "wrong_mode", "wrong_reason", "wrong_commitment"],
)
def test_diagnostic_waiver_is_exact_and_commitment_bound(
    tmp_path: Path, harness: ModuleType, mutation: str
) -> None:
    contract_path = tmp_path / "evaluation-materials" / "evaluation-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    waiver = contract["human_feedback_waiver"]
    if mutation == "extra_key":
        waiver["unexpected"] = True
    elif mutation == "not_frozen":
        waiver["frozen_before_generator_output"] = False
    elif mutation == "wrong_mode":
        waiver["mode"] = "required"
    elif mutation == "wrong_reason":
        waiver["reason"] = "diagnostic review was skipped"
    else:
        waiver["commitment_sha256"] = "0" * 64
    if mutation != "wrong_commitment":
        waiver_payload = {
            "frozen_before_generator_output": waiver["frozen_before_generator_output"],
            "mode": waiver["mode"],
            "reason": waiver["reason"],
        }
        waiver["commitment_sha256"] = _sha(
            json.dumps(
                waiver_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )
    _write_json(contract_path, contract)

    with pytest.raises(harness.IntegrityError, match="waiver"):
        harness._load_evaluation_materials()


@pytest.mark.parametrize(
    "mutation",
    ["extra_attempt", "missing_first", "over_budget", "failed_receipt"],
)
def test_completed_call_revalidates_full_continuous_attempt_sequence(
    tmp_path: Path, harness: ModuleType, mutation: str
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    call, call_dir = _second_attempt_completed_call(experiment_dir, harness)
    attempts_dir = call_dir / "attempts"
    if mutation == "extra_attempt":
        shutil.copytree(attempts_dir / "attempt_02", attempts_dir / "attempt_03")
    elif mutation == "missing_first":
        (attempts_dir / "attempt_01").rename(attempts_dir / "attempt_00")
    elif mutation == "over_budget":
        completion_path = call_dir / "complete.json"
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        completion["successful_attempt"] = harness.MAX_ATTEMPTS + 1
        _write_json(completion_path, completion)
    else:
        attempt_path = attempts_dir / "attempt_01"
        failure_path = attempt_path / "failure.json"
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        failure["failure_kind"] = "unsafe_tool_event"
        failure_bytes = _write_json(failure_path, failure)
        attempt_contract_path = attempt_path / "attempt-contract.json"
        attempt_contract = json.loads(attempt_contract_path.read_text(encoding="utf-8"))
        attempt_contract["artifact_sha256"]["failure.json"] = _sha(failure_bytes)
        _write_json(attempt_contract_path, attempt_contract)

    with pytest.raises(
        harness.IntegrityError,
        match=r"attempt|repair budget|failed attempt receipt",
    ):
        harness._verify_completed_call(call_dir, call)


@pytest.mark.parametrize("mutation", ["extra_key", "wrong_size"])
def test_generator_artifact_index_binds_exact_record_schema_and_size(
    tmp_path: Path, harness: ModuleType, mutation: str
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    manifest_path = experiment_dir / "experiment-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest["artifact_index"]["frozen/public-plan.json"]
    if mutation == "extra_key":
        record["unexpected"] = True
        expected = "artifact index"
    else:
        record["size_bytes"] += 1
        expected = "size mismatch"
    _write_json(manifest_path, manifest)

    with pytest.raises(harness.IntegrityError, match=expected):
        harness.prepare_judge_run(experiment_dir)


@pytest.mark.parametrize("section", ["judge", "aggregation", "acceptance_gates"])
def test_frozen_judge_aggregation_and_gate_constants_bind_runtime(
    tmp_path: Path, harness: ModuleType, section: str
) -> None:
    contract_path = tmp_path / "evaluation-materials" / "evaluation-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if section == "judge":
        contract[section]["required_call_count"] = 7
        expected = "Judge runtime constants"
    elif section == "aggregation":
        contract[section]["system_dimensions_and_integer_weights"]["precision_x4"] = 21
        expected = "aggregation runtime constants"
    else:
        contract[section]["judge_reliability"][
            "mean_absolute_pipeline_score_difference_maximum"
        ] = "11"
        expected = "acceptance gates"
    _write_json(contract_path, contract)

    with pytest.raises(harness.IntegrityError, match=expected):
        harness._load_evaluation_materials()


def test_precision_zero_is_derived_exactly_from_unqualified_members(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    call = next(iter(harness.prepare_judge_run(experiment_dir).calls.values()))
    answer = _valid_answer(call.input_payload)
    target_evaluation = answer["system_evaluations"][0]
    target_system_id = target_evaluation["anonymous_system_id"]
    target_members = [
        member
        for cluster in answer["topic_clusters"]
        for member in cluster["members"]
        if member["anonymous_system_id"] == target_system_id
    ]
    assert target_members
    for member in target_members:
        member["evidence_fidelity_x4"] = 0
    target_evaluation["judge_semantic_opportunity_coverage_x4"] = 0
    target_evaluation["precision_x4"] = 0

    _, validation = harness._validate_judge_result(answer, call)

    metrics = validation["derived_system_metrics"][target_system_id]
    assert metrics["precision"] == {
        "numerator": 0,
        "denominator": len(target_members),
        "bucket_x4": 0,
    }
    assert metrics["semantic_opportunity_coverage"]["numerator"] == 0
    assert metrics["semantic_opportunity_coverage"]["bucket_x4"] == 0


def test_no_qualified_semantic_opportunity_is_incomplete(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    call = next(iter(harness.prepare_judge_run(experiment_dir).calls.values()))
    answer = _valid_answer(call.input_payload)
    for cluster in answer["topic_clusters"]:
        for member in cluster["members"]:
            member["event_match_x4"] = 2

    with pytest.raises(harness.JudgeValidationError, match="source is unscorable"):
        harness._validate_judge_result(answer, call)


def test_preflight_invalid_utf8_is_bounded_zero_model_evidence(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    preflight_calls: list[int] = []
    model_calls: list[int] = []

    def invalid_preflight(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, env
        preflight_calls.append(1)
        return subprocess.CompletedProcess(command, 0, stdout=b"ready\xff", stderr=b"")

    for _ in range(harness.MAX_PREFLIGHT_FAILURES):
        with pytest.raises(harness.CodexInfrastructureUnavailable, match="invalid_utf8"):
            harness.run_judges(
                experiment_dir,
                preflight_only=True,
                invoke=_mock_invoke(model_calls),
                preflight=invalid_preflight,
            )
    with pytest.raises(harness.CodexInfrastructureUnavailable, match="failure limit"):
        harness.run_judges(
            experiment_dir,
            preflight_only=True,
            invoke=_mock_invoke(model_calls),
            preflight=invalid_preflight,
        )

    assert len(preflight_calls) == harness.MAX_PREFLIGHT_FAILURES
    assert model_calls == []
    prepared = harness.prepare_judge_run(experiment_dir)
    for number in range(1, harness.MAX_PREFLIGHT_FAILURES + 1):
        receipt = json.loads(
            (
                prepared.run_dir
                / "infrastructure"
                / "preflight"
                / "checks"
                / f"{number:03d}"
                / "receipt.json"
            ).read_text(encoding="utf-8")
        )
        assert receipt["category"] == "infrastructure_preflight_invalid_utf8"
        assert receipt["model_started"] is False
        assert receipt["model_attempt_consumed"] is False


def test_failed_preflight_cannot_be_flipped_to_passed_before_judging(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    model_calls: list[int] = []

    def failed_preflight(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, env
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b"",
            stderr=b"Error: Unknown feature flag: stale_flag",
        )

    with pytest.raises(harness.CodexInfrastructureUnavailable):
        harness.run_judges(
            experiment_dir,
            preflight_only=True,
            invoke=_mock_invoke(model_calls),
            preflight=failed_preflight,
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    receipt_path = (
        prepared.run_dir / "infrastructure" / "preflight" / "checks" / "001" / "receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["category"] == "infrastructure_configuration"
    assert receipt["returncode"] == 1
    receipt["status"] = "passed"
    _write_json(receipt_path, receipt)

    with pytest.raises(harness.IntegrityError, match="status semantics drift"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(model_calls),
            preflight=_passing_preflight(),
        )
    assert model_calls == []
    assert not (prepared.run_dir / "infrastructure" / "preflight" / "complete.json").exists()
    assert not (prepared.run_dir / "sources").exists()


def test_model_category_cannot_be_reclassified_as_zero_cost_call_infrastructure(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    initial_process_calls: list[int] = []
    with pytest.raises(harness.CodexInfrastructureUnavailable):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_pre_model_failure_invoke(harness, initial_process_calls),
            preflight=_passing_preflight(),
        )
    assert initial_process_calls == [1]
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    receipt_path = call_dir / "infrastructure-failures" / "001" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["category"] = "model_process_failure"
    receipt["returncode"] = 0
    _write_json(receipt_path, receipt)

    resumed_model_calls: list[int] = []
    with pytest.raises(harness.IntegrityError, match="status semantics drift"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(resumed_model_calls),
            preflight=_passing_preflight(),
        )
    assert resumed_model_calls == []
    assert not (call_dir / "attempts").exists()


def test_preflight_status_and_inventory_use_one_receipt_snapshot(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)

    def failed_preflight(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, env
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b"",
            stderr=b"permission denied",
        )

    with pytest.raises(harness.CodexInfrastructureUnavailable):
        harness.run_judges(
            experiment_dir,
            preflight_only=True,
            invoke=_mock_invoke([]),
            preflight=failed_preflight,
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    preflight_dir = prepared.run_dir / "infrastructure" / "preflight"
    receipt_path = (preflight_dir / "checks" / "001" / "receipt.json").resolve(strict=True)
    passed_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    passed_receipt.update(
        {
            "status": "passed",
            "category": "ready",
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "",
        }
    )
    passed_bytes = (
        json.dumps(passed_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    _write_json(
        preflight_dir / "complete.json",
        {
            "schema_version": "2",
            "policy_version": harness.PREFLIGHT_POLICY_VERSION,
            "passed_check": 1,
            "receipt_sha256": [
                {
                    "relative_path": "checks/001/receipt.json",
                    "sha256": _sha(passed_bytes),
                }
            ],
        },
    )
    real_read_bytes = Path.read_bytes
    receipt_reads = 0

    def staged_read(path: Path) -> bytes:
        nonlocal receipt_reads
        if path.resolve(strict=False) == receipt_path:
            receipt_reads += 1
            if receipt_reads == 1:
                return passed_bytes
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", staged_read)
    model_calls: list[int] = []

    def forbidden_preflight(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"verified passed preflight must resume: {args!r} {kwargs!r}")

    harness.run_judges(
        experiment_dir,
        preflight_only=True,
        invoke=_mock_invoke(model_calls),
        preflight=forbidden_preflight,
    )
    assert receipt_reads == 1
    assert model_calls == []


def test_call_infrastructure_cost_semantics_use_one_receipt_snapshot(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    initial_calls: list[int] = []
    with pytest.raises(harness.CodexInfrastructureUnavailable):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_pre_model_failure_invoke(harness, initial_calls),
            preflight=_passing_preflight(),
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    receipt_path = (call_dir / "infrastructure-failures" / "001" / "receipt.json").resolve(
        strict=True
    )
    poisoned_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    poisoned_receipt["model_started"] = True
    poisoned_receipt["model_attempt_consumed"] = True
    poisoned_bytes = (
        json.dumps(poisoned_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    real_read_bytes = Path.read_bytes
    receipt_reads = 0

    def staged_read(path: Path) -> bytes:
        nonlocal receipt_reads
        if path.resolve(strict=False) == receipt_path:
            receipt_reads += 1
            if receipt_reads == 1:
                return poisoned_bytes
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", staged_read)
    resumed_calls: list[int] = []
    with pytest.raises(harness.IntegrityError, match="binding drift"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(resumed_calls),
            preflight=_passing_preflight(),
        )
    assert receipt_reads == 1
    assert resumed_calls == []
    assert not (call_dir / "attempts").exists()


def test_generator_call_cost_receipt_uses_one_completion_snapshot(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir, pipeline_ids = _make_experiment(tmp_path)
    pipeline_id = pipeline_ids[0]
    pipeline_completion_path = experiment_dir / "pipelines" / pipeline_id / "complete.json"
    pipeline_completion = json.loads(pipeline_completion_path.read_text(encoding="utf-8"))
    call_id = pipeline_completion["call_receipts"][0]["call_id"]
    call_completion_path = (experiment_dir / "calls" / call_id / "complete.json").resolve(
        strict=True
    )
    poisoned_completion = json.loads(call_completion_path.read_text(encoding="utf-8"))
    poisoned_completion["attempt_receipts"][0]["model_attempt_consumed"] = False
    poisoned_bytes = (
        json.dumps(poisoned_completion, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    pipeline_completion["call_receipts"][0]["call_completion_sha256"] = _sha(poisoned_bytes)
    _write_json(pipeline_completion_path, pipeline_completion)
    real_read_bytes = Path.read_bytes
    completion_reads = 0

    def staged_read(path: Path) -> bytes:
        nonlocal completion_reads
        if path.resolve(strict=False) == call_completion_path:
            completion_reads += 1
            if completion_reads == 1:
                return poisoned_bytes
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", staged_read)
    judge_calls: list[int] = []
    preflight_calls: list[int] = []
    with pytest.raises(harness.GeneratorMatrixIncomplete, match="attempt receipts drifted"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(judge_calls),
            preflight=_passing_preflight(preflight_calls),
        )
    assert completion_reads == 1
    assert judge_calls == []
    assert preflight_calls == []
    assert not (experiment_dir / "judge-runs").exists()


@pytest.mark.parametrize("field", ["schema_version", "error", "failure_kind"])
def test_rehashed_failed_attempt_cannot_steer_resume_repair_prompt(
    tmp_path: Path, harness: ModuleType, field: str
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    interrupted_calls: list[int] = []

    def fail_then_interrupt(
        label: str,
        prompt: str,
        schema_path: Path,
        config: dict[str, str],
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        del label, schema_path, config
        interrupted_calls.append(1)
        if len(interrupted_calls) > 1:
            raise RuntimeError("test interruption before attempt two")
        return (
            json.dumps({"refusal": "cannot judge"}),
            {"schema_version": "2"},
            [
                {"type": "turn.started"},
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 8, "output_tokens": 2},
                },
            ],
        )

    with pytest.raises(RuntimeError, match="test interruption"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=fail_then_interrupt,
            preflight=_passing_preflight(),
        )
    assert interrupted_calls == [1, 1]
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    attempt_dir = call_dir / "attempts" / "attempt_01"
    failure_path = attempt_dir / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    if field == "schema_version":
        failure[field] = "tampered"
    elif field == "error":
        failure[field] = {"coerced": "prompt injection"}
    else:
        failure[field] = "unsafe_tool_event"
    failure_bytes = _write_json(failure_path, failure)
    contract_path = attempt_dir / "attempt-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["artifact_sha256"]["failure.json"] = _sha(failure_bytes)
    _write_json(contract_path, contract)

    resumed_calls: list[int] = []
    with pytest.raises(
        harness.IntegrityError,
        match=r"receipt drifted|failure kind drifted",
    ):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(resumed_calls),
            preflight=_passing_preflight(),
        )
    assert resumed_calls == []
    assert not (call_dir / "attempts" / "attempt_02").exists()


@pytest.mark.parametrize(
    "target_name",
    ["result.raw.txt", "failure.json", "call-metadata.json", "events.jsonl"],
)
def test_resume_derives_failed_attempt_only_from_verified_snapshot(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    interrupted_calls: list[int] = []

    def fail_then_interrupt(
        label: str,
        prompt: str,
        schema_path: Path,
        config: dict[str, str],
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        del label, prompt, schema_path, config
        interrupted_calls.append(1)
        if len(interrupted_calls) > 1:
            raise RuntimeError("test interruption before attempt two")
        return (
            json.dumps({"refusal": "cannot judge"}),
            {"schema_version": "2"},
            [
                {"type": "turn.started"},
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 8, "output_tokens": 2},
                },
            ],
        )

    with pytest.raises(RuntimeError, match="test interruption"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=fail_then_interrupt,
            preflight=_passing_preflight(),
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    attempt_dir = call_dir / "attempts" / "attempt_01"
    target_path = (attempt_dir / target_name).resolve(strict=True)
    baseline = target_path.read_bytes()
    if target_name == "result.raw.txt":
        poisoned = b"\xff"
    elif target_name == "failure.json":
        poisoned = _write_json(
            tmp_path / "poisoned-failure.json",
            {
                "schema_version": "2",
                "failure_kind": "model_output_validation",
                "error": {"prompt": "injection"},
            },
        )
    elif target_name == "call-metadata.json":
        metadata = json.loads(baseline)
        metadata["model_started"] = False
        poisoned = (
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
    else:
        poisoned = (
            b'{"type":"turn.started"}\n'
            b'{"type":"item.started","item":{"type":"tool_call","name":"shell"}}\n'
        )
    contract_path = attempt_dir / "attempt-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["artifact_sha256"][target_name] = _sha(poisoned)
    _write_json(contract_path, contract)

    real_read_bytes = Path.read_bytes
    target_reads = 0

    def staged_read(path: Path) -> bytes:
        nonlocal target_reads
        if path.resolve(strict=False) == target_path:
            target_reads += 1
            if target_reads == 1:
                return poisoned
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", staged_read)
    resumed_calls: list[int] = []
    with pytest.raises((harness.IntegrityError, harness.UnsafeToolEvent)):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(resumed_calls),
            preflight=_passing_preflight(),
        )
    assert target_reads == 1
    assert resumed_calls == []
    assert not (call_dir / "attempts" / "attempt_02").exists()


def test_completed_call_returns_single_read_verified_score_snapshot(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    prepared = harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=_mock_invoke([]),
        preflight=_passing_preflight(),
    )
    call = prepared.calls[(prepared.source_ids[0], "judge_01")]
    call_dir = prepared.run_dir / "sources" / call.source_id / call.judge_id
    result_path = (call_dir / "result.json").resolve(strict=True)
    real_read_bytes = Path.read_bytes
    result_reads = 0

    def staged_read(path: Path) -> bytes:
        nonlocal result_reads
        if path.resolve(strict=False) == result_path:
            result_reads += 1
            if result_reads > 1:
                return b'{"uncommitted_score_swap":true}\n'
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", staged_read)
    snapshot = harness._verify_completed_call(call_dir, call)

    assert result_reads == 1
    assert snapshot.result == _valid_answer(call.input_payload)
    assert snapshot.validation["status"] == "succeeded"
    assert snapshot.completion["source_id"] == call.source_id
    assert snapshot.completion_sha256 == _sha((call_dir / "complete.json").read_bytes())


@pytest.mark.parametrize("target", ["run_iteration.py", "contracts.py", "input_gate.py"])
def test_pinned_generator_verifier_never_executes_post_snapshot_path_swap(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    evaluation = harness._load_evaluation_materials()
    verifier_dir = tmp_path / "swapped-verifier"
    verifier_dir.mkdir()
    by_filename = {
        "run_iteration.py": "runner",
        "contracts.py": "contracts",
        "input_gate.py": "input_gate",
    }
    for filename, name in by_filename.items():
        (verifier_dir / filename).write_bytes(evaluation.generator_verifier_bytes[name])
    (verifier_dir / target).write_bytes(
        (verifier_dir / target).read_bytes()
        + b'\nraise AssertionError("uncommitted sentinel executed")\n'
    )
    monkeypatch.setattr(harness, "ITERATION_DIR", verifier_dir)
    harness._RUN_ITERATION_MODULES.clear()

    with pytest.raises(harness.IntegrityError, match="changed after evaluation freeze"):
        harness._load_frozen_run_iteration(evaluation)


def test_rubric_uses_the_single_artifact_index_verified_read(
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rubric_path = harness.JUDGE_RUBRIC_PATH.resolve(strict=True)
    real_read_bytes = Path.read_bytes
    rubric_reads = 0

    def staged_read(path: Path) -> bytes:
        nonlocal rubric_reads
        if path.resolve(strict=False) == rubric_path:
            rubric_reads += 1
            if rubric_reads == 1:
                return b"uncommitted malicious rubric"
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", staged_read)
    with pytest.raises(harness.IntegrityError, match=r"artifact size drifted.*judge-rubric"):
        harness._load_evaluation_materials()
    assert rubric_reads == 1


@pytest.mark.parametrize("target", ["evaluation", "plan", "source"])
def test_experiment_indexed_inputs_are_consumed_from_one_verified_snapshot(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    target_path = {
        "evaluation": experiment_dir / "frozen" / "evaluation-contract.json",
        "plan": experiment_dir / "frozen" / "public-plan.json",
        "source": experiment_dir / "frozen" / "inputs" / "src_alpha.json",
    }[target].resolve(strict=True)
    real_read_bytes = Path.read_bytes
    target_reads = 0

    def staged_read(path: Path) -> bytes:
        nonlocal target_reads
        if path.resolve(strict=False) == target_path:
            target_reads += 1
            if target_reads > 1:
                return b'{"uncommitted_sentinel":true}\n'
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", staged_read)
    prepared = harness.prepare_judge_run(experiment_dir)

    assert len(prepared.calls) == 6
    assert target_reads == 1
    assert not (prepared.run_dir / "sources").exists()


def test_post_start_invalid_utf8_stream_consumes_bounded_attempts(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    process_calls: list[int] = []

    def invalid_stream_process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        command = args[0]
        assert isinstance(kwargs["input"], bytes)
        process_calls.append(1)
        stdout = b"\n".join(
            (
                b'{"type":"thread.started","thread_id":"utf8-thread"}',
                b'{"type":"turn.started"}',
                (
                    b'{"type":"turn.completed","usage":{"input_tokens":7,'
                    b'"cached_input_tokens":2,"output_tokens":3}}'
                ),
                b"\xff",
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(harness.subprocess, "run", invalid_stream_process)
    with pytest.raises(harness.JudgeValidationError, match="exhausted its repair budget"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=harness._invoke_codex,
            preflight=_passing_preflight(),
        )

    assert process_calls == [1, 1]
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    for attempt in (1, 2):
        attempt_dir = call_dir / "attempts" / f"attempt_{attempt:02d}"
        failure = json.loads((attempt_dir / "failure.json").read_text(encoding="utf-8"))
        metadata = json.loads((attempt_dir / "call-metadata.json").read_text(encoding="utf-8"))
        assert "model_event_stream_invalid_utf8" in failure["error"]
        assert metadata["model_started"] is True
        assert metadata["usage_status"] == "reported"
        assert metadata["usage"] == {
            "input_tokens": 7,
            "cached_input_tokens": 2,
            "output_tokens": 3,
        }


@pytest.mark.parametrize("failure_mode", ["invalid_utf8", "timeout"])
def test_unsafe_event_dominates_decode_and_timeout_failures(
    tmp_path: Path,
    harness: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    unsafe_stdout = b"\n".join(
        (
            b'{"type":"thread.started","thread_id":"unsafe-priority"}',
            b'{"type":"item.completed","item":{"type":"command_execution"}}',
        )
    )

    def unsafe_process(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        del kwargs
        if failure_mode == "timeout":
            raise subprocess.TimeoutExpired(
                cmd=args[0], timeout=3600, output=unsafe_stdout, stderr=b"\xff"
            )
        return subprocess.CompletedProcess(
            args[0], 1, stdout=unsafe_stdout + b"\n\xff", stderr=b"\xff"
        )

    monkeypatch.setattr(harness.shutil, "which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(harness.subprocess, "run", unsafe_process)
    with pytest.raises(harness.CodexProcessFailure) as caught:
        harness._invoke_codex(
            "unsafe-priority",
            "prompt",
            tmp_path / "schema.json",
            harness.JUDGES["judge_01"],
        )
    assert caught.value.category == "model_safety_tool_event"
    assert caught.value.model_started is True


def test_incomplete_event_usage_never_completes_a_judge_attempt(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    calls: list[int] = []

    def missing_usage(
        label: str,
        prompt: str,
        schema_path: Path,
        config: dict[str, str],
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        del label, schema_path, config
        calls.append(1)
        return (
            json.dumps(_valid_answer(_input_from_prompt(prompt)), ensure_ascii=False),
            {"schema_version": "2"},
            [
                {"type": "turn.started"},
                {"type": "turn.completed", "usage": {"input_tokens": 9}},
            ],
        )

    with pytest.raises(harness.JudgeValidationError, match="exhausted its repair budget"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=missing_usage,
            preflight=_passing_preflight(),
        )
    assert calls == [1, 1]
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    for attempt in (1, 2):
        metadata = json.loads(
            (call_dir / "attempts" / f"attempt_{attempt:02d}" / "call-metadata.json").read_text(
                encoding="utf-8"
            )
        )
        assert metadata["usage_status"] == "invalid"
        assert metadata["usage"] is None
        assert not (call_dir / "complete.json").exists()


@pytest.mark.parametrize("hostile_kind", ["lone_surrogate", "huge_integer", "deep", "oversized"])
def test_hostile_judge_json_is_receipted_and_bounded(
    tmp_path: Path, harness: ModuleType, hostile_kind: str
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    calls: list[int] = []

    def hostile(
        label: str,
        prompt: str,
        schema_path: Path,
        config: dict[str, str],
    ) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
        del label, schema_path, config
        calls.append(1)
        if hostile_kind == "lone_surrogate":
            answer = _valid_answer(_input_from_prompt(prompt))
            answer["overall_verdict"] = "\ud800"
            raw = json.dumps(answer)
        elif hostile_kind == "huge_integer":
            raw = '{"value":' + ("9" * 10_000) + "}"
        elif hostile_kind == "deep":
            raw = "[" * 2_000 + "0" + "]" * 2_000
        else:
            raw = "x" * (harness.MAX_JUDGE_OUTPUT_BYTES + 1)
        return (
            raw,
            {"schema_version": "2"},
            [
                {"type": "item.completed", "item": {"type": "agent_message"}},
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 4, "output_tokens": 2},
                },
            ],
        )

    with pytest.raises(harness.JudgeValidationError, match="exhausted its repair budget"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=hostile,
            preflight=_passing_preflight(),
        )
    assert calls == [1, 1]
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    for attempt in (1, 2):
        attempt_dir = call_dir / "attempts" / f"attempt_{attempt:02d}"
        assert (attempt_dir / "failure.json").is_file()
        assert (attempt_dir / "call-metadata.json").is_file()
        assert (attempt_dir / "events.jsonl").is_file()
        (attempt_dir / "result.raw.txt").read_bytes().decode("utf-8")


def _coordinated_rehash_completed_judge_attempt(
    call_dir: Path,
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    attempt_dir = call_dir / "attempts" / "attempt_01"
    metadata_path = attempt_dir / "call-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    mutate(metadata)
    metadata_bytes = _write_json(metadata_path, metadata)
    (call_dir / "call-metadata.json").write_bytes(metadata_bytes)

    attempt_contract_path = attempt_dir / "attempt-contract.json"
    attempt_contract = json.loads(attempt_contract_path.read_text(encoding="utf-8"))
    attempt_contract["artifact_sha256"]["call-metadata.json"] = _sha(metadata_bytes)
    attempt_contract_bytes = _write_json(attempt_contract_path, attempt_contract)

    completion_path = call_dir / "complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    completion["successful_attempt_contract_sha256"] = _sha(attempt_contract_bytes)
    completion["artifact_sha256"]["call-metadata.json"] = _sha(metadata_bytes)
    _write_json(completion_path, completion)


@pytest.mark.parametrize("field", ["request_id", "usage", "unsafe_tool_event", "model_started"])
def test_completed_attempt_metadata_is_exactly_rederived_from_events(
    tmp_path: Path, harness: ModuleType, field: str
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    calls: list[int] = []
    prepared = harness.run_judges(
        experiment_dir,
        sentinel=True,
        invoke=_mock_invoke(calls),
        preflight=_passing_preflight(),
    )
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"

    def mutate(metadata: dict[str, Any]) -> None:
        if field == "request_id":
            metadata[field] = "coordinated-false-request"
        elif field == "usage":
            metadata[field]["input_tokens"] = 0
        else:
            metadata[field] = not metadata[field]

    _coordinated_rehash_completed_judge_attempt(call_dir, mutate)
    before = len(calls)
    with pytest.raises(harness.IntegrityError, match=f"metadata {field} drifted"):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(calls),
            preflight=_passing_preflight(),
        )
    assert len(calls) == before


def test_coordinated_rehash_cannot_repair_an_unsafe_attempt(
    tmp_path: Path, harness: ModuleType
) -> None:
    experiment_dir, _ = _make_experiment(tmp_path)
    calls: list[int] = []

    def add_unsafe(events: list[dict[str, Any]]) -> None:
        events.insert(
            1,
            {"type": "item.completed", "item": {"type": "command_execution"}},
        )

    with pytest.raises(harness.UnsafeToolEvent):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(calls, add_unsafe),
            preflight=_passing_preflight(),
        )
    prepared = harness.prepare_judge_run(experiment_dir)
    call_dir = prepared.run_dir / "sources" / prepared.source_ids[0] / "judge_01"
    attempt_dir = call_dir / "attempts" / "attempt_01"
    failure_path = attempt_dir / "failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    failure["failure_kind"] = "model_output_validation"
    failure_bytes = _write_json(failure_path, failure)
    metadata_path = attempt_dir / "call-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["unsafe_tool_event"] = False
    metadata_bytes = _write_json(metadata_path, metadata)
    contract_path = attempt_dir / "attempt-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["status"] = "failed"
    contract["artifact_sha256"]["failure.json"] = _sha(failure_bytes)
    contract["artifact_sha256"]["call-metadata.json"] = _sha(metadata_bytes)
    _write_json(contract_path, contract)

    with pytest.raises(harness.UnsafeToolEvent):
        harness.run_judges(
            experiment_dir,
            sentinel=True,
            invoke=_mock_invoke(calls),
            preflight=_passing_preflight(),
        )
    assert calls == [1]
    assert not (call_dir / "attempts" / "attempt_02").exists()


def test_real_generator_reconstruction_rejects_v1_and_v2_pipeline_only_tamper(
    tmp_path: Path, harness: _SyntheticHarnessAdapter
) -> None:
    nonempty_dir, nonempty_runner = _real_generator_experiment(
        tmp_path / "nonempty",
        harness,
        empty_v2=False,
    )
    empty_dir, empty_runner = _real_generator_experiment(
        tmp_path / "empty",
        harness,
        empty_v2=True,
    )
    production = object.__getattribute__(harness, "_module")

    def pipeline_for(
        experiment_dir: Path,
        skill_version: str,
        selected_count: int | None,
    ) -> str:
        private_map = json.loads(
            (experiment_dir / "private" / "arm-map.private.json").read_text(encoding="utf-8")
        )
        for pipeline_id, identity in private_map["pipeline_id_to_identity"].items():
            if identity["skill_version"] != skill_version:
                continue
            summary = json.loads(
                (experiment_dir / "pipelines" / pipeline_id / "summary.json").read_text(
                    encoding="utf-8"
                )
            )
            if (
                selected_count is None
                or (selected_count == -1 and summary["selected_count"] > 0)
                or summary["selected_count"] == selected_count
            ):
                return pipeline_id
        raise AssertionError(f"no {skill_version} pipeline with selected_count={selected_count}")

    cases = (
        (
            "v1",
            nonempty_dir,
            nonempty_runner,
            pipeline_for(nonempty_dir, "v1", None),
        ),
        (
            "v2-nonempty",
            nonempty_dir,
            nonempty_runner,
            pipeline_for(nonempty_dir, "v2", -1),
        ),
        (
            "v2-empty",
            empty_dir,
            empty_runner,
            pipeline_for(empty_dir, "v2", 0),
        ),
    )
    for label, base_dir, runner, pipeline_id in cases:
        experiment_dir = tmp_path / f"tampered-{label}" / base_dir.name
        shutil.copytree(base_dir, experiment_dir)
        pipeline_dir = experiment_dir / "pipelines" / pipeline_id
        completion_path = pipeline_dir / "complete.json"
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        if label == "v1":
            artifact_path = pipeline_dir / "validation.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["coordinated_pipeline_only_tamper"] = True
        else:
            artifact_path = pipeline_dir / "repair-budget.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["repairs_used"] = True
        artifact_bytes = runner._pretty_json_bytes(artifact)
        artifact_path.write_bytes(artifact_bytes)
        completion["artifact_sha256"][artifact_path.name] = _sha(artifact_bytes)
        completion_path.write_bytes(runner._pretty_json_bytes(completion))

        judge_calls: list[int] = []
        preflight_calls: list[int] = []
        with pytest.raises(
            production.GeneratorMatrixIncomplete,
            match="deterministic reconstruction failed",
        ):
            production.run_judges(
                experiment_dir,
                invoke=_mock_invoke(judge_calls),
                preflight=_passing_preflight(preflight_calls),
            )
        assert judge_calls == []
        assert preflight_calls == []
        assert not (experiment_dir / "judge-runs").exists()
