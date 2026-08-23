from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files

from liveclip.prompts import EditingPromptBundle


@lru_cache(maxsize=1)
def load_semantic_continuous_skill() -> EditingPromptBundle:
    package = files("liveclip.clipping_skills.semantic_continuous_v1")
    skill = package.joinpath("SKILL.md").read_text(encoding="utf-8").strip()
    repair = package.joinpath("REPAIR.md").read_text(encoding="utf-8").strip()
    if not skill or not repair or "\x00" in skill or "\x00" in repair:
        raise RuntimeError("semantic consolidation Skill is missing or invalid")
    encoded = f"{skill}\0{repair}".encode()
    return EditingPromptBundle(
        version="semantic_continuous_v1",
        initial=skill,
        repair=repair,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
