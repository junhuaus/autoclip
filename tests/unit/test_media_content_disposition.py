"""Stage 19c: download names keep Chinese via RFC 5987 without breaking ASCII names."""

from __future__ import annotations

from urllib.parse import unquote

from liveclip.api.media import content_disposition


def test_ascii_names_keep_the_historical_header() -> None:
    assert content_disposition("liveclip-v001.zip") == 'attachment; filename="liveclip-v001.zip"'


def test_chinese_names_add_utf8_filename_star() -> None:
    value = content_disposition("张老师-精选-v001.zip")
    assert value.startswith('attachment; filename="')
    encoded = value.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == "张老师-精选-v001.zip"
    assert "张" not in value.split(";")[1]


def test_separators_quotes_and_controls_are_neutralized() -> None:
    value = content_disposition('../坏"名\r\n/x.zip')
    decoded = unquote(value.split("filename*=UTF-8''", 1)[1])
    assert "/" not in decoded and '"' not in decoded and "\r" not in decoded
    assert "\n" not in value and "\r" not in value
