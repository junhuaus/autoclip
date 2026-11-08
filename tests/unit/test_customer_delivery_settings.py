"""Stage 19b: dual-profile import roots are explicit, env-only settings."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from liveclip.customer_delivery_settings import DualProfileImportSettings

ROOT = Path("/srv/liveclip")


def test_defaults_are_data_evaluations_and_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS", raising=False)
    monkeypatch.delenv("LIVECLIP_DUAL_PROFILE_TRANSCRIPT_ROOTS", raising=False)
    settings = DualProfileImportSettings()

    assert settings.import_roots(ROOT) == (ROOT / "data" / "evaluations",)
    assert settings.transcript_roots(ROOT) == (
        ROOT / "data" / "evaluations",
        ROOT / "input",
    )


def test_environment_overrides_are_split_and_anchored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS", os.pathsep.join(["/abs/runs", "rel/runs", " "])
    )
    monkeypatch.setenv("LIVECLIP_DUAL_PROFILE_TRANSCRIPT_ROOTS", "/abs/transcripts")
    settings = DualProfileImportSettings()

    assert settings.import_roots(ROOT) == (Path("/abs/runs"), ROOT / "rel" / "runs")
    assert settings.transcript_roots(ROOT) == (Path("/abs/transcripts"),)


def test_dotenv_files_are_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS", raising=False)
    (tmp_path / ".env").write_text("LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS=/from/dotenv\n")

    assert DualProfileImportSettings().import_roots(ROOT) == (ROOT / "data" / "evaluations",)
