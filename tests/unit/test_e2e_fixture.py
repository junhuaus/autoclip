from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "e2e_fixture.py"
_SPEC = importlib.util.spec_from_file_location("liveclip_e2e_fixture", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
allocated_e2e_root = _MODULE.allocated_e2e_root
cleanup_fixture = _MODULE.cleanup_fixture
validated_e2e_root = _MODULE.validated_e2e_root


def test_e2e_root_validation_and_cleanup_use_allocation_identity() -> None:
    root, identity = allocated_e2e_root()
    try:
        assert validated_e2e_root(str(root), expected_identity=identity) == root
        with pytest.raises(ValueError, match="allocated by this run"):
            validated_e2e_root(
                str(root),
                expected_identity=(identity[0], identity[1] + 1),
            )
        assert cleanup_fixture(root, expected_identity=identity)
        assert not root.exists()
    finally:
        if root.exists():
            current = os.stat(root, follow_symlinks=False)
            cleanup_fixture(
                root,
                expected_identity=(current.st_dev, current.st_ino),
            )


def test_e2e_cleanup_refuses_replaced_root() -> None:
    root, identity = allocated_e2e_root()
    detached = root.with_name(f".{root.name}.detached")
    replacement_created = False
    try:
        root.rename(detached)
        root.mkdir(mode=0o700)
        replacement_created = True

        with pytest.raises(ValueError, match="allocated by this run"):
            cleanup_fixture(root, expected_identity=identity)

        assert root.is_dir()
        assert detached.is_dir()
        root.rmdir()
        replacement_created = False
        detached.rename(root)
        assert cleanup_fixture(root, expected_identity=identity)
    finally:
        if replacement_created and root.is_dir():
            root.rmdir()
        if detached.is_dir():
            detached.rename(root)
        if root.is_dir():
            cleanup_fixture(root, expected_identity=identity)
