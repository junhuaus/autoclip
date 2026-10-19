from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Protocol, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.agent_runtime.models import json_bytes
from liveclip.media.secure_files import read_regular_text_no_follow

_SKILL_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")
_MAX_RESOURCE_BYTES = 512 * 1024
_MAX_SKILL_BYTES = 2 * 1024 * 1024


class AgentSkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(pattern=r"^1$")
    version: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    entrypoint: str
    includes: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    repair: str
    profiles: str

    @model_validator(mode="after")
    def validate_resources(self) -> AgentSkillManifest:
        values = (self.entrypoint, *self.includes, self.repair, self.profiles)
        if len(set(values)) != len(values):
            raise ValueError("Skill manifest resources must be unique")
        for value in values:
            if not _RESOURCE_NAME.fullmatch(value):
                raise ValueError(f"invalid Skill resource name: {value}")
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe Skill resource name: {value}")
        return self


@dataclass(frozen=True, slots=True)
class LoadedAgentSkill:
    version: str
    instructions: str
    repair: str
    configuration: MappingProxyType[str, object]
    sha256: str
    loaded_files: tuple[str, ...]


def load_packaged_agent_skill(skill_id: str) -> LoadedAgentSkill:
    if not _SKILL_ID.fullmatch(skill_id):
        raise ValueError("invalid packaged Skill identifier")
    root = files("liveclip.clipping_skills").joinpath(skill_id)

    def read_resource(name: str) -> str:
        value = root.joinpath(name).read_text(encoding="utf-8")
        return _validate_resource_text(value, name=name)

    manifest_text = read_resource("manifest.yaml")
    return _load_agent_skill(manifest_text=manifest_text, read_resource=read_resource)


def load_agent_skill_directory(root: Path) -> LoadedAgentSkill:
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError("Skill root must be a directory")

    def read_resource(name: str) -> str:
        if not _RESOURCE_NAME.fullmatch(name):
            raise ValueError(f"invalid Skill resource name: {name}")
        path = (resolved_root / name).resolve(strict=True)
        try:
            path.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("Skill resource escapes its root") from exc
        value = read_regular_text_no_follow(path, max_bytes=_MAX_RESOURCE_BYTES)
        return _validate_resource_text(value, name=name)

    manifest_text = read_resource("manifest.yaml")
    return _load_agent_skill(manifest_text=manifest_text, read_resource=read_resource)


def _load_agent_skill(
    *,
    manifest_text: str,
    read_resource: object,
) -> LoadedAgentSkill:
    if not callable(read_resource):
        raise TypeError("Skill resource reader must be callable")
    try:
        raw_manifest = yaml.safe_load(manifest_text)
    except yaml.YAMLError as exc:
        raise ValueError("Skill manifest is not valid YAML") from exc
    if isinstance(raw_manifest, dict) and isinstance(raw_manifest.get("includes"), list):
        raw_manifest = {**raw_manifest, "includes": tuple(raw_manifest["includes"])}
    manifest = AgentSkillManifest.model_validate(raw_manifest)
    reader = cast("_ResourceReader", read_resource)
    instruction_files = (manifest.entrypoint, *manifest.includes)
    instruction_parts = tuple(reader(name).strip() for name in instruction_files)
    repair = reader(manifest.repair).strip()
    profiles_text = reader(manifest.profiles)
    if any(not value or "\x00" in value for value in (*instruction_parts, repair)):
        raise ValueError("Skill instruction resource is empty or invalid")
    instructions = "\n\n".join(instruction_parts)
    if len(instructions.encode("utf-8")) > _MAX_SKILL_BYTES:
        raise ValueError("compiled Skill instructions exceed the size limit")
    try:
        raw_profiles = yaml.safe_load(profiles_text)
    except yaml.YAMLError as exc:
        raise ValueError("Skill profile configuration is not valid YAML") from exc
    if not isinstance(raw_profiles, dict):
        raise ValueError("Skill profile configuration must be a mapping")
    profiles = _string_key_mapping(raw_profiles, label="Skill profile configuration")
    json_bytes(profiles)
    loaded_files = ("manifest.yaml", *instruction_files, manifest.repair, manifest.profiles)
    identity = {
        "manifest": manifest.model_dump(mode="json"),
        "loaded_files": list(loaded_files),
        "resources": {
            **{
                name: value
                for name, value in zip(instruction_files, instruction_parts, strict=True)
            },
            manifest.repair: repair,
            manifest.profiles: profiles_text,
        },
    }
    digest = hashlib.sha256(json_bytes(identity)).hexdigest()
    return LoadedAgentSkill(
        version=manifest.version,
        instructions=instructions,
        repair=repair,
        configuration=MappingProxyType(profiles),
        sha256=digest,
        loaded_files=loaded_files,
    )


class _ResourceReader(Protocol):
    def __call__(self, name: str) -> str: ...


def _validate_resource_text(value: str, *, name: str) -> str:
    if not value or "\x00" in value:
        raise ValueError(f"Skill resource is empty or invalid: {name}")
    if len(value.encode("utf-8")) > _MAX_RESOURCE_BYTES:
        raise ValueError(f"Skill resource exceeds the size limit: {name}")
    return value


def _string_key_mapping(value: dict[object, object], *, label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{label} keys must be non-empty strings")
        result[key] = item
    return result


__all__ = [
    "AgentSkillManifest",
    "LoadedAgentSkill",
    "load_agent_skill_directory",
    "load_packaged_agent_skill",
]
