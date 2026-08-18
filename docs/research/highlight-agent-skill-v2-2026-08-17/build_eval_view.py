#!/usr/bin/env python3
# ruff: noqa: RUF001 -- Chinese viewer copy intentionally uses full-width punctuation.
"""Build an immutable, offline, blind review artifact for the formal v1/v2 study.

The builder intentionally reads only the public experiment contract, frozen source
evidence, completed pipeline receipts, and their hash-bound call evidence. It never
opens the experiment's private arm mapping. All twelve pipelines must be complete
and byte-consistent before a review directory is published.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

REVIEW_PROTOCOL = "liveclip-highlight-source-first-blind-review-v1"
EXPECTED_SOURCE_COUNT = 3
EXPECTED_REPEATS_PER_SOURCE = 2
EXPECTED_PIPELINE_COUNT = 12
ITERATION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HEX_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

COMMON_PIPELINE_ARTIFACTS = {
    "result.json",
    "validation.json",
    "summary.json",
}
V2_PIPELINE_ARTIFACTS = {
    "tier1-assessments.json",
    "tier1-validation.json",
    "tier2-inventory.json",
    "tier2-validation.json",
    "tier3-portfolio.json",
    "would-escalate.json",
    "repair-budget.json",
}
CALL_ARTIFACTS = {
    "result.raw.json",
    "result.json",
    "validation.json",
    "call-metadata.json",
    "events.jsonl",
}
INFRASTRUCTURE_FAILURE_RECEIPT_KEYS = {
    "schema_version",
    "experiment_id",
    "experiment_contract_sha256",
    "call_id",
    "pipeline_id",
    "stage",
    "failure_number",
    "category",
    "returncode",
    "model_started",
    "model_attempt_consumed",
    "call_contract_sha256",
    "stdout_tail",
    "stderr_tail",
    "recorded_at",
}
SENSITIVE_REVIEW_KEYS = {
    "arm_id",
    "pipeline_id",
    "repeat",
    "skill_version",
    "model",
    "reasoning_effort",
    "usage",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "latency",
    "elapsed_seconds",
    "call_elapsed_seconds",
    "tier_call_elapsed_seconds",
    "score",
    "scores",
    "quality_total",
    "quality_score_x100",
    "rank",
    "self_score",
}


class ReviewBuildError(RuntimeError):
    """The formal experiment cannot safely be converted into a review artifact."""


@dataclass(frozen=True)
class PlannedPipeline:
    pipeline_id: str
    source_id: str
    repeat: int
    arm_id: str


@dataclass(frozen=True)
class VerifiedPipeline:
    pipeline_id: str
    source_id: str
    repeat: int
    arm_id: str
    skill_version: str
    result: dict[str, Any]
    result_sha256: str
    completion_sha256: str


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


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX_SHA256_RE.fullmatch(value) is None:
        raise ReviewBuildError(f"{label} is not a SHA-256 digest")
    return value


def _safe_child(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ReviewBuildError(f"unsafe experiment-relative path: {relative!r}")
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ReviewBuildError(f"symlink is forbidden in experiment evidence: {relative}")
    try:
        current.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ReviewBuildError(f"experiment path escapes its root: {relative}") from exc
    return current


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReviewBuildError(f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewBuildError(f"invalid JSON for {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ReviewBuildError(f"{label} must be a JSON object: {path}")
    return value


def _artifact_record(
    manifest: dict[str, Any], experiment_dir: Path, relative: str
) -> tuple[Path, str]:
    artifact_index = manifest.get("artifact_index")
    if not isinstance(artifact_index, dict):
        raise ReviewBuildError("experiment manifest has no artifact index")
    record = artifact_index.get(relative)
    if not isinstance(record, dict) or set(record) != {"sha256", "size_bytes"}:
        raise ReviewBuildError(f"manifest artifact receipt is missing or malformed: {relative}")
    expected_sha = _require_sha256(record.get("sha256"), f"artifact {relative}")
    expected_size = record.get("size_bytes")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        raise ReviewBuildError(f"artifact size receipt is invalid: {relative}")
    path = _safe_child(experiment_dir, relative)
    if not path.is_file() or path.is_symlink():
        raise ReviewBuildError(f"indexed experiment artifact is missing: {relative}")
    if path.stat().st_size != expected_size or _sha256_path(path) != expected_sha:
        raise ReviewBuildError(f"indexed experiment artifact drift: {relative}")
    return path, expected_sha


def _load_public_contract(
    experiment_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = _read_object(experiment_dir / "experiment-manifest.json", "experiment manifest")
    immutable_contract = manifest.get("immutable_contract")
    if not isinstance(immutable_contract, dict):
        raise ReviewBuildError("experiment manifest has no immutable contract")
    contract_sha = _require_sha256(manifest.get("contract_sha256"), "experiment contract")
    if _sha256_bytes(_canonical_bytes(immutable_contract)) != contract_sha:
        raise ReviewBuildError("experiment immutable contract hash drift")
    if manifest.get("experiment_id") != f"exp_{contract_sha[:20]}":
        raise ReviewBuildError("experiment ID does not match its immutable contract")

    public_plan_path, public_plan_sha = _artifact_record(
        manifest, experiment_dir, "frozen/public-plan.json"
    )
    if immutable_contract.get("public_plan_sha256") != public_plan_sha:
        raise ReviewBuildError("public plan receipt disagrees with the immutable contract")
    public_plan = _read_object(public_plan_path, "public plan")

    raw_sources = immutable_contract.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != EXPECTED_SOURCE_COUNT:
        raise ReviewBuildError("formal study requires exactly three source contracts")
    source_contracts: dict[str, dict[str, Any]] = {}
    for item in raw_sources:
        if not isinstance(item, dict) or not isinstance(item.get("source_id"), str):
            raise ReviewBuildError("source contract is malformed")
        source_id = item["source_id"]
        if source_id in source_contracts:
            raise ReviewBuildError(f"duplicate source contract: {source_id}")
        source_contracts[source_id] = item
    return manifest, public_plan, source_contracts


def _planned_pipelines(public_plan: dict[str, Any]) -> dict[str, PlannedPipeline]:
    if public_plan.get("pipeline_count") != EXPECTED_PIPELINE_COUNT:
        raise ReviewBuildError("formal public plan must declare exactly 12 pipelines")
    if public_plan.get("unique_source_count") != EXPECTED_SOURCE_COUNT:
        raise ReviewBuildError("formal public plan must declare exactly three sources")
    if public_plan.get("repeats_per_source") != EXPECTED_REPEATS_PER_SOURCE:
        raise ReviewBuildError("formal public plan must declare two repeats per source")
    schedule = public_plan.get("schedule")
    if not isinstance(schedule, list) or len(schedule) != 6:
        raise ReviewBuildError("formal public plan must contain six source/repeat blocks")

    planned: dict[str, PlannedPipeline] = {}
    source_repeats: Counter[tuple[str, int]] = Counter()
    for pair in schedule:
        if not isinstance(pair, dict):
            raise ReviewBuildError("public plan block is malformed")
        source_id = pair.get("source_id")
        repeat = pair.get("repeat")
        pipelines = pair.get("pipelines")
        if (
            not isinstance(source_id, str)
            or not isinstance(repeat, int)
            or isinstance(repeat, bool)
        ):
            raise ReviewBuildError("public plan block identity is malformed")
        if repeat not in {1, 2} or not isinstance(pipelines, list) or len(pipelines) != 2:
            raise ReviewBuildError("each source/repeat block must contain exactly two pipelines")
        source_repeats[(source_id, repeat)] += 1
        for entry in pipelines:
            if not isinstance(entry, dict):
                raise ReviewBuildError("public pipeline entry is malformed")
            pipeline_id = entry.get("pipeline_id")
            arm_id = entry.get("arm_id")
            if (
                not isinstance(pipeline_id, str)
                or SAFE_COMPONENT_RE.fullmatch(pipeline_id) is None
                or not isinstance(arm_id, str)
            ):
                raise ReviewBuildError("public pipeline identity is malformed")
            if pipeline_id in planned:
                raise ReviewBuildError(f"duplicate public pipeline ID: {pipeline_id}")
            planned[pipeline_id] = PlannedPipeline(
                pipeline_id=pipeline_id,
                source_id=source_id,
                repeat=repeat,
                arm_id=arm_id,
            )
    if len(planned) != EXPECTED_PIPELINE_COUNT:
        raise ReviewBuildError("public plan does not contain exactly 12 unique pipelines")
    expected_blocks = {
        (source_id, repeat)
        for source_id in {item.source_id for item in planned.values()}
        for repeat in (1, 2)
    }
    invalid_counts = any(count != 1 for count in source_repeats.values())
    if set(source_repeats) != expected_blocks or invalid_counts:
        raise ReviewBuildError("public plan source/repeat accounting is incomplete")
    return planned


def _load_sources(
    manifest: dict[str, Any],
    experiment_dir: Path,
    source_contracts: dict[str, dict[str, Any]],
    planned: dict[str, PlannedPipeline],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    planned_source_ids = {item.source_id for item in planned.values()}
    if set(source_contracts) != planned_source_ids:
        raise ReviewBuildError("source contracts and public pipeline plan disagree")
    sources: dict[str, dict[str, Any]] = {}
    input_hashes: dict[str, str] = {}
    for source_id, contract in source_contracts.items():
        path, indexed_sha = _artifact_record(
            manifest, experiment_dir, f"frozen/inputs/{source_id}.json"
        )
        if contract.get("experiment_input_sha256") != indexed_sha:
            raise ReviewBuildError(f"source input receipt drift: {source_id}")
        evidence = _read_object(path, f"frozen source {source_id}")
        candidates = evidence.get("candidates")
        source = evidence.get("source")
        if not isinstance(candidates, list) or not isinstance(source, dict):
            raise ReviewBuildError(f"frozen source evidence is malformed: {source_id}")
        if contract.get("candidate_count") != len(candidates):
            raise ReviewBuildError(f"frozen source candidate count drift: {source_id}")
        candidate_ids = [item.get("candidate_id") for item in candidates if isinstance(item, dict)]
        if len(candidate_ids) != len(candidates) or len(set(candidate_ids)) != len(candidate_ids):
            raise ReviewBuildError(f"frozen source candidate identities are invalid: {source_id}")
        sources[source_id] = evidence
        input_hashes[source_id] = _sha256_bytes(_pretty_bytes(evidence))
    return sources, input_hashes


def _expected_call_ids(contract: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    required = contract.get("required_call_ids")
    conditional = contract.get("conditional_call_ids")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ReviewBuildError("pipeline required-call contract is malformed")
    if not isinstance(conditional, dict):
        raise ReviewBuildError("pipeline conditional-call contract is malformed")
    call_ids = list(required)
    if contract.get("skill_version") == "v2":
        selected_count = summary.get("selected_count")
        if not isinstance(selected_count, int) or isinstance(selected_count, bool):
            raise ReviewBuildError("pipeline summary selected_count is malformed")
        if selected_count > 0:
            conditional_id = conditional.get("nonempty_portfolio")
            if not isinstance(conditional_id, str):
                raise ReviewBuildError("v2 conditional call receipt is missing")
            call_ids.append(conditional_id)
    if len(call_ids) != len(set(call_ids)):
        raise ReviewBuildError("pipeline call IDs are not unique")
    for call_id in call_ids:
        if SAFE_COMPONENT_RE.fullmatch(call_id) is None:
            raise ReviewBuildError(f"unsafe call ID: {call_id!r}")
    return sorted(call_ids)


def _reported_infrastructure_failure_receipts(
    call_dir: Path, completion: dict[str, Any], call_id: str
) -> list[dict[str, str]]:
    reported = completion.get("infrastructure_failure_receipts")
    if not isinstance(reported, list):
        raise ReviewBuildError(
            f"call infrastructure failure receipt inventory is malformed: {call_id}"
        )
    validated: list[dict[str, str]] = []
    for index, item in enumerate(reported, start=1):
        if not isinstance(item, dict) or set(item) != {"relative_path", "sha256"}:
            raise ReviewBuildError(
                f"call infrastructure failure receipt entry is malformed: {call_id}"
            )
        relative = item.get("relative_path")
        expected_relative = f"infrastructure-failures/{index:03d}/receipt.json"
        if not isinstance(relative, str) or relative != expected_relative:
            raise ReviewBuildError(f"call infrastructure failure receipt path drift: {call_id}")
        _safe_child(call_dir, relative)
        digest = _require_sha256(
            item.get("sha256"), f"call infrastructure failure receipt {call_id}/{relative}"
        )
        validated.append({"relative_path": relative, "sha256": digest})
    return validated


def _actual_infrastructure_failure_receipts(
    call_dir: Path,
    call_contract: dict[str, Any],
    call_contract_sha: str,
    call_id: str,
) -> list[dict[str, str]]:
    failures_dir = call_dir / "infrastructure-failures"
    if not failures_dir.exists():
        return []
    if not failures_dir.is_dir() or failures_dir.is_symlink():
        raise ReviewBuildError(f"unsafe call infrastructure failure directory: {call_id}")
    directories = sorted(failures_dir.iterdir(), key=lambda path: path.name)
    expected_names = [f"{number:03d}" for number in range(1, len(directories) + 1)]
    if [path.name for path in directories] != expected_names or any(
        not path.is_dir() or path.is_symlink() for path in directories
    ):
        raise ReviewBuildError(f"call infrastructure failure receipt directory drift: {call_id}")
    inventory: list[dict[str, str]] = []
    for failure_number, directory in enumerate(directories, start=1):
        children = list(directory.iterdir())
        if (
            len(children) != 1
            or children[0].name != "receipt.json"
            or not children[0].is_file()
            or children[0].is_symlink()
        ):
            raise ReviewBuildError(
                f"call infrastructure failure receipt directory is incomplete: {call_id}"
            )
        receipt_path = children[0]
        receipt = _read_object(
            receipt_path,
            f"call infrastructure failure receipt {call_id}/{failure_number:03d}",
        )
        if (
            set(receipt) != INFRASTRUCTURE_FAILURE_RECEIPT_KEYS
            or receipt.get("schema_version") != "1"
            or receipt.get("experiment_id") != call_contract.get("experiment_id")
            or receipt.get("experiment_contract_sha256")
            != call_contract.get("experiment_contract_sha256")
            or receipt.get("call_id") != call_id
            or receipt.get("pipeline_id") != call_contract.get("pipeline_id")
            or receipt.get("stage") != call_contract.get("stage")
            or receipt.get("failure_number") != failure_number
            or receipt.get("call_contract_sha256") != call_contract_sha
            or receipt.get("model_started") is not False
            or receipt.get("model_attempt_consumed") is not False
        ):
            raise ReviewBuildError(f"call infrastructure failure receipt identity drift: {call_id}")
        relative = f"infrastructure-failures/{failure_number:03d}/receipt.json"
        inventory.append({"relative_path": relative, "sha256": _sha256_path(receipt_path)})
    return inventory


def _verify_call(
    experiment_dir: Path,
    manifest: dict[str, Any],
    contract_sha256: str,
    pipeline_id: str,
    call_id: str,
) -> str:
    call_dir = _safe_child(experiment_dir, f"calls/{call_id}")
    completion = _read_object(call_dir / "complete.json", f"call receipt {call_id}")
    expected_keys = {
        "schema_version",
        "call_id",
        "call_contract_sha256",
        "successful_attempt",
        "successful_attempt_contract_sha256",
        "artifact_sha256",
        "infrastructure_failure_receipts",
    }
    if set(completion) != expected_keys or completion.get("call_id") != call_id:
        raise ReviewBuildError(f"call completion receipt shape drift: {call_id}")
    call_contract_path = call_dir / "call-contract.json"
    call_contract = _read_object(call_contract_path, f"call contract {call_id}")
    if (
        call_contract.get("experiment_contract_sha256") != contract_sha256
        or call_contract.get("pipeline_id") != pipeline_id
        or call_contract.get("call_id") != call_id
    ):
        raise ReviewBuildError(f"call contract identity drift: {call_id}")
    immutable_model = manifest.get("immutable_contract", {}).get("model")
    if call_contract.get("model") != immutable_model:
        raise ReviewBuildError(f"call execution contract drift: {call_id}")
    call_contract_sha = _sha256_path(call_contract_path)
    if completion.get("call_contract_sha256") != call_contract_sha:
        raise ReviewBuildError(f"call contract hash drift: {call_id}")
    reported_infrastructure_receipts = _reported_infrastructure_failure_receipts(
        call_dir, completion, call_id
    )
    actual_infrastructure_receipts = _actual_infrastructure_failure_receipts(
        call_dir,
        call_contract,
        call_contract_sha,
        call_id,
    )
    if reported_infrastructure_receipts != actual_infrastructure_receipts:
        raise ReviewBuildError(f"call infrastructure failure receipt inventory drift: {call_id}")

    schema_relative = call_contract.get("schema_relative_path")
    if not isinstance(schema_relative, str):
        raise ReviewBuildError(f"call schema path is missing: {call_id}")
    schema_path, schema_sha = _artifact_record(manifest, experiment_dir, schema_relative)
    if call_contract.get("schema_sha256") != schema_sha or _sha256_path(schema_path) != schema_sha:
        raise ReviewBuildError(f"call schema receipt drift: {call_id}")

    attempt_number = completion.get("successful_attempt")
    if (
        not isinstance(attempt_number, int)
        or isinstance(attempt_number, bool)
        or attempt_number < 1
    ):
        raise ReviewBuildError(f"call attempt receipt is invalid: {call_id}")
    attempt_path = _safe_child(call_dir, f"attempts/{attempt_number:03d}/attempt-contract.json")
    if not attempt_path.is_file() or attempt_path.is_symlink():
        raise ReviewBuildError(f"successful call attempt is missing: {call_id}")
    if completion.get("successful_attempt_contract_sha256") != _sha256_path(attempt_path):
        raise ReviewBuildError(f"successful call attempt hash drift: {call_id}")

    artifact_hashes = completion.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != CALL_ARTIFACTS:
        raise ReviewBuildError(f"call artifact receipt is incomplete: {call_id}")
    for relative, digest in artifact_hashes.items():
        expected_sha = _require_sha256(digest, f"call artifact {call_id}/{relative}")
        path = _safe_child(call_dir, relative)
        if not path.is_file() or path.is_symlink() or _sha256_path(path) != expected_sha:
            raise ReviewBuildError(f"call artifact hash drift: {call_id}/{relative}")
    return _sha256_path(call_dir / "complete.json")


def _verify_pipeline(
    experiment_dir: Path,
    manifest: dict[str, Any],
    planned: PlannedPipeline,
    input_sha256: str,
) -> tuple[VerifiedPipeline, set[str]]:
    pipeline_dir = _safe_child(experiment_dir, f"pipelines/{planned.pipeline_id}")
    contract_path = pipeline_dir / "pipeline-contract.json"
    contract = _read_object(contract_path, f"pipeline contract {planned.pipeline_id}")
    contract_sha = manifest["contract_sha256"]
    if (
        contract.get("experiment_contract_sha256") != contract_sha
        or contract.get("pipeline_id") != planned.pipeline_id
        or contract.get("source_id") != planned.source_id
        or contract.get("repeat") != planned.repeat
        or contract.get("arm_id") != planned.arm_id
        or contract.get("input_sha256") != input_sha256
        or contract.get("fresh_generation") is not True
    ):
        raise ReviewBuildError(f"pipeline contract identity drift: {planned.pipeline_id}")
    skill_version = contract.get("skill_version")
    if skill_version not in {"v1", "v2"}:
        raise ReviewBuildError(f"unknown pipeline contract version: {planned.pipeline_id}")

    completion = _read_object(
        pipeline_dir / "complete.json", f"pipeline receipt {planned.pipeline_id}"
    )
    expected_keys = {
        "schema_version",
        "pipeline_id",
        "pipeline_contract_sha256",
        "artifact_sha256",
        "call_receipts",
    }
    if set(completion) != expected_keys or completion.get("pipeline_id") != planned.pipeline_id:
        raise ReviewBuildError(f"pipeline completion receipt shape drift: {planned.pipeline_id}")
    if completion.get("pipeline_contract_sha256") != _sha256_path(contract_path):
        raise ReviewBuildError(f"pipeline contract hash drift: {planned.pipeline_id}")

    expected_artifacts = set(COMMON_PIPELINE_ARTIFACTS)
    if skill_version == "v2":
        expected_artifacts.update(V2_PIPELINE_ARTIFACTS)
    artifact_hashes = completion.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != expected_artifacts:
        raise ReviewBuildError(f"pipeline artifact receipt is incomplete: {planned.pipeline_id}")
    for relative, digest in artifact_hashes.items():
        expected_sha = _require_sha256(
            digest, f"pipeline artifact {planned.pipeline_id}/{relative}"
        )
        path = _safe_child(pipeline_dir, relative)
        if not path.is_file() or path.is_symlink() or _sha256_path(path) != expected_sha:
            raise ReviewBuildError(
                f"pipeline artifact hash drift: {planned.pipeline_id}/{relative}"
            )

    summary = _read_object(pipeline_dir / "summary.json", f"pipeline summary {planned.pipeline_id}")
    if (
        summary.get("pipeline_id") != planned.pipeline_id
        or summary.get("source_id") != planned.source_id
        or summary.get("repeat") != planned.repeat
        or summary.get("arm_id") != planned.arm_id
    ):
        raise ReviewBuildError(f"pipeline summary identity drift: {planned.pipeline_id}")
    expected_call_ids = _expected_call_ids(contract, summary)
    receipts = completion.get("call_receipts")
    if not isinstance(receipts, list):
        raise ReviewBuildError(f"pipeline call receipts are malformed: {planned.pipeline_id}")
    verified_receipts = []
    for call_id in expected_call_ids:
        verified_receipts.append(
            {
                "call_id": call_id,
                "call_completion_sha256": _verify_call(
                    experiment_dir,
                    manifest,
                    contract_sha,
                    planned.pipeline_id,
                    call_id,
                ),
            }
        )
    if receipts != verified_receipts:
        raise ReviewBuildError(f"pipeline call receipt drift: {planned.pipeline_id}")

    result_path = pipeline_dir / "result.json"
    result = _read_object(result_path, f"pipeline result {planned.pipeline_id}")
    return (
        VerifiedPipeline(
            pipeline_id=planned.pipeline_id,
            source_id=planned.source_id,
            repeat=planned.repeat,
            arm_id=planned.arm_id,
            skill_version=skill_version,
            result=result,
            result_sha256=_sha256_path(result_path),
            completion_sha256=_sha256_path(pipeline_dir / "complete.json"),
        ),
        set(expected_call_ids),
    )


def _verify_formal_experiment(
    experiment_dir: Path,
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, Any]],
    list[VerifiedPipeline],
    str,
    set[str],
    set[str],
]:
    if not experiment_dir.is_dir() or experiment_dir.is_symlink():
        raise ReviewBuildError(f"experiment directory is missing or unsafe: {experiment_dir}")
    experiment_dir = experiment_dir.resolve(strict=True)
    manifest, public_plan, source_contracts = _load_public_contract(experiment_dir)
    planned = _planned_pipelines(public_plan)
    sources, input_hashes = _load_sources(manifest, experiment_dir, source_contracts, planned)

    pipelines_root = _safe_child(experiment_dir, "pipelines")
    if not pipelines_root.is_dir() or pipelines_root.is_symlink():
        raise ReviewBuildError("formal experiment has no completed pipeline directory")
    actual_pipeline_ids = {
        child.name
        for child in pipelines_root.iterdir()
        if child.is_dir() and not child.is_symlink()
    }
    if actual_pipeline_ids != set(planned):
        missing = sorted(set(planned) - actual_pipeline_ids)
        extra = sorted(actual_pipeline_ids - set(planned))
        raise ReviewBuildError(
            "formal experiment pipeline set is incomplete or drifted; "
            f"missing={missing}, extra={extra}"
        )

    verified: list[VerifiedPipeline] = []
    expected_call_ids: set[str] = set()
    for pipeline_id in sorted(planned):
        value, call_ids = _verify_pipeline(
            experiment_dir,
            manifest,
            planned[pipeline_id],
            input_hashes[planned[pipeline_id].source_id],
        )
        verified.append(value)
        if expected_call_ids & call_ids:
            raise ReviewBuildError("a call receipt is shared by multiple pipelines")
        expected_call_ids.update(call_ids)

    actual_call_ids = {
        child.name
        for child in _safe_child(experiment_dir, "calls").iterdir()
        if child.is_dir() and not child.is_symlink()
    }
    if actual_call_ids != expected_call_ids:
        raise ReviewBuildError("formal experiment call set is incomplete or drifted")

    block_versions: dict[tuple[str, int], list[str]] = defaultdict(list)
    source_counts: Counter[str] = Counter()
    for item in verified:
        block_versions[(item.source_id, item.repeat)].append(item.skill_version)
        source_counts[item.source_id] += 1
    if any(sorted(versions) != ["v1", "v2"] for versions in block_versions.values()):
        raise ReviewBuildError("each source/repeat block must contain both frozen study arms")
    if set(source_counts) != set(sources) or any(count != 4 for count in source_counts.values()):
        raise ReviewBuildError("each source must contain exactly four completed outputs")

    verified_input_set = [
        {
            "pipeline_id": item.pipeline_id,
            "completion_sha256": item.completion_sha256,
            "result_sha256": item.result_sha256,
        }
        for item in sorted(verified, key=lambda value: value.pipeline_id)
    ]
    input_set_sha = _sha256_bytes(_canonical_bytes(verified_input_set))
    arm_ids = {item.arm_id for item in verified}
    return (
        manifest,
        sources,
        verified,
        input_set_sha,
        set(planned),
        arm_ids,
    )


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewBuildError(f"review field is missing: {label}")
    return value


def _optional_text(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ReviewBuildError(f"review field must be text: {label}")
    return value


def _blind_id(namespace: str, contract_sha: str, identity: str) -> str:
    digest = _sha256_bytes(f"{REVIEW_PROTOCOL}:{contract_sha}:{namespace}:{identity}".encode())
    return f"{namespace}_{digest[:16]}"


def _candidate_index(evidence: dict[str, Any], source_id: str) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for candidate in evidence["candidates"]:
        if not isinstance(candidate, dict):
            raise ReviewBuildError(f"candidate evidence is malformed: {source_id}")
        candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
        for field in ("source_start_ms", "source_end_ms"):
            value = candidate.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ReviewBuildError(f"candidate {candidate_id} has invalid {field}")
        if candidate["source_end_ms"] <= candidate["source_start_ms"]:
            raise ReviewBuildError(f"candidate {candidate_id} has invalid time bounds")
        _required_text(candidate.get("text"), f"{candidate_id}.text")
        _optional_text(candidate.get("context_before"), f"{candidate_id}.context_before")
        _optional_text(candidate.get("context_after"), f"{candidate_id}.context_after")
        values[candidate_id] = candidate
    return values


def _common_output(
    pipeline: VerifiedPipeline,
    evidence: dict[str, Any],
    contract_sha: str,
) -> dict[str, Any]:
    candidates = _candidate_index(evidence, pipeline.source_id)
    raw_highlights = pipeline.result.get("highlights")
    if not isinstance(raw_highlights, list):
        raise ReviewBuildError(f"pipeline result has no highlight list: {pipeline.pipeline_id}")
    highlights: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_highlights):
        if not isinstance(item, dict):
            raise ReviewBuildError(f"pipeline highlight is malformed: {pipeline.pipeline_id}")
        candidate_id = _required_text(item.get("candidate_id"), "highlight.candidate_id")
        if candidate_id not in candidates:
            raise ReviewBuildError(
                f"pipeline highlight references unknown candidate: {pipeline.pipeline_id}"
            )
        if candidate_id in seen_ids:
            raise ReviewBuildError(
                f"pipeline selects a candidate more than once: {pipeline.pipeline_id}"
            )
        seen_ids.add(candidate_id)
        candidate = candidates[candidate_id]
        key_sentence = item.get("edited_sentence", item.get("highlight_sentence"))
        risk_flags = item.get("risk_flags", [])
        if not isinstance(risk_flags, list) or not all(
            isinstance(flag, str) for flag in risk_flags
        ):
            raise ReviewBuildError(f"pipeline risk flags are malformed: {pipeline.pipeline_id}")
        highlights.append(
            {
                "position": index + 1,
                "candidate_id": candidate_id,
                "source_start_ms": candidate["source_start_ms"],
                "source_end_ms": candidate["source_end_ms"],
                "topic": _required_text(item.get("topic"), "highlight.topic"),
                "title": _required_text(item.get("title"), "highlight.title"),
                "hook": _required_text(item.get("hook"), "highlight.hook"),
                "key_sentence": _required_text(key_sentence, "highlight.key_sentence"),
                "script_description": _required_text(
                    item.get("script_description"), "highlight.script_description"
                ),
                "selection_reason": _required_text(
                    item.get("selection_reason"), "highlight.selection_reason"
                ),
                "risk_flags": list(risk_flags),
            }
        )
    return {
        "output_id": _blind_id("output", contract_sha, pipeline.pipeline_id),
        "selection_summary": _required_text(
            pipeline.result.get("selection_summary"), "selection_summary"
        ),
        "highlights": highlights,
    }


def _candidate_evidence(evidence: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    candidates = _candidate_index(evidence, source_id)
    result = []
    for candidate in evidence["candidates"]:
        candidate_id = candidate["candidate_id"]
        assert candidate_id in candidates
        result.append(
            {
                "candidate_id": candidate_id,
                "source_start_ms": candidate["source_start_ms"],
                "source_end_ms": candidate["source_end_ms"],
                "text": candidate["text"],
                "context_before": candidate.get("context_before", ""),
                "context_after": candidate.get("context_after", ""),
            }
        )
    return result


def _assert_review_anonymity(
    review: dict[str, Any],
    pipeline_ids: set[str],
    arm_ids: set[str],
    immutable_contract: dict[str, Any],
) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            forbidden = set(value) & SENSITIVE_REVIEW_KEYS
            if forbidden:
                raise ReviewBuildError(
                    f"review projection leaked sensitive fields: {sorted(forbidden)}"
                )
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(review)
    encoded = _canonical_bytes(review).decode("utf-8")
    leaked_ids = sorted(
        identifier for identifier in pipeline_ids | arm_ids if identifier in encoded
    )
    if leaked_ids:
        raise ReviewBuildError("review projection leaked an execution identity")
    model = immutable_contract.get("model")
    if isinstance(model, dict):
        model_name = model.get("model")
        if isinstance(model_name, str) and model_name and model_name in encoded:
            raise ReviewBuildError("review projection leaked the execution model")


def _build_review_data(
    manifest: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    pipelines: list[VerifiedPipeline],
    input_set_sha256: str,
    pipeline_ids: set[str],
    arm_ids: set[str],
) -> dict[str, Any]:
    contract_sha = manifest["contract_sha256"]
    pipelines_by_source: dict[str, list[VerifiedPipeline]] = defaultdict(list)
    for pipeline in pipelines:
        pipelines_by_source[pipeline.source_id].append(pipeline)
    source_order = sorted(
        sources,
        key=lambda source_id: _blind_id("source", contract_sha, source_id),
    )
    review_sources = []
    for source_id in source_order:
        evidence = sources[source_id]
        source_meta = evidence["source"]
        outputs = [
            _common_output(pipeline, evidence, contract_sha)
            for pipeline in pipelines_by_source[source_id]
        ]
        outputs.sort(key=lambda item: item["output_id"])
        if len(outputs) != 4:
            raise ReviewBuildError(f"source does not contain four blind outputs: {source_id}")
        review_sources.append(
            {
                "source_id": _blind_id("source", contract_sha, source_id),
                "source_filename": _optional_text(source_meta.get("filename"), "source.filename"),
                "duration_ms": source_meta.get("duration_ms"),
                "candidate_evidence": _candidate_evidence(evidence, source_id),
                "outputs": outputs,
            }
        )
    review = {
        "schema_version": "1",
        "review_protocol": REVIEW_PROTOCOL,
        "review_id": _blind_id("review", contract_sha, input_set_sha256),
        "experiment_contract_sha256": contract_sha,
        "verified_input_set_sha256": input_set_sha256,
        "source_count": len(review_sources),
        "pipeline_count": len(pipelines),
        "instructions": (
            "按来源逐一比较四个匿名输出。只评价内容发现、证据忠实、完整性、重复控制与编辑价值；"
            "不要猜测输出来自哪个执行方案。"
        ),
        "sources": review_sources,
    }
    _assert_review_anonymity(
        review,
        pipeline_ids,
        arm_ids,
        manifest["immutable_contract"],
    )
    return review


def _review_html(review: dict[str, Any]) -> str:
    embedded = json.dumps(review, ensure_ascii=False, separators=(",", ":"))
    embedded = (
        embedded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    template = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LiveClip 匿名高光评审</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#667085; --line:#d7dee8;
      --paper:#fff; --canvas:#f4f6f9; --brand:#2457d6; --soft:#eef3ff; }
    * { box-sizing:border-box; }
    body { margin:0; font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC",
      "Microsoft YaHei",sans-serif; color:var(--ink); background:var(--canvas); }
    header { position:sticky; top:0; z-index:5; padding:16px 22px; background:#101828;
      color:white; box-shadow:0 2px 10px #10182833; }
    header h1 { margin:0 0 4px; font-size:20px; }
    header p { margin:0; color:#d0d5dd; }
    main { padding:18px; }
    .source { margin:0 0 28px; }
    .source-head { display:flex; gap:12px; align-items:baseline; margin-bottom:12px; }
    .source-head h2 { margin:0; font-size:19px; }
    .muted { color:var(--muted); }
    .outputs { display:grid; grid-template-columns:repeat(4,minmax(330px,1fr)); gap:14px;
      overflow-x:auto; align-items:start; padding-bottom:8px; }
    .output { min-width:330px; padding:14px; background:var(--paper); border:1px solid var(--line);
      border-radius:12px; box-shadow:0 2px 8px #1018280d; }
    .output h3 { margin:0 0 8px; font-size:16px; color:var(--brand); }
    .summary { min-height:66px; margin:0 0 12px; padding:10px; background:var(--soft);
      border-radius:8px; }
    .highlight { margin:0 0 12px; padding:11px; border:1px solid var(--line);
      border-radius:9px; }
    .highlight h4 { margin:0 0 8px; font-size:15px; }
    .field { margin:5px 0; white-space:pre-wrap; overflow-wrap:anywhere; }
    .field b { color:#344054; }
    details { margin-top:8px; }
    details pre { white-space:pre-wrap; overflow-wrap:anywhere; margin:8px 0 0; padding:9px;
      background:#f8fafc; border-radius:7px; font:13px/1.5 inherit; }
    textarea { width:100%; min-height:100px; margin-top:8px; padding:9px; resize:vertical;
      border:1px solid #98a2b3; border-radius:7px; font:inherit; }
    .evidence-index { margin-top:14px; padding:12px; background:var(--paper);
      border:1px solid var(--line); border-radius:10px; }
    .evidence-row { padding:8px 0; border-top:1px solid #eaecf0; }
    .evidence-row:first-of-type { border-top:0; }
    .toolbar { position:fixed; right:20px; bottom:20px; z-index:10; }
    button { border:0; border-radius:999px; padding:11px 18px; background:var(--brand);
      color:white; font-weight:650; cursor:pointer; box-shadow:0 4px 14px #2457d644; }
    @media (max-width:900px) { main { padding:12px; } header { position:static; }
      .outputs { grid-template-columns:repeat(4,minmax(300px,1fr)); } }
  </style>
</head>
<body>
  <header><h1>LiveClip 匿名高光评审</h1><p id="instructions"></p></header>
  <main id="app"></main>
  <div class="toolbar"><button id="export" type="button">导出评审反馈</button></div>
  <script id="review-data" type="application/json">__REVIEW_DATA__</script>
  <script>
    "use strict";
    const data = JSON.parse(document.getElementById("review-data").textContent);
    const app = document.getElementById("app");
    document.getElementById("instructions").textContent = data.instructions;
    const node = (tag, cls, text) => {
      const value = document.createElement(tag);
      if (cls) value.className = cls;
      if (text !== undefined) value.textContent = text;
      return value;
    };
    const addField = (root, label, value) => {
      const row = node("div", "field");
      const name = node("b", "", label + "：");
      row.append(name, document.createTextNode(Array.isArray(value) ? value.join("、") : value));
      root.appendChild(row);
    };
    for (const [sourceIndex, source] of data.sources.entries()) {
      const section = node("section", "source");
      const head = node("div", "source-head");
      head.append(node("h2", "", `来源 ${sourceIndex + 1}`));
      head.append(node("span", "muted", `${source.source_filename || source.source_id} · ` +
        `${(source.duration_ms / 60000).toFixed(1)} 分钟`));
      section.appendChild(head);
      const evidence = new Map(source.candidate_evidence.map(item => [item.candidate_id, item]));
      const grid = node("div", "outputs");
      for (const output of source.outputs) {
        const card = node("article", "output");
        card.append(node("h3", "", output.output_id));
        card.append(node("p", "summary", output.selection_summary));
        for (const highlight of output.highlights) {
          const item = node("section", "highlight");
          item.append(node("h4", "", `${highlight.position}. ${highlight.title}`));
          addField(item, "Topic", highlight.topic);
          addField(item, "Hook", highlight.hook);
          addField(item, "高光语句", highlight.key_sentence);
          addField(item, "内容描述", highlight.script_description);
          addField(item, "选择理由", highlight.selection_reason);
          addField(item, "风险标记", highlight.risk_flags.length ? highlight.risk_flags : "无");
          const proof = evidence.get(highlight.candidate_id);
          const details = node("details");
          details.append(node("summary", "", `候选证据 · ${highlight.candidate_id}`));
          const pre = node("pre");
          pre.textContent = `范围：${proof.source_start_ms}–${proof.source_end_ms} ms\n\n` +
            `正文：${proof.text}\n\n前文：${proof.context_before || "（无）"}\n\n` +
            `后文：${proof.context_after || "（无）"}`;
          details.appendChild(pre);
          item.appendChild(details);
          card.appendChild(item);
        }
        const label = node("label", "field", "评审意见（自动保存在本浏览器）");
        const textarea = node("textarea");
        const storageKey = `${data.review_id}:${output.output_id}`;
        textarea.value = localStorage.getItem(storageKey) || "";
        textarea.dataset.outputId = output.output_id;
        textarea.addEventListener("input", () => localStorage.setItem(storageKey, textarea.value));
        label.appendChild(textarea);
        card.appendChild(label);
        grid.appendChild(card);
      }
      section.appendChild(grid);
      const catalogue = node("details", "evidence-index");
      catalogue.append(node(
        "summary", "", `全部冻结候选证据（${source.candidate_evidence.length}）`
      ));
      for (const item of source.candidate_evidence) {
        const row = node("div", "evidence-row");
        addField(row, item.candidate_id, item.text);
        catalogue.appendChild(row);
      }
      section.appendChild(catalogue);
      app.appendChild(section);
    }
    document.getElementById("export").addEventListener("click", () => {
      const reviews = [...document.querySelectorAll("textarea[data-output-id]")].map(area => ({
        output_id: area.dataset.outputId,
        feedback: area.value
      }));
      const payload = { schema_version:"1", review_id:data.review_id, reviews };
      const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {type:"application/json"});
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "feedback.json";
      link.click();
      URL.revokeObjectURL(link.href);
    });
  </script>
</body>
</html>
"""
    return template.replace("__REVIEW_DATA__", embedded)


