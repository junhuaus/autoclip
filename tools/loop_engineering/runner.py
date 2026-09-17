from __future__ import annotations

import os
import re
import shlex
import time
from dataclasses import asdict
from pathlib import Path

from .config import CommandConfig, LoopConfig
from .contracts import CommandResult, RunState
from .process import bounded_redacted, run_bounded, safe_child_env
from .sandbox import runner_sandbox
from .store import (
    RunStore,
    file_identity,
    fingerprint_worktree,
    head_sha,
    new_id,
    snapshot_files,
    utc_now,
)
from .toolchain import ToolchainManager, TrustedToolchain, toolchain_fingerprint

ENVIRONMENT_ERROR = re.compile(
    r"(?:listen EPERM: operation not permitted|browserType\.launch:.*(?:EPERM|SIGABRT)"
    r"|sandbox-exec: sandbox_apply: Operation not permitted)",
    re.DOTALL,
)


class AllowlistedRunner:
    def __init__(
        self,
        config: LoopConfig,
        store: RunStore,
        toolchain: TrustedToolchain | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.toolchain = toolchain
        self.toolchains = ToolchainManager(config.root)
        self.source_root = config.root

    def run(self, state: RunState, command_id: str) -> CommandResult:
        if command_id not in self.config.commands:
            raise ValueError(f"command is not allowlisted: {command_id}")
        command = self.config.commands[command_id]
        head_before = head_sha(self.source_root)
        worktree_before = fingerprint_worktree(self.source_root)
        qa_id = self._new_qa_id()
        execution_path = self.toolchains.cache_root / "executions" / state.run_id / qa_id
        self._append_request(qa_id, command, state, execution_path, head_before)
        protected_before = self._protected_snapshot(state)
        started = time.monotonic()
        status = "PASS"
        exit_code: int | None
        try:
            if self.toolchain is None:
                self.toolchain = self.toolchains.prepare()
            execution = self.toolchains.execution_snapshot(
                self.toolchain,
                state.run_id,
                qa_id,
                worktree_before,
                source_root=self.source_root,
            )
            with runner_sandbox(
                self.config.root,
                list(command.argv),
                safe_child_env(),
                execution_root=execution.path,
                toolchain_root=self.toolchain.path,
            ) as sandboxed:
                captured = run_bounded(
                    sandboxed.argv,
                    cwd=execution.path,
                    env=sandboxed.env,
                    timeout_seconds=command.timeout_seconds,
                    limit_bytes=self.config.log_limit_bytes,
                )
            exit_code = captured.returncode
            output = captured.output
            if captured.timed_out:
                status = "ERROR"
            if exit_code != 0:
                status = (
                    "ERROR"
                    if captured.timed_out or ENVIRONMENT_ERROR.search(output) is not None
                    else "FAIL"
                )
            if captured.output_truncated:
                status = "ERROR"
                output = bounded_redacted(
                    f"{output}\nrunner output was truncated; incomplete evidence rejected",
                    self.config.log_limit_bytes,
                )
        except OSError as exc:
            exit_code = None
            execution_fingerprint = "unavailable"
            output = bounded_redacted(f"{type(exc).__name__}: {exc}", self.config.log_limit_bytes)
            status = "ERROR"
        else:
            execution_fingerprint = execution.source_fingerprint
        try:
            self._verify_protected_snapshot(state, protected_before)
        except OSError as exc:
            status = "ERROR"
            output = bounded_redacted(
                f"{output}\nprotected evidence violation: {exc}",
                self.config.log_limit_bytes,
            )
        head_after = head_sha(self.source_root)
        worktree_after = fingerprint_worktree(self.source_root)
        toolchain_before = (
            self.toolchain.fingerprint if self.toolchain is not None else "unavailable"
        )
        try:
            toolchain_after = (
                toolchain_fingerprint(self.toolchain.path)
                if self.toolchain is not None
                else "unavailable"
            )
        except OSError as exc:
            toolchain_after = "unavailable"
            status = "ERROR"
            output = bounded_redacted(
                f"{output}\ntrusted toolchain verification failed: {exc}",
                self.config.log_limit_bytes,
            )
        if toolchain_after != toolchain_before:
            status = "ERROR"
            output = bounded_redacted(
                f"{output}\ntrusted toolchain snapshot mutated",
                self.config.log_limit_bytes,
            )
        if head_after != head_before or worktree_after != worktree_before:
            status = "ERROR"
            output = bounded_redacted(
                f"{output}\nrunner command mutated the evidence worktree",
                self.config.log_limit_bytes,
            )
        duration = time.monotonic() - started
        log_dir = self.store.path(state.run_id) / "runner"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{qa_id}-{command_id}.log"
        with log_path.open("x", encoding="utf-8") as handle:
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        result = CommandResult(
            run_id=state.run_id,
            command_id=command_id,
            argv=list(command.argv),
            exit_code=exit_code,
            status=status,
            duration_seconds=round(duration, 3),
            head_sha=head_before,
            worktree_fingerprint=worktree_before,
            post_head_sha=head_after,
            post_worktree_fingerprint=worktree_after,
            toolchain_fingerprint=toolchain_before,
            post_toolchain_fingerprint=toolchain_after,
            execution_source_fingerprint=execution_fingerprint,
            source_path=str(self.source_root),
            execution_path=str(execution_path),
            log_path=str(log_path.relative_to(self.config.root)),
            log_identity=file_identity(log_path),
            qa_id=qa_id,
        )
        state.command_results.append(asdict(result))
        self.store.save(state)
        self.store.event(state, "runner.completed", asdict(result))
        self._append_report(result, output)
        return result

    def _append_request(
        self,
        qa_id: str,
        command: CommandConfig,
        state: RunState,
        execution_path: Path,
        head_before: str,
    ) -> None:
        import json

        path = self.config.root / "qa" / "pipeline.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": qa_id,
            "ts": utc_now().isoformat().replace("+00:00", "Z"),
            "command": shlex.join(command.argv),
            "cwd": str(self.config.root),
            "source_cwd": str(self.source_root),
            "execution_cwd": str(execution_path),
            "requested_by": "coding-ai",
            "notes": f"loop-engineering run {state.run_id}; allowlist id {command.command_id}",
            "timeout_seconds": command.timeout_seconds,
            "context": f"{state.run_id}@{head_before[:12]}",
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _protected_snapshot(self, state: RunState) -> dict[str, str]:
        paths = [
            path
            for path in self.store.path(state.run_id).rglob("*")
            if path.is_file() or path.is_symlink()
        ]
        paths.extend(
            self.config.root / "qa" / name for name in ("pipeline.jsonl", "test-report.md")
        )
        return snapshot_files(paths)

    def _verify_protected_snapshot(self, state: RunState, before: dict[str, str]) -> None:
        after = self._protected_snapshot(state)
        if after != before:
            changed = sorted(
                path for path in set(after) | set(before) if after.get(path) != before.get(path)
            )
            target = changed[0] if changed else "unknown"
            raise OSError(f"runner modified protected control-plane evidence: {target}")

    def _new_qa_id(self) -> str:
        pipeline = self.config.root / "qa" / "pipeline.jsonl"
        existing: set[str] = set()
        if pipeline.is_file():
            import json

            with pipeline.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        existing.add(item["id"])
        for _ in range(100):
            candidate = new_id(4)
            if candidate not in existing:
                return candidate
        raise OSError("unable to allocate a unique QA request ID")

    def _append_report(self, result: CommandResult, output: str) -> None:
        path = self.config.root / "qa" / "test-report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if result.status == "PASS":
            summary = "command passed"
        elif result.status == "ERROR":
            summary = "command could not complete in the execution environment"
        else:
            summary = "command completed with test or assertion failures"
        detail = (output[-4000:] or "(no output)").replace("```", "`\u200b``")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"\n### {result.qa_id}\n"
                f"- ts: {utc_now().isoformat().replace('+00:00', 'Z')}\n"
                f"- command: {shlex.join(result.argv)}\n"
                f"- cwd: {self.config.root}\n"
                f"- source_cwd: {result.source_path}\n"
                f"- execution_cwd: {result.execution_path}\n"
                f"- status: {result.status}\n"
                f"- duration_seconds: {int(result.duration_seconds)}\n"
                f"- summary: {summary}\n"
                f"- details:\n\n```text\n{detail}\n```\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
