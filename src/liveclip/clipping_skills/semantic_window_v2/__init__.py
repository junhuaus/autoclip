from __future__ import annotations

import hashlib
from functools import lru_cache
from importlib.resources import files

from liveclip.prompts import EditingPromptBundle


@lru_cache(maxsize=1)
def load_semantic_window_skill() -> EditingPromptBundle:
    package = files("liveclip.clipping_skills.semantic_window_v2")
    skill = package.joinpath("SKILL.md").read_text(encoding="utf-8").strip()
    scoring = package.joinpath("SCORING.md").read_text(encoding="utf-8").strip()
    repair = package.joinpath("REPAIR.md").read_text(encoding="utf-8").strip()
    initial = f"{skill}\n\n{scoring}"
    if not skill or not scoring or not repair or "\x00" in initial or "\x00" in repair:
        raise RuntimeError("semantic clipping Skill is missing or invalid")
    encoded = f"{initial}\0{repair}".encode()
    return EditingPromptBundle(
        version="semantic_window_v2",
        initial=initial,
        repair=repair,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
