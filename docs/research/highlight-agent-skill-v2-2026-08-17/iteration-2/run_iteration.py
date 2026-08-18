#!/usr/bin/env python3
"""Run the immutable, isolated Highlight Agent Skill iteration-2 experiment.

This is a research-only runner.  It reads the three already-frozen benchmark
evidence files and writes only beneath an explicitly validated experiment
root.  It never opens source media, product databases, or production assets.

The main comparison is deliberately narrow: fresh v1 and iteration-2
generations both use gpt-5.6-sol at medium reasoning effort.  The contender has
one all-candidate CombinedDiscovery call, deterministic adaptive portfolio
selection, and at most one SelectedCopy call.  Sol High is never called.

``--dry-run`` freezes and verifies the complete experiment plan but does not
invoke a model.  Re-running without ``--dry-run`` resumes only byte-identical,
hash-bound artifacts.  There is intentionally no force/overwrite option.
"""

from __future__ import annotations

import argparse
import hashlib
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
ITERATION_DIR = Path(__file__).resolve().parent
RESEARCH_ROOT = ITERATION_DIR.parent
PRIOR_BENCHMARK_DIR = ROOT / "docs/research/model-benchmark-2026-08-17"
CONTRACTS_PATH = ITERATION_DIR / "contracts.py"
INPUT_GATE_PATH = ITERATION_DIR / "input_gate.py"
EVALUATION_CONTRACT_PATH = ITERATION_DIR / "evaluation-contract.json"
V1_SKILL_PATH = PRIOR_BENCHMARK_DIR / "agent-v1/SKILL.md"
V1_SCHEMA_PATH = PRIOR_BENCHMARK_DIR / "schemas/highlight-output.schema.json"
V2_SKILL_DIR = ITERATION_DIR / "agent"
DEFAULT_OUTPUT_ROOT = ITERATION_DIR / "experiments"

CONTRACTS_RELATIVE_PATH = str(CONTRACTS_PATH.relative_to(ROOT))
INPUT_GATE_RELATIVE_PATH = str(INPUT_GATE_PATH.relative_to(ROOT))
RUNNER_RELATIVE_PATH = str(Path(__file__).resolve().relative_to(ROOT))
V1_SKILL_RELATIVE_PATH = str(V1_SKILL_PATH.relative_to(ROOT))
V1_SCHEMA_RELATIVE_PATH = str(V1_SCHEMA_PATH.relative_to(ROOT))
V2_SKILL_RELATIVE_ROOT = str(V2_SKILL_DIR.relative_to(ROOT))

RUNNER_VERSION = "liveclip-highlight-v1-v2-runner.iteration-2"
PROTOCOL_SEED = "liveclip-highlight-v2-ab-iteration-2-order-v1"
MODEL_CONFIG = {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}
REPEATS_PER_SOURCE = 2
DESIRED_MINIMUM = 8
MAXIMUM_COUNT = 12
BASE_MINIMUM_QUALITY = 65.0
MAXIMUM_INTERVAL_IOU = 0.45
MAXIMUM_TEXT_JACCARD = 0.65
MAX_MODEL_ATTEMPTS = 2
MAX_PIPELINE_REPAIRS = 1
PREFLIGHT_POLICY_VERSION = "codex-local-app-server-preflight-v2"
MAX_PREFLIGHT_FAILURES = 3
MAX_CALL_INFRASTRUCTURE_FAILURES = 3
PREFLIGHT_TIMEOUT_SECONDS = 20

PREFLIGHT_NONZERO_FAILURE_CATEGORIES = frozenset(
    {
        "infrastructure_permission_denied",
        "infrastructure_app_server_initialization",
        "infrastructure_state_initialization",
        "infrastructure_configuration",
        "infrastructure_preflight_process_failure",
    }
)
PREFLIGHT_NONE_FAILURE_CATEGORIES = frozenset(
    {
        "infrastructure_preflight_invalid_utf8",
        "infrastructure_preflight_timeout",
        "infrastructure_preflight_spawn_failure",
    }
)
CALL_NONZERO_INFRASTRUCTURE_CATEGORIES = frozenset(
    {
        "infrastructure_permission_denied",
        "infrastructure_app_server_initialization",
        "infrastructure_state_initialization",
        "infrastructure_configuration",
        "infrastructure_pre_model_process_failure",
    }
)
CALL_NONE_INFRASTRUCTURE_CATEGORIES = frozenset(
    {"infrastructure_process_timeout", "infrastructure_spawn_failure"}
)

