"""Deterministic M3S-v39 source-freeze and root-only helper.

This credential-free trusted helper reconstructs the accepted, unexecuted V38
design from frozen bytes, records why its root command became stale, derives a
fresh V39 driver, protects the operator-owned architecture HTML, executes the
derived driver's complete allocation-free pre-root gate graph, and may create
only the fixed V39 root.  It is non-product and import-only.
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
ARCHITECTURE = DELIVERY / "docs/liveclip-architecture.html"
SEED = BASE / "candidate.OlsWg1/repo"
V38_HELPER = DELIVERY / "tools/loop_engineering/m3s_v38_source_freeze.py"
V38_HELPER_SIZE = 41_978
V38_HELPER_SHA256 = "e6ec4f0400ee4a4477d82e5a75b4294900477834a8a5430d024d0fc18d9f4501"
V38_SOURCE_SIZE = 2_859
V38_SOURCE_SHA256 = "dc5e29f508a18e29ba735530478db35c2b77997f4a917aff14241c2ff87e592e"
V38_DRIVER_SIZE = 446_985
V38_DRIVER_SHA256 = "406a0a9cf2a901df045d8c0d237f057a30885b5f41dd95ee916163e8e27d6fb0"
V38_ACCEPTANCE_SIZE = 10_618
V38_ACCEPTANCE_SHA256 = "fca4c71b4b09cf7dc675dda16b5b034244b30275c0f22db86a8c29a92c6811e2"
V38_PLAN = {"size": 7_060_496, "sha256": "43b1b4a955a8fb867d1ec000ee9288ac3d12d1ed2b36b2bb720f4b6363d36680"}
V38_STATUS = {"size": 149_485, "sha256": "2ec540b45c13ad15276841a0fce963bdd0cf68d2742713a89bd04f209399b273"}
V38_ROOT = BASE / "trusted-tools/m3-successor-preparation-v38"
V38_SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V38_BEGIN\n"
V38_SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V38_END\n"
ARCHITECTURE_SIZE = 66_116
ARCHITECTURE_SHA256 = "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v39"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V39_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V39_END\n"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v39_source_freeze.py"
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
    "candidate.qaDKDWkQ", "candidate.vuDWtK0T", "candidate.xp23hqNY",
    "candidate.z6EbTJew",
)
V38_CONTRACT_HASHES = {
    "candidate_allocation": "c32b736d5f4b9547a621e9b3aabd46ece6e53e8e6dd360d1cba844d00ae1e2b6",
    "formal_dispatch": "70b63e787c7195e254bee058d98ada477ca411edfe637d101551dfb210124ae3",
    "initial_run": "034bf76f031f9da71b69d988cbcf15fb7674c24f7f455b3a72b8bacc4e1829c3",
    "policy_toolchain": "128b7e1572d07c53c64d5f08e3c042b3b15b08fb31128384c4177beb4a871e11",
    "trusted_context": "aba11e2b7e37aace5123f2ff4ba7be66909b69fd6d175c996d80c4d522365740",
}
V38_ROOT_ARGV = {
    "argv_sha256": "650021a2648e0aa495e66aa70d690fc69894ce9aea1106610dd2df0f5b3c2e49",
    "env_sha256": "c30a9d0d7e0c0de57b204741dcd25c60380b00902594f7d7a0b6699cf520db99",
    "envelope_sha256": "c525dad01e8e91d6932251d12d815f69131533fd2dc8303fa50792a7f8e348a3",
}
V38_CLOSURE = {
    "architecture_html": {
        "path": str(ARCHITECTURE), "sha256": ARCHITECTURE_SHA256,
        "size": ARCHITECTURE_SIZE,
    },
    "budgets": {
        "accept_final": "UNCONSUMED_UNAUTHORIZED",
        "auth": "UNAUTHORIZED",
        "formal": "UNAUTHORIZED",
        "init": "UNCONSUMED",
        "prepare_result": "UNCONSUMED",
        "root": "ABANDONED_STALE_UNEXECUTED",
        "suffix": "UNCONSUMED",
        "verify_prepare": "UNCONSUMED",
    },
    "candidate_count": 22,
    "contracts": V38_CONTRACT_HASHES,
    "documents": {"execplan": V38_PLAN, "status": V38_STATUS},
    "driver": {"sha256": V38_DRIVER_SHA256, "size": V38_DRIVER_SIZE},
    "external_acceptance": {
        "sha256": V38_ACCEPTANCE_SHA256, "size": V38_ACCEPTANCE_SIZE,
    },
    "helper": {
        "path": str(V38_HELPER), "sha256": V38_HELPER_SHA256,
        "size": V38_HELPER_SIZE,
    },
    "inventory": {
        "at_freeze": {"modified_tracked": 15, "ordinary_untracked": 164, "staged": 0},
        "after_operator_html": {"modified_tracked": 15, "ordinary_untracked": 165, "staged": 0},
        "v39_final": {"modified_tracked": 15, "ordinary_untracked": 166, "staged": 0},
    },
    "reason": "operator-authorized architecture HTML changed exact inventory after V38 source freeze",
    "root": str(V38_ROOT),
    "root_command": {**V38_ROOT_ARGV, "state": "STALE_UNEXECUTED_PERMANENTLY_ABANDONED"},
    "source": {"sha256": V38_SOURCE_SHA256, "size": V38_SOURCE_SIZE},
}


class FreezeError(RuntimeError):
    """Fail-closed V39 design or construction error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def read_regular(path: Path, maximum: int = 16 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
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


def require_file(path: Path, size: int, digest: str, mode: int = 0o644) -> dict[str, Any]:
    payload, info = read_regular(path)
    require((len(payload), sha256(payload)) == (size, digest), f"identity mismatch: {path}")
    require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode, f"mode mismatch: {path}")
    return {
        "mode": f"{mode:04o}", "owner_uid": info.st_uid, "path": str(path),
        "sha256": digest, "size": size,
    }


