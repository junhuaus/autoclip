from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from tools.loop_engineering.cli import _create, _install_profiles, main
from tools.loop_engineering.codex import (
    AgentError,
    AgentResult,
    CodexRoleRunner,
    _tool_host_unavailable,
)
from tools.loop_engineering.config import (
    CODEX_DISABLED_FEATURES,
    CODEX_REQUIRED_FEATURES,
    CommandConfig,
    LoopConfig,
    codex_feature_policy_matches,
    load_config,
)
from tools.loop_engineering.contracts import CommandResult, LoopState, Role
from tools.loop_engineering.gateway import blocking_findings, evaluate_gateway
from tools.loop_engineering.gateway_evidence import (
    GatewayEvidence,
    _bundle_identities,
    prepare_gateway_evidence,
)
from tools.loop_engineering.process import CapturedProcess, run_bounded, safe_child_env
from tools.loop_engineering.runner import ENVIRONMENT_ERROR, AllowlistedRunner
from tools.loop_engineering.sandbox import _profile, runner_sandbox
from tools.loop_engineering.schema import SchemaError, validate_instance
from tools.loop_engineering.store import RunStore, fingerprint_worktree, head_sha
from tools.loop_engineering.toolchain import (
    ToolchainError,
    ToolchainManager,
    TrustedToolchain,
    _copy_node_dependencies,
    _rewrite_embedded_paths,
    _snapshot_manifest,
    toolchain_fingerprint,
)
from tools.loop_engineering.workflow import LoopWorkflow

ROOT = Path(__file__).parents[2]


def _trusted_toolchain(root: Path) -> TrustedToolchain:
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text(
            ".venv\n.python\nnode_modules\n.loop\nqa/pipeline.jsonl\nqa/test-report.md\n",
            encoding="utf-8",
        )
    path = root.parent / f"{root.name}-trusted-toolchain"
    for relative in (
        ".python",
        ".venv",
        "apps/web/node_modules",
        ".cache/tiktoken",
        ".cache/playwright",
    ):
        (path / relative).mkdir(parents=True, exist_ok=True)
    for relative in (
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        "apps/web/package.json",
        "apps/web/package-lock.json",
    ):
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("test\n", encoding="utf-8")
        source = root / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            source.write_text("test\n", encoding="utf-8")
    fingerprint = toolchain_fingerprint(path)
    return TrustedToolchain(path, fingerprint, fingerprint)


def _allowlisted_runner(
    config: LoopConfig, store: RunStore, toolchain: TrustedToolchain
) -> AllowlistedRunner:
    runner = AllowlistedRunner(config, store, toolchain)
    runner.toolchains = ToolchainManager(
        config.root, config.root.parent / f"{config.root.name}-runner-cache"
    )
    return runner


def test_repository_loop_config_is_complete() -> None:
    config = load_config(ROOT)

    assert set(config.roles) == set(Role)
    assert config.roles[Role.CODER].sandbox == "workspace-write"
    assert all(
        item.sandbox == "read-only" for role, item in config.roles.items() if role is not Role.CODER
    )
    assert {item.command_id for item in config.commands.values() if item.required_for_final} == {
        "lint",
        "e2e",
        "test",
    }
    assert config.commands["e2e"].argv == ("make", "e2e")
    assert config.commands["e2e"].timeout_seconds == 900


