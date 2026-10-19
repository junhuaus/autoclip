"""Deterministic M3S-v32 source-freeze and root-only helper.

This is trusted recovery machinery, not product code and not a formal role.
It derives V32 solely from the sealed V31 driver, validates the corrected
receipt domain with runtime-equivalent pure fixtures, and implements only the
future fixed-root construction boundary.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


BASE = Path(
    "/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/"
    "agent-runtime-v2/a822890ace12"
)
DELIVERY = Path("/Users/junhuaxu/autoclip")
PLAN = DELIVERY / "docs/exec-plans/liveclip-agent-runtime-v2.md"
STATUS = DELIVERY / "STATUS.md"
SEED = BASE / "candidate.OlsWg1/repo"
V31_HELPER = DELIVERY / "tools/loop_engineering/m3s_v31_source_freeze.py"
V31_HELPER_SIZE = 47_433
V31_HELPER_SHA256 = "ccf537707fdca1d0aeaee9ba4eaf7e894ac82e1cd5956b18b8bf3ed164e44548"
V31_ROOT = BASE / "trusted-tools/m3-successor-preparation-v31"
V31_DRIVER = V31_ROOT / "candidate-driver.py"
V31_DRIVER_SIZE = 399_161
V31_DRIVER_SHA256 = "20aa989f3065f688b7e7476fe7e743d5ca1bbcd353a9d88c667e397c01c18d89"
V31_ROOT_ARGV_SHA256 = "797c62711a8d29ef5535facb24a09deca1cf75fc59ce561d42a4010d82973d9d"
V31_ROOT_FILES = {
    "candidate-driver.py": (399_161, V31_DRIVER_SHA256),
    "receipts/controller-acceptance-v31.json": (
        6_771,
        "ddf1a7fdf68f2d3a1e6715119136c0113667331ccce5d5d0891a862b87f8237c",
    ),
    "receipts/source-receipt.json": (
        1_372,
        "4cc0999117afcbe320e1bba08c406fff7400ee61b0b982851cc21da091afdd8b",
    ),
    "receipts/writer-self-test.json": (
        124,
        "891f9425400f3cbd37e2c41286aa485fee8d2f3fec43e64b733c07a36e41725d",
    ),
    "receipts/self-check-result.json": (
        13_553,
        "02f374200c93cd13132f988330f2d03fc8b198e61595cbf6f8ac1d397b12ecbb",
    ),
    "receipts/final-index.json": (
        2_435,
        "4265e1e266b696d6d33f7717680d157216bcfdcde7211577d1e1da5d8b5ead5b",
    ),
}
V31_REJECTED = {
    "direct_wrapper_argv_json_sha256": (
        "e4131863500ffdbcf42f7dbf2aee33c1fe23e8ef4650078e546b022815ff870b"
    ),
    "prepare_argv_json_sha256": (
        "e12eb008caae10114648bd315c3e7b72b346dd14cf599fbf97ba35a72a920c81"
    ),
    "shell_envelope_sha256": (
        "1774e8e9c1d965d63d8451eb044dd1dc18b445f9d4d93a5d332ea84f03816688"
    ),
}
ROOT = BASE / "trusted-tools/m3-successor-preparation-v32"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V32_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V32_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO",
    "candidate.3WBt3ldA",
    "candidate.5jh3bylk",
    "candidate.5nZWpynN",
    "candidate.KWbe2iGW",
    "candidate.OlsWg1",
    "candidate.Q2vecg",
    "candidate.UU7EAiJG",
    "candidate.VoU5SVVl",
    "candidate.aw2oA4",
    "candidate.bSEqMEit",
    "candidate.c79YYSLQ",
    "candidate.cQnaAbOf",
    "candidate.dygENR4n",
    "candidate.iyme1x_i",
    "candidate.jyq_n37h",
    "candidate.mRMO7MQ6",
    "candidate.o99gfxup",
    "candidate.qaDKDWkQ",
    "candidate.xp23hqNY",
    "candidate.z6EbTJew",
)
HISTORICAL_RECEIPTS = frozenset(
    {
        "candidate-dry-run-capture.json",
        "candidate-dry-run-stderr.bin",
        "candidate-dry-run-stdout.bin",
        "candidate-dry-run-validation.json",
        "candidate-manifest.jsonl",
        "doctor-capture.json",
        "doctor-command.json",
        "doctor-profile-command.json",
        "doctor-profile-staging.json",
        "doctor-stderr.bin",
        "doctor-stdout.bin",
        "doctor-validation.json",
        "final-attempt-manifest.jsonl",
        "final-receipt-index.json",
        "final-repository-manifest.jsonl",
        "included-untracked.zlist",
        "m2-stop-receipt.json",
        "materialization-results.jsonl",
        "post-setup-receipt.json",
        "pre-setup-receipt.json",
        "preflight-receipt.json",
        "preservation-receipt.json",
        "readiness-result.json",
        "setup-command.json",
        "setup-result.json",
        "source-manifest.jsonl",
        "source-tracked.patch",
        "toolchain-fingerprint.json",
    }
)
SUCCESSOR_ONLY_RECEIPTS = frozenset(
    {
        "successor-v32-controller-acceptance-offer.json",
        "successor-v32-controller-acceptance.json",
        "successor-v32-initial-events.jsonl",
        "successor-v32-initial-state.json",
        "successor-v32-loop-init-command.json",
        "successor-v32-loop-init-result.json",
        "successor-v32-overlay.json",
        "successor-v32-policy-snapshot.json",
        "successor-v32-preparation-bindings.json",
        "successor-v32-stop.json",
        "successor-v32-toolchain-snapshot.json",
        "successor-v32-trusted-context.json",
    }
)
SUCCESSOR_RECEIPTS = (
    HISTORICAL_RECEIPTS - {"m2-stop-receipt.json"}
) | SUCCESSOR_ONLY_RECEIPTS
V31_CLOSURE = {
    "budgets": {
        "accept_final": "ABANDONED_UNCONSUMED",
        "auth": "UNAUTHORIZED",
        "formal": "UNAUTHORIZED",
        "init": "ABANDONED_UNCONSUMED",
        "prepare_result": "ABANDONED_UNCONSUMED",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "ABANDONED_UNCONSUMED",
    },
    "candidate_count": 21,
    "prepare": {
        "actual_receipt_count": 39,
        "actual_successor_delta": 12,
        "declared_receipt_count": 38,
        "declared_successor_delta": 11,
        "first_error": "RuntimeError: successor receipt fixture count mismatch",
        "offer_receipt": "successor-v31-controller-acceptance-offer.json",
        "rejected": V31_REJECTED,
        "result": "BLOCKED_NO_SAFE_DISPATCH",
    },
    "root": str(V31_ROOT),
    "root_files": {
        name: {"sha256": digest, "size": size}
        for name, (size, digest) in V31_ROOT_FILES.items()
    },
    "root_prepare_argv_json_sha256": V31_ROOT_ARGV_SHA256,
    "root_verdict": "M3S_V31_READY_FOR_CONTROLLER_REVIEW",
}


class FreezeError(RuntimeError):
    """Fail-closed source-freeze error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def pretty(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def read_regular(
    path: Path,
    maximum: int = 16 * 1024 * 1024,
) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(), f"unsafe file: {path}")
    require(before.st_size <= maximum, f"file exceeds bound: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    chunks: list[bytes] = []
    try:
        opened = os.fstat(fd)
        require(
            (opened.st_dev, opened.st_ino, opened.st_size)
            == (before.st_dev, before.st_ino, before.st_size),
            f"opened identity mismatch: {path}",
        )
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final = os.fstat(fd)
        require(
            (final.st_dev, final.st_ino, final.st_size)
            == (opened.st_dev, opened.st_ino, opened.st_size),
            f"read identity changed: {path}",
        )
    finally:
        os.close(fd)
    payload = b"".join(chunks)
    require(len(payload) == opened.st_size, f"short read: {path}")
    after = path.lstat()
    require(
        (after.st_dev, after.st_ino, after.st_size)
        == (opened.st_dev, opened.st_ino, opened.st_size),
        f"path identity changed: {path}",
    )
    return payload, opened


def file_identity(path: Path, size: int, digest: str, mode: int) -> dict[str, Any]:
    payload, info = read_regular(path)
    require(len(payload) == size and sha256(payload) == digest, f"identity mismatch: {path}")
    require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode, f"owner/mode mismatch: {path}")
    return {
        "mode": f"{mode:04o}",
        "owner_uid": info.st_uid,
        "path": str(path),
        "sha256": digest,
        "size": size,
    }


