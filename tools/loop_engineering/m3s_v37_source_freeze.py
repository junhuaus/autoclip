"""Deterministic M3S-v37 source-freeze and root-only helper.

This credential-free trusted helper derives V37 only from the sealed V36
driver, restores immutable V32 terminal evidence, binds the completed V36
root and consumed verifier stop, executes the derived driver's complete
allocation-free read_only_gates graph, and may construct only the fixed V37
root.  It is non-product code and is import-only.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
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
V36_HELPER = DELIVERY / "tools/loop_engineering/m3s_v36_source_freeze.py"
V36_HELPER_SIZE = 34_717
V36_HELPER_SHA256 = "af81d42d4fe9840b9b71c050a65e8302dd461f0a6d9d587f80e317f588968eab"
V36_ROOT = BASE / "trusted-tools/m3-successor-preparation-v36"
V36_DRIVER = V36_ROOT / "candidate-driver.py"
V36_DRIVER_SIZE = 430_756
V36_DRIVER_SHA256 = "b77d5b05aed9cd86f8d17100f6e0a99e7c522ad38f79d015d61fc75a6e13cfa3"
V36_ROOT_FILES = {
    "candidate-driver.py": (430_756, V36_DRIVER_SHA256),
    "receipts/controller-acceptance-v36.json": (
        8_799,
        "b49b5f5d3b380866f75410a65f390b4d45fcb2f15eca10c8f811a3a4a47687dd",
    ),
    "receipts/source-receipt.json": (
        524,
        "afffcb591673791706e53db372ecbf1054e7497655c566709a43c578e556c500",
    ),
    "receipts/writer-self-test.json": (
        72,
        "25136877d8ba255deff9b18bb1e739213619e55a30466855f42ae46a7a17ce23",
    ),
    "receipts/self-check-result.json": (
        4_070,
        "78c41f930dc25b0dcf591221e6e21079ac590b7e14261d01e9dcdff729c3fbd0",
    ),
    "receipts/final-index.json": (
        1_999,
        "69bede8bac7bfcfd8f534d0e79ae7932e4929f2946905312a216f84541521213",
    ),
}
V36_CLOSURE = {
    "budgets": {
        "accept_final": "UNAUTHORIZED",
        "auth": "UNAUTHORIZED",
        "formal": "UNAUTHORIZED",
        "init": "ABANDONED_UNCONSUMED",
        "prepare_result": "ABANDONED_UNCONSUMED",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "ABANDONED_UNCONSUMED",
        "verify_prepare": "CONSUMED_NO_REUSE",
    },
    "candidate_count": 21,
    "inventory": {
        "modified_tracked": 15,
        "ordinary_untracked": 162,
        "staged": 0,
    },
    "post_root_documents": {
        "execplan": {
            "sha256": "4e45b255bd8e41c07a08d7f98dcb584897c0aa100beacbfff448b6f3cd7cf010",
            "size": 7_027_321,
        },
        "status": {
            "sha256": "a8751f764e6fbfd21484302c34cc918d4628d37cb575a02cc72467e1fff53fe6",
            "size": 142_632,
        },
    },
    "reserved_results": {
        "auth-handoff-v36-result.json": "ABSENT",
        "final-controller-acceptance-v36-result.json": "ABSENT",
        "successor-preparation-v36-result.json": "ABSENT",
    },
    "root": str(V36_ROOT),
    "root_documents": {
        "execplan": {
            "sha256": "657deb58d84faf8c53749bc06993f972415669f09a4339153bbd63cda4d4dc91",
            "size": 7_016_804,
        },
        "status": {
            "sha256": "e4a430ef0c35a261b9bd274e665fb950278770eaad7a53d9c31e94125e9942e0",
            "size": 140_655,
        },
    },
    "root_files": {
        name: {"sha256": digest, "size": size}
        for name, (size, digest) in V36_ROOT_FILES.items()
    },
    "root_prepare_argv_json_sha256": (
        "70e659e45fb34c8cf7db68c3c0afb2a7d9adc9ac7f476de10a5de0d9b51f1c3d"
    ),
    "root_verdict": "M3S_V36_READY_FOR_CONTROLLER_REVIEW",
    "verify_prepare": {
        "error": "RuntimeError: V32 result terminal evidence mismatch",
        "gate_count": 58,
        "gate_outcome": {
            "failed": "m3s_v32_blocked",
            "not_run": 17,
            "passed": 40,
        },
        "inputs": {
            "argv_json_sha256": (
                "f71916dbe7de10d0420d4098a78290fca3baa5101cc23f74c8bf5c808aa393e1"
            ),
            "env_vector_json_sha256": (
                "fb6436e9bb449da0f53c59e4e2e0874b7b2000fa2a97406e86a0323738a70a88"
            ),
            "shell_envelope_sha256": (
                "e8ddee40f572d280517b8664a98935b000e115ef9f04504d59f6bd719cc07e2a"
            ),
        },
        "returncode": 1,
        "stderr": {
            "sha256": "620a90d8c4a93b105f5bc2ddf7554f53b478bf4a13ae07c08bcb6e31b3bcc2a8",
            "size": 1_651,
        },
        "stdout": {
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "size": 0,
        },
        "tool": {
            "launch_chunk": "40e44c",
            "session_id": 55_489,
            "terminal_chunk": "973250",
            "wall_seconds": 28.708372417,
        },
    },
}
ROOT = BASE / "trusted-tools/m3-successor-preparation-v37"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V37_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V37_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO", "candidate.3WBt3ldA", "candidate.5jh3bylk",
    "candidate.5nZWpynN", "candidate.KWbe2iGW", "candidate.OlsWg1",
    "candidate.Q2vecg", "candidate.UU7EAiJG", "candidate.VoU5SVVl",
    "candidate.aw2oA4", "candidate.bSEqMEit", "candidate.c79YYSLQ",
    "candidate.cQnaAbOf", "candidate.dygENR4n", "candidate.iyme1x_i",
    "candidate.jyq_n37h", "candidate.mRMO7MQ6", "candidate.o99gfxup",
    "candidate.qaDKDWkQ", "candidate.xp23hqNY", "candidate.z6EbTJew",
)
V32_TERMINAL = "RuntimeError: future V33 result fixture mismatch"


class FreezeError(RuntimeError):
    """Fail-closed V37 design or construction error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def read_regular(path: Path, maximum: int = 8 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
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
    require(len(payload) == before.st_size, f"short read: {path}")
    after = path.lstat()
    require(
        (after.st_dev, after.st_ino, after.st_size)
        == (before.st_dev, before.st_ino, before.st_size),
        f"path identity changed: {path}",
    )
    return payload, before


def require_file(path: Path, size: int, digest: str, mode: int = 0o600) -> dict[str, Any]:
    payload, info = read_regular(path)
    require((len(payload), sha256(payload)) == (size, digest), f"identity mismatch: {path}")
    require(
        info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode,
        f"owner/mode mismatch: {path}",
    )
    return {
        "mode": f"{mode:04o}", "owner_uid": info.st_uid, "path": str(path),
        "sha256": digest, "size": size,
    }


def load_v36_helper() -> tuple[Any, bytes]:
    helper_bytes, _ = read_regular(V36_HELPER, 128 * 1024)
    require(
        (len(helper_bytes), sha256(helper_bytes)) == (V36_HELPER_SIZE, V36_HELPER_SHA256),
        "sealed V36 helper mismatch",
    )
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v36_frozen", V36_HELPER)
    require(spec is not None and spec.loader is not None, "V36 helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, helper_bytes


def literal_assignment(payload: bytes, name: str) -> Any:
    tree = ast.parse(payload, filename="<m3s-v37-literal>")
    values = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    require(len(values) == 1, f"literal assignment mismatch: {name}")
    return values[0]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    require(text.count(old) == 1, f"replacement count mismatch: {label}")
    return text.replace(old, new, 1)


def replace_assignment(text: str, name: str, value: object) -> str:
    tree = ast.parse(text, filename="<m3s-v37-assignment>")
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
    ]
    require(len(nodes) == 1, f"assignment replacement mismatch: {name}")
    node = nodes[0]
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    return text[:start] + f"{name} = {value!r}" + text[end:]


def derive_driver(v36_bytes: bytes) -> bytes:
    """Derive V37 deterministically and only from the sealed V36 driver."""

    require(
        (len(v36_bytes), sha256(v36_bytes)) == (V36_DRIVER_SIZE, V36_DRIVER_SHA256),
        "sealed V36 driver mismatch",
    )
    original_v32 = copy.deepcopy(literal_assignment(v36_bytes, "PREVIOUS_M3S_V32_CLOSURE"))
    original_v32["prepare"]["error"] = V32_TERMINAL
    text = v36_bytes.decode("utf-8")
    future_upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    future_lower = "liveclip_future_version_lower"
    require(future_upper not in text and future_lower not in text, "version sentinel collision")
    text = text.replace("V37", future_upper).replace("v37", future_lower)
    text = text.replace("V36", "V37").replace("v36", "v37")
    text = text.replace(future_upper, "V38").replace(future_lower, "v38")
    for old, new, label in (
        (
            'current_result_name = "successor-preparation-v" + "36-result.json"',
            'current_result_name = "successor-preparation-v" + "37-result.json"',
            "current result",
        ),
        (
            'future_result_name = "successor-preparation-v" + "37-result.json"',
            'future_result_name = "successor-preparation-v" + "38-result.json"',
            "future result",
        ),
        (
            'regression_name = "successor-preparation-v" + "36-result.json"',
            'regression_name = "successor-preparation-v" + "37-result.json"',
            "regression result",
        ),
    ):
        text = replace_once(text, old, new, label)
    text = replace_once(text, '"037-result.json"', '"038-result.json"', "future substitution")
    text = replace_once(text, "range(37, 55)", "range(38, 55)", "future range")
    text = replace_once(
        text, '"ordinary_untracked": 162', '"ordinary_untracked": 163', "inventory"
    )
    text = replace_assignment(text, "PREVIOUS_M3S_V32_CLOSURE", original_v32)
    text = replace_once(
        text,
        "CONTROLLER_ROOT_BINDING =",
        f"PREVIOUS_M3S_V36_CLOSURE = {V36_CLOSURE!r}\n\nCONTROLLER_ROOT_BINDING =",
        "V36 closure insertion",
    )
    terminal_source = f'''

IMMUTABLE_M3S_V32_TERMINAL = {V32_TERMINAL!r}


def historical_v32_terminal_violations(error: str) -> list[str]:
    return [] if error == IMMUTABLE_M3S_V32_TERMINAL else ["v32_terminal"]


def historical_v32_terminal_self_test() -> dict[str, Any]:
    actual = PREVIOUS_M3S_V32_CLOSURE["prepare"]["error"]
    require(historical_v32_terminal_violations(actual) == [], "V32 immutable terminal fixture mismatch")
    negatives = (
        "RuntimeError: future V36 result fixture mismatch",
        "RuntimeError: future V37 result fixture mismatch",
        "RuntimeError: future V34 result fixture mismatch",
    )
    require(all(historical_v32_terminal_violations(value) == ["v32_terminal"] for value in negatives), "V32 terminal negative fixture accepted")
    return {{"actual": actual, "negative_substitutions_rejected": len(negatives), "result": "PASS"}}
'''
    text = replace_once(
        text,
        "\ndef validate_m3s_v32_blocked() -> dict[str, Any]:",
        terminal_source + "\n\ndef validate_m3s_v32_blocked() -> dict[str, Any]:\n    historical_v32_terminal_self_test()",
        "V32 terminal fixture",
    )
    validator_source = '''

def validate_m3s_v36_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V36_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V36 root entries mismatch")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V36 private directory drift")
    expected_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_receipts, "V36 receipt set mismatch")
    files = {
        name: require_identity(root / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["root_files"].items()
    }
    index, _ = load_json(root / "receipts/final-index.json")
    require(index["verdict"] == closure["root_verdict"] and index["root_prepare_argv_json_sha256"] == closure["root_prepare_argv_json_sha256"], "V36 final-index mismatch")
    acceptance, _ = load_json(root / "receipts/controller-acceptance-v36.json")
    require(acceptance["phase"] == "M3S_V36_CONTROLLER_ACCEPTANCE" and acceptance["result"] == "ACCEPTED_BEFORE_ROOT_CREATION", "V36 acceptance mismatch")
    require(len([path for path in BASE.iterdir() if path.name.startswith("candidate.")]) == closure["candidate_count"], "V36 candidate count mismatch")
    for name in closure["reserved_results"]:
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V36 reserved result appeared")
    verify = closure["verify_prepare"]
    require(verify["returncode"] == 1 and verify["error"] == "RuntimeError: V32 result terminal evidence mismatch" and verify["gate_outcome"] == {"failed": "m3s_v32_blocked", "not_run": 17, "passed": 40}, "V36 verifier closure mismatch")
    require(closure["budgets"]["verify_prepare"] == "CONSUMED_NO_REUSE" and closure["budgets"]["prepare_result"] == "ABANDONED_UNCONSUMED", "V36 budget closure mismatch")
    return {"closure": closure, "files": files, "result": "PASS"}
'''
    text = replace_once(
        text,
        "\ndef validate_m3s_v35_stopped() -> dict[str, Any]:",
        validator_source + "\n\ndef validate_m3s_v35_stopped() -> dict[str, Any]:",
        "V36 validator insertion",
    )
    text = replace_once(
        text,
        '        "m3s_v35_stopped": validate_m3s_v35_stopped(),',
        '        "m3s_v36_stopped": validate_m3s_v36_stopped(),\n'
        '        "m3s_v35_stopped": validate_m3s_v35_stopped(),',
        "V36 gate insertion",
    )
    pre_root_driver_source = '''

PRE_ROOT_AUDIT_DRIVER_BYTES: bytes | None = None
PRE_ROOT_AUDIT_DRIVER_SHA256: str | None = None


def read_current_driver_for_static_gate() -> bytes:
    if PRE_ROOT_AUDIT_DRIVER_BYTES is not None:
        require(PRE_ROOT_AUDIT_DRIVER_SHA256 is not None, "pre-root driver digest missing")
        require(not DRIVER.exists() and not DRIVER.is_symlink(), "pre-root driver path appeared")
        require(sha(PRE_ROOT_AUDIT_DRIVER_BYTES) == PRE_ROOT_AUDIT_DRIVER_SHA256, "pre-root driver bytes mismatch")
        return PRE_ROOT_AUDIT_DRIVER_BYTES
    require(PRE_ROOT_AUDIT_DRIVER_SHA256 is None, "orphan pre-root driver digest")
    payload, _ = read_regular(DRIVER)
    return payload
'''
    text = replace_once(
        text,
        "\ndef living_plan_bound_contract_self_test() -> dict[str, Any]:",
        pre_root_driver_source + "\n\ndef living_plan_bound_contract_self_test() -> dict[str, Any]:",
        "pre-root driver gate surface",
    )
    text = replace_once(
        text,
        "    driver_bytes, _ = read_regular(DRIVER)\n    tree = ast.parse(driver_bytes, filename=str(DRIVER))",
        "    driver_bytes = read_current_driver_for_static_gate()\n    tree = ast.parse(driver_bytes, filename=str(DRIVER))",
        "living plan driver read",
    )
    require(text.count("    payload, _ = read_regular(DRIVER)\n    tree = ast.parse(payload, filename=str(DRIVER))") == 2, "static driver read count mismatch")
    text = text.replace(
        "    payload, _ = read_regular(DRIVER)\n    tree = ast.parse(payload, filename=str(DRIVER))",
        "    payload = read_current_driver_for_static_gate()\n    tree = ast.parse(payload, filename=str(DRIVER))",
    )
    old_semantic = '''def controller_acceptance_semantic_violations(value: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V35_CLOSURE):
        violations.append("predecessor_closure")
    if value.get("root") != CONTROLLER_ROOT_BINDING:
        violations.append("root")
    return violations'''
    new_semantic = old_semantic.replace("PREVIOUS_M3S_V35_CLOSURE", "PREVIOUS_M3S_V36_CLOSURE")
    text = replace_once(text, old_semantic, new_semantic, "V36 predecessor semantic")
    payload = text.encode("utf-8")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    contracts["policy_toolchain"]["controller_acceptance_semantics"] = {
        "model": "controller_acceptance_semantic_violations",
        "predecessor": "PREVIOUS_M3S_V36_CLOSURE",
        "rejects": ["V34", "V35", "missing", "mutated_v36", "extra_v36", "wrong_root"],
    }
    contracts["policy_toolchain"]["historical_terminal_evidence"] = {
        "immutable": {"m3s_v32": V32_TERMINAL},
        "negative_substitutions": ["future V36", "future V37", "future V34"],
        "validator": "historical_v32_terminal_self_test",
    }
    contracts["policy_toolchain"]["pre_root_full_audit"] = {
        "allocation": False,
        "gate_count": 59,
        "home": str(V36_ROOT / "home"),
        "include_process_gate": True,
        "no_write_snapshot": True,
        "tmp": str(V36_ROOT / "tmp"),
    }
    contracts["trusted_context"]["immediate_predecessor"] = {
        "closure": "PREVIOUS_M3S_V36_CLOSURE",
        "root": str(V36_ROOT),
        "verifier": "CONSUMED_FAILURE",
    }
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"function count mismatch: {name}")
    return matches[0]


