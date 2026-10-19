"""Deterministic M3S-v46 source freeze and split root-only helper.

V46 derives only from the accepted immutable V45 source design.  One
canonical bundle supplies every artifact and command identity so a launch
guard never retypes a document or artifact identity.  Importing this module
is read-only; only explicit root phases may write the fixed V46 root.
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
V45_ROOT = BASE / "trusted-tools/m3-successor-preparation-v45"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v46"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v46_source_freeze.py"
LEGACY_HELPER = DELIVERY / "tools/loop_engineering/m3s_v45_source_freeze.py"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V46_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V46_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
LEGACY_HELPER_SIZE = 59_278
LEGACY_HELPER_SHA256 = "45128636342d726e12e7c9d65fe49f15dce7f62fdc0810aaa87c6c92ee924653"
V44_DRIVER_SIZE = 538_746
V44_DRIVER_SHA256 = "d6d2141d37275259491ea79bbef10d12d1cd02d4152bf6505a3c273986ccf850"
V45_WRITER_SIZE = 1_003
V45_WRITER_SHA256 = "50d4eed30f0b6a0b2c5d3ebae39950608d377a8a791100e50e212fec364b3a30"
V45_DRIVER_SIZE = 553_286
V45_DRIVER_SHA256 = "a9dc673d7430021fa4adf8eda7ed43f88e391d8655a0e11177975580697284e7"
V45_ACCEPTANCE_SIZE = 18_244
V45_ACCEPTANCE_SHA256 = "2411e6d825beafd56b9631a99c6dcb0681adcfca6e239ffef99b06b16cb811a1"
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

V45_CLOSURE = {
    "artifacts_created": [],
    "budgets": {
        "launch_boundary": "CLOSED_NO_REUSE",
        "popen": "NOT_CROSSED",
        "root": "NOT_CROSSED_ABANDONED_WITH_BOUNDARY",
        "transport": "NOT_INVOKED_ABANDONED_WITH_BOUNDARY",
    },
    "candidate_count": 28,
    "commands": {
        "argv": {"bytes": 21_235, "sha256": "58faf772455f49c35d93fc2a28711bbcad944166c1aec797535615d11afbc92e", "strings": 21},
        "clean_vector": {"bytes": 21_759, "sha256": "f5e36f0c75c9df7bd286d45bf335f8112de6a275414511a344571f674815ea7b", "strings": 31},
        "literal_payload": {"bytes": 20_484, "sha256": "5c3ac9acc65ba6448135e696f5bfcc9d990b539c71956516472874eed4de91bb", "tokens": 31},
        "outer_argv": {"bytes": 21_814, "sha256": "6cb8d4906639c4dbbe7826c005d7cfa426adabb794ca70a54746e78e6fc3a79c", "strings": 4},
    },
    "documents": {
        "execplan": {"size": 7_383_673, "sha256": "e74f6daaf2ebd62f50f1c24940523c5888064815b42a319b9a0c46d490ea6aa9"},
        "status": {"size": 256_364, "sha256": "5ff0f8bad0b1f99f5ecbef8aa7a2f4496b945dcc0264af17129cb9fb983178"},
    },
    "final_guard": {
        "chunks": ["a8f01e", "49058e"],
        "elapsed_seconds_approx": 8.716,
        "error": "RuntimeError: status identity mismatch",
        "exit_code": 1,
        "no_child_pid": True,
        "no_popen": True,
        "session": 19_177,
        "stderr": {"size": 113, "sha256": "c4810d4a5973d27962d91a79b60474facdfa230ed201f315ee5267d80359bd60"},
    },
    "forensic_boundary": "AD_HOC_SUPERVISOR_DUPLICATE_COMPARISON_FALSE_NEGATIVE_BEFORE_POPEN",
    "helper_path": str(LEGACY_HELPER),
    "identities": {
        "acceptance": {"size": V45_ACCEPTANCE_SIZE, "sha256": V45_ACCEPTANCE_SHA256},
        "driver": {"size": V45_DRIVER_SIZE, "sha256": V45_DRIVER_SHA256},
        "helper": {"size": LEGACY_HELPER_SIZE, "sha256": LEGACY_HELPER_SHA256},
        "writer": {"size": V45_WRITER_SIZE, "sha256": V45_WRITER_SHA256},
    },
    "inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 179},
    "preflight": {
        "chunks": ["7c3894", "066d01"],
        "exit_code": 0,
        "gate_count": 73,
        "result": "PASS",
        "session": 41_498,
        "snapshot": {"size": 1_098, "sha256": "d97150050b3cc78bc6574e60aa84c1d9dc91b5475c47995f929d8b87f01cf95e"},
    },
    "root": str(V45_ROOT),
    "root_absent": True,
    "status": "STOPPED_BEFORE_POPEN_NO_REUSE",
}


class FreezeError(RuntimeError):
    """Fail-closed V46 design or construction error."""


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
    require((len(payload), sha256(payload)) == (LEGACY_HELPER_SIZE, LEGACY_HELPER_SHA256), "V45 helper drift")
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v45_freeze", LEGACY_HELPER)
    require(spec is not None and spec.loader is not None, "V45 helper import spec failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _v45_validator() -> str:
    return '''
def validate_m3s_v45_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V45_CLOSURE
    inherited = validate_m3s_v44_stopped()
    helper = Path(closure["helper_path"])
    helper_identity = require_identity(helper, closure["identities"]["helper"]["sha256"], 0o644, closure["identities"]["helper"]["size"])
    root = Path(closure["root"])
    require(not root.exists() and not root.is_symlink(), "V45 abandoned root appeared")
    for name in ("successor-preparation-v45-result.json", "final-controller-acceptance-v45-result.json", "auth-handoff-v45-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V45 abandoned result appeared")
    preflight = closure["preflight"]
    guard = closure["final_guard"]
    require(preflight["result"] == "PASS" and preflight["gate_count"] == 73 and preflight["snapshot"]["size"] == 1098, "V45 preflight evidence mismatch")
    require(guard["exit_code"] == 1 and guard["no_popen"] is True and guard["no_child_pid"] is True, "V45 guard boundary mismatch")
    require(guard["error"] == "RuntimeError: status identity mismatch", "V45 guard error mismatch")
    require(closure["artifacts_created"] == [] and closure["status"] == "STOPPED_BEFORE_POPEN_NO_REUSE", "V45 stop semantics mismatch")
    return {"helper": helper_identity, "inherited_v44": inherited, "private_home_traversed": False, "result": "PASS", "status": closure["status"]}
'''


def derive_v45_driver() -> bytes:
    legacy = _load_legacy()
    v44, _ = read_regular(V44_DRIVER)
    require((len(v44), sha256(v44)) == (V44_DRIVER_SIZE, V44_DRIVER_SHA256), "sealed V44 driver mismatch")
    driver = legacy.derive_driver(v44)
    require((len(driver), sha256(driver)) == (V45_DRIVER_SIZE, V45_DRIVER_SHA256), "canonical V45 driver mismatch")
    return driver


def derive_driver(v45_bytes: bytes) -> bytes:
    require((len(v45_bytes), sha256(v45_bytes)) == (V45_DRIVER_SIZE, V45_DRIVER_SHA256), "accepted V45 driver mismatch")
    legacy = _load_legacy()
    v44 = legacy._load_legacy()
    editor = v44._load_legacy()._load_legacy()
    transform = editor._load_legacy()._load_legacy()
    original_text = v45_bytes.decode("utf-8")
    original_tree = ast.parse(original_text, filename="<accepted-v45-driver>")
    historical: dict[str, str] = {}
    for node in original_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("PREVIOUS_"):
            source = ast.get_source_segment(original_text, node)
            require(source is not None, "historical assignment source missing")
            historical[node.targets[0].id] = source
    text = original_text.replace("V46", "__M3S_FUTURE_UPPER__").replace("v46", "__m3s_future_lower__")
    text = text.replace("V45", "V46").replace("v45", "v46")
    text = text.replace("__M3S_FUTURE_UPPER__", "V47").replace("__m3s_future_lower__", "v47")
    require(text.count("range(46, 55)") == 1, "active-version range anchor mismatch")
    text = text.replace("range(46, 55)", "range(47, 55)", 1)
    for name, source in historical.items():
        text = editor._replace_assignment_source(text, name, source)
    require(text.count('current_result_name = "successor-preparation-v" + "45-result.json"') == 1, "current result anchor mismatch")
    text = text.replace('current_result_name = "successor-preparation-v" + "45-result.json"', 'current_result_name = "successor-preparation-v" + "46-result.json"', 1)
    require(text.count('future_result_name = "successor-preparation-v" + "46-result.json"') == 1, "future result anchor mismatch")
    text = text.replace('future_result_name = "successor-preparation-v" + "46-result.json"', 'future_result_name = "successor-preparation-v" + "47-result.json"', 1)

    constants = f"PREVIOUS_M3S_V45_CLOSURE = {V45_CLOSURE!r}\n"
    text = editor._insert_after_assignment(text, "PREVIOUS_M3S_V44_CLOSURE", constants)
    require(text.count("def validate_m3s_v44_stopped()") == 1, "V44 validator anchor mismatch")
    text = text.replace("def validate_m3s_v44_stopped()", _v45_validator().rstrip() + "\n\n\ndef validate_m3s_v44_stopped()", 1)
    gate_anchor = '        "m3s_v44_stopped": validate_m3s_v44_stopped(),'
    require(text.count(gate_anchor) == 1, "V44 gate anchor mismatch")
    text = text.replace(gate_anchor, '        "m3s_v45_stopped": validate_m3s_v45_stopped(),\n' + gate_anchor, 1)
    inventory_old = 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 179}, "original status counts mismatch")'
    require(text.count(inventory_old) == 1, "inventory anchor mismatch")
    text = text.replace(inventory_old, 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 180}, "original status counts mismatch")', 1)
    semantic_old = 'if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V44_CLOSURE):'
    require(text.count(semantic_old) == 1, "acceptance semantic anchor mismatch")
    text = text.replace(semantic_old, 'if canonical_json_model(value.get("predecessor_closure")) != canonical_json_model(PREVIOUS_M3S_V45_CLOSURE):', 1)

    contracts = transform.literal_assignment(text.encode(), "CONTROLLER_CONTRACTS")
    candidate = contracts["candidate_allocation"]
    candidate["expected_predecessors"] = list(sorted(EXPECTED_CANDIDATES, key=os.fsencode))
    candidate["predecessor_count"] = 28
    candidate["candidate_set_contract"]["preallocation"] = "exact 28 immutable predecessor names"
    candidate["candidate_set_contract"]["postallocation"] = "exact 28 predecessors plus one unpredictable current candidate"
    candidate["fresh_successor"] = {"candidate_suffix": "one unpredictable new suffix", "private_home_tmp": "fresh", "run_id": "fresh", "retained_candidates_reusable": False}
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = "checked-in-loop-engineering-policy-plus-v46-canonical-launch-derivation-thirteen-path-v39-policy-toolchain-binding"
    policy["pre_root_full_audit"] = {"allocation": False, "gate_count": 74, "home": str(V44_ROOT / "home"), "include_process_gate": True, "no_write_snapshot": True, "tmp": str(V44_ROOT / "tmp")}
    policy["controller_acceptance_semantics"] = {"model": "controller_acceptance_semantic_violations", "predecessor": "PREVIOUS_M3S_V45_CLOSURE", "rejects": ["V44", "missing", "mutated_v45", "extra_v45", "wrong_root"]}
    policy["canonical_launch_derivation"] = {"authority": "canonical_bundle", "duplicate_handwritten_identity": False, "precondition": "launch_precondition_comparison", "mutation_negatives": ["plan", "status", "helper", "writer", "driver", "acceptance", "argv", "vector", "payload", "outer"]}
    policy["historical_candidate_counts"]["recorded_counts"]["V45"] = 28
    if "V45" not in policy["historical_candidate_counts"]["current_live_total_not_consulted"]:
        policy["historical_candidate_counts"]["current_live_total_not_consulted"].append("V45")
    policy["bounded_tree_recovery"]["stopped_predecessor"] = "PREVIOUS_M3S_V45_CLOSURE"
    policy["bounded_tree_recovery"]["retained_candidate_reuse"] = False
    policy["bounded_tree_recovery"]["next_authentication_design"] = "fresh separately authorized M3A-v8 only after V46 final acceptance"
    trusted = contracts["trusted_context"]
    trusted["immediate_predecessor_design"] = {"closure": "PREVIOUS_M3S_V45_CLOSURE", "state": "STOPPED_BEFORE_POPEN_NO_REUSE"}
    trusted["context_required_bindings"] = ["complete V39 closure", "V43 formal stop", "V44 postacceptance closure", "V7 retained stop", "V45 pre-Popen stop", "exact 13-path Coder allowlist", "policy receipt and semantic hash", "sealed toolchain receipt and fingerprints", "literal external controller acceptance"]
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")


def inspect_driver(payload: bytes) -> dict[str, Any]:
    legacy = _load_legacy()
    transform = legacy._load_legacy()._load_legacy()._load_legacy()._load_legacy()._load_legacy()
    tree = ast.parse(payload, filename="<m3s-v46-driver>")
    compile(tree, "<m3s-v46-driver>", "exec")
    contracts = transform.literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = transform.literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_only_gates"]
    returns = [node for node in ast.walk(gate[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)] if len(gate) == 1 else []
    require(len(returns) == 1 and len(returns[0].value.keys) == 74, "gate count mismatch")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v46_static"}
    exec(compile(tree, "<m3s-v46-static>", "exec"), namespace)  # noqa: S102
    surface = {name: len(shape) for name, shape in namespace["SHAPES"].items()}
    require(surface == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    closure_cases = namespace["trusted_context_closure_self_test"]()
    recovery_cases = namespace["validate_v46_recovery_contract"]()
    link_cases = namespace["post_setup_link_safety_self_test"]()
    return_cases = namespace["post_setup_return_path_self_test"]()
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(all(candidate_cases.values()) and all(context_cases.values()), "driver fixture failed")
    require(all(closure_cases["fixtures"].values()), "trusted closure fixture failed")
    require(credential_cases["sanitized_baseline_count"] == 5, "credential fixture failed")
    require(all(recovery_cases["transport_fixtures"].values()), "source transport fixture failed")
    require(all(link_cases["fixtures"].values()) and all(return_cases["fixtures"].values()), "link-return fixture failed")
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    execute_node = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute"]
    mktemp = [node for node in ast.walk(execute_node[0]) if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/mktemp"] if len(execute_node) == 1 else []
    initializers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "initialize_and_bind_successor"]
    loop_init = [node for initializer in initializers for node in ast.walk(initializer) if isinstance(node, ast.List) and len(node.elts) >= 2 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make" and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "46-result.json"' in payload and b'future_result_name = "successor-preparation-v" + "47-result.json"' in payload, "current/future result mismatch")
    require(b'"safe_links": len(links)' not in payload and b'"safe_links": validated_post_setup_link_count(link_safety)' in payload, "link fix regressed")
    require(b'if name == "candidate.3Wlu7MyG":' in payload and b'immutable[name] = validate_m3s_v44_stopped()' in payload, "private-HOME omission branch missing")
    return {
        "ast_compile": "PASS", "candidate_set_cases": candidate_cases,
        "command_surface": surface, "context_cases": context_cases,
        "contracts": hashes, "credential_policy": credential_cases,
        "gate_count": 74, "link_safety": link_cases, "one_loop_init": True,
        "one_mktemp": True, "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"},
        "post_setup_return_runtime": return_cases, "source_transport": recovery_cases["transport_fixtures"],
        "trusted_closure": closure_cases, "result": "PASS",
    }


def extract_source(plan_bytes: bytes) -> bytes:
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def writer_source(helper_payload: bytes) -> bytes:
    helper_size = len(helper_payload)
    helper_sha = sha256(helper_payload)
    return f'''import hashlib\nimport importlib.util\nimport os\nimport stat\nimport sys\nfrom pathlib import Path\n\npath = Path({str(HELPER)!r})\ninfo = path.lstat()\nif not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size != {helper_size}:\n    raise RuntimeError("V46 helper identity mismatch")\nfd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)\ntry:\n    payload = b""\n    while True:\n        chunk = os.read(fd, 1048576)\n        if not chunk:\n            break\n        payload += chunk\nfinally:\n    os.close(fd)\nif hashlib.sha256(payload).hexdigest() != {helper_sha!r}:\n    raise RuntimeError("V46 helper hash mismatch")\nspec = importlib.util.spec_from_file_location("liveclip_m3s_v46_root", path)\nif spec is None or spec.loader is None:\n    raise RuntimeError("V46 helper loader unavailable")\nmodule = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\nmodule.root_dispatch(sys.argv[2:])\n'''.encode("utf-8")


def build_acceptance(driver_bytes: bytes, *, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, helper_bytes: bytes) -> bytes:
    legacy = _load_legacy()
    transform = legacy._load_legacy()._load_legacy()._load_legacy()._load_legacy()._load_legacy()
    contracts = transform.literal_assignment(driver_bytes, "CONTROLLER_CONTRACTS")
    hashes = transform.literal_assignment(driver_bytes, "CONTROLLER_CONTRACT_HASHES")
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
        "phase": "M3S_V46_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V45_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "legacy_helper": {"path": str(LEGACY_HELPER), "sha256": LEGACY_HELPER_SHA256, "size": LEGACY_HELPER_SIZE},
            "requirements": {
                "v2": {"path": str(REQUIREMENT_V2), "sha256": REQUIREMENT_V2_SHA256, "size": REQUIREMENT_V2_SIZE},
                "v3": {"path": str(REQUIREMENT_V3), "sha256": REQUIREMENT_V3_SHA256, "size": REQUIREMENT_V3_SIZE},
            },
            "accepted_v45_driver": {"sha256": V45_DRIVER_SHA256, "size": V45_DRIVER_SIZE},
            "sha256": sha256(source_bytes), "size": len(source_bytes),
        },
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": transform.literal_assignment(driver_bytes, "CONTROLLER_ROOT_BINDING"),
        "seed": {
            "head": transform.literal_assignment(driver_bytes, "HEAD"),
            "manifest_sha256": transform.literal_assignment(driver_bytes, "MANIFEST_SHA"),
            "patch_sha256": transform.literal_assignment(driver_bytes, "PATCH_SHA"),
            "path_list_sha256": transform.literal_assignment(driver_bytes, "LIST_SHA"),
        },
    }
    return compact(value) + b"\n"


def expected_environment() -> dict[str, str]:
    return {
        "HOME": str(ROOT / "home"), "TMPDIR": str(ROOT / "tmp"),
        "PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1", "GIT_OPTIONAL_LOCKS": "0",
        "__CF_USER_TEXT_ENCODING": CF_USER_TEXT_ENCODING,
    }


def git_status_bytes(repo: Path = DELIVERY) -> bytes:
    result = subprocess.run(
        ["/usr/bin/git", "status", "--short", "--untracked-files=all"],
        cwd=repo,
        env={"PATH": PATH_VALUE, "LANG": "C", "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0"},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
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
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 180}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    v2 = require_file(REQUIREMENT_V2, REQUIREMENT_V2_SIZE, REQUIREMENT_V2_SHA256)
    v3 = require_file(REQUIREMENT_V3, REQUIREMENT_V3_SIZE, REQUIREMENT_V3_SHA256)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V46 root appeared")
    require(not V45_ROOT.exists() and not V45_ROOT.is_symlink(), "abandoned V45 root appeared")
    return {"architecture": architecture, "candidates_sha256": sha256(compact(candidates)), "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)}, "git_status_sha256": sha256(status_payload), "inventory": counts, "requirements": {"v2": v2, "v3": v3}, "v45_root_absent": True, "v46_root_absent": True}


def full_pre_root_audit(driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v46-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v46_audit"}
    exec(compile(tree, "<m3s-v46-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V46 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v44_substitution", namespace["PREVIOUS_M3S_V44_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["final_guard"]["exit_code"] = 0
    negatives["mutated_v45"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v45"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 45}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(all(negatives[name] == ["predecessor_closure"] for name in ("v44_substitution", "missing", "mutated_v45", "extra_v45")) and negatives["wrong_root"] == ["root"], "V46 acceptance negative accepted")
    values = {"base": str(BASE), "seed": str(SEED), "plan": str(PLAN), "expected_plan_sha256": sha256(plan_bytes), "status": str(STATUS), "expected_status_sha256": sha256(status_bytes)}
    saved_environment = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](values, V44_ROOT / "home", V44_ROOT / "tmp", include_process_gate=True)
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 74, "full pre-root gate count mismatch")
    require(gates["m3s_v45_stopped"]["result"] == "PASS", "V45 closure gate failed")
    require(gates["m3s_v44_stopped"]["result"] == "PASS", "V44 closure gate failed")
    require(gates["m3a_v7_stopped"]["result"] == "PASS", "V7 stop gate failed")
    require(gates["post_setup_link_safety"]["result"] == "PASS" and gates["post_setup_return_path"]["result"] == "PASS", "link gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION" and len(gates["predecessors"]["candidate_names"]) == 28, "preallocation state mismatch")
    after_plan, _ = read_regular(PLAN)
    after_status, _ = read_regular(STATUS)
    after = audit_snapshot(after_plan, after_status)
    require(after == before, "full pre-root audit wrote or changed protected state")
    return {"acceptance_negatives": negatives, "gate_count": len(gates), "gates": {name: "PASS" for name in gates}, "no_write": {"before": before, "after": after, "result": "PASS"}, "result": "PASS"}


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def phase_arguments(phase: str, *, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, driver_bytes: bytes, helper_bytes: bytes, acceptance: bytes) -> list[str]:
    common = [
        "--plan", str(PLAN), "--expected-plan-sha256", sha256(plan_bytes),
        "--status", str(STATUS), "--expected-status-sha256", sha256(status_bytes),
        "--expected-source-sha256", sha256(source_bytes), "--expected-driver-sha256", sha256(driver_bytes),
        "--expected-helper-sha256", sha256(helper_bytes),
    ]
    if phase == "transport":
        return [phase, *common, "--controller-acceptance-json", acceptance.decode("utf-8").rstrip("\n")]
    if phase == "self-check":
        return [phase, *common, "--expected-controller-acceptance-sha256", sha256(acceptance)]
    require(phase == "finalize", "unknown V46 root phase")
    static = inspect_driver(driver_bytes)
    return [phase, *common, "--expected-controller-acceptance-sha256", sha256(acceptance), "--expected-self-check-sha256", sha256(self_check_payload(plan_bytes, status_bytes, helper_bytes, driver_bytes, acceptance, static)), "--expected-writer-self-test-sha256", sha256(writer_test_payload())]


def command_identity(argv: list[str]) -> dict[str, Any]:
    argv_payload = compact(argv)
    env = expected_environment()
    order = ("HOME", "TMPDIR", "PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE", "GIT_OPTIONAL_LOCKS", "__CF_USER_TEXT_ENCODING")
    vector = ["/usr/bin/env", "-i", *(f"{name}={env[name]}" for name in order), *argv]
    vector_payload = compact(vector)
    payload = "exec " + " ".join(shell_quote(value) for value in vector) + " </dev/null"
    outer = ["/bin/zsh", "-f", "-c", payload]
    return {
        "argv": {"bytes": len(argv_payload), "sha256": sha256(argv_payload), "strings": len(argv)},
        "clean_vector": {"bytes": len(vector_payload), "sha256": sha256(vector_payload), "strings": len(vector)},
        "literal_payload": {"bytes": len(payload.encode()), "sha256": sha256(payload.encode()), "tokens": len(vector)},
        "outer_argv": {"bytes": len(compact(outer)), "sha256": sha256(compact(outer)), "strings": len(outer)},
        "schema": [], "values": {"argv": argv, "outer": outer},
    }


def command_identities(*, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, driver_bytes: bytes, helper_bytes: bytes, acceptance: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for phase in ("transport", "self-check", "finalize"):
        args = phase_arguments(phase, plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source_bytes, driver_bytes=driver_bytes, helper_bytes=helper_bytes, acceptance=acceptance)
        argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode(), "--", *args]
        result[phase] = command_identity(argv)
        result[phase]["schema"] = [args[0], *args[1::2]]
    return result


def canonical_bundle(plan_bytes: bytes, status_bytes: bytes, helper_bytes: bytes) -> dict[str, Any]:
    source = writer_source(helper_bytes)
    v45 = derive_v45_driver()
    driver = derive_driver(v45)
    acceptance = build_acceptance(driver, plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source, helper_bytes=helper_bytes)
    commands = command_identities(plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source, driver_bytes=driver, helper_bytes=helper_bytes, acceptance=acceptance)
    return {"acceptance": acceptance, "commands": commands, "driver": driver, "helper": helper_bytes, "plan": plan_bytes, "source": source, "status": status_bytes, "v45_driver": v45}


def identity(value: bytes) -> dict[str, Any]:
    return {"bytes": len(value), "sha256": sha256(value)}


def launch_precondition_comparison(bundle: dict[str, Any], observed: dict[str, Any]) -> bool:
    canonical = {
        "plan": identity(bundle["plan"]), "status": identity(bundle["status"]),
        "helper": identity(bundle["helper"]), "writer": identity(bundle["source"]),
        "driver": identity(bundle["driver"]), "acceptance": identity(bundle["acceptance"]),
        "commands": {phase: {name: data[name] for name in ("argv", "clean_vector", "literal_payload", "outer_argv")} for phase, data in bundle["commands"].items()},
    }
    return observed == canonical


def launch_precondition_self_test(bundle: dict[str, Any]) -> dict[str, Any]:
    observed = {
        "plan": identity(bundle["plan"]), "status": identity(bundle["status"]),
        "helper": identity(bundle["helper"]), "writer": identity(bundle["source"]),
        "driver": identity(bundle["driver"]), "acceptance": identity(bundle["acceptance"]),
        "commands": {phase: {name: data[name] for name in ("argv", "clean_vector", "literal_payload", "outer_argv")} for phase, data in bundle["commands"].items()},
    }
    require(launch_precondition_comparison(bundle, observed), "canonical launch comparison rejected")
    negatives: dict[str, bool] = {}
    for label in ("plan", "status", "helper", "writer", "driver", "acceptance"):
        changed = copy.deepcopy(observed)
        changed[label]["sha256"] = "0" * 64
        negatives[label] = not launch_precondition_comparison(bundle, changed)
    for label, phase, field in (("argv", "transport", "argv"), ("vector", "self-check", "clean_vector"), ("payload", "finalize", "literal_payload"), ("outer", "transport", "outer_argv")):
        changed = copy.deepcopy(observed)
        changed["commands"][phase][field]["sha256"] = "0" * 64
        negatives[label] = not launch_precondition_comparison(bundle, changed)
    require(all(negatives.values()), "canonical launch negative accepted")
    return {"negative_count": len(negatives), "negatives": negatives, "result": "PASS"}


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


def parse_phase(argv: list[str]) -> tuple[str, dict[str, str]]:
    require(argv, "missing V46 root phase")
    phase = argv[0]
    require(phase in {"transport", "self-check", "finalize"}, "V46 root phase mismatch")
    require(len(argv[1:]) % 2 == 0, "V46 root argument shape mismatch")
    values = dict(zip(argv[1::2], argv[2::2], strict=True))
    expected = {"--plan", "--expected-plan-sha256", "--status", "--expected-status-sha256", "--expected-source-sha256", "--expected-driver-sha256", "--expected-helper-sha256"}
    if phase == "transport":
        expected.add("--controller-acceptance-json")
    else:
        expected.add("--expected-controller-acceptance-sha256")
    if phase == "finalize":
        expected.update({"--expected-self-check-sha256", "--expected-writer-self-test-sha256"})
    require(set(values) == expected, "V46 root argument schema mismatch")
    return phase, values


def phase_context(values: dict[str, str]) -> tuple[bytes, bytes, bytes, bytes, bytes, dict[str, Any]]:
    require(values.get("--plan") == str(PLAN) and values.get("--status") == str(STATUS), "document path mismatch")
    plan, _ = read_regular(PLAN)
    status, _ = read_regular(STATUS)
    helper, _ = read_regular(HELPER)
    require(sha256(plan) == values.get("--expected-plan-sha256"), "plan argument mismatch")
    require(sha256(status) == values.get("--expected-status-sha256"), "status argument mismatch")
    require(sha256(helper) == values.get("--expected-helper-sha256"), "helper argument mismatch")
    bundle = canonical_bundle(plan, status, helper)
    source = bundle["source"]
    driver = bundle["driver"]
    acceptance = bundle["acceptance"]
    require(extract_source(plan) == source, "embedded writer source mismatch")
    require(sha256(source) == values.get("--expected-source-sha256"), "source argument mismatch")
    require(sha256(driver) == values.get("--expected-driver-sha256"), "driver argument mismatch")
    require(launch_precondition_self_test(bundle)["result"] == "PASS", "canonical launch precondition proof failed")
    return plan, status, helper, source, driver, {"acceptance": acceptance, "bundle": bundle, "static": inspect_driver(driver)}


def source_receipt_payload(helper: bytes, source: bytes, driver: bytes) -> bytes:
    return compact({"driver_sha256": sha256(driver), "driver_size": len(driver), "format_version": 1, "helper_sha256": sha256(helper), "helper_size": len(helper), "phase": "M3S_V46_SOURCE_TRANSPORT", "result": "PASS", "source_sha256": sha256(source), "source_size": len(source)}) + b"\n"


def writer_test_payload() -> bytes:
    return compact({"phase": "M3S_V46_WRITER_SELF_TEST", "result": "PASS"}) + b"\n"


def self_check_payload(plan: bytes, status: bytes, helper: bytes, driver: bytes, acceptance: bytes, static: dict[str, Any]) -> bytes:
    return compact({"acceptance_sha256": sha256(acceptance), "canonical_launch_derivation": "PASS", "documents": {"plan_sha256": sha256(plan), "status_sha256": sha256(status)}, "driver_sha256": sha256(driver), "format_version": 1, "gate_count": 74, "helper_sha256": sha256(helper), "phase": "M3S_V46_SELF_CHECK", "result": "PASS", "static": static}) + b"\n"


def final_index_payload(plan: bytes, status: bytes, helper: bytes, source: bytes, driver: bytes, acceptance: bytes) -> bytes:
    commands = command_identities(plan_bytes=plan, status_bytes=status, source_bytes=source, driver_bytes=driver, helper_bytes=helper, acceptance=acceptance)
    return compact({"controller_acceptance_sha256": sha256(acceptance), "documents": {"plan_sha256": sha256(plan), "status_sha256": sha256(status)}, "driver_sha256": sha256(driver), "format_version": 1, "phase": "M3S_V46_FINAL_INDEX", "phase_argv_sha256": {name: value["argv"]["sha256"] for name, value in commands.items()}, "source_sha256": sha256(source), "verdict": "M3S_V46_READY_FOR_CONTROLLER_REVIEW"}) + b"\n"


def validate_root_layout(receipt_names: set[str]) -> None:
    for path in (ROOT, ROOT / "home", ROOT / "tmp", RECEIPTS):
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), "unsafe V46 root directory")
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700, "V46 root directory mode mismatch")
    require(set(os.listdir(ROOT)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V46 root entries mismatch")
    require(not os.listdir(ROOT / "home") and not os.listdir(ROOT / "tmp"), "V46 root private directories changed")
    require(set(os.listdir(RECEIPTS)) == receipt_names, "V46 root receipt domain mismatch")


def transport_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V46 root exists")
    supplied = values.get("--controller-acceptance-json", "").encode() + b"\n"
    require(supplied == derived["acceptance"], "controller acceptance transport mismatch")
    audit = full_pre_root_audit(driver, supplied, plan, status)
    require(audit["gate_count"] == 74 and audit["no_write"]["result"] == "PASS", "pre-root audit mismatch")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    write_exclusive(DRIVER, driver)
    write_exclusive(RECEIPTS / "controller-acceptance-v46.json", supplied)
    write_exclusive(RECEIPTS / "source-receipt.json", source_receipt_payload(helper, source, driver))
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    return {"phase": "M3S_V46_ROOT_TRANSPORT", "result": "PASS"}


def self_check_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values)
    validate_root_layout({"controller-acceptance-v46.json", "source-receipt.json"})
    require_file(DRIVER, len(driver), sha256(driver), 0o600)
    acceptance = derived["acceptance"]
    require_file(RECEIPTS / "controller-acceptance-v46.json", len(acceptance), sha256(acceptance), 0o600)
    require(values.get("--expected-controller-acceptance-sha256") == sha256(acceptance), "acceptance argument mismatch")
    expected_source = source_receipt_payload(helper, source, driver)
    require_file(RECEIPTS / "source-receipt.json", len(expected_source), sha256(expected_source), 0o600)
    write_exclusive(RECEIPTS / "writer-self-test.json", writer_test_payload())
    write_exclusive(RECEIPTS / "self-check-result.json", self_check_payload(plan, status, helper, driver, acceptance, derived["static"]))
    fsync_directory(RECEIPTS)
    return {"phase": "M3S_V46_ROOT_SELF_CHECK", "result": "PASS"}


def finalize_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values)
    validate_root_layout({"controller-acceptance-v46.json", "source-receipt.json", "writer-self-test.json", "self-check-result.json"})
    acceptance = derived["acceptance"]
    expected_self = self_check_payload(plan, status, helper, driver, acceptance, derived["static"])
    expected_writer = writer_test_payload()
    require(values.get("--expected-controller-acceptance-sha256") == sha256(acceptance), "acceptance final argument mismatch")
    require(values.get("--expected-self-check-sha256") == sha256(expected_self), "self-check final argument mismatch")
    require(values.get("--expected-writer-self-test-sha256") == sha256(expected_writer), "writer-test final argument mismatch")
    require_file(RECEIPTS / "self-check-result.json", len(expected_self), sha256(expected_self), 0o600)
    require_file(RECEIPTS / "writer-self-test.json", len(expected_writer), sha256(expected_writer), 0o600)
    final_index = write_exclusive(RECEIPTS / "final-index.json", final_index_payload(plan, status, helper, source, driver, acceptance))
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    return {"final_index": final_index, "phase": "M3S_V46_ROOT_FINALIZE", "result": "M3S_V46_READY_FOR_CONTROLLER_REVIEW"}


def root_dispatch(argv: list[str]) -> None:
    phase, values = parse_phase(argv)
    output = {"transport": transport_phase, "self-check": self_check_phase, "finalize": finalize_phase}[phase](values)
    os.write(1, compact(output) + b"\n")


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