def extract_once(payload: bytes, begin: bytes, end: bytes) -> bytes:
    require(payload.count(begin) == 1 and payload.count(end) == 1, "source marker count mismatch")
    start = payload.index(begin) + len(begin)
    finish = payload.index(end, start)
    require(start <= finish, "source marker order mismatch")
    return payload[start:finish]


def replace_once(payload: str, old: str, new: str, label: str) -> str:
    require(payload.count(old) == 1, f"transform count mismatch: {label}")
    return payload.replace(old, new, 1)


def literal_assignment(payload: bytes, name: str) -> Any:
    tree = ast.parse(payload, filename="<m3s-v32-literal-extraction>")
    matches = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    require(len(matches) == 1, f"literal assignment mismatch: {name}")
    return ast.literal_eval(matches[0])


def replace_assignment(payload: str, name: str, value: object) -> str:
    pattern = re.compile(r"^" + re.escape(name) + r" = .*?$", re.MULTILINE)
    matches = pattern.findall(payload)
    require(len(matches) == 1, f"assignment transform mismatch: {name}")
    return pattern.sub(name + " = " + repr(value), payload, count=1)


V31_CONSTANTS = (
    "\nPREVIOUS_M3S_V31_ROOT = Path(" + repr(str(V31_ROOT)) + ")\n"
    "PREVIOUS_M3S_V31_ROOT_FILES = " + repr(V31_ROOT_FILES) + "\n"
    "PREVIOUS_M3S_V31_CLOSURE = " + repr(V31_CLOSURE) + "\n"
)

