from PIL import ImageFont

from liveclip.renderer.text import _wrap_text, detect_chinese_font


def test_wrap_text_does_not_claim_truncation_only_because_space_is_trimmed() -> None:
    font = ImageFont.truetype(str(detect_chinese_font()), 32)
    value = "第二句字幕不会进入 FFmpeg 的可执行语法。"

    lines = _wrap_text(value, font=font, maximum_width=450, max_lines=2)

    assert not lines[-1].endswith("…")
    assert "FFmpeg" in "".join(lines)
