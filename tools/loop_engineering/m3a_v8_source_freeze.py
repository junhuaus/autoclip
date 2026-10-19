#!/usr/bin/env python3
"""Freeze the credential-blind M3A-v8 root and later opaque handoff.

Static mode validates only non-secret evidence.  The embedded writer exposes
three separately authorized root phases: transport, self-check, and finalize.
Only the derived sealed driver can perform the later opaque authentication
handoff; static mode and every root phase omit both credential paths.
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
HELPER = DELIVERY / "tools/loop_engineering/m3a_v8_source_freeze.py"
V7_HELPER = DELIVERY / "tools/loop_engineering/m3a_v7_source_freeze.py"
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
TARGET = BASE / "candidate.8H1oW7vy"
TARGET_REPO = TARGET / "repo"
RUN_ID = "20261019T185413Z-870d2c8c"
RUN = TARGET_REPO / ".loop/runs" / RUN_ID
V48_ROOT = BASE / "trusted-tools/m3-successor-preparation-v48"
V7_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v7"
V7_DRIVER = V7_ROOT / "handoff-driver.py"
V8_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v8"
V8_DRIVER = V8_ROOT / "handoff-driver.py"
V8_RECEIPTS = V8_ROOT / "receipts"
V8_RESULT = V8_RECEIPTS / "auth-handoff-v8-result.json"
WRITER_BEGIN = "# BEGIN M3A_V8_WRITER_SOURCE\n"
WRITER_END = "# END M3A_V8_WRITER_SOURCE\n"

EXPECTED_HEAD = "2f361fcddc0e63ae62ee62826e27b54bb8204c53"
EXPECTED_DELIVERY = (0, 15, 183)
EXPECTED_TARGET = (0, 15, 74)
EXPECTED_V7_HELPER = (
    47333,
    "8a5395189b641852032273e6fe1d5afd28703c3d1093b27139090d5bf3ba5e67",
)
EXPECTED_V7_DRIVER = (
    31666,
    "d4a0fb12e65ebdfdad8295cac03eb8468c3a7569b517bdb309a40006b2bb64cb",
)
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
EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO",
    "candidate.3WBt3ldA",
    "candidate.3Wlu7MyG",
    "candidate.5jh3bylk",
    "candidate.5nZWpynN",
    "candidate.8H1oW7vy",
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
V48_ROOT_FILES: dict[str, tuple[int, str]] = {
    "candidate-driver.py": (
        577054,
        "cf6000818bc06823e3ae7464f6e7218365b06dcfaa8bf0fb95d11ddcb317ec30",
    ),
    "receipts/controller-acceptance-v48.json": (
        16999,
        "e46d3f0cef022139e8a1bcfe888a49985bd1e4ea06fa2d24d10303eeba6c060b",
    ),
    "receipts/final-index.json": (
        800,
        "c5d453ab94cb71f564a72517242fc692c8af0d3842101bf08ff092746a775fb0",
    ),
    "receipts/self-check-result.json": (
        4320,
        "597581fc98d40596f4b30b5a7ca07244704d3ea4b41e3d367eb92524c48068df",
    ),
    "receipts/source-receipt.json": (
        381,
        "34b070a94466dfe17a0c37cdeced3383d14a702f85379068ee1833a8307d26ce",
    ),
    "receipts/successor-preparation-v48-result.json": (
        23851,
        "6d54a37978db7d5bc37ff131ba9156f28317c1b460204412e4b7d459bae2914d",
    ),
    "receipts/writer-self-test.json": (
        53,
        "3c31afa2642bd63ff436297754cf593ca0cb9d3c14924c3abfdc4e7358f498d8",
    ),
}
TARGET_FILES: dict[str, tuple[int, str, int]] = {
    f"repo/.loop/runs/{RUN_ID}/events.jsonl": (
        144,
        "08877d5d9c90a30e5a9f5859c48cfaacf86f6262158dc6b7d961cd46a99efe5f",
        0o644,
    ),
    f"repo/.loop/runs/{RUN_ID}/state.json": (
        12796,
        "e00eb8d809c55bd767280a4b1bda8d63f265ffa4528e7259e16951e77d36b2a7",
        0o644,
    ),
    "repo/.loop/trusted/final-controller-acceptance-v48.json": (
        5132,
        "7d50309503a1fa5ccdb40f1036c2902d624978505865027a456b55764ef2c1cb",
        0o600,
    ),
    "successor-receipts/final-receipt-index.json": (
        18096,
        "f72bf846f30ca9f86254c966d84b00bb5f73fd837c9e0045cca47b6282151982",
        0o600,
    ),
    "successor-receipts/postacceptance-attempt-manifest.jsonl": (
        12184575,
        "9fdf7bfcbbf5967d80f4672a470d28da8ff689932b1cf0a0e72c53bc9ac3a46f",
        0o600,
    ),
    "successor-receipts/postacceptance-final-index.json": (
        2731,
        "f883864347d69e1011fdd2d7f77bbcf8688b806583a4c1ce8dcb3d364455e403",
        0o600,
    ),
    "successor-receipts/postacceptance-repository-manifest.jsonl": (
        6146580,
        "251b988f9a090b3afeedb6e40b2a7828bcffbdc8650ed4685fe47742a8554c47",
        0o600,
    ),
    "successor-receipts/successor-v48-controller-acceptance-offer.json": (
        5801,
        "557bf04cfa13b5c1c02c2f61a625f966857c602b0e0b45c046cd955f195d300f",
        0o600,
    ),
    "successor-receipts/successor-v48-controller-acceptance-transport.json": (
        1383,
        "520281505508fef8bb8428a9dfc82e339f8ec3da7f3bc3e23ac783997ff35baa",
        0o600,
    ),
    "successor-receipts/successor-v48-policy-snapshot.json": (
        4828,
        "b6362fa377ee5b210b6793cc69b941fcfa4ab272d17a9a0dd43df81719c464ca",
        0o600,
    ),
    "successor-receipts/successor-v48-preparation-bindings.json": (
        5414,
        "045ea56c60a7d55d8d58d9dfc318095b5f5e7e24c7842c75be31dd7b245312e3",
        0o600,
    ),
    "successor-receipts/successor-v48-toolchain-snapshot.json": (
        4878,
        "ebd73ede1ba08fdd0f8ca39ecc3993bab5fcb5b1ae4f4ab0413a8e7ff9f8d80e",
        0o600,
    ),
    "successor-receipts/successor-v48-trusted-context.json": (
        19034,
        "7591ff21917b527759a4677019ac04d872f10cf62f2e1228a8305d5444c2c9f7",
        0o600,
    ),
}
ROOT_RECEIPT_FILES = {
    "controller-acceptance-v8.json",
    "final-index.json",
    "self-check-result.json",
    "source-receipt.json",
    "writer-self-test.json",
}
ROOT_ACCEPTANCE_KEYS = {
    "contract",
    "documents",
    "driver",
    "format_version",
    "helper",
    "phase",
    "result",
    "root",
    "security",
    "source",
    "target",
}
ROOT_FINAL_INDEX_KEYS = {
    "controller_acceptance_sha256",
    "driver_sha256",
    "format_version",
    "phase",
    "result",
    "root_argv_sha256",
    "source_sha256",
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


def read_regular(path: Path, maximum: int | None = None) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(), f"regular file required: {path}")
    if maximum is not None:
        require(before.st_size <= maximum, f"file too large: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        require(
            (opened.st_dev, opened.st_ino, opened.st_size)
            == (before.st_dev, before.st_ino, before.st_size),
            f"file changed before read: {path}",
        )
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(fd)
        require(
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns),
            f"file changed during read: {path}",
        )
    finally:
        os.close(fd)
    payload = b"".join(chunks)
    require(len(payload) == before.st_size, f"read size mismatch: {path}")
    return payload, before


def exact_file(path: Path, expected: tuple[int, str], mode: int | None = None) -> bytes:
    payload, info = read_regular(path)
    require((len(payload), sha(payload)) == expected, f"identity mismatch: {path}")
    if mode is not None:
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == mode, f"mode mismatch: {path}")
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
    result = subprocess.run(  # noqa: S603 - fixed git executable and literals
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
    require(git_capture(repo, ["branch", "--show-current"]) == b"main\n", "branch mismatch")
    require(git_capture(repo, ["rev-parse", "HEAD"]).decode().strip() == EXPECTED_HEAD, "HEAD mismatch")
    require(status_counts(repo) == expected, "inventory mismatch")


def line_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, character in enumerate(text):
        if character == "\n":
            offsets.append(index + 1)
    return offsets


def span(node: ast.AST, offsets: list[int]) -> tuple[int, int]:
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
    start, end = span(matches[0], line_offsets(text))
    return text[start:end].encode()


def assignment_name(node: ast.Assign) -> str | None:
    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def replace_nodes(text: str, replacements: dict[str, str]) -> str:
    tree = ast.parse(text)
    offsets = line_offsets(text)
    edits: list[tuple[int, int, str]] = []
    found: set[str] = set()
    for node in tree.body:
        key = assignment_name(node) if isinstance(node, ast.Assign) else None
        if isinstance(node, ast.FunctionDef):
            key = node.name
        if key in replacements:
            require(key not in found, f"duplicate node: {key}")
            start, end = span(node, offsets)
            edits.append((start, end, replacements[key]))
            found.add(key)
    require(found == set(replacements), "replacement node mismatch")
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def assignment(name: str, value: Any) -> str:
    return f"{name} = {pprint.pformat(value, width=118, sort_dicts=True)}"


def handoff_contract() -> dict[str, Any]:
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
            "candidate_count": 29,
            "completed_tree": {
                "bytes": 968178470,
                "paths": 44358,
                "sha256": "9fdcea266b847db25389f1412d819ca89e2824f6c4c202350518a619c6eb0d1f",
            },
            "final_acceptance_sha256": TARGET_FILES[
                "repo/.loop/trusted/final-controller-acceptance-v48.json"
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
            "acceptance_requirement_v2_sha256": EXPECTED_REQUIREMENT_V2[1],
            "acceptance_requirement_v3_sha256": EXPECTED_REQUIREMENT_V3[1],
            "architecture_sha256": EXPECTED_ARCHITECTURE[1],
            "postacceptance_attempt_manifest_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-attempt-manifest.jsonl"
            ][1],
            "postacceptance_repository_manifest_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-repository-manifest.jsonl"
            ][1],
            "preparation_bindings_sha256": TARGET_FILES[
                "successor-receipts/successor-v48-preparation-bindings.json"
            ][1],
            "preparation_offer_sha256": TARGET_FILES[
                "successor-receipts/successor-v48-controller-acceptance-offer.json"
            ][1],
            "root_final_index_sha256": V48_ROOT_FILES["receipts/final-index.json"][1],
            "successor_policy_sha256": TARGET_FILES[
                "successor-receipts/successor-v48-policy-snapshot.json"
            ][1],
            "successor_toolchain_sha256": TARGET_FILES[
                "successor-receipts/successor-v48-toolchain-snapshot.json"
            ][1],
            "successor_trusted_context_sha256": TARGET_FILES[
                "successor-receipts/successor-v48-trusted-context.json"
            ][1],
            "v7_failure": "ROOT_ACCEPTANCE_SCHEMA_MISMATCH",
            "v7_nonreuse": True,
        },
        "formal_role_authority": False,
        "format_version": 1,
        "phase": "M3A_V8_AUTH_HANDOFF",
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
        "run": {
            "code_cycle": 0,
            "cycle": 0,
            "events_sha256": TARGET_FILES[f"repo/.loop/runs/{RUN_ID}/events.jsonl"][1],
            "state": "received",
            "state_sha256": TARGET_FILES[f"repo/.loop/runs/{RUN_ID}/state.json"][1],
        },
        "v48": {
            "driver_sha256": V48_ROOT_FILES["candidate-driver.py"][1],
            "final_acceptance_sha256": TARGET_FILES[
                "repo/.loop/trusted/final-controller-acceptance-v48.json"
            ][1],
            "final_index_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-final-index.json"
            ][1],
            "preparation_result_sha256": V48_ROOT_FILES[
                "receipts/successor-preparation-v48-result.json"
            ][1],
        },
    }


def root_receipt_validator_source() -> str:
    return '''def validate_root_receipt_values(
    *,
    acceptance_value: dict[str, Any],
    final_value: dict[str, Any],
    contract_value: dict[str, Any],
    expected_acceptance_sha256: str,
    expected_final_index_sha256: str,
    expected_driver_sha256: str,
    expected_root_argv_sha256: str,
    expected_source_sha256: str,
) -> None:
    require(set(acceptance_value) == ROOT_ACCEPTANCE_KEYS, "ROOT_ACCEPTANCE_SCHEMA_MISMATCH")
    require(set(final_value) == ROOT_FINAL_INDEX_KEYS, "ROOT_INDEX_SCHEMA_MISMATCH")
    contract_payload = compact(contract_value)
    require(
        acceptance_value["contract"]
        == {"canonical_bytes": len(contract_payload), "sha256": sha(contract_payload)},
        "CONTRACT_MISMATCH",
    )
    require(
        acceptance_value["phase"] == "M3A_V8_CONTROLLER_ACCEPTANCE"
        and acceptance_value["result"] == "ACCEPTED_BEFORE_ROOT_CREATION",
        "ROOT_ACCEPTANCE_SCHEMA_MISMATCH",
    )
    require(
        acceptance_value["root"]
        == {
            "fixed_name": "m3-authentication-handoff-v8",
            "no_replace": True,
            "result_absent": True,
            "root_absent": True,
        },
        "ROOT_ACCEPTANCE_SCHEMA_MISMATCH",
    )
    require(acceptance_value["driver"]["sha256"] == expected_driver_sha256, "ROOT_ACCEPTANCE_SCHEMA_MISMATCH")
    require(acceptance_value["source"]["sha256"] == expected_source_sha256, "ROOT_ACCEPTANCE_SCHEMA_MISMATCH")
    require(sha(compact(acceptance_value) + b"\\n") == expected_acceptance_sha256, "CONTROLLER_ACCEPTANCE_MISMATCH")
    require(re.fullmatch(r"[0-9a-f]{64}", expected_root_argv_sha256) is not None, "ROOT_INDEX_SCHEMA_MISMATCH")
    expected_final = root_final_index(
        acceptance_sha256=expected_acceptance_sha256,
        driver_sha256=expected_driver_sha256,
        root_argv_sha256=expected_root_argv_sha256,
        source_sha256=expected_source_sha256,
    )
    require(final_value == expected_final, "ROOT_INDEX_SCHEMA_MISMATCH")
    require(sha(pretty(final_value)) == expected_final_index_sha256, "ROOT_INDEX_MISMATCH")'''


def derive_driver(predecessor: bytes) -> bytes:
    require((len(predecessor), sha(predecessor)) == EXPECTED_V7_DRIVER, "V7 driver mismatch")
    text = predecessor.decode()
    for old, new in (
        ("M3A_V7", "M3A_V8"),
        ("m3-authentication-handoff-v7", "m3-authentication-handoff-v8"),
        ("auth-handoff-v7-result.json", "auth-handoff-v8-result.json"),
        ("controller-acceptance-v7.json", "controller-acceptance-v8.json"),
        ("candidate.3Wlu7MyG", "candidate.8H1oW7vy"),
        ("20261016T010806Z-b7f48207", RUN_ID),
        ("V44", "V48"),
        ("v44", "v48"),
    ):
        require(old in text, f"missing predecessor token: {old}")
        text = text.replace(old, new)
        require(old not in text, f"stale predecessor token: {old}")
    text = replace_nodes(
        text,
        {
            "EXPECTED_DELIVERY": assignment("EXPECTED_DELIVERY", EXPECTED_DELIVERY),
            "EXPECTED_TARGET": assignment("EXPECTED_TARGET", EXPECTED_TARGET),
            "EXPECTED_CANDIDATES": assignment("EXPECTED_CANDIDATES", set(EXPECTED_CANDIDATES)),
            "V48_FILES": assignment("V48_FILES", V48_ROOT_FILES),
            "TARGET_FILES": assignment("TARGET_FILES", TARGET_FILES),
            "HANDOFF_CONTRACT": assignment("HANDOFF_CONTRACT", handoff_contract()),
            "validate_root_receipt_values": root_receipt_validator_source(),
        },
    )
    payload = text.encode()
    compile(payload, "<m3a-v8-driver>", "exec", dont_inherit=True)
    return payload


def writer_source(helper: bytes) -> bytes:
    source = f'''from __future__ import annotations
import hashlib
import importlib.util
import sys
from pathlib import Path

HELPER = Path({str(HELPER)!r})
EXPECTED_HELPER_SIZE = {len(helper)}
EXPECTED_HELPER_SHA256 = {sha(helper)!r}
payload = HELPER.read_bytes()
if len(payload) != EXPECTED_HELPER_SIZE or hashlib.sha256(payload).hexdigest() != EXPECTED_HELPER_SHA256:
    raise RuntimeError("M3A-v8 helper identity mismatch")
spec = importlib.util.spec_from_file_location("m3a_v8_source_freeze", HELPER)
if spec is None or spec.loader is None:
    raise RuntimeError("M3A-v8 helper loader unavailable")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if sys.argv[:2] != ["-c", "--"]:
    raise RuntimeError("M3A-v8 Python -c argv shape mismatch")
module.root_dispatch(sys.argv[2:])
'''
    payload = source.encode()
    compile(payload, "<m3a-v8-writer>", "exec", dont_inherit=True)
    return payload


def extract_writer(plan: bytes) -> bytes:
    text = plan.decode()
    require(text.count(WRITER_BEGIN) == 1 and text.count(WRITER_END) == 1, "writer marker mismatch")
    return text.split(WRITER_BEGIN, 1)[1].split(WRITER_END, 1)[0].encode()


def controller_acceptance(
    plan: bytes, status: bytes, helper: bytes, writer: bytes, driver: bytes, contract: bytes
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
        "phase": "M3A_V8_CONTROLLER_ACCEPTANCE",
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": {
            "fixed_name": V8_ROOT.name,
            "no_replace": True,
            "result_absent": True,
            "root_absent": True,
        },
        "security": {
            "credential_blind_root_phases": ["transport", "self-check", "finalize"],
            "destination_precondition": "UNPROBED_EXCLUSIVE_GATE_INSIDE_HANDOFF",
            "formal_role_authority": False,
            "login_status_launched": False,
        },
        "source": {"bytes": len(writer), "sha256": sha(writer)},
        "target": {
            "candidate": TARGET.name,
            "run_id": RUN_ID,
            "v48_final_index_sha256": TARGET_FILES[
                "successor-receipts/postacceptance-final-index.json"
            ][1],
        },
    }


def derive_all(plan: bytes, status: bytes, helper: bytes) -> dict[str, Any]:
    writer = writer_source(helper)
    predecessor = exact_file(V7_DRIVER, EXPECTED_V7_DRIVER, 0o600)
    driver = derive_driver(predecessor)
    contract = compact(handoff_contract())
    acceptance = controller_acceptance(plan, status, helper, writer, driver, contract)
    return {
        "acceptance": acceptance,
        "acceptance_payload": compact(acceptance) + b"\n",
        "contract": contract,
        "driver": driver,
        "writer": writer,
    }


def quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def command_identity(argv: list[str], *, home: Path, tmp: Path) -> dict[str, Any]:
    argv_payload = compact(argv)
    vector = [
        "/usr/bin/env",
        "-i",
        f"HOME={home}",
        f"TMPDIR={tmp}",
        "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG=C",
        "LC_ALL=C",
        "PYTHONDONTWRITEBYTECODE=1",
        "GIT_OPTIONAL_LOCKS=0",
        "__CF_USER_TEXT_ENCODING=0x1F5:0x0:0x0",
        *argv,
    ]
    vector_payload = compact(vector)
    payload = "exec " + " ".join(quote(value) for value in vector) + " </dev/null"
    outer = ["/bin/zsh", "-f", "-c", payload]
    return {
        "argv": {"bytes": len(argv_payload), "sha256": sha(argv_payload), "strings": len(argv)},
        "clean_vector": {
            "bytes": len(vector_payload),
            "sha256": sha(vector_payload),
            "strings": len(vector),
        },
        "literal_payload": {
            "bytes": len(payload.encode()),
            "sha256": sha(payload.encode()),
            "tokens": len(vector),
        },
        "outer_argv": {
            "bytes": len(compact(outer)),
            "sha256": sha(compact(outer)),
            "strings": len(outer),
        },
    }


def phase_arguments(
    phase: str, plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]
) -> list[str]:
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
    require(phase == "finalize", "unknown root phase")
    return [
        phase,
        *common,
        "--expected-controller-acceptance-sha256",
        acceptance_sha,
        "--expected-self-check-sha256",
        sha(self_check_payload(plan, status, helper, derived)),
        "--expected-writer-self-test-sha256",
        sha(writer_test_payload()),
    ]


def root_commands(
    plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for phase in ("transport", "self-check", "finalize"):
        args = phase_arguments(phase, plan, status, helper, derived)
        argv = [str(PYTHON), "-c", derived["writer"].decode(), "--", *args]
        result[phase] = command_identity(argv, home=V8_ROOT / "home", tmp=V8_ROOT / "tmp")
        result[phase]["schema"] = [args[0], *args[1::2]]
    return result


def final_index_value(
    plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]
) -> dict[str, Any]:
    transport_args = phase_arguments("transport", plan, status, helper, derived)
    transport_argv = [
        str(PYTHON),
        "-c",
        derived["writer"].decode(),
        "--",
        *transport_args,
    ]
    transport = command_identity(
        transport_argv, home=V8_ROOT / "home", tmp=V8_ROOT / "tmp"
    )
    return {
        "controller_acceptance_sha256": sha(derived["acceptance_payload"]),
        "driver_sha256": sha(derived["driver"]),
        "format_version": 1,
        "phase": "M3A_V8_FINAL_INDEX",
        "result": "M3A_V8_READY_FOR_CONTROLLER_REVIEW",
        "root_argv_sha256": transport["argv"]["sha256"],
        "source_sha256": sha(derived["writer"]),
    }


def source_receipt_payload(helper: bytes, derived: dict[str, Any]) -> bytes:
    return pretty(
        {
            "contract_sha256": sha(derived["contract"]),
            "driver_sha256": sha(derived["driver"]),
            "format_version": 1,
            "helper_sha256": sha(helper),
            "phase": "M3A_V8_SOURCE_RECEIPT",
            "result": "PASS",
            "source_sha256": sha(derived["writer"]),
        }
    )


def writer_test_payload() -> bytes:
    return pretty({"format_version": 1, "phase": "M3A_V8_WRITER_SELF_TEST", "result": "PASS"})


def sanitized_success() -> dict[str, Any]:
    return {
        "copy_success": True,
        "destination_mode": "0600",
        "destination_owner_uid": 501,
        "format_version": 1,
        "login_status": "SUPPORTED_AUTHENTICATED",
        "phase": "M3A_V8_AUTH_HANDOFF",
        "result": "READY_FOR_CONTROLLER_REVIEW",
        "sanitized_error": None,
    }


def handoff_command(
    plan: bytes, status: bytes, derived: dict[str, Any], final_index: bytes
) -> dict[str, Any]:
    argv = [
        str(PYTHON),
        str(V8_DRIVER),
        "auth-handoff",
        "--expected-self-sha",
        sha(derived["driver"]),
        "--plan",
        str(PLAN),
        "--expected-plan-sha256",
        sha(plan),
        "--status",
        str(STATUS),
        "--expected-status-sha256",
        sha(status),
        "--expected-root-final-index-sha256",
        sha(final_index),
        "--expected-controller-acceptance-sha256",
        sha(derived["acceptance_payload"]),
    ]
    result = command_identity(argv, home=TARGET / "home", tmp=TARGET / "tmp")
    result["bounds"] = {
        "diagnostic_bytes": 65536,
        "login_status_seconds": 30,
        "outer_seconds": 120,
        "sanitized_stdout_bytes": 4096,
    }
    result["expected_stdout"] = {
        "bytes": len(compact(sanitized_success()) + b"\n"),
        "sha256": sha(compact(sanitized_success()) + b"\n"),
    }
    result["expected_result"] = {
        "bytes": len(pretty(sanitized_success())),
        "sha256": sha(pretty(sanitized_success())),
    }
    return result


def load_driver_namespace(driver: bytes) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": "m3a_v8_driver_static"}
    exec(compile(driver, "<m3a-v8-driver-static>", "exec", dont_inherit=True), namespace)  # noqa: S102
    return namespace


def validate_root_schema(
    plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]
) -> dict[str, Any]:
    acceptance = derived["acceptance"]
    final_value = final_index_value(plan, status, helper, derived)
    final_payload = pretty(final_value)
    namespace = load_driver_namespace(derived["driver"])
    validator = namespace["validate_root_receipt_values"]
    kwargs = {
        "acceptance_value": acceptance,
        "final_value": final_value,
        "contract_value": json.loads(derived["contract"]),
        "expected_acceptance_sha256": sha(derived["acceptance_payload"]),
        "expected_final_index_sha256": sha(final_payload),
        "expected_driver_sha256": sha(derived["driver"]),
        "expected_root_argv_sha256": final_value["root_argv_sha256"],
        "expected_source_sha256": sha(derived["writer"]),
    }
    validator(**kwargs)
    negatives: list[tuple[str, dict[str, Any]]] = []
    for name, mutate in (
        ("v7 acceptance extra writer", lambda a, f, k: a.__setitem__("writer", {})),
        ("acceptance missing source", lambda a, f, k: a.pop("source")),
        ("acceptance wrong phase", lambda a, f, k: a.__setitem__("phase", "M3A_V7_CONTROLLER_ACCEPTANCE")),
        ("acceptance wrong driver", lambda a, f, k: a["driver"].__setitem__("sha256", "0" * 64)),
        ("acceptance wrong source", lambda a, f, k: a["source"].__setitem__("sha256", "0" * 64)),
        ("v7 index extra phase argv", lambda a, f, k: f.__setitem__("phase_argv_sha256", {})),
        ("index missing source", lambda a, f, k: f.pop("source_sha256")),
        ("index wrong acceptance", lambda a, f, k: f.__setitem__("controller_acceptance_sha256", "0" * 64)),
        ("index wrong root argv", lambda a, f, k: f.__setitem__("root_argv_sha256", "0" * 64)),
        ("index wrong verdict", lambda a, f, k: f.__setitem__("result", "READY")),
        ("wrong contract", lambda a, f, k: k.__setitem__("formal_role_authority", True)),
    ):
        a = json.loads(json.dumps(acceptance))
        f = json.loads(json.dumps(final_value))
        k = json.loads(derived["contract"])
        mutate(a, f, k)
        negatives.append((name, {"acceptance_value": a, "final_value": f, "contract_value": k}))
    rejected = 0
    for name, changed in negatives:
        try:
            validator(**{**kwargs, **changed})
        except BaseException:
            rejected += 1
        else:
            raise RuntimeError(f"root schema negative accepted: {name}")
    require(rejected == len(negatives), "root schema rejection count mismatch")
    return {"negative_fixtures": len(negatives), "positive": "PASS", "shared_driver_validator": "PASS"}


def validate_driver(predecessor: bytes, driver: bytes) -> dict[str, Any]:
    compile(driver, "<m3a-v8-driver>", "exec", dont_inherit=True)
    tree = ast.parse(driver)
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    require(
        {
            "opaque_copy_state",
            "terminate_group",
            "login_status",
            "receipt",
            "validate_root",
            "validate_root_receipt_values",
            "validate_v48_and_target",
        }
        <= names,
        "driver phase surface mismatch",
    )
    require(b"M3A_V7_AUTH_HANDOFF" not in driver and driver.count(b"M3A_V8_AUTH_HANDOFF") == 2, "phase mismatch")
    equivalence: dict[str, str] = {}
    for name in ("opaque_copy_state", "terminate_group", "login_status", "receipt"):
        old = function_source(predecessor, name)
        new = function_source(driver, name).replace(b"M3A_V8", b"M3A_V7")
        require(new == old, f"security source equivalence mismatch: {name}")
        equivalence[name] = sha(new)
    opaque = function_source(driver, "opaque_copy_state")
    for operation in (b"lstat", b"os.open", b"os.fstat", b"os.read", b"os.write", b"os.fsync"):
        require(operation in opaque, f"opaque operation missing: {operation.decode()}")
    login = function_source(driver, "login_status")
    require(login.count(b"subprocess.DEVNULL") == 3 and b"shell=False" in login, "child channel mismatch")
    require(b"timeout=30" in login, "login timeout mismatch")
    early = function_source(driver, "validate_v48_and_target")
    require(b"AUTH_SOURCE" not in early and b"AUTH_DESTINATION" not in early, "protected entry referenced early")
    return {"ast_compile": "PASS", "equivalent_security_functions": equivalence, "result": "PASS"}


def ruff_validation(payload: bytes, filename: str) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603 - pinned project-local Ruff
        [str(RUFF), "check", "--select", "F,B,S", "--stdin-filename", filename, "-"],
        input=payload,
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
    require(result.returncode == 0, f"Ruff F/B/S failed: {filename}: {result.stdout.decode()}")
    return {"returncode": 0, "stderr_sha256": sha(result.stderr), "stdout_sha256": sha(result.stdout)}


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


def validate_nonsecret_evidence(*, root_absent: bool = True) -> dict[str, Any]:
    validate_git(DELIVERY, EXPECTED_DELIVERY)
    validate_git(TARGET_REPO, EXPECTED_TARGET)
    exact_file(ARCHITECTURE, EXPECTED_ARCHITECTURE)
    exact_file(REQUIREMENT_V2, EXPECTED_REQUIREMENT_V2)
    exact_file(REQUIREMENT_V3, EXPECTED_REQUIREMENT_V3)
    exact_file(V7_HELPER, EXPECTED_V7_HELPER)
    exact_file(V7_DRIVER, EXPECTED_V7_DRIVER, 0o600)
    private_directory(V48_ROOT)
    for relative, expected in V48_ROOT_FILES.items():
        exact_file(V48_ROOT / relative, expected, 0o600)
    for relative, (size, digest, mode) in TARGET_FILES.items():
        exact_file(TARGET / relative, (size, digest), mode)
    post_index = json.loads(read_regular(TARGET / "successor-receipts/postacceptance-final-index.json")[0])
    require(
        post_index.get("verdict") == "M3S_V48_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW"
        and post_index.get("repository", {}).get("path_count") == 27445
        and post_index.get("repository", {}).get("regular_file_bytes") == 581611455
        and post_index.get("attempt_pre_index", {}).get("path_count") == 44356
        and post_index.get("attempt_pre_index", {}).get("regular_file_bytes") == 955991164,
        "V48 postacceptance model mismatch",
    )
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
    if root_absent:
        require(not V8_ROOT.exists() and not V8_ROOT.is_symlink(), "V8 root already exists")
    require(not V8_RESULT.exists() and not V8_RESULT.is_symlink(), "V8 result already exists")
    require(
        not (V48_ROOT / "receipts/final-controller-acceptance-v48-result.json").exists()
        and not (V48_ROOT / "receipts/auth-handoff-v48-result.json").exists(),
        "V48 reserved root result exists",
    )
    return {
        "authentication_location_probe": False,
        "candidate_count": len(candidates),
        "candidate_names_sha256": sha(compact(list(candidates))),
        "delivery_inventory": list(status_counts(DELIVERY)),
        "destination_probe": False,
        "process_absence": validate_process_absence(),
        "result_absent": True,
        "root_absent": root_absent,
        "run_pristine": True,
        "target_inventory": list(status_counts(TARGET_REPO)),
        "v48_postacceptance": "PASS",
        "v7_nonreuse": "PASS",
    }


def validate_documents(plan: bytes, status: bytes, helper: bytes) -> dict[str, Any]:
    required = (
        "candidate.8H1oW7vy",
        RUN_ID,
        TARGET_FILES["successor-receipts/postacceptance-final-index.json"][1],
        "M3S_V48_FINAL_PROVENANCE_READY_FOR_CONTROLLER_REVIEW",
        "m3-authentication-handoff-v8",
        "ROOT_ACCEPTANCE_SCHEMA_MISMATCH",
        "M3A_V8_ROOT_TRANSPORT",
        "M3A_V8_ROOT_SELF_CHECK",
        "M3A_V8_ROOT_FINALIZE",
        "authentication is not formal",
    )
    for label, payload in (("plan", plan), ("status", status)):
        text = payload.decode()
        for value in required:
            require(value in text, f"{label} missing {value}")
        require(text.endswith("\n"), f"{label} missing final newline")
        require(text.count("```") % 2 == 0, f"{label} fence mismatch")
    require(extract_writer(plan) == writer_source(helper), "embedded writer mismatch")
    return {"headings": "PASS", "markers": "PASS", "writer": "PASS"}


def static_contract_validation(contract: bytes) -> dict[str, Any]:
    expected = handoff_contract()
    require(contract == compact(expected) and json.loads(contract) == expected, "contract mismatch")
    mutations = (
        ("phase", "M3A_V7_AUTH_HANDOFF"),
        ("formal_role_authority", True),
        ("candidate.name", "candidate.3Wlu7MyG"),
        ("candidate.candidate_count", 28),
        ("candidate.final_index_sha256", "0" * 64),
        ("delivery.inventory", [0, 15, 182]),
        ("privacy.opaque_copy", False),
        ("privacy.child_channels", "PIPE"),
        ("privacy.secret_derived_metadata", True),
        ("budgets.handoff_invocation", 2),
        ("bounds.login_status_seconds", 31),
        ("v48.final_index_sha256", "0" * 64),
        ("evidence.v7_nonreuse", False),
    )
    for dotted, value in mutations:
        candidate = json.loads(json.dumps(expected))
        current = candidate
        parts = dotted.split(".")
        for part in parts[:-1]:
            current = current[part]
        current[parts[-1]] = value
        require(compact(candidate) != contract, f"ineffective contract negative: {dotted}")
    return {"negative_fixtures": len(mutations), "positive": "PASS"}


def self_check_payload(
    plan: bytes, status: bytes, helper: bytes, derived: dict[str, Any]
) -> bytes:
    return pretty(
        {
            "contract": static_contract_validation(derived["contract"]),
            "documents": validate_documents(plan, status, helper),
            "driver": validate_driver(exact_file(V7_DRIVER, EXPECTED_V7_DRIVER, 0o600), derived["driver"]),
            "format_version": 1,
            "phase": "M3A_V8_SELF_CHECK",
            "result": "PASS",
            "root_schema": validate_root_schema(plan, status, helper, derived),
            "security": {
                "authentication_location_probe": False,
                "credential_blind": True,
                "destination_probe": False,
                "login_status_launched": False,
            },
        }
    )


def nonsecret_snapshot() -> str:
    records: list[Any] = []
    for path in (
        PLAN,
        STATUS,
        HELPER,
        V7_HELPER,
        V7_DRIVER,
        V48_ROOT / "candidate-driver.py",
        V48_ROOT / "receipts/final-index.json",
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
    records.append(("v8_root_absent", not V8_ROOT.exists() and not V8_ROOT.is_symlink()))
    records.append(("v8_result_absent", not V8_RESULT.exists() and not V8_RESULT.is_symlink()))
    return sha(compact(records))


def validate_root_environment() -> None:
    require(Path.cwd().resolve() == SEED_REPO.resolve(), "root cwd mismatch")
    require(
        set(os.environ)
        == {
            "HOME",
            "TMPDIR",
            "PATH",
            "LANG",
            "LC_ALL",
            "PYTHONDONTWRITEBYTECODE",
            "GIT_OPTIONAL_LOCKS",
            "__CF_USER_TEXT_ENCODING",
        },
        "root environment mismatch",
    )


def parse_phase(argv: list[str]) -> tuple[str, dict[str, str]]:
    require(argv and argv[0] in {"transport", "self-check", "finalize"}, "phase mismatch")
    require(len(argv[1:]) % 2 == 0, "argument shape mismatch")
    values: dict[str, str] = {}
    for index in range(1, len(argv), 2):
        require(argv[index].startswith("--") and argv[index] not in values, "argument schema mismatch")
        values[argv[index]] = argv[index + 1]
    return argv[0], values


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
    values: dict[str, str], *, root_absent: bool
) -> tuple[bytes, bytes, bytes, dict[str, Any]]:
    helper = read_regular(HELPER)[0]
    plan = read_regular(PLAN)[0]
    status = read_regular(STATUS)[0]
    require(sha(plan) == values.get("--expected-plan-sha256"), "plan hash mismatch")
    require(sha(status) == values.get("--expected-status-sha256"), "status hash mismatch")
    require(sha(helper) == values.get("--expected-helper-sha256"), "helper hash mismatch")
    derived = derive_all(plan, status, helper)
    require(sha(derived["writer"]) == values.get("--expected-writer-sha256"), "writer mismatch")
    require(sha(derived["driver"]) == values.get("--expected-driver-sha256"), "driver mismatch")
    require(sha(derived["contract"]) == values.get("--expected-contract-sha256"), "contract mismatch")
    validate_documents(plan, status, helper)
    validate_nonsecret_evidence(root_absent=root_absent)
    return plan, status, helper, derived


def validate_partial_root(files: set[str], derived: dict[str, Any]) -> None:
    private_directory(V8_ROOT)
    private_directory(V8_ROOT / "home")
    private_directory(V8_ROOT / "tmp")
    private_directory(V8_RECEIPTS)
    require(set(os.listdir(V8_ROOT)) == {"handoff-driver.py", "home", "receipts", "tmp"}, "root domain mismatch")
    require(set(os.listdir(V8_RECEIPTS)) == files, "receipt domain mismatch")
    exact_file(V8_DRIVER, (len(derived["driver"]), sha(derived["driver"])), 0o600)
    require(not V8_RESULT.exists() and not V8_RESULT.is_symlink(), "reserved result exists")


def root_transport(values: dict[str, str]) -> dict[str, Any]:
    require(not V8_ROOT.exists() and not V8_ROOT.is_symlink(), "V8 root exists")
    _plan, _status, helper, derived = phase_context(values, root_absent=True)
    acceptance = json.loads(values.get("--controller-acceptance-json", ""))
    require(acceptance == derived["acceptance"], "transport acceptance mismatch")
    os.mkdir(V8_ROOT, 0o700)
    os.mkdir(V8_ROOT / "home", 0o700)
    os.mkdir(V8_ROOT / "tmp", 0o700)
    os.mkdir(V8_RECEIPTS, 0o700)
    write_exclusive(V8_DRIVER, derived["driver"])
    write_exclusive(V8_RECEIPTS / "controller-acceptance-v8.json", derived["acceptance_payload"])
    write_exclusive(V8_RECEIPTS / "source-receipt.json", source_receipt_payload(helper, derived))
    for directory in (V8_RECEIPTS, V8_ROOT / "home", V8_ROOT / "tmp", V8_ROOT):
        sync_directory(directory)
    return {"phase": "M3A_V8_ROOT_TRANSPORT", "result": "PASS"}


def root_self_check(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, derived = phase_context(values, root_absent=False)
    require(
        sha(derived["acceptance_payload"]) == values.get("--expected-controller-acceptance-sha256"),
        "acceptance mismatch",
    )
    validate_partial_root({"controller-acceptance-v8.json", "source-receipt.json"}, derived)
    exact_file(
        V8_RECEIPTS / "controller-acceptance-v8.json",
        (len(derived["acceptance_payload"]), sha(derived["acceptance_payload"])),
        0o600,
    )
    source = source_receipt_payload(helper, derived)
    exact_file(V8_RECEIPTS / "source-receipt.json", (len(source), sha(source)), 0o600)
    write_exclusive(V8_RECEIPTS / "writer-self-test.json", writer_test_payload())
    write_exclusive(V8_RECEIPTS / "self-check-result.json", self_check_payload(plan, status, helper, derived))
    sync_directory(V8_RECEIPTS)
    return {"phase": "M3A_V8_ROOT_SELF_CHECK", "result": "PASS"}


def root_finalize(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, derived = phase_context(values, root_absent=False)
    self_check = self_check_payload(plan, status, helper, derived)
    writer_test = writer_test_payload()
    require(
        sha(derived["acceptance_payload"]) == values.get("--expected-controller-acceptance-sha256"),
        "acceptance mismatch",
    )
    require(sha(self_check) == values.get("--expected-self-check-sha256"), "self-check mismatch")
    require(sha(writer_test) == values.get("--expected-writer-self-test-sha256"), "writer test mismatch")
    validate_partial_root(
        {
            "controller-acceptance-v8.json",
            "self-check-result.json",
            "source-receipt.json",
            "writer-self-test.json",
        },
        derived,
    )
    exact_file(V8_RECEIPTS / "self-check-result.json", (len(self_check), sha(self_check)), 0o600)
    exact_file(V8_RECEIPTS / "writer-self-test.json", (len(writer_test), sha(writer_test)), 0o600)
    final = pretty(final_index_value(plan, status, helper, derived))
    write_exclusive(V8_RECEIPTS / "final-index.json", final)
    sync_directory(V8_RECEIPTS)
    require(set(os.listdir(V8_RECEIPTS)) == ROOT_RECEIPT_FILES, "final receipt domain mismatch")
    return {"phase": "M3A_V8_ROOT_FINALIZE", "result": "M3A_V8_READY_FOR_CONTROLLER_REVIEW"}


def root_dispatch(argv: list[str]) -> None:
    validate_root_environment()
    phase, values = parse_phase(argv)
    handlers: dict[str, Callable[[dict[str, str]], dict[str, Any]]] = {
        "transport": root_transport,
        "self-check": root_self_check,
        "finalize": root_finalize,
    }
    sys.stdout.buffer.write(compact(handlers[phase](values)) + b"\n")


def static_report() -> dict[str, Any]:
    helper = read_regular(HELPER)[0]
    plan = read_regular(PLAN)[0]
    status = read_regular(STATUS)[0]
    before = nonsecret_snapshot()
    derived = derive_all(plan, status, helper)
    documents = validate_documents(plan, status, helper)
    evidence = validate_nonsecret_evidence()
    driver_validation = validate_driver(exact_file(V7_DRIVER, EXPECTED_V7_DRIVER, 0o600), derived["driver"])
    contract_validation = static_contract_validation(derived["contract"])
    schema_validation = validate_root_schema(plan, status, helper, derived)
    helper_ruff = ruff_validation(helper, "m3a_v8_source_freeze.py")
    driver_ruff = ruff_validation(derived["driver"], "handoff-driver.py")
    commands = root_commands(plan, status, helper, derived)
    final_index = pretty(final_index_value(plan, status, helper, derived))
    handoff = handoff_command(plan, status, derived, final_index)
    after = nonsecret_snapshot()
    require(before == after, "static validation changed protected state")
    return {
        "acceptance": {
            "bytes": len(derived["acceptance_payload"]),
            "sha256": sha(derived["acceptance_payload"]),
        },
        "commands": commands,
        "contract": {"bytes": len(derived["contract"]), "sha256": sha(derived["contract"])},
        "contract_validation": contract_validation,
        "documents": documents,
        "driver": {"bytes": len(derived["driver"]), "sha256": sha(derived["driver"])},
        "driver_validation": driver_validation,
        "evidence": evidence,
        "final_index": {"bytes": len(final_index), "sha256": sha(final_index)},
        "gate_count": 35,
        "handoff": handoff,
        "helper": {"bytes": len(helper), "sha256": sha(helper)},
        "no_write_snapshot": before,
        "result": "PASS",
        "root_schema": schema_validation,
        "ruff": {"driver": driver_ruff, "helper": helper_ruff},
        "self_check": {
            "bytes": len(self_check_payload(plan, status, helper, derived)),
            "sha256": sha(self_check_payload(plan, status, helper, derived)),
        },
        "source_receipt": {
            "bytes": len(source_receipt_payload(helper, derived)),
            "sha256": sha(source_receipt_payload(helper, derived)),
        },
        "writer": {"bytes": len(derived["writer"]), "sha256": sha(derived["writer"])},
        "writer_self_test": {
            "bytes": len(writer_test_payload()),
            "sha256": sha(writer_test_payload()),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-writer", action="store_true")
    parser.add_argument("--static-json", action="store_true")
    args = parser.parse_args()
    helper = read_regular(HELPER)[0]
    if args.emit_writer:
        sys.stdout.buffer.write(writer_source(helper))
        return 0
    require(args.static_json, "static mode required")
    sys.stdout.buffer.write(compact(static_report()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
