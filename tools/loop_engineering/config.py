from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .contracts import Role

CODEX_DISABLED_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode",
    "computer_use",
    "goals",
    "hooks",
    "image_generation",
    "in_app_browser",
    "multi_agent",
    "multi_agent_v2",
    "plugin_sharing",
    "plugins",
    "recommended_plugins",
    "remote_plugin",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "workspace_dependencies",
)

# Current Codex models use this bundled local tool transport even when the
# optional code_mode feature is off. Role sandbox and approval remain separate.
CODEX_REQUIRED_FEATURES = ("code_mode_host",)


def codex_feature_args() -> list[str]:
    return [
        argument
        for flag, features in (
            ("--enable", CODEX_REQUIRED_FEATURES),
            ("--disable", CODEX_DISABLED_FEATURES),
        )
        for feature in features
        for argument in (flag, feature)
    ]


def codex_feature_policy_matches(output: str) -> bool:
    observed: dict[str, bool] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[-1] in {"true", "false"}:
            if fields[0] in observed:
                return False
            observed[fields[0]] = fields[-1] == "true"
    return all(observed.get(name) is True for name in CODEX_REQUIRED_FEATURES) and all(
        observed.get(name) is False for name in CODEX_DISABLED_FEATURES
    )


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RoleConfig:
    profile: str | None
    sandbox: str
    schema: Path
    prompt: Path
    ephemeral: bool


@dataclass(frozen=True)
class CommandConfig:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    required_for_final: bool


@dataclass(frozen=True)
class LoopConfig:
    root: Path
    codex_executable: str
    roles: dict[Role, RoleConfig]
    commands: dict[str, CommandConfig]
    max_plan_cycles: int
    max_code_cycles: int
    log_limit_bytes: int
    requirement_limit_bytes: int


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a mapping")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be a boolean")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{label} must be an integer")
    return value


