from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

MODULE_PATH = Path(__file__).with_name("build_eval_view.py")
SPEC = importlib.util.spec_from_file_location("highlight_v2_eval_view", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
VIEW = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VIEW
SPEC.loader.exec_module(VIEW)


@dataclass(frozen=True)
class FormalFixture:
    experiment_dir: Path
    pipeline_ids: tuple[str, ...]
    arm_ids: tuple[str, ...]
    result_paths: tuple[Path, ...]


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_json(path: Path, value: Any) -> None:
    _write_bytes(path, VIEW._pretty_bytes(value))


def _record(path: Path) -> dict[str, Any]:
    return {"sha256": VIEW._sha256_path(path), "size_bytes": path.stat().st_size}


def _make_call(
    experiment_dir: Path,
    *,
    experiment_id: str,
    contract_sha: str,
    pipeline_id: str,
    call_id: str,
    schema_relative: str,
    schema_sha: str,
    model: dict[str, str],
) -> str:
    call_dir = experiment_dir / "calls" / call_id
    call_contract = {
        "schema_version": "1",
        "experiment_id": experiment_id,
        "experiment_contract_sha256": contract_sha,
        "call_id": call_id,
        "pipeline_id": pipeline_id,
        "stage": "fixture-generation",
        "model": model,
        "prompt_sha256": "1" * 64,
        "schema_relative_path": schema_relative,
        "schema_sha256": schema_sha,
        "dependency_sha256": {"fixture": "2" * 64},
        "maximum_attempts": 2,
        "isolation": {"tools": "disabled"},
    }
    _write_json(call_dir / "call-contract.json", call_contract)
    attempt_contract = {"prompt_sha256": "1" * 64, "status": "validated"}
    attempt_path = call_dir / "attempts/001/attempt-contract.json"
    _write_json(attempt_path, attempt_contract)
    artifacts = {
        "result.raw.json": VIEW._pretty_bytes({"fixture": True}),
        "result.json": VIEW._pretty_bytes({"fixture": True}),
        "validation.json": VIEW._pretty_bytes({"status": "passed"}),
        "call-metadata.json": VIEW._pretty_bytes(
            {
                "model": model["model"],
                "reasoning_effort": model["reasoning_effort"],
                "usage": {"input_tokens": 100, "output_tokens": 20},
                "elapsed_seconds": 9.5,
            }
        ),
        "events.jsonl": b'{"type":"completed"}\n',
    }
    for relative, content in artifacts.items():
        _write_bytes(call_dir / relative, content)
    complete = {
        "schema_version": "1",
        "call_id": call_id,
        "call_contract_sha256": VIEW._sha256_path(call_dir / "call-contract.json"),
        "successful_attempt": 1,
        "successful_attempt_contract_sha256": VIEW._sha256_path(attempt_path),
        "artifact_sha256": {
            relative: VIEW._sha256_bytes(content) for relative, content in sorted(artifacts.items())
        },
        "infrastructure_failure_receipts": [],
    }
    _write_json(call_dir / "complete.json", complete)
    return VIEW._sha256_path(call_dir / "complete.json")


def _result(candidate_id: str, *, version: str, source_index: int) -> dict[str, Any]:
    common = {
        "candidate_id": candidate_id,
        "topic": f"来源 {source_index} 的自然话题",
        "title": f"匿名高光 {source_index}",
        "hook": "这段内容给出了一个可独立理解的观点。",
        "script_description": "供编辑比较内容发现与证据忠实度。",
        "selection_reason": "候选具有独立表达与编辑价值。",
        "risk_flags": [],
    }
    if version == "v1":
        return {
            "selection_summary": "选择来源中最值得比较的内容。",
            "highlights": [
                {
                    **common,
                    "highlight_sentence": "这是候选正文中的关键观点。",
                    "score": 91,
                }
            ],
        }
    return {
        "schema_version": "2",
        "selection_summary": "选择来源中最值得比较的内容。",
        "highlights": [
            {
                **common,
                "evidence_quote": "这是候选正文中的关键观点。",
                "edited_sentence": "这是候选正文中的关键观点。",
                "keywords": ["证据"],
                "quality_total": 91.0,
                "scores": {"content_value": 4},
            }
        ],
    }


def _make_formal_fixture(tmp_path: Path) -> FormalFixture:
    experiment_dir = tmp_path / "formal-experiment"
    source_ids = [f"src_fixture_{index:02d}" for index in range(1, 4)]
    arm_ids = ("arm_hidden_alpha", "arm_hidden_beta")
    model = {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}
    artifact_index: dict[str, dict[str, Any]] = {}
    source_contracts = []
    source_inputs: dict[str, dict[str, Any]] = {}
    schema_paths: dict[str, str] = {}

    for source_index, source_id in enumerate(source_ids, start=1):
        candidate_id = f"candidate_{source_index:016x}"
        evidence = {
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "source_start_ms": source_index * 1000,
                    "source_end_ms": source_index * 1000 + 30_000,
                    "allowed_start_ms": source_index * 1000 - 500,
                    "allowed_end_ms": source_index * 1000 + 30_500,
                    "text": "这是候选正文中的关键观点。它可以独立接受匿名评审。",
                    "context_before": "这是冻结前文。",
                    "context_after": "这是冻结后文。",
                    "rule_score": 73.2,
                    "rule_reasons": ["完整表达"],
                }
            ],
            "source": {
                "candidate_count": 1,
                "duration_ms": 120_000,
                "filename": f"fixture-{source_index}.ts",
                "source_sha256": f"{source_index}" * 64,
            },
        }
        source_inputs[source_id] = evidence
        input_relative = f"frozen/inputs/{source_id}.json"
        input_path = experiment_dir / input_relative
        _write_json(input_path, evidence)
        artifact_index[input_relative] = _record(input_path)
        schema_relative = f"frozen/schemas/{source_id}/common.json"
        schema_path = experiment_dir / schema_relative
        _write_json(schema_path, {"type": "object", "additionalProperties": False})
        artifact_index[schema_relative] = _record(schema_path)
        schema_paths[source_id] = schema_relative
        source_contracts.append(
            {
                "source_id": source_id,
                "experiment_input_sha256": VIEW._sha256_path(input_path),
                "candidate_count": 1,
            }
        )

    schedule = []
    pipeline_identity: dict[str, tuple[str, int, str, str]] = {}
    pair_sequence = 0
    for source_index, source_id in enumerate(source_ids, start=1):
        for repeat in (1, 2):
            pair_sequence += 1
            entries = []
            for arm_index, (arm_id, version) in enumerate(
                zip(arm_ids, ("v1", "v2"), strict=True), start=1
            ):
                pipeline_id = f"pipeline_s{source_index}_r{repeat}_a{arm_index}"
                entries.append(
                    {
                        "within_pair_sequence": arm_index,
                        "pipeline_id": pipeline_id,
                        "arm_id": arm_id,
                    }
                )
                pipeline_identity[pipeline_id] = (source_id, repeat, arm_id, version)
            schedule.append(
                {
                    "pair_sequence": pair_sequence,
                    "pair_id": f"pair_s{source_index}_r{repeat}",
                    "source_id": source_id,
                    "repeat": repeat,
                    "candidate_order": "original_frozen_order",
                    "pipelines": entries,
                }
            )
    public_plan = {
        "schema_version": "1",
        "study": "fixture-formal-matrix",
        "unique_source_count": 3,
        "repeats_per_source": 2,
        "pipeline_count": 12,
        "model": model,
        "schedule": schedule,
    }
    public_plan_path = experiment_dir / "frozen/public-plan.json"
    _write_json(public_plan_path, public_plan)
    artifact_index["frozen/public-plan.json"] = _record(public_plan_path)

    # This unresolvable receipt proves the builder does not traverse the private mapping.
    artifact_index["private/arm-map.private.json"] = {
        "sha256": "f" * 64,
        "size_bytes": 999,
    }
    immutable_contract = {
        "public_plan_sha256": VIEW._sha256_path(public_plan_path),
        "sources": source_contracts,
        "model": model,
    }
    contract_sha = VIEW._sha256_bytes(VIEW._canonical_bytes(immutable_contract))
    experiment_id = f"exp_{contract_sha[:20]}"
    manifest = {
        "schema_version": "1",
        "experiment_id": experiment_id,
        "contract_sha256": contract_sha,
        "immutable_contract": immutable_contract,
        "artifact_index": artifact_index,
    }
    _write_json(experiment_dir / "experiment-manifest.json", manifest)

    result_paths = []
    for pipeline_id, (source_id, repeat, arm_id, version) in pipeline_identity.items():
        pipeline_dir = experiment_dir / "pipelines" / pipeline_id
        required_calls = [f"call_{pipeline_id}_base"]
        conditional_calls = (
            {"nonempty_portfolio": f"call_{pipeline_id}_copy"} if version == "v2" else {}
        )
        pipeline_contract = {
            "schema_version": "1",
            "experiment_contract_sha256": contract_sha,
            "pipeline_id": pipeline_id,
            "source_id": source_id,
            "repeat": repeat,
            "arm_id": arm_id,
            "skill_version": version,
            "input_sha256": VIEW._sha256_bytes(VIEW._pretty_bytes(source_inputs[source_id])),
            "fresh_generation": True,
            "required_call_ids": required_calls,
            "conditional_call_ids": conditional_calls,
        }
        _write_json(pipeline_dir / "pipeline-contract.json", pipeline_contract)
        result = _result(
            source_inputs[source_id]["candidates"][0]["candidate_id"],
            version=version,
            source_index=source_ids.index(source_id) + 1,
        )
        summary = {
            "pipeline_id": pipeline_id,
            "arm_id": arm_id,
            "source_id": source_id,
            "repeat": repeat,
            "selected_count": 1,
            "call_elapsed_seconds": 8.0,
        }
        artifacts = {
            "result.json": result,
            "validation.json": {"status": "passed"},
            "summary.json": summary,
        }
        if version == "v2":
            artifacts.update(
                {relative: {"status": "passed"} for relative in VIEW.V2_PIPELINE_ARTIFACTS}
            )
        for relative, value in artifacts.items():
            _write_json(pipeline_dir / relative, value)
        result_paths.append(pipeline_dir / "result.json")

        call_ids = sorted([*required_calls, *conditional_calls.values()])
        call_receipts = []
        schema_relative = schema_paths[source_id]
        schema_sha = artifact_index[schema_relative]["sha256"]
        for call_id in call_ids:
            completion_sha = _make_call(
                experiment_dir,
                experiment_id=experiment_id,
                contract_sha=contract_sha,
                pipeline_id=pipeline_id,
                call_id=call_id,
                schema_relative=schema_relative,
                schema_sha=schema_sha,
                model=model,
            )
            call_receipts.append({"call_id": call_id, "call_completion_sha256": completion_sha})
        complete = {
            "schema_version": "1",
            "pipeline_id": pipeline_id,
            "pipeline_contract_sha256": VIEW._sha256_path(pipeline_dir / "pipeline-contract.json"),
            "artifact_sha256": {
                relative: VIEW._sha256_path(pipeline_dir / relative)
                for relative in sorted(artifacts)
            },
            "call_receipts": call_receipts,
        }
        _write_json(pipeline_dir / "complete.json", complete)

    return FormalFixture(
        experiment_dir=experiment_dir,
        pipeline_ids=tuple(sorted(pipeline_identity)),
        arm_ids=arm_ids,
        result_paths=tuple(result_paths),
    )


