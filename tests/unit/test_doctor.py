from pathlib import Path

import pytest

import liveclip.cli.doctor as doctor_module
from liveclip.cli.doctor import parse_ffmpeg_filters


def test_parse_ffmpeg_filters_requires_exact_filter_rows() -> None:
    output = """
 Filters:
  .. loudnorm          A->A       EBU R128 loudness normalization
  .. silencedetect     A->A       Detect silence.
  T. overlay           VV->V      Overlay a video source.
  .. notdrawtext       V->V       Description mentions drawtext only.
 """

    names = parse_ffmpeg_filters(output)

    assert {"loudnorm", "silencedetect", "overlay"}.issubset(names)
    assert "drawtext" not in names


def test_doctor_blocks_an_unsafe_application_sqlite_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject_runtime() -> None:
        raise RuntimeError("unsafe WAL runtime")

    monkeypatch.setattr(doctor_module, "assert_supported_sqlite_runtime", reject_runtime)

    result = doctor_module._sqlite_check(tmp_path)

    assert result.status == "fail"
    assert result.details == {
        "version": doctor_module.sqlite3.sqlite_version,
        "error": "RuntimeError",
        "wal_concurrency_safe": False,
    }