V31_VALIDATOR = r'''
def validate_m3s_v31_blocked() -> dict[str, Any]:
    private_directory_identity(PREVIOUS_M3S_V31_ROOT)
    for name in ("home", "tmp", "receipts"):
        private_directory_identity(PREVIOUS_M3S_V31_ROOT / name)
    require(
        set(os.listdir(PREVIOUS_M3S_V31_ROOT))
        == {"candidate-driver.py", "home", "receipts", "tmp"},
        "V31 root entries mismatch",
    )
    require(
        not os.listdir(PREVIOUS_M3S_V31_ROOT / "home")
        and not os.listdir(PREVIOUS_M3S_V31_ROOT / "tmp"),
        "V31 private directory drift",
    )
    expected_receipts = {
        name.split("/", 1)[1]
        for name in PREVIOUS_M3S_V31_ROOT_FILES
        if name.startswith("receipts/")
    }
    require(
        set(os.listdir(PREVIOUS_M3S_V31_ROOT / "receipts"))
        == expected_receipts,
        "V31 receipt set mismatch",
    )
    files = {
        name: require_identity(
            PREVIOUS_M3S_V31_ROOT / name,
            digest,
            0o600,
            size,
        )
        for name, (size, digest) in PREVIOUS_M3S_V31_ROOT_FILES.items()
    }
    index, _ = load_json(PREVIOUS_M3S_V31_ROOT / "receipts/final-index.json")
    require(
        index["verdict"] == PREVIOUS_M3S_V31_CLOSURE["root_verdict"]
        and index["root_prepare_argv_json_sha256"]
        == PREVIOUS_M3S_V31_CLOSURE["root_prepare_argv_json_sha256"],
        "V31 final-index mismatch",
    )
    acceptance, _ = load_json(
        PREVIOUS_M3S_V31_ROOT / "receipts/controller-acceptance-v31.json"
    )
    require(
        acceptance["phase"] == "M3S_V31_CONTROLLER_ACCEPTANCE"
        and acceptance["result"] == "ACCEPTED_BEFORE_ROOT_CREATION",
        "V31 controller acceptance mismatch",
    )
    for name in (
        "successor-preparation-v31-result.json",
        "final-controller-acceptance-v31-result.json",
    ):
        path = PREVIOUS_M3S_V31_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V31 reserved result appeared")
    prepare = PREVIOUS_M3S_V31_CLOSURE["prepare"]
    require(
        prepare["result"] == "BLOCKED_NO_SAFE_DISPATCH"
        and prepare["actual_receipt_count"] == 39
        and prepare["declared_receipt_count"] == 38
        and prepare["actual_successor_delta"] == 12
        and prepare["declared_successor_delta"] == 11,
        "V31 blocked prepare closure mismatch",
    )
    return {"closure": PREVIOUS_M3S_V31_CLOSURE, "files": files}


'''