def test_all_role_schemas_are_valid_json_objects() -> None:
    config = load_config(ROOT)

    for role in Role:
        schema = json.loads(config.roles[role].schema.read_text(encoding="utf-8"))
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_run_store_persists_state_events_and_artifacts(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    state = store.create("add a safe feature", "a" * 40)

    store.transition(state, LoopState.PLANNING, "plan")
    artifact = store.artifact(state, "planner", {"verdict": "READY"})
    loaded = store.load(state.run_id)

    assert loaded.state is LoopState.PLANNING
    assert loaded.artifacts["planner"] == [str(artifact.relative_to(tmp_path))]
    events = (store.path(state.run_id) / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["kind"] for line in events] == [
        "run.created",
        "state.changed",
        "artifact.recorded",
    ]


def test_runner_rejects_any_command_outside_allowlist(tmp_path: Path) -> None:
    config = load_config(ROOT)
    runner = AllowlistedRunner(config, RunStore(tmp_path))
    state = RunStore(tmp_path).create("requirement", "b" * 40)

    with pytest.raises(ValueError, match="not allowlisted"):
        runner.run(state, "rm-everything")


def test_runner_classifies_browser_host_permission_as_environment_error() -> None:
    assert ENVIRONMENT_ERROR.search("Error: listen EPERM: operation not permitted 127.0.0.1:5174")
    assert ENVIRONMENT_ERROR.search(
        "browserType.launch: Target closed; Google Chrome exited with SIGABRT and EPERM"
    )
    assert ENVIRONMENT_ERROR.search("assert 1 == 2") is None


@pytest.mark.parametrize(
    "captured",
    [
        CapturedProcess(
            2, "Error: listen EPERM: operation not permitted 127.0.0.1:5174", None, False
        ),
        CapturedProcess(0, "passed tail", None, False, output_truncated=True),
        CapturedProcess(2, "failed tail", None, False, output_truncated=True),
    ],
)
def test_runner_rejects_permission_failure_or_incomplete_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, captured: CapturedProcess
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Loop Test",
            "-c",
            "user.email=loop@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    command = CommandConfig("test", ("make", "test"), 10, True)
    config = LoopConfig(tmp_path, "codex", {}, {"test": command}, 1, 1, 4096, 1024)
    store = RunStore(tmp_path)
    state = store.create("requirement", head_sha(tmp_path))
    monkeypatch.setattr(
        "tools.loop_engineering.runner.run_bounded",
        lambda *_args, **_kwargs: captured,
    )

    result = _allowlisted_runner(config, store, _trusted_toolchain(tmp_path)).run(state, "test")

    assert result.status == "ERROR"
    report = (tmp_path / "qa" / "test-report.md").read_text(encoding="utf-8")
    assert f"### {result.qa_id}" in report
    assert "- status: ERROR" in report
    decision = evaluate_gateway(
        config,
        {"verdict": "PASS", "findings": []},
        {"verdict": "PASS", "route": "DONE"},
        [asdict(result)],
    )
    assert not decision.passed
    if captured.output_truncated:
        assert "incomplete evidence rejected" in (tmp_path / result.log_path).read_text()


def test_runner_rejects_worktree_mutation_and_protected_evidence_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Loop Test",
            "-c",
            "user.email=loop@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    command = CommandConfig("test", ("make", "test"), 10, True)
    config = LoopConfig(tmp_path, "codex", {}, {"test": command}, 1, 1, 4096, 1024)
    store = RunStore(tmp_path)
    state = store.create("requirement", head_sha(tmp_path))

    def fake_run(*_args: object, **_kwargs: object) -> CapturedProcess:
        (tmp_path / "mutation.txt").write_text("unsafe", encoding="utf-8")
        pipeline = tmp_path / "qa" / "pipeline.jsonl"
        with pipeline.open("a", encoding="utf-8") as handle:
            handle.write('{"forged":true}\n')
        return CapturedProcess(0, "passed", None, False)

    monkeypatch.setattr("tools.loop_engineering.runner.run_bounded", fake_run)

    result = _allowlisted_runner(config, store, _trusted_toolchain(tmp_path)).run(state, "test")

    assert result.status == "ERROR"
    log = (tmp_path / result.log_path).read_text(encoding="utf-8")
    assert "protected evidence violation" in log
    assert "mutated the evidence worktree" in log


def test_gateway_correlates_request_report_and_log_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Loop Test",
            "-c",
            "user.email=loop@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    command = CommandConfig("test", ("make", "test"), 10, True)
    config = LoopConfig(tmp_path, "codex", {}, {"test": command}, 1, 1, 4096, 1024)
    store = RunStore(tmp_path)
    state = store.create("requirement", head_sha(tmp_path))
    monkeypatch.setattr(
        "tools.loop_engineering.runner.run_bounded",
        lambda *_args, **_kwargs: CapturedProcess(0, "passed", None, False),
    )
    result = _allowlisted_runner(config, store, _trusted_toolchain(tmp_path)).run(state, "test")

    decision = evaluate_gateway(
        config,
        {"verdict": "PASS", "findings": []},
        {"verdict": "PASS", "route": "DONE"},
        [asdict(result)],
    )
    assert decision.passed is True

    with (tmp_path / result.log_path).open("a", encoding="utf-8") as handle:
        handle.write("forged")
    tampered = evaluate_gateway(
        config,
        {"verdict": "PASS", "findings": []},
        {"verdict": "PASS", "route": "DONE"},
        [asdict(result)],
    )
    assert tampered.passed is False
    assert any("evidence is invalid" in reason for reason in tampered.reasons)


def test_gateway_role_receives_only_current_verified_evidence_and_detects_copy_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Loop Test",
            "-c",
            "user.email=loop@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    command = CommandConfig("test", ("make", "test"), 10, True)
    config = LoopConfig(tmp_path, "codex", {}, {"test": command}, 1, 1, 4096, 1024)
    store = RunStore(tmp_path)
    state = store.create("requirement", head_sha(tmp_path))
    monkeypatch.setattr(
        "tools.loop_engineering.runner.run_bounded",
        lambda *_args, **_kwargs: CapturedProcess(0, "1 passed", None, False),
    )
    result = _allowlisted_runner(config, store, _trusted_toolchain(tmp_path)).run(state, "test")
    before = fingerprint_worktree(tmp_path)
    bundle = prepare_gateway_evidence(
        config,
        state,
        {"verdict": "PASS", "findings": []},
        tmp_path,
        toolchain_fingerprint=result.toolchain_fingerprint,
    )
    index = json.loads((bundle.path / "index.json").read_text())
    assert index["deterministic_canonical_evidence_precheck"] == "PASS"
    assert [(row["command_id"], row["qa_id"]) for row in index["commands"]] == [
        ("test", result.qa_id)
    ]
    assert (bundle.path / "test/runner.log").read_text() == "1 passed"
    assert json.loads((bundle.path / "test/qa-request.json").read_text())["id"] == result.qa_id
    assert f"### {result.qa_id}" in (bundle.path / "test/qa-report.md").read_text()
    assert fingerprint_worktree(tmp_path) == before
    bundle.verify_unchanged()
    copied_log = bundle.path / "test/runner.log"
    copied_log.chmod(0o644)
    copied_log.write_text("forged")
    with pytest.raises(OSError, match="changed"):
        bundle.verify_unchanged()


def test_gateway_bundle_identity_detects_an_unlisted_empty_directory(tmp_path: Path) -> None:
    root = tmp_path / "inspection"
    root.mkdir()
    (root / "index.json").write_text("{}")
    bundle = GatewayEvidence(root, "inspection", "unused", _bundle_identities(root))
    bundle.verify_unchanged()
    (root / "unexpected").mkdir()
    with pytest.raises(OSError, match="changed"):
        bundle.verify_unchanged()


def test_codex_argv_uses_profile_sandbox_and_explicit_resume_id(tmp_path: Path) -> None:
    config = load_config(ROOT)
    runner = CodexRoleRunner(config, RunStore(tmp_path))
    schema = config.roles[Role.CODER].schema
    final = tmp_path / "final.json"

    initial = runner._new_argv(Role.CODER, schema, final)
    resumed = runner._resume_argv("019abc00-0000-7000-8000-000000000000", schema, final)

    assert initial[:3] == ["codex", "-p", "liveclip-loop-coder"]
    assert initial[initial.index("-s") + 1] == "workspace-write"
    assert 'approval_policy="never"' in initial
    assert "--ephemeral" not in initial
    assert "--last" not in resumed
    assert "--ignore-user-config" in initial
    assert "--ignore-rules" in initial
    assert "--strict-config" in initial
    assert 'approval_policy="never"' in resumed
    assert 'sandbox_mode="workspace-write"' in resumed
    for feature in CODEX_DISABLED_FEATURES:
        assert initial.count(feature) == 1
        assert resumed.count(feature) == 1
    assert resumed[-2:] == ["019abc00-0000-7000-8000-000000000000", "-"]
    with pytest.raises(AgentError, match="invalid Coder session ID"):
        runner._resume_argv("--last", schema, final)


@pytest.mark.parametrize("role", list(Role))
def test_role_tool_host_is_available_without_changing_authority(tmp_path: Path, role: Role) -> None:
    config = load_config(ROOT)
    runner = CodexRoleRunner(config, RunStore(tmp_path))
    argv = runner._new_argv(role, config.roles[role].schema, tmp_path / "final.json")

    assert "code_mode_host" not in CODEX_DISABLED_FEATURES
    assert argv[argv.index("code_mode_host") - 1 : argv.index("code_mode_host") + 1] == [
        "--enable",
        "code_mode_host",
    ]
    assert argv[argv.index("-s") + 1] == ("workspace-write" if role is Role.CODER else "read-only")
    assert 'approval_policy="never"' in argv
    assert "--ignore-user-config" in argv and "--ignore-rules" in argv
    for feature in ("apps", "browser_use", "computer_use", "plugins", "multi_agent"):
        assert argv[argv.index(feature) - 1] == "--disable"


def test_resumed_coder_requires_tool_host_and_exact_session(tmp_path: Path) -> None:
    config = load_config(ROOT)
    runner = CodexRoleRunner(config, RunStore(tmp_path))
    session = "019abc00-0000-7000-8000-000000000000"
    argv = runner._resume_argv(session, config.roles[Role.CODER].schema, tmp_path / "final.json")

    assert argv[argv.index("code_mode_host") - 1] == "--enable"
    assert argv[-2:] == [session, "-"]
    assert 'sandbox_mode="workspace-write"' in argv
    assert "--color" not in argv  # exec resume 0.154 does not accept this exec-only flag.
    assert 'approval_policy="never"' in argv
    assert "--last" not in argv


@pytest.mark.parametrize("verdict", ["READY", "NEEDS_INPUT"])
@pytest.mark.parametrize("overflow", ["none", "raw", "redacted"])
def test_unavailable_tool_host_blocks_role_before_accepting_its_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verdict: str, overflow: str
) -> None:
    config = replace(load_config(ROOT), root=tmp_path)
    monkeypatch.setattr("tools.loop_engineering.codex.head_sha", lambda _root: "a" * 40)
    monkeypatch.setattr("tools.loop_engineering.codex.fingerprint_worktree", lambda _root: "b" * 64)
    store = RunStore(tmp_path)
    state = store.create("tool access requirement", "a" * 40)
    event = json.dumps(
        {
            "type": "item.completed",
            "item": {
                "type": "error",
                "message": "Code Mode is unavailable because code-mode host is disabled.",
            },
        }
    )
    truncated = overflow != "none"
    payload = "x" * 2048 if overflow == "raw" else ""
    if overflow == "redacted":
        monkeypatch.setenv("LIVECLIP_PROBE_SECRET", "q7v4")
        payload = "q7v4" * 60
        assert len((event + "\n" + payload + "\n").encode()) < 512
    captured = run_bounded(
        [sys.executable, "-c", f"print({event!r}); print({payload!r})"],
        cwd=ROOT,
        env=safe_child_env(),
        timeout_seconds=10,
        limit_bytes=512,
    )
    assert _tool_host_unavailable(captured.output) is not truncated

    def fake_run(argv: list[str], **_kwargs: object) -> CapturedProcess:
        final_path = Path(argv[argv.index("--output-last-message") + 1])
        final_path.write_text(
            json.dumps(
                {
                    "verdict": verdict,
                    "summary": "unverified plan",
                    "architecture": [],
                    "tasks": [{"id": "T1", "description": "read", "depends_on": [], "files": []}],
                    "acceptance_criteria": ["read source"],
                    "risks": [],
                }
            ),
            encoding="utf-8",
        )
        return captured

    monkeypatch.setattr("tools.loop_engineering.codex.run_bounded", fake_run)
    error = "output was truncated" if truncated else "tool host is unavailable"
    with pytest.raises(AgentError, match=error):
        CodexRoleRunner(config, store).run(state, Role.PLANNER, {})
    assert state.artifacts == {}
    log = store.path(state.run_id) / "agents/planner/001-events.jsonl"
    assert log.read_text(encoding="utf-8") == captured.output