def inspect_driver(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8")
    tree = ast.parse(text, filename="<m3s-v37-driver>")
    compile(tree, "<m3s-v37-driver>", "exec")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    execute_node = function_node(tree, "execute")
    mktemp = [
        node for node in ast.walk(execute_node)
        if isinstance(node, ast.List) and node.elts
        and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/mktemp"
    ]
    initializers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "initialize_and_bind_successor"
    ]
    require(initializers, "initializer missing")
    loop_init = [
        node for initializer in initializers for node in ast.walk(initializer)
        if isinstance(node, ast.List) and len(node.elts) >= 2
        and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make"
        and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"
    ]
    gate = function_node(tree, "read_only_gates")
    returns = [node for node in ast.walk(gate) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    require(len(returns) == 1 and len(returns[0].value.keys) == 59, "gate count mismatch")
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(payload.count(b'"ordinary_untracked": 163') == 1, "inventory count mismatch")
    require(b'"ordinary_untracked": 162' not in payload, "stale inventory retained")
    require(literal_assignment(payload, "PREVIOUS_M3S_V32_CLOSURE")["prepare"]["error"] == V32_TERMINAL, "V32 terminal drift")
    require(b'current_result_name = "successor-preparation-v" + "37-result.json"' in payload, "current result mismatch")
    require(b'future_result_name = "successor-preparation-v" + "38-result.json"' in payload, "future result mismatch")
    namespace: dict[str, Any] = {
        "__file__": str(DRIVER),
        "__name__": "liveclip_m3s_v37_static_surface",
    }
    exec(compile(tree, "<m3s-v37-static-surface>", "exec"), namespace)  # noqa: S102
    shapes = namespace["SHAPES"]
    require({name: len(shape) for name, shape in shapes.items()} == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    return {
        "ast_compile": "PASS", "command_surface": {name: len(shape) for name, shape in shapes.items()},
        "contracts": hashes, "gate_count": 59, "one_loop_init": True, "one_mktemp": True, "result": "PASS",
    }


def build_acceptance(
    driver_bytes: bytes, *, plan_bytes: bytes, status_bytes: bytes,
    source_bytes: bytes, helper_bytes: bytes,
) -> bytes:
    contracts = literal_assignment(driver_bytes, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(driver_bytes, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "acceptance contracts mismatch")
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
        "phase": "M3S_V37_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V36_CLOSURE,
        "preparation_source": {
            "helper": {
                "path": str(DELIVERY / "tools/loop_engineering/m3s_v37_source_freeze.py"),
                "sha256": sha256(helper_bytes), "size": len(helper_bytes),
            },
            "sealed_v36_helper": {"path": str(V36_HELPER), "sha256": V36_HELPER_SHA256, "size": V36_HELPER_SIZE},
            "sha256": sha256(source_bytes), "size": len(source_bytes),
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
    return compact(value) + b"\n"


def expected_environment() -> dict[str, str]:
    return {
        "GIT_OPTIONAL_LOCKS": "0", "HOME": "/Users/junhuaxu", "LANG": "C",
        "LC_ALL": "C", "PATH": PATH_VALUE, "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": "/tmp",  # noqa: S108 - frozen root-only environment
        "__CF_USER_TEXT_ENCODING": CF_USER_TEXT_ENCODING,
    }


def git_status_bytes() -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", "status", "--short", "--untracked-files=all"],
        cwd=DELIVERY, env={"PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
    )
    require(result.returncode == 0 and result.stderr == b"", "git status snapshot failed")
    return result.stdout


def v36_root_snapshot() -> dict[str, Any]:
    root_info = V36_ROOT.lstat()
    require(stat.S_ISDIR(root_info.st_mode) and not V36_ROOT.is_symlink(), "unsafe V36 root")
    require(root_info.st_uid == CURRENT_UID and stat.S_IMODE(root_info.st_mode) == 0o700, "V36 root owner/mode mismatch")
    require(set(os.listdir(V36_ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}, "V36 root entries mismatch")
    directories: dict[str, Any] = {}
    for name in ("home", "tmp", "receipts"):
        path = V36_ROOT / name
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), f"unsafe V36 directory: {name}")
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700, f"V36 directory owner/mode mismatch: {name}")
        directories[name] = {"entries": sorted(os.listdir(path)), "mode": "0700", "owner_uid": info.st_uid}
    require(directories["home"]["entries"] == [] and directories["tmp"]["entries"] == [], "V36 private directory drift")
    expected = {Path(name).name for name in V36_ROOT_FILES if name.startswith("receipts/")}
    require(set(directories["receipts"]["entries"]) == expected, "V36 receipt domain mismatch")
    files = {name: require_file(V36_ROOT / name, size, digest) for name, (size, digest) in V36_ROOT_FILES.items()}
    for name in V36_CLOSURE["reserved_results"]:
        path = V36_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V36 reserved result appeared")
    return {"directories": directories, "files": files, "root_mode": "0700", "root_owner_uid": root_info.st_uid}


def audit_snapshot(plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    candidates = tuple(sorted((p.name for p in BASE.iterdir() if p.name.startswith("candidate.")), key=os.fsencode))
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    return {
        "candidates_sha256": sha256(compact(candidates)),
        "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)},
        "git_status_sha256": sha256(git_status_bytes()),
        "v36_root": v36_root_snapshot(),
        "v37_root_absent": not ROOT.exists() and not ROOT.is_symlink(),
    }


def full_pre_root_audit(
    driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes,
) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    require(before["v37_root_absent"] is True, "V37 root exists before audit")
    tree = ast.parse(driver_bytes, filename="<m3s-v37-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v37_full_audit"}
    exec(compile(tree, "<m3s-v37-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V36 acceptance model rejected")
    semantic_negatives: dict[str, list[str]] = {}
    for label, replacement in (
        ("v34_substitution", namespace["PREVIOUS_M3S_V34_CLOSURE"]),
        ("v35_substitution", namespace["PREVIOUS_M3S_V35_CLOSURE"]),
        ("missing", {}),
    ):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        semantic_negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["verify_prepare"]["error"] = "RuntimeError: substituted"
    semantic_negatives["mutated_v36"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    semantic_negatives["extra_v36"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 36}
    semantic_negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(
        all(
            semantic_negatives[label] == ["predecessor_closure"]
            for label in ("v34_substitution", "v35_substitution", "missing", "mutated_v36", "extra_v36")
        ) and semantic_negatives["wrong_root"] == ["root"],
        "V36 acceptance negative fixture accepted",
    )
    terminal = namespace["historical_v32_terminal_self_test"]()
    require(namespace["validate_m3s_v32_blocked"]()["closure"]["prepare"]["error"] == V32_TERMINAL, "actual V32 receipt rejected")
    values = {
        "base": str(BASE), "seed": str(SEED), "plan": str(PLAN),
        "expected_plan_sha256": sha256(plan_bytes), "status": str(STATUS),
        "expected_status_sha256": sha256(status_bytes),
    }
    saved_environment = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](
            values, V36_ROOT / "home", V36_ROOT / "tmp", include_process_gate=True
        )
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 59, "full pre-root gate count mismatch")
    after_plan, _ = read_regular(PLAN)
    after_status, _ = read_regular(STATUS)
    after = audit_snapshot(after_plan, after_status)
    require(after == before, "full pre-root audit wrote or changed protected state")
    return {
        "acceptance_negatives": semantic_negatives,
        "gate_count": len(gates),
        "gates": {name: "PASS" for name in gates},
        "historical_v32_terminal": terminal,
        "no_write": {"before": before, "after": after, "result": "PASS"},
        "result": "PASS",
    }


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
    return {"mode": "0600", "owner_uid": info.st_uid, "path": str(path), "sha256": sha256(payload), "size": len(payload)}


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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


def root_only(args: argparse.Namespace, source_bytes: bytes, helper_bytes: bytes, raw_argv: list[str]) -> int:
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
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    require(plan_bytes[start:finish] == source_bytes, "embedded source mismatch")
    load_v36_helper()
    v36_bytes, _ = read_regular(V36_DRIVER)
    driver_bytes = derive_driver(v36_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(
        driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes,
        source_bytes=source_bytes, helper_bytes=helper_bytes,
    )
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V37 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v37.json", acceptance)
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V37_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n",
    )
    writer_receipt = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        compact({"format_version": 1, "phase": "M3S_V37_WRITER_SELF_TEST", "result": "PASS"}) + b"\n",
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        compact({"audit": audit, "format_version": 1, "phase": "M3S_V37_SELF_CHECK", "result": "PASS", "static": static}) + b"\n",
    )
    final_value = {
        "controller_acceptance": acceptance_identity,
        "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256},
        "driver": driver_identity, "format_version": 1, "phase": "M3S_V37_FINAL_INDEX",
        "root_prepare_argv_json_sha256": sha256(root_argv_json), "source_receipt": source_receipt,
        "self_check": self_check, "verdict": "M3S_V37_READY_FOR_CONTROLLER_REVIEW",
        "writer_self_test": writer_receipt,
    }
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V37_ROOT_ONLY", "result": "M3S_V37_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
