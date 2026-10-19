"""Deterministic M3S-v42 source-freeze and root-only helper.

This Trusted-Main-only helper derives V42 from the immutable sealed V41
driver. It binds the retained V41 post-setup stop, repairs only the stale
post-setup safe-link cardinality, runs the complete allocation-free pre-root
graph, and may create only the fixed V42 root. Importing it is read-only.
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
V41_ROOT = BASE / "trusted-tools/m3-successor-preparation-v41"
V41_DRIVER = V41_ROOT / "candidate-driver.py"
V41_CANDIDATE = BASE / "candidate.CrvNTqvL"
ROOT = BASE / "trusted-tools/m3-successor-preparation-v42"
DRIVER = ROOT / "candidate-driver.py"
RECEIPTS = ROOT / "receipts"
HELPER = DELIVERY / "tools/loop_engineering/m3s_v42_source_freeze.py"
LEGACY_HELPER = DELIVERY / "tools/loop_engineering/m3s_v41_source_freeze.py"
SOURCE_BEGIN = b"# LIVECLIP_M3S_PREPARATION_V42_BEGIN\n"
SOURCE_END = b"# LIVECLIP_M3S_PREPARATION_V42_END\n"
CURRENT_UID = 501
PATH_VALUE = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
CF_USER_TEXT_ENCODING = "0x1F5:0x0:0x0"
V41_DRIVER_SIZE = 484_708
V41_DRIVER_SHA256 = "b9dfd77aefd9091fada40f246ff9ebf0b6b650806ed7fcc1a45db5f7701f9fce"
LEGACY_HELPER_SIZE = 57_374
LEGACY_HELPER_SHA256 = "24d6487bf9b6d1e427ba1fcc90a07cc1ec03336e453eabb62fe2f72f0f44ad98"
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
    "candidate.bSEqMEit", "candidate.c79YYSLQ", "candidate.cQnaAbOf",
    "candidate.dygENR4n", "candidate.iyme1x_i", "candidate.jyq_n37h",
    "candidate.mRMO7MQ6", "candidate.o99gfxup", "candidate.oivrdV6U",
    "candidate.qaDKDWkQ", "candidate.vuDWtK0T", "candidate.xp23hqNY",
    "candidate.z6EbTJew",
)

V41_ROOT_FILES = {
    "candidate-driver.py": (484_708, V41_DRIVER_SHA256),
    "receipts/controller-acceptance-v41.json": (17_682, "07160e7ef979492bf15301563593561218b0dbb1bec8b471fd105966329fc5c1"),
    "receipts/source-receipt.json": (524, "5c1ff4f51b09be4ef18db25a4d0defe5f4ab5d4b97a1a5ef3d7ec16af7c49640"),
    "receipts/writer-self-test.json": (72, "0dc3d6b2af9cf305c70c42a66136561b5147db08dbdb3f7675e5d7acb12eab3c"),
    "receipts/self-check-result.json": (5_822, "89622c704c0ce42781d1e0fe1ea993aa2b2bfaecdda44d0c5207280285701f0d"),
    "receipts/final-index.json": (2_000, "435e742ed77c1efdb7b48d79684d4f2cbaaa90aabc2604953755dfb2cd806e7a"),
    "receipts/successor-preparation-v41-result.json": (14_087, "d9d279485b1e12307a2efb34a4262734ed2ceb3b4cf441554a43a1975a0a78f1"),
}
V41_CANDIDATE_FILES = {
    "candidate-dry-run-capture.json": (10_393, "7acbaf930b59e5358d19b70ae4c6e5515ef86af66576abbd49c36bd18bf2966f"),
    "candidate-dry-run-stderr.bin": (0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    "candidate-dry-run-stdout.bin": (2_294, "a2ea3cf6ebb5377275173f017173a73dc3eaf08b825cfcb80cad7a6ede953a91"),
    "candidate-dry-run-validation.json": (2_345, "22f700b5072d281285f996ceb6f433d732528808a87d23473d5a6c4d61f75057"),
    "candidate-manifest.jsonl": (625_482, "e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044"),
    "final-attempt-manifest.jsonl": (6_285_222, "45cb27122eef1a211b2c63b3c11893dc4ce5fd5231bbff94a0fe6c32d42f5455"),
    "final-receipt-index.json": (8_600, "6b2096059aab2506a6340151aa63226265856a6279cbb6f04a6d345ce0ffa7c3"),
    "final-repository-manifest.jsonl": (6_143_897, "4a20ee5f097ed5d7b9737bcfd8da54fef87ebe63d5685d0f7c889deae3e92b33"),
    "included-untracked.zlist": (3_619, "1cbfb3a787026491c1c979ce3f263adece51af8cc1210c94094dd7bf2ee3cec7"),
    "materialization-results.jsonl": (5_864, "c11a5add9c9a8a35d05f8587fd5510b592b6eca5a2dedf31d1fb7d6b9bdc8b97"),
    "pre-setup-receipt.json": (9_584, "2836735eb8af2fffcd83ef11eaa894cd588f1fe326d52042c6f44518ec704b0d"),
    "preflight-receipt.json": (326_813, "24bb96e79971b3a9225dd4095086ba478953e736cebb8d6ae91607780dc43cde"),
    "preservation-receipt.json": (340_852, "e569c90f1dc3cd742c4696444f41faa38af51ac5fe8be3b02f58103f8e5f5834"),
    "setup-command.json": (622, "c386341360487f2b67e2334ac3dab1660027b5ddbddbbb5e3a0c41b8e37cf788"),
    "setup-result.json": (14_222, "d14b5d66a46a01bf538a9a5d492278826769f67799e97140e3a6c6f9a22c117d"),
    "source-manifest.jsonl": (625_482, "e6bc1213d482c38c78b97c3390ea35c05ca05efb2c1ff1d754e3894a04fd8044"),
    "source-tracked.patch": (204_622, "472638a7f6c78634d3dbe5508716fc3a1328761dd4047eaf1b20c4d494a01254"),
    "successor-v41-overlay.json": (2_344, "b987fc0f8138dcc264edb1a331bf3ddab11e4a9673400532bf99fc98055cf9ed"),
    "successor-v41-stop.json": (244, "d26e2d965748b830eb3b3d5ce3178b2f038d30ff5c658c46e6bb1916a7983c30"),
}

V41_CLOSURE = {
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
        "name": "candidate.CrvNTqvL",
        "run_id": None,
        "completed_tree": {
            "path_count": 27_455,
            "regular_file_bytes": 595_892_935,
            "sha256": "2d1e5cad4ee1094bd0a311a58a01dfb8f196afb15546a2cfa2eda9f78aeb82ee",
            "protected_credential_paths_omitted": 0,
        },
        "inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 73},
        "tmp_file": {
            "name": "uv-57664ac1717b952c.lock",
            "mode": "0666",
            "size": 0,
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        "link_safety": {
            "canonical_json_bytes": 13_353,
            "canonical_json_sha256": "c7fb588e00d8dea1a960e917fa500f489ded954ca92d64c5badac26ea811fa6c",
            "link_count": POST_SETUP_LINK_COUNT,
            "unsafe_count": 0,
        },
    },
    "candidate_count": 25,
    "delivery_inventory": {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 173},
    "diagnosis": {
        "actual_safe_links": 103,
        "driver_expected_links": 102,
        "error": "RuntimeError: post-setup link safety mismatch",
        "setup_returncode": 0,
        "unsafe_links": 0,
    },
    "invocation": {
        "child_pid": 89_647,
        "elapsed_seconds": 134.507742,
        "outer_returncode": 1,
        "outer_wall_seconds": 134.5885662920191,
        "session": 47_430,
        "timed_out": False,
        "output_truncated": False,
        "wrapper_error": None,
    },
    "manifests": {
        "final_repository": {"path_count": 27_431, "regular_file_bytes": 581_280_434, "size": 6_143_897, "sha256": "4a20ee5f097ed5d7b9737bcfd8da54fef87ebe63d5685d0f7c889deae3e92b33"},
        "final_attempt": {"path_count": 27_453, "regular_file_bytes": 589_599_113, "size": 6_285_222, "sha256": "45cb27122eef1a211b2c63b3c11893dc4ce5fd5231bbff94a0fe6c32d42f5455"},
    },
    "result": {
        "path": str(V41_ROOT / "receipts/successor-preparation-v41-result.json"),
        "size": 14_087,
        "sha256": "d9d279485b1e12307a2efb34a4262734ed2ceb3b4cf441554a43a1975a0a78f1",
        "output_size": 11_284,
        "output_sha256": "8ee9276504d8ed400b09fdd4020c53a21d8db504505d838df71f11ac670d7c23",
    },
    "root": str(V41_ROOT),
    "root_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V41_ROOT_FILES.items()},
    "candidate_files": {name: {"size": size, "sha256": digest} for name, (size, digest) in V41_CANDIDATE_FILES.items()},
    "sealing": {
        "complete": True,
        "errors": [],
        "final_index": {"size": 8_600, "sha256": "6b2096059aab2506a6340151aa63226265856a6279cbb6f04a6d345ce0ffa7c3"},
        "preservation": {"size": 340_852, "sha256": "e569c90f1dc3cd742c4696444f41faa38af51ac5fe8be3b02f58103f8e5f5834"},
        "stop": {"size": 244, "sha256": "d26e2d965748b830eb3b3d5ce3178b2f038d30ff5c658c46e6bb1916a7983c30"},
        "verdict": "M3_SUCCESSOR_PREPARATION_V41_STOPPED",
    },
}


class FreezeError(RuntimeError):
    """Fail-closed V42 design or construction error."""


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
    spec = importlib.util.spec_from_file_location("liveclip_m3s_v41_freeze", LEGACY_HELPER)
    require(spec is not None and spec.loader is not None, "legacy helper import spec failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replace_assignment_source(text: str, name: str, source: str) -> str:
    tree = ast.parse(text, filename="<m3s-v42-restore>")
    matches = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
    ]
    require(len(matches) == 1, f"assignment restore mismatch: {name}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    return text[:start] + source + text[end:]


def _insert_after_assignment(text: str, name: str, addition: str) -> str:
    tree = ast.parse(text, filename="<m3s-v42-insert>")
    matches = [
        node for node in tree.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
    ]
    require(len(matches) == 1, f"assignment insertion mismatch: {name}")
    node = matches[0]
    lines = text.splitlines(keepends=True)
    end = sum(len(line) for line in lines[: node.end_lineno])
    return text[:end] + addition.rstrip() + "\n" + text[end:]


def _link_functions() -> str:
    return '''
def post_setup_link_safety_model(link_count: int, unsafe_states: tuple[str, ...]) -> dict[str, Any]:
    violations = []
    if link_count != POST_SETUP_LINK_COUNT:
        violations.append("link_count")
    if unsafe_states:
        violations.append("unsafe_links")
    return {"expected_link_count": POST_SETUP_LINK_COUNT, "link_count": link_count, "unsafe_states": list(unsafe_states), "violations": violations}


def validate_post_setup_link_safety(repo: Path) -> dict[str, Any]:
    links = [path for path in repo.rglob("*") if path.is_symlink()]
    unsafe = unsafe_links(repo)
    model = post_setup_link_safety_model(len(links), tuple(sorted(item[1] for item in unsafe)))
    require(not model["violations"], "post-setup link safety mismatch")
    return model


def post_setup_link_safety_self_test() -> dict[str, Any]:
    actual = validate_post_setup_link_safety(V41_RETAINED_CANDIDATE / "repo")
    fixtures = {
        "actual_103_internal_accept": actual["link_count"] == 103 and not actual["unsafe_states"],
        "stale_102_reject": post_setup_link_safety_model(102, ())["violations"] == ["link_count"],
        "extra_104_reject": post_setup_link_safety_model(104, ())["violations"] == ["link_count"],
        "broken_reject": post_setup_link_safety_model(103, ("broken",))["violations"] == ["unsafe_links"],
        "external_reject": post_setup_link_safety_model(103, ("external",))["violations"] == ["unsafe_links"],
    }
    require(all(fixtures.values()), "post-setup link fixture mismatch")
    return {"actual": actual, "fixtures": fixtures, "result": "PASS"}
'''


def _v41_validator() -> str:
    return '''
def validate_m3s_v41_stopped() -> dict[str, Any]:
    closure = PREVIOUS_M3S_V41_CLOSURE
    root = Path(closure["root"])
    for path in (root, root / "home", root / "tmp", root / "receipts"):
        private_directory_identity(path)
    require(set(os.listdir(root)) == {"candidate-driver.py", "home", "tmp", "receipts"}, "V41 root entries mismatch")
    require(not os.listdir(root / "home") and not os.listdir(root / "tmp"), "V41 private root drift")
    expected_root_receipts = {name.split("/", 1)[1] for name in closure["root_files"] if name.startswith("receipts/")}
    require(set(os.listdir(root / "receipts")) == expected_root_receipts, "V41 root receipt set mismatch")
    root_files = {name: require_identity(root / name, value["sha256"], 0o600, value["size"]) for name, value in closure["root_files"].items()}
    outer, outer_identity = load_json(root / "receipts/successor-preparation-v41-result.json")
    require(outer_identity["sha256"] == closure["result"]["sha256"], "V41 result identity mismatch")
    require(outer["returncode"] == 1 and outer["timed_out"] is False and outer["output_truncated"] is False and outer["wrapper_error"] is None and outer["session_id"] is None and outer["credential_variables"] == [], "V41 wrapper result mismatch")
    output_bytes = outer["output"].encode("utf-8")
    require(len(output_bytes) == closure["result"]["output_size"] and sha(output_bytes) == closure["result"]["output_sha256"], "V41 embedded output mismatch")
    require(closure["diagnosis"]["error"] in outer["output"], "V41 terminal error mismatch")
    candidate = BASE / closure["candidate"]["name"]
    private_directory_identity(candidate)
    require(set(os.listdir(candidate)) == {"home", "repo", "successor-receipts", "tmp"}, "V41 candidate entries mismatch")
    private_directory_identity(candidate / "home")
    private_directory_identity(candidate / "tmp")
    private_directory_identity(candidate / "successor-receipts")
    require(not os.listdir(candidate / "home"), "V41 candidate home drift")
    tmp_file = closure["candidate"]["tmp_file"]
    require(set(os.listdir(candidate / "tmp")) == {tmp_file["name"]}, "V41 candidate tmp domain mismatch")
    require_identity(candidate / "tmp" / tmp_file["name"], tmp_file["sha256"], int(tmp_file["mode"], 8), tmp_file["size"])
    expected_receipts = set(V41_STOPPED_CANDIDATE_FILES)
    require(set(os.listdir(candidate / "successor-receipts")) == expected_receipts, "V41 candidate receipt set mismatch")
    candidate_files = {name: require_identity(candidate / "successor-receipts" / name, value["sha256"], 0o600, value["size"]) for name, value in V41_STOPPED_CANDIDATE_FILES.items()}
    stop, _ = load_json(candidate / "successor-receipts/successor-v41-stop.json")
    preservation, _ = load_json(candidate / "successor-receipts/preservation-receipt.json")
    final_index, _ = load_json(candidate / "successor-receipts/final-receipt-index.json")
    setup, _ = load_json(candidate / "successor-receipts/setup-result.json")
    dry_run, _ = load_json(candidate / "successor-receipts/candidate-dry-run-validation.json")
    require(stop["error"] == closure["diagnosis"]["error"] and stop["verdict"] == closure["sealing"]["verdict"], "V41 stop mismatch")
    require(preservation["result"] == "FROZEN_PREALLOCATION_EVIDENCE", "V41 preservation mismatch")
    require(final_index["verdict"] == closure["sealing"]["verdict"], "V41 final index mismatch")
    require(setup["returncode"] == 0 and not setup["timed_out"] and not setup["aggregate_truncated"] and not setup["stdout_truncated"] and not setup["stderr_truncated"], "V41 setup result mismatch")
    require(dry_run["verdict"] == "PASS", "V41 dry-run validation mismatch")
    manifest_payload, totals = tree_manifest(candidate, 0)
    tree = closure["candidate"]["completed_tree"]
    require(totals == {"path_count": tree["path_count"], "regular_file_bytes": tree["regular_file_bytes"]} and sha(manifest_payload) == tree["sha256"], "V41 completed tree mismatch")
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
    require((len(link_rows), len(link_bytes), sha(link_bytes), len(unsafe_states)) == (link["link_count"], link["canonical_json_bytes"], link["canonical_json_sha256"], link["unsafe_count"]), "V41 retained link evidence mismatch")
    require(status_counts(repo) == closure["candidate"]["inventory"], "V41 candidate inventory mismatch")
    require(closure["candidate_count"] == 25 and closure["candidate"]["run_id"] is None, "V41 recorded budget state mismatch")
    for name in ("final-controller-acceptance-v41-result.json", "auth-handoff-v41-result.json"):
        path = root / "receipts" / name
        require(not path.exists() and not path.is_symlink(), "V41 reserved root result appeared")
    return {"candidate_files": candidate_files, "link_safety": link, "root_files": root_files, "result": "PASS", "sealing": closure["sealing"]}
'''


def derive_driver(v41_bytes: bytes) -> bytes:
    require((len(v41_bytes), sha256(v41_bytes)) == (V41_DRIVER_SIZE, V41_DRIVER_SHA256), "sealed V41 driver mismatch")
    legacy = _load_legacy()
    transform = legacy._load_legacy()
    original_text = v41_bytes.decode("utf-8")
    original_tree = ast.parse(original_text, filename="<sealed-v41-driver>")
    historical: dict[str, str] = {}
    for node in original_tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id.startswith("PREVIOUS_"):
            source = ast.get_source_segment(original_text, node)
            require(source is not None, "historical assignment source missing")
            historical[node.targets[0].id] = source
    future_upper = "__M3S_FUTURE_UPPER__"
    future_lower = "__m3s_future_lower__"
    text = original_text.replace("V42", future_upper).replace("v42", future_lower)
    text = text.replace("V41", "V42").replace("v41", "v42")
    text = text.replace(future_upper, "V43").replace(future_lower, "v43")
    require(text.count("range(42, 55)") == 1, "active-version range anchor mismatch")
    text = text.replace("range(42, 55)", "range(43, 55)", 1)
    require(text.count('current_result_name = "successor-preparation-v" + "41-result.json"') == 1, "current result anchor mismatch")
    text = text.replace('current_result_name = "successor-preparation-v" + "41-result.json"', 'current_result_name = "successor-preparation-v" + "42-result.json"', 1)
    require(text.count('future_result_name = "successor-preparation-v" + "42-result.json"') == 1, "future result anchor mismatch")
    text = text.replace('future_result_name = "successor-preparation-v" + "42-result.json"', 'future_result_name = "successor-preparation-v" + "43-result.json"', 1)
    for name, source in historical.items():
        text = _replace_assignment_source(text, name, source)

    constants = (
        f"PREVIOUS_M3S_V41_CLOSURE = {V41_CLOSURE!r}\n"
        f"V41_RETAINED_CANDIDATE = Path({str(V41_CANDIDATE)!r})\n"
        f"V41_STOPPED_CANDIDATE_FILES = { {name: {'size': size, 'sha256': digest} for name, (size, digest) in V41_CANDIDATE_FILES.items()}!r}\n"
        f"POST_SETUP_LINK_COUNT = {POST_SETUP_LINK_COUNT}\n"
    )
    text = _insert_after_assignment(text, "PREVIOUS_M3S_V40_CLOSURE", constants)
    predecessor_anchor = 'PREDECESSORS["candidate.M4v94Rmv"] = (44420, 968624315, "ea61d5daf2332341515b66f08782d313809bbdbe92b9dded693485003be73b9a", "d6f9d170fbc6db5ebceaaaa9e6dfc63b838f1d2e46dd77782db4845a87e42c5e")'
    require(text.count(predecessor_anchor) == 1, "V41 predecessor anchor mismatch")
    text = text.replace(predecessor_anchor, predecessor_anchor + '\nPREDECESSORS["candidate.CrvNTqvL"] = (27455, 595892935, "2d1e5cad4ee1094bd0a311a58a01dfb8f196afb15546a2cfa2eda9f78aeb82ee", "45cb27122eef1a211b2c63b3c11893dc4ce5fd5231bbff94a0fe6c32d42f5455")', 1)
    omission_anchor = 'PREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.M4v94Rmv"] = 1'
    require(text.count(omission_anchor) == 1, "V41 omission anchor mismatch")
    text = text.replace(omission_anchor, omission_anchor + '\nPREDECESSOR_PROTECTED_CREDENTIAL_OMISSIONS["candidate.CrvNTqvL"] = 0', 1)
    expected = tuple(sorted(EXPECTED_CANDIDATES, key=os.fsencode))

    require(text.count("def post_setup(") == 1, "post-setup function anchor mismatch")
    text = text.replace("def post_setup(", _link_functions().rstrip() + "\n\n\ndef post_setup(", 1)
    old_link = '    links = [path for path in repo.rglob("*") if path.is_symlink()]\n    unsafe = unsafe_links(repo)\n    require(not unsafe and len(links) == 102, "post-setup link safety mismatch")'
    require(text.count(old_link) == 1, "post-setup link check anchor mismatch")
    text = text.replace(old_link, "    link_safety = validate_post_setup_link_safety(repo)", 1)
    require(text.count("def validate_m3s_v40_stopped()") == 1, "V40 validator anchor mismatch")
    text = text.replace("def validate_m3s_v40_stopped()", _v41_validator().rstrip() + "\n\n\ndef validate_m3s_v40_stopped()", 1)
    gate_anchor = '        "m3s_v40_stopped": validate_m3s_v40_stopped(),'
    require(text.count(gate_anchor) == 1, "V40 gate anchor mismatch")
    text = text.replace(gate_anchor, '        "m3s_v41_stopped": validate_m3s_v41_stopped(),\n        "post_setup_link_safety": post_setup_link_safety_self_test(),\n' + gate_anchor, 1)
    semantic_anchor = "canonical_json_model(PREVIOUS_M3S_V40_CLOSURE)"
    require(text.count(semantic_anchor) == 1, "controller semantic predecessor anchor mismatch")
    text = text.replace(semantic_anchor, "canonical_json_model(PREVIOUS_M3S_V41_CLOSURE)", 1)
    inventory_old = 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 173}, "original status counts mismatch")'
    require(text.count(inventory_old) == 1, "original inventory anchor mismatch")
    text = text.replace(inventory_old, 'require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 174}, "original status counts mismatch")', 1)

    contracts = transform.literal_assignment(text.encode(), "CONTROLLER_CONTRACTS")
    candidate = contracts["candidate_allocation"]
    candidate["expected_predecessors"] = list(expected)
    candidate["predecessor_count"] = 25
    candidate["candidate_set_contract"]["preallocation"] = "exact 25 immutable predecessor names"
    candidate["candidate_set_contract"]["postallocation"] = "exact 25 predecessors plus one unpredictable current candidate"
    policy = contracts["policy_toolchain"]
    policy["policy_contract"] = "checked-in-loop-engineering-policy-plus-v42-exact-v2-v3-source-transport-bounded-tree-recovery-relational-toolchain-final-external-acceptance-post-setup-safe-link-cardinality-103"
    policy["pre_root_full_audit"] = {"allocation": False, "gate_count": 67, "home": str(V41_ROOT / "home"), "include_process_gate": True, "no_write_snapshot": True, "tmp": str(V41_ROOT / "tmp")}
    policy["controller_acceptance_semantics"] = {"model": "controller_acceptance_semantic_violations", "predecessor": "PREVIOUS_M3S_V41_CLOSURE", "rejects": ["V40", "missing", "mutated_v41", "extra_v41", "wrong_root"]}
    policy["post_setup_link_safety"] = {"expected_link_count": 103, "fixtures": ["actual_103_internal", "stale_102", "extra_104", "broken", "external"], "unsafe_links_allowed": False}
    recorded = policy["historical_candidate_counts"]["recorded_counts"]
    recorded["V40"] = 24
    recorded["V41"] = 25
    not_consulted = policy["historical_candidate_counts"]["current_live_total_not_consulted"]
    for version in ("V40", "V41"):
        if version not in not_consulted:
            not_consulted.append(version)
    trusted = contracts["trusted_context"]
    trusted["immediate_predecessor"] = {"candidate": "candidate.CrvNTqvL", "closure": "PREVIOUS_M3S_V41_CLOSURE", "init": "UNCONSUMED_ABANDONED", "prepare": "CONSUMED_STOPPED_NO_REUSE", "root": str(V41_ROOT), "run_id": None}
    trusted["immediate_predecessor_design"] = {"closure": "PREVIOUS_M3S_V41_CLOSURE", "root": str(V41_ROOT), "state": "POST_SETUP_LINK_COUNT_STOP_NO_REUSE"}
    hashes = {name: sha256(compact(value)) for name, value in contracts.items()}
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACTS", contracts)
    text = transform.replace_assignment(text, "CONTROLLER_CONTRACT_HASHES", hashes)
    return text.encode("utf-8")


def inspect_driver(payload: bytes) -> dict[str, Any]:
    legacy = _load_legacy()._load_legacy()
    tree = ast.parse(payload, filename="<m3s-v42-driver>")
    compile(tree, "<m3s-v42-driver>", "exec")
    contracts = legacy.literal_assignment(payload, "CONTROLLER_CONTRACTS")
    hashes = legacy.literal_assignment(payload, "CONTROLLER_CONTRACT_HASHES")
    require({name: sha256(compact(value)) for name, value in contracts.items()} == hashes, "contract hash mismatch")
    gate = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "read_only_gates"]
    returns = [node for node in ast.walk(gate[0]) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)] if len(gate) == 1 else []
    require(len(returns) == 1 and len(returns[0].value.keys) == 67, "gate count mismatch")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v42_static"}
    exec(compile(tree, "<m3s-v42-static>", "exec"), namespace)  # noqa: S102
    require({name: len(shape) for name, shape in namespace["SHAPES"].items()} == {"prepare": 23, "verify-prepare": 23, "accept-final": 15}, "command surface mismatch")
    candidate_cases = namespace["candidate_set_contract_self_test"]()
    credential_cases = namespace["manifest_credential_policy_self_test"]()
    context_cases = namespace["successor_contract_self_test"]()
    recovery_cases = namespace["validate_v42_recovery_contract"]()
    link_cases = namespace["post_setup_link_safety_self_test"]()
    phase_violations = namespace["phase_source_violations"](payload, True)
    require(all(candidate_cases.values()) and all(context_cases.values()), "driver fixture failed")
    require(credential_cases["sanitized_baseline_count"] == 3, "credential fixture failed")
    require(all(recovery_cases["transport_fixtures"].values()), "source transport fixture failed")
    require(all(link_cases["fixtures"].values()), "link-safety fixture failed")
    require(phase_violations == [], "runtime-equivalent phase fixtures failed")
    execute_node = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute"]
    mktemp = [node for node in ast.walk(execute_node[0]) if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/mktemp"] if len(execute_node) == 1 else []
    initializers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "initialize_and_bind_successor"]
    loop_init = [node for initializer in initializers for node in ast.walk(initializer) if isinstance(node, ast.List) and len(node.elts) >= 2 and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "/usr/bin/make" and isinstance(node.elts[1], ast.Constant) and node.elts[1].value == "loop-init"]
    require(len(mktemp) == 1 and len(loop_init) == 1, "allocation/init count mismatch")
    require(b'current_result_name = "successor-preparation-v" + "42-result.json"' in payload and b'future_result_name = "successor-preparation-v" + "43-result.json"' in payload, "current/future result mismatch")
    require(payload.count(b"post-setup link safety mismatch") == 2 and b"len(links) == 102" not in payload, "stale link check survived")
    return {"ast_compile": "PASS", "candidate_set_cases": candidate_cases, "command_surface": {name: len(shape) for name, shape in namespace["SHAPES"].items()}, "context_cases": context_cases, "contracts": hashes, "credential_policy": credential_cases, "gate_count": 67, "link_safety": link_cases, "one_loop_init": True, "one_mktemp": True, "phase_fixtures": {"actual_driver_violations": phase_violations, "result": "PASS"}, "source_transport": recovery_cases["transport_fixtures"], "result": "PASS"}


def extract_source(plan_bytes: bytes) -> bytes:
    require(plan_bytes.count(SOURCE_BEGIN) == 1 and plan_bytes.count(SOURCE_END) == 1, "source marker mismatch")
    start = plan_bytes.index(SOURCE_BEGIN) + len(SOURCE_BEGIN)
    finish = plan_bytes.index(SOURCE_END, start)
    return plan_bytes[start:finish]


def build_acceptance(driver_bytes: bytes, *, plan_bytes: bytes, status_bytes: bytes, source_bytes: bytes, helper_bytes: bytes) -> bytes:
    legacy = _load_legacy()._load_legacy()
    contracts = legacy.literal_assignment(driver_bytes, "CONTROLLER_CONTRACTS")
    hashes = legacy.literal_assignment(driver_bytes, "CONTROLLER_CONTRACT_HASHES")
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
        "phase": "M3S_V42_CONTROLLER_ACCEPTANCE",
        "predecessor_closure": V41_CLOSURE,
        "preparation_source": {
            "helper": {"path": str(HELPER), "sha256": sha256(helper_bytes), "size": len(helper_bytes)},
            "legacy_helper": {"path": str(LEGACY_HELPER), "sha256": LEGACY_HELPER_SHA256, "size": LEGACY_HELPER_SIZE},
            "requirements": {
                "v2": {"path": str(REQUIREMENT_V2), "sha256": REQUIREMENT_V2_SHA256, "size": REQUIREMENT_V2_SIZE},
                "v3": {"path": str(REQUIREMENT_V3), "sha256": REQUIREMENT_V3_SHA256, "size": REQUIREMENT_V3_SIZE},
            },
            "sealed_v41_driver": {"path": str(V41_DRIVER), "sha256": V41_DRIVER_SHA256, "size": V41_DRIVER_SIZE},
            "sha256": sha256(source_bytes),
            "size": len(source_bytes),
        },
        "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": legacy.literal_assignment(driver_bytes, "CONTROLLER_ROOT_BINDING"),
        "seed": {
            "head": legacy.literal_assignment(driver_bytes, "HEAD"),
            "manifest_sha256": legacy.literal_assignment(driver_bytes, "MANIFEST_SHA"),
            "patch_sha256": legacy.literal_assignment(driver_bytes, "PATCH_SHA"),
            "path_list_sha256": legacy.literal_assignment(driver_bytes, "LIST_SHA"),
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
    require(counts == {"staged": 0, "modified_tracked": 15, "ordinary_untracked": 174}, "final inventory mismatch")
    architecture = require_file(ARCHITECTURE, ARCHITECTURE_SIZE, ARCHITECTURE_SHA256)
    v2 = require_file(REQUIREMENT_V2, REQUIREMENT_V2_SIZE, REQUIREMENT_V2_SHA256)
    v3 = require_file(REQUIREMENT_V3, REQUIREMENT_V3_SIZE, REQUIREMENT_V3_SHA256)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V42 root appeared")
    return {"architecture": architecture, "candidates_sha256": sha256(compact(candidates)), "documents": {"execplan": sha256(plan_bytes), "status": sha256(status_bytes)}, "git_status_sha256": sha256(status_payload), "inventory": counts, "requirements": {"v2": v2, "v3": v3}, "v42_root_absent": True}


def full_pre_root_audit(driver_bytes: bytes, acceptance: bytes, plan_bytes: bytes, status_bytes: bytes) -> dict[str, Any]:
    before = audit_snapshot(plan_bytes, status_bytes)
    tree = ast.parse(driver_bytes, filename="<m3s-v42-full-audit>")
    namespace: dict[str, Any] = {"__file__": str(DRIVER), "__name__": "liveclip_m3s_v42_audit"}
    exec(compile(tree, "<m3s-v42-full-audit>", "exec"), namespace)  # noqa: S102
    value = json.loads(acceptance.decode("utf-8"))
    require(namespace["controller_acceptance_semantic_violations"](value) == [], "V41 acceptance model rejected")
    negatives: dict[str, list[str]] = {}
    for label, replacement in (("v40_substitution", namespace["PREVIOUS_M3S_V40_CLOSURE"]), ("missing", {})):
        changed = copy.deepcopy(value)
        changed["predecessor_closure"] = replacement
        negatives[label] = namespace["controller_acceptance_semantic_violations"](changed)
    mutated = copy.deepcopy(value)
    mutated["predecessor_closure"]["diagnosis"]["actual_safe_links"] = 102
    negatives["mutated_v41"] = namespace["controller_acceptance_semantic_violations"](mutated)
    extra = copy.deepcopy(value)
    extra["predecessor_closure"]["unexpected"] = True
    negatives["extra_v41"] = namespace["controller_acceptance_semantic_violations"](extra)
    wrong_root = copy.deepcopy(value)
    wrong_root["root"] = {**wrong_root["root"], "version": 41}
    negatives["wrong_root"] = namespace["controller_acceptance_semantic_violations"](wrong_root)
    require(all(negatives[name] == ["predecessor_closure"] for name in ("v40_substitution", "missing", "mutated_v41", "extra_v41")) and negatives["wrong_root"] == ["root"], "V41 acceptance negative accepted")
    values = {"base": str(BASE), "seed": str(SEED), "plan": str(PLAN), "expected_plan_sha256": sha256(plan_bytes), "status": str(STATUS), "expected_status_sha256": sha256(status_bytes)}
    saved_environment = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(expected_environment())
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = driver_bytes
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = sha256(driver_bytes)
        gates = namespace["read_only_gates"](values, V41_ROOT / "home", V41_ROOT / "tmp", include_process_gate=True)
    finally:
        namespace["PRE_ROOT_AUDIT_DRIVER_BYTES"] = None
        namespace["PRE_ROOT_AUDIT_DRIVER_SHA256"] = None
        os.environ.clear()
        os.environ.update(saved_environment)
    require(len(gates) == 67, "full pre-root gate count mismatch")
    require(gates["v42_recovery_contract"]["result"] == "PASS", "recovery gate failed")
    require(gates["m3s_v41_stopped"]["result"] == "PASS", "V41 closure gate failed")
    require(gates["post_setup_link_safety"]["result"] == "PASS", "link-safety gate failed")
    require(gates["predecessors"]["state"] == "PREALLOCATION" and len(gates["predecessors"]["candidate_names"]) == 25, "preallocation state mismatch")
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
    v41_bytes, _ = read_regular(V41_DRIVER)
    driver_bytes = derive_driver(v41_bytes)
    require(sha256(driver_bytes) == args.expected_driver_sha256, "driver hash mismatch")
    static = inspect_driver(driver_bytes)
    acceptance = build_acceptance(driver_bytes, plan_bytes=plan_bytes, status_bytes=status_bytes, source_bytes=source_bytes, helper_bytes=helper_bytes)
    audit = full_pre_root_audit(driver_bytes, acceptance, plan_bytes, status_bytes)
    require(not ROOT.exists() and not ROOT.is_symlink(), "V42 root exists")
    root_argv = ["/opt/homebrew/bin/python3.12", "-c", source_bytes.decode("utf-8"), *raw_argv]
    require(len(root_argv) == 18, "root argv count mismatch")
    root_argv_json = json.dumps(root_argv, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    os.mkdir(ROOT, 0o700)
    fsync_directory(ROOT.parent)
    for name in ("home", "tmp", "receipts"):
        os.mkdir(ROOT / name, 0o700)
        fsync_directory(ROOT)
    driver_identity = write_exclusive(DRIVER, driver_bytes)
    acceptance_identity = write_exclusive(RECEIPTS / "controller-acceptance-v42.json", acceptance)
    source_receipt = write_exclusive(RECEIPTS / "source-receipt.json", compact({"driver": driver_identity, "helper_sha256": sha256(helper_bytes), "phase": "M3S_V42_SOURCE_WRITE", "result": "PASS", "source_sha256": sha256(source_bytes)}) + b"\n")
    writer_receipt = write_exclusive(RECEIPTS / "writer-self-test.json", compact({"format_version": 1, "phase": "M3S_V42_WRITER_SELF_TEST", "result": "PASS"}) + b"\n")
    self_check = write_exclusive(RECEIPTS / "self-check-result.json", compact({"audit": audit, "format_version": 1, "phase": "M3S_V42_SELF_CHECK", "result": "PASS", "static": static}) + b"\n")
    final_value = {"controller_acceptance": acceptance_identity, "documents": {"plan_sha256": args.expected_plan_sha256, "status_sha256": args.expected_status_sha256}, "driver": driver_identity, "format_version": 1, "phase": "M3S_V42_FINAL_INDEX", "root_prepare_argv_json_sha256": sha256(root_argv_json), "source_receipt": source_receipt, "self_check": self_check, "verdict": "M3S_V42_READY_FOR_CONTROLLER_REVIEW", "writer_self_test": writer_receipt}
    final_index = write_exclusive(RECEIPTS / "final-index.json", compact(final_value) + b"\n")
    fsync_directory(RECEIPTS)
    fsync_directory(ROOT)
    os.write(1, compact({"driver": driver_identity, "final_index": final_index, "phase": "M3S_V42_ROOT_ONLY", "result": "M3S_V42_READY_FOR_CONTROLLER_REVIEW"}) + b"\n")
    return 0


def main(argv: list[str], *, source_bytes: bytes, helper_bytes: bytes) -> int:
    return root_only(parse_args(argv), source_bytes, helper_bytes, argv)


if __name__ == "__main__":
    raise FreezeError("helper is import-only")