def _bind_recovered_infrastructure_failure(fixture: FormalFixture) -> Path:
    pipeline_id = fixture.pipeline_ids[0]
    pipeline_dir = fixture.experiment_dir / "pipelines" / pipeline_id
    pipeline_completion_path = pipeline_dir / "complete.json"
    pipeline_completion = json.loads(pipeline_completion_path.read_text(encoding="utf-8"))
    call_id = pipeline_completion["call_receipts"][0]["call_id"]
    call_dir = fixture.experiment_dir / "calls" / call_id
    call_contract_path = call_dir / "call-contract.json"
    call_contract = json.loads(call_contract_path.read_text(encoding="utf-8"))
    receipt = {
        "schema_version": "1",
        "experiment_id": call_contract["experiment_id"],
        "experiment_contract_sha256": call_contract["experiment_contract_sha256"],
        "call_id": call_id,
        "pipeline_id": pipeline_id,
        "stage": call_contract["stage"],
        "failure_number": 1,
        "category": "infrastructure_permission_denied",
        "returncode": 1,
        "model_started": False,
        "model_attempt_consumed": False,
        "call_contract_sha256": VIEW._sha256_path(call_contract_path),
        "stdout_tail": "",
        "stderr_tail": "Operation not permitted",
        "recorded_at": "2026-08-17T00:00:00+00:00",
    }
    receipt_path = call_dir / "infrastructure-failures/001/receipt.json"
    _write_json(receipt_path, receipt)
    call_completion_path = call_dir / "complete.json"
    call_completion = json.loads(call_completion_path.read_text(encoding="utf-8"))
    call_completion["infrastructure_failure_receipts"] = [
        {
            "relative_path": "infrastructure-failures/001/receipt.json",
            "sha256": VIEW._sha256_path(receipt_path),
        }
    ]
    _write_json(call_completion_path, call_completion)
    for item in pipeline_completion["call_receipts"]:
        if item["call_id"] == call_id:
            item["call_completion_sha256"] = VIEW._sha256_path(call_completion_path)
    _write_json(pipeline_completion_path, pipeline_completion)
    return receipt_path


