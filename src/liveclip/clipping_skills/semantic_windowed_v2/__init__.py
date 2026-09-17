from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files

from liveclip.clipping_skills.semantic_global_v1 import (
    SemanticGlobalPromptBundle,
    SemanticProfile,
)
from liveclip.clipping_skills.semantic_windowed_v1 import (
    load_semantic_windowed_discovery_prompt,
)

SEMANTIC_WINDOWED_DISCOVERY_V1 = "semantic_windowed_v1.discovery"
SEMANTIC_WINDOWED_DISCOVERY_V2 = "semantic_windowed_v2.discovery"


@lru_cache(maxsize=2)
def load_semantic_windowed_v2_discovery_prompt(
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    v1 = load_semantic_windowed_discovery_prompt(profile)
    package = files("liveclip.clipping_skills.semantic_windowed_v2")
    delta_path = "semantic_windowed_v2/stages/discovery.md"
    repair_path = "semantic_windowed_v2/stages/repair.md"
    delta = package.joinpath("stages/discovery.md").read_text(encoding="utf-8").strip()
    repair_delta = package.joinpath("stages/repair.md").read_text(encoding="utf-8").strip()
    if not delta or not repair_delta or "\x00" in delta or "\x00" in repair_delta:
        raise RuntimeError("semantic windowed v2 prompt resource is missing or invalid")
    instructions = f"{v1.instructions}\n\n{delta}"
    repair = f"{v1.repair}\n\n{repair_delta}"
    version = "semantic_windowed_v2"
    loaded_files = (*v1.loaded_files, delta_path)
    identity = "\0".join(
        (version, "discovery", profile, *loaded_files, instructions, repair_path, repair)
    )
    return SemanticGlobalPromptBundle(
        version=version,
        stage="discovery",
        profile=profile,
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=loaded_files,
    )


def load_installed_semantic_windowed_discovery_prompt(
    skill_version: str,
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    if skill_version == SEMANTIC_WINDOWED_DISCOVERY_V1:
        return load_semantic_windowed_discovery_prompt(profile)
    if skill_version == SEMANTIC_WINDOWED_DISCOVERY_V2:
        return load_semantic_windowed_v2_discovery_prompt(profile)
    raise RuntimeError(f"semantic windowed Discovery Skill is not installed: {skill_version}")


__all__ = [
    "SEMANTIC_WINDOWED_DISCOVERY_V1",
    "SEMANTIC_WINDOWED_DISCOVERY_V2",
    "load_installed_semantic_windowed_discovery_prompt",
    "load_semantic_windowed_v2_discovery_prompt",
]