def test_model_text_cannot_impersonate_a_tool_host_failure() -> None:
    text = "Code Mode is unavailable because code-mode host is disabled."
    event = {"type": "item.completed", "item": {"type": "agent_message", "text": text}}
    assert _tool_host_unavailable(json.dumps(event)) is False
    assert _tool_host_unavailable(text) is False


@pytest.mark.parametrize("drift", ["none", "missing-host", "disabled-host", "enabled-apps"])
def test_doctor_requires_observed_feature_policy_not_just_parser_success(drift: str) -> None:
    lines = {name: f"{name} stable false" for name in CODEX_DISABLED_FEATURES}
    lines.update({name: f"{name} stable true" for name in CODEX_REQUIRED_FEATURES})
    if drift == "missing-host":
        del lines["code_mode_host"]
    elif drift == "disabled-host":
        lines["code_mode_host"] = "code_mode_host stable false"
    elif drift == "enabled-apps":
        lines["apps"] = "apps stable true"

    assert codex_feature_policy_matches("\n".join(lines.values())) is (drift == "none")


def _passing_results(config) -> list[dict[str, object]]:
    return [
        {
            "run_id": "20260824T000000Z-00000000",
            "command_id": item.command_id,
            "argv": list(item.argv),
            "exit_code": 0,
            "status": "PASS",
            "head_sha": "c" * 40,
            "worktree_fingerprint": "d" * 64,
            "post_head_sha": "c" * 40,
            "post_worktree_fingerprint": "d" * 64,
            "toolchain_fingerprint": "e" * 64,
            "post_toolchain_fingerprint": "e" * 64,
            "execution_source_fingerprint": "f" * 64,
            "source_path": "/trusted/source",
            "execution_path": "/trusted/execution",
            "log_path": "fake.log",
            "log_identity": "fake",
            "qa_id": f"qa-{item.command_id}",
        }
        for item in config.commands.values()
        if item.required_for_final
    ]


