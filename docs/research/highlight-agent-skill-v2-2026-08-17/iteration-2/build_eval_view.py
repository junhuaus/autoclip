#!/usr/bin/env python3
# ruff: noqa: E501, RUF001
"""Build the immutable iteration-2 blind viewer and feedback commitment.

The viewer reads only public, hash-bound generator evidence.  It retains every
source, output, and highlight's original position while replacing execution
identities with deterministic blind IDs.  The review artifacts bind the frozen
evaluation-contract and verified generator input set.  Required feedback can be
committed only after an exact schema/inventory/complete check; the current
``diagnostic_not_required`` study instead binds its pre-frozen waiver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

ITERATION_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = ITERATION_DIR.parents[3]
EVALUATION_CONTRACT_PATH = ITERATION_DIR / "evaluation-contract.json"
ITERATION_REPO_PREFIX = "docs/research/highlight-agent-skill-v2-2026-08-17/iteration-2"
JUDGE_HARNESS_ARTIFACT = f"{ITERATION_REPO_PREFIX}/run_judges.py"
REVIEW_PROTOCOL = "liveclip-highlight-source-first-blind-review.iteration-2.v1"
REVIEW_SCHEMA_VERSION = "2"
FEEDBACK_SCHEMA_VERSION = "liveclip-highlight-feedback.iteration-2.v1"
EXPECTED_SOURCE_COUNT = 3
EXPECTED_PIPELINE_COUNT = 12
EXPECTED_REPEATS_PER_SOURCE = 2
ITERATION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SENSITIVE_REVIEW_KEYS = {
    "arm_id",
    "pipeline_id",
    "repeat",
    "skill_version",
    "model",
    "reasoning_effort",
    "usage",
    "elapsed_seconds",
    "quality_score_x100",
    "scores",
    "rank",
}
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


class ReviewBuildError(RuntimeError):
    """The formal experiment cannot safely produce a review artifact."""


@dataclass(frozen=True)
class VerifiedPipeline:
    pipeline_id: str
    source_id: str
    public_position: int
    result: dict[str, Any]
    result_sha256: str
    completion_sha256: str


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ReviewBuildError(message)


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


def _verify_repository_artifact_index(
    evaluation: Mapping[str, Any],
) -> dict[str, bytes]:
    """Read every indexed artifact once and return its hash-verified bytes."""

    artifacts = evaluation.get("artifacts")
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
        raise ReviewBuildError("repository root cannot be resolved") from exc
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
            raise ReviewBuildError(
                f"evaluation artifact is missing or escapes: {relative}"
            ) from exc
        _expect(stat.S_ISREG(mode), f"evaluation artifact is not a regular file: {relative}")
        try:
            content = candidate.read_bytes()
        except OSError as exc:
            raise ReviewBuildError(f"evaluation artifact is unreadable: {relative}") from exc
        _expect(len(content) == expected_size, f"artifact size drifted: {relative}")
        _expect(_sha256_bytes(content) == expected_sha, f"artifact hash drifted: {relative}")
        verified[relative] = content
    return verified


def _read_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReviewBuildError(f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewBuildError(f"invalid JSON {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ReviewBuildError(f"{label} must be a JSON object")
    return value


def _expect_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    _expect(
        actual == expected,
        f"{label} keys differ; missing={sorted(expected - actual)}, "
        f"extra={sorted(actual - expected)}",
    )


def _load_evaluation_contract(
    experiment_dir: Path,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, bytes]]:
    repository_path = EVALUATION_CONTRACT_PATH
    frozen_path = experiment_dir / "frozen" / "evaluation-contract.json"
    if not repository_path.is_file() or repository_path.is_symlink():
        raise ReviewBuildError("repository evaluation contract is missing")
    if not frozen_path.is_file() or frozen_path.is_symlink():
        raise ReviewBuildError("frozen evaluation contract is missing")
    raw = repository_path.read_bytes()
    _expect(frozen_path.read_bytes() == raw, "frozen evaluation contract byte drift")
    try:
        evaluation = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewBuildError("invalid JSON evaluation contract") from exc
    _expect(isinstance(evaluation, dict), "evaluation contract must be a JSON object")
    _expect(
        set(evaluation) >= EVALUATION_CONTRACT_KEYS,
        "evaluation contract is missing required fields: "
        + str(sorted(EVALUATION_CONTRACT_KEYS - set(evaluation))),
    )
    _expect(
        evaluation["schema_version"] == "liveclip-highlight-evaluation-contract.iteration-2.v1",
        "wrong evaluation schema version",
    )
    _expect(
        evaluation["contract_version"] == "highlight-agent-skill-v2-iteration-2-evaluation-v1",
        "wrong evaluation contract version",
    )
    _expect(
        evaluation["iteration_id"] == "highlight-agent-skill-v2-iteration-2",
        "wrong evaluation iteration",
    )
    _expect(
        evaluation["status"] == "frozen_before_any_iteration2_generator_output",
        "evaluation contract is not pre-output frozen",
    )
    _expect(
        evaluation["human_review_mode"] in {"required", "diagnostic_not_required"},
        "unsupported human review mode",
    )
    verified_artifacts = _verify_repository_artifact_index(evaluation)
    manifest = _read_object(experiment_dir / "experiment-manifest.json", "experiment manifest")
    immutable = manifest.get("immutable_contract")
    _expect(isinstance(immutable, dict), "experiment immutable contract is missing")
    evaluation_sha = _sha256_bytes(raw)
    _expect(
        manifest.get("contract_sha256") == _sha256_bytes(_canonical_bytes(immutable)),
        "experiment immutable contract hash drifted",
    )
    _expect(
        immutable.get("evaluation_contract_sha256") == evaluation_sha,
        "experiment is not bound to the evaluation contract",
    )
    artifact_index = manifest.get("artifact_index")
    _expect(isinstance(artifact_index, dict), "experiment artifact index is missing")
    record = artifact_index.get("frozen/evaluation-contract.json")
    _expect(
        isinstance(record, dict)
        and set(record) == {"sha256", "size_bytes"}
        and record.get("sha256") == evaluation_sha
        and record.get("size_bytes") == len(raw),
        "indexed evaluation contract hash drifted",
    )
    return evaluation, evaluation_sha, manifest, verified_artifacts


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


def _load_pinned_judge_harness(
    verified_artifacts: Mapping[str, bytes],
) -> ModuleType:
    """Load Judge only from the already-read frozen snapshot."""

    try:
        source_bytes = verified_artifacts[JUDGE_HARNESS_ARTIFACT]
        digest = _sha256_bytes(source_bytes)
        return _verified_python_module(
            module_name=f"liveclip_viewer_judge_{digest}",
            source_path=REPOSITORY_ROOT / JUDGE_HARNESS_ARTIFACT,
            source_bytes=source_bytes,
        )
    except Exception as exc:
        raise ReviewBuildError("could not load frozen Viewer dependency") from exc


def _verify_formal_experiment(
    experiment_dir: Path,
) -> tuple[
    dict[str, Any],
    str,
    dict[str, dict[str, Any]],
    list[VerifiedPipeline],
    str,
    dict[str, int],
]:
    if not experiment_dir.is_dir() or experiment_dir.is_symlink():
        raise ReviewBuildError(f"unsafe experiment directory: {experiment_dir}")
    experiment_dir = experiment_dir.resolve(strict=True)
    evaluation, evaluation_sha, _manifest, verified_artifacts = _load_evaluation_contract(
        experiment_dir
    )
    judge_harness = _load_pinned_judge_harness(verified_artifacts)
    try:
        evaluation_materials = judge_harness._load_evaluation_materials()
    except judge_harness.IntegrityError as exc:
        raise ReviewBuildError(str(exc)) from exc
    _expect(
        evaluation_materials.contract_sha256 == evaluation_sha
        and evaluation_materials.contract == evaluation,
        "Viewer and Judge evaluation materials differ",
    )
    try:
        _experiment_id, bundles = judge_harness._load_source_bundles(
            experiment_dir,
            evaluation_materials,
        )
    except (judge_harness.GeneratorMatrixIncomplete, judge_harness.IntegrityError) as exc:
        raise ReviewBuildError(str(exc)) from exc
    _expect(len(bundles) == EXPECTED_SOURCE_COUNT, "formal viewer requires three sources")
    source_positions = {bundle.source_id: bundle.source_public_position for bundle in bundles}
    _expect(
        set(source_positions.values()) == set(range(1, EXPECTED_SOURCE_COUNT + 1)),
        "verified source public positions drifted",
    )
    pipeline_positions: dict[str, int] = {}
    for bundle in bundles:
        positions = bundle.pipeline_public_positions
        _expect(
            isinstance(positions, dict)
            and set(positions) == set(bundle.pipeline_ids)
            and set(positions.values()) == {1, 2, 3, 4},
            f"verified pipeline public positions drifted: {bundle.source_id}",
        )
        _expect(
            not (set(pipeline_positions) & set(positions)),
            "duplicate verified public pipeline ID",
        )
        pipeline_positions.update(positions)
    pipeline_ids = {pipeline for bundle in bundles for pipeline in bundle.pipeline_ids}
    _expect(pipeline_ids == set(pipeline_positions), "verified/public pipeline inventory drifted")

    sources: dict[str, dict[str, Any]] = {}
    pipelines: list[VerifiedPipeline] = []
    input_records: list[dict[str, Any]] = []
    arm_repeat_inventory: Counter[tuple[str, str, int]] = Counter()
    source_sha_values: set[str] = set()
    for bundle in bundles:
        sources[bundle.source_id] = dict(bundle.source_payload)
        source_sha = bundle.source_payload.get("source", {}).get("source_sha256")
        _expect(isinstance(source_sha, str) and len(source_sha) == 64, "source SHA missing")
        source_sha_values.add(source_sha)
        for pipeline_id in bundle.pipeline_ids:
            result = bundle.results_by_pipeline.get(pipeline_id)
            metadata = bundle.pipeline_public_metadata.get(pipeline_id)
            result_sha = bundle.pipeline_result_sha256.get(pipeline_id)
            completion_sha = bundle.pipeline_completion_sha256.get(pipeline_id)
            _expect(
                isinstance(result, dict)
                and isinstance(metadata, dict)
                and set(metadata) == {"skill_version", "repeat"}
                and isinstance(result_sha, str)
                and re.fullmatch(r"[a-f0-9]{64}", result_sha) is not None
                and result_sha == _sha256_bytes(_pretty_bytes(result))
                and isinstance(completion_sha, str)
                and re.fullmatch(r"[a-f0-9]{64}", completion_sha) is not None,
                "verified pipeline snapshot or digest drifted",
            )
            skill = metadata["skill_version"]
            repeat = metadata["repeat"]
            _expect(skill in {"v1", "v2"} and repeat in {1, 2}, "arm/repeat contract drifted")
            arm_repeat_inventory[(bundle.source_id, str(skill), int(repeat))] += 1
            pipelines.append(
                VerifiedPipeline(
                    pipeline_id=pipeline_id,
                    source_id=bundle.source_id,
                    public_position=pipeline_positions[pipeline_id],
                    result=dict(result),
                    result_sha256=result_sha,
                    completion_sha256=completion_sha,
                )
            )
            input_records.append(
                {
                    "pipeline_id": pipeline_id,
                    "completion_sha256": completion_sha,
                    "result_sha256": result_sha,
                }
            )
    _expect(len(source_sha_values) == 3, "viewer requires three unique source SHA-256 values")
    expected_inventory = {
        (source_id, skill, repeat)
        for source_id in sources
        for skill in ("v1", "v2")
        for repeat in (1, 2)
    }
    _expect(
        set(arm_repeat_inventory) == expected_inventory
        and all(value == 1 for value in arm_repeat_inventory.values()),
        "formal arm/repeat inventory drifted",
    )
    input_set_sha = _sha256_bytes(
        _canonical_bytes(sorted(input_records, key=lambda item: item["pipeline_id"]))
    )
    return evaluation, evaluation_sha, sources, pipelines, input_set_sha, source_positions


def _blind_id(namespace: str, evaluation_sha: str, identity: str) -> str:
    digest = _sha256_bytes(f"{REVIEW_PROTOCOL}:{evaluation_sha}:{namespace}:{identity}".encode())
    return f"{namespace}_{digest[:16]}"


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReviewBuildError(f"missing review text: {label}")
    return value


def _optional_text(value: Any, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ReviewBuildError(f"review field must be text: {label}")
    return value


def _candidate_evidence(evidence: Mapping[str, Any], source_id: str) -> list[dict[str, Any]]:
    raw = evidence.get("candidates")
    _expect(isinstance(raw, list), f"candidate evidence missing: {source_id}")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, candidate in enumerate(raw, start=1):
        _expect(isinstance(candidate, dict), "candidate evidence is malformed")
        candidate_id = _required_text(candidate.get("candidate_id"), "candidate_id")
        _expect(candidate_id not in seen, "duplicate candidate evidence")
        seen.add(candidate_id)
        result.append(
            {
                "original_position": index,
                "candidate_id": candidate_id,
                "source_start_ms": candidate.get("source_start_ms"),
                "source_end_ms": candidate.get("source_end_ms"),
                "text": _required_text(candidate.get("text"), f"{candidate_id}.text"),
                "context_before": _optional_text(
                    candidate.get("context_before"), f"{candidate_id}.context_before"
                ),
                "context_after": _optional_text(
                    candidate.get("context_after"), f"{candidate_id}.context_after"
                ),
            }
        )
    return result


def _project_output(
    pipeline: VerifiedPipeline,
    evidence: Mapping[str, Any],
    evaluation_sha: str,
) -> dict[str, Any]:
    candidate_index = {
        item["candidate_id"]: item for item in _candidate_evidence(evidence, pipeline.source_id)
    }
    highlights = pipeline.result.get("highlights")
    _expect(isinstance(highlights, list), "pipeline highlight list is missing")
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for original_position, highlight in enumerate(highlights, start=1):
        _expect(isinstance(highlight, dict), "pipeline highlight is malformed")
        candidate_id = _required_text(highlight.get("candidate_id"), "highlight candidate")
        _expect(candidate_id in candidate_index, "highlight references unknown candidate")
        _expect(candidate_id not in seen, "pipeline repeats a candidate")
        seen.add(candidate_id)
        sentence = highlight.get(
            "source_sentence", highlight.get("highlight_sentence", highlight.get("edited_sentence"))
        )
        risk_flags = highlight.get("risk_flags", [])
        _expect(
            isinstance(risk_flags, list) and all(isinstance(item, str) for item in risk_flags),
            "risk flags are malformed",
        )
        projected.append(
            {
                "original_position": original_position,
                "candidate_id": candidate_id,
                "source_start_ms": candidate_index[candidate_id]["source_start_ms"],
                "source_end_ms": candidate_index[candidate_id]["source_end_ms"],
                "topic": _required_text(highlight.get("topic"), "topic"),
                "title": _required_text(highlight.get("title"), "title"),
                "hook": _required_text(highlight.get("hook"), "hook"),
                "source_or_highlight_sentence": _required_text(sentence, "source sentence"),
                "script_description": _required_text(
                    highlight.get("script_description"), "script description"
                ),
                "selection_reason": _required_text(
                    highlight.get("selection_reason"), "selection reason"
                ),
                "risk_flags": list(risk_flags),
            }
        )
    return {
        "original_position": pipeline.public_position,
        "output_id": _blind_id("output", evaluation_sha, pipeline.pipeline_id),
        "selection_summary": _required_text(
            pipeline.result.get("selection_summary"), "selection summary"
        ),
        "highlights": projected,
    }


def _assert_anonymous(review: Mapping[str, Any], pipelines: Sequence[VerifiedPipeline]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            leaked = set(value) & SENSITIVE_REVIEW_KEYS
            _expect(not leaked, f"review leaked sensitive keys: {sorted(leaked)}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(review)
    encoded = _canonical_bytes(review).decode("utf-8")
    _expect(
        not any(item.pipeline_id in encoded for item in pipelines),
        "review leaked a pipeline identity",
    )


def _build_review_data(
    evaluation: Mapping[str, Any],
    evaluation_sha: str,
    sources: Mapping[str, dict[str, Any]],
    pipelines: Sequence[VerifiedPipeline],
    input_set_sha: str,
    source_positions: Mapping[str, int],
) -> dict[str, Any]:
    by_source: dict[str, list[VerifiedPipeline]] = defaultdict(list)
    for pipeline in pipelines:
        by_source[pipeline.source_id].append(pipeline)
    review_sources = []
    for source_id in sorted(sources, key=source_positions.__getitem__):
        evidence = sources[source_id]
        source = evidence.get("source")
        _expect(isinstance(source, dict), "source metadata is missing")
        outputs = [
            _project_output(pipeline, evidence, evaluation_sha)
            for pipeline in sorted(by_source[source_id], key=lambda item: item.public_position)
        ]
        _expect(len(outputs) == 4, "each source must contain four blind outputs")
        review_sources.append(
            {
                "original_position": source_positions[source_id],
                "source_id": _blind_id("source", evaluation_sha, source_id),
                "source_filename": _optional_text(source.get("filename"), "source filename"),
                "duration_ms": source.get("duration_ms"),
                "candidate_evidence": _candidate_evidence(evidence, source_id),
                "outputs": outputs,
            }
        )
    review = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "review_protocol": REVIEW_PROTOCOL,
        "review_id": _blind_id("review", evaluation_sha, input_set_sha),
        "evaluation_contract_sha256": evaluation_sha,
        "verified_input_set_sha256": input_set_sha,
        "human_review_mode": evaluation["human_review_mode"],
        "source_count": len(review_sources),
        "pipeline_count": len(pipelines),
        "instructions": (
            "按原始顺序比较匿名输出。只评价发现、证据、独立完整性、组合精度和编辑就绪度；"
            "不要猜测执行方案。"
        ),
        "sources": review_sources,
    }
    _assert_anonymous(review, pipelines)
    return review


def _feedback_inventory(review: Mapping[str, Any]) -> dict[str, Any]:
    items = [
        {
            "source_id": source["source_id"],
            "source_original_position": source["original_position"],
            "output_id": output["output_id"],
            "output_original_position": output["original_position"],
        }
        for source in review["sources"]
        for output in source["outputs"]
    ]
    return {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "review_id": review["review_id"],
        "evaluation_contract_sha256": review["evaluation_contract_sha256"],
        "verified_input_set_sha256": review["verified_input_set_sha256"],
        "expected_review_count": len(items),
        "items": items,
    }


def _feedback_schema(review: Mapping[str, Any], inventory: Mapping[str, Any]) -> dict[str, Any]:
    output_ids = [item["output_id"] for item in inventory["items"]]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": FEEDBACK_SCHEMA_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "status",
            "review_id",
            "evaluation_contract_sha256",
            "verified_input_set_sha256",
            "reviews",
        ],
        "properties": {
            "schema_version": {"const": FEEDBACK_SCHEMA_VERSION},
            "status": {"const": "complete"},
            "review_id": {"const": review["review_id"]},
            "evaluation_contract_sha256": {"const": review["evaluation_contract_sha256"]},
            "verified_input_set_sha256": {"const": review["verified_input_set_sha256"]},
            "reviews": {
                "type": "array",
                "minItems": len(output_ids),
                "maxItems": len(output_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "source_id",
                        "source_original_position",
                        "output_id",
                        "output_original_position",
                        "rating",
                        "feedback",
                    ],
                    "properties": {
                        "source_id": {"type": "string"},
                        "source_original_position": {"type": "integer", "minimum": 1},
                        "output_id": {"type": "string", "enum": output_ids},
                        "output_original_position": {"type": "integer", "minimum": 1},
                        "rating": {
                            "enum": ["preferred", "acceptable", "needs_revision", "unusable"]
                        },
                        "feedback": {"type": "string", "maxLength": 10000},
                    },
                },
            },
        },
    }


def _diagnostic_waiver_release(
    evaluation: Mapping[str, Any], evaluation_sha: str
) -> dict[str, Any]:
    _expect(
        evaluation["human_review_mode"] == "diagnostic_not_required",
        "diagnostic waiver requested for a feedback-required contract",
    )
    waiver = evaluation.get("human_feedback_waiver")
    _expect(isinstance(waiver, dict), "pre-frozen human feedback waiver is missing")
    _expect_keys(
        waiver,
        {"frozen_before_generator_output", "mode", "reason", "commitment_sha256"},
        "pre-frozen human feedback waiver",
    )
    payload = {key: waiver[key] for key in ("frozen_before_generator_output", "mode", "reason")}
    digest = waiver["commitment_sha256"]
    _expect(
        waiver["frozen_before_generator_output"] is True
        and waiver["mode"] == "diagnostic_not_required"
        and isinstance(digest, str)
        and digest == _sha256_bytes(_canonical_bytes(payload)),
        "human feedback waiver commitment drifted",
    )
    return {
        "mode": "diagnostic_not_required",
        "status": "waived",
        "evaluation_contract_sha256": evaluation_sha,
        "waiver_commitment_sha256": digest,
        "reason": waiver["reason"],
    }


def _review_html(review: Mapping[str, Any], inventory: Mapping[str, Any]) -> str:
    embedded = json.dumps(review, ensure_ascii=False, separators=(",", ":"))
    embedded_inventory = json.dumps(inventory, ensure_ascii=False, separators=(",", ":"))
    for unsafe, safe in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e")):
        embedded = embedded.replace(unsafe, safe)
        embedded_inventory = embedded_inventory.replace(unsafe, safe)
    template = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LiveClip iteration-2 匿名评审</title>
<style>body{margin:0;background:#f4f6f9;color:#17202a;font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}header{padding:16px 22px;background:#101828;color:white}main{padding:18px}.source{margin-bottom:26px}.outputs{display:grid;grid-template-columns:repeat(4,minmax(320px,1fr));gap:14px;overflow:auto}.output,.evidence{background:white;border:1px solid #d7dee8;border-radius:10px;padding:13px}.highlight{border-top:1px solid #e4e7ec;padding:10px 0}.field{white-space:pre-wrap;margin:4px 0}textarea,select{width:100%;margin-top:7px;padding:8px}textarea{min-height:90px}.toolbar{position:fixed;right:18px;bottom:18px}button{padding:11px 17px;border:0;border-radius:999px;background:#2457d6;color:white}</style></head><body><header><h1>LiveClip iteration-2 匿名评审</h1><p id="instructions"></p></header><main id="app"></main><div class="toolbar"><button id="export">导出完整反馈</button></div>
<script id="review-data" type="application/json">__REVIEW__</script><script id="inventory-data" type="application/json">__INVENTORY__</script><script>"use strict";const data=JSON.parse(document.getElementById("review-data").textContent);const inventory=JSON.parse(document.getElementById("inventory-data").textContent);const app=document.getElementById("app");document.getElementById("instructions").textContent=data.instructions;const node=(tag,cls,text)=>{const v=document.createElement(tag);if(cls)v.className=cls;if(text!==undefined)v.textContent=text;return v};const field=(root,label,value)=>{const row=node("div","field");row.append(node("b","",label+"："),document.createTextNode(Array.isArray(value)?value.join("、"):value));root.append(row)};for(const source of data.sources){const section=node("section","source");section.append(node("h2","",`来源 ${source.original_position} · ${source.source_filename||source.source_id}`));const evidence=new Map(source.candidate_evidence.map(v=>[v.candidate_id,v]));const grid=node("div","outputs");for(const output of source.outputs){const card=node("article","output");card.append(node("h3","",`位置 ${output.original_position} · ${output.output_id}`));field(card,"组合摘要",output.selection_summary);for(const h of output.highlights){const item=node("section","highlight");item.append(node("h4","",`${h.original_position}. ${h.title}`));field(item,"Topic",h.topic);field(item,"Hook",h.hook);field(item,"源话术/高光语句",h.source_or_highlight_sentence);field(item,"内容描述",h.script_description);field(item,"选择理由",h.selection_reason);const proof=evidence.get(h.candidate_id);const details=node("details");details.append(node("summary","",`候选证据 · 原始位置 ${proof.original_position}`));details.append(node("pre","",proof.text));item.append(details);card.append(item)}const select=node("select");for(const [value,label] of [["","请选择"],["preferred","首选"],["acceptable","可接受"],["needs_revision","需修改"],["unusable","不可用"]]){const option=node("option","",label);option.value=value;select.append(option)}const area=node("textarea");area.placeholder="评审意见（可留空，但必须选择评级）";select.dataset.outputId=output.output_id;area.dataset.outputId=output.output_id;const key=`${data.review_id}:${output.output_id}`;const saved=JSON.parse(localStorage.getItem(key)||"{}");select.value=saved.rating||"";area.value=saved.feedback||"";const save=()=>localStorage.setItem(key,JSON.stringify({rating:select.value,feedback:area.value}));select.addEventListener("change",save);area.addEventListener("input",save);card.append(select,area);grid.append(card)}section.append(grid);app.append(section)}document.getElementById("export").addEventListener("click",()=>{const reviews=inventory.items.map(item=>{const select=document.querySelector(`select[data-output-id="${item.output_id}"]`);const area=document.querySelector(`textarea[data-output-id="${item.output_id}"]`);if(!select.value)throw new Error(`未完成：${item.output_id}`);return {...item,rating:select.value,feedback:area.value}});const payload={schema_version:"liveclip-highlight-feedback.iteration-2.v1",status:"complete",review_id:data.review_id,evaluation_contract_sha256:data.evaluation_contract_sha256,verified_input_set_sha256:data.verified_input_set_sha256,reviews};const blob=new Blob([JSON.stringify(payload,null,2)+"\n"],{type:"application/json"});const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="feedback.complete.json";link.click();URL.revokeObjectURL(link.href)});</script></body></html>"""
    return template.replace("__REVIEW__", embedded).replace("__INVENTORY__", embedded_inventory)


