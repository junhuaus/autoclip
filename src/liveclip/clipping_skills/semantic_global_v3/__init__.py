from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from liveclip.clipping_skills.semantic_global_v1 import (
    SemanticGlobalPromptBundle,
    SemanticProfile,
)

SemanticGlobalV3Stage = Literal["boundary_review", "global_review"]
SEMANTIC_GLOBAL_REVIEW_V3 = "semantic_global_v3.global_review"


@lru_cache(maxsize=4)
def load_semantic_global_v3_prompt(
    stage: SemanticGlobalV3Stage,
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    package = files("liveclip.clipping_skills.semantic_global_v3")
    v1_package = files("liveclip.clipping_skills.semantic_global_v1")
    loaded_files = (
        "semantic_global_v3/main.md",
        f"semantic_global_v3/stages/{stage}.md",
        f"semantic_global_v1/profiles/{profile}.md",
    )
    parts = (
        package.joinpath("main.md").read_text(encoding="utf-8").strip(),
        package.joinpath(f"stages/{stage}.md").read_text(encoding="utf-8").strip(),
        v1_package.joinpath(f"profiles/{profile}.md").read_text(encoding="utf-8").strip(),
    )
    repair = package.joinpath(f"stages/{stage}_repair.md").read_text(encoding="utf-8").strip()
    if any(not value or "\x00" in value for value in (*parts, repair)):
        raise RuntimeError("semantic global v3 prompt resource is missing or invalid")
    instructions = "\n\n".join(parts)
    version = "semantic_global_v3"
    identity = "\0".join((version, stage, profile, *loaded_files, instructions, repair))
    return SemanticGlobalPromptBundle(
        version=version,
        stage=stage,
        profile=profile,
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=loaded_files,
    )


def load_semantic_global_v3_review_prompt(
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    return load_semantic_global_v3_prompt("global_review", profile)


def load_semantic_global_v3_boundary_prompt(
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    return load_semantic_global_v3_prompt("boundary_review", profile)


__all__ = [
    "SEMANTIC_GLOBAL_REVIEW_V3",
    "load_semantic_global_v3_boundary_prompt",
    "load_semantic_global_v3_prompt",
    "load_semantic_global_v3_review_prompt",
]
