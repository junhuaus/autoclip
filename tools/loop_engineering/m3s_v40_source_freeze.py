"""Deterministic M3S-v40 source-freeze and root-only helper.

This credential-free Trusted Main helper derives V40 only from the sealed V39
driver, binds the terminal V39 formal evidence and the bounded-tree recovery
requirement, executes a read-only pre-root audit, and may create only the fixed
V40 root.  It is non-product and import-only.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
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
RECOVERY_REQUIREMENT = (
    DELIVERY / "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md"
)
SEED = BASE / "candidate.OlsWg1/repo"
V39_ROOT = BASE / "trusted-tools/m3-successor-preparation-v39"
V39_DRIVER = V39_ROOT / "candidate-driver.py"
V39_DRIVER_SIZE = 452_597
V39_DRIVER_SHA256 = "9b756bf28d7c625e28c0a85ff92b1ee40ca7c53572105122973b9a35fdeca7bc"
V39_CANDIDATE = BASE / "candidate.oivrdV6U"
V39_RUN_ID = "20261014T191719Z-0802b465"
V39_RUN = V39_CANDIDATE / "repo/.loop/runs" / V39_RUN_ID
ROOT = BASE / "trusted-tools/m3-successor-preparation-v40"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V40_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V40_END\n"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v40_source_freeze.py"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
ARCHITECTURE_SIZE = 66_116
ARCHITECTURE_SHA256 = "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce"
RECOVERY_REQUIREMENT_SIZE = 12_289
RECOVERY_REQUIREMENT_SHA256 = "308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00"
EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO", "candidate.3WBt3ldA", "candidate.5jh3bylk",
    "candidate.5nZWpynN", "candidate.KWbe2iGW", "candidate.OlsWg1",
    "candidate.Q2vecg", "candidate.UU7EAiJG", "candidate.VoU5SVVl",
    "candidate.aw2oA4", "candidate.bSEqMEit", "candidate.c79YYSLQ",
    "candidate.cQnaAbOf", "candidate.dygENR4n", "candidate.iyme1x_i",
    "candidate.jyq_n37h", "candidate.mRMO7MQ6", "candidate.o99gfxup",
    "candidate.oivrdV6U", "candidate.qaDKDWkQ", "candidate.vuDWtK0T",
    "candidate.xp23hqNY", "candidate.z6EbTJew",
)
RECOVERY_ALLOWLIST = (
    "src/liveclip/agent_runtime/__init__.py",
    "src/liveclip/agent_runtime/checkpoints.py",
    "src/liveclip/media/secure_files.py",
    "src/liveclip/services/agent_clipping_validation.py",
    "src/liveclip/services/agent_clipping_delivery.py",
    "src/liveclip/cli/app.py",
    "scripts/evaluate_agent_benchmark.py",
    "tests/unit/test_agent_runtime.py",
    "tests/unit/test_agent_clipping_validation.py",
    "tests/unit/test_agent_clipping_delivery.py",
    "tests/unit/test_agent_benchmark_evaluator.py",
    "tests/unit/test_secure_files.py",
    "tests/integration/test_agent_clipping_v2.py",
)
SOURCE_PREIMAGES = {
    "src/liveclip/media/secure_files.py": {
        "sha256": "8bf78b587f96b82cd2c2669c2d1b32b10431217ef9bf51f6bed6b171af7f29b6",
        "size": 65_066,
    },
    "tests/unit/test_secure_files.py": {
        "sha256": "05fbb0882926603deff39fa3ebdf34edc075f38fa133e4aeb145281c6491d7b9",
        "size": 28_467,
    },
}
V39_ROOT_FILES = {
    "candidate-driver.py": (452_597, V39_DRIVER_SHA256),
    "receipts/controller-acceptance-v39.json": (
        10_768,
        "e32334901302206f7ea712c1559119c1d8ee8929b5279f71f64088dfab5e4da1",
    ),
    "receipts/source-receipt.json": (
        524,
        "e9ffd0486c0885049557090f98d75084fae6f469cd539f2fd9e9a420baa96098",
    ),
    "receipts/writer-self-test.json": (
        72,
        "3d03786a9b07dea917e1c42b7712ca8cbb19a8c4920a9d171e86fbbe80ee22d3",
    ),
    "receipts/self-check-result.json": (
        4_400,
        "d6932f607b85dee7b9294e6eceea3c8c86fe603c2b89115732e6d132d0d22e7e",
    ),
    "receipts/final-index.json": (
        2_000,
        "d13dd343c9aec55a93bab0e795780bf0e851269c9bf5f6ce4d3725ee8d7e06fc",
    ),
    "receipts/successor-preparation-v39-result.json": (
        23_849,
        "314a857182f9238219bb28d1ba03c7f84344883264518205241d6190bc692667",
    ),
}
V39_CANDIDATE_FILES = {
    "successor-receipts/successor-v39-controller-acceptance-offer.json": (
        5_031,
        "5d7eb88ee075a4d5945443a4d8801bc4707868c3cd27ea9e87921b74fc80df08",
    ),
    "successor-receipts/successor-v39-controller-acceptance-transport.json": (
        1_383,
        "6e37cf4d3f37d4c848c6f52dd5690b6bae145ce44fe7c8ed235657469073ad5e",
    ),
    "successor-receipts/postacceptance-repository-manifest.jsonl": (
        6_139_908,
        "86ed1804a7b9373e9547f985dbd71136d70787dcad229e3b475de277c97bb6bc",
    ),
    "successor-receipts/postacceptance-attempt-manifest.jsonl": (
        12_177_741,
        "115cd285478ced736b3af391e15f39947bd171786e18dc42c89313ac8ec5bdb7",
    ),
    "successor-receipts/postacceptance-final-index.json": (
        2_730,
        "a3b5ae0908569c996ac3b59957125b1647c2e8f9cd8595035a4d95d78cba4db6",
    ),
    "successor-receipts/successor-v39-policy-snapshot.json": (
        4_827,
        "640ac9e38423a7025ebb3575d90bed38db26e65a128c0143ed97af9dfc8ae392",
    ),
    "successor-receipts/successor-v39-toolchain-snapshot.json": (
        4_878,
        "507ebda410f62b19b3c2ba3d567d5347775c3cee7b8f9eafb2323d3e2e86f45a",
    ),
    "successor-receipts/successor-v39-trusted-context.json": (
        4_051,
        "46151d7fe93e5676c91221a8cafc95d64fae175c247439a6f010cb91f5c8c872",
    ),
    "repo/.loop/trusted/final-controller-acceptance-v39.json": (
        3_912,
        "fe6405636b4fa359c1e3ade43f0821a80cf636128a0f9726bdd4825f941f5c56",
    ),
    (
        "repo/config/loop-engineering/trusted-context/"
        "liveclip-agent-runtime-v2-successor-v1.json"
    ): (
        3_333,
        "2c50eb5ff5b3f93dc70780c17d4f6217ff3d12b9002e4ca409d18a040b24daab",
    ),
}
V39_CLOSURE = {
    "architecture_html": {
        "path": str(ARCHITECTURE),
        "sha256": ARCHITECTURE_SHA256,
        "size": ARCHITECTURE_SIZE,
    },
    "budgets": {
        "accept_final": "CONSUMED_NO_REUSE",
        "auth": "CONSUMED_NO_REUSE",
        "formal": "CONSUMED_STOPPED_NO_REUSE",
        "init": "CONSUMED_NO_REUSE",
        "prepare_result": "CONSUMED_NO_REUSE",
        "publication": "UNAUTHORIZED",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "CONSUMED_NO_REUSE",
        "verify_prepare": "CONSUMED_NO_REUSE",
    },
    "candidate": {
        "current_sanitized_tree": {
            "path_count": 56_251,
            "regular_file_bytes": 1_143_615_319,
            "sha256": "b1506798b693d79b61d3e1c55bd525d84fec54e09d793d910b65e3b2342d3d1c",
            "protected_credential_paths_omitted": 1,
        },
        "final_provenance_tree": {
            "path_count": 44_326,
            "regular_file_bytes": 967_213_201,
            "sha256": "c74a87299cdd78549769ba7a0f0490e1ebcd0d63a3a768c45debcde991cabbce",
        },
        "name": "candidate.oivrdV6U",
        "run_id": V39_RUN_ID,
    },
    "candidate_count": 23,
    "documents": {
        "formal_dispatch": {
            "execplan": {
                "sha256": "5ff63e98dbd959b42fb7babaef67a36b947a53ceabdc058db18ca04da1aa67c3",
                "size": 7_117_047,
            },
            "status": {
                "sha256": "c46663ab19976a0df2b476aab4ca8407feee58d0a3c49f0d2a26e036d1d97277",
                "size": 166_691,
            },
        },
        "v40_recovery_design": {
            "execplan": {
                "sha256": "17a097998140b413b28300f58b756ac64d7f4be628c48103187b289a96e3c6ff",
                "size": 7_127_127,
            },
            "requirement": {
                "sha256": RECOVERY_REQUIREMENT_SHA256,
                "size": RECOVERY_REQUIREMENT_SIZE,
            },
            "status": {
                "sha256": "5877740291932b6b1e844822835fba56ee64cea96640672a6b2cdf4db80d72dc",
                "size": 170_324,
            },
        },
    },
    "formal": {
        "coder_artifact_sha256": "53e325e8ef39291201051a03a8dedccea2b7b8c65165495ac287d9e4a421e945",
        "coder_session_id": "01a13c35-37c9-7493-821a-6cefd8ed7513",
        "events_sha256": "b9abfe8299d47328ca50638515f857115d6166a8b80ee8113a341007a0b12603",
        "planner_artifact_sha256": "39133d5beb3b72e22f4d2e96e9f3100a2bcbf4a27eef83195b738f582549c8c2",
        "run_id": V39_RUN_ID,
        "state_sha256": "78b8133ace2dbf2b9237465028245ab4e953fc4631c9c21f8f87f274af45d47d",
    },
    "formal_process": {
        "elapsed_seconds": 333.223254791,
        "exit": 2,
        "launch_chunk": "60025d",
        "session": 32807,
        "terminal_chunk": "02b218",
        "timed_out": False,
        "truncated": False,
    },
    "inventory": {
        "candidate": {"modified_tracked": 15, "ordinary_untracked": 73, "staged": 0},
        "formal_stop_delivery": {"modified_tracked": 15, "ordinary_untracked": 167, "staged": 0},
        "recovery_design_delivery": {"modified_tracked": 15, "ordinary_untracked": 168, "staged": 0},
        "v40_source_freeze_delivery": {"modified_tracked": 15, "ordinary_untracked": 169, "staged": 0},
    },
    "preparation": {
        "candidate_count_after": 23,
        "completed_tree_sha256": "0c6bdcf0df5bcc095a4bc8ff4c5dba5d8dcf939dde308b8cacc9831dbbeeee73",
        "output_sha256": "22f442e87a366331ce937d66132b3706bec4c18d072e76edcdb26e0fb0ddfdcb",
        "output_size": 20_476,
        "result_sha256": "314a857182f9238219bb28d1ba03c7f84344883264518205241d6190bc692667",
        "result_size": 23_849,
        "returncode": 0,
        "verdict": "M3_SUCCESSOR_PREPARATION_V39_AWAITING_CONTROLLER_ACCEPTANCE",
    },
    "root": str(V39_ROOT),
    "root_files": {
        name: {"sha256": digest, "size": size}
        for name, (size, digest) in V39_ROOT_FILES.items()
    },
    "root_prepare_argv_json_sha256": "9f0e085167d9eff3a844bd9c69317dbe65ce7bbe370e12c3684fb2a24c747b06",
    "root_verdict": "M3S_V39_READY_FOR_CONTROLLER_REVIEW",
    "sanitized_auth_result": {
        "path": str(
            BASE
            / "trusted-tools/m3-authentication-handoff-v2/receipts/"
            "auth-handoff-v2-result.json"
        ),
        "sha256": "e7da30b99e7983e6984c22a22a5d084d622a7eb2279ed417a88ac461410f5c1a",
        "size": 261,
    },
    "verify_prepare": {
        "gate_count": 62,
        "result": "PASS",
        "session": 25_851,
        "stdout_sha256": "efa65881acb2bd1e7fbb1167a019f60956f5668b61489349a02bd4b7c1057ecb",
        "stdout_size": 5_104,
    },
}


class FreezeError(RuntimeError):
    """Fail-closed V40 design or construction error."""


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
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    chunks: list[bytes] = []
    try:
        opened = os.fstat(descriptor)
        require(
            (opened.st_dev, opened.st_ino, opened.st_size)
            == (before.st_dev, before.st_ino, before.st_size),
            f"opened identity mismatch: {path}",
        )
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final = os.fstat(descriptor)
        require(
            (final.st_dev, final.st_ino, final.st_size)
            == (opened.st_dev, opened.st_ino, opened.st_size),
            f"read identity changed: {path}",
        )
    finally:
        os.close(descriptor)
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


def literal_assignment(payload: bytes, name: str) -> Any:
    tree = ast.parse(payload, filename="<m3s-v40-literal>")
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
    tree = ast.parse(text, filename="<m3s-v40-assignment>")
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


def replace_function(text: str, name: str, replacement: str) -> str:
    tree = ast.parse(text, filename="<m3s-v40-function>")
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(nodes) == 1, f"function replacement mismatch: {name}")
    node = nodes[0]
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1])
    end = sum(len(line) for line in lines[: node.end_lineno])
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def extract_source(plan_bytes: bytes) -> bytes:
    require(
        plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1,
        "source marker mismatch",
    )
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def _recovery_validator_source() -> str:
    return '''
def validate_v40_recovery_contract() -> dict[str, Any]:
    requirement = require_identity(
        RECOVERY_REQUIREMENT_PATH,
        RECOVERY_REQUIREMENT_IDENTITY["sha256"],
        0o644,
        RECOVERY_REQUIREMENT_IDENTITY["size"],
    )
    payload, _ = read_regular(RECOVERY_REQUIREMENT_PATH)
    text = payload.decode("utf-8")
    heading = "## Exact Coder allowlist\\n"
    require(text.count(heading) == 1, "recovery allowlist heading mismatch")
    start = text.index("```text\\n", text.index(heading)) + len("```text\\n")
    finish = text.index("```", start)
    observed = tuple(line for line in text[start:finish].splitlines() if line)
    require(observed == RECOVERY_CODER_ALLOWLIST, "recovery allowlist mismatch")
    identities = {
        relative: require_identity(ORIGINAL / relative, value["sha256"], 0o644, value["size"])
        for relative, value in RECOVERY_SOURCE_PREIMAGES.items()
    }
    secure_payload, _ = read_regular(ORIGINAL / "src/liveclip/media/secure_files.py")
    tree = ast.parse(secure_payload, filename="<secure-files-preimage>")
    scanners = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_scan_regular_directory_tree"]
    require(len(scanners) == 1, "secure scanner function mismatch")
    scanner = scanners[0]
    tuple_iterator = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "tuple" and node.args
        and isinstance(node.args[0], ast.Name) and node.args[0].id == "iterator"
        for node in ast.walk(scanner)
    )
    recursive = any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_scan_regular_directory_tree"
        for node in ast.walk(scanner)
    )
    require(tuple_iterator and recursive, "secure scanner defect preimage mismatch")
    fixtures = {
        "exact_accept": observed == RECOVERY_CODER_ALLOWLIST,
        "omission_reject": observed[:-1] != RECOVERY_CODER_ALLOWLIST,
        "substitution_reject": (*observed[:-1], "tests/unit/substitute.py") != RECOVERY_CODER_ALLOWLIST,
        "extra_reject": (*observed, "tests/unit/extra.py") != RECOVERY_CODER_ALLOWLIST,
    }
    require(all(fixtures.values()), "recovery allowlist fixture mismatch")
    return {"fixtures": fixtures, "identities": identities, "requirement": requirement, "result": "PASS"}


def validate_m3s_v39_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V39_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V39 root entries mismatch")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V39 private directory drift")
    expected_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_receipts, "V39 root receipt set mismatch")
    root_files = {
        name: require_identity(root / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["root_files"].items()
    }
    result, _ = load_json(root / "receipts/successor-preparation-v39-result.json")
    prepare = closure["preparation"]
    require(
        result["phase"] == "M3_SUCCESSOR_PREPARATION_V39"
        and result["returncode"] == prepare["returncode"]
        and result["timed_out"] is False
        and result["output_truncated"] is False
        and result["wrapper_error"] is None
        and result["session_id"] is None
        and result["credential_variables"] == [],
        "V39 preparation result mismatch",
    )
    output = result["output"].encode("utf-8")
    require((len(output), sha(output)) == (prepare["output_size"], prepare["output_sha256"]), "V39 output mismatch")
    terminal = json.loads(result["output"])
    require(
        terminal["candidate"] == str(BASE / closure["candidate"]["name"])
        and terminal["result"]["verdict"] == prepare["verdict"]
        and terminal["result"]["sealing_complete"] is True
        and terminal["result"]["sealing_outcomes"]["completed-attempt-tree"]["sha256"] == prepare["completed_tree_sha256"],
        "V39 preparation terminal mismatch",
    )
    candidate = BASE / closure["candidate"]["name"]
    private_directory_identity(candidate)
    require(set(os.listdir(candidate)) == {"home", "repo", "successor-receipts", "tmp"}, "V39 candidate entries mismatch")
    candidate_files = {
        name: require_identity(candidate / name, value["sha256"], 0o600, value["size"])
        for name, value in V39_ACCEPTED_CANDIDATE_FILES.items()
    }
    run = candidate / "repo/.loop/runs" / closure["candidate"]["run_id"]
    state, state_identity = load_json(run / "state.json")
    events = require_identity(run / "events.jsonl", closure["formal"]["events_sha256"], 0o644, 4224)
    planner = require_identity(run / "artifacts/planner/001.json", closure["formal"]["planner_artifact_sha256"], 0o644, 11291)
    coder = require_identity(run / "artifacts/coder/001.json", closure["formal"]["coder_artifact_sha256"], 0o644, 2691)
    require(
        state_identity["sha256"] == closure["formal"]["state_sha256"]
        and state["state"] == "blocked"
        and state["cycle"] == 1 and state["code_cycle"] == 1
        and state["coder_session_id"] == closure["formal"]["coder_session_id"]
        and state["command_results"] == []
        and set(state["artifacts"]) == {"planner", "coder"},
        "V39 formal state mismatch",
    )
    require(set(os.listdir(run / "artifacts")) == {"planner", "coder"}, "V39 later-role evidence appeared")
    sanitized = closure["sanitized_auth_result"]
    sanitized_identity = require_identity(Path(sanitized["path"]), sanitized["sha256"], 0o600, sanitized["size"])
    for name in ("final-controller-acceptance-v39-result.json", "auth-handoff-v39-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V39 reserved root result appeared")
    require(closure["candidate_count"] == 23, "V39 recorded candidate count mismatch")
    require(all(value.startswith("CONSUMED") for key, value in closure["budgets"].items() if key != "publication"), "V39 consumed budget mismatch")
    return {
        "candidate_files": candidate_files, "coder": coder, "events": events,
        "planner": planner, "root_files": root_files,
        "sanitized_auth_result": sanitized_identity, "state": state_identity,
        "result": "PASS",
    }
'''


def derive_driver(v39_bytes: bytes) -> bytes:
    """Derive V40 deterministically and only from sealed V39 bytes."""

    require((len(v39_bytes), sha256(v39_bytes)) == (V39_DRIVER_SIZE, V39_DRIVER_SHA256), "sealed V39 driver mismatch")
    original_v38 = literal_assignment(v39_bytes, "PREVIOUS_M3S_V38_CLOSURE")
    text = v39_bytes.decode("utf-8")
    upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    lower = "liveclip_future_version_lower"
    require(upper not in text and lower not in text, "version sentinel collision")
    text = text.replace("V40", upper).replace("v40", lower)
    text = text.replace("V39", "V40").replace("v39", "v40")
    text = text.replace(upper, "V41").replace(lower, "v41")
    text = replace_once(
        text,
        'current_result_name = "successor-preparation-v" + "39-result.json"',
        'current_result_name = "successor-preparation-v" + "40-result.json"',
        "current result fixture",
    )
    text = replace_once(
        text,
        'future_result_name = "successor-preparation-v" + "40-result.json"',
        'future_result_name = "successor-preparation-v" + "41-result.json"',
        "future result fixture",
    )
    text = replace_assignment(text, "PREVIOUS_M3S_V38_CLOSURE", original_v38)
    text = replace_once(text, "range(40, 55)", "range(41, 55)", "future phase range")
    text = replace_once(text, '"040-result.json"', '"041-result.json"', "future substitution")
    text = replace_once(
        text,
        "RuntimeError: future V40 result fixture mismatch",
        "RuntimeError: future V39 result fixture mismatch",
        "immutable historical V32 negative",
    )
    text = replace_once(text, '"ordinary_untracked": 166', '"ordinary_untracked": 169', "final inventory")
    text = text.replace(
        "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md",
        "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md",
    )
    text = text.replace(
        "liveclip-agent-runtime-v2-acceptance-v2.md",
        "liveclip-agent-runtime-v2-acceptance-v3.md",
    )
    text = replace_assignment(text, "SUCCESSOR_REQUIREMENT_SHA", RECOVERY_REQUIREMENT_SHA256)
    text = replace_once(text, "        8771,\n", "        12289,\n", "successor requirement size")
    text = text.replace(
        "liveclip-agent-runtime-v2-successor-v1.json",
        "liveclip-agent-runtime-v2-successor-v2.json",
    )
    text = replace_once(
        text,
        'SCHEMA_SEED = ORIGINAL / "config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v2.json"',
        'SCHEMA_SEED = ORIGINAL / "config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v1.json"',
        "schema seed remains v1",
    )
    text = text.replace(
        "liveclip_m3_successor_trusted_context_v1",
        "liveclip_m3_successor_trusted_context_v2",
    )
    text = replace_once(
        text,
        'PREDECESSORS["candidate.vuDWtK0T"] = (44322, 948848595, "86c961b967d997e7fa21810b8b6e4ab0ca81223a72eea2b14043008adf28bd16", "9538aca6435d95b1ca0ee86119040f5b02b144a54c7ad6d3e47256c23a3ddb57")',
        'PREDECESSORS["candidate.vuDWtK0T"] = (44322, 948848595, "86c961b967d997e7fa21810b8b6e4ab0ca81223a72eea2b14043008adf28bd16", "9538aca6435d95b1ca0ee86119040f5b02b144a54c7ad6d3e47256c23a3ddb57")\n'
        'PREDECESSORS["candidate.oivrdV6U"] = (56251, 1143615319, "b1506798b693d79b61d3e1c55bd525d84fec54e09d793d910b65e3b2342d3d1c", "115cd285478ced736b3af391e15f39947bd171786e18dc42c89313ac8ec5bdb7")',
        "V39 predecessor insertion",
    )
    text = replace_once(
        text,
        'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.vuDWtK0T"] = 0',
        'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.vuDWtK0T"] = 0\n'
        'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.oivrdV6U"] = 1',
        "V39 protected omission insertion",
    )
    text = replace_assignment(
        text,
        "SANITIZED_PROTECTED_PREDECESSOR_BASELINES",
        {
            "candidate.KWbe2iGW": (44_411, 949_916_895, "9f1a29d17baadad816fae6ba5916311b22629a84e4e55449423bf3d852022ff4"),
            "candidate.oivrdV6U": (56_251, 1_143_615_319, "b1506798b693d79b61d3e1c55bd525d84fec54e09d793d910b65e3b2342d3d1c"),
        },
    )
    text = replace_once(
        text,
        'sum(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS.values()) == 1 and PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.KWbe2iGW"] == 1',
        'sum(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS.values()) == 2 and PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.KWbe2iGW"] == 1 and PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.oivrdV6U"] == 1',
        "credential omission count",
    )
    text = replace_once(
        text,
        'set(SANITIZED_PROTECTED_PREDECESSOR_BASELINES) == {"candidate.KWbe2iGW"}',
        'set(SANITIZED_PROTECTED_PREDECESSOR_BASELINES) == {"candidate.KWbe2iGW", "candidate.oivrdV6U"}',
        "sanitized baseline domain",
    )
    text = replace_once(
        text,
        'require(PREDECESSORS["candidate.KWbe2iGW"][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES["candidate.KWbe2iGW"], "sanitized predecessor baseline mismatch")',
        'require(PREDECESSORS["candidate.KWbe2iGW"][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES["candidate.KWbe2iGW"], "sanitized predecessor baseline mismatch")\n'
        '    require(PREDECESSORS["candidate.oivrdV6U"][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES["candidate.oivrdV6U"], "V39 sanitized predecessor baseline mismatch")',
        "V39 sanitized baseline fixture",
    )
    text = replace_once(
        text,
        '"protected_path_count": 1, "sanitized_baseline_count": 1',
        '"protected_path_count": 1, "sanitized_baseline_count": 2',
        "sanitized fixture counts",
    )
    injected = (
        f"PREVIOUS_M3S_V39_CLOSURE = {V39_CLOSURE!r}\n\n"
        f"RECOVERY_REQUIREMENT_PATH = Path({str(RECOVERY_REQUIREMENT)!r})\n"
        f"RECOVERY_REQUIREMENT_IDENTITY = {{'size': {RECOVERY_REQUIREMENT_SIZE}, 'sha256': {RECOVERY_REQUIREMENT_SHA256!r}}}\n"
        f"RECOVERY_CODER_ALLOWLIST = {RECOVERY_ALLOWLIST!r}\n"
        f"RECOVERY_SOURCE_PREIMAGES = {SOURCE_PREIMAGES!r}\n"
        f"V39_ACCEPTED_CANDIDATE_FILES = {{name: {{'size': size, 'sha256': digest}} for name, (size, digest) in {V39_CANDIDATE_FILES!r}.items()}}\n\n"
    )
    text = replace_once(text, "CONTROLLER_ROOT_BINDING =", injected + "CONTROLLER_ROOT_BINDING =", "V39 closure insertion")
    text = replace_once(
        text,
        '''        "blocked_predecessor": {
            "coder_artifact_sha256": BLOCKED_CODER_SHA,
            "coder_event_log_sha256": BLOCKED_CODER_EVENTS_SHA,
            "coder_session_id": BLOCKED_CODER_SESSION,
            "events_sha256": BLOCKED_EVENTS_SHA,
            "planner_artifact_sha256": BLOCKED_PLANNER_SHA,
            "planner_session_id": BLOCKED_PLANNER_SESSION,
            "run_id": BLOCKED_RUN_ID,
            "state_sha256": BLOCKED_STATE_SHA,
        },''',
        '        "blocked_predecessor": PREVIOUS_M3S_V39_CLOSURE["formal"],',
        "trusted-context V39 predecessor",
    )
    text = replace_once(
        text,
        'value["run"]["run_id"] == run_id and run_id != BLOCKED_RUN_ID',
        'value["run"]["run_id"] == run_id and run_id not in (BLOCKED_RUN_ID, PREVIOUS_M3S_V39_CLOSURE["formal"]["run_id"])',
        "retained run exclusion",
    )
    text = replace_once(
        text,
        'value["blocked_predecessor"]["state_sha256"] == BLOCKED_STATE_SHA',
        'canonical_json_model(value["blocked_predecessor"]) == canonical_json_model(PREVIOUS_M3S_V39_CLOSURE["formal"])',
        "trusted-context V39 semantic",
    )
    text = replace_once(
        text,
        '        "blocked_run_id_reject": rejected(',
        '        "retained_v39_run_id_reject": rejected(\n'
        '            lambda item: item["run"].__setitem__(\n'
        '                "run_id",\n'
        '                PREVIOUS_M3S_V39_CLOSURE["formal"]["run_id"],\n'
        '            )\n'
        '        ),\n'
        '        "blocked_run_id_reject": rejected(',
        "retained V39 run fixture",
    )
    text = replace_function(
        text,
        "controller_acceptance_semantic_violations",
        '''def controller_acceptance_semantic_violations(value: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V39_CLOSURE):
        violations.append("predecessor_closure")
    if value.get("root") != CONTROLLER_ROOT_BINDING:
        violations.append("root")
    return violations''',
    )
    text = replace_once(
        text,
        "\ndef validate_m3s_v38_stale() -> dict[str, Any]:",
        _recovery_validator_source() + "\n\ndef validate_m3s_v38_stale() -> dict[str, Any]:",
        "V40 recovery validators",
    )
    text = replace_once(
        text,
        '        "architecture_html": validate_architecture_html(),',
        '        "architecture_html": validate_architecture_html(),\n'
        '        "v40_recovery_contract": validate_v40_recovery_contract(),',
        "recovery gate insertion",
    )
    text = replace_once(
        text,
        '        "m3s_v38_stale": validate_m3s_v38_stale(),',
        '        "m3s_v39_stopped": validate_m3s_v39_stopped(),\n'
        '        "m3s_v38_stale": validate_m3s_v38_stale(),',
        "V39 closure gate insertion",
    )
    payload = text.encode("utf-8")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    predecessors = sorted(EXPECTED_CANDIDATES, key=os.fsencode)
    contracts["candidate_allocation"].update({
        "expected_predecessors": predecessors,
        "predecessor_count": 23,
    })
    contracts["candidate_allocation"]["candidate_set_contract"].update({
        "preallocation": "exact 23 immutable predecessor names",
        "postallocation": "exact 23 predecessors plus one unpredictable current candidate",
    })
    contracts["initial_run"]["argv"] = [
        "/usr/bin/make", "loop-init",
        "REQUIREMENT=docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md",
    ]
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = (
        "checked-in-loop-engineering-policy-plus-independent-document-generations-"
        "v40-bounded-tree-recovery-relational-toolchain-final-external-acceptance"
    )
    policy["pre_root_full_audit"] = {
        "allocation": False,
        "gate_count": 64,
        "home": str(V39_ROOT / "home"),
        "include_process_gate": True,
        "no_write_snapshot": True,
        "tmp": str(V39_ROOT / "tmp"),
    }
    policy["controller_acceptance_semantics"] = {
        "model": "controller_acceptance_semantic_violations",
        "predecessor": "PREVIOUS_M3S_V39_CLOSURE",
        "rejects": ["V38", "missing", "mutated_v39", "extra_v39", "wrong_root"],
    }
    policy["bounded_tree_recovery"] = {
        "coder_allowlist": list(RECOVERY_ALLOWLIST),
        "coder_allowlist_count": 13,
        "requirement": {
            "path": str(RECOVERY_REQUIREMENT),
            "sha256": RECOVERY_REQUIREMENT_SHA256,
            "size": RECOVERY_REQUIREMENT_SIZE,
        },
        "source_preimages": SOURCE_PREIMAGES,
        "terminal_predecessor": "PREVIOUS_M3S_V39_CLOSURE",
    }
    policy["historical_candidate_counts"]["recorded_counts"]["V39"] = 23
    policy["historical_candidate_counts"]["current_live_total_not_consulted"].append("V39")
    trusted = contracts["trusted_context"]
    trusted["context_path"] = (
        "config/loop-engineering/trusted-context/"
        "liveclip-agent-runtime-v2-successor-v2.json"
    )
    trusted["immediate_predecessor"] = {
        "candidate": "candidate.oivrdV6U",
        "closure": "PREVIOUS_M3S_V39_CLOSURE",
        "formal": "CONSUMED_STOPPED_NO_REUSE",
        "prepare": "CONSUMED_ACCEPTED_NO_REUSE",
        "root": str(V39_ROOT),
        "run_id": V39_RUN_ID,
    }
    trusted["immediate_predecessor_design"] = {
        "closure": "PREVIOUS_M3S_V39_CLOSURE",
        "root": str(V39_ROOT),
        "state": "TERMINAL_FORMAL_STOP_NO_REUSE",
    }
    trusted["recovery_requirement"] = {
        "path": "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md",
        "sha256": RECOVERY_REQUIREMENT_SHA256,
        "trusted_record_version": 2,
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
    tree = ast.parse(text, filename="<m3s-v40-driver>")
    compile(tree, "<m3s-v40-driver>", "exec")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = function_node(tree, "read_only_gates")
    returns = [node for node in ast.walk(gate) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    require(len(returns) == 1 and len(returns[0].value.keys) == 64, "gate count mismatch")
    execute_node = function_node(tree, "execute")
    mktemp = [
        node for node in ast.walk(execute_node)
        if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "/usr/bin/mktemp"
    ]
    initializers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "initialize_and_bind_successor"
    ]
    require(len(initializers) == 2, "successor initializer count mismatch")
    loop_init = [
        node for initializer in initializers
        for node in ast.walk(initializer)
        if isinstance(node, ast.List) and len(node.elts) >= 2
        and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make"
        and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"
    ]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(
        b'current_result_name = "successor-preparation-v" + "40-result.json"' in payload
        and b'future_result_name = "successor-preparation-v" + "41-result.json"' in payload,
        "current/future result mismatch",
    )
    require(
        b"liveclip-agent-runtime-v2-acceptance-v3.md" in payload
        and b"liveclip-agent-runtime-v2-successor-v2.json" in payload,
        "V40 requirement/trusted-context binding missing",
    )
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v40_static"}
    exec(compile(tree, "<m3s-v40-static>", "exec"), namespace)  # noqa: S102
    require(
        {name: len(shape) for name, shape in namespace["SHAPES"].items()}
        == {"prepare": 23, "verify-prepare": 23, "accept-final": 15},
        "command surface mismatch",
    )
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(all(candidate_cases.values()) and all(context_cases.values()), "driver fixture failed")
    require(credential_cases["sanitized_baseline_count"] == 2, "credential fixture failed")
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    return {
        "ast_compile": "PASS",
        "candidate_set_cases": candidate_cases,
        "command_surface": {name: len(shape) for name, shape in namespace["SHAPES"].items()},
        "context_cases": context_cases,
        "contracts": hashes,
        "credential_policy": credential_cases,
        "gate_count": 64,
        "one_loop_init": True,
        "one_mktemp": True,
        "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"},
        "result": "PASS",
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
        "phase": "M3S_V40_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V39_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "recovery_requirement": {
                "path": str(RECOVERY_REQUIREMENT),
                "sha256": RECOVERY_REQUIREMENT_SHA256,
                "size": RECOVERY_REQUIREMENT_SIZE,
            },
            "sealed_v39_driver": {"path": str(V39_DRIVER), "sha256": V39_DRIVER_SHA256, "size": V39_DRIVER_SIZE},
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


def git_status_bytes(repo: Path = DELIVERY) -> bytes:
    result = subprocess.run(  # noqa: S603
        ["/usr/bin/git", "status", "--short", "--untracked-files=all"],
        cwd=repo,
        env={"PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
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


def audit_snapshot(plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    candidates = tuple(sorted(
        (entry.name for entry in os.scandir(BASE) if entry.is_dir(follow_symlinks=False) and entry.name.startswith("candidate.")),
        key=os.fsencode,
    ))
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    counts = status_counts(git_status_bytes())
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 169}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    requirement = require_file(
        RECOVERY_REQUIREMENT, RECOVERY_REQUIREMENT_SIZE, RECOVERY_REQUIREMENT_SHA256
    )
    require(not ROOT.exists() and not ROOT.is_symlink(), "V40 root appeared")
    return {
        "architecture": architecture,
        "candidates_sha256": sha256(compact(candidates)),
        "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)},
        "git_status_sha256": sha256(git_status_bytes()),
        "inventory": counts,
        "requirement": requirement,
        "v40_root_absent": True,
    }


def full_pre_root_audit(
    driver_bytes: bytes,
    acceptance: bytes,
    plan_bytes: bytes,
    status_bytes: bytes,
) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v40-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v40_audit"}
    exec(compile(tree, "<m3s-v40-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V39 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (
        ("v38_substitution", namespace["PREVIOUS_M3S_V38_CLOSURE"]),
        ("missing", {}),
    ):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["formal"]["state_sha256"] = "0" * 64
    negatives["mutated_v39"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v39"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 39}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(
        all(negatives[name] == ["predecessor_closure"] for name in ("v38_substitution", "missing", "mutated_v39", "extra_v39"))
        and negatives["wrong_root"] == ["root"],
        "V39 acceptance negative accepted",
    )
    values = {
        "base": str(BASE),
        "seed": str(SEED),
        "plan": str(PLAN),
        "expected_plan_sha256": sha256(plan_bytes),
        "status": str(STATUS),
        "expected_status_sha256": sha256(status_bytes),
    }
    saved_environment = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](
            values,
            V39_ROOT / "home",
            V39_ROOT / "tmp",
            include_process_gate=True,
        )
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 64, "full pre-root gate count mismatch")
    require(gates["v40_recovery_contract"]["result"] == "PASS", "recovery gate failed")
    require(gates["m3s_v39_stopped"]["result"] == "PASS", "V39 closure gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION", "preallocation state mismatch")
    require(len(gates["predecessors"]["candidate_names"]) == 23, "preallocation candidate count mismatch")
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
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            require(written > 0, f"short write: {path}")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o600, f"written mode mismatch: {path}")
    finally:
        os.close(descriptor)
    reread, info = read_regular(path)
    require(reread == payload, f"written bytes mismatch: {path}")
    return {"mode": "0600", "owner_uid": info.st_uid, "path": str(path), "sha256": sha256(payload), "size": len(payload)}


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
    require(extract_source(plan_bytes) == source_bytes, "embedded source mismatch")
    v39_bytes, _ = read_regular(V39_DRIVER)
    driver_bytes = derive_driver(v39_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(
        driver_bytes,
        plan_bytes=plan_bytes,
        status_bytes=status_bytes,
        source_bytes=source_bytes,
        helper_bytes=helper_bytes,
    )
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V40 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v40.json", acceptance)
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V40_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n",
    )
    writer_receipt = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        compact({"format_version": 1, "phase": "M3S_V40_WRITER_SELF_TEST", "result": "PASS"}) + b"\n",
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        compact({"audit": audit, "format_version": 1, "phase": "M3S_V40_SELF_CHECK", "result": "PASS", "static": static}) + b"\n",
    )
    final_value = {
        "controller_acceptance": acceptance_identity,
        "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256},
        "driver": driver_identity,
        "format_version": 1,
        "phase": "M3S_V40_FINAL_INDEX",
        "root_prepare_argv_json_sha256": sha256(root_argv_json),
        "source_receipt": source_receipt,
        "self_check": self_check,
        "verdict": "M3S_V40_READY_FOR_CONTROLLER_REVIEW",
        "writer_self_test": writer_receipt,
    }
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V40_ROOT_ONLY", "result": "M3S_V40_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