def _write_new(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _publish_iteration(
    output_root: Path,
    iteration_name: str,
    review: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> Path:
    _expect(
        ITERATION_NAME_RE.fullmatch(iteration_name) is not None,
        "iteration name must be a safe component",
    )
    _expect(not output_root.is_symlink(), "review output root cannot be a symlink")
    output_root = output_root.resolve(strict=False)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / iteration_name
    _expect(not target.exists() and not target.is_symlink(), "review iteration already exists")
    reservation = output_root / f".{iteration_name}.reserve"
    try:
        reservation_handle = reservation.open("xb")
    except FileExistsError as exc:
        raise ReviewBuildError("review iteration is already being built") from exc
    temporary: Path | None = None
    try:
        reservation_handle.close()
        temporary = Path(tempfile.mkdtemp(prefix=f".{iteration_name}-", dir=output_root))
        inventory = _feedback_inventory(review)
        schema = _feedback_schema(review, inventory)
        artifacts = {
            "review.json": _pretty_bytes(review),
            "review.html": _review_html(review, inventory).encode("utf-8"),
            "feedback.schema.json": _pretty_bytes(schema),
            "feedback-inventory.json": _pretty_bytes(inventory),
        }
        if evaluation["human_review_mode"] == "diagnostic_not_required":
            release = _diagnostic_waiver_release(
                evaluation, str(review["evaluation_contract_sha256"])
            )
            artifacts["feedback-waiver-receipt.json"] = _pretty_bytes(release)
        else:
            release = {"mode": "required", "status": "awaiting_complete_feedback"}
        receipt = {
            "schema_version": REVIEW_SCHEMA_VERSION,
            "review_protocol": REVIEW_PROTOCOL,
            "review_id": review["review_id"],
            "evaluation_contract_sha256": review["evaluation_contract_sha256"],
            "verified_input_set_sha256": review["verified_input_set_sha256"],
            "verified_source_count": review["source_count"],
            "verified_pipeline_count": review["pipeline_count"],
            "original_positions_preserved": True,
            "anonymous_projection": True,
            "human_feedback_release": release,
            "artifact_sha256": {
                name: _sha256_bytes(payload) for name, payload in sorted(artifacts.items())
            },
        }
        artifacts["build-receipt.json"] = _pretty_bytes(receipt)
        for name, payload in artifacts.items():
            _write_new(temporary / name, payload)
        temporary.rename(target)
        temporary = None
        return target
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        reservation.unlink(missing_ok=True)


def _validate_complete_feedback(review_dir: Path, feedback: Mapping[str, Any]) -> dict[str, Any]:
    review = _read_object(review_dir / "review.json", "review")
    inventory = _read_object(review_dir / "feedback-inventory.json", "feedback inventory")
    schema = _read_object(review_dir / "feedback.schema.json", "feedback schema")
    receipt = _read_object(review_dir / "build-receipt.json", "review build receipt")
    for field in (
        "review_id",
        "evaluation_contract_sha256",
        "verified_input_set_sha256",
    ):
        _expect(receipt.get(field) == review.get(field), f"build receipt {field} drifted")
    artifact_sha256 = receipt.get("artifact_sha256")
    _expect(isinstance(artifact_sha256, dict), "build artifact receipt is missing")
    for filename in (
        "review.json",
        "review.html",
        "feedback.schema.json",
        "feedback-inventory.json",
    ):
        path = review_dir / filename
        _expect(
            path.is_file()
            and not path.is_symlink()
            and artifact_sha256.get(filename) == _sha256_path(path),
            f"review artifact hash drifted: {filename}",
        )
    _expect_keys(
        inventory,
        {
            "schema_version",
            "review_id",
            "evaluation_contract_sha256",
            "verified_input_set_sha256",
            "expected_review_count",
            "items",
        },
        "feedback inventory",
    )
    for field in (
        "review_id",
        "evaluation_contract_sha256",
        "verified_input_set_sha256",
    ):
        _expect(inventory[field] == review[field], f"feedback inventory {field} drifted")
    _expect(schema == _feedback_schema(review, inventory), "feedback schema drifted")
    _expect_keys(
        feedback,
        {
            "schema_version",
            "status",
            "review_id",
            "evaluation_contract_sha256",
            "verified_input_set_sha256",
            "reviews",
        },
        "complete feedback",
    )
    _expect(feedback["schema_version"] == FEEDBACK_SCHEMA_VERSION, "feedback schema drifted")
    _expect(feedback["status"] == "complete", "feedback is not complete")
    for field in (
        "review_id",
        "evaluation_contract_sha256",
        "verified_input_set_sha256",
    ):
        _expect(feedback[field] == review[field], f"feedback {field} drifted")
    reviews = feedback.get("reviews")
    _expect(isinstance(reviews, list), "feedback reviews must be an array")
    expected = inventory["items"]
    _expect(
        isinstance(expected, list) and inventory["expected_review_count"] == len(expected),
        "feedback inventory count drifted",
    )
    _expect(len(reviews) == len(expected), "feedback review count is incomplete")
    identity_fields = (
        "source_id",
        "source_original_position",
        "output_id",
        "output_original_position",
    )
    observed_ids: set[str] = set()
    for expected_item, item in zip(expected, reviews, strict=True):
        _expect(isinstance(item, dict), "feedback item is malformed")
        _expect_keys(
            item,
            {*identity_fields, "rating", "feedback"},
            "feedback item",
        )
        _expect(
            all(item[field] == expected_item[field] for field in identity_fields),
            "feedback inventory/order drifted",
        )
        output_id = item["output_id"]
        _expect(output_id not in observed_ids, "feedback repeats an output")
        observed_ids.add(output_id)
        _expect(
            item["rating"] in {"preferred", "acceptable", "needs_revision", "unusable"},
            "feedback rating is missing",
        )
        _expect(
            isinstance(item["feedback"], str) and len(item["feedback"]) <= 10000,
            "feedback text is invalid",
        )
    return dict(feedback)


def commit_feedback(review_dir: Path, feedback_path: Path) -> Path:
    """Validate required human feedback and atomically commit its exact bytes."""

    review_dir = review_dir.resolve(strict=True)
    review = _read_object(review_dir / "review.json", "review")
    _expect(
        review.get("human_review_mode") == "required",
        "feedback commitment is forbidden by diagnostic_not_required waiver mode",
    )
    feedback = _read_object(feedback_path, "complete feedback")
    validated = _validate_complete_feedback(review_dir, feedback)
    complete_bytes = _pretty_bytes(validated)
    complete_path = review_dir / "feedback.complete.json"
    commitment = {
        "schema_version": "1",
        "complete": True,
        "review_id": review["review_id"],
        "evaluation_contract_sha256": review["evaluation_contract_sha256"],
        "feedback_manifest_sha256": _sha256_bytes(complete_bytes),
    }
    commitment_path = review_dir / "feedback-commitment.json"
    targets = (
        (complete_path, complete_bytes),
        (commitment_path, _pretty_bytes(commitment)),
    )
    for path, payload in targets:
        if path.exists() or path.is_symlink():
            _expect(path.is_file() and not path.is_symlink(), f"unsafe feedback target: {path}")
            _expect(path.read_bytes() == payload, f"feedback commitment is immutable: {path}")
    for path, payload in targets:
        if not path.exists():
            _write_new(path, payload)
    return commitment_path


def build_review(
    experiment_dir: Path,
    output_root: Path,
    *,
    iteration_name: str = "iteration-2",
) -> Path:
    (
        evaluation,
        evaluation_sha,
        sources,
        pipelines,
        input_set_sha,
        source_positions,
    ) = _verify_formal_experiment(experiment_dir)
    _expect(len(pipelines) == EXPECTED_PIPELINE_COUNT, "all 12 pipelines are required")
    review = _build_review_data(
        evaluation,
        evaluation_sha,
        sources,
        pipelines,
        input_set_sha,
        source_positions,
    )
    return _publish_iteration(output_root, iteration_name, review, evaluation)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    build = subparsers.add_parser("build", help="build a new immutable blind viewer")
    build.add_argument("experiment_dir", type=Path)
    build.add_argument("--output-root", required=True, type=Path)
    build.add_argument("--iteration-name", default="iteration-2")
    commit = subparsers.add_parser("commit-feedback", help="validate and commit feedback")
    commit.add_argument("review_dir", type=Path)
    commit.add_argument("feedback_file", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "commit-feedback":
            result = commit_feedback(args.review_dir, args.feedback_file)
        elif args.command == "build":
            result = build_review(
                args.experiment_dir,
                args.output_root,
                iteration_name=args.iteration_name,
            )
        else:
            raise ReviewBuildError("choose build or commit-feedback")
    except ReviewBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(result.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
