#!/usr/bin/env python3
"""Validate and aggregate the frozen LiveClip model benchmark.

The primary estimate gives each of the three unique source hashes equal weight:
first average the two blind judges inside a replicate, then average replicates
inside a source, and only then macro-average sources.  Diagnostic evidence sets
are intentionally excluded from every primary headline metric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_CASES = BENCHMARK_DIR / "cases.json"
DEFAULT_PROTOCOL = BENCHMARK_DIR / "protocol.json"
DEFAULT_RESULTS = BENCHMARK_DIR / "results"
DEFAULT_OUTPUT = BENCHMARK_DIR / "analysis.json"

ATOMIC_WEIGHTS = {
    "topic_discovery": 30,
    "evidence_fidelity": 20,
    "clip_selection": 20,
    "editorial_usability": 15,
    "portfolio_quality": 15,
}
MEMBER_SCORES = (
    "claim_fidelity",
    "editorial_value",
    "hook_strength",
    "expression_completeness",
    "title_copy_quality",
    "representative_quality",
)
GENERATOR_FIELDS = {
    "candidate_id",
    "topic",
    "title",
    "highlight_sentence",
    "script_description",
    "score",
    "hook",
    "selection_reason",
    "risk_flags",
}
ENRICHED_GENERATOR_FIELDS = GENERATOR_FIELDS | {"source_start_ms", "source_end_ms"}
PUNCTUATION_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)
CANDIDATE_ID_RE = re.compile(r"^candidate_[a-f0-9]{16}$")
HIGHLIGHT_ID_RE = re.compile(r"^h[0-9]{2}$")
CLUSTER_ID_RE = re.compile(r"^t[0-9]{3}$")
GENERATOR_ORDER = ("terra_medium", "sol_medium", "sol_high")
ANONYMOUS_IDS = ("Q7", "M4", "R2")


class AnalysisError(RuntimeError):
    """An integrity or aggregation precondition failed."""


def _fail(message: str) -> None:
    raise AnalysisError(message)


def _load_json(path: Path) -> Any:
    if not path.is_file():
        _fail(f"missing artifact: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"cannot read JSON artifact {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise AnalysisError(f"cannot hash artifact {path}: {exc}") from exc
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _round(value: float, places: int = 4) -> float:
    rounded = round(value, places)
    return 0.0 if rounded == 0 else rounded


def _mean(values: Iterable[float]) -> float:
    materialized = list(values)
    if not materialized:
        _fail("cannot average an empty collection")
    return sum(materialized) / len(materialized)


def _expect(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _expect_keys(value: Any, expected: set[str], context: str) -> None:
    _expect(isinstance(value, dict), f"{context} must be an object")
    actual = set(value)
    _expect(actual == expected, f"{context} keys differ: {sorted(actual ^ expected)}")


def _expect_string(value: Any, context: str, *, minimum: int = 1, maximum: int) -> None:
    _expect(isinstance(value, str), f"{context} must be a string")
    _expect(minimum <= len(value) <= maximum, f"{context} length is outside Schema")


def _expect_score(value: Any, context: str, *, minimum: int, maximum: int) -> None:
    _expect(isinstance(value, int) and not isinstance(value, bool), f"{context} must be int")
    _expect(minimum <= value <= maximum, f"{context} is outside [{minimum}, {maximum}]")


def _normalize_evidence(value: str) -> str:
    return PUNCTUATION_RE.sub("", unicodedata.normalize("NFKC", value).casefold())


def quote_alignment(quote: str, candidate_text: str) -> dict[str, Any]:
    """Recompute the runner's deterministic quote-alignment diagnostic."""
    normalized_quote = _normalize_evidence(quote)
    normalized_candidate = _normalize_evidence(candidate_text)
    exact = bool(normalized_quote) and normalized_quote in normalized_candidate
    matcher = SequenceMatcher(None, normalized_quote, normalized_candidate, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = matched / len(normalized_quote) if normalized_quote else 0.0
    status = "exact" if exact else "high_similarity" if coverage >= 0.85 else "failed"
    return {
        "status": status,
        "exact_normalized_substring": exact,
        "matched_character_coverage": _round(coverage),
    }


def candidate_jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    left_set, right_set = set(left), set(right)
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 1.0


def _interval_iou(left: tuple[int, int], right: tuple[int, int]) -> float:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return intersection / union if union > 0 else 0.0


def interval_match(
    left: Sequence[tuple[int, int]],
    right: Sequence[tuple[int, int]],
    *,
    threshold: float = 0.5,
) -> dict[str, float | int]:
    """Maximum-cardinality interval match and F1 at the requested IoU threshold."""
    adjacency = [
        sorted(
            (index for index, other in enumerate(right) if _interval_iou(item, other) >= threshold),
            key=lambda index: (-_interval_iou(item, right[index]), index),
        )
        for item in left
    ]
    matched_left_for_right: dict[int, int] = {}

    def augment(left_index: int, visited: set[int]) -> bool:
        for right_index in adjacency[left_index]:
            if right_index in visited:
                continue
            visited.add(right_index)
            prior = matched_left_for_right.get(right_index)
            if prior is None or augment(prior, visited):
                matched_left_for_right[right_index] = left_index
                return True
        return False

    matches = sum(augment(index, set()) for index in range(len(left)))
    precision = matches / len(left) if left else (1.0 if not right else 0.0)
    recall = matches / len(right) if right else (1.0 if not left else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "matches": matches,
        "left_count": len(left),
        "right_count": len(right),
        "precision": _round(precision),
        "recall": _round(recall),
        "f1": _round(f1),
    }


def _comb2(value: int) -> int:
    return value * (value - 1) // 2


def adjusted_rand_index(left: dict[str, str], right: dict[str, str]) -> float:
    """Adjusted Rand Index for two complete partitions over identical entity IDs."""
    _expect(set(left) == set(right), "partition entity sets differ")
    entity_count = len(left)
    if entity_count < 2:
        return 1.0
    contingency = Counter((left[key], right[key]) for key in left)
    left_sizes = Counter(left.values())
    right_sizes = Counter(right.values())
    pair_count = _comb2(entity_count)
    index = sum(_comb2(size) for size in contingency.values())
    left_pairs = sum(_comb2(size) for size in left_sizes.values())
    right_pairs = sum(_comb2(size) for size in right_sizes.values())
    expected = left_pairs * right_pairs / pair_count
    maximum = (left_pairs + right_pairs) / 2
    denominator = maximum - expected
    if denominator == 0:
        return 1.0 if left_pairs == right_pairs == index else 0.0
    return (index - expected) / denominator


def co_cluster_f1(left: dict[str, str], right: dict[str, str]) -> dict[str, float | int]:
    _expect(set(left) == set(right), "partition entity sets differ")
    entities = sorted(left)
    left_pairs = {
        (first, second)
        for first, second in combinations(entities, 2)
        if left[first] == left[second]
    }
    right_pairs = {
        (first, second)
        for first, second in combinations(entities, 2)
        if right[first] == right[second]
    }
    shared = len(left_pairs & right_pairs)
    precision = shared / len(left_pairs) if left_pairs else (1.0 if not right_pairs else 0.0)
    recall = shared / len(right_pairs) if right_pairs else (1.0 if not left_pairs else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "shared_positive_pairs": shared,
        "left_positive_pairs": len(left_pairs),
        "right_positive_pairs": len(right_pairs),
        "precision": _round(precision),
        "recall": _round(recall),
        "f1": _round(f1),
    }


def _score_system(atomics: dict[str, int]) -> float:
    return _round(sum(atomics[name] / 4 * weight for name, weight in ATOMIC_WEIGHTS.items()), 1)


def _rank_tau(left: dict[str, float], right: dict[str, float]) -> float:
    names = sorted(left)
    concordant = discordant = 0
    for first, second in combinations(names, 2):
        left_delta = left[first] - left[second]
        right_delta = right[first] - right[second]
        if left_delta == 0 or right_delta == 0:
            continue
        if left_delta * right_delta > 0:
            concordant += 1
        else:
            discordant += 1
    comparable = concordant + discordant
    return (concordant - discordant) / comparable if comparable else 1.0


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


class BenchmarkAnalyzer:
    def __init__(self, cases_path: Path, protocol_path: Path, results_dir: Path) -> None:
        self.cases_path = cases_path.resolve()
        self.protocol_path = protocol_path.resolve()
        self.results_dir = results_dir.resolve()
        self.cases_config = _load_json(self.cases_path)
        self.protocol = _load_json(self.protocol_path)
        self.generator_configs: dict[str, dict[str, str]] = self.protocol.get(
            "generator_models", {}
        )
        self.judge_configs: dict[str, dict[str, str]] = self.protocol.get("judge_models", {})
        self.generator_schema_path = BENCHMARK_DIR / "schemas/highlight-output.schema.json"
        self.judge_schema_path = BENCHMARK_DIR / "schemas/judge-output.schema.json"
        self.base_generator_schema = _load_json(self.generator_schema_path)
        self.base_judge_schema = _load_json(self.judge_schema_path)
        self.manifest: list[dict[str, str]] = []

    def analyze(self) -> dict[str, Any]:
        self._validate_protocol()
        cases = self._validate_case_plan()
        records = [
            self._load_replicate(case, number)
            for case in cases
            for number in range(1, case["replicates"] + 1)
        ]
        self._validate_artifact_counts(records)
        primary_records = [item for item in records if item["include_in_primary_aggregate"]]
        diagnostic_records = [item for item in records if not item["include_in_primary_aggregate"]]
        primary = self._aggregate_primary(primary_records)
        diagnostics = self._aggregate_diagnostics(diagnostic_records, primary_records)
        return {
            "schema_version": "1",
            "generated_at": datetime.now(UTC).isoformat(),
            "integrity": {
                "status": "passed",
                "expected_generator_outputs": 30,
                "validated_generator_outputs": len(records) * len(self.generator_configs),
                "expected_judge_outputs": 20,
                "validated_judge_outputs": len(records) * len(self.judge_configs),
                "validated_replicates": len(records),
                "primary_unique_source_count": len(
                    {item["source_sha256"] for item in primary_records}
                ),
                "artifact_manifest": sorted(
                    self.manifest, key=lambda item: (item["path"], item["sha256"])
                ),
            },
            "scope": {
                "generator_configurations": self.generator_configs,
                "configuration_labels": {
                    "terra_medium": "GPT-5.6 Terra / medium",
                    "sol_medium": "GPT-5.6 Sol / medium",
                    "sol_high": "GPT-5.6 Sol / high",
                },
                "judge_configurations": self.judge_configs,
                "primary_cases": [
                    item["case_id"] for item in cases if item["include_in_primary_aggregate"]
                ],
                "diagnostic_cases": [
                    item["case_id"] for item in cases if not item["include_in_primary_aggregate"]
                ],
                "aggregation_rule": self.protocol["aggregation_rule"],
                "source_alias_map": {
                    evidence["source_label"]: evidence["source_aliases"]
                    for evidence in self.cases_config["evidence_sets"].values()
                },
                "aliases_have_zero_weight": True,
                "diagnostics_have_zero_primary_weight": True,
                "limitations": [
                    (
                        "Only three unique primary sources are available; this is not a "
                        "statistical significance claim."
                    ),
                    (
                        "All primary sources are singing-instruction livestreams, so "
                        "genre-specific Skill branches are not evaluated."
                    ),
                    (
                        "Replicates combine candidate-order perturbation with model sampling; "
                        "they do not isolate a causal order effect."
                    ),
                    (
                        "Blind judges see the selected-output union, not an independent "
                        "exhaustive truth inventory; topic recall is relative."
                    ),
                    (
                        "The 0-4 integer judge rubric can saturate; ceiling and tie diagnostics "
                        "must accompany score rankings."
                    ),
                    (
                        "SequenceMatcher character coverage is a heuristic and may overstate "
                        "continuous quote fidelity; failed cases require editorial inspection."
                    ),
                ],
            },
            "primary": primary,
            "diagnostics": diagnostics,
        }

    def _validate_protocol(self) -> None:
        _expect(self.protocol.get("schema_version") == "1", "unsupported protocol Schema")
        _expect(len(self.generator_configs) == 3, "benchmark must have three generator configs")
        _expect(len(self.judge_configs) == 2, "benchmark must have two judge configs")
        _expect(
            set(self.generator_configs) == {"terra_medium", "sol_medium", "sol_high"},
            "unexpected generator configuration set",
        )
        _expect(
            set(self.judge_configs) == {"terra_max", "sol_max"},
            "unexpected judge configuration set",
        )
        expected_hashes = {
            "cases": self.cases_path,
            "runtime_agent_skill": BENCHMARK_DIR / "agent-v1/SKILL.md",
            "generation_schema": self.generator_schema_path,
            "judge_prompt": BENCHMARK_DIR / "prompts/judge-v1.md",
            "judge_schema": self.judge_schema_path,
        }
        frozen_hashes = self.protocol.get("artifact_sha256")
        _expect(isinstance(frozen_hashes, dict), "protocol has no artifact hash block")
        for name, path in expected_hashes.items():
            actual = _sha256(path)
            _expect(frozen_hashes.get(name) == actual, f"protocol hash mismatch for {name}")
            self._remember(path)

    def _validate_case_plan(self) -> list[dict[str, Any]]:
        cases = self.cases_config.get("cases")
        evidence_sets = self.cases_config.get("evidence_sets")
        _expect(isinstance(cases, list) and cases, "cases.json has no cases")
        _expect(isinstance(evidence_sets, dict), "cases.json has no evidence sets")
        _expect(cases == self.protocol.get("cases"), "protocol/cases plan mismatch")
        case_ids = [item.get("case_id") for item in cases]
        _expect(len(case_ids) == len(set(case_ids)), "duplicate case ID")
        total_replicates = 0
        primary_hashes: list[str] = []
        for case in cases:
            _expect_keys(
                case,
                {"case_id", "evidence_set", "include_in_primary_aggregate", "replicates"},
                f"case {case.get('case_id')}",
            )
            evidence = evidence_sets.get(case["evidence_set"])
            _expect(isinstance(evidence, dict), f"unknown evidence set for {case['case_id']}")
            _expect(
                isinstance(case["replicates"], int) and case["replicates"] > 0,
                f"invalid replicate count for {case['case_id']}",
            )
            total_replicates += case["replicates"]
            is_primary = case["include_in_primary_aggregate"]
            _expect(isinstance(is_primary, bool), "include_in_primary_aggregate must be bool")
            if is_primary:
                _expect(evidence.get("benchmark_role") == "primary", "primary role mismatch")
                _expect(case["replicates"] == 3, "each primary case must have three replicates")
                primary_hashes.append(evidence["expected_source_sha256"])
            else:
                _expect(evidence.get("benchmark_role") != "primary", "diagnostic role mismatch")
        _expect(total_replicates == 10, "benchmark must contain exactly ten replicates")
        _expect(len(primary_hashes) == len(set(primary_hashes)) == 3, "primary sources not unique")
        return cases

    def _remember(self, path: Path) -> None:
        resolved = path.resolve()
        relative = (
            str(resolved.relative_to(BENCHMARK_DIR))
            if resolved.is_relative_to(BENCHMARK_DIR)
            else str(resolved)
        )
        item = {"path": relative, "sha256": _sha256(resolved)}
        if item not in self.manifest:
            self.manifest.append(item)

    def _load_replicate(self, case: dict[str, Any], number: int) -> dict[str, Any]:
        case_id = case["case_id"]
        replicate_id = f"r{number:03d}"
        context = f"{case_id}/{replicate_id}"
        directory = self.results_dir / case_id / replicate_id
        evidence = _load_json(directory / "frozen-input.json")
        provenance = _load_json(directory / "provenance.json")
        runtime_path = directory / "runtime-agent-instructions.md"
        _expect(runtime_path.is_file(), f"missing runtime instructions for {context}")
        generation_schema_path = directory / "frozen-generation-schema.json"
        generation_schema = _load_json(generation_schema_path)
        source = evidence.get("source")
        candidates = evidence.get("candidates")
        _expect(isinstance(source, dict), f"{context} has invalid source evidence")
        _expect(isinstance(candidates, list) and candidates, f"{context} has no candidates")
        candidate_map: dict[str, dict[str, Any]] = {}
        for item in candidates:
            candidate_id = item.get("candidate_id")
            _expect(
                isinstance(candidate_id, str) and CANDIDATE_ID_RE.fullmatch(candidate_id),
                f"{context} has invalid candidate ID",
            )
            _expect(candidate_id not in candidate_map, f"{context} repeats candidate ID")
            _expect(
                isinstance(item.get("source_start_ms"), int)
                and isinstance(item.get("source_end_ms"), int)
                and 0 <= item["source_start_ms"] < item["source_end_ms"],
                f"{context}/{candidate_id} has invalid interval",
            )
            candidate_map[candidate_id] = item
        _expect(source.get("candidate_count") == len(candidates), f"{context} count mismatch")
        evidence_config = self.cases_config["evidence_sets"][case["evidence_set"]]
        source_sha = source.get("source_sha256")
        _expect(
            source_sha == evidence_config["expected_source_sha256"],
            f"{context} source hash mismatch",
        )
        _expect(provenance.get("case_id") == case_id, f"{context} provenance case mismatch")
        _expect(
            provenance.get("replicate_id") == replicate_id,
            f"{context} provenance replicate mismatch",
        )
        _expect(
            provenance.get("include_in_primary_aggregate") == case["include_in_primary_aggregate"],
            f"{context} provenance aggregate flag mismatch",
        )
        _expect(provenance.get("source_sha256") == source_sha, f"{context} provenance hash")
        _expect(
            provenance.get("transcript_sha256") == source.get("transcript_sha256")
            and provenance.get("rough_candidates_sha256") == source.get("rough_candidates_sha256"),
            f"{context} evidence hashes differ",
        )
        candidate_order_hash = _sha256_value([item["candidate_id"] for item in candidates])
        _expect(
            provenance.get("candidate_order_sha256") == candidate_order_hash,
            f"{context} candidate-order hash mismatch",
        )
        _expect(
            provenance.get("runtime_agent_sha256")
            == _sha256_text(runtime_path.read_text(encoding="utf-8")),
            f"{context} runtime Agent hash mismatch",
        )
        _expect(
            provenance.get("generation_schema_sha256") == _sha256(generation_schema_path),
            f"{context} generation Schema hash mismatch",
        )
        expected_generation_schema = deepcopy(self.base_generator_schema)
        expected_generation_schema["properties"]["highlights"]["items"]["properties"][
            "candidate_id"
        ] = {"type": "string", "enum": [item["candidate_id"] for item in candidates]}
        _expect(
            generation_schema == expected_generation_schema,
            f"{context} frozen generation Schema differs",
        )
        for path in (
            directory / "frozen-input.json",
            directory / "provenance.json",
            runtime_path,
            generation_schema_path,
        ):
            self._remember(path)

        generators = {
            name: self._load_generator(directory, case_id, replicate_id, name, candidate_map)
            for name in self.generator_configs
        }
        judges = {
            name: self._load_judge(
                directory,
                case_id,
                replicate_id,
                name,
                evidence,
                candidate_map,
                generators,
            )
            for name in self.judge_configs
        }
        summary = _load_json(directory / "replicate-summary.json")
        _expect(summary.get("case_id") == case_id, f"{context} summary case mismatch")
        _expect(summary.get("replicate_id") == replicate_id, f"{context} summary rep mismatch")
        _expect(
            summary.get("include_in_primary_aggregate") == case["include_in_primary_aggregate"],
            f"{context} summary aggregate flag mismatch",
        )
        _expect(
            summary.get("generator_validation")
            == {name: value["validation"] for name, value in generators.items()},
            f"{context} generator summary is stale or incomplete",
        )
        _expect(
            summary.get("judge_validation")
            == {name: value["validation"] for name, value in judges.items()},
            f"{context} judge summary is stale or incomplete",
        )
        self._remember(directory / "replicate-summary.json")

        consensus = {}
        for model_name in self.generator_configs:
            atomics = {
                atomic: _round(
                    _mean(
                        judges[judge]["atomic_scores_by_model"][model_name][atomic]
                        for judge in self.judge_configs
                    )
                )
                for atomic in ATOMIC_WEIGHTS
            }
            consensus[model_name] = {
                "atomic_scores": atomics,
                "total": _round(
                    _mean(
                        judges[judge]["computed_total_by_model"][model_name]
                        for judge in self.judge_configs
                    )
                ),
            }

        return {
            "case_id": case_id,
            "replicate_id": replicate_id,
            "benchmark_role": provenance["benchmark_role"],
            "include_in_primary_aggregate": case["include_in_primary_aggregate"],
            "source_sha256": source_sha,
            "source_label": evidence_config["source_label"],
            "source_aliases": evidence_config["source_aliases"],
            "candidate_order": provenance["candidate_order"],
            "generators": generators,
            "judges": judges,
            "judge_consensus": consensus,
            "cross_configuration": self._cross_configuration(generators),
            "dual_judge_agreement": self._dual_judge_agreement(judges),
        }

    def _load_generator(
        self,
        directory: Path,
        case_id: str,
        replicate_id: str,
        config_name: str,
        candidates: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        context = f"{case_id}/{replicate_id}/generators/{config_name}"
        output_dir = directory / "generators" / config_name
        result_path = output_dir / "result.json"
        raw_path = output_dir / "result.raw.json"
        validation_path = output_dir / "validation.json"
        metadata_path = output_dir / "call-metadata.json"
        result = _load_json(result_path)
        raw = _load_json(raw_path)
        validation = _load_json(validation_path)
        metadata = _load_json(metadata_path)
        config = self.generator_configs[config_name]
        _expect(metadata.get("model") == config["model"], f"{context} model mismatch")
        _expect(
            metadata.get("reasoning_effort") == config["effort"],
            f"{context} effort mismatch",
        )
        _expect(
            metadata.get("label") == f"{case_id}-{replicate_id}-{config_name}"
            or metadata.get("reused") is True,
            f"{context} label mismatch",
        )
        if metadata.get("reused") is True:
            _expect(
                metadata.get("unsafe_tool_event") in {None, False},
                f"{context} reused pilot records a tool event",
            )
        else:
            _expect(metadata.get("unsafe_tool_event") is False, f"{context} used a tool")
        _expect(metadata.get("result_sha256") == _sha256(result_path), f"{context} hash")
        elapsed = metadata.get("elapsed_seconds")
        _expect(
            isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed >= 0,
            f"{context} elapsed_seconds invalid",
        )
        usage = metadata.get("usage")
        _expect(isinstance(usage, dict), f"{context} usage missing")
        for key in ("input_tokens", "output_tokens", "reasoning_output_tokens"):
            _expect(
                isinstance(usage.get(key), int) and usage[key] >= 0,
                f"{context} usage/{key} invalid",
            )
        _expect_keys(result, {"selection_summary", "highlights"}, f"{context} result")
        _expect_keys(raw, {"selection_summary", "highlights"}, f"{context} raw")
        _expect_string(result["selection_summary"], f"{context} summary", maximum=500)
        _expect(result["selection_summary"] == raw["selection_summary"], f"{context} raw differs")
        highlights = result["highlights"]
        raw_highlights = raw["highlights"]
        _expect(
            isinstance(highlights, list) and 1 <= len(highlights) <= 12,
            f"{context} invalid highlight count",
        )
        _expect(len(raw_highlights) == len(highlights), f"{context} raw count differs")
        seen: set[str] = set()
        alignments: list[dict[str, Any]] = []
        for position, (highlight, raw_highlight) in enumerate(
            zip(highlights, raw_highlights, strict=True), start=1
        ):
            _expect_keys(highlight, ENRICHED_GENERATOR_FIELDS, f"{context}/h{position:02d}")
            _expect_keys(raw_highlight, GENERATOR_FIELDS, f"{context}/raw/h{position:02d}")
            stripped = {key: value for key, value in highlight.items() if key in GENERATOR_FIELDS}
            _expect(stripped == raw_highlight, f"{context}/h{position:02d} raw differs")
            candidate_id = highlight["candidate_id"]
            _expect(candidate_id in candidates, f"{context} unknown candidate {candidate_id}")
            _expect(candidate_id not in seen, f"{context} duplicate candidate {candidate_id}")
            seen.add(candidate_id)
            candidate = candidates[candidate_id]
            _expect(
                highlight["source_start_ms"] == candidate["source_start_ms"]
                and highlight["source_end_ms"] == candidate["source_end_ms"],
                f"{context}/{candidate_id} enriched interval differs",
            )
            limits = {
                "topic": 40,
                "title": 40,
                "highlight_sentence": 120,
                "script_description": 260,
                "hook": 80,
                "selection_reason": 220,
            }
            for key, maximum in limits.items():
                _expect_string(highlight[key], f"{context}/{candidate_id}/{key}", maximum=maximum)
            score = highlight["score"]
            _expect(
                isinstance(score, (int, float))
                and not isinstance(score, bool)
                and 0 <= score <= 100,
                f"{context}/{candidate_id}/score invalid",
            )
            risk_flags = highlight["risk_flags"]
            _expect(isinstance(risk_flags, list) and len(risk_flags) <= 8, "invalid risk_flags")
            for risk_index, value in enumerate(risk_flags):
                _expect_string(
                    value,
                    f"{context}/{candidate_id}/risk_flags/{risk_index}",
                    maximum=40,
                )
            alignment = quote_alignment(highlight["highlight_sentence"], candidate["text"])
            alignments.append(
                {
                    "position": position,
                    "candidate_id": candidate_id,
                    "highlight_sentence": highlight["highlight_sentence"],
                    **alignment,
                }
            )
        exact = sum(item["status"] == "exact" for item in alignments)
        failed = sum(item["status"] == "failed" for item in alignments)
        expected_validation = {
            "schema_and_candidate_gate": "passed",
            "selected_count": len(highlights),
            "unique_candidate_count": len(seen),
            "quote_alignment": alignments,
            "exact_quote_count": exact,
            "failed_quote_count": failed,
            "exact_quote_rate": _round(exact / len(highlights)),
            "note": (
                "Skill v1 has one edited highlight_sentence field, so exact matching is measured "
                "but not used to silently repair or discard output."
            ),
        }
        _expect(validation == expected_validation, f"{context} validation differs when recomputed")
        for path in (result_path, raw_path, validation_path, metadata_path):
            self._remember(path)
        if metadata.get("reused") is not True:
            events_path = output_dir / "events.jsonl"
            _expect(events_path.is_file(), f"{context} events are missing")
            self._remember(events_path)
        return {
            "selection_summary": result["selection_summary"],
            "highlights": highlights,
            "candidate_ids": [item["candidate_id"] for item in highlights],
            "intervals": [[item["source_start_ms"], item["source_end_ms"]] for item in highlights],
            "selected_count": len(highlights),
            "elapsed_seconds": elapsed,
            "usage": {
                key: usage.get(key, 0)
                for key in (
                    "input_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                )
            },
            "quote_alignment": {
                "exact_count": exact,
                "failed_count": failed,
                "high_similarity_count": len(highlights) - exact - failed,
                "exact_rate": _round(exact / len(highlights)),
                "failed_rate": _round(failed / len(highlights)),
                "mean_character_coverage": _round(
                    _mean(item["matched_character_coverage"] for item in alignments)
                ),
                "items": alignments,
            },
            "validation": validation,
        }

    def _load_judge(
        self,
        directory: Path,
        case_id: str,
        replicate_id: str,
        judge_name: str,
        evidence: dict[str, Any],
        candidates: dict[str, dict[str, Any]],
        generators: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        context = f"{case_id}/{replicate_id}/judges/{judge_name}"
        output_dir = directory / "judges" / judge_name
        paths = {
            name: output_dir / filename
            for name, filename in {
                "input": "input.json",
                "result": "result.json",
                "validation": "validation.json",
                "metadata": "call-metadata.json",
                "mapping": "mapping.disclosed-after-judging.json",
                "schema": "frozen-schema.json",
                "events": "events.jsonl",
            }.items()
        }
        values = {name: _load_json(path) for name, path in paths.items() if name != "events"}
        _expect(paths["events"].is_file(), f"{context} events are missing")
        judge_input = values["input"]
        result = values["result"]
        validation = values["validation"]
        metadata = values["metadata"]
        mapping = values["mapping"]
        config = self.judge_configs[judge_name]
        _expect(metadata.get("model") == config["model"], f"{context} model mismatch")
        _expect(metadata.get("reasoning_effort") == config["effort"], f"{context} effort")
        _expect(metadata.get("label") == f"{case_id}-{replicate_id}-{judge_name}", "label")
        _expect(metadata.get("unsafe_tool_event") is False, f"{context} used a tool")
        _expect(
            metadata.get("result_sha256") == _sha256(paths["result"]),
            f"{context} result hash mismatch",
        )
        elapsed = metadata.get("elapsed_seconds")
        _expect(
            isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed >= 0,
            f"{context} elapsed_seconds invalid",
        )
        usage = metadata.get("usage")
        _expect(isinstance(usage, dict), f"{context} usage missing")
        for key in ("input_tokens", "output_tokens", "reasoning_output_tokens"):
            _expect(
                isinstance(usage.get(key), int) and usage[key] >= 0,
                f"{context} usage/{key} invalid",
            )
        self._validate_judge_mapping(
            context, judge_name, judge_input, mapping, evidence, candidates, generators
        )
        expected_validation, translated_topics, partition = self._validate_judge_result(
            context, result, mapping
        )
        _expect(validation == expected_validation, f"{context} validation differs when recomputed")
        self._validate_judge_schema(context, values["schema"], mapping)
        for path in paths.values():
            self._remember(path)
        return {
            **expected_validation,
            "preferred_models": expected_validation["preferred_models"],
            "topics": translated_topics,
            "partition": partition,
            "verdict_reason": result["verdict_reason"],
            "limitations": result["limitations"],
            "elapsed_seconds": elapsed,
            "usage": {
                key: usage.get(key, 0)
                for key in (
                    "input_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                )
            },
            "validation": validation,
        }

    def _validate_judge_mapping(
        self,
        context: str,
        judge_name: str,
        judge_input: dict[str, Any],
        mapping: dict[str, Any],
        evidence: dict[str, Any],
        candidates: dict[str, dict[str, Any]],
        generators: dict[str, dict[str, Any]],
    ) -> None:
        _expect_keys(
            mapping,
            {
                "seed_sha256",
                "anonymous_system_mapping",
                "highlight_candidate_mapping",
                "all_highlight_keys",
            },
            f"{context} mapping",
        )
        expected_seed = hashlib.sha256(
            f"{context.split('/')[0]}:{context.split('/')[1]}:{judge_name}:anonymous-v1".encode()
        ).hexdigest()
        _expect(mapping["seed_sha256"] == expected_seed, f"{context} mapping seed mismatch")
        system_mapping = mapping["anonymous_system_mapping"]
        seed_text = f"{context.split('/')[0]}:{context.split('/')[1]}:{judge_name}:anonymous-v1"
        rng = random.Random(int(hashlib.sha256(seed_text.encode()).hexdigest()[:16], 16))
        expected_models = list(GENERATOR_ORDER)
        expected_anonymous_ids = list(ANONYMOUS_IDS)
        rng.shuffle(expected_models)
        rng.shuffle(expected_anonymous_ids)
        expected_mapping = dict(zip(expected_anonymous_ids, expected_models, strict=True))
        _expect(system_mapping == expected_mapping, f"{context} anonymous mapping differs")
        _expect(
            set(system_mapping.values()) == set(self.generator_configs)
            and len(system_mapping) == len(self.generator_configs),
            f"{context} mapping does not cover generator configs once",
        )
        systems = judge_input.get("anonymous_systems")
        _expect(isinstance(systems, list) and len(systems) == 3, f"{context} systems invalid")
        _expect(
            {item.get("anonymous_system_id") for item in systems} == set(system_mapping),
            f"{context} input systems differ from mapping",
        )
        expected_highlight_keys: set[str] = set()
        selected_candidates: set[str] = set()
        fields = {
            "candidate_id",
            "topic",
            "title",
            "highlight_sentence",
            "script_description",
            "hook",
            "selection_reason",
            "risk_flags",
        }
        for system in systems:
            system_id = system["anonymous_system_id"]
            model = system_mapping[system_id]
            highlights = system.get("highlights")
            _expect(isinstance(highlights, list), f"{context}/{system_id} highlights invalid")
            expected_by_candidate = {
                item["candidate_id"]: item for item in generators[model]["highlights"]
            }
            _expect(len(highlights) == len(expected_by_candidate), f"{context} input count differs")
            observed_candidates: set[str] = set()
            observed_highlights: set[str] = set()
            for highlight in highlights:
                _expect_keys(highlight, fields | {"highlight_id"}, f"{context} judge highlight")
                highlight_id = highlight["highlight_id"]
                candidate_id = highlight["candidate_id"]
                _expect(HIGHLIGHT_ID_RE.fullmatch(highlight_id) is not None, "bad highlight ID")
                _expect(
                    highlight_id not in observed_highlights, f"{context} duplicate highlight ID"
                )
                observed_highlights.add(highlight_id)
                observed_candidates.add(candidate_id)
                selected_candidates.add(candidate_id)
                expected_highlight_keys.add(f"{system_id}:{highlight_id}")
                _expect(candidate_id in expected_by_candidate, f"{context} unmapped generator item")
                expected = {
                    key: expected_by_candidate[candidate_id][key]
                    for key in fields
                    if key != "candidate_id"
                }
                expected["candidate_id"] = candidate_id
                _expect(
                    {key: highlight[key] for key in fields} == expected,
                    f"{context}/{system_id}/{highlight_id} differs from generator",
                )
                _expect(
                    mapping["highlight_candidate_mapping"].get(system_id, {}).get(highlight_id)
                    == candidate_id,
                    f"{context}/{system_id}/{highlight_id} mapping mismatch",
                )
            _expect(
                observed_candidates == set(generators[model]["candidate_ids"]),
                f"{context}/{system_id} candidate set mismatch",
            )
        _expect(
            set(mapping["all_highlight_keys"]) == expected_highlight_keys
            and len(mapping["all_highlight_keys"]) == len(expected_highlight_keys),
            f"{context} all_highlight_keys mismatch",
        )
        source = judge_input.get("source", {})
        _expect(
            source.get("source_sha256") == evidence["source"]["source_sha256"]
            and source.get("duration_ms") == evidence["source"]["duration_ms"],
            f"{context} source evidence mismatch",
        )
        evidence_items = judge_input.get("selected_candidate_evidence")
        _expect(isinstance(evidence_items, list), f"{context} selected evidence invalid")
        _expect(
            [item.get("candidate_id") for item in evidence_items] == sorted(selected_candidates),
            f"{context} selected evidence set/order mismatch",
        )
        evidence_fields = {
            "candidate_id",
            "source_start_ms",
            "source_end_ms",
            "text",
            "context_before",
            "context_after",
        }
        for item in evidence_items:
            _expect_keys(item, evidence_fields, f"{context} selected evidence item")
            candidate = candidates[item["candidate_id"]]
            _expect(
                item == {key: candidate[key] for key in evidence_fields},
                f"{context}/{item['candidate_id']} evidence differs",
            )

    def _validate_judge_result(
        self, context: str, result: dict[str, Any], mapping: dict[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, str]]:
        _expect_keys(
            result,
            {
                "clusters",
                "system_evaluations",
                "preferred_system_ids",
                "verdict_reason",
                "limitations",
            },
            f"{context} result",
        )
        _expect_string(result["verdict_reason"], f"{context} verdict", maximum=1400)
        limitations = result["limitations"]
        _expect(isinstance(limitations, list) and 1 <= len(limitations) <= 12, "limitations")
        for index, limitation in enumerate(limitations):
            _expect_string(limitation, f"{context}/limitation/{index}", maximum=300)
        system_mapping = mapping["anonymous_system_mapping"]
        expected_systems = set(system_mapping)
        evaluations = result["system_evaluations"]
        _expect(isinstance(evaluations, list) and len(evaluations) == 3, "evaluations")
        evaluation_ids = [item.get("anonymous_system_id") for item in evaluations]
        _expect(
            set(evaluation_ids) == expected_systems
            and len(evaluation_ids) == len(set(evaluation_ids)),
            f"{context} system evaluations incomplete",
        )
        atomics_by_model: dict[str, dict[str, int]] = {}
        totals_by_model: dict[str, float] = {}
        evaluation_fields = set(ATOMIC_WEIGHTS) | {
            "anonymous_system_id",
            "strengths",
            "weaknesses",
        }
        for evaluation in evaluations:
            _expect_keys(evaluation, evaluation_fields, f"{context} evaluation")
            system_id = evaluation["anonymous_system_id"]
            model = system_mapping[system_id]
            atomics = {}
            for name in ATOMIC_WEIGHTS:
                _expect_score(
                    evaluation[name], f"{context}/{system_id}/{name}", minimum=0, maximum=4
                )
                atomics[name] = evaluation[name]
            for name in ("strengths", "weaknesses"):
                _expect_string(evaluation[name], f"{context}/{system_id}/{name}", maximum=1000)
            atomics_by_model[model] = atomics
            totals_by_model[model] = _score_system(atomics)
        preferred = result["preferred_system_ids"]
        _expect(
            isinstance(preferred, list)
            and 1 <= len(preferred) <= 3
            and set(preferred) <= expected_systems
            and len(preferred) == len(set(preferred)),
            f"{context} preferred systems invalid",
        )
        expected_keys = set(mapping["all_highlight_keys"])
        observed_keys: list[str] = []
        cluster_ids: set[str] = set()
        clusters_per_system = {system: set() for system in expected_systems}
        member_counts = Counter()
        translated_topics: list[dict[str, Any]] = []
        partition: dict[str, str] = {}
        cluster_fields = {
            "cluster_id",
            "canonical_topic",
            "alignment_confidence",
            "members",
            "assessment",
        }
        member_fields = {
            "anonymous_system_id",
            "highlight_id",
            "candidate_id",
            *MEMBER_SCORES,
            "assessment",
        }
        clusters = result["clusters"]
        _expect(isinstance(clusters, list) and 1 <= len(clusters) <= 36, "clusters")
        for cluster in clusters:
            _expect_keys(cluster, cluster_fields, f"{context} cluster")
            cluster_id = cluster["cluster_id"]
            _expect(CLUSTER_ID_RE.fullmatch(cluster_id) is not None, "bad cluster ID")
            _expect(cluster_id not in cluster_ids, f"{context} repeats cluster ID")
            cluster_ids.add(cluster_id)
            _expect_string(cluster["canonical_topic"], f"{context}/{cluster_id}/topic", maximum=100)
            _expect(
                cluster["alignment_confidence"] in {"low", "medium", "high"},
                f"{context}/{cluster_id} confidence invalid",
            )
            _expect_string(cluster["assessment"], f"{context}/{cluster_id}/assessment", maximum=800)
            members = cluster["members"]
            _expect(isinstance(members, list) and 1 <= len(members) <= 36, "members")
            translated_members = []
            for member in members:
                _expect_keys(member, member_fields, f"{context}/{cluster_id}/member")
                system_id = member["anonymous_system_id"]
                highlight_id = member["highlight_id"]
                _expect(system_id in expected_systems, f"{context} unknown system")
                expected_candidate = mapping["highlight_candidate_mapping"][system_id].get(
                    highlight_id
                )
                _expect(
                    expected_candidate == member["candidate_id"],
                    f"{context}/{cluster_id} member mapping mismatch",
                )
                key = f"{system_id}:{highlight_id}"
                observed_keys.append(key)
                model = system_mapping[system_id]
                entity = f"{model}:{member['candidate_id']}"
                _expect(entity not in partition, f"{context} duplicate partition entity")
                partition[entity] = cluster_id
                clusters_per_system[system_id].add(cluster_id)
                member_counts[system_id] += 1
                for name in MEMBER_SCORES:
                    _expect_score(
                        member[name], f"{context}/{cluster_id}/{key}/{name}", minimum=0, maximum=4
                    )
                _expect_string(member["assessment"], f"{context}/{cluster_id}/{key}", maximum=500)
                translated_members.append(
                    {
                        "model": model,
                        "highlight_id": highlight_id,
                        "candidate_id": member["candidate_id"],
                        **{name: member[name] for name in MEMBER_SCORES},
                        "assessment": member["assessment"],
                    }
                )
            translated_topics.append(
                {
                    "cluster_id": cluster_id,
                    "canonical_topic": cluster["canonical_topic"],
                    "alignment_confidence": cluster["alignment_confidence"],
                    "assessment": cluster["assessment"],
                    "members": translated_members,
                }
            )
        _expect(
            set(observed_keys) == expected_keys and len(observed_keys) == len(expected_keys),
            f"{context} clusters do not cover every highlight exactly once",
        )
        model_to_system = {model: system for system, model in system_mapping.items()}
        pairwise_jaccard = {}
        for model_a, model_b in combinations(sorted(model_to_system), 2):
            topics_a = clusters_per_system[model_to_system[model_a]]
            topics_b = clusters_per_system[model_to_system[model_b]]
            pairwise_jaccard[f"{model_a}__{model_b}"] = _round(
                len(topics_a & topics_b) / len(topics_a | topics_b) if topics_a | topics_b else 1.0
            )
        topic_count = {
            model: len(clusters_per_system[system]) for model, system in model_to_system.items()
        }
        duplicate_rate = {
            model: _round(
                (member_counts[system] - topic_count[model]) / member_counts[system]
                if member_counts[system]
                else 0.0
            )
            for model, system in model_to_system.items()
        }
        validation = {
            "cluster_coverage_gate": "passed",
            "cluster_count": len(cluster_ids),
            "computed_total_by_model": totals_by_model,
            "atomic_scores_by_model": atomics_by_model,
            "preferred_models": [system_mapping[system] for system in preferred],
            "topic_count_by_model": topic_count,
            "semantic_duplicate_rate_by_model": duplicate_rate,
            "pairwise_semantic_jaccard": pairwise_jaccard,
        }
        return validation, translated_topics, partition

    def _validate_judge_schema(
        self, context: str, schema: dict[str, Any], mapping: dict[str, Any]
    ) -> None:
        member = schema["properties"]["clusters"]["items"]["properties"]["members"]["items"][
            "properties"
        ]
        evaluation = schema["properties"]["system_evaluations"]["items"]["properties"]
        preferred = schema["properties"]["preferred_system_ids"]["items"]
        expected_systems = set(mapping["anonymous_system_mapping"])
        expected_highlights = {key.split(":", 1)[1] for key in mapping["all_highlight_keys"]}
        expected_candidates = {
            candidate
            for values in mapping["highlight_candidate_mapping"].values()
            for candidate in values.values()
        }
        _expect(set(member["anonymous_system_id"]["enum"]) == expected_systems, "schema systems")
        _expect(set(evaluation["anonymous_system_id"]["enum"]) == expected_systems, "schema evals")
        _expect(set(preferred["enum"]) == expected_systems, "schema preferred")
        _expect(set(member["highlight_id"]["enum"]) == expected_highlights, "schema highlights")
        _expect(set(member["candidate_id"]["enum"]) == expected_candidates, "schema candidates")

    def _cross_configuration(self, generators: dict[str, dict[str, Any]]) -> dict[str, Any]:
        values = {}
        for left, right in combinations(sorted(generators), 2):
            left_value, right_value = generators[left], generators[right]
            values[f"{left}__{right}"] = {
                "candidate_jaccard": _round(
                    candidate_jaccard(left_value["candidate_ids"], right_value["candidate_ids"])
                ),
                "interval_match": interval_match(
                    [tuple(item) for item in left_value["intervals"]],
                    [tuple(item) for item in right_value["intervals"]],
                ),
            }
        return values

    def _dual_judge_agreement(self, judges: dict[str, dict[str, Any]]) -> dict[str, Any]:
        left_name, right_name = sorted(judges)
        left, right = judges[left_name], judges[right_name]
        total_deltas = {
            model: _round(
                abs(
                    left["computed_total_by_model"][model] - right["computed_total_by_model"][model]
                )
            )
            for model in self.generator_configs
        }
        atomic_deltas = {
            model: {
                atomic: abs(
                    left["atomic_scores_by_model"][model][atomic]
                    - right["atomic_scores_by_model"][model][atomic]
                )
                for atomic in ATOMIC_WEIGHTS
            }
            for model in self.generator_configs
        }
        left_scores, right_scores = (
            left["computed_total_by_model"],
            right["computed_total_by_model"],
        )
        left_top = {
            model for model, score in left_scores.items() if score == max(left_scores.values())
        }
        right_top = {
            model for model, score in right_scores.items() if score == max(right_scores.values())
        }
        co_cluster = co_cluster_f1(left["partition"], right["partition"])
        return {
            "judge_pair": [left_name, right_name],
            "total_absolute_delta_by_model": total_deltas,
            "total_mae": _round(_mean(total_deltas.values())),
            "atomic_absolute_delta_by_model": atomic_deltas,
            "atomic_mae": _round(
                _mean(value for model in atomic_deltas.values() for value in model.values())
            ),
            "preferred_top1_agreement": left["preferred_models"][0] == right["preferred_models"][0],
            "preferred_top1": {
                left_name: left["preferred_models"][0],
                right_name: right["preferred_models"][0],
            },
            "score_top_sets": {left_name: sorted(left_top), right_name: sorted(right_top)},
            "score_top1_agreement": left_top == right_top,
            "score_ranking_tau": _round(_rank_tau(left_scores, right_scores)),
            "partition_ari": _round(adjusted_rand_index(left["partition"], right["partition"])),
            "partition_co_cluster": co_cluster,
        }

    def _validate_artifact_counts(self, records: list[dict[str, Any]]) -> None:
        expected_replicates = len(records)
        _expect(expected_replicates == 10, "expected ten validated replicate records")
        actual_generator_results = list(self.results_dir.glob("*/*/generators/*/result.json"))
        actual_judge_results = list(self.results_dir.glob("*/*/judges/*/result.json"))
        _expect(len(actual_generator_results) == 30, "generator result count is not exactly 30")
        _expect(len(actual_judge_results) == 20, "judge result count is not exactly 20")

    def _aggregate_primary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            by_case[record["case_id"]].append(record)
        _expect(len(by_case) == 3, "primary aggregation requires three source cases")
        source_summaries = {
            case_id: self._aggregate_source(sorted(values, key=lambda item: item["replicate_id"]))
            for case_id, values in sorted(by_case.items())
        }
        macro_models = {}
        for model in self.generator_configs:
            macro_models[model] = {
                "judge_consensus": {
                    "atomic_scores": {
                        atomic: _round(
                            _mean(
                                source["models"][model]["judge_consensus"]["atomic_scores"][atomic]
                                for source in source_summaries.values()
                            )
                        )
                        for atomic in ATOMIC_WEIGHTS
                    },
                    "total": _round(
                        _mean(
                            source["models"][model]["judge_consensus"]["total"]
                            for source in source_summaries.values()
                        )
                    ),
                },
                "judge_raw": {
                    judge: {
                        "atomic_scores": {
                            atomic: _round(
                                _mean(
                                    source["models"][model]["judge_raw"][judge]["atomic_scores"][
                                        atomic
                                    ]
                                    for source in source_summaries.values()
                                )
                            )
                            for atomic in ATOMIC_WEIGHTS
                        },
                        "total": _round(
                            _mean(
                                source["models"][model]["judge_raw"][judge]["total"]
                                for source in source_summaries.values()
                            )
                        ),
                    }
                    for judge in self.judge_configs
                },
                "generation": {
                    metric: _round(
                        _mean(
                            source["models"][model]["generation"][metric]
                            for source in source_summaries.values()
                        )
                    )
                    for metric in (
                        "selected_count",
                        "elapsed_seconds",
                        "input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                        "quote_exact_rate",
                        "quote_failed_rate",
                        "quote_mean_character_coverage",
                    )
                },
                "quote_raw_counts": {
                    key: sum(
                        source["models"][model]["quote_raw_counts"][key]
                        for source in source_summaries.values()
                    )
                    for key in ("selected", "exact", "failed")
                },
            }
        stability = {
            model: {
                metric: _round(
                    _mean(
                        source["stability"][model][metric] for source in source_summaries.values()
                    )
                )
                for metric in ("candidate_jaccard", "interval_f1")
            }
            for model in self.generator_configs
        }
        cross_configuration = {
            pair: {
                metric: _round(
                    _mean(
                        source["cross_configuration"][pair][metric]
                        for source in source_summaries.values()
                    )
                )
                for metric in ("candidate_jaccard", "interval_f1")
            }
            for pair in next(iter(source_summaries.values()))["cross_configuration"]
        }
        paired = {}
        for left, right in combinations(sorted(self.generator_configs), 2):
            deltas = {
                case_id: _round(
                    source["models"][left]["judge_consensus"]["total"]
                    - source["models"][right]["judge_consensus"]["total"]
                )
                for case_id, source in source_summaries.items()
            }
            paired[f"{left}__{right}"] = {
                "metric": "source-level dual-judge-consensus total",
                "delta_definition": f"{left} minus {right}",
                "delta_by_source": deltas,
                "mean_paired_delta": _round(_mean(deltas.values())),
                "wins_ties_losses": {
                    "wins": sum(value > 0 for value in deltas.values()),
                    "ties": sum(value == 0 for value in deltas.values()),
                    "losses": sum(value < 0 for value in deltas.values()),
                },
            }
        agreement = self._aggregate_agreement(source_summaries, records)
        judge_runtime = {
            judge: {
                metric: _round(
                    _mean(
                        source["judge_runtime"][judge][metric]
                        for source in source_summaries.values()
                    )
                )
                for metric in (
                    "elapsed_seconds",
                    "input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                )
            }
            for judge in self.judge_configs
        }
        topic_metrics = {
            judge: {
                "mean_cluster_count": _round(
                    _mean(
                        source["topic_metrics"][judge]["mean_cluster_count"]
                        for source in source_summaries.values()
                    )
                ),
                "by_model": {
                    model: {
                        metric: _round(
                            _mean(
                                source["topic_metrics"][judge]["by_model"][model][metric]
                                for source in source_summaries.values()
                            )
                        )
                        for metric in ("topic_count", "semantic_duplicate_rate")
                    }
                    for model in self.generator_configs
                },
                "pairwise_semantic_jaccard": {
                    pair: _round(
                        _mean(
                            source["topic_metrics"][judge]["pairwise_semantic_jaccard"][pair]
                            for source in source_summaries.values()
                        )
                    )
                    for pair in next(iter(source_summaries.values()))["topic_metrics"][judge][
                        "pairwise_semantic_jaccard"
                    ]
                },
            }
            for judge in self.judge_configs
        }
        return {
            "aggregation_order": [
                "judge mean inside replicate",
                "replicate mean inside source",
                "equal-weight source macro mean",
            ],
            "replicates": [self._public_replicate(record) for record in records],
            "by_source": source_summaries,
            "macro": {
                "models": macro_models,
                "paired_comparisons": paired,
                "replicate_stability": stability,
                "cross_configuration_overlap": cross_configuration,
                "dual_judge_agreement": agreement,
                "judge_runtime": judge_runtime,
                "topic_metrics": topic_metrics,
            },
        }

    def _aggregate_source(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        _expect(len(records) == 3, f"{records[0]['case_id']} does not have three replicates")
        models = {}
        for model in self.generator_configs:
            generator_values = [record["generators"][model] for record in records]
            selected = sum(value["selected_count"] for value in generator_values)
            exact = sum(value["quote_alignment"]["exact_count"] for value in generator_values)
            failed = sum(value["quote_alignment"]["failed_count"] for value in generator_values)
            models[model] = {
                "judge_consensus": {
                    "atomic_scores": {
                        atomic: _round(
                            _mean(
                                record["judge_consensus"][model]["atomic_scores"][atomic]
                                for record in records
                            )
                        )
                        for atomic in ATOMIC_WEIGHTS
                    },
                    "total": _round(
                        _mean(record["judge_consensus"][model]["total"] for record in records)
                    ),
                },
                "judge_raw": {
                    judge: {
                        "atomic_scores": {
                            atomic: _round(
                                _mean(
                                    record["judges"][judge]["atomic_scores_by_model"][model][atomic]
                                    for record in records
                                )
                            )
                            for atomic in ATOMIC_WEIGHTS
                        },
                        "total": _round(
                            _mean(
                                record["judges"][judge]["computed_total_by_model"][model]
                                for record in records
                            )
                        ),
                    }
                    for judge in self.judge_configs
                },
                "generation": {
                    "selected_count": _round(
                        _mean(value["selected_count"] for value in generator_values)
                    ),
                    "elapsed_seconds": _round(
                        _mean(value["elapsed_seconds"] for value in generator_values)
                    ),
                    "input_tokens": _round(
                        _mean(value["usage"]["input_tokens"] for value in generator_values)
                    ),
                    "output_tokens": _round(
                        _mean(value["usage"]["output_tokens"] for value in generator_values)
                    ),
                    "reasoning_output_tokens": _round(
                        _mean(
                            value["usage"]["reasoning_output_tokens"] for value in generator_values
                        )
                    ),
                    "quote_exact_rate": _round(exact / selected),
                    "quote_failed_rate": _round(failed / selected),
                    "quote_mean_character_coverage": _round(
                        _mean(
                            item["matched_character_coverage"]
                            for value in generator_values
                            for item in value["quote_alignment"]["items"]
                        )
                    ),
                },
                "quote_raw_counts": {"selected": selected, "exact": exact, "failed": failed},
            }
        stability = {}
        for model in self.generator_configs:
            pair_values = []
            for left, right in combinations(records, 2):
                left_value, right_value = left["generators"][model], right["generators"][model]
                pair_values.append(
                    {
                        "replicates": [left["replicate_id"], right["replicate_id"]],
                        "candidate_jaccard": _round(
                            candidate_jaccard(
                                left_value["candidate_ids"], right_value["candidate_ids"]
                            )
                        ),
                        "interval_f1": interval_match(
                            [tuple(item) for item in left_value["intervals"]],
                            [tuple(item) for item in right_value["intervals"]],
                        )["f1"],
                    }
                )
            stability[model] = {
                "candidate_jaccard": _round(
                    _mean(value["candidate_jaccard"] for value in pair_values)
                ),
                "interval_f1": _round(_mean(float(value["interval_f1"]) for value in pair_values)),
                "replicate_pairs": pair_values,
            }
        pair_names = records[0]["cross_configuration"]
        cross = {
            pair: {
                "candidate_jaccard": _round(
                    _mean(
                        record["cross_configuration"][pair]["candidate_jaccard"]
                        for record in records
                    )
                ),
                "interval_f1": _round(
                    _mean(
                        float(record["cross_configuration"][pair]["interval_match"]["f1"])
                        for record in records
                    )
                ),
            }
            for pair in pair_names
        }
        agreement = {
            metric: _round(
                _mean(float(record["dual_judge_agreement"][metric]) for record in records)
            )
            for metric in ("total_mae", "atomic_mae", "score_ranking_tau", "partition_ari")
        }
        agreement.update(
            {
                "preferred_top1_agreement_rate": _round(
                    _mean(
                        float(record["dual_judge_agreement"]["preferred_top1_agreement"])
                        for record in records
                    )
                ),
                "score_top1_agreement_rate": _round(
                    _mean(
                        float(record["dual_judge_agreement"]["score_top1_agreement"])
                        for record in records
                    )
                ),
                "partition_co_cluster_f1": _round(
                    _mean(
                        record["dual_judge_agreement"]["partition_co_cluster"]["f1"]
                        for record in records
                    )
                ),
            }
        )
        judge_runtime = {
            judge: {
                "elapsed_seconds": _round(
                    _mean(record["judges"][judge]["elapsed_seconds"] for record in records)
                ),
                **{
                    key: _round(_mean(record["judges"][judge]["usage"][key] for record in records))
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "reasoning_output_tokens",
                    )
                },
            }
            for judge in self.judge_configs
        }
        topic_metrics = {
            judge: {
                "mean_cluster_count": _round(
                    _mean(record["judges"][judge]["cluster_count"] for record in records)
                ),
                "by_model": {
                    model: {
                        "topic_count": _round(
                            _mean(
                                record["judges"][judge]["topic_count_by_model"][model]
                                for record in records
                            )
                        ),
                        "semantic_duplicate_rate": _round(
                            _mean(
                                record["judges"][judge]["semantic_duplicate_rate_by_model"][model]
                                for record in records
                            )
                        ),
                    }
                    for model in self.generator_configs
                },
                "pairwise_semantic_jaccard": {
                    pair: _round(
                        _mean(
                            record["judges"][judge]["pairwise_semantic_jaccard"][pair]
                            for record in records
                        )
                    )
                    for pair in records[0]["judges"][judge]["pairwise_semantic_jaccard"]
                },
            }
            for judge in self.judge_configs
        }
        return {
            "source_sha256": records[0]["source_sha256"],
            "source_label": records[0]["source_label"],
            "source_aliases": records[0]["source_aliases"],
            "replicate_count": len(records),
            "models": models,
            "stability": stability,
            "cross_configuration": cross,
            "dual_judge_agreement": agreement,
            "judge_runtime": judge_runtime,
            "topic_metrics": topic_metrics,
        }

    def _aggregate_agreement(
        self,
        sources: dict[str, dict[str, Any]],
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        metrics = (
            "total_mae",
            "atomic_mae",
            "score_ranking_tau",
            "partition_ari",
            "preferred_top1_agreement_rate",
            "score_top1_agreement_rate",
            "partition_co_cluster_f1",
        )
        result = {
            metric: _round(
                _mean(source["dual_judge_agreement"][metric] for source in sources.values())
            )
            for metric in metrics
        }
        result["source_first"] = True
        result["scale_diagnostics"] = self._judge_scale_diagnostics(records)
        result["judge_bias"] = self._judge_bias(records)
        return result

    def _source_first_observation_mean(
        self,
        records: list[dict[str, Any]],
        extractor: Any,
    ) -> float:
        by_source: dict[str, list[float]] = defaultdict(list)
        for record in records:
            by_source[record["case_id"]].extend(float(value) for value in extractor(record))
        return _mean(_mean(values) for values in by_source.values())

    def _judge_scale_diagnostics(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Measure ceiling saturation and the effective resolution of the 0--4 rubric."""
        diagnostics = {}
        model_names = sorted(self.generator_configs)
        for judge in self.judge_configs:
            total_ceiling_by_model = {
                model: _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, model=model, judge=judge: [
                            record["judges"][judge]["computed_total_by_model"][model] == 100
                        ],
                    )
                )
                for model in model_names
            }
            atomic_ceiling_by_model = {
                model: {
                    atomic: _round(
                        self._source_first_observation_mean(
                            records,
                            lambda record, model=model, atomic=atomic, judge=judge: [
                                record["judges"][judge]["atomic_scores_by_model"][model][atomic]
                                == 4
                            ],
                        )
                    )
                    for atomic in ATOMIC_WEIGHTS
                }
                for model in model_names
            }
            total_ceiling_rate = _round(
                self._source_first_observation_mean(
                    records,
                    lambda record, judge=judge: [
                        record["judges"][judge]["computed_total_by_model"][model] == 100
                        for model in model_names
                    ],
                )
            )
            atomic_ceiling_rate = {
                atomic: _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, atomic=atomic, judge=judge: [
                            record["judges"][judge]["atomic_scores_by_model"][model][atomic] == 4
                            for model in model_names
                        ],
                    )
                )
                for atomic in ATOMIC_WEIGHTS
            }
            diagnostics[judge] = {
                "observation_count": len(records) * len(model_names),
                "total_100_ceiling_rate": total_ceiling_rate,
                "total_100_ceiling_rate_by_model": total_ceiling_by_model,
                "atomic_4_ceiling_rate": atomic_ceiling_rate,
                "atomic_4_ceiling_rate_by_model": atomic_ceiling_by_model,
                "mean_distinct_total_scores_per_replicate": _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, judge=judge: [
                            len(set(record["judges"][judge]["computed_total_by_model"].values()))
                        ],
                    )
                ),
                "mean_within_replicate_score_range": _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, judge=judge: [
                            max(record["judges"][judge]["computed_total_by_model"].values())
                            - min(record["judges"][judge]["computed_total_by_model"].values())
                        ],
                    )
                ),
                "any_total_tie_replicate_rate": _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, judge=judge: [
                            len(set(record["judges"][judge]["computed_total_by_model"].values()))
                            < len(model_names)
                        ],
                    )
                ),
                "all_total_tie_replicate_rate": _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, judge=judge: [
                            len(set(record["judges"][judge]["computed_total_by_model"].values()))
                            == 1
                        ],
                    )
                ),
                "pairwise_total_tie_rate": _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, judge=judge: [
                            record["judges"][judge]["computed_total_by_model"][left]
                            == record["judges"][judge]["computed_total_by_model"][right]
                            for left, right in combinations(model_names, 2)
                        ],
                    )
                ),
                "warning": (
                    "A high ceiling or tie rate means the 0-4 whole-number rubric may not "
                    "resolve small configuration differences."
                ),
            }
        return diagnostics

    def _judge_bias(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Expose judge-level severity and a same-family difference-in-differences."""
        judge_names = sorted(self.judge_configs)
        _expect(len(judge_names) == 2, "judge bias diagnostic requires exactly two judges")
        model_names = sorted(self.generator_configs)
        values: dict[str, Any] = {}
        for judge in judge_names:
            other = next(name for name in judge_names if name != judge)
            family = judge.split("_", 1)[0]
            own_family = [model for model in model_names if model.startswith(f"{family}_")]
            other_family = [model for model in model_names if model not in own_family]
            delta_by_model = {
                model: _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, model=model, judge=judge, other=other: [
                            record["judges"][judge]["computed_total_by_model"][model]
                            - record["judges"][other]["computed_total_by_model"][model]
                        ],
                    )
                )
                for model in model_names
            }
            own_delta = _mean(delta_by_model[model] for model in own_family)
            other_delta = _mean(delta_by_model[model] for model in other_family)
            values[judge] = {
                "mean_total": _round(
                    self._source_first_observation_mean(
                        records,
                        lambda record, judge=judge: [
                            record["judges"][judge]["computed_total_by_model"][model]
                            for model in model_names
                        ],
                    )
                ),
                "mean_total_by_model": {
                    model: _round(
                        self._source_first_observation_mean(
                            records,
                            lambda record, model=model, judge=judge: [
                                record["judges"][judge]["computed_total_by_model"][model]
                            ],
                        )
                    )
                    for model in model_names
                },
                "delta_vs_other_judge_by_model": delta_by_model,
                "own_family_models": own_family,
                "own_family_mean_delta_vs_other_judge": _round(own_delta),
                "other_family_mean_delta_vs_other_judge": _round(other_delta),
                "relative_own_family_bias_difference_in_differences": _round(
                    own_delta - other_delta
                ),
            }
        sol_judge = next(name for name in judge_names if name.startswith("sol_"))
        terra_judge = next(name for name in judge_names if name.startswith("terra_"))
        sol_models = [model for model in model_names if model.startswith("sol_")]
        non_sol_models = [model for model in model_names if model not in sol_models]
        sol_minus_terra = values[sol_judge]["delta_vs_other_judge_by_model"]
        sol_family_delta = _mean(sol_minus_terra[model] for model in sol_models)
        non_sol_delta = _mean(sol_minus_terra[model] for model in non_sol_models)
        return {
            "by_judge": values,
            "sol_family_probe": {
                "contrast": f"{sol_judge} minus {terra_judge}",
                "sol_configuration_mean_delta": _round(sol_family_delta),
                "non_sol_configuration_mean_delta": _round(non_sol_delta),
                "difference_in_differences": _round(sol_family_delta - non_sol_delta),
                "interpretation": (
                    "Positive values are compatible with same-family preference, but this "
                    "small observational benchmark cannot establish causality."
                ),
            },
            "source_first": True,
        }

    def _public_replicate(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in record.items()
            if key not in {"include_in_primary_aggregate"}
        }

    def _aggregate_diagnostics(
        self,
        diagnostic_records: list[dict[str, Any]],
        primary_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cases = [self._public_replicate(record) for record in diagnostic_records]
        comparisons = []
        for diagnostic in diagnostic_records:
            matches = [
                record
                for record in primary_records
                if record["source_sha256"] == diagnostic["source_sha256"]
                and record["replicate_id"] == "r001"
            ]
            _expect(len(matches) == 1, "diagnostic has no unique same-source primary r001")
            primary = matches[0]
            model_metrics = {}
            for model in self.generator_configs:
                left = primary["generators"][model]
                right = diagnostic["generators"][model]
                model_metrics[model] = {
                    "candidate_jaccard": _round(
                        candidate_jaccard(left["candidate_ids"], right["candidate_ids"])
                    ),
                    "interval_match": interval_match(
                        [tuple(item) for item in left["intervals"]],
                        [tuple(item) for item in right["intervals"]],
                    ),
                    "judge_consensus_total_delta_diagnostic_minus_primary": _round(
                        diagnostic["judge_consensus"][model]["total"]
                        - primary["judge_consensus"][model]["total"]
                    ),
                }
            comparisons.append(
                {
                    "diagnostic_case_id": diagnostic["case_id"],
                    "primary_case_id": primary["case_id"],
                    "shared_source_sha256": diagnostic["source_sha256"],
                    "interpretation": (
                        "Full frozen evidence-pipeline sensitivity; transcript and rough "
                        "candidates both differ."
                    ),
                    "models": model_metrics,
                }
            )
        return {
            "excluded_from_primary_aggregate": True,
            "cases": cases,
            "same_source_evidence_sensitivity": comparisons,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        analysis = BenchmarkAnalyzer(args.cases, args.protocol, args.results).analyze()
        _write_json(args.output.resolve(), analysis)
    except AnalysisError as exc:
        print(f"benchmark analysis failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"validated 30 generator and 20 judge outputs; wrote {args.output.resolve()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
