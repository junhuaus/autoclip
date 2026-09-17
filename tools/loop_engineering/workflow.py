from __future__ import annotations

from typing import Any

from .codex import AgentError, CodexRoleRunner
from .config import LoopConfig
from .contracts import LoopState, Role, RunState
from .gateway import blocking_findings, evaluate_gateway
from .gateway_evidence import prepare_gateway_evidence
from .runner import AllowlistedRunner
from .store import RunStore, fingerprint_worktree, head_sha
from .toolchain import ToolchainManager


class LoopWorkflow:
    def __init__(self, config: LoopConfig, store: RunStore) -> None:
        self.config = config
        self.store = store
        self.agents = CodexRoleRunner(config, store)
        self.runner = AllowlistedRunner(config, store)
        self.toolchains = ToolchainManager(config.root)

    def run(self, state: RunState) -> RunState:
        if state.state in {LoopState.DONE, LoopState.BLOCKED}:
            return state
        if state.state is not LoopState.RECEIVED:
            state.last_error = "interrupted MVP run cannot be resumed; create a new run"
            self.store.save(state)
            self.store.transition(state, LoopState.BLOCKED, state.last_error)
            return state
        try:
            return self._run(state)
        except (AgentError, OSError, ValueError) as exc:
            state.last_error = f"{type(exc).__name__}: {exc}"
            self.store.save(state)
            self.store.transition(state, LoopState.BLOCKED, state.last_error)
            return state

    def _run(self, state: RunState) -> RunState:
        for plan_cycle in range(state.cycle, self.config.max_plan_cycles):
            state.cycle = plan_cycle + 1
            state.coder_session_id = None
            self.store.transition(state, LoopState.PLANNING, "start or revise development plan")
            plan = self.agents.run(state, Role.PLANNER, {}).artifact
            if plan.get("verdict") != "READY":
                self.store.transition(
                    state,
                    LoopState.REWORK_PLAN,
                    "planner did not produce a ready plan",
                )
                continue

            if isinstance(self.runner, AllowlistedRunner) and self.runner.toolchain is None:
                self.runner.toolchain = self.toolchains.prepare()
            if not isinstance(self.runner, AllowlistedRunner) or self.runner.toolchain is None:
                coding_workspace = None
                source_worktree = fingerprint_worktree(self.config.root)
            else:
                source_worktree = fingerprint_worktree(self.config.root)
                coding_workspace = self.toolchains.execution_snapshot(
                    self.runner.toolchain,
                    state.run_id,
                    f"coding-{state.cycle}",
                    source_worktree,
                ).path

            coder_context: dict[str, Any] = {"plan": plan}
            for code_cycle in range(self.config.max_code_cycles):
                state.code_cycle = code_cycle + 1
                self.store.transition(state, LoopState.CODING, "implement or repair current plan")
                coding = self.agents.run(
                    state,
                    Role.CODER,
                    coder_context,
                    session_id=state.coder_session_id,
                    workspace=coding_workspace,
                )
                state.coder_session_id = coding.session_id
                if not state.coder_session_id:
                    raise AgentError("coder session identity is missing")
                self.store.save(state)
                if coding.artifact.get("verdict") == "BLOCKED":
                    state.last_error = self._blocked_reason("coder", coding.artifact)
                    self.store.save(state)
                    self.store.transition(state, LoopState.BLOCKED, state.last_error)
                    return state

                if isinstance(self.runner, AllowlistedRunner) and coding_workspace is not None:
                    assert self.runner.toolchain is not None
                    candidate_worktree = fingerprint_worktree(coding_workspace)
                    assurance = self.toolchains.execution_snapshot(
                        self.runner.toolchain,
                        state.run_id,
                        f"assurance-{state.cycle}-{state.code_cycle}",
                        candidate_worktree,
                        source_root=coding_workspace,
                    )
                    assurance_workspace = assurance.path
                else:
                    candidate_worktree = fingerprint_worktree(self.config.root)
                    assurance_workspace = None

                self.store.transition(state, LoopState.REVIEWING, "fresh read-only review")
                review = self.agents.run(
                    state,
                    Role.REVIEWER,
                    {"plan": plan},
                    workspace=assurance_workspace,
                ).artifact
                blockers = blocking_findings(review)
                if blockers:
                    coder_context = {"plan": plan, "review_findings": blockers}
                    self.store.transition(state, LoopState.REWORK_CODE, "review found P0/P1")
                    continue

                self.store.transition(state, LoopState.TEST_PLANNING, "fresh test analysis")
                test_plan = self.agents.run(
                    state,
                    Role.TESTER,
                    {
                        "plan": plan,
                        "review": review,
                        "allowlisted_commands": list(self.config.commands),
                    },
                    workspace=assurance_workspace,
                ).artifact
                if test_plan.get("verdict") == "BLOCKED":
                    state.last_error = self._blocked_reason("tester", test_plan)
                    self.store.save(state)
                    self.store.transition(state, LoopState.BLOCKED, state.last_error)
                    return state
                self.store.transition(
                    state,
                    LoopState.RUNNING,
                    "run deterministic allowlisted gates",
                )
                state.command_results = []
                self.store.save(state)
                if isinstance(self.runner, AllowlistedRunner):
                    if assurance_workspace is None:
                        raise AgentError("assurance workspace is missing")
                    self.runner.source_root = assurance_workspace
                results = [
                    self.runner.run(state, command.command_id)
                    for command in self.config.commands.values()
                    if command.required_for_final
                ]
                errors = [result for result in results if result.status == "ERROR"]
                if errors:
                    failed_ids = ", ".join(result.command_id for result in errors)
                    state.last_error = f"runner environment error: {failed_ids}"
                    self.store.save(state)
                    self.store.transition(state, LoopState.BLOCKED, state.last_error)
                    return state
                failures = [result for result in results if result.status != "PASS"]
                if failures:
                    coder_context = {
                        "plan": plan,
                        "review": review,
                        "test_plan": test_plan,
                        "runner_failures": [result.command_id for result in failures],
                    }
                    self.store.transition(state, LoopState.REWORK_CODE, "runner gate failed")
                    continue

                self.store.transition(state, LoopState.FINAL_GATE, "independent final assessment")
                gateway_context = {
                    "plan": plan,
                    "review": review,
                    "test_plan": test_plan,
                    "runner_results": state.command_results,
                }
                gateway_evidence = None
                if isinstance(self.runner, AllowlistedRunner):
                    if assurance_workspace is None or self.runner.toolchain is None:
                        raise AgentError("Gateway assurance/toolchain is missing")
                    gateway_evidence = prepare_gateway_evidence(
                        self.config,
                        state,
                        review,
                        assurance_workspace,
                        toolchain_fingerprint=self.runner.toolchain.fingerprint,
                    )
                    gateway_context["gateway_evidence"] = {
                        "relative_path": gateway_evidence.relative_path,
                        "index_sha256": gateway_evidence.index_sha256,
                        "canonical_deterministic_precheck": "PASS",
                    }
                try:
                    gateway = self.agents.run(
                        state,
                        Role.GATEWAY,
                        gateway_context,
                        workspace=assurance_workspace,
                    ).artifact
                finally:
                    if gateway_evidence is not None:
                        gateway_evidence.verify_unchanged()
                decision = evaluate_gateway(
                    self.config,
                    review,
                    gateway,
                    state.command_results,
                    current_head=(
                        head_sha(assurance_workspace) if assurance_workspace is not None else None
                    ),
                    current_worktree=(
                        fingerprint_worktree(assurance_workspace)
                        if assurance_workspace is not None
                        else None
                    ),
                    current_toolchain=(
                        self.runner.toolchain.fingerprint
                        if isinstance(self.runner, AllowlistedRunner)
                        and self.runner.toolchain is not None
                        else None
                    ),
                    verify_files=isinstance(self.runner, AllowlistedRunner),
                )
                self.store.event(
                    state,
                    "gateway.decision",
                    {
                        "passed": decision.passed,
                        "route": decision.route,
                        "reasons": list(decision.reasons),
                    },
                )
                if decision.passed:
                    if isinstance(self.runner, AllowlistedRunner):
                        if assurance_workspace is None:
                            raise AgentError("accepted assurance workspace is missing")
                        self.toolchains.publish_snapshot(
                            assurance_workspace,
                            expected_source_worktree=source_worktree,
                            expected_snapshot_worktree=candidate_worktree,
                        )
                    self.store.transition(
                        state,
                        LoopState.DONE,
                        "all deterministic and semantic gates passed",
                    )
                    return state
                if decision.route == "REWORK_PLAN":
                    self.store.transition(state, LoopState.REWORK_PLAN, "; ".join(decision.reasons))
                    break
                if decision.route == "BLOCKED":
                    state.last_error = "; ".join(decision.reasons)
                    self.store.save(state)
                    self.store.transition(state, LoopState.BLOCKED, state.last_error)
                    return state
                coder_context = {
                    "plan": plan,
                    "review": review,
                    "gateway": gateway,
                    "gate_reasons": list(decision.reasons),
                }
                self.store.transition(state, LoopState.REWORK_CODE, "; ".join(decision.reasons))
            else:
                state.last_error = "code repair budget exhausted"
                self.store.save(state)
                self.store.transition(state, LoopState.BLOCKED, state.last_error)
                return state

        state.last_error = "plan repair budget exhausted"
        self.store.save(state)
        self.store.transition(state, LoopState.BLOCKED, state.last_error)
        return state

    @staticmethod
    def _blocked_reason(role: str, artifact: dict[str, Any]) -> str:
        details: list[str] = []
        summary = artifact.get("summary") or artifact.get("strategy")
        if isinstance(summary, str) and summary.strip():
            details.append(summary.strip())
        for key in ("remaining", "gaps"):
            value = artifact.get(key)
            if isinstance(value, list):
                details.extend(str(item).strip() for item in value if str(item).strip())
        suffix = "; ".join(details) if details else "no actionable recovery was supplied"
        return f"{role} reported BLOCKED: {suffix}"
