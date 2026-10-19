"""Deterministic M3S-v33 source-freeze and root-only helper.

This is trusted recovery machinery, not product code and not a formal role.
It derives V33 solely from the sealed V32 driver, validates the corrected
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
V32_HELPER = DELIVERY / "tools/loop_engineering/m3s_v32_source_freeze.py"
V32_HELPER_SIZE = 38_831
V32_HELPER_SHA256 = "9d5ad6c51ffb33782b1e61f84614a7315c2baa51e0f63a9412ad1c6706c967c2"
V32_ROOT = BASE / "trusted-tools/m3-successor-preparation-v32"
V32_DRIVER = V32_ROOT / "candidate-driver.py"
V32_DRIVER_SIZE = 405_255
V32_DRIVER_SHA256 = "eb57ae59f13cd46d9b7009c93da8a6f30ced9881ac35621ac00d2abcb1e6eaa1"
V32_ROOT_ARGV_SHA256 = "b3b0e77fdfb7e2a4408436c75d59074bd9ca54ce08fa461db3c62ab959986177"
V32_ROOT_FILES = {
    "candidate-driver.py": (405_255, V32_DRIVER_SHA256),
    "receipts/controller-acceptance-v32.json": (
        7_339,
        "6a487a6feecdc7d03d8453ba40d144f7f6fb48c302df2474e8a326ec92a80ad6",
    ),
    "receipts/source-receipt.json": (
        1_285,
        "bf591c5933874b8a23ee5807c16ad2985f9cda872896ebcd349414ad0f555855",
    ),
    "receipts/writer-self-test.json": (
        124,
        "df23c47a6b0b68b04b09cb9f8feb7b6aa7d88b6e20f2d0b6b7d35022ab99edaa",
    ),
    "receipts/self-check-result.json": (
        8_265,
        "af760dfeb25e478ae902596cf9861741d4ed3668104f347f81fb0007d82fa963",
    ),
    "receipts/final-index.json": (
        2_434,
        "941a7991b0705d3d3e11f897ef3347c2690688909b3f539d1a0c64763a7add97",
    ),
    "receipts/successor-preparation-v32-result.json": (
        3_570,
        "004e8ad6abce6da0ffd0a32cbfbfb943536cf2e28f21a0c7d4fed0e77cb675ce",
    ),
}
V32_PREPARE_INPUTS = {
    "direct_wrapper_argv_json_sha256": (
        "66486b420d7d83863c08168b505a04aa00772e8b36bebb87944bbcfe39ebe877"
    ),
    "prepare_argv_json_sha256": (
        "7fc7f513179056fe2dfd6862e65e3f10f9e30bbe6a3c0e7a14a33403419fc798"
    ),
    "shell_envelope_sha256": (
        "4f820458f71cccd1caff065afa87b02e84409cf419a50395f8a58d580fc1ca24"
    ),
}
ROOT = BASE / "trusted-tools/m3-successor-preparation-v33"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V33_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V33_END\n"
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
        "successor-v33-controller-acceptance-offer.json",
        "successor-v33-controller-acceptance.json",
        "successor-v33-initial-events.jsonl",
        "successor-v33-initial-state.json",
        "successor-v33-loop-init-command.json",
        "successor-v33-loop-init-result.json",
        "successor-v33-overlay.json",
        "successor-v33-policy-snapshot.json",
        "successor-v33-preparation-bindings.json",
        "successor-v33-stop.json",
        "successor-v33-toolchain-snapshot.json",
        "successor-v33-trusted-context.json",
    }
)
SUCCESSOR_RECEIPTS = (
    HISTORICAL_RECEIPTS - {"m2-stop-receipt.json"}
) | SUCCESSOR_ONLY_RECEIPTS
V32_CLOSURE = {
    "budgets": {
        "accept_final": "ABANDONED_UNCONSUMED",
        "auth": "UNAUTHORIZED",
        "formal": "UNAUTHORIZED",
        "init": "ABANDONED_UNCONSUMED",
        "prepare_result": "CONSUMED_NO_REUSE",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "ABANDONED_UNCONSUMED",
    },
    "candidate_count": 21,
    "prepare": {
        "candidate_count": 21,
        "elapsed_seconds": 0.208103,
        "error": "RuntimeError: future V33 result fixture mismatch",
        "inputs": V32_PREPARE_INPUTS,
        "result_receipt": {
            "mode": "0600",
            "owner_uid": 501,
            "sha256": "004e8ad6abce6da0ffd0a32cbfbfb943536cf2e28f21a0c7d4fed0e77cb675ce",
            "size": 3570,
        },
        "returncode": 1,
        "result": "STOPPED_PREALLOCATION",
        "timed_out": False,
    },
    "root": str(V32_ROOT),
    "root_files": {
        name: {"sha256": digest, "size": size}
        for name, (size, digest) in V32_ROOT_FILES.items()
    },
    "root_prepare_argv_json_sha256": V32_ROOT_ARGV_SHA256,
    "root_verdict": "M3S_V32_READY_FOR_CONTROLLER_REVIEW",
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
    tree = ast.parse(payload, filename="<m3s-v33-literal-extraction>")
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


V32_CONSTANTS = (
    "\nPREVIOUS_M3S_V32_ROOT = Path(" + repr(str(V32_ROOT)) + ")\n"
    "PREVIOUS_M3S_V32_ROOT_FILES = " + repr(V32_ROOT_FILES) + "\n"
    "PREVIOUS_M3S_V32_CLOSURE = " + repr(V32_CLOSURE) + "\n"
)

V32_VALIDATOR = r'''
def validate_m3s_v32_blocked() -> dict[str, Any]:
    private_directory_identity(PREVIOUS_M3S_V32_ROOT)
    for name in ("home", "tmp", "receipts"):
        private_directory_identity(PREVIOUS_M3S_V32_ROOT / name)
    require(
        set(os.listdir(PREVIOUS_M3S_V32_ROOT))
        == {"candidate-driver.py", "home", "receipts", "tmp"},
        "V32 root entries mismatch",
    )
    require(
        not os.listdir(PREVIOUS_M3S_V32_ROOT / "home")
        and not os.listdir(PREVIOUS_M3S_V32_ROOT / "tmp"),
        "V32 private directory drift",
    )
    expected_receipts = {
        name.split("/", 1)[1]
        for name in PREVIOUS_M3S_V32_ROOT_FILES
        if name.startswith("receipts/")
    }
    require(
        set(os.listdir(PREVIOUS_M3S_V32_ROOT / "receipts"))
        == expected_receipts,
        "V32 receipt set mismatch",
    )
    files = {
        name: require_identity(
            PREVIOUS_M3S_V32_ROOT / name,
            digest,
            0o600,
            size,
        )
        for name, (size, digest) in PREVIOUS_M3S_V32_ROOT_FILES.items()
    }
    index, _ = load_json(PREVIOUS_M3S_V32_ROOT / "receipts/final-index.json")
    require(
        index["verdict"] == PREVIOUS_M3S_V32_CLOSURE["root_verdict"]
        and index["root_prepare_argv_json_sha256"]
        == PREVIOUS_M3S_V32_CLOSURE["root_prepare_argv_json_sha256"],
        "V32 final-index mismatch",
    )
    acceptance, _ = load_json(
        PREVIOUS_M3S_V32_ROOT / "receipts/controller-acceptance-v32.json"
    )
    require(
        acceptance["phase"] == "M3S_V32_CONTROLLER_ACCEPTANCE"
        and acceptance["result"] == "ACCEPTED_BEFORE_ROOT_CREATION",
        "V32 controller acceptance mismatch",
    )
    result, _ = load_json(
        PREVIOUS_M3S_V32_ROOT / "receipts/successor-preparation-v32-result.json"
    )
    prepare = PREVIOUS_M3S_V32_CLOSURE["prepare"]
    require(
        result["phase"] == "M3_SUCCESSOR_PREPARATION_V32"
        and result["returncode"] == prepare["returncode"]
        and result["elapsed_seconds"] == prepare["elapsed_seconds"]
        and result["timed_out"] is False
        and result["output_truncated"] is False
        and result["wrapper_error"] is None
        and result["session_id"] is None
        and result["credential_variables"] == [],
        "V32 result fixed fields mismatch",
    )
    require(
        sha(argv_json(result["argv"]))
        == prepare["inputs"]["prepare_argv_json_sha256"]
        and result["output"].endswith(prepare["error"] + "\n"),
        "V32 result terminal evidence mismatch",
    )
    for name in (
        "final-controller-acceptance-v32-result.json",
        "auth-handoff-v32-result.json",
    ):
        path = PREVIOUS_M3S_V32_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V32 reserved result appeared")
    require(
        prepare["result"] == "STOPPED_PREALLOCATION"
        and prepare["candidate_count"] == 21
        and PREVIOUS_M3S_V32_CLOSURE["budgets"]["prepare_result"]
        == "CONSUMED_NO_REUSE"
        and PREVIOUS_M3S_V32_CLOSURE["budgets"]["suffix"]
        == "ABANDONED_UNCONSUMED"
        and PREVIOUS_M3S_V32_CLOSURE["budgets"]["init"]
        == "ABANDONED_UNCONSUMED",
        "V32 stopped prepare closure mismatch",
    )
    return {"closure": PREVIOUS_M3S_V32_CLOSURE, "files": files}


'''


def derive_driver(v32_bytes: bytes) -> bytes:
    """Roll the sealed V32 driver to V33 and repair only the frozen defect."""

    require(
        len(v32_bytes) == V32_DRIVER_SIZE and sha256(v32_bytes) == V32_DRIVER_SHA256,
        "sealed V32 driver mismatch",
    )
    text = v32_bytes.decode("utf-8")
    future_upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    future_lower = "liveclip_future_version_lower"
    require(future_upper not in text and future_lower not in text, "transform sentinel collision")
    text = text.replace("V33", future_upper).replace("v33", future_lower)
    text = text.replace("V32", "V33").replace("v32", "v33")
    text = text.replace(future_upper, "V34").replace(future_lower, "v34")
    text = replace_assignment(
        text,
        "PREVIOUS_M3S_V29_CLOSURE",
        literal_assignment(v32_bytes, "PREVIOUS_M3S_V29_CLOSURE"),
    )
    text = replace_once(text, "range(33, 55)", "range(34, 55)", "future receipt range")
    broken_fixture = '''    current_result_name = "successor-preparation-v" + "31-result.json"
    current_result_fixture = (repr(current_result_name) + "\\n").encode("ascii")
    require(phase_source_violations(current_result_fixture, False) == [], "current V33 result positive fixture mismatch")
    future_result_name = "successor-preparation-v" + "32-result.json"
    future_result_fixture = (repr(future_result_name) + "\\n").encode("ascii")
    expected_future = ["forbidden_receipt:" + future_result_name]
    require(phase_source_violations(future_result_fixture, False) == expected_future, "future V34 result fixture mismatch")
    mutated_future_name = "successor-preparation-v" + "31-result.json"
    mutated_future_fixture = (repr(mutated_future_name) + "\\n").encode("ascii")
    require(phase_source_violations(mutated_future_fixture, False) == [] and phase_source_violations(mutated_future_fixture, False) != expected_future, "future-result version regression fixture mismatch")
'''
    corrected_fixture = '''    current_result_name = "successor-preparation-v" + "33-result.json"
    current_result_fixture = (repr(current_result_name) + "\\n").encode("ascii")
    require(phase_source_violations(current_result_fixture, False) == [], "current V33 result positive fixture mismatch")
    future_result_name = "successor-preparation-v" + "34-result.json"
    future_result_fixture = (repr(future_result_name) + "\\n").encode("ascii")
    expected_future = ["forbidden_receipt:" + future_result_name]
    require(phase_source_violations(future_result_fixture, False) == expected_future, "future V34 result fixture mismatch")
    regression_name = "successor-preparation-v" + "33-result.json"
    regression_fixture = (repr(regression_name) + "\\n").encode("ascii")
    require(phase_source_violations(regression_fixture, False) == [] and phase_source_violations(regression_fixture, False) != expected_future, "future-result version regression fixture mismatch")
    omitted_future_fixture = b"pass\\n"
    require(phase_source_violations(omitted_future_fixture, False) == [] and phase_source_violations(omitted_future_fixture, False) != expected_future, "future-result omission fixture mismatch")
    substituted_future_name = "successor-preparation-v" + "034-result.json"
    substituted_future_fixture = (repr(substituted_future_name) + "\\n").encode("ascii")
    require(phase_source_violations(substituted_future_fixture, False) == [] and phase_source_violations(substituted_future_fixture, False) != expected_future, "future-result substitution fixture mismatch")
'''
    text = replace_once(
        text,
        broken_fixture,
        corrected_fixture,
        "current/future result runtime fixtures",
    )
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
        V32_CONSTANTS + "\nCONTROLLER_ROOT_BINDING =",
        "V32 immutable closure constants",
    )
    text = replace_once(
        text,
        "\ndef validate_m3s_v29_stopped() -> dict[str, Any]:",
        "\n" + V32_VALIDATOR + "def validate_m3s_v29_stopped() -> dict[str, Any]:",
        "V32 immutable closure validator",
    )
    text = replace_once(
        text,
        '        "m3s_v29_stopped": validate_m3s_v29_stopped(),\n',
        '        "m3s_v29_stopped": validate_m3s_v29_stopped(),\n'
        '        "m3s_v32_blocked": validate_m3s_v32_blocked(),\n',
        "V32 read-only gate",
    )
    text = replace_once(
        text,
        "canonical_json_model(PREVIOUS_M3S_V31_CLOSURE) and value[\"root\"]",
        "canonical_json_model(PREVIOUS_M3S_V32_CLOSURE) and value[\"root\"]",
        "controller predecessor closure",
    )
    payload = text.encode("utf-8")
    tree = ast.parse(payload, filename="<m3s-v33-driver>")
    compile(tree, "<m3s-v33-driver>", "exec")
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
    tree = ast.parse(payload, filename="<m3s-v33-phase-policy>")
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
        *("M3S_V33_" + suffix for suffix in suffixes),
        "M3_SUCCESSOR_PREPARATION_V33",
        "M3_SUCCESSOR_PREPARATION_V33_PREFLIGHT",
        "M3_SUCCESSOR_PREPARATION_V33_FINAL_INDEX",
        "M3_SUCCESSOR_PREPARATION_V33_TOOLCHAIN_SNAPSHOT",
        "M3_SUCCESSOR_PREPARATION_V33_READY_FOR_CONTROLLER_REVIEW",
        "M3_SUCCESSOR_PREPARATION_V33_STOP",
        "M3_SUCCESSOR_PREPARATION_V33_PRESERVATION",
        "M3_SUCCESSOR_PREPARATION_V33_STOPPED",
        "M3_SUCCESSOR_DRY_RUN_V33_CAPTURE",
        "M3_SUCCESSOR_DRY_RUN_V33_VALIDATION",
    }
    violations: list[str] = []
    for item in sorted(active - exact):
        violations.append("missing_active:" + item)
    for item in sorted((full - active) & exact):
        violations.append("inactive_current:" + item)
    future = {item.replace("V33", "V34") for item in full}
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


def static_string_expression(node: ast.AST) -> str:
    """Evaluate only literal string concatenation used by frozen fixtures."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return static_string_expression(node.left) + static_string_expression(node.right)
    raise FreezeError("non-static result fixture expression")


