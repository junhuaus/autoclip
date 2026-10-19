#!/usr/bin/env python3
"""Design and future root-only writer for the credential-blind M3A-v7 root.

Static mode derives every non-secret artifact and command identity without
creating the root.  The future writer has three ordered commands: transport,
self-check, and finalize.  Authentication is implemented only by the derived
sealed driver and is never invoked by this helper's static mode or root phases.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pprint
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


DELIVERY = Path("/Users/junhuaxu/autoclip")
PLAN = DELIVERY / "docs/exec-plans/liveclip-agent-runtime-v2.md"
STATUS = DELIVERY / "STATUS.md"
HELPER = DELIVERY / "tools/loop_engineering/m3a_v7_source_freeze.py"
ARCHITECTURE = DELIVERY / "docs/liveclip-architecture.html"
REQUIREMENT_V2 = DELIVERY / "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md"
REQUIREMENT_V3 = DELIVERY / "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md"
RUFF = DELIVERY / ".venv/bin/ruff"
PYTHON = Path("/opt/homebrew/bin/python3.12")
BASE = Path(
    "/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/"
    "agent-runtime-v2/a822890ace12"
)
SEED_REPO = BASE / "candidate.OlsWg1/repo"
TARGET = BASE / "candidate.3Wlu7MyG"
TARGET_REPO = TARGET / "repo"
RUN_ID = "20261016T010806Z-b7f48207"
RUN = TARGET_REPO / ".loop/runs" / RUN_ID
V44_ROOT = BASE / "trusted-tools/m3-successor-preparation-v44"
V6_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v6"
V6_DRIVER = V6_ROOT / "handoff-driver.py"
V6_RESULT = V6_ROOT / "receipts/auth-handoff-v6-result.json"
V7_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v7"
V7_DRIVER = V7_ROOT / "handoff-driver.py"
V7_RECEIPTS = V7_ROOT / "receipts"
V7_RESULT = V7_RECEIPTS / "auth-handoff-v7-result.json"
WRITER_BEGIN = "# BEGIN M3A_V7_WRITER_SOURCE\n"
WRITER_END = "# END M3A_V7_WRITER_SOURCE\n"

EXPECTED_HEAD = "2f361fcddc0e63ae62ee62826e27b54bb8204c53"
EXPECTED_DELIVERY = (0, 15, 178)
EXPECTED_TARGET = (0, 15, 74)
EXPECTED_ARCHITECTURE = (
    66116,
    "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce",
)
EXPECTED_REQUIREMENT_V2 = (
    8771,
    "31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400",
)
EXPECTED_REQUIREMENT_V3 = (
    12289,
    "308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00",
)
EXPECTED_V6_DRIVER = (
    31499,
    "20c4c9afcba559625b0185308eb1a88844fc78fbc2bafe4e34adf8540e041a68",
)
EXPECTED_V6_RESULT = (
    261,
    "def12fc3c49b6016013291557e8b9c2171b63e97f2c0c5c6bd06556961b94bf4",
)
EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO",
    "candidate.3WBt3ldA",
    "candidate.3Wlu7MyG",
    "candidate.5jh3bylk",
    "candidate.5nZWpynN",
    "candidate.CbYcDirN",
    "candidate.CrvNTqvL",
    "candidate.KWbe2iGW",
    "candidate.M4v94Rmv",
    "candidate.OlsWg1",
    "candidate.Q2vecg",
    "candidate.UU7EAiJG",
    "candidate.VoU5SVVl",
    "candidate.aw2oA4",
    "candidate.bSEqMEit",
    "candidate.bm4AWiof",
    "candidate.c79YYSLQ",
    "candidate.cQnaAbOf",
    "candidate.dygENR4n",
    "candidate.iyme1x_i",
    "candidate.jyq_n37h",
    "candidate.mRMO7MQ6",
    "candidate.o99gfxup",
    "candidate.oivrdV6U",
    "candidate.qaDKDWkQ",
    "candidate.vuDWtK0T",
    "candidate.xp23hqNY",
    "candidate.z6EbTJew",
)
V44_ROOT_FILES: dict[str, tuple[int, str]] = {
    "candidate-driver.py": (
        538746,
        "d6d2141d37275259491ea79bbef10d12d1cd02d4152bf6505a3c273986ccf850",
    ),
    "receipts/controller-acceptance-v44.json": (
        18147,
        "c573fcdb80d07d9bd320cfd0ad0141206675b2b6ced3b34e55212ab50ba76626",
    ),
    "receipts/final-index.json": (
        2000,
        "1f44d31dec228076da80768ec87d493860c82bfc14248db678d2e4a1a9df6ca5",
    ),
    "receipts/self-check-result.json": (
        7012,
        "a14df6d41caf7d062258efc873f4c666f68a4e5be842e5d4a0a1b64778f785ac",
    ),
    "receipts/source-receipt.json": (
        524,
        "6ca3814d8490701e8105a021301644e139872d06bad0eebb7c247e7bc698831d",
    ),
    "receipts/successor-preparation-v44-result.json": (
        23851,
        "ba1b1878ad5e940ac145aa14b48e5621ea4b824dc73b6d8fccd6913a90c8546e",
    ),
    "receipts/writer-self-test.json": (
        72,
        "2152b25df8eb1201f681037632107a92a665d81b1c9b47058ca81148930298cd",
    ),
}
TARGET_FILES: dict[str, tuple[int, str, int]] = {
    f"repo/.loop/runs/{RUN_ID}/events.jsonl": (
        144,
        "f3b0b329f25891455f9e00377e8eaa02f185fa569131cc347de0fa54b7e43439",
        0o644,
    ),
    f"repo/.loop/runs/{RUN_ID}/state.json": (
        12796,
        "88f7be523d08def41b8abf3ff6be418b90d4955c1c9c1edf8a29396a0a739af2",
        0o644,
    ),
    "repo/.loop/trusted/final-controller-acceptance-v44.json": (
        5132,
        "0baec92ac199860c9811b9516e8edc3a2ea11ffd73a8dce175ab832cc2dc67f4",
        0o600,
    ),
    "successor-receipts/final-receipt-index.json": (
        18096,
        "4afaf3c7819498433cb5263c0c60ab6c97c1ca6f3c731c2fd73c90cad4051fbc",
        0o600,
    ),
    "successor-receipts/postacceptance-attempt-manifest.jsonl": (
        12183983,
        "f476ba94207b25161551f773a90436d4d6c325d6dcd238c63b3ec108c870fe0d",
        0o600,
    ),
    "successor-receipts/postacceptance-final-index.json": (
        2731,
        "10591eed8097571f8662b9a3ad05aeb0164aeebf2682610b4bd72bd317b07150",
        0o600,
    ),
    "successor-receipts/postacceptance-repository-manifest.jsonl": (
        6146003,
        "373c4fd19ff20ca1932222a8cb26cbb3e726fea441444ea91a27cf15cf6a1f93",
        0o600,
    ),
    "successor-receipts/successor-v44-controller-acceptance-offer.json": (
        5801,
        "100c87a96d06970939e2c0cdb1ccd6d7777bbf1eb8d4426f780bc6c181053dd8",
        0o600,
    ),
    "successor-receipts/successor-v44-controller-acceptance-transport.json": (
        1383,
        "b8a7d265dd77eb1171c97e3fd270bd000d09992169e6340788c5b16e8a433b28",
        0o600,
    ),
    "successor-receipts/successor-v44-policy-snapshot.json": (
        4828,
        "162392f08256d8acb8ffb488b981f80e33035a0e96b615cd1583a1201a39baf2",
        0o600,
    ),
    "successor-receipts/successor-v44-preparation-bindings.json": (
        5414,
        "b15134f22f25bb216a07c66fab39639b54f67f726ef414ab17a3926c5a3fb7ab",
        0o600,
    ),
    "successor-receipts/successor-v44-toolchain-snapshot.json": (
        4878,
        "bef168bb6289b53ea0c03611dd4e565503f50b3938232d2d615c4724114ab8f5",
        0o600,
    ),
    "successor-receipts/successor-v44-trusted-context.json": (
        12088,
        "c9a355391dc998e63d4b9cfc5fe5d669b86db0658b604be1383c930c2926cc87",
        0o600,
    ),
}

ROOT_RECEIPT_FILES = {
    "controller-acceptance-v7.json",
    "final-index.json",
    "self-check-result.json",
    "source-receipt.json",
    "writer-self-test.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def pretty(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def read_regular(path: Path) -> tuple[bytes, os.stat_result]:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), f"regular file required: {path}")
    with path.open("rb") as handle:
        payload = handle.read()
        opened = os.fstat(handle.fileno())
    require(
        (info.st_dev, info.st_ino, info.st_size)
        == (opened.st_dev, opened.st_ino, opened.st_size),
        f"file changed while reading: {path}",
    )
    return payload, opened


def exact_file(path: Path, expected: tuple[int, str], mode: int | None = None) -> bytes:
    payload, info = read_regular(path)
    require((len(payload), sha(payload)) == expected, f"identity mismatch: {path}")
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode and info.st_uid == os.getuid(), f"mode mismatch: {path}")
    return payload


def private_directory(path: Path) -> None:
    info = path.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        f"private directory mismatch: {path}",
    )


def git_capture(repo: Path, args: list[str]) -> bytes:
    result = subprocess.run(  # noqa: S603 - fixed git executable and caller-owned literals
        ["/usr/bin/git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "GIT_OPTIONAL_LOCKS": "0",
        },
    )
    require(result.returncode == 0 and not result.stderr, "git correlation failed")
    return result.stdout


def status_counts(repo: Path) -> tuple[int, int, int]:
    lines = git_capture(repo, ["status", "--short", "--untracked-files=all"]).decode().splitlines()
    staged = sum(1 for line in lines if line and line[0] not in {" ", "?"})
    modified = sum(
        1 for line in lines if not line.startswith("??") and len(line) > 1 and line[1] != " "
    )
    untracked = sum(1 for line in lines if line.startswith("??"))
    return staged, modified, untracked


def validate_git(repo: Path, expected: tuple[int, int, int]) -> None:
    require(git_capture(repo, ["rev-parse", "--abbrev-ref", "HEAD"]) == b"main\n", "branch mismatch")
    require(git_capture(repo, ["rev-parse", "HEAD"]).decode().strip() == EXPECTED_HEAD, "HEAD mismatch")
    require(status_counts(repo) == expected, "inventory mismatch")


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(text):
        if character == "\n":
            offsets.append(index + 1)
    return offsets


def _span(node: ast.AST, offsets: list[int]) -> tuple[int, int]:
    require(getattr(node, "end_lineno", None) is not None, "AST span unavailable")
    return (
        offsets[node.lineno - 1] + node.col_offset,
        offsets[node.end_lineno - 1] + node.end_col_offset,
    )


def function_source(payload: bytes, name: str) -> bytes:
    text = payload.decode()
    tree = ast.parse(text)
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"function count mismatch: {name}")
    start, end = _span(matches[0], _line_offsets(text))
    return text[start:end].encode()


def _assignment_name(node: ast.Assign) -> str | None:
    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def _replace_nodes(text: str, replacements: dict[str, str]) -> str:
    tree = ast.parse(text)
    offsets = _line_offsets(text)
    edits: list[tuple[int, int, str]] = []
    found: set[str] = set()
    for node in tree.body:
        key = _assignment_name(node) if isinstance(node, ast.Assign) else None
        if isinstance(node, ast.FunctionDef):
            key = node.name
        if key in replacements:
            require(key not in found, f"duplicate node: {key}")
            start, end = _span(node, offsets)
            edits.append((start, end, replacements[key]))
            found.add(key)
    require(found == set(replacements), "replacement node mismatch")
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def assignment(name: str, value: Any) -> str:
    return f"{name} = {pprint.pformat(value, width=118, sort_dicts=True)}"


def handoff_contract() -> dict[str, Any]:
    candidate_names_sha = sha(compact(list(EXPECTED_CANDIDATES)))
    return {
        "bounds": {
            "diagnostic_bytes": 65536,
            "login_status_seconds": 30,
            "outer_seconds": 120,
            "sanitized_stdout_bytes": 4096,
        },
        "budgets": {
            "destination": 1,
            "handoff_invocation": 1,
            "result": 1,
            "root_finalize": 1,
            "root_self_check": 1,
            "root_transport": 1,
        },
        "candidate": {
            "candidate_count": 28,
            "completed_tree": {
                "bytes": 967904492,
                "paths": 44355,
                "sha256": "aca8090a0b4da7967fc57e8b210400a064eec6e3bc7e67f44d0f00399412f14d",
            },
            "final_acceptance_sha256": TARGET_FILES[
                "repo/.loop/trusted/final-controller-acceptance-v44.json"
            ][1],
            "final_index_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-final-index.json"
            ][1],
            "name": TARGET.name,
            "run_id": RUN_ID,
            "sealed_receipt_index_sha256": TARGET_FILES[
                "successor-receipts/final-receipt-index.json"
            ][1],
        },
        "delivery": {
            "branch": "main",
            "candidate_inventory": list(EXPECTED_TARGET),
            "candidate_names_sha256": candidate_names_sha,
            "head": EXPECTED_HEAD,
            "inventory": list(EXPECTED_DELIVERY),
        },
        "environment_names": [
            "HOME",
            "TMPDIR",
            "PATH",
            "LANG",
            "LC_ALL",
            "PYTHONDONTWRITEBYTECODE",
            "GIT_OPTIONAL_LOCKS",
            "__CF_USER_TEXT_ENCODING",
        ],
        "evidence": {
            "acceptance_requirement_v2_sha256": EXPECTED_REQUIREMENT_V2[1],
            "acceptance_requirement_v3_sha256": EXPECTED_REQUIREMENT_V3[1],
            "architecture_sha256": EXPECTED_ARCHITECTURE[1],
            "controller_transport_sha256": TARGET_FILES[
                "successor-receipts/successor-v44-controller-acceptance-transport.json"
            ][1],
            "postacceptance_attempt_manifest_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-attempt-manifest.jsonl"
            ][1],
            "postacceptance_repository_manifest_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-repository-manifest.jsonl"
            ][1],
            "preparation_bindings_sha256": TARGET_FILES[
                "successor-receipts/successor-v44-preparation-bindings.json"
            ][1],
            "preparation_offer_sha256": TARGET_FILES[
                "successor-receipts/successor-v44-controller-acceptance-offer.json"
            ][1],
            "root_final_index_sha256": V44_ROOT_FILES["receipts/final-index.json"][1],
            "successor_policy_sha256": TARGET_FILES[
                "successor-receipts/successor-v44-policy-snapshot.json"
            ][1],
            "successor_toolchain_sha256": TARGET_FILES[
                "successor-receipts/successor-v44-toolchain-snapshot.json"
            ][1],
            "successor_trusted_context_sha256": TARGET_FILES[
                "successor-receipts/successor-v44-trusted-context.json"
            ][1],
        },
        "formal_role_authority": False,
        "format_version": 1,
        "phase": "M3A_V7_AUTH_HANDOFF",
        "pinned_status": {
            "argv": ["login", "status"],
            "binary_sha256": "12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de",
            "binary_size": 245096256,
            "child_channels": "DEVNULL",
            "timeout_seconds": 30,
        },
        "privacy": {
            "child_channels": "DEVNULL",
            "credential_environment_variables": False,
            "destination_observation": "UNPROBED_EXCLUSIVE_GATE_INSIDE_HANDOFF",
            "opaque_copy": True,
            "protected_entry_omitted_before_metadata": True,
            "raw_diagnostics": False,
            "receipt_fields": [
                "copy_success",
                "destination_mode",
                "destination_owner_uid",
                "format_version",
                "login_status",
                "phase",
                "result",
                "sanitized_error",
            ],
            "secret_derived_metadata": False,
        },
        "private_runtime": {"home_mode": "0700", "owner_uid": 501, "tmp_mode": "0700"},
        "run": {
            "code_cycle": 0,
            "cycle": 0,
            "events_sha256": TARGET_FILES[f"repo/.loop/runs/{RUN_ID}/events.jsonl"][1],
            "state": "received",
            "state_sha256": TARGET_FILES[f"repo/.loop/runs/{RUN_ID}/state.json"][1],
        },
        "v44": {
            "driver_sha256": V44_ROOT_FILES["candidate-driver.py"][1],
            "final_acceptance_sha256": TARGET_FILES[
                "repo/.loop/trusted/final-controller-acceptance-v44.json"
            ][1],
            "final_index_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-final-index.json"
            ][1],
            "preparation_result_sha256": V44_ROOT_FILES[
                "receipts/successor-preparation-v44-result.json"
            ][1],
        },
    }


def derive_driver(predecessor_payload: bytes) -> bytes:
    require((len(predecessor_payload), sha(predecessor_payload)) == EXPECTED_V6_DRIVER, "V6 driver mismatch")
    text = predecessor_payload.decode()
    replacements = (
        ("M3A_V6", "M3A_V7", 5),
        ("m3-authentication-handoff-v6", "m3-authentication-handoff-v7", 2),
        ("auth-handoff-v6-result.json", "auth-handoff-v7-result.json", 1),
        ("controller-acceptance-v6.json", "controller-acceptance-v7.json", 2),
        ("candidate.CbYcDirN", "candidate.3Wlu7MyG", 3),
        ("20261015T231933Z-6eee7fff", RUN_ID, 4),
        ("v43", "v44", 16),
        ("V43", "V44", 11),
    )
    for old, new, count in replacements:
        require(text.count(old) == count, f"driver transform count mismatch: {old}")
        text = text.replace(old, new)
    text = _replace_nodes(
        text,
        {
            "EXPECTED_DELIVERY": assignment("EXPECTED_DELIVERY", EXPECTED_DELIVERY),
            "EXPECTED_TARGET": assignment("EXPECTED_TARGET", EXPECTED_TARGET),
            "EXPECTED_CANDIDATES": assignment("EXPECTED_CANDIDATES", set(EXPECTED_CANDIDATES)),
            "V44_FILES": assignment("V44_FILES", V44_ROOT_FILES),
            "TARGET_FILES": assignment("TARGET_FILES", TARGET_FILES),
            "HANDOFF_CONTRACT": assignment("HANDOFF_CONTRACT", handoff_contract()),
        },
    )
    payload = text.encode()
    compile(payload, "<m3a-v7-driver>", "exec", dont_inherit=True)
    return payload


def static_driver_validation(predecessor: bytes, driver: bytes) -> dict[str, Any]:
    tree = ast.parse(driver)
    compile(driver, "<m3a-v7-driver>", "exec", dont_inherit=True)
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    required = {
        "opaque_copy_state",
        "terminate_group",
        "login_status",
        "receipt",
        "validate_root",
        "validate_v44_and_target",
    }
    require(required <= names and "validate_v43_and_target" not in names, "driver phase surface mismatch")
    require(driver.count(b"M3A_V7_AUTH_HANDOFF") == 2, "V7 phase count mismatch")
    require(b"M3A_V6_AUTH_HANDOFF" not in driver, "stale active phase")
    require(b"controller-acceptance-v7.json" in driver, "V7 root receipt missing")
    for forbidden in (b"loop-run", b"--last", b"resume_liveclip.sh"):
        require(forbidden not in driver, "forbidden driver surface")
    equivalence: dict[str, str] = {}
    for name in ("opaque_copy_state", "terminate_group", "login_status", "receipt"):
        old = function_source(predecessor, name)
        new = function_source(driver, name).replace(b"M3A_V7", b"M3A_V6")
        require(new == old, f"security source equivalence mismatch: {name}")
        equivalence[name] = sha(new)
    opaque = function_source(driver, "opaque_copy_state")
    for operation in (b"lstat", b"os.open", b"os.fstat", b"os.read", b"os.write", b"os.fsync"):
        require(operation in opaque, f"opaque operation missing: {operation.decode()}")
    login = function_source(driver, "login_status")
    require(login.count(b"subprocess.DEVNULL") == 3 and b"shell=False" in login, "child channel mismatch")
    require(b"timeout=30" in login, "login timeout mismatch")
    early = function_source(driver, "validate_v44_and_target")
    require(b"AUTH_SOURCE" not in early and b"AUTH_DESTINATION" not in early, "protected entry referenced early")
    return {"ast_compile": "PASS", "equivalent_security_functions": equivalence, "result": "PASS"}


def ruff_validation(driver: bytes) -> dict[str, Any]:
    exact_file(RUFF, (RUFF.stat().st_size, sha(RUFF.read_bytes())))
    result = subprocess.run(  # noqa: S603 - pinned project-local Ruff
        [str(RUFF), "check", "--select", "F,B,S", "--stdin-filename", "handoff-driver.py", "-"],
        input=driver,
        stdin=None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
        cwd=DELIVERY,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    require(result.returncode == 0, "Ruff F/B/S failed")
    return {"returncode": 0, "stderr_sha256": sha(result.stderr), "stdout_sha256": sha(result.stdout)}


def writer_source(helper_payload: bytes) -> bytes:
    source = f'''from __future__ import annotations
import hashlib
import importlib.util
import sys
from pathlib import Path

HELPER = Path({str(HELPER)!r})
EXPECTED_HELPER_SIZE = {len(helper_payload)}
EXPECTED_HELPER_SHA256 = {sha(helper_payload)!r}
payload = HELPER.read_bytes()
if len(payload) != EXPECTED_HELPER_SIZE or hashlib.sha256(payload).hexdigest() != EXPECTED_HELPER_SHA256:
    raise RuntimeError("M3A-v7 helper identity mismatch")
spec = importlib.util.spec_from_file_location("m3a_v7_source_freeze", HELPER)
if spec is None or spec.loader is None:
    raise RuntimeError("M3A-v7 helper loader unavailable")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if sys.argv[:2] != ["-c", "--"]:
    raise RuntimeError("M3A-v7 Python -c argv shape mismatch")
module.root_dispatch(sys.argv[2:])
'''
    payload = source.encode()
    compile(payload, "<m3a-v7-writer>", "exec", dont_inherit=True)
    return payload


def extract_writer(plan_payload: bytes) -> bytes:
    text = plan_payload.decode()
    require(text.count(WRITER_BEGIN) == 1 and text.count(WRITER_END) == 1, "writer marker count mismatch")
    return text.split(WRITER_BEGIN, 1)[1].split(WRITER_END, 1)[0].encode()


def controller_acceptance(
    plan: bytes,
    status: bytes,
    helper: bytes,
    writer: bytes,
    driver: bytes,
    contract: bytes,
) -> dict[str, Any]:
    return {
        "contract": {"canonical_bytes": len(contract), "sha256": sha(contract)},
        "documents": {
            "exec_plan": {"bytes": len(plan), "sha256": sha(plan)},
            "status": {"bytes": len(status), "sha256": sha(status)},
        },
        "driver": {"bytes": len(driver), "sha256": sha(driver)},
        "format_version": 1,
        "helper": {"bytes": len(helper), "sha256": sha(helper)},
        "phase": "M3A_V7_CONTROLLER_ACCEPTANCE",
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": {"fixed_name": V7_ROOT.name, "no_replace": True, "result_absent": True, "root_absent": True},
        "security": {
            "credential_blind_root_phases": ["transport", "self-check", "finalize"],
            "destination_precondition": "UNPROBED_EXCLUSIVE_GATE_INSIDE_HANDOFF",
            "formal_role_authority": False,
            "login_status_launched": False,
        },
        "target": {"candidate": TARGET.name, "run_id": RUN_ID, "v44_final_index_sha256": TARGET_FILES["successor-receipts/postacceptance-final-index.json"][1]},
        "writer": {"bytes": len(writer), "sha256": sha(writer)},
    }


def static_contract_validation(payload: bytes) -> dict[str, Any]:
    expected = handoff_contract()
    require(payload == compact(expected) and json.loads(payload) == expected, "contract mismatch")
    mutations: tuple[tuple[str, Any], ...] = (
        ("phase", "M3A_V6_AUTH_HANDOFF"),
        ("formal_role_authority", True),
        ("candidate.name", "candidate.CbYcDirN"),
        ("candidate.candidate_count", 27),
        ("candidate.final_index_sha256", "0" * 64),
        ("delivery.inventory", [0, 15, 177]),
        ("privacy.opaque_copy", False),
        ("privacy.child_channels", "PIPE"),
        ("privacy.secret_derived_metadata", True),
        ("budgets.handoff_invocation", 2),
        ("bounds.login_status_seconds", 31),
        ("v44.final_index_sha256", "0" * 64),
    )
    for dotted, value in mutations:
        candidate = json.loads(json.dumps(expected))
        current = candidate
        parts = dotted.split(".")
        for part in parts[:-1]:
            current = current[part]
        current[parts[-1]] = value
        require(compact(candidate) != payload, f"ineffective contract negative: {dotted}")
    return {"negative_fixtures": len(mutations), "positive": "PASS"}


def static_acceptance_validation(
    acceptance: dict[str, Any],
    plan: bytes,
    status: bytes,
    helper: bytes,
    writer: bytes,
    driver: bytes,
    contract: bytes,
) -> dict[str, Any]:
    expected = controller_acceptance(plan, status, helper, writer, driver, contract)
    require(acceptance == expected, "acceptance mismatch")
    mutations = (
        ("phase", "M3A_V6_CONTROLLER_ACCEPTANCE"),
        ("result", "READY"),
        ("target.candidate", "candidate.CbYcDirN"),
        ("target.run_id", "20261015T231933Z-6eee7fff"),
        ("target.v44_final_index_sha256", "0" * 64),
        ("root.fixed_name", "m3-authentication-handoff-v6"),
        ("root.root_absent", False),
        ("security.formal_role_authority", True),
        ("security.login_status_launched", True),
        ("writer.sha256", "0" * 64),
    )
    for dotted, value in mutations:
        candidate = json.loads(json.dumps(expected))
        current = candidate
        parts = dotted.split(".")
        for part in parts[:-1]:
            current = current[part]
        current[parts[-1]] = value
        require(candidate != expected, f"ineffective acceptance negative: {dotted}")
    return {"negative_fixtures": len(mutations), "positive": "PASS"}


def validate_process_absence() -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 - fixed read-only process query
        ["/bin/ps", "-axo", "command="],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"},
    )
    require(result.returncode == 0 and not result.stderr, "process query failed")
    prohibited = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        try:
            argv = shlex.split(line)
        except ValueError:
            continue
        if not argv:
            continue
        executable = Path(argv[0]).name
        if (
            (executable == "make" and len(argv) > 1 and argv[1] == "loop-run")
            or executable == "resume_liveclip.sh"
            or ("auth-handoff" in argv and any(Path(value).name == "handoff-driver.py" for value in argv))
        ):
            prohibited.append(line)
    require(not prohibited, "prohibited process present")
    return {"result": "PASS"}


def validate_nonsecret_evidence(*, require_root_absent: bool = True) -> dict[str, Any]:
    validate_git(DELIVERY, EXPECTED_DELIVERY)
    validate_git(TARGET_REPO, EXPECTED_TARGET)
    exact_file(ARCHITECTURE, EXPECTED_ARCHITECTURE)
    exact_file(REQUIREMENT_V2, EXPECTED_REQUIREMENT_V2)
    exact_file(REQUIREMENT_V3, EXPECTED_REQUIREMENT_V3)
    exact_file(V6_DRIVER, EXPECTED_V6_DRIVER, 0o600)
    exact_file(V6_RESULT, EXPECTED_V6_RESULT, 0o600)
    private_directory(V44_ROOT)
    for relative, expected in V44_ROOT_FILES.items():
        exact_file(V44_ROOT / relative, expected, 0o600)
    for relative, (size, digest, mode) in TARGET_FILES.items():
        exact_file(TARGET / relative, (size, digest), mode)
    state = json.loads(read_regular(RUN / "state.json")[0])
    require(
        state.get("run_id") == RUN_ID
        and state.get("state") == "received"
        and state.get("cycle") == 0
        and state.get("code_cycle") == 0
        and state.get("coder_session_id") is None
        and state.get("last_error") is None
        and state.get("artifacts") == {}
        and state.get("command_results") == [],
        "run not pristine",
    )
    candidates = tuple(
        sorted(
            path.name
            for path in BASE.iterdir()
            if path.name.startswith("candidate.") and path.is_dir() and not path.is_symlink()
        )
    )
    require(candidates == EXPECTED_CANDIDATES, "candidate set mismatch")
    if require_root_absent:
        require(not V7_ROOT.exists() and not V7_ROOT.is_symlink(), "V7 root already exists")
    require(not V7_RESULT.exists() and not V7_RESULT.is_symlink(), "V7 result already exists")
    require(
        not (V44_ROOT / "receipts/final-controller-acceptance-v44-result.json").exists()
        and not (V44_ROOT / "receipts/auth-handoff-v44-result.json").exists(),
        "V44 reserved result exists",
    )
    return {
        "authentication_location_probe": False,
        "candidate_count": len(candidates),
        "delivery_inventory": list(status_counts(DELIVERY)),
        "process_absence": validate_process_absence(),
        "result_absent": True,
        "root_absent": require_root_absent,
        "run_pristine": True,
        "target_inventory": list(status_counts(TARGET_REPO)),
        "v44_postacceptance": "PASS",
        "v6_nonreuse": "PASS",
    }


def validate_documents(plan: bytes, status: bytes, helper: bytes) -> dict[str, Any]:
    required = (
        "candidate.3Wlu7MyG",
        RUN_ID,
        TARGET_FILES["successor-receipts/postacceptance-final-index.json"][1],
        "M3S_V44_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW",
        "m3-authentication-handoff-v7",
        "M3A_V7_ROOT_TRANSPORT",
        "M3A_V7_ROOT_SELF_CHECK",
        "M3A_V7_ROOT_FINALIZE",
        "authentication is not formal",
    )
    for label, payload in (("plan", plan), ("status", status)):
        text = payload.decode()
        for value in required:
            require(value in text, f"{label} missing {value}")
        require(text.endswith("\n"), f"{label} missing final newline")
        require(text.count("```" ) % 2 == 0, f"{label} fence mismatch")
    expected_writer = writer_source(helper)
    require(extract_writer(plan) == expected_writer, "embedded writer mismatch")
    return {"headings": "PASS", "markers": "PASS", "writer": "PASS"}


def derive_all(plan: bytes, status: bytes, helper: bytes) -> dict[str, Any]:
    writer = writer_source(helper)
    predecessor = exact_file(V6_DRIVER, EXPECTED_V6_DRIVER, 0o600)
    driver = derive_driver(predecessor)
    contract = compact(handoff_contract())
    acceptance = controller_acceptance(plan, status, helper, writer, driver, contract)
    acceptance_payload = compact(acceptance) + b"\n"
    return {
        "acceptance": acceptance,
        "acceptance_payload": acceptance_payload,
        "acceptance_validation": static_acceptance_validation(
            acceptance, plan, status, helper, writer, driver, contract
        ),
        "contract": contract,
        "contract_validation": static_contract_validation(contract),
        "driver": driver,
        "driver_validation": static_driver_validation(predecessor, driver),
        "ruff": ruff_validation(driver),
        "writer": writer,
    }


def phase_arguments(phase: str, plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]) -> list[str]:
    common = [
        "--expected-plan-sha256",
        sha(plan),
        "--expected-status-sha256",
        sha(status),
        "--expected-writer-sha256",
        sha(derived["writer"]),
        "--expected-helper-sha256",
        sha(helper),
        "--expected-driver-sha256",
        sha(derived["driver"]),
        "--expected-contract-sha256",
        sha(derived["contract"]),
    ]
    acceptance_sha = sha(derived["acceptance_payload"])
    if phase == "transport":
        return [phase, *common, "--controller-acceptance-json", compact(derived["acceptance"]).decode()]
    if phase == "self-check":
        return [phase, *common, "--expected-controller-acceptance-sha256", acceptance_sha]
    require(phase == "finalize", "unknown phase")
    self_check = self_check_payload(plan, status, helper, derived)
    writer_test = writer_test_payload()
    return [
        phase,
        *common,
        "--expected-controller-acceptance-sha256",
        acceptance_sha,
        "--expected-self-check-sha256",
        sha(self_check),
        "--expected-writer-self-test-sha256",
        sha(writer_test),
    ]


def quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def command_identity(argv: list[str]) -> dict[str, Any]:
    argv_payload = compact(argv)
    env = [
        "/usr/bin/env",
        "-i",
        f"HOME={V7_ROOT / 'home'}",
        f"TMPDIR={V7_ROOT / 'tmp'}",
        "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "PYTHONDONTWRITEBYTECODE=1",
        "GIT_OPTIONAL_LOCKS=0",
        "__CF_USER_TEXT_ENCODING=0x1F5:0x0:0x0",
        *argv,
    ]
    vector_payload = compact(env)
    payload = "exec " + " ".join(quote(value) for value in env) + " </dev/null"
    outer = ["/bin/zsh", "-f", "-c", payload]
    return {
        "argv": {"bytes": len(argv_payload), "sha256": sha(argv_payload), "strings": len(argv)},
        "clean_vector": {"bytes": len(vector_payload), "sha256": sha(vector_payload), "strings": len(env)},
        "literal_payload": {"bytes": len(payload.encode()), "sha256": sha(payload.encode()), "tokens": len(env)},
        "outer_argv": {"bytes": len(compact(outer)), "sha256": sha(compact(outer)), "strings": len(outer)},
    }


def command_identities(plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for phase in ("transport", "self-check", "finalize"):
        args = phase_arguments(phase, plan, status, helper, derived)
        argv = [str(PYTHON), "-c", derived["writer"].decode(), "--", *args]
        result[phase] = command_identity(argv)
        result[phase]["schema"] = [args[0], *args[1::2]]
    return result


def source_receipt_payload(helper: bytes, derived: dict[str, Any]) -> bytes:
    return pretty(
        {
            "contract_sha256": sha(derived["contract"]),
            "driver_sha256": sha(derived["driver"]),
            "format_version": 1,
            "helper_sha256": sha(helper),
            "phase": "M3A_V7_SOURCE_RECEIPT",
            "result": "PASS",
            "writer_sha256": sha(derived["writer"]),
        }
    )


def writer_test_payload() -> bytes:
    return pretty({"format_version": 1, "phase": "M3A_V7_WRITER_SELF_TEST", "result": "PASS"})


def self_check_payload(plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]) -> bytes:
    return pretty(
        {
            "acceptance_validation": derived["acceptance_validation"],
            "contract_validation": derived["contract_validation"],
            "documents": validate_documents(plan, status, helper),
            "driver_validation": derived["driver_validation"],
            "format_version": 1,
            "phase": "M3A_V7_SELF_CHECK",
            "result": "PASS",
            "ruff": derived["ruff"],
            "security": {
                "authentication_location_probe": False,
                "credential_blind": True,
                "destination_probe": False,
                "login_status_launched": False,
            },
        }
    )


def final_index_payload(plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]) -> bytes:
    commands = command_identities(plan, status, helper, derived)
    return pretty(
        {
            "controller_acceptance_sha256": sha(derived["acceptance_payload"]),
            "driver_sha256": sha(derived["driver"]),
            "format_version": 1,
            "phase": "M3A_V7_FINAL_INDEX",
            "phase_argv_sha256": {name: value["argv"]["sha256"] for name, value in commands.items()},
            "result": "M3A_V7_READY_FOR_CONTROLLER_REVIEW",
            "writer_sha256": sha(derived["writer"]),
        }
    )


def validate_root_environment() -> None:
    require(Path.cwd().resolve() == SEED_REPO.resolve(), "root cwd mismatch")
    expected = {
        "HOME",
        "TMPDIR",
        "PATH",
        "LANG",
        "LC_ALL",
        "PYTHONDONTWRITEBYTECODE",
        "GIT_OPTIONAL_LOCKS",
        "__CF_USER_TEXT_ENCODING",
    }
    require(set(os.environ) == expected, "root environment mismatch")
    require(os.environ["PYTHONDONTWRITEBYTECODE"] == "1", "bytecode guard mismatch")
    require(os.environ["GIT_OPTIONAL_LOCKS"] == "0", "git lock guard mismatch")


def parse_phase(argv: list[str]) -> tuple[str, dict[str, str]]:
    require(argv, "missing phase")
    phase = argv[0]
    require(phase in {"transport", "self-check", "finalize"}, "phase mismatch")
    require(len(argv[1:]) % 2 == 0, "argument shape mismatch")
    values: dict[str, str] = {}
    for index in range(1, len(argv), 2):
        require(argv[index].startswith("--") and argv[index] not in values, "argument schema mismatch")
        values[argv[index]] = argv[index + 1]
    return phase, values


def write_exclusive(path: Path, payload: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        view = memoryview(payload)
        while view:
            count = os.write(fd, view)
            require(count > 0, "write stalled")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def phase_context(
    values: dict[str, str], *, require_root_absent: bool
) -> tuple[bytes, bytes, bytes, dict[str, Any]]:
    helper = read_regular(HELPER)[0]
    plan = read_regular(PLAN)[0]
    status = read_regular(STATUS)[0]
    require(sha(plan) == values.get("--expected-plan-sha256"), "plan hash mismatch")
    require(sha(status) == values.get("--expected-status-sha256"), "status hash mismatch")
    require(sha(helper) == values.get("--expected-helper-sha256"), "helper hash mismatch")
    derived = derive_all(plan, status, helper)
    require(sha(derived["writer"]) == values.get("--expected-writer-sha256"), "writer hash mismatch")
    require(sha(derived["driver"]) == values.get("--expected-driver-sha256"), "driver hash mismatch")
    require(sha(derived["contract"]) == values.get("--expected-contract-sha256"), "contract hash mismatch")
    validate_documents(plan, status, helper)
    validate_nonsecret_evidence(require_root_absent=require_root_absent)
    return plan, status, helper, derived


def root_transport(values: dict[str, str]) -> dict[str, Any]:
    require(not V7_ROOT.exists() and not V7_ROOT.is_symlink(), "V7 root exists")
    plan, status, helper, derived = phase_context(values, require_root_absent=True)
    acceptance = json.loads(values.get("--controller-acceptance-json", ""))
    require(acceptance == derived["acceptance"], "transport acceptance mismatch")
    os.mkdir(V7_ROOT, 0o700)
    os.mkdir(V7_ROOT / "home", 0o700)
    os.mkdir(V7_ROOT / "tmp", 0o700)
    os.mkdir(V7_RECEIPTS, 0o700)
    write_exclusive(V7_DRIVER, derived["driver"])
    write_exclusive(V7_RECEIPTS / "controller-acceptance-v7.json", derived["acceptance_payload"])
    write_exclusive(V7_RECEIPTS / "source-receipt.json", source_receipt_payload(helper, derived))
    for directory in (V7_RECEIPTS, V7_ROOT / "home", V7_ROOT / "tmp", V7_ROOT):
        sync_directory(directory)
    return {"phase": "M3A_V7_ROOT_TRANSPORT", "result": "PASS"}


def validate_partial_root(expected_files: set[str], derived: dict[str, Any]) -> None:
    private_directory(V7_ROOT)
    private_directory(V7_ROOT / "home")
    private_directory(V7_ROOT / "tmp")
    private_directory(V7_RECEIPTS)
    require(set(os.listdir(V7_ROOT)) == {"handoff-driver.py", "home", "receipts", "tmp"}, "root domain mismatch")
    require(set(os.listdir(V7_RECEIPTS)) == expected_files, "receipt domain mismatch")
    exact_file(V7_DRIVER, (len(derived["driver"]), sha(derived["driver"])), 0o600)
    require(not V7_RESULT.exists() and not V7_RESULT.is_symlink(), "reserved result exists")


def root_self_check(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, derived = phase_context(values, require_root_absent=False)
    require(
        sha(derived["acceptance_payload"]) == values.get("--expected-controller-acceptance-sha256"),
        "acceptance hash mismatch",
    )
    validate_partial_root({"controller-acceptance-v7.json", "source-receipt.json"}, derived)
    exact_file(
        V7_RECEIPTS / "controller-acceptance-v7.json",
        (len(derived["acceptance_payload"]), sha(derived["acceptance_payload"])),
        0o600,
    )
    exact_file(
        V7_RECEIPTS / "source-receipt.json",
        (len(source_receipt_payload(helper, derived)), sha(source_receipt_payload(helper, derived))),
        0o600,
    )
    write_exclusive(V7_RECEIPTS / "writer-self-test.json", writer_test_payload())
    write_exclusive(V7_RECEIPTS / "self-check-result.json", self_check_payload(plan, status, helper, derived))
    sync_directory(V7_RECEIPTS)
    return {"phase": "M3A_V7_ROOT_SELF_CHECK", "result": "PASS"}


def root_finalize(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, derived = phase_context(values, require_root_absent=False)
    require(
        sha(derived["acceptance_payload"]) == values.get("--expected-controller-acceptance-sha256"),
        "acceptance hash mismatch",
    )
    self_check = self_check_payload(plan, status, helper, derived)
    writer_test = writer_test_payload()
    require(sha(self_check) == values.get("--expected-self-check-sha256"), "self-check hash mismatch")
    require(sha(writer_test) == values.get("--expected-writer-self-test-sha256"), "writer test hash mismatch")
    validate_partial_root(
        {
            "controller-acceptance-v7.json",
            "self-check-result.json",
            "source-receipt.json",
            "writer-self-test.json",
        },
        derived,
    )
    exact_file(V7_RECEIPTS / "self-check-result.json", (len(self_check), sha(self_check)), 0o600)
    exact_file(V7_RECEIPTS / "writer-self-test.json", (len(writer_test), sha(writer_test)), 0o600)
    final_index = final_index_payload(plan, status, helper, derived)
    write_exclusive(V7_RECEIPTS / "final-index.json", final_index)
    sync_directory(V7_RECEIPTS)
    require(set(os.listdir(V7_RECEIPTS)) == ROOT_RECEIPT_FILES, "final receipt domain mismatch")
    return {"phase": "M3A_V7_ROOT_FINALIZE", "result": "M3A_V7_READY_FOR_CONTROLLER_REVIEW"}


def root_dispatch(argv: list[str]) -> None:
    validate_root_environment()
    phase, values = parse_phase(argv)
    handlers: dict[str, Callable[[dict[str, str]], dict[str, Any]]] = {
        "transport": root_transport,
        "self-check": root_self_check,
        "finalize": root_finalize,
    }
    value = handlers[phase](values)
    sys.stdout.buffer.write(compact(value) + b"\n")


def static_report() -> dict[str, Any]:
    helper = read_regular(HELPER)[0]
    plan = read_regular(PLAN)[0]
    status = read_regular(STATUS)[0]
    before = nonsecret_snapshot()
    derived = derive_all(plan, status, helper)
    documents = validate_documents(plan, status, helper)
    evidence = validate_nonsecret_evidence()
    commands = command_identities(plan, status, helper, derived)
    final_index = final_index_payload(plan, status, helper, derived)
    after = nonsecret_snapshot()
    require(before == after, "static validation changed protected state")
    return {
        "acceptance": {"bytes": len(derived["acceptance_payload"]), "sha256": sha(derived["acceptance_payload"])},
        "commands": commands,
        "contract": {"bytes": len(derived["contract"]), "sha256": sha(derived["contract"])},
        "documents": documents,
        "driver": {"bytes": len(derived["driver"]), "sha256": sha(derived["driver"])},
        "evidence": evidence,
        "final_index": {"bytes": len(final_index), "sha256": sha(final_index)},
        "gate_count": 32,
        "helper": {"bytes": len(helper), "sha256": sha(helper)},
        "no_write_snapshot": before,
        "result": "PASS",
        "self_check": {
            "bytes": len(self_check_payload(plan, status, helper, derived)),
            "sha256": sha(self_check_payload(plan, status, helper, derived)),
        },
        "source_receipt": {
            "bytes": len(source_receipt_payload(helper, derived)),
            "sha256": sha(source_receipt_payload(helper, derived)),
        },
        "writer": {"bytes": len(derived["writer"]), "sha256": sha(derived["writer"])},
        "writer_self_test": {"bytes": len(writer_test_payload()), "sha256": sha(writer_test_payload())},
    }


def nonsecret_snapshot() -> str:
    records: list[Any] = []
    for path in (
        PLAN,
        STATUS,
        HELPER,
        V6_DRIVER,
        V6_RESULT,
        V44_ROOT / "candidate-driver.py",
        TARGET / "successor-receipts/postacceptance-final-index.json",
        RUN / "state.json",
        RUN / "events.jsonl",
    ):
        payload, _ = read_regular(path)
        records.append((str(path), len(payload), sha(payload)))
    delivery_status = git_capture(DELIVERY, ["status", "--short", "--untracked-files=all"])
    target_status = git_capture(TARGET_REPO, ["status", "--short", "--untracked-files=all"])
    records.append(("delivery_status", len(delivery_status), sha(delivery_status)))
    records.append(("target_status", len(target_status), sha(target_status)))
    records.append(("v7_root_absent", not V7_ROOT.exists() and not V7_ROOT.is_symlink()))
    return sha(compact(records))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-writer", action="store_true")
    parser.add_argument("--static-json", action="store_true")
    args = parser.parse_args()
    if args.emit_writer:
        sys.stdout.buffer.write(writer_source(read_regular(HELPER)[0]))
        return 0
    require(args.static_json, "static mode required")
    sys.stdout.buffer.write(compact(static_report()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