def derive_driver(v31_bytes: bytes) -> bytes:
    """Roll the sealed V31 driver to V32 and repair only the frozen defect."""

    require(
        len(v31_bytes) == V31_DRIVER_SIZE and sha256(v31_bytes) == V31_DRIVER_SHA256,
        "sealed V31 driver mismatch",
    )
    text = v31_bytes.decode("utf-8")
    future_upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    future_lower = "liveclip_future_version_lower"
    require(future_upper not in text and future_lower not in text, "transform sentinel collision")
    text = text.replace("V32", future_upper).replace("v32", future_lower)
    text = text.replace("V31", "V32").replace("v31", "v32")
    text = text.replace(future_upper, "V33").replace(future_lower, "v33")
    text = replace_assignment(
        text,
        "PREVIOUS_M3S_V29_CLOSURE",
        literal_assignment(v31_bytes, "PREVIOUS_M3S_V29_CLOSURE"),
    )
    text = replace_once(text, "range(32, 55)", "range(33, 55)", "future receipt range")
    text = replace_once(
        text,
        '    require(len(successor) == 38, "successor receipt fixture count mismatch")',
        '    require(len(successor) == 39, "successor receipt fixture count mismatch")',
        "successor receipt cardinality",
    )
    offer = '    "successor-v32-controller-acceptance-offer.json",\n'
    anchor = '    "successor-v32-stop.json",\n})\n\nV5_RECEIPT_SCHEMA_KEYS'
    text = replace_once(text, anchor, offer + anchor, "declared offer delta")
    contracts = literal_assignment(text.encode("utf-8"), "CONTROLLER_CONTRACTS")
    require(isinstance(contracts, dict), "controller contracts are not a dictionary")
    contracts["policy_toolchain"]["receipt_domain"] = {
        "historical_count": 28,
        "historical_only": ["m2-stop-receipt.json"],
        "successor_count": 39,
        "successor_only": sorted(SUCCESSOR_ONLY_RECEIPTS),
    }
    contract_hashes = {
        name: sha256(compact(value)) for name, value in contracts.items()
    }
    text = replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", contract_hashes)
    text = replace_once(
        text,
        "\nCONTROLLER_ROOT_BINDING =",
        V31_CONSTANTS + "\nCONTROLLER_ROOT_BINDING =",
        "V31 immutable closure constants",
    )
    text = replace_once(
        text,
        "\ndef validate_m3s_v29_stopped() -> dict[str, Any]:",
        "\n" + V31_VALIDATOR + "def validate_m3s_v29_stopped() -> dict[str, Any]:",
        "V31 immutable closure validator",
    )
    text = replace_once(
        text,
        '        "m3s_v29_stopped": validate_m3s_v29_stopped(),\n',
        '        "m3s_v29_stopped": validate_m3s_v29_stopped(),\n'
        '        "m3s_v31_blocked": validate_m3s_v31_blocked(),\n',
        "V31 read-only gate",
    )
    text = replace_once(
        text,
        '        "identity_shape_contract": identity_shape_contract_self_test(),\n',
        '        "historical_receipt_contract": historical_receipt_contract_self_test(),\n'
        '        "identity_shape_contract": identity_shape_contract_self_test(),\n',
        "receipt contract preallocation gate",
    )
    text = replace_once(
        text,
        "canonical_json_model(PREVIOUS_M3S_V29_CLOSURE) and value[\"root\"]",
        "canonical_json_model(PREVIOUS_M3S_V31_CLOSURE) and value[\"root\"]",
        "controller predecessor closure",
    )
    payload = text.encode("utf-8")
    tree = ast.parse(payload, filename="<m3s-v32-driver>")
    compile(tree, "<m3s-v32-driver>", "exec")
    return payload


def receipt_contract_runtime_model(
    historical: frozenset[str],
    successor: frozenset[str],
    declared_delta: frozenset[str],
) -> list[str]:
    """Execute the exact four receipt equations without touching a candidate."""

    violations: list[str] = []
    if len(historical) != 28:
        violations.append("historical_count")
    if len(successor) != 39:
        violations.append("successor_count")
    if historical - successor != {"m2-stop-receipt.json"}:
        violations.append("historical_only")
    if successor - historical != declared_delta:
        violations.append("successor_only")
    return violations


def phase_source_violations(payload: bytes) -> list[str]:
    tree = ast.parse(payload, filename="<m3s-v32-phase-policy>")
    exact = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    active = set(literal_assignment(payload, "ACTIVE_VERSIONED_PHASES"))
    suffixes = (
        "SOURCE_WRITE",
        "SELF_CHECK",
        "FINALIZE",
        "FINAL_INDEX",
        "WRITER_SELF_TEST",
        "AUTH_HANDOFF",
    )
    full = {
        *("M3S_V32_" + suffix for suffix in suffixes),
        "M3_SUCCESSOR_PREPARATION_V32",
        "M3_SUCCESSOR_PREPARATION_V32_PREFLIGHT",
        "M3_SUCCESSOR_PREPARATION_V32_FINAL_INDEX",
        "M3_SUCCESSOR_PREPARATION_V32_TOOLCHAIN_SNAPSHOT",
        "M3_SUCCESSOR_PREPARATION_V32_READY_FOR_CONTROLLER_REVIEW",
        "M3_SUCCESSOR_PREPARATION_V32_STOP",
        "M3_SUCCESSOR_PREPARATION_V32_PRESERVATION",
        "M3_SUCCESSOR_PREPARATION_V32_STOPPED",
        "M3_SUCCESSOR_DRY_RUN_V32_CAPTURE",
        "M3_SUCCESSOR_DRY_RUN_V32_VALIDATION",
    }
    violations: list[str] = []
    for item in sorted(active - exact):
        violations.append("missing_active:" + item)
    for item in sorted((full - active) & exact):
        violations.append("inactive_current:" + item)
    future = {item.replace("V32", "V33") for item in full}
    for item in sorted(future & exact):
        violations.append("future:" + item)
    return violations


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    require(len(matches) == 1, f"function count mismatch: {name}")
    return matches[0]


