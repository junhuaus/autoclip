#!/usr/bin/env python3
# ruff: noqa: E501
"""Verify and analyze the frozen Highlight Agent iteration-2 experiment.

The analyzer is intentionally fail closed.  It verifies the frozen evaluation
contract and complete generator/Judge receipts before calling the Judge
harness's single global-unblind loader.  It never reads a per-call identity
mapping.  All gate arithmetic uses :class:`fractions.Fraction`; decimal values
exist only as ROUND_HALF_UP, three-place display strings.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import stat
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any
from urllib.parse import quote

ITERATION_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = ITERATION_DIR.parents[3]
EVALUATION_CONTRACT_PATH = ITERATION_DIR / "evaluation-contract.json"
DEFAULT_EXPERIMENTS_ROOT = ITERATION_DIR / "experiments"
DEFAULT_REPORTS_ROOT = ITERATION_DIR / "reports"
ANALYZER_VERSION = "liveclip-highlight-agent-v2-analysis.iteration-2.v1"
SCHEMA_VERSION = "2"
JUDGE_IDS = ("judge_01", "judge_02")
BASELINE = "fresh_v1"
CONTENDER = "iteration2"
ARMS = (BASELINE, CONTENDER)
ITERATION_REPO_PREFIX = "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2"
CONTRACTS_ARTIFACT = f"{ITERATION_REPO_PREFIX}/contracts.py"
JUDGE_HARNESS_ARTIFACT = f"{ITERATION_REPO_PREFIX}/run_judges.py"
SYSTEM_SCORE_FIELDS = (
    "valuable_discovery_x4",
    "judge_semantic_opportunity_coverage_x4",
    "precision_x4",
    "portfolio_coherence_x4",
    "editorial_readiness_x4",
)
SYSTEM_SCORE_WEIGHTS = {
    "valuable_discovery_x4": 30,
    "judge_semantic_opportunity_coverage_x4": 20,
    "precision_x4": 20,
    "portfolio_coherence_x4": 15,
    "editorial_readiness_x4": 15,
}
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
EVALUATION_CONTRACT_KEYS = {
    "schema_version",
    "contract_version",
    "iteration_id",
    "status",
    "human_review_mode",
    "human_feedback_waiver",
    "artifacts",
    "generator",
    "judge",
    "aggregation",
    "acceptance_gates",
    "outcomes",
}
REQUIRED_EVALUATION_ARTIFACTS = {
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/DESIGN.md",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/agent/SKILL.md",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/agent/references/atomic-scoring.md",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/agent/references/combined-discovery.md",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/agent/references/risk-and-repair.md",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/agent/references/selected-copy.md",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/analyze_iteration.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/build_eval_view.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/contracts.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/export_schemas.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/freeze_evaluation.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/input_gate.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/judge-rubric.md",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/run_iteration.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/run_judges.py",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/schemas/combined-discovery.schema.json",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/schemas/manifest.json",
    "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2/schemas/selected-copy.schema.json",
    "docs/research/model-benchmark-2026-08-17/agent-v1/SKILL.md",
    "docs/research/model-benchmark-2026-08-17/schemas/highlight-output.schema.json",
}


class AnalysisError(RuntimeError):
    """An artifact, aggregation, or reporting invariant failed."""


class AnalysisIncomplete(AnalysisError):
    """The frozen matrix cannot yet be globally unblinded."""


@dataclass(frozen=True)
class GeneratorRecord:
    pipeline_id: str
    source_id: str
    source_sha256: str
    arm: str
    repeat: int
    result: dict[str, Any]
    validation: dict[str, Any]
    summary: dict[str, Any]
    all_attempt_usage: dict[str, int]
    all_attempt_elapsed_seconds: Fraction
    normal_model_call_count: int
    total_model_attempt_count: int
    selected_count: int
    underfilled_due_to_quality: bool
    result_path: Path
    completion_path: Path


@dataclass(frozen=True)
class JudgeRecord:
    source_id: str
    source_sha256: str
    judge_id: str
    result: dict[str, Any]
    validation: dict[str, Any]
    binding: dict[str, Any]
    result_path: Path
    completion_path: Path


@dataclass(frozen=True)
class VerifiedExperiment:
    experiment_dir: Path
    judge_run_dir: Path
    experiment_id: str
    evaluation_contract: dict[str, Any]
    evaluation_contract_sha256: str
    source_ids: tuple[str, ...]
    source_sha256_by_id: dict[str, str]
    source_metadata_by_id: dict[str, dict[str, Any]]
    candidates_by_source: dict[str, dict[str, dict[str, Any]]]
    generators: tuple[GeneratorRecord, ...]
    judges: tuple[JudgeRecord, ...]
    global_unblind_path: Path
    feedback_release: dict[str, Any]
    contracts_module: ModuleType


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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalysisError(f"missing artifact: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"expected JSON object: {path}")
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_repository_artifact_index(
    contract: Mapping[str, Any],
) -> dict[str, bytes]:
    """Read every indexed artifact once and return its hash-verified bytes."""

    artifacts = contract.get("artifacts")
    _expect(isinstance(artifacts, dict), "evaluation artifact index is missing")
    _expect(
        set(artifacts) == REQUIRED_EVALUATION_ARTIFACTS,
        "evaluation artifact inventory differs; missing="
        + str(sorted(REQUIRED_EVALUATION_ARTIFACTS - set(artifacts)))
        + ", extra="
        + str(sorted(set(artifacts) - REQUIRED_EVALUATION_ARTIFACTS)),
    )
    try:
        repository_root = REPOSITORY_ROOT.resolve(strict=True)
    except OSError as exc:
        raise AnalysisError("repository root cannot be resolved") from exc
    _expect(repository_root.is_dir(), "repository root is not a directory")
    verified: dict[str, bytes] = {}
    for relative, record in sorted(artifacts.items()):
        _expect(isinstance(relative, str) and relative, "invalid evaluation artifact path")
        relative_path = PurePosixPath(relative)
        _expect(
            not relative_path.is_absolute()
            and relative_path.as_posix() == relative
            and ".." not in relative_path.parts
            and "." not in relative_path.parts
            and "\\" not in relative,
            f"evaluation artifact path escapes or is not normalized: {relative!r}",
        )
        _expect(isinstance(record, dict), f"artifact record is malformed: {relative}")
        _expect_keys(record, {"sha256", "size_bytes"}, f"artifact record {relative}")
        expected_sha = record["sha256"]
        expected_size = record["size_bytes"]
        _expect(
            isinstance(expected_sha, str)
            and len(expected_sha) == 64
            and all(character in "0123456789abcdef" for character in expected_sha),
            f"artifact SHA-256 is malformed: {relative}",
        )
        _expect(
            isinstance(expected_size, int)
            and not isinstance(expected_size, bool)
            and expected_size >= 0,
            f"artifact size is malformed: {relative}",
        )
        candidate = repository_root.joinpath(*relative_path.parts)
        cursor = repository_root
        for part in relative_path.parts:
            cursor /= part
            _expect(not cursor.is_symlink(), f"evaluation artifact uses a symlink: {relative}")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(repository_root)
            mode = os.lstat(candidate).st_mode
        except (OSError, ValueError) as exc:
            raise AnalysisError(f"evaluation artifact is missing or escapes: {relative}") from exc
        _expect(stat.S_ISREG(mode), f"evaluation artifact is not a regular file: {relative}")
        try:
            content = candidate.read_bytes()
        except OSError as exc:
            raise AnalysisError(f"evaluation artifact is unreadable: {relative}") from exc
        _expect(len(content) == expected_size, f"artifact size drifted: {relative}")
        _expect(_sha256_bytes(content) == expected_sha, f"artifact hash drifted: {relative}")
        verified[relative] = content
    return verified


def _regular_file(path: Path, context: str) -> Path:
    _expect(path.is_file() and not path.is_symlink(), f"{context} must be a regular file")
    return path


def _fraction(value: int | float | Decimal | Fraction) -> Fraction:
    if isinstance(value, bool):
        raise AnalysisError("boolean is not a numeric observation")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value, 1)
    if isinstance(value, float):
        return Fraction(Decimal(str(value)))
    if isinstance(value, Decimal):
        return Fraction(value)
    raise AnalysisError(f"unsupported numeric observation: {value!r}")


def _mean(values: Iterable[Fraction | int]) -> Fraction:
    items = [_fraction(value) for value in values]
    if not items:
        raise AnalysisError("cannot average an empty collection")
    return sum(items, Fraction()) / len(items)


def _display_fraction(value: Fraction) -> str:
    decimal = Decimal(value.numerator) / Decimal(value.denominator)
    rendered = decimal.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if rendered == 0:
        rendered = abs(rendered)
    return f"{rendered:.3f}"


def _metric(value: Fraction | int) -> dict[str, Any]:
    exact = _fraction(value)
    return {
        "numerator": exact.numerator,
        "denominator": exact.denominator,
        "display": _display_fraction(exact),
    }


def _metric_fraction(value: Mapping[str, Any], context: str) -> Fraction:
    _expect_keys(value, {"numerator", "denominator", "display"}, context)
    numerator = value["numerator"]
    denominator = value["denominator"]
    _expect(isinstance(numerator, int) and not isinstance(numerator, bool), context)
    _expect(
        isinstance(denominator, int) and not isinstance(denominator, bool) and denominator > 0,
        context,
    )
    exact = Fraction(numerator, denominator)
    _expect(value["display"] == _display_fraction(exact), f"{context} display drifted")
    return exact


def _arm_label(skill_version: str) -> str:
    if skill_version in {"v1", BASELINE}:
        return BASELINE
    if skill_version in {"v2", CONTENDER}:
        return CONTENDER
    raise AnalysisError(f"unknown generator skill version: {skill_version}")


def _usage_record(raw: Mapping[str, Any]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for field in TOKEN_FIELDS:
        value = raw.get(field, 0)
        _expect(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0,
            f"invalid usage field {field}",
        )
        usage[field] = value
    computed_total = usage["input_tokens"] + usage["output_tokens"]
    supplied_total = raw.get("reported_total_tokens", computed_total)
    _expect(
        isinstance(supplied_total, int)
        and not isinstance(supplied_total, bool)
        and supplied_total == computed_total,
        "reported total-token accounting drifted",
    )
    usage["reported_total_tokens"] = computed_total
    return usage


def _load_evaluation_contract(
    experiment_dir: Path,
) -> tuple[dict[str, Any], str, int, dict[str, bytes]]:
    repository_path = _regular_file(EVALUATION_CONTRACT_PATH, "evaluation contract")
    frozen_path = _regular_file(
        experiment_dir / "frozen" / "evaluation-contract.json",
        "frozen evaluation contract",
    )
    repository_bytes = repository_path.read_bytes()
    _expect(
        frozen_path.read_bytes() == repository_bytes,
        "frozen evaluation contract differs from the repository contract",
    )
    try:
        contract = json.loads(repository_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalysisError("invalid evaluation contract JSON") from exc
    _expect(isinstance(contract, dict), "evaluation contract must be a JSON object")
    _expect(
        set(contract) >= EVALUATION_CONTRACT_KEYS,
        "evaluation contract is missing required fields: "
        + str(sorted(EVALUATION_CONTRACT_KEYS - set(contract))),
    )
    _expect(
        contract["schema_version"] == "liveclip-highlight-evaluation-contract.iteration-2.v1",
        "wrong evaluation schema version",
    )
    _expect(
        contract["contract_version"] == "highlight-agent-skill-v2-iteration-2-evaluation-v1",
        "wrong evaluation contract version",
    )
    _expect(
        contract["iteration_id"] == "highlight-agent-skill-v2-iteration-2",
        "wrong evaluation iteration",
    )
    _expect(
        contract["status"] == "frozen_before_any_iteration2_generator_output",
        "evaluation contract is not pre-output frozen",
    )
    _expect(
        contract["human_review_mode"] in {"required", "diagnostic_not_required"},
        "unsupported human review mode",
    )
    verified_artifacts = _verify_repository_artifact_index(contract)
    return (
        contract,
        _sha256_bytes(repository_bytes),
        len(repository_bytes),
        verified_artifacts,
    )


def _verified_python_module(
    *, module_name: str, source_path: Path, source_bytes: bytes
) -> ModuleType:
    """Compile only bytes already verified against the frozen artifact index."""

    module = ModuleType(module_name)
    module.__file__ = str(source_path)
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        code = compile(source_bytes, str(source_path), "exec")
        exec(code, module.__dict__)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _load_pinned_dependencies(
    verified_artifacts: Mapping[str, bytes],
) -> tuple[ModuleType, ModuleType]:
    """Load Contracts and Judge only from the already-read frozen snapshot."""

    try:
        contracts_bytes = verified_artifacts[CONTRACTS_ARTIFACT]
        judge_bytes = verified_artifacts[JUDGE_HARNESS_ARTIFACT]
        contracts_digest = _sha256_bytes(contracts_bytes)
        judge_digest = _sha256_bytes(judge_bytes)
        contracts_module = _verified_python_module(
            module_name=f"liveclip_analysis_contracts_{contracts_digest}",
            source_path=REPOSITORY_ROOT / CONTRACTS_ARTIFACT,
            source_bytes=contracts_bytes,
        )
        judge_module = _verified_python_module(
            module_name=f"liveclip_analysis_judge_{judge_digest}",
            source_path=REPOSITORY_ROOT / JUDGE_HARNESS_ARTIFACT,
            source_bytes=judge_bytes,
        )
    except Exception as exc:
        raise AnalysisError("could not load frozen analysis dependencies") from exc
    return contracts_module, judge_module


def _verify_evaluation_contract_binding(
    experiment_dir: Path,
    contract_sha256: str,
    contract_size: int,
) -> dict[str, Any]:
    manifest = _load_json(
        _regular_file(experiment_dir / "experiment-manifest.json", "experiment manifest")
    )
    immutable = manifest.get("immutable_contract")
    _expect(isinstance(immutable, dict), "experiment immutable contract is missing")
    _expect(
        manifest.get("contract_sha256") == _sha256_bytes(_canonical_bytes(immutable)),
        "experiment immutable contract hash drifted",
    )
    _expect(
        immutable.get("evaluation_contract_sha256") == contract_sha256,
        "generator experiment is not bound to the frozen evaluation contract",
    )
    index = manifest.get("artifact_index")
    _expect(isinstance(index, dict), "experiment artifact index is missing")
    record = index.get("frozen/evaluation-contract.json")
    _expect(
        isinstance(record, dict)
        and set(record) == {"sha256", "size_bytes"}
        and record.get("sha256") == contract_sha256
        and record.get("size_bytes") == contract_size,
        "indexed evaluation contract receipt drifted",
    )
    return manifest


def _generator_summary_observations(
    summary: Mapping[str, Any],
    arm: str,
) -> tuple[dict[str, int], Fraction, int, int, int, bool]:
    usage_complete = summary.get("completion_bound_usage_complete")
    _expect(usage_complete is True, "all-attempt usage accounting is incomplete")
    usage = summary.get("completion_bound_total_usage")
    elapsed = summary.get("completion_bound_total_elapsed_seconds")
    _expect(isinstance(usage, dict), "all-attempt usage summary is missing")
    _expect(
        isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed >= 0,
        "all-attempt elapsed summary is invalid",
    )
    normal_calls = summary.get("normal_model_call_count")
    attempts = summary.get("total_model_attempt_count")
    selected = summary.get("selected_count")
    underfilled = summary.get("underfilled_due_to_quality")
    for value, label in (
        (normal_calls, "normal_model_call_count"),
        (attempts, "total_model_attempt_count"),
        (selected, "selected_count"),
    ):
        _expect(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0,
            f"invalid {label}",
        )
    _expect(isinstance(underfilled, bool), "underfilled flag is missing")
    if arm == BASELINE:
        _expect(normal_calls == 1, "fresh v1 must use exactly one normal model call")
    else:
        _expect(normal_calls <= 2, "iteration2 exceeds two normal model calls")
        _expect(normal_calls == (2 if selected > 0 else 1), "iteration2 topology is inconsistent")
        _expect(underfilled == (selected < 8), "adaptive underfilled receipt is inconsistent")
        _expect(selected <= 12, "adaptive portfolio exceeds twelve")
    _expect(attempts >= normal_calls, "attempt count is below normal call count")
    return (
        _usage_record(usage),
        _fraction(elapsed),
        normal_calls,
        attempts,
        selected,
        underfilled,
    )


def _global_binding(manifest: Mapping[str, Any], source_id: str, judge_id: str) -> dict[str, Any]:
    bindings = manifest.get("bindings")
    _expect(isinstance(bindings, dict), "global unblind bindings are missing")
    entry = bindings.get(f"{source_id}/{judge_id}")
    _expect(isinstance(entry, dict), f"global unblind binding missing: {source_id}/{judge_id}")
    binding = entry.get("binding")
    _expect(isinstance(binding, dict), f"global unblind binding malformed: {source_id}/{judge_id}")
    return dict(binding)


def load_verified_experiment(
    experiment_dir: Path,
    judge_run_dir: Path | None = None,
) -> VerifiedExperiment:
    """Verify the complete matrix and use only the global-unblind release."""

    experiment_dir = experiment_dir.resolve(strict=True)
    (
        evaluation_contract,
        evaluation_contract_sha256,
        evaluation_contract_size,
        verified_artifacts,
    ) = _load_evaluation_contract(experiment_dir)
    contracts_module, judge_harness = _load_pinned_dependencies(verified_artifacts)
    manifest = _verify_evaluation_contract_binding(
        experiment_dir, evaluation_contract_sha256, evaluation_contract_size
    )
    try:
        prepared = judge_harness.prepare_judge_run(experiment_dir)
    except (judge_harness.GeneratorMatrixIncomplete, judge_harness.IntegrityError) as exc:
        raise AnalysisError(str(exc)) from exc
    _expect(
        prepared.evaluation.contract_sha256 == evaluation_contract_sha256
        and prepared.evaluation.contract == evaluation_contract,
        "Analyzer and Judge evaluation materials differ",
    )
    bundles = prepared.source_bundles
    _expect(
        isinstance(bundles, tuple),
        "Prepared Judge run lacks the frozen source-bundle snapshot",
    )
    _expect(len(bundles) == 3, "formal development matrix requires three source entries")
    pipeline_ids = {pipeline for bundle in bundles for pipeline in bundle.pipeline_ids}
    _expect(len(pipeline_ids) == 12, "formal development matrix requires twelve pipelines")
    if judge_run_dir is not None:
        _expect(
            judge_run_dir.resolve(strict=True) == prepared.run_dir,
            "selected Judge run does not match the frozen harness",
        )
    _expect(
        prepared.manifest.get("evaluation_contract_sha256") == evaluation_contract_sha256,
        "Judge run is not bound to the evaluation contract",
    )
    _expect(len(prepared.calls) == 6, "Judge run must bind exactly six calls")
    expected_keys = {(bundle.source_id, judge_id) for bundle in bundles for judge_id in JUDGE_IDS}
    _expect(set(prepared.calls) == expected_keys, "Judge call inventory drifted")

    # Complete and validate all six calls before the sole global-unblind operation.
    judge_call_snapshots: dict[tuple[str, str], Any] = {}
    for key in sorted(expected_keys):
        call_dir = prepared.run_dir / "sources" / key[0] / key[1]
        completion = call_dir / "complete.json"
        if not completion.is_file() or completion.is_symlink():
            raise AnalysisIncomplete(
                f"all 6/6 Judge calls must complete before global unblind; missing={completion}"
            )
        try:
            snapshot = judge_harness._verify_completed_call(call_dir, prepared.calls[key])
        except (judge_harness.IntegrityError, judge_harness.JudgeValidationError) as exc:
            raise AnalysisError(str(exc)) from exc
        _expect(
            isinstance(snapshot, judge_harness.VerifiedJudgeCallSnapshot),
            f"Judge verifier did not return a frozen snapshot: {key}",
        )
        judge_call_snapshots[key] = snapshot

    loader = getattr(judge_harness, "load_verified_global_unblind", None)
    _expect(callable(loader), "Judge harness lacks the frozen global-unblind verifier")
    try:
        global_unblind = loader(prepared, call_snapshots=judge_call_snapshots)
    except (judge_harness.IntegrityError, judge_harness.JudgeValidationError) as exc:
        raise AnalysisIncomplete(str(exc)) from exc
    _expect(
        global_unblind.get("evaluation_contract_sha256") == evaluation_contract_sha256,
        "global unblind evaluation contract hash drifted",
    )
    feedback_release = global_unblind.get("feedback_commitment")
    _expect(isinstance(feedback_release, dict), "global unblind feedback release is missing")
    mode = evaluation_contract["human_review_mode"]
    if mode == "diagnostic_not_required":
        _expect_keys(
            feedback_release,
            {"mode", "status", "waiver_commitment_sha256", "reason"},
            "diagnostic feedback waiver",
        )
        _expect(
            feedback_release["mode"] == mode and feedback_release["status"] == "waived",
            "diagnostic feedback waiver is not effective",
        )
        waiver = evaluation_contract.get("human_feedback_waiver")
        _expect(isinstance(waiver, dict), "frozen diagnostic waiver is missing")
        _expect_keys(
            waiver,
            {"frozen_before_generator_output", "mode", "reason", "commitment_sha256"},
            "frozen diagnostic waiver",
        )
        waiver_payload = {
            key: waiver[key] for key in ("frozen_before_generator_output", "mode", "reason")
        }
        _expect(
            waiver["frozen_before_generator_output"] is True
            and waiver["mode"] == mode
            and waiver["commitment_sha256"] == _sha256_bytes(_canonical_bytes(waiver_payload)),
            "frozen diagnostic waiver commitment drifted",
        )
        _expect(
            feedback_release["waiver_commitment_sha256"] == waiver["commitment_sha256"]
            and feedback_release["reason"] == waiver["reason"],
            "global unblind waiver does not match the evaluation contract",
        )
    else:
        _expect(feedback_release.get("complete") is True, "human feedback is not complete")
        _expect(
            feedback_release.get("evaluation_contract_sha256") == evaluation_contract_sha256,
            "human feedback commitment is bound to another evaluation contract",
        )

    source_sha256_by_id: dict[str, str] = {}
    source_metadata_by_id: dict[str, dict[str, Any]] = {}
    candidates_by_source: dict[str, dict[str, dict[str, Any]]] = {}
    for bundle in bundles:
        metadata = dict(bundle.source_payload["source"])
        source_sha = metadata.get("source_sha256")
        _expect(isinstance(source_sha, str) and len(source_sha) == 64, "source SHA missing")
        source_sha256_by_id[bundle.source_id] = source_sha
        source_metadata_by_id[bundle.source_id] = metadata
        candidates_by_source[bundle.source_id] = {
            str(item["candidate_id"]): dict(item) for item in bundle.source_payload["candidates"]
        }
    _expect(
        len(set(source_sha256_by_id.values())) == 3,
        "formal gate requires three unique source SHA-256 values, not aliases",
    )

    generators: list[GeneratorRecord] = []
    for bundle in bundles:
        pipeline_inventory = set(bundle.pipeline_ids)
        for label, values in (
            ("results", bundle.results_by_pipeline),
            ("summaries", bundle.summaries_by_pipeline),
            ("validations", bundle.validations_by_pipeline),
            ("result digests", bundle.pipeline_result_sha256),
            ("completion digests", bundle.pipeline_completion_sha256),
            ("public metadata", bundle.pipeline_public_metadata),
        ):
            _expect(
                isinstance(values, dict) and set(values) == pipeline_inventory,
                f"verified pipeline {label} inventory drifted: {bundle.source_id}",
            )
        for pipeline_id in bundle.pipeline_ids:
            pipeline_dir = experiment_dir / "pipelines" / pipeline_id
            public_metadata = bundle.pipeline_public_metadata[pipeline_id]
            _expect(
                isinstance(public_metadata, dict)
                and set(public_metadata) == {"skill_version", "repeat"},
                f"pipeline public metadata drifted: {pipeline_id}",
            )
            arm = _arm_label(str(public_metadata.get("skill_version")))
            repeat = public_metadata.get("repeat")
            _expect(repeat in {1, 2}, f"invalid repeat: {pipeline_id}")
            result = bundle.results_by_pipeline[pipeline_id]
            validation = bundle.validations_by_pipeline[pipeline_id]
            summary = bundle.summaries_by_pipeline[pipeline_id]
            result_sha256 = bundle.pipeline_result_sha256[pipeline_id]
            completion_sha256 = bundle.pipeline_completion_sha256[pipeline_id]
            _expect(
                isinstance(result, dict)
                and isinstance(validation, dict)
                and isinstance(summary, dict)
                and isinstance(result_sha256, str)
                and result_sha256 == _sha256_bytes(_pretty_bytes(result))
                and isinstance(completion_sha256, str)
                and len(completion_sha256) == 64
                and all(character in "0123456789abcdef" for character in completion_sha256),
                f"verified pipeline snapshot drifted: {pipeline_id}",
            )
            (
                usage,
                elapsed,
                normal_calls,
                attempts,
                selected,
                underfilled,
            ) = _generator_summary_observations(summary, arm)
            generators.append(
                GeneratorRecord(
                    pipeline_id=pipeline_id,
                    source_id=bundle.source_id,
                    source_sha256=source_sha256_by_id[bundle.source_id],
                    arm=arm,
                    repeat=int(repeat),
                    result=dict(result),
                    validation=dict(validation),
                    summary=dict(summary),
                    all_attempt_usage=usage,
                    all_attempt_elapsed_seconds=elapsed,
                    normal_model_call_count=normal_calls,
                    total_model_attempt_count=attempts,
                    selected_count=selected,
                    underfilled_due_to_quality=underfilled,
                    result_path=pipeline_dir / "result.json",
                    completion_path=pipeline_dir / "complete.json",
                )
            )

    inventory = {(item.source_sha256, item.arm, item.repeat) for item in generators}
    _expect(len(inventory) == 12, "source-SHA/arm/repeat generator inventory drifted")
    for source_sha in set(source_sha256_by_id.values()):
        for arm in ARMS:
            _expect(
                sum(item.source_sha256 == source_sha and item.arm == arm for item in generators)
                == 2,
                f"expected two repeats for {source_sha}/{arm}",
            )

    judges: list[JudgeRecord] = []
    for bundle in bundles:
        for judge_id in JUDGE_IDS:
            call_dir = prepared.run_dir / "sources" / bundle.source_id / judge_id
            snapshot = judge_call_snapshots[(bundle.source_id, judge_id)]
            judges.append(
                JudgeRecord(
                    source_id=bundle.source_id,
                    source_sha256=source_sha256_by_id[bundle.source_id],
                    judge_id=judge_id,
                    result=dict(snapshot.result),
                    validation=dict(snapshot.validation),
                    binding=_global_binding(global_unblind, bundle.source_id, judge_id),
                    result_path=call_dir / "result.json",
                    completion_path=call_dir / "complete.json",
                )
            )
    return VerifiedExperiment(
        experiment_dir=experiment_dir,
        judge_run_dir=prepared.run_dir,
        experiment_id=str(manifest["experiment_id"]),
        evaluation_contract=evaluation_contract,
        evaluation_contract_sha256=evaluation_contract_sha256,
        source_ids=tuple(sorted(source_sha256_by_id)),
        source_sha256_by_id=source_sha256_by_id,
        source_metadata_by_id=source_metadata_by_id,
        candidates_by_source=candidates_by_source,
        generators=tuple(generators),
        judges=tuple(judges),
        global_unblind_path=prepared.run_dir / "unblind" / "global-unblind-manifest.json",
        feedback_release=dict(feedback_release),
        contracts_module=contracts_module,
    )


def _candidate_ids(record: GeneratorRecord) -> set[str]:
    highlights = record.result.get("highlights")
    _expect(isinstance(highlights, list), f"highlight list missing: {record.pipeline_id}")
    values = {str(item["candidate_id"]) for item in highlights if isinstance(item, dict)}
    _expect(len(values) == len(highlights), f"duplicate/malformed highlight: {record.pipeline_id}")
    return values


def _intervals(record: GeneratorRecord) -> list[tuple[int, int]]:
    return [
        (int(item["source_start_ms"]), int(item["source_end_ms"]))
        for item in record.result["highlights"]
    ]


def _candidate_jaccard(left: set[str], right: set[str]) -> Fraction:
    union = left | right
    return Fraction(len(left & right), len(union)) if union else Fraction(1)


def _interval_iou_at_least_half(left: tuple[int, int], right: tuple[int, int]) -> bool:
    intersection = max(0, min(left[1], right[1]) - max(left[0], right[0]))
    union = max(left[1], right[1]) - min(left[0], right[0])
    return union > 0 and intersection * 2 >= union


def _interval_match_f1(
    left: Sequence[tuple[int, int]], right: Sequence[tuple[int, int]]
) -> dict[str, Any]:
    adjacency = [
        [index for index, other in enumerate(right) if _interval_iou_at_least_half(item, other)]
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
    denominator = len(left) + len(right)
    f1 = Fraction(2 * count, denominator) if denominator else Fraction(1)
    return {"iou_threshold": _metric(Fraction(1, 2)), "matches": count, "f1": _metric(f1)}


def _judge_observations(
    verified: VerifiedExperiment,
) -> tuple[
    dict[tuple[str, str], Fraction],
    dict[tuple[str, str], dict[str, int]],
]:
    scores: dict[tuple[str, str], Fraction] = {}
    dimensions: dict[tuple[str, str], dict[str, int]] = {}
    generator_ids = {item.pipeline_id for item in verified.generators}
    for judge in verified.judges:
        mapping = judge.binding.get("anonymous_system_to_pipeline")
        _expect(isinstance(mapping, dict), "global anonymous-system binding is malformed")
        _expect(
            set(mapping.values()).issubset(generator_ids), "global binding has unknown pipeline"
        )
        evaluations = judge.result.get("system_evaluations")
        _expect(isinstance(evaluations, list) and len(evaluations) == 4, "Judge needs four systems")
        computed = judge.validation.get("computed_system_quality")
        _expect(isinstance(computed, dict), "Judge exact quality receipt is missing")
        _expect(set(computed) == set(mapping), "Judge exact quality inventory drifted")
        for evaluation in evaluations:
            _expect(isinstance(evaluation, dict), "Judge system evaluation is malformed")
            anonymous_id = evaluation.get("anonymous_system_id")
            _expect(anonymous_id in mapping, "Judge evaluation has unknown anonymous system")
            _expect(
                all(field in evaluation for field in SYSTEM_SCORE_FIELDS),
                "Judge evaluation is missing an anchored system field",
            )
            values: dict[str, int] = {}
            for field in SYSTEM_SCORE_FIELDS:
                value = evaluation[field]
                _expect(
                    isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 4,
                    f"invalid Judge field {field}",
                )
                values[field] = value
            numerator = sum(SYSTEM_SCORE_WEIGHTS[field] * values[field] for field in values)
            receipt = computed[anonymous_id]
            _expect(
                isinstance(receipt, dict)
                and receipt.get("weighted_numerator") == numerator
                and receipt.get("denominator") == 4,
                "Judge exact quality receipt drifted",
            )
            pipeline_id = str(mapping[anonymous_id])
            key = (judge.judge_id, pipeline_id)
            _expect(key not in scores, "duplicate Judge/pipeline observation")
            scores[key] = Fraction(numerator, 4)
            dimensions[key] = values
    _expect(len(scores) == 24, "expected 24 Judge/pipeline observations")
    return scores, dimensions


def _source_groups(records: Iterable[GeneratorRecord]) -> dict[str, list[GeneratorRecord]]:
    groups: dict[str, list[GeneratorRecord]] = defaultdict(list)
    for record in records:
        groups[record.source_sha256].append(record)
    return dict(groups)


def _quality_analysis(verified: VerifiedExperiment) -> dict[str, Any]:
    scores, dimensions = _judge_observations(verified)
    by_id = {record.pipeline_id: record for record in verified.generators}
    unique_sources = sorted({record.source_sha256 for record in verified.generators})
    arm_metrics: dict[str, Any] = {}
    exact_arm_macro: dict[str, Fraction] = {}
    exact_dimension_macro: dict[tuple[str, str], Fraction] = {}
    for arm in ARMS:
        by_source: dict[str, Any] = {}
        exact_sources: dict[str, Fraction] = {}
        for source_sha in unique_sources:
            pipelines = [
                record.pipeline_id
                for record in verified.generators
                if record.source_sha256 == source_sha and record.arm == arm
            ]
            _expect(len(pipelines) == 2, f"two repeats required for {source_sha}/{arm}")
            value = _mean(
                scores[(judge_id, pipeline)] for pipeline in pipelines for judge_id in JUDGE_IDS
            )
            exact_sources[source_sha] = value
            by_source[source_sha] = _metric(value)
        macro = _mean(exact_sources.values())
        exact_arm_macro[arm] = macro
        dimension_metrics: dict[str, Any] = {}
        for field in SYSTEM_SCORE_FIELDS:
            per_source = []
            for source_sha in unique_sources:
                pipelines = [
                    record.pipeline_id
                    for record in verified.generators
                    if record.source_sha256 == source_sha and record.arm == arm
                ]
                per_source.append(
                    _mean(
                        Fraction(dimensions[(judge_id, pipeline)][field] * 100, 4)
                        for pipeline in pipelines
                        for judge_id in JUDGE_IDS
                    )
                )
            exact = _mean(per_source)
            exact_dimension_macro[(arm, field)] = exact
            dimension_metrics[field.removesuffix("_x4") + "_x100"] = _metric(exact)
        arm_metrics[arm] = {
            "by_unique_source_sha256": by_source,
            "source_first_macro_x100": _metric(macro),
            "source_first_dimensions_x100": dimension_metrics,
        }

    source_deltas = {
        source_sha: _metric(
            _metric_fraction(
                arm_metrics[CONTENDER]["by_unique_source_sha256"][source_sha], "contender source"
            )
            - _metric_fraction(
                arm_metrics[BASELINE]["by_unique_source_sha256"][source_sha], "baseline source"
            )
        )
        for source_sha in unique_sources
    }
    return {
        "score_definition": (
            "Exact Judge system quality: valuable discovery 30%, "
            "judge semantic-opportunity coverage 20%, precision 20%, portfolio coherence 15%, "
            "editorial readiness 15%. No intermediate floor or rounding is used."
        ),
        "arms": arm_metrics,
        "iteration2_minus_fresh_v1_x100": _metric(
            exact_arm_macro[CONTENDER] - exact_arm_macro[BASELINE]
        ),
        "precision_iteration2_minus_fresh_v1_x100": _metric(
            exact_dimension_macro[(CONTENDER, "precision_x4")]
            - exact_dimension_macro[(BASELINE, "precision_x4")]
        ),
        "editorial_readiness_iteration2_minus_fresh_v1_x100": _metric(
            exact_dimension_macro[(CONTENDER, "editorial_readiness_x4")]
            - exact_dimension_macro[(BASELINE, "editorial_readiness_x4")]
        ),
        "by_unique_source_sha256_delta_x100": source_deltas,
        "worst_unique_source_sha256_delta_x100": _metric(
            min(_metric_fraction(value, "source delta") for value in source_deltas.values())
        ),
        "pipeline_scores": [
            {
                "source_sha256": record.source_sha256,
                "arm": record.arm,
                "repeat": record.repeat,
                "pipeline_id": record.pipeline_id,
                **{
                    judge_id: _metric(scores[(judge_id, record.pipeline_id)])
                    for judge_id in JUDGE_IDS
                },
                "dual_judge_mean_x100": _metric(
                    _mean(scores[(judge_id, record.pipeline_id)] for judge_id in JUDGE_IDS)
                ),
            }
            for record in sorted(
                by_id.values(), key=lambda item: (item.source_sha256, item.arm, item.repeat)
            )
        ],
    }


def _deterministic_metrics(verified: VerifiedExperiment) -> dict[str, Any]:
    by_source: list[dict[str, Any]] = []
    stability: list[dict[str, Any]] = []
    unique_sources = sorted({record.source_sha256 for record in verified.generators})
    macro_candidate: dict[str, list[Fraction]] = defaultdict(list)
    macro_interval: dict[str, list[Fraction]] = defaultdict(list)
    for source_sha in unique_sources:
        source_records = [r for r in verified.generators if r.source_sha256 == source_sha]
        observed_union = set().union(*(_candidate_ids(record) for record in source_records))
        row: dict[str, Any] = {
            "source_sha256": source_sha,
            "observed_selected_union_candidate_count": len(observed_union),
        }
        for arm in ARMS:
            records = sorted(
                (record for record in source_records if record.arm == arm),
                key=lambda item: item.repeat,
            )
            _expect(len(records) == 2, f"two repeats required for {source_sha}/{arm}")
            arm_union = _candidate_ids(records[0]) | _candidate_ids(records[1])
            exact_relative = (
                Fraction(len(arm_union), len(observed_union)) if observed_union else Fraction(1)
            )
            row[f"{arm}_selected_union_candidate_count"] = len(arm_union)
            row[f"{arm}_deterministic_relative_selected_union_candidate_coverage"] = _metric(
                exact_relative
            )
            candidate = _candidate_jaccard(_candidate_ids(records[0]), _candidate_ids(records[1]))
            interval = _interval_match_f1(_intervals(records[0]), _intervals(records[1]))
            interval_fraction = _metric_fraction(interval["f1"], "interval F1")
            macro_candidate[arm].append(candidate)
            macro_interval[arm].append(interval_fraction)
            stability.append(
                {
                    "source_sha256": source_sha,
                    "arm": arm,
                    "repeat_candidate_jaccard": _metric(candidate),
                    "repeat_interval_match": interval,
                }
            )
        by_source.append(row)
    macro = {
        arm: {
            "candidate_jaccard": _metric(_mean(macro_candidate[arm])),
            "interval_f1": _metric(_mean(macro_interval[arm])),
        }
        for arm in ARMS
    }
    return {
        "deterministic_relative_selected_union_candidate_coverage_definition": (
            "For each unique source SHA-256, an arm's repeat-union candidate IDs divided by "
            "the candidate-ID union observed across both arms and repeats; this is relative, "
            "not absolute recall and not Judge semantic-opportunity coverage."
        ),
        "by_unique_source_sha256": by_source,
        "sampling_stability": stability,
        "source_first_macro_sampling_stability": macro,
    }


def _evidence_and_adaptive_selection(verified: VerifiedExperiment) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total_failures = 0
    adaptive_failures = 0
    for record in verified.generators:
        failures = 0
        if record.arm == CONTENDER:
            candidates = verified.candidates_by_source[record.source_id]
            for highlight in record.result["highlights"]:
                candidate_id = str(highlight["candidate_id"])
                _expect(candidate_id in candidates, "contender selected unknown candidate")
                candidate_text = str(candidates[candidate_id]["text"])
                quote_text = highlight.get("evidence_quote")
                source_sentence = highlight.get("source_sentence")
                if not isinstance(quote_text, str) or not isinstance(source_sentence, str):
                    failures += 1
                    continue
                quote_receipt = verified.contracts_module.exact_quote_receipt(
                    quote_text, candidate_text
                )
                source_receipt = verified.contracts_module.exact_quote_receipt(
                    source_sentence, quote_text
                )
                if (
                    quote_receipt.get("status") != "passed"
                    or source_receipt.get("status") != "passed"
                    or len(str(source_receipt.get("normalized_quote", ""))) < 8
                ):
                    failures += 1
            total_failures += failures
            if (
                not 8 <= record.selected_count <= 12
                or record.underfilled_due_to_quality
                or record.selected_count != len(record.result["highlights"])
            ):
                adaptive_failures += 1
        rows.append(
            {
                "source_sha256": record.source_sha256,
                "arm": record.arm,
                "repeat": record.repeat,
                "selected_count": record.selected_count,
                "underfilled_due_to_quality": record.underfilled_due_to_quality,
                "exact_quote_or_source_sentence_failure_count": failures,
                "normal_model_call_count": record.normal_model_call_count,
                "total_model_attempt_count": record.total_model_attempt_count,
            }
        )
    return {
        "iteration2_outward_exact_quote_or_source_sentence_failure_count": total_failures,
        "iteration2_adaptive_portfolio_failure_count": adaptive_failures,
        "by_pipeline": rows,
    }


def _efficiency(verified: VerifiedExperiment) -> dict[str, Any]:
    totals: dict[str, Any] = {}
    exact_elapsed: dict[str, Fraction] = {}
    exact_tokens: dict[str, Fraction] = {}
    for arm in ARMS:
        records = [record for record in verified.generators if record.arm == arm]
        elapsed = sum((record.all_attempt_elapsed_seconds for record in records), Fraction())
        tokens = Fraction(
            sum(record.all_attempt_usage["reported_total_tokens"] for record in records)
        )
        exact_elapsed[arm] = elapsed
        exact_tokens[arm] = tokens
        totals[arm] = {
            "completion_bound_all_attempt_elapsed_seconds": _metric(elapsed),
            "completion_bound_all_attempt_reported_total_tokens": _metric(tokens),
            "normal_model_call_count": sum(record.normal_model_call_count for record in records),
            "total_model_attempt_count": sum(
                record.total_model_attempt_count for record in records
            ),
            "maximum_normal_model_call_count_per_pipeline": max(
                record.normal_model_call_count for record in records
            ),
        }
    by_source: list[dict[str, Any]] = []
    source_elapsed_ratios: list[Fraction] = []
    source_token_ratios: list[Fraction] = []
    for source_sha256 in sorted({record.source_sha256 for record in verified.generators}):
        source_totals: dict[str, dict[str, Fraction]] = {}
        for arm in ARMS:
            records = [
                record
                for record in verified.generators
                if record.source_sha256 == source_sha256 and record.arm == arm
            ]
            _expect(
                len(records) == 2,
                f"efficiency requires two repeats for {source_sha256}/{arm}",
            )
            source_totals[arm] = {
                "elapsed": sum(
                    (record.all_attempt_elapsed_seconds for record in records),
                    Fraction(),
                ),
                "tokens": Fraction(
                    sum(record.all_attempt_usage["reported_total_tokens"] for record in records)
                ),
            }
        baseline_elapsed = source_totals[BASELINE]["elapsed"]
        baseline_tokens = source_totals[BASELINE]["tokens"]
        _expect(
            baseline_elapsed > 0,
            f"fresh v1 elapsed denominator is zero: {source_sha256}",
        )
        _expect(
            baseline_tokens > 0,
            f"fresh v1 token denominator is zero: {source_sha256}",
        )
        elapsed_ratio = source_totals[CONTENDER]["elapsed"] / baseline_elapsed
        token_ratio = source_totals[CONTENDER]["tokens"] / baseline_tokens
        source_elapsed_ratios.append(elapsed_ratio)
        source_token_ratios.append(token_ratio)
        by_source.append(
            {
                "source_sha256": source_sha256,
                "fresh_v1_all_attempt_elapsed_seconds": _metric(baseline_elapsed),
                "iteration2_all_attempt_elapsed_seconds": _metric(
                    source_totals[CONTENDER]["elapsed"]
                ),
                "iteration2_to_fresh_v1_all_attempt_elapsed_ratio": _metric(elapsed_ratio),
                "fresh_v1_all_attempt_reported_total_tokens": _metric(baseline_tokens),
                "iteration2_all_attempt_reported_total_tokens": _metric(
                    source_totals[CONTENDER]["tokens"]
                ),
                "iteration2_to_fresh_v1_all_attempt_reported_total_token_ratio": _metric(
                    token_ratio
                ),
            }
        )
    return {
        "cost_scope": (
            "Completion-bound totals include every model attempt, including failed repairs; "
            "pre-model infrastructure probes are excluded. Ratios first total two repeats "
            "inside each unique source SHA-256, then use an equal-source macro mean."
        ),
        "ratio_aggregation": "equal_macro_mean_of_per_unique_source_sha256_arm_total_ratios",
        "arms": totals,
        "by_unique_source_sha256": by_source,
        "iteration2_to_fresh_v1_all_attempt_elapsed_ratio": _metric(_mean(source_elapsed_ratios)),
        "iteration2_to_fresh_v1_all_attempt_reported_total_token_ratio": _metric(
            _mean(source_token_ratios)
        ),
    }


def _judge_disagreement(verified: VerifiedExperiment, quality: Mapping[str, Any]) -> dict[str, Any]:
    pipeline_rows = quality["pipeline_scores"]
    by_key = {(row["source_sha256"], row["arm"], row["repeat"]): row for row in pipeline_rows}
    pipeline_differences = [
        abs(
            _metric_fraction(row["judge_01"], "Judge 01 pipeline score")
            - _metric_fraction(row["judge_02"], "Judge 02 pipeline score")
        )
        for row in pipeline_rows
    ]
    cells: list[dict[str, Any]] = []
    source_arm_differences: list[Fraction] = []
    for source_sha in sorted({record.source_sha256 for record in verified.generators}):
        for arm in ARMS:
            judge_means = {
                judge_id: _mean(
                    _metric_fraction(
                        by_key[(source_sha, arm, repeat)][judge_id], "Judge pipeline score"
                    )
                    for repeat in (1, 2)
                )
                for judge_id in JUDGE_IDS
            }
            difference = abs(judge_means[JUDGE_IDS[0]] - judge_means[JUDGE_IDS[1]])
            source_arm_differences.append(difference)
            cells.append(
                {
                    "source_sha256": source_sha,
                    "arm": arm,
                    "judge_01_mean_x100": _metric(judge_means["judge_01"]),
                    "judge_02_mean_x100": _metric(judge_means["judge_02"]),
                    "absolute_difference_x100": _metric(difference),
                }
            )
    return {
        "mean_absolute_quality_difference_x100": _metric(_mean(pipeline_differences)),
        "maximum_source_arm_absolute_quality_difference_x100": _metric(max(source_arm_differences)),
        "by_unique_source_sha256_and_arm": cells,
    }


def _gate(status: str, **evidence: Any) -> dict[str, Any]:
    return {"status": status, **evidence}


def _acceptance(
    quality: Mapping[str, Any],
    deterministic: Mapping[str, Any],
    evidence: Mapping[str, Any],
    efficiency: Mapping[str, Any],
    disagreement: Mapping[str, Any],
) -> dict[str, Any]:
    q_delta = _metric_fraction(quality["iteration2_minus_fresh_v1_x100"], "quality delta")
    precision_new = _metric_fraction(
        quality["arms"][CONTENDER]["source_first_dimensions_x100"]["precision_x100"],
        "iteration2 precision",
    )
    precision_delta = _metric_fraction(
        quality["precision_iteration2_minus_fresh_v1_x100"], "precision delta"
    )
    editorial_new = _metric_fraction(
        quality["arms"][CONTENDER]["source_first_dimensions_x100"]["editorial_readiness_x100"],
        "iteration2 editorial readiness",
    )
    editorial_delta = _metric_fraction(
        quality["editorial_readiness_iteration2_minus_fresh_v1_x100"],
        "editorial readiness delta",
    )
    worst_source = _metric_fraction(
        quality["worst_unique_source_sha256_delta_x100"], "worst source delta"
    )
    stability = deterministic["source_first_macro_sampling_stability"]
    candidate_new = _metric_fraction(stability[CONTENDER]["candidate_jaccard"], "new Jaccard")
    candidate_old = _metric_fraction(stability[BASELINE]["candidate_jaccard"], "old Jaccard")
    interval_new = _metric_fraction(stability[CONTENDER]["interval_f1"], "new interval F1")
    interval_old = _metric_fraction(stability[BASELINE]["interval_f1"], "old interval F1")
    elapsed_ratio = _metric_fraction(
        efficiency["iteration2_to_fresh_v1_all_attempt_elapsed_ratio"], "elapsed ratio"
    )
    token_ratio = _metric_fraction(
        efficiency["iteration2_to_fresh_v1_all_attempt_reported_total_token_ratio"],
        "token ratio",
    )
    mean_disagreement = _metric_fraction(
        disagreement["mean_absolute_quality_difference_x100"], "mean disagreement"
    )
    maximum_disagreement = _metric_fraction(
        disagreement["maximum_source_arm_absolute_quality_difference_x100"],
        "maximum disagreement",
    )
    gates = {
        "quality_noninferiority": _gate(
            "passed" if q_delta >= -2 else "failed",
            observed_delta_x100=quality["iteration2_minus_fresh_v1_x100"],
            threshold=">=-2",
        ),
        "precision_absolute_and_noninferiority": _gate(
            "passed" if precision_new >= 75 and precision_delta >= -2 else "failed",
            iteration2_x100=_metric(precision_new),
            observed_delta_x100=_metric(precision_delta),
            thresholds={"iteration2": ">=75", "delta": ">=-2"},
        ),
        "editorial_readiness_absolute_and_noninferiority": _gate(
            "passed" if editorial_new >= 75 and editorial_delta >= -2 else "failed",
            iteration2_x100=_metric(editorial_new),
            observed_delta_x100=_metric(editorial_delta),
            thresholds={"iteration2": ">=75", "delta": ">=-2"},
        ),
        "worst_unique_source_noninferiority": _gate(
            "passed" if worst_source >= -5 else "failed",
            observed_delta_x100=_metric(worst_source),
            threshold=">=-5",
        ),
        "candidate_jaccard_noninferiority": _gate(
            "passed" if candidate_new >= candidate_old - Fraction(1, 20) else "failed",
            fresh_v1=_metric(candidate_old),
            iteration2=_metric(candidate_new),
            threshold="iteration2>=fresh_v1-0.05",
        ),
        "interval_f1_noninferiority": _gate(
            "passed" if interval_new >= interval_old - Fraction(1, 20) else "failed",
            fresh_v1=_metric(interval_old),
            iteration2=_metric(interval_new),
            threshold="iteration2>=fresh_v1-0.05",
        ),
        "all_attempt_efficiency_within_3x": _gate(
            "passed" if elapsed_ratio <= 3 and token_ratio <= 3 else "failed",
            elapsed_ratio=_metric(elapsed_ratio),
            reported_total_token_ratio=_metric(token_ratio),
            threshold="both<=3",
        ),
        "normal_model_call_topology": _gate(
            "passed"
            if efficiency["arms"][CONTENDER]["maximum_normal_model_call_count_per_pipeline"] <= 2
            else "failed",
            observed_maximum=efficiency["arms"][CONTENDER][
                "maximum_normal_model_call_count_per_pipeline"
            ],
            threshold="<=2",
        ),
        "exact_quote_and_source_sentence": _gate(
            "passed"
            if evidence["iteration2_outward_exact_quote_or_source_sentence_failure_count"] == 0
            else "failed",
            observed_failures=evidence[
                "iteration2_outward_exact_quote_or_source_sentence_failure_count"
            ],
            threshold=0,
        ),
        "adaptive_portfolio_count": _gate(
            "passed" if evidence["iteration2_adaptive_portfolio_failure_count"] == 0 else "failed",
            observed_failures=evidence["iteration2_adaptive_portfolio_failure_count"],
            threshold=0,
            rule="every iteration2 pipeline selects 8-12 and underfilled=false",
        ),
        "judge_agreement_bound": _gate(
            "passed" if mean_disagreement <= 10 and maximum_disagreement <= 20 else "inconclusive",
            mean_absolute_difference_x100=_metric(mean_disagreement),
            maximum_source_arm_absolute_difference_x100=_metric(maximum_disagreement),
            thresholds={"mean": "<=10", "source_arm": "<=20"},
        ),
    }
    non_judge_gates = {key: gate for key, gate in gates.items() if key != "judge_agreement_bound"}
    if gates["judge_agreement_bound"]["status"] == "inconclusive":
        outcome = "inconclusive_iteration2"
    elif any(gate["status"] != "passed" for gate in non_judge_gates.values()):
        outcome = "reject_iteration2"
    elif all(gate["status"] == "passed" for gate in gates.values()):
        outcome = "advance_iteration2_to_frozen_holdout"
    else:
        outcome = "reject_iteration2"
    return {
        "outcome": outcome,
        "production_decision": "unchanged",
        "holdout_only": True,
        "gates": gates,
    }


def analyze_verified_experiment(verified: VerifiedExperiment) -> dict[str, Any]:
    quality = _quality_analysis(verified)
    deterministic = _deterministic_metrics(verified)
    evidence = _evidence_and_adaptive_selection(verified)
    efficiency = _efficiency(verified)
    disagreement = _judge_disagreement(verified, quality)
    acceptance = _acceptance(quality, deterministic, evidence, efficiency, disagreement)
    return {
        "schema_version": SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "scope": {
            "iteration": "iteration-2",
            "experiment_id": verified.experiment_id,
            "evaluation_contract_sha256": verified.evaluation_contract_sha256,
            "unique_source_sha256_count": len(set(verified.source_sha256_by_id.values())),
            "generator_pipeline_count": len(verified.generators),
            "judge_call_count": len(verified.judges),
            "global_unblind_only": True,
            "human_review_mode": verified.evaluation_contract["human_review_mode"],
            "feedback_release": verified.feedback_release,
        },
        "integrity": {
            "generator_topology_and_artifact_sets_verified": True,
            "all_attempt_usage_complete": True,
            "all_six_judges_verified_before_global_unblind": True,
            "per_call_identity_mapping_read": False,
            "source_first_unique_sha256_weighting": True,
            "exact_fraction_aggregation": True,
            "display_rounding": "ROUND_HALF_UP_3_DECIMALS",
        },
        "quality": quality,
        "deterministic_metrics": deterministic,
        "evidence_and_adaptive_selection": evidence,
        "efficiency": efficiency,
        "judge_disagreement": disagreement,
        "acceptance": acceptance,
        "limitations": [
            "The three development sources shaped iteration-2 and cannot prove generalization.",
            "Judge semantic-opportunity coverage is model-mediated and relative to observed evidence; it is not absolute recall.",
            "Deterministic relative selected-union candidate coverage is a separate candidate-union diagnostic.",
            "Passing advances only to a new frozen multi-genre holdout; it never accepts production integration.",
        ],
        "traceability": {
            "experiment_manifest": str(verified.experiment_dir / "experiment-manifest.json"),
            "global_unblind_manifest": str(verified.global_unblind_path),
            "generator_completions": [str(item.completion_path) for item in verified.generators],
            "judge_completions": [str(item.completion_path) for item in verified.judges],
        },
    }


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _display(value: Any) -> str:
    if isinstance(value, Mapping) and set(value) == {"numerator", "denominator", "display"}:
        return str(value["display"])
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "—"
    return str(value)


def _table(rows: Sequence[Mapping[str, Any]], columns: Sequence[tuple[str, str]]) -> str:
    head = "".join(f"<th>{_escape(label)}</th>" for _, label in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{_escape(_display(row.get(key)))}</td>" for key, _ in columns)
        + "</tr>"
        for row in rows
    )
    return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _relative_href(report_path: Path, target: Path) -> str:
    relative = os.path.relpath(target, start=report_path.parent)
    return quote(Path(relative).as_posix(), safe="/._-")


def render_html_report(
    analysis: Mapping[str, Any],
    verified: VerifiedExperiment,
    report_path: Path,
) -> str:
    quality = analysis["quality"]
    acceptance = analysis["acceptance"]
    quality_rows = [
        {
            "arm": arm,
            "quality": quality["arms"][arm]["source_first_macro_x100"],
            **quality["arms"][arm]["source_first_dimensions_x100"],
        }
        for arm in ARMS
    ]
    source_rows = [
        {
            "source_sha256": source_sha,
            BASELINE: quality["arms"][BASELINE]["by_unique_source_sha256"][source_sha],
            CONTENDER: quality["arms"][CONTENDER]["by_unique_source_sha256"][source_sha],
            "delta": quality["by_unique_source_sha256_delta_x100"][source_sha],
        }
        for source_sha in quality["by_unique_source_sha256_delta_x100"]
    ]
    stability_rows = []
    for arm in ARMS:
        row = {"arm": arm}
        row.update(analysis["deterministic_metrics"]["source_first_macro_sampling_stability"][arm])
        stability_rows.append(row)
    disagreement_rows = analysis["judge_disagreement"]["by_unique_source_sha256_and_arm"]
    gate_html = "".join(
        f"<li><strong>{_escape(name)}</strong>: {_escape(gate['status'])}"
        f"<pre>{_escape(json.dumps(gate, ensure_ascii=False, indent=2))}</pre></li>"
        for name, gate in acceptance["gates"].items()
    )
    traces = [
        ("evaluation contract", EVALUATION_CONTRACT_PATH),
        ("global unblind", verified.global_unblind_path),
        *[(f"generator {item.pipeline_id}", item.completion_path) for item in verified.generators],
        *[
            (f"Judge {item.source_id}/{item.judge_id}", item.completion_path)
            for item in verified.judges
        ],
    ]
    trace_html = "".join(
        f"<li><a href='{_relative_href(report_path, path)}'>{_escape(label)}</a></li>"
        for label, path in traces
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LiveClip Highlight Agent · Iteration 2</title>
<style>body{{max-width:1180px;margin:auto;padding:28px;background:#f5f7fa;color:#172033;font:15px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}}section{{background:white;border:1px solid #d8dee8;border-radius:12px;padding:20px;margin:14px 0}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #e3e7ee;text-align:left;vertical-align:top}}.scroll{{overflow:auto}}pre{{white-space:pre-wrap;background:#f7f8fa;padding:9px;border-radius:7px}}code{{word-break:break-all}}</style></head><body>
<section><h1>Highlight Agent · Iteration 2</h1><p><strong>Outcome:</strong> {_escape(acceptance["outcome"])}</p><p>Only a fully passing development result may advance to a new frozen holdout. Production remains unchanged.</p><p><code>{_escape(verified.evaluation_contract_sha256)}</code></p></section>
<section><h2>Frozen gates</h2><ul>{gate_html}</ul></section>
<section><h2>Exact source-first Judge quality</h2><p>{_escape(quality["score_definition"])}</p>{_table(quality_rows, [("arm", "Arm"), ("quality", "Quality"), ("valuable_discovery_x100", "Valuable discovery"), ("judge_semantic_opportunity_coverage_x100", "Judge semantic-opportunity coverage"), ("precision_x100", "Precision"), ("portfolio_coherence_x100", "Portfolio coherence"), ("editorial_readiness_x100", "Editorial readiness")])}<h3>Unique source SHA-256 deltas</h3>{_table(source_rows, [("source_sha256", "Unique source SHA-256"), (BASELINE, "Fresh v1"), (CONTENDER, "Iteration 2"), ("delta", "Delta")])}</section>
<section><h2>Deterministic relative selected-union candidate metric</h2><p>{_escape(analysis["deterministic_metrics"]["deterministic_relative_selected_union_candidate_coverage_definition"])}</p><p>This metric is distinct from Judge semantic-opportunity coverage.</p></section>
<section><h2>Sampling stability</h2>{_table(stability_rows, [("arm", "Arm"), ("candidate_jaccard", "Candidate Jaccard"), ("interval_f1", "Interval F1")])}</section>
<section><h2>Judge disagreement</h2><p>Mean absolute difference: {_escape(_display(analysis["judge_disagreement"]["mean_absolute_quality_difference_x100"]))}; maximum unique-source/arm difference: {_escape(_display(analysis["judge_disagreement"]["maximum_source_arm_absolute_quality_difference_x100"]))}.</p>{_table(disagreement_rows, [("source_sha256", "Unique source SHA-256"), ("arm", "Arm"), ("judge_01_mean_x100", "Judge 01"), ("judge_02_mean_x100", "Judge 02"), ("absolute_difference_x100", "Absolute difference")])}</section>
<section><h2>All-attempt efficiency</h2><p>{_escape(analysis["efficiency"]["cost_scope"])}</p>{_table([{"metric": "Elapsed ratio", "value": analysis["efficiency"]["iteration2_to_fresh_v1_all_attempt_elapsed_ratio"]}, {"metric": "Reported total-token ratio", "value": analysis["efficiency"]["iteration2_to_fresh_v1_all_attempt_reported_total_token_ratio"]}], [("metric", "Metric"), ("value", "Iteration 2 / fresh v1")])}</section>
<section><h2>Traceability</h2><ul>{trace_html}</ul></section>
</body></html>"""


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _expect(path.is_file() and not path.is_symlink(), f"unsafe report target: {path}")
        if path.read_bytes() == payload:
            return
        raise AnalysisError(f"refusing to overwrite immutable report: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
    candidates = [
        path
        for path in DEFAULT_EXPERIMENTS_ROOT.glob("exp_*")
        if (path / "run-summary.json").is_file()
        and _load_json(path / "run-summary.json").get("status") == "generation_completed"
    ]
    if len(candidates) != 1:
        raise AnalysisError(
            "default discovery requires exactly one completed iteration-2 experiment; "
            f"found {len(candidates)}"
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
    print(f"OUTCOME: {analysis['acceptance']['outcome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
