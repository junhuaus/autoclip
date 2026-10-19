"""Deterministic M3S-v44 trust-recovery source-freeze/root-only helper.

This Trusted-Main-only helper derives V44 from the immutable sealed V43
driver. It binds the complete accepted V43 root/preparation/final/auth/formal
stop, repairs only the candidate-local trusted-record provenance contract,
runs the allocation-free pre-root graph, and may create only the fixed V44
root. Importing it is read-only.
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
V43_ROOT = BASE / "trusted-tools/m3-successor-preparation-v43"
V43_DRIVER = V43_ROOT / "candidate-driver.py"
V43_CANDIDATE = BASE / "candidate.CbYcDirN"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v44"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v44_source_freeze.py"
LEGACY_HELPER = DELIVERY / "tools/loop_engineering/m3s_v43_source_freeze.py"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V44_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V44_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
V43_DRIVER_SIZE = 517_933
V43_DRIVER_SHA256 = "fa0f4340fdc5ae7093b807bd43c17d3f9a8c4f8efbe1f0bd57a249bee87814bc"
LEGACY_HELPER_SIZE = 48_825
LEGACY_HELPER_SHA256 = "482f3266f0d4775114dd4c496733470b3bf9839bda61a635b96ab810a4f60750"
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
)

V43_ROOT_FILES = {
    "candidate-driver.py": (517_933, V43_DRIVER_SHA256),
    "receipts/controller-acceptance-v43.json": (17_249, "b0ac531ff708d8c117e10efc79e1caa33925c4608a93dbd267e9f665654cde05"),
    "receipts/source-receipt.json": (524, "11208485b7c4184eafd32e380080c9efc001cbaaa67ccec7962695e873cbb405"),
    "receipts/writer-self-test.json": (72, "847b63ac13ae5f1ccae504fe9f244ded36253e9f30a261f34509f38a8f9d69f2"),
    "receipts/self-check-result.json": (6_546, "47d7a55206b83e77f0f25871e674904be1a322801f8a1e8a6d0c94b02d31e05f"),
    "receipts/final-index.json": (2_000, "dc1cfdd133dc05e8d197ddc61c653e43e7e8326c9ea920574d26465f3b66e4e4"),
    "receipts/successor-preparation-v43-result.json": (23_850, "7c2cf6fe2bff1be5a6369f79aae65ae85c2e96046d4335d77241c92fc4e8b7b3"),
}
V43_CANDIDATE_FILES = {
    "successor-receipts/successor-v43-controller-acceptance-offer.json": (5_032, "95c783319e2f11b2b666d40a93e36ffdba3a484f38ddcc5b8075b9a24615ff48"),
    "successor-receipts/successor-v43-policy-snapshot.json": (4_827, "47034cf37bd9e4dd9ce1764c909a36a692d9fee2288006105de99337d1ebd7ab"),
    "successor-receipts/successor-v43-trusted-context.json": (4_227, "a7dfbf10610016990c08fadc091007bae24a8bc4eaa690f984d974a5a2bf3e0c"),
    "successor-receipts/successor-v43-toolchain-snapshot.json": (4_878, "1942f05fc5686652004bb18842418ebd337d9dfaf53515319915e00a2782543d"),
    "successor-receipts/final-receipt-index.json": (18_095, "fc54928088059a084f0c998bac7b96addca4713b7c2d41c6cc13eb0c3477b0d3"),
    "successor-receipts/postacceptance-final-index.json": (2_731, "a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8"),
    "successor-receipts/postacceptance-repository-manifest.jsonl": (6_146_002, "cdf949a84656807f9a538fca3d9fe45647a7fcf26246c651fd8db3a85a9e596e"),
    "successor-receipts/postacceptance-attempt-manifest.jsonl": (12_183_981, "d657dd1f513b3a982fef52517355f845cbc7d6b135700d481e12b5b29ec45031"),
    "repo/.loop/trusted/final-controller-acceptance-v43.json": (3_913, "8e92f8d63142313e70be4a15add0538e0e13a9e406cfcfc6f7e792ab5682a42a"),
    "repo/config/loop-engineering/trusted-context/liveclip-agent-runtime-v2-successor-v2.json": (3_485, "698e1a6d7be3d8d886aabb3a1b8c0c326d268ef319cd3d48e5ec8ea8ef466983"),
}
V6_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v6"
V6_ROOT_FILES = {
    "handoff-driver.py": (31_499, "20c4c9afcba559625b0185308eb1a88844fc78fbc2bafe4e34adf8540e041a68"),
    "receipts/controller-acceptance-v6.json": (1_272, "73c2c980d7b432b4c8be97ebffdb1ee36e11a683e36cb19ac77a5d24ed174ee5"),
    "receipts/source-receipt.json": (432, "57d36f93936ed03cab10bacfdac250ac62c0d5f2e382c1820916deba42508aee"),
    "receipts/writer-self-test.json": (84, "c239260588d420779d8e22b803779a2784a468d91cab664ab062774aab923d29"),
    "receipts/self-check-result.json": (2_917, "a206c1095fd58833f5fab882ecfa21f61684d4a5ea522212ecf2461e11d295ec"),
    "receipts/final-index.json": (475, "6f4a9e53970769876c6576e5d84cf45295e340b8a30661905bfe4302d842faeb"),
    "receipts/auth-handoff-v6-result.json": (261, "def12fc3c49b6016013291557e8b9c2171b63e97f2c0c5c6bd06556961b94bf4"),
}
V43_RUN_ID = "20261015T231933Z-6eee7fff"
V43_CANDIDATE = BASE / "candidate.CbYcDirN"
V43_RUN = V43_CANDIDATE / "repo/.loop/runs" / V43_RUN_ID
V43_FORMAL_FILES = {
    "state.json": (12_992, "f61c8a6eb0eacf2e6f04a05d46f7c77d8c61565582ae7a7f913f7cc2aec02c4b"),
    "events.jsonl": (2_056, "bb172c73a5bd151e2b6b71c990d388460f225ecc2ae17ae3bb1b67715cd4d4c1"),
    "artifacts/planner/001.json": (11_143, "efd893e7287a3c78426096279e066d9ef85619f1d95e47950b03b80f7fb7465c"),
    "artifacts/planner/002.json": (12_005, "76b6f040f9a993a3fdd65f8519d9301aeef1a21ec66b801c88ff632f2a2f5869"),
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
V43_CLOSURE = {
    "budgets": {
        "authentication": "CONSUMED_NO_REUSE",
        "final_acceptance": "CONSUMED_NO_REUSE",
        "formal": "CONSUMED_STOPPED_NO_REUSE",
        "init": "CONSUMED_NO_REUSE",
        "prepare": "CONSUMED_NO_REUSE",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "CONSUMED_NO_REUSE",
    },
    "candidate": {
        "name": "candidate.CbYcDirN",
        "inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 74},
        "postacceptance_final_index_sha256": "a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8",
        "run_id": V43_RUN_ID,
    },
    "candidate_count": 27,
    "delivery_inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 176},
    "formal": {
        "session": 53_627,
        "chunks": ["3fa762", "f69db8", "59b1f8", "5b5c07", "8c9a69", "13dbcf", "75c517", "087e07"],
        "pid": 80_564,
        "returncode": 2,
        "elapsed_seconds": 214.122168416,
        "timed_out": False,
        "output_truncated": False,
        "stdout": {"size": 12_992, "sha256": "6dccd2f0a0caa4247ea904799ae2817a23295c6ba32754601e2e3af6353c0459"},
        "stderr": {"size": 29, "sha256": "6c061b4cc7a28f0ded4346994615b1c0f93dfb978ad9d40db3578a6196a2c822"},
        "state": "blocked",
        "cycle": 2,
        "code_cycle": 0,
        "coder_session_id": None,
        "last_error": "plan repair budget exhausted",
        "planner_sessions": ["01a14212-7d99-7d90-bc8e-1e81e958b84c", "01a14214-04b6-7fe3-8102-479d154d63d4"],
        "planner_verdicts": ["NEEDS_INPUT", "NEEDS_INPUT"],
        "defect": "candidate-local trusted record lacks current externally accepted closure, exact thirteen-path allowlist, and sealed policy/toolchain binding",
    },
    "formal_dispatch_documents": {
        "execplan": {"size": 7_314_422, "sha256": "609b299d5343aa2e3d50b995b6b19bcf7ca1dae9a72cea5d4875e1f3c56cb5a8"},
        "status": {"size": 235_843, "sha256": "099e5307674f780d87b3be4c9391d7a191cb42bece7f60279351ab18d10f8f61"},
    },
    "policy": {"receipt_sha256": "47034cf37bd9e4dd9ce1764c909a36a692d9fee2288006105de99337d1ebd7ab", "semantic_sha256": "42e336af0cede32572d865a93ec3ac43748a8e1b8f0cee34e306ca8c5b61bc99"},
    "toolchain": {"receipt_sha256": "1942f05fc5686652004bb18842418ebd337d9dfaf53515319915e00a2782543d", "source_fingerprint": "35956ed8f635694bd8e13e5d905c4dd02edf5fa7a4a7efba37838499dde172e3", "snapshot_fingerprint": "6d5498032da72fa665092b63d5ee681671e474fb16ca4c7282789960c38f5434"},
    "trusted_record": {"sha256": "698e1a6d7be3d8d886aabb3a1b8c0c326d268ef319cd3d48e5ec8ea8ef466983", "receipt_sha256": "a7dfbf10610016990c08fadc091007bae24a8bc4eaa690f984d974a5a2bf3e0c", "authority_state": "EXTERNAL_CONTROLLER_ACCEPTANCE_RECEIPT_REQUIRED"},
    "root": str(V43_ROOT),
    "root_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V43_ROOT_FILES.items()},
    "candidate_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V43_CANDIDATE_FILES.items()},
    "formal_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V43_FORMAL_FILES.items()},
    "v6_root": str(V6_ROOT),
    "v6_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V6_ROOT_FILES.items()},
}


class FreezeError(RuntimeError):
    """Fail-closed V44 design or construction error."""


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
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v43_freeze", LEGACY_HELPER)
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


def _v43_validator() -> str:
    return '''
def validate_m3s_v43_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V43_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V43 root entries mismatch")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V43 private root drift")
    expected_root_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_root_receipts, "V43 root receipt set mismatch")
    root_files = {
        name: require_identity(root / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["root_files"].items()
    }
    candidate = BASE / closure["candidate"]["name"]
    private_directory_identity(candidate)
    private_directory_identity(candidate / "successor-receipts")
    private_directory_identity(candidate / "tmp")
    require(set(os.listdir(candidate)) == {"home", "repo", "successor-receipts", "tmp"}, "V43 candidate entries mismatch")
    candidate_files = {
        name: require_identity(candidate / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["candidate_files"].items()
    }
    repo = candidate / "repo"
    require(status_counts(repo) == closure["candidate"]["inventory"], "V43 candidate inventory mismatch")
    run_id = closure["candidate"]["run_id"]
    run = repo / ".loop/runs" / run_id
    formal_files = {
        name: require_identity(run / name, value["sha256"], 0o644, value["size"])
        for name, value in closure["formal_files"].items()
    }
    state, _ = load_json(run / "state.json")
    require(
        state["run_id"] == run_id
        and state["state"] == "blocked"
        and state["cycle"] == closure["formal"]["cycle"]
        and state["code_cycle"] == closure["formal"]["code_cycle"]
        and state["coder_session_id"] is None
        and state["command_results"] == []
        and state["last_error"] == closure["formal"]["last_error"],
        "V43 formal state mismatch",
    )
    expected_planners = [
        ".loop/runs/" + run_id + "/artifacts/planner/001.json",
        ".loop/runs/" + run_id + "/artifacts/planner/002.json",
    ]
    require(state["artifacts"] == {"planner": expected_planners}, "V43 artifact map mismatch")
    artifacts = run / "artifacts"
    require(set(os.listdir(artifacts)) == {"planner"}, "V43 downstream role artifact appeared")
    require(set(os.listdir(artifacts / "planner")) == {"001.json", "002.json"}, "V43 planner artifact domain mismatch")
    first, _ = load_json(artifacts / "planner/001.json")
    second, _ = load_json(artifacts / "planner/002.json")
    require(first["verdict"] == second["verdict"] == "NEEDS_INPUT", "V43 planner verdict mismatch")
    required_fragments = (
        "candidate-local trusted record",
        "thirteen-path allowlist",
        "policy",
        "toolchain",
        "external controller acceptance",
    )
    combined = (first["summary"] + "\\n" + second["summary"]).lower()
    require(all(fragment in combined for fragment in required_fragments), "V43 planner provenance diagnosis mismatch")
    for path in (
        run / "artifacts/coder",
        run / "artifacts/reviewer",
        run / "artifacts/tester",
        run / "artifacts/gateway",
    ):
        require(not path.exists() and not path.is_symlink(), "V43 downstream artifact exists")
    v6 = Path(closure["v6_root"])
    for path in (v6, v6 / "home", v6 / "tmp", v6 / "receipts"):
        private_directory_identity(path)
    require(not os.listdir(v6 / "home") and not os.listdir(v6 / "tmp"), "V6 sealed private root drift")
    expected_v6_receipts = {name.split("/", 1)[1] for name in closure["v6_files"] if name.startswith("receipts/")}
    require(set(os.listdir(v6 / "receipts")) == expected_v6_receipts, "V6 receipt set mismatch")
    v6_files = {
        name: require_identity(v6 / name, value["sha256"], 0o600, value["size"])
        for name, value in closure["v6_files"].items()
    }
    auth, _ = load_json(v6 / "receipts/auth-handoff-v6-result.json")
    require(
        auth == {
            "copy_success": True,
            "destination_mode": "0600",
            "destination_owner_uid": 501,
            "format_version": 1,
            "login_status": "SUPPORTED_AUTHENTICATED",
            "phase": "M3A_V6_AUTH_HANDOFF",
            "result": "READY_FOR_CONTROLLER_REVIEW",
            "sanitized_error": None,
        },
        "V6 sanitized receipt mismatch",
    )
    for name in ("final-controller-acceptance-v43-result.json", "auth-handoff-v43-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V43 reserved root result appeared")
    require(closure["candidate_count"] == 27, "V43 recorded candidate count mismatch")
    return {
        "candidate_files": candidate_files,
        "formal_files": formal_files,
        "planner_gap": closure["formal"]["defect"],
        "result": "PASS",
        "root_files": root_files,
        "v6_files": v6_files,
    }
'''


def derive_driver(v43_bytes: bytes) -> bytes:
    require((len(v43_bytes), sha256(v43_bytes)) == (V43_DRIVER_SIZE, V43_DRIVER_SHA256), "sealed V43 driver mismatch")
    legacy = _load_legacy()
    editor = legacy._load_legacy()
    transform = editor._load_legacy()._load_legacy()
    original_text = v43_bytes.decode("utf-8")
    original_tree = ast.parse(original_text, filename="<sealed-v43-driver>")
    historical: dict[str, str] = {}
    for node in original_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("PREVIOUS_"):
            source = ast.get_source_segment(original_text, node)
            require(source is not None, "historical assignment source missing")
            historical[node.targets[0].id] = source
    text = original_text.replace("V44", "__M3S_FUTURE_UPPER__").replace("v44", "__m3s_future_lower__")
    text = text.replace("V43", "V44").replace("v43", "v44")
    text = text.replace("__M3S_FUTURE_UPPER__", "V45").replace("__m3s_future_lower__", "v45")
    require(text.count("range(44, 55)") == 1, "active-version range anchor mismatch")
    text = text.replace("range(44, 55)", "range(45, 55)", 1)
    require(text.count('current_result_name = "successor-preparation-v" + "43-result.json"') == 1, "current result anchor mismatch")
    text = text.replace('current_result_name = "successor-preparation-v" + "43-result.json"', 'current_result_name = "successor-preparation-v" + "44-result.json"', 1)
    require(text.count('future_result_name = "successor-preparation-v" + "44-result.json"') == 1, "future result anchor mismatch")
    text = text.replace('future_result_name = "successor-preparation-v" + "44-result.json"', 'future_result_name = "successor-preparation-v" + "45-result.json"', 1)
    for name, source in historical.items():
        text = editor._replace_assignment_source(text, name, source)

    constants = (
        f"PREVIOUS_M3S_V43_CLOSURE = {V43_CLOSURE!r}\n"
        f"V43_RETAINED_CANDIDATE = Path({str(V43_CANDIDATE)!r})\n"
        f"V43_RETAINED_CANDIDATE_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V43_CANDIDATE_FILES.items()}!r}\n"
        f"V43_FORMAL_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V43_FORMAL_FILES.items()}!r}\n"
        f"V6_ROOT_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V6_ROOT_FILES.items()}!r}\n"
        f"CODER_ALLOWLIST = {CODER_ALLOWLIST!r}\n"
    )
    text = editor._insert_after_assignment(text, "PREVIOUS_M3S_V42_CLOSURE", constants)
    predecessor_anchor = 'PREDECESSORS["candidate.bm4AWiof"] = (27455, 595947585, "622981626b1c22e4f86f9d83a125ade10101c9973aba3f19f65626eed5406357", "0874bfc3b63c7f7fff53aa6b58f0e7192dd24b43ee25851ae6d14dc1d42e3a7c")'
    require(text.count(predecessor_anchor) == 1, "V43 predecessor anchor mismatch")
    text = text.replace(predecessor_anchor, predecessor_anchor + '\nPREDECESSORS["candidate.CbYcDirN"] = (0, 0, "0" * 64, "a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8")', 1)
    omission_anchor = 'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.bm4AWiof"] = 0'
    require(text.count(omission_anchor) == 1, "V43 omission anchor mismatch")
    text = text.replace(omission_anchor, omission_anchor + '\nPREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.CbYcDirN"] = 1', 1)
    omission_test_old = '''    sanitized = {"candidate.KWbe2iGW", "candidate.oivrdV6U", "candidate.M4v94Rmv"}
    require(sum(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS.values()) == 3 and all(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS[name] == 1 for name in sanitized), "credential omission count fixture mismatch")
    require(set(SANITIZED_PROTECTED_PREDECESSOR_BASELINES) == sanitized, "sanitized baseline domain mismatch")
    require(all(PREDECESSORS[name][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES[name] for name in sanitized), "sanitized predecessor baseline mismatch")
    return {"negative_fixture_count": len(negatives), "protected_path_count": 1, "sanitized_baseline_count": 3, "result": "PASS"}'''
    omission_test_new = '''    sanitized = {"candidate.KWbe2iGW", "candidate.oivrdV6U", "candidate.M4v94Rmv"}
    explicitly_validated = {"candidate.CbYcDirN"}
    require(sum(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS.values()) == 4 and all(PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS[name] == 1 for name in sanitized | explicitly_validated), "credential omission count fixture mismatch")
    require(set(SANITIZED_PROTECTED_PREDECESSOR_BASELINES) == sanitized, "sanitized baseline domain mismatch")
    require(all(PREDECESSORS[name][:3] == SANITIZED_PROTECTED_PREDECESSOR_BASELINES[name] for name in sanitized), "sanitized predecessor baseline mismatch")
    return {"negative_fixture_count": len(negatives), "protected_path_count": 1, "sanitized_baseline_count": 4, "result": "PASS"}'''
    require(text.count(omission_test_old) == 1, "credential omission fixture anchor mismatch")
    text = text.replace(omission_test_old, omission_test_new, 1)
    loop_anchor = '    for name, (count, regular_bytes, current_sha, historical_sha) in PREDECESSORS.items():\n        if name == "candidate.5nZWpynN":'
    require(text.count(loop_anchor) == 1, "predecessor loop anchor mismatch")
    text = text.replace(loop_anchor, '    for name, (count, regular_bytes, current_sha, historical_sha) in PREDECESSORS.items():\n        if name == "candidate.CbYcDirN":\n            immutable[name] = validate_m3s_v43_stopped()\n            continue\n        if name == "candidate.5nZWpynN":', 1)

    require(text.count("def validate_m3s_v42_stopped()") == 1, "V42 validator anchor mismatch")
    text = text.replace("def validate_m3s_v42_stopped()", _v43_validator().rstrip() + "\n\n\ndef validate_m3s_v42_stopped()", 1)
    gate_anchor = '        "m3s_v42_stopped": validate_m3s_v42_stopped(),'
    require(text.count(gate_anchor) == 1, "V42 gate anchor mismatch")
    text = text.replace(gate_anchor, '        "m3s_v43_stopped": validate_m3s_v43_stopped(),\n        "trusted_context_closure": trusted_context_closure_self_test(),\n' + gate_anchor, 1)
    semantic_anchor = "canonical_json_model(PREVIOUS_M3S_V42_CLOSURE)"
    require(text.count(semantic_anchor) == 1, "controller semantic predecessor anchor mismatch")
    text = text.replace(semantic_anchor, "canonical_json_model(PREVIOUS_M3S_V43_CLOSURE)", 1)
    inventory_old = 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 175}, "original status counts mismatch")'
    require(text.count(inventory_old) == 1, "original inventory anchor mismatch")
    text = text.replace(inventory_old, 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 177}, "original status counts mismatch")', 1)

    record_anchor = '        "authority_state": "EXTERNAL_CONTROLLER_ACCEPTANCE_RECEIPT_REQUIRED",\n        "blocked_predecessor": PREVIOUS_M3S_V40_CLOSURE["formal"],'
    require(text.count(record_anchor) == 1, "trusted record anchor mismatch")
    text = text.replace(
        record_anchor,
        '        "authority_state": "EXTERNAL_CONTROLLER_ACCEPTANCE_RECEIPT_REQUIRED",\n'
        '        "coder_allowlist": list(CODER_ALLOWLIST),\n'
        '        "external_acceptance_contract": {\n'
        '            "accepted_record_identity_required": True,\n'
        '            "exact_policy_receipt_required": True,\n'
        '            "exact_sealed_toolchain_receipt_required": True,\n'
        '            "formal_dispatch_before_acceptance": False,\n'
        '        },\n'
        '        "immediate_predecessor": PREVIOUS_M3S_V43_CLOSURE["formal"],\n'
        '        "policy_toolchain_contract": {\n'
        '            "policy_semantic": "exact-candidate-snapshot-bound-by-external-acceptance",\n'
        '            "toolchain": "source-and-private-snapshot-fingerprints-bound-by-external-acceptance",\n'
        '        },\n'
        '        "terminal_product_predecessor": PREVIOUS_M3S_V39_CLOSURE,',
        1,
    )
    text = text.replace('"record_kind": "liveclip_m3_successor_trusted_context_v2"', '"record_kind": "liveclip_m3_successor_trusted_context_v3"', 2)
    kind_anchor = 'value["record_kind"] == "liveclip_m3_successor_trusted_context_v2"'
    require(text.count(kind_anchor) == 1, "trusted record-kind validation anchor mismatch")
    text = text.replace(kind_anchor, 'value["record_kind"] == "liveclip_m3_successor_trusted_context_v3"', 1)
    key_anchor = '            "authority_state",\n            "blocked_predecessor",\n            "candidate",'
    require(text.count(key_anchor) == 1, "trusted context key anchor mismatch")
    text = text.replace(
        key_anchor,
        '            "authority_state",\n'
        '            "candidate",\n'
        '            "coder_allowlist",\n'
        '            "external_acceptance_contract",\n'
        '            "immediate_predecessor",\n'
        '            "policy_toolchain_contract",\n'
        '            "terminal_product_predecessor",',
        1,
    )
    old_block = '''    require(
        canonical_json_model(value["blocked_predecessor"]) == canonical_json_model(PREVIOUS_M3S_V40_CLOSURE["formal"]),
        "context blocked state mismatch",
    )'''
    require(text.count(old_block) == 1, "trusted predecessor validation anchor mismatch")
    new_block = '''    require(
        canonical_json_model(value["immediate_predecessor"]) == canonical_json_model(PREVIOUS_M3S_V43_CLOSURE["formal"]),
        "context immediate predecessor mismatch",
    )
    require(
        canonical_json_model(value["terminal_product_predecessor"]) == canonical_json_model(PREVIOUS_M3S_V39_CLOSURE),
        "context V39 terminal closure mismatch",
    )
    require(value["coder_allowlist"] == list(CODER_ALLOWLIST) and len(value["coder_allowlist"]) == 13, "context Coder allowlist mismatch")
    require(
        value["external_acceptance_contract"] == {
            "accepted_record_identity_required": True,
            "exact_policy_receipt_required": True,
            "exact_sealed_toolchain_receipt_required": True,
            "formal_dispatch_before_acceptance": False,
        },
        "context external acceptance contract mismatch",
    )
    require(
        value["policy_toolchain_contract"] == {
            "policy_semantic": "exact-candidate-snapshot-bound-by-external-acceptance",
            "toolchain": "source-and-private-snapshot-fingerprints-bound-by-external-acceptance",
        },
        "context policy/toolchain contract mismatch",
    )'''
    text = text.replace(old_block, new_block, 1)

    fixture = r'''
def trusted_context_closure_self_test() -> dict[str, Any]:
    repo = BASE / "candidate.M3SSELFTEST/repo"
    run_id = "20990101T010203Z-1a2b3c4d"
    state_identity = {"sha256": "a" * 64, "size": 123}
    valid = final_context_record(repo, run_id, state_identity, "b" * 64, "c" * 64)
    validate_final_context_shape(valid, repo, run_id, state_identity)
    require(valid["coder_allowlist"] == list(CODER_ALLOWLIST), "trusted fixture allowlist mismatch")
    require(canonical_json_model(valid["terminal_product_predecessor"]) == canonical_json_model(PREVIOUS_M3S_V39_CLOSURE), "trusted fixture V39 closure mismatch")
    require(canonical_json_model(valid["immediate_predecessor"]) == canonical_json_model(PREVIOUS_M3S_V43_CLOSURE["formal"]), "trusted fixture immediate closure mismatch")

    def rejected(mutator: Any) -> bool:
        candidate = json.loads(json.dumps(valid))
        mutator(candidate)
        try:
            validate_final_context_shape(candidate, repo, run_id, state_identity)
        except RuntimeError:
            return True
        return False

    cases = {
        "positive": True,
        "old_v40_predecessor_reject": rejected(lambda item: item.__setitem__("immediate_predecessor", PREVIOUS_M3S_V40_CLOSURE["formal"])),
        "missing_v39_reject": rejected(lambda item: item.pop("terminal_product_predecessor")),
        "v39_substitution_reject": rejected(lambda item: item.__setitem__("terminal_product_predecessor", PREVIOUS_M3S_V40_CLOSURE)),
        "eleven_path_reject": rejected(lambda item: item.__setitem__("coder_allowlist", item["coder_allowlist"][:-2])),
        "allowlist_substitution_reject": rejected(lambda item: item["coder_allowlist"].__setitem__(2, "src/liveclip/services/agent_clipping_validation.py")),
        "policy_omission_reject": rejected(lambda item: item.pop("policy_toolchain_contract")),
        "toolchain_substitution_reject": rejected(lambda item: item["policy_toolchain_contract"].__setitem__("toolchain", "unsealed")),
        "acceptance_omission_reject": rejected(lambda item: item.pop("external_acceptance_contract")),
    }
    require(all(cases.values()), "trusted-context closure fixture mismatch")
    return {"fixtures": cases, "result": "PASS"}
'''
    init_anchor = "\ndef initialize_and_bind_successor("
    require(text.count(init_anchor) == 2, "initializer anchor mismatch")
    text = text.replace(init_anchor, fixture + init_anchor, 1)

    offer_anchor = '''        "final_record": {
            "preparation_bindings": preparation_identity,
            "root_controller_acceptance": acceptance_identity,
            "root_controller_acceptance_transport": legacy["controller_acceptance_transport"],
        },'''
    require(text.count(offer_anchor) == 1, "offer final-record anchor mismatch")
    text = text.replace(
        offer_anchor,
        '''        "final_record": {
            "preparation_bindings": preparation_identity,
            "root_controller_acceptance": acceptance_identity,
            "root_controller_acceptance_transport": legacy["controller_acceptance_transport"],
            "trusted_context": legacy["context"],
            "trusted_context_receipt": legacy["context_receipt"],
        },''',
        1,
    )
    acceptance_keys_anchor = '''    "authority", "candidate", "contracts", "documents", "final_record",
    "format_version", "phase", "result", "run", "sealed_toolchain",'''
    require(text.count(acceptance_keys_anchor) == 1, "final acceptance key anchor mismatch")
    text = text.replace(
        acceptance_keys_anchor,
        '''    "authority", "candidate", "contracts", "documents", "final_record",
    "format_version", "phase", "policy", "result", "run", "sealed_toolchain",''',
        1,
    )
    toolchain_anchor = '    require(acceptance["sealed_toolchain"] == offer["sealed_toolchain"], "accepted toolchain mismatch")'
    require(text.count(toolchain_anchor) == 1, "final acceptance toolchain anchor mismatch")
    text = text.replace(
        toolchain_anchor,
        toolchain_anchor + '\n    require(acceptance["policy"] == offer["policy"], "accepted policy mismatch")',
        1,
    )

    contracts = transform.literal_assignment(text.encode(), "CONTROLLER_CONTRACTS")
    expected = tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode))
    candidate = contracts["candidate_allocation"]
    candidate["expected_predecessors"] = list(expected)
    candidate["predecessor_count"] = 27
    candidate["candidate_set_contract"]["preallocation"] = "exact 27 immutable predecessor names"
    candidate["candidate_set_contract"]["postallocation"] = "exact 27 predecessors plus one unpredictable current candidate"
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = "checked-in-loop-engineering-policy-plus-v44-current-external-trust-closure-thirteen-path-v39-policy-toolchain-binding"
    policy["pre_root_full_audit"] = {"allocation": False, "gate_count": 71, "home": str(V43_ROOT / "home"), "include_process_gate": True, "no_write_snapshot": True, "tmp": str(V43_ROOT / "tmp")}
    policy["controller_acceptance_semantics"] = {"model": "controller_acceptance_semantic_violations", "predecessor": "PREVIOUS_M3S_V43_CLOSURE", "rejects": ["V42", "missing", "mutated_v43", "extra_v43", "wrong_root"]}
    recorded = policy["historical_candidate_counts"]["recorded_counts"]
    recorded["V43"] = 27
    not_consulted = policy["historical_candidate_counts"]["current_live_total_not_consulted"]
    if "V43" not in not_consulted:
        not_consulted.append("V43")
    recovery = policy["bounded_tree_recovery"]
    recovery["terminal_predecessor"] = "PREVIOUS_M3S_V39_CLOSURE"
    recovery["formal_stop_predecessor"] = "PREVIOUS_M3S_V43_CLOSURE"
    recovery["trusted_record_required_fields"] = ["external_acceptance_contract", "terminal_product_predecessor", "immediate_predecessor", "coder_allowlist", "policy_toolchain_contract"]
    trusted = contracts["trusted_context"]
    trusted["immediate_predecessor"] = {"candidate": "candidate.CbYcDirN", "closure": "PREVIOUS_M3S_V43_CLOSURE", "formal": "CONSUMED_STOPPED_NO_REUSE", "root": str(V43_ROOT), "run_id": V43_RUN_ID}
    trusted["immediate_predecessor_design"] = {"closure": "PREVIOUS_M3S_V43_CLOSURE", "state": "FORMAL_PLAN_REPAIR_BUDGET_EXHAUSTED_NO_REUSE"}
    trusted["context_required_bindings"] = ["complete V39 closure", "V43 formal stop", "exact 13-path Coder allowlist", "policy receipt and semantic hash", "sealed toolchain receipt and fingerprints", "literal external controller acceptance"]
    trusted["external_final_acceptance_schema"] = "binds exact context identity/receipt plus policy and sealed toolchain"
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
    transform = legacy._load_legacy()._load_legacy()._load_legacy()
    tree = ast.parse(payload, filename="<m3s-v44-driver>")
    compile(tree, "<m3s-v44-driver>", "exec")
    contracts = transform.literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = transform.literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_only_gates"]
    returns = [node for node in ast.walk(gate[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)] if len(gate) == 1 else []
    require(len(returns) == 1 and len(returns[0].value.keys) == 71, "gate count mismatch")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v44_static"}
    exec(compile(tree, "<m3s-v44-static>", "exec"), namespace)  # noqa: S102
    surface = {name: len(shape) for name, shape in namespace["SHAPES"].items()}
    require(surface == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    closure_cases = namespace["trusted_context_closure_self_test"]()
    recovery_cases = namespace["validate_v44_recovery_contract"]()
    link_cases = namespace["post_setup_link_safety_self_test"]()
    return_cases = namespace["post_setup_return_path_self_test"]()
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(all(candidate_cases.values()) and all(context_cases.values()), "driver fixture failed")
    require(all(closure_cases["fixtures"].values()), "trusted closure fixture failed")
    require(credential_cases["sanitized_baseline_count"] == 4, "credential fixture failed")
    require(all(recovery_cases["transport_fixtures"].values()), "source transport fixture failed")
    require(all(link_cases["fixtures"].values()) and all(return_cases["fixtures"].values()), "link-return fixture failed")
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    execute_node = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute"]
    mktemp = [node for node in ast.walk(execute_node[0]) if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/mktemp"] if len(execute_node) == 1 else []
    initializers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "initialize_and_bind_successor"]
    loop_init = [node for initializer in initializers for node in ast.walk(initializer) if isinstance(node, ast.List) and len(node.elts) >= 2 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make" and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "44-result.json"' in payload and b'future_result_name = "successor-preparation-v" + "45-result.json"' in payload, "current/future result mismatch")
    require(b'"safe_links": len(links)' not in payload and b'"safe_links": validated_post_setup_link_count(link_safety)' in payload, "V43 link fix regressed")
    require(b'"policy"' in payload and b'"trusted_context": legacy["context"]' in payload and b'"trusted_context_receipt": legacy["context_receipt"]' in payload, "external acceptance binding missing")
    require(b'if name == "candidate.CbYcDirN":' in payload and b'immutable[name] = validate_m3s_v43_stopped()' in payload, "V43 private-HOME omission branch missing")
    ast_proof = _post_setup_ast_proof(tree)
    return {
        "ast_compile": "PASS",
        "candidate_set_cases": candidate_cases,
        "command_surface": surface,
        "context_cases": context_cases,
        "contracts": hashes,
        "credential_policy": credential_cases,
        "gate_count": 71,
        "link_safety": link_cases,
        "one_loop_init": True,
        "one_mktemp": True,
        "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"},
        "post_setup_return_ast": ast_proof,
        "post_setup_return_runtime": return_cases,
        "private_home_policy": "V43 explicit evidence only; no candidate-private HOME traversal",
        "source_transport": recovery_cases["transport_fixtures"],
        "trusted_closure": closure_cases,
        "result": "PASS",
    }



def extract_source(plan_bytes: bytes) -> bytes:
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def build_acceptance(driver_bytes: bytes, *, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, helper_bytes: bytes) -> bytes:
    transform = _load_legacy()._load_legacy()._load_legacy()._load_legacy()
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
        "phase": "M3S_V44_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V43_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "legacy_helper": {"path": str(LEGACY_HELPER), "sha256": LEGACY_HELPER_SHA256, "size": LEGACY_HELPER_SIZE},
            "requirements": {
                "v2": {"path": str(REQUIREMENT_V2), "sha256": REQUIREMENT_V2_SHA256, "size": REQUIREMENT_V2_SIZE},
                "v3": {"path": str(REQUIREMENT_V3), "sha256": REQUIREMENT_V3_SHA256, "size": REQUIREMENT_V3_SIZE},
            },
            "sealed_v43_driver": {"path": str(V43_DRIVER), "sha256": V43_DRIVER_SHA256, "size": V43_DRIVER_SIZE},
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
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 177}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    v2 = require_file(REQUIREMENT_V2, REQUIREMENT_V2_SIZE, REQUIREMENT_V2_SHA256)
    v3 = require_file(REQUIREMENT_V3, REQUIREMENT_V3_SIZE, REQUIREMENT_V3_SHA256)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V44 root appeared")
    return {"architecture": architecture, "candidates_sha256": sha256(compact(candidates)), "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)}, "git_status_sha256": sha256(status_payload), "inventory": counts, "requirements": {"v2": v2, "v3": v3}, "v44_root_absent": True}


def full_pre_root_audit(driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v44-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v44_audit"}
    exec(compile(tree, "<m3s-v44-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V44 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v42_substitution", namespace["PREVIOUS_M3S_V42_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["formal"]["elapsed_seconds"] = 214.0
    negatives["mutated_v43"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v43"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 42}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(all(negatives[name] == ["predecessor_closure"] for name in ("v42_substitution", "missing", "mutated_v43", "extra_v43")) and negatives["wrong_root"] == ["root"], "V44 acceptance negative accepted")
    values = {"base": str(BASE), "seed": str(SEED), "plan": str(PLAN), "expected_plan_sha256": sha256(plan_bytes), "status": str(STATUS), "expected_status_sha256": sha256(status_bytes)}
    saved_environment = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](values, V43_ROOT / "home", V43_ROOT / "tmp", include_process_gate=True)
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 71, "full pre-root gate count mismatch")
    require(gates["v44_recovery_contract"]["result"] == "PASS", "recovery gate failed")
    require(gates["m3s_v43_stopped"]["result"] == "PASS", "V43 closure gate failed")
    require(gates["post_setup_link_safety"]["result"] == "PASS", "link-safety gate failed")
    require(gates["post_setup_return_path"]["result"] == "PASS", "return-path gate failed")
    require(gates["trusted_context_closure"]["result"] == "PASS", "trusted-context closure gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION" and len(gates["predecessors"]["candidate_names"]) == 27, "preallocation state mismatch")
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
    v43_bytes, _ = read_regular(V43_DRIVER)
    driver_bytes = derive_driver(v43_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source_bytes, helper_bytes=helper_bytes)
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V44 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v44.json", acceptance)
    source_receipt = write_exclusive(RECEIPTS / "source-receipt.json", compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V44_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n")
    writer_receipt = write_exclusive(RECEIPTS / "writer-self-test.json", compact({"format_version": 1, "phase": "M3S_V44_WRITER_SELF_TEST", "result": "PASS"}) + b"\n")
    self_check = write_exclusive(RECEIPTS / "self-check-result.json", compact({"audit": audit, "format_version": 1, "phase": "M3S_V44_SELF_CHECK", "result": "PASS", "static": static}) + b"\n")
    final_value = {"controller_acceptance": acceptance_identity, "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256}, "driver": driver_identity, "format_version": 1, "phase": "M3S_V44_FINAL_INDEX", "root_prepare_argv_json_sha256": sha256(root_argv_json), "source_receipt": source_receipt, "self_check": self_check, "verdict": "M3S_V44_READY_FOR_CONTROLLER_REVIEW", "writer_self_test": writer_receipt}
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V44_ROOT_ONLY", "result": "M3S_V44_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
