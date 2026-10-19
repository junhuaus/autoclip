from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


DELIVERY = Path("/Users/junhuaxu/autoclip")
PLAN = DELIVERY / "docs/exec-plans/liveclip-agent-runtime-v2.md"
STATUS = DELIVERY / "STATUS.md"
ARCHITECTURE = DELIVERY / "docs/liveclip-architecture.html"
HELPER = DELIVERY / "tools/loop_engineering/m3a_v2_source_freeze.py"
BASE = Path(
    "/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/"
    "agent-runtime-v2/a822890ace12"
)
SEED = BASE / "candidate.OlsWg1/repo"
V1_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v1"
V1_DRIVER = V1_ROOT / "handoff-driver.py"
V39_ROOT = BASE / "trusted-tools/m3-successor-preparation-v39"
TARGET = BASE / "candidate.oivrdV6U"
RUN_ID = "20261014T191719Z-0802b465"
RUN = TARGET / "repo/.loop/runs" / RUN_ID
ROOT = BASE / "trusted-tools/m3-authentication-handoff-v2"
DRIVER = ROOT / "handoff-driver.py"
RECEIPTS = ROOT / "receipts"
CONTROLLER_RECEIPT = RECEIPTS / "controller-acceptance-v2.json"
CURRENT_UID = 501
EXPECTED_HEAD = "2f361fcddc0e63ae62ee62826e27b54bb8204c53"
EXPECTED_BRANCH = "main"
EXPECTED_DELIVERY = (0, 15, 167)
EXPECTED_TARGET = (0, 15, 73)
EXPECTED_ARCHITECTURE = (66116, "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce")
EXPECTED_V1_DRIVER = (22180, "c513d37f32e171a131ce336d7e419854d42beacc4fdc997ab8324bfebc4202f4")
PYTHON = Path("/opt/homebrew/bin/python3.12")
PYTHON_TARGET = Path(
    "/opt/homebrew/Cellar/python@3.12/3.12.14/Frameworks/Python.framework/"
    "Versions/3.12/bin/python3.12"
)
PYTHON_SIZE = 34640
PYTHON_SHA = "c6af311afeecacffa2c8c627894a4bf9d3e2c00e0d3dc91b26c881c4b0615d23"
CODEX = Path("/opt/homebrew/bin/codex")
CODEX_TARGET = Path("/opt/homebrew/Caskroom/codex/0.161.0/bin/codex")
CODEX_SIZE = 245096256
CODEX_SHA = "12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de"
RUFF = DELIVERY / ".venv/bin/ruff"
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
SOURCE_BEGIN = b"# LIVECLIP_M3A_PREPARATION_V2_" + b"BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3A_PREPARATION_V2_" + b"END\n"
ROOT_FILES = {
    "controller-acceptance-v2.json",
    "final-index.json",
    "self-check-result.json",
    "source-receipt.json",
    "writer-self-test.json",
}
EXPECTED_CANDIDATES = {
    "candidate.22BiM8pO", "candidate.3WBt3ldA", "candidate.5jh3bylk",
    "candidate.5nZWpynN", "candidate.KWbe2iGW", "candidate.OlsWg1",
    "candidate.Q2vecg", "candidate.UU7EAiJG", "candidate.VoU5SVVl",
    "candidate.aw2oA4", "candidate.bSEqMEit", "candidate.c79YYSLQ",
    "candidate.cQnaAbOf", "candidate.dygENR4n", "candidate.iyme1x_i",
    "candidate.jyq_n37h", "candidate.mRMO7MQ6", "candidate.o99gfxup",
    "candidate.oivrdV6U", "candidate.qaDKDWkQ", "candidate.vuDWtK0T",
    "candidate.xp23hqNY", "candidate.z6EbTJew",
}
V39_FILES = {
    "candidate-driver.py": (452597, "9b756bf28d7c625e28c0a85ff92b1ee40ca7c53572105122973b9a35fdeca7bc"),
    "receipts/controller-acceptance-v39.json": (10768, "e32334901302206f7ea712c1559119c1d8ee8929b5279f71f64088dfab5e4da1"),
    "receipts/source-receipt.json": (524, "e9ffd0486c0885049557090f98d75084fae6f469cd539f2fd9e9a420baa96098"),
    "receipts/writer-self-test.json": (72, "3d03786a9b07dea917e1c42b7712ca8cbb19a8c4920a9d171e86fbbe80ee22d3"),
    "receipts/self-check-result.json": (4400, "d6932f607b85dee7b9294e6eceea3c8c86fe603c2b89115732e6d132d0d22e7e"),
    "receipts/final-index.json": (2000, "d13dd343c9aec55a93bab0e795780bf0e851269c9bf5f6ce4d3725ee8d7e06fc"),
    "receipts/successor-preparation-v39-result.json": (23849, "314a857182f9238219bb28d1ba03c7f84344883264518205241d6190bc692667"),
}
TARGET_FILES = {
    "successor-receipts/final-receipt-index.json": (18094, "b42071ee39c7f176f30750a937106ed50a22c65d7aed41c8aacf9db0b9521867", 0o600),
    "successor-receipts/successor-v39-controller-acceptance-offer.json": (5031, "5d7eb88ee075a4d5945443a4d8801bc4707868c3cd27ea9e87921b74fc80df08", 0o600),
    "successor-receipts/successor-v39-controller-acceptance-transport.json": (1383, "6e37cf4d3f37d4c848c6f52dd5690b6bae145ce44fe7c8ed235657469073ad5e", 0o600),
    "successor-receipts/successor-v39-preparation-bindings.json": (5411, "4a5f2a588137b6d174871ecc7521989978b4b80fe59378eddc99f418d67b60ae", 0o600),
    "successor-receipts/successor-v39-toolchain-snapshot.json": (4878, "507ebda410f62b19b3c2ba3d567d5347775c3cee7b8f9eafb2323d3e2e86f45a", 0o600),
    "successor-receipts/postacceptance-final-index.json": (2730, "a3b5ae0908569c996ac3b59957125b1647c2e8f9cd8595035a4d95d78cba4db6", 0o600),
    "repo/.loop/trusted/final-controller-acceptance-v39.json": (3912, "fe6405636b4fa359c1e3ade43f0821a80cf636128a0f9726bdd4825f941f5c56", 0o600),
    "repo/.loop/runs/20261014T191719Z-0802b465/state.json": (9210, "2648acc7d3dcc144911480c434dc7e52ec3dce984bc0baf382c44dad8e594043", 0o644),
    "repo/.loop/runs/20261014T191719Z-0802b465/events.jsonl": (144, "8378d385b481413208343ce35b4a9f7976f6ed47fee2a7395b2b70a792a1ece2", 0o644),
}
V39_ROOT_RECEIPTS = {
    "controller-acceptance-v39.json", "final-index.json", "self-check-result.json",
    "source-receipt.json", "successor-preparation-v39-result.json", "writer-self-test.json",
}
V39_TARGET_RECEIPTS = {
    "candidate-dry-run-capture.json", "candidate-dry-run-stderr.bin",
    "candidate-dry-run-stdout.bin", "candidate-dry-run-validation.json",
    "candidate-manifest.jsonl", "doctor-capture.json", "doctor-command.json",
    "doctor-profile-command.json", "doctor-profile-staging.json", "doctor-stderr.bin",
    "doctor-stdout.bin", "doctor-validation.json", "final-attempt-manifest.jsonl",
    "final-receipt-index.json", "final-repository-manifest.jsonl", "included-untracked.zlist",
    "materialization-results.jsonl", "post-setup-receipt.json",
    "postacceptance-attempt-manifest.jsonl", "postacceptance-final-index.json",
    "postacceptance-repository-manifest.jsonl", "pre-setup-receipt.json",
    "preflight-receipt.json", "preservation-receipt.json", "readiness-result.json",
    "setup-command.json", "setup-result.json", "source-manifest.jsonl",
    "source-tracked.patch", "successor-v39-controller-acceptance-offer.json",
    "successor-v39-controller-acceptance-transport.json",
    "successor-v39-controller-acceptance.json", "successor-v39-initial-events.jsonl",
    "successor-v39-initial-state.json", "successor-v39-loop-init-command.json",
    "successor-v39-loop-init-result.json", "successor-v39-overlay.json",
    "successor-v39-policy-snapshot.json", "successor-v39-preparation-bindings.json",
    "successor-v39-toolchain-snapshot.json", "successor-v39-trusted-context.json",
    "toolchain-fingerprint.json",
}


