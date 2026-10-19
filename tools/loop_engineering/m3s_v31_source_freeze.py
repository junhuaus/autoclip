"""Deterministic M3S-v31 source-freeze helper.

This module is trusted preparation machinery, not product code and not a
formal-loop role.  Its public surfaces are the pure ``derive_driver`` byte
transform and the root-only ``main`` entry point used by the unique source
embedded in the Living ExecPlan.
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
V30_ROOT = BASE / "trusted-tools/m3-successor-preparation-v30"
V30_DRIVER = V30_ROOT / "candidate-driver.py"
V30_DRIVER_SIZE = 383_064
V30_DRIVER_SHA256 = "520f6a6ccb243ae970d1160c3c94935eed348dde4453368abd2355c8d6d5038f"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v31"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V31_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V31_END\n"
DESIGN_SHA256 = "8a7644183a20a2afba6833cb4bcee31ea64553cb3a035523fa69a934545776df"
TERMINAL_CLOSURE_SHA256 = "a5f42d591bce6309906e575cd89373e5f471ad59bdd297c19ffb6064f0e81791"
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
TERMINAL_FILES = {
    "repo/.loop/runs/20261013T215618Z-941df9ff/state.json": (
        9_406,
        "92428fa2311798509fa658a5d425b5bab558415c72827e99b141fa4fca0f902e",
        0o644,
    ),
    "repo/.loop/runs/20261013T215618Z-941df9ff/artifacts/planner/001.json": (
        10_607,
        "81081997445f3882d0dec34aadcb2c89a5778d1d0e4b3dd7562f709853de506a",
        0o644,
    ),
    "repo/.loop/runs/20261013T215618Z-941df9ff/artifacts/planner/002.json": (
        11_089,
        "0f1a624c79674b82d9e81946965a44d587ee85379eecc5bf7ce98a988c06bbc7",
        0o644,
    ),
    "successor-receipts/final-receipt-index.json": (
        17_607,
        "dfa502322327d4ee6a3f67227ecbbc3544416e052cb146bfe7220a03c972e3de",
        0o600,
    ),
    "successor-receipts/successor-v30-final-bindings.json": (
        5_408,
        "bfe7219b055694f54a7f7f9ed64aa59dac2bfd20f98ed056054c19ec5ef55ca6",
        0o600,
    ),
    "successor-receipts/successor-v30-toolchain-snapshot.json": (
        4_878,
        "4e2be14297c8437f1266967809b5d392b8dfd68675340f224fe159c4e007a238",
        0o600,
    ),
}
V30_RESULT = V30_ROOT / "receipts/successor-preparation-v30-result.json"
V30_RESULT_SIZE = 23_400
V30_RESULT_SHA256 = "509bbec65b5cb07bc19bf0d9c740c945322209201dc23d322f06e0a7c856de2a"
V30_FINAL_INDEX = V30_ROOT / "receipts/final-index.json"
V30_FINAL_INDEX_SIZE = 5_452
V30_FINAL_INDEX_SHA256 = "1b3e06d653d93ef52615bf9369a33927c0cbf186e3b00b89d78a9055237a850b"
TARGET = BASE / "candidate.5nZWpynN"
RUN_ID = "20261013T215618Z-941df9ff"
HEAD = "2f361fcddc0e63ae62ee62826e27b54bb8204c53"
WRAPPER = BASE / "candidate.xp23hqNY/receipts/bounded-wrapper.py"
WRAPPER_SIZE = 2_345
WRAPPER_SHA256 = "d022a3dbb40be1664ba663617c18e1690c3e353be51d20a46d8c852f2d3e14ed"


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


def open_regular(path: Path) -> tuple[int, os.stat_result]:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(), f"unsafe file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    opened = os.fstat(fd)
    require(
        (opened.st_dev, opened.st_ino, opened.st_size)
        == (before.st_dev, before.st_ino, before.st_size),
        f"opened identity mismatch: {path}",
    )
    return fd, opened


def read_regular(path: Path, maximum: int = 16 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
    fd, opened = open_regular(path)
    require(opened.st_size <= maximum, f"file exceeds bound: {path}")
    chunks: list[bytes] = []
    try:
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
    tree = ast.parse(payload, filename="<m3s-v31-literal-extraction>")
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


OFFER_WRAPPER = r'''

_v31_prepare_bindings = initialize_and_bind_successor


def initialize_and_bind_successor(
    repo: Path,
    parent: Path,
    receipts: Path,
    env: dict[str, str],
    plan_sha: str,
    status_sha: str,
    acceptance_payload: bytes,
    acceptance_identity: dict[str, Any],
) -> dict[str, Any]:
    legacy = _v31_prepare_bindings(
        repo,
        parent,
        receipts,
        env,
        plan_sha,
        status_sha,
        acceptance_payload,
        acceptance_identity,
    )
    preparation_path = receipts / "successor-v31-preparation-bindings.json"
    preparation_identity = hash_regular(preparation_path)
    offer = {
        "candidate": {
            "name": parent.name,
            "repo": str(repo),
            "root": str(parent),
        },
        "candidate_worktree_sha256": legacy["candidate_worktree_sha256"],
        "current_documents": {
            "execplan_sha256": plan_sha,
            "status_sha256": status_sha,
        },
        "dispatch": {
            "argv": legacy["future_loop_run_argv"],
            "argv_json_sha256": legacy["future_loop_run_argv_json_sha256"],
        },
        "final_record": {
            "preparation_bindings": preparation_identity,
            "root_controller_acceptance": acceptance_identity,
            "root_controller_acceptance_transport": legacy["controller_acceptance_transport"],
        },
        "format_version": 1,
        "initial_run": {
            "events": legacy["initial_events"],
            "run_id": legacy["run_id"],
            "state": legacy["initial_state"],
        },
        "phase": "M3_SUCCESSOR_PREPARATION_V31_AWAITING_CONTROLLER_ACCEPTANCE",
        "policy": {
            "receipt": legacy["policy_receipt"],
            "semantic_sha256": legacy["policy_snapshot_sha256"],
        },
        "preparation": {
            "design_sha256": "8a7644183a20a2afba6833cb4bcee31ea64553cb3a035523fa69a934545776df",
            "driver": hash_regular(DRIVER),
            "preparation_bindings": preparation_identity,
        },
        "sealed_toolchain": {
            "receipt": legacy["toolchain_receipt"],
            "snapshot_fingerprint": legacy["toolchain_snapshot_fingerprint"],
            "source_fingerprint": legacy["toolchain_source_fingerprint"],
        },
        "serialization": {
            "algorithm": "sorted-key-compact-json-plus-one-lf",
            "encoding": "UTF-8",
            "terminal_lf": True,
        },
    }
    offer_payload = compact(offer) + b"\n"
    trusted_offer = repo / ".loop/trusted/controller-acceptance-offer-v31.json"
    require(not trusted_offer.exists() and not trusted_offer.is_symlink(), "trusted offer collision")
    trusted_identity = write_exclusive(trusted_offer, offer_payload)
    receipt_identity = write_exclusive(
        receipts / "successor-v31-controller-acceptance-offer.json",
        offer_payload,
    )
    require(trusted_identity["sha256"] == receipt_identity["sha256"], "offer transport mismatch")
    return {
        "offer": offer,
        "offer_identity": trusted_identity,
        "offer_receipt": receipt_identity,
        "verdict": "M3_SUCCESSOR_PREPARATION_V31_AWAITING_CONTROLLER_ACCEPTANCE",
    }
'''


PREDECESSOR_OVERRIDE = r'''

def validate_v30_terminal_predecessor() -> dict[str, Any]:
    target = BASE / "candidate.5nZWpynN"
    root = private_directory_identity(target)
    require(
        set(os.listdir(target)) == {"home", "repo", "successor-receipts", "tmp"},
        "V30 terminal candidate entries mismatch",
    )
    files = {
        "state": require_identity(
            target / "repo/.loop/runs/20261013T215618Z-941df9ff/state.json",
            "92428fa2311798509fa658a5d425b5bab558415c72827e99b141fa4fca0f902e",
            0o644,
            9406,
        ),
        "planner_001": require_identity(
            target / "repo/.loop/runs/20261013T215618Z-941df9ff/artifacts/planner/001.json",
            "81081997445f3882d0dec34aadcb2c89a5778d1d0e4b3dd7562f709853de506a",
            0o644,
            10607,
        ),
        "planner_002": require_identity(
            target / "repo/.loop/runs/20261013T215618Z-941df9ff/artifacts/planner/002.json",
            "0f1a624c79674b82d9e81946965a44d587ee85379eecc5bf7ce98a988c06bbc7",
            0o644,
            11089,
        ),
        "candidate_final_index": require_identity(
            target / "successor-receipts/final-receipt-index.json",
            "dfa502322327d4ee6a3f67227ecbbc3544416e052cb146bfe7220a03c972e3de",
            0o600,
            17607,
        ),
        "candidate_final_bindings": require_identity(
            target / "successor-receipts/successor-v30-final-bindings.json",
            "bfe7219b055694f54a7f7f9ed64aa59dac2bfd20f98ed056054c19ec5ef55ca6",
            0o600,
            5408,
        ),
        "candidate_toolchain": require_identity(
            target / "successor-receipts/successor-v30-toolchain-snapshot.json",
            "4e2be14297c8437f1266967809b5d392b8dfd68675340f224fe159c4e007a238",
            0o600,
            4878,
        ),
    }
    state, _ = load_json(target / "repo/.loop/runs/20261013T215618Z-941df9ff/state.json")
    require(
        state["state"] == "blocked"
        and state["cycle"] == 2
        and state["code_cycle"] == 0
        and state["coder_session_id"] is None
        and state["command_results"] == []
        and state["last_error"] == "plan repair budget exhausted",
        "V30 terminal state mismatch",
    )
    require(
        state["artifacts"] == {
            "planner": [
                ".loop/runs/20261013T215618Z-941df9ff/artifacts/planner/001.json",
                ".loop/runs/20261013T215618Z-941df9ff/artifacts/planner/002.json",
            ]
        },
        "V30 terminal planner lineage mismatch",
    )
    for name in ("001.json", "002.json"):
        artifact, _ = load_json(
            target
            / "repo/.loop/runs/20261013T215618Z-941df9ff/artifacts/planner"
            / name
        )
        require(artifact["verdict"] == "NEEDS_INPUT", "V30 planner verdict mismatch")
    return {
        "credential_tree_manifested": False,
        "files": files,
        "protected_private_home_traversed": False,
        "root": root,
    }


def validate_predecessors(
    current_candidate: Path | None = None,
    expected_current_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate_paths = sorted(
        (path for path in BASE.iterdir() if path.name.startswith("candidate.")),
        key=lambda path: os.fsencode(path.name),
    )
    observed_names = [path.name for path in candidate_paths]
    current_name = None if current_candidate is None else current_candidate.name
    require(candidate_name_set_matches(observed_names, current_name), "candidate set mismatch for allocation state")
    for path in candidate_paths:
        require(path.is_dir() and not path.is_symlink(), f"unsafe candidate path: {path}")
    immutable: dict[str, Any] = {}
    for name, (count, regular_bytes, current_sha, historical_sha) in PREDECESSORS.items():
        if name == "candidate.5nZWpynN":
            immutable[name] = validate_v30_terminal_predecessor()
            continue
        protected_omissions = PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS[name]
        payload, totals = tree_manifest(BASE / name, protected_omissions)
        require(totals["path_count"] == count, f"predecessor path count mismatch: {name}")
        require(totals["regular_file_bytes"] == regular_bytes, f"predecessor byte count mismatch: {name}")
        require(sha(payload) == current_sha, f"predecessor tree mismatch: {name}")
        immutable[name] = {
            **totals,
            "canonical_current_sha256": current_sha,
            "historical_receipt_sha256": historical_sha,
            "protected_credential_paths_omitted": protected_omissions,
        }
    if current_candidate is None:
        require(expected_current_identity is None, "unexpected current identity before allocation")
        current = None
    else:
        require(expected_current_identity is not None, "missing current candidate identity")
        current = validate_current_candidate(current_candidate, expected_current_identity)
    return {
        "authorized_current_candidate": current,
        "candidate_names": observed_names,
        "immutable_predecessors": immutable,
        "state": "PREALLOCATION" if current is None else "POSTALLOCATION",
    }
'''


ACCEPT_FINAL = r'''

FINAL_ACCEPTANCE_KEYS = frozenset({
    "authority", "candidate", "contracts", "documents", "final_record",
    "format_version", "phase", "result", "run", "sealed_toolchain",
    "serialization",
})


def _same_identity(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return all(left[key] == right[key] for key in ("mode", "path", "sha256", "size", "type"))


def accept_final(values: dict[str, str]) -> int:
    current_argv = [str(PYTHON), str(DRIVER), *sys.argv[1:]]
    result_path = M2B / "receipts/final-controller-acceptance-v31-result.json"
    validate_phase_environment(
        "M3S_V31_FINAL_CONTROLLER_ACCEPTANCE",
        120,
        current_argv,
        result_path,
    )
    self_identity(values["expected_self_sha"])
    require(not result_path.exists() and not result_path.is_symlink(), "final acceptance result exists")
    validate_documents(
        str(PLAN),
        values["expected_current_plan_sha256"],
        str(STATUS),
        values["expected_current_status_sha256"],
    )
    candidate = Path(values["candidate"])
    require(candidate.parent == BASE and re.fullmatch(r"candidate\.[A-Za-z0-9_]+", candidate.name) is not None, "candidate path mismatch")
    require(candidate.name not in PREDECESSORS, "predecessor cannot be accepted")
    private_directory_identity(candidate)
    observed = sorted(
        (path.name for path in BASE.iterdir() if path.name.startswith("candidate.")),
        key=os.fsencode,
    )
    require(observed == sorted([*PREDECESSORS, candidate.name], key=os.fsencode), "postprepare candidate set mismatch")
    repo = candidate / "repo"
    receipts = candidate / "successor-receipts"
    private_directory_identity(receipts)
    run_id = values["run_id"]
    require(re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", run_id) is not None, "run ID shape mismatch")
    state_path = repo / ".loop/runs" / run_id / "state.json"
    state, state_identity = load_json(state_path)
    require(
        state["state"] == "received"
        and state["cycle"] == 0
        and state["code_cycle"] == 0
        and state["coder_session_id"] is None
        and state["artifacts"] == {}
        and state["command_results"] == []
        and state["last_error"] is None,
        "run is not pristine",
    )
    offer_receipt_path = receipts / "successor-v31-controller-acceptance-offer.json"
    offer_trusted_path = repo / ".loop/trusted/controller-acceptance-offer-v31.json"
    offer_receipt_bytes, offer_receipt_identity = read_regular(offer_receipt_path)
    offer_trusted_bytes, offer_trusted_identity = read_regular(offer_trusted_path)
    require(offer_receipt_bytes == offer_trusted_bytes, "offer copies differ")
    require(sha(offer_trusted_bytes) == values["offer_sha256"], "offer hash mismatch")
    offer = json.loads(offer_trusted_bytes.decode("utf-8"))
    require(offer_trusted_bytes == compact(offer) + b"\n", "offer is not canonical")
    require(offer["candidate"] == {"name": candidate.name, "repo": str(repo), "root": str(candidate)}, "offer candidate mismatch")
    require(offer["initial_run"]["run_id"] == run_id and _same_identity(offer["initial_run"]["state"], state_identity), "offer run mismatch")
    acceptance_text = values["controller_acceptance_json"]
    acceptance = json.loads(acceptance_text)
    acceptance_bytes = compact(acceptance) + b"\n"
    require(acceptance_text.encode("utf-8") == compact(acceptance), "external acceptance is not canonical")
    require(set(acceptance) == FINAL_ACCEPTANCE_KEYS, "external acceptance schema mismatch")
    require(
        acceptance["authority"] == "EXTERNAL_CONTROLLER"
        and acceptance["format_version"] == 1
        and acceptance["phase"] == "M3S_V31_FINAL_CONTROLLER_ACCEPTANCE"
        and acceptance["result"] == "ACCEPTED_AFTER_CANDIDATE_CREATION",
        "external acceptance fixed fields mismatch",
    )
    require(acceptance["candidate"] == offer["candidate"], "accepted candidate mismatch")
    require(acceptance["documents"] == offer["current_documents"], "accepted documents mismatch")
    require(acceptance["final_record"] == offer["final_record"], "accepted final record mismatch")
    require(acceptance["run"] == offer["initial_run"], "accepted run mismatch")
    require(acceptance["sealed_toolchain"] == offer["sealed_toolchain"], "accepted toolchain mismatch")
    require(
        acceptance["contracts"] == {
            "design_sha256": "8a7644183a20a2afba6833cb4bcee31ea64553cb3a035523fa69a934545776df",
            "offer_sha256": values["offer_sha256"],
            "policy_semantic_sha256": offer["policy"]["semantic_sha256"],
            "future_dispatch_argv_json_sha256": offer["dispatch"]["argv_json_sha256"],
        },
        "accepted contracts mismatch",
    )
    require(
        acceptance["serialization"] == {
            "algorithm": "sorted-key-compact-json-plus-one-lf",
            "encoding": "UTF-8",
            "terminal_lf": True,
        },
        "acceptance serialization mismatch",
    )
    final_path = repo / ".loop/trusted/final-controller-acceptance-v31.json"
    require(not final_path.exists() and not final_path.is_symlink(), "final controller acceptance exists")
    final_identity = write_exclusive(final_path, acceptance_bytes)
    transport = {
        "acceptance": final_identity,
        "format_version": 1,
        "offer_receipt": offer_receipt_identity,
        "offer_trusted": offer_trusted_identity,
        "phase": "M3S_V31_FINAL_CONTROLLER_ACCEPTANCE_TRANSPORT",
        "result": "PASS",
        "secret_material_accessed": False,
    }
    transport_identity = write_exclusive(
        receipts / "successor-v31-controller-acceptance-transport.json",
        pretty(transport),
    )
    repository_manifest, repository_totals = tree_manifest(repo)
    repository_identity = write_exclusive(
        receipts / "postacceptance-repository-manifest.jsonl",
        repository_manifest,
    )
    attempt_manifest, attempt_totals = tree_manifest(candidate)
    attempt_identity = write_exclusive(
        receipts / "postacceptance-attempt-manifest.jsonl",
        attempt_manifest,
    )
    index = {
        "acceptance": final_identity,
        "attempt_pre_index": {**attempt_totals, "identity": attempt_identity, "sha256": sha(attempt_manifest)},
        "format_version": 1,
        "offer_sha256": values["offer_sha256"],
        "phase": "M3S_V31_POSTACCEPTANCE_FINAL_INDEX",
        "repository": {**repository_totals, "identity": repository_identity, "sha256": sha(repository_manifest)},
        "run": {"id": run_id, "state": state_identity},
        "transport": transport_identity,
        "verdict": "M3S_V31_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW",
    }
    index_identity = write_exclusive(
        receipts / "postacceptance-final-index.json",
        pretty(index),
    )
    completed_manifest, completed_totals = tree_manifest(candidate)
    os.write(
        1,
        compact({
            "candidate": str(candidate),
            "completed_tree": {**completed_totals, "sha256": sha(completed_manifest)},
            "final_index": index_identity,
            "phase": "M3S_V31_FINAL_CONTROLLER_ACCEPTANCE",
            "result": "M3S_V31_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW",
        }) + b"\n",
    )
    return 0
'''


MAIN_REPLACEMENT = r'''def main() -> int:
    command, values = parse_shape(sys.argv[1:])
    if command == "prepare":
        return execute(values)
    require(command == "accept-final", "credential-free V31 command mismatch")
    return accept_final(values)


if __name__ == "__main__":
    raise SystemExit(main())
'''


def derive_driver(v30_bytes: bytes) -> bytes:
    """Derive the complete two-command V31 driver from sealed V30 bytes."""

    require(
        len(v30_bytes) == V30_DRIVER_SIZE and sha256(v30_bytes) == V30_DRIVER_SHA256,
        "sealed V30 driver mismatch",
    )
    text = v30_bytes.decode("utf-8")
    text = text.replace("successor-v30-final-bindings.json", "successor-v30-preparation-bindings.json")
    future_upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    future_lower = "liveclip_future_version_lower"
    require(future_upper not in text and future_lower not in text, "transform sentinel collision")
    text = text.replace("V31", future_upper).replace("v31", future_lower)
    text = text.replace("V30", "V31").replace("v30", "v31")
    text = text.replace(future_upper, "V32").replace(future_lower, "v32")
    text = text.replace("range(31, 55)", "range(32, 55)")
    text = replace_once(
        text,
        'current_result_name = "successor-preparation-v" + "30-result.json"',
        'current_result_name = "successor-preparation-v" + "31-result.json"',
        "current result fixture",
    )
    text = replace_once(
        text,
        'future_result_name = "successor-preparation-v" + "31-result.json"',
        'future_result_name = "successor-preparation-v" + "32-result.json"',
        "future result fixture",
    )
    text = replace_once(
        text,
        'mutated_future_name = "successor-preparation-v" + "30-result.json"',
        'mutated_future_name = "successor-preparation-v" + "31-result.json"',
        "mutated result fixture",
    )
    text = replace_once(
        text,
        '"execute": [\n        "execute",',
        '"prepare": [\n        "prepare",',
        "prepare command surface",
    )
    text = replace_once(
        text,
        '        "--expected-root-prepare-argv-json-sha256", None,\n',
        "",
        "prepare sealed-root argv option removal",
    )
    text = replace_once(
        text,
        '    require(index["root_prepare_argv_json_sha256"] == values["expected_root_prepare_argv_json_sha256"], "root prepare argv hash mismatch")\n',
        "",
        "prepare sealed-root argv check removal",
    )
    shape_injection = '''\nSHAPES["accept-final"] = [\n    "accept-final", "--expected-self-sha", None, "--candidate", None,\n    "--run-id", None, "--offer-sha256", None,\n    "--controller-acceptance-json", None,\n    "--expected-current-plan-sha256", None,\n    "--expected-current-status-sha256", None,\n]\n'''
    text = replace_once(text, "\n\nPREDECESSORS = {", shape_injection + "\nPREDECESSORS = {", "accept-final shape")
    predecessor_injection = '''\nPREDECESSORS = dict(PREDECESSORS)\nPREDECESSORS["candidate.5nZWpynN"] = (0, 0, "0" * 64, "0" * 64)\n'''
    text = replace_once(text, "\n\nPROFILES = {", predecessor_injection + "\nPROFILES = {", "terminal predecessor")
    contracts = literal_assignment(text.encode("utf-8"), "CONTROLLER_CONTRACTS")
    require(isinstance(contracts, dict), "controller contract object is not a dictionary")
    contracts["candidate_allocation"]["expected_predecessors"] = sorted(EXPECTED_CANDIDATES)
    contracts["policy_toolchain"]["policy_contract"] = (
        "checked-in-loop-engineering-policy-plus-independent-document-generations-v31-"
        "relational-toolchain-binding-final-external-controller-acceptance"
    )
    contracts["trusted_context"]["context_authority_state"] = (
        "PREPARATION_OFFER_THEN_EXTERNAL_FINAL_ACCEPTANCE_REQUIRED"
    )
    contracts["trusted_context"]["final_acceptance_path"] = (
        ".loop/trusted/final-controller-acceptance-v31.json"
    )
    contracts["trusted_context"]["transport"] = (
        "root-acceptance-plus-candidate-offer-plus-exact-external-final-acceptance"
    )
    contract_hashes = {
        name: sha256(compact(value)) for name, value in contracts.items()
    }
    text = replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", contract_hashes)
    text = replace_once(
        text,
        "PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS = {",
        "PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS = {",
        "credential omission map anchor",
    )
    omission_anchor = "\n\n\ndef is_protected_credential_manifest_path("
    omission_update = '\nPREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS = dict(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS)\nPREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.5nZWpynN"] = 0\n\n\ndef is_protected_credential_manifest_path('
    text = replace_once(text, omission_anchor, omission_update, "terminal omission policy")
    text = text.replace(
        '"V27", "V28", "V29"}',
        '"V27", "V28", "V29", "V30"}',
    )
    text = text.replace(
        '"V26", "V27", "V28"}',
        '"V26", "V27", "V28", "V29", "V30"}',
    )
    receipt_anchor = '    "successor-v31-preparation-bindings.json",\n'
    require(text.count(receipt_anchor) >= 1, "preparation receipt anchor missing")
    text = text.replace(
        receipt_anchor,
        receipt_anchor + '    "successor-v31-controller-acceptance-offer.json",\n',
        1,
    )
    text = replace_once(text, "\n\ndef setup_argv(", OFFER_WRAPPER + "\n\ndef setup_argv(", "offer wrapper")
    text = replace_once(
        text,
        "def validate_predecessors(\n",
        "def _v31_legacy_validate_predecessors(\n",
        "legacy predecessor validator rename",
    )
    text = replace_once(text, "\ndef execute(values: dict[str, str]) -> int:", PREDECESSOR_OVERRIDE + "\n\ndef execute(values: dict[str, str]) -> int:", "predecessor override")
    text = text.replace(
        'values["expected_controller_acceptance_sha256"]',
        'values["expected_root_acceptance_sha256"]',
    ).replace(
        '"--expected-controller-acceptance-sha256"',
        '"--expected-root-acceptance-sha256"',
    )
    text = replace_once(
        text,
        'bindings["verdict"]\n            == "M3_SUCCESSOR_PREPARATION_V31_READY_FOR_CONTROLLER_REVIEW"',
        'bindings["verdict"]\n            == "M3_SUCCESSOR_PREPARATION_V31_AWAITING_CONTROLLER_ACCEPTANCE"',
        "prepare verdict",
    )
    text = replace_once(
        text,
        '"M3_SUCCESSOR_PREPARATION_V31_READY_FOR_CONTROLLER_REVIEW",\n            None,\n            frozen_preflight,',
        '"M3_SUCCESSOR_PREPARATION_V31_AWAITING_CONTROLLER_ACCEPTANCE",\n            None,\n            frozen_preflight,',
        "prepare seal verdict",
    )
    main_start = text.rfind("def main() -> int:\n")
    require(main_start >= 0, "main anchor missing")
    text = text[:main_start] + ACCEPT_FINAL + "\n\n" + MAIN_REPLACEMENT
    payload = text.encode("utf-8")
    tree = ast.parse(payload, filename="<m3s-v31-driver>")
    compile(tree, "<m3s-v31-driver>", "exec")
    return payload


def inspect_driver(payload: bytes) -> dict[str, Any]:
    tree = ast.parse(payload, filename="<m3s-v31-driver-static>")
    compile(tree, "<m3s-v31-driver-static>", "exec")
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    shapes = literal_assignment(payload, "SHAPES")
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
            and isinstance(node.targets[0].value, ast.Name)
            and node.targets[0].value.id == "SHAPES"
        ):
            key = ast.literal_eval(node.targets[0].slice)
            shapes[key] = ast.literal_eval(node.value)
    require(set(shapes) == {"prepare", "accept-final"}, "command surface mismatch")
    require(len(shapes["prepare"]) == 23 and len(shapes["accept-final"]) == 15, "command schema mismatch")
    require("prepare" in literals and "accept-final" in literals, "command literals missing")
    require("--last" not in literals and "resume_liveclip.sh" not in literals, "forbidden resume capability present")
    function_nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    function_lists = [item for function in function_nodes for item in ast.walk(function) if isinstance(item, ast.List)]
    mktemp_sites = sum(
        1
        for item in function_lists
        if item.elts
        and isinstance(item.elts[0], ast.Constant)
        and item.elts[0].value == "/usr/bin/mktemp"
    )
    loop_init_sites = sum(
        1
        for item in function_lists
        if len(item.elts) >= 2
        and isinstance(item.elts[0], ast.Constant)
        and item.elts[0].value == "/usr/bin/make"
        and isinstance(item.elts[1], ast.Constant)
        and item.elts[1].value == "loop-init"
    )
    require(mktemp_sites == 1, "mktemp executable site mismatch")
    require(loop_init_sites == 1, "loop-init executable site mismatch")
    require(payload.count(b"M3S_V31_FINAL_CONTROLLER_ACCEPTANCE") >= 2, "final acceptance phase missing")
    active = tuple(literal_assignment(payload, "ACTIVE_VERSIONED_PHASES"))
    require(len(active) == 14 and len(set(active)) == 14, "active phase set mismatch")
    exact = set(literals)
    suffixes = (
        "SOURCE_WRITE", "SELF_CHECK", "FINALIZE", "FINAL_INDEX",
        "WRITER_SELF_TEST", "AUTH_HANDOFF",
    )
    full = {
        *("M3S_V31_" + suffix for suffix in suffixes),
        "M3_SUCCESSOR_PREPARATION_V31",
        "M3_SUCCESSOR_PREPARATION_V31_PREFLIGHT",
        "M3_SUCCESSOR_PREPARATION_V31_FINAL_INDEX",
        "M3_SUCCESSOR_PREPARATION_V31_TOOLCHAIN_SNAPSHOT",
        "M3_SUCCESSOR_PREPARATION_V31_READY_FOR_CONTROLLER_REVIEW",
        "M3_SUCCESSOR_PREPARATION_V31_STOP",
        "M3_SUCCESSOR_PREPARATION_V31_PRESERVATION",
        "M3_SUCCESSOR_PREPARATION_V31_STOPPED",
        "M3_SUCCESSOR_DRY_RUN_V31_CAPTURE",
        "M3_SUCCESSOR_DRY_RUN_V31_VALIDATION",
    }
    require(set(active) == full - {"M3S_V31_WRITER_SELF_TEST", "M3S_V31_AUTH_HANDOFF"}, "active phase vocabulary mismatch")
    require(set(active) <= exact, "active phase literal missing")
    require(not (full - set(active)) & exact, "inactive phase literal present")
    future = {item.replace("V31", "V32") for item in full}
    require(not future & exact, "future phase literal present")
    require(not any(f"successor-preparation-v{version}-result.json".encode() in payload for version in range(32, 55)), "future result literal present")
    require("EXTERNAL_CONTROLLER" in literals, "external authority surface missing")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require(
        {name: sha256(compact(value)) for name, value in contracts.items()} == hashes,
        "controller contract hash mismatch",
    )
    require(
        contracts["candidate_allocation"]["expected_predecessors"]
        == sorted(EXPECTED_CANDIDATES),
        "controller predecessor set mismatch",
    )
    return {
        "accept_final_literal": True,
        "active_phase_count": len(active),
        "ast": "PASS",
        "credential_command_absent": True,
        "controller_contracts": hashes,
        "formal_dispatch_absent": True,
        "mktemp_count": mktemp_sites,
        "prepare_literal": True,
        "loop_init_count": loop_init_sites,
        "runtime_equivalent_phase_model": "PASS",
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    require(argv[:1] == ["--"], "root-only argv separator missing")
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--expected-status-sha256", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-driver-sha256", required=True)
    parser.add_argument("--expected-design-sha256", required=True)
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


def validate_terminal() -> dict[str, Any]:
    require(TARGET.is_dir() and not TARGET.is_symlink(), "terminal candidate unsafe")
    require(set(os.listdir(TARGET)) == {"home", "repo", "successor-receipts", "tmp"}, "terminal candidate entries mismatch")
    files = {
        relative: file_identity(TARGET / relative, size, digest, mode)
        for relative, (size, digest, mode) in TERMINAL_FILES.items()
    }
    state = json.loads((TARGET / f"repo/.loop/runs/{RUN_ID}/state.json").read_text(encoding="utf-8"))
    require(
        state["state"] == "blocked"
        and state["cycle"] == 2
        and state["code_cycle"] == 0
        and state["coder_session_id"] is None
        and state["command_results"] == []
        and state["last_error"] == "plan repair budget exhausted",
        "terminal state mismatch",
    )
    require(
        state["artifacts"] == {
            "planner": [
                f".loop/runs/{RUN_ID}/artifacts/planner/001.json",
                f".loop/runs/{RUN_ID}/artifacts/planner/002.json",
            ]
        },
        "terminal planner lineage mismatch",
    )
    return {"files": files, "protected_home_traversed": False, "state": state}


def build_acceptance(
    driver_bytes: bytes,
    *,
    plan_bytes: bytes,
    status_bytes: bytes,
    source_bytes: bytes,
    helper_bytes: bytes,
    plan_sha: str,
    status_sha: str,
    source_sha: str,
    driver_sha: str,
) -> tuple[bytes, dict[str, Any]]:
    contracts = literal_assignment(driver_bytes, "CONTROLLER_CONTRACTS")
    contract_hashes = literal_assignment(driver_bytes, "CONTROLLER_CONTRACT_HASHES")
    require(
        {name: sha256(compact(contract)) for name, contract in contracts.items()}
        == contract_hashes,
        "acceptance contract hashes mismatch",
    )
    value = {
        "authority": "EXTERNAL_CONTROLLER",
        "contract_objects": contracts,
        "contracts": contract_hashes,
        "documents": {
            "execplan": {
                "path": str(PLAN),
                "sha256": plan_sha,
                "size": len(plan_bytes),
            },
            "status": {
                "path": str(STATUS),
                "sha256": status_sha,
                "size": len(status_bytes),
            },
        },
        "driver": {
            "path": str(DRIVER),
            "sha256": driver_sha,
            "size": len(driver_bytes),
        },
        "format_version": 1,
        "phase": "M3S_V31_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": literal_assignment(
            driver_bytes, "PREVIOUS_M3S_V29_CLOSURE"
        ),
        "preparation_source": {
            "helper": {
                "path": str(
                    DELIVERY / "tools/loop_engineering/m3s_v31_source_freeze.py"
                ),
                "sha256": sha256(helper_bytes),
                "size": len(helper_bytes),
            },
            "sha256": source_sha,
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
    payload = compact(value) + b"\n"
    return payload, value


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
    require(args.expected_design_sha256 == DESIGN_SHA256, "design hash mismatch")
    require(sha256(source_bytes) == args.expected_source_sha256, "source hash mismatch")
    plan_bytes, _ = read_regular(PLAN)
    status_bytes, _ = read_regular(STATUS)
    require(sha256(plan_bytes) == args.expected_plan_sha256, "plan hash mismatch")
    require(sha256(status_bytes) == args.expected_status_sha256, "status hash mismatch")
    require(extract_once(plan_bytes, SOURCE_BEGIN, SOURCE_END) == source_bytes, "embedded source mismatch")
    v30_bytes, _ = read_regular(V30_DRIVER)
    driver_bytes = derive_driver(v30_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "derived driver hash mismatch")
    static = inspect_driver(driver_bytes)
    file_identity(V30_RESULT, V30_RESULT_SIZE, V30_RESULT_SHA256, 0o600)
    file_identity(V30_FINAL_INDEX, V30_FINAL_INDEX_SIZE, V30_FINAL_INDEX_SHA256, 0o600)
    file_identity(WRAPPER, WRAPPER_SIZE, WRAPPER_SHA256, 0o600)
    terminal = validate_terminal()
    candidates = tuple(
        sorted(
            (path.name for path in BASE.iterdir() if path.name.startswith("candidate.")),
            key=os.fsencode,
        )
    )
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    require(not ROOT.exists() and not ROOT.is_symlink(), "V31 root exists")
    acceptance_bytes, acceptance = build_acceptance(
        driver_bytes,
        plan_bytes=plan_bytes,
        status_bytes=status_bytes,
        source_bytes=source_bytes,
        helper_bytes=helper_bytes,
        plan_sha=args.expected_plan_sha256,
        status_sha=args.expected_status_sha256,
        source_sha=args.expected_source_sha256,
        driver_sha=args.expected_driver_sha256,
    )
    root_argv = [
        "/opt/homebrew/bin/python3.12",
        "-c",
        source_bytes.decode("utf-8"),
        *raw_argv,
    ]
    require(len(root_argv) == 18, "root-only argv count mismatch")
    root_argv_sha256 = sha256(
        json.dumps(
            root_argv,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v31.json", acceptance_bytes)
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        pretty({
            "acceptance": acceptance_identity,
            "design_sha256": DESIGN_SHA256,
            "documents": {"execplan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256},
            "driver": driver,
            "format_version": 1,
            "helper_sha256": sha256(helper_bytes),
            "phase": "M3S_V31_SOURCE_WRITE",
            "preparation_source_sha256": args.expected_source_sha256,
            "result": "PASS",
            "root_prepare_argv_json_sha256": root_argv_sha256,
        }),
    )
    writer_self_test = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        pretty({
            "error": None,
            "format_version": 1,
            "no_replace": True,
            "phase": "M3S_V31_WRITER_SELF_TEST",
            "result": "PASS",
        }),
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        pretty({
            "candidate_count": len(candidates),
            "design_sha256": DESIGN_SHA256,
            "driver": driver,
            "format_version": 1,
            "phase": "M3S_V31_SELF_CHECK",
            "result": "PASS",
            "root_result_absent": True,
            "static": static,
            "terminal": terminal,
        }),
    )
    final_index = write_exclusive(
        RECEIPTS / "final-index.json",
        pretty({
            "controller_acceptance": acceptance_identity,
            "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256},
            "driver": driver,
            "files": {
                "self-check-result.json": self_check,
                "source-receipt.json": source_receipt,
                "writer-self-test.json": writer_self_test,
            },
            "format_version": 1,
            "phase": "M3S_V31_FINAL_INDEX",
            "root_prepare_argv_json_sha256": root_argv_sha256,
            "reserved_results_absent": [
                "successor-preparation-v31-result.json",
                "final-controller-acceptance-v31-result.json",
            ],
            "verdict": "M3S_V31_READY_FOR_CONTROLLER_REVIEW",
        }),
    )
    require(
        set(os.listdir(ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}
        and set(os.listdir(RECEIPTS))
        == {
            "controller-acceptance-v31.json",
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
        compact({
            "driver": driver,
            "final_index": final_index,
            "phase": "M3S_V31_ROOT_ONLY",
            "result": "M3S_V31_READY_FOR_CONTROLLER_REVIEW",
        }) + b"\n",
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
