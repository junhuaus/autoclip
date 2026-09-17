from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from .config import ConfigError, codex_feature_args, codex_feature_policy_matches, load_config
from .contracts import RunState
from .process import safe_child_env
from .sandbox import resolve_command, runner_sandbox
from .store import RunStore
from .toolchain import ToolchainManager
from .workflow import LoopWorkflow


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="loop-engineering")
    result.add_argument("--root", type=Path, default=Path.cwd())
    commands = result.add_subparsers(dest="action", required=True)
    init = commands.add_parser("init", help="create a durable run without invoking an agent")
    init.add_argument("requirement", type=Path)
    run = commands.add_parser("run", help="execute or resume the autonomous loop")
    target = run.add_mutually_exclusive_group(required=True)
    target.add_argument("--requirement", type=Path)
    target.add_argument("--run-id")
    status = commands.add_parser("status", help="show durable run state")
    status.add_argument("run_id")
    commands.add_parser("doctor", help="validate config, Codex and profile readiness")
    profiles = commands.add_parser("install-profiles", help="install reviewed profile templates")
    profiles.add_argument("--codex-home", type=Path)
    return result


def _create(store: RunStore, root: Path, requirement_path: Path, limit_bytes: int) -> RunState:
    allowed = (root / "docs" / "requirements").resolve()
    resolved = requirement_path.resolve(strict=True)
    if not resolved.is_relative_to(allowed):
        raise ValueError("requirement must be a file below docs/requirements")
    metadata = resolved.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit_bytes:
        raise ValueError("requirement must be a bounded regular file")
    requirement = resolved.read_text(encoding="utf-8").strip()
    if not requirement:
        raise ValueError("requirement file is empty")
    return store.create(requirement, _git(root, "rev-parse", "HEAD"))


def _doctor(root: Path) -> int:
    config = load_config(root)
    issues: list[str] = []
    executable = shutil.which(config.codex_executable)
    if executable is None:
        issues.append(f"Codex executable not found: {config.codex_executable}")
    child_env = safe_child_env()
    issues.extend(ToolchainManager(root).readiness_issues())
    try:
        with runner_sandbox(root, ["/usr/bin/true"], child_env) as sandboxed:
            probe = subprocess.run(
                sandboxed.argv,
                cwd=root,
                env=sandboxed.env,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        if probe.returncode != 0:
            issues.append("macOS Runner sandbox cannot be activated")
    except (OSError, subprocess.TimeoutExpired) as exc:
        issues.append(f"macOS Runner sandbox check failed: {type(exc).__name__}")
    for command in config.commands.values():
        try:
            resolve_command(command.argv[0], child_env)
        except OSError as exc:
            issues.append(f"Runner command {command.command_id} is unavailable: {exc}")
    codex_home = _codex_home()
    profile_source = root / "config" / "loop-engineering" / "profiles"
    for role, item in config.roles.items():
        if item.profile:
            installed = codex_home / f"{item.profile}.config.toml"
            expected = profile_source / f"{item.profile}.config.toml"
            if not installed.is_file():
                issues.append(f"profile missing for {role.value}: {item.profile}")
            elif installed.read_bytes() != expected.read_bytes():
                issues.append(f"profile differs from reviewed template for {role.value}")
    if executable is not None:
        help_commands = (
            (["exec", "--help"], "exec"),
            (["exec", "resume", "--help"], "resume"),
        )
        for arguments, label in help_commands:
            try:
                completed = subprocess.run(
                    [executable, *arguments],
                    cwd=root,
                    env=safe_child_env(),
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                issues.append(f"Codex {label} help failed: {type(exc).__name__}")
                continue
            help_text = completed.stdout + completed.stderr
            if completed.returncode != 0 or "--output-schema" not in help_text:
                issues.append(f"Codex {label} lacks required structured-output options")
        feature_argv = [executable, *codex_feature_args()]
        feature_argv.extend(["features", "list"])
        try:
            feature_check = subprocess.run(
                feature_argv,
                cwd=root,
                env=safe_child_env(),
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            issues.append(f"Codex feature-policy check failed: {type(exc).__name__}")
        else:
            if feature_check.returncode != 0 or not codex_feature_policy_matches(
                feature_check.stdout
            ):
                issues.append("Codex feature-isolation policy is incompatible")
    if issues:
        print("NOT READY")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"READY root={root} codex={executable} commands={len(config.commands)}")
    return 0


def _install_profiles(root: Path, destination: Path | None) -> int:
    source = root / "config" / "loop-engineering" / "profiles"
    target = (destination or _codex_home()).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("*.config.toml")):
        output = target / path.name
        if output.exists():
            unsafe = not output.is_file() or output.is_symlink()
            if unsafe or output.read_bytes() != path.read_bytes():
                raise FileExistsError(f"refusing to overwrite different profile: {output}")
        else:
            with output.open("xb") as handle:
                handle.write(path.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            output.chmod(0o600)
        print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    store = RunStore(root)
    try:
        if args.action == "doctor":
            return _doctor(root)
        if args.action == "install-profiles":
            return _install_profiles(root, args.codex_home)
        if args.action == "status":
            print(json.dumps(store.load(args.run_id).to_dict(), ensure_ascii=False, indent=2))
            return 0
        config = load_config(root)
        if args.action == "init":
            state = _create(store, root, args.requirement, config.requirement_limit_bytes)
            print(state.run_id)
            return 0
        state = (
            store.load(args.run_id)
            if args.run_id
            else _create(store, root, args.requirement, config.requirement_limit_bytes)
        )
        completed = LoopWorkflow(config, store).run(state)
        print(json.dumps(completed.to_dict(), ensure_ascii=False, indent=2))
        return 0 if completed.state.value == "done" else 1
    except (
        ConfigError,
        FileExistsError,
        OSError,
        ValueError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"ERROR: {exc}")
        return 2


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser().resolve() if configured else (Path.home() / ".codex")
