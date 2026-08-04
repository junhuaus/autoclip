from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

CHINESE_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
)
REQUIRED_CHINESE_GLYPHS = "中文直播高光字幕标题，。！？：；“”‘’0123456789ABCxyz"  # noqa: RUF001


def available_chinese_fonts() -> tuple[Path, ...]:
    return tuple(
        candidate
        for candidate in CHINESE_FONT_CANDIDATES
        if candidate.is_file() and font_supports_text(candidate, REQUIRED_CHINESE_GLYPHS)
    )


def font_supports_text(path: Path, text: str) -> bool:
    try:
        font = _coverage_font(str(path.resolve(strict=True)))
    except (OSError, ValueError):
        return False
    missing_signature = _glyph_signature(font, "\u0378")
    for character in set(text):
        category = unicodedata.category(character)
        if character.isspace() or category.startswith("C"):
            continue
        if _glyph_signature(font, character) == missing_signature:
            return False
    return True


def resolve_font_for_text(text: str, *, preferred: Path | None = None) -> Path:
    candidates: tuple[Path, ...] = (
        *((preferred,) if preferred is not None else ()),
        *(candidate for candidate in CHINESE_FONT_CANDIDATES if candidate != preferred),
    )
    for candidate in candidates:
        if candidate.is_file() and font_supports_text(candidate, text):
            return Path(candidate.resolve(strict=True))
    raise ValueError("no configured Chinese font covers all requested text glyphs")


def detect_chinese_font(text: str = REQUIRED_CHINESE_GLYPHS) -> Path:
    try:
        return resolve_font_for_text(text)
    except ValueError as exc:
        raise FileNotFoundError("no supported Chinese font covers required glyphs") from exc


@lru_cache(maxsize=8)
def _coverage_font(path: str) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, 32)


def _glyph_signature(
    font: ImageFont.FreeTypeFont,
    character: str,
) -> tuple[tuple[int, int], tuple[int, int, int, int], bytes]:
    mask = font.getmask(character, mode="L")
    raw_bounds = font.getbbox(character)
    size = (int(mask.size[0]), int(mask.size[1]))
    bounds = (
        int(raw_bounds[0]),
        int(raw_bounds[1]),
        int(raw_bounds[2]),
        int(raw_bounds[3]),
    )
    return size, bounds, bytes(mask)
