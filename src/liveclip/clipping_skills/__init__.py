"""Versioned, data-only instructions for model-driven clipping algorithms."""

from liveclip.clipping_skills.semantic_continuous_v1 import (
    load_semantic_continuous_skill,
)
from liveclip.clipping_skills.semantic_window_v1 import load_semantic_window_skill as load_v1
from liveclip.clipping_skills.semantic_window_v2 import load_semantic_window_skill as load_v2
from liveclip.prompts import EditingPromptBundle


def load_semantic_discovery_skill(version: str) -> EditingPromptBundle:
    loaders = {
        "semantic_window_v1": load_v1,
        "semantic_window_v2": load_v2,
    }
    try:
        return loaders[version]()
    except KeyError as exc:
        raise RuntimeError("semantic discovery Skill version is not installed") from exc


__all__ = [
    "load_semantic_continuous_skill",
    "load_semantic_discovery_skill",
]