def load_helper(path: Path, module_name: str, size: int, digest: str) -> tuple[Any, bytes]:
    payload, _ = read_regular(path, 128 * 1024)
    require((len(payload), sha256(payload)) == (size, digest), f"helper mismatch: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    require(spec is not None and spec.loader is not None, f"helper unavailable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, payload


def literal_assignment(payload: bytes, name: str) -> Any:
    tree = ast.parse(payload, filename="<m3s-v39-literal>")
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
    ]
    require(len(nodes) == 1, f"literal assignment mismatch: {name}")
    return ast.literal_eval(nodes[0].value)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    require(text.count(old) == 1, f"replacement count mismatch: {label}")
    return text.replace(old, new, 1)


def replace_assignment(text: str, name: str, value: object) -> str:
    tree = ast.parse(text, filename="<m3s-v39-assignment>")
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


def extract_source(plan_bytes: bytes, begin: bytes, end: bytes) -> bytes:
    require(plan_bytes.count(begin) == 1 and plan_bytes.count(end) == 1, "source marker mismatch")
    start = plan_bytes.index(begin) + len(begin)
    finish = plan_bytes.index(end, start)
    return plan_bytes[start:finish]


def reconstruct_v38(plan_bytes: bytes) -> dict[str, Any]:
    v38, helper_bytes = load_helper(
        V38_HELPER, "liveclip_m3s_v38_frozen", V38_HELPER_SIZE, V38_HELPER_SHA256
    )
    source_bytes = extract_source(plan_bytes, V38_SOURCE_BEGIN, V38_SOURCE_END)
    require((len(source_bytes), sha256(source_bytes)) == (V38_SOURCE_SIZE, V38_SOURCE_SHA256), "V38 source mismatch")
    v37_bytes, _ = read_regular(v38.V37_DRIVER)
    driver_bytes = v38.derive_driver(v37_bytes)
    require((len(driver_bytes), sha256(driver_bytes)) == (V38_DRIVER_SIZE, V38_DRIVER_SHA256), "V38 driver mismatch")
    contracts = literal_assignment(driver_bytes, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(driver_bytes, "CONTROLLER_CONTRACT_HASHES")
    require(hashes == V38_CONTRACT_HASHES, "V38 contract hash mismatch")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "V38 contract object mismatch")
    acceptance_value = {
        "authority": "EXTERNAL_CONTROLLER",
        "contract_objects": contracts,
        "contracts": hashes,
        "documents": {
            "execplan": {"path": str(PLAN), **V38_PLAN},
            "status": {"path": str(STATUS), **V38_STATUS},
        },
        "driver": {"path": str(V38_ROOT / "candidate-driver.py"), "sha256": V38_DRIVER_SHA256, "size": V38_DRIVER_SIZE},
        "format_version": 1,
        "phase": "M3S_V38_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": v38.V37_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(V38_HELPER), "sha256": V38_HELPER_SHA256, "size": V38_HELPER_SIZE},
            "sealed_v37_helper": {"path": str(v38.V37_HELPER), "sha256": v38.V37_HELPER_SHA256, "size": v38.V37_HELPER_SIZE},
            "sha256": V38_SOURCE_SHA256,
            "size": V38_SOURCE_SIZE,
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
    acceptance = compact(acceptance_value) + b"\n"
    require((len(acceptance), sha256(acceptance)) == (V38_ACCEPTANCE_SIZE, V38_ACCEPTANCE_SHA256), "V38 acceptance mismatch")
    return {
        "acceptance": acceptance, "contracts": contracts, "driver": driver_bytes,
        "helper": helper_bytes, "module": v38, "source": source_bytes,
    }