def result_fixture_runtime_model(payload: bytes) -> dict[str, Any]:
    """Run the exact result-name policy over the derived fixture values."""

    tree = ast.parse(payload, filename="<m3s-v33-result-fixture-model>")
    function = function_node(tree, "validate_active_phase_names")
    assignments: dict[str, str] = {}
    for node in function.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id
            in {
                "current_result_name",
                "future_result_name",
                "regression_name",
                "substituted_future_name",
            }
        ):
            assignments[node.targets[0].id] = static_string_expression(node.value)
    require(
        assignments
        == {
            "current_result_name": "successor-preparation-v33-result.json",
            "future_result_name": "successor-preparation-v34-result.json",
            "regression_name": "successor-preparation-v33-result.json",
            "substituted_future_name": "successor-preparation-v034-result.json",
        },
        "result fixture assignments mismatch",
    )
    source = ast.get_source_segment(payload.decode("utf-8"), function)
    require(source is not None, "result fixture source unavailable")
    require(
        'omitted_future_fixture = b"pass\\n"' in source
        and "future-result omission fixture mismatch" in source
        and "future-result substitution fixture mismatch" in source,
        "result omission/substitution fixture missing",
    )
    require(payload.count(b"range(34, 55)") == 1, "future result range mismatch")

    def violations(name: str | None) -> list[str]:
        fixture = b"pass\n" if name is None else (repr(name) + "\n").encode("ascii")
        return [
            "forbidden_receipt:" + candidate
            for candidate in (
                f"successor-preparation-v{version}-result.json"
                for version in range(34, 55)
            )
            if candidate.encode("ascii") in fixture
        ]

    expected_future = [
        "forbidden_receipt:successor-preparation-v34-result.json"
    ]
    current = violations(assignments["current_result_name"])
    future = violations(assignments["future_result_name"])
    regression = violations(assignments["regression_name"])
    omission = violations(None)
    substitution = violations(assignments["substituted_future_name"])
    require(current == [], "current V33 result rejected")
    require(future == expected_future, "future V34 result accepted")
    require(
        regression == [] and regression != expected_future,
        "result version regression fixture accepted",
    )
    require(
        omission == [] and omission != expected_future,
        "result omission fixture accepted",
    )
    require(
        substitution == [] and substitution != expected_future,
        "result substitution fixture accepted",
    )
    return {
        "current_positive": current,
        "future_negative": future,
        "omission_negative": omission,
        "regression_negative": regression,
        "result": "PASS",
        "substitution_negative": substitution,
    }


