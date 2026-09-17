from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Literal

import yaml

SemanticStage = Literal[
    "discovery",
    "link_review",
    "topic_chain",
    "boundary_review",
    "global_review",
    "boundary_refinement",
]
SemanticProfile = Literal["general", "vocal_coach_live"]


@dataclass(frozen=True, slots=True)
class SemanticGlobalPromptBundle:
    version: str
    stage: SemanticStage
    profile: SemanticProfile
    instructions: str
    repair: str
    sha256: str
    loaded_files: tuple[str, ...]


@lru_cache(maxsize=12)
def load_semantic_global_prompt(
    stage: SemanticStage,
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    package = files("liveclip.clipping_skills.semantic_global_v1")
    raw_manifest = package.joinpath("manifest.yaml").read_text(encoding="utf-8")
    manifest = yaml.safe_load(raw_manifest)
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise RuntimeError("semantic global manifest is invalid")
    try:
        base = tuple(str(value) for value in manifest["base"])
        stage_path = str(manifest["stages"][stage])
        profile_path = str(manifest["profiles"][profile])
        repair_path = str(manifest["repairs"][stage])
        version = str(manifest["name"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError("semantic global prompt stage or profile is not installed") from exc
    loaded = (*base, stage_path, profile_path)
    if any(
        path.startswith(("/", ".")) or ".." in path.split("/") for path in (*loaded, repair_path)
    ):
        raise RuntimeError("semantic global manifest contains an unsafe resource path")
    parts = [package.joinpath(path).read_text(encoding="utf-8").strip() for path in loaded]
    repair = package.joinpath(repair_path).read_text(encoding="utf-8").strip()
    if any(not part or "\x00" in part for part in (*parts, repair)):
        raise RuntimeError("semantic global prompt resource is missing or invalid")
    instructions = "\n\n".join(parts)
    identity = "\0".join((version, stage, profile, *loaded, instructions, repair))
    return SemanticGlobalPromptBundle(
        version=version,
        stage=stage,
        profile=profile,
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=loaded,
    )


__all__ = [
    "SemanticGlobalPromptBundle",
    "SemanticProfile",
    "SemanticStage",
    "load_semantic_global_prompt",
]
