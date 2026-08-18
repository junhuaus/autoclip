# ruff: noqa: RUF001
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

SCRIPT_PATH = Path(__file__).with_name("analyze_iteration.py")


@pytest.fixture(scope="module")
def analyzer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("liveclip_iteration2_analysis_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    contracts_path = SCRIPT_PATH.with_name("contracts.py")
    module._test_contracts_module = module._verified_python_module(
        module_name="liveclip_iteration2_analysis_test_contracts",
        source_path=contracts_path,
        source_bytes=contracts_path.read_bytes(),
    )
    return module


def _metric(analyzer: ModuleType, numerator: int, denominator: int = 1) -> dict[str, Any]:
    return analyzer._metric(Fraction(numerator, denominator))


def _highlight(candidate_id: str, index: int, *, contender: bool) -> dict[str, Any]:
    phrase = f"第{index}条原话保留完整条件和结论"
    value = {
        "candidate_id": candidate_id,
        "source_start_ms": index * 100_000,
        "source_end_ms": index * 100_000 + 50_000,
        "topic": f"话题{index}",
        "title": f"标题{index}",
        "hook": f"钩子{index}",
        "script_description": f"描述{index}",
        "selection_reason": "确定性选择理由",
    }
    if contender:
        value.update(evidence_quote=phrase, source_sentence=phrase)
    else:
        value["highlight_sentence"] = phrase
    return value


def _synthetic_verified(analyzer: ModuleType, root: Path) -> Any:
    generators = []
    judges = []
    candidates_by_source: dict[str, dict[str, dict[str, Any]]] = {}
    source_sha256_by_id: dict[str, str] = {}
    source_metadata_by_id: dict[str, dict[str, Any]] = {}
    records_by_source: dict[str, list[Any]] = {}
    for source_index in range(3):
        source_id = f"source_{source_index}"
        source_sha = f"{source_index + 1:064x}"
        source_sha256_by_id[source_id] = source_sha
        source_metadata_by_id[source_id] = {
            "source_sha256": source_sha,
            "filename": f"source-{source_index}.mp4",
        }
        candidate_ids = [f"candidate_{source_index}_{index:02d}" for index in range(8)]
        candidates_by_source[source_id] = {
            candidate_id: {
                "candidate_id": candidate_id,
                "text": f"前文，第{index}条原话保留完整条件和结论，后文。",
            }
            for index, candidate_id in enumerate(candidate_ids)
        }
        source_records = []
        for arm in (analyzer.BASELINE, analyzer.CONTENDER):
            for repeat in (1, 2):
                pipeline_id = f"pipeline_{source_index}_{arm}_{repeat}"
                contender = arm == analyzer.CONTENDER
                highlights = [
                    _highlight(candidate_id, index, contender=contender)
                    for index, candidate_id in enumerate(candidate_ids)
                ]
                result = {
                    "selection_summary": "合成组合",
                    "highlights": highlights,
                }
                record = analyzer.GeneratorRecord(
                    pipeline_id=pipeline_id,
                    source_id=source_id,
                    source_sha256=source_sha,
                    arm=arm,
                    repeat=repeat,
                    result=result,
                    validation={},
                    summary={},
                    all_attempt_usage={
                        "input_tokens": 100 if arm == analyzer.BASELINE else 200,
                        "cached_input_tokens": 0,
                        "output_tokens": 100 if arm == analyzer.BASELINE else 200,
                        "reasoning_output_tokens": 0,
                        "reported_total_tokens": 200 if arm == analyzer.BASELINE else 400,
                    },
                    all_attempt_elapsed_seconds=Fraction(10 if arm == analyzer.BASELINE else 20),
                    normal_model_call_count=1 if arm == analyzer.BASELINE else 2,
                    total_model_attempt_count=1 if arm == analyzer.BASELINE else 2,
                    selected_count=8,
                    underfilled_due_to_quality=False,
                    result_path=root / pipeline_id / "result.json",
                    completion_path=root / pipeline_id / "complete.json",
                )
                generators.append(record)
                source_records.append(record)
        records_by_source[source_id] = source_records

        for judge_id in analyzer.JUDGE_IDS:
            mapping: dict[str, str] = {}
            evaluations = []
            computed: dict[str, dict[str, int]] = {}
            for system_index, record in enumerate(source_records):
                anonymous_id = f"system_{source_index}_{judge_id}_{system_index}"
                mapping[anonymous_id] = record.pipeline_id
                values = {field: 3 for field in analyzer.SYSTEM_SCORE_FIELDS}
                evaluations.append({"anonymous_system_id": anonymous_id, **values})
                computed[anonymous_id] = {
                    "weighted_numerator": sum(
                        analyzer.SYSTEM_SCORE_WEIGHTS[field] * score
                        for field, score in values.items()
                    ),
                    "denominator": 4,
                }
            judges.append(
                analyzer.JudgeRecord(
                    source_id=source_id,
                    source_sha256=source_sha,
                    judge_id=judge_id,
                    result={"system_evaluations": evaluations},
                    validation={"computed_system_quality": computed},
                    binding={"anonymous_system_to_pipeline": mapping},
                    result_path=root / source_id / judge_id / "result.json",
                    completion_path=root / source_id / judge_id / "complete.json",
                )
            )

    return analyzer.VerifiedExperiment(
        experiment_dir=root,
        judge_run_dir=root / "judge-run",
        experiment_id="exp_fixture",
        evaluation_contract={"human_review_mode": "diagnostic_not_required"},
        evaluation_contract_sha256="a" * 64,
        source_ids=tuple(sorted(source_sha256_by_id)),
        source_sha256_by_id=source_sha256_by_id,
        source_metadata_by_id=source_metadata_by_id,
        candidates_by_source=candidates_by_source,
        generators=tuple(generators),
        judges=tuple(judges),
        global_unblind_path=root / "judge-run/unblind/global-unblind-manifest.json",
        feedback_release={
            "mode": "diagnostic_not_required",
            "status": "waived",
            "waiver_commitment_sha256": "b" * 64,
            "reason": "pre-frozen diagnostic waiver",
        },
        contracts_module=analyzer._test_contracts_module,
    )


def _parts(analyzer: ModuleType, verified: Any) -> tuple[Any, ...]:
    quality = analyzer._quality_analysis(verified)
    deterministic = analyzer._deterministic_metrics(verified)
    evidence = analyzer._evidence_and_adaptive_selection(verified)
    efficiency = analyzer._efficiency(verified)
    disagreement = analyzer._judge_disagreement(verified, quality)
    return quality, deterministic, evidence, efficiency, disagreement


def test_round_half_up_is_display_only(analyzer: ModuleType) -> None:
    assert analyzer._display_fraction(Fraction(2469, 2000)) == "1.235"
    assert analyzer._display_fraction(Fraction(-2469, 2000)) == "-1.235"
    metric = analyzer._metric(Fraction(1, 3))
    assert metric == {"numerator": 1, "denominator": 3, "display": "0.333"}
    assert analyzer._metric_fraction(metric, "fixture") == Fraction(1, 3)


def test_quality_uses_new_fields_and_exact_source_first_arithmetic(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    quality = analyzer._quality_analysis(verified)
    assert quality["arms"][analyzer.BASELINE]["source_first_macro_x100"] == _metric(analyzer, 75)
    assert quality["arms"][analyzer.CONTENDER]["source_first_macro_x100"] == _metric(analyzer, 75)
    dimensions = quality["arms"][analyzer.CONTENDER]["source_first_dimensions_x100"]
    assert set(dimensions) == {
        "valuable_discovery_x100",
        "judge_semantic_opportunity_coverage_x100",
        "precision_x100",
        "portfolio_coherence_x100",
        "editorial_readiness_x100",
    }
    assert "coverage_x100" not in dimensions
    assert "discovery_x100" not in dimensions
    assert "stability_x100" not in dimensions


def test_unique_source_sha256_is_the_only_source_macro_key(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    result = analyzer.analyze_verified_experiment(_synthetic_verified(analyzer, tmp_path))
    source_keys = set(result["quality"]["arms"][analyzer.CONTENDER]["by_unique_source_sha256"])
    assert source_keys == {f"{index:064x}" for index in (1, 2, 3)}
    assert not source_keys & {"source_0", "source_1", "source_2"}


def test_efficiency_uses_equal_source_macro_of_per_source_ratios(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    first_source = "1".zfill(64)
    generators = []
    for record in verified.generators:
        if record.source_sha256 == first_source:
            cost = 1 if record.arm == analyzer.BASELINE else 10
        else:
            cost = 100
        usage = {**record.all_attempt_usage, "reported_total_tokens": cost}
        generators.append(
            replace(
                record,
                all_attempt_elapsed_seconds=Fraction(cost),
                all_attempt_usage=usage,
            )
        )
    uneven = replace(verified, generators=tuple(generators))

    efficiency = analyzer._efficiency(uneven)

    assert analyzer._metric_fraction(
        efficiency["iteration2_to_fresh_v1_all_attempt_elapsed_ratio"],
        "elapsed ratio",
    ) == Fraction(4)
    assert analyzer._metric_fraction(
        efficiency["iteration2_to_fresh_v1_all_attempt_reported_total_token_ratio"],
        "token ratio",
    ) == Fraction(4)


def test_full_metric_names_never_regress_to_bare_coverage(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    result = analyzer.analyze_verified_experiment(_synthetic_verified(analyzer, tmp_path))

    keys: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            keys.update(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(result)
    assert "coverage" not in keys
    assert "coverage_x4" not in keys
    assert "relative_coverage" not in keys
    assert any("judge_semantic_opportunity_coverage" in key for key in keys)
    assert any("deterministic_relative_selected_union_candidate_coverage" in key for key in keys)


def test_all_boundary_gates_pass_exactly_and_only_advance_to_holdout(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    quality, deterministic, evidence, efficiency, disagreement = _parts(analyzer, verified)
    quality["iteration2_minus_fresh_v1_x100"] = _metric(analyzer, -2)
    quality["precision_iteration2_minus_fresh_v1_x100"] = _metric(analyzer, -2)
    quality["editorial_readiness_iteration2_minus_fresh_v1_x100"] = _metric(analyzer, -2)
    quality["worst_unique_source_sha256_delta_x100"] = _metric(analyzer, -5)
    deterministic["source_first_macro_sampling_stability"][analyzer.BASELINE] = {
        "candidate_jaccard": _metric(analyzer, 4, 5),
        "interval_f1": _metric(analyzer, 4, 5),
    }
    deterministic["source_first_macro_sampling_stability"][analyzer.CONTENDER] = {
        "candidate_jaccard": _metric(analyzer, 3, 4),
        "interval_f1": _metric(analyzer, 3, 4),
    }
    efficiency["iteration2_to_fresh_v1_all_attempt_elapsed_ratio"] = _metric(analyzer, 3)
    efficiency["iteration2_to_fresh_v1_all_attempt_reported_total_token_ratio"] = _metric(
        analyzer, 3
    )
    disagreement["mean_absolute_quality_difference_x100"] = _metric(analyzer, 10)
    disagreement["maximum_source_arm_absolute_quality_difference_x100"] = _metric(analyzer, 20)
    acceptance = analyzer._acceptance(quality, deterministic, evidence, efficiency, disagreement)
    assert all(gate["status"] == "passed" for gate in acceptance["gates"].values())
    assert acceptance["outcome"] == "advance_iteration2_to_frozen_holdout"
    assert acceptance["holdout_only"] is True
    assert acceptance["production_decision"] == "unchanged"


@pytest.mark.parametrize(
    ("mutation", "gate"),
    [
        ("quality", "quality_noninferiority"),
        ("precision_absolute", "precision_absolute_and_noninferiority"),
        ("precision_delta", "precision_absolute_and_noninferiority"),
        ("editorial_absolute", "editorial_readiness_absolute_and_noninferiority"),
        ("editorial_delta", "editorial_readiness_absolute_and_noninferiority"),
        ("worst_source", "worst_unique_source_noninferiority"),
        ("candidate_jaccard", "candidate_jaccard_noninferiority"),
        ("interval_f1", "interval_f1_noninferiority"),
        ("elapsed", "all_attempt_efficiency_within_3x"),
        ("tokens", "all_attempt_efficiency_within_3x"),
    ],
)
def test_fractional_gate_epsilon_fails_without_display_rounding(
    analyzer: ModuleType, tmp_path: Path, mutation: str, gate: str
) -> None:
    quality, deterministic, evidence, efficiency, disagreement = _parts(
        analyzer, _synthetic_verified(analyzer, tmp_path)
    )
    epsilon = Fraction(1, 1000)
    if mutation == "quality":
        quality["iteration2_minus_fresh_v1_x100"] = analyzer._metric(-2 - epsilon)
    elif mutation == "precision_absolute":
        quality["arms"][analyzer.CONTENDER]["source_first_dimensions_x100"]["precision_x100"] = (
            analyzer._metric(75 - epsilon)
        )
    elif mutation == "precision_delta":
        quality["precision_iteration2_minus_fresh_v1_x100"] = analyzer._metric(-2 - epsilon)
    elif mutation == "editorial_absolute":
        quality["arms"][analyzer.CONTENDER]["source_first_dimensions_x100"][
            "editorial_readiness_x100"
        ] = analyzer._metric(75 - epsilon)
    elif mutation == "editorial_delta":
        quality["editorial_readiness_iteration2_minus_fresh_v1_x100"] = analyzer._metric(
            -2 - epsilon
        )
    elif mutation == "worst_source":
        quality["worst_unique_source_sha256_delta_x100"] = analyzer._metric(-5 - epsilon)
    elif mutation == "candidate_jaccard":
        deterministic["source_first_macro_sampling_stability"][analyzer.BASELINE][
            "candidate_jaccard"
        ] = analyzer._metric(1)
        deterministic["source_first_macro_sampling_stability"][analyzer.CONTENDER][
            "candidate_jaccard"
        ] = analyzer._metric(Fraction(19, 20) - epsilon)
    elif mutation == "interval_f1":
        deterministic["source_first_macro_sampling_stability"][analyzer.BASELINE]["interval_f1"] = (
            analyzer._metric(1)
        )
        deterministic["source_first_macro_sampling_stability"][analyzer.CONTENDER][
            "interval_f1"
        ] = analyzer._metric(Fraction(19, 20) - epsilon)
    elif mutation == "elapsed":
        efficiency["iteration2_to_fresh_v1_all_attempt_elapsed_ratio"] = analyzer._metric(
            3 + epsilon
        )
    else:
        efficiency["iteration2_to_fresh_v1_all_attempt_reported_total_token_ratio"] = (
            analyzer._metric(3 + epsilon)
        )
    acceptance = analyzer._acceptance(quality, deterministic, evidence, efficiency, disagreement)
    assert acceptance["gates"][gate]["status"] == "failed"
    assert acceptance["outcome"] == "reject_iteration2"


@pytest.mark.parametrize(
    ("mean", "maximum"),
    [(Fraction(10001, 1000), 20), (10, Fraction(20001, 1000))],
)
def test_judge_disagreement_beyond_either_bound_is_inconclusive(
    analyzer: ModuleType, tmp_path: Path, mean: Fraction, maximum: Fraction
) -> None:
    quality, deterministic, evidence, efficiency, disagreement = _parts(
        analyzer, _synthetic_verified(analyzer, tmp_path)
    )
    disagreement["mean_absolute_quality_difference_x100"] = analyzer._metric(mean)
    disagreement["maximum_source_arm_absolute_quality_difference_x100"] = analyzer._metric(maximum)
    acceptance = analyzer._acceptance(quality, deterministic, evidence, efficiency, disagreement)
    assert acceptance["gates"]["judge_agreement_bound"]["status"] == "inconclusive"
    assert acceptance["outcome"] == "inconclusive_iteration2"


def test_judge_inconclusive_takes_precedence_over_non_judge_rejection(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    quality, deterministic, evidence, efficiency, disagreement = _parts(
        analyzer, _synthetic_verified(analyzer, tmp_path)
    )
    quality["iteration2_minus_fresh_v1_x100"] = analyzer._metric(-3)
    disagreement["mean_absolute_quality_difference_x100"] = analyzer._metric(11)
    acceptance = analyzer._acceptance(quality, deterministic, evidence, efficiency, disagreement)
    assert acceptance["gates"]["quality_noninferiority"]["status"] == "failed"
    assert acceptance["gates"]["judge_agreement_bound"]["status"] == "inconclusive"
    assert acceptance["outcome"] == "inconclusive_iteration2"


def test_pipeline_judge_differences_do_not_cancel_before_mean(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    quality = analyzer._quality_analysis(verified)
    source_sha = verified.generators[0].source_sha256
    rows = [
        row
        for row in quality["pipeline_scores"]
        if row["source_sha256"] == source_sha and row["arm"] == analyzer.BASELINE
    ]
    rows.sort(key=lambda row: row["repeat"])
    rows[0]["judge_01"] = analyzer._metric(85)
    rows[0]["judge_02"] = analyzer._metric(65)
    rows[1]["judge_01"] = analyzer._metric(65)
    rows[1]["judge_02"] = analyzer._metric(85)

    disagreement = analyzer._judge_disagreement(verified, quality)
    assert analyzer._metric_fraction(
        disagreement["mean_absolute_quality_difference_x100"], "pipeline mean"
    ) == Fraction(10, 3)
    matching_cell = next(
        row
        for row in disagreement["by_unique_source_sha256_and_arm"]
        if row["source_sha256"] == source_sha and row["arm"] == analyzer.BASELINE
    )
    assert (
        analyzer._metric_fraction(
            matching_cell["absolute_difference_x100"], "source/arm repeat mean"
        )
        == 0
    )


def test_underfilled_portfolio_can_never_advance(analyzer: ModuleType, tmp_path: Path) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    target = next(record for record in verified.generators if record.arm == analyzer.CONTENDER)
    object.__setattr__(target, "underfilled_due_to_quality", True)
    object.__setattr__(target, "selected_count", 7)
    object.__setattr__(
        target,
        "result",
        {**target.result, "highlights": target.result["highlights"][:7]},
    )
    result = analyzer.analyze_verified_experiment(verified)
    assert (
        result["evidence_and_adaptive_selection"]["iteration2_adaptive_portfolio_failure_count"]
        == 1
    )
    assert result["acceptance"]["gates"]["adaptive_portfolio_count"]["status"] == "failed"
    assert result["acceptance"]["outcome"] == "reject_iteration2"


def test_exact_quote_and_source_sentence_are_recomputed(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    target = next(record for record in verified.generators if record.arm == analyzer.CONTENDER)
    target.result["highlights"][0]["source_sentence"] = "模型重新概括并扩张了原意"
    result = analyzer.analyze_verified_experiment(verified)
    assert (
        result["evidence_and_adaptive_selection"][
            "iteration2_outward_exact_quote_or_source_sentence_failure_count"
        ]
        == 1
    )
    assert result["acceptance"]["outcome"] == "reject_iteration2"


def test_all_attempt_cost_includes_repair_usage(analyzer: ModuleType, tmp_path: Path) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    target = next(record for record in verified.generators if record.arm == analyzer.CONTENDER)
    object.__setattr__(target, "all_attempt_elapsed_seconds", Fraction(81))
    object.__setattr__(
        target,
        "all_attempt_usage",
        {**target.all_attempt_usage, "reported_total_tokens": 1601},
    )
    result = analyzer.analyze_verified_experiment(verified)
    assert (
        analyzer._metric_fraction(
            result["efficiency"]["iteration2_to_fresh_v1_all_attempt_elapsed_ratio"],
            "elapsed",
        )
        > 3
    )
    assert result["acceptance"]["gates"]["all_attempt_efficiency_within_3x"]["status"] == "failed"


def test_interval_matching_is_one_to_one_and_exact(analyzer: ModuleType) -> None:
    result = analyzer._interval_match_f1([(0, 100), (10, 90)], [(0, 100)])
    assert result["matches"] == 1
    assert analyzer._metric_fraction(result["f1"], "f1") == Fraction(2, 3)


def test_evaluation_contract_copy_and_hash_are_exact(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    frozen_artifact = repository_root / "analyze_iteration.py"
    frozen_artifact.parent.mkdir(parents=True)
    frozen_artifact.write_bytes(b"frozen analyzer bytes\n")
    contract = {
        "schema_version": "liveclip-highlight-evaluation-contract.iteration-2.v1",
        "contract_version": "highlight-agent-skill-v2-iteration-2-evaluation-v1",
        "iteration_id": "highlight-agent-skill-v2-iteration-2",
        "status": "frozen_before_any_iteration2_generator_output",
        "human_review_mode": "diagnostic_not_required",
        "human_feedback_waiver": {},
        "artifacts": {
            "analyze_iteration.py": {
                "sha256": analyzer._sha256_file(frozen_artifact),
                "size_bytes": frozen_artifact.stat().st_size,
            }
        },
        "generator": {},
        "judge": {},
        "aggregation": {},
        "acceptance_gates": {},
        "outcomes": {},
    }
    repository = repository_root / "evaluation-contract.json"
    frozen = tmp_path / "experiment/frozen/evaluation-contract.json"
    repository.write_text(json.dumps(contract), encoding="utf-8")
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(repository.read_bytes())
    monkeypatch.setattr(analyzer, "EVALUATION_CONTRACT_PATH", repository)
    monkeypatch.setattr(analyzer, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(analyzer, "REQUIRED_EVALUATION_ARTIFACTS", {"analyze_iteration.py"})
    loaded, digest, size, artifacts = analyzer._load_evaluation_contract(tmp_path / "experiment")
    assert loaded == contract
    assert digest == analyzer._sha256_bytes(repository.read_bytes())
    assert size == len(repository.read_bytes())
    assert artifacts == {"analyze_iteration.py": b"frozen analyzer bytes\n"}
    frozen.write_text(json.dumps({**contract, "status": "changed"}), encoding="utf-8")
    with pytest.raises(analyzer.AnalysisError, match="differs"):
        analyzer._load_evaluation_contract(tmp_path / "experiment")


def test_evaluation_contract_detects_analyzer_self_hash_drift(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    analyzer_copy = repository_root / "analyze_iteration.py"
    analyzer_copy.parent.mkdir(parents=True)
    analyzer_copy.write_bytes(b"pre-registered analyzer\n")
    contract = {
        "artifacts": {
            "analyze_iteration.py": {
                "sha256": analyzer._sha256_file(analyzer_copy),
                "size_bytes": analyzer_copy.stat().st_size,
            }
        }
    }
    monkeypatch.setattr(analyzer, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(analyzer, "REQUIRED_EVALUATION_ARTIFACTS", {"analyze_iteration.py"})
    analyzer._verify_repository_artifact_index(contract)
    analyzer_copy.write_bytes(b"changed after freeze\n")
    with pytest.raises(analyzer.AnalysisError, match=r"artifact (size|hash) drifted"):
        analyzer._verify_repository_artifact_index(contract)


def test_pinned_dependencies_execute_verified_bytes_not_swapped_paths(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "executed.txt"
    contracts_path = tmp_path / analyzer.CONTRACTS_ARTIFACT
    judge_path = tmp_path / analyzer.JUDGE_HARNESS_ARTIFACT
    contracts_path.parent.mkdir(parents=True)
    malicious = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n"
    contracts_path.write_text(malicious, encoding="utf-8")
    judge_path.write_text(malicious, encoding="utf-8")
    monkeypatch.setattr(analyzer, "REPOSITORY_ROOT", tmp_path)

    contracts, judge = analyzer._load_pinned_dependencies(
        {
            analyzer.CONTRACTS_ARTIFACT: (
                b"def exact_quote_receipt(quote, source):\n    return {'status': 'passed'}\n"
            ),
            analyzer.JUDGE_HARNESS_ARTIFACT: b"FROZEN_JUDGE = True\n",
        }
    )

    assert contracts.exact_quote_receipt("x", "x") == {"status": "passed"}
    assert judge.FROZEN_JUDGE is True
    assert not sentinel.exists()


def test_analyzer_has_no_unverified_local_imports() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "\nimport contracts" not in source
    assert "\nimport run_iteration" not in source
    assert "\nimport run_judges" not in source


@pytest.mark.parametrize("unsafe_relative", ["../escape.py", "/absolute.py", "a/../b.py"])
def test_evaluation_artifact_index_rejects_path_escape(
    analyzer: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_relative: str,
) -> None:
    monkeypatch.setattr(analyzer, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(analyzer, "REQUIRED_EVALUATION_ARTIFACTS", {unsafe_relative})
    contract = {"artifacts": {unsafe_relative: {"sha256": "0" * 64, "size_bytes": 0}}}
    with pytest.raises(analyzer.AnalysisError, match=r"escapes|normalized"):
        analyzer._verify_repository_artifact_index(contract)


def test_global_unblind_loader_is_not_reached_before_all_six_calls(
    analyzer: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_ids = [f"src_{index}" for index in range(3)]
    bundles = tuple(
        SimpleNamespace(
            source_id=source_id,
            pipeline_ids=tuple(f"pipeline_{index}_{position}" for position in range(4)),
            source_payload={},
        )
        for index, source_id in enumerate(source_ids)
    )
    calls = {
        (source_id, judge_id): object()
        for source_id in source_ids
        for judge_id in analyzer.JUDGE_IDS
    }
    prepared = SimpleNamespace(
        run_dir=tmp_path / "judge-run",
        manifest={"evaluation_contract_sha256": "a" * 64},
        calls=calls,
        evaluation=SimpleNamespace(contract={}, contract_sha256="a" * 64),
        pipeline_reconstructor=lambda *_args: {},
        source_bundles=bundles,
    )
    reached = False

    def global_loader(_prepared: Any) -> dict[str, Any]:
        nonlocal reached
        reached = True
        return {}

    monkeypatch.setattr(
        analyzer,
        "_load_evaluation_contract",
        lambda _path: ({}, "a" * 64, 1, {}),
    )
    monkeypatch.setattr(analyzer, "_verify_evaluation_contract_binding", lambda *_: {})
    harness_error = type("HarnessError", (RuntimeError,), {})
    judge_harness = SimpleNamespace(
        GeneratorMatrixIncomplete=harness_error,
        IntegrityError=harness_error,
        JudgeValidationError=harness_error,
        prepare_judge_run=lambda _path: prepared,
        _load_source_bundles=lambda _path, _evaluation, **_kwargs: ("exp", bundles),
        load_verified_global_unblind=global_loader,
    )
    monkeypatch.setattr(
        analyzer,
        "_load_pinned_dependencies",
        lambda _artifacts: (analyzer._test_contracts_module, judge_harness),
    )
    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(analyzer.AnalysisIncomplete, match="6/6"):
        analyzer.load_verified_experiment(tmp_path)
    assert reached is False


def test_report_escapes_text_and_uses_only_full_metric_names(
    analyzer: ModuleType, tmp_path: Path
) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    analysis = analyzer.analyze_verified_experiment(verified)
    analysis["quality"]["score_definition"] = "<script>alert(1)</script>"
    rendered = analyzer.render_html_report(analysis, verified, tmp_path / "REPORT.html")
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "Judge semantic-opportunity coverage" in rendered
    assert "Deterministic relative selected-union candidate metric" in rendered
    assert "advance_iteration2_to_frozen_holdout" in rendered
    assert "production" in rendered.lower()


def test_report_write_is_idempotent_and_immutable(analyzer: ModuleType, tmp_path: Path) -> None:
    verified = _synthetic_verified(analyzer, tmp_path)
    analysis = analyzer.analyze_verified_experiment(verified)
    output = tmp_path / "report"
    first = analyzer.write_report(analysis, verified, output)
    second = analyzer.write_report(analysis, verified, output)
    assert first == second
    changed = copy.deepcopy(analysis)
    changed["acceptance"]["outcome"] = "reject_iteration2"
    with pytest.raises(analyzer.AnalysisError, match="refusing to overwrite"):
        analyzer.write_report(changed, verified, output)