def preallocation_runtime_model(payload: bytes) -> dict[str, Any]:
    """Run safe fixture equivalents for every gate reached before mktemp."""

    tree = ast.parse(payload, filename="<m3s-v33-preallocation-model>")
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
        "validate_m3s_v32_blocked",
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
        "successor-v33-controller-acceptance-offer.json"
    }
    without_offer_delta = SUCCESSOR_ONLY_RECEIPTS - {
        "successor-v33-controller-acceptance-offer.json"
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
            without_offer_successor | {"successor-v33-controller-acceptance-offer.json.mutated"},
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
    tree = ast.parse(payload, filename="<m3s-v33-driver-static>")
    compile(tree, "<m3s-v33-driver-static>", "exec")
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
    require(payload.count(b"successor-v33-controller-acceptance-offer.json") >= 4, "offer binding missing")
    require(b"auth-handoff-v33-result.json" not in payload, "auth result capability present")
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
    result_fixtures = result_fixture_runtime_model(payload)
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
        "result_fixture_runtime_equivalent": result_fixtures,
    }


def validate_v32_root() -> dict[str, Any]:
    root = V32_ROOT.lstat()
    require(stat.S_ISDIR(root.st_mode) and not V32_ROOT.is_symlink(), "V32 root unsafe")
    require(root.st_uid == CURRENT_UID and stat.S_IMODE(root.st_mode) == 0o700, "V32 root owner/mode mismatch")
    require(set(os.listdir(V32_ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}, "V32 root entries mismatch")
    for name in ("home", "tmp", "receipts"):
        info = (V32_ROOT / name).lstat()
        require(stat.S_ISDIR(info.st_mode) and not (V32_ROOT / name).is_symlink(), "V32 private directory unsafe")
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700, "V32 private owner/mode mismatch")
    require(not os.listdir(V32_ROOT / "home") and not os.listdir(V32_ROOT / "tmp"), "V32 private directory drift")
    files = {
        name: file_identity(V32_ROOT / name, size, digest, 0o600)
        for name, (size, digest) in V32_ROOT_FILES.items()
    }
    expected_receipts = {
        name.split("/", 1)[1]
        for name in V32_ROOT_FILES
        if name.startswith("receipts/")
    }
    require(set(os.listdir(V32_ROOT / "receipts")) == expected_receipts, "V32 receipt domain mismatch")
    index = json.loads(read_regular(V32_ROOT / "receipts/final-index.json")[0].decode("utf-8"))
    require(
        index["verdict"] == "M3S_V32_READY_FOR_CONTROLLER_REVIEW"
        and index["root_prepare_argv_json_sha256"] == V32_ROOT_ARGV_SHA256,
        "V32 final index mismatch",
    )
    result = json.loads(
        read_regular(
            V32_ROOT / "receipts/successor-preparation-v32-result.json"
        )[0].decode("utf-8")
    )
    prepare = V32_CLOSURE["prepare"]
    require(
        result["phase"] == "M3_SUCCESSOR_PREPARATION_V32"
        and result["returncode"] == 1
        and result["elapsed_seconds"] == prepare["elapsed_seconds"]
        and result["timed_out"] is False
        and result["output_truncated"] is False
        and result["wrapper_error"] is None
        and result["session_id"] is None
        and result["credential_variables"] == []
        and sha256(compact(result["argv"]))
        == prepare["inputs"]["prepare_argv_json_sha256"]
        and result["output"].endswith(prepare["error"] + "\n"),
        "V32 result mismatch",
    )
    for name in (
        "final-controller-acceptance-v32-result.json",
        "auth-handoff-v32-result.json",
    ):
        path = V32_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V32 reserved result appeared")
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
        "phase": "M3S_V33_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V32_CLOSURE,
        "preparation_source": {
            "helper": {
                "path": str(DELIVERY / "tools/loop_engineering/m3s_v33_source_freeze.py"),
                "sha256": sha256(helper_bytes),
                "size": len(helper_bytes),
            },
            "sealed_v32_helper": {
                "path": str(V32_HELPER),
                "sha256": V32_HELPER_SHA256,
                "size": V32_HELPER_SIZE,
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
    v32_helper_bytes, _ = read_regular(V32_HELPER)
    require(
        len(v32_helper_bytes) == V32_HELPER_SIZE
        and sha256(v32_helper_bytes) == V32_HELPER_SHA256,
        "sealed V32 helper mismatch",
    )
    v32_bytes, _ = read_regular(V32_DRIVER)
    driver_bytes = derive_driver(v32_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "derived driver hash mismatch")
    static = inspect_driver(driver_bytes)
    predecessor_root = validate_v32_root()
    candidates = tuple(
        sorted(
            (path.name for path in BASE.iterdir() if path.name.startswith("candidate.")),
            key=os.fsencode,
        )
    )
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    require(not ROOT.exists() and not ROOT.is_symlink(), "V33 root exists")
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
        RECEIPTS / "controller-acceptance-v33.json",
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
                "phase": "M3S_V33_SOURCE_WRITE",
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
                "phase": "M3S_V33_WRITER_SELF_TEST",
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
                "phase": "M3S_V33_SELF_CHECK",
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
                "phase": "M3S_V33_FINAL_INDEX",
                "root_prepare_argv_json_sha256": sha256(root_argv_bytes),
                "reserved_results_absent": [
                    "successor-preparation-v33-result.json",
                    "final-controller-acceptance-v33-result.json",
                ],
                "verdict": "M3S_V33_READY_FOR_CONTROLLER_REVIEW",
            }
        ),
    )
    require(
        set(os.listdir(ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}
        and set(os.listdir(RECEIPTS))
        == {
            "controller-acceptance-v33.json",
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
                "phase": "M3S_V33_ROOT_ONLY",
                "result": "M3S_V33_READY_FOR_CONTROLLER_REVIEW",
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
