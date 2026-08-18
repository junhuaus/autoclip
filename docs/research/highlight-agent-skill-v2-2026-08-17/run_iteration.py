#!/usr/bin/env python3
"""Run the immutable, isolated Highlight Agent Skill v1-v2 experiment.

This is a research-only runner.  It reads the three already-frozen benchmark
evidence files and writes only beneath an explicitly validated experiment
root.  It never opens source media, product databases, or production assets.

The main comparison is deliberately narrow: fresh v1 and v2 generations both
use gpt-5.6-sol at medium reasoning effort.  Skill v2 is a staged pipeline:
Tier 1 batches (at most 15 candidates), Tier 2 topic inventory, deterministic
Tier 3 portfolio selection, and Tier 4 editorial copy.  Sol High is never
called; the runner only records deterministic ``would_escalate`` diagnostics.

``--dry-run`` freezes and verifies the complete experiment plan but does not
invoke a model.  Re-running without ``--dry-run`` resumes only byte-identical,
hash-bound artifacts.  There is intentionally no force/overwrite option.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ITERATION_DIR = Path(__file__).resolve().parent
PRIOR_BENCHMARK_DIR = ROOT / "docs/research/model-benchmark-2026-08-17"
CONTRACTS_PATH = ITERATION_DIR / "contracts.py"
INPUT_GATE_PATH = ITERATION_DIR / "input_gate.py"
V1_SKILL_PATH = PRIOR_BENCHMARK_DIR / "agent-v1/SKILL.md"
V1_SCHEMA_PATH = PRIOR_BENCHMARK_DIR / "schemas/highlight-output.schema.json"
V2_SKILL_DIR = ITERATION_DIR / "agent-v2"
DEFAULT_OUTPUT_ROOT = ITERATION_DIR / "experiments"

RUNNER_VERSION = "liveclip-highlight-v1-v2-runner.iteration-1"
PROTOCOL_SEED = "liveclip-highlight-v2-ab-iteration-1-order-v1"
MODEL_CONFIG = {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}
REPEATS_PER_SOURCE = 2
TIER1_BATCH_SIZE = 15
TOP_N = 12
MINIMUM_QUALITY = 55.0
MAXIMUM_INTERVAL_IOU = 0.45
MAXIMUM_TEXT_JACCARD = 0.65
MAX_MODEL_ATTEMPTS = 2
MAX_PIPELINE_REPAIRS = 2


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    case_id: str
    relative_input_path: str
    expected_frozen_input_sha256: str
    expected_source_sha256: str
    expected_candidate_count: int


SOURCE_SPECS = (
    SourceSpec(
        source_id="src_7f34cc21eaf6d819",
        case_id="b1_8_16_2",
        relative_input_path=(
            "docs/research/model-benchmark-2026-08-17/results/b1_8_16_2/r001/frozen-input.json"
        ),
        expected_frozen_input_sha256=(
            "cc035e5eb5764b7b53bd0855fccee5d07334ee3b32abd15bcb957f27b1996936"
        ),
        expected_source_sha256=("6cdac49603cb5e25faf6cb33523aa8c46e28398770f02345a05ca526b503f417"),
        expected_candidate_count=45,
    ),
    SourceSpec(
        source_id="src_4ae8fc713215e94c",
        case_id="b2_7_28",
        relative_input_path=(
            "docs/research/model-benchmark-2026-08-17/results/b2_7_28/r001/frozen-input.json"
        ),
        expected_frozen_input_sha256=(
            "1b7d77e407657adceaed7bd8e28fe286cfac1732e0a7784680053c3ccad331ec"
        ),
        expected_source_sha256=("595cc75a65fe8d9faa3b41ba9f5b58b307d1b0a41236f7fc6016c0c1ae8acd03"),
        expected_candidate_count=41,
    ),
    SourceSpec(
        source_id="src_199c8497104d75ba",
        case_id="b3_8_16_1",
        relative_input_path=(
            "docs/research/model-benchmark-2026-08-17/results/b3_8_16_1/r001/frozen-input.json"
        ),
        expected_frozen_input_sha256=(
            "3c46dca758569693b84006179e04708a2586418fc299aed81bce5eacde6c19ec"
        ),
        expected_source_sha256=("af88f7fe27cbdfc05e68b32684c558bb1877dbc7dd025b12726dd21b5e7e7d29"),
        expected_candidate_count=45,
    ),
)


DISABLED_FEATURES = (
    "apps",
    "artifact",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode",
    "code_mode_buffered_exec",
    "code_mode_host",
    "code_mode_only",
    "computer_use",
    "default_mode_request_user_input",
    "deferred_executor",
    "deferred_tool_world_state",
    "enable_mcp_apps",
    "exec_permission_approvals",
    "executor_capability_discovery",
    "external_agent_memory_import",
    "goals",
    "guardian_approval",
    "hooks",
    "image_generation",
    "in_app_browser",
    "mcp_2026_07_28",
    "memories",
    "multi_agent",
    "network_proxy",
    "plugin_sharing",
    "plugins",
    "realtime_conversation",
    "remote_plugin",
    "request_permissions_tool",
    "shell_snapshot",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "standalone_web_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "unified_exec",
    "workspace_dependencies",
)
SAFE_ENV_KEYS = {
    "CODEX_HOME",
    "HOME",
    "LANG",
    "LC_ALL",
    "LOGNAME",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TMPDIR",
    "USER",
}
SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+|api[_-]?key\s*[=:]\s*|sk-or-v1-|sk-)[A-Za-z0-9._~+/=-]{8,}"
)


@dataclass(frozen=True)
class PreparedExperiment:
    experiment_dir: Path
    experiment_id: str
    contract_sha256: str
    manifest: dict[str, Any]
    contracts: ModuleType
    sources: dict[str, dict[str, Any]]
    source_specs: dict[str, SourceSpec]
    public_plan: dict[str, Any]
    private_map: dict[str, Any]
    tier_bundles: dict[str, str]


@dataclass
class RepairBudget:
    maximum_repairs: int = MAX_PIPELINE_REPAIRS
    used_by_stage: list[str] | None = None

    def __post_init__(self) -> None:
        if self.used_by_stage is None:
            self.used_by_stage = []

    def consume(self, stage: str) -> None:
        assert self.used_by_stage is not None
        tier = "v2-tier1" if stage.startswith("v2-tier1-") else stage
        if tier in self.used_by_stage:
            raise RuntimeError(
                f"same-tier repair already used for {tier}; no second repair is permitted"
            )
        if len(self.used_by_stage) >= self.maximum_repairs:
            raise RuntimeError(
                "pipeline repair budget exhausted; no additional model call is permitted"
            )
        self.used_by_stage.append(tier)

    def receipt(self) -> dict[str, Any]:
        assert self.used_by_stage is not None
        return {
            "maximum_repairs": self.maximum_repairs,
            "repairs_used": len(self.used_by_stage),
            "used_by_stage": list(self.used_by_stage),
        }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8")), raw


def _atomic_write_new(path: Path, content: bytes) -> None:
    """Create ``path`` or verify it; never replace different bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != content:
            raise RuntimeError(f"immutable artifact differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            if path.read_bytes() != content:
                raise RuntimeError(
                    f"immutable artifact raced with different bytes: {path}"
                ) from exc
        finally:
            temporary.unlink(missing_ok=True)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_replace_derived(path: Path, content: bytes) -> None:
    """Atomically replace a derived progress summary, never a call result."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _skill_body(path: Path) -> str:
    value = path.read_text(encoding="utf-8")
    if not value.startswith("---\n"):
        raise RuntimeError(f"runtime Skill has no YAML frontmatter: {path}")
    marker = value.find("\n---\n", 4)
    if marker < 0:
        raise RuntimeError(f"runtime Skill frontmatter is not closed: {path}")
    return value[marker + 5 :].lstrip("\n")


def _load_contracts() -> ModuleType:
    if not CONTRACTS_PATH.is_file():
        raise RuntimeError(f"v2 contracts are missing: {CONTRACTS_PATH}")
    module_name = "liveclip_highlight_agent_v2_contracts_runtime"
    spec = importlib.util.spec_from_file_location(module_name, CONTRACTS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the v2 contracts module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    required = (
        "AssessmentBatch",
        "TopicInventoryDraft",
        "EditorialCopyBatch",
        "validate_assessment_batch",
        "validate_complete_assessments",
        "validate_and_enrich_inventory",
        "select_portfolio",
        "validate_editorial_copies",
        "compose_final_result",
        "audit_v1_result",
        "CONTRACT_VERSION",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "contracts.py interface is incomplete; fail closed until adapted: " + ", ".join(missing)
        )
    return module


def _load_input_gate() -> ModuleType:
    if not INPUT_GATE_PATH.is_file():
        raise RuntimeError(f"Tier 0 input Gate is missing: {INPUT_GATE_PATH}")
    module_name = "liveclip_highlight_agent_v2_input_gate_runtime"
    spec = importlib.util.spec_from_file_location(module_name, INPUT_GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the Tier 0 input Gate module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    required = (
        "INPUT_GATE_VERSION",
        "validate_frozen_evidence",
        "evidence_set_sha256",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            "input_gate.py interface is incomplete; fail closed until adapted: "
            + ", ".join(missing)
        )
    return module


def _tier_reference_path(tier: str) -> Path:
    references = V2_SKILL_DIR / "references"
    if not references.is_dir():
        raise RuntimeError(f"v2 Skill references are missing: {references}")
    normalized_tier = tier.replace("tier", "")
    candidates = []
    for path in sorted(references.glob("*.md")):
        normalized_name = re.sub(r"[^a-z0-9]", "", path.stem.casefold())
        if f"tier{normalized_tier}" in normalized_name:
            candidates.append(path)
    if len(candidates) != 1:
        rendered = ", ".join(str(path.name) for path in candidates) or "none"
        raise RuntimeError(
            f"expected exactly one Tier {normalized_tier} reference, found: {rendered}"
        )
    return candidates[0]


def _load_v2_tier_bundles() -> tuple[dict[str, str], dict[str, str]]:
    skill_path = V2_SKILL_DIR / "SKILL.md"
    if not skill_path.is_file():
        raise RuntimeError(f"v2 runtime Skill is missing: {skill_path}")
    body = _skill_body(skill_path)
    bundles: dict[str, str] = {}
    paths: dict[str, str] = {}
    common_references = {
        "atomic-scoring": V2_SKILL_DIR / "references/atomic-scoring.md",
        "risk-and-repair": V2_SKILL_DIR / "references/risk-and-repair.md",
    }
    for label, path in common_references.items():
        if not path.is_file():
            raise RuntimeError(f"v2 {label} reference is missing: {path}")
    tier_common = {
        "tier1": ("atomic-scoring", "risk-and-repair"),
        "tier2": ("risk-and-repair",),
        "tier4": ("risk-and-repair",),
    }
    for tier in ("tier1", "tier2", "tier4"):
        reference_path = _tier_reference_path(tier)
        paths[tier] = str(reference_path.relative_to(ROOT))
        bundle = (
            body.rstrip()
            + "\n\n<task_tier_contract>\n"
            + reference_path.read_text(encoding="utf-8").strip()
            + "\n</task_tier_contract>\n"
        )
        for common_label in tier_common[tier]:
            common_path = common_references[common_label]
            paths[f"{tier}:{common_label}"] = str(common_path.relative_to(ROOT))
            bundle += (
                f'\n<supporting_contract name="{common_label}">\n'
                + common_path.read_text(encoding="utf-8").strip()
                + "\n</supporting_contract>\n"
            )
        bundles[tier] = bundle
    return bundles, paths


def _package_hashes(directory: Path) -> dict[str, str]:
    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"v2 Skill package is empty: {directory}")
    return {str(path.relative_to(directory)): _sha256_path(path) for path in files}


def _validate_frozen_source(spec: SourceSpec, input_gate: ModuleType) -> tuple[dict[str, Any], str]:
    path = ROOT / spec.relative_input_path
    if not path.is_file():
        raise RuntimeError(f"frozen evidence is missing: {path}")
    if _sha256_path(path) != spec.expected_frozen_input_sha256:
        raise RuntimeError(f"frozen evidence hash changed: {spec.case_id}")
    raw, _ = _json_bytes(path)
    if not isinstance(raw, dict):
        raise RuntimeError(f"invalid frozen evidence root: {spec.case_id}")
    validated = input_gate.validate_frozen_evidence(raw)
    evidence = validated.model_dump(mode="json")
    if evidence["source"]["source_sha256"] != spec.expected_source_sha256:
        raise RuntimeError(f"source identity changed: {spec.case_id}")
    if len(evidence["candidates"]) != spec.expected_candidate_count:
        raise RuntimeError(f"candidate count changed: {spec.case_id}")
    if evidence["source"]["candidate_count"] != spec.expected_candidate_count:
        raise RuntimeError(f"source candidate count changed: {spec.case_id}")
    return evidence, str(input_gate.evidence_set_sha256(validated))


def _freeze_candidate_enum(schema: dict[str, Any], candidate_ids: Sequence[str]) -> None:
    """Replace every candidate_id property with this experiment's frozen enum."""

    replacements = 0

    def visit(value: Any) -> None:
        nonlocal replacements
        if isinstance(value, dict):
            properties = value.get("properties")
            if isinstance(properties, dict) and "candidate_id" in properties:
                properties["candidate_id"] = {
                    "type": "string",
                    "enum": list(candidate_ids),
                }
                replacements += 1
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    if replacements == 0:
        raise RuntimeError("output Schema has no candidate_id property to freeze")


def _schema_from_model(model: Any, candidate_ids: Sequence[str]) -> dict[str, Any]:
    schema = model.model_json_schema(mode="validation")
    _freeze_candidate_enum(schema, candidate_ids)
    return schema


def _frozen_v1_schema(candidate_ids: Sequence[str]) -> dict[str, Any]:
    schema, _ = _json_bytes(V1_SCHEMA_PATH)
    _freeze_candidate_enum(schema, candidate_ids)
    return schema


def _opaque_id(namespace: str, identity: str) -> str:
    digest = _sha256_bytes(f"{PROTOCOL_SEED}:{namespace}:{identity}".encode())
    return f"{namespace}_{digest[:16]}"


def _arm_map() -> dict[str, str]:
    return {
        _opaque_id("arm", "old_skill"): "v1",
        _opaque_id("arm", "with_skill"): "v2",
    }


def _build_schedule(arm_map: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    arm_by_version = {version: arm_id for arm_id, version in arm_map.items()}
    pairs = [
        (spec.source_id, repeat)
        for spec in SOURCE_SPECS
        for repeat in range(1, REPEATS_PER_SOURCE + 1)
    ]
    rng = random.Random(int(_sha256_bytes(PROTOCOL_SEED.encode("utf-8"))[:16], 16))
    rng.shuffle(pairs)
    first_v2_pairs = set(pairs[: len(pairs) // 2])
    schedule: list[dict[str, Any]] = []
    private_pipelines: dict[str, Any] = {}
    for pair_index, (source_id, repeat) in enumerate(pairs, start=1):
        versions = ("v2", "v1") if (source_id, repeat) in first_v2_pairs else ("v1", "v2")
        pair_id = _opaque_id("pair", f"{source_id}:r{repeat:03d}")
        public_pair = {
            "pair_sequence": pair_index,
            "pair_id": pair_id,
            "source_id": source_id,
            "repeat": repeat,
            "candidate_order": "original_frozen_order",
            "pipelines": [],
        }
        for within_pair, version in enumerate(versions, start=1):
            arm_id = arm_by_version[version]
            pipeline_id = _opaque_id("pipeline", f"{source_id}:r{repeat:03d}:{arm_id}")
            public_pair["pipelines"].append(
                {
                    "within_pair_sequence": within_pair,
                    "pipeline_id": pipeline_id,
                    "arm_id": arm_id,
                }
            )
            private_pipelines[pipeline_id] = {
                "source_id": source_id,
                "repeat": repeat,
                "arm_id": arm_id,
                "skill_version": version,
            }
        schedule.append(public_pair)
    private = {
        "arm_id_to_skill_version": arm_map,
        "pipeline_id_to_identity": private_pipelines,
    }
    return schedule, private


def _codex_identity() -> dict[str, str]:
    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("codex CLI is unavailable; cannot freeze an executable contract")
    completed = subprocess.run(
        [executable, "--version"],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
        env={key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS},
    )
    version = (
        completed.stdout.strip() or completed.stderr.strip() if completed.returncode == 0 else ""
    )
    if not version:
        raise RuntimeError("cannot determine codex CLI version")
    return {"path": str(Path(executable).resolve()), "version": version}


def _validate_output_root(value: Path) -> Path:
    requested = value.expanduser()
    requested.parent.mkdir(parents=True, exist_ok=True)
    resolved = requested.resolve(strict=False)
    forbidden = (
        ROOT / "data",
        ROOT / "input",
        ROOT / ".git",
        ROOT / "src",
        ROOT / "apps",
        PRIOR_BENCHMARK_DIR,
    )
    for path in forbidden:
        resolved_forbidden = path.resolve(strict=False)
        if resolved == resolved_forbidden or resolved_forbidden in resolved.parents:
            raise RuntimeError(f"experiment output root is forbidden: {resolved}")
    if resolved.exists() and resolved.is_symlink():
        raise RuntimeError(f"experiment output root cannot be a symlink: {resolved}")
    return resolved


def _artifact_record(content: bytes) -> dict[str, Any]:
    return {"sha256": _sha256_bytes(content), "size_bytes": len(content)}


def _prepare_experiment(output_root: Path) -> PreparedExperiment:
    contracts = _load_contracts()
    input_gate = _load_input_gate()
    tier_bundles, tier_reference_paths = _load_v2_tier_bundles()
    validated_sources = {
        spec.source_id: _validate_frozen_source(spec, input_gate) for spec in SOURCE_SPECS
    }
    sources = {source_id: values[0] for source_id, values in validated_sources.items()}
    evidence_set_hashes = {source_id: values[1] for source_id, values in validated_sources.items()}
    source_specs = {spec.source_id: spec for spec in SOURCE_SPECS}
    if len({value["source"]["source_sha256"] for value in sources.values()}) != 3:
        raise RuntimeError("the experiment matrix must contain exactly three unique sources")

    arm_map = _arm_map()
    schedule, private_map = _build_schedule(arm_map)
    private_bytes = _pretty_json_bytes(private_map)
    public_plan = {
        "schema_version": "1",
        "study": "fresh-v1-v2-same-model-minimum-matrix",
        "unique_source_count": 3,
        "repeats_per_source": REPEATS_PER_SOURCE,
        "pipeline_count": 3 * REPEATS_PER_SOURCE * 2,
        "candidate_order_variants": ["original_frozen_order"],
        "order_claim_limit": "No candidate-order robustness claim is permitted.",
        "execution_design": (
            "Six source/repeat blocks in a fixed seeded random order; exactly three blocks "
            "run each opaque arm first, and both arms use the same frozen evidence."
        ),
        "model": MODEL_CONFIG,
        "tier_topology": {
            "v1": ["single_fresh_generation"],
            "v2": [
                "tier1_batches_max_15",
                "tier2_topic_inventory",
                "tier3_deterministic_portfolio",
                "tier4_editorial_copy",
                "deterministic_exact_quote_gate",
            ],
        },
        "sol_high_policy": "disabled; record deterministic would_escalate only",
        "schedule": schedule,
        "arm_mapping_commitment_sha256": _sha256_bytes(private_bytes),
    }

    expected_files: dict[str, bytes] = {
        "frozen/public-plan.json": _pretty_json_bytes(public_plan),
        "private/arm-map.private.json": private_bytes,
        "frozen/runtime/v1-skill.md": V1_SKILL_PATH.read_bytes(),
        "frozen/runtime/v2-tier1-bundle.md": tier_bundles["tier1"].encode("utf-8"),
        "frozen/runtime/v2-tier2-bundle.md": tier_bundles["tier2"].encode("utf-8"),
        "frozen/runtime/v2-tier4-bundle.md": tier_bundles["tier4"].encode("utf-8"),
        "frozen/gates/input_gate.py": INPUT_GATE_PATH.read_bytes(),
    }
    schema_hashes: dict[str, dict[str, str]] = {}
    source_contracts: list[dict[str, Any]] = []
    for spec in SOURCE_SPECS:
        evidence = sources[spec.source_id]
        candidate_ids = [item["candidate_id"] for item in evidence["candidates"]]
        evidence_bytes = _pretty_json_bytes(evidence)
        expected_files[f"frozen/inputs/{spec.source_id}.json"] = evidence_bytes
        schemas = {
            "v1": _frozen_v1_schema(candidate_ids),
            "v2-tier2": _schema_from_model(contracts.TopicInventoryDraft, candidate_ids),
            "v2-tier4": _schema_from_model(contracts.EditorialCopyBatch, candidate_ids),
        }
        for batch_index in range(0, len(candidate_ids), TIER1_BATCH_SIZE):
            batch_ids = candidate_ids[batch_index : batch_index + TIER1_BATCH_SIZE]
            schemas[f"v2-tier1-b{batch_index // TIER1_BATCH_SIZE + 1:02d}"] = _schema_from_model(
                contracts.AssessmentBatch, batch_ids
            )
        schema_hashes[spec.source_id] = {}
        for name, schema in schemas.items():
            relative = f"frozen/schemas/{spec.source_id}/{name}.json"
            content = _pretty_json_bytes(schema)
            expected_files[relative] = content
            schema_hashes[spec.source_id][name] = _sha256_bytes(content)
        source_contracts.append(
            {
                "source_id": spec.source_id,
                "case_id": spec.case_id,
                "source_sha256": spec.expected_source_sha256,
                "upstream_frozen_input_sha256": spec.expected_frozen_input_sha256,
                "experiment_input_sha256": _sha256_bytes(evidence_bytes),
                "input_gate_sha256": _sha256_path(INPUT_GATE_PATH),
                "input_gate_version": str(input_gate.INPUT_GATE_VERSION),
                "evidence_set_sha256": evidence_set_hashes[spec.source_id],
                "candidate_order_sha256": _sha256_bytes(_canonical_bytes(candidate_ids)),
                "candidate_count": len(candidate_ids),
                "tier1_batch_count": math.ceil(len(candidate_ids) / TIER1_BATCH_SIZE),
                "schema_sha256": schema_hashes[spec.source_id],
            }
        )

    runner_sha = _sha256_path(Path(__file__).resolve())
    package_hashes = _package_hashes(V2_SKILL_DIR)
    contract_payload = {
        "schema_version": "1",
        "runner_version": RUNNER_VERSION,
        "runner_sha256": runner_sha,
        "contracts_sha256": _sha256_path(CONTRACTS_PATH),
        "contracts_version": str(contracts.CONTRACT_VERSION),
        "input_gate_sha256": _sha256_path(INPUT_GATE_PATH),
        "input_gate_version": str(input_gate.INPUT_GATE_VERSION),
        "v1_skill_sha256": _sha256_path(V1_SKILL_PATH),
        "v1_base_schema_sha256": _sha256_path(V1_SCHEMA_PATH),
        "v2_skill_package_sha256": package_hashes,
        "v2_tier_reference_paths": tier_reference_paths,
        "public_plan_sha256": _sha256_bytes(expected_files["frozen/public-plan.json"]),
        "arm_mapping_commitment_sha256": _sha256_bytes(private_bytes),
        "sources": source_contracts,
        "model": MODEL_CONFIG,
        "selection_configuration": {
            "top_n": TOP_N,
            "minimum_quality": MINIMUM_QUALITY,
            "maximum_interval_iou": MAXIMUM_INTERVAL_IOU,
            "maximum_text_jaccard": MAXIMUM_TEXT_JACCARD,
        },
        "repair_policy": {
            "maximum_attempts_per_model_call": MAX_MODEL_ATTEMPTS,
            "maximum_repairs_per_tier": 1,
            "maximum_repairs_per_pipeline": MAX_PIPELINE_REPAIRS,
            "repair_returns_to_same_tier": True,
        },
        "runtime_isolation": {
            "ephemeral": True,
            "ignore_user_config": True,
            "ignore_rules": True,
            "sandbox": "read-only",
            "tools": "disabled",
            "environment": "allowlist",
            "unsafe_tool_event": "hard_fail",
        },
        "codex_cli": _codex_identity(),
    }
    contract_sha = _sha256_bytes(_canonical_bytes(contract_payload))
    experiment_id = f"exp_{contract_sha[:20]}"
    experiment_dir = output_root / experiment_id
    artifact_index = {
        relative: _artifact_record(content) for relative, content in sorted(expected_files.items())
    }
    manifest = {
        "schema_version": "1",
        "experiment_id": experiment_id,
        "contract_sha256": contract_sha,
        "immutable_contract": contract_payload,
        "artifact_index": artifact_index,
    }
    manifest_bytes = _pretty_json_bytes(manifest)

    output_root.mkdir(parents=True, exist_ok=True)
    if experiment_dir.exists():
        if not experiment_dir.is_dir() or experiment_dir.is_symlink():
            raise RuntimeError(f"invalid existing experiment directory: {experiment_dir}")
        manifest_path = experiment_dir / "experiment-manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(
                f"existing experiment has no manifest; choose a clean output root: {experiment_dir}"
            )
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing_manifest != manifest:
            raise RuntimeError("experiment manifest drift; a changed contract requires a new ID")
        for relative, content in expected_files.items():
            path = experiment_dir / relative
            if not path.is_file() or path.read_bytes() != content:
                raise RuntimeError(f"frozen experiment artifact drift: {path}")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f".{experiment_id}-", dir=str(output_root)))
        try:
            for relative, content in expected_files.items():
                _atomic_write_new(temporary / relative, content)
            _atomic_write_new(temporary / "experiment-manifest.json", manifest_bytes)
            temporary.rename(experiment_dir)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    return PreparedExperiment(
        experiment_dir=experiment_dir,
        experiment_id=experiment_id,
        contract_sha256=contract_sha,
        manifest=manifest,
        contracts=contracts,
        sources=sources,
        source_specs=source_specs,
        public_plan=public_plan,
        private_map=private_map,
        tier_bundles=tier_bundles,
    )


def _render_v1_prompt(evidence: dict[str, Any]) -> str:
    source = evidence["source"]
    rendered = (
        _skill_body(V1_SKILL_PATH)
        .replace("{{SOURCE_LABEL}}", str(source["filename"]))
        .replace("{{DURATION_MS}}", f"{source['duration_ms']:,}")
    )
    return (
        rendered.rstrip()
        + "\n\n<untrusted_frozen_input>\n"
        + _canonical_bytes(evidence).decode("utf-8")
        + "\n</untrusted_frozen_input>\n"
    )


def _render_v2_prompt(bundle: str, payload: dict[str, Any]) -> str:
    return (
        bundle.rstrip()
        + "\n\n<untrusted_frozen_input>\n"
        + _canonical_bytes(payload).decode("utf-8")
        + "\n</untrusted_frozen_input>\n"
    )


def _codex_command(schema: Path, output: Path) -> list[str]:
    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("codex CLI is unavailable")
    disabled = [value for name in DISABLED_FEATURES for value in ("--disable", name)]
    return [
        executable,
        "--ask-for-approval",
        "never",
        *disabled,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--strict-config",
        "--sandbox",
        "read-only",
        "-c",
        "features.shell_tool=false",
        "-c",
        "features.unified_exec=false",
        "-c",
        "features.multi_agent=false",
        "-c",
        'web_search="disabled"',
        "-c",
        f'model_reasoning_effort="{MODEL_CONFIG["reasoning_effort"]}"',
        "--model",
        MODEL_CONFIG["model"],
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(output),
        "--json",
        "--color",
        "never",
        "-",
    ]


def _parse_events(stdout: str) -> tuple[str | None, dict[str, int] | None, bool]:
    request_id: str | None = None
    usage: dict[str, int] | None = None
    unsafe_event = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            request_id = event["thread_id"]
        event_type = event.get("type")
        if isinstance(event_type, str) and event_type.startswith("item."):
            item = event.get("item")
            item_type = item.get("type") if isinstance(item, dict) else None
            if item_type not in {"agent_message", "reasoning"}:
                unsafe_event = True
        if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = {
                key: value
                for key, value in event["usage"].items()
                if isinstance(key, str)
                and re.fullmatch(r"[a-z_]{1,40}", key)
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            }
    return request_id, usage, unsafe_event


def _redact(value: str) -> str:
    return SECRET_RE.sub("[REDACTED]", value)


def _invoke_codex(
    *,
    label: str,
    prompt: str,
    schema_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    started_at = datetime.now(UTC)
    started = time.monotonic()
    print(f"START {label} sol/medium", flush=True)
    with tempfile.TemporaryDirectory(prefix=f"liveclip-v2-{label}-") as temp_value:
        output = Path(temp_value) / "result.json"
        completed = subprocess.run(
            _codex_command(schema_path, output),
            input=prompt,
            text=True,
            capture_output=True,
            cwd=temp_value,
            env={key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS},
            timeout=2_400,
            check=False,
        )
        request_id, usage, unsafe_event = _parse_events(completed.stdout)
        if unsafe_event:
            raise RuntimeError(f"{label} emitted a forbidden tool event")
        if completed.returncode != 0:
            tail = "\n".join(completed.stderr.splitlines()[-12:])
            raise RuntimeError(
                f"{label} failed with exit {completed.returncode}: {_redact(tail)[:3000]}"
            )
        if not output.is_file():
            raise RuntimeError(f"{label} did not produce structured output")
        raw = json.loads(output.read_text(encoding="utf-8"))
        events = completed.stdout
    metadata = {
        "label": label,
        "model": MODEL_CONFIG["model"],
        "reasoning_effort": MODEL_CONFIG["reasoning_effort"],
        "request_id": request_id,
        "usage": usage,
        "started_at": started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "unsafe_tool_event": False,
    }
    print(f"DONE {label} {metadata['elapsed_seconds']}s", flush=True)
    return raw, metadata, events


Validation = Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]


def _call_id(pipeline_id: str, stage: str) -> str:
    return _opaque_id("call", f"{pipeline_id}:{stage}")


def _call_contract(
    *,
    prepared: PreparedExperiment,
    call_id: str,
    pipeline_id: str,
    stage: str,
    prompt: str,
    schema_path: Path,
    dependency_hashes: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "experiment_id": prepared.experiment_id,
        "experiment_contract_sha256": prepared.contract_sha256,
        "call_id": call_id,
        "pipeline_id": pipeline_id,
        "stage": stage,
        "model": MODEL_CONFIG,
        "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
        "schema_relative_path": str(schema_path.relative_to(prepared.experiment_dir)),
        "schema_sha256": _sha256_path(schema_path),
        "dependency_sha256": dict(sorted(dependency_hashes.items())),
        "maximum_attempts": MAX_MODEL_ATTEMPTS,
        "isolation": prepared.manifest["immutable_contract"]["runtime_isolation"],
    }


def _validate_completed_call(
    call_dir: Path,
    expected_contract: dict[str, Any],
    validator: Validation,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    completion_path = call_dir / "complete.json"
    if not completion_path.exists():
        return None
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if set(completion) != {
        "schema_version",
        "call_id",
        "call_contract_sha256",
        "successful_attempt",
        "successful_attempt_contract_sha256",
        "artifact_sha256",
    } or completion.get("call_id") != expected_contract["call_id"]:
        raise RuntimeError(f"completed call receipt shape/identity drift: {call_dir}")
    contract_path = call_dir / "call-contract.json"
    if not contract_path.is_file() or json.loads(contract_path.read_text()) != expected_contract:
        raise RuntimeError(f"completed call contract drift: {call_dir}")
    if completion.get("call_contract_sha256") != _sha256_path(contract_path):
        raise RuntimeError(f"completed call contract receipt drift: {call_dir}")
    attempt_number = completion.get("successful_attempt")
    if not isinstance(attempt_number, int) or isinstance(attempt_number, bool):
        raise RuntimeError(f"completed call has invalid attempt receipt: {call_dir}")
    attempt_contract_path = (
        call_dir / "attempts" / f"{attempt_number:03d}" / "attempt-contract.json"
    )
    if not attempt_contract_path.is_file() or completion.get(
        "successful_attempt_contract_sha256"
    ) != _sha256_path(attempt_contract_path):
        raise RuntimeError(f"completed call attempt receipt drift: {call_dir}")
    artifact_hashes = completion.get("artifact_sha256")
    expected_artifacts = {
        "result.raw.json",
        "result.json",
        "validation.json",
        "call-metadata.json",
        "events.jsonl",
    }
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != expected_artifacts:
        raise RuntimeError(f"completed call artifact receipt is incomplete: {call_dir}")
    for relative, expected_hash in artifact_hashes.items():
        path = call_dir / relative
        if not path.is_file() or _sha256_path(path) != expected_hash:
            raise RuntimeError(f"completed call artifact drift: {path}")
    raw = json.loads((call_dir / "result.raw.json").read_text(encoding="utf-8"))
    enriched, validation = validator(raw)
    if enriched != json.loads((call_dir / "result.json").read_text(encoding="utf-8")):
        raise RuntimeError(f"completed call enriched result no longer validates: {call_dir}")
    if validation != json.loads((call_dir / "validation.json").read_text(encoding="utf-8")):
        raise RuntimeError(f"completed call validation receipt drift: {call_dir}")
    metadata = json.loads((call_dir / "call-metadata.json").read_text(encoding="utf-8"))
    print(f"RESUME {expected_contract['call_id']}", flush=True)
    return enriched, validation, metadata


def _persist_attempt(
    attempt_dir: Path,
    *,
    prompt: str,
    raw: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    events: str | None,
    error: str | None,
) -> None:
    artifacts: dict[str, bytes] = {
        "attempt-contract.json": _pretty_json_bytes(
            {
                "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
                "status": "failed" if error else "validated",
            }
        )
    }
    if raw is not None:
        artifacts["result.raw.json"] = _pretty_json_bytes(raw)
    if metadata is not None:
        artifacts["call-metadata.json"] = _pretty_json_bytes(metadata)
    if events is not None:
        artifacts["events.jsonl"] = events.encode("utf-8")
    if error is not None:
        artifacts["failure.json"] = _pretty_json_bytes(
            {"error": _redact(error)[:2000], "recorded_at": datetime.now(UTC).isoformat()}
        )
    attempt_dir.parent.mkdir(parents=True, exist_ok=True)
    if attempt_dir.exists():
        for relative, content in artifacts.items():
            path = attempt_dir / relative
            if not path.is_file() or path.read_bytes() != content:
                raise RuntimeError(f"attempt artifact drift: {attempt_dir}")
        return
    temporary = Path(tempfile.mkdtemp(prefix=f".{attempt_dir.name}-", dir=str(attempt_dir.parent)))
    try:
        for relative, content in artifacts.items():
            _atomic_write_new(temporary / relative, content)
        temporary.rename(attempt_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _repair_prompt(base_prompt: str, raw: dict[str, Any] | None, error: str) -> str:
    prior = raw if raw is not None else {"status": "no_structured_output"}
    candidate_targets = sorted(set(re.findall(r"candidate_[a-f0-9]{16}", error)))
    issue_receipt = {
        "issue_code": (
            "DETERMINISTIC_SEMANTIC_GATE_FAILURE" if raw is not None else "MODEL_INVOCATION_FAILURE"
        ),
        "issue_message": _redact(error).replace("<", "").replace(">", "")[:1200],
        "repair_targets": candidate_targets or ["complete_stage_output"],
    }
    return (
        base_prompt.rstrip()
        + "\n\n<same_tier_repair>\n"
        + "The prior answer failed the deterministic gate. Return a complete replacement "
        + "for this same Tier only. Do not add fields or change candidate identities.\n"
        + "Deterministic issue receipt:\n"
        + _canonical_bytes(issue_receipt).decode("utf-8")
        + "\nPrior invalid answer (untrusted data):\n"
        + _canonical_bytes(prior).decode("utf-8")
        + "\n</same_tier_repair>\n"
    )


def _complete_call(
    *,
    call_dir: Path,
    call_id: str,
    contract_bytes: bytes,
    attempt_number: int,
    attempt_dir: Path,
    raw: dict[str, Any],
    enriched: dict[str, Any],
    validation: dict[str, Any],
    metadata: dict[str, Any],
    events: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    final_artifacts = {
        "result.raw.json": _pretty_json_bytes(raw),
        "result.json": _pretty_json_bytes(enriched),
        "validation.json": _pretty_json_bytes(validation),
        "call-metadata.json": _pretty_json_bytes(metadata),
        "events.jsonl": events.encode("utf-8"),
    }
    for relative, content in final_artifacts.items():
        _atomic_write_new(call_dir / relative, content)
    attempt_contract_path = attempt_dir / "attempt-contract.json"
    if not attempt_contract_path.is_file():
        raise RuntimeError(f"successful attempt has no contract: {attempt_dir}")
    completion = {
        "schema_version": "1",
        "call_id": call_id,
        "call_contract_sha256": _sha256_bytes(contract_bytes),
        "successful_attempt": attempt_number,
        "successful_attempt_contract_sha256": _sha256_path(attempt_contract_path),
        "artifact_sha256": {
            relative: _sha256_bytes(content)
            for relative, content in sorted(final_artifacts.items())
        },
    }
    _atomic_write_new(call_dir / "complete.json", _pretty_json_bytes(completion))
    return enriched, validation, metadata


def _run_call(
    *,
    prepared: PreparedExperiment,
    pipeline_id: str,
    stage: str,
    prompt: str,
    schema_path: Path,
    dependency_hashes: dict[str, str],
    validator: Validation,
    repair_budget: RepairBudget,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    call_id = _call_id(pipeline_id, stage)
    call_dir = prepared.experiment_dir / "calls" / call_id
    contract = _call_contract(
        prepared=prepared,
        call_id=call_id,
        pipeline_id=pipeline_id,
        stage=stage,
        prompt=prompt,
        schema_path=schema_path,
        dependency_hashes=dependency_hashes,
    )
    contract_bytes = _pretty_json_bytes(contract)
    _atomic_write_new(call_dir / "call-contract.json", contract_bytes)
    completion_path = call_dir / "complete.json"
    if completion_path.is_file():
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        if completion.get("successful_attempt") == 2:
            repair_budget.consume(stage)
    resumed = _validate_completed_call(call_dir, contract, validator)
    if resumed is not None:
        return resumed

    current_prompt = prompt
    last_error = ""
    repair_consumed = False
    for attempt_number in range(1, MAX_MODEL_ATTEMPTS + 1):
        if attempt_number > 1 and not repair_consumed:
            repair_budget.consume(stage)
            repair_consumed = True
        attempt_dir = call_dir / "attempts" / f"{attempt_number:03d}"
        if attempt_dir.exists():
            attempt_contract_path = attempt_dir / "attempt-contract.json"
            if not attempt_contract_path.is_file():
                raise RuntimeError(f"persisted attempt has no contract: {attempt_dir}")
            attempt_contract = json.loads(attempt_contract_path.read_text(encoding="utf-8"))
            failure_path = attempt_dir / "failure.json"
            if attempt_contract.get("status") == "validated":
                required = (
                    "result.raw.json",
                    "call-metadata.json",
                    "events.jsonl",
                )
                if not all((attempt_dir / name).is_file() for name in required):
                    raise RuntimeError(f"incomplete successful attempt: {attempt_dir}")
                raw = json.loads((attempt_dir / "result.raw.json").read_text(encoding="utf-8"))
                metadata = json.loads(
                    (attempt_dir / "call-metadata.json").read_text(encoding="utf-8")
                )
                events = (attempt_dir / "events.jsonl").read_text(encoding="utf-8")
                enriched, validation = validator(raw)
                return _complete_call(
                    call_dir=call_dir,
                    call_id=call_id,
                    contract_bytes=contract_bytes,
                    attempt_number=attempt_number,
                    attempt_dir=attempt_dir,
                    raw=raw,
                    enriched=enriched,
                    validation=validation,
                    metadata=metadata,
                    events=events,
                )
            if attempt_contract.get("status") != "failed" or not failure_path.is_file():
                raise RuntimeError(f"invalid persisted attempt state: {attempt_dir}")
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            last_error = str(failure["error"])
            prior_raw_path = attempt_dir / "result.raw.json"
            prior_raw = (
                json.loads(prior_raw_path.read_text(encoding="utf-8"))
                if prior_raw_path.is_file()
                else None
            )
            current_prompt = _repair_prompt(prompt, prior_raw, last_error)
            continue

        raw: dict[str, Any] | None = None
        metadata: dict[str, Any] | None = None
        events: str | None = None
        try:
            raw, metadata, events = _invoke_codex(
                label=f"{call_id}-a{attempt_number}",
                prompt=current_prompt,
                schema_path=schema_path,
            )
            enriched, validation = validator(raw)
        except Exception as exc:
            last_error = _redact(f"{type(exc).__name__}: {exc}")[:2000]
            _persist_attempt(
                attempt_dir,
                prompt=current_prompt,
                raw=raw,
                metadata=metadata,
                events=events,
                error=last_error,
            )
            current_prompt = _repair_prompt(prompt, raw, last_error)
            continue

        _persist_attempt(
            attempt_dir,
            prompt=current_prompt,
            raw=raw,
            metadata=metadata,
            events=events,
            error=None,
        )
        return _complete_call(
            call_dir=call_dir,
            call_id=call_id,
            contract_bytes=contract_bytes,
            attempt_number=attempt_number,
            attempt_dir=attempt_dir,
            raw=raw,
            enriched=enriched,
            validation=validation,
            metadata=metadata,
            events=events,
        )
    raise RuntimeError(f"{call_id} exhausted {MAX_MODEL_ATTEMPTS} same-tier attempts: {last_error}")


def _validate_v1(
    raw: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    contracts: ModuleType,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(raw, dict) or set(raw) != {"selection_summary", "highlights"}:
        raise ValueError("v1 output has unexpected root fields")
    if not isinstance(raw["selection_summary"], str) or not raw["selection_summary"]:
        raise ValueError("v1 selection summary is empty")
    highlights = raw["highlights"]
    if not isinstance(highlights, list) or not 1 <= len(highlights) <= 12:
        raise ValueError("v1 output has invalid highlight count")
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    required = {
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
    seen: set[str] = set()
    enriched = json.loads(json.dumps(raw, ensure_ascii=False))
    for highlight in enriched["highlights"]:
        if not isinstance(highlight, dict) or set(highlight) != required:
            raise ValueError("v1 highlight has unexpected fields")
        candidate_id = highlight.get("candidate_id")
        if candidate_id not in candidates_by_id or candidate_id in seen:
            raise ValueError(f"v1 output has unknown or duplicate ID: {candidate_id!r}")
        seen.add(candidate_id)
        candidate = candidates_by_id[candidate_id]
        highlight["source_start_ms"] = candidate["source_start_ms"]
        highlight["source_end_ms"] = candidate["source_end_ms"]
    audit = contracts.audit_v1_result(enriched, candidates_by_id)
    validation = {
        "schema_candidate_time_gate": "passed",
        "selected_count": len(enriched["highlights"]),
        "unique_candidate_count": len(seen),
        "v2_quote_gate_shadow_audit": audit,
    }
    return enriched, validation


def _assessment_dicts(assessments: Iterable[Any]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in assessments]


def _would_escalate(
    assessments: Sequence[Any], inventory: dict[str, Any], portfolio: dict[str, Any]
) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []
    low_confidence = [
        item.candidate_id
        for item in assessments
        if str(item.assessment_confidence) == "low"
        or getattr(item.assessment_confidence, "value", None) == "low"
    ]
    if assessments and len(low_confidence) / len(assessments) > 0.20:
        reasons.append(
            {
                "code": "TIER1_LOW_CONFIDENCE_RATE",
                "observed": len(low_confidence),
                "threshold": ">20%",
            }
        )
    low_topics = [
        topic["topic_id"]
        for topic in inventory["topics"]
        if topic["cluster_confidence"] == "low" and len(topic["members"]) >= 2
    ]
    if low_topics:
        reasons.append(
            {
                "code": "TIER2_LOW_CONFIDENCE_MULTI_MEMBER_TOPIC",
                "topic_ids": low_topics,
            }
        )
    desired_minimum = min(8, TOP_N)
    if portfolio["selected_count"] < desired_minimum:
        reasons.append(
            {
                "code": "TIER3_THIN_PORTFOLIO",
                "observed": portfolio["selected_count"],
                "threshold": desired_minimum,
            }
        )
    near_threshold = [
        item
        for item in portfolio["ledger"]
        if abs(int(item["quality_score_x100"]) - round(MINIMUM_QUALITY * 100)) <= 300
    ]
    if assessments and len(near_threshold) / len(assessments) >= 0.25:
        reasons.append(
            {
                "code": "TIER3_THRESHOLD_SENSITIVITY",
                "observed": len(near_threshold),
                "threshold": ">=25% within +/-3 points",
            }
        )
    return {
        "policy_version": "shadow-escalation-v1",
        "would_escalate": bool(reasons),
        "target_model_if_enabled": "gpt-5.6-sol/high",
        "actually_escalated": False,
        "reasons": reasons,
    }


def _expected_pipeline_call_ids(
    contract: dict[str, Any], summary: dict[str, Any]
) -> list[str]:
    call_ids = list(contract["required_call_ids"])
    conditional = contract["conditional_call_ids"]
    if contract["skill_version"] == "v2" and int(summary["selected_count"]) > 0:
        call_ids.append(conditional["nonempty_portfolio"])
    if len(call_ids) != len(set(call_ids)):
        raise RuntimeError("pipeline contract contains duplicate call IDs")
    return sorted(call_ids)


def _verify_call_evidence(call_dir: Path) -> str:
    completion_path = call_dir / "complete.json"
    contract_path = call_dir / "call-contract.json"
    if not completion_path.is_file() or not contract_path.is_file():
        raise RuntimeError(f"pipeline call evidence is incomplete: {call_dir}")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if completion.get("call_contract_sha256") != _sha256_path(contract_path):
        raise RuntimeError(f"pipeline call contract receipt drift: {call_dir}")
    attempt_number = completion.get("successful_attempt")
    attempt_contract = call_dir / "attempts" / f"{attempt_number:03d}" / "attempt-contract.json"
    if not attempt_contract.is_file() or completion.get(
        "successful_attempt_contract_sha256"
    ) != _sha256_path(attempt_contract):
        raise RuntimeError(f"pipeline call attempt receipt drift: {call_dir}")
    artifact_hashes = completion.get("artifact_sha256")
    expected_artifacts = {
        "result.raw.json",
        "result.json",
        "validation.json",
        "call-metadata.json",
        "events.jsonl",
    }
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != expected_artifacts:
        raise RuntimeError(f"pipeline call artifact receipt is incomplete: {call_dir}")
    for relative, digest in artifact_hashes.items():
        path = call_dir / relative
        if not path.is_file() or _sha256_path(path) != digest:
            raise RuntimeError(f"pipeline call artifact drift: {path}")
    return _sha256_path(completion_path)


def _pipeline_completion(
    pipeline_dir: Path,
    expected_contract: dict[str, Any],
) -> dict[str, Any] | None:
    complete_path = pipeline_dir / "complete.json"
    if not complete_path.exists():
        return None
    contract_path = pipeline_dir / "pipeline-contract.json"
    if json.loads(contract_path.read_text()) != expected_contract:
        raise RuntimeError(f"pipeline contract drift: {pipeline_dir}")
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if set(complete) != {
        "schema_version",
        "pipeline_id",
        "pipeline_contract_sha256",
        "artifact_sha256",
        "call_receipts",
    } or complete.get("pipeline_id") != expected_contract["pipeline_id"]:
        raise RuntimeError(f"pipeline completion receipt shape/identity drift: {pipeline_dir}")
    if complete.get("pipeline_contract_sha256") != _sha256_path(contract_path):
        raise RuntimeError(f"pipeline contract receipt drift: {pipeline_dir}")
    expected_artifacts = {
        "result.json",
        "validation.json",
        "summary.json",
    }
    if expected_contract["skill_version"] == "v2":
        expected_artifacts.update(
            {
                "tier1-assessments.json",
                "tier1-validation.json",
                "tier2-inventory.json",
                "tier2-validation.json",
                "tier3-portfolio.json",
                "would-escalate.json",
                "repair-budget.json",
            }
        )
    artifact_hashes = complete.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != expected_artifacts:
        raise RuntimeError(f"pipeline artifact receipt is incomplete: {pipeline_dir}")
    for relative, digest in artifact_hashes.items():
        path = pipeline_dir / relative
        if not path.is_file() or _sha256_path(path) != digest:
            raise RuntimeError(f"completed pipeline artifact drift: {path}")
    summary = json.loads((pipeline_dir / "summary.json").read_text(encoding="utf-8"))
    call_ids = _expected_pipeline_call_ids(expected_contract, summary)
    receipts = complete.get("call_receipts")
    expected_receipts = []
    experiment_dir = pipeline_dir.parents[1]
    for call_id in call_ids:
        digest = _verify_call_evidence(experiment_dir / "calls" / call_id)
        expected_receipts.append(
            {"call_id": call_id, "call_completion_sha256": digest}
        )
    if receipts != expected_receipts:
        raise RuntimeError(f"pipeline call receipt drift: {pipeline_dir}")
    return summary


def _finish_pipeline(
    pipeline_dir: Path,
    contract: dict[str, Any],
    artifacts: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    _atomic_write_new(pipeline_dir / "pipeline-contract.json", _pretty_json_bytes(contract))
    encoded = {relative: _pretty_json_bytes(value) for relative, value in artifacts.items()}
    encoded["summary.json"] = _pretty_json_bytes(summary)
    for relative, content in encoded.items():
        _atomic_write_new(pipeline_dir / relative, content)
    experiment_dir = pipeline_dir.parents[1]
    call_receipts = [
        {
            "call_id": call_id,
            "call_completion_sha256": _verify_call_evidence(
                experiment_dir / "calls" / call_id
            ),
        }
        for call_id in _expected_pipeline_call_ids(contract, summary)
    ]
    completion = {
        "schema_version": "1",
        "pipeline_id": contract["pipeline_id"],
        "pipeline_contract_sha256": _sha256_path(pipeline_dir / "pipeline-contract.json"),
        "artifact_sha256": {
            relative: _sha256_bytes(content) for relative, content in sorted(encoded.items())
        },
        "call_receipts": call_receipts,
    }
    _atomic_write_new(pipeline_dir / "complete.json", _pretty_json_bytes(completion))
    return summary


def _expected_pipeline_contract(
    prepared: PreparedExperiment,
    pipeline_id: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    source_id = identity["source_id"]
    evidence = prepared.sources[source_id]
    contract = {
        "schema_version": "1",
        "experiment_contract_sha256": prepared.contract_sha256,
        "pipeline_id": pipeline_id,
        "source_id": source_id,
        "repeat": identity["repeat"],
        "arm_id": identity["arm_id"],
        "skill_version": identity["skill_version"],
        "input_sha256": _sha256_bytes(_pretty_json_bytes(evidence)),
        "fresh_generation": True,
    }
    if identity["skill_version"] == "v2":
        tier1_call_ids = [
            _call_id(pipeline_id, f"v2-tier1-b{batch_number:02d}")
            for batch_number in range(
                1, math.ceil(len(evidence["candidates"]) / TIER1_BATCH_SIZE) + 1
            )
        ]
        contract.update(
            {
                "tier1_batch_size": TIER1_BATCH_SIZE,
                "selection_configuration": prepared.manifest["immutable_contract"][
                    "selection_configuration"
                ],
                "sol_high_execution": False,
                "required_call_ids": [
                    *tier1_call_ids,
                    _call_id(pipeline_id, "v2-tier2-inventory"),
                ],
                "conditional_call_ids": {
                    "nonempty_portfolio": _call_id(pipeline_id, "v2-tier4-copy")
                },
            }
        )
    elif identity["skill_version"] == "v1":
        contract["required_call_ids"] = [_call_id(pipeline_id, "v1-generation")]
        contract["conditional_call_ids"] = {}
    else:
        raise RuntimeError(f"unknown private arm mapping: {pipeline_id}")
    return contract


def _run_v1_pipeline(
    prepared: PreparedExperiment,
    pipeline_id: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    source_id = identity["source_id"]
    evidence = prepared.sources[source_id]
    pipeline_dir = prepared.experiment_dir / "pipelines" / pipeline_id
    pipeline_contract = _expected_pipeline_contract(prepared, pipeline_id, identity)
    _atomic_write_new(
        pipeline_dir / "pipeline-contract.json", _pretty_json_bytes(pipeline_contract)
    )
    resumed = _pipeline_completion(pipeline_dir, pipeline_contract)
    if resumed is not None:
        print(f"RESUME PIPELINE {pipeline_id}", flush=True)
        return resumed
    schema_path = prepared.experiment_dir / f"frozen/schemas/{source_id}/v1.json"
    prompt = _render_v1_prompt(evidence)
    repair_budget = RepairBudget()
    result, validation, metadata = _run_call(
        prepared=prepared,
        pipeline_id=pipeline_id,
        stage="v1-generation",
        prompt=prompt,
        schema_path=schema_path,
        dependency_hashes={
            "input": _sha256_bytes(_pretty_json_bytes(evidence)),
            "runtime_skill": _sha256_path(prepared.experiment_dir / "frozen/runtime/v1-skill.md"),
        },
        validator=lambda raw: _validate_v1(raw, evidence["candidates"], prepared.contracts),
        repair_budget=repair_budget,
    )
    summary = {
        "pipeline_id": pipeline_id,
        "arm_id": identity["arm_id"],
        "source_id": source_id,
        "repeat": identity["repeat"],
        "selected_count": len(result["highlights"]),
        "quote_gate_failed_count": validation["v2_quote_gate_shadow_audit"]["failed_count"],
        "call_elapsed_seconds": metadata["elapsed_seconds"],
        "repair_budget": repair_budget.receipt(),
        "completed_at": metadata["completed_at"],
    }
    return _finish_pipeline(
        pipeline_dir,
        pipeline_contract,
        {"result.json": result, "validation.json": validation},
        summary,
    )


def _run_v2_pipeline(
    prepared: PreparedExperiment,
    pipeline_id: str,
    identity: dict[str, Any],
) -> dict[str, Any]:
    source_id = identity["source_id"]
    evidence = prepared.sources[source_id]
    candidates = evidence["candidates"]
    candidate_ids = [item["candidate_id"] for item in candidates]
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    input_sha = _sha256_bytes(_pretty_json_bytes(evidence))
    pipeline_dir = prepared.experiment_dir / "pipelines" / pipeline_id
    pipeline_contract = _expected_pipeline_contract(prepared, pipeline_id, identity)
    _atomic_write_new(
        pipeline_dir / "pipeline-contract.json", _pretty_json_bytes(pipeline_contract)
    )
    resumed = _pipeline_completion(pipeline_dir, pipeline_contract)
    if resumed is not None:
        print(f"RESUME PIPELINE {pipeline_id}", flush=True)
        return resumed

    assessments: list[Any] = []
    tier1_metadata: list[dict[str, Any]] = []
    repair_budget = RepairBudget()
    for offset in range(0, len(candidates), TIER1_BATCH_SIZE):
        batch_number = offset // TIER1_BATCH_SIZE + 1
        batch = candidates[offset : offset + TIER1_BATCH_SIZE]
        batch_ids = [item["candidate_id"] for item in batch]
        payload = {
            "task": "tier1_candidate_assessment",
            "source": {
                "duration_ms": evidence["source"]["duration_ms"],
                "source_sha256": evidence["source"]["source_sha256"],
                "evidence_note": "Text-only ASR evidence; no video frames are supplied.",
            },
            "batch": {
                "batch_number": batch_number,
                "batch_count": math.ceil(len(candidates) / TIER1_BATCH_SIZE),
                "candidate_count": len(batch),
                "candidates": batch,
            },
        }
        prompt = _render_v2_prompt(prepared.tier_bundles["tier1"], payload)
        schema_path = prepared.experiment_dir / (
            f"frozen/schemas/{source_id}/v2-tier1-b{batch_number:02d}.json"
        )

        def validate_tier1(
            raw: dict[str, Any], expected: list[str] = batch_ids
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            values = prepared.contracts.validate_assessment_batch(raw, expected)
            enriched = {"assessments": _assessment_dicts(values)}
            return enriched, {
                "candidate_order_gate": "passed",
                "candidate_count": len(values),
            }

        result, validation, metadata = _run_call(
            prepared=prepared,
            pipeline_id=pipeline_id,
            stage=f"v2-tier1-b{batch_number:02d}",
            prompt=prompt,
            schema_path=schema_path,
            dependency_hashes={
                "source_input": input_sha,
                "batch_input": _sha256_bytes(_canonical_bytes(batch)),
                "runtime_bundle": _sha256_bytes(prepared.tier_bundles["tier1"].encode("utf-8")),
            },
            validator=validate_tier1,
            repair_budget=repair_budget,
        )
        parsed = prepared.contracts.validate_assessment_batch(result, batch_ids)
        assessments.extend(parsed)
        tier1_metadata.append(
            {
                "batch_number": batch_number,
                "validation": validation,
                "call_metadata": metadata,
            }
        )
    prepared.contracts.validate_complete_assessments(assessments, candidate_ids)
    assessment_values = _assessment_dicts(assessments)
    assessment_sha = _sha256_bytes(_canonical_bytes(assessment_values))

    tier2_payload = {
        "task": "tier2_free_topic_inventory",
        "source": {
            "duration_ms": evidence["source"]["duration_ms"],
            "source_sha256": evidence["source"]["source_sha256"],
            "evidence_note": "Text-only ASR evidence; no video frames are supplied.",
        },
        "candidates": candidates,
        "tier1_assessments": assessment_values,
    }
    tier2_prompt = _render_v2_prompt(prepared.tier_bundles["tier2"], tier2_payload)
    tier2_schema = prepared.experiment_dir / (f"frozen/schemas/{source_id}/v2-tier2.json")

    def validate_tier2(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        inventory = prepared.contracts.validate_and_enrich_inventory(raw, assessments)
        return inventory, {
            "all_candidate_accounting_gate": "passed",
            "accounting": inventory["accounting"],
            "topic_count": len(inventory["topics"]),
        }

    inventory, tier2_validation, tier2_metadata = _run_call(
        prepared=prepared,
        pipeline_id=pipeline_id,
        stage="v2-tier2-inventory",
        prompt=tier2_prompt,
        schema_path=tier2_schema,
        dependency_hashes={
            "source_input": input_sha,
            "tier1_assessments": assessment_sha,
            "runtime_bundle": _sha256_bytes(prepared.tier_bundles["tier2"].encode("utf-8")),
        },
        validator=validate_tier2,
        repair_budget=repair_budget,
    )

    portfolio = prepared.contracts.select_portfolio(
        candidates,
        assessments,
        inventory,
        top_n=TOP_N,
        minimum_quality=MINIMUM_QUALITY,
        maximum_interval_iou=MAXIMUM_INTERVAL_IOU,
        maximum_text_jaccard=MAXIMUM_TEXT_JACCARD,
    )
    escalation = _would_escalate(assessments, inventory, portfolio)
    selected_ids = [item["candidate_id"] for item in portfolio["selected"]]
    selected_payload = []
    assessment_by_id = {item.candidate_id: item for item in assessments}
    for selected in portfolio["selected"]:
        candidate_id = selected["candidate_id"]
        selected_payload.append(
            {
                "candidate": candidates_by_id[candidate_id],
                "assessment": assessment_by_id[candidate_id].model_dump(mode="json"),
                "selection": selected,
            }
        )
    tier4_payload = {
        "task": "tier4_editorial_copy",
        "source": {
            "duration_ms": evidence["source"]["duration_ms"],
            "source_sha256": evidence["source"]["source_sha256"],
            "evidence_note": "Text-only ASR evidence; no video frames are supplied.",
        },
        "selected_candidates_in_required_order": selected_payload,
    }
    tier4_prompt = _render_v2_prompt(prepared.tier_bundles["tier4"], tier4_payload)
    tier4_schema = prepared.experiment_dir / (f"frozen/schemas/{source_id}/v2-tier4.json")

    def validate_tier4(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        copies, receipts = prepared.contracts.validate_editorial_copies(
            raw, selected_ids, candidates_by_id
        )
        final_result = prepared.contracts.compose_final_result(
            candidates=candidates,
            assessments=assessments,
            inventory=inventory,
            portfolio=portfolio,
            copies=copies,
            receipts=receipts,
        )
        return final_result, {
            "selected_order_gate": "passed",
            "exact_quote_gate": "passed",
            "receipt_count": len(receipts),
            "receipts": receipts,
        }

    if selected_ids:
        final_result, tier4_validation, tier4_metadata = _run_call(
            prepared=prepared,
            pipeline_id=pipeline_id,
            stage="v2-tier4-copy",
            prompt=tier4_prompt,
            schema_path=tier4_schema,
            dependency_hashes={
                "source_input": input_sha,
                "tier1_assessments": assessment_sha,
                "tier2_inventory": _sha256_bytes(_canonical_bytes(inventory)),
                "tier3_portfolio": _sha256_bytes(_canonical_bytes(portfolio)),
                "runtime_bundle": _sha256_bytes(
                    prepared.tier_bundles["tier4"].encode("utf-8")
                ),
            },
            validator=validate_tier4,
            repair_budget=repair_budget,
        )
    else:
        final_result, tier4_validation = validate_tier4(
            {
                "selection_summary": "没有候选达到冻结的确定性质量与去重门槛。",
                "copies": [],
            }
        )
        tier4_validation["status"] = "skipped_empty_portfolio"
        tier4_metadata = {
            "status": "skipped_empty_portfolio",
            "model_call_count": 0,
            "elapsed_seconds": 0.0,
            "completed_at": tier2_metadata["completed_at"],
        }
    summary = {
        "pipeline_id": pipeline_id,
        "arm_id": identity["arm_id"],
        "source_id": source_id,
        "repeat": identity["repeat"],
        "selected_count": len(final_result["highlights"]),
        "topic_count": len(inventory["topics"]),
        "exact_quote_failed_count": 0,
        "would_escalate": escalation,
        "repair_budget": repair_budget.receipt(),
        "tier_call_elapsed_seconds": {
            "tier1": round(
                sum(item["call_metadata"]["elapsed_seconds"] for item in tier1_metadata),
                3,
            ),
            "tier2": tier2_metadata["elapsed_seconds"],
            "tier4": tier4_metadata["elapsed_seconds"],
        },
        "completed_at": tier4_metadata["completed_at"],
    }
    artifacts = {
        "tier1-assessments.json": {"assessments": assessment_values},
        "tier1-validation.json": {"batches": tier1_metadata},
        "tier2-inventory.json": inventory,
        "tier2-validation.json": tier2_validation,
        "tier3-portfolio.json": portfolio,
        "would-escalate.json": escalation,
        "repair-budget.json": repair_budget.receipt(),
        "result.json": final_result,
        "validation.json": tier4_validation,
    }
    return _finish_pipeline(pipeline_dir, pipeline_contract, artifacts, summary)


def _completed_pipeline_summaries(
    prepared: PreparedExperiment,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    private_pipelines = prepared.private_map["pipeline_id_to_identity"]
    for pair in prepared.public_plan["schedule"]:
        for item in pair["pipelines"]:
            pipeline_id = item["pipeline_id"]
            identity = private_pipelines[pipeline_id]
            summary = _pipeline_completion(
                prepared.experiment_dir / "pipelines" / pipeline_id,
                _expected_pipeline_contract(prepared, pipeline_id, identity),
            )
            if summary is not None:
                summaries.append(summary)
    return summaries


def _current_run_summary(
    prepared: PreparedExperiment,
    *,
    invocation_scope: str,
    scheduled_pipeline_count: int,
) -> dict[str, Any]:
    summaries = _completed_pipeline_summaries(prepared)
    expected = prepared.public_plan["pipeline_count"]
    completed = len(summaries)
    return {
        "schema_version": "1",
        "experiment_id": prepared.experiment_id,
        "experiment_contract_sha256": prepared.contract_sha256,
        "status": ("generation_completed" if completed == expected else "generation_partial"),
        "invocation_scope": invocation_scope,
        "scheduled_pipeline_count_this_invocation": scheduled_pipeline_count,
        "completed_pipeline_count": completed,
        "expected_pipeline_count": expected,
        "remaining_pipeline_count": expected - completed,
        "completed_pipelines": summaries,
        "sol_high_call_count": 0,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _run_experiment(prepared: PreparedExperiment, *, sentinel: bool = False) -> dict[str, Any]:
    private_pipelines = prepared.private_map["pipeline_id_to_identity"]
    selected_pairs = (
        prepared.public_plan["schedule"][:1] if sentinel else prepared.public_plan["schedule"]
    )
    scheduled_pipeline_count = sum(len(pair["pipelines"]) for pair in selected_pairs)
    invocation_scope = "sentinel_pair" if sentinel else "full_matrix"
    for pair in selected_pairs:
        if sentinel and len(pair["pipelines"]) != 2:
            raise RuntimeError("sentinel pair must contain exactly two opaque arms")
        for item in pair["pipelines"]:
            pipeline_id = item["pipeline_id"]
            identity = private_pipelines[pipeline_id]
            if identity["skill_version"] == "v1":
                _run_v1_pipeline(prepared, pipeline_id, identity)
            elif identity["skill_version"] == "v2":
                _run_v2_pipeline(prepared, pipeline_id, identity)
            else:
                raise RuntimeError(f"unknown private arm mapping: {pipeline_id}")
            progress = _current_run_summary(
                prepared,
                invocation_scope=invocation_scope,
                scheduled_pipeline_count=scheduled_pipeline_count,
            )
            _atomic_replace_derived(
                prepared.experiment_dir / "run-summary.json",
                _pretty_json_bytes(progress),
            )
    final = _current_run_summary(
        prepared,
        invocation_scope=invocation_scope,
        scheduled_pipeline_count=scheduled_pipeline_count,
    )
    _atomic_replace_derived(prepared.experiment_dir / "run-summary.json", _pretty_json_bytes(final))
    return final


def _dry_run_summary(prepared: PreparedExperiment, *, sentinel: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "experiment_id": prepared.experiment_id,
        "experiment_dir": str(prepared.experiment_dir),
        "contract_sha256": prepared.contract_sha256,
        "dry_run": True,
        "model_calls": 0,
        "unique_sources": len(prepared.sources),
        "repeats_per_source": REPEATS_PER_SOURCE,
        "planned_pipelines": prepared.public_plan["pipeline_count"],
        "execution_scope_if_started": "sentinel_pair" if sentinel else "full_matrix",
        "pipelines_if_started": (
            len(prepared.public_plan["schedule"][0]["pipelines"])
            if sentinel
            else prepared.public_plan["pipeline_count"]
        ),
        "planned_v1_model_calls": len(prepared.sources) * REPEATS_PER_SOURCE,
        "planned_v2_model_calls_before_repairs": sum(
            math.ceil(len(evidence["candidates"]) / TIER1_BATCH_SIZE) + 2
            for evidence in prepared.sources.values()
        )
        * REPEATS_PER_SOURCE,
        "sol_high_call_count": 0,
        "message": "Immutable inputs and plan verified; no model was invoked.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze or run the isolated three-source, two-repeat fresh v1-v2 "
            "Highlight Agent Skill experiment."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="freeze/verify the immutable experiment only; make zero model calls",
    )
    parser.add_argument(
        "--sentinel",
        action="store_true",
        help=(
            "run only the first frozen source/repeat pair (both v1 and v2 arms); "
            "a later invocation without this flag resumes the remaining matrix"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help=(
            "experiment parent directory (default: the v2 research experiments directory); "
            "the derived experiment ID is appended automatically"
        ),
    )
    args = parser.parse_args()
    output_root = _validate_output_root(args.output_root)
    prepared = _prepare_experiment(output_root)
    result = (
        _dry_run_summary(prepared, sentinel=args.sentinel)
        if args.dry_run
        else _run_experiment(prepared, sentinel=args.sentinel)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
