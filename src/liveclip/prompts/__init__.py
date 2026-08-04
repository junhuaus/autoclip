from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class EditingPromptBundle:
    version: str
    initial: str
    repair: str
    sha256: str


@lru_cache(maxsize=1)
def load_editing_prompts() -> EditingPromptBundle:
    package = files("liveclip.prompts")
    initial = package.joinpath("editing_v1.md").read_text(encoding="utf-8").strip()
    repair = package.joinpath("editing_repair_v1.md").read_text(encoding="utf-8").strip()
    if not initial or not repair or "\x00" in initial or "\x00" in repair:
        raise RuntimeError("versioned editing prompts are missing or invalid")
    encoded = f"{initial}\0{repair}".encode()
    return EditingPromptBundle(
        version="editing_v1",
        initial=initial,
        repair=repair,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
