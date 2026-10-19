#!/usr/bin/env python3
"""Credential-blind M3A-v3 source freeze and root-only constructor.

This trusted helper derives the V3 handoff driver from the sealed M3A-v2
driver without resolving or probing any authentication location.  Its local
validation surface is read-only.  ``root_only`` is reachable only through the
unique source embedded in the Living ExecPlan and is not invoked by the
source-freeze validation command.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pprint
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


DELIVERY = Path("/Users/junhuaxu/autoclip")
PLAN = DELIVERY / "docs/exec-plans/liveclip-agent-runtime-v2.md"
STATUS = DELIVERY / "STATUS.md"
ARCHITECTURE = DELIVERY / "docs/liveclip-architecture.html"
REQUIREMENT = DELIVERY / "docs/requirements/liveclip-agent-runtime-v2-acceptance-v3.md"
BASE = Path(
    "/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/"
    "agent-runtime-v2/a822890ace12"
)
SEED_REPO = BASE / "candidate.OlsWg1/repo"
TARGET = BASE / "candidate.M4v94Rmv"
TARGET_REPO = TARGET / "repo"
RUN_ID = "20261014T214746Z-cd5796b8"
RUN = TARGET_REPO / ".loop/runs" / RUN_ID
V2_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v2"
V2_DRIVER = V2_ROOT / "handoff-driver.py"
V40_ROOT = BASE / "trusted-tools/m3-successor-preparation-v40"
V3_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v3"
V3_DRIVER = V3_ROOT / "handoff-driver.py"
V3_RECEIPTS = V3_ROOT / "receipts"
V3_RESULT = V3_RECEIPTS / "auth-handoff-v3-result.json"
HELPER = DELIVERY / "tools/loop_engineering/m3a_v3_source_freeze.py"
RUFF = DELIVERY / ".venv/bin/ruff"
PYTHON = Path("/Library/Frameworks/Python.framework/Versions/3.11/bin/python3")

SOURCE_BEGIN = "# BEGIN M3A_V3_PREPARATION_SOURCE\n"
SOURCE_END = "# END M3A_V3_PREPARATION_SOURCE\n"
EXPECTED_HEAD = "2f361fcddc0e63ae62ee62826e27b54bb8204c53"
EXPECTED_BRANCH = "main"
EXPECTED_DELIVERY = (0, 15, 170)
EXPECTED_TARGET = (0, 15, 73)
EXPECTED_ARCHITECTURE = (
    66116,
    "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce",
)
EXPECTED_REQUIREMENT = (
    12289,
    "308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00",
)
EXPECTED_V2_DRIVER = (
    23756,
    "0e86fb41bbee0ae89244a5a766b33714f302c72407a7c9994c5e384996ec7288",
)
EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO",
    "candidate.3WBt3ldA",
    "candidate.5jh3bylk",
    "candidate.5nZWpynN",
    "candidate.KWbe2iGW",
    "candidate.M4v94Rmv",
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
    "candidate.oivrdV6U",
    "candidate.qaDKDWkQ",
    "candidate.vuDWtK0T",
    "candidate.xp23hqNY",
    "candidate.z6EbTJew",
)

V40_ROOT_FILES: dict[str, tuple[int, str]] = {
    "candidate-driver.py": (
        468657,
        "4b2e438f652998fc36cae9590ecf17b08d6e245433cdf5eab9480b5ddc1fafc2",
    ),
    "receipts/controller-acceptance-v40.json": (
        14519,
        "89b2ebbc6d18cc24bab47c72bf5e9499c1e47da22fd648ef5e563ee1c461e7c5",
    ),
    "receipts/final-index.json": (
        2000,
        "9d623cd3b398010a279cb424a93cbee91e99e2555ab9307075bd9043c1dd7a7a",
    ),
    "receipts/self-check-result.json": (
        5173,
        "fdcd6049a7f6dad74eb7f6522ad8b2c1c20fb18368024af8ef9a04e5c8c1feaa",
    ),
    "receipts/source-receipt.json": (
        524,
        "8de386e0c256635505bb41c8b3c1855db8744fa889d96f6be80b7ad19e916d25",
    ),
    "receipts/successor-preparation-v40-result.json": (
        23850,
        "cd13363aee5d6fd069355ff1ee31ac1f3827b2f25bb9a565eebc3bb68b2dd9bf",
    ),
    "receipts/writer-self-test.json": (
        72,
        "931b38e3d416a90977e891d368b075055925ae6070e732e3d5820ae21f610388",
    ),
}

TARGET_FILES: dict[str, tuple[int, str, int]] = {
    f"repo/.loop/runs/{RUN_ID}/events.jsonl": (
        144,
        "f1a5ec47ed1051af8f64e2fdf0c105881b6a733c63bbfeedde0bf273e21285a8",
        0o644,
    ),
    f"repo/.loop/runs/{RUN_ID}/state.json": (
        12796,
        "3a5517a757be71d40566e5175576b200cef65da8c4b0184e75d6ff880a159ed8",
        0o644,
    ),
    "repo/.loop/trusted/final-controller-acceptance-v40.json": (
        3913,
        "a44929f89fca9629b06163814c8c1233278f830036c343c52e11fd4b1ea22a3e",
        0o600,
    ),
    "successor-receipts/final-receipt-index.json": (
        18095,
        "f31b88a03ec37ada6237eb92817004ad4a39b42ee768da1ad5fb019206bd2a81",
        0o600,
    ),
    "successor-receipts/postacceptance-attempt-manifest.jsonl": (
        12177744,
        "d6f9d170fbc6db5ebceaaaa9e6dfc63b838f1d2e46dd77782db4845a87e42c5e",
        0o600,
    ),
    "successor-receipts/postacceptance-final-index.json": (
        2731,
        "2668171e0b0c22f2022793c4413b359b3dd31282bc3fbbe1ac413665a647b7b6",
        0o600,
    ),
    "successor-receipts/postacceptance-repository-manifest.jsonl": (
        6139910,
        "20f5cf4e26274de1176aa23a79ee9508396246d18a14a1046bae5918f2e87403",
        0o600,
    ),
    "successor-receipts/successor-v40-controller-acceptance-offer.json": (
        5032,
        "afa8c4b8427193e6efa2ca2c024af22baf35a7f2eab7c8c00ba01ee9393f977c",
        0o600,
    ),
    "successor-receipts/successor-v40-controller-acceptance-transport.json": (
        1383,
        "1651b2c39787898f63a20390f30ac52fae672a3fb691116f44566242b1d15f2d",
        0o600,
    ),
    "successor-receipts/successor-v40-policy-snapshot.json": (
        4827,
        "5a6b03c002f64e01266e94ebc2724e4e625fde7f6a5144e0c1d1e91ac32ca7c1",
        0o600,
    ),
    "successor-receipts/successor-v40-preparation-bindings.json": (
        5412,
        "b3ce9cfd31c0a56baf6d906895a80ffad398f62c11187728b2f4d76628a79e3a",
        0o600,
    ),
    "successor-receipts/successor-v40-toolchain-snapshot.json": (
        4878,
        "f4e33b7d885e68d62efb0704c6abb47d38d15a396352b187f94ceb2139f91651",
        0o600,
    ),
    "successor-receipts/successor-v40-trusted-context.json": (
        3884,
        "664402f3791b17c88bcd6ea9e4f3cba59eec5e319e11e5514f8717c1fd1f3bca",
        0o600,
    ),
}

ROOT_SHAPE = (
    "--plan",
    None,
    "--expected-plan-sha256",
    None,
    "--status",
    None,
    "--expected-status-sha256",
    None,
    "--expected-source-sha256",
    None,
    "--expected-helper-sha256",
    None,
    "--expected-driver-sha256",
    None,
    "--expected-contract-sha256",
    None,
    "--controller-acceptance-json",
    None,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def pretty(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def read_regular(path: Path, maximum: int = 32_000_000) -> tuple[bytes, os.stat_result]:
    require(not path.is_symlink(), "symlink rejected")
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "regular file required")
    require(before.st_size <= maximum, "file bound exceeded")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino), "identity changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(fd, min(1_048_576, maximum + 1 - total))
            if not block:
                break
            chunks.append(block)
            total += len(block)
            require(total <= maximum, "file bound exceeded")
        final = os.fstat(fd)
    finally:
        os.close(fd)
    require(
        (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        == (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns),
        "file changed while read",
    )
    payload = b"".join(chunks)
    require(len(payload) == final.st_size, "short read")
    return payload, final


def exact_file(path: Path, expected: tuple[int, str], mode: int | None = None) -> bytes:
    payload, info = read_regular(path)
    require((len(payload), sha(payload)) == expected, f"identity mismatch: {path.name}")
    require(info.st_uid == os.getuid(), f"owner mismatch: {path.name}")
    if mode is not None:
        require(stat.S_IMODE(info.st_mode) == mode, f"mode mismatch: {path.name}")
    return payload


def private_directory(path: Path) -> None:
    require(not path.is_symlink(), "private directory symlink rejected")
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode), "private directory required")
    require(info.st_uid == os.getuid(), "private directory owner mismatch")
    require(stat.S_IMODE(info.st_mode) == 0o700, "private directory mode mismatch")


def extract_source(plan_payload: bytes) -> bytes:
    text = plan_payload.decode("utf-8")
    require(text.count(SOURCE_BEGIN) == 1, "source begin marker mismatch")
    require(text.count(SOURCE_END) == 1, "source end marker mismatch")
    start = text.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    end = text.index(SOURCE_END, start)
    source = text[start:end].encode()
    require(source.endswith(b"\n"), "source terminal LF missing")
    return source


def git_capture(repo: Path, args: list[str]) -> bytes:
    result = subprocess.run(  # noqa: S603 - fixed executable and closed argv sets
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
    require(result.returncode == 0, "git correlation failed")
    require(not result.stderr, "git correlation stderr")
    return result.stdout


def status_counts(repo: Path) -> tuple[int, int, int]:
    payload = git_capture(repo, ["status", "--short", "--untracked-files=all"])
    lines = payload.decode().splitlines()
    staged = sum(1 for line in lines if line and line[0] not in {" ", "?"})
    modified = sum(1 for line in lines if not line.startswith("??") and len(line) > 1 and line[1] != " ")
    untracked = sum(1 for line in lines if line.startswith("??"))
    return staged, modified, untracked


def validate_git(repo: Path, expected: tuple[int, int, int]) -> None:
    require(git_capture(repo, ["rev-parse", "--abbrev-ref", "HEAD"]) == b"main\n", "branch mismatch")
    require(git_capture(repo, ["rev-parse", "HEAD"]).decode().strip() == EXPECTED_HEAD, "HEAD mismatch")
    require(status_counts(repo) == expected, "inventory mismatch")


def handoff_contract() -> dict[str, Any]:
    return {
        "bounds": {
            "diagnostic_bytes": 65_536,
            "login_status_seconds": 30,
            "outer_seconds": 120,
            "sanitized_stdout_bytes": 4_096,
        },
        "budgets": {
            "destination": 1,
            "handoff_invocation": 1,
            "result": 1,
            "root": 1,
        },
        "candidate": {
            "candidate_count": 24,
            "completed_tree": {
                "bytes": 967_345_497,
                "paths": 44_326,
                "sha256": "894bf7939742cafb4f7ee512bd2ffa4b592a5016a93f3e8288e4adf75251f1ba",
            },
            "final_acceptance_sha256": "a44929f89fca9629b06163814c8c1233278f830036c343c52e11fd4b1ea22a3e",
            "final_index_sha256": "2668171e0b0c22f2022793c4413b359b3dd31282bc3fbbe1ac413665a647b7b6",
            "name": TARGET.name,
            "run_id": RUN_ID,
            "sealed_receipt_index_sha256": "f31b88a03ec37ada6237eb92817004ad4a39b42ee768da1ad5fb019206bd2a81",
        },
        "delivery": {
            "branch": EXPECTED_BRANCH,
            "candidate_inventory": list(EXPECTED_TARGET),
            "candidate_names_sha256": sha(compact(list(EXPECTED_CANDIDATES))),
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
            "acceptance_requirement_sha256": EXPECTED_REQUIREMENT[1],
            "architecture_sha256": EXPECTED_ARCHITECTURE[1],
            "controller_transport_sha256": "1651b2c39787898f63a20390f30ac52fae672a3fb691116f44566242b1d15f2d",
            "postacceptance_attempt_manifest_sha256": "d6f9d170fbc6db5ebceaaaa9e6dfc63b838f1d2e46dd77782db4845a87e42c5e",
            "postacceptance_repository_manifest_sha256": "20f5cf4e26274de1176aa23a79ee9508396246d18a14a1046bae5918f2e87403",
            "preparation_bindings_sha256": "b3ce9cfd31c0a56baf6d906895a80ffad398f62c11187728b2f4d76628a79e3a",
            "preparation_offer_sha256": "afa8c4b8427193e6efa2ca2c024af22baf35a7f2eab7c8c00ba01ee9393f977c",
            "root_final_index_sha256": "9d623cd3b398010a279cb424a93cbee91e99e2555ab9307075bd9043c1dd7a7a",
            "successor_policy_sha256": "5a6b03c002f64e01266e94ebc2724e4e625fde7f6a5144e0c1d1e91ac32ca7c1",
            "successor_toolchain_sha256": "f4e33b7d885e68d62efb0704c6abb47d38d15a396352b187f94ceb2139f91651",
            "successor_trusted_context_sha256": "664402f3791b17c88bcd6ea9e4f3cba59eec5e319e11e5514f8717c1fd1f3bca",
        },
        "format_version": 1,
        "formal_role_authority": False,
        "phase": "M3A_V3_AUTH_HANDOFF",
        "pinned_status": {
            "argv": ["login", "status"],
            "binary_sha256": "12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de",
            "binary_size": 245_096_256,
            "child_channels": "DEVNULL",
            "timeout_seconds": 30,
        },
        "private_runtime": {"home_mode": "0700", "owner_uid": os.getuid(), "tmp_mode": "0700"},
        "privacy": {
            "child_channels": "DEVNULL",
            "credential_environment_variables": False,
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
        "run": {
            "code_cycle": 0,
            "cycle": 0,
            "events_sha256": "f1a5ec47ed1051af8f64e2fdf0c105881b6a733c63bbfeedde0bf273e21285a8",
            "state": "received",
            "state_sha256": "3a5517a757be71d40566e5175576b200cef65da8c4b0184e75d6ff880a159ed8",
        },
        "v40": {
            "driver_sha256": "4b2e438f652998fc36cae9590ecf17b08d6e245433cdf5eab9480b5ddc1fafc2",
            "final_acceptance_sha256": "a44929f89fca9629b06163814c8c1233278f830036c343c52e11fd4b1ea22a3e",
            "final_index_sha256": "2668171e0b0c22f2022793c4413b359b3dd31282bc3fbbe1ac413665a647b7b6",
            "preparation_result_sha256": "cd13363aee5d6fd069355ff1ee31ac1f3827b2f25bb9a565eebc3bb68b2dd9bf",
        },
    }


def static_contract_validation(contract_payload: bytes) -> dict[str, Any]:
    expected = handoff_contract()
    require(contract_payload == compact(expected), "positive contract mismatch")
    require(json.loads(contract_payload) == expected, "contract decode mismatch")
    mutations = (
        ("phase", "M3A_V2_AUTH_HANDOFF"),
        ("formal_role_authority", True),
        ("candidate.name", "candidate.oivrdV6U"),
        ("candidate.run_id", "20261014T191719Z-0802b465"),
        ("candidate.candidate_count", 23),
        ("delivery.inventory", [0, 15, 169]),
        ("delivery.candidate_inventory", [0, 15, 72]),
        ("privacy.opaque_copy", False),
        ("privacy.protected_entry_omitted_before_metadata", False),
        ("privacy.secret_derived_metadata", True),
        ("budgets.handoff_invocation", 2),
        ("bounds.login_status_seconds", 31),
        ("evidence.architecture_sha256", "0" * 64),
    )
    negatives = 0
    for dotted, value in mutations:
        candidate = json.loads(json.dumps(expected))
        target: dict[str, Any] = candidate
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
        require(compact(candidate) != contract_payload, f"negative contract fixture ineffective: {dotted}")
        negatives += 1
    return {"negative_fixtures": negatives, "positive": "PASS"}


def _assignment_name(node: ast.Assign) -> str | None:
    if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
        return None
    return node.targets[0].id


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def _span(node: ast.AST, offsets: list[int]) -> tuple[int, int]:
    require(hasattr(node, "end_lineno") and node.end_lineno is not None, "AST span missing")
    start = offsets[node.lineno - 1] + node.col_offset
    end = offsets[node.end_lineno - 1] + node.end_col_offset
    return start, end


def _replace_nodes(text: str, replacements: dict[str, str]) -> str:
    tree = ast.parse(text)
    offsets = _line_offsets(text)
    edits: list[tuple[int, int, str]] = []
    found: set[str] = set()
    for node in tree.body:
        key: str | None = None
        if isinstance(node, ast.Assign):
            key = _assignment_name(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key = node.name
        if key in replacements:
            require(key not in found, f"duplicate replacement node: {key}")
            start, end = _span(node, offsets)
            edits.append((start, end, replacements[key]))
            found.add(key)
    require(found == set(replacements), "replacement node set mismatch")
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def _python_assignment(name: str, value: Any) -> str:
    rendered = pprint.pformat(value, width=118, sort_dicts=True)
    return f"{name} = {rendered}"


def derive_driver(v2_payload: bytes) -> bytes:
    require((len(v2_payload), sha(v2_payload)) == EXPECTED_V2_DRIVER, "sealed V2 driver mismatch")
    text = v2_payload.decode("utf-8")
    token_replacements = (
        ("M3A_V2", "M3A_V3", 4),
        ("m3-authentication-handoff-v2", "m3-authentication-handoff-v3", 1),
        ("auth-handoff-v2-result.json", "auth-handoff-v3-result.json", 1),
        ("candidate.oivrdV6U", "candidate.M4v94Rmv", 3),
        ("20261014T191719Z-0802b465", RUN_ID, 4),
        ("v39", "v40", 14),
        ("V39", "V40", 11),
    )
    for old, new, count in token_replacements:
        require(text.count(old) == count, f"transform count mismatch: {old}")
        text = text.replace(old, new)

    driver_target_files = dict(TARGET_FILES)
    driver_v40_files = dict(V40_ROOT_FILES)
    replacements = {
        "EXPECTED_DELIVERY": _python_assignment("EXPECTED_DELIVERY", EXPECTED_DELIVERY),
        "EXPECTED_TARGET": _python_assignment("EXPECTED_TARGET", EXPECTED_TARGET),
        "EXPECTED_CANDIDATES": "EXPECTED_CANDIDATES = {"
        + ", ".join(repr(name) for name in EXPECTED_CANDIDATES)
        + "}",
        "V40_FILES": _python_assignment("V40_FILES", driver_v40_files),
        "TARGET_FILES": _python_assignment("TARGET_FILES", driver_target_files),
        "HANDOFF_CONTRACT": _python_assignment("HANDOFF_CONTRACT", handoff_contract()),
    }
    text = _replace_nodes(text, replacements)
    payload = text.encode("utf-8")
    compile(payload, "<m3a-v3-driver>", "exec", dont_inherit=True)
    return payload


def function_source(payload: bytes, name: str) -> bytes:
    text = payload.decode("utf-8")
    tree = ast.parse(text)
    offsets = _line_offsets(text)
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"function count mismatch: {name}")
    start, end = _span(matches[0], offsets)
    return text[start:end].encode()


def static_driver_validation(v2_payload: bytes, driver_payload: bytes) -> dict[str, Any]:
    tree = ast.parse(driver_payload)
    compile(driver_payload, "<m3a-v3-driver>", "exec", dont_inherit=True)
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    required_functions = {
        "opaque_copy_state",
        "terminate_group",
        "login_status",
        "receipt",
        "validate_private_runtime",
        "validate_v40_and_target",
    }
    require(required_functions <= functions, "required driver functions missing")
    require("validate_v39_and_target" not in functions, "stale V39 validator remains")
    require(driver_payload.count(b"M3A_V3_AUTH_HANDOFF") == 2, "active phase count mismatch")
    require(b"M3A_V2_AUTH_HANDOFF" not in driver_payload, "stale active phase remains")
    require(driver_payload.count(b"auth-handoff") >= 2, "handoff surface missing")
    for forbidden in (b"loop-run", b"--last", b"resume_liveclip.sh"):
        require(forbidden not in driver_payload, "forbidden command surface")
    for name in ("validate_v40_and_target", "validate_private_runtime"):
        pre_handoff_source = function_source(driver_payload, name)
        require(b"AUTH_SOURCE" not in pre_handoff_source, f"protected source reference before handoff: {name}")
        require(b"AUTH_DESTINATION" not in pre_handoff_source, f"protected destination reference before handoff: {name}")
        require(b"login_status(" not in pre_handoff_source, f"login status before handoff: {name}")

    equivalence: dict[str, str] = {}
    for name in ("opaque_copy_state", "terminate_group", "login_status", "receipt"):
        old = function_source(v2_payload, name)
        new = function_source(driver_payload, name).replace(b"M3A_V3", b"M3A_V2")
        require(new == old, f"source equivalence mismatch: {name}")
        equivalence[name] = sha(new)

    opaque_tree = ast.parse(function_source(driver_payload, "opaque_copy_state"))
    opaque_calls = [
        node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        for node in ast.walk(opaque_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
    ]
    for required in ("lstat", "open", "fstat", "fsync", "read", "write"):
        require(required in opaque_calls, f"opaque operation missing: {required}")

    receipt_tree = ast.parse(function_source(driver_payload, "receipt"))
    receipt_keys = {
        node.value
        for node in ast.walk(receipt_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    expected_receipt_keys = set(handoff_contract()["privacy"]["receipt_fields"])
    require(expected_receipt_keys <= receipt_keys, "sanitized receipt field mismatch")
    return {
        "ast_compile": "PASS",
        "equivalent_functions": equivalence,
        "opaque_operations": sorted(set(opaque_calls) & {"lstat", "open", "fstat", "fsync", "read", "write"}),
        "receipt_fields": sorted(expected_receipt_keys),
    }


def runtime_nonsecret_validation(driver_payload: bytes) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": "m3a_v3_driver_static_validation"}
    exec(  # noqa: S102 - exact derived bytes, hash-bound and compiled above
        compile(driver_payload, "<m3a-v3-driver>", "exec", dont_inherit=True), namespace
    )
    validator = namespace.get("validate_v40_and_target")
    require(callable(validator), "derived non-secret validator missing")
    validator()
    return {
        "authentication_location_probe": False,
        "login_status_launched": False,
        "result": "PASS",
        "validator": "validate_v40_and_target",
    }


def ruff_validation(driver_payload: bytes) -> dict[str, Any]:
    require(RUFF.is_file() and not RUFF.is_symlink(), "project Ruff missing")
    result = subprocess.run(  # noqa: S603 - pinned project-local Ruff and fixed argv
        [str(RUFF), "check", "--select", "F,B,S", "--stdin-filename", "handoff-driver.py", "-"],
        input=driver_payload,
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
    return {"returncode": result.returncode, "stdout_sha256": sha(result.stdout), "stderr_sha256": sha(result.stderr)}


def controller_acceptance(
    *,
    plan_payload: bytes,
    status_payload: bytes,
    source_payload: bytes,
    helper_payload: bytes,
    driver_payload: bytes,
    contract_payload: bytes,
) -> dict[str, Any]:
    return {
        "contract": {"canonical_bytes": len(contract_payload), "sha256": sha(contract_payload)},
        "documents": {
            "exec_plan": {"bytes": len(plan_payload), "sha256": sha(plan_payload)},
            "status": {"bytes": len(status_payload), "sha256": sha(status_payload)},
        },
        "driver": {"bytes": len(driver_payload), "sha256": sha(driver_payload)},
        "format_version": 1,
        "helper": {"bytes": len(helper_payload), "sha256": sha(helper_payload)},
        "phase": "M3A_V3_CONTROLLER_ACCEPTANCE",
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": {
            "fixed_name": V3_ROOT.name,
            "no_replace": True,
            "result_absent": True,
            "root_absent": True,
        },
        "security": {
            "credential_blind_root_only": True,
            "destination_precondition": "ABSENT_UNPROBED",
            "formal_role_authority": False,
            "login_status_during_root_only": False,
            "protected_entry_omitted_before_metadata": True,
        },
        "source": {"bytes": len(source_payload), "sha256": sha(source_payload)},
        "target": {
            "candidate": TARGET.name,
            "candidate_count": len(EXPECTED_CANDIDATES),
            "final_provenance_sha256": "2668171e0b0c22f2022793c4413b359b3dd31282bc3fbbe1ac413665a647b7b6",
            "run_id": RUN_ID,
        },
    }


def static_acceptance_validation(
    acceptance: dict[str, Any],
    *,
    plan_payload: bytes,
    status_payload: bytes,
    source_payload: bytes,
    helper_payload: bytes,
    driver_payload: bytes,
    contract_payload: bytes,
) -> dict[str, Any]:
    expected = controller_acceptance(
        plan_payload=plan_payload,
        status_payload=status_payload,
        source_payload=source_payload,
        helper_payload=helper_payload,
        driver_payload=driver_payload,
        contract_payload=contract_payload,
    )
    require(acceptance == expected, "positive acceptance mismatch")
    negatives = 0
    mutations = (
        ("phase", "M3A_V2_CONTROLLER_ACCEPTANCE"),
        ("result", "READY"),
        ("target.candidate", "candidate.oivrdV6U"),
        ("target.run_id", "20261014T191719Z-0802b465"),
        ("target.candidate_count", 23),
        ("security.credential_blind_root_only", False),
        ("security.login_status_during_root_only", True),
        ("security.destination_precondition", "INSPECTED"),
        ("root.no_replace", False),
        ("documents.exec_plan.sha256", "0" * 64),
        ("driver.sha256", "0" * 64),
        ("contract.sha256", "0" * 64),
    )
    for dotted, value in mutations:
        candidate = json.loads(json.dumps(expected))
        target: dict[str, Any] = candidate
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
        require(candidate != expected, f"negative fixture ineffective: {dotted}")
        require(compact(candidate) != compact(expected), f"negative canonical fixture ineffective: {dotted}")
        negatives += 1
    return {"positive": "PASS", "negative_fixtures": negatives}


def validate_nonsecret_evidence() -> dict[str, Any]:
    validate_git(DELIVERY, EXPECTED_DELIVERY)
    validate_git(TARGET_REPO, EXPECTED_TARGET)
    exact_file(ARCHITECTURE, EXPECTED_ARCHITECTURE)
    exact_file(REQUIREMENT, EXPECTED_REQUIREMENT)
    exact_file(V2_DRIVER, EXPECTED_V2_DRIVER, 0o600)
    private_directory(V40_ROOT)
    for relative, expected in V40_ROOT_FILES.items():
        exact_file(V40_ROOT / relative, expected, 0o600)
    private_directory(TARGET)
    for relative, (size, digest, mode) in TARGET_FILES.items():
        exact_file(TARGET / relative, (size, digest), mode)
    state = json.loads((RUN / "state.json").read_text(encoding="utf-8"))
    require(state.get("state") == "received", "run state mismatch")
    require(state.get("cycle") == 0 and state.get("code_cycle") == 0, "run cycle mismatch")
    require(state.get("coder_session_id") is None, "Coder session must be null")
    require(state.get("last_error") is None, "run error must be null")
    require(state.get("artifacts") == {} and state.get("command_results") == [], "run outputs not pristine")
    candidates = tuple(
        sorted(
            path.name
            for path in BASE.iterdir()
            if path.name.startswith("candidate.") and path.is_dir() and not path.is_symlink()
        )
    )
    require(candidates == EXPECTED_CANDIDATES, "candidate set mismatch")
    require(not V3_ROOT.exists() and not V3_ROOT.is_symlink(), "V3 root must be absent")
    require(not V3_RESULT.exists() and not V3_RESULT.is_symlink(), "V3 result must be absent")
    require(not (V40_ROOT / "receipts/final-controller-acceptance-v40-result.json").exists(), "V40 final result exists")
    require(not (V40_ROOT / "receipts/auth-handoff-v40-result.json").exists(), "V40 auth result exists")
    return {
        "architecture": "PASS",
        "candidates": len(candidates),
        "delivery_inventory": list(status_counts(DELIVERY)),
        "requirement": "PASS",
        "root_absent": True,
        "run_pristine": True,
        "target_inventory": list(status_counts(TARGET_REPO)),
        "v40_evidence": "PASS",
        "v3_result_absent": True,
    }


def validate_root_environment() -> None:
    require(Path.cwd().resolve() == SEED_REPO.resolve(), "root-only cwd mismatch")
    expected_names = {
        "HOME",
        "TMPDIR",
        "PATH",
        "LANG",
        "LC_ALL",
        "PYTHONDONTWRITEBYTECODE",
        "GIT_OPTIONAL_LOCKS",
        "__CF_USER_TEXT_ENCODING",
    }
    require(set(os.environ) == expected_names, "root-only environment names mismatch")
    require(os.environ["PYTHONDONTWRITEBYTECODE"] == "1", "bytecode guard mismatch")
    require(os.environ["GIT_OPTIONAL_LOCKS"] == "0", "git lock guard mismatch")
    require(not V3_ROOT.exists() and not V3_ROOT.is_symlink(), "V3 root already exists")


def write_exclusive(path: Path, payload: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            require(written > 0, "exclusive write stalled")
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd)
        require(info.st_uid == os.getuid(), "written owner mismatch")
        require(stat.S_IMODE(info.st_mode) == mode, "written mode mismatch")
    finally:
        os.close(fd)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def parse_args(argv: list[str]) -> dict[str, str]:
    require(len(argv) == len(ROOT_SHAPE), "root-only argument count mismatch")
    values: dict[str, str] = {}
    for index, expected in enumerate(ROOT_SHAPE):
        if expected is None:
            values[ROOT_SHAPE[index - 1]] = argv[index]
        else:
            require(argv[index] == expected, "root-only argument schema mismatch")
    return values


def argument_strings(
    *,
    plan_sha: str,
    status_sha: str,
    source_sha: str,
    helper_sha: str,
    driver_sha: str,
    contract_sha: str,
    acceptance_json: str,
) -> list[str]:
    return [
        "--plan",
        str(PLAN),
        "--expected-plan-sha256",
        plan_sha,
        "--status",
        str(STATUS),
        "--expected-status-sha256",
        status_sha,
        "--expected-source-sha256",
        source_sha,
        "--expected-helper-sha256",
        helper_sha,
        "--expected-driver-sha256",
        driver_sha,
        "--expected-contract-sha256",
        contract_sha,
        "--controller-acceptance-json",
        acceptance_json,
    ]


def make_source(helper_size: int, helper_sha: str) -> bytes:
    source = f'''from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path

HELPER = Path({str(HELPER)!r})
EXPECTED_HELPER_SIZE = {helper_size}
EXPECTED_HELPER_SHA256 = {helper_sha!r}
payload = HELPER.read_bytes()
if len(payload) != EXPECTED_HELPER_SIZE or hashlib.sha256(payload).hexdigest() != EXPECTED_HELPER_SHA256:
    raise RuntimeError("M3A-v3 helper identity mismatch")
spec = importlib.util.spec_from_file_location("m3a_v3_source_freeze", HELPER)
if spec is None or spec.loader is None:
    raise RuntimeError("M3A-v3 helper loader unavailable")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.root_only()
'''
    payload = source.encode()
    compile(payload, "<m3a-v3-source>", "exec", dont_inherit=True)
    return payload


def derive_all(plan_payload: bytes, helper_payload: bytes) -> dict[str, Any]:
    source_payload = extract_source(plan_payload)
    expected_source = make_source(len(helper_payload), sha(helper_payload))
    require(source_payload == expected_source, "embedded source mismatch")
    v2_payload = exact_file(V2_DRIVER, EXPECTED_V2_DRIVER, 0o600)
    driver_payload = derive_driver(v2_payload)
    contract_payload = compact(handoff_contract())
    return {
        "source": source_payload,
        "driver": driver_payload,
        "contract": contract_payload,
        "contract_validation": static_contract_validation(contract_payload),
        "driver_validation": static_driver_validation(v2_payload, driver_payload),
        "runtime_nonsecret_validation": runtime_nonsecret_validation(driver_payload),
        "ruff": ruff_validation(driver_payload),
    }


def _identity(path: Path) -> dict[str, Any]:
    payload, info = read_regular(path)
    return {
        "bytes": len(payload),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "sha256": sha(payload),
        "uid": info.st_uid,
    }


def root_only() -> None:
    values = parse_args(sys.argv[1:])
    validate_root_environment()
    require(Path(values["--plan"]) == PLAN, "plan path mismatch")
    require(Path(values["--status"]) == STATUS, "status path mismatch")
    plan_payload = exact_file(PLAN, (PLAN.stat().st_size, values["--expected-plan-sha256"]))
    status_payload = exact_file(STATUS, (STATUS.stat().st_size, values["--expected-status-sha256"]))
    helper_payload = read_regular(HELPER)[0]
    derived = derive_all(plan_payload, helper_payload)
    source_payload = derived["source"]
    driver_payload = derived["driver"]
    contract_payload = derived["contract"]
    require(sha(source_payload) == values["--expected-source-sha256"], "source hash mismatch")
    require(sha(helper_payload) == values["--expected-helper-sha256"], "helper hash mismatch")
    require(sha(driver_payload) == values["--expected-driver-sha256"], "driver hash mismatch")
    require(sha(contract_payload) == values["--expected-contract-sha256"], "contract hash mismatch")
    acceptance = json.loads(values["--controller-acceptance-json"])
    acceptance_validation = static_acceptance_validation(
        acceptance,
        plan_payload=plan_payload,
        status_payload=status_payload,
        source_payload=source_payload,
        helper_payload=helper_payload,
        driver_payload=driver_payload,
        contract_payload=contract_payload,
    )
    evidence = validate_nonsecret_evidence()

    root_argv = [str(PYTHON), "-c", source_payload.decode(), "--", *sys.argv[1:]]
    root_argv_payload = compact(root_argv)
    os.mkdir(V3_ROOT, 0o700)
    try:
        os.mkdir(V3_ROOT / "home", 0o700)
        os.mkdir(V3_ROOT / "tmp", 0o700)
        os.mkdir(V3_RECEIPTS, 0o700)
        write_exclusive(V3_DRIVER, driver_payload)
        write_exclusive(V3_RECEIPTS / "controller-acceptance-v3.json", compact(acceptance) + b"\n")
        write_exclusive(
            V3_RECEIPTS / "source-receipt.json",
            pretty(
                {
                    "contract_sha256": sha(contract_payload),
                    "driver_sha256": sha(driver_payload),
                    "format_version": 1,
                    "helper_sha256": sha(helper_payload),
                    "phase": "M3A_V3_SOURCE_RECEIPT",
                    "result": "PASS",
                    "source_sha256": sha(source_payload),
                }
            ),
        )
        write_exclusive(
            V3_RECEIPTS / "writer-self-test.json",
            pretty({"format_version": 1, "phase": "M3A_V3_WRITER_SELF_TEST", "result": "PASS"}),
        )
        self_check = {
            "acceptance_validation": acceptance_validation,
            "driver_validation": derived["driver_validation"],
            "runtime_nonsecret_validation": derived["runtime_nonsecret_validation"],
            "contract_validation": derived["contract_validation"],
            "evidence": evidence,
            "format_version": 1,
            "phase": "M3A_V3_SELF_CHECK",
            "result": "PASS",
            "ruff": derived["ruff"],
            "security": {
                "authentication_location_probe": False,
                "credential_blind": True,
                "login_status_launched": False,
            },
        }
        write_exclusive(V3_RECEIPTS / "self-check-result.json", pretty(self_check))
        final_index = {
            "controller_acceptance_sha256": sha(compact(acceptance) + b"\n"),
            "driver_sha256": sha(driver_payload),
            "format_version": 1,
            "phase": "M3A_V3_FINAL_INDEX",
            "result": "M3A_V3_READY_FOR_CONTROLLER_REVIEW",
            "root_argv_sha256": sha(root_argv_payload),
            "source_sha256": sha(source_payload),
        }
        write_exclusive(V3_RECEIPTS / "final-index.json", pretty(final_index))
        for directory in (V3_RECEIPTS, V3_ROOT / "home", V3_ROOT / "tmp", V3_ROOT):
            sync_directory(directory)
    except BaseException:
        sync_directory(V3_ROOT)
        raise

    files = {
        "candidate_driver": _identity(V3_DRIVER),
        "controller_acceptance": _identity(V3_RECEIPTS / "controller-acceptance-v3.json"),
        "final_index": _identity(V3_RECEIPTS / "final-index.json"),
        "self_check": _identity(V3_RECEIPTS / "self-check-result.json"),
        "source_receipt": _identity(V3_RECEIPTS / "source-receipt.json"),
        "writer_self_test": _identity(V3_RECEIPTS / "writer-self-test.json"),
    }
    sys.stdout.buffer.write(
        compact(
            {
                "files": files,
                "phase": "M3A_V3_ROOT_ONLY",
                "result": "M3A_V3_READY_FOR_CONTROLLER_REVIEW",
                "root_argv_sha256": sha(root_argv_payload),
            }
        )
        + b"\n"
    )


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def command_identities(
    *,
    source_payload: bytes,
    plan_sha: str,
    status_sha: str,
    helper_sha: str,
    driver_sha: str,
    contract_sha: str,
    acceptance_json: str,
) -> dict[str, Any]:
    args = argument_strings(
        plan_sha=plan_sha,
        status_sha=status_sha,
        source_sha=sha(source_payload),
        helper_sha=helper_sha,
        driver_sha=driver_sha,
        contract_sha=contract_sha,
        acceptance_json=acceptance_json,
    )
    argv = [str(PYTHON), "-c", source_payload.decode(), "--", *args]
    environment = [
        "HOME=/Users/junhuaxu",
        "TMPDIR=/tmp",
        "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "PYTHONDONTWRITEBYTECODE=1",
        "GIT_OPTIONAL_LOCKS=0",
        "__CF_USER_TEXT_ENCODING=0x1F5:0x0:0x0",
    ]
    vector = ["/usr/bin/env", "-i", *environment, *argv]
    envelope = " ".join(shell_quote(value) for value in vector).encode()
    zsh_argv = ["/bin/zsh", "-f", "-c", envelope.decode()]
    return {
        "argv": {"bytes": len(compact(argv)), "count": len(argv), "sha256": sha(compact(argv))},
        "envelope": {"bytes": len(envelope), "count": len(vector), "sha256": sha(envelope)},
        "environment_names": [item.split("=", 1)[0] for item in environment],
        "launch": {
            "cwd": str(SEED_REPO),
            "stdin": "/dev/null",
            "zsh_argv": {
                "bytes": len(compact(zsh_argv)),
                "count": len(zsh_argv),
                "sha256": sha(compact(zsh_argv)),
            },
        },
        "vector": {"bytes": len(compact(vector)), "count": len(vector), "sha256": sha(compact(vector))},
    }


def validate_design() -> dict[str, Any]:
    plan_payload = read_regular(PLAN)[0]
    status_payload = read_regular(STATUS)[0]
    helper_payload = read_regular(HELPER)[0]
    derived = derive_all(plan_payload, helper_payload)
    contract_payload = derived["contract"]
    acceptance = controller_acceptance(
        plan_payload=plan_payload,
        status_payload=status_payload,
        source_payload=derived["source"],
        helper_payload=helper_payload,
        driver_payload=derived["driver"],
        contract_payload=contract_payload,
    )
    acceptance_validation = static_acceptance_validation(
        acceptance,
        plan_payload=plan_payload,
        status_payload=status_payload,
        source_payload=derived["source"],
        helper_payload=helper_payload,
        driver_payload=derived["driver"],
        contract_payload=contract_payload,
    )
    evidence = validate_nonsecret_evidence()
    acceptance_json = compact(acceptance).decode()
    commands = command_identities(
        source_payload=derived["source"],
        plan_sha=sha(plan_payload),
        status_sha=sha(status_payload),
        helper_sha=sha(helper_payload),
        driver_sha=sha(derived["driver"]),
        contract_sha=sha(contract_payload),
        acceptance_json=acceptance_json,
    )
    return {
        "acceptance": {"bytes_with_lf": len(compact(acceptance)) + 1, "sha256_with_lf": sha(compact(acceptance) + b"\n")},
        "acceptance_validation": acceptance_validation,
        "commands": commands,
        "contract": {"bytes": len(contract_payload), "sha256": sha(contract_payload)},
        "contract_validation": derived["contract_validation"],
        "documents": {
            "exec_plan": {"bytes": len(plan_payload), "sha256": sha(plan_payload)},
            "status": {"bytes": len(status_payload), "sha256": sha(status_payload)},
        },
        "driver": {"bytes": len(derived["driver"]), "sha256": sha(derived["driver"])},
        "driver_validation": derived["driver_validation"],
        "evidence": evidence,
        "helper": {"bytes": len(helper_payload), "sha256": sha(helper_payload)},
        "ruff": derived["ruff"],
        "runtime_nonsecret_validation": derived["runtime_nonsecret_validation"],
        "source": {"bytes": len(derived["source"]), "sha256": sha(derived["source"])},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate",))
    args = parser.parse_args()
    if args.command == "validate":
        sys.stdout.buffer.write(compact(validate_design()) + b"\n")


if __name__ == "__main__":
    main()
