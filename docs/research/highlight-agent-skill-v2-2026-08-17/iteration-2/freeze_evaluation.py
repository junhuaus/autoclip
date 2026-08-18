#!/usr/bin/env python3
"""Create or verify the immutable iteration-2 evaluation contract.

This command is deliberately local and model-free.  It must run only after the
generator, Judge, analyzer, viewer, Skill, and Schema bytes are final and before
any iteration-2 generator attempt starts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
DEFAULT_OUTPUT = SCRIPT_DIR / "evaluation-contract.json"
SCHEMA_VERSION = "liveclip-highlight-evaluation-contract.iteration-2.v1"
CONTRACT_VERSION = "highlight-agent-skill-v2-iteration-2-evaluation-v1"

ITERATION_ARTIFACTS = (
    "DESIGN.md",
    "agent/SKILL.md",
    "agent/references/atomic-scoring.md",
    "agent/references/combined-discovery.md",
    "agent/references/risk-and-repair.md",
    "agent/references/selected-copy.md",
    "analyze_iteration.py",
    "build_eval_view.py",
    "contracts.py",
    "export_schemas.py",
    "freeze_evaluation.py",
    "input_gate.py",
    "judge-rubric.md",
    "run_iteration.py",
    "run_judges.py",
    "schemas/combined-discovery.schema.json",
    "schemas/manifest.json",
    "schemas/selected-copy.schema.json",
)
BASELINE_ARTIFACTS = (
    "docs/research/model-benchmark-2026-08-17/agent-v1/SKILL.md",
    "docs/research/model-benchmark-2026-08-17/schemas/highlight-output.schema.json",
)

EXPOSED_SOURCES = (
    {
        "source_id": "src_7f34cc21eaf6d819",
        "source_sha256": "6cdac49603cb5e25faf6cb33523aa8c46e28398770f02345a05ca526b503f417",
        "frozen_input_sha256": "cc035e5eb5764b7b53bd0855fccee5d07334ee3b32abd15bcb957f27b1996936",
        "candidate_count": 45,
    },
    {
        "source_id": "src_4ae8fc713215e94c",
        "source_sha256": "595cc75a65fe8d9faa3b41ba9f5b58b307d1b0a41236f7fc6016c0c1ae8acd03",
        "frozen_input_sha256": "1b7d77e407657adceaed7bd8e28fe286cfac1732e0a7784680053c3ccad331ec",
        "candidate_count": 41,
    },
    {
        "source_id": "src_199c8497104d75ba",
        "source_sha256": "af88f7fe27cbdfc05e68b32684c558bb1877dbc7dd025b12726dd21b5e7e7d29",
        "frozen_input_sha256": "3c46dca758569693b84006179e04708a2586418fc299aed81bce5eacde6c19ec",
        "candidate_count": 45,
    },
)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _capture_artifacts() -> dict[str, bytes]:
    """Capture every frozen artifact once before any cross-artifact validation."""

    paths = [SCRIPT_DIR / relative for relative in ITERATION_ARTIFACTS]
    paths.extend(ROOT / relative for relative in BASELINE_ARTIFACTS)
    captured: dict[str, bytes] = {}
    for path in paths:
        if path.is_symlink():
            raise RuntimeError(f"evaluation artifact cannot be a symlink: {path}")
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            raise RuntimeError(f"evaluation artifact must be a regular file: {path}")
        try:
            relative = resolved.relative_to(ROOT).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"evaluation artifact escapes repository: {path}") from exc
        if relative in captured:
            raise RuntimeError(f"duplicate evaluation artifact path: {relative}")
        captured[relative] = resolved.read_bytes()
    return dict(sorted(captured.items()))


def _artifact_index(
    captured: Mapping[str, bytes],
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for relative, content in sorted(captured.items()):
        records[relative] = {
            "sha256": sha256_bytes(content),
            "size_bytes": len(content),
        }
    return records


def _artifact_key(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"evaluation artifact path is unavailable: {path}") from exc


def _verify_schema_manifest(captured: Mapping[str, bytes]) -> None:
    manifest_key = _artifact_key(SCRIPT_DIR / "schemas/manifest.json")
    contracts_key = _artifact_key(SCRIPT_DIR / "contracts.py")
    manifest = json.loads(captured[manifest_key])
    expected_contracts_hash = sha256_bytes(captured[contracts_key])
    if manifest.get("contracts_sha256") != expected_contracts_hash:
        raise RuntimeError("schema manifest is not bound to the current contracts.py")
    schemas = manifest.get("schemas")
    if not isinstance(schemas, dict) or set(schemas) != {
        "combined-discovery.schema.json",
        "selected-copy.schema.json",
    }:
        raise RuntimeError("schema manifest has the wrong iteration-2 inventory")
    for filename, record in schemas.items():
        content = captured[_artifact_key(SCRIPT_DIR / "schemas" / filename)]
        if record != {"sha256": sha256_bytes(content), "size_bytes": len(content)}:
            raise RuntimeError(f"schema manifest drifted for {filename}")


def _verify_design_language(captured: Mapping[str, bytes]) -> None:
    design = captured[_artifact_key(SCRIPT_DIR / "DESIGN.md")].decode("utf-8")
    rubric = captured[_artifact_key(SCRIPT_DIR / "judge-rubric.md")].decode("utf-8")
    required_design = {
        "advance_iteration2_to_frozen_holdout",
        "reject_iteration2",
        "inconclusive_iteration2",
        "underfilled_due_to_quality=true",
        "diagnostic-not-required",
    }
    required_rubric = {
        "judge_semantic_opportunity_coverage_x4",
        "portfolio_coherence_x4",
        "ROUND_HALF_UP",
        "event_match_x4 >= 3",
        "usability_x4 >= 2",
    }
    missing_design = sorted(value for value in required_design if value not in design)
    missing_rubric = sorted(value for value in required_rubric if value not in rubric)
    if missing_design or missing_rubric:
        raise RuntimeError(
            f"frozen design/rubric language is incomplete: "
            f"design={missing_design}, rubric={missing_rubric}"
        )


def _assert_no_generator_output() -> None:
    experiments = SCRIPT_DIR / "experiments"
    if not experiments.exists():
        return
    forbidden_names = {
        "complete.json",
        "result.json",
        "attempt-result.json",
        "run-summary.json",
    }
    observed = [
        path
        for path in experiments.rglob("*")
        if path.is_file() and (path.name in forbidden_names or path.name.startswith("attempt-"))
    ]
    if observed:
        raise RuntimeError("refusing to freeze after iteration-2 generator output/attempts exist")


def build_contract() -> dict[str, Any]:
    captured = _capture_artifacts()
    _verify_schema_manifest(captured)
    _verify_design_language(captured)
    waiver_payload = {
        "frozen_before_generator_output": True,
        "mode": "diagnostic_not_required",
        "reason": (
            "Human review is diagnostic only for exposed development regression; "
            "semantic acceptance uses the frozen dual-Judge contract."
        ),
    }
    waiver = {
        **waiver_payload,
        "commitment_sha256": sha256_bytes(canonical_bytes(waiver_payload)),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "iteration_id": "highlight-agent-skill-v2-iteration-2",
        "status": "frozen_before_any_iteration2_generator_output",
        "data_classification": "exposed_development_regression",
        "human_review_mode": "diagnostic_not_required",
        "human_feedback_waiver": waiver,
        "artifacts": _artifact_index(captured),
        "generator": {
            "sources": list(EXPOSED_SOURCES),
            "unique_source_count": 3,
            "arms": [
                {"arm_id": "v1", "meaning": "fresh_frozen_v1"},
                {"arm_id": "v2", "meaning": "iteration_2_contender"},
            ],
            "repeats_per_source_arm": 2,
            "required_pipeline_count": 12,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "medium",
            "normal_calls_per_pipeline": {
                "v1": 1,
                "v2_maximum": 2,
                "v2_selected_copy_skipped_when_empty": True,
            },
            "maximum_model_repair_attempts_per_pipeline": 1,
            "maximum_model_repair_attempts_per_stage": 1,
            "all_model_started_attempt_costs_completion_hash_bound": True,
            "candidate_order_fixed_across_repeats": True,
            "candidate_capacity": 60,
            "combined_payload_capacity_bytes": 131072,
            "adaptive_portfolio": {
                "desired_minimum": 8,
                "maximum_count": 12,
                "base_minimum_quality": 65,
                "extension_minimum_atomic_score": 3,
                "maximum_interval_iou": "9/20",
                "maximum_text_jaccard": "13/20",
                "same_claim_second_selection": False,
            },
            "sol_high_enabled": False,
            "production_mutation_permitted": False,
        },
        "judge": {
            "models": [
                {"judge_id": "judge_01", "model": "gpt-5.6-sol", "effort": "max"},
                {"judge_id": "judge_02", "model": "gpt-5.6-terra", "effort": "max"},
            ],
            "required_call_count": 6,
            "systems_per_call": 4,
            "source_first": True,
            "preserve_highlight_position_within_system": True,
            "counterbalance_system_order_between_judges": True,
            "maximum_same_call_schema_repairs": 1,
            "adaptive_third_judge_permitted": False,
            "global_unblind_requires_all_calls": True,
            "global_unblind_requires_human_feedback_commitment_or_frozen_waiver": True,
            "qualified_semantic_opportunity_predicate": {
                "event_match_x4_minimum": 3,
                "editorial_value_x4_minimum": 3,
                "evidence_fidelity_x4_minimum": 3,
                "usability_x4_minimum": 2,
            },
            "semantic_opportunity_coverage_scope": "observed_selected_union_not_absolute_recall",
        },
        "aggregation": {
            "system_dimensions_and_integer_weights": {
                "valuable_discovery_x4": 30,
                "judge_semantic_opportunity_coverage_x4": 20,
                "precision_x4": 20,
                "portfolio_coherence_x4": 15,
                "editorial_readiness_x4": 15,
            },
            "system_score": "sum(weight*dimension_x4)/4",
            "intermediate_floor_or_round": False,
            "source_alias_policy": "deduplicate_by_source_sha256_before_equal_macro_mean",
            "source_score": "mean_of_two_repeats_and_two_judges_as_exact_fraction",
            "headline_score": "equal_macro_mean_over_unique_source_sha256",
            "gate_arithmetic": "exact_rational",
            "display_rounding": "ROUND_HALF_UP_3_DECIMALS_ONLY",
            "coverage_metric_names": [
                "judge_semantic_opportunity_coverage",
                "deterministic_relative_selected_union_candidate_coverage",
            ],
        },
        "acceptance_gates": {
            "integrity_and_safety": {
                "required_generator_pipelines": "12/12",
                "required_judge_calls": "6/6",
                "all_hash_receipt_schema_identity_anonymity_checks": True,
                "unknown_or_duplicate_candidate_ids": 0,
                "tool_events": 0,
                "identity_leaks": 0,
                "unbound_model_started_attempt_costs": 0,
            },
            "evidence_and_structure": {
                "iteration2_outward_exact_evidence_failures": 0,
                "all_structure_candidate_time_selection_gates": True,
                "underfilled_iteration2_portfolios": 0,
                "normal_iteration2_calls_per_pipeline_maximum": 2,
            },
            "quality": {
                "iteration2_minus_fresh_v1_minimum": "-2",
                "iteration2_precision_minimum": "75",
                "precision_delta_minimum": "-2",
                "iteration2_editorial_readiness_minimum": "75",
                "editorial_readiness_delta_minimum": "-2",
                "worst_unique_source_quality_delta_minimum": "-5",
            },
            "deterministic_repeat_stability": {
                "candidate_jaccard_delta_minimum": "-1/20",
                "interval_f1_delta_minimum": "-1/20",
                "judge_sampling_stability_dimension_permitted": False,
            },
            "judge_reliability": {
                "mean_absolute_pipeline_score_difference_maximum": "10",
                "any_source_arm_score_difference_maximum": "20",
                "exceeded_outcome": "inconclusive_iteration2",
            },
            "efficiency": {
                "source_first_all_attempt_elapsed_ratio_maximum": "3",
                "source_first_all_reported_token_ratio_maximum": "3",
                "quality_justification_override_permitted": False,
            },
        },
        "outcomes": {
            "allowed": [
                "reject_iteration2",
                "inconclusive_iteration2",
                "advance_iteration2_to_frozen_holdout",
            ],
            "passing_development_outcome": "advance_iteration2_to_frozen_holdout",
            "production_acceptance_permitted": False,
        },
        "future_holdout": {
            "minimum_new_unique_source_hashes": 6,
            "minimum_content_genres": 3,
            "minimum_sources_per_genre": 2,
            "source_first_then_equal_genre_macro_mean": True,
            "reuse_of_exposed_development_sources_permitted": False,
            "result_can_directly_change_production": False,
        },
    }


def _write_new(path: Path, content: bytes) -> None:
    if path.is_symlink():
        raise RuntimeError(f"evaluation contract path cannot be a symlink: {path}")
    path = path.resolve()
    if path.exists():
        raise RuntimeError(f"refusing to overwrite frozen evaluation contract: {path}")
    if not path.parent.is_dir():
        raise RuntimeError(f"evaluation contract parent does not exist: {path.parent}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.write and args.output.resolve(strict=False) != DEFAULT_OUTPUT.resolve(strict=False):
            raise RuntimeError(
                "the formal evaluation contract may only be written to the default path"
            )
        expected = pretty_bytes(build_contract())
        if args.write:
            _assert_no_generator_output()
            _write_new(args.output, expected)
        else:
            if args.output.is_symlink():
                raise RuntimeError(f"evaluation contract path cannot be a symlink: {args.output}")
            observed = args.output.resolve(strict=True).read_bytes()
            if observed != expected:
                raise RuntimeError("evaluation contract bytes or artifact hashes drifted")
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"evaluation_contract={args.output.resolve()}")
    print(f"evaluation_contract_sha256={sha256_bytes(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
