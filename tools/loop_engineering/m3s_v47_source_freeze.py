"""Deterministic M3S-v47 source freeze with fail-closed hash reuse.

V47 derives only from the accepted V46 canonical bundle, binds the consumed
pre-root timeout, and removes redundant in-process file reads without
removing any evidence gate.  Importing this module is read-only.
"""

from __future__ import annotations

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
V44_ROOT = BASE / "trusted-tools/m3-successor-preparation-v44"
V44_DRIVER = V44_ROOT / "candidate-driver.py"
V46_ROOT = BASE / "trusted-tools/m3-successor-preparation-v46"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v47"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v47_source_freeze.py"
LEGACY_HELPER = DELIVERY / "tools/loop_engineering/m3s_v46_source_freeze.py"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V47_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V47_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
LEGACY_HELPER_SIZE = 46_162
LEGACY_HELPER_SHA256 = "b60074b6aa8583e7f083a202d57f114e98ae86d2f6e9f9332b47a48a2dfc890a"
V46_WRITER_SIZE = 1_003
V46_WRITER_SHA256 = "391b1d04e0a1ee63b792c5e8ea4ad5684087ed5f1ac288be2b49b6cc8cb840ea"
V46_DRIVER_SIZE = 557_620
V46_DRIVER_SHA256 = "0930b7b35e6880881d0a7e95fa1b25f64e4674b602c290f912142e85e9a76a31"
V46_ACCEPTANCE_SIZE = 14_681
V46_ACCEPTANCE_SHA256 = "958c422c677c11c5f93a8b0e487a8a50a279d4c2925882d277ed17a4ce36d177"
V44_DRIVER_SIZE = 538_746
V44_DRIVER_SHA256 = "d6d2141d37275259491ea79bbef10d12d1cd02d4152bf6505a3c273986ccf850"
ARCHITECTURE_SIZE = 66_116
ARCHITECTURE_SHA256 = "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce"
REQUIREMENT_V2_SIZE = 8_771
REQUIREMENT_V2_SHA256 = "31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400"
REQUIREMENT_V3_SIZE = 12_289
REQUIREMENT_V3_SHA256 = "308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00"

EXPECTED_CANDIDATES = (
    "candidate.22BiM8pO", "candidate.3WBt3ldA", "candidate.5jh3bylk",
    "candidate.5nZWpynN", "candidate.CrvNTqvL", "candidate.KWbe2iGW",
    "candidate.M4v94Rmv", "candidate.OlsWg1", "candidate.Q2vecg",
    "candidate.UU7EAiJG", "candidate.VoU5SVVl", "candidate.aw2oA4",
    "candidate.bSEqMEit", "candidate.bm4AWiof", "candidate.c79YYSLQ",
    "candidate.cQnaAbOf", "candidate.dygENR4n", "candidate.iyme1x_i",
    "candidate.jyq_n37h", "candidate.mRMO7MQ6", "candidate.o99gfxup",
    "candidate.oivrdV6U", "candidate.qaDKDWkQ", "candidate.vuDWtK0T",
    "candidate.xp23hqNY", "candidate.z6EbTJew", "candidate.CbYcDirN",
    "candidate.3Wlu7MyG",
)

