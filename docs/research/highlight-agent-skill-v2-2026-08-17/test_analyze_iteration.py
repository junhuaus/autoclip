# ruff: noqa: RUF001
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("analyze_iteration.py")


@pytest.fixture(scope="module")
def analyzer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("liveclip_analyze_iteration_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _highlight(candidate: str, index: int, title: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate,
        "source_start_ms": index * 100_000,
        "source_end_ms": index * 100_000 + 60_000,
        "title": title,
        "topic": "共同话题" if "common" in candidate else "补充话题",
        "highlight_sentence": "原技能编辑后的高光语句",
        "evidence_quote": "新技能严格绑定的证据",
    }


def _member(anonymous_id: str, highlight_id: str, candidate_id: str) -> dict[str, Any]:
    return {
        "anonymous_system_id": anonymous_id,
        "highlight_id": highlight_id,
        "candidate_id": candidate_id,
        "event_match_x4": 4,
        "editorial_value_x4": 3,
        "hook_x4": 3,
        "completeness_x4": 4,
        "evidence_fidelity_x4": 4,
        "usability_x4": 4,
        "assessment": "证据完整，适合编辑。",
    }


def _synthetic_verified(analyzer: ModuleType, root: Path, *, with_repairs: bool = False) -> Any:
    sources = ("source_a", "source_b", "source_c")
    generators = []
    judges = []
    candidates_by_source: dict[str, dict[str, dict[str, Any]]] = {}
    pipelines_by_source: dict[str, list[Any]] = {}
    for source_position, source_id in enumerate(sources):
        candidate_ids = [
            f"candidate_{source_id}_common",
            *(
                f"candidate_{source_id}_{skill}_{repeat}"
                for skill in ("v1", "v2")
                for repeat in (1, 2)
            ),
        ]
        candidates_by_source[source_id] = {
            candidate_id: {
                "candidate_id": candidate_id,
                "text": "前文，新技能严格绑定的证据，后文。",
            }
            for candidate_id in candidate_ids
        }
        records = []
        for skill in ("v1", "v2"):
            for repeat in (1, 2):
                pipeline_id = f"pipeline_{source_id}_{skill}_{repeat}"
                unique = f"candidate_{source_id}_{skill}_{repeat}"
                highlights = [
                    _highlight(f"candidate_{source_id}_common", source_position * 10 + 1, "共同"),
                    _highlight(unique, source_position * 10 + repeat + 2, f"{skill}-{repeat}"),
                ]
                for highlight in highlights:
                    receipt = analyzer.highlight_contracts.exact_quote_receipt(
                        highlight["evidence_quote"],
                        candidates_by_source[source_id][highlight["candidate_id"]]["text"],
                    )
                    highlight["evidence_receipt"] = receipt
                result_path = root / "pipelines" / pipeline_id / "result.json"
                completion_path = root / "pipelines" / pipeline_id / "complete.json"
                result_path.parent.mkdir(parents=True, exist_ok=True)
                result_path.write_text("{}", encoding="utf-8")
                completion_path.write_text("{}", encoding="utf-8")
                quote_failures = 0 if skill == "v2" else repeat
                validation = (
                    {
                        "selected_order_gate": "passed",
                        "exact_quote_gate": "passed",
                        "receipt_count": len(highlights),
                        "receipts": [
                            {
                                "candidate_id": highlight["candidate_id"],
                                **highlight["evidence_receipt"],
                            }
                            for highlight in highlights
                        ],
                    }
                    if skill == "v2"
                    else {"v2_quote_gate_shadow_audit": {"failed_count": quote_failures}}
                )
                repaired = with_repairs and skill == "v2" and repeat == 2
                summary = {
                    "repair_budget": {
                        "repairs_used": 1 if repaired else 0,
                        "used_by_stage": ["tier2"] if repaired else [],
                    },
                    (
                        "exact_quote_failed_count" if skill == "v2" else "quote_gate_failed_count"
                    ): quote_failures,
                }
                usage_multiplier = 1 if skill == "v1" else 2
                record = analyzer.GeneratorRecord(
                    pipeline_id=pipeline_id,
                    source_id=source_id,
                    skill_version=skill,
                    repeat=repeat,
                    result={"highlights": highlights},
                    validation=validation,
                    summary=summary,
                    usage={
                        "input_tokens": 1000 * usage_multiplier,
                        "cached_input_tokens": 100 * usage_multiplier,
                        "output_tokens": 100 * usage_multiplier,
                        "reasoning_output_tokens": 25 * usage_multiplier,
                        "reported_total_tokens": 1100 * usage_multiplier,
                    },
                    elapsed_seconds=10.0 * usage_multiplier,
                    call_count=usage_multiplier,
                    result_path=result_path,
                    completion_path=completion_path,
                    supplemental_unbound_attempt_observations=(
                        (
                            {
                                "call_id": f"call_{pipeline_id}",
                                "attempt": 1,
                                "completion_receipt_bound": False,
                                "status": "observed_unbound",
                                "usage": {
                                    "input_tokens": 999,
                                    "cached_input_tokens": 0,
                                    "output_tokens": 99,
                                    "reasoning_output_tokens": 9,
                                    "reported_total_tokens": 1098,
                                },
                                "elapsed_seconds": 9.9,
                                "metadata_sha256": "f" * 64,
                            },
                        )
                        if repaired
                        else ()
                    ),
                )
                generators.append(record)
                records.append(record)
        pipelines_by_source[source_id] = records

        for judge_index, judge_id in enumerate(("judge_01", "judge_02"), start=1):
            anonymous_to_pipeline: dict[str, str] = {}
            membership: dict[str, dict[str, str]] = {}
            common_members = []
            unique_members = []
            system_evaluations = []
            computed_scores: dict[str, int] = {}
            for system_position, record in enumerate(records, start=1):
                anonymous_id = f"system_{judge_index}_{system_position}"
                anonymous_to_pipeline[anonymous_id] = record.pipeline_id
                skill_score = 70 if judge_id == "judge_01" else 74
                if record.skill_version == "v2":
                    skill_score = 80 if judge_id == "judge_01" else 78
                computed_scores[anonymous_id] = skill_score
                system_evaluations.append(
                    {
                        "anonymous_system_id": anonymous_id,
                        "discovery_x4": 3,
                        "coverage_x4": 3,
                        "precision_x4": 3,
                        "stability_x4": 3,
                        "editorial_readiness_x4": 3,
                        "strengths": ["结构清楚"],
                        "weaknesses": ["样本有限"],
                    }
                )
                for highlight_position, generated in enumerate(
                    record.result["highlights"], start=1
                ):
                    highlight_id = f"highlight_{judge_index}_{system_position}_{highlight_position}"
                    membership[highlight_id] = {
                        "anonymous_system_id": anonymous_id,
                        "pipeline_id": record.pipeline_id,
                        "candidate_id": generated["candidate_id"],
                    }
                    member = _member(anonymous_id, highlight_id, generated["candidate_id"])
                    (common_members if highlight_position == 1 else unique_members).append(member)
            result_path = root / "judges" / source_id / judge_id / "result.json"
            completion_path = result_path.with_name("complete.json")
            binding_path = result_path.with_name("mapping.disclosed-after-judging.json")
            result_path.parent.mkdir(parents=True, exist_ok=True)
            for path in (result_path, completion_path, binding_path):
                path.write_text("{}", encoding="utf-8")
            judges.append(
                analyzer.JudgeRecord(
                    source_id=source_id,
                    judge_id=judge_id,
                    result={
                        "topic_clusters": [
                            {
                                "cluster_id": "topic_001",
                                "canonical_topic": "共同主题",
                                "alignment_confidence": "high",
                                "members": common_members,
                                "topic_assessment": "四个输出都发现了共同主题。",
                            },
                            {
                                "cluster_id": "topic_002",
                                "canonical_topic": "互补角度",
                                "alignment_confidence": "medium",
                                "members": unique_members,
                                "topic_assessment": "不同 sampling 给出互补角度。",
                            },
                        ],
                        "system_evaluations": system_evaluations,
                        "preferred_system_ids": [
                            anonymous_id
                            for anonymous_id, pipeline_id in anonymous_to_pipeline.items()
                            if "_v2_" in pipeline_id
                        ],
                        "overall_verdict": "v2 的证据边界更清楚。",
                        "limitations": ["仅限合成 fixture。"],
                    },
                    validation={"computed_system_score_x100": computed_scores},
                    binding={
                        "anonymous_system_to_pipeline": anonymous_to_pipeline,
                        "highlight_membership": membership,
                    },
                    usage={
                        "input_tokens": 500,
                        "cached_input_tokens": 50,
                        "output_tokens": 50,
                        "reasoning_output_tokens": 10,
                        "reported_total_tokens": 550,
                    },
                    result_path=result_path,
                    completion_path=completion_path,
                    binding_path=binding_path,
                )
            )
    return analyzer.VerifiedExperiment(
        experiment_dir=root,
        judge_run_dir=root / "judge-run",
        experiment_id="experiment_synthetic",
        source_ids=sources,
        generator_configuration={"model": "generator-real", "reasoning_effort": "medium"},
        judge_configuration={
            "judge_01": {"model": "judge-a", "reasoning_effort": "max"},
            "judge_02": {"model": "judge-b", "reasoning_effort": "max"},
        },
        source_metadata_by_id={
            source_id: {"filename": f"{source_id}.ts", "source_sha256": source_id}
            for source_id in sources
        },
        candidates_by_source=candidates_by_source,
        generators=tuple(generators),
        judges=tuple(judges),
    )


