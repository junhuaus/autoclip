"""Deterministic M3S-v36 source-freeze and root-only helper.

This credential-free trusted helper derives V36 only from the sealed V35
driver, repairs its stale controller-acceptance predecessor comparison, binds
the retained V35 root/verifier stop, and constructs only the fixed V36 root.
It is not product code and is import-only.
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
V35_HELPER = DELIVERY / "tools/loop_engineering/m3s_v35_source_freeze.py"
V35_HELPER_SIZE = 35_092
V35_HELPER_SHA256 = "86a376a73130fea509582b9ad5da0a9ceef90ec9327adf206163bd9a2307d8af"
V35_ROOT = BASE / "trusted-tools/m3-successor-preparation-v35"
V35_DRIVER = V35_ROOT / "candidate-driver.py"
V35_DRIVER_SIZE = 425_920
V35_DRIVER_SHA256 = "349309ec7bd676d8bd2d5b34b69d0fc1e57683fe864d4287ad29b2f8069aaafd"
V35_ROOT_FILES = {
    "candidate-driver.py": (425_920, V35_DRIVER_SHA256),
    "receipts/controller-acceptance-v35.json": (
        8_153,
        "b25ef8c63eb64cbe9d40de696faef654b51473e266e94fb198e5fea13a5fb14a",
    ),
    "receipts/source-receipt.json": (
        524,
        "e6c02026f2aa61ec39515e6a058b937a153061b77d1f100537f7ff4fc87f3177",
    ),
    "receipts/writer-self-test.json": (
        72,
        "0496e888261c39d62140eecaf3e148054fef41b93bf8110ff6a40d2d3232688c",
    ),
    "receipts/self-check-result.json": (
        4_461,
        "00eb0055128d2939a1ccd9fe8a727b9cf1fb2d3011411371ac8c53ac9c189823",
    ),
    "receipts/final-index.json": (
        1_999,
        "b3a31500402e750f658c1c2006ae43309597f2ca89016b0b47a94cd5b7785172",
    ),
}
V35_CLOSURE = {
    "budgets": {
        "accept_final": "UNAUTHORIZED",
        "auth": "UNAUTHORIZED",
        "formal": "UNAUTHORIZED",
        "init": "ABANDONED_UNCONSUMED",
        "prepare_result": "ABANDONED_UNCONSUMED",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "ABANDONED_UNCONSUMED",
        "verify_prepare": "CONSUMED_NO_REUSE",
    },
    "candidate_count": 21,
    "post_root_documents": {
        "execplan": {
            "sha256": "5e825d8462f7bd2e4ff3bc98e73a040704638b6a7b1f19bd06e7892aecdc4837",
            "size": 7_003_866,
        },
        "status": {
            "sha256": "7a9b18ee4345d3192087329da131b1a20f77190789af60c9b42e5e5f3d9847d1",
            "size": 142_437,
        },
    },
    "root": str(V35_ROOT),
    "root_documents": {
        "execplan": {
            "sha256": "64cee09b79f4d6875871981851e936113db2476905309f52111e3ba3e3c1359b",
            "size": 6_994_015,
        },
        "status": {
            "sha256": "181058267a8ef4e4462f82aa3c5963dd294e4370c2f17e701c488b403653c673",
            "size": 140_639,
        },
    },
    "root_files": {
        name: {"sha256": digest, "size": size}
        for name, (size, digest) in V35_ROOT_FILES.items()
    },
    "root_prepare_argv_json_sha256": (
        "ea6e876fc44d9bff1f87917487df43cc2680d6727580ea2b25f3e61b0525a48a"
    ),
    "root_verdict": "M3S_V35_READY_FOR_CONTROLLER_REVIEW",
    "verify_prepare": {
        "error": "RuntimeError: controller acceptance semantic mismatch",
        "gate_count": 57,
        "gate_outcome": "NOT_RUN",
        "inputs": {
            "argv_json_sha256": (
                "d4010a1d4449cd7904d1e0ec684a6cf00a671b408683ae38c420d3aca7422723"
            ),
            "env_vector_json_sha256": (
                "80ff466d44f48424d276136af1133e3931774cfaf4ad87999132f3fd1df463b6"
            ),
            "shell_envelope_sha256": (
                "9dc28590122bd4599b6ae370d5e6e6ab02dfab8cb75c1cdd4517bbe95ed22a71"
            ),
        },
        "returncode": 1,
        "stderr": {
            "sha256": "371b0b9ab0da298aa7e234544e3590eb078b453e8e52ac2eb95c6755366c961c",
            "size": 1_652,
        },
        "stdout": {
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "size": 0,
        },
        "tool": {
            "chunk": "7a2cc9",
            "session_id": None,
            "wall_seconds": 0.026321792,
        },
    },
}
ROOT = BASE / "trusted-tools/m3-successor-preparation-v36"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V36_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V36_END\n"
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
    """Fail-closed V36 design or construction error."""


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


def read_regular(
    path: Path,
    maximum: int = 8 * 1024 * 1024,
) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and not path.is_symlink(),
        f"unsafe file: {path}",
    )
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


def require_file(
    path: Path,
    size: int,
    digest: str,
    mode: int = 0o600,
) -> dict[str, Any]:
    payload, info = read_regular(path)
    require(
        (len(payload), sha256(payload)) == (size, digest),
        f"identity mismatch: {path}",
    )
    require(
        info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode,
        f"owner/mode mismatch: {path}",
    )
    return {
        "mode": f"{mode:04o}",
        "owner_uid": info.st_uid,
        "path": str(path),
        "sha256": digest,
        "size": size,
    }


def load_v35_helper() -> tuple[Any, bytes]:
    helper_bytes, _ = read_regular(V35_HELPER, 128 * 1024)
    require(
        (len(helper_bytes), sha256(helper_bytes))
        == (V35_HELPER_SIZE, V35_HELPER_SHA256),
        "sealed V35 helper mismatch",
    )
    spec = importlib.util.spec_from_file_location(
        "liveclip_m3s_v35_frozen",
        V35_HELPER,
    )
    require(spec is not None and spec.loader is not None, "V35 helper unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, helper_bytes


def literal_assignment(payload: bytes, name: str) -> Any:
    tree = ast.parse(payload, filename="<m3s-v36-literal>")
    values = [
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    require(len(values) == 1, f"literal assignment mismatch: {name}")
    return values[0]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    require(text.count(old) == 1, f"replacement count mismatch: {label}")
    return text.replace(old, new, 1)


def replace_assignment(text: str, name: str, value: object) -> str:
    tree = ast.parse(text, filename="<m3s-v36-assignment>")
    nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    ]
    require(len(nodes) == 1, f"assignment replacement mismatch: {name}")
    node = nodes[0]
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    return text[:start] + f"{name} = {value!r}" + text[end:]


def derive_driver(v35_bytes: bytes) -> bytes:
    """Derive V36 deterministically from the exact sealed V35 driver."""

    require(
        (len(v35_bytes), sha256(v35_bytes))
        == (V35_DRIVER_SIZE, V35_DRIVER_SHA256),
        "sealed V35 driver mismatch",
    )
    text = v35_bytes.decode("utf-8")
    future_upper = "LIVECLIP_FUTURE_VERSION_UPPER"
    future_lower = "liveclip_future_version_lower"
    require(
        future_upper not in text and future_lower not in text,
        "version sentinel collision",
    )
    text = text.replace("V36", future_upper).replace("v36", future_lower)
    text = text.replace("V35", "V36").replace("v35", "v36")
    text = text.replace(future_upper, "V37").replace(future_lower, "v37")
    for old, new, label in (
        (
            'current_result_name = "successor-preparation-v" + "35-result.json"',
            'current_result_name = "successor-preparation-v" + "36-result.json"',
            "current result",
        ),
        (
            'future_result_name = "successor-preparation-v" + "36-result.json"',
            'future_result_name = "successor-preparation-v" + "37-result.json"',
            "future result",
        ),
        (
            'regression_name = "successor-preparation-v" + "35-result.json"',
            'regression_name = "successor-preparation-v" + "36-result.json"',
            "regression result",
        ),
        ('"036-result.json"', '"037-result.json"', "substitution result"),
        ("range(36, 55)", "range(37, 55)", "future result range"),
        ('"ordinary_untracked": 161', '"ordinary_untracked": 162', "inventory"),
    ):
        text = replace_once(text, old, new, label)

    text = replace_once(
        text,
        "CONTROLLER_ROOT_BINDING =",
        f"PREVIOUS_M3S_V35_CLOSURE = {V35_CLOSURE!r}\n\nCONTROLLER_ROOT_BINDING =",
        "V35 closure insertion",
    )
    validator_source = '''

def validate_m3s_v35_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V35_CLOSURE
    root = Path(closure["root"])
    private_directory_identity(root)
    private_directory_identity(root / "home")
    private_directory_identity(root / "tmp")
    private_directory_identity(root / "receipts")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V35 private directory drift")
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V35 root entries mismatch")
    expected_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_receipts, "V35 receipt set mismatch")
    files = {
        name: require_identity(root / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["root_files"].items()
    }
    require(len([path for path in BASE.iterdir() if path.name.startswith("candidate.")]) == closure["candidate_count"], "V35 candidate count mismatch")
    for name in (
        "successor-preparation-v35-result.json",
        "final-controller-acceptance-v35-result.json",
        "auth-handoff-v35-result.json",
    ):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V35 reserved result appeared")
    return {"closure": closure, "files": files, "result": "PASS"}
'''
    text = replace_once(
        text,
        "\ndef validate_m3s_v34_stopped() -> dict[str, Any]:",
        validator_source + "\n\ndef validate_m3s_v34_stopped() -> dict[str, Any]:",
        "V35 validator insertion",
    )
    text = replace_once(
        text,
        '        "m3s_v34_stopped": validate_m3s_v34_stopped(),',
        '        "m3s_v35_stopped": validate_m3s_v35_stopped(),\n'
        '        "m3s_v34_stopped": validate_m3s_v34_stopped(),',
        "V35 gate insertion",
    )
    semantic_source = '''

def controller_acceptance_semantic_violations(value: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V35_CLOSURE):
        violations.append("predecessor_closure")
    if value.get("root") != CONTROLLER_ROOT_BINDING:
        violations.append("root")
    return violations
'''
    text = replace_once(
        text,
        "\ndef validate_controller_acceptance(values: dict[str, str])",
        semantic_source + "\n\ndef validate_controller_acceptance(values: dict[str, str])",
        "acceptance semantic model insertion",
    )
    stale_comparison = (
        '    require(canonical_json_model(value["predecessor_closure"]) == '
        'canonical_json_model(PREVIOUS_M3S_V33_CLOSURE) and value["root"] == '
        'CONTROLLER_ROOT_BINDING, "controller acceptance semantic mismatch")'
    )
    text = replace_once(
        text,
        stale_comparison,
        '    require(controller_acceptance_semantic_violations(value) == [], '
        '"controller acceptance semantic mismatch")',
        "stale acceptance comparison",
    )
    payload = text.encode("utf-8")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    require(isinstance(contracts, dict), "contract object mismatch")
    contracts["policy_toolchain"]["controller_acceptance_semantics"] = {
        "model": "controller_acceptance_semantic_violations",
        "predecessor": "PREVIOUS_M3S_V35_CLOSURE",
        "rejects": ["V33", "V34", "missing", "mutated_v35", "extra_v35"],
    }
    contracts["trusted_context"]["immediate_predecessor"] = {
        "closure": "PREVIOUS_M3S_V35_CLOSURE",
        "root": str(V35_ROOT),
        "verifier": "CONSUMED_FAILURE",
    }
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")


def function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    require(len(matches) == 1, f"function count mismatch: {name}")
    return matches[0]


def inspect_driver(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8")
    tree = ast.parse(text, filename="<m3s-v36-driver>")
    compile(tree, "<m3s-v36-driver>", "exec")
    contracts = literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require(
        {name: sha256(compact(value)) for name, value in contracts.items()}
        == hashes,
        "contract hash mismatch",
    )
    execute_node = function_node(tree, "execute")
    mktemp = [
        node
        for node in ast.walk(execute_node)
        if isinstance(node, ast.List)
        and node.elts
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "/usr/bin/mktemp"
    ]
    initializers = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "initialize_and_bind_successor"
    ]
    loop_init = [
        node
        for function in initializers
        for node in ast.walk(function)
        if isinstance(node, ast.List)
        and len(node.elts) >= 2
        and isinstance(node.elts[0], ast.Constant)
        and node.elts[0].value == "/usr/bin/make"
        and isinstance(node.elts[1], ast.Constant)
        and node.elts[1].value == "loop-init"
    ]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(payload.count(b'"ordinary_untracked": 162') == 1, "inventory count mismatch")
    require(b'"ordinary_untracked": 161' not in payload, "stale inventory retained")
    require(b'current_result_name = "successor-preparation-v" + "36-result.json"' in payload, "current result mismatch")
    require(b'future_result_name = "successor-preparation-v" + "37-result.json"' in payload, "future result mismatch")
    semantic = ast.get_source_segment(text, function_node(tree, "controller_acceptance_semantic_violations"))
    acceptance = ast.get_source_segment(text, function_node(tree, "validate_controller_acceptance"))
    require(semantic is not None and "PREVIOUS_M3S_V35_CLOSURE" in semantic, "immediate predecessor model missing")
    require(acceptance is not None and "controller_acceptance_semantic_violations(value)" in acceptance, "validator/model binding missing")
    require("canonical_json_model(PREVIOUS_M3S_V33_CLOSURE) and value[\"root\"]" not in acceptance, "stale V33 comparator retained")
    gate = function_node(tree, "read_only_gates")
    returns = [node for node in ast.walk(gate) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    require(len(returns) == 1 and len(returns[0].value.keys) == 58, "gate count mismatch")
    return {
        "ast_compile": "PASS",
        "contracts": hashes,
        "gate_count": 58,
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
    require(
        {name: sha256(compact(value)) for name, value in contracts.items()}
        == hashes,
        "acceptance contracts mismatch",
    )
    value = {
        "authority": "EXTERNAL_CONTROLLER",
        "contract_objects": contracts,
        "contracts": hashes,
        "documents": {
            "execplan": {
                "path": str(PLAN),
                "sha256": sha256(plan_bytes),
                "size": len(plan_bytes),
            },
            "status": {
                "path": str(STATUS),
                "sha256": sha256(status_bytes),
                "size": len(status_bytes),
            },
        },
        "driver": {
            "path": str(DRIVER),
            "sha256": sha256(driver_bytes),
            "size": len(driver_bytes),
        },
        "format_version": 1,
        "phase": "M3S_V36_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V35_CLOSURE,
        "preparation_source": {
            "helper": {
                "path": str(DELIVERY / "tools/loop_engineering/m3s_v36_source_freeze.py"),
                "sha256": sha256(helper_bytes),
                "size": len(helper_bytes),
            },
            "sealed_v35_helper": {
                "path": str(V35_HELPER),
                "sha256": V35_HELPER_SHA256,
                "size": V35_HELPER_SIZE,
            },
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


def acceptance_model_fixtures(
    payload: bytes,
    acceptance: bytes,
) -> dict[str, Any]:
    tree = ast.parse(payload, filename="<m3s-v36-acceptance-runtime>")
    namespace: dict[str, Any] = {
        "__file__": str(DRIVER),
        "__name__": "liveclip_m3s_v36_static_runtime",
    }
    exec(compile(tree, "<m3s-v36-acceptance-runtime>", "exec"), namespace)  # noqa: S102
    model = namespace["controller_acceptance_semantic_violations"]
    value = json.loads(acceptance.decode("utf-8"))
    require(model(value) == [], "actual V35 predecessor acceptance rejected")
    negatives: dict[str, list[str]] = {}
    replacements = {
        "v33_substitution": namespace["PREVIOUS_M3S_V33_CLOSURE"],
        "v34_substitution": namespace["PREVIOUS_M3S_V34_CLOSURE"],
        "missing": {},
    }
    for label, replacement in replacements.items():
        candidate = copy.deepcopy(value)
        candidate["predecessor_closure"] = replacement
        negatives[label] = model(candidate)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["verify_prepare"]["error"] = "RuntimeError: substituted"
    negatives["mutated_v35"] = model(mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v35"] = model(extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 35}
    negatives["wrong_root"] = model(wrong_root)
    require(
        all(
            negatives[label] == ["predecessor_closure"]
            for label in (
                "v33_substitution",
                "v34_substitution",
                "missing",
                "mutated_v35",
                "extra_v35",
            )
        ),
        "predecessor negative fixture accepted",
    )
    require(negatives["wrong_root"] == ["root"], "root negative fixture accepted")
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(phase_violations == [], "actual phase-source policy mismatch")
    shapes = namespace["SHAPES"]
    require(
        set(shapes) == {"prepare", "verify-prepare", "accept-final"}
        and len(shapes["prepare"]) == 23
        and len(shapes["verify-prepare"]) == 23
        and len(shapes["accept-final"]) == 15,
        "actual command surface mismatch",
    )
    return {
        "actual_model_positive": "PASS",
        "command_surface": {name: len(shape) for name, shape in shapes.items()},
        "negative_fixtures": negatives,
        "phase_source_policy": "PASS",
        "result": "PASS",
    }


def runtime_validation(
    payload: bytes,
    acceptance: bytes,
    plan_sha: str,
    status_sha: str,
) -> dict[str, Any]:
    tree = ast.parse(payload, filename="<m3s-v36-runtime>")
    namespace: dict[str, Any] = {
        "__file__": str(DRIVER),
        "__name__": "liveclip_m3s_v36_runtime",
    }
    exec(compile(tree, "<m3s-v36-runtime>", "exec"), namespace)  # noqa: S102
    model = acceptance_model_fixtures(payload, acceptance)
    v35 = namespace["validate_m3s_v35_stopped"]()
    observed = namespace["status_counts"](DELIVERY)
    expected = {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 162}
    require(observed == expected, "final inventory mismatch")
    original = namespace["validate_original"](plan_sha, status_sha)
    actual_status_counts = namespace["status_counts"]
    stale: dict[str, bool] = {}
    for count in (156, 159, 160, 161):
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
    namespace["status_counts"] = actual_status_counts
    require(all(stale.values()), "stale inventory fixture accepted")
    return {
        "acceptance_model": model,
        "final_inventory": observed,
        "original": original,
        "stale_inventory": stale,
        "v35_stopped": v35["result"],
        "result": "PASS",
    }


def validate_v35_root() -> dict[str, Any]:
    root_info = V35_ROOT.lstat()
    require(
        stat.S_ISDIR(root_info.st_mode) and not V35_ROOT.is_symlink(),
        "unsafe V35 root",
    )
    require(
        root_info.st_uid == CURRENT_UID
        and stat.S_IMODE(root_info.st_mode) == 0o700,
        "V35 root owner/mode mismatch",
    )
    require(
        set(os.listdir(V35_ROOT)) == {"candidate-driver.py", "home", "tmp", "receipts"},
        "V35 root entries mismatch",
    )
    directories: dict[str, dict[str, Any]] = {}
    for name in ("home", "tmp", "receipts"):
        path = V35_ROOT / name
        info = path.lstat()
        require(
            stat.S_ISDIR(info.st_mode) and not path.is_symlink(),
            f"unsafe V35 directory: {name}",
        )
        require(
            info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700,
            f"V35 directory owner/mode mismatch: {name}",
        )
        directories[name] = {
            "mode": "0700",
            "owner_uid": info.st_uid,
            "path": str(path),
        }
    require(
        not os.listdir(V35_ROOT / "home") and not os.listdir(V35_ROOT / "tmp"),
        "V35 private directory not empty",
    )
    expected_receipts = {
        Path(name).name for name in V35_ROOT_FILES if name.startswith("receipts/")
    }
    require(
        set(os.listdir(V35_ROOT / "receipts")) == expected_receipts,
        "V35 receipt entries mismatch",
    )
    files = {
        name: require_file(V35_ROOT / name, size, digest)
        for name, (size, digest) in V35_ROOT_FILES.items()
    }
    for name in (
        "successor-preparation-v35-result.json",
        "final-controller-acceptance-v35-result.json",
        "auth-handoff-v35-result.json",
    ):
        path = V35_ROOT / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V35 reserved result appeared")
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


def write_exclusive(path: Path, payload: bytes) -> dict[str, Any]:
    require(not path.exists() and not path.is_symlink(), f"destination exists: {path}")
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            require(written > 0, f"short write: {path}")
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd)
        require(
            info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o600,
            f"written owner/mode mismatch: {path}",
        )
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
    require(sha256(source_bytes) == args.expected_source_sha256, "source hash mismatch")
    require(sha256(helper_bytes) == args.expected_helper_sha256, "helper hash mismatch")
    plan_bytes, _ = read_regular(PLAN)
    status_bytes, _ = read_regular(STATUS)
    require(sha256(plan_bytes) == args.expected_plan_sha256, "plan hash mismatch")
    require(sha256(status_bytes) == args.expected_status_sha256, "status hash mismatch")
    require(
        plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1,
        "source marker mismatch",
    )
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    require(plan_bytes[start:finish] == source_bytes, "embedded source mismatch")
    load_v35_helper()
    v35_bytes, _ = read_regular(V35_DRIVER)
    driver_bytes = derive_driver(v35_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(
        driver_bytes,
        plan_bytes=plan_bytes,
        status_bytes=status_bytes,
        source_bytes=source_bytes,
        helper_bytes=helper_bytes,
    )
    runtime = runtime_validation(
        driver_bytes,
        acceptance,
        args.expected_plan_sha256,
        args.expected_status_sha256,
    )
    predecessor = validate_v35_root()
    candidates = tuple(
        sorted(
            (path.name for path in BASE.iterdir() if path.name.startswith("candidate.")),
            key=os.fsencode,
        )
    )
    require(
        candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)),
        "candidate set mismatch",
    )
    require(not ROOT.exists() and not ROOT.is_symlink(), "V36 root exists")
    root_argv = [
        "/opt/homebrew/bin/python3.12",
        "-c",
        source_bytes.decode("utf-8"),
        *raw_argv,
    ]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(
        root_argv,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")

    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(
        RECEIPTS / "controller-acceptance-v36.json",
        acceptance,
    )
    source_receipt = write_exclusive(
        RECEIPTS / "source-receipt.json",
        compact(
            {
                "driver": driver_identity,
                "helper_sha256": sha256(helper_bytes),
                "phase": "M3S_V36_SOURCE_WRITE",
                "result": "PASS",
                "source_sha256": sha256(source_bytes),
            }
        )
        + b"\n",
    )
    writer_receipt = write_exclusive(
        RECEIPTS / "writer-self-test.json",
        compact(
            {
                "format_version": 1,
                "phase": "M3S_V36_WRITER_SELF_TEST",
                "result": "PASS",
            }
        )
        + b"\n",
    )
    self_check = write_exclusive(
        RECEIPTS / "self-check-result.json",
        compact(
            {
                "format_version": 1,
                "phase": "M3S_V36_SELF_CHECK",
                "predecessor": predecessor,
                "result": "PASS",
                "runtime": runtime,
                "static": static,
            }
        )
        + b"\n",
    )
    final_index_value = {
        "controller_acceptance": acceptance_identity,
        "documents": {
            "plan_sha256": args.expected_plan_sha256,
            "status_sha256": args.expected_status_sha256,
        },
        "driver": driver_identity,
        "format_version": 1,
        "phase": "M3S_V36_FINAL_INDEX",
        "root_prepare_argv_json_sha256": sha256(root_argv_json),
        "source_receipt": source_receipt,
        "self_check": self_check,
        "verdict": "M3S_V36_READY_FOR_CONTROLLER_REVIEW",
        "writer_self_test": writer_receipt,
    }
    final_index = write_exclusive(
        RECEIPTS / "final-index.json",
        compact(final_index_value) + b"\n",
    )
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(
        1,
        compact(
            {
                "driver": driver_identity,
                "final_index": final_index,
                "phase": "M3S_V36_ROOT_ONLY",
                "result": "M3S_V36_READY_FOR_CONTROLLER_REVIEW",
            }
        )
        + b"\n",
    )
    return 0


def main(
    argv: list[str],
    *,
    source_bytes: bytes,
    helper_bytes: bytes,
) -> int:
    args = parse_args(argv)
    return root_only(args, source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
