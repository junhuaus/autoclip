from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("audit_v1_results.py")
SPEC = importlib.util.spec_from_file_location("highlight_v2_v1_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def test_artifact_manifest_binds_all_prior_benchmark_files() -> None:
    manifest = AUDIT._load_and_verify_artifact_manifest(AUDIT.DEFAULT_BENCHMARK_ROOT)
    assert len(manifest) == 343
    assert (
        manifest["results/b1_8_16_2/r001/frozen-input.json"]
        == "cc035e5eb5764b7b53bd0855fccee5d07334ee3b32abd15bcb957f27b1996936"
    )


def test_full_offline_audit_has_expected_scope_and_exact_evidence_count() -> None:
    report = AUDIT.audit(AUDIT.DEFAULT_BENCHMARK_ROOT)
    assert report["scope"]["audited_output_count"] == 30
    assert report["scope"]["unique_source_count"] == 3
    primary = report["aggregates"]["primary_overall"]
    assert primary["highlight_count"] == 263
    assert primary["classification_counts"] == {
        "exact_candidate": 30,
        "context_only": 2,
        "other_candidate": 1,
        "unsupported": 230,
    }
    assert report["method"]["verified_artifact_manifest_count"] == 343


def test_paired_result_and_metadata_tamper_still_fails_manifest(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "benchmark"
    shutil.copytree(AUDIT.DEFAULT_BENCHMARK_ROOT, copied)
    result_path = copied / "results/b1_8_16_2/r001/generators/sol_medium/result.json"
    metadata_path = result_path.with_name("call-metadata.json")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["selection_summary"] += " tampered"
    result_bytes = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    result_path.write_bytes(result_bytes)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["result_sha256"] = hashlib.sha256(result_bytes).hexdigest()
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="manifest artifact hash mismatch"):
        AUDIT.audit(copied)