def derive_driver(v38_bytes: bytes) -> bytes:
    """Derive V39 deterministically and only from accepted V38 bytes."""

    require((len(v38_bytes), sha256(v38_bytes)) == (V38_DRIVER_SIZE, V38_DRIVER_SHA256), "accepted V38 driver mismatch")
    text = v38_bytes.decode("utf-8")
    upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    lower = "liveclip_future_version_lower"
    require(upper not in text and lower not in text, "version sentinel collision")
    text = text.replace("V39", upper).replace("v39", lower)
    text = text.replace("V38", "V39").replace("v38", "v39")
    text = text.replace(upper, "V40").replace(lower, "v40")
    for old, new, label in (
        ('current_result_name = "successor-preparation-v" + "38-result.json"', 'current_result_name = "successor-preparation-v" + "39-result.json"', "current result"),
        ('future_result_name = "successor-preparation-v" + "39-result.json"', 'future_result_name = "successor-preparation-v" + "40-result.json"', "future result"),
        ('regression_name = "successor-preparation-v" + "38-result.json"', 'regression_name = "successor-preparation-v" + "39-result.json"', "regression result"),
    ):
        text = replace_once(text, old, new, label)
    text = replace_once(text, '"039-result.json"', '"040-result.json"', "future substitution")
    text = replace_once(text, "range(39, 55)", "range(40, 55)", "future range")
    text = replace_once(text, '"ordinary_untracked": 164', '"ordinary_untracked": 166', "final inventory")
    text = replace_once(
        text,
        "CONTROLLER_ROOT_BINDING =",
        f"PREVIOUS_M3S_V38_CLOSURE = {V38_CLOSURE!r}\n\n"
        f"PROTECTED_ARCHITECTURE_HTML = {{'path': {str(ARCHITECTURE)!r}, 'size': {ARCHITECTURE_SIZE}, 'sha256': {ARCHITECTURE_SHA256!r}}}\n\n"
        "CONTROLLER_ROOT_BINDING =",
        "V38 closure and architecture insertion",
    )
    validator_source = '''

def validate_architecture_html() -> dict[str, Any]:
    protected = PROTECTED_ARCHITECTURE_HTML
    identity = require_identity(Path(protected["path"]), protected["sha256"], 0o644, protected["size"])
    exact = {"path": protected["path"], "sha256": protected["sha256"], "size": protected["size"]}
    fixtures = {
        "exact_accept": exact == protected,
        "loss_reject": {} != protected,
        "mutation_reject": {**exact, "sha256": "0" * 64} != protected,
        "substitution_reject": {**exact, "path": str(PLAN)} != protected,
    }
    require(all(fixtures.values()), "architecture HTML fixture mismatch")
    return {"fixtures": fixtures, "identity": identity, "result": "PASS"}


def validate_m3s_v38_stale() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V38_CLOSURE
    require(closure["root_command"]["state"] == "STALE_UNEXECUTED_PERMANENTLY_ABANDONED", "V38 root-command state mismatch")
    require(closure["budgets"]["root"] == "ABANDONED_STALE_UNEXECUTED", "V38 root budget mismatch")
    require(closure["candidate_count"] == 22, "V38 recorded candidate count mismatch")
    require(closure["inventory"]["at_freeze"] == {"modified_tracked": 15, "ordinary_untracked": 164, "staged": 0}, "V38 frozen inventory mismatch")
    require(closure["inventory"]["after_operator_html"] == {"modified_tracked": 15, "ordinary_untracked": 165, "staged": 0}, "V38 stale inventory mismatch")
    root = Path(closure["root"])
    require(not root.exists() and not root.is_symlink(), "V38 root appeared")
    for name in ("successor-preparation-v38-result.json", "final-controller-acceptance-v38-result.json", "auth-handoff-v38-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V38 result appeared")
    helper = require_identity(Path(closure["helper"]["path"]), closure["helper"]["sha256"], 0o644, closure["helper"]["size"])
    architecture = validate_architecture_html()
    return {"architecture": architecture, "closure": closure, "helper": helper, "result": "PASS"}
'''
    text = replace_once(
        text,
        "\ndef validate_m3s_v37_stopped() -> dict[str, Any]:",
        validator_source + "\n\ndef validate_m3s_v37_stopped() -> dict[str, Any]:",
        "V38 stale validator insertion",
    )
    text = replace_once(
        text,
        '        "original": validate_original(values["expected_plan_sha256"], values["expected_status_sha256"]),',
        '        "original": validate_original(values["expected_plan_sha256"], values["expected_status_sha256"]),\n'
        '        "architecture_html": validate_architecture_html(),',
        "architecture gate insertion",
    )
    text = replace_once(
        text,
        '        "m3s_v37_stopped": validate_m3s_v37_stopped(),',
        '        "m3s_v38_stale": validate_m3s_v38_stale(),\n'
        '        "m3s_v37_stopped": validate_m3s_v37_stopped(),',
        "V38 stale gate insertion",
    )
    old_semantic = '''def controller_acceptance_semantic_violations(value: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V37_CLOSURE):
        violations.append("predecessor_closure")
    if value.get("root") != CONTROLLER_ROOT_BINDING:
        violations.append("root")
    return violations'''
    text = replace_once(
        text, old_semantic,
        old_semantic.replace("PREVIOUS_M3S_V37_CLOSURE", "PREVIOUS_M3S_V38_CLOSURE"),
        "V38 predecessor semantic",
    )
    payload = text.encode("utf-8")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    contracts["policy_toolchain"]["pre_root_full_audit"] = {
        "allocation": False,
        "architecture_html": {"sha256": ARCHITECTURE_SHA256, "size": ARCHITECTURE_SIZE},
        "gate_count": 62,
        "home": str(BASE / "trusted-tools/m3-successor-preparation-v37/home"),
        "include_process_gate": True,
        "no_write_snapshot": True,
        "tmp": str(BASE / "trusted-tools/m3-successor-preparation-v37/tmp"),
    }
    contracts["policy_toolchain"]["controller_acceptance_semantics"] = {
        "model": "controller_acceptance_semantic_violations",
        "predecessor": "PREVIOUS_M3S_V38_CLOSURE",
        "rejects": ["V37", "missing", "mutated_v38", "extra_v38", "wrong_root"],
    }
    contracts["policy_toolchain"]["protected_operator_evidence"] = {
        "architecture_html": {"path": str(ARCHITECTURE), "sha256": ARCHITECTURE_SHA256, "size": ARCHITECTURE_SIZE},
        "checked_before_allocation": True,
        "rejects": ["mutation", "loss", "substitution", "extra_inventory_drift"],
    }
    contracts["trusted_context"]["immediate_predecessor_design"] = {
        "closure": "PREVIOUS_M3S_V38_CLOSURE",
        "root": str(V38_ROOT),
        "state": "STALE_UNEXECUTED_PERMANENTLY_ABANDONED",
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
    tree = ast.parse(text, filename="<m3s-v39-driver>")
    compile(tree, "<m3s-v39-driver>", "exec")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = function_node(tree, "read_only_gates")
    returns = [node for node in ast.walk(gate) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    require(len(returns) == 1 and len(returns[0].value.keys) == 62, "gate count mismatch")
    execute_node = function_node(tree, "execute")
    mktemp = [
        node for node in ast.walk(execute_node)
        if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "/usr/bin/mktemp"
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
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(payload.count(b'"ordinary_untracked": 166') == 1, "inventory count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "39-result.json"' in payload, "current result mismatch")
    require(b'future_result_name = "successor-preparation-v" + "40-result.json"' in payload, "future result mismatch")
    require(b"PROTECTED_ARCHITECTURE_HTML" in payload and ARCHITECTURE_SHA256.encode() in payload, "architecture binding missing")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v39_static"}
    exec(compile(tree, "<m3s-v39-static>", "exec"), namespace)  # noqa: S102
    shapes = namespace["SHAPES"]
    require({name: len(shape) for name, shape in shapes.items()} == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    require(all(candidate_cases.values()), "candidate-set fixtures failed")
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    return {
        "ast_compile": "PASS", "candidate_set_cases": candidate_cases,
        "command_surface": {name: len(shape) for name, shape in shapes.items()},
        "contracts": hashes, "gate_count": 62, "one_loop_init": True,
        "one_mktemp": True,
        "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"},
        "result": "PASS",
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
        "phase": "M3S_V39_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V38_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "sealed_v38_helper": {"path": str(V38_HELPER), "sha256": V38_HELPER_SHA256, "size": V38_HELPER_SIZE},
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
    result = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "status", "--short", "--untracked-files=all"],
        cwd=DELIVERY,
        env={"PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
    )
    require(result.returncode == 0 and result.stderr == b"", "git status snapshot failed")
    return result.stdout


def status_counts(payload: bytes) -> dict[str, int]:
    staged = modified = untracked = 0
    for raw in payload.splitlines():
        line = raw.decode("utf-8", "strict")
        if line.startswith("?? "):
            untracked += 1
            continue
        require(len(line) >= 3, "short git status entry")
        if line[0] != " ":
            staged += 1
        if line[1] != " ":
            modified += 1
    return {"staged": staged, "modified_tracked": modified, "ordinary_untracked": untracked}


def reserved_absences(root: Path) -> dict[str, bool]:
    names = (
        "successor-preparation-v39-result.json",
        "final-controller-acceptance-v39-result.json",
        "auth-handoff-v39-result.json",
    )
    values = {name: not (root / "receipts" / name).exists() and not (root / "receipts" / name).is_symlink() for name in names}
    require(all(values.values()), "V39 reserved result appeared")
    return values


def audit_snapshot(plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    candidates = tuple(sorted((p.name for p in BASE.iterdir() if p.name.startswith("candidate.")), key=os.fsencode))
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    status_payload = git_status_bytes()
    counts = status_counts(status_payload)
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 166}, "final inventory mismatch")
    require(not V38_ROOT.exists() and not V38_ROOT.is_symlink(), "V38 root appeared")
    require(not ROOT.exists() and not ROOT.is_symlink(), "V39 root appeared")
    return {
        "architecture": architecture,
        "candidates_sha256": sha256(compact(candidates)),
        "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)},
        "git_status_sha256": sha256(status_payload), "inventory": counts,
        "v38_root_absent": True, "v39_root_absent": True,
    }


def full_pre_root_audit(
    driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes,
) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v39-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v39_audit"}
    exec(compile(tree, "<m3s-v39-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V38 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v37_substitution", namespace["PREVIOUS_M3S_V37_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["reason"] = "substituted"
    negatives["mutated_v38"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v38"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 38}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(
        all(negatives[name] == ["predecessor_closure"] for name in ("v37_substitution", "missing", "mutated_v38", "extra_v38"))
        and negatives["wrong_root"] == ["root"],
        "V38 acceptance negative accepted",
    )
    values = {
        "base": str(BASE), "seed": str(SEED), "plan": str(PLAN),
        "expected_plan_sha256": sha256(plan_bytes), "status": str(STATUS),
        "expected_status_sha256": sha256(status_bytes),
    }
    saved_environment = dict(os.environ)
    audit_home = BASE / "trusted-tools/m3-successor-preparation-v37/home"
    audit_tmp = BASE / "trusted-tools/m3-successor-preparation-v37/tmp"
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](
            values, audit_home, audit_tmp, include_process_gate=True
        )
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 62, "full pre-root gate count mismatch")
    require(gates["architecture_html"]["result"] == "PASS", "architecture gate failed")
    require(gates["m3s_v38_stale"]["result"] == "PASS", "V38 stale gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION", "preallocation state mismatch")
    require(len(gates["predecessors"]["candidate_names"]) == 22, "preallocation candidate count mismatch")
    stale_counts = {
        value: value != 166 for value in (164, 165)
    }
    require(all(stale_counts.values()), "stale inventory fixture failed")
    after_plan, _ = read_regular(PLAN)
    after_status, _ = read_regular(STATUS)
    after = audit_snapshot(after_plan, after_status)
    require(after == before, "full pre-root audit wrote or changed protected state")
    return {
        "acceptance_negatives": negatives, "gate_count": len(gates),
        "gates": {name: "PASS" for name in gates},
        "inventory_negatives": {"164_reject": stale_counts[164], "165_reject": stale_counts[165]},
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
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o600, f"written mode mismatch: {path}")
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
    require(extract_source(plan_bytes, SOURCE_BEGIN, SOURCE_END) == source_bytes, "embedded source mismatch")
    v38 = reconstruct_v38(plan_bytes)
    driver_bytes = derive_driver(v38["driver"])
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(
        driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes,
        source_bytes=source_bytes, helper_bytes=helper_bytes,
    )
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V39 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v39.json", acceptance)
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V39_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n",
    )
    writer_receipt = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        compact({"format_version": 1, "phase": "M3S_V39_WRITER_SELF_TEST", "result": "PASS"}) + b"\n",
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        compact({"audit": audit, "format_version": 1, "phase": "M3S_V39_SELF_CHECK", "result": "PASS", "static": static}) + b"\n",
    )
    final_value = {
        "controller_acceptance": acceptance_identity,
        "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256},
        "driver": driver_identity, "format_version": 1, "phase": "M3S_V39_FINAL_INDEX",
        "root_prepare_argv_json_sha256": sha256(root_argv_json), "source_receipt": source_receipt,
        "self_check": self_check, "verdict": "M3S_V39_READY_FOR_CONTROLLER_REVIEW",
        "writer_self_test": writer_receipt,
    }
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V39_ROOT_ONLY", "result": "M3S_V39_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
