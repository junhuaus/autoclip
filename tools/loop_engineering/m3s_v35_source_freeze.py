"""Deterministic M3S-v35 source-freeze and root-only helper.

This is credential-free trusted recovery machinery, not product code.  It
derives V35 only from the sealed V34 driver, repairs the exact V29 closure and
delivery-inventory defects, adds a read-only post-root verification command,
and implements only the fixed-root construction boundary.
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
V34_HELPER = DELIVERY / "tools/loop_engineering/m3s_v34_source_freeze.py"
V34_HELPER_SIZE = 48_066
V34_HELPER_SHA256 = "1a105b430a1c42357f817d86cd7ab077866605ec20244023621eb4577642ca89"
V34_ROOT = BASE / "trusted-tools/m3-successor-preparation-v34"
V34_DRIVER = V34_ROOT / "candidate-driver.py"
V34_DRIVER_SIZE = 419_288
V34_DRIVER_SHA256 = "376a6a65e907dd37024e9c615dd8e80e2fd0ab429b1e7d588bf7ffb67a8aa311"
V34_ROOT_FILES = {
    "candidate-driver.py": (419_288, V34_DRIVER_SHA256),
    "receipts/controller-acceptance-v34.json": (
        7_776,
        "37bc9a44abfec3563591f257a7da73784ee60735cd80ae4426d03d5bc3ca3b26",
    ),
    "receipts/source-receipt.json": (
        1_285,
        "b886fb83a89dbc6e16d75a0e55bf9a5f1b7d7e9de598b30c59fe8632a23750b1",
    ),
    "receipts/writer-self-test.json": (
        124,
        "574319210cc14fa09c4c4c2ad93e3a09c9de3d58422993ae40486a09591d6d54",
    ),
    "receipts/self-check-result.json": (
        9_611,
        "bbeca7385bb70baeb192d5bd9205e7e95eec7a34545dd1e897fafaf185cab579",
    ),
    "receipts/final-index.json": (
        2_434,
        "06cd81b2ee35260a9362c3f9721c98e84aa250e02da62433d4b845e70ff0c5b1",
    ),
    "receipts/successor-preparation-v34-result.json": (
        3_880,
        "596375f122b97bb8f685466afff5537a2b67fbc0e93054da8da6097ef652218e",
    ),
}
V34_CLOSURE = {
    "accepted_documents": {
        "execplan": {
            "sha256": "05eb192555b5326f31a03fabcf027683aa32c98362c4befe2845d8583e8b2410",
            "size": 6_981_737,
        },
        "status": {
            "sha256": "51f75f849ec5be029256b38f2f35ac9f5b5e903db2f62673b396d1222270e913",
            "size": 136_792,
        },
    },
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
        "elapsed_seconds": 53.205939,
        "error": "RuntimeError: V29 terminal evidence mismatch",
        "inputs": {
            "direct_wrapper_argv_json_sha256": (
                "19419a3ebe2f065c224bdaea3a398de668fb71cf4e810d29d7e2385e2fda6001"
            ),
            "prepare_argv_json_sha256": (
                "b78d3f1fac0838ab457f5dd712255ce5f5e5e45e4eb5afed23b77ae6e5ebe513"
            ),
            "shell_envelope_sha256": (
                "dbaf62be1a50497c4de32993a59303af64cd13ac625e24df653f5075d3a7297a"
            ),
        },
        "result_receipt": {
            "mode": "0600",
            "owner_uid": 501,
            "sha256": "596375f122b97bb8f685466afff5537a2b67fbc0e93054da8da6097ef652218e",
            "size": 3_880,
        },
        "returncode": 1,
        "result": "STOPPED_PREALLOCATION",
        "timed_out": False,
        "tool": {
            "launch_chunk": "5dbeaf",
            "session_id": 45505,
            "terminal_chunk": "5a23c5",
        },
    },
    "root": str(V34_ROOT),
    "root_files": {
        name: {"sha256": digest, "size": size}
        for name, (size, digest) in V34_ROOT_FILES.items()
    },
    "root_verdict": "M3S_V34_READY_FOR_CONTROLLER_REVIEW",
}
ROOT = BASE / "trusted-tools/m3-successor-preparation-v35"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V35_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V35_END\n"
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


class FreezeError(RuntimeError):
    """Fail-closed design or construction error."""


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
    require(len(payload) == size and sha256(payload) == digest, f"identity mismatch: {path}")
    require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode, f"owner/mode mismatch: {path}")
    return {
        "mode": f"{mode:04o}",
        "owner_uid": info.st_uid,
        "path": str(path),
        "sha256": digest,
        "size": size,
    }


def load_v34_helper() -> tuple[Any, bytes]:
    helper_bytes, _ = read_regular(V34_HELPER, 128 * 1024)
    require(
        (len(helper_bytes), sha256(helper_bytes))
        == (V34_HELPER_SIZE, V34_HELPER_SHA256),
        "sealed V34 helper mismatch",
    )
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v34_frozen", V34_HELPER)
    require(spec is not None and spec.loader is not None, "V34 helper loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, helper_bytes


def replace_once(text: str, old: str, new: str, label: str) -> str:
    require(text.count(old) == 1, f"{label} replacement count mismatch")
    return text.replace(old, new, 1)


def literal_assignment(payload: bytes, name: str) -> Any:
    tree = ast.parse(payload, filename=f"<literal:{name}>")
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    require(len(matches) == 1, f"assignment count mismatch: {name}")
    return ast.literal_eval(matches[0].value)


def replace_assignment(text: str, name: str, value: object) -> str:
    payload = text.encode("utf-8")
    tree = ast.parse(payload, filename=f"<replace:{name}>")
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    require(len(matches) == 1, f"assignment count mismatch: {name}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    replacement = f"{name} = {value!r}"
    return text[:start] + replacement + text[end:]


def derive_driver(v34_bytes: bytes) -> bytes:
    """Derive V35 from the exact sealed V34 driver."""

    require(
        (len(v34_bytes), sha256(v34_bytes)) == (V34_DRIVER_SIZE, V34_DRIVER_SHA256),
        "sealed V34 driver mismatch",
    )
    text = v34_bytes.decode("utf-8")
    future_upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    future_lower = "liveclip_future_version_lower"
    require(future_upper not in text and future_lower not in text, "sentinel collision")
    text = text.replace("V35", future_upper).replace("v35", future_lower)
    text = text.replace("V34", "V35").replace("v34", "v35")
    text = text.replace(future_upper, "V36").replace(future_lower, "v36")
    for old, new, label in (
        ('current_result_name = "successor-preparation-v" + "34-result.json"', 'current_result_name = "successor-preparation-v" + "35-result.json"', "current result"),
        ('future_result_name = "successor-preparation-v" + "35-result.json"', 'future_result_name = "successor-preparation-v" + "36-result.json"', "future result"),
        ('regression_name = "successor-preparation-v" + "34-result.json"', 'regression_name = "successor-preparation-v" + "35-result.json"', "regression result"),
        ('"035-result.json"', '"036-result.json"', "substitution result"),
        ("range(35, 55)", "range(36, 55)", "future result range"),
        ('"ordinary_untracked": 160', '"ordinary_untracked": 161', "inventory count"),
        ("RuntimeError: future V31 result fixture mismatch", "RuntimeError: future V30 result fixture mismatch", "V29 closure error"),
    ):
        text = replace_once(text, old, new, label)

    closure_literal = repr(V34_CLOSURE)
    text = replace_once(
        text,
        "CONTROLLER_ROOT_BINDING =",
        f"PREVIOUS_M3S_V34_CLOSURE = {closure_literal}\n\nCONTROLLER_ROOT_BINDING =",
        "V34 closure insertion",
    )
    text = replace_once(
        text,
        'SHAPES["accept-final"] = [',
        'SHAPES["verify-prepare"] = ["verify-prepare", *SHAPES["prepare"][1:]]\n\nSHAPES["accept-final"] = [',
        "verify shape insertion",
    )
    execute_receipts = (
        '        "execute": {\n'
        '            "source-receipt.json",\n'
        '            "writer-self-test.json",\n'
        '            "self-check-result.json",\n'
        '            "final-index.json",\n'
        '            "controller-acceptance-v35.json",\n'
        '        },'
    )
    text = replace_once(
        text,
        execute_receipts,
        execute_receipts
        + '\n        "verify-prepare": {\n'
        + '            "source-receipt.json",\n'
        + '            "writer-self-test.json",\n'
        + '            "self-check-result.json",\n'
        + '            "final-index.json",\n'
        + '            "controller-acceptance-v35.json",\n'
        + '        },',
        "verify root-state insertion",
    )

    validate_v34 = '''\n\ndef validate_m3s_v34_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V34_CLOSURE
    root = Path(closure["root"])
    files = {
        name: require_identity(root / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["root_files"].items()
    }
    result, _ = load_json(root / "receipts/successor-preparation-v34-result.json")
    require(
        result["phase"] == "M3_SUCCESSOR_PREPARATION_V34"
        and result["returncode"] == 1
        and result["timed_out"] is False
        and result["output_truncated"] is False
        and result["wrapper_error"] is None
        and result["session_id"] is None
        and result["credential_variables"] == []
        and result["output"].endswith(closure["prepare"]["error"] + "\\n"),
        "V34 stopped result mismatch",
    )
    require(
        len([path for path in BASE.iterdir() if path.name.startswith("candidate.")])
        == closure["candidate_count"],
        "V34 stopped candidate count mismatch",
    )
    for name in (
        "final-controller-acceptance-v34-result.json",
        "auth-handoff-v34-result.json",
    ):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V34 forbidden result appeared")
    return {"closure": closure, "files": files, "result": "PASS"}
'''
    text = replace_once(
        text,
        "\ndef validate_m3s_v33_blocked() -> dict[str, Any]:",
        validate_v34 + "\n\ndef validate_m3s_v33_blocked() -> dict[str, Any]:",
        "V34 validator insertion",
    )
    text = replace_once(
        text,
        '        "m3s_v33_blocked": validate_m3s_v33_blocked(),',
        '        "m3s_v34_stopped": validate_m3s_v34_stopped(),\n'
        '        "m3s_v33_blocked": validate_m3s_v33_blocked(),',
        "V34 gate insertion",
    )

    verify_source = '''\n\ndef verify_prepare(values: dict[str, str]) -> int:
    started = time.monotonic()
    initial_driver = self_identity(values["expected_self_sha"])
    active_phase_check = validate_active_phase_names()
    current_argv = [str(PYTHON), str(DRIVER), *sys.argv[1:]]
    environment = validate_phase_environment(
        "M3S_" + "V35_VERIFY_PREPARE",
        120,
        current_argv,
        None,
    )
    root_state = validate_m2b_state("verify-prepare", values["expected_self_sha"])
    _, acceptance_identity, acceptance_value = validate_controller_acceptance(values)
    validate_wrapper(values["wrapper"], values["expected_wrapper_sha"])
    final_index = M2B / "receipts/final-index.json"
    require_identity(final_index, values["expected_bootstrap_final_index_sha256"], 0o600)
    index, _ = load_json(final_index)
    require(index["verdict"] == "M3S_V35_READY_FOR_CONTROLLER_REVIEW", "verify final-index verdict mismatch")
    require(index["controller_acceptance"]["sha256"] == values["expected_root_acceptance_sha256"], "verify root acceptance mismatch")
    require(index["documents"] == {"plan_sha256": acceptance_value["documents"]["execplan"]["sha256"], "status_sha256": acceptance_value["documents"]["status"]["sha256"]}, "verify historical documents mismatch")
    os.environ["M3S_PLAN_SHA256"] = values["expected_plan_sha256"]
    os.environ["M3S_STATUS_SHA256"] = values["expected_status_sha256"]
    gates = read_only_gates(
        values,
        M2B / "home",
        M2B / "tmp",
        include_process_gate=True,
    )
    require(time.monotonic() - started < 120, "post-root verification deadline exhausted")
    os.write(1, compact({
        "active_phase_check": active_phase_check,
        "controller_acceptance": acceptance_identity,
        "driver": initial_driver,
        "environment": environment,
        "gate_count": len(gates),
        "phase": "M3S_V35_POST_ROOT_VERIFY_PREPARE",
        "result": "PASS",
        "root_state": root_state,
    }) + b"\\n")
    return 0
'''
    text = replace_once(
        text,
        "\ndef execute(values: dict[str, str]) -> int:",
        verify_source + "\n\ndef execute(values: dict[str, str]) -> int:",
        "post-root verification insertion",
    )
    text = replace_once(
        text,
        '    if command == "prepare":\n        return execute(values)',
        '    if command == "verify-prepare":\n'
        '        return verify_prepare(values)\n'
        '    if command == "prepare":\n'
        '        return execute(values)',
        "verify dispatch insertion",
    )

    payload = text.encode("utf-8")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    require(isinstance(contracts, dict), "contract object mismatch")
    contracts["policy_toolchain"]["post_root_verification"] = {
        "allocation": False,
        "command": "verify-prepare",
        "home": str(ROOT / "home"),
        "include_process_gate": True,
        "prepare_value_schema": 23,
        "tmp": str(ROOT / "tmp"),
    }
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"function count mismatch: {name}")
    return matches[0]


def verify_surface_model(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8")
    tree = ast.parse(text, filename="<m3s-v35-surface>")
    function = function_node(tree, "verify_prepare")
    source = ast.get_source_segment(text, function)
    require(source is not None, "verify surface source unavailable")

    def violations(candidate: str) -> list[str]:
        found: list[str] = []
        if 'read_only_gates(\n        values,\n        M2B / "home",\n        M2B / "tmp",\n        include_process_gate=True,\n    )' not in candidate:
            found.append("full-gate-call")
        for forbidden in ("/usr/bin/mktemp", "loop-init", "write_exclusive(", "execute(values)"):
            if forbidden in candidate:
                found.append("allocation-or-write:" + forbidden)
        return found

    require(violations(source) == [], "post-root verification surface mismatch")
    negatives = {
        "process_gate_false": violations(source.replace("include_process_gate=True", "include_process_gate=False")),
        "home_substitution": violations(source.replace('M2B / "home"', 'M2B / "tmp"', 1)),
        "allocation_injected": violations(source + '\n    marker = "/usr/bin/mktemp"'),
    }
    require(all(value for value in negatives.values()), "post-root negative fixture accepted")
    return {"negative_fixtures": negatives, "result": "PASS"}


def inspect_driver(payload: bytes) -> dict[str, Any]:
    tree = ast.parse(payload, filename="<m3s-v35-driver>")
    compile(tree, "<m3s-v35-driver>", "exec")
    shapes = literal_assignment(payload, "SHAPES") if False else None
    del shapes
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require(
        {name: sha256(compact(value)) for name, value in contracts.items()} == hashes,
        "contract hash mismatch",
    )
    execute_function = function_node(tree, "execute")
    initialize_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "initialize_and_bind_successor"
    ]
    require(len(initialize_functions) == 2, "successor initializer count mismatch")
    mktemp_lists = [
        node
        for node in ast.walk(execute_function)
        if isinstance(node, ast.List)
        and node.elts
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "/usr/bin/mktemp"
    ]
    loop_init_lists = [
        node
        for function in initialize_functions
        for node in ast.walk(function)
        if isinstance(node, ast.List)
        and len(node.elts) >= 2
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "/usr/bin/make"
        and isinstance(node.elts[1], ast.Constant)
        and node.elts[1].value == "loop-init"
    ]
    require(len(mktemp_lists) == 1, "mktemp call count mismatch")
    require(len(loop_init_lists) == 1, "loop-init call count mismatch")
    require(b"RuntimeError: future V30 result fixture mismatch" in payload, "V29 repair missing")
    require(b"RuntimeError: future V31 result fixture mismatch" not in payload, "old V29 error retained")
    require(payload.count(b'"ordinary_untracked": 161') == 1, "inventory count mismatch")
    require(b'"ordinary_untracked": 160' not in payload, "stale inventory count retained")
    gate_function = function_node(tree, "read_only_gates")
    returns = [node for node in ast.walk(gate_function) if isinstance(node, ast.Return)]
    require(len(returns) == 1 and isinstance(returns[0].value, ast.Dict), "gate return mismatch")
    gate_count = len(returns[0].value.keys)
    require(gate_count == 57, "read-only gate count mismatch")
    main_source = ast.get_source_segment(payload.decode("utf-8"), function_node(tree, "main"))
    require(main_source is not None and 'command == "verify-prepare"' in main_source, "verify dispatch missing")
    return {
        "ast_compile": "PASS",
        "contracts": hashes,
        "gate_count": gate_count,
        "post_root_verification": verify_surface_model(payload),
        "result": "PASS",
    }


def runtime_validation(payload: bytes, plan_sha: str, status_sha: str) -> dict[str, Any]:
    tree = ast.parse(payload, filename="<m3s-v35-runtime>")
    namespace: dict[str, Any] = {
        "__file__": str(DRIVER),
        "__name__": "liveclip_m3s_v35_static_runtime",
    }
    exec(compile(tree, "<m3s-v35-runtime>", "exec"), namespace)  # noqa: S102
    shapes = namespace["SHAPES"]
    require(
        set(shapes) == {"prepare", "verify-prepare", "accept-final"}
        and len(shapes["prepare"]) == 23
        and len(shapes["verify-prepare"]) == 23
        and len(shapes["accept-final"]) == 15,
        "actual command surface mismatch",
    )
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(phase_violations == [], "actual phase-source policy mismatch")
    repaired = namespace["validate_m3s_v29_stopped"]()
    require(repaired["closure"]["candidate_recovery"]["error"].endswith("future V30 result fixture mismatch"), "actual V29 repair mismatch")
    old_closure = copy.deepcopy(namespace["PREVIOUS_M3S_V29_CLOSURE"])
    old_closure["candidate_recovery"]["error"] = "RuntimeError: future V31 result fixture mismatch"
    namespace["PREVIOUS_M3S_V29_CLOSURE"] = old_closure
    old_rejected = False
    try:
        namespace["validate_m3s_v29_stopped"]()
    except RuntimeError:
        old_rejected = True
    require(old_rejected, "old V29 string negative accepted")
    namespace["PREVIOUS_M3S_V29_CLOSURE"] = literal_assignment(payload, "PREVIOUS_M3S_V29_CLOSURE")
    v34_stopped = namespace["validate_m3s_v34_stopped"]()

    observed = namespace["status_counts"](DELIVERY)
    expected = {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 161}
    require(observed == expected, "final inventory mismatch")
    original = namespace["validate_original"](plan_sha, status_sha)
    real_status_counts = namespace["status_counts"]
    stale: dict[str, bool] = {}
    for count in (156, 159, 160):
        namespace["status_counts"] = lambda _path, value=count: {
            "staged": 0,
            "modified_tracked": 15,
            "ordinary_untracked": value,
        }
        rejected = False
        try:
            namespace["validate_original"](plan_sha, status_sha)
        except RuntimeError:
            rejected = True
        stale[f"stale_{count}_rejected"] = rejected
    namespace["status_counts"] = real_status_counts
    require(all(stale.values()), "stale inventory fixture accepted")
    return {
        "actual_v29_stopped": "PASS",
        "actual_v34_stopped": v34_stopped["result"],
        "command_surface": {
            "accept_final_tokens": len(shapes["accept-final"]),
            "commands": sorted(shapes),
            "prepare_tokens": len(shapes["prepare"]),
            "verify_prepare_tokens": len(shapes["verify-prepare"]),
        },
        "final_inventory": observed,
        "old_v31_string_rejected": old_rejected,
        "original": original,
        "phase_source_policy": "PASS",
        "result": "PASS",
        "stale_fixtures": stale,
    }


def validate_v34_root() -> dict[str, Any]:
    root_info = V34_ROOT.lstat()
    require(stat.S_ISDIR(root_info.st_mode) and not V34_ROOT.is_symlink(), "unsafe V34 root")
    require(root_info.st_uid == CURRENT_UID and stat.S_IMODE(root_info.st_mode) == 0o700, "V34 root owner/mode mismatch")
    require(set(os.listdir(V34_ROOT)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V34 root entries mismatch")
    directories: dict[str, dict[str, Any]] = {}
    for name in ("home", "tmp", "receipts"):
        path = V34_ROOT / name
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), f"unsafe V34 directory: {name}")
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700, f"V34 directory owner/mode mismatch: {name}")
        directories[name] = {"mode": "0700", "owner_uid": info.st_uid, "path": str(path)}
    require(not os.listdir(V34_ROOT / "home") and not os.listdir(V34_ROOT / "tmp"), "V34 private directory not empty")
    expected_receipts = {
        Path(name).name for name in V34_ROOT_FILES if name.startswith("receipts/")
    }
    require(set(os.listdir(V34_ROOT / "receipts")) == expected_receipts, "V34 receipt entries mismatch")
    files = {name: require_file(V34_ROOT / name, size, digest) for name, (size, digest) in V34_ROOT_FILES.items()}
    for name in ("final-controller-acceptance-v34-result.json", "auth-handoff-v34-result.json"):
        path = V34_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V34 forbidden result appeared")
    return {"directories": directories, "files": files, "result": "PASS"}


def expected_environment() -> dict[str, str]:
    return {
        "GIT_OPTIONAL_LOCKS": "0",
        "HOME": "/Users/junhuaxu",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": PATH_VALUE,
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": "/tmp",  # noqa: S108 - frozen root-only environment
        "__CF_USER_TEXT_ENCODING": CF_USER_TEXT_ENCODING,
    }


def build_acceptance(
    driver_bytes: bytes,
    *,
    plan_bytes: bytes,
    status_bytes: bytes,
    source_bytes: bytes,
    helper_bytes: bytes,
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
        "phase": "M3S_V35_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V34_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(DELIVERY / "tools/loop_engineering/m3s_v35_source_freeze.py"), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "sealed_v34_helper": {"path": str(V34_HELPER), "sha256": V34_HELPER_SHA256, "size": V34_HELPER_SIZE},
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
    return compact(value) + b"\n"


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
    v34_module, _ = load_v34_helper()
    del v34_module
    v34_bytes, _ = read_regular(V34_DRIVER)
    driver_bytes = derive_driver(v34_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "derived driver hash mismatch")
    static = inspect_driver(driver_bytes)
    runtime = runtime_validation(driver_bytes, args.expected_plan_sha256, args.expected_status_sha256)
    predecessor = validate_v34_root()
    candidates = tuple(sorted((path.name for path in BASE.iterdir() if path.name.startswith("candidate.")), key=os.fsencode))
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    require(not ROOT.exists() and not ROOT.is_symlink(), "V35 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    acceptance = build_acceptance(driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source_bytes, helper_bytes=helper_bytes)

    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v35.json", acceptance)
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V35_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n",
    )
    writer_receipt = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        compact({"format_version": 1, "phase": "M3S_V35_WRITER_SELF_TEST", "result": "PASS"}) + b"\n",
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        compact({"format_version": 1, "phase": "M3S_V35_SELF_CHECK", "predecessor": predecessor, "result": "PASS", "runtime": runtime, "static": static}) + b"\n",
    )
    final_index_value = {
        "controller_acceptance": acceptance_identity,
        "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256},
        "driver": driver_identity,
        "format_version": 1,
        "phase": "M3S_V35_FINAL_INDEX",
        "root_prepare_argv_json_sha256": sha256(root_argv_json),
        "source_receipt": source_receipt,
        "self_check": self_check,
        "verdict": "M3S_V35_READY_FOR_CONTROLLER_REVIEW",
        "writer_self_test": writer_receipt,
    }
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_index_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V35_ROOT_ONLY", "result": "M3S_V35_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    args = parse_args(argv)
    return root_only(args, source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
