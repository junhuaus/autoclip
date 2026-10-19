#!/usr/bin/env python3
"""Credential-blind M3A-v6 source freeze and root-only constructor.

This trusted helper derives the V5 handoff driver from the sealed M3A-v2
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
import shlex
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
TARGET = BASE / "candidate.CbYcDirN"
TARGET_REPO = TARGET / "repo"
RUN_ID = "20261015T231933Z-6eee7fff"
RUN = TARGET_REPO / ".loop/runs" / RUN_ID
V2_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v2"
V2_DRIVER = V2_ROOT / "handoff-driver.py"
V3_HELPER = DELIVERY / "tools/loop_engineering/m3a_v3_source_freeze.py"
V3_FAILED_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v3"
V4_HELPER = DELIVERY / "tools/loop_engineering/m3a_v4_source_freeze.py"
V4_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v4"
V4_DRIVER = V4_ROOT / "handoff-driver.py"
V4_RECEIPTS = V4_ROOT / "receipts"
V4_RESULT = V4_RECEIPTS / "auth-handoff-v4-result.json"
V43_ROOT = BASE / "trusted-tools/m3-successor-preparation-v43"
V6_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v6"
V6_DRIVER = V6_ROOT / "handoff-driver.py"
V6_RECEIPTS = V6_ROOT / "receipts"
V6_RESULT = V6_RECEIPTS / "auth-handoff-v6-result.json"
HELPER = DELIVERY / "tools/loop_engineering/m3a_v6_source_freeze.py"
RUFF = DELIVERY / ".venv/bin/ruff"
PYTHON = Path("/Library/Frameworks/Python.framework/Versions/3.11/bin/python3")

SOURCE_BEGIN = "# BEGIN M3A_V6_PREPARATION_SOURCE\n"
SOURCE_END = "# END M3A_V6_PREPARATION_SOURCE\n"
EXPECTED_HEAD = "2f361fcddc0e63ae62ee62826e27b54bb8204c53"
EXPECTED_BRANCH = "main"
EXPECTED_DELIVERY = (0, 15, 176)
EXPECTED_TARGET = (0, 15, 74)
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
EXPECTED_V3_HELPER = (
    44684,
    "e4cf74b028e03d61493a8bc4cfebb7ffdc3b6ba72dbdbce8cdda7eb3338d614c",
)
EXPECTED_V4_HELPER = (47848, 'c3321a52ff2bfafe44bcec3a62eb19e78003eab46db4ef0a7b070d3894be7ff2')
EXPECTED_V5_PRECEDENT_HELPER = (63577, "b8407a30f79bf52e4696856116322c8105049200b57eb76d9c8b60891d54fb84")
V5_PRECEDENT_HELPER = DELIVERY / "tools/loop_engineering/m3a_v5_source_freeze.py"
V5_PRECEDENT_ROOT = BASE / "trusted-tools/m3-authentication-handoff-v5"
V5_PRECEDENT_DRIVER = V5_PRECEDENT_ROOT / "handoff-driver.py"
V5_PRECEDENT_RESULT = V5_PRECEDENT_ROOT / "receipts/auth-handoff-v5-result.json"
REQUIREMENT_V2 = DELIVERY / "docs/requirements/liveclip-agent-runtime-v2-acceptance-v2.md"
EXPECTED_REQUIREMENT_V2 = (8771, "31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400")
V5_PRECEDENT_FILES = {'handoff-driver.py': (31335, '8dc670fa2aca566f9107d51b0e291f8a7e6dc18ec7d45c30d0cab8b3869b506d'),
 'receipts/auth-handoff-v5-result.json': (261, '24f0729ab014db86903430394aee6927163063f164ab40d5481fc76cb088ece0'),
 'receipts/controller-acceptance-v5.json': (1295, 'e4067945105daa5413d1e2af72cdcd1598e1c59939487c9e4b688922dae0790b'),
 'receipts/final-index.json': (475, 'b0ea1d421e6eec8135485a4de5b36bd551cd489786058d589809edf5e855486d'),
 'receipts/self-check-result.json': (2832, 'e2ef09c2cb87eedf96cc8b5c301bc77f4235bd5a2652e28065b87cecf9170be5'),
 'receipts/source-receipt.json': (432, 'b6e12b972cf04d8158dfd985107a56b09b7d3140b916801dc6c4728e79db243d'),
 'receipts/writer-self-test.json': (84, '0be3d41e3bcdcee3b79bb20f9936414865667fc55ab4a48544e6b2dab114818d')}
V3_FAILURE = {
    "chunk": "7001f7",
    "elapsed_seconds": "0.05623454198939726",
    "exit": 1,
    "result": "ROOT_ONLY_ARGUMENT_COUNT_MISMATCH",
    "stderr_bytes": 624,
    "stderr_sha256": "a9a207454070b918c21aa99b8e45e8ce4d066f0b92f53a0f027b0870bcc7b74d",
    "stdout_bytes": 0,
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "tool_wall_seconds": "0.733792416",
}
V4_ROOT_EXECUTION = {
    "chunk": "0bf301",
    "exit": 0,
    "result": "M3A_V4_READY_FOR_CONTROLLER_REVIEW",
    "stderr_bytes": 0,
    "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "stdout_bytes": 964,
    "stdout_sha256": "2fa18b555dca33f4bff5061f4c272a5e0eac6186d2fd3462bae6c53742cc06f9",
    "wall_seconds": "1.472920666",
}
V4_ROOT_FILES: dict[str, tuple[int, str]] = {
    "handoff-driver.py": (
        28285,
        "5fc9247bf3798f91e3d9e1232aedd5930944ad47075e95ffe60c6f9acc9c30b2",
    ),
    "receipts/controller-acceptance-v4.json": (
        1249,
        "4a68168e89ab721b49b88b3d4c6a85e20fd5ff9ce6f31d25e3a1e98959fcb49d",
    ),
    "receipts/final-index.json": (
        475,
        "b93529d171eb4b406fc391ba703f0810efc688f70bed2eef02a0064e693fbffd",
    ),
    "receipts/self-check-result.json": (
        1935,
        "3a9d4034fa5d4f1190c94e8f9ff0d3cb69e10ac5a87e4bb2b9d231f792781034",
    ),
    "receipts/source-receipt.json": (
        432,
        "f226b8521985f29171045533a1e3f53175b84efe80f5aaf90bb35062464a3083",
    ),
    "receipts/writer-self-test.json": (
        84,
        "5703e6adb4a55660c4d0bbbed7b0b341d95231dccbf894a9a5dacac5e266a080",
    ),
}
EXPECTED_CANDIDATES = ('candidate.22BiM8pO',
 'candidate.3WBt3ldA',
 'candidate.5jh3bylk',
 'candidate.5nZWpynN',
 'candidate.CbYcDirN',
 'candidate.CrvNTqvL',
 'candidate.KWbe2iGW',
 'candidate.M4v94Rmv',
 'candidate.OlsWg1',
 'candidate.Q2vecg',
 'candidate.UU7EAiJG',
 'candidate.VoU5SVVl',
 'candidate.aw2oA4',
 'candidate.bSEqMEit',
 'candidate.bm4AWiof',
 'candidate.c79YYSLQ',
 'candidate.cQnaAbOf',
 'candidate.dygENR4n',
 'candidate.iyme1x_i',
 'candidate.jyq_n37h',
 'candidate.mRMO7MQ6',
 'candidate.o99gfxup',
 'candidate.oivrdV6U',
 'candidate.qaDKDWkQ',
 'candidate.vuDWtK0T',
 'candidate.xp23hqNY',
 'candidate.z6EbTJew')

V43_ROOT_FILES = {'candidate-driver.py': (517933, 'fa0f4340fdc5ae7093b807bd43c17d3f9a8c4f8efbe1f0bd57a249bee87814bc'),
 'receipts/controller-acceptance-v43.json': (17249,
                                             'b0ac531ff708d8c117e10efc79e1caa33925c4608a93dbd267e9f665654cde05'),
 'receipts/final-index.json': (2000, 'dc1cfdd133dc05e8d197ddc61c653e43e7e8326c9ea920574d26465f3b66e4e4'),
 'receipts/self-check-result.json': (6546, '47d7a55206b83e77f0f25871e674904be1a322801f8a1e8a6d0c94b02d31e05f'),
 'receipts/source-receipt.json': (524, '11208485b7c4184eafd32e380080c9efc001cbaaa67ccec7962695e873cbb405'),
 'receipts/successor-preparation-v43-result.json': (23850,
                                                    '7c2cf6fe2bff1be5a6369f79aae65ae85c2e96046d4335d77241c92fc4e8b7b3'),
 'receipts/writer-self-test.json': (72, '847b63ac13ae5f1ccae504fe9f244ded36253e9f30a261f34509f38a8f9d69f2')}

TARGET_FILES = {'repo/.loop/runs/20261015T231933Z-6eee7fff/events.jsonl': (144,
                                                            '63f229995c4575673e775418f520c76a4951e0a990364a35881f689e4426d79e',
                                                            420),
 'repo/.loop/runs/20261015T231933Z-6eee7fff/state.json': (12796,
                                                          '4800a39ea96cda89363b1f9f2e0dda2e7dc093a64ecb2531d98fa07f2848ee6d',
                                                          420),
 'repo/.loop/trusted/final-controller-acceptance-v43.json': (3913,
                                                             '8e92f8d63142313e70be4a15add0538e0e13a9e406cfcfc6f7e792ab5682a42a',
                                                             384),
 'successor-receipts/final-receipt-index.json': (18095,
                                                 'fc54928088059a084f0c998bac7b96addca4713b7c2d41c6cc13eb0c3477b0d3',
                                                 384),
 'successor-receipts/postacceptance-attempt-manifest.jsonl': (12183981,
                                                              'd657dd1f513b3a982fef52517355f845cbc7d6b135700d481e12b5b29ec45031',
                                                              384),
 'successor-receipts/postacceptance-final-index.json': (2731,
                                                        'a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8',
                                                        384),
 'successor-receipts/postacceptance-repository-manifest.jsonl': (6146002,
                                                                 'cdf949a84656807f9a538fca3d9fe45647a7fcf26246c651fd8db3a85a9e596e',
                                                                 384),
 'successor-receipts/successor-v43-controller-acceptance-offer.json': (5032,
                                                                       '95c783319e2f11b2b666d40a93e36ffdba3a484f38ddcc5b8075b9a24615ff48',
                                                                       384),
 'successor-receipts/successor-v43-controller-acceptance-transport.json': (1383,
                                                                           'd5b3b0dd6c66bff23aac430f4a9400c8ce7180c85d927ba72d82cdf38973ee72',
                                                                           384),
 'successor-receipts/successor-v43-policy-snapshot.json': (4827,
                                                           '47034cf37bd9e4dd9ce1764c909a36a692d9fee2288006105de99337d1ebd7ab',
                                                           384),
 'successor-receipts/successor-v43-preparation-bindings.json': (5412,
                                                                'a20c0fc550ef9602c30c3897087a75e6073839577cc3bfb976d8ec47f42b220a',
                                                                384),
 'successor-receipts/successor-v43-toolchain-snapshot.json': (4878,
                                                              '1942f05fc5686652004bb18842418ebd337d9dfaf53515319915e00a2782543d',
                                                              384),
 'successor-receipts/successor-v43-trusted-context.json': (4227,
                                                           'a7dfbf10610016990c08fadc091007bae24a8bc4eaa690f984d974a5a2bf3e0c',
                                                           384)}

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
ROOT_RECEIPT_FILES = {
    "controller-acceptance-v6.json",
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
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def pretty(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def root_final_index(
    *,
    acceptance_sha256: str,
    driver_sha256: str,
    root_argv_sha256: str,
    source_sha256: str,
) -> dict[str, Any]:
    return {
        "controller_acceptance_sha256": acceptance_sha256,
        "driver_sha256": driver_sha256,
        "format_version": 1,
        "phase": "M3A_V6_FINAL_INDEX",
        "result": "M3A_V6_READY_FOR_CONTROLLER_REVIEW",
        "root_argv_sha256": root_argv_sha256,
        "source_sha256": source_sha256,
    }


def validate_root_file_domain(file_names: set[str]) -> None:
    require(file_names == ROOT_RECEIPT_FILES, "ROOT_DOMAIN_MISMATCH")


def validate_root_receipt_values(
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
        acceptance_value["phase"] == "M3A_V6_CONTROLLER_ACCEPTANCE"
        and acceptance_value["result"] == "ACCEPTED_BEFORE_ROOT_CREATION",
        "ROOT_ACCEPTANCE_SCHEMA_MISMATCH",
    )
    require(
        acceptance_value["root"]
        == {
            "fixed_name": "m3-authentication-handoff-v6",
            "no_replace": True,
            "result_absent": True,
            "root_absent": True,
        },
        "ROOT_ACCEPTANCE_SCHEMA_MISMATCH",
    )
    require(
        acceptance_value["driver"]["sha256"] == expected_driver_sha256,
        "ROOT_ACCEPTANCE_SCHEMA_MISMATCH",
    )
    require(
        sha(compact(acceptance_value) + b"\n") == expected_acceptance_sha256,
        "CONTROLLER_ACCEPTANCE_MISMATCH",
    )
    expected_final = root_final_index(
        acceptance_sha256=expected_acceptance_sha256,
        driver_sha256=expected_driver_sha256,
        root_argv_sha256=expected_root_argv_sha256,
        source_sha256=expected_source_sha256,
    )
    require(final_value == expected_final, "ROOT_INDEX_SCHEMA_MISMATCH")
    require(
        sha(pretty(final_value)) == expected_final_index_sha256,
        "ROOT_INDEX_MISMATCH",
    )


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
    return {'bounds': {'diagnostic_bytes': 65536,
                'login_status_seconds': 30,
                'outer_seconds': 120,
                'sanitized_stdout_bytes': 4096},
     'budgets': {'destination': 1, 'handoff_invocation': 1, 'result': 1, 'root': 1},
     'candidate': {'candidate_count': 27,
                   'completed_tree': {'bytes': 967736903,
                                      'paths': 44355,
                                      'sha256': '268729fa276c2a400bcbabf881491b534ab81926b572a94b080675fc266ceaa3'},
                   'final_acceptance_sha256': '8e92f8d63142313e70be4a15add0538e0e13a9e406cfcfc6f7e792ab5682a42a',
                   'final_index_sha256': 'a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8',
                   'name': 'candidate.CbYcDirN',
                   'run_id': '20261015T231933Z-6eee7fff',
                   'sealed_receipt_index_sha256': 'fc54928088059a084f0c998bac7b96addca4713b7c2d41c6cc13eb0c3477b0d3'},
     'delivery': {'branch': 'main',
                  'candidate_inventory': [0, 15, 74],
                  'candidate_names_sha256': 'de2aee16e2338d8ec0f8fbb5ba03c7b0f1afcb1788c23e59d556a57cbd58bded',
                  'head': '2f361fcddc0e63ae62ee62826e27b54bb8204c53',
                  'inventory': [0, 15, 176]},
     'environment_names': ['HOME',
                           'TMPDIR',
                           'PATH',
                           'LANG',
                           'LC_ALL',
                           'PYTHONDONTWRITEBYTECODE',
                           'GIT_OPTIONAL_LOCKS',
                           '__CF_USER_TEXT_ENCODING'],
     'evidence': {'acceptance_requirement_v2_sha256': '31e967e04b3f9987e5c0a9ac00b809c215aed543f9da035c3a06e73ebc976400',
                  'acceptance_requirement_v3_sha256': '308fdc96f2c5ddaffb6d01c65ddc089958a5ba883ab2c00c986da38d5483ba00',
                  'architecture_sha256': '48d87ef5864adfa9f4eb7115055924713e64b1a9000c2ed17678bc84bc8c41ce',
                  'controller_transport_sha256': 'd5b3b0dd6c66bff23aac430f4a9400c8ce7180c85d927ba72d82cdf38973ee72',
                  'postacceptance_attempt_manifest_sha256': 'd657dd1f513b3a982fef52517355f845cbc7d6b135700d481e12b5b29ec45031',
                  'postacceptance_repository_manifest_sha256': 'cdf949a84656807f9a538fca3d9fe45647a7fcf26246c651fd8db3a85a9e596e',
                  'preparation_bindings_sha256': 'a20c0fc550ef9602c30c3897087a75e6073839577cc3bfb976d8ec47f42b220a',
                  'preparation_offer_sha256': '95c783319e2f11b2b666d40a93e36ffdba3a484f38ddcc5b8075b9a24615ff48',
                  'root_final_index_sha256': 'dc1cfdd133dc05e8d197ddc61c653e43e7e8326c9ea920574d26465f3b66e4e4',
                  'successor_policy_sha256': '47034cf37bd9e4dd9ce1764c909a36a692d9fee2288006105de99337d1ebd7ab',
                  'successor_toolchain_sha256': '1942f05fc5686652004bb18842418ebd337d9dfaf53515319915e00a2782543d',
                  'successor_trusted_context_sha256': 'a7dfbf10610016990c08fadc091007bae24a8bc4eaa690f984d974a5a2bf3e0c'},
     'formal_role_authority': False,
     'format_version': 1,
     'phase': 'M3A_V6_AUTH_HANDOFF',
     'pinned_status': {'argv': ['login', 'status'],
                       'binary_sha256': '12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de',
                       'binary_size': 245096256,
                       'child_channels': 'DEVNULL',
                       'timeout_seconds': 30},
     'privacy': {'child_channels': 'DEVNULL',
                 'credential_environment_variables': False,
                 'destination_observation': 'UNPROBED_EXCLUSIVE_GATE_INSIDE_HANDOFF',
                 'opaque_copy': True,
                 'protected_entry_omitted_before_metadata': True,
                 'raw_diagnostics': False,
                 'receipt_fields': ['copy_success',
                                    'destination_mode',
                                    'destination_owner_uid',
                                    'format_version',
                                    'login_status',
                                    'phase',
                                    'result',
                                    'sanitized_error'],
                 'secret_derived_metadata': False},
     'private_runtime': {'home_mode': '0700', 'owner_uid': 501, 'tmp_mode': '0700'},
     'run': {'code_cycle': 0,
             'cycle': 0,
             'events_sha256': '63f229995c4575673e775418f520c76a4951e0a990364a35881f689e4426d79e',
             'state': 'received',
             'state_sha256': '4800a39ea96cda89363b1f9f2e0dda2e7dc093a64ecb2531d98fa07f2848ee6d'},
     'v43': {'driver_sha256': 'fa0f4340fdc5ae7093b807bd43c17d3f9a8c4f8efbe1f0bd57a249bee87814bc',
             'final_acceptance_sha256': '8e92f8d63142313e70be4a15add0538e0e13a9e406cfcfc6f7e792ab5682a42a',
             'final_index_sha256': 'a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8',
             'preparation_result_sha256': '7c2cf6fe2bff1be5a6369f79aae65ae85c2e96046d4335d77241c92fc4e8b7b3'}}


def static_contract_validation(contract_payload: bytes) -> dict[str, Any]:
    expected = handoff_contract()
    require(contract_payload == compact(expected), "positive contract mismatch")
    require(json.loads(contract_payload) == expected, "contract decode mismatch")
    mutations = (
        ("phase", "M3A_V5_AUTH_HANDOFF"),
        ("formal_role_authority", True),
        ("candidate.name", "candidate.M4v94Rmv"),
        ("candidate.run_id", "20261014T214746Z-cd5796b8"),
        ("candidate.candidate_count", 24),
        ("candidate.final_index_sha256", "0" * 64),
        ("delivery.inventory", [0, 15, 175]),
        ("delivery.candidate_inventory", [0, 15, 73]),
        ("privacy.opaque_copy", False),
        ("privacy.destination_observation", "CONTROLLER_OBSERVED_ABSENT_ONCE_NOT_REPROBED"),
        ("privacy.protected_entry_omitted_before_metadata", False),
        ("privacy.secret_derived_metadata", True),
        ("privacy.child_channels", "PIPE"),
        ("budgets.handoff_invocation", 2),
        ("bounds.login_status_seconds", 31),
        ("evidence.architecture_sha256", "0" * 64),
        ("v43.final_index_sha256", "0" * 64),
    )
    negatives = 0
    for dotted, value in mutations:
        candidate = json.loads(json.dumps(expected)); target = candidate; parts = dotted.split(".")
        for part in parts[:-1]: target = target[part]
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


def driver_validate_root_source() -> str:
    return '''def validate_root(values: dict[str, str]) -> None:
    private_directory(ROOT)
    private_directory(RECEIPTS)
    private_directory(ROOT / "home")
    private_directory(ROOT / "tmp")
    require(set(os.listdir(ROOT)) == {"handoff-driver.py", "home", "receipts", "tmp"}, "ROOT_DOMAIN_MISMATCH")
    validate_root_file_domain(set(os.listdir(RECEIPTS)))
    require(not os.path.lexists(RESULT), "RESULT_ALREADY_EXISTS")
    self_payload, self_info = read_regular(DRIVER)
    require(sha(self_payload) == values["expected_self_sha"] and self_info.st_uid == CURRENT_UID and stat.S_IMODE(self_info.st_mode) == 0o600, "SELF_IDENTITY_MISMATCH")
    final_payload, _ = read_regular(RECEIPTS / "final-index.json")
    acceptance_payload, _ = read_regular(RECEIPTS / "controller-acceptance-v6.json")
    require(sha(final_payload) == values["expected_root_final_index_sha256"], "ROOT_INDEX_MISMATCH")
    require(sha(acceptance_payload) == values["expected_controller_acceptance_sha256"], "CONTROLLER_ACCEPTANCE_MISMATCH")
    final_value = json.loads(final_payload.decode("utf-8"))
    acceptance_value = json.loads(acceptance_payload.decode("utf-8"))
    validate_root_receipt_values(
        acceptance_value=acceptance_value,
        final_value=final_value,
        contract_value=HANDOFF_CONTRACT,
        expected_acceptance_sha256=values["expected_controller_acceptance_sha256"],
        expected_final_index_sha256=values["expected_root_final_index_sha256"],
        expected_driver_sha256=values["expected_self_sha"],
        expected_root_argv_sha256=final_value.get("root_argv_sha256", ""),
        expected_source_sha256=final_value.get("source_sha256", ""),
    )'''


def derive_driver(v2_payload: bytes) -> bytes:
    require((len(v2_payload), sha(v2_payload)) == EXPECTED_V2_DRIVER, "sealed V2 driver mismatch")
    text = v2_payload.decode("utf-8")
    token_replacements = (
        ("M3A_V2", "M3A_V6", 4),
        ("m3-authentication-handoff-v2", "m3-authentication-handoff-v6", 1),
        ("auth-handoff-v2-result.json", "auth-handoff-v6-result.json", 1),
        ("candidate.oivrdV6U", "candidate.CbYcDirN", 3),
        ("20261014T191719Z-0802b465", RUN_ID, 4),
        ("v39", "v43", 14),
        ("V39", "V43", 11),
    )
    for old, new, count in token_replacements:
        require(text.count(old) == count, f"transform count mismatch: {old}")
        text = text.replace(old, new)
    helper_payload = read_regular(HELPER)[0]
    root_schema_block = "\n".join((
        _python_assignment("ROOT_RECEIPT_FILES", ROOT_RECEIPT_FILES),
        _python_assignment("ROOT_ACCEPTANCE_KEYS", ROOT_ACCEPTANCE_KEYS),
        _python_assignment("ROOT_FINAL_INDEX_KEYS", ROOT_FINAL_INDEX_KEYS),
        function_source(helper_payload, "root_final_index").decode(),
        function_source(helper_payload, "validate_root_file_domain").decode(),
        function_source(helper_payload, "validate_root_receipt_values").decode(),
    ))
    replacements = {
        "EXPECTED_DELIVERY": _python_assignment("EXPECTED_DELIVERY", EXPECTED_DELIVERY),
        "EXPECTED_TARGET": _python_assignment("EXPECTED_TARGET", EXPECTED_TARGET),
        "EXPECTED_CANDIDATES": "EXPECTED_CANDIDATES = {" + ", ".join(repr(name) for name in EXPECTED_CANDIDATES) + "}",
        "V43_FILES": _python_assignment("V43_FILES", dict(V43_ROOT_FILES)),
        "TARGET_FILES": _python_assignment("TARGET_FILES", dict(TARGET_FILES)),
        "HANDOFF_CONTRACT": _python_assignment("HANDOFF_CONTRACT", handoff_contract()),
        "ROOT_FILES": root_schema_block,
        "validate_root": driver_validate_root_source(),
    }
    text = _replace_nodes(text, replacements)
    payload = text.encode("utf-8")
    compile(payload, "<m3a-v6-driver>", "exec", dont_inherit=True)
    return payload


def function_source(payload: bytes, name: str) -> bytes:
    text = payload.decode("utf-8")
    tree = ast.parse(text)
    offsets = _line_offsets(text)
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    require(len(matches) == 1, f"function count mismatch: {name}")
    start, end = _span(matches[0], offsets)
    return text[start:end].encode()


def static_driver_validation(precedent_payload: bytes, driver_payload: bytes) -> dict[str, Any]:
    tree = ast.parse(driver_payload); compile(driver_payload, "<m3a-v6-driver>", "exec", dont_inherit=True)
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    required = {"opaque_copy_state", "terminate_group", "login_status", "receipt", "root_final_index", "validate_private_runtime", "validate_root_file_domain", "validate_root_receipt_values", "validate_v43_and_target"}
    require(required <= functions, "required driver functions missing")
    require("validate_v40_and_target" not in functions, "stale V40 validator remains")
    require(driver_payload.count(b"M3A_V6_AUTH_HANDOFF") == 2, "active phase count mismatch")
    require(b"M3A_V5_AUTH_HANDOFF" not in driver_payload, "stale active phase remains")
    require(b"controller-acceptance-v5.json" not in driver_payload, "stale root receipt filename remains")
    require(b"controller-acceptance-v6.json" in driver_payload, "current root receipt filename missing")
    root_source = function_source(driver_payload, "validate_root")
    require(b"validate_root_receipt_values(" in root_source, "shared root validator missing")
    for forbidden in (b"loop-run", b"--last", b"resume_liveclip.sh"):
        require(forbidden not in driver_payload, "forbidden command surface")
    for name in ("validate_v43_and_target", "validate_private_runtime"):
        payload = function_source(driver_payload, name)
        require(b"AUTH_SOURCE" not in payload and b"AUTH_DESTINATION" not in payload and b"login_status(" not in payload, f"protected reference before handoff: {name}")
    equivalence = {}
    for name in ("opaque_copy_state", "terminate_group", "login_status", "receipt"):
        old = function_source(precedent_payload, name)
        new = function_source(driver_payload, name).replace(b"M3A_V6", b"M3A_V5")
        require(new == old, f"V5 source equivalence mismatch: {name}")
        equivalence[name] = sha(new)
    helper_payload = read_regular(HELPER)[0]; shared = {}
    for name in ("root_final_index", "validate_root_file_domain", "validate_root_receipt_values"):
        hs=function_source(helper_payload,name); ds=function_source(driver_payload,name)
        require(hs==ds, f"shared root schema mismatch: {name}"); shared[name]=sha(ds)
    opaque_tree=ast.parse(function_source(driver_payload,"opaque_copy_state"))
    calls=[node.func.id if isinstance(node.func,ast.Name) else node.func.attr for node in ast.walk(opaque_tree) if isinstance(node,ast.Call) and isinstance(node.func,(ast.Name,ast.Attribute))]
    for required_call in ("lstat","open","fstat","fsync","read","write"):
        require(required_call in calls, f"opaque operation missing: {required_call}")
    login_tree=ast.parse(function_source(driver_payload,"login_status"))
    login_text=function_source(driver_payload,"login_status")
    require(login_text.count(b"subprocess.DEVNULL") == 3 and b"shell=False" in login_text, "login child channel mismatch")
    require(any(isinstance(n,ast.Call) for n in ast.walk(login_tree)), "login child surface missing")
    receipt_keys={n.value for n in ast.walk(ast.parse(function_source(driver_payload,"receipt"))) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
    expected_keys=set(handoff_contract()["privacy"]["receipt_fields"]); require(expected_keys <= receipt_keys,"receipt fields mismatch")
    return {"ast_compile":"PASS","equivalent_v5_functions":equivalence,"opaque_operations":sorted(set(calls)&{"lstat","open","fstat","fsync","read","write"}),"receipt_fields":sorted(expected_keys),"shared_root_schema":shared}


def runtime_nonsecret_validation(driver_payload: bytes) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": "m3a_v6_driver_static_validation"}
    exec(  # noqa: S102 - exact derived bytes, hash-bound and compiled above
        compile(driver_payload, "<m3a-v6-driver>", "exec", dont_inherit=True), namespace
    )
    validator = namespace.get("validate_v43_and_target")
    require(callable(validator), "derived non-secret validator missing")
    validator()
    return {"authentication_location_probe": False, "login_status_launched": False, "result": "PASS", "validator": "validate_v43_and_target"}


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


def controller_acceptance(*, plan_payload: bytes, status_payload: bytes, source_payload: bytes, helper_payload: bytes, driver_payload: bytes, contract_payload: bytes) -> dict[str, Any]:
    return {
        "contract": {"canonical_bytes": len(contract_payload), "sha256": sha(contract_payload)},
        "documents": {"exec_plan": {"bytes": len(plan_payload), "sha256": sha(plan_payload)}, "status": {"bytes": len(status_payload), "sha256": sha(status_payload)}},
        "driver": {"bytes": len(driver_payload), "sha256": sha(driver_payload)}, "format_version": 1,
        "helper": {"bytes": len(helper_payload), "sha256": sha(helper_payload)},
        "phase": "M3A_V6_CONTROLLER_ACCEPTANCE", "result": "ACCEPTED_BEFORE_ROOT_CREATION",
        "root": {"fixed_name": V6_ROOT.name, "no_replace": True, "result_absent": True, "root_absent": True},
        "security": {"credential_blind_root_only": True, "destination_precondition": "UNPROBED_EXCLUSIVE_GATE_INSIDE_HANDOFF", "formal_role_authority": False, "login_status_during_root_only": False, "protected_entry_omitted_before_metadata": True},
        "source": {"bytes": len(source_payload), "sha256": sha(source_payload)},
        "target": {"candidate": TARGET.name, "candidate_count": len(EXPECTED_CANDIDATES), "final_provenance_sha256": "a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8", "run_id": RUN_ID},
    }


def static_acceptance_validation(acceptance: dict[str, Any], *, plan_payload: bytes, status_payload: bytes, source_payload: bytes, helper_payload: bytes, driver_payload: bytes, contract_payload: bytes) -> dict[str, Any]:
    expected=controller_acceptance(plan_payload=plan_payload,status_payload=status_payload,source_payload=source_payload,helper_payload=helper_payload,driver_payload=driver_payload,contract_payload=contract_payload)
    require(acceptance==expected,"positive acceptance mismatch")
    mutations=(("phase","M3A_V5_CONTROLLER_ACCEPTANCE"),("result","READY"),("target.candidate","candidate.M4v94Rmv"),("target.run_id","20261014T214746Z-cd5796b8"),("target.candidate_count",26),("target.final_provenance_sha256","0"*64),("security.credential_blind_root_only",False),("security.login_status_during_root_only",True),("security.destination_precondition","CONTROLLER_OBSERVED_ABSENT_ONCE_NOT_REPROBED"),("root.no_replace",False),("documents.exec_plan.sha256","0"*64),("driver.sha256","0"*64),("contract.sha256","0"*64))
    negatives=0
    for dotted,value in mutations:
        candidate=json.loads(json.dumps(expected)); target=candidate; parts=dotted.split(".")
        for part in parts[:-1]: target=target[part]
        target[parts[-1]]=value
        require(candidate!=expected and compact(candidate)!=compact(expected),f"negative fixture ineffective: {dotted}"); negatives+=1
    return {"positive":"PASS","negative_fixtures":negatives}


def static_root_schema_validation(
    *,
    acceptance: dict[str, Any],
    driver_sha256: str,
    root_argv_sha256: str,
    source_sha256: str,
    contract_value: dict[str, Any],
) -> dict[str, Any]:
    acceptance_sha256 = sha(compact(acceptance) + b"\n")
    final_value = root_final_index(
        acceptance_sha256=acceptance_sha256,
        driver_sha256=driver_sha256,
        root_argv_sha256=root_argv_sha256,
        source_sha256=source_sha256,
    )
    final_sha256 = sha(pretty(final_value))
    validate_root_file_domain(set(ROOT_RECEIPT_FILES))
    validate_root_receipt_values(
        acceptance_value=acceptance,
        final_value=final_value,
        contract_value=contract_value,
        expected_acceptance_sha256=acceptance_sha256,
        expected_final_index_sha256=final_sha256,
        expected_driver_sha256=driver_sha256,
        expected_root_argv_sha256=root_argv_sha256,
        expected_source_sha256=source_sha256,
    )

    negatives = 0

    def rejected(action: Any, label: str) -> None:
        nonlocal negatives
        try:
            action()
        except RuntimeError:
            negatives += 1
            return
        raise RuntimeError(f"root schema negative accepted: {label}")

    stale_v2_files = set(ROOT_RECEIPT_FILES)
    stale_v2_files.remove("controller-acceptance-v6.json")
    stale_v2_files.add("controller-acceptance-v2.json")
    rejected(lambda: validate_root_file_domain(stale_v2_files), "stale V2 receipt filename")
    stale_v5_files = set(ROOT_RECEIPT_FILES)
    stale_v5_files.remove("controller-acceptance-v6.json")
    stale_v5_files.add("controller-acceptance-v5.json")
    rejected(lambda: validate_root_file_domain(stale_v5_files), "stale V5 receipt filename")

    stale_v4_files = set(ROOT_RECEIPT_FILES)
    stale_v4_files.remove("controller-acceptance-v6.json")
    stale_v4_files.add("controller-acceptance-v4.json")
    rejected(lambda: validate_root_file_domain(stale_v4_files), "stale V4 receipt filename")

    final_mutations: list[tuple[str, dict[str, Any]]] = []
    verdict_value = dict(final_value)
    verdict_value["verdict"] = verdict_value.pop("result")
    final_mutations.append(("V4 verdict key", verdict_value))
    contract_hash_value = dict(final_value)
    contract_hash_value["contract_sha256"] = sha(compact(contract_value))
    final_mutations.append(("V4 contract hash key", contract_hash_value))
    missing_result = dict(final_value)
    missing_result.pop("result")
    final_mutations.append(("missing result", missing_result))
    stale_phase = dict(final_value)
    stale_phase["phase"] = "M3A_V4_FINAL_INDEX"
    final_mutations.append(("stale final phase", stale_phase))
    for label, mutated_final in final_mutations:
        rejected(
            lambda mutated_final=mutated_final: validate_root_receipt_values(
                acceptance_value=acceptance,
                final_value=mutated_final,
                contract_value=contract_value,
                expected_acceptance_sha256=acceptance_sha256,
                expected_final_index_sha256=final_sha256,
                expected_driver_sha256=driver_sha256,
                expected_root_argv_sha256=root_argv_sha256,
                expected_source_sha256=source_sha256,
            ),
            label,
        )

    stale_acceptance = json.loads(json.dumps(acceptance))
    stale_acceptance["phase"] = "M3A_V4_CONTROLLER_ACCEPTANCE"
    rejected(
        lambda: validate_root_receipt_values(
            acceptance_value=stale_acceptance,
            final_value=final_value,
            contract_value=contract_value,
            expected_acceptance_sha256=acceptance_sha256,
            expected_final_index_sha256=final_sha256,
            expected_driver_sha256=driver_sha256,
            expected_root_argv_sha256=root_argv_sha256,
            expected_source_sha256=source_sha256,
        ),
        "stale acceptance phase",
    )
    return {
        "final_index": {"bytes": len(pretty(final_value)), "sha256": final_sha256},
        "negative_fixtures": negatives,
        "positive": "PASS",
        "receipt_files": sorted(ROOT_RECEIPT_FILES),
    }


def validate_nonsecret_evidence() -> dict[str, Any]:
    validate_git(DELIVERY, EXPECTED_DELIVERY); validate_git(TARGET_REPO, EXPECTED_TARGET)
    exact_file(ARCHITECTURE, EXPECTED_ARCHITECTURE); exact_file(REQUIREMENT, EXPECTED_REQUIREMENT); exact_file(REQUIREMENT_V2, EXPECTED_REQUIREMENT_V2)
    exact_file(V2_DRIVER, EXPECTED_V2_DRIVER, 0o600); exact_file(V3_HELPER, EXPECTED_V3_HELPER); exact_file(V4_HELPER, EXPECTED_V4_HELPER)
    exact_file(V5_PRECEDENT_HELPER, EXPECTED_V5_PRECEDENT_HELPER)
    private_directory(V5_PRECEDENT_ROOT)
    for relative,expected in V5_PRECEDENT_FILES.items(): exact_file(V5_PRECEDENT_ROOT/relative,expected,0o600)
    precedent=read_regular(V5_PRECEDENT_DRIVER)[0]
    require(b"candidate.M4v94Rmv" in precedent and b"20261014T214746Z-cd5796b8" in precedent,"V5 precedent binding missing")
    require(b"candidate.CbYcDirN" not in precedent and RUN_ID.encode() not in precedent,"V5 precedent illegally reusable")
    private_directory(V43_ROOT)
    require(set(os.listdir(V43_ROOT))=={"candidate-driver.py","home","receipts","tmp"},"V43 root domain mismatch")
    for relative,expected in V43_ROOT_FILES.items(): exact_file(V43_ROOT/relative,expected,0o600)
    private_directory(TARGET)
    for relative,(size,digest,mode) in TARGET_FILES.items(): exact_file(TARGET/relative,(size,digest),mode)
    state=json.loads((RUN/"state.json").read_text(encoding="utf-8"))
    require(state.get("state")=="received" and state.get("cycle")==0 and state.get("code_cycle")==0 and state.get("coder_session_id") is None and state.get("last_error") is None and state.get("artifacts")=={} and state.get("command_results")==[],"run not pristine")
    candidates=tuple(sorted(path.name for path in BASE.iterdir() if path.name.startswith("candidate.") and path.is_dir() and not path.is_symlink()))
    require(candidates==EXPECTED_CANDIDATES,"candidate set mismatch")
    require(not V6_ROOT.exists() and not V6_ROOT.is_symlink(),"V6 root must be absent")
    require(not V6_RESULT.exists() and not V6_RESULT.is_symlink(),"V6 result must be absent")
    require(not (V43_ROOT/"receipts/final-controller-acceptance-v43-result.json").exists(),"V43 final root result exists")
    require(not (V43_ROOT/"receipts/auth-handoff-v43-result.json").exists(),"V43 auth result exists")
    process=validate_process_absence()
    return {"architecture":"PASS","candidates":len(candidates),"delivery_inventory":list(status_counts(DELIVERY)),"destination_observation":"UNPROBED","process_absence":process,"requirements":"PASS","root_absent":True,"run_pristine":True,"target_inventory":list(status_counts(TARGET_REPO)),"v43_evidence":"PASS","v5_nonreuse":"PASS","v6_result_absent":True}


def validate_v43_closure_documents(plan_payload: bytes, status_payload: bytes) -> dict[str, Any]:
    required=("candidate.CbYcDirN",RUN_ID,"a87524d4180ef07115d336b640cb4e3513ad73e92cf5a239e7ebd6e61a6b54c8","268729fa276c2a400bcbabf881491b534ab81926b572a94b080675fc266ceaa3","BLOCKED_FRESH_M3A_V6_ROOT_REQUIRED","m3-authentication-handoff-v6")
    for label,payload in (("plan",plan_payload),("status",status_payload)):
        text=payload.decode("utf-8")
        for value in required: require(value in text,f"V43 closure missing from {label}")
    return {"documents":["exec_plan","status"],"result":"PASS"}


def validate_v5_nonreuse_documents(plan_payload: bytes, status_payload: bytes) -> dict[str, Any]:
    required=(EXPECTED_V5_PRECEDENT_HELPER[1],"candidate.M4v94Rmv","20261014T214746Z-cd5796b8","consumed","non-reusable")
    for label,payload in (("plan",plan_payload),("status",status_payload)):
        text=payload.decode("utf-8")
        for value in required: require(value in text,f"V5 non-reuse missing from {label}")
    return {"documents":["exec_plan","status"],"result":"PASS"}


def validate_process_absence() -> dict[str, Any]:
    result=subprocess.run(["/bin/ps","-axo","command="],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,check=False,env={"PATH":"/usr/bin:/bin","LANG":"C","LC_ALL":"C"})
    require(result.returncode==0 and not result.stderr,"process audit failed")
    lines=result.stdout.decode("utf-8","replace").splitlines()
    prohibited: list[str] = []
    for line in lines:
        try:
            argv = shlex.split(line)
        except ValueError:
            continue
        if not argv:
            continue
        executable = Path(argv[0]).name
        is_loop = executable == "make" and len(argv) > 1 and argv[1] == "loop-run"
        is_resume = executable == "resume_liveclip.sh"
        is_handoff = any(Path(value).name == "handoff-driver.py" for value in argv) and "auth-handoff" in argv
        if is_loop or is_resume or is_handoff:
            prohibited.append(line)
    require(not prohibited,"prohibited process present")
    return {"checked":["exact handoff argv","exact loop-run argv","exact resume argv"],"result":"PASS"}


def nonsecret_snapshot() -> str:
    records=[]
    for path in (PLAN,STATUS,HELPER,V5_PRECEDENT_HELPER,V5_PRECEDENT_DRIVER,V43_ROOT/"candidate-driver.py",TARGET/"successor-receipts/postacceptance-final-index.json",RUN/"state.json",RUN/"events.jsonl"):
        payload,_=read_regular(path); records.append((str(path),len(payload),sha(payload)))
    records.append(("delivery_status",len(git_capture(DELIVERY,["status","--short","--untracked-files=all"])),sha(git_capture(DELIVERY,["status","--short","--untracked-files=all"]))))
    records.append(("target_status",len(git_capture(TARGET_REPO,["status","--short","--untracked-files=all"])),sha(git_capture(TARGET_REPO,["status","--short","--untracked-files=all"]))))
    records.append(("v6_root_absent",not V6_ROOT.exists() and not V6_ROOT.is_symlink()))
    return sha(compact(records))


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
    require(not V6_ROOT.exists() and not V6_ROOT.is_symlink(), "V6 root already exists")


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
import sys
from pathlib import Path

HELPER = Path({str(HELPER)!r})
EXPECTED_HELPER_SIZE = {helper_size}
EXPECTED_HELPER_SHA256 = {helper_sha!r}
payload = HELPER.read_bytes()
if len(payload) != EXPECTED_HELPER_SIZE or hashlib.sha256(payload).hexdigest() != EXPECTED_HELPER_SHA256:
    raise RuntimeError("M3A-v6 helper identity mismatch")
spec = importlib.util.spec_from_file_location("m3a_v6_source_freeze", HELPER)
if spec is None or spec.loader is None:
    raise RuntimeError("M3A-v6 helper loader unavailable")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if sys.argv[:2] != ["-c", "--"] or len(sys.argv) != 20:
    raise RuntimeError("M3A-v6 Python -c argv shape mismatch")
module.root_only(sys.argv[2:])
'''
    payload = source.encode()
    compile(payload, "<m3a-v5-source>", "exec", dont_inherit=True)
    return payload


def python_c_argv_validation() -> dict[str, Any]:
    probe = "import json,sys;print(json.dumps(sys.argv,separators=(',',':')))"
    result = subprocess.run(  # noqa: S603 - pinned Python and fixed non-secret probe argv
        [str(PYTHON), "-c", probe, "--", "sentinel-a", "sentinel-b"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
        env={
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    require(result.returncode == 0 and not result.stderr, "Python -c argv probe failed")
    observed = json.loads(result.stdout)
    expected = ["-c", "--", "sentinel-a", "sentinel-b"]
    require(observed == expected, "real Python -c argv shape mismatch")
    return {
        "observed": observed,
        "result": "PASS",
        "source_slice": "sys.argv[2:]",
        "stdout_sha256": sha(result.stdout),
    }


def derive_all(plan_payload: bytes, helper_payload: bytes) -> dict[str, Any]:
    source_payload=extract_source(plan_payload); expected_source=make_source(len(helper_payload),sha(helper_payload))
    require(source_payload==expected_source,"embedded source mismatch"); require(b"module.root_only(sys.argv[2:])" in source_payload,"argv slice missing")
    v2_payload=exact_file(V2_DRIVER,EXPECTED_V2_DRIVER,0o600); precedent_payload=exact_file(V5_PRECEDENT_DRIVER,V5_PRECEDENT_FILES["handoff-driver.py"],0o600)
    driver_payload=derive_driver(v2_payload); contract_payload=compact(handoff_contract())
    return {"source":source_payload,"driver":driver_payload,"contract":contract_payload,"contract_validation":static_contract_validation(contract_payload),"driver_validation":static_driver_validation(precedent_payload,driver_payload),"runtime_nonsecret_validation":runtime_nonsecret_validation(driver_payload),"ruff":ruff_validation(driver_payload),"python_c_argv":python_c_argv_validation()}


def _identity(path: Path) -> dict[str, Any]:
    payload, info = read_regular(path)
    return {
        "bytes": len(payload),
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "sha256": sha(payload),
        "uid": info.st_uid,
    }


def root_only(argv: list[str]) -> None:
    values = parse_args(argv)
    validate_root_environment()
    require(Path(values["--plan"]) == PLAN, "plan path mismatch")
    require(Path(values["--status"]) == STATUS, "status path mismatch")
    plan_payload = exact_file(PLAN, (PLAN.stat().st_size, values["--expected-plan-sha256"]))
    status_payload = exact_file(STATUS, (STATUS.stat().st_size, values["--expected-status-sha256"]))
    validate_v43_closure_documents(plan_payload, status_payload)
    validate_v5_nonreuse_documents(plan_payload, status_payload)
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

    root_argv = [str(PYTHON), "-c", source_payload.decode(), "--", *argv]
    root_argv_payload = compact(root_argv)
    acceptance_sha256 = sha(compact(acceptance) + b"\n")
    final_index = root_final_index(
        acceptance_sha256=acceptance_sha256,
        driver_sha256=sha(driver_payload),
        root_argv_sha256=sha(root_argv_payload),
        source_sha256=sha(source_payload),
    )
    root_schema_validation = static_root_schema_validation(
        acceptance=acceptance,
        driver_sha256=sha(driver_payload),
        root_argv_sha256=sha(root_argv_payload),
        source_sha256=sha(source_payload),
        contract_value=handoff_contract(),
    )
    require(
        root_schema_validation["final_index"]
        == {"bytes": len(pretty(final_index)), "sha256": sha(pretty(final_index))},
        "root schema precreation mismatch",
    )
    os.mkdir(V6_ROOT, 0o700)
    try:
        os.mkdir(V6_ROOT / "home", 0o700)
        os.mkdir(V6_ROOT / "tmp", 0o700)
        os.mkdir(V6_RECEIPTS, 0o700)
        write_exclusive(V6_DRIVER, driver_payload)
        write_exclusive(V6_RECEIPTS / "controller-acceptance-v6.json", compact(acceptance) + b"\n")
        write_exclusive(
            V6_RECEIPTS / "source-receipt.json",
            pretty(
                {
                    "contract_sha256": sha(contract_payload),
                    "driver_sha256": sha(driver_payload),
                    "format_version": 1,
                    "helper_sha256": sha(helper_payload),
                    "phase": "M3A_V6_SOURCE_RECEIPT",
                    "result": "PASS",
                    "source_sha256": sha(source_payload),
                }
            ),
        )
        write_exclusive(
            V6_RECEIPTS / "writer-self-test.json",
            pretty({"format_version": 1, "phase": "M3A_V6_WRITER_SELF_TEST", "result": "PASS"}),
        )
        self_check = {
            "acceptance_validation": acceptance_validation,
            "driver_validation": derived["driver_validation"],
            "runtime_nonsecret_validation": derived["runtime_nonsecret_validation"],
            "contract_validation": derived["contract_validation"],
            "evidence": evidence,
            "format_version": 1,
            "phase": "M3A_V6_SELF_CHECK",
            "result": "PASS",
            "root_schema_validation": root_schema_validation,
            "ruff": derived["ruff"],
            "security": {
                "authentication_location_probe": False,
                "credential_blind": True,
                "destination_reprobe": False,
                "login_status_launched": False,
            },
        }
        write_exclusive(V6_RECEIPTS / "self-check-result.json", pretty(self_check))
        write_exclusive(V6_RECEIPTS / "final-index.json", pretty(final_index))
        for directory in (V6_RECEIPTS, V6_ROOT / "home", V6_ROOT / "tmp", V6_ROOT):
            sync_directory(directory)
    except BaseException:
        sync_directory(V6_ROOT)
        raise

    files = {
        "candidate_driver": _identity(V6_DRIVER),
        "controller_acceptance": _identity(V6_RECEIPTS / "controller-acceptance-v6.json"),
        "final_index": _identity(V6_RECEIPTS / "final-index.json"),
        "self_check": _identity(V6_RECEIPTS / "self-check-result.json"),
        "source_receipt": _identity(V6_RECEIPTS / "source-receipt.json"),
        "writer_self_test": _identity(V6_RECEIPTS / "writer-self-test.json"),
    }
    sys.stdout.buffer.write(
        compact(
            {
                "files": files,
                "phase": "M3A_V6_ROOT_ONLY",
                "result": "M3A_V6_READY_FOR_CONTROLLER_REVIEW",
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
    plan_payload=read_regular(PLAN)[0]; status_payload=read_regular(STATUS)[0]; helper_payload=read_regular(HELPER)[0]
    v43_closure_validation=validate_v43_closure_documents(plan_payload,status_payload); v5_nonreuse_validation=validate_v5_nonreuse_documents(plan_payload,status_payload)
    derived=derive_all(plan_payload,helper_payload); contract_payload=derived["contract"]
    acceptance=controller_acceptance(plan_payload=plan_payload,status_payload=status_payload,source_payload=derived["source"],helper_payload=helper_payload,driver_payload=derived["driver"],contract_payload=contract_payload)
    acceptance_validation=static_acceptance_validation(acceptance,plan_payload=plan_payload,status_payload=status_payload,source_payload=derived["source"],helper_payload=helper_payload,driver_payload=derived["driver"],contract_payload=contract_payload)
    evidence=validate_nonsecret_evidence(); acceptance_json=compact(acceptance).decode()
    commands=command_identities(source_payload=derived["source"],plan_sha=sha(plan_payload),status_sha=sha(status_payload),helper_sha=sha(helper_payload),driver_sha=sha(derived["driver"]),contract_sha=sha(contract_payload),acceptance_json=acceptance_json)
    root_schema=static_root_schema_validation(acceptance=acceptance,driver_sha256=sha(derived["driver"]),root_argv_sha256=commands["argv"]["sha256"],source_sha256=sha(derived["source"]),contract_value=handoff_contract())
    gates=("baseline_documents","unique_source","helper_ast_compile","driver_ast_compile","ruff_fbs","opaque_copy_equivalence","termination_equivalence","login_status_equivalence","receipt_equivalence","root_schema_positive","root_schema_negatives","contract_positive","contract_negatives","acceptance_positive","acceptance_negatives","v5_nonreuse","v43_root_evidence","target_binding","pristine_run","candidate_set","delivery_inventory","candidate_inventory","process_absence","protected_omission","credential_blind_validation","root_result_absence","python_c_shape","argv_identity","vector_identity","payload_identity","outer_launch_identity","formal_separation")
    require(len(gates)==32,"gate count mismatch")
    return {"acceptance":{"bytes_no_lf":len(compact(acceptance)),"bytes_with_lf":len(compact(acceptance))+1,"sha256_no_lf":sha(compact(acceptance)),"sha256_with_lf":sha(compact(acceptance)+b"\n")},"acceptance_validation":acceptance_validation,"commands":commands,"contract":{"bytes":len(contract_payload),"sha256":sha(contract_payload)},"contract_validation":derived["contract_validation"],"documents":{"exec_plan":{"bytes":len(plan_payload),"sha256":sha(plan_payload)},"status":{"bytes":len(status_payload),"sha256":sha(status_payload)}},"driver":{"bytes":len(derived["driver"]),"sha256":sha(derived["driver"])},"driver_validation":derived["driver_validation"],"evidence":evidence,"gate_count":len(gates),"gates":list(gates),"helper":{"bytes":len(helper_payload),"sha256":sha(helper_payload)},"ruff":derived["ruff"],"python_c_argv":derived["python_c_argv"],"root_schema_validation":root_schema,"runtime_nonsecret_validation":derived["runtime_nonsecret_validation"],"source":{"bytes":len(derived["source"]),"sha256":sha(derived["source"])},"v43_closure_validation":v43_closure_validation,"v5_nonreuse_validation":v5_nonreuse_validation}


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument("command",choices=("validate",)); args=parser.parse_args()
    if args.command=="validate":
        before=nonsecret_snapshot(); value=validate_design(); after=nonsecret_snapshot(); require(before==after,"no-write snapshot mismatch")
        value["no_write"]={"after":after,"before":before,"result":"PASS"}; sys.stdout.buffer.write(compact(value)+b"\n")


if __name__ == "__main__":
    main()