def _write_synced(path: Path, content: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _publish_iteration(
    output_root: Path,
    iteration_name: str,
    review: dict[str, Any],
) -> Path:
    if ITERATION_NAME_RE.fullmatch(iteration_name) is None:
        raise ReviewBuildError("iteration name must be a safe 1-64 character component")
    output_root = output_root.resolve(strict=False)
    output_root.mkdir(parents=True, exist_ok=True)
    if output_root.is_symlink():
        raise ReviewBuildError(f"review output root cannot be a symlink: {output_root}")
    target = output_root / iteration_name
    if target.exists() or target.is_symlink():
        raise ReviewBuildError(f"review iteration already exists; refusing overwrite: {target}")
    reservation = output_root / f".{iteration_name}.reserve"
    try:
        reservation_handle = reservation.open("xb")
    except FileExistsError as exc:
        raise ReviewBuildError(
            f"review iteration is already being built: {iteration_name}"
        ) from exc
    temporary: Path | None = None
    try:
        reservation_handle.close()
        temporary = Path(tempfile.mkdtemp(prefix=f".{iteration_name}-", dir=str(output_root)))
        review_bytes = _pretty_bytes(review)
        html_bytes = _review_html(review).encode("utf-8")
        receipt = {
            "schema_version": "1",
            "review_protocol": REVIEW_PROTOCOL,
            "review_id": review["review_id"],
            "experiment_contract_sha256": review["experiment_contract_sha256"],
            "verified_input_set_sha256": review["verified_input_set_sha256"],
            "verified_source_count": review["source_count"],
            "verified_pipeline_count": review["pipeline_count"],
            "anonymous_projection": True,
            "artifact_sha256": {
                "review.html": _sha256_bytes(html_bytes),
                "review.json": _sha256_bytes(review_bytes),
            },
        }
        _write_synced(temporary / "review.json", review_bytes)
        _write_synced(temporary / "review.html", html_bytes)
        _write_synced(temporary / "build-receipt.json", _pretty_bytes(receipt))
        if target.exists() or target.is_symlink():
            raise ReviewBuildError(f"review iteration appeared during build: {target}")
        temporary.rename(target)
        temporary = None
        return target
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        reservation.unlink(missing_ok=True)


def build_review(
    experiment_dir: Path,
    output_root: Path,
    *,
    iteration_name: str = "iteration-1",
) -> Path:
    """Verify all formal outputs and atomically publish a blind static review."""

    (
        manifest,
        sources,
        pipelines,
        input_set_sha,
        pipeline_ids,
        arm_ids,
    ) = _verify_formal_experiment(experiment_dir)
    if len(pipelines) != EXPECTED_PIPELINE_COUNT:
        raise ReviewBuildError("all 12 final pipeline outputs are required before review")
    review = _build_review_data(
        manifest,
        sources,
        pipelines,
        input_set_sha,
        pipeline_ids,
        arm_ids,
    )
    return _publish_iteration(output_root, iteration_name, review)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the complete formal experiment and build an offline blind viewer."
    )
    parser.add_argument("experiment_dir", type=Path, help="formal experiment directory")
    parser.add_argument("--output-root", required=True, type=Path, help="review parent directory")
    parser.add_argument(
        "--iteration-name",
        default="iteration-1",
        help="new immutable review directory name (default: iteration-1)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_review(
            args.experiment_dir,
            args.output_root,
            iteration_name=args.iteration_name,
        )
    except ReviewBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(result.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
