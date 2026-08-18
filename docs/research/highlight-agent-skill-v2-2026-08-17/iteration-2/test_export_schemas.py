from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("export_schemas.py")
SPEC = importlib.util.spec_from_file_location("highlight_i2_export_schemas", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
EXPORT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = EXPORT
SPEC.loader.exec_module(EXPORT)


def test_exported_schema_inventory_is_iteration2_only() -> None:
    assert set(EXPORT.build_artifacts()) == {
        "combined-discovery.schema.json",
        "selected-copy.schema.json",
        "manifest.json",
    }


def test_schema_check_rejects_extra_directory(tmp_path: Path) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    artifacts = {"one.json": b"{}\n"}
    (schema_dir / "one.json").write_bytes(artifacts["one.json"])
    EXPORT.check_existing(schema_dir, artifacts)
    (schema_dir / "unexpected").mkdir()
    with pytest.raises(RuntimeError, match="file set mismatch"):
        EXPORT.check_existing(schema_dir, artifacts)


def test_schema_helpers_reject_symlink_directory(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symlink"):
        EXPORT.check_existing(linked, {})
    with pytest.raises(RuntimeError, match="symlink"):
        EXPORT.write_new(linked, {})
