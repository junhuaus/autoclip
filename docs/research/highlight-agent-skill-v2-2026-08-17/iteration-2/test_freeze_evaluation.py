from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("freeze_evaluation.py")
SPEC = importlib.util.spec_from_file_location("highlight_i2_evaluation_freeze", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
FREEZE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = FREEZE
SPEC.loader.exec_module(FREEZE)


def test_contract_preregisters_only_nonproduction_outcomes() -> None:
    contract = FREEZE.build_contract()
    assert contract["status"] == "frozen_before_any_iteration2_generator_output"
    assert contract["data_classification"] == "exposed_development_regression"
    assert contract["outcomes"] == {
        "allowed": [
            "reject_iteration2",
            "inconclusive_iteration2",
            "advance_iteration2_to_frozen_holdout",
        ],
        "passing_development_outcome": "advance_iteration2_to_frozen_holdout",
        "production_acceptance_permitted": False,
    }


def test_human_feedback_waiver_commitment_is_frozen_before_output() -> None:
    waiver = FREEZE.build_contract()["human_feedback_waiver"]
    payload = {key: value for key, value in waiver.items() if key != "commitment_sha256"}
    assert waiver["commitment_sha256"] == FREEZE.sha256_bytes(FREEZE.canonical_bytes(payload))
    assert payload["frozen_before_generator_output"] is True


def test_generator_and_judge_budgets_are_explicit() -> None:
    contract = FREEZE.build_contract()
    generator = contract["generator"]
    judge = contract["judge"]
    assert generator["required_pipeline_count"] == 12
    assert generator["normal_calls_per_pipeline"]["v2_maximum"] == 2
    assert generator["maximum_model_repair_attempts_per_pipeline"] == 1
    assert judge["required_call_count"] == 6
    assert judge["adaptive_third_judge_permitted"] is False


def test_metric_names_and_exact_arithmetic_cannot_collapse() -> None:
    aggregation = FREEZE.build_contract()["aggregation"]
    assert aggregation["coverage_metric_names"] == [
        "judge_semantic_opportunity_coverage",
        "deterministic_relative_selected_union_candidate_coverage",
    ]
    assert aggregation["intermediate_floor_or_round"] is False
    assert aggregation["gate_arithmetic"] == "exact_rational"


def test_cross_artifact_checks_use_only_the_single_captured_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = FREEZE._capture_artifacts()

    def unexpected_reopen(_path: Path) -> bytes:
        raise AssertionError("cross-artifact validation must not reopen paths")

    monkeypatch.setattr(Path, "read_bytes", unexpected_reopen)
    FREEZE._verify_schema_manifest(captured)
    FREEZE._verify_design_language(captured)
    index = FREEZE._artifact_index(captured)
    assert set(index) == set(captured)
    assert all(
        record
        == {
            "sha256": FREEZE.sha256_bytes(captured[relative]),
            "size_bytes": len(captured[relative]),
        }
        for relative, record in index.items()
    )


def test_write_new_refuses_to_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "evaluation-contract.json"
    FREEZE._write_new(target, b"first\n")
    assert target.read_bytes() == b"first\n"
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        FREEZE._write_new(target, b"second\n")


def test_write_new_rejects_symlink_target(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_bytes(b"existing\n")
    linked = tmp_path / "linked.json"
    linked.symlink_to(real)
    with pytest.raises(RuntimeError, match="symlink"):
        FREEZE._write_new(linked, b"replacement\n")
    assert real.read_bytes() == b"existing\n"


def test_formal_write_rejects_nondefault_output_before_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "second-evaluation-contract.json"

    def unexpected_build() -> dict:
        raise AssertionError("custom output must fail before building a contract")

    monkeypatch.setattr(FREEZE, "build_contract", unexpected_build)
    assert FREEZE.main(["--write", "--output", str(target)]) == 2
    assert not target.exists()


@pytest.mark.parametrize("filename", ["attempt-contract.json", "result.json"])
def test_freeze_rejects_existing_generator_attempt_or_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    iteration_dir = tmp_path / "iteration-2"
    artifact = iteration_dir / "experiments" / "exp_test" / "attempts" / "001" / filename
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"{}\n")
    monkeypatch.setattr(FREEZE, "SCRIPT_DIR", iteration_dir)

    with pytest.raises(RuntimeError, match="refusing to freeze"):
        FREEZE._assert_no_generator_output()