def test_gateway_requires_review_runner_freshness_and_semantic_pass() -> None:
    config = load_config(ROOT)
    review = {"verdict": "PASS", "findings": []}
    gateway = {"verdict": "PASS", "route": "DONE"}

    decision = evaluate_gateway(
        config,
        review,
        gateway,
        _passing_results(config),
        current_head="c" * 40,
        current_worktree="d" * 64,
        current_toolchain="e" * 64,
        verify_files=False,
    )

    assert decision.passed is True
    assert decision.route == "DONE"


def test_gateway_rejects_p1_and_stale_or_missing_runner_evidence() -> None:
    config = load_config(ROOT)
    review = {
        "verdict": "FAIL",
        "findings": [{"severity": "P1", "summary": "unsafe", "evidence": "x", "fix": "y"}],
    }
    results = _passing_results(config)
    results[0]["worktree_fingerprint"] = "changed"

    decision = evaluate_gateway(
        config,
        review,
        {"verdict": "FAIL", "route": "REWORK_CODE"},
        results[:-1],
        current_head="c" * 40,
        current_worktree="d" * 64,
        current_toolchain="e" * 64,
        verify_files=False,
    )

    assert decision.passed is False
    assert decision.route == "REWORK_CODE"
    assert blocking_findings(review) == review["findings"]
    assert any("P0/P1" in reason for reason in decision.reasons)
    assert any("not run" in reason for reason in decision.reasons)


def test_project_baseline_commit_exists() -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "6009b23^{commit}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    assert completed.stdout.strip().startswith("6009b23")


def test_local_schema_validation_rejects_missing_extra_and_oversized_values() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "items"],
        "properties": {
            "verdict": {"enum": ["PASS"]},
            "items": {"type": "array", "maxItems": 1, "items": {"type": "string"}},
        },
    }

    validate_instance({"verdict": "PASS", "items": ["ok"]}, schema)
    with pytest.raises(SchemaError, match="missing required"):
        validate_instance({"items": []}, schema)
    with pytest.raises(SchemaError, match="unexpected"):
        validate_instance({"verdict": "PASS", "items": [], "command": "rm"}, schema)
    with pytest.raises(SchemaError, match="maximum"):
        validate_instance({"verdict": "PASS", "items": ["a", "b"]}, schema)


def test_bounded_process_capture_keeps_session_and_redacts_tail() -> None:
    code = (
        'print(\'{"thread_id":"019abc00-0000-7000-8000-000000000000"}\'); '
        'print("x" * 10000); print("Bearer abcdefghijklmnopqrstuvwxyz")'
    )

    captured = run_bounded(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=safe_child_env(),
        timeout_seconds=10,
        limit_bytes=256,
        capture_session=True,
    )

    assert captured.returncode == 0
    assert len(captured.output.encode()) <= 256
    assert captured.output_truncated
    assert captured.session_id == "019abc00-0000-7000-8000-000000000000"
    assert "abcdefghijklmnopqrstuvwxyz" not in captured.output
    assert "[REDACTED]" in captured.output


def test_bounded_process_timeout_stops_the_owned_process_group(tmp_path: Path) -> None:
    sentinel = tmp_path / "grandchild-finished"
    grandchild = f"import time; time.sleep(2); open({str(sentinel)!r}, 'w').write('unsafe')"
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); "
        "time.sleep(30)"
    )

    captured = run_bounded(
        [sys.executable, "-c", parent],
        cwd=ROOT,
        env=safe_child_env(),
        timeout_seconds=1,
        limit_bytes=1024,
    )
    time.sleep(2)

    assert captured.timed_out is True
    assert not sentinel.exists()


def test_bounded_process_stops_descendant_holding_pipe_after_parent_exit(tmp_path: Path) -> None:
    sentinel = tmp_path / "orphan-finished"
    grandchild = f"import time; time.sleep(3); open({str(sentinel)!r}, 'w').write('unsafe')"
    parent = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {grandchild!r}])"

    started = time.monotonic()
    captured = run_bounded(
        [sys.executable, "-c", parent],
        cwd=ROOT,
        env=safe_child_env(),
        timeout_seconds=10,
        limit_bytes=1024,
    )
    elapsed = time.monotonic() - started
    time.sleep(3)

    assert captured.returncode == 0
    assert elapsed < 2.5
    assert not sentinel.exists()


