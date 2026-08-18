#!/usr/bin/env python3
"""Build the Skill Creator offline review viewer for the LiveClip benchmark.

This adapter is intentionally read-only with respect to frozen benchmark inputs and
results.  It refuses to produce a partial viewer unless every configured generator
and both blind judges are complete for every replicate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BENCHMARK_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = BENCHMARK_ROOT / "eval-review"
WORKSPACE_RELATIVE = Path("workspace/iteration-1")
GENERATOR_ORDER = ("terra_medium", "sol_medium", "sol_high")
JUDGE_ORDER = ("terra_max", "sol_max")
PRIMARY_SUMMARY_CONFIGS = ("sol_medium", "sol_high")
QUALITY_THRESHOLD = 80.0
VIEWER_SCRIPT = (
    Path.home()
    / ".codex/plugins/cache/claude-cowork/anthropic-skills/1.0.0/skills/"
    "skill-creator/eval-viewer/generate_review.py"
)


class IncompleteBenchmarkError(RuntimeError):
    """The viewer must not be generated from incomplete benchmark evidence."""


def _read_json(path: Path, failures: list[str]) -> dict[str, Any]:
    if not path.is_file():
        failures.append(f"missing: {path.relative_to(BENCHMARK_ROOT)}")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"invalid JSON: {path.relative_to(BENCHMARK_ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        failures.append(f"expected JSON object: {path.relative_to(BENCHMARK_ROOT)}")
        return {}
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _artifact_paths(rep_dir: Path) -> Iterable[Path]:
    yield rep_dir / "frozen-input.json"
    yield rep_dir / "provenance.json"
    yield rep_dir / "replicate-summary.json"
    for config in GENERATOR_ORDER:
        base = rep_dir / "generators" / config
        yield base / "result.json"
        yield base / "validation.json"
        yield base / "call-metadata.json"
    for judge in JUDGE_ORDER:
        base = rep_dir / "judges" / judge
        yield base / "input.json"
        yield base / "result.json"
        yield base / "validation.json"
        yield base / "call-metadata.json"
        yield base / "mapping.disclosed-after-judging.json"


def _validate_call_metadata(
    metadata: Mapping[str, Any],
    result_path: Path,
    expected: Mapping[str, Any],
    label: str,
    failures: list[str],
) -> None:
    _require(metadata.get("model") == expected.get("model"), f"{label}: model mismatch", failures)
    _require(
        metadata.get("reasoning_effort") == expected.get("effort"),
        f"{label}: reasoning effort mismatch",
        failures,
    )
    expected_hash = metadata.get("result_sha256")
    if result_path.is_file() and isinstance(expected_hash, str):
        _require(_sha256(result_path) == expected_hash, f"{label}: result hash mismatch", failures)
    else:
        failures.append(f"{label}: missing result hash")


def _validate_replicate(
    rep_dir: Path,
    case: Mapping[str, Any],
    protocol: Mapping[str, Any],
    failures: list[str],
) -> None:
    relative = rep_dir.relative_to(BENCHMARK_ROOT)
    missing_paths = [path for path in _artifact_paths(rep_dir) if not path.is_file()]
    if missing_paths:
        failures.extend(
            f"missing: {path.relative_to(BENCHMARK_ROOT)}" for path in missing_paths
        )
        return

    provenance = _read_json(rep_dir / "provenance.json", failures)
    _require(
        provenance.get("case_id") == case.get("case_id"),
        f"{relative}: wrong case_id",
        failures,
    )
    _require(
        provenance.get("include_in_primary_aggregate")
        == case.get("include_in_primary_aggregate"),
        f"{relative}: primary/diagnostic role mismatch",
        failures,
    )

    generator_models = protocol.get("generator_models", {})
    judge_models = protocol.get("judge_models", {})
    for config in GENERATOR_ORDER:
        base = rep_dir / "generators" / config
        result = _read_json(base / "result.json", failures)
        validation = _read_json(base / "validation.json", failures)
        metadata = _read_json(base / "call-metadata.json", failures)
        expected = generator_models.get(config, {}) if isinstance(generator_models, dict) else {}
        _validate_call_metadata(
            metadata,
            base / "result.json",
            expected,
            f"{relative}/generators/{config}",
            failures,
        )
        highlights = result.get("highlights", [])
        _require(
            isinstance(highlights, list),
            f"{relative}/{config}: highlights is not a list",
            failures,
        )
        selected_count = validation.get("selected_count")
        _require(
            isinstance(highlights, list) and selected_count == len(highlights),
            f"{relative}/{config}: selected_count mismatch",
            failures,
        )
        _require(
            validation.get("schema_and_candidate_gate") == "passed",
            f"{relative}/{config}: schema/candidate gate did not pass",
            failures,
        )

    for judge in JUDGE_ORDER:
        base = rep_dir / "judges" / judge
        result = _read_json(base / "result.json", failures)
        validation = _read_json(base / "validation.json", failures)
        metadata = _read_json(base / "call-metadata.json", failures)
        mapping = _read_json(base / "mapping.disclosed-after-judging.json", failures)
        judge_input = _read_json(base / "input.json", failures)
        expected = judge_models.get(judge, {}) if isinstance(judge_models, dict) else {}
        _validate_call_metadata(
            metadata,
            base / "result.json",
            expected,
            f"{relative}/judges/{judge}",
            failures,
        )
        _require(
            validation.get("cluster_coverage_gate") == "passed",
            f"{relative}/{judge}: cluster coverage gate did not pass",
            failures,
        )
        system_mapping = mapping.get("anonymous_system_mapping", {})
        _require(
            isinstance(system_mapping, dict)
            and set(system_mapping.values()) == set(GENERATOR_ORDER),
            f"{relative}/{judge}: disclosed mapping does not cover all generators",
            failures,
        )
        _require(
            isinstance(result.get("clusters"), list),
            f"{relative}/{judge}: no clusters",
            failures,
        )
        _require(
            isinstance(judge_input.get("selected_candidate_evidence"), list),
            f"{relative}/{judge}: no selected candidate evidence",
            failures,
        )


def _load_and_validate() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    failures: list[str] = []
    cases_document = _read_json(BENCHMARK_ROOT / "cases.json", failures)
    protocol = _read_json(BENCHMARK_ROOT / "protocol.json", failures)
    evals_document = _read_json(BENCHMARK_ROOT / "evals/evals.json", failures)

    cases = cases_document.get("cases", [])
    _require(isinstance(cases, list) and bool(cases), "cases.json has no cases", failures)
    for case in cases if isinstance(cases, list) else []:
        if not isinstance(case, dict):
            failures.append("cases.json contains a non-object case")
            continue
        case_id = case.get("case_id")
        replicate_count = case.get("replicates")
        if not isinstance(case_id, str) or not isinstance(replicate_count, int):
            failures.append(f"invalid case entry: {case!r}")
            continue
        for number in range(1, replicate_count + 1):
            rep_dir = BENCHMARK_ROOT / "results" / case_id / f"r{number:03d}"
            _validate_replicate(rep_dir, case, protocol, failures)

    if failures:
        details = "\n".join(f"  - {item}" for item in failures)
        raise IncompleteBenchmarkError(
            f"benchmark is incomplete or invalid ({len(failures)} issue(s)); "
            f"REVIEW.html was not generated:\n{details}"
        )
    return cases_document, protocol, evals_document


def _deanonymized_judge_view(
    rep_dir: Path,
    judge: str,
    config: str,
) -> dict[str, Any]:
    base = rep_dir / "judges" / judge
    result = json.loads((base / "result.json").read_text(encoding="utf-8"))
    validation = json.loads((base / "validation.json").read_text(encoding="utf-8"))
    mapping = json.loads(
        (base / "mapping.disclosed-after-judging.json").read_text(encoding="utf-8")
    )
    metadata = json.loads((base / "call-metadata.json").read_text(encoding="utf-8"))
    anonymous_id = next(
        key for key, value in mapping["anonymous_system_mapping"].items() if value == config
    )

    system_evaluation = next(
        item
        for item in result["system_evaluations"]
        if item["anonymous_system_id"] == anonymous_id
    )
    relevant_clusters: list[dict[str, Any]] = []
    for cluster in result["clusters"]:
        members = [
            {**member, "generator_config": config}
            for member in cluster["members"]
            if member["anonymous_system_id"] == anonymous_id
        ]
        if members:
            relevant_clusters.append(
                {
                    "alignment_confidence": cluster["alignment_confidence"],
                    "assessment": cluster["assessment"],
                    "canonical_topic": cluster["canonical_topic"],
                    "cluster_id": cluster["cluster_id"],
                    "members": members,
                }
            )

    preferred = [
        mapping["anonymous_system_mapping"][item] for item in result["preferred_system_ids"]
    ]
    return {
        "blind_identity_disclosed_after_judging": anonymous_id,
        "computed_total": validation["computed_total_by_model"][config],
        "generator_config": config,
        "judge": {
            "judge_config": judge,
            "model": metadata["model"],
            "reasoning_effort": metadata["reasoning_effort"],
            "request_id": metadata.get("request_id"),
        },
        "limitations": result["limitations"],
        "model_scores": validation["atomic_scores_by_model"][config],
        "preferred_generator_configs": preferred,
        "rank": preferred.index(config) + 1,
        "semantic_duplicate_rate": validation["semantic_duplicate_rate_by_model"][config],
        "system_evaluation": {**system_evaluation, "generator_config": config},
        "topic_clusters": relevant_clusters,
        "topic_count": validation["topic_count_by_model"][config],
        "verdict_reason": result["verdict_reason"],
    }


def _selected_evidence(
    rep_dir: Path,
    result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    judge_input = json.loads(
        (rep_dir / "judges/sol_max/input.json").read_text(encoding="utf-8")
    )
    evidence_by_id = {
        item["candidate_id"]: item for item in judge_input["selected_candidate_evidence"]
    }
    candidate_ids = [item["candidate_id"] for item in result["highlights"]]
    return [evidence_by_id[item] for item in candidate_ids]


def _has_video_viewing_claim(result: Mapping[str, Any]) -> tuple[bool, list[str]]:
    serialized = json.dumps(result, ensure_ascii=False)
    patterns = (
        "从画面中可以看出",
        "从视频画面可以看出",
        "画面显示主播",
        "视频中可以看到主播",
        "我看到画面",
    )
    matches = [item for item in patterns if item in serialized]
    return bool(matches), matches


def _make_grading(
    generator_result: Mapping[str, Any],
    generator_validation: Mapping[str, Any],
    judge_views: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    selected_count = generator_validation["selected_count"]
    unique_count = generator_validation["unique_candidate_count"]
    failed_quotes = generator_validation["failed_quote_count"]
    judge_totals = [float(item["computed_total"]) for item in judge_views.values()]
    judge_average = statistics.fmean(judge_totals)
    has_view_claim, view_claim_matches = _has_video_viewing_claim(generator_result)

    expectations = [
        {
            "text": "所有 candidate_id 均通过冻结候选白名单校验",
            "passed": generator_validation["schema_and_candidate_gate"] == "passed",
            "evidence": (
                "schema_and_candidate_gate="
                f"{generator_validation['schema_and_candidate_gate']}"
            ),
        },
        {
            "text": "方案选择 1-12 条且 candidate_id 不重复",
            "passed": 1 <= selected_count <= 12 and selected_count == unique_count,
            "evidence": f"selected={selected_count}, unique={unique_count}",
        },
        {
            "text": "所有高光语句通过绑定候选文本的自动追溯启发式检查",
            "passed": failed_quotes == 0,
            "evidence": (
                f"failed_quote_count={failed_quotes}; 该启发式不是人工逐字核验, "
                "高相似编辑句可能仍需复查"
            ),
        },
        {
            "text": "两名盲审 Judge 均完成 Topic 聚类、去重和该方案评分",
            "passed": len(judge_views) == len(JUDGE_ORDER)
            and all(item["topic_count"] >= 1 for item in judge_views.values()),
            "evidence": ", ".join(
                f"{name}: topics={view['topic_count']}, duplicate_rate="
                f"{view['semantic_duplicate_rate']}"
                for name, view in judge_views.items()
            ),
        },
        {
            "text": "未出现声称实际看过未提供视频画面的固定短语 (词法检查)",
            "passed": not has_view_claim,
            "evidence": (
                "未检测到固定短语; 仍需人工抽查"
                if not view_claim_matches
                else f"检测到: {', '.join(view_claim_matches)}"
            ),
        },
        {
            "text": f"双 Judge 平均总分达到 {QUALITY_THRESHOLD:.0f}/100",
            "passed": judge_average >= QUALITY_THRESHOLD,
            "evidence": (
                ", ".join(
                    f"{name}={float(view['computed_total']):.1f}"
                    for name, view in judge_views.items()
                )
                + f"; mean={judge_average:.1f}"
            ),
        },
    ]
    passed = sum(bool(item["passed"]) for item in expectations)
    total = len(expectations)
    return {
        "expectations": expectations,
        "summary": {
            "failed": total - passed,
            "pass_rate": passed / total,
            "passed": passed,
            "total": total,
        },
    }


def _stat(values: list[float]) -> dict[str, float]:
    return {
        "max": max(values),
        "mean": statistics.fmean(values),
        "min": min(values),
        "stddev": statistics.pstdev(values),
    }


def _source_macro_summary(
    benchmark_runs: list[dict[str, Any]],
    config: str,
    metric: str,
) -> dict[str, float]:
    primary = [
        item
        for item in benchmark_runs
        if item["configuration"] == config and item["include_in_primary_aggregate"]
    ]
    case_ids = sorted({item["case_id"] for item in primary})
    source_means = [
        statistics.fmean(
            float(item["result"][metric]) for item in primary if item["case_id"] == case_id
        )
        for case_id in case_ids
    ]
    return _stat(source_means)


def _make_benchmark(
    benchmark_runs: list[dict[str, Any]],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for config in PRIMARY_SUMMARY_CONFIGS:
        summary[config] = {
            "pass_rate": _source_macro_summary(benchmark_runs, config, "pass_rate"),
            "time_seconds": _source_macro_summary(benchmark_runs, config, "time_seconds"),
            "tokens": _source_macro_summary(benchmark_runs, config, "tokens"),
        }
    pass_rate_delta = (
        summary["sol_high"]["pass_rate"]["mean"]
        - summary["sol_medium"]["pass_rate"]["mean"]
    )
    summary["delta"] = {
        "pass_rate": f"{pass_rate_delta:+.2f}"
    }
    viewer_runs = [
        {
            key: value
            for key, value in item.items()
            if key not in {"case_id", "include_in_primary_aggregate"}
        }
        for item in benchmark_runs
    ]
    return {
        "metadata": {
            "evals_run": ["3 unique sources", "3 order variants", "1 diagnostic"],
            "executor_model": "three Codex configurations",
            "runs_per_configuration": 10,
            "skill_name": "liveclip-highlight-discovery-v1",
            "timestamp": protocol["created_at"],
        },
        "notes": [
            "主汇总只按三个唯一 source 先聚合 replicate, 再宏平均; "
            "D1 诊断和文件名别名权重为零。",
            "Bundled Skill Creator viewer 的顶部汇总只渲染两个配置, "
            "因此这里只放 Sol Medium 与 Sol High; Terra Medium 仍完整显示在每个 "
            "Eval 的三配置表和 Outputs 中。",
            "Pass Rate 是 6 项可审计门槛的通过率, 不等同于 Judge 连续质量分; "
            "两名 Judge 的原始分数和 Topic 证据在每个 Output 中。",
            "Tokens 使用 call metadata 的 input_tokens + output_tokens; "
            "reasoning_output_tokens 不重复相加。",
            "候选顺序每种只调用一次, replicate 反映顺序扰动与采样的合并一致性, "
            "不支持候选顺序的因果结论。",
        ],
        "run_summary": summary,
        "runs": viewer_runs,
    }


def _usage_tokens(metadata: Mapping[str, Any]) -> int:
    usage = metadata.get("usage", {})
    return int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))


def _build_workspace(
    staging_root: Path,
    cases_document: Mapping[str, Any],
    protocol: Mapping[str, Any],
    evals_document: Mapping[str, Any],
) -> tuple[Path, Path, list[dict[str, Any]]]:
    workspace = staging_root / WORKSPACE_RELATIVE
    eval_by_id = {item["id"]: item for item in evals_document["evals"]}
    case_to_eval_id = {
        "b1_8_16_2": 1,
        "b2_7_28": 2,
        "b3_8_16_1": 3,
        "d1_8_15_2_asr_variant": 4,
    }
    evidence_sets = cases_document["evidence_sets"]
    benchmark_runs: list[dict[str, Any]] = []
    manifest_runs: list[dict[str, Any]] = []

    for case in cases_document["cases"]:
        case_id = case["case_id"]
        eval_id = case_to_eval_id[case_id]
        eval_definition = eval_by_id[eval_id]
        evidence = evidence_sets[case["evidence_set"]]
        for number in range(1, case["replicates"] + 1):
            replicate_id = f"r{number:03d}"
            rep_dir = BENCHMARK_ROOT / "results" / case_id / replicate_id
            provenance = json.loads((rep_dir / "provenance.json").read_text(encoding="utf-8"))
            for config in GENERATOR_ORDER:
                generator_base = rep_dir / "generators" / config
                generator_result = json.loads(
                    (generator_base / "result.json").read_text(encoding="utf-8")
                )
                generator_validation = json.loads(
                    (generator_base / "validation.json").read_text(encoding="utf-8")
                )
                call_metadata = json.loads(
                    (generator_base / "call-metadata.json").read_text(encoding="utf-8")
                )
                judge_views = {
                    judge: _deanonymized_judge_view(rep_dir, judge, config)
                    for judge in JUDGE_ORDER
                }
                grading = _make_grading(generator_result, generator_validation, judge_views)
                totals = [float(item["computed_total"]) for item in judge_views.values()]
                scorecard = {
                    "blind_judge_mean": statistics.fmean(totals),
                    "blind_judge_range": [min(totals), max(totals)],
                    "generator_config": config,
                    "judge_scores": {
                        judge: {
                            "rank": view["rank"],
                            "total": view["computed_total"],
                        }
                        for judge, view in judge_views.items()
                    },
                    "quality_threshold": QUALITY_THRESHOLD,
                }
                context = {
                    "benchmark_role": evidence["benchmark_role"],
                    "candidate_order": provenance["candidate_order"],
                    "case_id": case_id,
                    "generator_config": config,
                    "include_in_primary_aggregate": case["include_in_primary_aggregate"],
                    "model": protocol["generator_models"][config]["model"],
                    "reasoning_effort": protocol["generator_models"][config]["effort"],
                    "replicate_id": replicate_id,
                    "source_aliases": evidence["source_aliases"],
                    "source_label": evidence["source_label"],
                    "source_sha256": evidence["expected_source_sha256"],
                    "warning": (
                        None
                        if case["include_in_primary_aggregate"]
                        else "诊断证据集: 不计入三个唯一 source 的主统计。"
                    ),
                }
                run_dir = workspace / f"eval-{eval_id}-{case_id}" / f"{replicate_id}-{config}"
                outputs = run_dir / "outputs"
                _write_json(outputs / "00-review-context.json", context)
                _write_json(outputs / "01-generator-output.json", generator_result)
                _write_json(outputs / "02-generator-validation.json", generator_validation)
                _write_json(outputs / "03-blind-judge-scorecard.json", scorecard)
                _write_json(outputs / "04-judge-terra-max-evidence.json", judge_views["terra_max"])
                _write_json(outputs / "05-judge-sol-max-evidence.json", judge_views["sol_max"])
                _write_json(
                    outputs / "06-selected-frozen-evidence.json",
                    _selected_evidence(rep_dir, generator_result),
                )
                prompt = (
                    f"{eval_definition['prompt']}\n\n本页方案: {config} "
                    f"({context['model']} / {context['reasoning_effort']}); "
                    f"replicate={replicate_id}; "
                    f"candidate_order={provenance['candidate_order']}。"
                )
                _write_json(
                    run_dir / "eval_metadata.json",
                    {
                        "assertions": [item["text"] for item in grading["expectations"]],
                        "eval_id": eval_id,
                        "eval_name": eval_definition["name"],
                        "prompt": prompt,
                    },
                )
                _write_json(run_dir / "grading.json", grading)
                _write_json(
                    run_dir / "timing.json",
                    {
                        "total_duration_seconds": call_metadata["elapsed_seconds"],
                        "total_tokens": _usage_tokens(call_metadata),
                    },
                )
                summary = grading["summary"]
                benchmark_runs.append(
                    {
                        "case_id": case_id,
                        "configuration": config,
                        "eval_id": eval_id,
                        "eval_name": eval_definition["name"],
                        "expectations": grading["expectations"],
                        "include_in_primary_aggregate": case["include_in_primary_aggregate"],
                        "result": {
                            "errors": int(bool(call_metadata.get("unsafe_tool_event"))),
                            "failed": summary["failed"],
                            "pass_rate": summary["pass_rate"],
                            "passed": summary["passed"],
                            "time_seconds": float(call_metadata["elapsed_seconds"]),
                            "tokens": _usage_tokens(call_metadata),
                            "total": summary["total"],
                            "tool_calls": 0,
                        },
                        "run_number": number,
                    }
                )
                manifest_runs.append(
                    {
                        "case_id": case_id,
                        "config": config,
                        "replicate_id": replicate_id,
                        "source_result": str(
                            (generator_base / "result.json").relative_to(BENCHMARK_ROOT)
                        ),
                        "source_result_sha256": _sha256(generator_base / "result.json"),
                        "viewer_run": str(run_dir.relative_to(staging_root)),
                    }
                )

    benchmark = _make_benchmark(benchmark_runs, protocol)
    benchmark_path = workspace / "benchmark.json"
    _write_json(benchmark_path, benchmark)
    _write_json(
        staging_root / "MANIFEST.json",
        {
            "benchmark_role_note": (
                "Only three unique primary source hashes contribute to primary statistics; "
                "D1 and filename aliases have zero weight."
            ),
            "bundled_viewer_limit": (
                "The top summary supports two configurations. It shows Sol Medium versus "
                "Sol High; Terra Medium remains in all per-eval tables and outputs."
            ),
            "generated_at": datetime.now(UTC).isoformat(),
            "generator_run_count": len(manifest_runs),
            "judge_evidence_view_count": len(manifest_runs) * len(JUDGE_ORDER),
            "runs": manifest_runs,
            "schema_version": "1",
            "skill_creator_viewer": str(VIEWER_SCRIPT),
            "skill_creator_viewer_sha256": _sha256(VIEWER_SCRIPT),
        },
    )
    return workspace, benchmark_path, manifest_runs


def _replace_output(staging_root: Path) -> None:
    expected = BENCHMARK_ROOT / "eval-review"
    if expected != OUTPUT_ROOT or OUTPUT_ROOT.parent != BENCHMARK_ROOT:
        raise RuntimeError(f"refusing unsafe output replacement: {OUTPUT_ROOT}")
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)
    shutil.copytree(staging_root, OUTPUT_ROOT)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate completeness without creating eval-review/",
    )
    parser.add_argument(
        "--viewer-script",
        type=Path,
        default=VIEWER_SCRIPT,
        help="path to the bundled Skill Creator generate_review.py",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    global VIEWER_SCRIPT
    VIEWER_SCRIPT = args.viewer_script.expanduser().resolve()
    if not VIEWER_SCRIPT.is_file():
        print(f"error: Skill Creator viewer not found: {VIEWER_SCRIPT}", file=sys.stderr)
        return 2
    try:
        cases_document, protocol, evals_document = _load_and_validate()
    except IncompleteBenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.check_only:
        print("benchmark completeness check passed")
        return 0

    with tempfile.TemporaryDirectory(prefix="liveclip-eval-review-") as temporary:
        staging_root = Path(temporary) / "eval-review"
        workspace, benchmark_path, manifest_runs = _build_workspace(
            staging_root,
            cases_document,
            protocol,
            evals_document,
        )
        review_path = staging_root / "REVIEW.html"
        subprocess.run(
            [
                sys.executable,
                str(VIEWER_SCRIPT),
                str(workspace),
                "--skill-name",
                "LiveClip Highlight Discovery v1 — three configurations",
                "--benchmark",
                str(benchmark_path),
                "--static",
                str(review_path),
            ],
            check=True,
        )
        html = review_path.read_text(encoding="utf-8")
        expected_runs = len(manifest_runs)
        if "const EMBEDDED_DATA =" not in html or '"runs": [' not in html:
            raise RuntimeError("bundled viewer did not embed review data")
        if expected_runs != 30:
            raise RuntimeError(f"expected 30 generator review runs, found {expected_runs}")
        _replace_output(staging_root)

    size = (OUTPUT_ROOT / "REVIEW.html").stat().st_size
    if not math.isfinite(float(size)) or size <= 0:
        raise RuntimeError("generated REVIEW.html is empty")
    print(f"offline viewer: {OUTPUT_ROOT / 'REVIEW.html'}")
    print("review runs: 30 (27 primary + 3 diagnostic); blind judge views: 60")
    print(f"viewer size: {size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