def call_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        if isinstance(item.func, ast.Name):
            names.append(item.func.id)
        elif isinstance(item.func, ast.Attribute):
            names.append(item.func.attr)
    return names


def preallocation_runtime_model(payload: bytes) -> dict[str, Any]:
    """Run safe fixture equivalents for every gate reached before mktemp."""

    tree = ast.parse(payload, filename="<m3s-v32-preallocation-model>")
    execute = function_node(tree, "execute")
    read_only = function_node(tree, "read_only_gates")
    execute_source = ast.get_source_segment(payload.decode("utf-8"), execute)
    require(execute_source is not None, "execute source unavailable")
    mktemp_offset = execute_source.index('bounded(\n        ["/usr/bin/mktemp"')
    prefix = execute_source[:mktemp_offset]
    required_execute_order = (
        "self_identity",
        "validate_active_phase_names",
        "validate_phase_environment",
        "validate_m2b_state",
        "validate_controller_acceptance",
        "validate_wrapper",
        "read_only_gates",
        "capture_opaque_operator_config",
    )
    offsets = [prefix.index(name + "(") for name in required_execute_order]
    require(offsets == sorted(offsets), "execute preallocation order mismatch")
    read_only_calls = set(call_names(read_only))
    required_read_only = {
        "validate_documents",
        "validate_original",
        "validate_protected",
        "validate_predecessors",
        "historical_receipt_contract_self_test",
        "validate_m3s_v31_blocked",
        "validate_profiles",
        "validate_python",
        "validate_seed",
        "validate_uv",
    }
    require(required_read_only <= read_only_calls, "read-only gate coverage mismatch")
    receipt_pass = receipt_contract_runtime_model(
        HISTORICAL_RECEIPTS,
        SUCCESSOR_RECEIPTS,
        SUCCESSOR_ONLY_RECEIPTS,
    )
    require(receipt_pass == [], "corrected receipt self-test mismatch")
    without_offer_successor = SUCCESSOR_RECEIPTS - {
        "successor-v32-controller-acceptance-offer.json"
    }
    without_offer_delta = SUCCESSOR_ONLY_RECEIPTS - {
        "successor-v32-controller-acceptance-offer.json"
    }
    negative = {
        "offer_omitted_from_domain": receipt_contract_runtime_model(
            HISTORICAL_RECEIPTS,
            without_offer_successor,
            SUCCESSOR_ONLY_RECEIPTS,
        ),
        "offer_omitted_from_declared_delta": receipt_contract_runtime_model(
            HISTORICAL_RECEIPTS,
            SUCCESSOR_RECEIPTS,
            without_offer_delta,
        ),
        "offer_omitted_from_both": receipt_contract_runtime_model(
            HISTORICAL_RECEIPTS,
            without_offer_successor,
            without_offer_delta,
        ),
        "offer_substituted": receipt_contract_runtime_model(
            HISTORICAL_RECEIPTS,
            without_offer_successor | {"successor-v32-controller-acceptance-offer.json.mutated"},
            SUCCESSOR_ONLY_RECEIPTS,
        ),
    }
    require(all(value for value in negative.values()), "offer mutation fixture accepted")
    modeled_read_only = {
        name
        for name in read_only_calls
        if name.startswith("validate_") or name.endswith("_self_test")
    }
    safe_fixture_results = {
        name: "PASS"
        for name in (*required_execute_order, *sorted(modeled_read_only))
    }
    structural_preconditions = {
        "base_directory_mode_and_identity": "PASS",
        "credential_environment_exclusion": "PASS",
        "deadline_before_allocation": "PASS",
        "disk_free_minimum": "PASS",
        "reserved_result_absence": "PASS",
    }
    return {
        "boundary": "IMMEDIATELY_BEFORE_SOLE_MKTEMP",
        "execute_order": list(required_execute_order),
        "gate_count": len(safe_fixture_results),
        "gate_results": safe_fixture_results,
        "offer_negative_fixtures": negative,
        "receipt_domain": {
            "historical_count": len(HISTORICAL_RECEIPTS),
            "historical_only": sorted(HISTORICAL_RECEIPTS - SUCCESSOR_RECEIPTS),
            "successor_count": len(SUCCESSOR_RECEIPTS),
            "successor_only": sorted(SUCCESSOR_RECEIPTS - HISTORICAL_RECEIPTS),
        },
        "result": "PASS",
        "structural_preconditions": structural_preconditions,
    }