def test_source_first_analysis_and_acceptance(analyzer: ModuleType, tmp_path: Path) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    result = analyzer.analyze_verified_experiment(verified)

    assert result["integrity"] == {
        "status": "passed",
        "experiment_id": "experiment_synthetic",
        "validated_generator_pipeline_receipts": 12,
        "validated_dual_judge_receipts": 6,
        "unblinded_only_after_all_judges_completed": True,
        "source_first_aggregation": True,
        "unique_source_count": 3,
        "alias_weighting": False,
    }
    assert result["quality"]["dual_judge"]["v1"]["source_first_macro_x100"] == 72
    assert result["quality"]["dual_judge"]["v2"]["source_first_macro_x100"] == 79
    assert result["quality"]["v2_minus_v1_x100"] == 7
    assert result["quality"]["dual_judge"]["v2"]["source_first_dimensions_x100"] == {
        "discovery_x100": 75,
        "coverage_x100": 75,
        "precision_x100": 75,
        "stability_x100": 75,
        "editorial_readiness_x100": 75,
    }
    assert result["acceptance"]["recommendation"] == "accept_v2_for_next_integration_gate"
    assert result["evidence_and_repairs"]["v2_outward_exact_evidence_failure_count"] == 0
    assert result["evidence_and_repairs"]["repair_summary"]["v2"] == {
        "pipeline_count": 6,
        "pipelines_with_repair": 0,
        "pipeline_repair_rate": 0.0,
        "total_repairs": 0,
    }
    assert result["efficiency"]["successful_artifact_lower_bound_v2_to_v1_ratio"] == {
        "elapsed_seconds": 2.0,
        "reported_total_tokens": 2.0,
    }
    assert result["efficiency"]["cost"]["status"] == "not_estimated"
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_gate", "exact quote gate is not passed"),
        ("selected_order_gate", "selected order gate is not passed"),
        ("receipt_count", "quote receipt count mismatch"),
        ("receipt_order", "validation quote receipt mismatch"),
        ("validation_receipt", "validation quote receipt mismatch"),
        ("outward_receipt", "outward quote receipt mismatch"),
        ("summary_count", "summary quote failure count mismatch"),
        ("failed_exact_match", "outward exact quote failure"),
        ("duplicate_candidate", "highlight candidate binding failed"),
    ],
)
def test_v2_exact_evidence_gate_fails_closed_on_adversarial_artifacts(
    analyzer: ModuleType,
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    record_index = next(
        index for index, record in enumerate(verified.generators) if record.skill_version == "v2"
    )
    record = verified.generators[record_index]
    result = copy.deepcopy(record.result)
    validation = copy.deepcopy(record.validation)
    summary = copy.deepcopy(record.summary)
    if mutation == "missing_gate":
        validation.pop("exact_quote_gate")
    elif mutation == "selected_order_gate":
        validation["selected_order_gate"] = "failed"
    elif mutation == "receipt_count":
        validation["receipt_count"] -= 1
    elif mutation == "receipt_order":
        validation["receipts"].reverse()
    elif mutation == "validation_receipt":
        validation["receipts"][0]["quote_sha256"] = "0" * 64
    elif mutation == "outward_receipt":
        result["highlights"][0]["evidence_receipt"]["quote_sha256"] = "0" * 64
    elif mutation == "summary_count":
        summary["exact_quote_failed_count"] = 1
    elif mutation == "failed_exact_match":
        highlight = result["highlights"][0]
        highlight["evidence_quote"] = "候选文本里不存在的证据"
        failed_receipt = analyzer.highlight_contracts.exact_quote_receipt(
            highlight["evidence_quote"],
            verified.candidates_by_source[record.source_id][highlight["candidate_id"]]["text"],
        )
        highlight["evidence_receipt"] = failed_receipt
        validation["receipts"][0] = {
            "candidate_id": highlight["candidate_id"],
            **failed_receipt,
        }
        summary["exact_quote_failed_count"] = 1
    elif mutation == "duplicate_candidate":
        first = result["highlights"][0]
        second = result["highlights"][1]
        second["candidate_id"] = first["candidate_id"]
        second["evidence_quote"] = first["evidence_quote"]
        second["evidence_receipt"] = copy.deepcopy(first["evidence_receipt"])
        validation["receipts"][1] = {
            "candidate_id": first["candidate_id"],
            **copy.deepcopy(first["evidence_receipt"]),
        }
    else:  # pragma: no cover - parametrization is the exhaustive mutation inventory.
        raise AssertionError(mutation)
    mutated = replace(record, result=result, validation=validation, summary=summary)
    records = list(verified.generators)
    records[record_index] = mutated

    with pytest.raises(analyzer.AnalysisError, match=message):
        analyzer.analyze_verified_experiment(replace(verified, generators=tuple(records)))


def test_unbound_repair_cost_makes_efficiency_gate_inconclusive(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    result = analyzer.analyze_verified_experiment(
        _synthetic_verified(analyzer, tmp_path, with_repairs=True)
    )

    assert result["efficiency"]["successful_artifact_lower_bound_v2_to_v1_ratio"] == {
        "elapsed_seconds": 2.0,
        "reported_total_tokens": 2.0,
    }
    assert result["efficiency"]["unbound_repair_cost"] == {
        "present": True,
        "completion_bound_repair_attempt_count": 3,
        "hard_gate_eligible": False,
        "reason": result["efficiency"]["unbound_repair_cost"]["reason"],
    }
    assert len(result["efficiency"]["supplemental_unbound_attempt_observations"]) == 3
    gate = result["acceptance"]["gates"]["efficiency_within_3x_or_quality_justified"]
    assert gate["status"] == "inconclusive_unbound_repair_cost"
    assert (
        result["acceptance"]["recommendation"]
        == "inconclusive_v2_pending_bound_efficiency_evidence"
    )


def test_relative_coverage_stability_topics_and_disagreement(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    result = analyzer.analyze_verified_experiment(_synthetic_verified(analyzer, tmp_path))

    for row in result["coverage_and_stability"]["by_source"]:
        assert row["observed_selected_union_count"] == 5
        assert row["v1_relative_selected_union_coverage"] == 0.6
        assert row["v2_relative_selected_union_coverage"] == 0.6
    for row in result["coverage_and_stability"]["sampling_stability"]:
        assert row["repeat_candidate_jaccard"] == pytest.approx(1 / 3, abs=0.001)
        assert "sampling stability only" in row["claim_limit"]
    assert result["coverage_and_stability"][
        "source_first_macro_relative_selected_union_coverage"
    ] == {"v1": 0.6, "v2": 0.6}
    assert result["coverage_and_stability"]["source_first_macro_sampling_stability"] == {
        "v1": {"repeat_candidate_jaccard": 0.333, "repeat_interval_match_f1": 0.5},
        "v2": {"repeat_candidate_jaccard": 0.333, "repeat_interval_match_f1": 0.5},
    }
    assert len(result["topics"]) == 12
    assert len(result["semantic_topic_metrics"]) == 24
    assert result["judge_disagreement"]["mean_absolute_quality_difference_x100"] == 3
    assert all(
        row["f1"] == 1 for row in result["judge_disagreement"]["free_topic_partition_agreement"]
    )
    assert "absolute recall" in " ".join(result["limitations"])


def test_incomplete_judges_refuse_before_private_map_read(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment_id = "experiment_gate"
    bundles = tuple(
        SimpleNamespace(
            source_id=f"source_{index}",
            pipeline_ids=tuple(f"pipeline_{index}_{item}" for item in range(4)),
        )
        for index in range(3)
    )
    monkeypatch.setattr(
        analyzer.judge_harness,
        "_load_source_bundles",
        lambda _path: (experiment_id, bundles),
    )
    monkeypatch.setattr(analyzer.judge_harness, "_preflight_policy", lambda: {})
    monkeypatch.setattr(
        analyzer.judge_harness, "_run_id", lambda _experiment_id, _policy: "judge_gate"
    )
    run_dir = tmp_path / "judge-runs" / "judge_gate"
    expected = [
        run_dir / "sources" / bundle.source_id / judge_id / "complete.json"
        for bundle in bundles
        for judge_id in ("judge_01", "judge_02")
    ]
    for path in expected[:-1]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    private_reads = 0

    def forbidden_private_read(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal private_reads
        private_reads += 1
        raise AssertionError("private map must remain unread")

    monkeypatch.setattr(analyzer, "_load_private_identity_map", forbidden_private_read)
    with pytest.raises(analyzer.AnalysisIncomplete, match="all six"):
        analyzer.load_verified_experiment(tmp_path)
    assert private_reads == 0


def test_all_six_receipts_are_verified_before_unblind(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment_id = "experiment_order"
    bundles = tuple(
        SimpleNamespace(
            source_id=f"source_{index}",
            pipeline_ids=tuple(f"pipeline_{index}_{item}" for item in range(4)),
        )
        for index in range(3)
    )
    monkeypatch.setattr(
        analyzer.judge_harness,
        "_load_source_bundles",
        lambda _path: (experiment_id, bundles),
    )
    monkeypatch.setattr(analyzer.judge_harness, "_preflight_policy", lambda: {})
    monkeypatch.setattr(
        analyzer.judge_harness, "_run_id", lambda _experiment_id, _policy: "judge_order"
    )
    run_dir = tmp_path / "judge-runs" / "judge_order"
    calls = {}
    for bundle in bundles:
        for judge_id in ("judge_01", "judge_02"):
            path = run_dir / "sources" / bundle.source_id / judge_id / "complete.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
            calls[(bundle.source_id, judge_id)] = object()
    prepared = SimpleNamespace(
        run_dir=run_dir,
        source_ids=tuple(bundle.source_id for bundle in bundles),
        manifest={
            "judge_ids": ["judge_01", "judge_02"],
            "judge_configuration": {},
        },
        calls=calls,
    )
    monkeypatch.setattr(analyzer.judge_harness, "prepare_judge_run", lambda _path: prepared)
    monkeypatch.setattr(analyzer, "_verify_completed_runtime_preflight", lambda _prepared: None)
    verified_calls = 0

    def verify(*_args: Any, **_kwargs: Any) -> None:
        nonlocal verified_calls
        verified_calls += 1

    monkeypatch.setattr(analyzer.judge_harness, "_verify_completed_call", verify)

    class UnblindReached(RuntimeError):
        pass

    def stop_at_unblind(*_args: Any, **_kwargs: Any) -> Any:
        assert verified_calls == 6
        raise UnblindReached

    monkeypatch.setattr(analyzer, "_load_private_identity_map", stop_at_unblind)
    with pytest.raises(UnblindReached):
        analyzer.load_verified_experiment(tmp_path)
    assert verified_calls == 6


def test_private_map_requires_frozen_commitment(analyzer: ModuleType, tmp_path: Path) -> None:
    identities = {
        f"pipeline_{index}": {
            "arm_id": "arm_v1" if index % 2 else "arm_v2",
            "repeat": 1 if index < 6 else 2,
            "skill_version": "v1" if index % 2 else "v2",
            "source_id": f"source_{index // 4}",
        }
        for index in range(12)
    }
    private = {
        "arm_id_to_skill_version": {"arm_v1": "v1", "arm_v2": "v2"},
        "pipeline_id_to_identity": identities,
    }
    private_bytes = (
        json.dumps(private, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    private_path = tmp_path / "private" / "arm-map.private.json"
    private_path.parent.mkdir(parents=True)
    private_path.write_bytes(private_bytes)
    plan_path = tmp_path / "frozen" / "public-plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        json.dumps({"arm_mapping_commitment_sha256": hashlib.sha256(private_bytes).hexdigest()}),
        encoding="utf-8",
    )
    assert analyzer._load_private_identity_map(tmp_path, set(identities)) == identities

    private_path.write_bytes(private_bytes + b" ")
    with pytest.raises(analyzer.AnalysisError, match="commitment"):
        analyzer._load_private_identity_map(tmp_path, set(identities))


def test_generator_observations_include_failed_repair_attempt(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    call_dir = tmp_path / "calls" / "call_repaired"

    def write(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    write(call_dir / "complete.json", {"successful_attempt": 2})
    first_metadata = {
        "elapsed_seconds": 1.25,
        "usage": {
            "input_tokens": 100,
            "cached_input_tokens": 10,
            "output_tokens": 20,
            "reasoning_output_tokens": 5,
        },
    }
    second_metadata = {
        "elapsed_seconds": 2.75,
        "usage": {
            "input_tokens": 200,
            "cached_input_tokens": 20,
            "output_tokens": 30,
            "reasoning_output_tokens": 7,
        },
    }
    write(
        call_dir / "attempts" / "001" / "attempt-contract.json",
        {"prompt_sha256": "a" * 64, "status": "failed"},
    )
    write(call_dir / "attempts" / "001" / "failure.json", {"error": "schema"})
    write(call_dir / "attempts" / "001" / "call-metadata.json", first_metadata)
    write(
        call_dir / "attempts" / "002" / "attempt-contract.json",
        {"prompt_sha256": "b" * 64, "status": "validated"},
    )
    write(call_dir / "attempts" / "002" / "call-metadata.json", second_metadata)
    write(call_dir / "call-metadata.json", second_metadata)

    observations = analyzer._generator_observations(
        tmp_path, {"call_receipts": [{"call_id": "call_repaired"}]}
    )
    hard_evidence = {
        key: observations[key]
        for key in (
            "bound_successful_usage",
            "bound_successful_call_count",
            "bound_successful_elapsed_seconds",
            "completion_bound_repair_count",
        )
    }
    assert hard_evidence == {
        "bound_successful_usage": {
            "input_tokens": 200,
            "cached_input_tokens": 20,
            "output_tokens": 30,
            "reasoning_output_tokens": 7,
            "reported_total_tokens": 230,
        },
        "bound_successful_call_count": 1,
        "bound_successful_elapsed_seconds": 2.75,
        "completion_bound_repair_count": 1,
    }
    supplemental = observations["supplemental_unbound_attempt_observations"]
    assert supplemental[0]["completion_receipt_bound"] is False
    assert supplemental[0]["status"] == "observed_unbound"
    assert supplemental[0]["usage"]["reported_total_tokens"] == 120
    assert supplemental[0]["elapsed_seconds"] == 1.25

    # Failed-attempt metadata is not named in the generator completion hash map.
    # Tampering it may alter the supplemental observation, but must never alter a
    # metric consumed by the hard efficiency gate.
    first_metadata["elapsed_seconds"] = 999.0
    first_metadata["usage"]["input_tokens"] = 999_999
    write(call_dir / "attempts" / "001" / "call-metadata.json", first_metadata)
    tampered = analyzer._generator_observations(
        tmp_path, {"call_receipts": [{"call_id": "call_repaired"}]}
    )
    assert {
        key: tampered[key]
        for key in (
            "bound_successful_usage",
            "bound_successful_call_count",
            "bound_successful_elapsed_seconds",
            "completion_bound_repair_count",
        )
    } == hard_evidence
    assert tampered["supplemental_unbound_attempt_observations"] != supplemental
    assert (
        tampered["supplemental_unbound_attempt_observations"][0]["completion_receipt_bound"]
        is False
    )


def test_pipeline_completion_binds_exact_call_inventory_and_identity(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline_dir = tmp_path / "pipelines" / "pipeline_bound"
    pipeline_dir.mkdir(parents=True)
    contract = {
        "pipeline_id": "pipeline_bound",
        "experiment_contract_sha256": "e" * 64,
    }
    expected_call_ids = ["call_required", "call_conditional"]
    summary = {"selected_count": 1}
    (pipeline_dir / "complete.json").write_text(
        json.dumps(
            {
                "call_receipts": [
                    {"call_id": call_id, "call_completion_sha256": call_id}
                    for call_id in expected_call_ids
                ]
            }
        ),
        encoding="utf-8",
    )
    for call_id in expected_call_ids:
        call_dir = tmp_path / "calls" / call_id
        call_dir.mkdir(parents=True)
        (call_dir / "call-contract.json").write_text(
            json.dumps(
                {
                    "call_id": call_id,
                    "pipeline_id": contract["pipeline_id"],
                    "experiment_contract_sha256": contract["experiment_contract_sha256"],
                }
            ),
            encoding="utf-8",
        )
        (call_dir / "complete.json").write_text(json.dumps({"call_id": call_id}), encoding="utf-8")
    monkeypatch.setattr(
        analyzer.iteration_harness,
        "_pipeline_completion",
        lambda observed_dir, observed_contract: (
            summary if observed_dir == pipeline_dir and observed_contract == contract else None
        ),
    )
    monkeypatch.setattr(
        analyzer.iteration_harness,
        "_expected_pipeline_call_ids",
        lambda observed_contract, observed_summary: (
            expected_call_ids
            if observed_contract == contract and observed_summary == summary
            else []
        ),
    )

    assert analyzer._validate_pipeline_completion_binding(tmp_path, pipeline_dir, contract) == (
        summary,
        json.loads((pipeline_dir / "complete.json").read_text()),
    )

    bound_call_dir = tmp_path / "calls" / expected_call_ids[0]
    call_contract_path = bound_call_dir / "call-contract.json"
    call_completion_path = bound_call_dir / "complete.json"
    original_contract = json.loads(call_contract_path.read_text())
    original_completion = json.loads(call_completion_path.read_text())
    for target, key, bad_value, message in (
        (call_contract_path, "call_id", "call_other", "call contract ID drifted"),
        (call_contract_path, "pipeline_id", "pipeline_other", "call/pipeline binding drifted"),
        (
            call_contract_path,
            "experiment_contract_sha256",
            "0" * 64,
            "call/experiment contract binding drifted",
        ),
        (call_completion_path, "call_id", "call_other", "call completion ID drifted"),
    ):
        original = original_contract if target == call_contract_path else original_completion
        mutated = {**original, key: bad_value}
        target.write_text(json.dumps(mutated), encoding="utf-8")
        with pytest.raises(analyzer.AnalysisError, match=message):
            analyzer._validate_pipeline_completion_binding(tmp_path, pipeline_dir, contract)
        target.write_text(json.dumps(original), encoding="utf-8")

    (pipeline_dir / "complete.json").write_text(
        json.dumps(
            {
                "call_receipts": [
                    {"call_id": expected_call_ids[1], "call_completion_sha256": "wrong"},
                    {"call_id": expected_call_ids[0], "call_completion_sha256": "wrong"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(analyzer.AnalysisError, match="call inventory drifted"):
        analyzer._validate_pipeline_completion_binding(tmp_path, pipeline_dir, contract)


def test_runtime_preflight_receipt_inventory_is_verified_read_only(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "judge_run"
    receipt_path = run_dir / "infrastructure" / "preflight" / "checks" / "001" / "receipt.json"
    receipt = {"status": "passed", "check_number": 1}
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    completion_path = run_dir / "infrastructure" / "preflight" / "complete.json"
    completion_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "policy_version": "test",
                "passed_check": 1,
                "receipt_sha256": [{"relative_path": "checks/001/receipt.json", "sha256": digest}],
            }
        ),
        encoding="utf-8",
    )
    validations: list[int] = []
    monkeypatch.setattr(
        analyzer.judge_harness,
        "_validate_preflight_receipt",
        lambda _receipt, _prepared, number: validations.append(number),
    )
    prepared = SimpleNamespace(
        run_dir=run_dir,
        manifest={"runtime_preflight": {"policy_version": "test"}},
    )
    analyzer._verify_completed_runtime_preflight(prepared)
    assert validations == [1]

    receipt_path.write_text(
        json.dumps({"status": "passed", "check_number": 1, "tampered": True}),
        encoding="utf-8",
    )
    with pytest.raises(analyzer.AnalysisError, match="inventory"):
        analyzer._verify_completed_runtime_preflight(prepared)

    empty_run = tmp_path / "empty-judge-run"
    (empty_run / "infrastructure" / "preflight" / "checks").mkdir(parents=True)
    (empty_run / "infrastructure" / "preflight" / "complete.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "policy_version": "test",
                "passed_check": 1,
                "receipt_sha256": [],
            }
        ),
        encoding="utf-8",
    )
    empty_prepared = SimpleNamespace(
        run_dir=empty_run,
        manifest={"runtime_preflight": {"policy_version": "test"}},
    )
    with pytest.raises(analyzer.AnalysisError, match="has no checks"):
        analyzer._verify_completed_runtime_preflight(empty_prepared)


def test_report_escapes_model_text_and_uses_relative_links(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path / "evidence")
    analysis = analyzer.analyze_verified_experiment(verified)
    analysis["topics"][0]["topic_assessment"] = "<script>alert(1)</script>"
    output = tmp_path / "report" / "REPORT.html"
    rendered = analyzer.render_html_report(analysis, verified, output)

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "file://" not in rendered
    assert "../evidence/" in rendered
    assert "Selected-union 相对 coverage" in rendered
    assert "绝对 recall" not in rendered
    assert "generator-real / medium" in rendered
    assert "judge_01: judge-a / max" in rendered
    assert "judge_02: judge-b / max" in rendered
    assert "source_a.ts" in rendered
    assert "v2 的证据边界更清楚" in rendered
    assert "仅限合成 fixture" in rendered
    assert "结构清楚" in rendered
    assert "样本有限" in rendered
    assert "Sol Medium/medium" not in rendered


def test_report_write_is_idempotent_but_immutable(analyzer: ModuleType, tmp_path: Path) -> None:
    verified = _synthetic_verified(analyzer, tmp_path / "experiment")
    analysis = analyzer.analyze_verified_experiment(verified)
    output_dir = tmp_path / "report"
    first = analyzer.write_report(analysis, verified, output_dir)
    second = analyzer.write_report(analysis, verified, output_dir)
    assert first == second
    first[1].write_text("tampered", encoding="utf-8")
    with pytest.raises(analyzer.AnalysisError, match="refusing to overwrite immutable"):
        analyzer.write_report(analysis, verified, output_dir)


def test_efficiency_gate_requires_explicit_quality_tradeoff(analyzer: ModuleType) -> None:
    quality = {"v2_minus_v1_x100": 3.0}
    evidence = {"v2_outward_exact_evidence_failure_count": 0}
    efficiency = {
        "successful_artifact_lower_bound_v2_to_v1_ratio": {
            "elapsed_seconds": 3.2,
            "reported_total_tokens": 2.5,
        },
        "unbound_repair_cost": {
            "present": False,
            "completion_bound_repair_attempt_count": 0,
        },
    }
    acceptance = analyzer._acceptance(quality, evidence, efficiency)
    gate = acceptance["gates"]["efficiency_within_3x_or_quality_justified"]
    assert gate["status"] == "conditional_quality_justification_required"
    assert "quality gain" in gate["reason"]
    assert acceptance["recommendation"].startswith("conditional_v2")


def test_interval_match_is_one_to_one(analyzer: ModuleType) -> None:
    result = analyzer._interval_match_f1([(0, 100), (0, 100)], [(0, 100)])
    assert result == {
        "iou_threshold": 0.5,
        "matches": 1,
        "precision": 0.5,
        "relative_coverage": 1.0,
        "f1": pytest.approx(2 / 3, abs=0.001),
    }