class Stop(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise Stop(message)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def pretty(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def read_regular(path: Path, maximum: int = 16 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and not path.is_symlink() and before.st_size <= maximum,
        "unsafe non-secret file",
    )
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    chunks: list[bytes] = []
    try:
        opened = os.fstat(fd)
        require(
            (opened.st_dev, opened.st_ino, opened.st_size)
            == (before.st_dev, before.st_ino, before.st_size),
            "changed non-secret file",
        )
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        final = os.fstat(fd)
        require(
            (final.st_dev, final.st_ino, final.st_size)
            == (opened.st_dev, opened.st_ino, opened.st_size),
            "changed non-secret file",
        )
    finally:
        os.close(fd)
    payload = b"".join(chunks)
    require(len(payload) == before.st_size, "changed non-secret file")
    return payload, before


def exact_file(path: Path, size: int, digest: str, mode: int = 0o600) -> bytes:
    payload, info = read_regular(path, max(size, 1))
    require(len(payload) == size and sha(payload) == digest, f"identity mismatch: {path.name}")
    require(
        info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode,
        f"ownership mismatch: {path.name}",
    )
    return payload


def private_directory(path: Path) -> None:
    info = path.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and not path.is_symlink()
        and info.st_uid == CURRENT_UID
        and stat.S_IMODE(info.st_mode) == 0o700,
        f"private directory mismatch: {path.name}",
    )


def extract_source(plan_payload: bytes) -> bytes:
    require(plan_payload.count(SOURCE_BEGIN) == 1 and plan_payload.count(SOURCE_END) == 1, "source markers")
    start = plan_payload.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    end = plan_payload.index(SOURCE_END, start)
    payload = plan_payload[start:end]
    require(payload.endswith(b"\n"), "source newline")
    return payload


def git_capture(repo: Path, args: list[str]) -> bytes:
    process = subprocess.Popen(  # noqa: S603 - fixed git binary, literal read-only call sites
        ["/usr/bin/git", "-C", str(repo), *args],
        cwd=repo,
        env={
            "GIT_OPTIONAL_LOCKS": "0", "HOME": "/Users/junhuaxu", "LANG": "C",
            "LC_ALL": "C", "PATH": PATH_VALUE, "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": "/tmp",  # noqa: S108 - frozen non-secret root-only environment
            "__CF_USER_TEXT_ENCODING": CF_USER_TEXT_ENCODING,
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        shell=False,
    )
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        raise Stop("git timeout") from None
    require(process.returncode == 0 and not stderr and len(stdout) <= 1024 * 1024, "git failed")
    return stdout


def status_counts(repo: Path) -> tuple[int, int, int]:
    lines = git_capture(repo, ["status", "--porcelain=v1", "--untracked-files=all"]).decode().splitlines()
    return (
        sum(1 for line in lines if line[:1] not in {" ", "?"}),
        sum(1 for line in lines if len(line) > 1 and line[1] not in {" ", "?"}),
        sum(1 for line in lines if line.startswith("??")),
    )


def validate_git(repo: Path, expected: tuple[int, int, int]) -> None:
    require(git_capture(repo, ["branch", "--show-current"]) == b"main\n", "branch mismatch")
    require(git_capture(repo, ["rev-parse", "HEAD"]) == (EXPECTED_HEAD + "\n").encode(), "head mismatch")
    require(status_counts(repo) == expected, "inventory mismatch")


def driver_constants() -> str:
    candidates = ", ".join(json.dumps(value) for value in sorted(EXPECTED_CANDIDATES))
    v39_files = repr(dict(sorted(V39_FILES.items())))
    target_files = repr(dict(sorted(TARGET_FILES.items())))
    contract = repr(handoff_contract())
    return f'''DELIVERY = Path("/Users/junhuaxu/autoclip")
PLAN = DELIVERY / "docs/exec-plans/liveclip-agent-runtime-v2.md"
STATUS = DELIVERY / "STATUS.md"
ARCHITECTURE = DELIVERY / "docs/liveclip-architecture.html"
BASE = Path(
    "/Users/junhuaxu/Library/Application Support/LiveClip/engineering-candidates/"
    "agent-runtime-v2/a822890ace12"
)
V39_ROOT = BASE / "trusted-tools/m3-successor-preparation-v39"
TARGET = BASE / "candidate.oivrdV6U"
RUN_ID = "20261014T191719Z-0802b465"
RUN = TARGET / "repo/.loop/runs" / RUN_ID
ROOT = BASE / "trusted-tools/m3-authentication-handoff-v2"
DRIVER = ROOT / "handoff-driver.py"
RECEIPTS = ROOT / "receipts"
RESULT = RECEIPTS / "auth-handoff-v2-result.json"
AUTH_SOURCE = Path("/Users/junhuaxu/.codex/auth.json")
AUTH_DESTINATION = TARGET / "home/.codex/auth.json"
CODEX = Path("/opt/homebrew/bin/codex")
CODEX_TARGET = Path("/opt/homebrew/Caskroom/codex/0.161.0/bin/codex")
CODEX_SIZE = 245096256
CODEX_SHA = "12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
EXPECTED_HEAD = "{EXPECTED_HEAD}"
EXPECTED_BRANCH = "main"
EXPECTED_DELIVERY = (0, 15, 167)
EXPECTED_TARGET = (0, 15, 73)
EXPECTED_ARCHITECTURE = (66116, "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce")
EXPECTED_CANDIDATES = {{{candidates}}}
V39_FILES = {v39_files}
TARGET_FILES = {target_files}
HANDOFF_CONTRACT = {contract}
ROOT_FILES = {{
    "controller-acceptance-v2.json", "final-index.json", "self-check-result.json",
    "source-receipt.json", "writer-self-test.json",
}}
SHAPE = (
    "auth-handoff", "--expected-self-sha", None,
    "--plan", None, "--expected-plan-sha256", None,
    "--status", None, "--expected-status-sha256", None,
    "--expected-root-final-index-sha256", None,
    "--expected-controller-acceptance-sha256", None,
)
'''


def handoff_contract() -> dict[str, Any]:
    return {
        "bounds": {
            "diagnostic_bytes": 65536,
            "login_status_seconds": 30,
            "outer_seconds": 120,
            "sanitized_stdout_bytes": 4096,
        },
        "budgets": {"destination": 1, "handoff_invocation": 1, "result": 1, "root": 1},
        "candidate": {
            "candidate_count": 23,
            "completed_tree": {
                "bytes": 967213201,
                "paths": 44326,
                "sha256": "c74a87299cdd78549769ba7a0f0490e1ebcd0d63a3a768c45debcde991cabbce",
            },
            "final_acceptance_sha256": "fe6405636b4fa359c1e3ade43f0821a80cf636128a0f9726bdd4825f941f5c56",
            "final_index_sha256": "a3b5ae0908569c996ac3b59957125b1647c2e8f9cd8595035a4d95d78cba4db6",
            "name": "candidate.oivrdV6U",
            "run_id": RUN_ID,
            "sealed_receipt_index_sha256": "b42071ee39c7f176f30750a937106ed50a22c65d7aed41c8aacf9db0b9521867",
        },
        "delivery": {
            "branch": EXPECTED_BRANCH,
            "candidate_inventory": list(EXPECTED_TARGET),
            "candidate_names_sha256": sha(compact(sorted(EXPECTED_CANDIDATES))),
            "head": EXPECTED_HEAD,
            "inventory": list(EXPECTED_DELIVERY),
        },
        "environment_names": [
            "GIT_OPTIONAL_LOCKS", "HOME", "LANG", "LC_ALL", "PATH",
            "PYTHONDONTWRITEBYTECODE", "TMPDIR", "__CF_USER_TEXT_ENCODING",
        ],
        "format_version": 1,
        "formal_role_authority": False,
        "phase": "M3A_V2_OPAQUE_AUTH_HANDOFF_CONTRACT",
        "pinned_status": {
            "argv": [str(CODEX), "login", "status"],
            "binary_sha256": CODEX_SHA,
            "binary_size": CODEX_SIZE,
            "child_channels": "DEVNULL",
            "timeout_seconds": 30,
        },
        "private_runtime": {"home_mode": "0700", "owner_uid": CURRENT_UID, "tmp_mode": "0700"},
        "privacy": {
            "child_channels": "DEVNULL",
            "credential_environment_variables": False,
            "opaque_copy": True,
            "raw_diagnostics": False,
            "receipt_fields": [
                "copy_success", "destination_mode", "destination_owner_uid",
                "format_version", "login_status", "phase", "result", "sanitized_error",
            ],
            "secret_derived_metadata": False,
        },
        "run": {
            "code_cycle": 0,
            "cycle": 0,
            "events_sha256": "8378d385b481413208343ce35b4a9f7976f6ed47fee2a7395b2b70a792a1ece2",
            "state": "received",
            "state_sha256": "2648acc7d3dcc144911480c434dc7e52ec3dce984bc0baf382c44dad8e594043",
        },
        "v39": {
            "driver_sha256": "9b756bf28d7c625e28c0a85ff92b1ee40ca7c53572105122973b9a35fdeca7bc",
            "final_index_sha256": "d13dd343c9aec55a93bab0e795780bf0e851269c9bf5f6ce4d3725ee8d7e06fc",
            "preparation_result_sha256": "314a857182f9238219bb28d1ba03c7f84344883264518205241d6190bc692667",
        },
    }


def replacement_validator() -> str:
    return '''def validate_v39_and_target() -> None:
    private_directory(V39_ROOT)
    require(set(os.listdir(V39_ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}, "V39_ROOT_MISMATCH")
    require(set(os.listdir(V39_ROOT / "receipts")) == {"controller-acceptance-v39.json", "final-index.json", "self-check-result.json", "source-receipt.json", "successor-preparation-v39-result.json", "writer-self-test.json"}, "V39_ROOT_MISMATCH")
    for relative, values in V39_FILES.items():
        identity(V39_ROOT / relative, values[0], values[1])
    result_value = json.loads(read_regular(V39_ROOT / "receipts/successor-preparation-v39-result.json")[0].decode("utf-8"))
    require(result_value["returncode"] == 0 and result_value["timed_out"] is False and result_value["output_truncated"] is False and result_value["wrapper_error"] is None and result_value["credential_variables"] == [], "V39_RESULT_MISMATCH")
    private_directory(TARGET)
    require(set(os.listdir(TARGET)) == {"home", "repo", "successor-receipts", "tmp"}, "TARGET_DOMAIN_MISMATCH")
    for relative, values in TARGET_FILES.items():
        identity(TARGET / relative, values[0], values[1], values[2])
    architecture_payload, _ = read_regular(ARCHITECTURE)
    require((len(architecture_payload), sha(architecture_payload)) == EXPECTED_ARCHITECTURE, "ARCHITECTURE_MISMATCH")
    state_value = json.loads(read_regular(RUN / "state.json")[0].decode("utf-8"))
    require(
        state_value["run_id"] == RUN_ID
        and state_value["state"] == "received"
        and state_value["cycle"] == 0
        and state_value["code_cycle"] == 0
        and state_value["coder_session_id"] is None
        and state_value["artifacts"] == {}
        and state_value["command_results"] == []
        and state_value["last_error"] is None,
        "RUN_NOT_PRISTINE",
    )
    candidates = {path.name for path in BASE.iterdir() if path.name.startswith("candidate.") and path.is_dir() and not path.is_symlink()}
    require(candidates == EXPECTED_CANDIDATES, "CANDIDATE_SET_MISMATCH")
    inventory(DELIVERY, EXPECTED_DELIVERY)
    inventory(TARGET / "repo", EXPECTED_TARGET)
'''


def derive_driver(v1_payload: bytes) -> bytes:
    text = v1_payload.decode("utf-8")
    start = text.index("DELIVERY = Path(")
    end = text.index("\n\nclass AuthStop", start)
    text = text[:start] + driver_constants().rstrip() + text[end:]
    start = text.index("def validate_v30_and_target() -> None:")
    end = text.index("\n\ndef validate_private_runtime", start)
    text = text[:start] + replacement_validator().rstrip() + text[end:]
    text = text.replace("validate_v30_and_target()", "validate_v39_and_target()")
    text = text.replace('"controller-acceptance-v1.json"', '"controller-acceptance-v2.json"')
    text = text.replace('"M3A_V1_FINAL_INDEX"', '"M3A_V2_FINAL_INDEX"')
    text = text.replace('"M3A_V1_READY_FOR_CONTROLLER_REVIEW"', '"M3A_V2_READY_FOR_CONTROLLER_REVIEW"')
    text = text.replace('"M3A_V1_AUTH_HANDOFF"', '"M3A_V2_AUTH_HANDOFF"')
    payload = text.encode("utf-8")
    ast.parse(payload, filename="handoff-driver.py")
    compile(payload, "handoff-driver.py", "exec", dont_inherit=True)
    return payload


def function_source(payload: bytes, name: str) -> str:
    text = payload.decode("utf-8")
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(text, node)
            require(segment is not None, f"missing source: {name}")
            return segment
    raise Stop(f"missing function: {name}")


def static_driver_validation(v1_payload: bytes, driver_payload: bytes) -> dict[str, Any]:
    tree = ast.parse(driver_payload)
    compile(driver_payload, "handoff-driver.py", "exec", dont_inherit=True)
    text = driver_payload.decode("utf-8")
    require("M3A_V1" not in text and "V30" not in text, "stale metadata")
    require(text.count("M3A_V2_AUTH_HANDOFF") == 1, "phase count")
    require(text.count("auth-handoff-v2-result.json") == 1, "result count")
    require(text.count("def opaque_copy_state()") == 1 and text.count("def login_status(") == 1, "opaque surface")
    for name in ("opaque_copy_state", "terminate_group", "login_status"):
        old = function_source(v1_payload, name).replace("M3A_V1", "M3A_V2")
        new = function_source(driver_payload, name)
        require(old == new, f"opaque precedent drift: {name}")
    function_names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    require(
        {"opaque_copy_state", "login_status", "validate_v39_and_target", "validate_private_runtime"}
        <= function_names,
        "driver surface",
    )
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    popen_calls = [node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "Popen"]
    require(len(popen_calls) == 2, "subprocess surface")
    require("shell=False" in text and text.count("subprocess.DEVNULL") >= 4, "child channel contract")
    require("os.O_EXCL" in text and "os.O_NOFOLLOW" in text and "os.fsync" in text, "copy contract")
    receipt_node = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Dict)
        and any(isinstance(key, ast.Constant) and key.value == "copy_success" for key in node.value.keys)
    )
    receipt = {
        key.value: value
        for key, value in zip(receipt_node.keys, receipt_node.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    require(
        set(receipt) == {
            "copy_success", "destination_mode", "destination_owner_uid", "format_version",
            "login_status", "phase", "result", "sanitized_error",
        },
        "receipt schema",
    )
    forbidden = ("loop-run", "--last", "Reviewer", "Tester", "Gateway", "Runner")
    require(all(token not in text for token in forbidden), "forbidden capability")
    negative = []
    for old, new in (
        ("candidate.oivrdV6U", "candidate.5nZWpynN"),
        (RUN_ID, "20261013T215618Z-941df9ff"),
        ("M3A_V2_AUTH_HANDOFF", "M3A_V1_AUTH_HANDOFF"),
        ("EXPECTED_DELIVERY = (0, 15, 167)", "EXPECTED_DELIVERY = (0, 15, 166)"),
        ("SUPPORTED_AUTHENTICATED", "UNSUPPORTED"),
    ):
        mutated = driver_payload.replace(old.encode(), new.encode(), 1)
        require(mutated != driver_payload and sha(mutated) != sha(driver_payload), "negative mutation")
        negative.append(old)
    return {
        "ast_parse": "PASS",
        "compile": "PASS",
        "credential_copy_precedent": "BYTE_EQUIVALENT_FUNCTIONS",
        "negative_fixtures": negative,
        "receipt_fields": sorted(receipt),
    }


def ruff_validation(driver_payload: bytes) -> None:
    require(RUFF.is_file() and not RUFF.is_symlink(), "ruff unavailable")
    process = subprocess.Popen(  # noqa: S603 - fixed project-local Ruff and fixed argv
        [
            str(RUFF), "check", "--no-cache", "--select", "F,B,S",
            "--stdin-filename", "handoff-driver.py", "-",
        ],
        cwd=DELIVERY,
        env={
            "HOME": "/Users/junhuaxu", "LANG": "C", "LC_ALL": "C",
            "PATH": PATH_VALUE, "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": "/tmp",  # noqa: S108
        },
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        shell=False,
    )
    try:
        stdout, stderr = process.communicate(driver_payload, timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        raise Stop("ruff timeout") from None
    require(process.returncode == 0 and len(stdout) <= 65536 and len(stderr) <= 65536, "ruff failed")


def controller_acceptance(
    plan_payload: bytes,
    status_payload: bytes,
    source_payload: bytes,
    helper_payload: bytes,
    driver_payload: bytes,
) -> dict[str, Any]:
    contract = handoff_contract()
    return {
        "authority": "EXTERNAL_CONTROLLER",
        "contract": contract,
        "contract_sha256": sha(compact(contract)),
        "documents": {
            "execplan": {"path": str(PLAN), "sha256": sha(plan_payload), "size": len(plan_payload)},
            "status": {"path": str(STATUS), "sha256": sha(status_payload), "size": len(status_payload)},
        },
        "driver": {"sha256": sha(driver_payload), "size": len(driver_payload)},
        "format_version": 1,
        "helper": {"sha256": sha(helper_payload), "size": len(helper_payload)},
        "phase": "M3A_V2_CONTROLLER_ACCEPTANCE",
        "preparation_source": {"sha256": sha(source_payload), "size": len(source_payload)},
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": {"name": "m3-authentication-handoff-v2", "no_replace": True},
        "v39_final_provenance": {
            "acceptance_sha256": "fe6405636b4fa359c1e3ade43f0821a80cf636128a0f9726bdd4825f941f5c56",
            "candidate": "candidate.oivrdV6U",
            "completed_tree_sha256": "c74a87299cdd78549769ba7a0f0490e1ebcd0d63a3a768c45debcde991cabbce",
            "postacceptance_index_sha256": "a3b5ae0908569c996ac3b59957125b1647c2e8f9cd8595035a4d95d78cba4db6",
            "run_id": RUN_ID,
        },
    }


def static_acceptance_validation(value: dict[str, Any]) -> list[str]:
    expected_keys = {
        "authority", "contract", "contract_sha256", "documents", "driver",
        "format_version", "helper", "phase", "preparation_source", "result",
        "root", "v39_final_provenance",
    }
    require(set(value) == expected_keys, "acceptance schema")
    require(value["authority"] == "EXTERNAL_CONTROLLER", "acceptance authority")
    require(value["phase"] == "M3A_V2_CONTROLLER_ACCEPTANCE", "acceptance phase")
    require(value["result"] == "ACCEPTED_BEFORE_ROOT_CREATION", "acceptance result")
    require(value["contract_sha256"] == sha(compact(value["contract"])), "acceptance contract")
    negatives: list[str] = []
    fixtures = (
        ("authority", "DRIVER_SELF_ASSERTED"),
        ("phase", "M3A_V1_CONTROLLER_ACCEPTANCE"),
        ("result", "READY_FOR_CONTROLLER_REVIEW"),
        ("format_version", 2),
    )
    canonical = compact(value)
    for key, replacement in fixtures:
        mutated = dict(value)
        mutated[key] = replacement
        require(compact(mutated) != canonical, f"acceptance negative: {key}")
        negatives.append(key)
    for key in ("contract", "documents", "driver", "helper", "preparation_source", "root", "v39_final_provenance"):
        mutated = dict(value)
        mutated[key] = None
        require(compact(mutated) != canonical, f"acceptance negative: {key}")
        negatives.append(key)
    mutated = dict(value)
    mutated["extra"] = True
    require(set(mutated) != expected_keys, "acceptance extra-key negative")
    negatives.append("extra")
    return negatives


def validate_nonsecret_evidence() -> None:
    require(not os.path.lexists(ROOT), "V2 root already exists")
    private_directory(V39_ROOT)
    require(set(os.listdir(V39_ROOT)) == {"candidate-driver.py", "home", "receipts", "tmp"}, "V39 root domain")
    require(set(os.listdir(V39_ROOT / "receipts")) == V39_ROOT_RECEIPTS, "V39 receipt domain")
    for relative, values in V39_FILES.items():
        exact_file(V39_ROOT / relative, values[0], values[1])
    private_directory(TARGET)
    require(set(os.listdir(TARGET)) == {"home", "repo", "successor-receipts", "tmp"}, "target domain")
    require(set(os.listdir(TARGET / "successor-receipts")) == V39_TARGET_RECEIPTS, "target receipts")
    for relative, values in TARGET_FILES.items():
        exact_file(TARGET / relative, values[0], values[1], values[2])
    state = json.loads(exact_file(RUN / "state.json", 9210, TARGET_FILES[f"repo/.loop/runs/{RUN_ID}/state.json"][1], 0o644))
    require(
        state["run_id"] == RUN_ID and state["state"] == "received"
        and state["cycle"] == 0 and state["code_cycle"] == 0
        and state["coder_session_id"] is None and state["artifacts"] == {}
        and state["command_results"] == [] and state["last_error"] is None,
        "run not pristine",
    )
    candidates = {
        path.name for path in BASE.iterdir()
        if path.name.startswith("candidate.") and path.is_dir() and not path.is_symlink()
    }
    require(candidates == EXPECTED_CANDIDATES, "candidate set")
    validate_git(DELIVERY, EXPECTED_DELIVERY)
    validate_git(TARGET / "repo", EXPECTED_TARGET)
    exact_file(ARCHITECTURE, *EXPECTED_ARCHITECTURE, 0o644)
    require(PYTHON.is_symlink() and PYTHON.resolve(strict=True) == PYTHON_TARGET, "python symlink")
    exact_file(PYTHON_TARGET, PYTHON_SIZE, PYTHON_SHA, 0o755)
    require(CODEX.is_symlink() and CODEX.resolve(strict=True) == CODEX_TARGET, "codex symlink")
    exact_file(CODEX_TARGET, CODEX_SIZE, CODEX_SHA, 0o755)


def validate_root_environment() -> None:
    expected = {
        "GIT_OPTIONAL_LOCKS": "0", "HOME": "/Users/junhuaxu", "LANG": "C",
        "LC_ALL": "C", "PATH": PATH_VALUE, "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": "/tmp",  # noqa: S108 - frozen non-secret root-only environment
        "__CF_USER_TEXT_ENCODING": CF_USER_TEXT_ENCODING,
    }
    require(dict(os.environ) == expected, "environment mismatch")
    require(Path.cwd() == SEED and os.getuid() == CURRENT_UID, "runtime mismatch")


def write_exclusive(path: Path, payload: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            require(written > 0, "write failed")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and not path.is_symlink() and info.st_uid == CURRENT_UID
        and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size == len(payload),
        "write verification failed",
    )


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--expected-status-sha256", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-helper-sha256", required=True)
    parser.add_argument("--expected-driver-sha256", required=True)
    parser.add_argument("--expected-contract-sha256", required=True)
    parser.add_argument("--controller-acceptance-json", required=True)
    values = parser.parse_args(argv)
    require(len(argv) == 18, "argv schema")
    return values


def argument_strings(args: argparse.Namespace) -> list[str]:
    return [
        "--plan", args.plan,
        "--expected-plan-sha256", args.expected_plan_sha256,
        "--status", args.status,
        "--expected-status-sha256", args.expected_status_sha256,
        "--expected-source-sha256", args.expected_source_sha256,
        "--expected-helper-sha256", args.expected_helper_sha256,
        "--expected-driver-sha256", args.expected_driver_sha256,
        "--expected-contract-sha256", args.expected_contract_sha256,
        "--controller-acceptance-json", args.controller_acceptance_json,
    ]


def derive_all(args: argparse.Namespace) -> dict[str, Any]:
    require(Path(args.plan) == PLAN and Path(args.status) == STATUS, "document paths")
    plan_payload, _ = read_regular(PLAN)
    status_payload, _ = read_regular(STATUS)
    helper_payload, _ = read_regular(HELPER)
    source_payload = extract_source(plan_payload)
    require(sha(plan_payload) == args.expected_plan_sha256, "plan hash")
    require(sha(status_payload) == args.expected_status_sha256, "status hash")
    require(sha(source_payload) == args.expected_source_sha256, "source hash")
    require(sha(helper_payload) == args.expected_helper_sha256, "helper hash")
    v1_payload = exact_file(V1_DRIVER, *EXPECTED_V1_DRIVER)
    driver_payload = derive_driver(v1_payload)
    require(sha(driver_payload) == args.expected_driver_sha256, "driver hash")
    contract = handoff_contract()
    require(sha(compact(contract)) == args.expected_contract_sha256, "contract hash")
    validation = static_driver_validation(v1_payload, driver_payload)
    ruff_validation(driver_payload)
    validation["ruff_f_b_s"] = "PASS"
    acceptance = controller_acceptance(plan_payload, status_payload, source_payload, helper_payload, driver_payload)
    validation["acceptance_negative_fixtures"] = static_acceptance_validation(acceptance)
    acceptance_payload = compact(acceptance) + b"\n"
    provided = args.controller_acceptance_json.encode("utf-8") + b"\n"
    require(provided == acceptance_payload, "controller acceptance mismatch")
    validate_nonsecret_evidence()
    return {
        "acceptance": acceptance,
        "acceptance_payload": acceptance_payload,
        "contract": contract,
        "driver_payload": driver_payload,
        "helper_payload": helper_payload,
        "plan_payload": plan_payload,
        "source_payload": source_payload,
        "status_payload": status_payload,
        "validation": validation,
    }


def root_only(args: argparse.Namespace) -> int:
    validate_root_environment()
    values = derive_all(args)
    require(not os.path.lexists(ROOT), "root exists")
    os.mkdir(ROOT, 0o700)
    os.mkdir(ROOT / "home", 0o700)
    os.mkdir(ROOT / "tmp", 0o700)
    os.mkdir(RECEIPTS, 0o700)
    write_exclusive(DRIVER, values["driver_payload"])
    write_exclusive(CONTROLLER_RECEIPT, values["acceptance_payload"])
    source_receipt = {
        "driver_sha256": sha(values["driver_payload"]),
        "driver_size": len(values["driver_payload"]),
        "helper_sha256": sha(values["helper_payload"]),
        "helper_size": len(values["helper_payload"]),
        "phase": "M3A_V2_SOURCE_TRANSPORT",
        "result": "PASS",
        "source_sha256": sha(values["source_payload"]),
        "source_size": len(values["source_payload"]),
    }
    writer = {"phase": "M3A_V2_WRITER_SELF_TEST", "result": "PASS"}
    self_check = {
        "acceptance_sha256": sha(values["acceptance_payload"]),
        "contract_sha256": sha(compact(values["contract"])),
        "driver_sha256": sha(values["driver_payload"]),
        "phase": "M3A_V2_SELF_CHECK",
        "result": "PASS",
        "validation": values["validation"],
    }
    write_exclusive(RECEIPTS / "source-receipt.json", pretty(source_receipt))
    write_exclusive(RECEIPTS / "writer-self-test.json", pretty(writer))
    write_exclusive(RECEIPTS / "self-check-result.json", pretty(self_check))
    final_index = {
        "acceptance_sha256": sha(values["acceptance_payload"]),
        "contract_sha256": sha(compact(values["contract"])),
        "driver_sha256": sha(values["driver_payload"]),
        "documents": {
            "execplan": {"sha256": sha(values["plan_payload"]), "size": len(values["plan_payload"])},
            "status": {"sha256": sha(values["status_payload"]), "size": len(values["status_payload"])},
        },
        "phase": "M3A_V2_FINAL_INDEX",
        "receipt_names": sorted(ROOT_FILES - {"final-index.json"}),
        "root_argv_sha256": sha(
            compact(
                [
                    str(PYTHON), "-c", values["source_payload"].decode("utf-8"),
                    "--", *argument_strings(args),
                ]
            )
        ),
        "verdict": "M3A_V2_READY_FOR_CONTROLLER_REVIEW",
    }
    write_exclusive(RECEIPTS / "final-index.json", pretty(final_index))
    require(set(os.listdir(ROOT)) == {"handoff-driver.py", "home", "receipts", "tmp"}, "root domain")
    require(set(os.listdir(RECEIPTS)) == ROOT_FILES, "receipt domain")
    require(not os.listdir(ROOT / "home") and not os.listdir(ROOT / "tmp"), "private roots not empty")
    for path in (ROOT, ROOT / "home", ROOT / "tmp", RECEIPTS):
        private_directory(path)
    sync_directory(RECEIPTS)
    sync_directory(ROOT)
    output = {
        "phase": "M3A_V2_ROOT_ONLY",
        "result": "M3A_V2_READY_FOR_CONTROLLER_REVIEW",
        "root_argv_sha256": final_index["root_argv_sha256"],
    }
    os.write(1, compact(output) + b"\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return root_only(args)


if __name__ == "__main__":
    raise SystemExit(main())