def test_refuses_partial_formal_matrix(tmp_path: Path) -> None:
    fixture = _make_formal_fixture(tmp_path)
    missing = fixture.experiment_dir / "pipelines" / fixture.pipeline_ids[-1] / "complete.json"
    missing.unlink()

    with pytest.raises(VIEW.ReviewBuildError, match="missing or unsafe pipeline receipt"):
        VIEW.build_review(fixture.experiment_dir, tmp_path / "reviews")
    assert not (tmp_path / "reviews/iteration-1").exists()


def test_builds_anonymous_source_first_complete_review(tmp_path: Path) -> None:
    fixture = _make_formal_fixture(tmp_path)
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["infrastructure_failure_receipts"] == []
        for path in (fixture.experiment_dir / "calls").glob("*/complete.json")
    )
    output = VIEW.build_review(fixture.experiment_dir, tmp_path / "reviews")
    review = json.loads((output / "review.json").read_text(encoding="utf-8"))
    html = (output / "review.html").read_text(encoding="utf-8")
    receipt = json.loads((output / "build-receipt.json").read_text(encoding="utf-8"))

    assert review["source_count"] == 3
    assert review["pipeline_count"] == 12
    assert len(review["sources"]) == 3
    assert all(len(source["outputs"]) == 4 for source in review["sources"])
    assert all(source["candidate_evidence"] for source in review["sources"])
    assert sum(len(source["outputs"]) for source in review["sources"]) == 12
    assert all(
        set(highlight)
        == {
            "position",
            "candidate_id",
            "source_start_ms",
            "source_end_ms",
            "topic",
            "title",
            "hook",
            "key_sentence",
            "script_description",
            "selection_reason",
            "risk_flags",
        }
        for source in review["sources"]
        for output_value in source["outputs"]
        for highlight in output_value["highlights"]
    )

    serialized = json.dumps(review, ensure_ascii=False)
    for secret in (*fixture.pipeline_ids, *fixture.arm_ids, "gpt-5.6-sol"):
        assert secret not in serialized
        assert secret not in html
    for forbidden_key in VIEW.SENSITIVE_REVIEW_KEYS:
        assert f'"{forbidden_key}"' not in serialized
    assert receipt["verified_pipeline_count"] == 12
    assert receipt["anonymous_projection"] is True
    assert receipt["artifact_sha256"]["review.json"] == VIEW._sha256_path(output / "review.json")
    assert receipt["artifact_sha256"]["review.html"] == VIEW._sha256_path(output / "review.html")
    assert "https://" not in html
    assert "http://" not in html


