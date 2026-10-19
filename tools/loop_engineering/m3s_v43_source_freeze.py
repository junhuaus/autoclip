"""Deterministic M3S-v43 source-freeze and root-only helper.

This Trusted-Main-only helper derives V43 from the immutable sealed V42
driver. It binds the complete retained V42 post-setup stop, repairs only the
undefined ``links`` return-path reference, runs the full allocation-free
pre-root graph, and may create only the fixed V43 root. Importing it is
read-only.
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
V42_ROOT = BASE / "trusted-tools/m3-successor-preparation-v42"
V42_DRIVER = V42_ROOT / "candidate-driver.py"
V42_CANDIDATE = BASE / "candidate.bm4AWiof"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v43"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v43_source_freeze.py"
LEGACY_HELPER = DELIVERY / "tools/loop_engineering/m3s_v42_source_freeze.py"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V43_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V43_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
V42_DRIVER_SIZE = 501_094
V42_DRIVER_SHA256 = "6a09e8e515338714e5477c094aa083b9a6f32bd7303a272eaf1965857a5d7a30"
LEGACY_HELPER_SIZE = 47_531
LEGACY_HELPER_SHA256 = "3f8cf5b2dd3948696ea6feea6860b94da61361a5b45f4a02581611c6da54ed12"
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
    "candidate.xp23hqNY", "candidate.z6EbTJew",
)

V42_ROOT_FILES = {
    "candidate-driver.py": (501_094, V42_DRIVER_SHA256),
    "receipts/controller-acceptance-v42.json": (17_037, "e0da374d8508dc74935b8043b87823cf3eff4b6c800c9264bd4018ae7ab06ccc"),
    "receipts/source-receipt.json": (524, "57695cf4dee9c8b1a5c47916b6dcbc7e810cbb36f03b91bab6a30cd6034f9a27"),
    "receipts/writer-self-test.json": (72, "be8914d7ed140c49e85c7eb35910e83a3606a0021232acdf4e631fdec155b31c"),
    "receipts/self-check-result.json": (6_139, "0bfc013a4979caf37d8e4e3610fba36eb2dbc5945479f98bb89f16b8d49a6f72"),
    "receipts/final-index.json": (2_000, "ea9ef09aaafa0ca2cca584b864fc67bd14984ebd05c5ac1bd57b41c3d0a2dcbc"),
    "receipts/successor-preparation-v42-result.json": (14_080, "ce8653e0ea2e02ef939ee78f3b70c219a2b71e907f2b0497bfd73805760037e3"),
}
V42_CANDIDATE_FILES = {
    "candidate-dry-run-capture.json": (10_393, "b976f9808ad9b158231c94fe745a3a0e7f7a3d37135d32b00cb51690f7a6bfa2"),
    "candidate-dry-run-stderr.bin": (0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    "candidate-dry-run-stdout.bin": (2_294, "7b3c8cbdbf0e9b36d9b2ca9576e32f8d3ccb262586d28e1e298367e2c817d669"),
    "candidate-dry-run-validation.json": (2_345, "aaa77cbf2b6e7ddfe343d4e1c0d37314decdc21bdbd569b537522062e498aa91"),
    "candidate-manifest.jsonl": (625_482, "e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044"),
    "final-attempt-manifest.jsonl": (6_285_222, "0874bfc3b63c7f7fff53aa6b58f0e7192dd24b43ee25851ae6d14dc1d42e3a7c"),
    "final-receipt-index.json": (8_600, "39f2f0e96809c48404397fbae63b99b2c23b3a7829b47666c1483ef140de9f45"),
    "final-repository-manifest.jsonl": (6_143_897, "f21f0934386666ebc6d539af6a03498370f37a010f5ff81af254afb9d89a94d9"),
    "included-untracked.zlist": (3_619, "1cbfb3a787026491c1c979ce3f263adece51af8cc1210c94094dd7bf2ee3cec7"),
    "materialization-results.jsonl": (5_867, "468875c19e5f891ffd0bf6cb0bd9fe55d2e13df55d53f3dc2e2c6624c650a00f"),
    "pre-setup-receipt.json": (9_584, "094a6f837b1a68ab622b73ae1d5cfb2210dca27ac75d6d6ea393f91717c47065"),
    "preflight-receipt.json": (340_149, "76cbaaf4608f2936231c3b35b6c4d530adbe44c7650e478621a639f9313e0dc2"),
    "preservation-receipt.json": (354_764, "3556b249e86cff09850a79618f5efa0357a8b476b910a65031b88a55da429248"),
    "setup-command.json": (622, "227bb93235ac0158663fcac632312e633b366a8888a5ec56b9736cab1565ab51"),
    "setup-result.json": (14_226, "71d10c56d4f5b3bb7a072ac4756e9a1572d2315a2b0e316e048afd71b0a86290"),
    "source-manifest.jsonl": (625_482, "e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044"),
    "source-tracked.patch": (204_622, "472638a7f6c78634d3dbe5508716fc3a1328761dd4047eaf1b20c4d494a01254"),
    "successor-v42-overlay.json": (2_344, "c50db5025f2af642a830a82777a5273d1b827ef471e028b6e893931ae01df8a7"),
    "successor-v42-stop.json": (237, "b335a72c09c857106357971bbab488da567308ae82899fa2672ce4b33ecdf76c"),
}

V42_CLOSURE = {
    "budgets": {
        "accept_final": "UNCONSUMED_UNAUTHORIZED",
        "authentication": "UNCONSUMED_UNAUTHORIZED",
        "init": "UNCONSUMED_ABANDONED",
        "prepare_invocation": "CONSUMED_NO_REUSE",
        "prepare_result": "CONSUMED_NO_REUSE",
        "root": "CONSUMED_NO_REUSE",
        "suffix": "CONSUMED_NO_REUSE",
    },
    "candidate": {
        "name": "candidate.bm4AWiof",
        "run_id": None,
        "completed_tree": {
            "path_count": 27_455,
            "regular_file_bytes": 595_947_585,
            "sha256": "622981626b1c22e4f86f9d83a125ade10101c9973aba3f19f65626eed5406357",
            "protected_credential_paths_omitted": 0,
        },
        "inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 73},
        "tmp_file": {
            "name": "uv-3cd09864a7d8cfb8.lock",
            "mode": "0666",
            "size": 0,
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "link_safety": {
            "canonical_json_bytes": 13_353,
            "canonical_json_sha256": "0d4a80e7378410829bbe4e0cdb5733e9a42b6af51ae8f524def3a2d32bc70df8",
            "link_count": POST_SETUP_LINK_COUNT,
            "unsafe_count": 0,
        },
    },
    "candidate_count": 26,
    "delivery_inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 174},
    "diagnosis": {
        "error": "NameError: name 'links' is not defined",
        "setup_returncode": 0,
        "validated_link_count": 103,
        "unsafe_links": 0,
        "defect": "post_setup assigned link_safety then returned len(links)",
    },
    "invocation": {
        "session": 20_858,
        "chunks": ["422de7", "062e03", "c9c7d2", "c955ef", "99ab74"],
        "elapsed_seconds": 150.497624,
        "outer_returncode": 1,
        "timed_out": False,
        "output_truncated": False,
        "wrapper_error": None,
        "session_id": None,
        "credential_variables": [],
    },
    "manifests": {
        "final_repository": {"path_count": 27_431, "regular_file_bytes": 581_307_836, "size": 6_143_897, "sha256": "f21f0934386666ebc6d539af6a03498370f37a010f5ff81af254afb9d89a94d9"},
        "final_attempt": {"path_count": 27_453, "regular_file_bytes": 589_653_763, "size": 6_285_222, "sha256": "0874bfc3b63c7f7fff53aa6b58f0e7192dd24b43ee25851ae6d14dc1d42e3a7c"},
    },
    "result": {
        "path": str(V42_ROOT / "receipts/successor-preparation-v42-result.json"),
        "size": 14_080,
        "sha256": "ce8653e0ea2e02ef939ee78f3b70c219a2b71e907f2b0497bfd73805760037e3",
        "output_size": 11_277,
        "output_sha256": "48ac90753f925c5cd435f64de56768ab32bff839c8c43803be37547ef43c2e95",
    },
    "root": str(V42_ROOT),
    "root_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V42_ROOT_FILES.items()},
    "candidate_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V42_CANDIDATE_FILES.items()},
    "sealing": {
        "complete": True,
        "errors": [],
        "final_index": {"size": 8_600, "sha256": "39f2f0e96809c48404397fbae63b99b2c23b3a7829b47666c1483ef140de9f45"},
        "preservation": {"size": 354_764, "sha256": "3556b249e86cff09850a79618f5efa0357a8b476b910a65031b88a55da429248"},
        "stop": {"size": 237, "sha256": "b335a72c09c857106357971bbab488da567308ae82899fa2672ce4b33ecdf76c"},
        "verdict": "M3_SUCCESSOR_PREPARATION_V42_STOPPED",
    },
}


class FreezeError(RuntimeError):
    """Fail-closed V43 design or construction error."""


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
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v42_freeze", LEGACY_HELPER)
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


def _v42_validator() -> str:
    return '''
def validate_m3s_v42_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V42_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V42 root entries mismatch")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V42 private root drift")
    expected_root_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_root_receipts, "V42 root receipt set mismatch")
    root_files = {name: require_identity(root / name, value["sha256"], 0o600, value["size"]) for name, value in closure["root_files"].items()}
    outer, outer_identity = load_json(root / "receipts/successor-preparation-v42-result.json")
    require(outer_identity["sha256"] == closure["result"]["sha256"], "V42 result identity mismatch")
    require(outer["returncode"] == 1 and outer["timed_out"] is False and outer["output_truncated"] is False and outer["wrapper_error"] is None and outer["session_id"] is None and outer["credential_variables"] == [], "V42 wrapper result mismatch")
    output_bytes = outer["output"].encode("utf-8")
    require(len(output_bytes) == closure["result"]["output_size"] and sha(output_bytes) == closure["result"]["output_sha256"], "V42 embedded output mismatch")
    require(closure["diagnosis"]["error"] in outer["output"], "V42 terminal error mismatch")
    candidate = BASE / closure["candidate"]["name"]
    private_directory_identity(candidate)
    require(set(os.listdir(candidate)) == {"home", "repo", "successor-receipts", "tmp"}, "V42 candidate entries mismatch")
    private_directory_identity(candidate / "home")
    private_directory_identity(candidate / "tmp")
    private_directory_identity(candidate / "successor-receipts")
    require(not os.listdir(candidate / "home"), "V42 candidate home drift")
    tmp_file = closure["candidate"]["tmp_file"]
    require(set(os.listdir(candidate / "tmp")) == {tmp_file["name"]}, "V42 candidate tmp domain mismatch")
    require_identity(candidate / "tmp" / tmp_file["name"], tmp_file["sha256"], int(tmp_file["mode"], 8), tmp_file["size"])
    expected_receipts = set(V42_STOPPED_CANDIDATE_FILES)
    require(set(os.listdir(candidate / "successor-receipts")) == expected_receipts, "V42 candidate receipt set mismatch")
    candidate_files = {name: require_identity(candidate / "successor-receipts" / name, value["sha256"], 0o600, value["size"]) for name, value in V42_STOPPED_CANDIDATE_FILES.items()}
    stop, _ = load_json(candidate / "successor-receipts/successor-v42-stop.json")
    preservation, _ = load_json(candidate / "successor-receipts/preservation-receipt.json")
    final_index, _ = load_json(candidate / "successor-receipts/final-receipt-index.json")
    setup, _ = load_json(candidate / "successor-receipts/setup-result.json")
    dry_run, _ = load_json(candidate / "successor-receipts/candidate-dry-run-validation.json")
    overlay, _ = load_json(candidate / "successor-receipts/successor-v42-overlay.json")
    require(stop["error"] == closure["diagnosis"]["error"] and stop["verdict"] == closure["sealing"]["verdict"], "V42 stop mismatch")
    require(preservation["result"] == "FROZEN_PREALLOCATION_EVIDENCE", "V42 preservation mismatch")
    require(final_index["verdict"] == closure["sealing"]["verdict"] and final_index["sealing_errors_before_index"] == [], "V42 final index mismatch")
    require(setup["returncode"] == 0 and not setup["timed_out"] and not setup["aggregate_truncated"] and not setup["stdout_truncated"] and not setup["stderr_truncated"], "V42 setup result mismatch")
    require(dry_run["verdict"] == "PASS" and overlay["result"] == "PASS", "V42 validation/overlay mismatch")
    manifest_payload, totals = tree_manifest(candidate, 0)
    tree = closure["candidate"]["completed_tree"]
    require(totals == {"path_count": tree["path_count"], "regular_file_bytes": tree["regular_file_bytes"]} and sha(manifest_payload) == tree["sha256"], "V42 completed tree mismatch")
    link_rows = []
    unsafe_states = []
    repo = candidate / "repo"
    for path in sorted(repo.rglob("*"), key=lambda item: os.fsencode(item.relative_to(repo).as_posix())):
        if not path.is_symlink():
            continue
        relative = path.relative_to(repo).as_posix()
        target = os.readlink(path)
        try:
            resolved = path.resolve(strict=True)
            state = "internal" if resolved.is_relative_to(repo) else "external"
        except (FileNotFoundError, RuntimeError, OSError):
            state = "broken"
        link_rows.append({"path": relative, "state": state, "target": target})
        if state != "internal":
            unsafe_states.append(state)
    link_bytes = compact(link_rows)
    link = closure["candidate"]["link_safety"]
    require((len(link_rows), len(link_bytes), sha(link_bytes), len(unsafe_states)) == (link["link_count"], link["canonical_json_bytes"], link["canonical_json_sha256"], link["unsafe_count"]), "V42 retained link evidence mismatch")
    require(status_counts(repo) == closure["candidate"]["inventory"], "V42 candidate inventory mismatch")
    require(closure["candidate_count"] == 26 and closure["candidate"]["run_id"] is None, "V42 recorded budget state mismatch")
    runs = repo / ".loop/runs"
    require(not runs.exists() and not runs.is_symlink(), "V42 run unexpectedly exists")
    for name in ("final-controller-acceptance-v42-result.json", "auth-handoff-v42-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V42 reserved root result appeared")
    return {"candidate_files": candidate_files, "link_safety": link, "root_files": root_files, "result": "PASS", "sealing": closure["sealing"]}
'''


def derive_driver(v42_bytes: bytes) -> bytes:
    require((len(v42_bytes), sha256(v42_bytes)) == (V42_DRIVER_SIZE, V42_DRIVER_SHA256), "sealed V42 driver mismatch")
    legacy = _load_legacy()
    transform = legacy._load_legacy()._load_legacy()
    original_text = v42_bytes.decode("utf-8")
    original_tree = ast.parse(original_text, filename="<sealed-v42-driver>")
    historical: dict[str, str] = {}
    for node in original_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("PREVIOUS_"):
            source = ast.get_source_segment(original_text, node)
            require(source is not None, "historical assignment source missing")
            historical[node.targets[0].id] = source
    text = original_text.replace("V43", "__M3S_FUTURE_UPPER__").replace("v43", "__m3s_future_lower__")
    text = text.replace("V42", "V43").replace("v42", "v43")
    text = text.replace("__M3S_FUTURE_UPPER__", "V44").replace("__m3s_future_lower__", "v44")
    require(text.count("range(43, 55)") == 1, "active-version range anchor mismatch")
    text = text.replace("range(43, 55)", "range(44, 55)", 1)
    require(text.count('current_result_name = "successor-preparation-v" + "42-result.json"') == 1, "current result anchor mismatch")
    text = text.replace('current_result_name = "successor-preparation-v" + "42-result.json"', 'current_result_name = "successor-preparation-v" + "43-result.json"', 1)
    require(text.count('future_result_name = "successor-preparation-v" + "43-result.json"') == 1, "future result anchor mismatch")
    text = text.replace('future_result_name = "successor-preparation-v" + "43-result.json"', 'future_result_name = "successor-preparation-v" + "44-result.json"', 1)
    for name, source in historical.items():
        text = legacy._replace_assignment_source(text, name, source)

    constants = (
        f"PREVIOUS_M3S_V42_CLOSURE = {V42_CLOSURE!r}\n"
        f"V42_RETAINED_CANDIDATE = Path({str(V42_CANDIDATE)!r})\n"
        f"V42_STOPPED_CANDIDATE_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V42_CANDIDATE_FILES.items()}!r}\n"
    )
    text = legacy._insert_after_assignment(text, "PREVIOUS_M3S_V41_CLOSURE", constants)
    predecessor_anchor = 'PREDECESSORS["candidate.CrvNTqvL"] = (27455, 595892935, "2d1e5cad4ee1094bd0a311a58a01dfb8f196afb15546a2cfa2eda9f78aeb82ee", "45cb27122eef1a211b2c63b3c11893dc4ce5fd5231bbff94a0fe6c32d42f5455")'
    require(text.count(predecessor_anchor) == 1, "V42 predecessor anchor mismatch")
    text = text.replace(predecessor_anchor, predecessor_anchor + '\nPREDECESSORS["candidate.bm4AWiof"] = (27455, 595947585, "622981626b1c22e4f86f9d83a125ade10101c9973aba3f19f65626eed5406357", "0874bfc3b63c7f7fff53aa6b58f0e7192dd24b43ee25851ae6d14dc1d42e3a7c")', 1)
    omission_anchor = 'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.CrvNTqvL"] = 0'
    require(text.count(omission_anchor) == 1, "V42 omission anchor mismatch")
    text = text.replace(omission_anchor, omission_anchor + '\nPREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.bm4AWiof"] = 0', 1)

    require(text.count("def post_setup(") == 1, "post-setup function anchor mismatch")
    text = text.replace("def post_setup(", _return_path_functions().rstrip() + "\n\n\ndef post_setup(", 1)
    bad_return = '        "safe_links": len(links),'
    require(text.count(bad_return) == 1, "V42 undefined-link return anchor mismatch")
    text = text.replace(bad_return, '        "safe_links": validated_post_setup_link_count(link_safety),', 1)
    actual_anchor = 'actual = validate_post_setup_link_safety(V41_RETAINED_CANDIDATE / "repo")'
    require(text.count(actual_anchor) == 1, "V42 retained-link fixture anchor mismatch")
    text = text.replace(actual_anchor, 'actual = validate_post_setup_link_safety(V42_RETAINED_CANDIDATE / "repo")', 1)
    require(text.count("def validate_m3s_v41_stopped()") == 1, "V41 validator anchor mismatch")
    text = text.replace("def validate_m3s_v41_stopped()", _v42_validator().rstrip() + "\n\n\ndef validate_m3s_v41_stopped()", 1)
    gate_anchor = '        "m3s_v41_stopped": validate_m3s_v41_stopped(),'
    require(text.count(gate_anchor) == 1, "V41 gate anchor mismatch")
    text = text.replace(gate_anchor, '        "m3s_v42_stopped": validate_m3s_v42_stopped(),\n        "post_setup_return_path": post_setup_return_path_self_test(),\n' + gate_anchor, 1)
    semantic_anchor = "canonical_json_model(PREVIOUS_M3S_V41_CLOSURE)"
    require(text.count(semantic_anchor) == 1, "controller semantic predecessor anchor mismatch")
    text = text.replace(semantic_anchor, "canonical_json_model(PREVIOUS_M3S_V42_CLOSURE)", 1)
    inventory_old = 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 174}, "original status counts mismatch")'
    require(text.count(inventory_old) == 1, "original inventory anchor mismatch")
    text = text.replace(inventory_old, 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 175}, "original status counts mismatch")', 1)

    contracts = transform.literal_assignment(text.encode(), "CONTROLLER_CONTRACTS")
    expected = tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode))
    candidate = contracts["candidate_allocation"]
    candidate["expected_predecessors"] = list(expected)
    candidate["predecessor_count"] = 26
    candidate["candidate_set_contract"]["preallocation"] = "exact 26 immutable predecessor names"
    candidate["candidate_set_contract"]["postallocation"] = "exact 26 predecessors plus one unpredictable current candidate"
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = "checked-in-loop-engineering-policy-plus-v43-exact-v2-v3-source-transport-bounded-tree-recovery-relational-toolchain-final-external-acceptance-post-setup-safe-link-return-103"
    policy["pre_root_full_audit"] = {"allocation": False, "gate_count": 69, "home": str(V42_ROOT / "home"), "include_process_gate": True, "no_write_snapshot": True, "tmp": str(V42_ROOT / "tmp")}
    policy["controller_acceptance_semantics"] = {"model": "controller_acceptance_semantic_violations", "predecessor": "PREVIOUS_M3S_V42_CLOSURE", "rejects": ["V41", "missing", "mutated_v42", "extra_v42", "wrong_root"]}
    policy["post_setup_link_safety"] = {"expected_link_count": 103, "fixtures": ["actual_103_internal", "stale_102", "extra_104", "broken", "external", "executed_return_path", "missing_field"], "return_source": "validated link_safety model only", "unsafe_links_allowed": False}
    recorded = policy["historical_candidate_counts"]["recorded_counts"]
    recorded["V42"] = 26
    not_consulted = policy["historical_candidate_counts"]["current_live_total_not_consulted"]
    if "V42" not in not_consulted:
        not_consulted.append("V42")
    trusted = contracts["trusted_context"]
    trusted["immediate_predecessor"] = {"candidate": "candidate.bm4AWiof", "closure": "PREVIOUS_M3S_V42_CLOSURE", "init": "UNCONSUMED_ABANDONED", "prepare": "CONSUMED_STOPPED_NO_REUSE", "root": str(V42_ROOT), "run_id": None}
    trusted["immediate_predecessor_design"] = {"closure": "PREVIOUS_M3S_V42_CLOSURE", "root": str(V42_ROOT), "state": "POST_SETUP_UNDEFINED_LINKS_RETURN_STOP_NO_REUSE"}
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
    transform = legacy._load_legacy()._load_legacy()
    tree = ast.parse(payload, filename="<m3s-v43-driver>")
    compile(tree, "<m3s-v43-driver>", "exec")
    contracts = transform.literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = transform.literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_only_gates"]
    returns = [node for node in ast.walk(gate[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)] if len(gate) == 1 else []
    require(len(returns) == 1 and len(returns[0].value.keys) == 69, "gate count mismatch")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v43_static"}
    exec(compile(tree, "<m3s-v43-static>", "exec"), namespace)  # noqa: S102
    surface = {name: len(shape) for name, shape in namespace["SHAPES"].items()}
    require(surface == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    recovery_cases = namespace["validate_v43_recovery_contract"]()
    link_cases = namespace["post_setup_link_safety_self_test"]()
    return_cases = namespace["post_setup_return_path_self_test"]()
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(all(candidate_cases.values()) and all(context_cases.values()), "driver fixture failed")
    require(credential_cases["sanitized_baseline_count"] == 3, "credential fixture failed")
    require(all(recovery_cases["transport_fixtures"].values()), "source transport fixture failed")
    require(all(link_cases["fixtures"].values()) and all(return_cases["fixtures"].values()), "link-return fixture failed")
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    execute_node = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute"]
    mktemp = [node for node in ast.walk(execute_node[0]) if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/mktemp"] if len(execute_node) == 1 else []
    initializers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "initialize_and_bind_successor"]
    loop_init = [node for initializer in initializers for node in ast.walk(initializer) if isinstance(node, ast.List) and len(node.elts) >= 2 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make" and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "43-result.json"' in payload and b'future_result_name = "successor-preparation-v" + "44-result.json"' in payload, "current/future result mismatch")
    require(b'"safe_links": len(links)' not in payload and b'"safe_links": validated_post_setup_link_count(link_safety)' in payload, "undefined-link return survived")
    ast_proof = _post_setup_ast_proof(tree)
    return {"ast_compile": "PASS", "candidate_set_cases": candidate_cases, "command_surface": surface, "context_cases": context_cases, "contracts": hashes, "credential_policy": credential_cases, "gate_count": 69, "link_safety": link_cases, "one_loop_init": True, "one_mktemp": True, "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"}, "post_setup_return_ast": ast_proof, "post_setup_return_runtime": return_cases, "source_transport": recovery_cases["transport_fixtures"], "result": "PASS"}


def extract_source(plan_bytes: bytes) -> bytes:
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def build_acceptance(driver_bytes: bytes, *, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, helper_bytes: bytes) -> bytes:
    transform = _load_legacy()._load_legacy()._load_legacy()
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
        "phase": "M3S_V43_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V42_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "legacy_helper": {"path": str(LEGACY_HELPER), "sha256": LEGACY_HELPER_SHA256, "size": LEGACY_HELPER_SIZE},
            "requirements": {
                "v2": {"path": str(REQUIREMENT_V2), "sha256": REQUIREMENT_V2_SHA256, "size": REQUIREMENT_V2_SIZE},
                "v3": {"path": str(REQUIREMENT_V3), "sha256": REQUIREMENT_V3_SHA256, "size": REQUIREMENT_V3_SIZE},
            },
            "sealed_v42_driver": {"path": str(V42_DRIVER), "sha256": V42_DRIVER_SHA256, "size": V42_DRIVER_SIZE},
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
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 175}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    v2 = require_file(REQUIREMENT_V2, REQUIREMENT_V2_SIZE, REQUIREMENT_V2_SHA256)
    v3 = require_file(REQUIREMENT_V3, REQUIREMENT_V3_SIZE, REQUIREMENT_V3_SHA256)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V43 root appeared")
    return {"architecture": architecture, "candidates_sha256": sha256(compact(candidates)), "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)}, "git_status_sha256": sha256(status_payload), "inventory": counts, "requirements": {"v2": v2, "v3": v3}, "v43_root_absent": True}


def full_pre_root_audit(driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v43-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v43_audit"}
    exec(compile(tree, "<m3s-v43-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V42 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v41_substitution", namespace["PREVIOUS_M3S_V41_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["diagnosis"]["validated_link_count"] = 102
    negatives["mutated_v42"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v42"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 42}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(all(negatives[name] == ["predecessor_closure"] for name in ("v41_substitution", "missing", "mutated_v42", "extra_v42")) and negatives["wrong_root"] == ["root"], "V42 acceptance negative accepted")
    values = {"base": str(BASE), "seed": str(SEED), "plan": str(PLAN), "expected_plan_sha256": sha256(plan_bytes), "status": str(STATUS), "expected_status_sha256": sha256(status_bytes)}
    saved_environment = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](values, V42_ROOT / "home", V42_ROOT / "tmp", include_process_gate=True)
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 69, "full pre-root gate count mismatch")
    require(gates["v43_recovery_contract"]["result"] == "PASS", "recovery gate failed")
    require(gates["m3s_v42_stopped"]["result"] == "PASS", "V42 closure gate failed")
    require(gates["post_setup_link_safety"]["result"] == "PASS", "link-safety gate failed")
    require(gates["post_setup_return_path"]["result"] == "PASS", "return-path gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION" and len(gates["predecessors"]["candidate_names"]) == 26, "preallocation state mismatch")
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
    v42_bytes, _ = read_regular(V42_DRIVER)
    driver_bytes = derive_driver(v42_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source_bytes, helper_bytes=helper_bytes)
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V43 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v43.json", acceptance)
    source_receipt = write_exclusive(RECEIPTS / "source-receipt.json", compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V43_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n")
    writer_receipt = write_exclusive(RECEIPTS / "writer-self-test.json", compact({"format_version": 1, "phase": "M3S_V43_WRITER_SELF_TEST", "result": "PASS"}) + b"\n")
    self_check = write_exclusive(RECEIPTS / "self-check-result.json", compact({"audit": audit, "format_version": 1, "phase": "M3S_V43_SELF_CHECK", "result": "PASS", "static": static}) + b"\n")
    final_value = {"controller_acceptance": acceptance_identity, "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256}, "driver": driver_identity, "format_version": 1, "phase": "M3S_V43_FINAL_INDEX", "root_prepare_argv_json_sha256": sha256(root_argv_json), "source_receipt": source_receipt, "self_check": self_check, "verdict": "M3S_V43_READY_FOR_CONTROLLER_REVIEW", "writer_self_test": writer_receipt}
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V43_ROOT_ONLY", "result": "M3S_V43_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
