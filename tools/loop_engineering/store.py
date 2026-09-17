from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .contracts import LoopState, RunState

RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
ALLOWED_TRANSITIONS = {
    LoopState.RECEIVED: {LoopState.PLANNING, LoopState.BLOCKED},
    LoopState.PLANNING: {LoopState.CODING, LoopState.REWORK_PLAN, LoopState.BLOCKED},
    LoopState.CODING: {LoopState.REVIEWING, LoopState.BLOCKED},
    LoopState.REVIEWING: {LoopState.TEST_PLANNING, LoopState.REWORK_CODE, LoopState.BLOCKED},
    LoopState.TEST_PLANNING: {LoopState.RUNNING, LoopState.BLOCKED},
    LoopState.RUNNING: {LoopState.FINAL_GATE, LoopState.REWORK_CODE, LoopState.BLOCKED},
    LoopState.FINAL_GATE: {
        LoopState.DONE,
        LoopState.REWORK_PLAN,
        LoopState.REWORK_CODE,
        LoopState.BLOCKED,
    },
    LoopState.REWORK_PLAN: {LoopState.PLANNING, LoopState.BLOCKED},
    LoopState.REWORK_CODE: {LoopState.CODING, LoopState.BLOCKED},
    LoopState.DONE: set(),
    LoopState.BLOCKED: set(),
}


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def new_id(hex_chars: int = 8) -> str:
    now = utc_now()
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(hex_chars // 2)}"


def atomic_json(path: Path, value: dict[str, Any], *, overwrite: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.run_root = self.root / ".loop" / "runs"

    def path(self, run_id: str) -> Path:
        if not RUN_ID.fullmatch(run_id):
            raise ValueError("invalid run id")
        return self.run_root / run_id

    def create(self, requirement: str, base_sha: str) -> RunState:
        if not requirement or len(requirement.encode("utf-8")) > 1_000_000:
            raise ValueError("requirement is empty or oversized")
        if re.fullmatch(r"[0-9a-f]{40,64}", base_sha) is None:
            raise ValueError("invalid base SHA")
        run_id = new_id()
        path = self.path(run_id)
        path.mkdir(parents=True, exist_ok=False)
        state = RunState(run_id=run_id, requirement=requirement, base_sha=base_sha)
        self.save(state)
        self.event(state, "run.created", {"base_sha": base_sha})
        return state

    def load(self, run_id: str) -> RunState:
        try:
            value = json.loads((self.path(run_id) / "state.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("run state is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("run state must be a JSON object")
        return RunState.from_dict(value)

    def save(self, state: RunState) -> None:
        atomic_json(self.path(state.run_id) / "state.json", state.to_dict())

    def transition(self, state: RunState, target: LoopState, reason: str) -> None:
        previous = state.state
        if target not in ALLOWED_TRANSITIONS[previous]:
            raise ValueError(f"invalid loop transition: {previous.value} -> {target.value}")
        state.state = target
        self.save(state)
        self.event(
            state,
            "state.changed",
            {"from": previous.value, "to": target.value, "reason": reason},
        )

    def event(self, state: RunState, kind: str, payload: dict[str, Any]) -> None:
        path = self.path(state.run_id) / "events.jsonl"
        event = {
            "ts": utc_now().isoformat().replace("+00:00", "Z"),
            "kind": kind,
            "state": state.state.value,
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def artifact(self, state: RunState, role: str, value: dict[str, Any]) -> Path:
        role_dir = self.path(state.run_id) / "artifacts" / role
        role_dir.mkdir(parents=True, exist_ok=True)
        index = len(state.artifacts.get(role, [])) + 1
        while (role_dir / f"{index:03d}.json").exists():
            index += 1
        path = role_dir / f"{index:03d}.json"
        atomic_json(path, value, overwrite=False)
        relative = str(path.relative_to(self.root))
        state.artifacts.setdefault(role, []).append(relative)
        self.save(state)
        self.event(state, "artifact.recorded", {"role": role, "path": relative})
        return path


def fingerprint_worktree(root: Path) -> str:
    import subprocess

    result = subprocess.run(
        [
            "git",
            "diff",
            "--binary",
            "HEAD",
            "--",
            ".",
            ":(exclude)qa/pipeline.jsonl",
            ":(exclude)qa/test-report.md",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    untracked = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            ".",
            ":(exclude).loop/**",
            ":(exclude)qa/pipeline.jsonl",
            ":(exclude)qa/test-report.md",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )
    digest = hashlib.sha256(result.stdout)
    for raw_path in sorted(value for value in untracked.stdout.split(b"\0") if value):
        path = root / os.fsdecode(raw_path)
        digest.update(raw_path)
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            _update_hash_from_file(digest, path)
    return digest.hexdigest()


def head_sha(root: Path) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def file_identity(path: Path) -> str:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        return f"symlink:{os.readlink(path)}"
    if not stat.S_ISREG(metadata.st_mode):
        return f"mode:{metadata.st_mode}"
    digest = hashlib.sha256()
    _update_hash_from_file(digest, path)
    return f"regular:{metadata.st_mode}:{metadata.st_size}:{digest.hexdigest()}"


def snapshot_files(paths: list[Path]) -> dict[str, str]:
    return {str(path): file_identity(path) for path in paths if path.exists() or path.is_symlink()}


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _update_hash_from_file(digest: Any, path: Path) -> None:
    with path.open("rb") as handle:
        while chunk := handle.read(1_048_576):
            digest.update(chunk)