def load_config(root: Path, path: Path | None = None) -> LoopConfig:
    root = root.resolve()
    config_path = (path or root / "loop-engineering.yaml").resolve()
    if not config_path.is_relative_to(root) or not config_path.is_file():
        raise ConfigError("loop-engineering config must be a repository file")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = _mapping(raw, "config")
    if set(data) != {"version", "codex_executable", "roles", "commands", "limits"}:
        raise ConfigError("config has missing or unknown top-level fields")
    if _integer(data.get("version"), "version") != 1:
        raise ConfigError("loop-engineering config version must be 1")
    codex_executable = data.get("codex_executable")
    if not isinstance(codex_executable, str) or not codex_executable:
        raise ConfigError("codex_executable must be a nonempty string")

    role_data = _mapping(data.get("roles"), "roles")
    if set(role_data) != {role.value for role in Role}:
        raise ConfigError("roles must contain exactly the five supported roles")
    roles: dict[Role, RoleConfig] = {}
    for role in Role:
        item = _mapping(role_data.get(role.value), f"roles.{role.value}")
        if set(item) != {"profile", "sandbox", "schema", "prompt", "ephemeral"}:
            raise ConfigError(f"roles.{role.value} has missing or unknown fields")
        sandbox = item.get("sandbox")
        if sandbox not in {"read-only", "workspace-write"}:
            raise ConfigError(f"invalid sandbox for {role.value}")
        profile = item.get("profile")
        schema_value_raw = item.get("schema")
        prompt_value_raw = item.get("prompt")
        if not isinstance(profile, str) or not profile:
            raise ConfigError(f"roles.{role.value}.profile must be a nonempty string")
        if not isinstance(schema_value_raw, str) or not schema_value_raw:
            raise ConfigError(f"roles.{role.value}.schema must be a nonempty string")
        if not isinstance(prompt_value_raw, str) or not prompt_value_raw:
            raise ConfigError(f"roles.{role.value}.prompt must be a nonempty string")
        schema = (root / schema_value_raw).resolve()
        prompt = (root / prompt_value_raw).resolve()
        for resolved, label in ((schema, "schema"), (prompt, "prompt")):
            if not resolved.is_relative_to(root) or not resolved.is_file():
                raise ConfigError(f"{role.value} {label} must be a repository file")
        try:
            schema_value = json.loads(schema.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{role.value} schema must be valid JSON") from exc
        if not isinstance(schema_value, dict) or schema_value.get("type") != "object":
            raise ConfigError(f"{role.value} schema must describe an object")
        ephemeral_raw = item.get("ephemeral", role is not Role.CODER)
        roles[role] = RoleConfig(
            profile=profile,
            sandbox=sandbox,
            schema=schema,
            prompt=prompt,
            ephemeral=_boolean(ephemeral_raw, f"roles.{role.value}.ephemeral"),
        )
    for role, role_config in roles.items():
        expected_sandbox = "workspace-write" if role is Role.CODER else "read-only"
        expected_ephemeral = role is not Role.CODER
        if (
            role_config.sandbox != expected_sandbox
            or role_config.ephemeral is not expected_ephemeral
        ):
            raise ConfigError(f"{role.value} violates the fixed role-isolation policy")
        if role_config.profile != f"liveclip-loop-{role.value}":
            raise ConfigError(f"{role.value} must use its reviewed named profile")
        profile_path = (
            root / "config" / "loop-engineering" / "profiles" / f"{role_config.profile}.config.toml"
        )
        if not profile_path.is_file() or profile_path.is_symlink():
            raise ConfigError(f"{role.value} reviewed profile template is missing or unsafe")

    command_data = _mapping(data.get("commands"), "commands")
    commands: dict[str, CommandConfig] = {}
    for command_id, raw_command in command_data.items():
        valid_id = isinstance(command_id, str) and re.fullmatch(
            r"[a-z][a-z0-9_-]{0,39}", command_id
        )
        if not valid_id:
            raise ConfigError("command IDs must use lowercase allowlist names")
        item = _mapping(raw_command, f"commands.{command_id}")
        if set(item) != {"argv", "timeout_seconds", "required_for_final"}:
            raise ConfigError(f"commands.{command_id} has missing or unknown fields")
        argv = item.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(value, str) and value for value in argv)
        ):
            raise ConfigError(f"commands.{command_id}.argv must be a nonempty string list")
        timeout_seconds = _integer(
            item.get("timeout_seconds", 900), f"commands.{command_id}.timeout_seconds"
        )
        if not 1 <= timeout_seconds <= 86_400:
            raise ConfigError(f"commands.{command_id}.timeout_seconds is out of range")
        commands[command_id] = CommandConfig(
            command_id=command_id,
            argv=tuple(argv),
            timeout_seconds=timeout_seconds,
            required_for_final=_boolean(
                item.get("required_for_final", True),
                f"commands.{command_id}.required_for_final",
            ),
        )

    limits = _mapping(data.get("limits", {}), "limits")
    if set(limits) != {
        "max_plan_cycles",
        "max_code_cycles",
        "log_limit_bytes",
        "requirement_limit_bytes",
    }:
        raise ConfigError("limits has missing or unknown fields")
    max_plan_cycles = _integer(limits.get("max_plan_cycles", 2), "limits.max_plan_cycles")
    max_code_cycles = _integer(limits.get("max_code_cycles", 3), "limits.max_code_cycles")
    log_limit_bytes = _integer(limits.get("log_limit_bytes", 1_000_000), "limits.log_limit_bytes")
    requirement_limit_bytes = _integer(
        limits.get("requirement_limit_bytes", 131_072), "limits.requirement_limit_bytes"
    )
    if not 1 <= max_plan_cycles <= 10 or not 1 <= max_code_cycles <= 20:
        raise ConfigError("loop repair limits are out of range")
    if not 4_096 <= log_limit_bytes <= 16_000_000:
        raise ConfigError("log_limit_bytes is out of range")
    if not 1_024 <= requirement_limit_bytes <= 1_000_000:
        raise ConfigError("requirement_limit_bytes is out of range")
    return LoopConfig(
        root=root,
        codex_executable=codex_executable,
        roles=roles,
        commands=commands,
        max_plan_cycles=max_plan_cycles,
        max_code_cycles=max_code_cycles,
        log_limit_bytes=log_limit_bytes,
        requirement_limit_bytes=requirement_limit_bytes,
    )
