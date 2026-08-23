from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files

import yaml

from liveclip.clipping_skills.semantic_global_v1 import (
    SemanticGlobalPromptBundle,
    SemanticProfile,
)


@lru_cache(maxsize=2)
def load_semantic_windowed_discovery_prompt(
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    package = files("liveclip.clipping_skills.semantic_windowed_v1")
    raw_manifest = package.joinpath("manifest.yaml").read_text(encoding="utf-8")
    manifest = yaml.safe_load(raw_manifest)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise RuntimeError("semantic windowed manifest is invalid")
    try:
        base = tuple(str(value) for value in manifest["base"])
        stage_path = str(manifest["stages"]["discovery"])
        profile_path = str(manifest["profiles"][profile])
        repair_path = str(manifest["repairs"]["discovery"])
        version = str(manifest["name"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError("semantic windowed prompt profile is not installed") from exc
    loaded = (*base, stage_path, profile_path)
    if any(
        path.startswith(("/", ".")) or ".." in path.split("/") for path in (*loaded, repair_path)
    ):
        raise RuntimeError("semantic windowed manifest contains an unsafe resource path")
    parts = [package.joinpath(path).read_text(encoding="utf-8").strip() for path in loaded]
    repair = package.joinpath(repair_path).read_text(encoding="utf-8").strip()
    if any(not value or "\x00" in value for value in (*parts, repair)):
        raise RuntimeError("semantic windowed prompt resource is missing or invalid")
    instructions = "\n\n".join(parts)
    identity = "\0".join((version, "discovery", profile, *loaded, instructions, repair))
    return SemanticGlobalPromptBundle(
        version=version,
        stage="discovery",
        profile=profile,
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=loaded,
    )


__all__ = ["load_semantic_windowed_discovery_prompt"]