REQUIRED_EVALUATION_ARTIFACTS = frozenset(
    {
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
)


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
    input_gate: ModuleType
    sources: dict[str, dict[str, Any]]
    source_specs: dict[str, SourceSpec]
    public_plan: dict[str, Any]
    private_map: dict[str, Any]
    v1_skill_text: str
    stage_bundles: dict[str, str]


@dataclass(frozen=True)
class EvaluationMaterials:
    contract: dict[str, Any]
    contract_bytes: bytes
    contract_sha256: str
    artifact_bytes: dict[str, bytes]


@dataclass(frozen=True)
class JsonReceiptSnapshot:
    relative_path: str
    content: bytes
    value: dict[str, Any]


class CodexProcessFailure(RuntimeError):
    """A classified Codex process failure with explicit model-start evidence."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        model_started: bool,
        returncode: int | None,
        stdout: str = "",
        stderr: str = "",
        attempt_metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.model_started = model_started
        self.returncode = returncode
        self.stdout_evidence = _redact(stdout)
        self.stdout_tail = _redact(stdout)[-3000:]
        self.stderr_tail = _redact(stderr)[-3000:]
        self.attempt_metadata = attempt_metadata


class CodexInfrastructureUnavailable(RuntimeError):
    """Raised after an immutable zero-model infrastructure receipt is saved."""


class PermanentModelOutputError(RuntimeError):
    """A model-started identity or safety violation that must never be repaired."""

    def __init__(self, message: str, *, category: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass
class RepairBudget:
    maximum_repairs: int = MAX_PIPELINE_REPAIRS
    used_by_stage: list[str] | None = None

    def __post_init__(self) -> None:
        if self.used_by_stage is None:
            self.used_by_stage = []

    def consume(self, stage: str) -> None:
        assert self.used_by_stage is not None
        if stage in self.used_by_stage:
            raise RuntimeError(
                f"same-stage repair already used for {stage}; no second repair is permitted"
            )
        if len(self.used_by_stage) >= self.maximum_repairs:
            raise RuntimeError(
                "pipeline repair budget exhausted; no additional model call is permitted"
            )
        self.used_by_stage.append(stage)

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


def _json_receipt_snapshot(path: Path, *, relative_path: str, label: str) -> JsonReceiptSnapshot:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is missing or unsafe: {path}")
    content = path.read_bytes()
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object: {path}")
    return JsonReceiptSnapshot(
        relative_path=relative_path,
        content=content,
        value=value,
    )


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


def _skill_body_text(value: str, label: str) -> str:
    if not value.startswith("---\n"):
        raise RuntimeError(f"runtime Skill has no YAML frontmatter: {label}")
    marker = value.find("\n---\n", 4)
    if marker < 0:
        raise RuntimeError(f"runtime Skill frontmatter is not closed: {label}")
    return value[marker + 5 :].lstrip("\n")


def _skill_body(path: Path) -> str:
    return _skill_body_text(path.read_text(encoding="utf-8"), str(path))


def _verified_material_bytes(materials: EvaluationMaterials, relative_name: str) -> bytes:
    artifacts = materials.contract.get("artifacts")
    receipt = artifacts.get(relative_name) if isinstance(artifacts, dict) else None
    content = materials.artifact_bytes.get(relative_name)
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"sha256", "size_bytes"}
        or content is None
        or len(content) != receipt.get("size_bytes")
        or _sha256_bytes(content) != receipt.get("sha256")
    ):
        raise RuntimeError(f"verified evaluation material drift: {relative_name}")
    return content


def _execute_verified_module(
    *, module_role: str, content: bytes, source_label: str, required: Sequence[str]
) -> ModuleType:
    digest = _sha256_bytes(content)
    module_name = f"liveclip_highlight_agent_{module_role}_{digest[:16]}"
    module = ModuleType(module_name)
    module.__file__ = source_label
    module.__package__ = ""
    sys.modules[module_name] = module
    try:
        code = compile(content, source_label, "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception:
        if sys.modules.get(module_name) is module:
            del sys.modules[module_name]
        raise
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(
            f"{module_role} interface is incomplete; fail closed until adapted: "
            + ", ".join(missing)
        )
    return module


CONTRACTS_INTERFACE = (
    "CombinedDiscovery",
    "SelectedCopyBatchIteration2",
    "validate_combined_discovery",
    "select_adaptive_portfolio",
    "validate_selected_copies_iteration2",
    "exact_quote_receipt",
    "compose_iteration2_result",
    "audit_v1_result",
    "CONTRACT_VERSION",
)
INPUT_GATE_INTERFACE = (
    "INPUT_GATE_VERSION",
    "validate_frozen_evidence",
    "evidence_set_sha256",
    "validate_combined_payload_capacity",
    "canonical_json_bytes",
    "MAX_COMBINED_PAYLOAD_BYTES",
)


def _load_contracts(materials: EvaluationMaterials) -> ModuleType:
    return _execute_verified_module(
        module_role="v2_contracts_runtime",
        content=_verified_material_bytes(materials, CONTRACTS_RELATIVE_PATH),
        source_label=f"evaluation://{CONTRACTS_RELATIVE_PATH}",
        required=CONTRACTS_INTERFACE,
    )


def _load_input_gate(materials: EvaluationMaterials) -> ModuleType:
    return _execute_verified_module(
        module_role="v2_input_gate_runtime",
        content=_verified_material_bytes(materials, INPUT_GATE_RELATIVE_PATH),
        source_label=f"evaluation://{INPUT_GATE_RELATIVE_PATH}",
        required=INPUT_GATE_INTERFACE,
    )


def _load_v2_stage_bundles(
    materials: EvaluationMaterials,
) -> tuple[dict[str, str], dict[str, str]]:
    skill_relative = f"{V2_SKILL_RELATIVE_ROOT}/SKILL.md"
    skill_text = _verified_material_bytes(materials, skill_relative).decode("utf-8")
    body = _skill_body_text(skill_text, skill_relative)
    bundles: dict[str, str] = {}
    paths: dict[str, str] = {}
    common_references = {
        "atomic-scoring": f"{V2_SKILL_RELATIVE_ROOT}/references/atomic-scoring.md",
        "risk-and-repair": f"{V2_SKILL_RELATIVE_ROOT}/references/risk-and-repair.md",
    }
    stage_references = {
        "combined-discovery": (f"{V2_SKILL_RELATIVE_ROOT}/references/combined-discovery.md"),
        "selected-copy": f"{V2_SKILL_RELATIVE_ROOT}/references/selected-copy.md",
    }
    stage_common = {
        "combined-discovery": ("atomic-scoring", "risk-and-repair"),
        "selected-copy": ("risk-and-repair",),
    }
    for stage, reference_relative in stage_references.items():
        reference_text = _verified_material_bytes(materials, reference_relative).decode("utf-8")
        paths[stage] = reference_relative
        bundle = (
            body.rstrip()
            + "\n\n<task_tier_contract>\n"
            + reference_text.strip()
            + "\n</task_tier_contract>\n"
        )
        for common_label in stage_common[stage]:
            common_relative = common_references[common_label]
            common_text = _verified_material_bytes(materials, common_relative).decode("utf-8")
            paths[f"{stage}:{common_label}"] = common_relative
            bundle += (
                f'\n<supporting_contract name="{common_label}">\n'
                + common_text.strip()
                + "\n</supporting_contract>\n"
            )
        bundles[stage] = bundle
    return bundles, paths


def _package_hashes_from_materials(
    materials: EvaluationMaterials,
) -> dict[str, str]:
    prefix = f"{V2_SKILL_RELATIVE_ROOT}/"
    package_hashes = {
        relative_name.removeprefix(prefix): _sha256_bytes(
            _verified_material_bytes(materials, relative_name)
        )
        for relative_name in sorted(materials.artifact_bytes)
        if relative_name.startswith(prefix)
    }
    if not package_hashes:
        raise RuntimeError("verified v2 Skill package is empty")
    return package_hashes


def _verify_evaluation_artifact_index(
    contract: dict[str, Any],
) -> dict[str, bytes]:
    artifacts = contract.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise RuntimeError("iteration-2 evaluation contract artifact index is missing")
    missing = sorted(REQUIRED_EVALUATION_ARTIFACTS.difference(artifacts))
    if missing:
        raise RuntimeError(
            f"iteration-2 evaluation contract artifact index is incomplete: {missing}"
        )
    repository_root = ROOT.resolve(strict=True)
    artifact_bytes: dict[str, bytes] = {}
    for relative_name, receipt in sorted(artifacts.items()):
        if not isinstance(relative_name, str):
            raise RuntimeError("evaluation artifact path must be a repository-relative string")
        relative = PurePosixPath(relative_name)
        if (
            relative.is_absolute()
            or not relative.parts
            or relative.as_posix() != relative_name
            or "\\" in relative_name
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise RuntimeError(f"evaluation artifact path escapes repository: {relative_name!r}")
        if (
            not isinstance(receipt, dict)
            or set(receipt) != {"sha256", "size_bytes"}
            or not isinstance(receipt.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"]) is None
            or not isinstance(receipt.get("size_bytes"), int)
            or isinstance(receipt.get("size_bytes"), bool)
            or receipt["size_bytes"] < 0
        ):
            raise RuntimeError(f"evaluation artifact receipt is malformed: {relative_name}")
        artifact_path = repository_root.joinpath(*relative.parts)
        current = repository_root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise RuntimeError(
                    f"evaluation artifact cannot traverse a symlink: {relative_name}"
                )
        try:
            resolved = artifact_path.resolve(strict=True)
            resolved.relative_to(repository_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"evaluation artifact is missing or escapes repository: {relative_name}"
            ) from exc
        if not resolved.is_file():
            raise RuntimeError(f"evaluation artifact is not a regular file: {relative_name}")
        content = resolved.read_bytes()
        if len(content) != receipt["size_bytes"]:
            raise RuntimeError(f"evaluation artifact size drift: {relative_name}")
        if _sha256_bytes(content) != receipt["sha256"]:
            raise RuntimeError(f"evaluation artifact hash drift: {relative_name}")
        artifact_bytes[relative_name] = content
    return artifact_bytes


EVALUATION_CONTRACT_IDENTITY = {
    "schema_version": "liveclip-highlight-evaluation-contract.iteration-2.v1",
    "contract_version": "highlight-agent-skill-v2-iteration-2-evaluation-v1",
    "iteration_id": "highlight-agent-skill-v2-iteration-2",
    "status": "frozen_before_any_iteration2_generator_output",
    "human_review_mode": "diagnostic_not_required",
}


def _validate_evaluation_contract_identity(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError("iteration-2 evaluation contract must be a non-empty JSON object")
    for field, expected in EVALUATION_CONTRACT_IDENTITY.items():
        if raw.get(field) != expected:
            raise RuntimeError(f"iteration-2 evaluation contract {field} must equal {expected!r}")
    return raw


def _load_evaluation_materials() -> EvaluationMaterials:
    if not EVALUATION_CONTRACT_PATH.is_file() or EVALUATION_CONTRACT_PATH.is_symlink():
        raise RuntimeError(
            f"iteration-2 evaluation contract is missing or unsafe: {EVALUATION_CONTRACT_PATH}"
        )
    raw_bytes = EVALUATION_CONTRACT_PATH.read_bytes()
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("iteration-2 evaluation contract is unreadable") from exc
    contract = _validate_evaluation_contract_identity(raw)
    artifact_bytes = _verify_evaluation_artifact_index(contract)
    return EvaluationMaterials(
        contract=contract,
        contract_bytes=raw_bytes,
        contract_sha256=_sha256_bytes(raw_bytes),
        artifact_bytes=artifact_bytes,
    )


def _load_evaluation_contract() -> tuple[dict[str, Any], bytes, str]:
    materials = _load_evaluation_materials()
    return materials.contract, materials.contract_bytes, materials.contract_sha256


def _combined_discovery_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "iteration_2_combined_discovery",
        "source": {
            "duration_ms": evidence["source"]["duration_ms"],
            "source_sha256": evidence["source"]["source_sha256"],
            "evidence_note": "Text-only ASR evidence; no video frames are supplied.",
        },
        "candidate_count": len(evidence["candidates"]),
        "candidates_in_required_order": evidence["candidates"],
    }


def _validate_frozen_source(spec: SourceSpec, input_gate: ModuleType) -> tuple[dict[str, Any], str]:
    path = ROOT / spec.relative_input_path
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"frozen evidence is missing or unsafe: {path}")
    raw_bytes = path.read_bytes()
    if _sha256_bytes(raw_bytes) != spec.expected_frozen_input_sha256:
        raise RuntimeError(f"frozen evidence hash changed: {spec.case_id}")
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid frozen evidence JSON: {spec.case_id}") from exc
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


def _frozen_v1_schema(candidate_ids: Sequence[str], base_schema_bytes: bytes) -> dict[str, Any]:
    schema = json.loads(base_schema_bytes.decode("utf-8"))
    if not isinstance(schema, dict):
        raise RuntimeError("verified v1 base Schema must be a JSON object")
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


def _safe_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key.upper() in SAFE_ENV_KEYS}


def _disabled_feature_args() -> list[str]:
    return [value for name in DISABLED_FEATURES for value in ("--disable", name)]


def _codex_preflight_command() -> list[str]:
    """Initialize the local app-server runtime without creating a model turn."""

    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("codex CLI is unavailable")
    return [
        executable,
        "--ask-for-approval",
        "never",
        "--sandbox",
        "read-only",
        *_disabled_feature_args(),
        "-c",
        "features.shell_tool=false",
        "-c",
        "features.unified_exec=false",
        "-c",
        "features.multi_agent=false",
        "-c",
        'web_search="disabled"',
        "app-server",
        "--listen",
        "stdio://",
        "--strict-config",
    ]


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
        RESEARCH_ROOT / "experiments",
        RESEARCH_ROOT / "reports",
        RESEARCH_ROOT / "eval-review",
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


def _prepare_experiment(
    output_root: Path,
    *,
    evaluation_materials: EvaluationMaterials | None = None,
) -> PreparedExperiment:
    materials = evaluation_materials or _load_evaluation_materials()
    contracts_bytes = _verified_material_bytes(materials, CONTRACTS_RELATIVE_PATH)
    input_gate_bytes = _verified_material_bytes(materials, INPUT_GATE_RELATIVE_PATH)
    runner_bytes = _verified_material_bytes(materials, RUNNER_RELATIVE_PATH)
    v1_skill_bytes = _verified_material_bytes(materials, V1_SKILL_RELATIVE_PATH)
    v1_schema_bytes = _verified_material_bytes(materials, V1_SCHEMA_RELATIVE_PATH)
    contracts = _load_contracts(materials)
    input_gate = _load_input_gate(materials)
    stage_bundles, stage_reference_paths = _load_v2_stage_bundles(materials)
    evaluation_contract = materials.contract
    evaluation_contract_bytes = materials.contract_bytes
    evaluation_contract_sha256 = materials.contract_sha256
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
        "study": "fresh-v1-iteration2-same-model-minimum-matrix",
        "iteration": 2,
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
        "pipeline_topology": {
            "v1": ["single_fresh_generation"],
            "v2": [
                "combined_discovery_all_candidates",
                "deterministic_adaptive_portfolio",
                "selected_copy_if_nonempty",
                "deterministic_exact_quote_and_source_sentence_gate",
            ],
        },
        "normal_model_call_limit_per_v2_pipeline": 2,
        "sol_high_policy": "disabled",
        "schedule": schedule,
        "arm_mapping_commitment_sha256": _sha256_bytes(private_bytes),
    }
    codex_cli = _codex_identity()
    preflight_command = _codex_preflight_command()
    preflight_policy = {
        "policy_version": PREFLIGHT_POLICY_VERSION,
        "probe": "local_app_server_stdio_eof",
        "model_requests": 0,
        "command_sha256": _sha256_bytes(_canonical_bytes(preflight_command)),
        "timeout_seconds": PREFLIGHT_TIMEOUT_SECONDS,
        "maximum_failed_checks": MAX_PREFLIGHT_FAILURES,
        "maximum_pre_model_failures_per_call": MAX_CALL_INFRASTRUCTURE_FAILURES,
        "environment": "same_allowlist_as_model_process",
        "tool_policy": "same_disabled_feature_set; read-only sandbox",
    }

    expected_files: dict[str, bytes] = {
        "frozen/public-plan.json": _pretty_json_bytes(public_plan),
        "frozen/evaluation-contract.json": evaluation_contract_bytes,
        "private/arm-map.private.json": private_bytes,
        "frozen/runtime/v1-skill.md": v1_skill_bytes,
        "frozen/runtime/v2-combined-discovery-bundle.md": stage_bundles[
            "combined-discovery"
        ].encode("utf-8"),
        "frozen/runtime/v2-selected-copy-bundle.md": stage_bundles["selected-copy"].encode("utf-8"),
        "frozen/gates/contracts.py": contracts_bytes,
        "frozen/gates/input_gate.py": input_gate_bytes,
        "frozen/runtime/codex-preflight-policy.json": _pretty_json_bytes(preflight_policy),
    }
    schema_hashes: dict[str, dict[str, str]] = {}
    source_contracts: list[dict[str, Any]] = []
    for spec in SOURCE_SPECS:
        evidence = sources[spec.source_id]
        candidate_ids = [item["candidate_id"] for item in evidence["candidates"]]
        evidence_bytes = _pretty_json_bytes(evidence)
        expected_files[f"frozen/inputs/{spec.source_id}.json"] = evidence_bytes
        combined_payload = _combined_discovery_payload(evidence)
        combined_payload_size = input_gate.validate_combined_payload_capacity(combined_payload)
        schemas = {
            "v1": _frozen_v1_schema(candidate_ids, v1_schema_bytes),
            "combined-discovery": _schema_from_model(contracts.CombinedDiscovery, candidate_ids),
            "selected-copy": _schema_from_model(
                contracts.SelectedCopyBatchIteration2, candidate_ids
            ),
        }
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
                "input_gate_sha256": _sha256_bytes(input_gate_bytes),
                "input_gate_version": str(input_gate.INPUT_GATE_VERSION),
                "evidence_set_sha256": evidence_set_hashes[spec.source_id],
                "candidate_order_sha256": _sha256_bytes(_canonical_bytes(candidate_ids)),
                "candidate_count": len(candidate_ids),
                "combined_payload_sha256": _sha256_bytes(_canonical_bytes(combined_payload)),
                "combined_payload_size_bytes": combined_payload_size,
                "combined_payload_maximum_bytes": int(input_gate.MAX_COMBINED_PAYLOAD_BYTES),
                "schema_sha256": schema_hashes[spec.source_id],
            }
        )

    runner_sha = _sha256_bytes(runner_bytes)
    package_hashes = _package_hashes_from_materials(materials)
    contract_payload = {
        "schema_version": "1",
        "runner_version": RUNNER_VERSION,
        "runner_sha256": runner_sha,
        "contracts_sha256": _sha256_bytes(contracts_bytes),
        "contracts_version": str(contracts.CONTRACT_VERSION),
        "evaluation_contract_sha256": evaluation_contract_sha256,
        "evaluation_contract_version": evaluation_contract["contract_version"],
        "input_gate_sha256": _sha256_bytes(input_gate_bytes),
        "input_gate_version": str(input_gate.INPUT_GATE_VERSION),
        "v1_skill_sha256": _sha256_bytes(v1_skill_bytes),
        "v1_base_schema_sha256": _sha256_bytes(v1_schema_bytes),
        "v2_skill_package_sha256": package_hashes,
        "v2_stage_bundle_sha256": {
            stage: _sha256_bytes(bundle.encode("utf-8"))
            for stage, bundle in sorted(stage_bundles.items())
        },
        "v2_stage_reference_paths": stage_reference_paths,
        "public_plan_sha256": _sha256_bytes(expected_files["frozen/public-plan.json"]),
        "arm_mapping_commitment_sha256": _sha256_bytes(private_bytes),
        "sources": source_contracts,
        "model": MODEL_CONFIG,
        "selection_configuration": {
            "desired_minimum": DESIRED_MINIMUM,
            "maximum_count": MAXIMUM_COUNT,
            "base_minimum_quality": BASE_MINIMUM_QUALITY,
            "maximum_interval_iou": MAXIMUM_INTERVAL_IOU,
            "maximum_text_jaccard": MAXIMUM_TEXT_JACCARD,
        },
        "repair_policy": {
            "maximum_attempts_per_model_call": MAX_MODEL_ATTEMPTS,
            "maximum_repairs_per_stage": 1,
            "maximum_repairs_per_pipeline": MAX_PIPELINE_REPAIRS,
            "repair_returns_to_same_stage": True,
            "all_model_started_attempt_costs_completion_bound": True,
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
        "runtime_preflight": preflight_policy,
        "codex_cli": codex_cli,
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
        _regular_json_object(manifest_path, "experiment manifest")
        if manifest_path.read_bytes() != manifest_bytes:
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
        input_gate=input_gate,
        sources=sources,
        source_specs=source_specs,
        public_plan=public_plan,
        private_map=private_map,
        v1_skill_text=v1_skill_bytes.decode("utf-8"),
        stage_bundles=stage_bundles,
    )


def _render_v1_prompt(evidence: dict[str, Any], runtime_skill_text: str, source_label: str) -> str:
    source = evidence["source"]
    rendered = (
        _skill_body_text(runtime_skill_text, source_label)
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


def _assert_only_known_candidate_ids(raw: Any, known_candidate_ids: Sequence[str]) -> None:
    known = set(known_candidate_ids)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "candidate_id" and (not isinstance(child, str) or child not in known):
                    raise PermanentModelOutputError(
                        f"model output contains unknown candidate_id: {child!r}",
                        category="model_output_unknown_candidate_id",
                    )
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(raw)


def _assert_no_cross_candidate_evidence(
    raw: Any,
    *,
    candidates_by_id: dict[str, dict[str, Any]],
    contracts: ModuleType,
) -> None:
    if not isinstance(raw, dict) or not isinstance(raw.get("copies"), list):
        return
    for copy in raw["copies"]:
        if not isinstance(copy, dict):
            continue
        candidate_id = copy.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in candidates_by_id:
            continue
        own_text = candidates_by_id[candidate_id]["text"]
        other_candidates = (
            (other_id, candidate["text"])
            for other_id, candidate in candidates_by_id.items()
            if other_id != candidate_id
        )
        evidence_quote = copy.get("evidence_quote")
        if isinstance(evidence_quote, str):
            own_receipt = contracts.exact_quote_receipt(evidence_quote, own_text)
            if own_receipt["status"] != "passed" and len(own_receipt["normalized_quote"]) >= 8:
                for other_id, other_text in other_candidates:
                    other_receipt = contracts.exact_quote_receipt(evidence_quote, other_text)
                    if other_receipt["status"] == "passed":
                        raise PermanentModelOutputError(
                            f"candidate {candidate_id} borrowed evidence_quote from {other_id}",
                            category="cross_candidate_evidence",
                        )
        source_sentence = copy.get("source_sentence")
        if isinstance(source_sentence, str) and isinstance(evidence_quote, str):
            source_receipt = contracts.exact_quote_receipt(source_sentence, evidence_quote)
            own_text_receipt = contracts.exact_quote_receipt(source_sentence, own_text)
            if (
                source_receipt["status"] != "passed"
                and own_text_receipt["status"] != "passed"
                and len(source_receipt["normalized_quote"]) >= 8
            ):
                for other_id, other_candidate in candidates_by_id.items():
                    if other_id == candidate_id:
                        continue
                    if (
                        contracts.exact_quote_receipt(source_sentence, other_candidate["text"])[
                            "status"
                        ]
                        == "passed"
                    ):
                        raise PermanentModelOutputError(
                            f"candidate {candidate_id} borrowed source_sentence from {other_id}",
                            category="cross_candidate_evidence",
                        )


def _codex_command(schema: Path, output: Path) -> list[str]:
    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("codex CLI is unavailable")
    return [
        executable,
        "--ask-for-approval",
        "never",
        *_disabled_feature_args(),
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


def _parse_events(
    stdout: str,
) -> tuple[str | None, dict[str, int] | None, bool, bool]:
    request_id: str | None = None
    usage: dict[str, int] | None = None
    unsafe_event = False
    model_started = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, RecursionError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            candidate_request_id = event["thread_id"]
            try:
                candidate_request_id.encode("utf-8")
            except UnicodeEncodeError:
                request_id = None
            else:
                request_id = candidate_request_id if len(candidate_request_id) <= 512 else None
        event_type = event.get("type")
        if event_type == "turn.started":
            model_started = True
        if isinstance(event_type, str) and event_type.startswith("item."):
            model_started = True
            item = event.get("item")
            item_type = item.get("type") if isinstance(item, dict) else None
            if item_type not in {"agent_message", "reasoning"}:
                unsafe_event = True
        if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
            candidate_usage = {
                key: value
                for key, value in event["usage"].items()
                if isinstance(key, str)
                and re.fullmatch(r"[a-z_]{1,40}", key)
                and isinstance(value, int)
                and not isinstance(value, bool)
                and value >= 0
            }
            usage = (
                candidate_usage
                if {"input_tokens", "output_tokens"}.issubset(candidate_usage)
                else None
            )
    return request_id, usage, unsafe_event, model_started


def _redact(value: str) -> str:
    return SECRET_RE.sub("[REDACTED]", value)


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _classify_pre_model_failure(stderr: str, *, fallback: str) -> str:
    normalized = stderr.casefold()
    if "operation not permitted" in normalized or "permission denied" in normalized:
        return "infrastructure_permission_denied"
    if "failed to initialize in-process app-server" in normalized:
        return "infrastructure_app_server_initialization"
    if "failed to initialize sqlite state runtime" in normalized:
        return "infrastructure_state_initialization"
    if "config" in normalized and ("invalid" in normalized or "error" in normalized):
        return "infrastructure_configuration"
    return fallback


def _run_preflight_process(
    command: Sequence[str], *, cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        list(command),
        input=b"",
        capture_output=True,
        cwd=cwd,
        env=env,
        timeout=PREFLIGHT_TIMEOUT_SECONDS,
        check=False,
    )


def _valid_preflight_failure_semantics(category: Any, returncode: Any) -> bool:
    plain_int = isinstance(returncode, int) and not isinstance(returncode, bool)
    if category in PREFLIGHT_NONZERO_FAILURE_CATEGORIES:
        return plain_int and returncode != 0
    if category in PREFLIGHT_NONE_FAILURE_CATEGORIES:
        return returncode is None
    return False


def _valid_call_infrastructure_semantics(category: Any, returncode: Any) -> bool:
    plain_int = isinstance(returncode, int) and not isinstance(returncode, bool)
    if category in CALL_NONZERO_INFRASTRUCTURE_CATEGORIES:
        return plain_int and returncode != 0
    if category in CALL_NONE_INFRASTRUCTURE_CATEGORIES:
        return returncode is None
    if category == "infrastructure_no_model_turn":
        return plain_int and returncode == 0
    if category == "infrastructure_event_stream_invalid_utf8":
        return returncode is None or plain_int
    return False


def _validate_preflight_receipt(
    receipt: dict[str, Any], prepared: PreparedExperiment, check_number: int
) -> None:
    required = {
        "schema_version",
        "policy_version",
        "experiment_id",
        "experiment_contract_sha256",
        "check_number",
        "status",
        "category",
        "command_sha256",
        "returncode",
        "model_started",
        "model_attempt_consumed",
        "stdout_tail",
        "stderr_tail",
        "recorded_at",
    }
    policy = prepared.manifest["immutable_contract"]["runtime_preflight"]
    status = receipt.get("status")
    category = receipt.get("category")
    returncode = receipt.get("returncode")
    passed_semantics = (
        status == "passed"
        and category == "ready"
        and isinstance(returncode, int)
        and not isinstance(returncode, bool)
        and returncode == 0
    )
    failed_semantics = status == "failed" and _valid_preflight_failure_semantics(
        category, returncode
    )
    if (
        set(receipt) != required
        or receipt.get("schema_version") != "1"
        or receipt.get("policy_version") != PREFLIGHT_POLICY_VERSION
        or receipt.get("experiment_id") != prepared.experiment_id
        or receipt.get("experiment_contract_sha256") != prepared.contract_sha256
        or not isinstance(receipt.get("check_number"), int)
        or isinstance(receipt.get("check_number"), bool)
        or receipt.get("check_number") != check_number
        or receipt.get("command_sha256") != policy["command_sha256"]
        or receipt.get("model_started") is not False
        or receipt.get("model_attempt_consumed") is not False
        or not (passed_semantics or failed_semantics)
        or not isinstance(receipt.get("stdout_tail"), str)
        or not isinstance(receipt.get("stderr_tail"), str)
        or not isinstance(receipt.get("recorded_at"), str)
    ):
        raise RuntimeError("Codex infrastructure preflight receipt drift")


def _preflight_receipt_inventory(
    snapshots: Sequence[JsonReceiptSnapshot],
) -> list[dict[str, str]]:
    return [
        {
            "relative_path": snapshot.relative_path,
            "sha256": _sha256_bytes(snapshot.content),
        }
        for snapshot in snapshots
    ]


def _complete_or_validate_preflight(
    prepared: PreparedExperiment,
    snapshots: Sequence[JsonReceiptSnapshot],
    passed_number: int,
    passed_receipt: dict[str, Any],
) -> dict[str, Any]:
    completion_path = prepared.experiment_dir / "infrastructure/preflight/complete.json"
    completion = {
        "schema_version": "1",
        "policy_version": PREFLIGHT_POLICY_VERSION,
        "experiment_id": prepared.experiment_id,
        "experiment_contract_sha256": prepared.contract_sha256,
        "passed_check": passed_number,
        "receipt_sha256": _preflight_receipt_inventory(snapshots),
    }
    if completion_path.exists() or completion_path.is_symlink():
        if completion_path.is_symlink() or not completion_path.is_file():
            raise RuntimeError("invalid Codex infrastructure preflight completion receipt")
        _regular_json_object(completion_path, "preflight completion")
        if completion_path.read_bytes() != _pretty_json_bytes(completion):
            raise RuntimeError("Codex infrastructure preflight completion receipt drift")
    else:
        _atomic_write_new(completion_path, _pretty_json_bytes(completion))
    return passed_receipt


def _ensure_runtime_preflight(prepared: PreparedExperiment) -> dict[str, Any]:
    """Run at most one new zero-model readiness check per invocation."""

    preflight_dir = prepared.experiment_dir / "infrastructure/preflight"
    attempts_dir = preflight_dir / "checks"
    existing: list[tuple[int, Path]] = []
    if preflight_dir.exists():
        if preflight_dir.is_symlink() or not preflight_dir.is_dir():
            raise RuntimeError("Codex infrastructure preflight root is unsafe")
        if not {path.name for path in preflight_dir.iterdir()}.issubset(
            {"checks", "complete.json"}
        ):
            raise RuntimeError("Codex infrastructure preflight root inventory drift")
    if attempts_dir.exists():
        if attempts_dir.is_symlink() or not attempts_dir.is_dir():
            raise RuntimeError("Codex infrastructure preflight checks root is unsafe")
        children = list(attempts_dir.iterdir())
        if any(
            path.is_symlink()
            or not path.is_dir()
            or not path.name.isdigit()
            or path.name != f"{int(path.name):03d}"
            for path in children
        ):
            raise RuntimeError("Codex infrastructure preflight receipt tree drift")
        for path in children:
            existing.append((int(path.name), path))
        existing.sort()
        if [number for number, _ in existing] != list(range(1, len(existing) + 1)):
            raise RuntimeError("Codex infrastructure preflight receipt sequence drift")
    failed_count = 0
    passed_receipt: dict[str, Any] | None = None
    receipt_snapshots: list[JsonReceiptSnapshot] = []
    for check_number, directory in existing:
        children = list(directory.iterdir())
        if (
            len(children) != 1
            or children[0].name != "receipt.json"
            or children[0].is_symlink()
            or not children[0].is_file()
        ):
            raise RuntimeError(f"Codex preflight receipt directory drift: {directory}")
        receipt_path = directory / "receipt.json"
        snapshot = _json_receipt_snapshot(
            receipt_path,
            relative_path=f"checks/{check_number:03d}/receipt.json",
            label="Codex preflight receipt",
        )
        receipt = snapshot.value
        _validate_preflight_receipt(receipt, prepared, check_number)
        receipt_snapshots.append(snapshot)
        if receipt["status"] == "passed":
            if passed_receipt is not None or check_number != len(existing):
                raise RuntimeError("Codex preflight passed receipt sequence drift")
            passed_receipt = receipt
        else:
            if passed_receipt is not None:
                raise RuntimeError("Codex preflight failure follows a passed receipt")
            failed_count += 1
    if passed_receipt is not None:
        return _complete_or_validate_preflight(
            prepared, receipt_snapshots, len(existing), passed_receipt
        )
    completion_path = preflight_dir / "complete.json"
    if completion_path.exists() or completion_path.is_symlink():
        raise RuntimeError("Codex infrastructure preflight completion has no passed check")
    if failed_count >= MAX_PREFLIGHT_FAILURES:
        raise CodexInfrastructureUnavailable(
            "Codex infrastructure preflight failure limit reached; preserve this experiment "
            "and start a new immutable contract after fixing the environment"
        )

    command = _codex_preflight_command()
    policy = prepared.manifest["immutable_contract"]["runtime_preflight"]
    if _sha256_bytes(_canonical_bytes(command)) != policy["command_sha256"]:
        raise RuntimeError("Codex infrastructure preflight command drift")
    check_number = len(existing) + 1
    started_at = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="liveclip-v2-preflight-") as temp_value:
        try:
            completed = _run_preflight_process(
                command,
                cwd=Path(temp_value),
                env=_safe_environment(),
            )
            try:
                stdout = (
                    completed.stdout.decode("utf-8")
                    if isinstance(completed.stdout, bytes)
                    else _as_text(completed.stdout)
                )
                stderr = (
                    completed.stderr.decode("utf-8")
                    if isinstance(completed.stderr, bytes)
                    else _as_text(completed.stderr)
                )
            except UnicodeDecodeError:
                stdout = _as_text(completed.stdout)
                stderr = _as_text(completed.stderr)
                returncode = None
                passed = False
                category = "infrastructure_preflight_invalid_utf8"
            else:
                returncode = completed.returncode
                passed = completed.returncode == 0
                category = (
                    "ready"
                    if passed
                    else _classify_pre_model_failure(
                        stderr,
                        fallback="infrastructure_preflight_process_failure",
                    )
                )
        except subprocess.TimeoutExpired as exc:
            stdout = _as_text(exc.stdout)
            stderr = _as_text(exc.stderr)
            returncode = None
            passed = False
            category = "infrastructure_preflight_timeout"
        except OSError as exc:
            stdout = ""
            stderr = str(exc)
            returncode = None
            passed = False
            category = "infrastructure_preflight_spawn_failure"
    receipt = {
        "schema_version": "1",
        "policy_version": PREFLIGHT_POLICY_VERSION,
        "experiment_id": prepared.experiment_id,
        "experiment_contract_sha256": prepared.contract_sha256,
        "check_number": check_number,
        "status": "passed" if passed else "failed",
        "category": category,
        "command_sha256": policy["command_sha256"],
        "returncode": returncode,
        "model_started": False,
        "model_attempt_consumed": False,
        "stdout_tail": _redact(stdout)[-3000:],
        "stderr_tail": _redact(stderr)[-3000:],
        "recorded_at": started_at.isoformat(),
    }
    receipt_path = attempts_dir / f"{check_number:03d}" / "receipt.json"
    receipt_bytes = _pretty_json_bytes(receipt)
    _atomic_write_new(receipt_path, receipt_bytes)
    if not passed:
        raise CodexInfrastructureUnavailable(
            f"Codex infrastructure preflight failed ({category}); receipt: {receipt_path}"
        )
    return _complete_or_validate_preflight(
        prepared,
        [
            *receipt_snapshots,
            JsonReceiptSnapshot(
                relative_path=f"checks/{check_number:03d}/receipt.json",
                content=receipt_bytes,
                value=receipt,
            ),
        ],
        check_number,
        receipt,
    )


def _invoke_codex(
    *,
    label: str,
    prompt: str,
    schema_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    started_at = datetime.now(UTC)
    started = time.monotonic()

    def attempt_metadata(
        *,
        request_id: str | None,
        usage: dict[str, int] | None,
        model_started: bool,
        unsafe_tool_event: bool,
        failure_category: str | None = None,
    ) -> dict[str, Any]:
        value = {
            "label": label,
            "model": MODEL_CONFIG["model"],
            "reasoning_effort": MODEL_CONFIG["reasoning_effort"],
            "request_id": request_id,
            "usage": usage,
            "usage_status": "reported" if usage is not None else "unavailable",
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "unsafe_tool_event": unsafe_tool_event,
            "model_started": model_started,
        }
        if failure_category is not None:
            value["failure_category"] = failure_category
        return value

    print(f"START {label} sol/medium", flush=True)
    with tempfile.TemporaryDirectory(prefix=f"liveclip-v2-{label}-") as temp_value:
        output = Path(temp_value) / "result.json"
        try:
            completed = subprocess.run(
                _codex_command(schema_path, output),
                input=prompt.encode("utf-8"),
                capture_output=True,
                cwd=temp_value,
                env=_safe_environment(),
                timeout=2_400,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _as_text(exc.stdout)
            stderr = _as_text(exc.stderr)
            request_id, usage, unsafe_event, model_started = _parse_events(stdout)
            category = (
                "model_safety_tool_event"
                if unsafe_event
                else "model_process_timeout"
                if model_started
                else "infrastructure_process_timeout"
            )
            raise CodexProcessFailure(
                f"{label} timed out",
                category=category,
                model_started=model_started,
                returncode=None,
                stdout=stdout,
                stderr=stderr,
                attempt_metadata=attempt_metadata(
                    request_id=request_id,
                    usage=usage,
                    model_started=model_started,
                    unsafe_tool_event=unsafe_event,
                    failure_category=category,
                ),
            ) from exc
        except OSError as exc:
            raise CodexProcessFailure(
                f"{label} could not start the Codex process",
                category="infrastructure_spawn_failure",
                model_started=False,
                returncode=None,
                stderr=str(exc),
            ) from exc
        stderr = _as_text(completed.stderr)
        try:
            stdout = (
                completed.stdout.decode("utf-8")
                if isinstance(completed.stdout, bytes)
                else _as_text(completed.stdout)
            )
        except UnicodeDecodeError as exc:
            stdout = completed.stdout.decode("utf-8", errors="replace")
            request_id, usage, unsafe_event, model_started = _parse_events(stdout)
            category = (
                "model_safety_tool_event"
                if unsafe_event
                else "model_event_stream_invalid_utf8"
                if model_started
                else "infrastructure_event_stream_invalid_utf8"
            )
            raise CodexProcessFailure(
                f"{label} emitted an invalid UTF-8 event stream",
                category=category,
                model_started=model_started,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                attempt_metadata=attempt_metadata(
                    request_id=request_id,
                    usage=usage,
                    model_started=model_started,
                    unsafe_tool_event=unsafe_event,
                    failure_category=category,
                ),
            ) from exc
        request_id, usage, unsafe_event, model_started = _parse_events(stdout)
        if unsafe_event:
            category = "model_safety_tool_event"
            raise CodexProcessFailure(
                f"{label} emitted a forbidden tool event",
                category=category,
                model_started=True,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                attempt_metadata=attempt_metadata(
                    request_id=request_id,
                    usage=usage,
                    model_started=True,
                    unsafe_tool_event=True,
                    failure_category=category,
                ),
            )
        if completed.returncode != 0:
            tail = "\n".join(stderr.splitlines()[-12:])
            category = (
                "model_process_failure"
                if model_started
                else _classify_pre_model_failure(
                    stderr,
                    fallback="infrastructure_pre_model_process_failure",
                )
            )
            raise CodexProcessFailure(
                f"{label} failed with exit {completed.returncode}: {_redact(tail)[:3000]}",
                category=category,
                model_started=model_started,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                attempt_metadata=attempt_metadata(
                    request_id=request_id,
                    usage=usage,
                    model_started=model_started,
                    unsafe_tool_event=False,
                    failure_category=category,
                ),
            )
        if not model_started:
            raise CodexProcessFailure(
                f"{label} exited without a model turn",
                category="infrastructure_no_model_turn",
                model_started=False,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                attempt_metadata=attempt_metadata(
                    request_id=request_id,
                    usage=usage,
                    model_started=False,
                    unsafe_tool_event=False,
                    failure_category="infrastructure_no_model_turn",
                ),
            )
        if not output.is_file():
            category = "model_output_missing"
            raise CodexProcessFailure(
                f"{label} did not produce structured output",
                category=category,
                model_started=True,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                attempt_metadata=attempt_metadata(
                    request_id=request_id,
                    usage=usage,
                    model_started=True,
                    unsafe_tool_event=False,
                    failure_category=category,
                ),
            )
        try:
            output_text = output.read_text(encoding="utf-8")
            raw = json.loads(output_text)
            _pretty_json_bytes(raw)
        except (
            OSError,
            UnicodeDecodeError,
            UnicodeEncodeError,
            json.JSONDecodeError,
            RecursionError,
            ValueError,
        ) as exc:
            if isinstance(exc, UnicodeDecodeError):
                category = "model_output_invalid_utf8"
            elif isinstance(exc, UnicodeEncodeError):
                category = "model_output_invalid_unicode"
            elif isinstance(exc, json.JSONDecodeError):
                category = "model_output_invalid_json"
            elif isinstance(exc, (RecursionError, ValueError)):
                category = "model_output_invalid_json_resource"
            else:
                category = "model_output_read_failure"
            raise CodexProcessFailure(
                f"{label} produced unreadable structured output ({category})",
                category=category,
                model_started=True,
                returncode=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                attempt_metadata=attempt_metadata(
                    request_id=request_id,
                    usage=usage,
                    model_started=True,
                    unsafe_tool_event=False,
                    failure_category=category,
                ),
            ) from exc
        events = stdout
    metadata = attempt_metadata(
        request_id=request_id,
        usage=usage,
        model_started=True,
        unsafe_tool_event=False,
    )
    print(f"DONE {label} {metadata['elapsed_seconds']}s", flush=True)
    return raw, metadata, events


Validation = Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]
ATTEMPT_TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
CALL_CONTRACT_KEYS = {
    "schema_version",
    "experiment_id",
    "experiment_contract_sha256",
    "call_id",
    "pipeline_id",
    "stage",
    "model",
    "prompt_sha256",
    "schema_relative_path",
    "schema_sha256",
    "dependency_sha256",
    "maximum_attempts",
    "isolation",
}
SUCCESSFUL_CALL_COMPLETION_KEYS = {
    "schema_version",
    "call_id",
    "call_contract_sha256",
    "successful_attempt",
    "successful_attempt_contract_sha256",
    "attempt_receipts",
    "artifact_sha256",
    "infrastructure_failure_receipts",
}
TERMINAL_CALL_RECEIPT_KEYS = {
    "schema_version",
    "status",
    "experiment_id",
    "experiment_contract_sha256",
    "call_id",
    "pipeline_id",
    "stage",
    "call_contract_sha256",
    "terminal_attempt",
    "terminal_attempt_contract_sha256",
    "failure_category",
    "attempt_failure_category",
    "failure_sha256",
    "attempt_receipts",
    "total_model_attempt_count",
    "completion_bound_total_elapsed_seconds",
    "completion_bound_total_usage",
    "completion_bound_usage_complete",
    "infrastructure_failure_receipts",
    "recorded_at",
}


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


def _regular_json_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object: {path}")
    return value


def _regular_json_value(path: Path, label: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is missing or unsafe: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is unreadable: {path}") from exc


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _safe_experiment_artifact(experiment_dir: Path, relative_name: str, label: str) -> Path:
    relative = PurePosixPath(relative_name)
    if (
        relative.is_absolute()
        or not relative.parts
        or relative.as_posix() != relative_name
        or "\\" in relative_name
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise RuntimeError(f"{label} path is unsafe: {relative_name!r}")
    root = experiment_dir.resolve(strict=True)
    candidate = root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise RuntimeError(f"{label} path traverses a symlink: {relative_name}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"{label} path escapes or is missing: {relative_name}") from exc
    if not resolved.is_file():
        raise RuntimeError(f"{label} is not a regular file: {relative_name}")
    return resolved


def _verified_experiment_manifest(
    experiment_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = _safe_experiment_artifact(
        experiment_dir, "experiment-manifest.json", "experiment manifest"
    )
    manifest = _regular_json_object(manifest_path, "experiment manifest")
    immutable = manifest.get("immutable_contract")
    if not isinstance(immutable, dict) or not immutable:
        raise RuntimeError("experiment immutable contract is missing")
    contract_sha256 = _sha256_bytes(_canonical_bytes(immutable))
    expected_experiment_id = f"exp_{contract_sha256[:20]}"
    if (
        manifest.get("schema_version") != "1"
        or manifest.get("contract_sha256") != contract_sha256
        or manifest.get("experiment_id") != expected_experiment_id
        or experiment_dir.name != expected_experiment_id
        or not isinstance(manifest.get("artifact_index"), dict)
    ):
        raise RuntimeError("experiment manifest identity or immutable contract drift")
    return manifest, immutable


def _evaluation_artifact_receipt(
    evaluation_contract: dict[str, Any], relative_name: str
) -> dict[str, Any]:
    artifacts = evaluation_contract.get("artifacts")
    receipt = artifacts.get(relative_name) if isinstance(artifacts, dict) else None
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"sha256", "size_bytes"}
        or not _is_sha256(receipt.get("sha256"))
        or not isinstance(receipt.get("size_bytes"), int)
        or isinstance(receipt.get("size_bytes"), bool)
        or receipt["size_bytes"] < 0
    ):
        raise RuntimeError(f"frozen evaluation artifact receipt is malformed: {relative_name}")
    return receipt


def _verified_indexed_experiment_bytes(
    experiment_dir: Path,
    manifest: dict[str, Any],
    relative_name: str,
    label: str,
    *,
    expected_sha256: str,
    expected_size_bytes: int | None = None,
) -> bytes:
    if not _is_sha256(expected_sha256):
        raise RuntimeError(f"{label} expected digest is malformed")
    path = _safe_experiment_artifact(experiment_dir, relative_name, label)
    content = path.read_bytes()
    observed = _artifact_record(content)
    if observed["sha256"] != expected_sha256 or (
        expected_size_bytes is not None and observed["size_bytes"] != expected_size_bytes
    ):
        raise RuntimeError(f"{label} immutable digest or size drift")
    artifact_index = manifest.get("artifact_index")
    indexed = artifact_index.get(relative_name) if isinstance(artifact_index, dict) else None
    if indexed != observed:
        raise RuntimeError(f"{label} experiment artifact receipt drift")
    return content


def _frozen_evaluation_context(
    experiment_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest, immutable = _verified_experiment_manifest(experiment_dir)
    evaluation_sha256 = immutable.get("evaluation_contract_sha256")
    if not _is_sha256(evaluation_sha256):
        raise RuntimeError("immutable evaluation contract digest is malformed")
    evaluation_bytes = _verified_indexed_experiment_bytes(
        experiment_dir,
        manifest,
        "frozen/evaluation-contract.json",
        "frozen evaluation contract",
        expected_sha256=evaluation_sha256,
    )
    try:
        raw = json.loads(evaluation_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("frozen evaluation contract is unreadable") from exc
    evaluation_contract = _validate_evaluation_contract_identity(raw)
    if immutable.get("evaluation_contract_version") != evaluation_contract.get("contract_version"):
        raise RuntimeError("frozen evaluation contract version drift")

    immutable_receipts = {
        "runner_sha256": RUNNER_RELATIVE_PATH,
        "contracts_sha256": CONTRACTS_RELATIVE_PATH,
        "input_gate_sha256": INPUT_GATE_RELATIVE_PATH,
        "v1_skill_sha256": V1_SKILL_RELATIVE_PATH,
        "v1_base_schema_sha256": V1_SCHEMA_RELATIVE_PATH,
    }
    for field, relative_name in immutable_receipts.items():
        receipt = _evaluation_artifact_receipt(evaluation_contract, relative_name)
        if immutable.get(field) != receipt["sha256"]:
            raise RuntimeError(
                f"immutable {field} does not match frozen evaluation artifact receipt"
            )

    artifacts = evaluation_contract.get("artifacts")
    assert isinstance(artifacts, dict)
    package_prefix = f"{V2_SKILL_RELATIVE_ROOT}/"
    expected_package_hashes = {
        relative_name.removeprefix(package_prefix): _evaluation_artifact_receipt(
            evaluation_contract, relative_name
        )["sha256"]
        for relative_name in sorted(artifacts)
        if isinstance(relative_name, str) and relative_name.startswith(package_prefix)
    }
    if (
        not expected_package_hashes
        or immutable.get("v2_skill_package_sha256") != expected_package_hashes
    ):
        raise RuntimeError("immutable v2 Skill package receipts drift")
    return manifest, immutable, evaluation_contract


def _verified_evaluation_copy_from_context(
    experiment_dir: Path,
    *,
    manifest: dict[str, Any],
    immutable: dict[str, Any],
    evaluation_contract: dict[str, Any],
    source_relative_name: str,
    frozen_relative_name: str,
    immutable_field: str,
    label: str,
) -> bytes:
    receipt = _evaluation_artifact_receipt(evaluation_contract, source_relative_name)
    if immutable.get(immutable_field) != receipt["sha256"]:
        raise RuntimeError(f"{label} immutable receipt drift")
    return _verified_indexed_experiment_bytes(
        experiment_dir,
        manifest,
        frozen_relative_name,
        label,
        expected_sha256=receipt["sha256"],
        expected_size_bytes=receipt["size_bytes"],
    )


def _verified_evaluation_copy_bytes(
    experiment_dir: Path,
    *,
    source_relative_name: str,
    frozen_relative_name: str,
    immutable_field: str,
    label: str,
) -> bytes:
    manifest, immutable, evaluation_contract = _frozen_evaluation_context(experiment_dir)
    return _verified_evaluation_copy_from_context(
        experiment_dir,
        manifest=manifest,
        immutable=immutable,
        evaluation_contract=evaluation_contract,
        source_relative_name=source_relative_name,
        frozen_relative_name=frozen_relative_name,
        immutable_field=immutable_field,
        label=label,
    )


def _load_experiment_contracts(experiment_dir: Path) -> ModuleType:
    content = _verified_evaluation_copy_bytes(
        experiment_dir,
        source_relative_name=CONTRACTS_RELATIVE_PATH,
        frozen_relative_name="frozen/gates/contracts.py",
        immutable_field="contracts_sha256",
        label="frozen contracts module",
    )
    return _execute_verified_module(
        module_role="v2_contracts_frozen",
        content=content,
        source_label="experiment://frozen/gates/contracts.py",
        required=CONTRACTS_INTERFACE,
    )


def _load_experiment_input_gate(experiment_dir: Path) -> ModuleType:
    content = _verified_evaluation_copy_bytes(
        experiment_dir,
        source_relative_name=INPUT_GATE_RELATIVE_PATH,
        frozen_relative_name="frozen/gates/input_gate.py",
        immutable_field="input_gate_sha256",
        label="frozen input gate module",
    )
    return _execute_verified_module(
        module_role="v2_input_gate_frozen",
        content=content,
        source_label="experiment://frozen/gates/input_gate.py",
        required=INPUT_GATE_INTERFACE,
    )


def _verify_experiment_trust_bridge(experiment_dir: Path) -> None:
    manifest, immutable, evaluation_contract = _frozen_evaluation_context(experiment_dir)
    for source_relative, frozen_relative, immutable_field, label in (
        (
            CONTRACTS_RELATIVE_PATH,
            "frozen/gates/contracts.py",
            "contracts_sha256",
            "frozen contracts module",
        ),
        (
            INPUT_GATE_RELATIVE_PATH,
            "frozen/gates/input_gate.py",
            "input_gate_sha256",
            "frozen input gate module",
        ),
        (
            V1_SKILL_RELATIVE_PATH,
            "frozen/runtime/v1-skill.md",
            "v1_skill_sha256",
            "frozen v1 runtime Skill",
        ),
    ):
        receipt = _evaluation_artifact_receipt(evaluation_contract, source_relative)
        if immutable.get(immutable_field) != receipt["sha256"]:
            raise RuntimeError(f"{label} immutable receipt drift")
        _verified_indexed_experiment_bytes(
            experiment_dir,
            manifest,
            frozen_relative,
            label,
            expected_sha256=receipt["sha256"],
            expected_size_bytes=receipt["size_bytes"],
        )

    bundle_hashes = immutable.get("v2_stage_bundle_sha256")
    if not isinstance(bundle_hashes, dict) or set(bundle_hashes) != {
        "combined-discovery",
        "selected-copy",
    }:
        raise RuntimeError("immutable v2 runtime bundle receipts are incomplete")
    for stage, digest in sorted(bundle_hashes.items()):
        _verified_indexed_experiment_bytes(
            experiment_dir,
            manifest,
            f"frozen/runtime/v2-{stage}-bundle.md",
            f"frozen v2 {stage} runtime bundle",
            expected_sha256=digest,
        )

    sources = immutable.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError("immutable source contracts are missing")
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("source_id"), str):
            raise RuntimeError("immutable source contract is malformed")
        source_id = source["source_id"]
        _verified_indexed_experiment_bytes(
            experiment_dir,
            manifest,
            f"frozen/inputs/{source_id}.json",
            f"frozen source input {source_id}",
            expected_sha256=source.get("experiment_input_sha256"),
        )
        schema_hashes = source.get("schema_sha256")
        if not isinstance(schema_hashes, dict) or set(schema_hashes) != {
            "v1",
            "combined-discovery",
            "selected-copy",
        }:
            raise RuntimeError(f"immutable Schema receipts are incomplete: {source_id}")
        for schema_name, digest in sorted(schema_hashes.items()):
            _verified_indexed_experiment_bytes(
                experiment_dir,
                manifest,
                f"frozen/schemas/{source_id}/{schema_name}.json",
                f"frozen {schema_name} Schema for {source_id}",
                expected_sha256=digest,
            )


def _expected_call_dependencies(
    experiment_dir: Path,
    pipeline_contract: dict[str, Any],
    stage: str,
) -> tuple[str, str, dict[str, str], str, str]:
    source_id = pipeline_contract["source_id"]
    manifest, immutable, evaluation_contract = _frozen_evaluation_context(experiment_dir)
    if pipeline_contract.get("experiment_contract_sha256") != manifest.get("contract_sha256"):
        raise RuntimeError("call pipeline is not bound to the immutable experiment")
    source_contract = next(
        (
            item
            for item in immutable.get("sources", [])
            if isinstance(item, dict) and item.get("source_id") == source_id
        ),
        None,
    )
    if not isinstance(source_contract, dict):
        raise RuntimeError(f"call source contract is missing: {source_id}")
    input_bytes = _verified_indexed_experiment_bytes(
        experiment_dir,
        manifest,
        f"frozen/inputs/{source_id}.json",
        "call frozen input",
        expected_sha256=source_contract.get("experiment_input_sha256"),
    )
    try:
        evidence = json.loads(input_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"call frozen input is unreadable: {source_id}") from exc
    if not isinstance(evidence, dict):
        raise RuntimeError(f"call frozen input must be an object: {source_id}")
    input_sha = _sha256_bytes(input_bytes)
    schema_by_stage = {
        "v1-generation": "v1",
        "v2-combined-discovery": "combined-discovery",
        "v2-selected-copy": "selected-copy",
    }
    schema_name = schema_by_stage.get(stage)
    if schema_name is None:
        raise RuntimeError(f"unknown call stage: {stage}")
    schema_hashes = source_contract.get("schema_sha256")
    expected_schema_sha256 = (
        schema_hashes.get(schema_name)
        if isinstance(schema_hashes, dict) and schema_name is not None
        else None
    )
    schema_relative = f"frozen/schemas/{source_id}/{schema_name}.json"
    _verified_indexed_experiment_bytes(
        experiment_dir,
        manifest,
        schema_relative,
        "call output Schema",
        expected_sha256=expected_schema_sha256,
    )
    assert isinstance(expected_schema_sha256, str)
    if stage == "v1-generation":
        runtime_skill_bytes = _verified_evaluation_copy_from_context(
            experiment_dir,
            manifest=manifest,
            immutable=immutable,
            evaluation_contract=evaluation_contract,
            source_relative_name=V1_SKILL_RELATIVE_PATH,
            frozen_relative_name="frozen/runtime/v1-skill.md",
            immutable_field="v1_skill_sha256",
            label="frozen v1 runtime Skill",
        )
        prompt = _render_v1_prompt(
            evidence,
            runtime_skill_bytes.decode("utf-8"),
            "experiment://frozen/runtime/v1-skill.md",
        )
        return (
            schema_relative,
            expected_schema_sha256,
            {
                "input": input_sha,
                "runtime_skill": _sha256_bytes(runtime_skill_bytes),
            },
            _sha256_bytes(prompt.encode("utf-8")),
            prompt,
        )
    common = {
        "source_input": input_sha,
        "evaluation_contract": immutable.get("evaluation_contract_sha256"),
    }
    if not all(_is_sha256(value) for value in common.values()):
        raise RuntimeError("call common dependency identity drift")
    if stage == "v2-combined-discovery":
        bundle_hashes = immutable.get("v2_stage_bundle_sha256")
        expected_bundle_sha256 = (
            bundle_hashes.get("combined-discovery") if isinstance(bundle_hashes, dict) else None
        )
        runtime_bundle_bytes = _verified_indexed_experiment_bytes(
            experiment_dir,
            manifest,
            "frozen/runtime/v2-combined-discovery-bundle.md",
            "combined runtime bundle",
            expected_sha256=expected_bundle_sha256,
        )
        combined_payload = _combined_discovery_payload(evidence)
        prompt = _render_v2_prompt(runtime_bundle_bytes.decode("utf-8"), combined_payload)
        return (
            schema_relative,
            expected_schema_sha256,
            {
                **common,
                "combined_payload": source_contract["combined_payload_sha256"],
                "runtime_bundle": _sha256_bytes(runtime_bundle_bytes),
            },
            _sha256_bytes(prompt.encode("utf-8")),
            prompt,
        )
    if stage != "v2-selected-copy":
        raise RuntimeError(f"unknown call stage: {stage}")
    combined_call = (
        experiment_dir
        / "calls"
        / _call_id(pipeline_contract["pipeline_id"], "v2-combined-discovery")
    )
    discovery = _verified_call_snapshot(combined_call)["result.json"]
    pipeline_discovery_path = (
        experiment_dir / "pipelines" / pipeline_contract["pipeline_id"] / "combined-discovery.json"
    )
    if pipeline_discovery_path.exists() or pipeline_discovery_path.is_symlink():
        if pipeline_discovery_path.is_symlink() or not pipeline_discovery_path.is_file():
            raise RuntimeError("selected-copy combined discovery mirror is unsafe")
        pipeline_discovery_bytes = pipeline_discovery_path.read_bytes()
        if pipeline_discovery_bytes != _pretty_json_bytes(discovery):
            raise RuntimeError("selected-copy combined discovery mirror drift")
    contracts_bytes = _verified_evaluation_copy_from_context(
        experiment_dir,
        manifest=manifest,
        immutable=immutable,
        evaluation_contract=evaluation_contract,
        source_relative_name=CONTRACTS_RELATIVE_PATH,
        frozen_relative_name="frozen/gates/contracts.py",
        immutable_field="contracts_sha256",
        label="frozen contracts module",
    )
    contracts = _execute_verified_module(
        module_role="v2_contracts_call_dependency_snapshot",
        content=contracts_bytes,
        source_label="experiment://frozen/gates/contracts.py",
        required=CONTRACTS_INTERFACE,
    )
    portfolio = contracts.select_adaptive_portfolio(
        evidence["candidates"],
        discovery,
        desired_minimum=DESIRED_MINIMUM,
        maximum_count=MAXIMUM_COUNT,
        base_minimum_quality=BASE_MINIMUM_QUALITY,
        maximum_interval_iou=MAXIMUM_INTERVAL_IOU,
        maximum_text_jaccard=MAXIMUM_TEXT_JACCARD,
    )
    candidates_by_id = {item["candidate_id"]: item for item in evidence["candidates"]}
    assessments_by_id = {item["candidate_id"]: item for item in discovery["assessments"]}
    selected_payload = [
        {
            "candidate": candidates_by_id[item["candidate_id"]],
            "assessment": assessments_by_id[item["candidate_id"]],
            "selection": item,
        }
        for item in portfolio["selected"]
    ]
    copy_payload = {
        "task": "iteration_2_selected_copy",
        "source": {
            "duration_ms": evidence["source"]["duration_ms"],
            "source_sha256": evidence["source"]["source_sha256"],
            "evidence_note": "Text-only ASR evidence; no video frames are supplied.",
        },
        "selected_candidates_in_required_order": selected_payload,
    }
    bundle_hashes = immutable.get("v2_stage_bundle_sha256")
    expected_bundle_sha256 = (
        bundle_hashes.get("selected-copy") if isinstance(bundle_hashes, dict) else None
    )
    runtime_bundle_bytes = _verified_indexed_experiment_bytes(
        experiment_dir,
        manifest,
        "frozen/runtime/v2-selected-copy-bundle.md",
        "selected-copy runtime bundle",
        expected_sha256=expected_bundle_sha256,
    )
    prompt = _render_v2_prompt(runtime_bundle_bytes.decode("utf-8"), copy_payload)
    return (
        schema_relative,
        expected_schema_sha256,
        {
            **common,
            "combined_discovery": _sha256_bytes(_canonical_bytes(discovery)),
            "adaptive_portfolio": _sha256_bytes(_canonical_bytes(portfolio)),
            "selected_payload": _sha256_bytes(_canonical_bytes(copy_payload)),
            "runtime_bundle": _sha256_bytes(runtime_bundle_bytes),
        },
        _sha256_bytes(prompt.encode("utf-8")),
        prompt,
    )


def _validate_call_contract(
    call_dir: Path,
    *,
    expected_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if call_dir.is_symlink() or not call_dir.is_dir():
        raise RuntimeError(f"call directory is missing or unsafe: {call_dir}")
    contract_path = call_dir / "call-contract.json"
    contract = _regular_json_object(contract_path, "call contract")
    if set(contract) != CALL_CONTRACT_KEYS or contract.get("schema_version") != "1":
        raise RuntimeError(f"call contract shape/schema drift: {call_dir}")
    if expected_contract is not None and _pretty_json_bytes(contract) != _pretty_json_bytes(
        expected_contract
    ):
        raise RuntimeError(f"call contract drift: {call_dir}")
    experiment_dir = call_dir.parents[1]
    manifest, immutable, _ = _frozen_evaluation_context(experiment_dir)
    pipeline_id = contract.get("pipeline_id")
    stage = contract.get("stage")
    call_id = contract.get("call_id")
    if (
        not isinstance(pipeline_id, str)
        or not isinstance(stage, str)
        or not isinstance(call_id, str)
        or call_id != call_dir.name
        or call_id != _call_id(pipeline_id, stage)
        or contract.get("experiment_id") != manifest.get("experiment_id")
        or contract.get("experiment_id") != experiment_dir.name
        or contract.get("experiment_contract_sha256") != manifest.get("contract_sha256")
        or contract.get("model") != MODEL_CONFIG
        or not _is_sha256(contract.get("prompt_sha256"))
        or contract.get("maximum_attempts") != MAX_MODEL_ATTEMPTS
    ):
        raise RuntimeError(f"call contract identity drift: {call_dir}")
    if _canonical_bytes(contract.get("isolation")) != _canonical_bytes(
        immutable.get("runtime_isolation")
    ):
        raise RuntimeError(f"call isolation contract drift: {call_dir}")
    pipeline_path = experiment_dir / "pipelines" / pipeline_id / "pipeline-contract.json"
    pipeline_contract = _regular_json_object(pipeline_path, "pipeline contract")
    required_call_ids = pipeline_contract.get("required_call_ids")
    conditional_call_ids = pipeline_contract.get("conditional_call_ids")
    if not isinstance(required_call_ids, list) or not isinstance(conditional_call_ids, dict):
        raise RuntimeError(f"call pipeline topology drift: {call_dir}")
    all_call_ids = [
        *required_call_ids,
        *conditional_call_ids.values(),
    ]
    if (
        pipeline_contract.get("pipeline_id") != pipeline_id
        or pipeline_contract.get("experiment_contract_sha256") != manifest.get("contract_sha256")
        or call_id not in all_call_ids
    ):
        raise RuntimeError(f"call-to-pipeline contract binding drift: {call_dir}")
    (
        expected_schema_relative,
        expected_schema_sha256,
        expected_dependencies,
        expected_prompt_sha256,
        _,
    ) = _expected_call_dependencies(experiment_dir, pipeline_contract, stage)
    if contract.get("prompt_sha256") != expected_prompt_sha256:
        raise RuntimeError(f"call initial prompt binding drift: {call_dir}")
    schema_relative = contract.get("schema_relative_path")
    if schema_relative != expected_schema_relative:
        raise RuntimeError(f"call Schema path binding drift: {call_dir}")
    if contract.get("schema_sha256") != expected_schema_sha256:
        raise RuntimeError(f"call Schema hash drift: {call_dir}")
    dependencies = contract.get("dependency_sha256")
    if dependencies != dict(sorted(expected_dependencies.items())):
        raise RuntimeError(f"call dependency hash drift: {call_dir}")
    return contract


def _normalized_attempt_usage(metadata: dict[str, Any]) -> dict[str, int] | None:
    usage = metadata.get("usage")
    if usage is None:
        if metadata.get("usage_status") != "unavailable":
            raise RuntimeError("model attempt usage status drift")
        return None
    if not isinstance(usage, dict) or metadata.get("usage_status") != "reported":
        raise RuntimeError("model attempt usage receipt is malformed")
    normalized: dict[str, int] = {}
    for field in ATTEMPT_TOKEN_FIELDS:
        value = usage.get(field, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError(f"model attempt has invalid {field}")
        normalized[field] = value
    normalized["reported_total_tokens"] = normalized["input_tokens"] + normalized["output_tokens"]
    return normalized


def _attempt_receipt(attempt_dir: Path, attempt_number: int) -> dict[str, Any]:
    if not attempt_dir.is_dir() or attempt_dir.is_symlink():
        raise RuntimeError(f"model attempt directory is missing or unsafe: {attempt_dir}")
    contract_path = attempt_dir / "attempt-contract.json"
    if not contract_path.is_file() or contract_path.is_symlink():
        raise RuntimeError(f"model attempt contract is missing or unsafe: {attempt_dir}")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "prompt_sha256",
        "status",
        "model_started",
        "model_attempt_consumed",
        "artifact_sha256",
    }
    if (
        set(contract) != required
        or contract.get("schema_version") != "2"
        or contract.get("status") not in {"validated", "failed", "terminal_failed"}
        or contract.get("model_started") is not True
        or contract.get("model_attempt_consumed") is not True
        or not _is_sha256(contract.get("prompt_sha256"))
    ):
        raise RuntimeError(f"model attempt contract drift: {attempt_dir}")
    artifact_hashes = contract.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict):
        raise RuntimeError(f"model attempt artifact receipt is malformed: {attempt_dir}")
    required_artifacts = {"call-metadata.json", "events.jsonl"}
    if contract["status"] == "validated":
        required_artifacts.add("result.raw.json")
        allowed_artifacts = required_artifacts
    else:
        required_artifacts.add("failure.json")
        allowed_artifacts = {*required_artifacts, "result.raw.json"}
    if not required_artifacts.issubset(artifact_hashes) or not set(artifact_hashes).issubset(
        allowed_artifacts
    ):
        raise RuntimeError(f"model attempt artifact receipt is incomplete: {attempt_dir}")
    children = list(attempt_dir.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in children):
        raise RuntimeError(f"model attempt contains an unsafe artifact: {attempt_dir}")
    observed_files = {path.name for path in children}
    if observed_files != {"attempt-contract.json", *artifact_hashes}:
        raise RuntimeError(f"model attempt artifact set drift: {attempt_dir}")
    for relative, expected_hash in artifact_hashes.items():
        path = attempt_dir / relative
        if not path.is_file() or path.is_symlink() or _sha256_path(path) != expected_hash:
            raise RuntimeError(f"model attempt artifact drift: {path}")
    metadata = _regular_json_object(attempt_dir / "call-metadata.json", "model attempt metadata")
    metadata_keys = {
        "label",
        "model",
        "reasoning_effort",
        "request_id",
        "usage",
        "usage_status",
        "started_at",
        "completed_at",
        "elapsed_seconds",
        "unsafe_tool_event",
        "model_started",
    }
    if contract["status"] != "validated":
        metadata_keys.add("failure_category")
    elapsed = metadata.get("elapsed_seconds")
    if (
        set(metadata) != metadata_keys
        or metadata.get("label") != f"{attempt_dir.parents[1].name}-a{attempt_number}"
        or metadata.get("model") != MODEL_CONFIG["model"]
        or metadata.get("reasoning_effort") != MODEL_CONFIG["reasoning_effort"]
        or metadata.get("model_started") is not True
        or not isinstance(metadata.get("unsafe_tool_event"), bool)
        or not isinstance(metadata.get("started_at"), str)
        or not isinstance(metadata.get("completed_at"), str)
        or not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or not math.isfinite(float(elapsed))
        or elapsed < 0
    ):
        raise RuntimeError(f"model attempt cost metadata drift: {attempt_dir}")
    usage = _normalized_attempt_usage(metadata)
    events = (attempt_dir / "events.jsonl").read_text(encoding="utf-8")
    parsed_events = _parse_events(events)
    if (
        not parsed_events[3]
        or parsed_events[0] != metadata["request_id"]
        or parsed_events[1] != metadata["usage"]
        or parsed_events[2] is not metadata["unsafe_tool_event"]
        or (parsed_events[2] and contract["status"] != "terminal_failed")
    ):
        raise RuntimeError(f"model attempt lacks turn.started evidence: {attempt_dir}")
    if contract["status"] != "validated":
        failure = _regular_json_object(attempt_dir / "failure.json", "model attempt failure")
        if (
            set(failure) != {"error", "category", "recorded_at"}
            or not isinstance(failure.get("error"), str)
            or not failure["error"]
            or not isinstance(failure.get("category"), str)
            or not failure["category"]
            or not isinstance(failure.get("recorded_at"), str)
            or metadata.get("failure_category") != failure["category"]
            or (parsed_events[2] and failure["category"] != "model_safety_tool_event")
        ):
            raise RuntimeError(f"model attempt failure receipt drift: {attempt_dir}")
    return {
        "attempt": attempt_number,
        "status": contract["status"],
        "attempt_contract_sha256": _sha256_path(contract_path),
        "model_started": True,
        "model_attempt_consumed": True,
        "elapsed_seconds": elapsed,
        "usage_status": metadata["usage_status"],
        "usage": usage,
    }


def _verified_attempt_snapshot(attempt_dir: Path, attempt_number: int) -> dict[str, Any]:
    contract_path = attempt_dir / "attempt-contract.json"
    if contract_path.is_symlink() or not contract_path.is_file():
        raise RuntimeError(f"model attempt contract is missing or unsafe: {attempt_dir}")
    contract_bytes = contract_path.read_bytes()
    try:
        contract = json.loads(contract_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"model attempt contract is unreadable: {attempt_dir}") from exc
    if not isinstance(contract, dict) or not isinstance(contract.get("artifact_sha256"), dict):
        raise RuntimeError(f"model attempt contract is malformed: {attempt_dir}")
    artifact_bytes: dict[str, bytes] = {}
    for relative in contract["artifact_sha256"]:
        if (
            not isinstance(relative, str)
            or PurePosixPath(relative).parts != (relative,)
            or relative in {"", ".", ".."}
            or "\\" in relative
        ):
            raise RuntimeError(f"model attempt artifact path is unsafe: {relative!r}")
        path = attempt_dir / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"model attempt artifact drift: {path}")
        artifact_bytes[relative] = path.read_bytes()

    receipt = _attempt_receipt(attempt_dir, attempt_number)
    if receipt.get("attempt_contract_sha256") != _sha256_bytes(contract_bytes):
        raise RuntimeError(f"model attempt contract changed during snapshot: {attempt_dir}")
    observed_hashes = {
        relative: _sha256_bytes(content) for relative, content in sorted(artifact_bytes.items())
    }
    if contract.get("artifact_sha256") != observed_hashes:
        raise RuntimeError(f"model attempt artifacts changed during snapshot: {attempt_dir}")

    parsed: dict[str, Any] = {
        "contract": contract,
        "receipt": receipt,
    }
    for relative, content in artifact_bytes.items():
        if relative == "events.jsonl":
            try:
                parsed[relative] = content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeError(f"model attempt events are unreadable: {attempt_dir}") from exc
            continue
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"model attempt JSON is unreadable: {attempt_dir / relative}"
            ) from exc
        parsed[relative] = value
    metadata = parsed.get("call-metadata.json")
    if not isinstance(metadata, dict):
        raise RuntimeError(f"model attempt metadata is malformed: {attempt_dir}")
    expected_receipt = {
        "attempt": attempt_number,
        "status": contract.get("status"),
        "attempt_contract_sha256": _sha256_bytes(contract_bytes),
        "model_started": True,
        "model_attempt_consumed": True,
        "elapsed_seconds": metadata.get("elapsed_seconds"),
        "usage_status": metadata.get("usage_status"),
        "usage": _normalized_attempt_usage(metadata),
    }
    if receipt != expected_receipt:
        raise RuntimeError(f"model attempt receipt changed during snapshot: {attempt_dir}")
    return parsed


def _attempt_receipt_inventory(call_dir: Path, attempt_count: int) -> list[dict[str, Any]]:
    attempts_root = call_dir / "attempts"
    if not attempts_root.is_dir() or attempts_root.is_symlink():
        raise RuntimeError(f"model attempt root is missing or unsafe: {call_dir}")
    observed = sorted(path.name for path in attempts_root.iterdir())
    expected = [f"{number:03d}" for number in range(1, attempt_count + 1)]
    if observed != expected:
        raise RuntimeError(f"model attempt sequence drift: {call_dir}")
    return [
        _attempt_receipt(attempts_root / f"{number:03d}", number)
        for number in range(1, attempt_count + 1)
    ]


def _verify_successful_attempt_mirrors(call_dir: Path, attempt_number: int) -> None:
    attempt_dir = call_dir / "attempts" / f"{attempt_number:03d}"
    for relative in ("result.raw.json", "call-metadata.json", "events.jsonl"):
        final_path = call_dir / relative
        attempt_path = attempt_dir / relative
        if (
            not final_path.is_file()
            or final_path.is_symlink()
            or not attempt_path.is_file()
            or attempt_path.is_symlink()
            or final_path.read_bytes() != attempt_path.read_bytes()
        ):
            raise RuntimeError(f"successful model attempt mirror drift: {attempt_path}")


def _validated_completed_call_snapshot(
    call_dir: Path,
    expected_contract: dict[str, Any],
    validator: Validation,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    completion_path = call_dir / "complete.json"
    if (call_dir / "terminal.json").exists() or (call_dir / "terminal.json").is_symlink():
        raise RuntimeError(f"completed call also has terminal evidence: {call_dir}")
    if not completion_path.exists():
        return None
    snapshot = _verified_call_snapshot(call_dir)
    if snapshot["contract"] != expected_contract:
        raise RuntimeError(f"call contract drift: {call_dir}")
    raw = snapshot["result.raw.json"]
    enriched, validation = validator(raw)
    if enriched != snapshot["result.json"]:
        raise RuntimeError(f"completed call enriched result no longer validates: {call_dir}")
    if validation != snapshot["validation.json"]:
        raise RuntimeError(f"completed call validation receipt drift: {call_dir}")
    print(f"RESUME {expected_contract['call_id']}", flush=True)
    return enriched, validation, snapshot["call-metadata.json"], snapshot["completion"]


def _validate_completed_call(
    call_dir: Path,
    expected_contract: dict[str, Any],
    validator: Validation,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    snapshot = _validated_completed_call_snapshot(call_dir, expected_contract, validator)
    return None if snapshot is None else snapshot[:3]


def _persist_attempt(
    attempt_dir: Path,
    *,
    prompt: str,
    raw: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    events: str | None,
    error: str | None,
    failure_category: str | None = None,
    terminal_failure_category: str | None = None,
) -> None:
    if metadata is None or events is None or metadata.get("model_started") is not True:
        raise RuntimeError("every persisted model attempt requires cost and event evidence")
    _normalized_attempt_usage(metadata)
    if not _parse_events(events)[3]:
        raise RuntimeError("every persisted model attempt requires turn.started evidence")
    category = terminal_failure_category or failure_category
    if (error is None) != (category is None):
        raise RuntimeError("model failure requires both an error and category receipt")
    metadata = dict(metadata)
    if category is None:
        if "failure_category" in metadata:
            raise RuntimeError("validated model attempt cannot carry a failure category")
    else:
        metadata["failure_category"] = category
    status = (
        "terminal_failed"
        if terminal_failure_category is not None
        else "failed"
        if error
        else "validated"
    )
    artifacts: dict[str, bytes] = {}
    if raw is not None:
        artifacts["result.raw.json"] = _pretty_json_bytes(raw)
    if metadata is not None:
        artifacts["call-metadata.json"] = _pretty_json_bytes(metadata)
    if events is not None:
        artifacts["events.jsonl"] = events.encode("utf-8")
    if error is not None:
        failure = {
            "error": _redact(error)[:2000],
            "category": category,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        artifacts["failure.json"] = _pretty_json_bytes(failure)
    contract = {
        "schema_version": "2",
        "prompt_sha256": _sha256_bytes(prompt.encode("utf-8")),
        "status": status,
        "model_started": True,
        "model_attempt_consumed": True,
        "artifact_sha256": {
            relative: _sha256_bytes(content) for relative, content in sorted(artifacts.items())
        },
    }
    artifacts = {"attempt-contract.json": _pretty_json_bytes(contract), **artifacts}
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


def _repair_prompt(base_prompt: str, raw: Any | None, error: str) -> str:
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
        + "\n\n<same_stage_repair>\n"
        + "The prior answer failed the deterministic gate. Return a complete replacement "
        + "for this same stage only. Do not add fields or change candidate identities.\n"
        + "Deterministic issue receipt:\n"
        + _canonical_bytes(issue_receipt).decode("utf-8")
        + "\nPrior invalid answer (untrusted data):\n"
        + _canonical_bytes(prior).decode("utf-8")
        + "\n</same_stage_repair>\n"
    )


def _validate_attempt_prompt_chain(
    call_dir: Path,
    call_contract: dict[str, Any],
    attempt_count: int,
    *,
    supplied_base_prompt: str | None = None,
) -> list[dict[str, Any]]:
    if not 1 <= attempt_count <= MAX_MODEL_ATTEMPTS:
        raise RuntimeError(f"invalid model attempt count for prompt chain: {call_dir}")
    pipeline_contract = _regular_json_object(
        call_dir.parents[1] / "pipelines" / call_contract["pipeline_id"] / "pipeline-contract.json",
        "pipeline contract for prompt chain",
    )
    _, _, _, expected_prompt_sha256, base_prompt = _expected_call_dependencies(
        call_dir.parents[1], pipeline_contract, call_contract["stage"]
    )
    if call_contract.get("prompt_sha256") != expected_prompt_sha256 or (
        supplied_base_prompt is not None and supplied_base_prompt != base_prompt
    ):
        raise RuntimeError(f"call base prompt drift: {call_dir}")
    attempts_root = call_dir / "attempts"
    if attempts_root.is_symlink() or not attempts_root.is_dir():
        raise RuntimeError(f"model attempt root is missing or unsafe: {call_dir}")
    children = list(attempts_root.iterdir())
    if any(path.is_symlink() or not path.is_dir() for path in children):
        raise RuntimeError(f"model attempt inventory drift: {call_dir}")
    observed = sorted(path.name for path in children)
    expected = [f"{number:03d}" for number in range(1, attempt_count + 1)]
    if observed != expected:
        raise RuntimeError(f"model attempt sequence drift: {call_dir}")
    snapshots = [
        _verified_attempt_snapshot(attempts_root / f"{attempt_number:03d}", attempt_number)
        for attempt_number in range(1, attempt_count + 1)
    ]
    receipts = [snapshot["receipt"] for snapshot in snapshots]
    current_prompt = base_prompt
    for attempt_number, (receipt, snapshot) in enumerate(zip(receipts, snapshots, strict=True), 1):
        attempt_dir = call_dir / "attempts" / f"{attempt_number:03d}"
        attempt_contract = snapshot["contract"]
        if attempt_contract.get("prompt_sha256") != _sha256_bytes(current_prompt.encode("utf-8")):
            raise RuntimeError(f"model attempt prompt chain drift: {attempt_dir}")
        if attempt_number == attempt_count:
            continue
        if receipt["status"] != "failed":
            raise RuntimeError(f"model attempt prompt-chain status drift: {call_dir}")
        failure = snapshot.get("failure.json")
        if not isinstance(failure, dict):
            raise RuntimeError(f"model attempt failure is malformed: {attempt_dir}")
        prior_raw = snapshot.get("result.raw.json")
        current_prompt = _repair_prompt(base_prompt, prior_raw, failure["error"])
    return receipts


def _validate_incomplete_attempt_inventory(
    call_dir: Path, call_contract: dict[str, Any], base_prompt: str
) -> int:
    attempts_root = call_dir / "attempts"
    if not attempts_root.exists() and not attempts_root.is_symlink():
        return 0
    if attempts_root.is_symlink() or not attempts_root.is_dir():
        raise RuntimeError(f"model attempt root is unsafe: {call_dir}")
    children = list(attempts_root.iterdir())
    if any(
        path.is_symlink() or not path.is_dir() or re.fullmatch(r"[0-9]{3}", path.name) is None
        for path in children
    ):
        raise RuntimeError(f"model attempt inventory drift: {call_dir}")
    observed = sorted(path.name for path in children)
    expected = [f"{number:03d}" for number in range(1, len(children) + 1)]
    if observed != expected or len(children) > MAX_MODEL_ATTEMPTS:
        raise RuntimeError(f"model attempt sequence drift: {call_dir}")
    _validate_attempt_prompt_chain(
        call_dir,
        call_contract,
        len(observed),
        supplied_base_prompt=base_prompt,
    )
    return len(observed)


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
        "attempt_receipts": _attempt_receipt_inventory(call_dir, attempt_number),
        "artifact_sha256": {
            relative: _sha256_bytes(content)
            for relative, content in sorted(final_artifacts.items())
        },
        "infrastructure_failure_receipts": _call_infrastructure_failure_receipt_inventory(
            call_dir, json.loads(contract_bytes)
        ),
    }
    _atomic_write_new(call_dir / "complete.json", _pretty_json_bytes(completion))
    return enriched, validation, metadata


def _call_infrastructure_failure_snapshots(
    call_dir: Path, call_contract: dict[str, Any]
) -> list[JsonReceiptSnapshot]:
    failures_dir = call_dir / "infrastructure-failures"
    existing: list[tuple[int, Path]] = []
    if failures_dir.exists() or failures_dir.is_symlink():
        if failures_dir.is_symlink() or not failures_dir.is_dir():
            raise RuntimeError(f"call infrastructure receipt root is unsafe: {call_dir}")
        for path in failures_dir.iterdir():
            if (
                path.is_symlink()
                or not path.is_dir()
                or not path.name.isdigit()
                or path.name != f"{int(path.name):03d}"
            ):
                raise RuntimeError(f"call infrastructure receipt layout drift: {call_dir}")
            existing.append((int(path.name), path))
        existing.sort()
        if [number for number, _ in existing] != list(range(1, len(existing) + 1)):
            raise RuntimeError(f"call infrastructure receipt sequence drift: {call_dir}")
    required = {
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
    contract_path = call_dir / "call-contract.json"
    contract_sha = _sha256_path(contract_path)
    snapshots: list[JsonReceiptSnapshot] = []
    for failure_number, directory in existing:
        children = list(directory.iterdir())
        if (
            len(children) != 1
            or children[0].name != "receipt.json"
            or children[0].is_symlink()
            or not children[0].is_file()
        ):
            raise RuntimeError(f"call infrastructure receipt layout drift: {directory}")
        receipt_path = directory / "receipt.json"
        snapshot = _json_receipt_snapshot(
            receipt_path,
            relative_path=(f"infrastructure-failures/{failure_number:03d}/receipt.json"),
            label="call infrastructure failure receipt",
        )
        receipt = snapshot.value
        returncode = receipt.get("returncode")
        if (
            set(receipt) != required
            or receipt.get("schema_version") != "1"
            or receipt.get("experiment_id") != call_contract["experiment_id"]
            or receipt.get("experiment_contract_sha256")
            != call_contract["experiment_contract_sha256"]
            or receipt.get("call_id") != call_contract["call_id"]
            or receipt.get("pipeline_id") != call_contract["pipeline_id"]
            or receipt.get("stage") != call_contract["stage"]
            or receipt.get("failure_number") != failure_number
            or receipt.get("call_contract_sha256") != contract_sha
            or receipt.get("model_started") is not False
            or receipt.get("model_attempt_consumed") is not False
            or not _valid_call_infrastructure_semantics(receipt.get("category"), returncode)
            or not isinstance(receipt.get("stdout_tail"), str)
            or not isinstance(receipt.get("stderr_tail"), str)
            or not isinstance(receipt.get("recorded_at"), str)
        ):
            raise RuntimeError(f"call infrastructure receipt drift: {receipt_path}")
        snapshots.append(snapshot)
    return snapshots


def _validated_call_infrastructure_failure_count(
    call_dir: Path, call_contract: dict[str, Any]
) -> int:
    return len(_call_infrastructure_failure_snapshots(call_dir, call_contract))


def _call_infrastructure_failure_receipt_inventory(
    call_dir: Path, call_contract: dict[str, Any]
) -> list[dict[str, str]]:
    snapshots = _call_infrastructure_failure_snapshots(call_dir, call_contract)
    return [
        {
            "relative_path": snapshot.relative_path,
            "sha256": _sha256_bytes(snapshot.content),
        }
        for snapshot in snapshots
    ]


def _attempt_cost_totals(attempt_receipts: Sequence[dict[str, Any]]) -> dict[str, Any]:
    usage = {field: 0 for field in ATTEMPT_TOKEN_FIELDS}
    elapsed_seconds = 0.0
    usage_complete = True
    for attempt in attempt_receipts:
        elapsed_seconds += float(attempt["elapsed_seconds"])
        attempt_usage = attempt["usage"]
        if attempt_usage is None:
            usage_complete = False
            continue
        for field in ATTEMPT_TOKEN_FIELDS:
            usage[field] += int(attempt_usage[field])
    usage["reported_total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return {
        "total_model_attempt_count": len(attempt_receipts),
        "completion_bound_total_elapsed_seconds": round(elapsed_seconds, 3),
        "completion_bound_total_usage": usage,
        "completion_bound_usage_complete": usage_complete,
    }


def _terminal_call_receipt(
    *,
    call_dir: Path,
    call_contract: dict[str, Any],
    terminal_attempt: int,
    status: str,
    failure_category: str,
) -> dict[str, Any]:
    if status not in {"terminal_failed", "exhausted"}:
        raise RuntimeError(f"invalid terminal call status: {status}")
    if status == "exhausted":
        expected_category = (
            "model_attempts_exhausted"
            if terminal_attempt == MAX_MODEL_ATTEMPTS
            else "pipeline_repair_budget_exhausted"
        )
        if failure_category != expected_category:
            raise RuntimeError(f"exhausted call category/attempt drift: {failure_category}")
        if failure_category == "pipeline_repair_budget_exhausted":
            if call_contract["stage"] != "v2-selected-copy" or terminal_attempt != 1:
                raise RuntimeError(
                    "pipeline repair exhaustion is only valid for selected-copy attempt 1"
                )
            combined_call_dir = call_dir.parent / _call_id(
                call_contract["pipeline_id"], "v2-combined-discovery"
            )
            _verify_call_evidence(combined_call_dir)
            combined_completion = _regular_json_object(
                combined_call_dir / "complete.json", "combined call completion"
            )
            if combined_completion.get("successful_attempt") != 2:
                raise RuntimeError(
                    "pipeline repair exhaustion lacks a consumed combined-discovery repair"
                )
    attempt_receipts = _validate_attempt_prompt_chain(call_dir, call_contract, terminal_attempt)
    final_attempt_dir = call_dir / "attempts" / f"{terminal_attempt:03d}"
    final_attempt_contract = _regular_json_object(
        final_attempt_dir / "attempt-contract.json", "terminal attempt contract"
    )
    failure_path = final_attempt_dir / "failure.json"
    failure = _regular_json_object(failure_path, "terminal attempt failure")
    expected_attempt_status = "terminal_failed" if status == "terminal_failed" else "failed"
    if (
        any(item["status"] != "failed" for item in attempt_receipts[:-1])
        or attempt_receipts[-1]["status"] != expected_attempt_status
        or final_attempt_contract.get("status") != expected_attempt_status
    ):
        raise RuntimeError(f"terminal call attempt status sequence drift: {call_dir}")
    if status == "terminal_failed" and failure_category != failure["category"]:
        raise RuntimeError(f"terminal call hard-failure category drift: {call_dir}")
    return {
        "schema_version": "1",
        "status": status,
        "experiment_id": call_contract["experiment_id"],
        "experiment_contract_sha256": call_contract["experiment_contract_sha256"],
        "call_id": call_contract["call_id"],
        "pipeline_id": call_contract["pipeline_id"],
        "stage": call_contract["stage"],
        "call_contract_sha256": _sha256_path(call_dir / "call-contract.json"),
        "terminal_attempt": terminal_attempt,
        "terminal_attempt_contract_sha256": _sha256_path(
            final_attempt_dir / "attempt-contract.json"
        ),
        "failure_category": failure_category,
        "attempt_failure_category": failure["category"],
        "failure_sha256": _sha256_path(failure_path),
        "attempt_receipts": attempt_receipts,
        **_attempt_cost_totals(attempt_receipts),
        "infrastructure_failure_receipts": (
            _call_infrastructure_failure_receipt_inventory(call_dir, call_contract)
        ),
        "recorded_at": failure["recorded_at"],
    }


def _validate_terminal_call(
    call_dir: Path,
    expected_contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    terminal_path = call_dir / "terminal.json"
    if not terminal_path.exists() and not terminal_path.is_symlink():
        return None
    if (call_dir / "complete.json").exists() or (call_dir / "complete.json").is_symlink():
        raise RuntimeError(f"call cannot be both successful and terminal: {call_dir}")
    call_contract = _validate_call_contract(call_dir, expected_contract=expected_contract)
    terminal = _regular_json_object(terminal_path, "terminal call receipt")
    terminal_attempt = terminal.get("terminal_attempt")
    if (
        set(terminal) != TERMINAL_CALL_RECEIPT_KEYS
        or terminal.get("schema_version") != "1"
        or terminal.get("status") not in {"terminal_failed", "exhausted"}
        or terminal.get("experiment_id") != call_contract["experiment_id"]
        or terminal.get("experiment_contract_sha256") != call_contract["experiment_contract_sha256"]
        or terminal.get("call_id") != call_contract["call_id"]
        or terminal.get("pipeline_id") != call_contract["pipeline_id"]
        or terminal.get("stage") != call_contract["stage"]
        or terminal.get("call_contract_sha256") != _sha256_path(call_dir / "call-contract.json")
        or not isinstance(terminal_attempt, int)
        or isinstance(terminal_attempt, bool)
        or not 1 <= terminal_attempt <= MAX_MODEL_ATTEMPTS
        or not isinstance(terminal.get("failure_category"), str)
        or not terminal["failure_category"]
        or not isinstance(terminal.get("recorded_at"), str)
    ):
        raise RuntimeError(f"terminal call receipt shape/identity drift: {call_dir}")
    expected = _terminal_call_receipt(
        call_dir=call_dir,
        call_contract=call_contract,
        terminal_attempt=terminal_attempt,
        status=terminal["status"],
        failure_category=terminal["failure_category"],
    )
    if _pretty_json_bytes(terminal) != _pretty_json_bytes(expected):
        raise RuntimeError(f"terminal call receipt drift: {call_dir}")
    expected_children = {"call-contract.json", "attempts", "terminal.json"}
    if (call_dir / "infrastructure-failures").exists():
        expected_children.add("infrastructure-failures")
    children = list(call_dir.iterdir())
    if {path.name for path in children} != expected_children or any(
        path.is_symlink() for path in children
    ):
        raise RuntimeError(f"terminal call artifact inventory drift: {call_dir}")
    return terminal


def _persist_terminal_call(
    *,
    call_dir: Path,
    call_contract: dict[str, Any],
    terminal_attempt: int,
    status: str,
    failure_category: str,
) -> dict[str, Any]:
    terminal = _terminal_call_receipt(
        call_dir=call_dir,
        call_contract=call_contract,
        terminal_attempt=terminal_attempt,
        status=status,
        failure_category=failure_category,
    )
    _atomic_write_new(call_dir / "terminal.json", _pretty_json_bytes(terminal))
    validated = _validate_terminal_call(call_dir, expected_contract=call_contract)
    assert validated is not None
    return validated


def _raise_persisted_terminal(call_id: str, terminal: dict[str, Any]) -> None:
    category = terminal["failure_category"]
    if category == "pipeline_repair_budget_exhausted":
        raise RuntimeError("pipeline repair budget exhausted")
    if terminal["status"] == "exhausted":
        raise RuntimeError(
            f"{call_id} exhausted {terminal['terminal_attempt']} same-stage attempts"
        )
    raise RuntimeError(
        f"{call_id} has a persisted terminal model failure ({category}); hard failure cannot retry"
    )


def _assert_call_infrastructure_budget(call_dir: Path, call_contract: dict[str, Any]) -> int:
    failure_count = _validated_call_infrastructure_failure_count(call_dir, call_contract)
    if failure_count >= MAX_CALL_INFRASTRUCTURE_FAILURES:
        raise CodexInfrastructureUnavailable(
            f"call {call_contract['call_id']} reached the bounded pre-model "
            "infrastructure failure limit"
        )
    return failure_count


def _persist_call_infrastructure_failure(
    *,
    call_dir: Path,
    call_contract: dict[str, Any],
    failure: CodexProcessFailure,
) -> Path:
    if failure.model_started:
        raise RuntimeError("model-started failures cannot use infrastructure receipts")
    if not _valid_call_infrastructure_semantics(failure.category, failure.returncode):
        raise RuntimeError(
            "pre-model failure category/returncode cannot use infrastructure receipts"
        )
    failures_dir = call_dir / "infrastructure-failures"
    failure_number = _assert_call_infrastructure_budget(call_dir, call_contract) + 1
    contract_sha = _sha256_path(call_dir / "call-contract.json")
    receipt = {
        "schema_version": "1",
        "experiment_id": call_contract["experiment_id"],
        "experiment_contract_sha256": call_contract["experiment_contract_sha256"],
        "call_id": call_contract["call_id"],
        "pipeline_id": call_contract["pipeline_id"],
        "stage": call_contract["stage"],
        "failure_number": failure_number,
        "category": failure.category,
        "returncode": failure.returncode,
        "model_started": False,
        "model_attempt_consumed": False,
        "call_contract_sha256": contract_sha,
        "stdout_tail": failure.stdout_tail,
        "stderr_tail": failure.stderr_tail,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    receipt_path = failures_dir / f"{failure_number:03d}" / "receipt.json"
    _atomic_write_new(receipt_path, _pretty_json_bytes(receipt))
    return receipt_path


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
    terminal = _validate_terminal_call(call_dir, expected_contract=contract)
    if terminal is not None:
        _raise_persisted_terminal(call_id, terminal)
    resumed_snapshot = _validated_completed_call_snapshot(call_dir, contract, validator)
    if resumed_snapshot is not None:
        resumed_result, resumed_validation, resumed_metadata, completion = resumed_snapshot
        if completion["successful_attempt"] == 2:
            repair_budget.consume(stage)
        return resumed_result, resumed_validation, resumed_metadata
    _validate_incomplete_attempt_inventory(call_dir, contract, prompt)
    _assert_call_infrastructure_budget(call_dir, contract)

    current_prompt = prompt
    last_error = ""
    repair_consumed = False
    for attempt_number in range(1, MAX_MODEL_ATTEMPTS + 1):
        if attempt_number > 1 and not repair_consumed:
            try:
                repair_budget.consume(stage)
            except RuntimeError:
                _persist_terminal_call(
                    call_dir=call_dir,
                    call_contract=contract,
                    terminal_attempt=attempt_number - 1,
                    status="exhausted",
                    failure_category="pipeline_repair_budget_exhausted",
                )
                raise
            repair_consumed = True
        attempt_dir = call_dir / "attempts" / f"{attempt_number:03d}"
        if attempt_dir.exists():
            attempt_snapshot = _verified_attempt_snapshot(attempt_dir, attempt_number)
            attempt_contract = attempt_snapshot["contract"]
            if attempt_contract["prompt_sha256"] != _sha256_bytes(current_prompt.encode("utf-8")):
                raise RuntimeError(f"persisted attempt prompt drift: {attempt_dir}")
            if attempt_contract.get("status") == "validated":
                raw = attempt_snapshot.get("result.raw.json")
                metadata = attempt_snapshot.get("call-metadata.json")
                events = attempt_snapshot.get("events.jsonl")
                if (
                    not isinstance(raw, dict)
                    or not isinstance(metadata, dict)
                    or not isinstance(events, str)
                ):
                    raise RuntimeError(f"validated attempt snapshot is malformed: {attempt_dir}")
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
            if attempt_contract.get("status") == "terminal_failed":
                failure = attempt_snapshot.get("failure.json")
                if not isinstance(failure, dict):
                    raise RuntimeError(f"terminal attempt snapshot is malformed: {attempt_dir}")
                terminal = _persist_terminal_call(
                    call_dir=call_dir,
                    call_contract=contract,
                    terminal_attempt=attempt_number,
                    status="terminal_failed",
                    failure_category=str(failure["category"]),
                )
                _raise_persisted_terminal(call_id, terminal)
            failure = attempt_snapshot.get("failure.json")
            if attempt_contract.get("status") != "failed" or not isinstance(failure, dict):
                raise RuntimeError(f"invalid persisted attempt state: {attempt_dir}")
            last_error = str(failure["error"])
            prior_raw = attempt_snapshot.get("result.raw.json")
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
        except PermanentModelOutputError as exc:
            last_error = _redact(f"{type(exc).__name__}: {exc}")[:2000]
            _persist_attempt(
                attempt_dir,
                prompt=current_prompt,
                raw=raw,
                metadata=metadata,
                events=events,
                error=last_error,
                terminal_failure_category=exc.category,
            )
            _persist_terminal_call(
                call_dir=call_dir,
                call_contract=contract,
                terminal_attempt=attempt_number,
                status="terminal_failed",
                failure_category=exc.category,
            )
            raise RuntimeError(
                f"{call_id} emitted a permanent identity violation; hard failure cannot retry"
            ) from exc
        except CodexProcessFailure as exc:
            if not exc.model_started:
                receipt_path = _persist_call_infrastructure_failure(
                    call_dir=call_dir,
                    call_contract=contract,
                    failure=exc,
                )
                raise CodexInfrastructureUnavailable(
                    f"{call_id} stopped before any model turn ({exc.category}); "
                    f"receipt: {receipt_path}"
                ) from exc
            last_error = _redact(f"CodexProcessFailure[{exc.category}]: {exc}")[:2000]
            metadata = exc.attempt_metadata
            events = exc.stdout_evidence
            if exc.category == "model_safety_tool_event":
                _persist_attempt(
                    attempt_dir,
                    prompt=current_prompt,
                    raw=raw,
                    metadata=metadata,
                    events=events,
                    error=last_error,
                    terminal_failure_category=exc.category,
                )
                _persist_terminal_call(
                    call_dir=call_dir,
                    call_contract=contract,
                    terminal_attempt=attempt_number,
                    status="terminal_failed",
                    failure_category=exc.category,
                )
                raise RuntimeError(
                    f"{call_id} emitted an unsafe tool event; hard failure cannot retry"
                ) from exc
            _persist_attempt(
                attempt_dir,
                prompt=current_prompt,
                raw=raw,
                metadata=metadata,
                events=events,
                error=last_error,
                failure_category=exc.category,
            )
            current_prompt = _repair_prompt(prompt, raw, last_error)
            continue
        except Exception as exc:
            last_error = _redact(f"{type(exc).__name__}: {exc}")[:2000]
            _persist_attempt(
                attempt_dir,
                prompt=current_prompt,
                raw=raw,
                metadata=metadata,
                events=events,
                error=last_error,
                failure_category="model_output_validation_failure",
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
    _persist_terminal_call(
        call_dir=call_dir,
        call_contract=contract,
        terminal_attempt=MAX_MODEL_ATTEMPTS,
        status="exhausted",
        failure_category="model_attempts_exhausted",
    )
    raise RuntimeError(
        f"{call_id} exhausted {MAX_MODEL_ATTEMPTS} same-stage attempts: {last_error}"
    )


def _validate_v1(
    raw: dict[str, Any],
    candidates: Sequence[dict[str, Any]],
    contracts: ModuleType,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _assert_only_known_candidate_ids(raw, [item["candidate_id"] for item in candidates])
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


def _would_escalate(discovery: dict[str, Any], portfolio: dict[str, Any]) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []
    low_confidence = [
        item["candidate_id"]
        for item in discovery["assessments"]
        if item["assessment_confidence"] == "low"
    ]
    if discovery["assessments"] and len(low_confidence) / len(discovery["assessments"]) > 0.20:
        reasons.append(
            {
                "code": "COMBINED_DISCOVERY_LOW_CONFIDENCE_RATE",
                "observed": len(low_confidence),
                "threshold": ">20%",
            }
        )
    low_topics = [
        topic["topic_id"]
        for topic in discovery["topics"]
        if topic["cluster_confidence"] == "low" and len(topic["members"]) >= 2
    ]
    if low_topics:
        reasons.append(
            {
                "code": "COMBINED_DISCOVERY_LOW_CONFIDENCE_MULTI_MEMBER_TOPIC",
                "topic_ids": low_topics,
            }
        )
    if portfolio["underfilled_due_to_quality"]:
        reasons.append(
            {
                "code": "ADAPTIVE_PORTFOLIO_UNDERFILLED",
                "observed": portfolio["selected_count"],
                "threshold": DESIRED_MINIMUM,
            }
        )
    return {
        "policy_version": "iteration-2-shadow-escalation-v1",
        "would_escalate": bool(reasons),
        "target_model_if_enabled": None,
        "actually_escalated": False,
        "reasons": reasons,
    }


def _expected_pipeline_call_ids(contract: dict[str, Any], summary: dict[str, Any]) -> list[str]:
    call_ids = list(contract["required_call_ids"])
    conditional = contract["conditional_call_ids"]
    if contract["skill_version"] == "v2" and int(summary["selected_count"]) > 0:
        call_ids.append(conditional["nonempty_portfolio"])
    if len(call_ids) != len(set(call_ids)):
        raise RuntimeError("pipeline contract contains duplicate call IDs")
    return sorted(call_ids)


def _verify_call_evidence(call_dir: Path) -> str:
    completion_path = call_dir / "complete.json"
    if (call_dir / "terminal.json").exists() or (call_dir / "terminal.json").is_symlink():
        raise RuntimeError(f"terminal call cannot be pipeline evidence: {call_dir}")
    if completion_path.is_symlink() or not completion_path.is_file():
        raise RuntimeError(f"pipeline call evidence is incomplete: {call_dir}")
    completion = _regular_json_object(completion_path, "pipeline call completion")
    contract = _validate_call_contract(call_dir)
    contract_path = call_dir / "call-contract.json"
    if (
        set(completion) != SUCCESSFUL_CALL_COMPLETION_KEYS
        or completion.get("schema_version") != "1"
        or completion.get("call_id") != contract["call_id"]
    ):
        raise RuntimeError(f"pipeline call completion shape drift: {call_dir}")
    if completion.get("call_contract_sha256") != _sha256_path(contract_path):
        raise RuntimeError(f"pipeline call contract receipt drift: {call_dir}")
    expected_infrastructure_receipts = _call_infrastructure_failure_receipt_inventory(
        call_dir, contract
    )
    if completion.get("infrastructure_failure_receipts") != expected_infrastructure_receipts:
        raise RuntimeError(f"pipeline call infrastructure receipt drift: {call_dir}")
    attempt_number = completion.get("successful_attempt")
    if (
        not isinstance(attempt_number, int)
        or isinstance(attempt_number, bool)
        or not 1 <= attempt_number <= MAX_MODEL_ATTEMPTS
    ):
        raise RuntimeError(f"pipeline call successful attempt is invalid: {call_dir}")
    attempt_contract = call_dir / "attempts" / f"{attempt_number:03d}" / "attempt-contract.json"
    if not attempt_contract.is_file() or completion.get(
        "successful_attempt_contract_sha256"
    ) != _sha256_path(attempt_contract):
        raise RuntimeError(f"pipeline call attempt receipt drift: {call_dir}")
    expected_attempt_receipts = _validate_attempt_prompt_chain(call_dir, contract, attempt_number)
    if _pretty_json_bytes(completion.get("attempt_receipts")) != _pretty_json_bytes(
        expected_attempt_receipts
    ):
        raise RuntimeError(f"pipeline call all-attempt receipt drift: {call_dir}")
    if (
        any(item["status"] != "failed" for item in expected_attempt_receipts[:-1])
        or expected_attempt_receipts[-1]["status"] != "validated"
    ):
        raise RuntimeError(f"pipeline call attempt status sequence drift: {call_dir}")
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
        if path.is_symlink() or not path.is_file() or _sha256_path(path) != digest:
            raise RuntimeError(f"pipeline call artifact drift: {path}")
    _verify_successful_attempt_mirrors(call_dir, attempt_number)
    expected_children = {
        "call-contract.json",
        "complete.json",
        "attempts",
        *expected_artifacts,
    }
    if (call_dir / "infrastructure-failures").exists():
        expected_children.add("infrastructure-failures")
    children = list(call_dir.iterdir())
    if {path.name for path in children} != expected_children or any(
        path.is_symlink() for path in children
    ):
        raise RuntimeError(f"pipeline call artifact inventory drift: {call_dir}")
    return _sha256_path(completion_path)


def _verified_call_snapshot(call_dir: Path) -> dict[str, Any]:
    """Return the exact bytes verified by the call completion receipt."""

    artifact_names = (
        "result.raw.json",
        "result.json",
        "validation.json",
        "call-metadata.json",
        "events.jsonl",
    )
    captured: dict[str, bytes] = {}
    for relative in ("call-contract.json", "complete.json", *artifact_names):
        path = call_dir / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"pipeline call artifact drift: {path}")
        captured[relative] = path.read_bytes()

    verified_completion_sha256 = _verify_call_evidence(call_dir)
    if _sha256_bytes(captured["complete.json"]) != verified_completion_sha256:
        raise RuntimeError(f"call completion changed during verified snapshot: {call_dir}")
    try:
        completion = json.loads(captured["complete.json"].decode("utf-8"))
        contract = json.loads(captured["call-contract.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"call snapshot contract or completion is unreadable: {call_dir}"
        ) from exc
    if not isinstance(completion, dict) or not isinstance(contract, dict):
        raise RuntimeError(f"call snapshot contract or completion is malformed: {call_dir}")
    if completion.get("call_contract_sha256") != _sha256_bytes(captured["call-contract.json"]):
        raise RuntimeError(f"call contract changed during verified snapshot: {call_dir}")
    expected_artifact_hashes = {
        relative: _sha256_bytes(captured[relative]) for relative in artifact_names
    }
    if completion.get("artifact_sha256") != expected_artifact_hashes:
        raise RuntimeError(f"call artifacts changed during verified snapshot: {call_dir}")

    parsed: dict[str, Any] = {
        "completion": completion,
        "completion_sha256": verified_completion_sha256,
        "contract": contract,
    }
    for relative in artifact_names[:-1]:
        try:
            value = json.loads(captured[relative].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"call snapshot JSON is unreadable: {call_dir / relative}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"call snapshot JSON must be an object: {call_dir / relative}")
        parsed[relative] = value
    return parsed


def _pipeline_attempt_costs_from_snapshots(
    snapshots: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    usage = {field: 0 for field in ATTEMPT_TOKEN_FIELDS}
    elapsed_seconds = 0.0
    attempt_count = 0
    usage_complete = True
    for snapshot in snapshots:
        completion = snapshot["completion"]
        for attempt in completion["attempt_receipts"]:
            attempt_count += 1
            elapsed_seconds += float(attempt["elapsed_seconds"])
            attempt_usage = attempt["usage"]
            if attempt_usage is None:
                usage_complete = False
                continue
            for field in ATTEMPT_TOKEN_FIELDS:
                usage[field] += int(attempt_usage[field])
    usage["reported_total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return {
        "normal_model_call_count": len(snapshots),
        "total_model_attempt_count": attempt_count,
        "completion_bound_total_elapsed_seconds": round(elapsed_seconds, 3),
        "completion_bound_total_usage": usage,
        "completion_bound_usage_complete": usage_complete,
    }


def _pipeline_attempt_costs(experiment_dir: Path, call_ids: Sequence[str]) -> dict[str, Any]:
    snapshots = [
        _verified_call_snapshot(experiment_dir / "calls" / call_id) for call_id in call_ids
    ]
    return _pipeline_attempt_costs_from_snapshots(snapshots)


def _pipeline_repair_budget_from_snapshots(
    snapshots: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    repaired_stages: list[str] = []
    total_repairs = 0
    for snapshot in snapshots:
        contract = snapshot["contract"]
        completion = snapshot["completion"]
        successful_attempt = completion["successful_attempt"]
        repairs = successful_attempt - 1
        total_repairs += repairs
        if repairs:
            repaired_stages.append(contract["stage"])
    if (
        total_repairs > MAX_PIPELINE_REPAIRS
        or total_repairs != len(repaired_stages)
        or len(repaired_stages) != len(set(repaired_stages))
    ):
        raise RuntimeError("completed pipeline repair budget drift")
    return {
        "maximum_repairs": MAX_PIPELINE_REPAIRS,
        "repairs_used": total_repairs,
        "used_by_stage": repaired_stages,
    }


def _pipeline_repair_budget_receipt(
    experiment_dir: Path, call_ids: Sequence[str]
) -> dict[str, Any]:
    snapshots = [
        _verified_call_snapshot(experiment_dir / "calls" / call_id) for call_id in call_ids
    ]
    return _pipeline_repair_budget_from_snapshots(snapshots)


def _verified_call_outputs(
    experiment_dir: Path, call_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    call_dir = experiment_dir / "calls" / call_id
    snapshot = _verified_call_snapshot(call_dir)
    return (
        snapshot["result.raw.json"],
        snapshot["result.json"],
        snapshot["validation.json"],
        snapshot["call-metadata.json"],
    )


def _assert_exact_json_artifact(path: Path, expected: Any, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is missing or unsafe: {path}")
    if path.read_bytes() != _pretty_json_bytes(expected):
        raise RuntimeError(f"{label} byte drift: {path}")


def _reconstruct_pipeline(
    pipeline_dir: Path, contract: dict[str, Any]
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[str],
    list[dict[str, str]],
]:
    experiment_dir = pipeline_dir.parents[1]
    source_id = contract["source_id"]
    manifest, immutable, evaluation_contract = _frozen_evaluation_context(experiment_dir)
    if contract.get("experiment_contract_sha256") != manifest.get("contract_sha256"):
        raise RuntimeError(f"pipeline-to-manifest contract binding drift: {pipeline_dir}")
    source_contract = next(
        (
            item
            for item in immutable.get("sources", [])
            if isinstance(item, dict) and item.get("source_id") == source_id
        ),
        None,
    )
    if not isinstance(source_contract, dict):
        raise RuntimeError(f"pipeline source contract is missing: {source_id}")
    evidence_bytes = _verified_indexed_experiment_bytes(
        experiment_dir,
        manifest,
        f"frozen/inputs/{source_id}.json",
        "pipeline frozen input",
        expected_sha256=source_contract.get("experiment_input_sha256"),
    )
    try:
        evidence = json.loads(evidence_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"pipeline frozen input is unreadable: {source_id}") from exc
    if not isinstance(evidence, dict):
        raise RuntimeError(f"pipeline frozen input must be an object: {source_id}")
    contracts_bytes = _verified_evaluation_copy_from_context(
        experiment_dir,
        manifest=manifest,
        immutable=immutable,
        evaluation_contract=evaluation_contract,
        source_relative_name=CONTRACTS_RELATIVE_PATH,
        frozen_relative_name="frozen/gates/contracts.py",
        immutable_field="contracts_sha256",
        label="frozen contracts module",
    )
    contracts = _execute_verified_module(
        module_role="v2_contracts_pipeline_snapshot",
        content=contracts_bytes,
        source_label="experiment://frozen/gates/contracts.py",
        required=CONTRACTS_INTERFACE,
    )
    candidates = evidence["candidates"]
    candidate_ids = [item["candidate_id"] for item in candidates]
    candidates_by_id = {item["candidate_id"]: item for item in candidates}

    if contract["skill_version"] == "v1":
        if len(contract["required_call_ids"]) != 1 or contract["conditional_call_ids"]:
            raise RuntimeError(f"v1 pipeline call topology drift: {pipeline_dir}")
        call_ids = list(contract["required_call_ids"])
        call_snapshot = _verified_call_snapshot(experiment_dir / "calls" / call_ids[0])
        raw = call_snapshot["result.raw.json"]
        metadata = call_snapshot["call-metadata.json"]
        result, validation = _validate_v1(raw, candidates, contracts)
        if call_snapshot["result.json"] != result:
            raise RuntimeError("v1 captured call result no longer validates")
        if call_snapshot["validation.json"] != validation:
            raise RuntimeError("v1 captured call validation receipt drift")
        call_snapshots = [call_snapshot]
        repair_budget = _pipeline_repair_budget_from_snapshots(call_snapshots)
        summary = {
            "pipeline_id": contract["pipeline_id"],
            "arm_id": contract["arm_id"],
            "source_id": source_id,
            "repeat": contract["repeat"],
            "selected_count": len(result["highlights"]),
            "underfilled_due_to_quality": False,
            "quote_gate_failed_count": validation["v2_quote_gate_shadow_audit"]["failed_count"],
            "call_elapsed_seconds": metadata["elapsed_seconds"],
            "repair_budget": repair_budget,
            "completed_at": metadata["completed_at"],
            **_pipeline_attempt_costs_from_snapshots(call_snapshots),
        }
        call_receipts = [
            {
                "call_id": call_ids[0],
                "call_completion_sha256": call_snapshot["completion_sha256"],
            }
        ]
        return (
            {"result.json": result, "validation.json": validation},
            summary,
            call_ids,
            call_receipts,
        )

    if contract["skill_version"] != "v2":
        raise RuntimeError(f"unknown pipeline Skill version: {pipeline_dir}")
    if len(contract["required_call_ids"]) != 1 or set(contract["conditional_call_ids"]) != {
        "nonempty_portfolio"
    }:
        raise RuntimeError(f"v2 pipeline call topology drift: {pipeline_dir}")
    combined_payload = _combined_discovery_payload(evidence)
    input_gate_bytes = _verified_evaluation_copy_from_context(
        experiment_dir,
        manifest=manifest,
        immutable=immutable,
        evaluation_contract=evaluation_contract,
        source_relative_name=INPUT_GATE_RELATIVE_PATH,
        frozen_relative_name="frozen/gates/input_gate.py",
        immutable_field="input_gate_sha256",
        label="frozen input gate module",
    )
    input_gate = _execute_verified_module(
        module_role="v2_input_gate_pipeline_snapshot",
        content=input_gate_bytes,
        source_label="experiment://frozen/gates/input_gate.py",
        required=INPUT_GATE_INTERFACE,
    )
    observed_payload = input_gate.canonical_json_bytes(combined_payload)
    gated_size = input_gate.validate_combined_payload_capacity(combined_payload)
    if (
        gated_size != len(observed_payload)
        or gated_size != source_contract["combined_payload_size_bytes"]
        or _sha256_bytes(observed_payload) != source_contract["combined_payload_sha256"]
    ):
        raise RuntimeError(f"pipeline combined payload capacity drift: {pipeline_dir}")
    capacity = {
        "input_gate_version": input_gate.INPUT_GATE_VERSION,
        "status": "passed",
        "payload_sha256": source_contract["combined_payload_sha256"],
        "observed_size_bytes": gated_size,
        "maximum_size_bytes": input_gate.MAX_COMBINED_PAYLOAD_BYTES,
    }
    combined_call_id = contract["required_call_ids"][0]
    combined_snapshot = _verified_call_snapshot(experiment_dir / "calls" / combined_call_id)
    raw = combined_snapshot["result.raw.json"]
    combined_metadata = combined_snapshot["call-metadata.json"]
    _assert_only_known_candidate_ids(raw, candidate_ids)
    discovery = contracts.validate_combined_discovery(raw, candidate_ids)
    combined_validation = {
        "all_candidate_accounting_gate": "passed",
        "candidate_order_gate": "passed",
        "accounting": discovery["accounting"],
        "topic_count": len(discovery["topics"]),
        "capacity": capacity,
    }
    if combined_snapshot["result.json"] != discovery:
        raise RuntimeError("captured combined call result no longer validates")
    if combined_snapshot["validation.json"] != combined_validation:
        raise RuntimeError("captured combined call validation receipt drift")
    selection = immutable["selection_configuration"]
    portfolio = contracts.select_adaptive_portfolio(
        candidates,
        discovery,
        desired_minimum=selection["desired_minimum"],
        maximum_count=selection["maximum_count"],
        base_minimum_quality=selection["base_minimum_quality"],
        maximum_interval_iou=selection["maximum_interval_iou"],
        maximum_text_jaccard=selection["maximum_text_jaccard"],
    )
    escalation = _would_escalate(discovery, portfolio)
    selected_ids = [item["candidate_id"] for item in portfolio["selected"]]
    selected_payload = []
    assessments_by_id = {item["candidate_id"]: item for item in discovery["assessments"]}
    for selected in portfolio["selected"]:
        candidate_id = selected["candidate_id"]
        selected_payload.append(
            {
                "candidate": candidates_by_id[candidate_id],
                "assessment": assessments_by_id[candidate_id],
                "selection": selected,
            }
        )
    call_ids = [combined_call_id]
    call_snapshots = [combined_snapshot]
    if selected_ids:
        selected_call_id = contract["conditional_call_ids"]["nonempty_portfolio"]
        call_ids.append(selected_call_id)
        selected_snapshot = _verified_call_snapshot(experiment_dir / "calls" / selected_call_id)
        call_snapshots.append(selected_snapshot)
        raw_copy = selected_snapshot["result.raw.json"]
        copy_metadata = selected_snapshot["call-metadata.json"]
        _assert_only_known_candidate_ids(raw_copy, selected_ids)
        _assert_no_cross_candidate_evidence(
            raw_copy, candidates_by_id=candidates_by_id, contracts=contracts
        )
        copies, receipts = contracts.validate_selected_copies_iteration2(
            raw_copy, selected_ids, candidates_by_id
        )
        result = contracts.compose_iteration2_result(
            candidates=candidates,
            discovery=discovery,
            portfolio=portfolio,
            copies=copies,
            receipts=receipts,
        )
        validation = {
            "selected_order_gate": "passed",
            "exact_quote_gate": "passed",
            "receipt_count": len(receipts),
            "receipts": receipts,
        }
        if selected_snapshot["result.json"] != result:
            raise RuntimeError("captured selected-copy call result no longer validates")
        if selected_snapshot["validation.json"] != validation:
            raise RuntimeError("captured selected-copy call validation receipt drift")
    else:
        copies, receipts = contracts.validate_selected_copies_iteration2(
            {
                "selection_summary": "没有候选达到冻结的确定性质量与去重门槛。",
                "copies": [],
            },
            [],
            candidates_by_id,
        )
        result = contracts.compose_iteration2_result(
            candidates=candidates,
            discovery=discovery,
            portfolio=portfolio,
            copies=copies,
            receipts=receipts,
        )
        validation = {
            "selected_order_gate": "passed",
            "exact_quote_gate": "passed",
            "receipt_count": len(receipts),
            "receipts": receipts,
            "status": "skipped_empty_portfolio",
        }
        copy_metadata = {
            "elapsed_seconds": 0.0,
            "completed_at": combined_metadata["completed_at"],
        }
    ordered_snapshots = [
        snapshot
        for _, snapshot in sorted(
            zip(call_ids, call_snapshots, strict=True), key=lambda item: item[0]
        )
    ]
    call_ids.sort()
    repair_budget = _pipeline_repair_budget_from_snapshots(ordered_snapshots)
    summary = {
        "pipeline_id": contract["pipeline_id"],
        "arm_id": contract["arm_id"],
        "source_id": source_id,
        "repeat": contract["repeat"],
        "selected_count": len(result["highlights"]),
        "underfilled_due_to_quality": portfolio["underfilled_due_to_quality"],
        "topic_count": len(discovery["topics"]),
        "exact_quote_failed_count": 0,
        "source_sentence_failed_count": 0,
        "would_escalate": escalation,
        "repair_budget": repair_budget,
        "stage_success_elapsed_seconds": {
            "combined_discovery": combined_metadata["elapsed_seconds"],
            "selected_copy": copy_metadata["elapsed_seconds"],
        },
        "completed_at": copy_metadata["completed_at"],
        **_pipeline_attempt_costs_from_snapshots(ordered_snapshots),
    }
    artifacts = {
        "combined-discovery.json": discovery,
        "combined-validation.json": combined_validation,
        "combined-payload-capacity.json": capacity,
        "adaptive-portfolio.json": portfolio,
        "would-escalate.json": escalation,
        "repair-budget.json": repair_budget,
        "result.json": result,
        "validation.json": validation,
    }
    call_receipts = [
        {
            "call_id": call_id,
            "call_completion_sha256": snapshot["completion_sha256"],
        }
        for call_id, snapshot in zip(call_ids, ordered_snapshots, strict=True)
    ]
    return artifacts, summary, call_ids, call_receipts


def _verified_pipeline_payload(
    pipeline_dir: Path,
    expected_contract: dict[str, Any],
) -> dict[str, Any] | None:
    complete_path = pipeline_dir / "complete.json"
    if not complete_path.exists():
        return None
    manifest, _ = _verified_experiment_manifest(pipeline_dir.parents[1])
    if expected_contract.get("experiment_contract_sha256") != manifest.get("contract_sha256"):
        raise RuntimeError(f"pipeline expected contract is not manifest-bound: {pipeline_dir}")
    contract_path = pipeline_dir / "pipeline-contract.json"
    if (
        pipeline_dir.is_symlink()
        or not pipeline_dir.is_dir()
        or contract_path.is_symlink()
        or not contract_path.is_file()
    ):
        raise RuntimeError(f"pipeline contract drift: {pipeline_dir}")
    expected_artifacts = {
        "result.json",
        "validation.json",
        "summary.json",
    }
    if expected_contract.get("skill_version") == "v2":
        expected_artifacts.update(
            {
                "combined-discovery.json",
                "combined-validation.json",
                "combined-payload-capacity.json",
                "adaptive-portfolio.json",
                "would-escalate.json",
                "repair-budget.json",
            }
        )
    captured: dict[str, bytes] = {}
    for relative in ("pipeline-contract.json", "complete.json", *expected_artifacts):
        path = pipeline_dir / relative
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"pipeline snapshot artifact is missing or unsafe: {path}")
        captured[relative] = path.read_bytes()
    try:
        captured_contract = json.loads(captured["pipeline-contract.json"].decode("utf-8"))
        complete = json.loads(captured["complete.json"].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"pipeline contract or completion is unreadable: {pipeline_dir}"
        ) from exc
    if (
        not isinstance(captured_contract, dict)
        or captured_contract != expected_contract
        or captured["pipeline-contract.json"] != _pretty_json_bytes(expected_contract)
    ):
        raise RuntimeError(f"pipeline contract drift: {pipeline_dir}")
    if not isinstance(complete, dict):
        raise RuntimeError(f"pipeline completion must be an object: {pipeline_dir}")
    if (
        set(complete)
        != {
            "schema_version",
            "pipeline_id",
            "pipeline_contract_sha256",
            "artifact_sha256",
            "call_receipts",
        }
        or complete.get("schema_version") != "1"
        or complete.get("pipeline_id") != expected_contract["pipeline_id"]
    ):
        raise RuntimeError(f"pipeline completion receipt shape/identity drift: {pipeline_dir}")
    if complete.get("pipeline_contract_sha256") != _sha256_bytes(
        captured["pipeline-contract.json"]
    ):
        raise RuntimeError(f"pipeline contract receipt drift: {pipeline_dir}")
    artifact_hashes = complete.get("artifact_sha256")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != expected_artifacts:
        raise RuntimeError(f"pipeline artifact receipt is incomplete: {pipeline_dir}")
    observed_artifact_hashes = {
        relative: _sha256_bytes(captured[relative]) for relative in expected_artifacts
    }
    if artifact_hashes != observed_artifact_hashes:
        raise RuntimeError(f"completed pipeline artifact drift during snapshot: {pipeline_dir}")
    (
        reconstructed_artifacts,
        reconstructed_summary,
        call_ids,
        reconstructed_call_receipts,
    ) = _reconstruct_pipeline(pipeline_dir, expected_contract)
    for relative, expected_value in reconstructed_artifacts.items():
        if captured.get(relative) != _pretty_json_bytes(expected_value):
            raise RuntimeError(
                f"completed pipeline deterministic artifact byte drift: {pipeline_dir / relative}"
            )
    if captured["summary.json"] != _pretty_json_bytes(reconstructed_summary):
        raise RuntimeError(f"completed pipeline deterministic summary byte drift: {pipeline_dir}")
    if complete.get("call_receipts") != reconstructed_call_receipts:
        raise RuntimeError(f"pipeline call receipt drift: {pipeline_dir}")
    if expected_contract["skill_version"] == "v2" and len(call_ids) > 2:
        raise RuntimeError(f"iteration-2 pipeline exceeds two normal model calls: {pipeline_dir}")
    expected_children = {
        "pipeline-contract.json",
        "complete.json",
        *expected_artifacts,
    }
    children = list(pipeline_dir.iterdir())
    if {path.name for path in children} != expected_children or any(
        path.is_symlink() for path in children
    ):
        raise RuntimeError(f"completed pipeline artifact inventory drift: {pipeline_dir}")
    return {
        "result": reconstructed_artifacts["result.json"],
        "summary": reconstructed_summary,
        "artifacts": reconstructed_artifacts,
        "call_ids": call_ids,
        "call_receipts": reconstructed_call_receipts,
        "pipeline_completion_sha256": _sha256_bytes(captured["complete.json"]),
    }


def _pipeline_completion(
    pipeline_dir: Path,
    expected_contract: dict[str, Any],
) -> dict[str, Any] | None:
    payload = _verified_pipeline_payload(pipeline_dir, expected_contract)
    return None if payload is None else payload["summary"]


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
    expected_artifacts, expected_summary, _, call_receipts = _reconstruct_pipeline(
        pipeline_dir, contract
    )
    if {relative: _pretty_json_bytes(value) for relative, value in artifacts.items()} != {
        relative: _pretty_json_bytes(value) for relative, value in expected_artifacts.items()
    } or _pretty_json_bytes(summary) != _pretty_json_bytes(expected_summary):
        raise RuntimeError(f"pipeline deterministic reconstruction drift: {pipeline_dir}")
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
    validated = _pipeline_completion(pipeline_dir, contract)
    assert validated is not None
    return validated


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
        contract.update(
            {
                "normal_model_call_limit": 2,
                "selection_configuration": prepared.manifest["immutable_contract"][
                    "selection_configuration"
                ],
                "sol_high_execution": False,
                "required_call_ids": [_call_id(pipeline_id, "v2-combined-discovery")],
                "conditional_call_ids": {
                    "nonempty_portfolio": _call_id(pipeline_id, "v2-selected-copy")
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
    _verify_experiment_trust_bridge(prepared.experiment_dir)
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
    prompt = _render_v1_prompt(
        evidence,
        prepared.v1_skill_text,
        "frozen/runtime/v1-skill.md",
    )
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
        "underfilled_due_to_quality": False,
        "quote_gate_failed_count": validation["v2_quote_gate_shadow_audit"]["failed_count"],
        "call_elapsed_seconds": metadata["elapsed_seconds"],
        "repair_budget": repair_budget.receipt(),
        "completed_at": metadata["completed_at"],
        **_pipeline_attempt_costs(prepared.experiment_dir, pipeline_contract["required_call_ids"]),
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
    _verify_experiment_trust_bridge(prepared.experiment_dir)
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

    repair_budget = RepairBudget()
    combined_payload = _combined_discovery_payload(evidence)
    source_contract = next(
        item
        for item in prepared.manifest["immutable_contract"]["sources"]
        if item["source_id"] == source_id
    )
    input_gate = prepared.input_gate
    observed_payload = input_gate.canonical_json_bytes(combined_payload)
    observed_payload_size_bytes = len(observed_payload)
    gated_size = input_gate.validate_combined_payload_capacity(combined_payload)
    if (
        gated_size != observed_payload_size_bytes
        or gated_size != source_contract["combined_payload_size_bytes"]
        or _sha256_bytes(observed_payload) != source_contract["combined_payload_sha256"]
    ):
        raise RuntimeError("combined discovery payload capacity receipt drift")
    capacity_receipt = {
        "input_gate_version": input_gate.INPUT_GATE_VERSION,
        "status": "passed",
        "payload_sha256": source_contract["combined_payload_sha256"],
        "observed_size_bytes": gated_size,
        "maximum_size_bytes": input_gate.MAX_COMBINED_PAYLOAD_BYTES,
    }
    combined_prompt = _render_v2_prompt(
        prepared.stage_bundles["combined-discovery"], combined_payload
    )
    combined_schema = prepared.experiment_dir / (
        f"frozen/schemas/{source_id}/combined-discovery.json"
    )

    def validate_combined(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        _assert_only_known_candidate_ids(raw, candidate_ids)
        discovery = prepared.contracts.validate_combined_discovery(raw, candidate_ids)
        return discovery, {
            "all_candidate_accounting_gate": "passed",
            "candidate_order_gate": "passed",
            "accounting": discovery["accounting"],
            "topic_count": len(discovery["topics"]),
            "capacity": capacity_receipt,
        }

    discovery, combined_validation, combined_metadata = _run_call(
        prepared=prepared,
        pipeline_id=pipeline_id,
        stage="v2-combined-discovery",
        prompt=combined_prompt,
        schema_path=combined_schema,
        dependency_hashes={
            "source_input": input_sha,
            "combined_payload": source_contract["combined_payload_sha256"],
            "runtime_bundle": _sha256_bytes(
                prepared.stage_bundles["combined-discovery"].encode("utf-8")
            ),
            "evaluation_contract": prepared.manifest["immutable_contract"][
                "evaluation_contract_sha256"
            ],
        },
        validator=validate_combined,
        repair_budget=repair_budget,
    )

    portfolio = prepared.contracts.select_adaptive_portfolio(
        candidates,
        discovery,
        desired_minimum=DESIRED_MINIMUM,
        maximum_count=MAXIMUM_COUNT,
        base_minimum_quality=BASE_MINIMUM_QUALITY,
        maximum_interval_iou=MAXIMUM_INTERVAL_IOU,
        maximum_text_jaccard=MAXIMUM_TEXT_JACCARD,
    )
    escalation = _would_escalate(discovery, portfolio)
    selected_ids = [item["candidate_id"] for item in portfolio["selected"]]
    selected_payload = []
    assessment_by_id = {item["candidate_id"]: item for item in discovery["assessments"]}
    for selected in portfolio["selected"]:
        candidate_id = selected["candidate_id"]
        selected_payload.append(
            {
                "candidate": candidates_by_id[candidate_id],
                "assessment": assessment_by_id[candidate_id],
                "selection": selected,
            }
        )
    copy_payload = {
        "task": "iteration_2_selected_copy",
        "source": {
            "duration_ms": evidence["source"]["duration_ms"],
            "source_sha256": evidence["source"]["source_sha256"],
            "evidence_note": "Text-only ASR evidence; no video frames are supplied.",
        },
        "selected_candidates_in_required_order": selected_payload,
    }
    copy_prompt = _render_v2_prompt(prepared.stage_bundles["selected-copy"], copy_payload)
    copy_schema = prepared.experiment_dir / (f"frozen/schemas/{source_id}/selected-copy.json")

    def validate_copy(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        _assert_only_known_candidate_ids(raw, selected_ids)
        _assert_no_cross_candidate_evidence(
            raw,
            candidates_by_id=candidates_by_id,
            contracts=prepared.contracts,
        )
        copies, receipts = prepared.contracts.validate_selected_copies_iteration2(
            raw, selected_ids, candidates_by_id
        )
        final_result = prepared.contracts.compose_iteration2_result(
            candidates=candidates,
            discovery=discovery,
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
        final_result, copy_validation, copy_metadata = _run_call(
            prepared=prepared,
            pipeline_id=pipeline_id,
            stage="v2-selected-copy",
            prompt=copy_prompt,
            schema_path=copy_schema,
            dependency_hashes={
                "source_input": input_sha,
                "combined_discovery": _sha256_bytes(_canonical_bytes(discovery)),
                "adaptive_portfolio": _sha256_bytes(_canonical_bytes(portfolio)),
                "selected_payload": _sha256_bytes(_canonical_bytes(copy_payload)),
                "runtime_bundle": _sha256_bytes(
                    prepared.stage_bundles["selected-copy"].encode("utf-8")
                ),
                "evaluation_contract": prepared.manifest["immutable_contract"][
                    "evaluation_contract_sha256"
                ],
            },
            validator=validate_copy,
            repair_budget=repair_budget,
        )
    else:
        final_result, copy_validation = validate_copy(
            {
                "selection_summary": "没有候选达到冻结的确定性质量与去重门槛。",
                "copies": [],
            }
        )
        copy_validation["status"] = "skipped_empty_portfolio"
        copy_metadata = {
            "status": "skipped_empty_portfolio",
            "model_call_count": 0,
            "elapsed_seconds": 0.0,
            "completed_at": combined_metadata["completed_at"],
        }
    call_ids = list(pipeline_contract["required_call_ids"])
    if selected_ids:
        call_ids.append(pipeline_contract["conditional_call_ids"]["nonempty_portfolio"])
    if len(call_ids) > 2:
        raise RuntimeError("iteration-2 contender exceeded two normal model Calls")
    attempt_costs = _pipeline_attempt_costs(prepared.experiment_dir, sorted(call_ids))
    summary = {
        "pipeline_id": pipeline_id,
        "arm_id": identity["arm_id"],
        "source_id": source_id,
        "repeat": identity["repeat"],
        "selected_count": len(final_result["highlights"]),
        "underfilled_due_to_quality": portfolio["underfilled_due_to_quality"],
        "topic_count": len(discovery["topics"]),
        "exact_quote_failed_count": 0,
        "source_sentence_failed_count": 0,
        "would_escalate": escalation,
        "repair_budget": repair_budget.receipt(),
        "stage_success_elapsed_seconds": {
            "combined_discovery": combined_metadata["elapsed_seconds"],
            "selected_copy": copy_metadata["elapsed_seconds"],
        },
        "completed_at": copy_metadata["completed_at"],
        **attempt_costs,
    }
    artifacts = {
        "combined-discovery.json": discovery,
        "combined-validation.json": combined_validation,
        "combined-payload-capacity.json": capacity_receipt,
        "adaptive-portfolio.json": portfolio,
        "would-escalate.json": escalation,
        "repair-budget.json": repair_budget.receipt(),
        "result.json": final_result,
        "validation.json": copy_validation,
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
    _verify_experiment_trust_bridge(prepared.experiment_dir)
    _ensure_runtime_preflight(prepared)
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
        "planned_v2_model_calls_before_repairs_maximum": (
            len(prepared.sources) * REPEATS_PER_SOURCE * 2
        ),
        "planned_total_model_calls_before_repairs_maximum": (
            len(prepared.sources) * REPEATS_PER_SOURCE * 3
        ),
        "sol_high_call_count": 0,
        "message": "Immutable inputs and plan verified; no model was invoked.",
    }


def _preflight_only_summary(prepared: PreparedExperiment) -> dict[str, Any]:
    _verify_experiment_trust_bridge(prepared.experiment_dir)
    receipt = _ensure_runtime_preflight(prepared)
    if (
        receipt.get("model_started") is not False
        or receipt.get("model_attempt_consumed") is not False
    ):
        raise RuntimeError("zero-model preflight receipt unexpectedly consumed a model attempt")
    return {
        "schema_version": "1",
        "experiment_id": prepared.experiment_id,
        "experiment_dir": str(prepared.experiment_dir),
        "contract_sha256": prepared.contract_sha256,
        "preflight_only": True,
        "model_calls": 0,
        "model_started": False,
        "preflight_receipt": receipt,
        "message": (
            "Immutable experiment and real stdio/EOF Codex preflight verified; "
            "no generator call started."
        ),
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
        "--preflight-only",
        action="store_true",
        help=(
            "freeze/verify the experiment and run only the real stdio/EOF zero-model "
            "Codex compatibility preflight"
        ),
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
    if args.preflight_only and (args.dry_run or args.sentinel):
        parser.error("--preflight-only is mutually exclusive with --dry-run and --sentinel")
    output_root = _validate_output_root(args.output_root)
    evaluation_materials = _load_evaluation_materials()
    prepared = _prepare_experiment(output_root, evaluation_materials=evaluation_materials)
    if args.preflight_only:
        result = _preflight_only_summary(prepared)
    elif args.dry_run:
        result = _dry_run_summary(prepared, sentinel=args.sentinel)
    else:
        result = _run_experiment(prepared, sentinel=args.sentinel)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
