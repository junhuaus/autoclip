from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

SESSION_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class Role(StrEnum):
    PLANNER = "planner"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    GATEWAY = "gateway"


class LoopState(StrEnum):
    RECEIVED = "received"
    PLANNING = "planning"
    CODING = "coding"
    REVIEWING = "reviewing"
    TEST_PLANNING = "test_planning"
    RUNNING = "running"
    FINAL_GATE = "final_gate"
    REWORK_PLAN = "rework_plan"
    REWORK_CODE = "rework_code"
    DONE = "done"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CommandResult:
    run_id: str
    command_id: str
    argv: list[str]
    exit_code: int | None
    status: str
    duration_seconds: float
    head_sha: str
    worktree_fingerprint: str
    post_head_sha: str
    post_worktree_fingerprint: str
    toolchain_fingerprint: str
    post_toolchain_fingerprint: str
    execution_source_fingerprint: str
    source_path: str
    execution_path: str
    log_path: str
    log_identity: str
    qa_id: str


@dataclass
class RunState:
    run_id: str
    requirement: str
    base_sha: str
    state: LoopState = LoopState.RECEIVED
    cycle: int = 0
    code_cycle: int = 0
    coder_session_id: str | None = None
    artifacts: dict[str, list[str]] = field(default_factory=dict)
    command_results: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunState:
        expected = {
            "run_id",
            "requirement",
            "base_sha",
            "state",
            "cycle",
            "code_cycle",
            "coder_session_id",
            "artifacts",
            "command_results",
            "last_error",
        }
        if set(value) != expected:
            raise ValueError("run state has an unexpected field set")
        copy = dict(value)
        run_id = copy["run_id"]
        requirement = copy["requirement"]
        base_sha = copy["base_sha"]
        if (
            not isinstance(run_id, str)
            or re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", run_id) is None
        ):
            raise ValueError("run state has an invalid run ID")
        if not isinstance(requirement, str) or not requirement or len(requirement) > 1_000_000:
            raise ValueError("run state has an invalid requirement")
        if not isinstance(base_sha, str) or re.fullmatch(r"[0-9a-f]{40,64}", base_sha) is None:
            raise ValueError("run state has an invalid base SHA")
        for counter in ("cycle", "code_cycle"):
            if (
                not isinstance(copy[counter], int)
                or isinstance(copy[counter], bool)
                or copy[counter] < 0
            ):
                raise ValueError(f"run state has an invalid {counter}")
        session = copy["coder_session_id"]
        if session is not None and (
            not isinstance(session, str) or SESSION_ID_PATTERN.fullmatch(session) is None
        ):
            raise ValueError("run state has an invalid Coder session ID")
        artifacts = copy["artifacts"]
        if not isinstance(artifacts, dict) or not all(
            isinstance(role, str)
            and isinstance(paths, list)
            and all(isinstance(path, str) for path in paths)
            for role, paths in artifacts.items()
        ):
            raise ValueError("run state has invalid artifact references")
        results = copy["command_results"]
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise ValueError("run state has invalid command results")
        if copy["last_error"] is not None and not isinstance(copy["last_error"], str):
            raise ValueError("run state has an invalid last error")
        try:
            copy["state"] = LoopState(copy["state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("run state has an invalid state") from exc
        return cls(**copy)
