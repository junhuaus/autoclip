from __future__ import annotations

import json
import re
import shlex
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import LoopConfig
from .store import file_identity, fingerprint_worktree, head_sha


@dataclass(frozen=True)
class GateDecision:
    passed: bool
    route: str
    reasons: tuple[str, ...]


def blocking_findings(review: dict[str, Any]) -> list[dict[str, Any]]:
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        return [{"severity": "P0", "summary": "review findings are malformed"}]
    return [
        finding
        for finding in findings
        if isinstance(finding, dict) and finding.get("severity") in {"P0", "P1"}
    ]


def evaluate_gateway(
    config: LoopConfig,
    review: dict[str, Any],
    gateway: dict[str, Any],
    command_results: list[dict[str, Any]],
    *,
    current_head: str | None = None,
    current_worktree: str | None = None,
    current_toolchain: str | None = None,
    verify_files: bool = True,
) -> GateDecision:
    reasons: list[str] = []
    blockers = blocking_findings(review)
    if blockers:
        reasons.append(f"review has {len(blockers)} unresolved P0/P1 finding(s)")

    latest: dict[str, dict[str, Any]] = {}
    for result in command_results:
        command_id = result.get("command_id")
        if isinstance(command_id, str):
            latest[command_id] = result
    required = [item for item in config.commands.values() if item.required_for_final]
    for command in required:
        command_result = latest.get(command.command_id)
        if command_result is None:
            reasons.append(f"required command not run: {command.command_id}")
        elif command_result.get("status") != "PASS":
            reasons.append(f"required command did not pass: {command.command_id}")
        else:
            if command_result.get("argv") != list(command.argv):
                reasons.append(
                    f"required command argv does not match allowlist: {command.command_id}"
                )
            if command_result.get("exit_code") != 0:
                reasons.append(f"required command PASS has nonzero exit: {command.command_id}")
            if command_result.get("head_sha") != command_result.get(
                "post_head_sha"
            ) or command_result.get("worktree_fingerprint") != command_result.get(
                "post_worktree_fingerprint"
            ):
                reasons.append(
                    f"required command mutated its evidence worktree: {command.command_id}"
                )
            if command_result.get("toolchain_fingerprint") != command_result.get(
                "post_toolchain_fingerprint"
            ):
                reasons.append(f"required command toolchain mutated: {command.command_id}")
            if verify_files:
                reasons.extend(_verify_command_evidence(config, command, command_result))

    evidence = [latest[item.command_id] for item in required if item.command_id in latest]
    heads = {item.get("head_sha") for item in evidence}
    fingerprints = {item.get("worktree_fingerprint") for item in evidence}
    toolchains = {item.get("toolchain_fingerprint") for item in evidence}
    if len(heads) > 1 or len(fingerprints) > 1 or len(toolchains) > 1:
        reasons.append("required command evidence is stale across different worktrees")
    current_head = current_head or head_sha(config.root)
    current_worktree = current_worktree or fingerprint_worktree(config.root)
    if evidence and (heads != {current_head} or fingerprints != {current_worktree}):
        reasons.append("required command evidence does not match the current worktree")
    if evidence and current_toolchain is not None and toolchains != {current_toolchain}:
        reasons.append("required command evidence does not match the trusted toolchain")

    verdict = gateway.get("verdict")
    if verdict != "PASS":
        reasons.append(f"gateway verdict is {verdict!r}, not PASS")
    route = str(gateway.get("route", "REWORK_CODE"))
    if route not in {"DONE", "REWORK_PLAN", "REWORK_CODE", "BLOCKED"}:
        route = "REWORK_CODE"
        reasons.append("gateway returned an invalid route")
    return GateDecision(not reasons, "DONE" if not reasons else route, tuple(reasons))


def _verify_command_evidence(config: LoopConfig, command: Any, result: dict[str, Any]) -> list[str]:
    command_id = command.command_id
    reason = f"required command evidence is invalid: {command_id}"
    run_id = result.get("run_id")
    qa_id = result.get("qa_id")
    log_value = result.get("log_path")
    identity = result.get("log_identity")
    execution_path = result.get("execution_path")
    source_path = result.get("source_path")
    if (
        not isinstance(run_id, str)
        or not run_id
        or not isinstance(qa_id, str)
        or not qa_id
        or not isinstance(log_value, str)
        or not log_value
        or not isinstance(identity, str)
        or not identity
        or not isinstance(execution_path, str)
        or not execution_path
        or not isinstance(source_path, str)
        or not source_path
    ):
        return [reason]
    relative = Path(log_value)
    if relative.is_absolute() or ".." in relative.parts:
        return [reason]
    log_path = (config.root / relative).resolve()
    expected_dir = (config.root / ".loop" / "runs" / run_id / "runner").resolve()
    try:
        metadata = log_path.lstat()
    except OSError:
        return [reason]
    if (
        not log_path.is_relative_to(expected_dir)
        or not stat.S_ISREG(metadata.st_mode)
        or file_identity(log_path) != identity
    ):
        return [reason]

    execution = Path(execution_path)
    source = Path(source_path)
    try:
        execution_metadata = execution.lstat()
        execution_fingerprint = fingerprint_worktree(execution)
        source_metadata = source.lstat()
        source_fingerprint = fingerprint_worktree(source)
    except (OSError, subprocess.SubprocessError):
        return [reason]
    if (
        execution.name != qa_id
        or execution.parent.name != run_id
        or execution.parent.parent.name != "executions"
        or execution.resolve().is_relative_to(config.root)
        or not stat.S_ISDIR(execution_metadata.st_mode)
        or result.get("execution_source_fingerprint") != result.get("worktree_fingerprint")
        or execution_fingerprint != result.get("execution_source_fingerprint")
        or not stat.S_ISDIR(source_metadata.st_mode)
        or source_fingerprint != result.get("worktree_fingerprint")
    ):
        return [reason]

    requests: list[dict[str, Any]] = []
    try:
        with (config.root / "qa" / "pipeline.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("id") == qa_id:
                    requests.append(item)
    except (OSError, json.JSONDecodeError):
        return [reason]
    expected_command = shlex.join(command.argv)
    if len(requests) != 1:
        return [reason]
    request = requests[0]
    if (
        request.get("command") != expected_command
        or request.get("cwd") != str(config.root)
        or request.get("execution_cwd") != execution_path
        or request.get("source_cwd") != source_path
        or run_id not in str(request.get("notes", ""))
        or request.get("context") != f"{run_id}@{str(result.get('head_sha'))[:12]}"
    ):
        return [reason]

    try:
        report = (config.root / "qa" / "test-report.md").read_text(encoding="utf-8")
    except OSError:
        return [reason]
    headings = list(re.finditer(rf"(?m)^### {re.escape(qa_id)}$", report))
    if len(headings) != 1:
        return [reason]
    start = headings[0].end()
    following = re.search(r"(?m)^### ", report[start:])
    section = report[start : start + following.start() if following else None]
    if (
        f"- command: {expected_command}\n" not in section
        or f"- status: {result.get('status')}\n" not in section
        or f"- execution_cwd: {execution_path}\n" not in section
        or f"- source_cwd: {source_path}\n" not in section
    ):
        return [reason]
    return []
