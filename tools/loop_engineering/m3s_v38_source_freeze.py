"""Deterministic M3S-v38 source-freeze and root-only helper.

This credential-free trusted helper derives V38 only from the sealed V37
driver.  It binds the complete stopped V37 prepare closure, repairs historical
candidate-count validation without weakening the phase-aware live name-set
contract, runs the derived driver's full allocation-free read-only gate graph,
and may construct only the fixed V38 root.  It is non-product and import-only.
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
V37_HELPER = DELIVERY / "tools/loop_engineering/m3s_v37_source_freeze.py"
V37_HELPER_SIZE = 37_310
V37_HELPER_SHA256 = "293041d4ef2cbc336ffcb9e77d4b333bd165a00c1e642960f8b40a2d3b142ceb"
V37_ROOT = BASE / "trusted-tools/m3-successor-preparation-v37"
V37_DRIVER = V37_ROOT / "candidate-driver.py"
V37_DRIVER_SIZE = 438_264
V37_DRIVER_SHA256 = "d23f1513e8130da7d389697d33c543770453648ad1d5be5ca117d31f5e97094d"
V37_ROOT_FILES = {
    "candidate-driver.py": (438_264, V37_DRIVER_SHA256),
    "receipts/controller-acceptance-v37.json": (
        9_784,
        "d00250be433935fa1dc69d1f8ff39b7976b215a5dde62d946a1a45c318fcd8ed",
    ),
    "receipts/source-receipt.json": (
        524,
        "ba745a5d94b04d430842beb916de82fe32422c22d064007085dad0868fb5259c",
    ),
    "receipts/writer-self-test.json": (
        72,
        "b09abfdb6b28cebf2a5c787da2bb923902aeeba2a57af61d3c6c1330ac8fd06c",
    ),
    "receipts/self-check-result.json": (
        8_072,
        "18fc6544f84ea687b15b942a450f1b7b7341bd4e67ef4598e665c573094a2f59",
    ),
    "receipts/final-index.json": (
        1_999,
        "c48aadacb754bce93e6ffe9b090fa58304c09b8a1b698d159773f6c313d6f53a",
    ),
    "receipts/successor-preparation-v37-result.json": (
        24_715,
        "ea6666ca7f1265377bdda4492ad8fb2c53ee620dfd42c821d24ef5ca55dd5c2f",
    ),
}
V37_CANDIDATE = BASE / "candidate.vuDWtK0T"
V37_RUN_ID = "20261014T075525Z-4dcccf5a"
V37_CANDIDATE_FILES = {
    "successor-receipts/preservation-receipt.json": (
        281_296,
        "73966dd258cd96b855f8091392ad4309cb110071f164710d0ebd86e18afcca24",
    ),
    "successor-receipts/successor-v37-stop.json": (
        241,
        "bbc6de901b1f01586df4b6b662d50932b72a104cf7e6ceef0ddbb742fdc28c58",
    ),
    "successor-receipts/final-receipt-index.json": (
        18_496,
        "3712d186cc0e43732aed03c29d8aa9226d16c5cab93c5e48ff4049bcd47ae3ac",
    ),
    "successor-receipts/successor-v37-controller-acceptance-offer.json": (
        5_029,
        "f57fcf42a8b85cf5452aec990f7cdc5ccaf25a4c60130dce4ca50de413cfa0fa",
    ),
    "repo/.loop/runs/20261014T075525Z-4dcccf5a/state.json": (
        9_210,
        "9515eef57e186b52e0d516286a5c9ea678eed60bce2198b74c9a5e3a12416dda",
    ),
    "repo/.loop/runs/20261014T075525Z-4dcccf5a/events.jsonl": (
        144,
        "e8b410becf7950eac9c37163c5d394ccb335c5b544ea70355d075b015cbe4209",
    ),
}
V37_CLOSURE = {
    "budgets": {
        "accept_final": "UNCONSUMED_UNAUTHORIZED",
        "auth": "UNAUTHORIZED",
        "formal": "UNAUTHORIZED",
        "init": "CONSUMED_NO_REUSE",
        "prepare_result": "CONSUMED_NO_REUSE",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "CONSUMED_NO_REUSE",
        "verify_prepare": "CONSUMED_NO_REUSE",
    },
    "candidate": {
        "completed_tree": {
            "path_count": 44_322,
            "regular_file_bytes": 948_848_595,
            "sha256": "86c961b967d997e7fa21810b8b6e4ab0ca81223a72eea2b14043008adf28bd16",
        },
        "name": "candidate.vuDWtK0T",
        "run_id": V37_RUN_ID,
    },
    "candidate_count": 22,
    "post_root_documents": {
        "execplan": {
            "sha256": "bdfd3646b50b775792886bc1f4301f049346e383cc62d7405a8291b48e1871b9",
            "size": 7_048_516,
        },
        "status": {
            "sha256": "0c968343e2a42f38c87123e4f388e722149166da2b1ba674c7f566ffe5bf63a4",
            "size": 146_214,
        },
    },
    "prepare": {
        "error": "RuntimeError: V36 candidate count mismatch",
        "output": {
            "sha256": "094c81669dba218a55122645a3969155989fb39c03ba25cf3c3948e8d7467ca3",
            "size": 21_286,
        },
        "result_receipt": {
            "sha256": "ea6666ca7f1265377bdda4492ad8fb2c53ee620dfd42c821d24ef5ca55dd5c2f",
            "size": 24_715,
        },
        "returncode": 1,
        "session_id": 69_918,
        "tool_launch_chunk": "a91429",
        "wrapper_elapsed_seconds": 199.764291,
    },
    "root": str(V37_ROOT),
    "root_files": {
        name: {"sha256": digest, "size": size}
        for name, (size, digest) in V37_ROOT_FILES.items()
    },
    "root_prepare_argv_json_sha256": (
        "fb72c714707fae63b0a165daa719514df6a33a2bfd1e8f048410e431579c114c"
    ),
    "root_verdict": "M3S_V37_READY_FOR_CONTROLLER_REVIEW",
    "sealing": {
        "complete": True,
        "errors": [],
        "final_index": {
            "sha256": "3712d186cc0e43732aed03c29d8aa9226d16c5cab93c5e48ff4049bcd47ae3ac",
            "size": 18_496,
        },
        "preservation": {
            "sha256": "73966dd258cd96b855f8091392ad4309cb110071f164710d0ebd86e18afcca24",
            "size": 281_296,
        },
        "stop": {
            "sha256": "bbc6de901b1f01586df4b6b662d50932b72a104cf7e6ceef0ddbb742fdc28c58",
            "size": 241,
        },
    },
    "verify_prepare": {
        "exit": 0,
        "gate_count": 59,
        "session_id": 51_656,
        "stderr": {
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "size": 0,
        },
        "stdout": {
            "sha256": "6426c9834eaf30b72b9c955198dccfc59166b1abb0cebe20f2eea303858c4516",
            "size": 5_102,
        },
        "tool_chunks": ["c2a01c", "81d484", "9a7104"],
    },
}
ROOT = BASE / "trusted-tools/m3-successor-preparation-v38"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V38_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V38_END\n"
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


class FreezeError(RuntimeError):
    """Fail-closed V38 design or construction error."""


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


def require_file(path: Path, size: int, digest: str, mode: int = 0o600) -> dict[str, Any]:
    payload, info = read_regular(path)
    require((len(payload), sha256(payload)) == (size, digest), f"identity mismatch: {path}")
    require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode, f"mode mismatch: {path}")
    return {
        "mode": f"{mode:04o}", "owner_uid": info.st_uid, "path": str(path),
        "sha256": digest, "size": size,
    }


def load_v37_helper() -> tuple[Any, bytes]:
    helper_bytes, _ = read_regular(V37_HELPER, 128 * 1024)
    require(
        (len(helper_bytes), sha256(helper_bytes)) == (V37_HELPER_SIZE, V37_HELPER_SHA256),
        "sealed V37 helper mismatch",
    )
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v37_frozen", V37_HELPER)
    require(spec is not None and spec.loader is not None, "V37 helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, helper_bytes


def literal_assignment(payload: bytes, name: str) -> Any:
    tree = ast.parse(payload, filename="<m3s-v38-literal>")
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
    tree = ast.parse(text, filename="<m3s-v38-assignment>")
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


def derive_driver(v37_bytes: bytes) -> bytes:
    """Derive V38 deterministically and only from the sealed V37 driver."""

    require(
        (len(v37_bytes), sha256(v37_bytes)) == (V37_DRIVER_SIZE, V37_DRIVER_SHA256),
        "sealed V37 driver mismatch",
    )
    text = v37_bytes.decode("utf-8")
    future_upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    future_lower = "liveclip_future_version_lower"
    require(future_upper not in text and future_lower not in text, "version sentinel collision")
    text = text.replace("V38", future_upper).replace("v38", future_lower)
    text = text.replace("V37", "V38").replace("v37", "v38")
    text = text.replace(future_upper, "V39").replace(future_lower, "v39")
    for old, new, label in (
        (
            'current_result_name = "successor-preparation-v" + "37-result.json"',
            'current_result_name = "successor-preparation-v" + "38-result.json"',
            "current result",
        ),
        (
            'future_result_name = "successor-preparation-v" + "38-result.json"',
            'future_result_name = "successor-preparation-v" + "39-result.json"',
            "future result",
        ),
        (
            'regression_name = "successor-preparation-v" + "37-result.json"',
            'regression_name = "successor-preparation-v" + "38-result.json"',
            "regression result",
        ),
    ):
        text = replace_once(text, old, new, label)
    text = replace_once(text, '"038-result.json"', '"039-result.json"', "future substitution")
    text = replace_once(text, "range(38, 55)", "range(39, 55)", "future range")
    text = replace_once(text, '"ordinary_untracked": 163', '"ordinary_untracked": 164', "inventory")
    text = replace_once(
        text,
        'PREDECESSORS["candidate.5nZWpynN"] = (0, 0, "0" * 64, "0" * 64)',
        'PREDECESSORS["candidate.5nZWpynN"] = (0, 0, "0" * 64, "0" * 64)\n'
        'PREDECESSORS["candidate.vuDWtK0T"] = (44322, 948848595, '
        '"86c961b967d997e7fa21810b8b6e4ab0ca81223a72eea2b14043008adf28bd16", '
        '"9538aca6435d95b1ca0ee86119040f5b02b144a54c7ad6d3e47256c23a3ddb57")',
        "V37 predecessor",
    )
    text = replace_once(
        text,
        'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.5nZWpynN"] = 0',
        'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.5nZWpynN"] = 0\n'
        'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.vuDWtK0T"] = 0',
        "V37 credential omission domain",
    )
    text = replace_once(
        text,
        '    require(len([path for path in BASE.iterdir() if path.name.startswith("candidate.")]) == closure["candidate_count"], "V36 candidate count mismatch")',
        '    require(closure["candidate_count"] == 21, "V36 recorded candidate count mismatch")',
        "V36 historical count",
    )
    text = replace_once(
        text,
        '    require(len([path for path in BASE.iterdir() if path.name.startswith("candidate.")]) == closure["candidate_count"], "V35 candidate count mismatch")',
        '    require(closure["candidate_count"] == 21, "V35 recorded candidate count mismatch")',
        "V35 historical count",
    )
    text = replace_once(
        text,
        '''    require(
        len([path for path in BASE.iterdir() if path.name.startswith("candidate.")])
        == closure["candidate_count"],
        "V34 stopped candidate count mismatch",
    )''',
        '''    require(
        closure["candidate_count"] == 21,
        "V34 recorded candidate count mismatch",
    )''',
        "V34 historical count",
    )
    text = replace_once(
        text,
        "CONTROLLER_ROOT_BINDING =",
        f"PREVIOUS_M3S_V37_CLOSURE = {V37_CLOSURE!r}\n\nCONTROLLER_ROOT_BINDING =",
        "V37 closure insertion",
    )
    validator_source = '''

def validate_m3s_v37_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V37_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V37 root entries mismatch")
    expected_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_receipts, "V37 receipt set mismatch")
    files = {name: require_identity(root / name, value["sha256"], 0o600, value["size"]) for name, value in closure["root_files"].items()}
    index, _ = load_json(root / "receipts/final-index.json")
    require(index["verdict"] == closure["root_verdict"] and index["root_prepare_argv_json_sha256"] == closure["root_prepare_argv_json_sha256"], "V37 final index mismatch")
    result, _ = load_json(root / "receipts/successor-preparation-v37-result.json")
    prepare = closure["prepare"]
    require(result["phase"] == "M3_SUCCESSOR_PREPARATION_V37" and result["returncode"] == prepare["returncode"] and result["elapsed_seconds"] == prepare["wrapper_elapsed_seconds"] and result["timed_out"] is False and result["output_truncated"] is False and result["wrapper_error"] is None and result["session_id"] is None and result["credential_variables"] == [], "V37 result fixed fields mismatch")
    require(len(result["output"].encode("utf-8")) == prepare["output"]["size"] and sha(result["output"].encode("utf-8")) == prepare["output"]["sha256"], "V37 result output mismatch")
    terminal = json.loads(result["output"])
    require(terminal["candidate"] == str(BASE / closure["candidate"]["name"]) and terminal["error"] == prepare["error"] and terminal["result"]["sealing_complete"] is True and terminal["result"]["path_count"] == closure["candidate"]["completed_tree"]["path_count"] and terminal["result"]["regular_file_bytes"] == closure["candidate"]["completed_tree"]["regular_file_bytes"] and terminal["result"]["sealing_outcomes"]["completed-attempt-tree"]["sha256"] == closure["candidate"]["completed_tree"]["sha256"], "V37 terminal payload mismatch")
    candidate = BASE / closure["candidate"]["name"]
    private_directory_identity(candidate)
    require(set(os.listdir(candidate)) == {"home", "repo", "successor-receipts", "tmp"}, "V37 candidate entries mismatch")
    retained = {
        "preservation": require_identity(candidate / "successor-receipts/preservation-receipt.json", closure["sealing"]["preservation"]["sha256"], 0o600, closure["sealing"]["preservation"]["size"]),
        "stop": require_identity(candidate / "successor-receipts/successor-v37-stop.json", closure["sealing"]["stop"]["sha256"], 0o600, closure["sealing"]["stop"]["size"]),
        "final_index": require_identity(candidate / "successor-receipts/final-receipt-index.json", closure["sealing"]["final_index"]["sha256"], 0o600, closure["sealing"]["final_index"]["size"]),
    }
    run = candidate / "repo/.loop/runs" / closure["candidate"]["run_id"]
    state, state_identity = load_json(run / "state.json")
    events = require_identity(run / "events.jsonl", "e8b410becf7950eac9c37163c5d394ccb335c5b544ea70355d075b015cbe4209", 0o644, 144)
    require(state["state"] == "received" and state["cycle"] == 0 and state["code_cycle"] == 0 and state["coder_session_id"] is None and state["last_error"] is None and state["artifacts"] == {} and state["command_results"] == [], "V37 run state mismatch")
    require(closure["candidate_count"] == 22, "V37 recorded candidate count mismatch")
    for name in ("final-controller-acceptance-v37-result.json", "auth-handoff-v37-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V37 reserved result appeared")
    require(closure["budgets"]["prepare_result"] == "CONSUMED_NO_REUSE" and closure["budgets"]["suffix"] == "CONSUMED_NO_REUSE" and closure["budgets"]["init"] == "CONSUMED_NO_REUSE", "V37 budget mismatch")
    return {"closure": closure, "events": events, "files": files, "retained": retained, "state": state_identity, "result": "PASS"}
'''
    text = replace_once(
        text,
        "\ndef validate_m3s_v36_stopped() -> dict[str, Any]:",
        validator_source + "\n\ndef validate_m3s_v36_stopped() -> dict[str, Any]:",
        "V37 validator insertion",
    )
    text = replace_once(
        text,
        '        "m3s_v36_stopped": validate_m3s_v36_stopped(),',
        '        "m3s_v37_stopped": validate_m3s_v37_stopped(),\n'
        '        "m3s_v36_stopped": validate_m3s_v36_stopped(),',
        "V37 gate insertion",
    )
    enhanced_cases = '''        "preallocation_duplicate_reject": not candidate_name_set_matches(
            [*predecessors, predecessors[0]],
            None,
        ),
        "preallocation_missing_reject": not candidate_name_set_matches(
            predecessors[1:],
            None,
        ),
        "postallocation_duplicate_current_reject": not candidate_name_set_matches(
            [*predecessors, current, current],
            current,
        ),
        "postallocation_current_predecessor_reject": not candidate_name_set_matches(
            predecessors,
            predecessors[0],
        ),
'''
    text = replace_once(
        text,
        '        "preallocation_exact_predecessors_accept": candidate_name_set_matches(\n'
        '            predecessors,\n'
        '            None,\n'
        '        ),\n',
        '        "preallocation_exact_predecessors_accept": candidate_name_set_matches(\n'
        '            predecessors,\n'
        '            None,\n'
        '        ),\n' + enhanced_cases,
        "candidate set fixtures",
    )
    old_semantic = '''def controller_acceptance_semantic_violations(value: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V36_CLOSURE):
        violations.append("predecessor_closure")
    if value.get("root") != CONTROLLER_ROOT_BINDING:
        violations.append("root")
    return violations'''
    new_semantic = old_semantic.replace("PREVIOUS_M3S_V36_CLOSURE", "PREVIOUS_M3S_V37_CLOSURE")
    text = replace_once(text, old_semantic, new_semantic, "V37 predecessor semantic")
    payload = text.encode("utf-8")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    names = sorted(EXPECTED_CANDIDATES, key=os.fsencode)
    contracts["candidate_allocation"]["expected_predecessors"] = names
    contracts["candidate_allocation"]["predecessor_count"] = 22
    contracts["candidate_allocation"]["candidate_set_contract"] = {
        "postallocation": "exact 22 predecessors plus one unpredictable current candidate",
        "preallocation": "exact 22 immutable predecessor names",
        "rejects": ["unknown_extra", "missing", "duplicate", "current_is_predecessor"],
        "live_authority": "validate_predecessors/candidate_name_set_matches plus accept_final exact postprepare set",
    }
    contracts["policy_toolchain"]["historical_candidate_counts"] = {
        "current_live_total_not_consulted": ["V34", "V35", "V36", "V37"],
        "recorded_counts": {"V34": 21, "V35": 21, "V36": 21, "V37": 22},
        "validator": "historical closure structural fields",
    }
    contracts["policy_toolchain"]["pre_root_full_audit"] = {
        "allocation": False,
        "gate_count": 60,
        "home": str(V37_ROOT / "home"),
        "include_process_gate": True,
        "no_write_snapshot": True,
        "tmp": str(V37_ROOT / "tmp"),
    }
    contracts["policy_toolchain"]["controller_acceptance_semantics"] = {
        "model": "controller_acceptance_semantic_violations",
        "predecessor": "PREVIOUS_M3S_V37_CLOSURE",
        "rejects": ["V36", "missing", "mutated_v37", "extra_v37", "wrong_root"],
    }
    contracts["trusted_context"]["immediate_predecessor"] = {
        "candidate": "candidate.vuDWtK0T",
        "closure": "PREVIOUS_M3S_V37_CLOSURE",
        "prepare": "CONSUMED_STOPPED_POSTALLOCATION",
        "root": str(V37_ROOT),
        "run_id": V37_RUN_ID,
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
    tree = ast.parse(text, filename="<m3s-v38-driver>")
    compile(tree, "<m3s-v38-driver>", "exec")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
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
    gate = function_node(tree, "read_only_gates")
    returns = [node for node in ast.walk(gate) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    require(len(returns) == 1 and len(returns[0].value.keys) == 60, "gate count mismatch")
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(payload.count(b'"ordinary_untracked": 164') == 1, "inventory count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "38-result.json"' in payload, "current result mismatch")
    require(b'future_result_name = "successor-preparation-v" + "39-result.json"' in payload, "future result mismatch")
    require(b'PREDECESSORS["candidate.vuDWtK0T"]' in payload, "V37 predecessor missing")
    for stale in (
        b'"V34 candidate count mismatch"', b'"V35 candidate count mismatch"',
        b'"V36 candidate count mismatch"', b'"V37 candidate count mismatch"',
    ):
        require(stale not in payload, "live historical count assertion retained")
    live_candidate_functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and "BASE.iterdir()" in (ast.get_source_segment(text, node) or "")
        and "candidate." in (ast.get_source_segment(text, node) or "")
    }
    require(
        live_candidate_functions
        == {"_v38_legacy_validate_predecessors", "validate_predecessors", "accept_final"},
        "live candidate assertion surface mismatch",
    )
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v38_static"}
    exec(compile(tree, "<m3s-v38-static>", "exec"), namespace)  # noqa: S102
    shapes = namespace["SHAPES"]
    require({name: len(shape) for name, shape in shapes.items()} == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    required_cases = {
        "preallocation_exact_predecessors_accept", "preallocation_duplicate_reject",
        "preallocation_missing_reject", "postallocation_exact_current_accept",
        "postallocation_duplicate_current_reject", "postallocation_current_predecessor_reject",
        "postallocation_missing_current_reject", "postallocation_missing_predecessor_reject",
        "postallocation_substituted_predecessor_reject", "postallocation_second_extra_reject",
    }
    require(required_cases <= candidate_cases.keys() and all(candidate_cases[name] for name in required_cases), "candidate fixtures mismatch")
    return {
        "ast_compile": "PASS", "candidate_set_cases": candidate_cases,
        "command_surface": {name: len(shape) for name, shape in shapes.items()},
        "contracts": hashes, "gate_count": 60, "one_loop_init": True,
        "live_candidate_functions": sorted(live_candidate_functions),
        "one_mktemp": True, "result": "PASS",
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
        "phase": "M3S_V38_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V37_CLOSURE,
        "preparation_source": {
            "helper": {
                "path": str(DELIVERY / "tools/loop_engineering/m3s_v38_source_freeze.py"),
                "sha256": sha256(helper_bytes), "size": len(helper_bytes),
            },
            "sealed_v37_helper": {"path": str(V37_HELPER), "sha256": V37_HELPER_SHA256, "size": V37_HELPER_SIZE},
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
        cwd=DELIVERY,
        env={"PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
    )
    require(result.returncode == 0 and result.stderr == b"", "git status snapshot failed")
    return result.stdout


def v37_snapshot() -> dict[str, Any]:
    root_info = V37_ROOT.lstat()
    require(stat.S_ISDIR(root_info.st_mode) and not V37_ROOT.is_symlink(), "unsafe V37 root")
    require(root_info.st_uid == CURRENT_UID and stat.S_IMODE(root_info.st_mode) == 0o700, "V37 root mode mismatch")
    require(set(os.listdir(V37_ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}, "V37 root entries mismatch")
    files = {name: require_file(V37_ROOT / name, size, digest) for name, (size, digest) in V37_ROOT_FILES.items()}
    candidate_info = V37_CANDIDATE.lstat()
    require(stat.S_ISDIR(candidate_info.st_mode) and not V37_CANDIDATE.is_symlink(), "unsafe V37 candidate")
    require(set(os.listdir(V37_CANDIDATE)) == {"home", "repo", "successor-receipts", "tmp"}, "V37 candidate entries mismatch")
    candidate_files = {name: require_file(V37_CANDIDATE / name, size, digest, 0o644 if name.endswith(("state.json", "events.jsonl")) else 0o600) for name, (size, digest) in V37_CANDIDATE_FILES.items()}
    for name in ("final-controller-acceptance-v37-result.json", "auth-handoff-v37-result.json"):
        path = V37_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V37 reserved result appeared")
    return {"candidate_files": candidate_files, "files": files, "root_mode": "0700"}


def audit_snapshot(plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    candidates = tuple(sorted((p.name for p in BASE.iterdir() if p.name.startswith("candidate.")), key=os.fsencode))
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    return {
        "candidates_sha256": sha256(compact(candidates)),
        "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)},
        "git_status_sha256": sha256(git_status_bytes()),
        "v37": v37_snapshot(),
        "v38_root_absent": not ROOT.exists() and not ROOT.is_symlink(),
    }


def full_pre_root_audit(
    driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes,
) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    require(before["v38_root_absent"] is True, "V38 root exists before audit")
    tree = ast.parse(driver_bytes, filename="<m3s-v38-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v38_audit"}
    exec(compile(tree, "<m3s-v38-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V37 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (
        ("v36_substitution", namespace["PREVIOUS_M3S_V36_CLOSURE"]),
        ("missing", {}),
    ):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["prepare"]["error"] = "RuntimeError: substituted"
    negatives["mutated_v37"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v37"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 37}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(
        all(negatives[name] == ["predecessor_closure"] for name in ("v36_substitution", "missing", "mutated_v37", "extra_v37"))
        and negatives["wrong_root"] == ["root"],
        "V37 acceptance negative accepted",
    )
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
            values, V37_ROOT / "home", V37_ROOT / "tmp", include_process_gate=True
        )
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 60, "full pre-root gate count mismatch")
    require(gates["m3s_v37_stopped"]["result"] == "PASS", "V37 closure gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION", "preallocation state mismatch")
    require(len(gates["predecessors"]["candidate_names"]) == 22, "preallocation candidate count mismatch")
    after_plan, _ = read_regular(PLAN)
    after_status, _ = read_regular(STATUS)
    after = audit_snapshot(after_plan, after_status)
    require(after == before, "full pre-root audit wrote or changed protected state")
    return {
        "acceptance_negatives": negatives,
        "gate_count": len(gates),
        "gates": {name: "PASS" for name in gates},
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
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    require(plan_bytes[start:finish] == source_bytes, "embedded source mismatch")
    load_v37_helper()
    v37_bytes, _ = read_regular(V37_DRIVER)
    driver_bytes = derive_driver(v37_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(
        driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes,
        source_bytes=source_bytes, helper_bytes=helper_bytes,
    )
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V38 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v38.json", acceptance)
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V38_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n",
    )
    writer_receipt = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        compact({"format_version": 1, "phase": "M3S_V38_WRITER_SELF_TEST", "result": "PASS"}) + b"\n",
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        compact({"audit": audit, "format_version": 1, "phase": "M3S_V38_SELF_CHECK", "result": "PASS", "static": static}) + b"\n",
    )
    final_value = {
        "controller_acceptance": acceptance_identity,
        "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256},
        "driver": driver_identity, "format_version": 1, "phase": "M3S_V38_FINAL_INDEX",
        "root_prepare_argv_json_sha256": sha256(root_argv_json), "source_receipt": source_receipt,
        "self_check": self_check, "verdict": "M3S_V38_READY_FOR_CONTROLLER_REVIEW",
        "writer_self_test": writer_receipt,
    }
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V38_ROOT_ONLY", "result": "M3S_V38_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
