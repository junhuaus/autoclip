#!/usr/bin/env python3
# ruff: noqa: E501, RUF001
"""Verify, unblind, analyze, and report Highlight Agent Skill v2 iteration 1.

The analyzer is deliberately fail closed.  It delegates immutable generator and
Judge receipt verification to ``run_judges.py`` and does not read the private arm
map until all six Judge calls have been verified as complete.  Headline metrics
are source-first: repeats are averaged inside each of the three unique sources,
then sources receive equal weight.  "Coverage" in this report always means
coverage relative to the observed selected union, never absolute recall.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any
from urllib.parse import quote

import contracts as highlight_contracts
import run_iteration as iteration_harness
import run_judges as judge_harness

ITERATION_DIR = Path(__file__).resolve().parent
DEFAULT_EXPERIMENTS_ROOT = ITERATION_DIR / "experiments"
DEFAULT_REPORTS_ROOT = ITERATION_DIR / "reports"
ANALYZER_VERSION = "liveclip-highlight-agent-v2-analysis.iteration-1"
SCHEMA_VERSION = "1"
SKILL_VERSIONS = ("v1", "v2")
JUDGE_IDS = ("judge_01", "judge_02")
MEMBER_SCORE_FIELDS = (
    "event_match_x4",
    "editorial_value_x4",
    "hook_x4",
    "completeness_x4",
    "evidence_fidelity_x4",
    "usability_x4",
)
SYSTEM_SCORE_FIELDS = (
    "discovery_x4",
    "coverage_x4",
    "precision_x4",
    "stability_x4",
    "editorial_readiness_x4",
)
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)


class AnalysisError(RuntimeError):
    """An artifact, aggregation, or reporting precondition failed."""


class AnalysisIncomplete(AnalysisError):
    """The frozen generator/Judge matrix is not complete enough to unblind."""


@dataclass(frozen=True)
class GeneratorRecord:
    pipeline_id: str
    source_id: str
    skill_version: str
    repeat: int
    result: dict[str, Any]
    validation: dict[str, Any]
    summary: dict[str, Any]
    usage: dict[str, int]
    elapsed_seconds: float
    call_count: int
    result_path: Path
    completion_path: Path
    supplemental_unbound_attempt_observations: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class JudgeRecord:
    source_id: str
    judge_id: str
    result: dict[str, Any]
    validation: dict[str, Any]
    binding: dict[str, Any]
    usage: dict[str, int]
    result_path: Path
    completion_path: Path
    binding_path: Path


@dataclass(frozen=True)
class VerifiedExperiment:
    experiment_dir: Path
    judge_run_dir: Path
    experiment_id: str
    source_ids: tuple[str, ...]
    generator_configuration: dict[str, str]
    judge_configuration: dict[str, dict[str, str]]
    source_metadata_by_id: dict[str, dict[str, Any]]
    candidates_by_source: dict[str, dict[str, dict[str, Any]]]
    generators: tuple[GeneratorRecord, ...]
    judges: tuple[JudgeRecord, ...]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalysisError(f"missing artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"expected a JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        raise AnalysisError("cannot average an empty collection")
    return sum(items) / len(items)


def _round(value: float, places: int = 3) -> float:
    result = round(value, places)
    return 0.0 if result == 0 else result


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return _round(numerator / denominator)


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def _expect_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    _expect(
        actual == expected,
        f"{context} keys differ; missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}",
    )


def _usage_record(raw: Mapping[str, Any]) -> dict[str, int]:
    record: dict[str, int] = {}
    for field in TOKEN_FIELDS:
        value = raw.get(field, 0)
        _expect(isinstance(value, int) and not isinstance(value, bool), f"invalid {field}")
        _expect(value >= 0, f"negative {field}")
        record[field] = value
    record["reported_total_tokens"] = record["input_tokens"] + record["output_tokens"]
    return record


def _add_usage(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    total = {field: 0 for field in TOKEN_FIELDS}
    for item in items:
        normalized = _usage_record(item)
        for field in TOKEN_FIELDS:
            total[field] += normalized[field]
    total["reported_total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return total


def _load_private_identity_map(
    experiment_dir: Path,
    pipeline_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Load the private map.  Callers must enforce the six-Judge completion gate first."""
    plan = _load_json(experiment_dir / "frozen" / "public-plan.json")
    private_path = experiment_dir / "private" / "arm-map.private.json"
    _expect(
        private_path.is_file() and not private_path.is_symlink(),
        "private arm map must be a regular non-symlink file",
    )
    expected_commitment = plan.get("arm_mapping_commitment_sha256")
    _expect(isinstance(expected_commitment, str), "public plan lacks arm commitment")
    _expect(
        _sha256_file(private_path) == expected_commitment,
        "private arm map no longer matches its pre-judgment commitment",
    )
    private = _load_json(private_path)
    _expect_keys(
        private,
        {"arm_id_to_skill_version", "pipeline_id_to_identity"},
        "private arm map",
    )
    arm_map = private["arm_id_to_skill_version"]
    identities = private["pipeline_id_to_identity"]
    _expect(isinstance(arm_map, dict), "arm map must be an object")
    _expect(isinstance(identities, dict), "pipeline identity map must be an object")
    _expect(set(arm_map.values()) == set(SKILL_VERSIONS), "arm map must disclose v1 and v2")
    _expect(set(identities) == pipeline_ids, "private map pipeline inventory drifted")
    for pipeline_id, identity in identities.items():
        _expect(isinstance(identity, dict), f"identity is malformed for {pipeline_id}")
        _expect_keys(
            identity,
            {"arm_id", "repeat", "skill_version", "source_id"},
            f"identity {pipeline_id}",
        )
        _expect(identity["arm_id"] in arm_map, f"unknown arm for {pipeline_id}")
        _expect(
            identity["skill_version"] == arm_map[identity["arm_id"]],
            f"arm/skill mismatch for {pipeline_id}",
        )
        _expect(identity["repeat"] in (1, 2), f"invalid repeat for {pipeline_id}")
    return identities


def _regular_file(path: Path, context: str) -> Path:
    _expect(path.is_file() and not path.is_symlink(), f"{context} must be a regular file")
    return path


def _generator_observations(experiment_dir: Path, completion: Mapping[str, Any]) -> dict[str, Any]:
    """Separate completion-bound success cost from unbound failed-attempt observations."""
    receipts = completion.get("call_receipts")
    _expect(isinstance(receipts, list) and receipts, "generator completion has no calls")
    bound_usages: list[Mapping[str, Any]] = []
    bound_elapsed_seconds = 0.0
    repair_count = 0
    supplemental: list[dict[str, Any]] = []
    seen: set[str] = set()
    for receipt in receipts:
        _expect(isinstance(receipt, dict), "generator call receipt is malformed")
        call_id = receipt.get("call_id")
        _expect(isinstance(call_id, str) and call_id not in seen, "invalid generator call ID")
        seen.add(call_id)
        call_dir = experiment_dir / "calls" / call_id
        call_completion = _load_json(
            _regular_file(call_dir / "complete.json", f"call {call_id} completion")
        )
        successful_attempt = call_completion.get("successful_attempt")
        _expect(
            isinstance(successful_attempt, int)
            and not isinstance(successful_attempt, bool)
            and successful_attempt >= 1,
            f"call {call_id} has an invalid successful attempt",
        )
        root_metadata = _load_json(
            _regular_file(call_dir / "call-metadata.json", f"call {call_id} metadata")
        )
        root_usage = root_metadata.get("usage")
        root_elapsed = root_metadata.get("elapsed_seconds")
        _expect(isinstance(root_usage, dict), f"call {call_id} has no bound usage")
        _expect(
            isinstance(root_elapsed, (int, float))
            and not isinstance(root_elapsed, bool)
            and root_elapsed >= 0,
            f"call {call_id} has invalid bound elapsed time",
        )
        bound_usages.append(root_usage)
        bound_elapsed_seconds += float(root_elapsed)

        # successful_attempt is completion-bound and proves how many prior model attempts
        # occurred. Their metadata is not in the completion artifact hash map, so it is
        # intentionally best-effort supplemental evidence and never enters a hard gate.
        attempts_root = call_dir / "attempts"
        for attempt in range(1, successful_attempt):
            attempt_dir = attempts_root / f"{attempt:03d}"
            observation: dict[str, Any] = {
                "call_id": call_id,
                "attempt": attempt,
                "completion_receipt_bound": False,
                "status": "unavailable",
                "usage": None,
                "elapsed_seconds": None,
                "metadata_sha256": None,
            }
            metadata_path = attempt_dir / "call-metadata.json"
            if metadata_path.is_file() and not metadata_path.is_symlink():
                observation["metadata_sha256"] = _sha256_file(metadata_path)
                try:
                    metadata = _load_json(metadata_path)
                    usage = metadata.get("usage")
                    elapsed = metadata.get("elapsed_seconds")
                    if (
                        isinstance(usage, dict)
                        and isinstance(elapsed, (int, float))
                        and not isinstance(elapsed, bool)
                        and elapsed >= 0
                    ):
                        observation["status"] = "observed_unbound"
                        observation["usage"] = _usage_record(usage)
                        observation["elapsed_seconds"] = float(elapsed)
                    else:
                        observation["status"] = "invalid_unbound_metadata"
                except AnalysisError:
                    observation["status"] = "invalid_unbound_metadata"
            supplemental.append(observation)
        repair_count += successful_attempt - 1
    _expect(
        len(supplemental) == repair_count,
        "completion-bound repair count and supplemental attempt inventory differ",
    )
    return {
        "bound_successful_usage": _add_usage(bound_usages),
        "bound_successful_call_count": len(receipts),
        "bound_successful_elapsed_seconds": bound_elapsed_seconds,
        "completion_bound_repair_count": repair_count,
        "supplemental_unbound_attempt_observations": supplemental,
    }


