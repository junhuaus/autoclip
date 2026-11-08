"""Settings for importing dual-profile results (Stage 19b).

Deliberately separate from ``liveclip.config.settings.Settings``: that module is
inside the frozen dual-profile benchmark closure, and its field set feeds the
benchmark Settings fingerprint. These settings are read only from process
environment variables (never from ``.env`` files).

- ``LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS``: ``os.pathsep``-separated directories a
  run directory must resolve inside. Default ``<repo>/data/evaluations``, where
  ``dual-profile-eval`` runs are written.
- ``LIVECLIP_DUAL_PROFILE_TRANSCRIPT_ROOTS``: directories the transcript SRT must
  resolve inside. Default ``<repo>/data/evaluations`` and ``<repo>/input`` (the
  operator's local-only input directory, beside the source media). Repository
  code or test directories are never allowed by default; an operator who keeps a
  transcript elsewhere names that directory explicitly.

Relative paths given to the import resolve against the repository root.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_paths(value: str) -> tuple[Path, ...]:
    return tuple(Path(item).expanduser() for item in value.split(os.pathsep) if item.strip())


class DualProfileImportSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LIVECLIP_DUAL_PROFILE_",
        env_file=None,
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    import_roots_raw: str = Field(default="", validation_alias="LIVECLIP_DUAL_PROFILE_IMPORT_ROOTS")
    transcript_roots_raw: str = Field(
        default="", validation_alias="LIVECLIP_DUAL_PROFILE_TRANSCRIPT_ROOTS"
    )

    def import_roots(self, project_root: Path) -> tuple[Path, ...]:
        configured = _split_paths(self.import_roots_raw)
        return _absolute(configured or (project_root / "data" / "evaluations",), project_root)

    def transcript_roots(self, project_root: Path) -> tuple[Path, ...]:
        configured = _split_paths(self.transcript_roots_raw)
        defaults = (project_root / "data" / "evaluations", project_root / "input")
        return _absolute(configured or defaults, project_root)


def _absolute(paths: tuple[Path, ...], project_root: Path) -> tuple[Path, ...]:
    return tuple(path if path.is_absolute() else project_root / path for path in paths)


__all__ = ["DualProfileImportSettings"]
