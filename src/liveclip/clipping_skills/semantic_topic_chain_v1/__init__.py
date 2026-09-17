from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from liveclip.clipping_skills.semantic_global_v1 import (
    SemanticGlobalPromptBundle,
    SemanticProfile,
)
from liveclip.domain.clip_profile import ClipProfile

TopicChainStage = Literal[
    "discovery",
    "link_review",
    "topic_chain",
    "boundary_review",
    "global_review",
]

SEMANTIC_TOPIC_CHAIN_VERSION = "semantic_topic_chain_v1"
SEMANTIC_TOPIC_CHAIN_DISCOVERY = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.discovery"
SEMANTIC_TOPIC_CHAIN_LINK_REVIEW = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.link_review"
SEMANTIC_TOPIC_CHAIN_ASSEMBLY = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.topic_chain"
SEMANTIC_TOPIC_CHAIN_BOUNDARY_REVIEW = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.boundary_review"
SEMANTIC_TOPIC_CHAIN_GLOBAL_REVIEW = f"{SEMANTIC_TOPIC_CHAIN_VERSION}.global_review"


@lru_cache(maxsize=20)
def load_semantic_topic_chain_prompt(
    stage: TopicChainStage,
    semantic_profile: SemanticProfile,
    clip_profile: ClipProfile,
) -> SemanticGlobalPromptBundle:
    package = files("liveclip.clipping_skills.semantic_topic_chain_v1")
    v1_package = files("liveclip.clipping_skills.semantic_global_v1")
    loaded_files = (
        "semantic_topic_chain_v1/main.md",
        f"semantic_topic_chain_v1/stages/{stage}.md",
        f"semantic_topic_chain_v1/profiles/{clip_profile.value}.md",
        f"semantic_global_v1/profiles/{semantic_profile}.md",
    )
    parts = (
        package.joinpath("main.md").read_text(encoding="utf-8").strip(),
        package.joinpath(f"stages/{stage}.md").read_text(encoding="utf-8").strip(),
        package.joinpath(f"profiles/{clip_profile.value}.md").read_text(encoding="utf-8").strip(),
        v1_package.joinpath(f"profiles/{semantic_profile}.md").read_text(encoding="utf-8").strip(),
    )
    repair_path = "semantic_topic_chain_v1/repair.md"
    repair = package.joinpath("repair.md").read_text(encoding="utf-8").strip()
    if any(not value or "\x00" in value for value in (*parts, repair)):
        raise RuntimeError("semantic Topic Chain prompt resource is missing or invalid")
    instructions = "\n\n".join(parts)
    identity = "\0".join(
        (
            SEMANTIC_TOPIC_CHAIN_VERSION,
            stage,
            semantic_profile,
            clip_profile.value,
            *loaded_files,
            instructions,
            repair_path,
            repair,
        )
    )
    return SemanticGlobalPromptBundle(
        version=SEMANTIC_TOPIC_CHAIN_VERSION,
        stage=stage,
        profile=semantic_profile,
        instructions=instructions,
        repair=repair,
        sha256=hashlib.sha256(identity.encode()).hexdigest(),
        loaded_files=loaded_files,
    )


__all__ = [
    "SEMANTIC_TOPIC_CHAIN_ASSEMBLY",
    "SEMANTIC_TOPIC_CHAIN_BOUNDARY_REVIEW",
    "SEMANTIC_TOPIC_CHAIN_DISCOVERY",
    "SEMANTIC_TOPIC_CHAIN_GLOBAL_REVIEW",
    "SEMANTIC_TOPIC_CHAIN_LINK_REVIEW",
    "SEMANTIC_TOPIC_CHAIN_VERSION",
    "TopicChainStage",
    "load_semantic_topic_chain_prompt",
]