def _validate_pipeline_completion_binding(
    experiment_dir: Path,
    pipeline_dir: Path,
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply the frozen runner's full pipeline check plus explicit call identity binding."""
    try:
        summary = iteration_harness._pipeline_completion(pipeline_dir, contract)
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise AnalysisError(
            f"pipeline completion validation failed: {pipeline_dir}: {exc}"
        ) from exc
    _expect(summary is not None, f"pipeline is incomplete: {pipeline_dir}")
    completion = _load_json(pipeline_dir / "complete.json")
    try:
        expected_call_ids = iteration_harness._expected_pipeline_call_ids(contract, summary)
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        raise AnalysisError(f"pipeline call inventory is invalid: {pipeline_dir}: {exc}") from exc
    receipts = completion.get("call_receipts")
    _expect(isinstance(receipts, list), f"pipeline call receipts missing: {pipeline_dir}")
    _expect(
        all(isinstance(receipt, dict) for receipt in receipts),
        f"pipeline call receipt is malformed: {pipeline_dir}",
    )
    observed_call_ids = [receipt.get("call_id") for receipt in receipts]
    _expect(
        observed_call_ids == expected_call_ids,
        f"pipeline required/conditional call inventory drifted: {pipeline_dir}",
    )
    for call_id in expected_call_ids:
        call_dir = experiment_dir / "calls" / call_id
        call_contract = _load_json(
            _regular_file(call_dir / "call-contract.json", f"call {call_id} contract")
        )
        call_completion = _load_json(
            _regular_file(call_dir / "complete.json", f"call {call_id} completion")
        )
        _expect(call_contract.get("call_id") == call_id, f"call contract ID drifted: {call_id}")
        _expect(
            call_contract.get("pipeline_id") == contract.get("pipeline_id"),
            f"call/pipeline binding drifted: {call_id}",
        )
        _expect(
            call_contract.get("experiment_contract_sha256")
            == contract.get("experiment_contract_sha256"),
            f"call/experiment contract binding drifted: {call_id}",
        )
        _expect(call_completion.get("call_id") == call_id, f"call completion ID drifted: {call_id}")
    return summary, completion


def _verify_completed_runtime_preflight(prepared: Any) -> None:
    """Read-only verification of the Judge run's zero-model runtime preflight."""
    root = prepared.run_dir / "infrastructure" / "preflight"
    completion_path = _regular_file(root / "complete.json", "Judge runtime preflight completion")
    completion = _load_json(completion_path)
    _expect_keys(
        completion,
        {"schema_version", "policy_version", "passed_check", "receipt_sha256"},
        "Judge runtime preflight completion",
    )
    _expect(
        completion["schema_version"] == judge_harness.SCHEMA_VERSION,
        "Judge runtime preflight completion schema drifted",
    )
    _expect(
        completion["policy_version"] == prepared.manifest["runtime_preflight"]["policy_version"],
        "Judge runtime preflight completion policy drifted",
    )
    checks_root = root / "checks"
    _expect(
        checks_root.is_dir() and not checks_root.is_symlink(),
        "Judge runtime preflight checks root is invalid",
    )
    children = sorted(checks_root.iterdir(), key=lambda path: path.name)
    _expect(
        all(
            child.is_dir() and not child.is_symlink() and child.name.isdigit() for child in children
        ),
        "Judge runtime preflight check layout drifted",
    )
    numbers = [int(child.name) for child in children]
    _expect(bool(numbers), "Judge runtime preflight has no checks")
    _expect(numbers == list(range(1, len(numbers) + 1)), "preflight check sequence drifted")
    inventory = []
    passed: list[int] = []
    for number, directory in zip(numbers, children, strict=True):
        receipt_path = _regular_file(
            directory / "receipt.json", f"Judge runtime preflight check {number}"
        )
        _expect(len(list(directory.iterdir())) == 1, "preflight check has extra artifacts")
        receipt = _load_json(receipt_path)
        try:
            judge_harness._validate_preflight_receipt(receipt, prepared, number)
        except judge_harness.IntegrityError as exc:
            raise AnalysisError(str(exc)) from exc
        if receipt.get("status") == "passed":
            passed.append(number)
        inventory.append(
            {
                "relative_path": f"checks/{number:03d}/receipt.json",
                "sha256": _sha256_file(receipt_path),
            }
        )
    _expect(len(passed) == 1 and passed[0] == numbers[-1], "preflight pass receipt drifted")
    _expect(completion["passed_check"] == passed[0], "preflight passed check binding drifted")
    _expect(completion["receipt_sha256"] == inventory, "preflight receipt inventory drifted")


def load_verified_experiment(
    experiment_dir: Path,
    judge_run_dir: Path | None = None,
) -> VerifiedExperiment:
    """Verify all public receipts, then (and only then) load private identities."""
    experiment_dir = experiment_dir.resolve(strict=True)
    try:
        experiment_id, bundles = judge_harness._load_source_bundles(experiment_dir)
    except (judge_harness.GeneratorMatrixIncomplete, judge_harness.IntegrityError) as exc:
        raise AnalysisError(str(exc)) from exc
    _expect(len(bundles) == 3, "analysis requires exactly three unique sources")
    pipeline_ids = {pipeline_id for bundle in bundles for pipeline_id in bundle.pipeline_ids}
    _expect(len(pipeline_ids) == 12, "analysis requires exactly twelve generator pipelines")

    try:
        preflight_policy = judge_harness._preflight_policy()
        run_id = judge_harness._run_id(experiment_id, preflight_policy)
    except judge_harness.CodexInfrastructureUnavailable as exc:
        raise AnalysisError(f"cannot resolve frozen Judge runtime identity: {exc}") from exc
    expected_run_dir = experiment_dir / "judge-runs" / run_id
    selected_run_dir = (
        judge_run_dir.resolve(strict=True) if judge_run_dir is not None else expected_run_dir
    )
    _expect(selected_run_dir == expected_run_dir, "Judge run does not match the frozen harness")
    if not selected_run_dir.is_dir() or selected_run_dir.is_symlink():
        raise AnalysisIncomplete(f"expected Judge run does not exist: {selected_run_dir}")

    # This inventory check is intentionally before prepare_judge_run or any private-map read.
    expected_call_dirs = [
        selected_run_dir / "sources" / bundle.source_id / judge_id
        for bundle in bundles
        for judge_id in JUDGE_IDS
    ]
    missing = [
        str(path / "complete.json")
        for path in expected_call_dirs
        if not (path / "complete.json").is_file()
        or (path / "complete.json").is_symlink()
        or path.is_symlink()
    ]
    if missing:
        raise AnalysisIncomplete(
            "all six dual-Judge receipts must be complete before analysis or unblinding; "
            f"missing={missing}"
        )

    try:
        prepared = judge_harness.prepare_judge_run(experiment_dir)
    except (judge_harness.GeneratorMatrixIncomplete, judge_harness.IntegrityError) as exc:
        raise AnalysisError(str(exc)) from exc
    _expect(prepared.run_dir == selected_run_dir, "prepared Judge run identity drifted")
    _expect(set(prepared.source_ids) == {bundle.source_id for bundle in bundles}, "source drift")
    _expect(set(prepared.manifest.get("judge_ids", [])) == set(JUDGE_IDS), "Judge set drifted")
    _expect(len(prepared.calls) == 6, "Judge manifest must bind exactly six calls")
    _verify_completed_runtime_preflight(prepared)
    for key, call in prepared.calls.items():
        try:
            judge_harness._verify_completed_call(
                selected_run_dir / "sources" / key[0] / key[1], call
            )
        except (judge_harness.IntegrityError, judge_harness.JudgeValidationError) as exc:
            raise AnalysisError(str(exc)) from exc

    # The only private read is below, after all 12 generator and all 6 Judge receipts pass.
    identities = _load_private_identity_map(experiment_dir, pipeline_ids)
    candidates_by_source = {
        bundle.source_id: {
            str(candidate["candidate_id"]): dict(candidate)
            for candidate in bundle.source_payload["candidates"]
        }
        for bundle in bundles
    }

    generators: list[GeneratorRecord] = []
    for bundle in bundles:
        for pipeline_id in bundle.pipeline_ids:
            pipeline_dir = experiment_dir / "pipelines" / pipeline_id
            contract = _load_json(pipeline_dir / "pipeline-contract.json")
            identity = identities[pipeline_id]
            for field in ("arm_id", "repeat", "skill_version", "source_id"):
                _expect(
                    contract.get(field) == identity[field],
                    f"private identity/contract mismatch: {pipeline_id}/{field}",
                )
            summary, completion = _validate_pipeline_completion_binding(
                experiment_dir, pipeline_dir, contract
            )
            observations = _generator_observations(experiment_dir, completion)
            repair_budget = summary.get("repair_budget")
            _expect(isinstance(repair_budget, dict), f"repair budget missing: {pipeline_id}")
            _expect(
                repair_budget.get("repairs_used") == observations["completion_bound_repair_count"],
                f"attempt/repair accounting drifted: {pipeline_id}",
            )
            generators.append(
                GeneratorRecord(
                    pipeline_id=pipeline_id,
                    source_id=bundle.source_id,
                    skill_version=identity["skill_version"],
                    repeat=identity["repeat"],
                    result=bundle.results_by_pipeline[pipeline_id],
                    validation=_load_json(pipeline_dir / "validation.json"),
                    summary=summary,
                    usage=observations["bound_successful_usage"],
                    elapsed_seconds=observations["bound_successful_elapsed_seconds"],
                    call_count=observations["bound_successful_call_count"],
                    result_path=pipeline_dir / "result.json",
                    completion_path=pipeline_dir / "complete.json",
                    supplemental_unbound_attempt_observations=tuple(
                        observations["supplemental_unbound_attempt_observations"]
                    ),
                )
            )

    judges: list[JudgeRecord] = []
    for bundle in bundles:
        for judge_id in JUDGE_IDS:
            call_dir = selected_run_dir / "sources" / bundle.source_id / judge_id
            judges.append(
                JudgeRecord(
                    source_id=bundle.source_id,
                    judge_id=judge_id,
                    result=_load_json(call_dir / "result.json"),
                    validation=_load_json(call_dir / "validation.json"),
                    binding=_load_json(call_dir / "mapping.disclosed-after-judging.json"),
                    usage=_usage_record(_load_json(call_dir / "usage.json")),
                    result_path=call_dir / "result.json",
                    completion_path=call_dir / "complete.json",
                    binding_path=call_dir / "mapping.disclosed-after-judging.json",
                )
            )
    return VerifiedExperiment(
        experiment_dir=experiment_dir,
        judge_run_dir=selected_run_dir,
        experiment_id=experiment_id,
        source_ids=tuple(sorted(bundle.source_id for bundle in bundles)),
        generator_configuration=dict(
            _load_json(experiment_dir / "frozen" / "public-plan.json")["model"]
        ),
        judge_configuration=dict(prepared.manifest["judge_configuration"]),
        source_metadata_by_id={
            bundle.source_id: dict(bundle.source_payload["source"]) for bundle in bundles
        },
        candidates_by_source=candidates_by_source,
        generators=tuple(generators),
        judges=tuple(judges),
    )


def _candidate_ids(record: GeneratorRecord) -> set[str]:
    return {str(item["candidate_id"]) for item in record.result["highlights"]}


def _intervals(record: GeneratorRecord) -> list[tuple[int, int]]:
    return [
        (int(item["source_start_ms"]), int(item["source_end_ms"]))
        for item in record.result["highlights"]
    ]


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _interval_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union > 0 else 0.0


def _interval_match_f1(
    left: Sequence[tuple[int, int]], right: Sequence[tuple[int, int]], threshold: float = 0.5
) -> dict[str, Any]:
    adjacency = [
        sorted(
            (index for index, other in enumerate(right) if _interval_iou(item, other) >= threshold),
            key=lambda index: (-_interval_iou(item, right[index]), index),
        )
        for item in left
    ]
    matched: dict[int, int] = {}

    def augment(left_index: int, visited: set[int]) -> bool:
        for right_index in adjacency[left_index]:
            if right_index in visited:
                continue
            visited.add(right_index)
            prior = matched.get(right_index)
            if prior is None or augment(prior, visited):
                matched[right_index] = left_index
                return True
        return False

    count = sum(augment(index, set()) for index in range(len(left)))
    precision = count / len(left) if left else (1.0 if not right else 0.0)
    relative_coverage = count / len(right) if right else (1.0 if not left else 0.0)
    f1 = (
        2 * precision * relative_coverage / (precision + relative_coverage)
        if precision + relative_coverage
        else 0.0
    )
    return {
        "iou_threshold": threshold,
        "matches": count,
        "precision": _round(precision),
        "relative_coverage": _round(relative_coverage),
        "f1": _round(f1),
    }


def _overlap_diagnostics(record: GeneratorRecord) -> dict[str, Any]:
    highlights = record.result["highlights"]
    candidate_ids = [str(item["candidate_id"]) for item in highlights]
    intervals = _intervals(record)
    pairs = [
        {
            "left_index": left,
            "right_index": right,
            "iou": _round(_interval_iou(intervals[left], intervals[right])),
        }
        for left, right in combinations(range(len(intervals)), 2)
        if _interval_iou(intervals[left], intervals[right]) > 0.45
    ]
    return {
        "selected_count": len(candidate_ids),
        "duplicate_candidate_count": len(candidate_ids) - len(set(candidate_ids)),
        "interval_overlap_pair_count_above_0_45": len(pairs),
        "interval_overlap_pairs": pairs,
    }


def _partition_pair_f1(left: Mapping[str, str], right: Mapping[str, str]) -> dict[str, Any]:
    _expect(set(left) == set(right), "Judge partitions cover different highlight entities")
    entities = sorted(left)
    left_pairs = {pair for pair in combinations(entities, 2) if left[pair[0]] == left[pair[1]]}
    right_pairs = {pair for pair in combinations(entities, 2) if right[pair[0]] == right[pair[1]]}
    shared = len(left_pairs & right_pairs)
    precision = shared / len(left_pairs) if left_pairs else (1.0 if not right_pairs else 0.0)
    relative_coverage = (
        shared / len(right_pairs) if right_pairs else (1.0 if not left_pairs else 0.0)
    )
    f1 = (
        2 * precision * relative_coverage / (precision + relative_coverage)
        if precision + relative_coverage
        else 0.0
    )
    return {
        "shared_co_cluster_pairs": shared,
        "judge_01_co_cluster_pairs": len(left_pairs),
        "judge_02_co_cluster_pairs": len(right_pairs),
        "precision": _round(precision),
        "relative_coverage": _round(relative_coverage),
        "f1": _round(f1),
    }


def _source_first_metric(
    records: Sequence[GeneratorRecord],
    value: Callable[[GeneratorRecord], float],
) -> dict[str, Any]:
    by_source: dict[str, float] = {}
    for source_id in sorted({record.source_id for record in records}):
        source_records = [record for record in records if record.source_id == source_id]
        _expect(len(source_records) == 2, f"expected two repeats for {source_id}")
        by_source[source_id] = _round(_mean(float(value(record)) for record in source_records))
    return {"by_source": by_source, "macro": _round(_mean(by_source.values()))}


def _judge_score_lookup(verified: VerifiedExperiment) -> dict[tuple[str, str], float]:
    lookup: dict[tuple[str, str], float] = {}
    for judge in verified.judges:
        systems = judge.binding["anonymous_system_to_pipeline"]
        scores = judge.validation["computed_system_score_x100"]
        _expect(set(systems) == set(scores), f"Judge score binding drifted: {judge.judge_id}")
        for anonymous_id, pipeline_id in systems.items():
            score = scores[anonymous_id]
            _expect(isinstance(score, int) and 0 <= score <= 100, "invalid Judge score")
            lookup[(judge.judge_id, pipeline_id)] = float(score)
    _expect(len(lookup) == 24, "expected 24 Judge/pipeline quality scores")
    return lookup


def _quality_analysis(
    verified: VerifiedExperiment,
    generators_by_id: Mapping[str, GeneratorRecord],
) -> dict[str, Any]:
    scores = _judge_score_lookup(verified)
    evaluation_lookup: dict[tuple[str, str], Mapping[str, Any]] = {}
    for judge in verified.judges:
        anon_to_pipeline = judge.binding["anonymous_system_to_pipeline"]
        evaluations = judge.result["system_evaluations"]
        _expect(len(evaluations) == 4, "Judge must evaluate four anonymous systems")
        for evaluation in evaluations:
            pipeline_id = anon_to_pipeline[evaluation["anonymous_system_id"]]
            evaluation_lookup[(judge.judge_id, pipeline_id)] = evaluation
    _expect(len(evaluation_lookup) == 24, "expected 24 Judge/pipeline evaluations")
    by_judge: dict[str, Any] = {}
    for judge_id in JUDGE_IDS:
        skills: dict[str, Any] = {}
        for skill in SKILL_VERSIONS:
            records = [record for record in verified.generators if record.skill_version == skill]
            source_scores: dict[str, float] = {}
            for source_id in verified.source_ids:
                source_records = [record for record in records if record.source_id == source_id]
                source_scores[source_id] = _round(
                    _mean(scores[(judge_id, record.pipeline_id)] for record in source_records)
                )
            dimensions: dict[str, float] = {}
            for field in SYSTEM_SCORE_FIELDS:
                source_dimension_scores = []
                for source_id in verified.source_ids:
                    source_records = [record for record in records if record.source_id == source_id]
                    source_dimension_scores.append(
                        _mean(
                            float(evaluation_lookup[(judge_id, record.pipeline_id)][field])
                            / 4
                            * 100
                            for record in source_records
                        )
                    )
                dimensions[field.removesuffix("_x4") + "_x100"] = _round(
                    _mean(source_dimension_scores)
                )
            skills[skill] = {
                "by_source": source_scores,
                "source_first_macro_x100": _round(_mean(source_scores.values())),
                "source_first_dimensions_x100": dimensions,
            }
        by_judge[judge_id] = skills

    dual_by_skill: dict[str, Any] = {}
    for skill in SKILL_VERSIONS:
        source_scores = {
            source_id: _round(
                _mean(by_judge[judge_id][skill]["by_source"][source_id] for judge_id in JUDGE_IDS)
            )
            for source_id in verified.source_ids
        }
        dual_by_skill[skill] = {
            "by_source": source_scores,
            "source_first_macro_x100": _round(_mean(source_scores.values())),
            "source_first_dimensions_x100": {
                field.removesuffix("_x4") + "_x100": _round(
                    _mean(
                        by_judge[judge_id][skill]["source_first_dimensions_x100"][
                            field.removesuffix("_x4") + "_x100"
                        ]
                        for judge_id in JUDGE_IDS
                    )
                )
                for field in SYSTEM_SCORE_FIELDS
            },
        }
    delta = _round(
        dual_by_skill["v2"]["source_first_macro_x100"]
        - dual_by_skill["v1"]["source_first_macro_x100"]
    )
    return {
        "score_definition": (
            "Judge system score: discovery 30%, selected-union-relative coverage 20%, "
            "precision 20%, sampling stability 15%, editorial readiness 15%."
        ),
        "by_judge": by_judge,
        "dual_judge": dual_by_skill,
        "v2_minus_v1_x100": delta,
        "pipeline_scores": [
            {
                "source_id": record.source_id,
                "skill_version": record.skill_version,
                "repeat": record.repeat,
                "pipeline_id": record.pipeline_id,
                **{judge_id: scores[(judge_id, record.pipeline_id)] for judge_id in JUDGE_IDS},
                "dual_judge_mean_x100": _round(
                    _mean(scores[(judge_id, record.pipeline_id)] for judge_id in JUDGE_IDS)
                ),
            }
            for record in sorted(
                generators_by_id.values(),
                key=lambda item: (item.source_id, item.skill_version, item.repeat),
            )
        ],
    }


def _coverage_and_stability(verified: VerifiedExperiment) -> dict[str, Any]:
    source_rows: list[dict[str, Any]] = []
    stability_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    for source_id in verified.source_ids:
        source_records = [record for record in verified.generators if record.source_id == source_id]
        selected_union = set().union(*(_candidate_ids(record) for record in source_records))
        row: dict[str, Any] = {
            "source_id": source_id,
            "observed_selected_union_count": len(selected_union),
        }
        for skill in SKILL_VERSIONS:
            skill_records = sorted(
                (record for record in source_records if record.skill_version == skill),
                key=lambda item: item.repeat,
            )
            skill_union = _candidate_ids(skill_records[0]) | _candidate_ids(skill_records[1])
            row[f"{skill}_selected_union_count"] = len(skill_union)
            row[f"{skill}_relative_selected_union_coverage"] = _round(
                len(skill_union) / len(selected_union) if selected_union else 1.0
            )
            stability_rows.append(
                {
                    "source_id": source_id,
                    "skill_version": skill,
                    "repeat_candidate_jaccard": _round(
                        _jaccard(_candidate_ids(skill_records[0]), _candidate_ids(skill_records[1]))
                    ),
                    "repeat_interval_match": _interval_match_f1(
                        _intervals(skill_records[0]), _intervals(skill_records[1])
                    ),
                    "claim_limit": "sampling stability only; candidate order was fixed",
                }
            )
        source_rows.append(row)
        overlap_rows.extend(
            {
                "source_id": record.source_id,
                "skill_version": record.skill_version,
                "repeat": record.repeat,
                "pipeline_id": record.pipeline_id,
                **_overlap_diagnostics(record),
            }
            for record in source_records
        )
    relative_coverage_macro = {
        skill: _round(
            _mean(row[f"{skill}_relative_selected_union_coverage"] for row in source_rows)
        )
        for skill in SKILL_VERSIONS
    }
    stability_macro = {
        skill: {
            "repeat_candidate_jaccard": _round(
                _mean(
                    row["repeat_candidate_jaccard"]
                    for row in stability_rows
                    if row["skill_version"] == skill
                )
            ),
            "repeat_interval_match_f1": _round(
                _mean(
                    row["repeat_interval_match"]["f1"]
                    for row in stability_rows
                    if row["skill_version"] == skill
                )
            ),
        }
        for skill in SKILL_VERSIONS
    }
    return {
        "definition": (
            "Denominator is the union of candidates selected by all four outputs for the same "
            "frozen source. This is relative selected-union coverage, not absolute recall."
        ),
        "by_source": source_rows,
        "source_first_macro_relative_selected_union_coverage": relative_coverage_macro,
        "sampling_stability": stability_rows,
        "source_first_macro_sampling_stability": stability_macro,
        "duplicates_and_interval_overlap": overlap_rows,
    }


def _validate_v2_exact_evidence(
    record: GeneratorRecord,
    candidates: Mapping[str, Mapping[str, Any]],
) -> int:
    highlights = record.result.get("highlights")
    _expect(isinstance(highlights, list), f"v2 highlights missing: {record.pipeline_id}")
    validation = record.validation
    _expect(
        validation.get("exact_quote_gate") == "passed",
        f"v2 exact quote gate is not passed: {record.pipeline_id}",
    )
    _expect(
        validation.get("selected_order_gate") == "passed",
        f"v2 selected order gate is not passed: {record.pipeline_id}",
    )
    receipts = validation.get("receipts")
    receipt_count = validation.get("receipt_count")
    _expect(isinstance(receipts, list), f"v2 quote receipts missing: {record.pipeline_id}")
    _expect(
        isinstance(receipt_count, int)
        and not isinstance(receipt_count, bool)
        and receipt_count == len(receipts) == len(highlights),
        f"v2 quote receipt count mismatch: {record.pipeline_id}",
    )
    seen: set[str] = set()
    failed_count = 0
    for index, (highlight, validation_receipt) in enumerate(zip(highlights, receipts, strict=True)):
        _expect(isinstance(highlight, dict), f"v2 highlight {index} is malformed")
        _expect(isinstance(validation_receipt, dict), f"v2 receipt {index} is malformed")
        candidate_id = highlight.get("candidate_id")
        _expect(
            isinstance(candidate_id, str)
            and candidate_id in candidates
            and candidate_id not in seen,
            f"v2 highlight candidate binding failed: {record.pipeline_id}/{index}",
        )
        seen.add(candidate_id)
        quote = highlight.get("evidence_quote")
        candidate_text = candidates[candidate_id].get("text")
        _expect(isinstance(quote, str), f"v2 evidence quote missing: {candidate_id}")
        _expect(isinstance(candidate_text, str), f"candidate text missing: {candidate_id}")
        expected_receipt = highlight_contracts.exact_quote_receipt(quote, candidate_text)
        outward_receipt = highlight.get("evidence_receipt")
        _expect(
            outward_receipt == expected_receipt,
            f"v2 outward quote receipt mismatch: {record.pipeline_id}/{candidate_id}",
        )
        expected_validation_receipt = {"candidate_id": candidate_id, **expected_receipt}
        _expect(
            validation_receipt == expected_validation_receipt,
            f"v2 validation quote receipt mismatch: {record.pipeline_id}/{candidate_id}",
        )
        if expected_receipt.get("status") != "passed":
            failed_count += 1
    summary_failures = record.summary.get("exact_quote_failed_count")
    _expect(
        isinstance(summary_failures, int)
        and not isinstance(summary_failures, bool)
        and summary_failures == failed_count,
        f"v2 summary quote failure count mismatch: {record.pipeline_id}",
    )
    _expect(failed_count == 0, f"v2 outward exact quote failure: {record.pipeline_id}")
    return failed_count


def _evidence_and_repairs(verified: VerifiedExperiment) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for record in sorted(
        verified.generators,
        key=lambda item: (item.source_id, item.skill_version, item.repeat),
    ):
        repair = record.summary.get("repair_budget", {})
        _expect(isinstance(repair, dict), "repair budget is malformed")
        if record.skill_version == "v2":
            failures = _validate_v2_exact_evidence(
                record, verified.candidates_by_source[record.source_id]
            )
            kind = "outward_exact_evidence_gate"
        else:
            failures = record.summary.get("quote_gate_failed_count")
            gate = record.validation.get("v2_quote_gate_shadow_audit", {}).get("failed_count")
            kind = "non_blocking_v2_shadow_audit_of_v1_copy"
            _expect(gate == failures, f"v1 quote shadow audit drifted: {record.pipeline_id}")
        _expect(isinstance(failures, int) and failures >= 0, "quote failure count invalid")
        rows.append(
            {
                "source_id": record.source_id,
                "skill_version": record.skill_version,
                "repeat": record.repeat,
                "pipeline_id": record.pipeline_id,
                "evidence_metric_kind": kind,
                "exact_quote_failure_count": failures,
                "repair_count": int(repair.get("repairs_used", 0)),
                "repair_stages": repair.get("used_by_stage", []),
            }
        )
    v2_outward = sum(
        row["exact_quote_failure_count"] for row in rows if row["skill_version"] == "v2"
    )
    repair_summary = {}
    for skill in SKILL_VERSIONS:
        skill_rows = [row for row in rows if row["skill_version"] == skill]
        repaired = sum(row["repair_count"] > 0 for row in skill_rows)
        repair_summary[skill] = {
            "pipeline_count": len(skill_rows),
            "pipelines_with_repair": repaired,
            "pipeline_repair_rate": _round(repaired / len(skill_rows)),
            "total_repairs": sum(row["repair_count"] for row in skill_rows),
        }
    return {
        "v2_outward_exact_evidence_failure_count": v2_outward,
        "v1_note": (
            "v1 failures are a non-blocking v2 exact-quote shadow audit of an old field that "
            "mixed edited copy with evidence; they are not v1 pipeline hard failures."
        ),
        "by_pipeline": rows,
        "repair_summary": repair_summary,
    }


def _efficiency(verified: VerifiedExperiment) -> dict[str, Any]:
    skills: dict[str, Any] = {}
    for skill in SKILL_VERSIONS:
        records = [record for record in verified.generators if record.skill_version == skill]
        elapsed = _source_first_metric(records, lambda record: record.elapsed_seconds)
        tokens = {
            field: _source_first_metric(records, lambda record, name=field: record.usage[name])
            for field in (*TOKEN_FIELDS, "reported_total_tokens")
        }
        skills[skill] = {
            "elapsed_seconds": elapsed,
            "tokens": tokens,
            "total_model_calls": sum(record.call_count for record in records),
        }
    elapsed_ratio = _ratio(
        skills["v2"]["elapsed_seconds"]["macro"],
        skills["v1"]["elapsed_seconds"]["macro"],
    )
    token_ratio = _ratio(
        skills["v2"]["tokens"]["reported_total_tokens"]["macro"],
        skills["v1"]["tokens"]["reported_total_tokens"]["macro"],
    )
    supplemental = [
        {
            "source_id": record.source_id,
            "skill_version": record.skill_version,
            "repeat": record.repeat,
            "pipeline_id": record.pipeline_id,
            **observation,
        }
        for record in verified.generators
        for observation in record.supplemental_unbound_attempt_observations
    ]
    completion_bound_repair_count = sum(
        int(record.summary["repair_budget"]["repairs_used"]) for record in verified.generators
    )
    _expect(
        len(supplemental) == completion_bound_repair_count,
        "supplemental repair observation inventory drifted",
    )
    judge_usage = _add_usage(judge.usage for judge in verified.judges)
    return {
        "completion_bound_successful_lower_bound_source_first": skills,
        "successful_artifact_lower_bound_v2_to_v1_ratio": {
            "elapsed_seconds": elapsed_ratio,
            "reported_total_tokens": token_ratio,
        },
        "token_definition": (
            "Hard-gate lower bound uses only completion-hash-bound successful artifacts. "
            "reported_total_tokens = input_tokens + output_tokens; cached and reasoning fields "
            "are shown separately and are not double-counted."
        ),
        "latency_definition": (
            "Hard-gate lower bound sums only completion-hash-bound successful call metadata "
            "before source-first aggregation."
        ),
        "unbound_repair_cost": {
            "present": completion_bound_repair_count > 0,
            "completion_bound_repair_attempt_count": completion_bound_repair_count,
            "hard_gate_eligible": False,
            "reason": (
                "Failed-attempt metadata is not bound by the generator completion artifact "
                "hash map. A Git checkpoint may preserve current bytes, but this analyzer does "
                "not prove that chain; these observations cannot enter an efficiency hard gate."
            ),
        },
        "supplemental_unbound_attempt_observations": supplemental,
        "judge_successful_call_usage_not_attributed_to_either_skill": judge_usage,
        "cost": {
            "status": "not_estimated",
            "reason": "No frozen price configuration was supplied; model prices are not hard-coded.",
        },
    }


def _topic_analysis(
    verified: VerifiedExperiment,
    generators_by_id: Mapping[str, GeneratorRecord],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    clusters: list[dict[str, Any]] = []
    semantic_rows: list[dict[str, Any]] = []
    partition_by_source_judge: dict[tuple[str, str], dict[str, str]] = {}
    for judge in verified.judges:
        anon_to_pipeline = judge.binding["anonymous_system_to_pipeline"]
        membership = judge.binding["highlight_membership"]
        partition: dict[str, str] = {}
        all_cluster_ids = {cluster["cluster_id"] for cluster in judge.result["topic_clusters"]}
        systems_in_clusters: dict[str, set[str]] = defaultdict(set)
        per_system_count: dict[tuple[str, str], int] = defaultdict(int)
        per_system_total: dict[str, int] = defaultdict(int)
        for cluster in judge.result["topic_clusters"]:
            members: list[dict[str, Any]] = []
            for member in cluster["members"]:
                highlight_id = member["highlight_id"]
                disclosed = membership[highlight_id]
                pipeline_id = disclosed["pipeline_id"]
                record = generators_by_id[pipeline_id]
                _expect(
                    anon_to_pipeline[member["anonymous_system_id"]] == pipeline_id,
                    "Judge member/pipeline binding drifted",
                )
                entity_id = f"{pipeline_id}:{member['candidate_id']}"
                _expect(entity_id not in partition, "Judge partition repeats an entity")
                partition[entity_id] = cluster["cluster_id"]
                systems_in_clusters[pipeline_id].add(cluster["cluster_id"])
                per_system_count[(pipeline_id, cluster["cluster_id"])] += 1
                per_system_total[pipeline_id] += 1
                generated = next(
                    item
                    for item in record.result["highlights"]
                    if item["candidate_id"] == member["candidate_id"]
                )
                member_score = _round(
                    _mean(float(member[field]) for field in MEMBER_SCORE_FIELDS) / 4 * 100
                )
                members.append(
                    {
                        "skill_version": record.skill_version,
                        "repeat": record.repeat,
                        "pipeline_id": pipeline_id,
                        "candidate_id": member["candidate_id"],
                        "title": generated.get("title", ""),
                        "generator_topic": generated.get("topic", ""),
                        "evidence_or_edited_sentence": generated.get(
                            "evidence_quote", generated.get("highlight_sentence", "")
                        ),
                        "judge_member_score_x100": member_score,
                        "scores_x4": {field: member[field] for field in MEMBER_SCORE_FIELDS},
                        "assessment": member["assessment"],
                        "generator_result_path": record.result_path.relative_to(
                            verified.experiment_dir
                        ).as_posix(),
                    }
                )
            clusters.append(
                {
                    "source_id": judge.source_id,
                    "judge_id": judge.judge_id,
                    "cluster_id": cluster["cluster_id"],
                    "canonical_topic": cluster["canonical_topic"],
                    "alignment_confidence": cluster["alignment_confidence"],
                    "topic_assessment": cluster["topic_assessment"],
                    "member_count": len(members),
                    "skills_present": sorted({member["skill_version"] for member in members}),
                    "members": members,
                    "judge_result_path": judge.result_path.relative_to(
                        verified.experiment_dir
                    ).as_posix(),
                }
            )
        partition_by_source_judge[(judge.source_id, judge.judge_id)] = partition
        for pipeline_id, cluster_ids in systems_in_clusters.items():
            record = generators_by_id[pipeline_id]
            duplicate_excess = sum(
                max(0, per_system_count[(pipeline_id, cluster_id)] - 1)
                for cluster_id in all_cluster_ids
            )
            semantic_rows.append(
                {
                    "source_id": judge.source_id,
                    "judge_id": judge.judge_id,
                    "skill_version": record.skill_version,
                    "repeat": record.repeat,
                    "pipeline_id": pipeline_id,
                    "observed_topic_cluster_count": len(cluster_ids),
                    "relative_judged_cluster_coverage": _round(
                        len(cluster_ids) / len(all_cluster_ids) if all_cluster_ids else 1.0
                    ),
                    "within_output_semantic_duplicate_excess": duplicate_excess,
                    "within_output_semantic_duplicate_rate": _round(
                        duplicate_excess / per_system_total[pipeline_id]
                        if per_system_total[pipeline_id]
                        else 0.0
                    ),
                }
            )
    judge_partition_rows = []
    for source_id in verified.source_ids:
        judge_partition_rows.append(
            {
                "source_id": source_id,
                **_partition_pair_f1(
                    partition_by_source_judge[(source_id, "judge_01")],
                    partition_by_source_judge[(source_id, "judge_02")],
                ),
            }
        )
    return clusters, semantic_rows, judge_partition_rows


def _judge_disagreement(
    verified: VerifiedExperiment,
    quality: Mapping[str, Any],
    generators_by_id: Mapping[str, GeneratorRecord],
    partition_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source_id in verified.source_ids:
        for skill in SKILL_VERSIONS:
            left = quality["by_judge"]["judge_01"][skill]["by_source"][source_id]
            right = quality["by_judge"]["judge_02"][skill]["by_source"][source_id]
            rows.append(
                {
                    "source_id": source_id,
                    "skill_version": skill,
                    "judge_01_x100": left,
                    "judge_02_x100": right,
                    "signed_judge_01_minus_judge_02": _round(left - right),
                    "absolute_difference": _round(abs(left - right)),
                }
            )
    preference_rows: list[dict[str, Any]] = []
    system_rows: list[dict[str, Any]] = []
    for judge in verified.judges:
        anon_to_pipeline = judge.binding["anonymous_system_to_pipeline"]
        preferred = judge.result["preferred_system_ids"]
        counts = {skill: 0 for skill in SKILL_VERSIONS}
        for anonymous_id in preferred:
            counts[generators_by_id[anon_to_pipeline[anonymous_id]].skill_version] += 1
        preference_rows.append(
            {
                "source_id": judge.source_id,
                "judge_id": judge.judge_id,
                "preferred_v1_outputs": counts["v1"],
                "preferred_v2_outputs": counts["v2"],
                "overall_verdict": judge.result["overall_verdict"],
                "limitations": judge.result["limitations"],
            }
        )
        for evaluation in judge.result["system_evaluations"]:
            pipeline_id = anon_to_pipeline[evaluation["anonymous_system_id"]]
            record = generators_by_id[pipeline_id]
            system_rows.append(
                {
                    "source_id": judge.source_id,
                    "judge_id": judge.judge_id,
                    "skill_version": record.skill_version,
                    "repeat": record.repeat,
                    "pipeline_id": pipeline_id,
                    "computed_score_x100": judge.validation["computed_system_score_x100"][
                        evaluation["anonymous_system_id"]
                    ],
                    "strengths": list(evaluation["strengths"]),
                    "weaknesses": list(evaluation["weaknesses"]),
                }
            )
    return {
        "quality_score_differences": rows,
        "mean_absolute_quality_difference_x100": _round(
            _mean(row["absolute_difference"] for row in rows)
        ),
        "preferred_output_counts": preference_rows,
        "system_strengths_and_weaknesses": system_rows,
        "free_topic_partition_agreement": list(partition_rows),
    }


def _acceptance(
    quality: Mapping[str, Any],
    evidence: Mapping[str, Any],
    efficiency: Mapping[str, Any],
) -> dict[str, Any]:
    quality_delta = quality["v2_minus_v1_x100"]
    quality_pass = quality_delta >= -2
    evidence_pass = evidence["v2_outward_exact_evidence_failure_count"] == 0
    lower_bound_ratios = efficiency["successful_artifact_lower_bound_v2_to_v1_ratio"]
    elapsed_ratio = lower_bound_ratios["elapsed_seconds"]
    token_ratio = lower_bound_ratios["reported_total_tokens"]
    unbound_repair_cost = efficiency["unbound_repair_cost"]
    ratios_known = elapsed_ratio is not None and token_ratio is not None
    within_efficiency = ratios_known and elapsed_ratio <= 3 and token_ratio <= 3
    if unbound_repair_cost["present"]:
        efficiency_status = "inconclusive_unbound_repair_cost"
        efficiency_reason = (
            "Successful-artifact ratios are lower bounds only. Completion receipts prove "
            f"{unbound_repair_cost['completion_bound_repair_attempt_count']} repair attempt(s), "
            "but do not hash-bind failed-attempt token/time metadata, so total cost has no "
            "verified upper bound and v2 cannot pass the efficiency gate."
        )
    elif within_efficiency:
        efficiency_status = "passed"
        efficiency_reason = "Both source-first elapsed and reported-token ratios are <=3x."
    elif quality_delta > 0:
        efficiency_status = "conditional_quality_justification_required"
        efficiency_reason = (
            f"At least one ratio exceeds 3x; the measured dual-Judge quality gain is "
            f"{quality_delta:+.3f}/100. This quantified gain is the only available quality "
            "rationale and requires an explicit product trade-off decision."
        )
    else:
        efficiency_status = "failed"
        efficiency_reason = "At least one ratio exceeds 3x without a measured quality gain."
    gates = {
        "quality_no_worse_than_v1_by_more_than_2": {
            "status": "passed" if quality_pass else "failed",
            "observed_v2_minus_v1_x100": quality_delta,
            "threshold": ">=-2",
        },
        "v2_outward_exact_evidence_failures_zero": {
            "status": "passed" if evidence_pass else "failed",
            "observed": evidence["v2_outward_exact_evidence_failure_count"],
            "threshold": 0,
        },
        "efficiency_within_3x_or_quality_justified": {
            "status": efficiency_status,
            "successful_artifact_lower_bound_elapsed_ratio": elapsed_ratio,
            "successful_artifact_lower_bound_reported_total_token_ratio": token_ratio,
            "reason": efficiency_reason,
        },
    }
    if not quality_pass or not evidence_pass or efficiency_status == "failed":
        recommendation = "reject_v2_for_production"
    elif efficiency_status == "inconclusive_unbound_repair_cost":
        recommendation = "inconclusive_v2_pending_bound_efficiency_evidence"
    elif efficiency_status != "passed":
        recommendation = "conditional_v2_requires_efficiency_tradeoff_decision"
    else:
        recommendation = "accept_v2_for_next_integration_gate"
    return {"recommendation": recommendation, "gates": gates}


def analyze_verified_experiment(verified: VerifiedExperiment) -> dict[str, Any]:
    _expect(len(verified.generators) == 12, "verified generator record count is not 12")
    _expect(len(verified.judges) == 6, "verified Judge record count is not 6")
    generators_by_id = {record.pipeline_id: record for record in verified.generators}
    _expect(len(generators_by_id) == 12, "generator IDs are not unique")
    for source_id in verified.source_ids:
        source_records = [record for record in verified.generators if record.source_id == source_id]
        for skill in SKILL_VERSIONS:
            repeats = {record.repeat for record in source_records if record.skill_version == skill}
            _expect(repeats == {1, 2}, f"missing repeats for {source_id}/{skill}")

    quality = _quality_analysis(verified, generators_by_id)
    coverage = _coverage_and_stability(verified)
    evidence = _evidence_and_repairs(verified)
    efficiency = _efficiency(verified)
    topics, semantic_rows, partition_rows = _topic_analysis(verified, generators_by_id)
    disagreement = _judge_disagreement(verified, quality, generators_by_id, partition_rows)
    acceptance = _acceptance(quality, evidence, efficiency)
    return {
        "schema_version": SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "integrity": {
            "status": "passed",
            "experiment_id": verified.experiment_id,
            "validated_generator_pipeline_receipts": 12,
            "validated_dual_judge_receipts": 6,
            "unblinded_only_after_all_judges_completed": True,
            "source_first_aggregation": True,
            "unique_source_count": 3,
            "alias_weighting": False,
        },
        "scope": {
            "generator_configuration": verified.generator_configuration,
            "judge_configuration": verified.judge_configuration,
            "sources": {
                source_id: {
                    "filename": verified.source_metadata_by_id[source_id].get("filename"),
                    "source_sha256": verified.source_metadata_by_id[source_id].get("source_sha256"),
                }
                for source_id in verified.source_ids
            },
        },
        "acceptance": acceptance,
        "quality": quality,
        "coverage_and_stability": coverage,
        "evidence_and_repairs": evidence,
        "efficiency": efficiency,
        "semantic_topic_metrics": semantic_rows,
        "judge_disagreement": disagreement,
        "topics": topics,
        "traceability": {
            "path_base": "experiment_dir",
            "judge_run_dir": verified.judge_run_dir.relative_to(verified.experiment_dir).as_posix(),
            "generator_artifacts": [
                {
                    "pipeline_id": record.pipeline_id,
                    "result": record.result_path.relative_to(verified.experiment_dir).as_posix(),
                    "completion": record.completion_path.relative_to(
                        verified.experiment_dir
                    ).as_posix(),
                }
                for record in verified.generators
            ],
            "judge_artifacts": [
                {
                    "source_id": record.source_id,
                    "judge_id": record.judge_id,
                    "result": record.result_path.relative_to(verified.experiment_dir).as_posix(),
                    "completion": record.completion_path.relative_to(
                        verified.experiment_dir
                    ).as_posix(),
                    "post_judgment_mapping": record.binding_path.relative_to(
                        verified.experiment_dir
                    ).as_posix(),
                }
                for record in verified.judges
            ],
        },
        "limitations": [
            "Only three unique development sources were tested; this is not a genre holdout.",
            "The two repeats use the same fixed candidate order and measure sampling stability only.",
            "No independent human Topic gold inventory exists; all coverage is relative to the observed selected union, never absolute recall.",
            "Both Judges are model-based; disagreement is reported, but shared family bias may remain.",
            "v1 exact-quote figures are a shadow audit of mixed editorial/evidence copy and are not directly symmetric with the v2 outward hard gate.",
            "Failed repair-attempt token/time metadata is not generator-completion-hash-bound; successful-artifact efficiency ratios are lower bounds and repairs make the hard efficiency gate inconclusive.",
            "No price configuration was frozen, so monetary cost is intentionally not estimated.",
        ],
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _display(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="muted">无数据</p>'
    head = "".join(f"<th>{_escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{_escape(_display(row.get(key)))}</td>" for key, _ in columns)
        body.append(f"<tr>{cells}</tr>")
    return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def _relative_href(report_path: Path, target: Path) -> str:
    relative = os.path.relpath(target, report_path.parent)
    return quote(Path(relative).as_posix(), safe="/._-")


def _status_pill(status: str) -> str:
    css = (
        "good"
        if status == "passed"
        else "warn"
        if "conditional" in status or "inconclusive" in status
        else "bad"
    )
    return f'<span class="pill {css}">{_escape(status)}</span>'


def render_html_report(
    analysis: Mapping[str, Any],
    verified: VerifiedExperiment,
    report_path: Path,
) -> str:
    quality = analysis["quality"]
    acceptance = analysis["acceptance"]
    filenames = {
        source_id: str(verified.source_metadata_by_id[source_id].get("filename", source_id))
        for source_id in verified.source_ids
    }
    generator_label = " / ".join(
        filter(
            None,
            (
                verified.generator_configuration.get("model"),
                verified.generator_configuration.get("reasoning_effort"),
            ),
        )
    )
    judge_label = "；".join(
        f"{judge_id}: {configuration.get('model')} / {configuration.get('reasoning_effort')}"
        for judge_id, configuration in verified.judge_configuration.items()
    )
    quality_rows = []
    for skill in SKILL_VERSIONS:
        quality_rows.append(
            {
                "skill": skill,
                "judge_01": quality["by_judge"]["judge_01"][skill]["source_first_macro_x100"],
                "judge_02": quality["by_judge"]["judge_02"][skill]["source_first_macro_x100"],
                "dual": quality["dual_judge"][skill]["source_first_macro_x100"],
            }
        )
    source_quality_rows = [
        {
            "source_id": source_id,
            "filename": filenames[source_id],
            "v1": quality["dual_judge"]["v1"]["by_source"][source_id],
            "v2": quality["dual_judge"]["v2"]["by_source"][source_id],
            "delta": _round(
                quality["dual_judge"]["v2"]["by_source"][source_id]
                - quality["dual_judge"]["v1"]["by_source"][source_id]
            ),
        }
        for source_id in verified.source_ids
    ]
    dimension_rows = [
        {
            "skill": skill,
            **quality["dual_judge"][skill]["source_first_dimensions_x100"],
        }
        for skill in SKILL_VERSIONS
    ]
    efficiency_rows = []
    for skill in SKILL_VERSIONS:
        skill_data = analysis["efficiency"]["completion_bound_successful_lower_bound_source_first"][
            skill
        ]
        efficiency_rows.append(
            {
                "skill": skill,
                "elapsed": skill_data["elapsed_seconds"]["macro"],
                "tokens": skill_data["tokens"]["reported_total_tokens"]["macro"],
                "calls": skill_data["total_model_calls"],
            }
        )
    source_rows = [
        {"filename": filenames[row["source_id"]], **row}
        for row in analysis["coverage_and_stability"]["by_source"]
    ]
    stability_rows = [
        {
            "source_id": row["source_id"],
            "filename": filenames[row["source_id"]],
            "skill": row["skill_version"],
            "candidate_jaccard": row["repeat_candidate_jaccard"],
            "interval_f1": row["repeat_interval_match"]["f1"],
        }
        for row in analysis["coverage_and_stability"]["sampling_stability"]
    ]
    disagreement_rows = [
        {"filename": filenames[row["source_id"]], **row}
        for row in analysis["judge_disagreement"]["quality_score_differences"]
    ]
    overlap_rows = [
        {
            "source_id": row["source_id"],
            "filename": filenames[row["source_id"]],
            "skill": row["skill_version"],
            "repeat": row["repeat"],
            "duplicates": row["duplicate_candidate_count"],
            "interval_overlap_pairs": row["interval_overlap_pair_count_above_0_45"],
        }
        for row in analysis["coverage_and_stability"]["duplicates_and_interval_overlap"]
    ]
    semantic_rows = [
        {
            "source_id": row["source_id"],
            "filename": filenames[row["source_id"]],
            "judge": row["judge_id"],
            "skill": row["skill_version"],
            "repeat": row["repeat"],
            "clusters": row["observed_topic_cluster_count"],
            "relative_cluster_coverage": row["relative_judged_cluster_coverage"],
            "semantic_duplicate_rate": row["within_output_semantic_duplicate_rate"],
        }
        for row in analysis["semantic_topic_metrics"]
    ]
    repair_rows = [
        {"skill": skill, **analysis["evidence_and_repairs"]["repair_summary"][skill]}
        for skill in SKILL_VERSIONS
    ]
    supplemental_rows = [
        {
            "source_id": row["source_id"],
            "skill": row["skill_version"],
            "repeat": row["repeat"],
            "attempt": row["attempt"],
            "status": row["status"],
            "elapsed": row["elapsed_seconds"],
            "tokens": (
                row["usage"]["reported_total_tokens"] if isinstance(row["usage"], dict) else None
            ),
            "bound": row["completion_receipt_bound"],
        }
        for row in analysis["efficiency"]["supplemental_unbound_attempt_observations"]
    ]
    judge_narratives = "".join(
        "<article class='topic'>"
        f"<h4>{_escape(row['source_id'])} · {_escape(row['judge_id'])}</h4>"
        f"<p><strong>Overall verdict：</strong>{_escape(row['overall_verdict'])}</p>"
        f"<p><strong>Limitations：</strong>{_escape('；'.join(row['limitations']))}</p>"
        "</article>"
        for row in analysis["judge_disagreement"]["preferred_output_counts"]
    )
    system_rows = [
        {
            "source_id": row["source_id"],
            "judge": row["judge_id"],
            "skill": row["skill_version"],
            "repeat": row["repeat"],
            "score": row["computed_score_x100"],
            "strengths": "；".join(row["strengths"]),
            "weaknesses": "；".join(row["weaknesses"]),
        }
        for row in analysis["judge_disagreement"]["system_strengths_and_weaknesses"]
    ]

    topic_sections: list[str] = []
    topics_by_group: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for topic in analysis["topics"]:
        topics_by_group[(topic["source_id"], topic["judge_id"])].append(topic)
    generator_paths = {record.pipeline_id: record.result_path for record in verified.generators}
    for (source_id, judge_id), topics in sorted(topics_by_group.items()):
        cards = []
        for topic in topics:
            members = []
            for member in topic["members"]:
                href = _relative_href(report_path, generator_paths[member["pipeline_id"]])
                members.append(
                    "<li>"
                    f"<strong>{_escape(member['skill_version'])} / repeat {member['repeat']}</strong> · "
                    f"{_escape(member['title'])} · 成员分 {_escape(member['judge_member_score_x100'])}/100"
                    f"<br><span class='quote'>“{_escape(member['evidence_or_edited_sentence'])}”</span>"
                    f"<br>Judge：{_escape(member['assessment'])} "
                    f"<a href='{href}'>生成结果</a>"
                    "</li>"
                )
            cards.append(
                "<article class='topic'>"
                f"<h4>{_escape(topic['canonical_topic'])}</h4>"
                f"<p class='micro'>{_escape(topic['cluster_id'])} · confidence "
                f"{_escape(topic['alignment_confidence'])} · {topic['member_count']} members</p>"
                f"<p>{_escape(topic['topic_assessment'])}</p><ul>{''.join(members)}</ul>"
                "</article>"
            )
        judge_record = next(
            record
            for record in verified.judges
            if record.source_id == source_id and record.judge_id == judge_id
        )
        judge_href = _relative_href(report_path, judge_record.result_path)
        topic_sections.append(
            "<details open><summary>"
            f"{_escape(filenames[source_id])} ({_escape(source_id)}) · "
            f"{_escape(judge_id)} · {len(topics)} Topics"
            f" · <a href='{judge_href}'>Judge 原始结果</a></summary>"
            f"<div class='topic-grid'>{''.join(cards)}</div></details>"
        )

    trace_rows = []
    for record in verified.generators:
        trace_rows.append(
            {
                "kind": "generator",
                "id": record.pipeline_id,
                "source": record.source_id,
                "link": f"<a href='{_relative_href(report_path, record.completion_path)}'>complete.json</a>",
            }
        )
    for record in verified.judges:
        trace_rows.append(
            {
                "kind": "judge",
                "id": record.judge_id,
                "source": record.source_id,
                "link": f"<a href='{_relative_href(report_path, record.completion_path)}'>complete.json</a>",
            }
        )
    trace_table = (
        "<div class='scroll'><table><thead><tr><th>类型</th><th>ID</th><th>Source</th>"
        "<th>相对链接</th></tr></thead><tbody>"
        + "".join(
            f"<tr><td>{_escape(row['kind'])}</td><td>{_escape(row['id'])}</td>"
            f"<td>{_escape(row['source'])}</td><td>{row['link']}</td></tr>"
            for row in trace_rows
        )
        + "</tbody></table></div>"
    )
    gates_html = "".join(
        f"<li>{_status_pill(gate['status'])} <strong>{_escape(name)}</strong>"
        f"<pre>{_escape(json.dumps(gate, ensure_ascii=False, indent=2))}</pre></li>"
        for name, gate in acceptance["gates"].items()
    )
    limitations = "".join(f"<li>{_escape(item)}</li>" for item in analysis["limitations"])
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LiveClip Highlight Agent v2 · Iteration 1</title>
<style>
:root{{--bg:#f4f6f8;--panel:#fff;--ink:#172033;--muted:#667085;--line:#d8dee8;--accent:#3157d5;--good:#157347;--warn:#a15c00;--bad:#b42318}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.58 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}
main{{max-width:1320px;margin:auto;padding:32px}}h1{{font-size:30px;margin:0 0 8px}}h2{{margin-top:0}}a{{color:var(--accent)}}.hero,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:18px;box-shadow:0 2px 8px #1118270b}}
.hero{{border-top:5px solid var(--accent)}}.micro,.muted{{color:var(--muted);font-size:13px}}.pill{{display:inline-block;padding:2px 8px;border-radius:99px;background:#eef2ff;font-size:12px}}.pill.good{{color:var(--good);background:#eaf7ef}}.pill.warn{{color:var(--warn);background:#fff4df}}.pill.bad{{color:var(--bad);background:#ffebe9}}
.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:650px}}th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:#f8fafc;position:sticky;top:0}}pre{{white-space:pre-wrap;background:#f7f8fa;padding:10px;border-radius:8px;font-size:12px}}details{{border-top:1px solid var(--line);padding:10px 0}}summary{{cursor:pointer;font-weight:650}}.topic-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px;margin-top:12px}}.topic{{border:1px solid var(--line);border-radius:10px;padding:14px}}.topic h4{{margin:0}}.topic li{{margin:9px 0}}.quote{{color:#344054}}@media(max-width:700px){{main{{padding:15px}}}}
</style></head><body><main>
<section class="hero"><h1>Highlight Agent v2 · Iteration 1</h1>
<p>Generator：{_escape(generator_label)}；Judges：{_escape(judge_label)}。3 个唯一 source、每版每 source 2 次 sampling、双 Judge 匿名盲审。</p>
<p><strong>结论：</strong>{_escape(acceptance["recommendation"])} · v2-v1 双 Judge 质量差 {_escape(quality["v2_minus_v1_x100"])}/100。</p>
<p class="micro">完整性：12/12 generator receipts，6/6 Judge receipts；全部验证后才解盲。Source-first 宏平均，不按 alias 加权。</p></section>
<section class="panel"><h2>验收门</h2><ul>{gates_html}</ul></section>
<section class="panel"><h2>质量总览</h2>{_table(quality_rows, [("skill", "Skill"), ("judge_01", "Judge 01"), ("judge_02", "Judge 02"), ("dual", "双 Judge 平均")])}<h3>双 Judge 原子维度</h3>{_table(dimension_rows, [("skill", "Skill"), ("discovery_x100", "Discovery"), ("coverage_x100", "相对 coverage"), ("precision_x100", "Precision"), ("stability_x100", "Sampling stability"), ("editorial_readiness_x100", "Editorial readiness")])}<h3>按唯一 Source</h3>{_table(source_quality_rows, [("filename", "源文件"), ("source_id", "Source"), ("v1", "v1 双 Judge"), ("v2", "v2 双 Judge"), ("delta", "v2-v1")])}</section>
<section class="panel"><h2>效率</h2><p><strong>硬门只使用 completion-hash-bound 成功调用；下表是总成本下界。</strong></p>{_table(efficiency_rows, [("skill", "Skill"), ("elapsed", "Source-first 成功耗时下界"), ("tokens", "成功 reported tokens 下界"), ("calls", "绑定成功调用数")])}<p>{_escape(analysis["efficiency"]["unbound_repair_cost"]["reason"])}</p><h3>失败 repair 的非绑定补充观察</h3>{_table(supplemental_rows, [("source_id", "Source"), ("skill", "Skill"), ("repeat", "Repeat"), ("attempt", "Attempt"), ("status", "Status"), ("elapsed", "观察耗时"), ("tokens", "观察 tokens"), ("bound", "Completion bound")])}<p>{_escape(analysis["efficiency"]["cost"]["reason"])}</p></section>
<section class="panel"><h2>Selected-union 相对 coverage</h2><p>{_escape(analysis["coverage_and_stability"]["definition"])}</p>{_table(source_rows, [("filename", "源文件"), ("source_id", "Source"), ("observed_selected_union_count", "全系统 selected union"), ("v1_selected_union_count", "v1 union"), ("v1_relative_selected_union_coverage", "v1 相对 coverage"), ("v2_selected_union_count", "v2 union"), ("v2_relative_selected_union_coverage", "v2 相对 coverage")])}</section>
<section class="panel"><h2>Sampling stability</h2><p>两次重复保持相同候选顺序，因此这里只衡量 sampling stability，不证明 order robustness。</p>{_table(stability_rows, [("filename", "源文件"), ("source_id", "Source"), ("skill", "Skill"), ("candidate_jaccard", "候选 Jaccard"), ("interval_f1", "时间区间匹配 F1")])}</section>
<section class="panel"><h2>重复、重叠与语义 coverage</h2><h3>确定性候选/时间检查</h3>{_table(overlap_rows, [("filename", "源文件"), ("source_id", "Source"), ("skill", "Skill"), ("repeat", "Repeat"), ("duplicates", "重复候选"), ("interval_overlap_pairs", "IoU > 0.45 pairs")])}<h3>Judge 自由 Topic 诊断</h3>{_table(semantic_rows, [("filename", "源文件"), ("source_id", "Source"), ("judge", "Judge"), ("skill", "Skill"), ("repeat", "Repeat"), ("clusters", "覆盖 Topic clusters"), ("relative_cluster_coverage", "相对 cluster coverage"), ("semantic_duplicate_rate", "语义重复率")])}</section>
<section class="panel"><h2>Judge 分歧</h2><p>双 Judge 质量分平均绝对差：{_escape(analysis["judge_disagreement"]["mean_absolute_quality_difference_x100"])}/100。</p>{_table(disagreement_rows, [("filename", "源文件"), ("source_id", "Source"), ("skill_version", "Skill"), ("judge_01_x100", "Judge 01"), ("judge_02_x100", "Judge 02"), ("absolute_difference", "绝对差")])}<h3>Judge 首选输出计数</h3>{_table(analysis["judge_disagreement"]["preferred_output_counts"], [("source_id", "Source"), ("judge_id", "Judge"), ("preferred_v1_outputs", "首选 v1 outputs"), ("preferred_v2_outputs", "首选 v2 outputs")])}<h3>每系统 strengths / weaknesses</h3>{_table(system_rows, [("source_id", "Source"), ("judge", "Judge"), ("skill", "Skill"), ("repeat", "Repeat"), ("score", "Score"), ("strengths", "Strengths"), ("weaknesses", "Weaknesses")])}<h3>Judge overall verdict / limitations</h3><div class="topic-grid">{judge_narratives}</div><h3>自由 Topic 分区一致性</h3>{_table(analysis["judge_disagreement"]["free_topic_partition_agreement"], [("source_id", "Source"), ("shared_co_cluster_pairs", "共享同簇 pair"), ("judge_01_co_cluster_pairs", "Judge 01 pairs"), ("judge_02_co_cluster_pairs", "Judge 02 pairs"), ("f1", "Pair F1")])}</section>
<section class="panel"><h2>每个 Source / Topic 的评价</h2><p>Topic 由每个 Judge 自由发现；不同 Judge 的 Topic 不强制同名。每个成员只出现一次。</p>{"".join(topic_sections)}</section>
<section class="panel"><h2>证据与修复</h2><p>v2 outward exact evidence failures：{_escape(analysis["evidence_and_repairs"]["v2_outward_exact_evidence_failure_count"])}。{_escape(analysis["evidence_and_repairs"]["v1_note"])}</p><h3>Repair rate</h3>{_table(repair_rows, [("skill", "Skill"), ("pipeline_count", "Pipelines"), ("pipelines_with_repair", "有 repair 的 pipelines"), ("pipeline_repair_rate", "Repair rate"), ("total_repairs", "Repairs")])}<h3>逐 Pipeline</h3>{_table(analysis["evidence_and_repairs"]["by_pipeline"], [("source_id", "Source"), ("skill_version", "Skill"), ("repeat", "Repeat"), ("exact_quote_failure_count", "Exact quote failures"), ("repair_count", "Repairs")])}</section>
<section class="panel"><h2>限制</h2><ul>{limitations}</ul></section>
<section class="panel"><h2>可追溯证据</h2><p>以下均为相对于本 HTML 的本地链接。</p>{trace_table}</section>
</main></body></html>"""


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _expect(path.is_file() and not path.is_symlink(), f"unsafe report target: {path}")
        if path.read_bytes() == payload:
            return
        raise AnalysisError(
            f"refusing to overwrite immutable report artifact with different bytes: {path}"
        )
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_report(
    analysis: Mapping[str, Any],
    verified: VerifiedExperiment,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir = output_dir.resolve()
    analysis_path = output_dir / "analysis.json"
    report_path = output_dir / "REPORT.html"
    analysis_payload = (
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    report_payload = render_html_report(analysis, verified, report_path).encode("utf-8")
    _atomic_write(analysis_path, analysis_payload)
    _atomic_write(report_path, report_payload)
    return analysis_path, report_path


def _discover_experiment() -> Path:
    candidates: list[Path] = []
    for path in DEFAULT_EXPERIMENTS_ROOT.glob("exp_*"):
        summary_path = path / "run-summary.json"
        if not summary_path.is_file():
            continue
        summary = _load_json(summary_path)
        if summary.get("status") == "generation_completed":
            candidates.append(path)
    if len(candidates) != 1:
        raise AnalysisError(
            "default discovery requires exactly one generation_completed experiment; "
            f"found {len(candidates)}. Pass --experiment-dir explicitly."
        )
    return candidates[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path)
    parser.add_argument("--judge-run-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        experiment_dir = args.experiment_dir or _discover_experiment()
        verified = load_verified_experiment(experiment_dir, args.judge_run_dir)
        analysis = analyze_verified_experiment(verified)
        output_dir = args.output_dir or (
            DEFAULT_REPORTS_ROOT / verified.experiment_id / verified.judge_run_dir.name
        )
        analysis_path, report_path = write_report(analysis, verified, output_dir)
    except (AnalysisError, FileNotFoundError) as exc:
        print(f"ANALYSIS REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"ANALYSIS: {analysis_path}")
    print(f"REPORT: {report_path}")
    print(f"RECOMMENDATION: {analysis['acceptance']['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