def test_streaming_redaction_happens_before_output_tail_is_capped() -> None:
    secret = "A" * 20_000
    code = (
        f"print('Bearer {secret}'); "
        "print('Basic dXNlcjpwYXNzd29yZA=='); "
        "print('password=visible-password-value'); "
        "print('https://user:credential@example.invalid/path')"
    )

    captured = run_bounded(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=safe_child_env(),
        timeout_seconds=10,
        limit_bytes=512,
    )

    assert secret[-100:] not in captured.output
    assert "dXNlcjpwYXNzd29yZA" not in captured.output
    assert "visible-password-value" not in captured.output
    assert "user:credential@" not in captured.output
    assert "[REDACTED]" in captured.output


def test_child_environment_removes_credentials_and_authenticated_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UNRELATED_LOOP_VALUE", "kept")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("LIVECLIP_BOOTSTRAP_ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://redirect.example.test")
    monkeypatch.setenv("HTTPS_PROXY", "https://user:password@example.test")

    safe = safe_child_env()

    assert safe["UNRELATED_LOOP_VALUE"] == "kept"
    assert "GITHUB_TOKEN" not in safe
    assert "LIVECLIP_BOOTSTRAP_ADMIN_PASSWORD" not in safe
    assert "OPENAI_BASE_URL" not in safe
    assert "HTTPS_PROXY" not in safe


def test_coder_without_observed_session_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "e" * 40)

    def fake_run(argv: list[str], **_kwargs: object) -> CapturedProcess:
        final_path = Path(argv[argv.index("--output-last-message") + 1])
        final_path.write_text(
            json.dumps(
                {
                    "verdict": "IMPLEMENTED",
                    "summary": "done",
                    "changed_files": [],
                    "tests_run": [],
                    "remaining": [],
                }
            ),
            encoding="utf-8",
        )
        return CapturedProcess(0, "", None, False)

    monkeypatch.setattr("tools.loop_engineering.codex.run_bounded", fake_run)

    with pytest.raises(AgentError, match="session ID"):
        CodexRoleRunner(config, store).run(state, Role.CODER, {})


def test_agent_cannot_rewrite_existing_control_plane_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "0" * 40)

    def fake_run(argv: list[str], **_kwargs: object) -> CapturedProcess:
        final_path = Path(argv[argv.index("--output-last-message") + 1])
        final_path.write_text(
            json.dumps(
                {
                    "verdict": "IMPLEMENTED",
                    "summary": "done",
                    "changed_files": [],
                    "tests_run": [],
                    "remaining": [],
                }
            ),
            encoding="utf-8",
        )
        (store.path(state.run_id) / "state.json").write_text("{}\n", encoding="utf-8")
        return CapturedProcess(0, "", "019abc00-0000-7000-8000-000000000000", False)

    monkeypatch.setattr("tools.loop_engineering.codex.run_bounded", fake_run)

    with pytest.raises(AgentError, match="protected control-plane evidence"):
        CodexRoleRunner(config, store).run(state, Role.CODER, {})


def test_agent_cannot_mutate_frozen_loop_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "8" * 40)
    runner = CodexRoleRunner(config, store)
    frozen = runner._policy_snapshot()

    def fake_run(argv: list[str], **_kwargs: object) -> CapturedProcess:
        final_path = Path(argv[argv.index("--output-last-message") + 1])
        final_path.write_text("{}", encoding="utf-8")
        return CapturedProcess(0, "", "019abc00-0000-7000-8000-000000000000", False)

    monkeypatch.setattr("tools.loop_engineering.codex.run_bounded", fake_run)
    monkeypatch.setattr(runner, "_policy_snapshot", lambda _root=None: {**frozen, "changed": "yes"})

    with pytest.raises(AgentError, match="frozen loop policy"):
        runner.run(state, Role.CODER, {})


def test_interrupted_mvp_run_is_blocked_instead_of_replayed(tmp_path: Path) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "f" * 40)
    store.transition(state, LoopState.PLANNING, "started")

    completed = LoopWorkflow(config, store).run(state)

    assert completed.state is LoopState.BLOCKED
    assert completed.last_error == "interrupted MVP run cannot be resumed; create a new run"


