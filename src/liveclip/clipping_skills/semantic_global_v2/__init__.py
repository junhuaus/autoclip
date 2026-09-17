from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files

from liveclip.clipping_skills.semantic_global_v1 import (
    SemanticGlobalPromptBundle,
    SemanticProfile,
    load_semantic_global_prompt,
)

SEMANTIC_GLOBAL_REVIEW_V1 = "semantic_global_v1.global_review"
SEMANTIC_GLOBAL_REVIEW_V2 = "semantic_global_v2.global_review"
SEMANTIC_GLOBAL_REVIEW_V3 = "semantic_global_v3.global_review"


@lru_cache(maxsize=2)
def load_semantic_global_v2_review_prompt(
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    """Load the v2 final-review delta over the frozen v1 evidence rules."""

    v1_package = files("liveclip.clipping_skills.semantic_global_v1")
    v2_package = files("liveclip.clipping_skills.semantic_global_v2")
    loaded_files = (
        "semantic_global_v1/main.md",
        "semantic_global_v1/common_rules.md",
        "semantic_global_v1/stages/global_review.md",
        f"semantic_global_v1/profiles/{profile}.md",
        "semantic_global_v2/stages/global_review.md",
    )
    parts = (
        v1_package.joinpath("main.md").read_text(encoding="utf-8").strip(),
        v1_package.joinpath("common_rules.md").read_text(encoding="utf-8").strip(),
        v1_package.joinpath("stages/global_review.md").read_text(encoding="utf-8").strip(),
        v1_package.joinpath(f"profiles/{profile}.md").read_text(encoding="utf-8").strip(),
        v2_package.joinpath("stages/global_review.md").read_text(encoding="utf-8").strip(),
    )
    repair_parts = (
        v1_package.joinpath("stages/global_review_repair.md").read_text(encoding="utf-8").strip(),
        v2_package.joinpath("stages/global_review_repair.md").read_text(encoding="utf-8").strip(),
    )
    if any(not part or "\x00" in part for part in (*parts, *repair_parts)):
        raise RuntimeError("semantic global v2 prompt resource is missing or invalid")
    instructions = "\n\n".join(parts)
    repair = "\n\n".join(repair_parts)
    version = "semantic_global_v2"
    identity = "\0".join((version, "global_review", profile, *loaded_files, instructions, repair))
    return SemanticGlobalPromptBundle(
        version=version,
        stage="global_review",
        profile=profile,
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=loaded_files,
    )


def load_installed_global_review_prompt(
    skill_version: str,
    profile: SemanticProfile,
) -> SemanticGlobalPromptBundle:
    """Route immutable historical runs to their exact installed Prompt."""

    if skill_version == SEMANTIC_GLOBAL_REVIEW_V1:
        return load_semantic_global_prompt("global_review", profile)
    if skill_version == SEMANTIC_GLOBAL_REVIEW_V2:
        return load_semantic_global_v2_review_prompt(profile)
    if skill_version == SEMANTIC_GLOBAL_REVIEW_V3:
        from liveclip.clipping_skills.semantic_global_v3 import (
            load_semantic_global_v3_review_prompt,
        )

        return load_semantic_global_v3_review_prompt(profile)
    raise RuntimeError(f"semantic Global Review Skill is not installed: {skill_version}")


def candidate_assessments_required(skill_version: str) -> bool:
    if skill_version == SEMANTIC_GLOBAL_REVIEW_V1:
        return False
    if skill_version == SEMANTIC_GLOBAL_REVIEW_V2:
        return True
    if skill_version == SEMANTIC_GLOBAL_REVIEW_V3:
        return False
    raise RuntimeError(f"semantic Global Review Skill is not installed: {skill_version}")


__all__ = [
    "SEMANTIC_GLOBAL_REVIEW_V1",
    "SEMANTIC_GLOBAL_REVIEW_V2",
    "SEMANTIC_GLOBAL_REVIEW_V3",
    "candidate_assessments_required",
    "load_installed_global_review_prompt",
    "load_semantic_global_v2_review_prompt",
]
