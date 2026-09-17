"""Fixed, opt-in ADR041 resources; selectors are validated before resource lookup."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from liveclip.clipping_skills.semantic_global_v1 import (
    SemanticGlobalPromptBundle,
    SemanticProfile,
)
from liveclip.domain.clip_profile import ClipProfile

TopicChainStage = Literal["discovery", "topic_chain", "boundary_review"]
SEMANTIC_TOPIC_CHAIN_VERSION = "semantic_topic_chain_v2"
SEMANTIC_TOPIC_CHAIN_DISCOVERY = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.discovery"
SEMANTIC_TOPIC_CHAIN_ASSEMBLY = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.topic_chain"
SEMANTIC_TOPIC_CHAIN_BOUNDARY_REVIEW = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.boundary_review"


@lru_cache(maxsize=6)
def load_semantic_topic_chain_prompt(
    stage: TopicChainStage,
    semantic_profile: SemanticProfile,
    clip_profile: ClipProfile,
) -> SemanticGlobalPromptBundle:
    if stage not in ("discovery", "topic_chain", "boundary_review"):
        raise ValueError("unsupported lineage stage")
    if semantic_profile not in ("general", "vocal_coach_live"):
        raise ValueError("unsupported semantic profile")
    if not isinstance(clip_profile, ClipProfile) or clip_profile != ClipProfile.MINI_LESSON:
        raise ValueError("lineage prompts require mini_lesson")
    package = files("liveclip.clipping_skills.semantic_topic_chain_v2")
    domain = files("liveclip.clipping_skills.semantic_global_v1")
    names = ("main.md", f"stages/{stage}.md", "profiles/mini_lesson.md", "repair.md")
    resources = tuple(
        (f"semantic_topic_chain_v2/{name}", package.joinpath(name).read_text(encoding="utf-8"))
        for name in names
    )
    domain_name = f"profiles/{semantic_profile}.md"
    resources += (
        (
            f"semantic_global_v1/{domain_name}",
            domain.joinpath(domain_name).read_text(encoding="utf-8"),
        ),
    )
    if any(not text.strip() or "\x00" in text for _, text in resources):
        raise RuntimeError("invalid lineage prompt resource")
    identity = json.dumps(
        (SEMANTIC_TOPIC_CHAIN_VERSION, stage, semantic_profile, clip_profile.value, resources),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return SemanticGlobalPromptBundle(
        version=SEMANTIC_TOPIC_CHAIN_VERSION,
        stage=stage,
        profile=semantic_profile,
        instructions="\n\n".join(resources[i][1].strip() for i in (0, 1, 2, 4)),
        repair=resources[3][1].strip(),
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=tuple(name for name, _ in resources),
    )