def test_requirement_is_confined_and_profile_install_is_no_clobber(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("requirement", encoding="utf-8")
    with pytest.raises(ValueError, match="docs/requirements"):
        _create(store, ROOT, outside, 1024)

    codex_home = tmp_path / "codex-home"
    assert _install_profiles(ROOT, codex_home) == 0
    installed = codex_home / "liveclip-loop-coder.config.toml"
    before = installed.stat().st_mtime_ns
    assert _install_profiles(ROOT, codex_home) == 0
    assert installed.stat().st_mtime_ns == before
    installed.write_text("different", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        _install_profiles(ROOT, codex_home)


def test_store_rejects_invalid_state_transition(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    state = store.create("requirement", "1" * 40)

    with pytest.raises(ValueError, match="invalid loop transition"):
        store.transition(state, LoopState.DONE, "skip every gate")


def test_status_remains_available_when_repository_config_is_broken(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = RunStore(tmp_path).create("requirement", "4" * 40)

    assert main(["--root", str(tmp_path), "status", state.run_id]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == state.run_id


class _FakeAgents:
    def __init__(
        self,
        *,
        block_first_review: bool = False,
        plan_ready: bool = True,
        coder_blocked: bool = False,
        tester_blocked: bool = False,
    ) -> None:
        self.block_first_review = block_first_review
        self.plan_ready = plan_ready
        self.coder_blocked = coder_blocked
        self.tester_blocked = tester_blocked
        self.calls: list[tuple[Role, str | None]] = []
        self.review_count = 0

    def run(
        self,
        _state: Any,
        role: Role,
        _context: dict[str, Any],
        *,
        session_id: str | None = None,
        workspace: Path | None = None,
    ) -> AgentResult:
        self.calls.append((role, session_id))
        if role is Role.PLANNER:
            artifact = {"verdict": "READY" if self.plan_ready else "NEEDS_INPUT"}
        elif role is Role.CODER:
            artifact = {
                "verdict": "BLOCKED" if self.coder_blocked else "IMPLEMENTED",
                "summary": "missing authority" if self.coder_blocked else "done",
                "remaining": ["operator decision"] if self.coder_blocked else [],
            }
        elif role is Role.REVIEWER:
            self.review_count += 1
            blocked = self.block_first_review and self.review_count == 1
            artifact = {
                "verdict": "FAIL" if blocked else "PASS",
                "findings": (
                    [{"severity": "P1", "summary": "repair", "evidence": "x", "fix": "y"}]
                    if blocked
                    else []
                ),
            }
        elif role is Role.TESTER:
            artifact = {
                "verdict": "BLOCKED" if self.tester_blocked else "READY",
                "strategy": "host unavailable" if self.tester_blocked else "run gates",
                "gaps": ["browser host"] if self.tester_blocked else [],
            }
        else:
            artifact = {"verdict": "PASS", "route": "DONE"}
        observed = session_id or (
            "019abc00-0000-7000-8000-000000000000" if role is Role.CODER else None
        )
        return AgentResult(role, observed, artifact, "fake.log")


class _PassingRunner:
    def __init__(self, config: Any, status: str = "PASS") -> None:
        self.config = config
        self.status = status

    def run(self, state: Any, command_id: str) -> CommandResult:
        head = head_sha(self.config.root)
        worktree = fingerprint_worktree(self.config.root)
        result = CommandResult(
            run_id=state.run_id,
            command_id=command_id,
            argv=list(self.config.commands[command_id].argv),
            exit_code=0 if self.status == "PASS" else 2,
            status=self.status,
            duration_seconds=0,
            head_sha=head,
            worktree_fingerprint=worktree,
            post_head_sha=head,
            post_worktree_fingerprint=worktree,
            toolchain_fingerprint="e" * 64,
            post_toolchain_fingerprint="e" * 64,
            execution_source_fingerprint="f" * 64,
            source_path=str(self.config.root),
            execution_path="/trusted/execution",
            log_path="fake.log",
            log_identity="fake",
            qa_id=f"qa-{command_id}",
        )
        state.command_results.append(asdict(result))
        return result


def test_workflow_reuses_exact_coder_session_after_review_repair(tmp_path: Path) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "2" * 40)
    workflow = LoopWorkflow(config, store)
    agents = _FakeAgents(block_first_review=True)
    workflow.agents = agents  # type: ignore[assignment]
    workflow.runner = _PassingRunner(config)  # type: ignore[assignment]

    completed = workflow.run(state)

    coder_calls = [session for role, session in agents.calls if role is Role.CODER]
    assert completed.state is LoopState.DONE
    assert coder_calls == [None, "019abc00-0000-7000-8000-000000000000"]


def test_workflow_stops_after_plan_budget(tmp_path: Path) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "3" * 40)
    workflow = LoopWorkflow(config, store)
    workflow.agents = _FakeAgents(plan_ready=False)  # type: ignore[assignment]

    completed = workflow.run(state)

    assert completed.state is LoopState.BLOCKED
    assert completed.last_error == "plan repair budget exhausted"


def test_workflow_blocks_immediately_on_runner_environment_error(tmp_path: Path) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "5" * 40)
    workflow = LoopWorkflow(config, store)
    agents = _FakeAgents()
    workflow.agents = agents  # type: ignore[assignment]
    workflow.runner = _PassingRunner(config, status="ERROR")  # type: ignore[assignment]

    completed = workflow.run(state)

    assert completed.state is LoopState.BLOCKED
    assert completed.last_error == "runner environment error: lint, e2e, test"
    assert len([role for role, _session in agents.calls if role is Role.CODER]) == 1


@pytest.mark.parametrize(
    ("agents", "expected"),
    [
        (_FakeAgents(coder_blocked=True), "coder reported BLOCKED"),
        (_FakeAgents(tester_blocked=True), "tester reported BLOCKED"),
    ],
)
def test_workflow_honors_agent_blocked_verdicts(
    tmp_path: Path, agents: _FakeAgents, expected: str
) -> None:
    config = load_config(ROOT)
    store = RunStore(tmp_path)
    state = store.create("requirement", "9" * 40)
    workflow = LoopWorkflow(config, store)
    workflow.agents = agents  # type: ignore[assignment]
    workflow.runner = _PassingRunner(config)  # type: ignore[assignment]

    completed = workflow.run(state)

    assert completed.state is LoopState.BLOCKED
    assert completed.last_error is not None and expected in completed.last_error


def test_config_rejects_yaml_truthy_strings_for_isolation_flags(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "config" / "loop-engineering", tmp_path / "config" / "loop-engineering")
    source = (ROOT / "loop-engineering.yaml").read_text(encoding="utf-8")
    (tmp_path / "loop-engineering.yaml").write_text(
        source.replace("ephemeral: true", 'ephemeral: "true"', 1), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="must be a boolean"):
        load_config(tmp_path)

    (tmp_path / "loop-engineering.yaml").write_text(
        source.replace("version: 1", "version: true", 1), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="version must be an integer"):
        load_config(tmp_path)

    (tmp_path / "loop-engineering.yaml").write_text(
        source.replace("    schema: config/loop-engineering/schemas/plan.schema.json\n", "", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing or unknown fields"):
        load_config(tmp_path)


def test_toolchain_is_snapshotted_outside_coder_workspace_before_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.loop_engineering import tokenizer_cache

    asset = b"pinned fixture"
    url = "https://example.invalid/tokenizer"
    monkeypatch.setattr(
        tokenizer_cache, "ENCODING_ASSETS", ((url, hashlib.sha256(asset).hexdigest()),)
    )
    for relative in (
        ".python",
        ".venv/bin",
        "apps/web/node_modules",
        ".cache/tiktoken",
        ".cache/playwright/ffmpeg-1011",
    ):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    helper = tmp_path / ".cache/playwright/ffmpeg-1011/ffmpeg-mac"
    helper.write_text("tool\n")
    helper.chmod(0o755)
    cache_key = hashlib.sha1(url.encode()).hexdigest()
    (tmp_path / ".cache/tiktoken" / cache_key).write_bytes(asset)
    python = tmp_path / ".venv/bin/python"
    python.write_text("#!/bin/sh\nprintf '%s\\n' \"$0\"\n", encoding="utf-8")
    python.chmod(0o755)
    for name in ("ruff", "mypy"):
        executable = tmp_path / ".venv/bin" / name
        executable.write_text("tool\n", encoding="utf-8")
        executable.chmod(0o755)
    for relative in (
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        "apps/web/package.json",
        "apps/web/package-lock.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("locked\n", encoding="utf-8")

    manager = ToolchainManager(tmp_path, tmp_path.parent / f"{tmp_path.name}-secure-cache")
    snapshot = manager.prepare()
    before = toolchain_fingerprint(snapshot.path)
    (tmp_path / ".venv/bin/ruff").write_text("forged pass\n", encoding="utf-8")

    assert not snapshot.path.is_relative_to(tmp_path)
    assert snapshot.fingerprint == before
    assert toolchain_fingerprint(snapshot.path) == before
    assert (snapshot.path / ".venv/bin/ruff").read_text(encoding="utf-8") == "tool\n"
    assert (snapshot.path / ".cache/tiktoken" / cache_key).read_bytes() == asset
    assert (snapshot.path / ".cache/playwright/ffmpeg-1011/ffmpeg-mac").read_text() == "tool\n"
    helper.chmod(0o644)
    assert any("not a regular executable" in issue for issue in manager.readiness_issues())
    helper.chmod(0o755)
    (tmp_path / ".cache/tiktoken" / cache_key).write_bytes(b"corrupt")
    assert any("tokenizer cache" in issue for issue in manager.readiness_issues())
    assert toolchain_fingerprint(snapshot.path) == before

    (tmp_path / "Makefile").write_text("forged-pass:\n\t@true\n", encoding="utf-8")
    with pytest.raises(ToolchainError, match="gate changed"):
        manager.execution_snapshot(snapshot, "20260824T000000Z-00000000", "qa-test", "0" * 64)


def test_runner_sandbox_profile_denies_default_and_protects_evidence(tmp_path: Path) -> None:
    root = Path.home() / "liveclip-profile-fixture"
    profile = _profile(root, tmp_path)

    assert "(deny default)" in profile
    assert "(allow signal (target same-sandbox))" in profile
    assert "(allow signal)" not in profile
    assert '(allow iokit-open (iokit-registry-entry-class "RootDomainUserClient"))' in profile
    assert "(allow iokit-open)" not in profile
    assert r"^com\.google\.Chrome\.MachPortRendezvousServer\.[0-9]+$" in profile
    assert "(allow mach-register)" not in profile
    assert f'(deny file-write* (subpath "{root / ".git"}"))' in profile
    assert f'(deny file-write* (subpath "{root / ".loop"}"))' in profile
    assert f'(deny file-write* (subpath "{root / "qa"}"))' in profile
    assert f'(allow file-write* (subpath "{root}"))' not in profile
    assert f'(deny file-read* file-write* (literal "{root / ".env"}"))' in profile
    assert f'(allow file-read* (require-not (subpath "{Path.home()}")))' in profile
    assert "(allow file-read*)\n" not in profile
    assert (
        f'(allow file-read-metadata (require-all (literal "{Path.home()}") (vnode-type DIRECTORY)))'
    ) in profile
    assert f'(allow file-read* (subpath "{Path.home()}"))' not in profile
    assert '(allow network-outbound (remote ip "localhost:*"))' in profile
    assert '(allow network-outbound (remote ip "*:*"))' not in profile
    assert f'(allow network-bind (local unix-socket (subpath "{tmp_path / "tmp"}")))' in profile
    assert (
        f'(allow network-outbound (remote unix-socket (subpath "{tmp_path / "tmp"}")))'
    ) in profile
    assert "(allow network-bind (local unix-socket))" not in profile
    assert "(allow network-outbound (remote unix-socket))" not in profile


@pytest.mark.parametrize("attachment_name", [".venv", ".python"])
@pytest.mark.parametrize("attachment_kind", ["file", "symlink"])
def test_nested_dependency_names_remain_in_source_fingerprint(
    tmp_path: Path, attachment_name: str, attachment_kind: str
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Loop Test",
            "-c",
            "user.email=loop@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    before = fingerprint_worktree(tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    path = nested / attachment_name
    if attachment_kind == "file":
        path.write_text("synthetic source marker\n")
    else:
        path.symlink_to("missing-owned-target")
    assert fingerprint_worktree(tmp_path) != before
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=tmp_path,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    assert f"nested/{attachment_name}" in untracked


@pytest.mark.parametrize("replace_attachment", [False, True])
def test_coding_snapshot_round_trips_with_real_project_ignore_rules(
    tmp_path: Path, replace_attachment: bool
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Loop Test",
            "-c",
            "user.email=loop@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    # The old synthetic fixture already ignored links and masked the production mismatch.
    (tmp_path / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
    source = tmp_path / "example.py"
    source.write_text("original\n")
    trusted = _trusted_toolchain(tmp_path)
    manager = ToolchainManager(tmp_path, tmp_path.parent / f"{tmp_path.name}-roundtrip")
    before = fingerprint_worktree(tmp_path)
    coding = manager.execution_snapshot(trusted, "20260912T000000Z-00000000", "coding", before)
    assert (coding.path / ".venv").is_symlink()
    assert (coding.path / ".python").is_symlink()
    assert fingerprint_worktree(coding.path) == before

    (coding.path / "example.py").write_text("reviewable change\n")
    changed = fingerprint_worktree(coding.path)
    assert changed != before
    if replace_attachment:
        (coding.path / ".venv").unlink()
        (coding.path / ".venv/bin").mkdir(parents=True)
        (coding.path / ".venv/bin/ruff").write_text("untrusted tool replacement\n")
        assert fingerprint_worktree(coding.path) == changed

    assurance = manager.execution_snapshot(
        trusted, "20260912T000000Z-00000000", "assurance", changed, source_root=coding.path
    )
    assert fingerprint_worktree(assurance.path) == changed
    assert (assurance.path / "example.py").read_text() == "reviewable change\n"
    assert source.read_text() == "original\n"
    assert (assurance.path / ".venv").resolve() == trusted.path / ".venv"
    assert toolchain_fingerprint(trusted.path) == trusted.fingerprint


def test_relocated_console_script_cannot_use_removed_original_interpreter(tmp_path: Path) -> None:
    source = tmp_path / "source"
    staging = tmp_path / "staging"
    destination = tmp_path / "sealed"
    for root in (source, staging):
        (root / ".venv/bin").mkdir(parents=True)
        # Header-rewrite fixture only: execute the intact signed system shell.
        # Production toolchain readiness separately rejects escaping symlinks.
        (root / ".venv/bin/python").symlink_to("/bin/sh")
    body = b"printf 'SEALED-PROOF\\n'\n"
    original = b"#!" + bytes(str(source / ".venv/bin/python"), "utf-8") + b"\n" + body
    entrypoint = staging / ".venv/bin/probe"
    entrypoint.write_bytes(original)
    entrypoint.chmod(0o755)
    (source / ".venv/bin/python").unlink()
    with pytest.raises(FileNotFoundError):
        subprocess.run([str(entrypoint)], check=False, capture_output=True)
    _rewrite_embedded_paths(source, destination, staging)
    staging.rename(destination)

    completed = subprocess.run(
        [str(destination / ".venv/bin/probe")], check=False, capture_output=True, text=True
    )

    assert completed.returncode == 0
    assert completed.stdout == "SEALED-PROOF\n"
    assert (destination / ".venv/bin/probe").read_bytes().split(b"\n", 1)[1] == body


def test_python_shell_trampoline_relocation_preserves_body(tmp_path: Path) -> None:
    source = tmp_path / "source with spaces"
    staging = tmp_path / "staging"
    destination = tmp_path / "sealed with spaces"
    entrypoint = staging / ".venv/bin/probe"
    entrypoint.parent.mkdir(parents=True)
    body = f"print({str(source)!r})\r\n"
    header = f"#!/bin/sh\n'''exec' \"{source}/.venv/bin/python3.12\" \"$0\" \"$@\"\n' '''\n"
    entrypoint.write_text(header + body)
    entrypoint.chmod(0o755)

    _rewrite_embedded_paths(source, destination, staging)

    expected_header = (
        f"#!/bin/sh\n'''exec' {shlex.quote(str(destination / '.venv/bin/python3.12'))} "
        "\"$0\" \"$@\"\n' '''\n"
    )
    assert entrypoint.read_bytes() == (expected_header + body).encode()
    assert entrypoint.stat().st_mode & 0o111 == 0o111


def test_old_toolchain_manifest_cannot_reuse_unrelocated_entrypoints(tmp_path: Path) -> None:
    (tmp_path / "snapshot.json").write_text(
        json.dumps({"source_fingerprint": "a" * 64, "snapshot_fingerprint": "b" * 64})
    )
    with pytest.raises(ToolchainError, match="format"):
        _snapshot_manifest(tmp_path, "a" * 64)


def test_sealed_node_copy_creates_only_existing_allowed_mutable_caches(tmp_path: Path) -> None:
    source = tmp_path / "sealed-node"
    target = tmp_path / "execution-node"
    source.mkdir()
    package = source / "package.js"
    package.write_text("immutable dependency\n")
    package.chmod(0o444)
    (source / ".vite").mkdir()
    (source / ".vite/old-cache").write_text("discard scratch\n")
    (source / ".vite").chmod(0o555)
    source.chmod(0o555)

    _copy_node_dependencies(source, target)

    assert target.stat().st_mode & 0o222 == 0
    assert (target / "package.js").stat().st_mode & 0o222 == 0
    assert (target / "package.js").read_text() == package.read_text()
    assert not (target / ".vite/old-cache").exists()
    assert (source / ".vite/old-cache").read_text() == "discard scratch\n"
    for name in (".vite", ".vite-temp"):
        (target / name / "probe").write_text("private scratch\n")


def test_static_tool_caches_use_existing_runner_private_scratch() -> None:
    with runner_sandbox(
        ROOT,
        ["/usr/bin/true"],
        {
            "MAC_CHROMIUM_TMPDIR": "/outside",
            "TIKTOKEN_CACHE_DIR": "/outside",
            "PLAYWRIGHT_BROWSERS_PATH": "/outside",
        },
    ) as sandboxed:
        scratch = Path(sandboxed.env["TMPDIR"])
        assert sandboxed.env["MAC_CHROMIUM_TMPDIR"] == str(scratch)
        assert sandboxed.env["TIKTOKEN_CACHE_DIR"] == str(ROOT / ".cache/tiktoken")
        assert sandboxed.env["PLAYWRIGHT_BROWSERS_PATH"] == str(ROOT / ".cache/playwright")
        for name in ("RUFF_CACHE_DIR", "MYPY_CACHE_DIR"):
            assert Path(sandboxed.env[name]).is_relative_to(scratch)
        assert not scratch.is_relative_to(ROOT)
