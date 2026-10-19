"""Deterministic M3S-v41 source-freeze and root-only helper.

This Trusted-Main-only helper derives V41 from the immutable sealed V40
driver.  It repairs the missing acceptance-v2 source transport, binds the
retained V40 formal stop, executes the complete allocation-free pre-root gate
graph, and may create only the fixed V41 root.  Importing it is read-only.
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
REQUIREMENT_V2 = DELIVERY / "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md"
REQUIREMENT_V3 = DELIVERY / "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md"
SEED = BASE / "candidate.OlsWg1/repo"
V40_ROOT = BASE / "trusted-tools/m3-successor-preparation-v40"
V40_DRIVER = V40_ROOT / "candidate-driver.py"
V40_CANDIDATE = BASE / "candidate.M4v94Rmv"
V40_RUN_ID = "20261014T214746Z-cd5796b8"
V40_RUN = V40_CANDIDATE / "repo/.loop/runs" / V40_RUN_ID
ROOT = BASE / "trusted-tools/m3-successor-preparation-v41"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v41_source_freeze.py"
LEGACY_HELPER = DELIVERY / "tools/loop_engineering/m3s_v40_source_freeze.py"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V41_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V41_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
V40_DRIVER_SIZE = 468_657
V40_DRIVER_SHA256 = "4b2e438f652998fc36cae9590ecf17b08d6e245433cdf5eab9480b5ddc1fafc2"
LEGACY_HELPER_SIZE = 52_494
LEGACY_HELPER_SHA256 = "227a27e6adc77357e829caaa0ed617c941c7aa39e70cd96dbd0d1dfa93cb1dfe"
ARCHITECTURE_SIZE = 66_116
ARCHITECTURE_SHA256 = "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce"
REQUIREMENT_V2_SIZE = 8_771
REQUIREMENT_V2_SHA256 = "31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400"
REQUIREMENT_V3_SIZE = 12_289
REQUIREMENT_V3_SHA256 = "308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00"
EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO", "candidate.3WBt3ldA", "candidate.5jh3bylk",
    "candidate.5nZWpynN", "candidate.KWbe2iGW", "candidate.M4v94Rmv",
    "candidate.OlsWg1", "candidate.Q2vecg", "candidate.UU7EAiJG",
    "candidate.VoU5SVVl", "candidate.aw2oA4", "candidate.bSEqMEit",
    "candidate.c79YYSLQ", "candidate.cQnaAbOf", "candidate.dygENR4n",
    "candidate.iyme1x_i", "candidate.jyq_n37h", "candidate.mRMO7MQ6",
    "candidate.o99gfxup", "candidate.oivrdV6U", "candidate.qaDKDWkQ",
    "candidate.vuDWtK0T", "candidate.xp23hqNY", "candidate.z6EbTJew",
)

V40_ROOT_FILES = {
    "candidate-driver.py": (468_657, V40_DRIVER_SHA256),
    "receipts/controller-acceptance-v40.json": (14_519, "89b2ebbc6d18cc24bab47c72bf5e9499c1e47da22fd648ef5e563ee1c461e7c5"),
    "receipts/source-receipt.json": (524, "8de386e0c256635505bb41c8b3c1855db8744fa889d96f6be80b7ad19e916d25"),
    "receipts/writer-self-test.json": (72, "931b38e3d416a90977e891d368b075055925ae6070e732e3d5820ae21f610388"),
    "receipts/self-check-result.json": (5_173, "fdcd6049a7f6dad74eb7f6522ad8b2c1c20fb18368024af8ef9a04e5c8c1feaa"),
    "receipts/final-index.json": (2_000, "9d623cd3b398010a279cb424a93cbee91e99e2555ab9307075bd9043c1dd7a7a"),
    "receipts/successor-preparation-v40-result.json": (23_850, "cd13363aee5d6fd069355ff1ee31ac1f3827b2f25bb9a565eebc3bb68b2dd9bf"),
}
V40_CANDIDATE_FILES = {
    "successor-receipts/source-manifest.jsonl": (625_482, "e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044"),
    "successor-receipts/included-untracked.zlist": (3_619, "1cbfb3a787026491c1c979ce3f263adece51af8cc1210c94094dd7bf2ee3cec7"),
    "successor-receipts/source-tracked.patch": (204_622, "472638a7f6c78634d3dbe5508716fc3a1328761dd4047eaf1b20c4d494a01254"),
    "successor-receipts/successor-v40-overlay.json": (1_858, "72fafe4ae1088d614be9fc8b5224c4a68f930c73d76bc8a60096f54b117ce6a7"),
    "successor-receipts/final-receipt-index.json": (18_095, "f31b88a03ec37ada6237eb92817004ad4a39b42ee768da1ad5fb019206bd2a81"),
    "successor-receipts/preservation-receipt.json": (275_705, "41b74996571468d1f5c4047890ee218a3197a39f9cf9b247cfdf4ec4cb60383f"),
    "successor-receipts/successor-v40-controller-acceptance-offer.json": (5_032, "afa8c4b8427193e6efa2ca2c024af22baf35a7f2eab7c8c00ba01ee9393f977c"),
    "successor-receipts/successor-v40-controller-acceptance-transport.json": (1_383, "1651b2c39787898f63a20390f30ac52fae672a3fb691116f44566242b1d15f2d"),
    "successor-receipts/successor-v40-controller-acceptance.json": (891, "422c4b3d036345e2d5151837ad8a2d068aa35952a2e7699bc2b9afb2494a2a25"),
    "successor-receipts/successor-v40-policy-snapshot.json": (4_827, "5a6b03c002f64e01266e94ebc2724e4e625fde7f6a5144e0c1d1e91ac32ca7c1"),
    "successor-receipts/successor-v40-toolchain-snapshot.json": (4_878, "f4e33b7d885e68d62efb0704c6abb47d38d15a396352b187f94ceb2139f91651"),
    "successor-receipts/successor-v40-trusted-context.json": (3_884, "664402f3791b17c88bcd6ea9e4f3cba59eec5e319e11e5514f8717c1fd1f3bca"),
    "successor-receipts/postacceptance-repository-manifest.jsonl": (6_139_910, "20f5cf4e26274de1176aa23a79ee9508396246d18a14a1046bae5918f2e87403"),
    "successor-receipts/postacceptance-attempt-manifest.jsonl": (12_177_744, "d6f9d170fbc6db5ebceaaaa9e6dfc63b838f1d2e46dd77782db4845a87e42c5e"),
    "successor-receipts/postacceptance-final-index.json": (2_731, "2668171e0b0c22f2022793c4413b359b3dd31282bc3fbbe1ac413665a647b7b6"),
    "repo/.loop/trusted/controller-acceptance-v40.json": (14_519, "89b2ebbc6d18cc24bab47c72bf5e9499c1e47da22fd648ef5e563ee1c461e7c5"),
    "repo/.loop/trusted/final-controller-acceptance-v40.json": (3_913, "a44929f89fca9629b06163814c8c1233278f830036c343c52e11fd4b1ea22a3e"),
    "repo/config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v2.json": (3_170, "02377e94ec5468b85f9803b11e53e67a0ef88767ef13ce61563f7a7cb0ab74bc"),
}
V40_FORMAL_FILES = {
    "state.json": (12_992, "ad2ddb96e257db00f419a8a4d6148e54b13df8842062f8ab439c50cc62f8ae9c"),
    "events.jsonl": (2_056, "53917898bb2fecf7f5a3babd430ec18d9ed4236bd9aea28e5e8c3eed8e3f2bfc"),
    "artifacts/planner/001.json": (4_418, "e97a67e300d07fc501e02a343fd4f8ef48f45d03b92af926c3b32f190228a015"),
    "artifacts/planner/002.json": (3_840, "c09ff7eeed6da18e09101cd07b79156a9c64e34f0f29fdc758706228b0a7be69"),
}

V40_CLOSURE = {
    "budgets": {
        "accept_final": "CONSUMED_NO_REUSE",
        "authentication": "CONSUMED_NO_REUSE",
        "formal": "CONSUMED_STOPPED_NO_REUSE",
        "init": "CONSUMED_NO_REUSE",
        "prepare_result": "CONSUMED_NO_REUSE",
        "publication": "UNAUTHORIZED",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "CONSUMED_NO_REUSE",
    },
    "candidate": {
        "name": "candidate.M4v94Rmv",
        "run_id": V40_RUN_ID,
        "current_sanitized_tree": {
            "path_count": 44_420,
            "regular_file_bytes": 968_624_315,
            "sha256": "ea61d5daf2332341515b66f08782d313809bbdbe92b9dded693485003be73b9a",
            "protected_credential_paths_omitted": 1,
        },
        "postacceptance_tree": {
            "path_count": 44_326,
            "regular_file_bytes": 967_345_497,
            "sha256": "894bf7939742cafb4f7ee512bd2ffa4b592a5016a93f3e8288e4adf75251f1ba",
        },
    },
    "candidate_count": 24,
    "documents": {
        "formal_dispatch": {
            "execplan": {"size": 7_210_259, "sha256": "6ac9cbc8634b90d446aad1935e0dd3baeff3eef92c45080dd80b1840bae377a1"},
            "status": {"size": 201_232, "sha256": "3cf9761d66c5cafc3ecf54ebfd82fbbd162d29dd3d524357d467b816c265b1ed"},
        },
        "requirements": {
            "v2": {"size": REQUIREMENT_V2_SIZE, "sha256": REQUIREMENT_V2_SHA256},
            "v3": {"size": REQUIREMENT_V3_SIZE, "sha256": REQUIREMENT_V3_SHA256},
        },
    },
    "formal": {
        "exit": 2,
        "session": 26_870,
        "run_id": V40_RUN_ID,
        "launch_chunk": "d138f9",
        "poll_chunk": "74521f",
        "terminal_chunk": "70e508",
        "observed_wait_seconds": 55.441192876,
        "state": "blocked",
        "cycle": 2,
        "code_cycle": 0,
        "coder_session_id": None,
        "last_error": "plan repair budget exhausted",
        "planner_verdicts": ["NEEDS_INPUT", "NEEDS_INPUT"],
        "missing_requirement": "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md",
    },
    "inventory": {
        "candidate": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 73},
        "delivery_at_stop": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 172},
    },
    "root": str(V40_ROOT),
    "root_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V40_ROOT_FILES.items()},
    "candidate_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V40_CANDIDATE_FILES.items()},
    "formal_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V40_FORMAL_FILES.items()},
    "sanitized_auth_result": {
        "path": str(BASE / "trusted-tools/m3-authentication-handoff-v5/receipts/auth-handoff-v5-result.json"),
        "size": 261,
        "sha256": "24f0729ab014db86903430394aee6927163063f164ab40d5481fc76cb088ece0",
    },
    "source_transport_defect": {
        "authoritative_v2": {"path": str(REQUIREMENT_V2), "size": REQUIREMENT_V2_SIZE, "sha256": REQUIREMENT_V2_SHA256},
        "b2_path_count": 71,
        "v2_in_b2_path_list": False,
        "v2_in_v40_overlay": False,
        "v2_in_postacceptance_repository_manifest": False,
        "v2_in_postacceptance_attempt_manifest": False,
        "v3_requires_v2": True,
    },
}


class FreezeError(RuntimeError):
    """Fail-closed V41 design or construction error."""


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
    return {"mode": f"{mode:04o}", "owner_uid": info.st_uid, "path": str(path), "sha256": digest, "size": size}


def _load_legacy() -> Any:
    payload, _ = read_regular(LEGACY_HELPER)
    require((len(payload), sha256(payload)) == (LEGACY_HELPER_SIZE, LEGACY_HELPER_SHA256), "legacy helper drift")
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v40_freeze", LEGACY_HELPER)
    require(spec is not None and spec.loader is not None, "legacy helper import spec failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _insert_after_assignment(text: str, name: str, addition: str) -> str:
    tree = ast.parse(text, filename="<m3s-v41-insert>")
    matches = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
    ]
    require(len(matches) == 1, f"assignment insertion mismatch: {name}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    end = sum(len(line) for line in lines[: node.end_lineno])
    return text[:end] + addition.rstrip() + "\n" + text[end:]


def _replace_assignment_source(text: str, name: str, source: str) -> str:
    tree = ast.parse(text, filename="<m3s-v41-restore>")
    matches = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
    ]
    require(len(matches) == 1, f"assignment restore mismatch: {name}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    return text[:start] + source + text[end:]


def _function_source() -> dict[str, str]:
    recovery = '''
def validate_v41_recovery_contract() -> dict[str, Any]:
    predecessor = require_identity(RECOVERY_PREDECESSOR_PATH, RECOVERY_PREDECESSOR_IDENTITY["sha256"], 0o644, RECOVERY_PREDECESSOR_IDENTITY["size"])
    requirement = require_identity(RECOVERY_REQUIREMENT_PATH, RECOVERY_REQUIREMENT_IDENTITY["sha256"], 0o644, RECOVERY_REQUIREMENT_IDENTITY["size"])
    payload, _ = read_regular(RECOVERY_REQUIREMENT_PATH)
    text = payload.decode("utf-8")
    require(RECOVERY_PREDECESSOR_IDENTITY["sha256"] in text and "8,771 bytes" in text, "v3 predecessor binding mismatch")
    heading = "## Exact Coder allowlist\\n"
    require(text.count(heading) == 1, "recovery allowlist heading mismatch")
    start = text.index("```text\\n", text.index(heading)) + len("```text\\n")
    finish = text.index("```", start)
    observed = tuple(line for line in text[start:finish].splitlines() if line)
    require(observed == RECOVERY_CODER_ALLOWLIST, "recovery allowlist mismatch")
    identities = {relative: require_identity(ORIGINAL / relative, value["sha256"], 0o644, value["size"]) for relative, value in RECOVERY_SOURCE_PREIMAGES.items()}
    secure_payload, _ = read_regular(ORIGINAL / "src/liveclip/media/secure_files.py")
    tree = ast.parse(secure_payload, filename="<secure-files-preimage>")
    scanners = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_scan_regular_directory_tree"]
    require(len(scanners) == 1, "secure scanner function mismatch")
    scanner = scanners[0]
    tuple_iterator = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tuple" and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "iterator" for node in ast.walk(scanner))
    recursive = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_scan_regular_directory_tree" for node in ast.walk(scanner))
    require(tuple_iterator and recursive, "secure scanner defect preimage mismatch")
    exact = ("docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md", "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md")
    transport = {
        "exact_accept": exact == tuple(SUCCESSOR_REQUIREMENT_PATHS),
        "v2_omission_reject": exact[1:] != tuple(SUCCESSOR_REQUIREMENT_PATHS),
        "v3_omission_reject": exact[:1] != tuple(SUCCESSOR_REQUIREMENT_PATHS),
        "substitution_reject": (exact[0], "docs/requirements/substitute.md") != tuple(SUCCESSOR_REQUIREMENT_PATHS),
        "extra_reject": (*exact, "docs/requirements/extra.md") != tuple(SUCCESSOR_REQUIREMENT_PATHS),
        "v2_hash_drift_reject": RECOVERY_PREDECESSOR_IDENTITY["sha256"] != "0" * 64,
    }
    allowlist = {
        "exact_accept": observed == RECOVERY_CODER_ALLOWLIST,
        "omission_reject": observed[:-1] != RECOVERY_CODER_ALLOWLIST,
        "substitution_reject": (*observed[:-1], "tests/unit/substitute.py") != RECOVERY_CODER_ALLOWLIST,
        "extra_reject": (*observed, "tests/unit/extra.py") != RECOVERY_CODER_ALLOWLIST,
    }
    require(all(transport.values()) and all(allowlist.values()), "recovery fixture mismatch")
    return {"allowlist_fixtures": allowlist, "identities": identities, "predecessor": predecessor, "requirement": requirement, "result": "PASS", "transport_fixtures": transport}
'''
    manifest = '''
def manifest_credential_policy_self_test() -> dict[str, Any]:
    require(is_protected_credential_manifest_path("home/.codex/auth.json"), "protected credential fixture rejected")
    negatives = (".codex/auth.json", "home/.codex/auth.json.bak", "home/.codex/Auth.json", "home/auth.json")
    require(not any(is_protected_credential_manifest_path(item) for item in negatives), "credential near-match fixture accepted")
    require(set(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS) == set(PREDECESSORS), "credential omission predecessor domain mismatch")
    sanitized = {"candidate.KWbe2iGW", "candidate.oivrdV6U", "candidate.M4v94Rmv"}
    require(sum(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS.values()) == 3 and all(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS[name] == 1 for name in sanitized), "credential omission count fixture mismatch")
    require(set(SANITIZED_PROTECTED_PREDECESSOR_BASELINES) == sanitized, "sanitized baseline domain mismatch")
    require(all(PREDECESSORS[name][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES[name] for name in sanitized), "sanitized predecessor baseline mismatch")
    return {"negative_fixture_count": len(negatives), "protected_path_count": 1, "sanitized_baseline_count": 3, "result": "PASS"}
'''
    successor = '''
def validate_successor_source(repo: Path, *, plan_sha: str, status_sha: str, context_expected: bool) -> dict[str, Any]:
    reference_bytes, _ = read_regular(BASE / "candidate.OlsWg1/receipts/candidate-pre-setup-manifest.jsonl")
    require(sha(reference_bytes) == MANIFEST_SHA, "B2 reference manifest mismatch")
    payload, counts = canonical_manifest(repo)
    rows = manifest_rows(payload)
    reference = manifest_rows(reference_bytes)
    v2_path, v3_path = SUCCESSOR_REQUIREMENT_PATHS
    context_path = TRUSTED_CONTEXT_REL.as_posix()
    acceptance_path = CONTROLLER_ACCEPTANCE_REL.as_posix()
    expected_paths = set(reference) | {v2_path, v3_path}
    if context_expected:
        expected_paths.add(context_path)
    require(set(rows) == expected_paths, "successor repository path set mismatch")
    for path, value in reference.items():
        if path not in {"STATUS.md", "docs/exec-plans/liveclip-agent-runtime-v2.md"}:
            require(rows[path] == value, "non-overlay B2 record changed: " + path)
    expected_overlay = {
        "STATUS.md": ("tracked", status_sha),
        "docs/exec-plans/liveclip-agent-runtime-v2.md": ("ordinary-untracked", plan_sha),
        v2_path: ("ordinary-untracked", SUCCESSOR_REQUIREMENT_V2_SHA),
        v3_path: ("ordinary-untracked", SUCCESSOR_REQUIREMENT_SHA),
    }
    for path, (path_class, expected_sha) in expected_overlay.items():
        row = rows[path]
        require(row["class"] == path_class and row["type"] == "regular" and row["mode"] == "0644" and row["sha256"] == expected_sha, "successor overlay identity mismatch: " + path)
    if context_expected:
        row = rows[context_path]
        require(row["class"] == "ordinary-untracked" and row["type"] == "regular" and row["mode"] == "0600", "trusted-context record identity mismatch")
        require(acceptance_path not in rows, "ignored controller acceptance entered Git manifest")
        source_acceptance, source_info = read_regular(M2B / "receipts" / CONTROLLER_ACCEPTANCE_NAME)
        candidate_acceptance, candidate_info = read_regular(repo / CONTROLLER_ACCEPTANCE_REL)
        source_owner = correlate_read_identity_owner(M2B / "receipts" / CONTROLLER_ACCEPTANCE_NAME, source_info, "0600")
        candidate_owner = correlate_read_identity_owner(repo / CONTROLLER_ACCEPTANCE_REL, candidate_info, "0600")
        require(candidate_acceptance == source_acceptance and candidate_owner == source_owner == CURRENT_UID, "ignored controller acceptance byte/owner mismatch")
        acceptance_identity = {"mode": candidate_info["mode"], "owner_uid": candidate_owner, "path": str(repo / CONTROLLER_ACCEPTANCE_REL), "sha256": sha(candidate_acceptance), "size": len(candidate_acceptance)}
        expected_counts = {"tracked": 2251, "ordinary_untracked": 74, "records": 2325}
    else:
        require(context_path not in rows, "trusted-context exists before init")
        acceptance_identity = None
        expected_counts = {"tracked": 2251, "ordinary_untracked": 73, "records": 2324}
    require(counts == expected_counts, "successor manifest counts mismatch")
    current_status = status_counts(repo)
    require(current_status == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": expected_counts["ordinary_untracked"]}, "successor Git status mismatch")
    require(git_bytes(["remote"], repo) == b"", "successor remote exists")
    return {"controller_acceptance": acceptance_identity, "counts": counts, "manifest_sha256": sha(payload), "status": current_status}
'''
    overlay = '''
def overlay_successor_documents(repo: Path, receipts: Path, plan_sha: str, status_sha: str) -> dict[str, Any]:
    context = repo / TRUSTED_CONTEXT_REL
    v2_target = repo / SUCCESSOR_REQUIREMENT_PATHS[0]
    v3_target = repo / SUCCESSOR_REQUIREMENT_PATHS[1]
    require(not context.exists() and not context.is_symlink(), "trusted-context path not reserved")
    require(not context.parent.exists() and not context.parent.is_symlink(), "trusted-context parent path not reserved")
    for target in (v2_target, v3_target):
        require(not target.exists() and not target.is_symlink(), "requirement collision")
    plan_bytes, _ = read_living_plan()
    status_bytes, _ = read_regular(STATUS)
    v2_bytes, _ = read_regular(SUCCESSOR_REQUIREMENT_V2)
    v3_bytes, _ = read_regular(SUCCESSOR_REQUIREMENT)
    require(sha(plan_bytes) == plan_sha and sha(status_bytes) == status_sha, "overlay document drift")
    require(sha(v2_bytes) == SUCCESSOR_REQUIREMENT_V2_SHA and sha(v3_bytes) == SUCCESSOR_REQUIREMENT_SHA, "overlay requirement drift")
    identities = {
        "docs/exec-plans/liveclip-agent-runtime-v2.md": write_candidate_file(repo / "docs/exec-plans/liveclip-agent-runtime-v2.md", plan_bytes, replace=True),
        "STATUS.md": write_candidate_file(repo / "STATUS.md", status_bytes, replace=True),
        SUCCESSOR_REQUIREMENT_PATHS[0]: write_candidate_file(v2_target, v2_bytes, replace=False),
        SUCCESSOR_REQUIREMENT_PATHS[1]: write_candidate_file(v3_target, v3_bytes, replace=False),
    }
    require(sha(read_regular(SCHEMA_SEED)[0]) == SCHEMA_SEED_SHA, "schema seed changed during overlay")
    validation = validate_successor_source(repo, plan_sha=plan_sha, status_sha=status_sha, context_expected=False)
    receipt = {"format_version": 1, "identities": identities, "phase": "M3_SUCCESSOR_OVERLAY", "result": "PASS", "schema_seed_copied": False, "trusted_context_reserved_absent": True, "validation": validation}
    write_exclusive(receipts / "successor-v41-overlay.json", pretty(receipt))
    return receipt
'''
    v40 = '''
def validate_m3s_v40_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V40_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V40 root entries mismatch")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V40 private root drift")
    expected_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_receipts, "V40 root receipt set mismatch")
    root_files = {name: require_identity(root / name, value["sha256"], 0o600, value["size"]) for name, value in closure["root_files"].items()}
    candidate = BASE / closure["candidate"]["name"]
    private_directory_identity(candidate)
    require(set(os.listdir(candidate)) == {"home", "repo", "successor-receipts", "tmp"}, "V40 candidate entries mismatch")
    candidate_files = {name: require_identity(candidate / name, value["sha256"], 0o600, value["size"]) for name, value in V40_ACCEPTED_CANDIDATE_FILES.items()}
    run = candidate / "repo/.loop/runs" / closure["candidate"]["run_id"]
    state, state_identity = load_json(run / "state.json")
    formal_files = {name: require_identity(run / name, value["sha256"], 0o644, value["size"]) for name, value in closure["formal_files"].items()}
    require(state_identity["sha256"] == closure["formal_files"]["state.json"]["sha256"] and state["state"] == "blocked" and state["cycle"] == 2 and state["code_cycle"] == 0 and state["coder_session_id"] is None and state["last_error"] == "plan repair budget exhausted" and state["command_results"] == [], "V40 formal state mismatch")
    require(set(state["artifacts"]) == {"planner"} and len(state["artifacts"]["planner"]) == 2 and set(os.listdir(run / "artifacts")) == {"planner"}, "V40 downstream role evidence appeared")
    for name in ("001.json", "002.json"):
        planner, _ = load_json(run / "artifacts/planner" / name)
        require(planner["verdict"] == "NEEDS_INPUT" and closure["formal"]["missing_requirement"] in planner["summary"], "V40 planner stop mismatch")
    authoritative = require_identity(RECOVERY_PREDECESSOR_PATH, RECOVERY_PREDECESSOR_IDENTITY["sha256"], 0o644, RECOVERY_PREDECESSOR_IDENTITY["size"])
    v2_relative = b"docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md"
    v3_relative = b"docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md"
    path_list, _ = read_regular(candidate / "successor-receipts/included-untracked.zlist")
    require(v2_relative not in path_list and v3_relative not in path_list, "V40 B2 path-list defect mismatch")
    overlay, _ = load_json(candidate / "successor-receipts/successor-v40-overlay.json")
    require(v2_relative.decode() not in overlay["identities"] and v3_relative.decode() in overlay["identities"], "V40 overlay defect mismatch")
    for manifest_name in ("postacceptance-repository-manifest.jsonl", "postacceptance-attempt-manifest.jsonl"):
        manifest, _ = read_regular(candidate / "successor-receipts" / manifest_name, 16 * 1024 * 1024)
        require(v2_relative not in manifest and v3_relative in manifest, "V40 postacceptance defect mismatch")
    sanitized = closure["sanitized_auth_result"]
    sanitized_identity = require_identity(Path(sanitized["path"]), sanitized["sha256"], 0o600, sanitized["size"])
    counts = status_counts(candidate / "repo")
    require(counts == closure["inventory"]["candidate"], "V40 candidate inventory mismatch")
    for name in ("final-controller-acceptance-v40-result.json", "auth-handoff-v40-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V40 reserved root result appeared")
    require(closure["candidate_count"] == 24, "V40 recorded candidate count mismatch")
    return {"authoritative_v2": authoritative, "candidate_files": candidate_files, "formal_files": formal_files, "root_files": root_files, "sanitized_auth_result": sanitized_identity, "source_transport_defect": closure["source_transport_defect"], "state": state_identity, "result": "PASS"}
'''
    return {"manifest": manifest, "overlay": overlay, "recovery": recovery, "successor": successor, "v40": v40}


def derive_driver(v40_bytes: bytes) -> bytes:
    require((len(v40_bytes), sha256(v40_bytes)) == (V40_DRIVER_SIZE, V40_DRIVER_SHA256), "sealed V40 driver mismatch")
    legacy = _load_legacy()
    original_text = v40_bytes.decode("utf-8")
    original_tree = ast.parse(original_text, filename="<sealed-v40-driver>")
    historical: dict[str, str] = {}
    for node in original_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("PREVIOUS_"):
            source = ast.get_source_segment(original_text, node)
            require(source is not None, "historical assignment source missing")
            historical[node.targets[0].id] = source
    future_upper = "__M3S_FUTURE_UPPER__"
    future_lower = "__m3s_future_lower__"
    text = original_text.replace("V41", future_upper).replace("v41", future_lower)
    text = text.replace("V40", "V41").replace("v40", "v41")
    text = text.replace(future_upper, "V42").replace(future_lower, "v42")
    text = text.replace("range(41, 55)", "range(42, 55)", 1)
    text = text.replace('current_result_name = "successor-preparation-v" + "40-result.json"', 'current_result_name = "successor-preparation-v" + "41-result.json"', 1)
    text = text.replace('future_result_name = "successor-preparation-v" + "41-result.json"', 'future_result_name = "successor-preparation-v" + "42-result.json"', 1)
    for name, source in historical.items():
        text = _replace_assignment_source(text, name, source)

    constants = (
        f"PREVIOUS_M3S_V40_CLOSURE = {V40_CLOSURE!r}\n"
        f"V40_ACCEPTED_CANDIDATE_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V40_CANDIDATE_FILES.items()}!r}\n"
        f"RECOVERY_PREDECESSOR_PATH = Path({str(REQUIREMENT_V2)!r})\n"
        f"RECOVERY_PREDECESSOR_IDENTITY = {{'size': {REQUIREMENT_V2_SIZE}, 'sha256': {REQUIREMENT_V2_SHA256!r}}}\n"
        f"SUCCESSOR_REQUIREMENT_V2 = ORIGINAL / 'docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md'\n"
        f"SUCCESSOR_REQUIREMENT_V2_SHA = {REQUIREMENT_V2_SHA256!r}\n"
        "SUCCESSOR_REQUIREMENT_PATHS = ('docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md', 'docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md')\n"
    )
    text = _insert_after_assignment(text, "RECOVERY_SOURCE_PREIMAGES", constants)
    predecessor_anchor = 'PREDECESSORS["candidate.oivrdV6U"] = (56251, 1143615319, "b1506798b693d79b61d3e1c55bd525d84fec54e09d793d910b65e3b2342d3d1c", "115cd285478ced736b3af391e15f39947bd171786e18dc42c89313ac8ec5bdb7")'
    require(text.count(predecessor_anchor) == 1, "V40 predecessor anchor mismatch")
    text = text.replace(predecessor_anchor, predecessor_anchor + '\nPREDECESSORS["candidate.M4v94Rmv"] = (44420, 968624315, "ea61d5daf2332341515b66f08782d313809bbdbe92b9dded693485003be73b9a", "d6f9d170fbc6db5ebceaaaa9e6dfc63b838f1d2e46dd77782db4845a87e42c5e")', 1)
    omission_anchor = 'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.oivrdV6U"] = 1'
    require(text.count(omission_anchor) == 1, "V40 omission anchor mismatch")
    text = text.replace(omission_anchor, omission_anchor + '\nPREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.M4v94Rmv"] = 1', 1)
    baselines = legacy.literal_assignment(text.encode(), "SANITIZED_PROTECTED_PREDECESSOR_BASELINES")
    baselines["candidate.M4v94Rmv"] = (44_420, 968_624_315, "ea61d5daf2332341515b66f08782d313809bbdbe92b9dded693485003be73b9a")
    text = legacy.replace_assignment(text, "SANITIZED_PROTECTED_PREDECESSOR_BASELINES", baselines)
    funcs = _function_source()
    text = legacy.replace_function(text, "manifest_credential_policy_self_test", funcs["manifest"])
    text = legacy.replace_function(text, "validate_v41_recovery_contract", funcs["recovery"])
    text = legacy.replace_function(text, "validate_successor_source", funcs["successor"])
    text = legacy.replace_function(text, "overlay_successor_documents", funcs["overlay"])
    text = text.replace('"m3s_v39_stopped": validate_m3s_v39_stopped(),', '"m3s_v40_stopped": validate_m3s_v40_stopped(),\n        "m3s_v39_stopped": validate_m3s_v39_stopped(),', 1)
    require(text.count("def validate_m3s_v39_stopped()") == 1, "V39 validator anchor mismatch")
    text = text.replace("def validate_m3s_v39_stopped()", funcs["v40"].rstrip() + "\n\n\ndef validate_m3s_v39_stopped()", 1)
    text = text.replace('PREVIOUS_M3S_V39_CLOSURE["formal"]', 'PREVIOUS_M3S_V40_CLOSURE["formal"]')
    text = text.replace('PREVIOUS_M3S_V39_CLOSURE["formal"]["run_id"]', 'PREVIOUS_M3S_V40_CLOSURE["formal"]["run_id"]')
    text = text.replace("canonical_json_model(PREVIOUS_M3S_V39_CLOSURE)", "canonical_json_model(PREVIOUS_M3S_V40_CLOSURE)")
    text = text.replace('"retained_v39_run_id_reject"', '"retained_v40_run_id_reject"')
    overlay_old = '[\n            "STATUS.md",\n            TRUSTED_CONTEXT_REL.as_posix(),\n            "docs/exec-plans/liveclip-agent-runtime-v2.md",\n            "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md",\n        ]'
    overlay_new = '[\n            "STATUS.md",\n            TRUSTED_CONTEXT_REL.as_posix(),\n            "docs/exec-plans/liveclip-agent-runtime-v2.md",\n            "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md",\n            "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md",\n        ]'
    require(text.count(overlay_old) == 1, "context overlay validator anchor mismatch")
    text = text.replace(overlay_old, overlay_new, 1)
    record_old = '                (\n                    "docs/requirements/"\n                    "liveclip-agent-runtime-v2-acceptance-v3.md"\n                ),'
    record_new = '                "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md",\n' + record_old
    require(text.count(record_old) == 1, "context overlay record anchor mismatch")
    text = text.replace(record_old, record_new, 1)
    text = text.replace('"requirement_path": (\n                "docs/requirements/"\n                "liveclip-agent-runtime-v2-acceptance-v3.md"\n            ),', '"requirement_predecessor_path": "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md",\n            "requirement_predecessor_sha256": SUCCESSOR_REQUIREMENT_V2_SHA,\n            "requirement_path": (\n                "docs/requirements/"\n                "liveclip-agent-runtime-v2-acceptance-v3.md"\n            ),', 1)
    text = text.replace('require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 169}, "original status counts mismatch")', 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 173}, "original status counts mismatch")', 1)

    contracts = legacy.literal_assignment(text.encode(), "CONTROLLER_CONTRACTS")
    candidate = contracts["candidate_allocation"]
    candidate["expected_predecessors"] = sorted(EXPECTED_CANDIDATES, key=os.fsencode)
    candidate["predecessor_count"] = 24
    candidate["candidate_set_contract"]["preallocation"] = "exact 24 immutable predecessor names"
    candidate["candidate_set_contract"]["postallocation"] = "exact 24 predecessors plus one unpredictable current candidate"
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = "checked-in-loop-engineering-policy-plus-v41-exact-v2-v3-source-transport-bounded-tree-recovery-relational-toolchain-final-external-acceptance"
    policy["pre_root_full_audit"] = {"allocation": False, "gate_count": 65, "home": str(V40_ROOT / "home"), "include_process_gate": True, "no_write_snapshot": True, "tmp": str(V40_ROOT / "tmp")}
    policy["controller_acceptance_semantics"] = {"model": "controller_acceptance_semantic_violations", "predecessor": "PREVIOUS_M3S_V40_CLOSURE", "rejects": ["V39", "missing", "mutated_v40", "extra_v40", "wrong_root"]}
    policy["source_transport"] = {
        "authoritative_source": "Trusted Main exact bytes",
        "paths": list(("docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md", "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md")),
        "v2": {"size": REQUIREMENT_V2_SIZE, "sha256": REQUIREMENT_V2_SHA256},
        "v3": {"size": REQUIREMENT_V3_SIZE, "sha256": REQUIREMENT_V3_SHA256},
        "fixtures": ["exact", "v2_omission", "v3_omission", "substitution", "hash_drift", "extra"],
    }
    policy["historical_candidate_counts"]["recorded_counts"]["V40"] = 24
    policy["historical_candidate_counts"]["current_live_total_not_consulted"].append("V40")
    trusted = contracts["trusted_context"]
    trusted["immediate_predecessor"] = {"candidate": "candidate.M4v94Rmv", "closure": "PREVIOUS_M3S_V40_CLOSURE", "formal": "CONSUMED_STOPPED_NO_REUSE", "prepare": "CONSUMED_ACCEPTED_NO_REUSE", "root": str(V40_ROOT), "run_id": V40_RUN_ID}
    trusted["immediate_predecessor_design"] = {"closure": "PREVIOUS_M3S_V40_CLOSURE", "root": str(V40_ROOT), "state": "TERMINAL_FORMAL_STOP_NO_REUSE"}
    trusted["recovery_requirement"] = {"path": "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md", "sha256": REQUIREMENT_V3_SHA256, "trusted_record_version": 3, "predecessor": {"path": "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md", "sha256": REQUIREMENT_V2_SHA256}}
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = legacy.replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = legacy.replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")


def inspect_driver(payload: bytes) -> dict[str, Any]:
    legacy = _load_legacy()
    text = payload.decode("utf-8")
    tree = ast.parse(text, filename="<m3s-v41-driver>")
    compile(tree, "<m3s-v41-driver>", "exec")
    contracts = legacy.literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = legacy.literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_only_gates"]
    require(len(gate) == 1, "read-only gate function mismatch")
    returns = [node for node in ast.walk(gate[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    require(len(returns) == 1 and len(returns[0].value.keys) == 65, "gate count mismatch")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v41_static"}
    exec(compile(tree, "<m3s-v41-static>", "exec"), namespace)  # noqa: S102
    require({name: len(shape) for name, shape in namespace["SHAPES"].items()} == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    recovery_cases = namespace["validate_v41_recovery_contract"]()
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(all(candidate_cases.values()) and all(context_cases.values()), "driver fixture failed")
    require(credential_cases["sanitized_baseline_count"] == 3, "credential fixture failed")
    require(all(recovery_cases["transport_fixtures"].values()), "source transport fixture failed")
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    execute_node = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute"]
    require(len(execute_node) == 1, "execute function mismatch")
    mktemp = [node for node in ast.walk(execute_node[0]) if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/mktemp"]
    initializers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "initialize_and_bind_successor"]
    loop_init = [node for initializer in initializers for node in ast.walk(initializer) if isinstance(node, ast.List) and len(node.elts) >= 2 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make" and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "41-result.json"' in payload and b'future_result_name = "successor-preparation-v" + "42-result.json"' in payload, "current/future result mismatch")
    return {"ast_compile": "PASS", "candidate_set_cases": candidate_cases, "command_surface": {name: len(shape) for name, shape in namespace["SHAPES"].items()}, "context_cases": context_cases, "contracts": hashes, "credential_policy": credential_cases, "gate_count": 65, "one_loop_init": True, "one_mktemp": True, "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"}, "source_transport": recovery_cases["transport_fixtures"], "result": "PASS"}


def extract_source(plan_bytes: bytes) -> bytes:
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def build_acceptance(driver_bytes: bytes, *, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, helper_bytes: bytes) -> bytes:
    legacy = _load_legacy()
    contracts = legacy.literal_assignment(driver_bytes, "CONTROLLER_CONTRACTS")
    hashes = legacy.literal_assignment(driver_bytes, "CONTROLLER_CONTRACT_HASHES")
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
        "phase": "M3S_V41_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V40_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "legacy_helper": {"path": str(LEGACY_HELPER), "sha256": LEGACY_HELPER_SHA256, "size": LEGACY_HELPER_SIZE},
            "requirements": {
                "v2": {"path": str(REQUIREMENT_V2), "sha256": REQUIREMENT_V2_SHA256, "size": REQUIREMENT_V2_SIZE},
                "v3": {"path": str(REQUIREMENT_V3), "sha256": REQUIREMENT_V3_SHA256, "size": REQUIREMENT_V3_SIZE},
            },
            "sealed_v40_driver": {"path": str(V40_DRIVER), "sha256": V40_DRIVER_SHA256, "size": V40_DRIVER_SIZE},
            "sha256": sha256(source_bytes),
            "size": len(source_bytes),
        },
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": legacy.literal_assignment(driver_bytes, "CONTROLLER_ROOT_BINDING"),
        "seed": {
            "head": legacy.literal_assignment(driver_bytes, "HEAD"),
            "manifest_sha256": legacy.literal_assignment(driver_bytes, "MANIFEST_SHA"),
            "patch_sha256": legacy.literal_assignment(driver_bytes, "PATCH_SHA"),
            "path_list_sha256": legacy.literal_assignment(driver_bytes, "LIST_SHA"),
        },
    }
    return compact(value) + b"\n"


def expected_environment() -> dict[str, str]:
    return {
        "HOME": "/Users/junhuaxu",
        "TMPDIR": "/tmp",  # noqa: S108 - frozen root-only environment
        "PATH": PATH_VALUE,
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_OPTIONAL_LOCKS": "0",
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
    candidates = tuple(sorted((entry.name for entry in os.scandir(BASE) if entry.is_dir(follow_symlinks=False) and entry.name.startswith("candidate.")), key=os.fsencode))
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    status_payload = git_status_bytes()
    counts = status_counts(status_payload)
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 173}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    v2 = require_file(REQUIREMENT_V2, REQUIREMENT_V2_SIZE, REQUIREMENT_V2_SHA256)
    v3 = require_file(REQUIREMENT_V3, REQUIREMENT_V3_SIZE, REQUIREMENT_V3_SHA256)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V41 root appeared")
    return {"architecture": architecture, "candidates_sha256": sha256(compact(candidates)), "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)}, "git_status_sha256": sha256(status_payload), "inventory": counts, "requirements": {"v2": v2, "v3": v3}, "v41_root_absent": True}


def full_pre_root_audit(driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v41-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v41_audit"}
    exec(compile(tree, "<m3s-v41-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V40 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v39_substitution", namespace["PREVIOUS_M3S_V39_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["formal"]["state"] = "received"
    negatives["mutated_v40"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v40"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 40}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(all(negatives[name] == ["predecessor_closure"] for name in ("v39_substitution", "missing", "mutated_v40", "extra_v40")) and negatives["wrong_root"] == ["root"], "V40 acceptance negative accepted")
    values = {"base": str(BASE), "seed": str(SEED), "plan": str(PLAN), "expected_plan_sha256": sha256(plan_bytes), "status": str(STATUS), "expected_status_sha256": sha256(status_bytes)}
    saved_environment = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](values, V40_ROOT / "home", V40_ROOT / "tmp", include_process_gate=True)
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 65, "full pre-root gate count mismatch")
    require(gates["v41_recovery_contract"]["result"] == "PASS", "recovery gate failed")
    require(gates["m3s_v40_stopped"]["result"] == "PASS", "V40 closure gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION" and len(gates["predecessors"]["candidate_names"]) == 24, "preallocation state mismatch")
    after_plan, _ = read_regular(PLAN)
    after_status, _ = read_regular(STATUS)
    after = audit_snapshot(after_plan, after_status)
    require(after == before, "full pre-root audit wrote or changed protected state")
    return {"acceptance_negatives": negatives, "gate_count": len(gates), "gates": {name: "PASS" for name in gates}, "no_write": {"before": before, "after": after, "result": "PASS"}, "result": "PASS"}


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def command_identities(*, plan_sha: str, status_sha: str, source_bytes: bytes, driver_bytes: bytes, helper_bytes: bytes) -> dict[str, Any]:
    python_argv = [
        "/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), "--",
        "--plan", str(PLAN), "--expected-plan-sha256", plan_sha,
        "--status", str(STATUS), "--expected-status-sha256", status_sha,
        "--expected-source-sha256", sha256(source_bytes),
        "--expected-driver-sha256", sha256(driver_bytes),
        "--expected-helper-sha256", sha256(helper_bytes),
    ]
    env = expected_environment()
    env_order = ("HOME", "TMPDIR", "PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE", "GIT_OPTIONAL_LOCKS", "__CF_USER_TEXT_ENCODING")
    vector = ["/usr/bin/env", "-i", *(f"{name}={env[name]}" for name in env_order), *python_argv]
    payload = " ".join(shell_quote(value) for value in vector).encode("utf-8")
    outer = ["/bin/zsh", "-f", "-c", payload.decode("utf-8")]
    def identity(values: list[str]) -> dict[str, Any]:
        encoded = json.dumps(values, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        return {"count": len(values), "json_bytes": len(encoded), "sha256": sha256(encoded)}
    return {"python_argv": identity(python_argv), "python_argv_values": python_argv, "clean_vector": identity(vector), "clean_vector_values": vector, "literal_envelope": {"bytes": len(payload), "sha256": sha256(payload), "token_count": len(vector)}, "literal_envelope_bytes": payload, "outer_zsh_argv": identity(outer), "outer_zsh_argv_values": outer}


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
    require(os.getuid() == CURRENT_UID and Path.cwd() == SEED, "root-only process context mismatch")
    require(dict(os.environ) == expected_environment(), "root-only environment mismatch")
    require(Path(args.plan) == PLAN and Path(args.status) == STATUS, "document path mismatch")
    require(sha256(source_bytes) == args.expected_source_sha256 and sha256(helper_bytes) == args.expected_helper_sha256, "source/helper hash mismatch")
    plan_bytes, _ = read_regular(PLAN)
    status_bytes, _ = read_regular(STATUS)
    require(sha256(plan_bytes) == args.expected_plan_sha256 and sha256(status_bytes) == args.expected_status_sha256, "document hash mismatch")
    require(extract_source(plan_bytes) == source_bytes, "embedded source mismatch")
    v40_bytes, _ = read_regular(V40_DRIVER)
    driver_bytes = derive_driver(v40_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source_bytes, helper_bytes=helper_bytes)
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V41 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v41.json", acceptance)
    source_receipt = write_exclusive(RECEIPTS / "source-receipt.json", compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V41_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n")
    writer_receipt = write_exclusive(RECEIPTS / "writer-self-test.json", compact({"format_version": 1, "phase": "M3S_V41_WRITER_SELF_TEST", "result": "PASS"}) + b"\n")
    self_check = write_exclusive(RECEIPTS / "self-check-result.json", compact({"audit": audit, "format_version": 1, "phase": "M3S_V41_SELF_CHECK", "result": "PASS", "static": static}) + b"\n")
    final_value = {"controller_acceptance": acceptance_identity, "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256}, "driver": driver_identity, "format_version": 1, "phase": "M3S_V41_FINAL_INDEX", "root_prepare_argv_json_sha256": sha256(root_argv_json), "source_receipt": source_receipt, "self_check": self_check, "verdict": "M3S_V41_READY_FOR_CONTROLLER_REVIEW", "writer_self_test": writer_receipt}
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V41_ROOT_ONLY", "result": "M3S_V41_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
