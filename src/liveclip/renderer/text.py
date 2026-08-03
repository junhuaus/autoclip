from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from liveclip.config.fonts import detect_chinese_font


@dataclass(frozen=True, slots=True)
class TextOverlay:
    path: Path
    start_ms: int
    end_ms: int
    safe_bounds: tuple[int, int, int, int]
    kind: str


def normalize_display_text(value: str, *, maximum_characters: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.replace("\r", " ").replace("\n", " ").split())
    normalized = "".join(
        character for character in normalized if unicodedata.category(character) != "Cc"
    )
    return normalized[:maximum_characters].strip()


def render_title_overlay(
    *,
    output_path: Path,
    width: int,
    height: int,
    text: str,
    start_ms: int,
    end_ms: int,
    font_path: Path | None = None,
) -> TextOverlay:
    clean_text = normalize_display_text(text, maximum_characters=40)
    if not clean_text:
        raise ValueError("title cannot be empty after normalization")
    scale = width / 540
    margin_x = round(32 * scale)
    top = round(74 * (height / 960))
    font = ImageFont.truetype(str(font_path or detect_chinese_font()), round(34 * scale))
    lines = _wrap_text(
        clean_text,
        font=font,
        maximum_width=width - 2 * margin_x - round(36 * scale),
        max_lines=2,
    )
    padding_x = round(18 * scale)
    padding_y = round(13 * scale)
    line_gap = round(5 * scale)
    text_box = _multiline_bbox(lines, font=font, line_gap=line_gap)
    box_height = text_box[3] - text_box[1] + 2 * padding_y
    box = (margin_x, top, width - margin_x, top + box_height)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box, radius=round(16 * scale), fill=(12, 18, 28, 208))
    draw.multiline_text(
        (box[0] + padding_x, box[1] + padding_y - text_box[1]),
        "\n".join(lines),
        font=font,
        fill=(255, 255, 255, 255),
        spacing=line_gap,
        stroke_width=max(1, round(scale)),
        stroke_fill=(0, 0, 0, 150),
    )
    _save_rgba(image, output_path)
    return TextOverlay(output_path, start_ms, end_ms, box, "title")


def render_caption_overlay(
    *,
    output_path: Path,
    width: int,
    height: int,
    text: str,
    start_ms: int,
    end_ms: int,
    font_path: Path | None = None,
) -> TextOverlay:
    clean_text = normalize_display_text(text, maximum_characters=120)
    if not clean_text:
        raise ValueError("caption cannot be empty after normalization")
    scale = width / 540
    font = ImageFont.truetype(str(font_path or detect_chinese_font()), round(32 * scale))
    margin_x = round(28 * scale)
    padding_x = round(18 * scale)
    padding_y = round(13 * scale)
    line_gap = round(6 * scale)
    lines = _wrap_text(
        clean_text,
        font=font,
        maximum_width=width - 2 * margin_x - 2 * padding_x,
        max_lines=2,
    )
    text_box = _multiline_bbox(lines, font=font, line_gap=line_gap)
    box_height = text_box[3] - text_box[1] + 2 * padding_y
    safe_bottom = height - round(142 * (height / 960))
    box = (margin_x, safe_bottom - box_height, width - margin_x, safe_bottom)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box, radius=round(14 * scale), fill=(0, 0, 0, 185))
    total_width = max(_line_width(line, font) for line in lines)
    x = max(box[0] + padding_x, (width - total_width) / 2)
    draw.multiline_text(
        (x, box[1] + padding_y - text_box[1]),
        "\n".join(lines),
        font=font,
        fill=(255, 255, 255, 255),
        spacing=line_gap,
        align="center",
        stroke_width=max(1, round(1.5 * scale)),
        stroke_fill=(0, 0, 0, 230),
    )
    _save_rgba(image, output_path)
    return TextOverlay(output_path, start_ms, end_ms, box, "caption")


def _wrap_text(
    value: str,
    *,
    font: ImageFont.FreeTypeFont,
    maximum_width: int,
    max_lines: int,
) -> tuple[str, ...]:
    lines: list[str] = []
    current = ""
    truncated = False
    for character in value:
        proposal = current + character
        if current and _line_width(proposal, font) > maximum_width:
            lines.append(current.rstrip())
            if len(lines) == max_lines:
                truncated = True
                break
            current = character.lstrip()
        else:
            current = proposal
    if len(lines) < max_lines and current:
        lines.append(current.rstrip())
    if not lines:
        lines = [value[:1]]
    if truncated:
        last = lines[-1]
        while last and _line_width(last + "…", font) > maximum_width:
            last = last[:-1]
        lines[-1] = (last or value[:1]) + "…"
    return tuple(lines[:max_lines])


def _line_width(value: str, font: ImageFont.FreeTypeFont) -> int:
    box = font.getbbox(value)
    return int(box[2] - box[0])


def _multiline_bbox(
    lines: tuple[str, ...], *, font: ImageFont.FreeTypeFont, line_gap: int
) -> tuple[int, int, int, int]:
    image = Image.new("L", (4, 4))
    draw = ImageDraw.Draw(image)
    bounds = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font, spacing=line_gap)
    return (int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3]))


def _save_rgba(image: Image.Image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() != ".png":
        raise ValueError("text overlay must be a PNG")
    image.save(output_path, format="PNG", optimize=True)