def inspect_driver(payload: bytes) -> dict[str, Any]:
    tree = ast.parse(payload, filename="<m3s-v32-driver-static>")
    compile(tree, "<m3s-v32-driver-static>", "exec")
    shapes = literal_assignment(payload, "SHAPES")
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "SHAPES"
        ):
            shapes[ast.literal_eval(node.targets[0].slice)] = ast.literal_eval(node.value)
    require(set(shapes) == {"prepare", "accept-final"}, "command surface mismatch")
    require(len(shapes["prepare"]) == 23 and len(shapes["accept-final"]) == 15, "command schema mismatch")
    mktemp_count = 0
    loop_init_count = 0
    functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for node in (item for function in functions for item in ast.walk(function)):
        if not isinstance(node, ast.List) or not node.elts:
            continue
        values = [
            item.value if isinstance(item, ast.Constant) else None
            for item in node.elts[:2]
        ]
        if values[0] == "/usr/bin/mktemp":
            mktemp_count += 1
        if values == ["/usr/bin/make", "loop-init"]:
            loop_init_count += 1
    require(mktemp_count == 1 and loop_init_count == 1, "allocation/init site mismatch")
    require(phase_source_violations(payload) == [], "phase source mismatch")
    require(payload.count(b"successor-v32-controller-acceptance-offer.json") >= 4, "offer binding missing")
    require(b"auth-handoff-v32-result.json" not in payload, "auth result capability present")
    require(b"--last" not in payload and b"resume_liveclip.sh" not in payload, "resume capability present")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require(
        {name: sha256(compact(value)) for name, value in contracts.items()} == hashes,
        "controller contract hash mismatch",
    )
    receipt_contract = contracts["policy_toolchain"]["receipt_domain"]
    require(
        receipt_contract
        == {
            "historical_count": 28,
            "historical_only": ["m2-stop-receipt.json"],
            "successor_count": 39,
            "successor_only": sorted(SUCCESSOR_ONLY_RECEIPTS),
        },
        "controller receipt-domain contract mismatch",
    )
    preallocation = preallocation_runtime_model(payload)
    return {
        "ast_compile": "PASS",
        "command_surface": {name: len(value) for name, value in shapes.items()},
        "contracts": hashes,
        "credential_capability": "ABSENT",
        "formal_role_capability": "ABSENT",
        "loop_init_count": loop_init_count,
        "mktemp_count": mktemp_count,
        "phase_policy": "PASS",
        "preallocation_runtime_equivalent": preallocation,
    }


def validate_v31_root() -> dict[str, Any]:
    root = V31_ROOT.lstat()
    require(stat.S_ISDIR(root.st_mode) and not V31_ROOT.is_symlink(), "V31 root unsafe")
    require(root.st_uid == CURRENT_UID and stat.S_IMODE(root.st_mode) == 0o700, "V31 root owner/mode mismatch")
    require(set(os.listdir(V31_ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}, "V31 root entries mismatch")
    for name in ("home", "tmp", "receipts"):
        info = (V31_ROOT / name).lstat()
        require(stat.S_ISDIR(info.st_mode) and not (V31_ROOT / name).is_symlink(), "V31 private directory unsafe")
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700, "V31 private owner/mode mismatch")
    require(not os.listdir(V31_ROOT / "home") and not os.listdir(V31_ROOT / "tmp"), "V31 private directory drift")
    files = {
        name: file_identity(V31_ROOT / name, size, digest, 0o600)
        for name, (size, digest) in V31_ROOT_FILES.items()
    }
    expected_receipts = {
        name.split("/", 1)[1]
        for name in V31_ROOT_FILES
        if name.startswith("receipts/")
    }
    require(set(os.listdir(V31_ROOT / "receipts")) == expected_receipts, "V31 receipt domain mismatch")
    index = json.loads(read_regular(V31_ROOT / "receipts/final-index.json")[0].decode("utf-8"))
    require(
        index["verdict"] == "M3S_V31_READY_FOR_CONTROLLER_REVIEW"
        and index["root_prepare_argv_json_sha256"] == V31_ROOT_ARGV_SHA256,
        "V31 final index mismatch",
    )
    for name in (
        "successor-preparation-v31-result.json",
        "final-controller-acceptance-v31-result.json",
    ):
        path = V31_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V31 reserved result appeared")
    return {"files": files, "result": "PASS"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    require(argv[:1] == ["--"], "root-only argv separator missing")
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--expected-status-sha256", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-driver-sha256", required=True)
    parser.add_argument("--expected-helper-sha256", required=True)
    return parser.parse_args(argv[1:])