def test_refuses_tampered_pipeline_artifact(tmp_path: Path) -> None:
    fixture = _make_formal_fixture(tmp_path)
    fixture.result_paths[0].write_bytes(fixture.result_paths[0].read_bytes() + b" ")

    with pytest.raises(VIEW.ReviewBuildError, match="pipeline artifact hash drift"):
        VIEW.build_review(fixture.experiment_dir, tmp_path / "reviews")
    assert not (tmp_path / "reviews/iteration-1").exists()


def test_accepts_fully_bound_failure_then_success_receipt(tmp_path: Path) -> None:
    fixture = _make_formal_fixture(tmp_path)
    receipt_path = _bind_recovered_infrastructure_failure(fixture)

    output = VIEW.build_review(fixture.experiment_dir, tmp_path / "reviews")
    assert receipt_path.is_file()
    assert (output / "review.html").is_file()
    assert "infrastructure_failure_receipts" not in (output / "review.json").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("mutation", ["tamper", "delete", "extra"])
def test_recovered_call_binds_every_infrastructure_failure_receipt(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _make_formal_fixture(tmp_path)
    receipt_path = _bind_recovered_infrastructure_failure(fixture)
    if mutation == "tamper":
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["stderr_tail"] = "tampered after successful recovery"
        _write_json(receipt_path, receipt)
    elif mutation == "delete":
        receipt_path.unlink()
    else:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["failure_number"] = 2
        _write_json(
            receipt_path.parents[1] / "002/receipt.json",
            receipt,
        )

    with pytest.raises(VIEW.ReviewBuildError, match="infrastructure failure receipt"):
        VIEW.build_review(fixture.experiment_dir, tmp_path / "reviews")
    assert not (tmp_path / "reviews/iteration-1").exists()


def test_atomic_iteration_never_overwrites(tmp_path: Path) -> None:
    fixture = _make_formal_fixture(tmp_path)
    output = VIEW.build_review(fixture.experiment_dir, tmp_path / "reviews")
    before = {path.name: path.read_bytes() for path in output.iterdir()}

    with pytest.raises(VIEW.ReviewBuildError, match="refusing overwrite"):
        VIEW.build_review(fixture.experiment_dir, tmp_path / "reviews")
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert after == before
    assert not list((tmp_path / "reviews").glob(".iteration-1-*"))
    assert not (tmp_path / "reviews/.iteration-1.reserve").exists()
