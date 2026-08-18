#!/usr/bin/env python3
"""Export and verify the frozen iteration-2 generator JSON Schemas."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
CONTRACTS_PATH = SCRIPT_DIR / "contracts.py"
DEFAULT_SCHEMA_DIR = SCRIPT_DIR / "schemas"
FORBIDDEN_MODEL_FIELDS = {
    "source_start",
    "source_start_ms",
    "source_end",
    "source_end_ms",
    "start",
    "end",
    "path",
    "file_path",
    "command",
    "script",
    "code",
    "sql",
    "ffmpeg",
    "filtergraph",
    "filter",
    "topic_id",
    "quality_total",
    "quality_score_x100",
    "total_score",
    "rank",
    "model",
}


def _load_contracts() -> Any:
    spec = importlib.util.spec_from_file_location(
        "liveclip_highlight_v2_schema_contracts", CONTRACTS_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load contracts module from {CONTRACTS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _property_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        properties = value.get("properties")
        if isinstance(properties, dict):
            names.update(str(name) for name in properties)
        for child in value.values():
            names.update(_property_names(child))
    elif isinstance(value, list):
        for child in value:
            names.update(_property_names(child))
    return names


def build_artifacts() -> dict[str, bytes]:
    contracts = _load_contracts()
    models = {
        "combined-discovery.schema.json": contracts.CombinedDiscovery,
        "selected-copy.schema.json": contracts.SelectedCopyBatchIteration2,
    }
    artifacts: dict[str, bytes] = {}
    for filename, model in models.items():
        schema = model.model_json_schema(mode="validation")
        unexpected = sorted(_property_names(schema) & FORBIDDEN_MODEL_FIELDS)
        if unexpected:
            raise RuntimeError(f"{filename} exposes forbidden model fields: {unexpected}")
        artifacts[filename] = _canonical_bytes(schema)

    contracts_bytes = CONTRACTS_PATH.read_bytes()
    manifest = {
        "schema_version": "liveclip-highlight-agent-v2-schema-manifest-iteration-2-v1",
        "contract_version": contracts.CONTRACT_VERSION,
        "contracts_sha256": _sha256(contracts_bytes),
        "schemas": {
            filename: {"sha256": _sha256(content), "size_bytes": len(content)}
            for filename, content in sorted(artifacts.items())
        },
    }
    artifacts["manifest.json"] = _canonical_bytes(manifest)
    return artifacts


def write_new(schema_dir: Path, artifacts: dict[str, bytes]) -> None:
    if schema_dir.is_symlink():
        raise RuntimeError(f"schema directory cannot be a symlink: {schema_dir}")
    schema_dir = schema_dir.resolve()
    if schema_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing schema directory: {schema_dir}")
    if not schema_dir.parent.is_dir():
        raise RuntimeError(f"schema parent does not exist: {schema_dir.parent}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{schema_dir.name}-", dir=str(schema_dir.parent)))
    try:
        for filename, content in artifacts.items():
            (temporary / filename).write_bytes(content)
        temporary.rename(schema_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def check_existing(schema_dir: Path, artifacts: dict[str, bytes]) -> None:
    if schema_dir.is_symlink():
        raise RuntimeError(f"schema directory cannot be a symlink: {schema_dir}")
    schema_dir = schema_dir.resolve()
    if not schema_dir.is_dir():
        raise RuntimeError(f"schema directory does not exist: {schema_dir}")
    children = tuple(schema_dir.iterdir())
    observed_names = {path.name for path in children}
    if observed_names != set(artifacts):
        raise RuntimeError(
            f"schema file set mismatch: expected={sorted(artifacts)}, "
            f"observed={sorted(observed_names)}"
        )
    unsafe = [path.name for path in children if path.is_symlink() or not path.is_file()]
    if unsafe:
        raise RuntimeError(f"schema directory contains unsafe entries: {sorted(unsafe)}")
    mismatched = [
        filename
        for filename, expected in artifacts.items()
        if (schema_dir / filename).read_bytes() != expected
    ]
    if mismatched:
        raise RuntimeError(f"schema content/hash mismatch: {mismatched}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="create a new schema directory")
    mode.add_argument("--check", action="store_true", help="verify existing schemas byte-for-byte")
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifacts = build_artifacts()
        if args.write:
            write_new(args.schema_dir, artifacts)
        else:
            check_existing(args.schema_dir, artifacts)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"schema_dir={args.schema_dir.resolve()}")
    print(f"schema_files={len(artifacts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