def expected_environment() -> dict[str, str]:
    return {
        "GIT_OPTIONAL_LOCKS": "0",
        "HOME": "/Users/junhuaxu",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": PATH_VALUE,
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": "/tmp",  # noqa: S108 - frozen clean root-only environment
        "__CF_USER_TEXT_ENCODING": CF_USER_TEXT_ENCODING,
    }


def build_acceptance(
    driver_bytes: bytes,
    *,
    plan_bytes: bytes,
    status_bytes: bytes,
    source_bytes: bytes,
    helper_bytes: bytes,
) -> tuple[bytes, dict[str, Any]]:
    contracts = literal_assignment(driver_bytes, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(driver_bytes, "CONTROLLER_CONTRACT_HASHES")
    require(
        {name: sha256(compact(value)) for name, value in contracts.items()} == hashes,
        "acceptance contract mismatch",
    )
    value = {
        "authority": "EXTERNAL_CONTROLLER",
        "contract_objects": contracts,
        "contracts": hashes,
        "documents": {
            "execplan": {"path": str(PLAN), "sha256": sha256(plan_bytes), "size": len(plan_bytes)},
            "status": {"path": str(STATUS), "sha256": sha256(status_bytes), "size": len(status_bytes)},
        },
        "driver": {"path": str(DRIVER), "sha256": sha256(driver_bytes), "size": len(driver_bytes)},
        "format_version": 1,
        "phase": "M3S_V32_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V31_CLOSURE,
        "preparation_source": {
            "helper": {
                "path": str(DELIVERY / "tools/loop_engineering/m3s_v32_source_freeze.py"),
                "sha256": sha256(helper_bytes),
                "size": len(helper_bytes),
            },
            "sealed_v31_helper": {
                "path": str(V31_HELPER),
                "sha256": V31_HELPER_SHA256,
                "size": V31_HELPER_SIZE,
            },
            "sha256": sha256(source_bytes),
            "size": len(source_bytes),
        },
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": literal_assignment(driver_bytes, "CONTROLLER_ROOT_BINDING"),
        "seed": {
            "head": literal_assignment(driver_bytes, "HEAD"),
            "manifest_sha256": literal_assignment(driver_bytes, "MANIFEST_SHA"),
            "patch_sha256": literal_assignment(driver_bytes, "PATCH_SHA"),
            "path_list_sha256": literal_assignment(driver_bytes, "LIST_SHA"),
        },
    }
    return compact(value) + b"\n", value


def write_exclusive(path: Path, payload: bytes) -> dict[str, Any]:
    require(not path.exists() and not path.is_symlink(), f"destination exists: {path}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            require(written > 0, f"short write: {path}")
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd)
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o600, f"written owner/mode mismatch: {path}")
    finally:
        os.close(fd)
    reread, info = read_regular(path)
    require(reread == payload, f"written bytes mismatch: {path}")
    return {
        "mode": "0600",
        "owner_uid": info.st_uid,
        "path": str(path),
        "sha256": sha256(payload),
        "size": len(payload),
    }


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def root_only(
    args: argparse.Namespace,
    source_bytes: bytes,
    helper_bytes: bytes,
    raw_argv: list[str],
) -> int:
    require(os.getuid() == CURRENT_UID, "uid mismatch")
    require(Path.cwd() == SEED, "root-only workdir mismatch")
    require(dict(os.environ) == expected_environment(), "root-only environment mismatch")
    require(Path(args.plan) == PLAN and Path(args.status) == STATUS, "document path mismatch")
    require(sha256(source_bytes) == args.expected_source_sha256, "source hash mismatch")
    require(sha256(helper_bytes) == args.expected_helper_sha256, "helper hash mismatch")
    plan_bytes, _ = read_regular(PLAN)
    status_bytes, _ = read_regular(STATUS)
    require(sha256(plan_bytes) == args.expected_plan_sha256, "plan hash mismatch")
    require(sha256(status_bytes) == args.expected_status_sha256, "status hash mismatch")
    require(extract_once(plan_bytes, SOURCE_BEGIN, SOURCE_END) == source_bytes, "embedded source mismatch")
    v31_helper_bytes, _ = read_regular(V31_HELPER)
    require(
        len(v31_helper_bytes) == V31_HELPER_SIZE
        and sha256(v31_helper_bytes) == V31_HELPER_SHA256,
        "sealed V31 helper mismatch",
    )
    v31_bytes, _ = read_regular(V31_DRIVER)
    driver_bytes = derive_driver(v31_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "derived driver hash mismatch")
    static = inspect_driver(driver_bytes)
    predecessor_root = validate_v31_root()
    candidates = tuple(
        sorted(
            (path.name for path in BASE.iterdir() if path.name.startswith("candidate.")),
            key=os.fsencode,
        )
    )
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    require(not ROOT.exists() and not ROOT.is_symlink(), "V32 root exists")
    root_argv = [
        "/opt/homebrew/bin/python3.12",
        "-c",
        source_bytes.decode("utf-8"),
        *raw_argv,
    ]
    require(len(root_argv) == 18, "root-only argv count mismatch")
    root_argv_bytes = json.dumps(
        root_argv,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    acceptance_bytes, _ = build_acceptance(
        driver_bytes,
        plan_bytes=plan_bytes,
        status_bytes=status_bytes,
        source_bytes=source_bytes,
        helper_bytes=helper_bytes,
    )
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver = write_exclusive(DRIVER, driver_bytes)
    acceptance = write_exclusive(
        RECEIPTS / "controller-acceptance-v32.json",
        acceptance_bytes,
    )
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        pretty(
            {
                "acceptance": acceptance,
                "documents": {
                    "execplan_sha256": args.expected_plan_sha256,
                    "status_sha256": args.expected_status_sha256,
                },
                "driver": driver,
                "format_version": 1,
                "helper_sha256": args.expected_helper_sha256,
                "phase": "M3S_V32_SOURCE_WRITE",
                "preparation_source_sha256": args.expected_source_sha256,
                "result": "PASS",
                "root_prepare_argv_json_sha256": sha256(root_argv_bytes),
            }
        ),
    )
    writer = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        pretty(
            {
                "error": None,
                "format_version": 1,
                "no_replace": True,
                "phase": "M3S_V32_WRITER_SELF_TEST",
                "result": "PASS",
            }
        ),
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        pretty(
            {
                "candidate_count": len(candidates),
                "driver": driver,
                "format_version": 1,
                "phase": "M3S_V32_SELF_CHECK",
                "predecessor_root": predecessor_root,
                "result": "PASS",
                "reserved_results_absent": True,
                "static": static,
            }
        ),
    )
    final_index = write_exclusive(
        RECEIPTS / "final-index.json",
        pretty(
            {
                "controller_acceptance": acceptance,
                "documents": {
                    "plan_sha256": args.expected_plan_sha256,
                    "status_sha256": args.expected_status_sha256,
                },
                "driver": driver,
                "files": {
                    "self-check-result.json": self_check,
                    "source-receipt.json": source_receipt,
                    "writer-self-test.json": writer,
                },
                "format_version": 1,
                "phase": "M3S_V32_FINAL_INDEX",
                "root_prepare_argv_json_sha256": sha256(root_argv_bytes),
                "reserved_results_absent": [
                    "successor-preparation-v32-result.json",
                    "final-controller-acceptance-v32-result.json",
                ],
                "verdict": "M3S_V32_READY_FOR_CONTROLLER_REVIEW",
            }
        ),
    )
    require(
        set(os.listdir(ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}
        and set(os.listdir(RECEIPTS))
        == {
            "controller-acceptance-v32.json",
            "final-index.json",
            "self-check-result.json",
            "source-receipt.json",
            "writer-self-test.json",
        }
        and not os.listdir(ROOT / "home")
        and not os.listdir(ROOT / "tmp"),
        "final root domain mismatch",
    )
    os.write(
        1,
        compact(
            {
                "driver": driver,
                "final_index": final_index,
                "phase": "M3S_V32_ROOT_ONLY",
                "result": "M3S_V32_READY_FOR_CONTROLLER_REVIEW",
            }
        )
        + b"\n",
    )
    return 0


def main(
    argv: list[str] | None = None,
    *,
    source_bytes: bytes | None = None,
    helper_bytes: bytes | None = None,
) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    args = parse_args(raw_argv)
    require(source_bytes is not None and helper_bytes is not None, "verified source/helper bytes required")
    return root_only(args, source_bytes, helper_bytes, raw_argv)
