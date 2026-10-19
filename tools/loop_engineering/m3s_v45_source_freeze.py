"""Deterministic M3S-v45 trust-recovery source-freeze/root-only helper.

This Trusted-Main-only helper derives V45 from the immutable sealed V44
driver. It binds the complete accepted V44 root/preparation/final/auth/formal
stop, repairs only the candidate-local trusted-record provenance contract,
runs the allocation-free pre-root graph, and may create only the fixed V45
root. Importing it is read-only.
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
V44_CANDIDATE = BASE / "candidate.3Wlu7MyG"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v45"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v45_source_freeze.py"
LEGACY_HELPER = DELIVERY / "tools/loop_engineering/m3s_v44_source_freeze.py"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V45_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V45_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
V44_DRIVER_SIZE = 538_746
V44_DRIVER_SHA256 = "d6d2141d37275259491ea79bbef10d12d1cd02d4152bf6505a3c273986ccf850"
LEGACY_HELPER_SIZE = 60_428
LEGACY_HELPER_SHA256 = "dbca295b37576ada70096481055fb3dbc9e67f269d15b76ff8203ad55e87a119"
ARCHITECTURE_SIZE = 66_116
ARCHITECTURE_SHA256 = "48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce"
REQUIREMENT_V2_SIZE = 8_771
REQUIREMENT_V2_SHA256 = "31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400"
REQUIREMENT_V3_SIZE = 12_289
REQUIREMENT_V3_SHA256 = "308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00"
POST_SETUP_LINK_COUNT = 103
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

V44_ROOT_FILES = {
    "candidate-driver.py": (538_746, V44_DRIVER_SHA256),
    "receipts/controller-acceptance-v44.json": (18_147, "c573fcdb80d07d9bd320cfd0ad0141206675b2b6ced3b34e55212ab50ba76626"),
    "receipts/source-receipt.json": (524, "6ca3814d8490701e8105a021301644e139872d06bad0eebb7c247e7bc698831d"),
    "receipts/writer-self-test.json": (72, "2152b25df8eb1201f681037632107a92a665d81b1c9b47058ca81148930298cd"),
    "receipts/self-check-result.json": (7_012, "a14df6d41caf7d062258efc873f4c666f68a4e5be842e5d4a0a1b64778f785ac"),
    "receipts/final-index.json": (2_000, "1f44d31dec228076da80768ec87d493860c82bfc14248db678d2e4a1a9df6ca5"),
    "receipts/successor-preparation-v44-result.json": (23_851, "ba1b1878ad5e940ac145aa14b48e5621ea4b824dc73b6d8fccd6913a90c8546e"),
}
V44_CANDIDATE_FILES = {
    "successor-receipts/successor-v44-controller-acceptance-offer.json": (5_801, "100c87a96d06970939e2c0cdb1ccd6d7777bbf1eb8d4426f780bc6c181053dd8"),
    "successor-receipts/successor-v44-policy-snapshot.json": (4_828, "162392f08256d8acb8ffb488b981f80e33035a0e96b615cd1583a1201a39baf2"),
    "successor-receipts/successor-v44-preparation-bindings.json": (5_414, "b15134f22f25bb216a07c66fab39639b54f67f726ef414ab17a3926c5a3fb7ab"),
    "successor-receipts/successor-v44-trusted-context.json": (12_088, "c9a355391dc998e63d4b9cfc5fe5d669b86db0658b604be1383c930c2926cc87"),
    "successor-receipts/successor-v44-toolchain-snapshot.json": (4_878, "bef168bb6289b53ea0c03611dd4e565503f50b3938232d2d615c4724114ab8f5"),
    "successor-receipts/final-receipt-index.json": (18_096, "4afaf3c7819498433cb5263c0c60ab6c97c1ca6f3c731c2fd73c90cad4051fbc"),
    "successor-receipts/postacceptance-final-index.json": (2_731, "10591eed8097571f8662b9a3ad05aeb0164aeebf2682610b4bd72bd317b07150"),
    "successor-receipts/postacceptance-repository-manifest.jsonl": (6_146_003, "373c4fd19ff20ca1932222a8cb26cbb3e726fea441444ea91a27cf15cf6a1f93"),
    "successor-receipts/postacceptance-attempt-manifest.jsonl": (12_183_983, "f476ba94207b25161551f773a90436d4d6c325d6dcd238c63b3ec108c870fe0d"),
    "successor-receipts/successor-v44-controller-acceptance-transport.json": (1_383, "b8a7d265dd77eb1171c97e3fd270bd000d09992169e6340788c5b16e8a433b28"),
    "repo/.loop/trusted/final-controller-acceptance-v44.json": (5_132, "0baec92ac199860c9811b9516e8edc3a2ea11ffd73a8dce175ab832cc2dc67f4"),
}
V7_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v7"
V7_ROOT_FILES = {
    "handoff-driver.py": (31_666, "d4a0fb12e65ebdfdad8295cac03eb8468c3a7569b517bdb309a40006b2bb64cb"),
    "receipts/controller-acceptance-v7.json": (1_230, "561b5729698cf91cf93440d3b927500bd2bfb9aef9c65a03cc7f96f7c9dbb1b1"),
    "receipts/source-receipt.json": (432, "894b598cae2418cc1a3ebf0bc7427182f71f9562d27a084a8b82e56d0f5396f6"),
    "receipts/writer-self-test.json": (84, "156b8186ccfc23de06d15001820172ec43cb3cf0ddc389bcb28c79c7d5dc6370"),
    "receipts/self-check-result.json": (1_201, "3c2c31b860ede8f40b3980e9a3ed6b6b8b84e5a9c982b49a6d7b13b90c49d099"),
    "receipts/final-index.json": (669, "9bd7be45d263b950b11018e10604246a04a6c2ca35efe133542fa5e850b0bc26"),
}
V44_RUN_ID = "20261016T010806Z-b7f48207"
V44_CANDIDATE = BASE / "candidate.3Wlu7MyG"
V44_RUN = V44_CANDIDATE / "repo/.loop/runs" / V44_RUN_ID
V44_RUN_FILES = {
    "state.json": (12_796, "88f7be523d08def41b8abf3ff6be418b90d4955c1c9c1edf8a29396a0a739af2"),
    "events.jsonl": (144, "f3b0b329f25891455f9e00377e8eaa02f185fa569131cc347de0fa54b7e43439"),
}
CODER_ALLOWLIST = (
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
V44_CLOSURE = {
    "budgets": {
        "authentication": "CONSUMED_FAILED_NO_REUSE",
        "authentication_destination": "SEALED_POSSIBLY_CONSUMED_NO_PROBE",
        "authentication_result": "UNCONSUMED_ABANDONED_WITH_AUTHORITY",
        "final_acceptance": "CONSUMED_NO_REUSE",
        "formal": "UNCONSUMED",
        "init": "CONSUMED_NO_REUSE",
        "prepare": "CONSUMED_NO_REUSE",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "CONSUMED_NO_REUSE",
    },
    "candidate": {
        "name": "candidate.3Wlu7MyG",
        "inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 74},
        "postacceptance_final_index_sha256": "10591eed8097571f8662b9a3ad05aeb0164aeebf2682610b4bd72bd317b07150",
        "run_id": V44_RUN_ID,
    },
    "candidate_count": 28,
    "delivery_inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 178},
    "authentication_stop": {
        "chunk": "20f0c4",
        "pid": 37_540,
        "driver_returncode": 1,
        "wrapper_returncode": 96,
        "elapsed_seconds": 0.08915825001895428,
        "timed_out": False,
        "output_truncated": False,
        "stdout": {"size": 0, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
        "stderr": {"size": 0, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
        "sanitized_result": "ABSENT",
        "forensic_boundary": "ROOT_ACCEPTANCE_SCHEMA_MISMATCH_BEFORE_PRIVATE_RUNTIME_AND_CREDENTIAL_ACCESS",
        "schema_differences": {
            "controller_acceptance_extra": ["writer"],
            "controller_acceptance_missing": ["source"],
            "final_index_extra": ["phase_argv_sha256", "writer_sha256"],
            "final_index_missing": ["root_argv_sha256", "source_sha256"],
        },
    },
    "handoff_documents": {
        "execplan": {"size": 7_376_720, "sha256": "007b93547a6c91ed50c6201525b0aaacaa1a1865639939818494f8845c67dc64"},
        "status": {"size": 254_794, "sha256": "149fdd9abe08da073f97ea224d8d378f43e0c9e6366442e7066d91341b40c12b"},
    },
    "policy": {"receipt_sha256": "162392f08256d8acb8ffb488b981f80e33035a0e96b615cd1583a1201a39baf2"},
    "toolchain": {"receipt_sha256": "bef168bb6289b53ea0c03611dd4e565503f50b3938232d2d615c4724114ab8f5", "source_fingerprint": "4cd808c9048436ac4cd024856e3453cb0d1abff8c53837747a62d287f0540e4f", "snapshot_fingerprint": "f294e0001a1af9b0d1c2cdc5c92afc4d9cf1ed10271cffed8205db62236b98e0"},
    "trusted_record": {"receipt_sha256": "c9a355391dc998e63d4b9cfc5fe5d669b86db0658b604be1383c930c2926cc87", "authority_state": "EXTERNAL_CONTROLLER_ACCEPTANCE_RECEIPT_REQUIRED"},
    "root": str(V44_ROOT),
    "root_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V44_ROOT_FILES.items()},
    "candidate_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V44_CANDIDATE_FILES.items()},
    "run_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V44_RUN_FILES.items()},
    "v7_root": str(V7_ROOT),
    "v7_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V7_ROOT_FILES.items()},
}


class FreezeError(RuntimeError):
    """Fail-closed V45 design or construction error."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FreezeError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def read_regular(path: Path, maximum: int = 32 * 1024 * 1024) -> tuple[bytes, os.stat_result]:
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
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v44_freeze", LEGACY_HELPER)
    require(spec is not None and spec.loader is not None, "legacy helper import spec failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



def _return_path_functions() -> str:
    return '''
def validated_post_setup_link_count(link_safety: dict[str, Any]) -> int:
    require(set(link_safety) == {"expected_link_count", "link_count", "unsafe_states", "violations"}, "post-setup link result schema mismatch")
    require(link_safety["expected_link_count"] == POST_SETUP_LINK_COUNT, "post-setup expected link count mismatch")
    require(link_safety["link_count"] == POST_SETUP_LINK_COUNT, "post-setup validated link count mismatch")
    require(link_safety["unsafe_states"] == [] and link_safety["violations"] == [], "post-setup unsafe link result")
    return link_safety["link_count"]


def post_setup_return_path_self_test() -> dict[str, Any]:
    exact = post_setup_link_safety_model(POST_SETUP_LINK_COUNT, ())
    fixtures = {"exact_103_zero_unsafe": validated_post_setup_link_count(exact) == POST_SETUP_LINK_COUNT}
    negatives = {
        "stale_102": post_setup_link_safety_model(102, ()),
        "extra_104": post_setup_link_safety_model(104, ()),
        "broken": post_setup_link_safety_model(103, ("broken",)),
        "external": post_setup_link_safety_model(103, ("external",)),
        "missing_field": {"expected_link_count": 103, "link_count": 103, "unsafe_states": []},
    }
    for label, value in negatives.items():
        try:
            validated_post_setup_link_count(value)
        except RuntimeError:
            fixtures[label + "_reject"] = True
        else:
            fixtures[label + "_reject"] = False
    require(all(fixtures.values()), "post-setup return-path fixture mismatch")
    return {"fixtures": fixtures, "result": "PASS", "safe_links": POST_SETUP_LINK_COUNT}
'''


def _v44_validator() -> str:
    return '''
def validate_m3s_v44_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V44_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V44 root entries mismatch")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V44 private root drift")
    expected_root_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_root_receipts, "V44 root receipt set mismatch")
    root_files = {
        name: require_identity(root / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["root_files"].items()
    }
    candidate = BASE / closure["candidate"]["name"]
    private_directory_identity(candidate)
    private_directory_identity(candidate / "successor-receipts")
    private_directory_identity(candidate / "tmp")
    repo = candidate / "repo"
    require(repo.is_dir() and not repo.is_symlink(), "unsafe V44 candidate repository")
    candidate_files = {
        name: require_identity(candidate / name, value["sha256"], 0o644 if name.endswith(("state.json", "events.jsonl")) else 0o600, value["size"])
        for name, value in closure["candidate_files"].items()
    }
    require(status_counts(repo) == closure["candidate"]["inventory"], "V44 candidate inventory mismatch")
    run_id = closure["candidate"]["run_id"]
    run = repo / ".loop/runs" / run_id
    run_files = {
        name: require_identity(run / name, value["sha256"], 0o644, value["size"])
        for name, value in closure["run_files"].items()
    }
    state, _ = load_json(run / "state.json")
    require(
        state["run_id"] == run_id
        and state["state"] == "received"
        and state["cycle"] == 0
        and state["code_cycle"] == 0
        and state["coder_session_id"] is None
        and state["last_error"] is None
        and state["artifacts"] == {}
        and state["command_results"] == [],
        "V44 pristine run mismatch",
    )
    v7 = Path(closure["v7_root"])
    for path in (v7, v7 / "home", v7 / "tmp", v7 / "receipts"):
        private_directory_identity(path)
    require(not os.listdir(v7 / "home") and not os.listdir(v7 / "tmp"), "V7 root private directories drift")
    expected_v7_receipts = {name.split("/", 1)[1] for name in closure["v7_files"] if name.startswith("receipts/")}
    require(set(os.listdir(v7 / "receipts")) == expected_v7_receipts, "V7 receipt set mismatch")
    v7_files = {
        name: require_identity(v7 / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["v7_files"].items()
    }
    v7_result = v7 / "receipts/auth-handoff-v7-result.json"
    require(not v7_result.exists() and not v7_result.is_symlink(), "V7 sanitized result appeared")
    for name in ("final-controller-acceptance-v44-result.json", "auth-handoff-v44-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V44 reserved root result appeared")
    require(closure["candidate_count"] == 28, "V44 recorded candidate count mismatch")
    stop = closure["authentication_stop"]
    require(
        stop["driver_returncode"] == 1
        and stop["wrapper_returncode"] == 96
        and stop["stdout"]["size"] == 0
        and stop["stderr"]["size"] == 0
        and stop["sanitized_result"] == "ABSENT",
        "V7 retained terminal evidence mismatch",
    )
    return {
        "candidate_files": candidate_files,
        "forensic_boundary": stop["forensic_boundary"],
        "private_home_traversed": False,
        "result": "PASS",
        "root_files": root_files,
        "run_files": run_files,
        "v7_files": v7_files,
    }


def validate_m3a_v7_stopped() -> dict[str, Any]:
    closure = validate_m3s_v44_stopped()
    require(closure["private_home_traversed"] is False, "V7 private-HOME boundary violated")
    require(closure["forensic_boundary"] == "ROOT_ACCEPTANCE_SCHEMA_MISMATCH_BEFORE_PRIVATE_RUNTIME_AND_CREDENTIAL_ACCESS", "V7 forensic boundary mismatch")
    return {
        "forensic_boundary": closure["forensic_boundary"],
        "private_home_traversed": False,
        "result": "PASS",
        "v7_files": closure["v7_files"],
    }
'''
def derive_driver(v44_bytes: bytes) -> bytes:
    require((len(v44_bytes), sha256(v44_bytes)) == (V44_DRIVER_SIZE, V44_DRIVER_SHA256), "sealed V44 driver mismatch")
    legacy = _load_legacy()
    editor = legacy._load_legacy()._load_legacy()
    transform = editor._load_legacy()._load_legacy()
    original_text = v44_bytes.decode("utf-8")
    original_tree = ast.parse(original_text, filename="<sealed-v44-driver>")
    historical: dict[str, str] = {}
    for node in original_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("PREVIOUS_"):
            source = ast.get_source_segment(original_text, node)
            require(source is not None, "historical assignment source missing")
            historical[node.targets[0].id] = source
    text = original_text.replace("V45", "__M3S_FUTURE_UPPER__").replace("v45", "__m3s_future_lower__")
    text = text.replace("V44", "V45").replace("v44", "v45")
    text = text.replace("__M3S_FUTURE_UPPER__", "V46").replace("__m3s_future_lower__", "v46")
    require(text.count("range(45, 55)") == 1, "active-version range anchor mismatch")
    text = text.replace("range(45, 55)", "range(46, 55)", 1)
    for name, source in historical.items():
        text = editor._replace_assignment_source(text, name, source)
    require(text.count('current_result_name = "successor-preparation-v" + "44-result.json"') == 1, "current result anchor mismatch")
    text = text.replace('current_result_name = "successor-preparation-v" + "44-result.json"', 'current_result_name = "successor-preparation-v" + "45-result.json"', 1)
    require(text.count('future_result_name = "successor-preparation-v" + "45-result.json"') == 1, "future result anchor mismatch")
    text = text.replace('future_result_name = "successor-preparation-v" + "45-result.json"', 'future_result_name = "successor-preparation-v" + "46-result.json"', 1)
    require('current_result_name = "successor-preparation-v" + "45-result.json"' in text, "current result fixture mismatch")
    require('future_result_name = "successor-preparation-v" + "46-result.json"' in text, "future result fixture mismatch")

    constants = (
        f"PREVIOUS_M3S_V44_CLOSURE = {V44_CLOSURE!r}\n"
        f"V44_RETAINED_CANDIDATE = Path({str(V44_CANDIDATE)!r})\n"
        f"V44_RETAINED_CANDIDATE_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V44_CANDIDATE_FILES.items()}!r}\n"
        f"V44_RUN_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V44_RUN_FILES.items()}!r}\n"
        f"V7_ROOT_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V7_ROOT_FILES.items()}!r}\n"
    )
    text = editor._insert_after_assignment(text, "PREVIOUS_M3S_V43_CLOSURE", constants)

    predecessor_anchor = 'PREDECESSORS["candidate.CbYcDirN"] = (0, 0, "0" * 64, "a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8")'
    require(text.count(predecessor_anchor) == 1, "V44 predecessor anchor mismatch")
    text = text.replace(predecessor_anchor, predecessor_anchor + '\nPREDECESSORS["candidate.3Wlu7MyG"] = (0, 0, "0" * 64, "10591eed8097571f8662b9a3ad05aeb0164aeebf2682610b4bd72bd317b07150")', 1)
    omission_anchor = 'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.CbYcDirN"] = 1'
    require(text.count(omission_anchor) == 1, "V44 omission anchor mismatch")
    text = text.replace(omission_anchor, omission_anchor + '\nPREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.3Wlu7MyG"] = 1', 1)

    omission_old = '''    explicitly_validated = {"candidate.CbYcDirN"}
    require(sum(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS.values()) == 4 and all(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS[name] == 1 for name in sanitized | explicitly_validated), "credential omission count fixture mismatch")
    require(set(SANITIZED_PROTECTED_PREDECESSOR_BASELINES) == sanitized, "sanitized baseline domain mismatch")
    require(all(PREDECESSORS[name][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES[name] for name in sanitized), "sanitized predecessor baseline mismatch")
    return {"negative_fixture_count": len(negatives), "protected_path_count": 1, "sanitized_baseline_count": 4, "result": "PASS"}'''
    omission_new = '''    explicitly_validated = {"candidate.CbYcDirN", "candidate.3Wlu7MyG"}
    require(sum(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS.values()) == 5 and all(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS[name] == 1 for name in sanitized | explicitly_validated), "credential omission count fixture mismatch")
    require(set(SANITIZED_PROTECTED_PREDECESSOR_BASELINES) == sanitized, "sanitized baseline domain mismatch")
    require(all(PREDECESSORS[name][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES[name] for name in sanitized), "sanitized predecessor baseline mismatch")
    return {"negative_fixture_count": len(negatives), "protected_path_count": 1, "sanitized_baseline_count": 5, "result": "PASS"}'''
    require(text.count(omission_old) == 1, "credential omission fixture anchor mismatch")
    text = text.replace(omission_old, omission_new, 1)

    loop_anchor = '    for name, (count, regular_bytes, current_sha, historical_sha) in PREDECESSORS.items():\n        if name == "candidate.CbYcDirN":'
    require(text.count(loop_anchor) == 1, "predecessor loop anchor mismatch")
    text = text.replace(loop_anchor, '    for name, (count, regular_bytes, current_sha, historical_sha) in PREDECESSORS.items():\n        if name == "candidate.3Wlu7MyG":\n            immutable[name] = validate_m3s_v44_stopped()\n            continue\n        if name == "candidate.CbYcDirN":', 1)
    require(text.count("def validate_m3s_v43_stopped()") == 1, "V43 validator anchor mismatch")
    text = text.replace("def validate_m3s_v43_stopped()", _v44_validator().rstrip() + "\n\n\ndef validate_m3s_v43_stopped()", 1)
    gate_anchor = '        "m3s_v43_stopped": validate_m3s_v43_stopped(),'
    require(text.count(gate_anchor) == 1, "V43 gate anchor mismatch")
    text = text.replace(gate_anchor, '        "m3s_v44_stopped": validate_m3s_v44_stopped(),\n        "m3a_v7_stopped": validate_m3a_v7_stopped(),\n' + gate_anchor, 1)

    inventory_old = 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 177}, "original status counts mismatch")'
    require(text.count(inventory_old) == 1, "original inventory anchor mismatch")
    text = text.replace(inventory_old, 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 179}, "original status counts mismatch")', 1)
    require(text.count('PREVIOUS_M3S_V43_CLOSURE["formal"]') == 3, "trusted-context predecessor anchors mismatch")
    text = text.replace('PREVIOUS_M3S_V43_CLOSURE["formal"]', 'PREVIOUS_M3S_V44_CLOSURE')
    semantic_anchor = "canonical_json_model(PREVIOUS_M3S_V43_CLOSURE)"
    require(text.count(semantic_anchor) == 1, "controller acceptance predecessor anchor mismatch")
    text = text.replace(semantic_anchor, "canonical_json_model(PREVIOUS_M3S_V44_CLOSURE)", 1)

    contracts = transform.literal_assignment(text.encode(), "CONTROLLER_CONTRACTS")
    expected = tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode))
    candidate = contracts["candidate_allocation"]
    candidate["expected_predecessors"] = list(expected)
    candidate["predecessor_count"] = 28
    candidate["candidate_set_contract"]["preallocation"] = "exact 28 immutable predecessor names"
    candidate["candidate_set_contract"]["postallocation"] = "exact 28 predecessors plus one unpredictable current candidate"
    candidate["fresh_successor"] = {"candidate_suffix": "one unpredictable new suffix", "private_home_tmp": "fresh", "run_id": "fresh", "retained_candidates_reusable": False}
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = "checked-in-loop-engineering-policy-plus-v45-current-external-trust-closure-thirteen-path-v39-policy-toolchain-binding"
    policy["pre_root_full_audit"] = {"allocation": False, "gate_count": 73, "home": str(V44_ROOT / "home"), "include_process_gate": True, "no_write_snapshot": True, "tmp": str(V44_ROOT / "tmp")}
    policy["controller_acceptance_semantics"] = {"model": "controller_acceptance_semantic_violations", "predecessor": "PREVIOUS_M3S_V44_CLOSURE", "rejects": ["V43", "missing", "mutated_v44", "extra_v44", "wrong_root"]}
    recorded = policy["historical_candidate_counts"]["recorded_counts"]
    recorded["V44"] = 28
    not_consulted = policy["historical_candidate_counts"]["current_live_total_not_consulted"]
    if "V44" not in not_consulted:
        not_consulted.append("V44")
    recovery = policy["bounded_tree_recovery"]
    recovery["terminal_predecessor"] = "PREVIOUS_M3S_V39_CLOSURE"
    recovery["handoff_stop_predecessor"] = "PREVIOUS_M3S_V44_CLOSURE"
    recovery["retained_candidate_reuse"] = False
    recovery["next_authentication_design"] = "fresh separately authorized M3A-v8 only"
    trusted = contracts["trusted_context"]
    trusted["immediate_predecessor"] = {"candidate": "candidate.3Wlu7MyG", "closure": "PREVIOUS_M3S_V44_CLOSURE", "authentication": "CONSUMED_FAILED_NO_REUSE", "root": str(V44_ROOT), "run_id": V44_RUN_ID}
    trusted["immediate_predecessor_design"] = {"closure": "PREVIOUS_M3S_V44_CLOSURE", "state": "V7_PRE_RECEIPT_ROOT_SCHEMA_MISMATCH_NO_REUSE"}
    trusted["context_required_bindings"] = ["complete V39 closure", "V43 formal stop", "V44 postacceptance closure", "V7 retained stop", "exact 13-path Coder allowlist", "policy receipt and semantic hash", "sealed toolchain receipt and fingerprints", "literal external controller acceptance"]
    trusted["authentication_boundary"] = "later fresh M3A-v8 design and exact operator authority"
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")
def _post_setup_ast_proof(tree: ast.Module) -> dict[str, Any]:
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "post_setup"]
    require(len(matches) == 1, "post_setup AST function mismatch")
    function = matches[0]
    assigned = {
        target.id
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    bad_links_load = [node for node in ast.walk(function) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id == "links"]
    safe_values = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "safe_links":
                safe_values.append(value)
    require("link_safety" in assigned and not bad_links_load and len(safe_values) == 1, "post_setup undefined-name proof failed")
    value = safe_values[0]
    require(
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "validated_post_setup_link_count"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
        and value.args[0].id == "link_safety",
        "post_setup safe-links return path mismatch",
    )
    return {"assigned_link_safety": True, "undefined_links_loads": 0, "validated_return_call": True, "result": "PASS"}


def inspect_driver(payload: bytes) -> dict[str, Any]:
    legacy = _load_legacy()
    transform = legacy._load_legacy()._load_legacy()._load_legacy()._load_legacy()
    tree = ast.parse(payload, filename="<m3s-v45-driver>")
    compile(tree, "<m3s-v45-driver>", "exec")
    contracts = transform.literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = transform.literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_only_gates"]
    returns = [node for node in ast.walk(gate[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)] if len(gate) == 1 else []
    require(len(returns) == 1 and len(returns[0].value.keys) == 73, "gate count mismatch")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v45_static"}
    exec(compile(tree, "<m3s-v45-static>", "exec"), namespace)  # noqa: S102
    surface = {name: len(shape) for name, shape in namespace["SHAPES"].items()}
    require(surface == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    closure_cases = namespace["trusted_context_closure_self_test"]()
    recovery_cases = namespace["validate_v45_recovery_contract"]()
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
    require(b'current_result_name = "successor-preparation-v" + "45-result.json"' in payload and b'future_result_name = "successor-preparation-v" + "46-result.json"' in payload, "current/future result mismatch")
    require(b'"safe_links": len(links)' not in payload and b'"safe_links": validated_post_setup_link_count(link_safety)' in payload, "V44 link fix regressed")
    require(b'"policy"' in payload and b'"trusted_context": legacy["context"]' in payload and b'"trusted_context_receipt": legacy["context_receipt"]' in payload, "external acceptance binding missing")
    require(b'if name == "candidate.3Wlu7MyG":' in payload and b'immutable[name] = validate_m3s_v44_stopped()' in payload, "V44/V7 private-HOME omission branch missing")
    ast_proof = _post_setup_ast_proof(tree)
    return {
        "ast_compile": "PASS",
        "candidate_set_cases": candidate_cases,
        "command_surface": surface,
        "context_cases": context_cases,
        "contracts": hashes,
        "credential_policy": credential_cases,
        "gate_count": 73,
        "link_safety": link_cases,
        "one_loop_init": True,
        "one_mktemp": True,
        "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"},
        "post_setup_return_ast": ast_proof,
        "post_setup_return_runtime": return_cases,
        "private_home_policy": "V44/V7 explicit non-secret evidence only; no candidate-private HOME traversal",
        "source_transport": recovery_cases["transport_fixtures"],
        "trusted_closure": closure_cases,
        "result": "PASS",
    }



def extract_source(plan_bytes: bytes) -> bytes:
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def writer_source(helper_payload: bytes) -> bytes:
    helper_size = len(helper_payload)
    helper_sha = sha256(helper_payload)
    return f'''import hashlib\nimport importlib.util\nimport os\nimport stat\nimport sys\nfrom pathlib import Path\n\npath = Path({str(HELPER)!r})\ninfo = path.lstat()\nif not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size != {helper_size}:\n    raise RuntimeError("V45 helper identity mismatch")\nfd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)\ntry:\n    payload = b""\n    while True:\n        chunk = os.read(fd, 1048576)\n        if not chunk:\n            break\n        payload += chunk\nfinally:\n    os.close(fd)\nif hashlib.sha256(payload).hexdigest() != {helper_sha!r}:\n    raise RuntimeError("V45 helper hash mismatch")\nspec = importlib.util.spec_from_file_location("liveclip_m3s_v45_root", path)\nif spec is None or spec.loader is None:\n    raise RuntimeError("V45 helper loader unavailable")\nmodule = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\nmodule.root_dispatch(sys.argv[2:])\n'''.encode("utf-8")


def build_acceptance(driver_bytes: bytes, *, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, helper_bytes: bytes) -> bytes:
    transform = _load_legacy()._load_legacy()._load_legacy()._load_legacy()._load_legacy()
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
        "phase": "M3S_V45_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V44_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "legacy_helper": {"path": str(LEGACY_HELPER), "sha256": LEGACY_HELPER_SHA256, "size": LEGACY_HELPER_SIZE},
            "requirements": {
                "v2": {"path": str(REQUIREMENT_V2), "sha256": REQUIREMENT_V2_SHA256, "size": REQUIREMENT_V2_SIZE},
                "v3": {"path": str(REQUIREMENT_V3), "sha256": REQUIREMENT_V3_SHA256, "size": REQUIREMENT_V3_SIZE},
            },
            "sealed_v44_driver": {"path": str(V44_DRIVER), "sha256": V44_DRIVER_SHA256, "size": V44_DRIVER_SIZE},
            "sha256": sha256(source_bytes),
            "size": len(source_bytes),
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
        "HOME": str(ROOT / "home"),
        "TMPDIR": str(ROOT / "tmp"),
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
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 179}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    v2 = require_file(REQUIREMENT_V2, REQUIREMENT_V2_SIZE, REQUIREMENT_V2_SHA256)
    v3 = require_file(REQUIREMENT_V3, REQUIREMENT_V3_SIZE, REQUIREMENT_V3_SHA256)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V45 root appeared")
    return {"architecture": architecture, "candidates_sha256": sha256(compact(candidates)), "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)}, "git_status_sha256": sha256(status_payload), "inventory": counts, "requirements": {"v2": v2, "v3": v3}, "v45_root_absent": True}


def full_pre_root_audit(driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v45-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v45_audit"}
    exec(compile(tree, "<m3s-v45-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V45 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v43_substitution", namespace["PREVIOUS_M3S_V43_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["authentication_stop"]["elapsed_seconds"] = 0.08
    negatives["mutated_v44"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v44"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 42}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(all(negatives[name] == ["predecessor_closure"] for name in ("v43_substitution", "missing", "mutated_v44", "extra_v44")) and negatives["wrong_root"] == ["root"], "V45 acceptance negative accepted")
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
    require(len(gates) == 73, "full pre-root gate count mismatch")
    require(gates["v45_recovery_contract"]["result"] == "PASS", "recovery gate failed")
    require(gates["m3s_v44_stopped"]["result"] == "PASS", "V44 closure gate failed")
    require(gates["m3a_v7_stopped"]["result"] == "PASS", "V7 stop gate failed")
    require(gates["post_setup_link_safety"]["result"] == "PASS", "link-safety gate failed")
    require(gates["post_setup_return_path"]["result"] == "PASS", "return-path gate failed")
    require(gates["trusted_context_closure"]["result"] == "PASS", "trusted-context closure gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION" and len(gates["predecessors"]["candidate_names"]) == 28, "preallocation state mismatch")
    after_plan, _ = read_regular(PLAN)
    after_status, _ = read_regular(STATUS)
    after = audit_snapshot(after_plan, after_status)
    require(after == before, "full pre-root audit wrote or changed protected state")
    return {"acceptance_negatives": negatives, "gate_count": len(gates), "gates": {name: "PASS" for name in gates}, "no_write": {"before": before, "after": after, "result": "PASS"}, "result": "PASS"}


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def phase_arguments(
    phase: str,
    *,
    plan_bytes: bytes,
    status_bytes: bytes,
    source_bytes: bytes,
    driver_bytes: bytes,
    helper_bytes: bytes,
    acceptance: bytes,
) -> list[str]:
    common = [
        "--plan", str(PLAN),
        "--expected-plan-sha256", sha256(plan_bytes),
        "--status", str(STATUS),
        "--expected-status-sha256", sha256(status_bytes),
        "--expected-source-sha256", sha256(source_bytes),
        "--expected-driver-sha256", sha256(driver_bytes),
        "--expected-helper-sha256", sha256(helper_bytes),
    ]
    if phase == "transport":
        return [phase, *common, "--controller-acceptance-json", acceptance.decode("utf-8").rstrip("\n")]
    if phase == "self-check":
        return [phase, *common, "--expected-controller-acceptance-sha256", sha256(acceptance)]
    require(phase == "finalize", "unknown V45 root phase")
    static = inspect_driver(driver_bytes)
    return [
        phase,
        *common,
        "--expected-controller-acceptance-sha256", sha256(acceptance),
        "--expected-self-check-sha256", sha256(self_check_payload(plan_bytes, status_bytes, helper_bytes, driver_bytes, acceptance, static)),
        "--expected-writer-self-test-sha256", sha256(writer_test_payload()),
    ]


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
        "literal_payload": {"bytes": len(payload.encode("utf-8")), "sha256": sha256(payload.encode("utf-8")), "tokens": len(vector)},
        "outer_argv": {"bytes": len(compact(outer)), "sha256": sha256(compact(outer)), "strings": len(outer)},
        "schema": [],
    }


def command_identities(
    *,
    plan_bytes: bytes,
    status_bytes: bytes,
    source_bytes: bytes,
    driver_bytes: bytes,
    helper_bytes: bytes,
    acceptance: bytes,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for phase in ("transport", "self-check", "finalize"):
        args = phase_arguments(
            phase,
            plan_bytes=plan_bytes,
            status_bytes=status_bytes,
            source_bytes=source_bytes,
            driver_bytes=driver_bytes,
            helper_bytes=helper_bytes,
            acceptance=acceptance,
        )
        argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), "--", *args]
        result[phase] = command_identity(argv)
        result[phase]["schema"] = [args[0], *args[1::2]]
        result[phase]["values"] = {"argv": argv, "outer": ["/bin/zsh", "-f", "-c", "exec " + " ".join(shell_quote(value) for value in ["/usr/bin/env", "-i", *(f"{name}={expected_environment()[name]}" for name in ("HOME", "TMPDIR", "PATH", "LANG", "LC_ALL", "PYTHONDONTWRITEBYTECODE", "GIT_OPTIONAL_LOCKS", "__CF_USER_TEXT_ENCODING")), *argv]) + " </dev/null"]}
    return result
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
    require(argv, "missing V45 root phase")
    phase = argv[0]
    require(phase in {"transport", "self-check", "finalize"}, "V45 root phase mismatch")
    require(len(argv[1:]) % 2 == 0, "V45 root argument count mismatch")
    values: dict[str, str] = {}
    for index in range(1, len(argv), 2):
        key = argv[index]
        require(key.startswith("--") and key not in values, "V45 root argument schema mismatch")
        values[key] = argv[index + 1]
    return phase, values


def phase_context(values: dict[str, str]) -> tuple[bytes, bytes, bytes, bytes, bytes, dict[str, Any]]:
    require(os.getuid() == CURRENT_UID and Path.cwd() == SEED, "root-only process context mismatch")
    require(dict(os.environ) == expected_environment(), "root-only environment mismatch")
    helper_bytes, _ = read_regular(HELPER)
    plan_bytes, _ = read_regular(PLAN)
    status_bytes, _ = read_regular(STATUS)
    require(sha256(plan_bytes) == values.get("--expected-plan-sha256"), "plan hash mismatch")
    require(sha256(status_bytes) == values.get("--expected-status-sha256"), "status hash mismatch")
    require(sha256(helper_bytes) == values.get("--expected-helper-sha256"), "helper hash mismatch")
    source_bytes = writer_source(helper_bytes)
    require(sha256(source_bytes) == values.get("--expected-source-sha256"), "writer source hash mismatch")
    require(extract_source(plan_bytes) == source_bytes, "embedded writer source mismatch")
    v44_bytes, _ = read_regular(V44_DRIVER)
    driver_bytes = derive_driver(v44_bytes)
    require(sha256(driver_bytes) == values.get("--expected-driver-sha256"), "derived driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(
        driver_bytes,
        plan_bytes=plan_bytes,
        status_bytes=status_bytes,
        source_bytes=source_bytes,
        helper_bytes=helper_bytes,
    )
    return plan_bytes, status_bytes, helper_bytes, source_bytes, driver_bytes, {"acceptance": acceptance, "static": static}


def source_receipt_payload(helper_bytes: bytes, source_bytes: bytes, driver_bytes: bytes) -> bytes:
    return compact({
        "driver_sha256": sha256(driver_bytes),
        "format_version": 1,
        "helper_sha256": sha256(helper_bytes),
        "phase": "M3S_V45_SOURCE_RECEIPT",
        "pre_root_audit": {"allocation": False, "gate_count": 73, "no_write": "PASS"},
        "result": "PASS",
        "source_sha256": sha256(source_bytes),
    }) + b"\n"


def writer_test_payload() -> bytes:
    return compact({"format_version": 1, "phase": "M3S_V45_WRITER_SELF_TEST", "result": "PASS"}) + b"\n"


def self_check_payload(
    plan_bytes: bytes,
    status_bytes: bytes,
    helper_bytes: bytes,
    driver_bytes: bytes,
    acceptance: bytes,
    static: dict[str, Any],
) -> bytes:
    return compact({
        "controller_acceptance_sha256": sha256(acceptance),
        "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)},
        "driver_sha256": sha256(driver_bytes),
        "format_version": 1,
        "helper_sha256": sha256(helper_bytes),
        "phase": "M3S_V45_SELF_CHECK",
        "result": "PASS",
        "security": {"authentication_access": False, "candidate_private_home_traversed": False, "formal_authority": False},
        "static": static,
    }) + b"\n"


def final_index_payload(
    plan_bytes: bytes,
    status_bytes: bytes,
    helper_bytes: bytes,
    source_bytes: bytes,
    driver_bytes: bytes,
    acceptance: bytes,
) -> bytes:
    commands = command_identities(
        plan_bytes=plan_bytes,
        status_bytes=status_bytes,
        source_bytes=source_bytes,
        driver_bytes=driver_bytes,
        helper_bytes=helper_bytes,
        acceptance=acceptance,
    )
    return compact({
        "controller_acceptance_sha256": sha256(acceptance),
        "documents": {"plan_sha256": sha256(plan_bytes), "status_sha256": sha256(status_bytes)},
        "driver_sha256": sha256(driver_bytes),
        "format_version": 1,
        "phase": "M3S_V45_FINAL_INDEX",
        "phase_argv_sha256": {name: value["argv"]["sha256"] for name, value in commands.items()},
        "source_sha256": sha256(source_bytes),
        "verdict": "M3S_V45_READY_FOR_CONTROLLER_REVIEW",
    }) + b"\n"


def validate_root_layout(receipt_names: set[str]) -> None:
    for path in (ROOT, ROOT / "home", ROOT / "tmp", RECEIPTS):
        info = path.lstat()
        require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(), "unsafe V45 root directory")
        require(info.st_uid == CURRENT_UID and stat.S_IMODE(info.st_mode) == 0o700, "V45 root directory mode mismatch")
    require(set(os.listdir(ROOT)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V45 root entries mismatch")
    require(not os.listdir(ROOT / "home") and not os.listdir(ROOT / "tmp"), "V45 root private directories changed")
    require(set(os.listdir(RECEIPTS)) == receipt_names, "V45 root receipt domain mismatch")


def transport_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V45 root exists")
    supplied = values.get("--controller-acceptance-json", "").encode("utf-8") + b"\n"
    require(supplied == derived["acceptance"], "controller acceptance transport mismatch")
    audit = full_pre_root_audit(driver, supplied, plan, status)
    require(audit["gate_count"] == 73 and audit["no_write"]["result"] == "PASS", "pre-root audit mismatch")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    write_exclusive(DRIVER, driver)
    write_exclusive(RECEIPTS / "controller-acceptance-v45.json", supplied)
    write_exclusive(RECEIPTS / "source-receipt.json", source_receipt_payload(helper, source, driver))
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    return {"phase": "M3S_V45_ROOT_TRANSPORT", "result": "PASS"}


def self_check_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values)
    validate_root_layout({"controller-acceptance-v45.json", "source-receipt.json"})
    require_file(DRIVER, len(driver), sha256(driver), 0o600)
    acceptance = derived["acceptance"]
    require_file(RECEIPTS / "controller-acceptance-v45.json", len(acceptance), sha256(acceptance), 0o600)
    require(values.get("--expected-controller-acceptance-sha256") == sha256(acceptance), "acceptance argument mismatch")
    expected_source = source_receipt_payload(helper, source, driver)
    require_file(RECEIPTS / "source-receipt.json", len(expected_source), sha256(expected_source), 0o600)
    write_exclusive(RECEIPTS / "writer-self-test.json", writer_test_payload())
    write_exclusive(RECEIPTS / "self-check-result.json", self_check_payload(plan, status, helper, driver, acceptance, derived["static"]))
    fsync_directory(RECEIPTS)
    return {"phase": "M3S_V45_ROOT_SELF_CHECK", "result": "PASS"}


def finalize_phase(values: dict[str, str]) -> dict[str, Any]:
    plan, status, helper, source, driver, derived = phase_context(values)
    validate_root_layout({"controller-acceptance-v45.json", "source-receipt.json", "writer-self-test.json", "self-check-result.json"})
    acceptance = derived["acceptance"]
    expected_self = self_check_payload(plan, status, helper, driver, acceptance, derived["static"])
    expected_writer = writer_test_payload()
    require(values.get("--expected-controller-acceptance-sha256") == sha256(acceptance), "acceptance final argument mismatch")
    require(values.get("--expected-self-check-sha256") == sha256(expected_self), "self-check final argument mismatch")
    require(values.get("--expected-writer-self-test-sha256") == sha256(expected_writer), "writer-test final argument mismatch")
    require_file(RECEIPTS / "self-check-result.json", len(expected_self), sha256(expected_self), 0o600)
    require_file(RECEIPTS / "writer-self-test.json", len(expected_writer), sha256(expected_writer), 0o600)
    payload = final_index_payload(plan, status, helper, source, driver, acceptance)
    final_index = write_exclusive(RECEIPTS / "final-index.json", payload)
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    return {"final_index": final_index, "phase": "M3S_V45_ROOT_FINALIZE", "result": "M3S_V45_READY_FOR_CONTROLLER_REVIEW"}


def root_dispatch(argv: list[str]) -> None:
    phase, values = parse_phase(argv)
    handlers = {"transport": transport_phase, "self-check": self_check_phase, "finalize": finalize_phase}
    output = handlers[phase](values)
    os.write(1, compact(output) + b"\n")
if __name__ == "__main__":
    raise FreezeError("helper is import-only")