V46_CLOSURE = {
    "artifacts_created": [],
    "budgets": {
        "finalize": "UNCONSUMED",
        "prepare": "UNCONSUMED",
        "root": "NOT_CROSSED_ABANDONED_WITH_TRANSPORT",
        "self_check": "UNCONSUMED",
        "transport": "CONSUMED_TIMEOUT_NO_REUSE",
        "verify": "UNCONSUMED",
    },
    "candidate_count": 28,
    "documents": {
        "execplan": {"size": 7_390_955, "sha256": "197449286a85736bd91fc71c6cc6751fac1891d954f32771d361f12b6ad93754"},
        "status": {"size": 258_138, "sha256": "2c149a14c8f0dad9960388ecb9c4f6935c9fc3ab9c58027b232238e30d3aa6b1"},
    },
    "identities": {
        "acceptance": {"size": V46_ACCEPTANCE_SIZE, "sha256": V46_ACCEPTANCE_SHA256},
        "driver": {"size": V46_DRIVER_SIZE, "sha256": V46_DRIVER_SHA256},
        "helper": {"size": LEGACY_HELPER_SIZE, "sha256": LEGACY_HELPER_SHA256},
        "writer": {"size": V46_WRITER_SIZE, "sha256": V46_WRITER_SHA256},
    },
    "inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 180},
    "preflight": {
        "canonical_comparison": "PASS",
        "gate_count": 74,
        "mutation_negatives": 10,
        "result": "PASS",
        "snapshot": {"size": 1_121, "sha256": "22a9224e4d0beb6bd6034dabaabbbb5417bb59de30fb4e7cb476d1ec6cacc7d4"},
    },
    "root": str(V46_ROOT),
    "helper_path": str(LEGACY_HELPER),
    "root_absent": True,
    "status": "TRANSPORT_TIMEOUT_BEFORE_ROOT_CREATION_NO_REUSE",
    "transport": {
        "child_exit": -9,
        "child_pid": 42_457,
        "chunks": ["93018f", "4ded26", "ad1c6f", "4f074f", "f84a37", "557631"],
        "diagnostic_overflow": False,
        "elapsed_seconds": 120.00495970802149,
        "session": 86_208,
        "stderr": {"size": 0, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
        "stdout": {"size": 0, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
        "supervisor_exit": 247,
        "timed_out": True,
    },
}


class FreezeError(RuntimeError):
    """Fail-closed V47 design or construction error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def read_regular(path: Path, maximum: int = 32 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink(), f"unsafe file: {path}")
    require(before.st_size <= maximum, f"file exceeds bound: {path}")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    chunks: list[bytes] = []
    try:
        opened = os.fstat(descriptor)
        require((opened.st_dev, opened.st_ino, opened.st_size) == (before.st_dev, before.st_ino, before.st_size), f"opened identity mismatch: {path}")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        final = os.fstat(descriptor)
        require((final.st_dev, final.st_ino, final.st_size) == (opened.st_dev, opened.st_ino, opened.st_size), f"read identity changed: {path}")
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    require(len(payload) == before.st_size, f"short read: {path}")
    after = path.lstat()
    require((after.st_dev, after.st_ino, after.st_size) == (before.st_dev, before.st_ino, before.st_size), f"path identity changed: {path}")
    return payload, before


def require_file(path: Path, size: int, digest: str, mode: int = 0o644) -> dict[str, Any]:
    payload, info = read_regular(path)
    require((len(payload), sha256(payload)) == (size, digest), f"identity mismatch: {path}")
    require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == mode, f"mode mismatch: {path}")
    return {"mode": f"{mode:04o}", "owner_uid": info.st_uid, "path": str(path), "sha256": digest, "size": size}


def _load_legacy() -> Any:
    payload, _ = read_regular(LEGACY_HELPER)
    require((len(payload), sha256(payload)) == (LEGACY_HELPER_SIZE, LEGACY_HELPER_SHA256), "V46 helper drift")
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v46_freeze", LEGACY_HELPER)
    require(spec is not None and spec.loader is not None, "V46 helper import spec failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_function(text: str, name: str, replacement: str) -> str:
    tree = ast.parse(text)
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"function replacement anchor mismatch: {name}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    return "".join(lines[: node.lineno - 1]) + replacement.rstrip() + "\n\n" + "".join(lines[node.end_lineno :])


def _hash_cache_functions() -> str:
    return '''
PROCESS_LOCAL_HASH_CACHE: dict[tuple[int, int, int, int, int, int, int], dict[str, Any]] = {}


def regular_file_cache_key(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def hash_cache_revalidation_model(before: tuple[int, ...], after: tuple[int, ...]) -> bool:
    return before == after


def hash_cache_self_test() -> dict[str, Any]:
    base = (11, 22, 501, 33188, 4096, 1001, 1002)
    labels = ("device", "inode", "uid", "mode", "size", "mtime_ns", "ctime_ns")
    fixtures = {"exact_identity_accept": hash_cache_revalidation_model(base, base)}
    for index, label in enumerate(labels):
        changed = list(base); changed[index] += 1
        fixtures[label + "_mutation_reject"] = not hash_cache_revalidation_model(base, tuple(changed))
    fixtures["toctou_reject"] = not hash_cache_revalidation_model(base, (11, 22, 501, 33188, 4096, 1001, 1003))
    require(all(fixtures.values()), "hash cache identity fixture mismatch")
    return {"cache_scope": "PROCESS_LOCAL_ONLY", "external_cache_trusted": False, "fixtures": fixtures, "identity_fields": list(labels), "result": "PASS"}


def hash_regular(path: Path, before: os.stat_result | None = None) -> dict[str, Any]:
    initial = path.lstat() if before is None else before
    require(stat.S_ISREG(initial.st_mode), f"not regular: {path}")
    key = regular_file_cache_key(initial)
    cached = PROCESS_LOCAL_HASH_CACHE.get(key)
    if cached is not None:
        after = path.lstat()
        require(stat.S_ISREG(after.st_mode) and regular_file_cache_key(after) == key, f"cached path identity changed: {path}")
        return {**cached, "path": str(path)}
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256(); size = 0
    try:
        opened = os.fstat(fd)
        require(regular_file_cache_key(opened) == key, f"opened identity changed: {path}")
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk); size += len(chunk)
        final = os.fstat(fd)
        require(regular_file_cache_key(final) == key, f"identity changed while hashing: {path}")
    finally:
        os.close(fd)
    require(size == initial.st_size, f"short read: {path}")
    after = path.lstat()
    require(stat.S_ISREG(after.st_mode) and regular_file_cache_key(after) == key, f"path identity changed while hashing: {path}")
    cached = {"device": final.st_dev, "inode": final.st_ino, "mode": f"{stat.S_IMODE(final.st_mode):04o}", "sha256": digest.hexdigest(), "size": size, "type": "regular"}
    PROCESS_LOCAL_HASH_CACHE[key] = cached
    return {**cached, "path": str(path)}
'''


def _parallel_validate_predecessors() -> str:
    return '''
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

    def validate_one(item: tuple[str, tuple[int, int, str, str]]) -> tuple[str, dict[str, Any]]:
        name, (count, regular_bytes, current_sha, historical_sha) = item
        if name == "candidate.3Wlu7MyG":
            return name, validate_m3s_v44_stopped()
        if name == "candidate.CbYcDirN":
            return name, validate_m3s_v43_stopped()
        if name == "candidate.5nZWpynN":
            return name, validate_v30_terminal_predecessor()
        protected_omissions = PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS[name]
        payload, totals = tree_manifest(BASE / name, protected_omissions)
        require(totals["path_count"] == count, f"predecessor path count mismatch: {name}")
        require(totals["regular_file_bytes"] == regular_bytes, f"predecessor byte count mismatch: {name}")
        require(sha(payload) == current_sha, f"predecessor tree mismatch: {name}")
        return name, {
            **totals,
            "canonical_current_sha256": current_sha,
            "historical_receipt_sha256": historical_sha,
            "protected_credential_paths_omitted": protected_omissions,
        }

    items = list(PREDECESSORS.items())
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="v47-predecessor-audit") as executor:
        immutable = dict(executor.map(validate_one, items))
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


def _v46_validator() -> str:
    return '''
def validate_m3s_v46_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V46_CLOSURE
    inherited = validate_m3s_v45_stopped()
    helper = Path(closure["helper_path"])
    helper_identity = require_identity(helper, closure["identities"]["helper"]["sha256"], 0o644, closure["identities"]["helper"]["size"])
    root = Path(closure["root"])
    require(not root.exists() and not root.is_symlink(), "V46 abandoned root appeared")
    for name in ("successor-preparation-v46-result.json", "final-controller-acceptance-v46-result.json", "auth-handoff-v46-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V46 abandoned result appeared")
    preflight = closure["preflight"]; transport = closure["transport"]
    require(preflight["result"] == "PASS" and preflight["gate_count"] == 74 and preflight["mutation_negatives"] == 10, "V46 preflight mismatch")
    require(transport["child_exit"] == -9 and transport["supervisor_exit"] == 247 and transport["timed_out"] is True, "V46 timeout mismatch")
    require(transport["stdout"]["size"] == 0 and transport["stderr"]["size"] == 0 and transport["diagnostic_overflow"] is False, "V46 output mismatch")
    require(closure["artifacts_created"] == [] and closure["status"] == "TRANSPORT_TIMEOUT_BEFORE_ROOT_CREATION_NO_REUSE", "V46 stop semantics mismatch")
    return {"helper": helper_identity, "inherited_v45": inherited, "private_home_traversed": False, "result": "PASS", "status": closure["status"]}
'''


def derive_v46_driver() -> bytes:
    legacy = _load_legacy()
    driver = legacy.derive_driver(legacy.derive_v45_driver())
    require((len(driver), sha256(driver)) == (V46_DRIVER_SIZE, V46_DRIVER_SHA256), "canonical V46 driver mismatch")
    return driver


def derive_driver(v46_bytes: bytes) -> bytes:
    require((len(v46_bytes), sha256(v46_bytes)) == (V46_DRIVER_SIZE, V46_DRIVER_SHA256), "accepted V46 driver mismatch")
    legacy = _load_legacy()
    v45 = legacy._load_legacy()
    v44 = v45._load_legacy()
    editor = v44._load_legacy()._load_legacy()
    transform = editor._load_legacy()._load_legacy()
    original_text = v46_bytes.decode("utf-8")
    original_tree = ast.parse(original_text, filename="<accepted-v46-driver>")
    historical: dict[str, str] = {}
    for node in original_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("PREVIOUS_"):
            source = ast.get_source_segment(original_text, node)
            require(source is not None, "historical assignment source missing")
            historical[node.targets[0].id] = source
    text = original_text.replace("V47", "__M3S_FUTURE_UPPER__").replace("v47", "__m3s_future_lower__")
    text = text.replace("V46", "V47").replace("v46", "v47")
    text = text.replace("__M3S_FUTURE_UPPER__", "V48").replace("__m3s_future_lower__", "v48")
    require(text.count("range(47, 55)") == 1, "active-version range anchor mismatch")
    text = text.replace("range(47, 55)", "range(48, 55)", 1)
    for name, source in historical.items():
        text = editor._replace_assignment_source(text, name, source)
    require(text.count('current_result_name = "successor-preparation-v" + "46-result.json"') == 1, "current result anchor mismatch")
    text = text.replace('current_result_name = "successor-preparation-v" + "46-result.json"', 'current_result_name = "successor-preparation-v" + "47-result.json"', 1)
    require(text.count('future_result_name = "successor-preparation-v" + "47-result.json"') == 1, "future result anchor mismatch")
    text = text.replace('future_result_name = "successor-preparation-v" + "47-result.json"', 'future_result_name = "successor-preparation-v" + "48-result.json"', 1)

    text = editor._insert_after_assignment(text, "PREVIOUS_M3S_V45_CLOSURE", f"PREVIOUS_M3S_V46_CLOSURE = {V46_CLOSURE!r}\n")
    require(text.count("import ast\n") == 1, "concurrency import anchor mismatch")
    text = text.replace("import ast\n", "import ast\nfrom concurrent.futures import ThreadPoolExecutor\n", 1)
    require(text.count("def validate_m3s_v45_stopped()") == 1, "V45 validator anchor mismatch")
    text = text.replace("def validate_m3s_v45_stopped()", _v46_validator().rstrip() + "\n\n\ndef validate_m3s_v45_stopped()", 1)
    gate_anchor = '        "m3s_v45_stopped": validate_m3s_v45_stopped(),'
    require(text.count(gate_anchor) == 1, "V45 gate anchor mismatch")
    text = text.replace(gate_anchor, '        "m3s_v46_stopped": validate_m3s_v46_stopped(),\n' + gate_anchor, 1)
    inventory_old = 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 180}, "original status counts mismatch")'
    require(text.count(inventory_old) == 1, "inventory anchor mismatch")
    text = text.replace(inventory_old, 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 181}, "original status counts mismatch")', 1)
    semantic_old = 'if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V45_CLOSURE):'
    require(text.count(semantic_old) == 1, "acceptance semantic anchor mismatch")
    text = text.replace(semantic_old, 'if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V46_CLOSURE):', 1)

    file_record_anchor = "if stat.S_ISREG(info.st_mode):\n        identity = hash_regular(path)"
    require(text.count(file_record_anchor) == 1, "file-record hash anchor mismatch")
    text = text.replace(file_record_anchor, "if stat.S_ISREG(info.st_mode):\n        identity = hash_regular(path, info)", 1)
    text = replace_function(text, "hash_regular", _hash_cache_functions())
    text = replace_function(text, "validate_predecessors", _parallel_validate_predecessors())
    read_anchor = '''def read_only_gates(
    values: dict[str, str],
    home: Path,
    tmp: Path,
    *,
    include_process_gate: bool,
    current_candidate: Path | None = None,
    expected_current_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require(Path(values["base"]) == BASE, "base path mismatch")'''
    require(text.count(read_anchor) == 1, "read-only gate cache anchor mismatch")
    text = text.replace(read_anchor, read_anchor.replace('    require(Path(values["base"]) == BASE, "base path mismatch")', '    PROCESS_LOCAL_HASH_CACHE.clear()\n    require(Path(values["base"]) == BASE, "base path mismatch")'), 1)
    recovery_gate = '        "v47_recovery_contract": validate_v47_recovery_contract(),'
    require(text.count(recovery_gate) == 1, "recovery gate anchor mismatch")
    text = text.replace(recovery_gate, recovery_gate + '\n        "process_local_hash_cache": hash_cache_self_test(),', 1)

    contracts = transform.literal_assignment(text.encode(), "CONTROLLER_CONTRACTS")
    candidate = contracts["candidate_allocation"]
    candidate["expected_predecessors"] = list(sorted(EXPECTED_CANDIDATES, key=os.fsencode))
    candidate["predecessor_count"] = 28
    candidate["candidate_set_contract"]["preallocation"] = "exact 28 immutable predecessor names"
    candidate["candidate_set_contract"]["postallocation"] = "exact 28 predecessors plus one unpredictable current candidate"
    candidate["fresh_successor"] = {"candidate_suffix": "one unpredictable new suffix", "private_home_tmp": "fresh", "run_id": "fresh", "retained_candidates_reusable": False}
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = "checked-in-loop-engineering-policy-plus-v47-revalidated-process-local-hash-cache-thirteen-path-v39-policy-toolchain-binding"
    policy["pre_root_full_audit"] = {"allocation": False, "gate_count": 76, "home": str(V44_ROOT / "home"), "include_process_gate": True, "no_write_snapshot": True, "tmp": str(V44_ROOT / "tmp")}
    policy["controller_acceptance_semantics"] = {"model": "controller_acceptance_semantic_violations", "predecessor": "PREVIOUS_M3S_V46_CLOSURE", "rejects": ["V45", "missing", "mutated_v46", "extra_v46", "wrong_root"]}
    policy["process_local_hash_cache"] = {"bounded_parallel_workers": 8, "external_cache_trusted": False, "identity_fields": ["device", "inode", "uid", "mode", "size", "mtime_ns", "ctime_ns"], "parallel_scope": "historical predecessor manifest validation only", "revalidate_each_hit": True, "scope": "single read_only_gates call", "semantic_gates_removed": 0, "toctou_negatives": True}
    policy["historical_candidate_counts"]["recorded_counts"]["V46"] = 28
    if "V46" not in policy["historical_candidate_counts"]["current_live_total_not_consulted"]:
        policy["historical_candidate_counts"]["current_live_total_not_consulted"].append("V46")
    policy["bounded_tree_recovery"]["stopped_predecessor"] = "PREVIOUS_M3S_V46_CLOSURE"
    policy["bounded_tree_recovery"]["retained_candidate_reuse"] = False
    trusted = contracts["trusted_context"]
    trusted["immediate_predecessor_design"] = {"closure": "PREVIOUS_M3S_V46_CLOSURE", "state": "TRANSPORT_TIMEOUT_BEFORE_ROOT_CREATION_NO_REUSE"}
    trusted["context_required_bindings"] = ["complete V39 closure", "V43 formal stop", "V44 postacceptance closure", "V7 retained stop", "V45 pre-Popen stop", "V46 transport timeout", "exact 13-path Coder allowlist", "policy receipt and semantic hash", "sealed toolchain receipt and fingerprints", "literal external controller acceptance"]
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")


def inspect_driver(payload: bytes) -> dict[str, Any]:
    legacy = _load_legacy()
    transform = legacy._load_legacy()._load_legacy()._load_legacy()._load_legacy()._load_legacy()._load_legacy()
    tree = ast.parse(payload, filename="<m3s-v47-driver>")
    compile(tree, "<m3s-v47-driver>", "exec")
    contracts = transform.literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = transform.literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_only_gates"]
    returns = [node for node in ast.walk(gate[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)] if len(gate) == 1 else []
    require(len(returns) == 1 and len(returns[0].value.keys) == 76, "gate count mismatch")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v47_static"}
    exec(compile(tree, "<m3s-v47-static>", "exec"), namespace)  # noqa: S102
    surface = {name: len(shape) for name, shape in namespace["SHAPES"].items()}
    require(surface == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    cache_cases = namespace["hash_cache_self_test"]()
    require(cache_cases["result"] == "PASS" and len(cache_cases["fixtures"]) == 9 and all(cache_cases["fixtures"].values()), "hash cache fixture failed")
    cache_key = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "regular_file_cache_key"]
    require(len(cache_key) == 1, "cache key function mismatch")
    key_returns = [node for node in ast.walk(cache_key[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple)]
    require(len(key_returns) == 1 and len(key_returns[0].value.elts) == 7, "cache identity field count mismatch")
    hash_fn = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "hash_regular"]
    require(len(hash_fn) == 1, "hash function mismatch")
    lstat_calls = [node for node in ast.walk(hash_fn[0]) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "lstat"]
    require(len(lstat_calls) >= 2, "cache hit/final lstat revalidation missing")
    predecessor_fn = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "validate_predecessors"]
    require(len(predecessor_fn) == 1, "predecessor validator mismatch")
    worker_keywords = [keyword for node in ast.walk(predecessor_fn[0]) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ThreadPoolExecutor" for keyword in node.keywords if keyword.arg == "max_workers"]
    require(len(worker_keywords) == 1 and isinstance(worker_keywords[0].value, ast.Constant) and worker_keywords[0].value.value == 8, "bounded predecessor worker mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    closure_cases = namespace["trusted_context_closure_self_test"]()
    recovery_cases = namespace["validate_v47_recovery_contract"]()
    link_cases = namespace["post_setup_link_safety_self_test"]()
    return_cases = namespace["post_setup_return_path_self_test"]()
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(all(candidate_cases.values()) and all(context_cases.values()), "driver fixture failed")
    require(all(closure_cases["fixtures"].values()), "trusted closure fixture failed")
    require(credential_cases["sanitized_baseline_count"] == 5, "credential fixture failed")
    require(all(recovery_cases["transport_fixtures"].values()), "source transport fixture failed")
    require(all(link_cases["fixtures"].values()) and all(return_cases["fixtures"].values()), "link fixture failed")
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    execute_node = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute"]
    mktemp = [node for node in ast.walk(execute_node[0]) if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/mktemp"] if len(execute_node) == 1 else []
    initializers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "initialize_and_bind_successor"]
    loop_init = [node for initializer in initializers for node in ast.walk(initializer) if isinstance(node, ast.List) and len(node.elts) >= 2 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make" and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "47-result.json"' in payload and b'future_result_name = "successor-preparation-v" + "48-result.json"' in payload, "current/future result mismatch")
    return {"ast_compile": "PASS", "cache": cache_cases, "candidate_set_cases": candidate_cases, "command_surface": surface, "context_cases": context_cases, "contracts": hashes, "credential_policy": credential_cases, "gate_count": 76, "link_safety": link_cases, "one_loop_init": True, "one_mktemp": True, "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"}, "post_setup_return_runtime": return_cases, "source_transport": recovery_cases["transport_fixtures"], "trusted_closure": closure_cases, "result": "PASS"}


def extract_source(plan_bytes: bytes) -> bytes:
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def writer_source(helper_payload: bytes) -> bytes:
    return f'''import hashlib\nimport importlib.util\nimport os\nimport stat\nimport sys\nfrom pathlib import Path\n\npath = Path({str(HELPER)!r})\ninfo = path.lstat()\nif not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size != {len(helper_payload)}:\n    raise RuntimeError("V47 helper identity mismatch")\nfd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)\ntry:\n    payload = b""\n    while True:\n        chunk = os.read(fd, 1048576)\n        if not chunk:\n            break\n        payload += chunk\nfinally:\n    os.close(fd)\nif hashlib.sha256(payload).hexdigest() != {sha256(helper_payload)!r}:\n    raise RuntimeError("V47 helper hash mismatch")\nspec = importlib.util.spec_from_file_location("liveclip_m3s_v47_root", path)\nif spec is None or spec.loader is None:\n    raise RuntimeError("V47 helper loader unavailable")\nmodule = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\nmodule.root_dispatch(sys.argv[2:])\n'''.encode()


def build_acceptance(driver: bytes, *, plan: bytes, status: bytes, source: bytes, helper: bytes) -> bytes:
    legacy = _load_legacy()
    transform = legacy._load_legacy()._load_legacy()._load_legacy()._load_legacy()._load_legacy()._load_legacy()
    contracts = transform.literal_assignment(driver, "CONTROLLER_CONTRACTS")
    hashes = transform.literal_assignment(driver, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "acceptance contracts mismatch")
    value = {
        "authority": "EXTERNAL_CONTROLLER", "contract_objects": contracts, "contracts": hashes,
        "documents": {"execplan": {"path": str(PLAN), "sha256": sha256(plan), "size": len(plan)}, "status": {"path": str(STATUS), "sha256": sha256(status), "size": len(status)}},
        "driver": {"path": str(DRIVER), "sha256": sha256(driver), "size": len(driver)}, "format_version": 1,
        "phase": "M3S_V47_CONTROLLER_ACCEPTANCE", "predecessor_closure": V46_CLOSURE,
        "preparation_source": {"helper": {"path": str(HELPER), "sha256": sha256(helper), "size": len(helper)}, "legacy_helper": {"path": str(LEGACY_HELPER), "sha256": LEGACY_HELPER_SHA256, "size": LEGACY_HELPER_SIZE}, "requirements": {"v2": {"path": str(REQUIREMENT_V2), "sha256": REQUIREMENT_V2_SHA256, "size": REQUIREMENT_V2_SIZE}, "v3": {"path": str(REQUIREMENT_V3), "sha256": REQUIREMENT_V3_SHA256, "size": REQUIREMENT_V3_SIZE}}, "accepted_v46_driver": {"sha256": V46_DRIVER_SHA256, "size": V46_DRIVER_SIZE}, "sha256": sha256(source), "size": len(source)},
        "result": "ACCEPTED_BEFORE_ROOT_CREATION", "root": transform.literal_assignment(driver, "CONTROLLER_ROOT_BINDING"),
        "seed": {"head": transform.literal_assignment(driver, "HEAD"), "manifest_sha256": transform.literal_assignment(driver, "MANIFEST_SHA"), "patch_sha256": transform.literal_assignment(driver, "PATCH_SHA"), "path_list_sha256": transform.literal_assignment(driver, "LIST_SHA")},
    }
    return compact(value) + b"\n"


def expected_environment() -> dict[str, str]:
    return {"HOME": str(ROOT / "home"), "TMPDIR": str(ROOT / "tmp"), "PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0", "__CF_USER_TEXT_ENCODING": CF_USER_TEXT_ENCODING}


def git_status_bytes(repo: Path = DELIVERY) -> bytes:
    result = subprocess.run(["/usr/bin/git", "status", "--short", "--untracked-files=all"], cwd=repo, env={"PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"}, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30)
    require(result.returncode == 0 and result.stderr == b"", "git status snapshot failed")
    return result.stdout


def status_counts(payload: bytes) -> dict[str, int]:
    staged = modified = untracked = 0
    for raw in payload.splitlines():
        line = raw.decode("utf-8", "strict")
        if line.startswith("?? "):
            untracked += 1; continue
        require(len(line) >= 3, "short git status entry")
        if line[0] != " ": staged += 1
        if line[1] != " ": modified += 1
    return {"staged": staged, "modified_tracked": modified, "ordinary_untracked": untracked}


def audit_snapshot(plan: bytes, status: bytes) -> dict[str, Any]:
    candidates = tuple(sorted((entry.name for entry in os.scandir(BASE) if entry.is_dir(follow_symlinks=False) and entry.name.startswith("candidate.")), key=os.fsencode))
    require(candidates == tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode)), "candidate set mismatch")
    status_payload = git_status_bytes(); counts = status_counts(status_payload)
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 181}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    v2 = require_file(REQUIREMENT_V2, REQUIREMENT_V2_SIZE, REQUIREMENT_V2_SHA256)
    v3 = require_file(REQUIREMENT_V3, REQUIREMENT_V3_SIZE, REQUIREMENT_V3_SHA256)
    require(not V46_ROOT.exists() and not V46_ROOT.is_symlink(), "abandoned V46 root appeared")
    require(not ROOT.exists() and not ROOT.is_symlink(), "V47 root appeared")
    return {"architecture": architecture, "candidates_sha256": sha256(compact(candidates)), "documents": {"execplan": sha256(plan), "status": sha256(status)}, "git_status_sha256": sha256(status_payload), "inventory": counts, "requirements": {"v2": v2, "v3": v3}, "v46_root_absent": True, "v47_root_absent": True}


def full_pre_root_audit(driver: bytes, acceptance: bytes, plan: bytes, status: bytes) -> dict[str, Any]:
    before = audit_snapshot(plan, status)
    tree = ast.parse(driver, filename="<m3s-v47-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v47_audit"}
    exec(compile(tree, "<m3s-v47-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode())
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V47 acceptance rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v45_substitution", namespace["PREVIOUS_M3S_V45_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value); changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value); mutated["predecessor_closure"]["transport"]["timed_out"] = False
    negatives["mutated_v46"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value); extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v46"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value); wrong_root["root"] = {**wrong_root["root"], "version": 46}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(all(negatives[name] == ["predecessor_closure"] for name in ("v45_substitution", "missing", "mutated_v46", "extra_v46")) and negatives["wrong_root"] == ["root"], "V47 acceptance negative accepted")
    values = {"base": str(BASE), "seed": str(SEED), "plan": str(PLAN), "expected_plan_sha256": sha256(plan), "status": str(STATUS), "expected_status_sha256": sha256(status)}
    saved = dict(os.environ)
    try:
        os.environ.clear(); os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver; namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver)
        gates = namespace["read_only_gates"](values, V44_ROOT / "home", V44_ROOT / "tmp", include_process_gate=True)
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None; namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear(); os.environ.update(saved)
    require(len(gates) == 76, "full pre-root gate count mismatch")
    require(gates["m3s_v46_stopped"]["result"] == "PASS" and gates["process_local_hash_cache"]["result"] == "PASS", "V46/cache gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION" and len(gates["predecessors"]["candidate_names"]) == 28, "preallocation mismatch")
    after_plan, _ = read_regular(PLAN); after_status, _ = read_regular(STATUS); after = audit_snapshot(after_plan, after_status)
    require(after == before, "full audit wrote protected state")
    return {"acceptance_negatives": negatives, "cache": gates["process_local_hash_cache"], "gate_count": len(gates), "gates": {name: "PASS" for name in gates}, "no_write": {"before": before, "after": after, "result": "PASS"}, "result": "PASS"}


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def source_receipt_payload(helper: bytes, source: bytes, driver: bytes) -> bytes:
    return compact({"driver_sha256": sha256(driver), "driver_size": len(driver), "format_version": 1, "helper_sha256": sha256(helper), "helper_size": len(helper), "phase": "M3S_V47_SOURCE_TRANSPORT", "result": "PASS", "source_sha256": sha256(source), "source_size": len(source)}) + b"\n"


def writer_test_payload() -> bytes:
    return compact({"phase": "M3S_V47_WRITER_SELF_TEST", "result": "PASS"}) + b"\n"


def self_check_payload(plan: bytes, status: bytes, helper: bytes, driver: bytes, acceptance: bytes, static: dict[str, Any]) -> bytes:
    return compact({"acceptance_sha256": sha256(acceptance), "cache_contract": static["cache"], "documents": {"plan_sha256": sha256(plan), "status_sha256": sha256(status)}, "driver_sha256": sha256(driver), "format_version": 1, "gate_count": 76, "helper_sha256": sha256(helper), "phase": "M3S_V47_SELF_CHECK", "result": "PASS", "static": static}) + b"\n"


def phase_arguments(phase: str, *, plan: bytes, status: bytes, source: bytes, driver: bytes, helper: bytes, acceptance: bytes) -> list[str]:
    common = ["--plan", str(PLAN), "--expected-plan-sha256", sha256(plan), "--status", str(STATUS), "--expected-status-sha256", sha256(status), "--expected-source-sha256", sha256(source), "--expected-driver-sha256", sha256(driver), "--expected-helper-sha256", sha256(helper)]
    if phase == "transport": return [phase, *common, "--controller-acceptance-json", acceptance.decode().rstrip("\n")]
    if phase == "self-check": return [phase, *common, "--expected-controller-acceptance-sha256", sha256(acceptance)]
    require(phase == "finalize", "unknown V47 phase")
    static = inspect_driver(driver)
    return [phase, *common, "--expected-controller-acceptance-sha256", sha256(acceptance), "--expected-self-check-sha256", sha256(self_check_payload(plan, status, helper, driver, acceptance, static)), "--expected-writer-self-test-sha256", sha256(writer_test_payload())]


def command_identity(argv: list[str]) -> dict[str, Any]:
    argv_payload = compact(argv); env = expected_environment(); order = ("HOME", "TMPDIR", "PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE", "GIT_OPTIONAL_LOCKS", "__CF_USER_TEXT_ENCODING")
    vector = ["/usr/bin/env", "-i", *(f"{name}={env[name]}" for name in order), *argv]; vector_payload = compact(vector)
    payload = "exec " + " ".join(shell_quote(value) for value in vector) + " </dev/null"; outer = ["/bin/zsh", "-f", "-c", payload]
    return {"argv": {"bytes": len(argv_payload), "sha256": sha256(argv_payload), "strings": len(argv)}, "clean_vector": {"bytes": len(vector_payload), "sha256": sha256(vector_payload), "strings": len(vector)}, "literal_payload": {"bytes": len(payload.encode()), "sha256": sha256(payload.encode()), "tokens": len(vector)}, "outer_argv": {"bytes": len(compact(outer)), "sha256": sha256(compact(outer)), "strings": len(outer)}, "schema": [], "values": {"argv": argv, "outer": outer}}


def command_identities(*, plan: bytes, status: bytes, source: bytes, driver: bytes, helper: bytes, acceptance: bytes) -> dict[str, Any]:
    result = {}
    for phase in ("transport", "self-check", "finalize"):
        args = phase_arguments(phase, plan=plan, status=status, source=source, driver=driver, helper=helper, acceptance=acceptance)
        argv = ["/opt/homebrew/bin/python3.12", "-c", source.decode(), "--", *args]
        result[phase] = command_identity(argv); result[phase]["schema"] = [args[0], *args[1::2]]
    return result


def canonical_bundle(plan: bytes, status: bytes, helper: bytes) -> dict[str, Any]:
    source = writer_source(helper); v46 = derive_v46_driver(); driver = derive_driver(v46)
    acceptance = build_acceptance(driver, plan=plan, status=status, source=source, helper=helper)
    commands = command_identities(plan=plan, status=status, source=source, driver=driver, helper=helper, acceptance=acceptance)
    return {"acceptance": acceptance, "commands": commands, "driver": driver, "helper": helper, "plan": plan, "source": source, "status": status, "v46_driver": v46}


def identity(value: bytes) -> dict[str, Any]:
    return {"bytes": len(value), "sha256": sha256(value)}


def launch_observation(bundle: dict[str, Any]) -> dict[str, Any]:
    return {"plan": identity(bundle["plan"]), "status": identity(bundle["status"]), "helper": identity(bundle["helper"]), "writer": identity(bundle["source"]), "driver": identity(bundle["driver"]), "acceptance": identity(bundle["acceptance"]), "commands": {phase: {name: data[name] for name in ("argv", "clean_vector", "literal_payload", "outer_argv")} for phase, data in bundle["commands"].items()}}


def launch_precondition_comparison(bundle: dict[str, Any], observed: dict[str, Any]) -> bool:
    return observed == launch_observation(bundle)


def launch_precondition_self_test(bundle: dict[str, Any]) -> dict[str, Any]:
    observed = launch_observation(bundle); require(launch_precondition_comparison(bundle, observed), "canonical comparison rejected")
    negatives = {}
    for label in ("plan", "status", "helper", "writer", "driver", "acceptance"):
        changed = copy.deepcopy(observed); changed[label]["sha256"] = "0" * 64; negatives[label] = not launch_precondition_comparison(bundle, changed)
    for label, phase, field in (("argv", "transport", "argv"), ("vector", "self-check", "clean_vector"), ("payload", "finalize", "literal_payload"), ("outer", "transport", "outer_argv")):
        changed = copy.deepcopy(observed); changed["commands"][phase][field]["sha256"] = "0" * 64; negatives[label] = not launch_precondition_comparison(bundle, changed)
    require(all(negatives.values()), "canonical comparison negative accepted")
    return {"negative_count": len(negatives), "negatives": negatives, "result": "PASS"}


def write_exclusive(path: Path, payload: bytes) -> dict[str, Any]:
    require(not path.exists() and not path.is_symlink(), f"destination exists: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view); require(written > 0, f"short write: {path}"); view = view[written:]
        os.fsync(descriptor); info = os.fstat(descriptor)
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o600, f"written mode mismatch: {path}")
    finally: os.close(descriptor)
    reread, info = read_regular(path); require(reread == payload, f"written bytes mismatch: {path}")
    return {"mode": "0600", "owner_uid": info.st_uid, "path": str(path), "sha256": sha256(payload), "size": len(payload)}


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def parse_phase(argv: list[str]) -> tuple[str, dict[str, str]]:
    require(argv and argv[0] in {"transport", "self-check", "finalize"}, "V47 phase mismatch"); phase = argv[0]
    require(len(argv[1:]) % 2 == 0, "V47 argument shape mismatch"); values = dict(zip(argv[1::2], argv[2::2], strict=True))
    expected = {"--plan", "--expected-plan-sha256", "--status", "--expected-status-sha256", "--expected-source-sha256", "--expected-driver-sha256", "--expected-helper-sha256"}
    if phase == "transport": expected.add("--controller-acceptance-json")
    else: expected.add("--expected-controller-acceptance-sha256")
    if phase == "finalize": expected.update({"--expected-self-check-sha256", "--expected-writer-self-test-sha256"})
    require(set(values) == expected, "V47 argument schema mismatch"); return phase, values


def phase_context(values: dict[str, str]) -> tuple[bytes, bytes, bytes, bytes, bytes, dict[str, Any]]:
    require(values.get("--plan") == str(PLAN) and values.get("--status") == str(STATUS), "document path mismatch")
    plan, _ = read_regular(PLAN); status, _ = read_regular(STATUS); helper, _ = read_regular(HELPER)
    require(sha256(plan) == values.get("--expected-plan-sha256") and sha256(status) == values.get("--expected-status-sha256") and sha256(helper) == values.get("--expected-helper-sha256"), "canonical input mismatch")
    bundle = canonical_bundle(plan, status, helper); source = bundle["source"]; driver = bundle["driver"]
    require(extract_source(plan) == source and sha256(source) == values.get("--expected-source-sha256") and sha256(driver) == values.get("--expected-driver-sha256"), "canonical artifact mismatch")
    require(launch_precondition_self_test(bundle)["result"] == "PASS", "canonical launch proof failed")
    return plan, status, helper, source, driver, {"acceptance": bundle["acceptance"], "bundle": bundle, "static": inspect_driver(driver)}


def final_index_payload(plan: bytes, status: bytes, helper: bytes, source: bytes, driver: bytes, acceptance: bytes) -> bytes:
    commands = command_identities(plan=plan, status=status, source=source, driver=driver, helper=helper, acceptance=acceptance)
    return compact({"controller_acceptance_sha256": sha256(acceptance), "documents": {"plan_sha256": sha256(plan), "status_sha256": sha256(status)}, "driver_sha256": sha256(driver), "format_version": 1, "phase": "M3S_V47_FINAL_INDEX", "phase_argv_sha256": {name: value["argv"]["sha256"] for name, value in commands.items()}, "source_sha256": sha256(source), "verdict": "M3S_V47_READY_FOR_CONTROLLER_REVIEW"}) + b"\n"


def validate_root_layout(receipt_names: set[str]) -> None:
    for path in (ROOT, ROOT / "home", ROOT / "tmp", RECEIPTS):
        info = path.lstat(); require(stat.S_ISDIR(info.st_mode) and not path.is_symlink() and info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700, "unsafe V47 root directory")
    require(set(os.listdir(ROOT)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V47 root entries mismatch")
    require(not os.listdir(ROOT / "home") and not os.listdir(ROOT / "tmp"), "V47 private directories changed")
    require(set(os.listdir(RECEIPTS)) == receipt_names, "V47 receipt domain mismatch")


def transport_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values); require(not ROOT.exists() and not ROOT.is_symlink(), "V47 root exists")
    supplied = values.get("--controller-acceptance-json", "").encode() + b"\n"; require(supplied == derived["acceptance"], "acceptance transport mismatch")
    audit = full_pre_root_audit(driver, supplied, plan, status); require(audit["gate_count"] == 76 and audit["no_write"]["result"] == "PASS", "pre-root audit mismatch")
    os.mkdir(ROOT, 0o700); fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"): os.mkdir(ROOT / name, 0o700); fsync_directory(ROOT)
    write_exclusive(DRIVER, driver); write_exclusive(RECEIPTS / "controller-acceptance-v47.json", supplied); write_exclusive(RECEIPTS / "source-receipt.json", source_receipt_payload(helper, source, driver)); fsync_directory(RECEIPTS); fsync_directory(ROOT)
    return {"phase": "M3S_V47_ROOT_TRANSPORT", "result": "PASS"}


def self_check_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values); validate_root_layout({"controller-acceptance-v47.json", "source-receipt.json"})
    require_file(DRIVER, len(driver), sha256(driver), 0o600); acceptance = derived["acceptance"]
    require_file(RECEIPTS / "controller-acceptance-v47.json", len(acceptance), sha256(acceptance), 0o600); require(values.get("--expected-controller-acceptance-sha256") == sha256(acceptance), "acceptance argument mismatch")
    expected_source = source_receipt_payload(helper, source, driver); require_file(RECEIPTS / "source-receipt.json", len(expected_source), sha256(expected_source), 0o600)
    write_exclusive(RECEIPTS / "writer-self-test.json", writer_test_payload()); write_exclusive(RECEIPTS / "self-check-result.json", self_check_payload(plan, status, helper, driver, acceptance, derived["static"])); fsync_directory(RECEIPTS)
    return {"phase": "M3S_V47_ROOT_SELF_CHECK", "result": "PASS"}


def finalize_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values); validate_root_layout({"controller-acceptance-v47.json", "source-receipt.json", "writer-self-test.json", "self-check-result.json"})
    acceptance = derived["acceptance"]; expected_self = self_check_payload(plan, status, helper, driver, acceptance, derived["static"]); expected_writer = writer_test_payload()
    require(values.get("--expected-controller-acceptance-sha256") == sha256(acceptance) and values.get("--expected-self-check-sha256") == sha256(expected_self) and values.get("--expected-writer-self-test-sha256") == sha256(expected_writer), "final argument mismatch")
    require_file(RECEIPTS / "self-check-result.json", len(expected_self), sha256(expected_self), 0o600); require_file(RECEIPTS / "writer-self-test.json", len(expected_writer), sha256(expected_writer), 0o600)
    final_index = write_exclusive(RECEIPTS / "final-index.json", final_index_payload(plan, status, helper, source, driver, acceptance)); fsync_directory(RECEIPTS); fsync_directory(ROOT)
    return {"final_index": final_index, "phase": "M3S_V47_ROOT_FINALIZE", "result": "M3S_V47_READY_FOR_CONTROLLER_REVIEW"}


def root_dispatch(argv: list[str]) -> None:
    phase, values = parse_phase(argv); output = {"transport": transport_phase, "self-check": self_check_phase, "finalize": finalize_phase}[phase](values); os.write(1, compact(output) + b"\n")


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
