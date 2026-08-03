from pathlib import Path

CHINESE_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
    Path("/System/Library/Fonts/STHeiti Light.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
)


def available_chinese_fonts() -> tuple[Path, ...]:
    return tuple(candidate for candidate in CHINESE_FONT_CANDIDATES if candidate.is_file())


def detect_chinese_font() -> Path:
    fonts = available_chinese_fonts()
    if not fonts:
        raise FileNotFoundError("no supported Chinese font is available")
    return fonts[0]
