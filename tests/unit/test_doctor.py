from pathlib import Path

import pytest

import liveclip.cli.doctor as doctor_module
from liveclip.cli.doctor import parse_ffmpeg_filters
from liveclip.config import Settings
from liveclip.providers.asr.mlx import MLXModelSnapshot


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


def test_doctor_reports_selected_full_precision_mlx_snapshot_without_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = (tmp_path / "large-v3").resolve()
    snapshot = MLXModelSnapshot(
        path=model_path,
        sha256="a" * 64,
        config_sha256="b" * 64,
        weights_sha256="c" * 64,
        weights_size_bytes=3_000_000_000,
    )
    monkeypatch.setattr(doctor_module, "assert_mlx_asr_ready", lambda _path: snapshot)

    result = doctor_module._mlx_asr_check(
        Settings(
            ai_provider="mlx-codex",
            mlx_asr_model_path=model_path,
            _env_file=None,
        )
    )

    assert result.status == "pass"
    assert result.details["model_snapshot"] == "a" * 64
    assert str(model_path) not in repr(result)


def test_doctor_does_not_probe_unselected_mlx_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor_module,
        "assert_mlx_asr_ready",
        lambda _path: (_ for _ in ()).throw(AssertionError("must not probe MLX")),
    )

    result = doctor_module._mlx_asr_check(Settings(ai_provider="openrouter-codex", _env_file=None))

    assert result.status == "pass"
    assert result.details["selected"] is False
