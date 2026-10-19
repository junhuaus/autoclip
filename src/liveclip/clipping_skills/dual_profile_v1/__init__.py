from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from liveclip.clipping_skills.semantic_global_v1 import SemanticGlobalPromptBundle
from liveclip.domain.clip_profile import ClipProfile

DualProfileStage = Literal[
    "discovery",
    "coverage_audit",
    "precision_audit",
    "precision_confirmation",
    "risk_discovery",
    "boundary_review",
    "global_review",
    "global_audit",
]


@lru_cache(maxsize=16)
def load_dual_profile_prompt(
    stage: DualProfileStage,
    clip_profile: ClipProfile,
) -> SemanticGlobalPromptBundle:
    package = files("liveclip.clipping_skills.dual_profile_v1")
    resources = (
        "dual_profile_v1/main.md",
        f"dual_profile_v1/profiles/{clip_profile.value}.md",
        f"dual_profile_v1/stages/{stage}.md",
    )
    parts = [
        package.joinpath(path.removeprefix("dual_profile_v1/")).read_text(encoding="utf-8").strip()
        for path in resources
    ]
    repair_path = "dual_profile_v1/repair.md"
    repair = package.joinpath("repair.md").read_text(encoding="utf-8").strip()
    if stage in {
        "discovery",
        "coverage_audit",
        "precision_audit",
        "precision_confirmation",
        "risk_discovery",
    }:
        repair += (
            "\n\nFor this Discovery-stage repair, preserve every candidate that can satisfy "
            "the deterministic error on real cue boundaries without unrelated padding. If an "
            "optional candidate cannot satisfy the requested Profile duration, ownership, cue "
            "truth or ID rule, omit that invalid candidate from the replacement output; do not "
            "expand it with unrelated content and do not change or hide any other valid or risky "
            "candidate."
        )
    if any(not value or "\x00" in value for value in (*parts, repair)):
        raise RuntimeError("dual Profile prompt resource is missing or invalid")
    instructions = "\n\n".join(parts)
    version = "dual_profile_v1"
    identity = "\0".join(
        (version, stage, clip_profile.value, *resources, instructions, repair_path, repair)
    )
    bundle_stage: Literal["discovery", "boundary_review", "global_review"]
    if stage in {
        "coverage_audit",
        "precision_audit",
        "precision_confirmation",
        "risk_discovery",
    }:
        bundle_stage = "discovery"
    elif stage == "boundary_review":
        bundle_stage = "boundary_review"
    else:
        bundle_stage = "global_review"
    return SemanticGlobalPromptBundle(
        version=version,
        stage=bundle_stage,
        profile="vocal_coach_live",
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=(*resources, repair_path),
    )


@lru_cache(maxsize=1)
def load_dual_profile_variant_link_prompt() -> SemanticGlobalPromptBundle:
    package = files("liveclip.clipping_skills.dual_profile_v1")
    resources = ("dual_profile_v1/stages/variant_link.md",)
    parts = [
        package.joinpath(path.removeprefix("dual_profile_v1/")).read_text(encoding="utf-8").strip()
        for path in resources
    ]
    repair_path = "dual_profile_v1/repair.md"
    repair = package.joinpath("repair.md").read_text(encoding="utf-8").strip()
    if any(not value or "\x00" in value for value in (*parts, repair)):
        raise RuntimeError("dual Profile Variant Link prompt resource is missing or invalid")
    instructions = "\n\n".join(parts)
    identity = "\0".join(
        (
            "dual_profile_v1",
            "variant_link",
            "cross_profile",
            *resources,
            instructions,
            repair_path,
            repair,
        )
    )
    return SemanticGlobalPromptBundle(
        version="dual_profile_v1",
        stage="global_review",
        profile="vocal_coach_live",
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=(*resources, repair_path),
    )


__all__ = [
    "DualProfileStage",
    "load_dual_profile_prompt",
    "load_dual_profile_variant_link_prompt",
]
