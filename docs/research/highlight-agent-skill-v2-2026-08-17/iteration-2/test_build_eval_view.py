from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

MODULE_PATH = Path(__file__).with_name("build_eval_view.py")
SPEC = importlib.util.spec_from_file_location("highlight_iteration2_eval_view_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
VIEW = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VIEW
SPEC.loader.exec_module(VIEW)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(VIEW._pretty_bytes(value))


def _waiver() -> dict[str, Any]:
    payload = {
        "frozen_before_generator_output": True,
        "mode": "diagnostic_not_required",
        "reason": "diagnostic review was waived before generator output",
    }
    return {
        **payload,
        "commitment_sha256": VIEW._sha256_bytes(VIEW._canonical_bytes(payload)),
    }


def _evaluation(mode: str = "diagnostic_not_required") -> dict[str, Any]:
    return {
        "human_review_mode": mode,
        "human_feedback_waiver": _waiver() if mode == "diagnostic_not_required" else {},
    }


def _sources() -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for source_position in range(1, 4):
        source_id = f"source_secret_{source_position}"
        candidates = []
        for candidate_position in range(1, 3):
            candidates.append(
                {
                    "candidate_id": f"candidate_{source_position}_{candidate_position}",
                    "source_start_ms": candidate_position * 1000,
                    "source_end_ms": candidate_position * 1000 + 30_000,
                    "text": f"来源{source_position}候选{candidate_position}的完整证据。",
                    "context_before": "冻结前文",
                    "context_after": "冻结后文",
                }
            )
        values[source_id] = {
            "source": {
                "filename": f"source-{source_position}</script>.mp4",
                "duration_ms": 120_000,
                "source_sha256": f"{source_position:064x}",
            },
            "candidates": candidates,
        }
    return values


def _pipeline_result(source_position: int, output_position: int) -> dict[str, Any]:
    highlights = []
    for highlight_position, candidate_position in enumerate((2, 1), start=1):
        sentence_key = "source_sentence" if output_position % 2 == 0 else "highlight_sentence"
        highlights.append(
            {
                "candidate_id": f"candidate_{source_position}_{candidate_position}",
                "topic": f"话题 {highlight_position}",
                "title": f"标题 {highlight_position}",
                "hook": "一条可独立理解的钩子",
                sentence_key: f"来源{source_position}候选{candidate_position}的完整证据。",
                "script_description": "匿名编辑描述",
                "selection_reason": "证据完整且具有编辑价值",
                "risk_flags": [],
            }
        )
    return {"selection_summary": "匿名组合摘要", "highlights": highlights}


def _pipelines() -> list[Any]:
    pipelines = []
    for source_position in range(1, 4):
        source_id = f"source_secret_{source_position}"
        for output_position in (4, 2, 1, 3):
            pipeline_id = f"pipeline_secret_{source_position}_{output_position}"
            pipelines.append(
                VIEW.VerifiedPipeline(
                    pipeline_id=pipeline_id,
                    source_id=source_id,
                    public_position=output_position,
                    result=_pipeline_result(source_position, output_position),
                    result_sha256=f"{source_position * 10 + output_position:064x}",
                    completion_sha256=f"{source_position * 100 + output_position:064x}",
                )
            )
    return list(reversed(pipelines))


def _review(mode: str = "diagnostic_not_required") -> dict[str, Any]:
    sources = _sources()
    return VIEW._build_review_data(
        _evaluation(mode),
        "a" * 64,
        sources,
        _pipelines(),
        "b" * 64,
        {source_id: index for index, source_id in enumerate(sources, start=1)},
    )


def _complete_feedback(review_dir: Path) -> dict[str, Any]:
    review = json.loads((review_dir / "review.json").read_text(encoding="utf-8"))
    inventory = json.loads((review_dir / "feedback-inventory.json").read_text(encoding="utf-8"))
    return {
        "schema_version": VIEW.FEEDBACK_SCHEMA_VERSION,
        "status": "complete",
        "review_id": review["review_id"],
        "evaluation_contract_sha256": review["evaluation_contract_sha256"],
        "verified_input_set_sha256": review["verified_input_set_sha256"],
        "reviews": [
            {**item, "rating": "acceptable", "feedback": "结构化评审意见"}
            for item in inventory["items"]
        ],
    }


def _full_contract(artifacts: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "liveclip-highlight-evaluation-contract.iteration-2.v1",
        "contract_version": "highlight-agent-skill-v2-iteration-2-evaluation-v1",
        "iteration_id": "highlight-agent-skill-v2-iteration-2",
        "status": "frozen_before_any_iteration2_generator_output",
        "human_review_mode": "diagnostic_not_required",
        "human_feedback_waiver": _waiver(),
        "artifacts": artifacts,
        "generator": {},
        "judge": {},
        "aggregation": {},
        "acceptance_gates": {},
        "outcomes": {},
    }


def test_review_preserves_source_output_candidate_and_highlight_positions() -> None:
    review = _review()
    assert [source["original_position"] for source in review["sources"]] == [1, 2, 3]
    for source in review["sources"]:
        assert [output["original_position"] for output in source["outputs"]] == [1, 2, 3, 4]
        assert [item["original_position"] for item in source["candidate_evidence"]] == [1, 2]
        for output in source["outputs"]:
            assert [item["original_position"] for item in output["highlights"]] == [1, 2]
            assert output["highlights"][0]["candidate_id"].endswith("_2")
    assert review["evaluation_contract_sha256"] == "a" * 64
    assert review["verified_input_set_sha256"] == "b" * 64

    encoded = json.dumps(review, ensure_ascii=False)
    assert not any(pipeline.pipeline_id in encoded for pipeline in _pipelines())
    assert not (
        set(VIEW.SENSITIVE_REVIEW_KEYS)
        & set().union(
            *(set(output) for source in review["sources"] for output in source["outputs"])
        )
    )


def test_feedback_schema_and_inventory_are_complete_and_position_ordered() -> None:
    review = _review()
    inventory = VIEW._feedback_inventory(review)
    schema = VIEW._feedback_schema(review, inventory)
    assert inventory["expected_review_count"] == 12
    observed_positions = [
        (item["source_original_position"], item["output_original_position"])
        for item in inventory["items"]
    ]
    assert observed_positions == [
        (source, output) for source in range(1, 4) for output in range(1, 5)
    ]
    assert schema["properties"]["status"] == {"const": "complete"}
    assert schema["properties"]["evaluation_contract_sha256"] == {"const": "a" * 64}
    assert schema["properties"]["verified_input_set_sha256"] == {"const": "b" * 64}


def test_html_escapes_embedded_script_terminators_and_exports_complete_payload() -> None:
    review = _review()
    inventory = VIEW._feedback_inventory(review)
    rendered = VIEW._review_html(review, inventory)
    assert "source-1</script>.mp4" not in rendered
    assert "source-1\\u003c/script\\u003e.mp4" in rendered
    assert 'status:"complete"' in rendered
    assert "evaluation_contract_sha256:data.evaluation_contract_sha256" in rendered
    assert "verified_input_set_sha256:data.verified_input_set_sha256" in rendered


def test_diagnostic_publish_binds_waiver_hashes_and_original_positions(tmp_path: Path) -> None:
    review = _review()
    output = VIEW._publish_iteration(tmp_path / "reviews", "iteration-2", review, _evaluation())
    assert {path.name for path in output.iterdir()} == {
        "review.json",
        "review.html",
        "feedback.schema.json",
        "feedback-inventory.json",
        "feedback-waiver-receipt.json",
        "build-receipt.json",
    }
    receipt = json.loads((output / "build-receipt.json").read_text(encoding="utf-8"))
    waiver = json.loads((output / "feedback-waiver-receipt.json").read_text(encoding="utf-8"))
    assert receipt["original_positions_preserved"] is True
    assert receipt["evaluation_contract_sha256"] == "a" * 64
    assert receipt["verified_input_set_sha256"] == "b" * 64
    assert waiver["status"] == "waived"
    assert waiver["waiver_commitment_sha256"] == _waiver()["commitment_sha256"]
    for filename, expected in receipt["artifact_sha256"].items():
        assert VIEW._sha256_path(output / filename) == expected


def test_required_feedback_commitment_matches_global_unblind_interface(
    tmp_path: Path,
) -> None:
    output = VIEW._publish_iteration(
        tmp_path / "reviews", "iteration-2", _review("required"), _evaluation("required")
    )
    assert not (output / "feedback-waiver-receipt.json").exists()
    feedback = _complete_feedback(output)
    feedback_path = tmp_path / "feedback.json"
    _write_json(feedback_path, feedback)
    commitment_path = VIEW.commit_feedback(output, feedback_path)
    commitment = json.loads(commitment_path.read_text(encoding="utf-8"))
    assert set(commitment) == {
        "schema_version",
        "review_id",
        "evaluation_contract_sha256",
        "complete",
        "feedback_manifest_sha256",
    }
    assert commitment["schema_version"] == "1"
    assert commitment["complete"] is True
    assert commitment["feedback_manifest_sha256"] == VIEW._sha256_path(
        output / "feedback.complete.json"
    )
    assert VIEW.commit_feedback(output, feedback_path) == commitment_path


@pytest.mark.parametrize(
    "mutation",
    ["pending", "missing", "reordered", "wrong_evaluation", "missing_rating"],
)
def test_feedback_commit_rejects_any_incomplete_or_inventory_drift(
    tmp_path: Path, mutation: str
) -> None:
    output = VIEW._publish_iteration(
        tmp_path / "reviews", "iteration-2", _review("required"), _evaluation("required")
    )
    feedback = _complete_feedback(output)
    if mutation == "pending":
        feedback["status"] = "pending"
    elif mutation == "missing":
        feedback["reviews"].pop()
    elif mutation == "reordered":
        feedback["reviews"][0], feedback["reviews"][1] = (
            feedback["reviews"][1],
            feedback["reviews"][0],
        )
    elif mutation == "wrong_evaluation":
        feedback["evaluation_contract_sha256"] = "c" * 64
    else:
        feedback["reviews"][0]["rating"] = ""
    feedback_path = tmp_path / "feedback.json"
    _write_json(feedback_path, feedback)
    with pytest.raises(VIEW.ReviewBuildError):
        VIEW.commit_feedback(output, feedback_path)
    assert not (output / "feedback.complete.json").exists()
    assert not (output / "feedback-commitment.json").exists()


def test_commit_rejects_tampered_schema_and_diagnostic_mode(tmp_path: Path) -> None:
    required = VIEW._publish_iteration(
        tmp_path / "required", "iteration-2", _review("required"), _evaluation("required")
    )
    feedback_path = tmp_path / "feedback.json"
    _write_json(feedback_path, _complete_feedback(required))
    (required / "feedback.schema.json").write_bytes(b"{}\n")
    with pytest.raises(VIEW.ReviewBuildError, match="artifact hash drifted"):
        VIEW.commit_feedback(required, feedback_path)

    diagnostic = VIEW._publish_iteration(
        tmp_path / "diagnostic", "iteration-2", _review(), _evaluation()
    )
    _write_json(feedback_path, _complete_feedback(diagnostic))
    with pytest.raises(VIEW.ReviewBuildError, match="forbidden"):
        VIEW.commit_feedback(diagnostic, feedback_path)


def test_publish_is_immutable_and_rejects_unsafe_name(tmp_path: Path) -> None:
    root = tmp_path / "reviews"
    VIEW._publish_iteration(root, "iteration-2", _review(), _evaluation())
    with pytest.raises(VIEW.ReviewBuildError, match="already exists"):
        VIEW._publish_iteration(root, "iteration-2", _review(), _evaluation())
    with pytest.raises(VIEW.ReviewBuildError, match="safe component"):
        VIEW._publish_iteration(root, "../escape", _review(), _evaluation())


def test_evaluation_contract_checks_raw_copy_manifest_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = tmp_path / "repository"
    viewer_copy = repository_root / "build_eval_view.py"
    viewer_copy.parent.mkdir(parents=True)
    viewer_copy.write_bytes(b"pre-registered viewer bytes\n")
    contract = _full_contract(
        {
            "build_eval_view.py": {
                "sha256": VIEW._sha256_path(viewer_copy),
                "size_bytes": viewer_copy.stat().st_size,
            }
        }
    )
    repository_contract = repository_root / "evaluation-contract.json"
    _write_json(repository_contract, contract)
    experiment = tmp_path / "experiment"
    frozen = experiment / "frozen/evaluation-contract.json"
    frozen.parent.mkdir(parents=True)
    frozen.write_bytes(repository_contract.read_bytes())
    evaluation_sha = VIEW._sha256_path(repository_contract)
    immutable = {"evaluation_contract_sha256": evaluation_sha}
    _write_json(
        experiment / "experiment-manifest.json",
        {
            "contract_sha256": VIEW._sha256_bytes(VIEW._canonical_bytes(immutable)),
            "immutable_contract": immutable,
            "artifact_index": {
                "frozen/evaluation-contract.json": {
                    "sha256": evaluation_sha,
                    "size_bytes": frozen.stat().st_size,
                }
            },
        },
    )
    monkeypatch.setattr(VIEW, "REPOSITORY_ROOT", repository_root)
    monkeypatch.setattr(VIEW, "EVALUATION_CONTRACT_PATH", repository_contract)
    monkeypatch.setattr(VIEW, "REQUIRED_EVALUATION_ARTIFACTS", {"build_eval_view.py"})
    loaded, digest, _manifest, artifacts = VIEW._load_evaluation_contract(experiment)
    assert loaded == contract
    assert digest == evaluation_sha
    assert artifacts == {"build_eval_view.py": b"pre-registered viewer bytes\n"}
    frozen.write_bytes(frozen.read_bytes() + b" ")
    with pytest.raises(VIEW.ReviewBuildError, match="byte drift"):
        VIEW._load_evaluation_contract(experiment)


def test_evaluation_contract_detects_viewer_self_hash_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    viewer_copy = tmp_path / "build_eval_view.py"
    viewer_copy.write_bytes(b"frozen viewer\n")
    contract = {
        "artifacts": {
            "build_eval_view.py": {
                "sha256": VIEW._sha256_path(viewer_copy),
                "size_bytes": viewer_copy.stat().st_size,
            }
        }
    }
    monkeypatch.setattr(VIEW, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(VIEW, "REQUIRED_EVALUATION_ARTIFACTS", {"build_eval_view.py"})
    VIEW._verify_repository_artifact_index(contract)
    viewer_copy.write_bytes(b"changed viewer\n")
    with pytest.raises(VIEW.ReviewBuildError, match=r"artifact (size|hash) drifted"):
        VIEW._verify_repository_artifact_index(contract)


def test_pinned_judge_executes_verified_bytes_not_swapped_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "executed.txt"
    judge_path = tmp_path / VIEW.JUDGE_HARNESS_ARTIFACT
    judge_path.parent.mkdir(parents=True)
    judge_path.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(VIEW, "REPOSITORY_ROOT", tmp_path)

    judge = VIEW._load_pinned_judge_harness({VIEW.JUDGE_HARNESS_ARTIFACT: b"FROZEN_JUDGE = True\n"})

    assert judge.FROZEN_JUDGE is True
    assert not sentinel.exists()


@pytest.mark.parametrize("unsafe_relative", ["../escape.py", "/absolute.py", "a/../b.py"])
def test_evaluation_artifact_index_rejects_path_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe_relative: str
) -> None:
    monkeypatch.setattr(VIEW, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(VIEW, "REQUIRED_EVALUATION_ARTIFACTS", {unsafe_relative})
    with pytest.raises(VIEW.ReviewBuildError, match=r"escapes|normalized"):
        VIEW._verify_repository_artifact_index(
            {"artifacts": {unsafe_relative: {"sha256": "0" * 64, "size_bytes": 0}}}
        )


def test_formal_verification_requires_exact_three_by_two_by_two_topology(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    evaluation = _evaluation()
    evaluation_materials = SimpleNamespace(
        contract=evaluation,
        contract_sha256="a" * 64,
    )
    sources = _sources()
    bundles = []
    for source_position, (source_id, source_payload) in enumerate(sources.items(), start=1):
        pipeline_ids = []
        results: dict[str, dict[str, Any]] = {}
        result_sha256: dict[str, str] = {}
        completion_sha256: dict[str, str] = {}
        public_metadata: dict[str, dict[str, Any]] = {}
        for output_position, (skill, repeat) in enumerate(
            (("v1", 1), ("v2", 1), ("v1", 2), ("v2", 2)), start=1
        ):
            pipeline_id = f"pipeline_{source_position}_{output_position}"
            pipeline_ids.append(pipeline_id)
            pipeline_dir = experiment / "pipelines" / pipeline_id
            result = _pipeline_result(source_position, output_position)
            _write_json(pipeline_dir / "result.json", result)
            _write_json(
                pipeline_dir / "pipeline-contract.json",
                {"skill_version": skill, "repeat": repeat},
            )
            _write_json(
                pipeline_dir / "complete.json",
                {
                    "artifact_sha256": {
                        "result.json": VIEW._sha256_path(pipeline_dir / "result.json")
                    }
                },
            )
            results[pipeline_id] = result
            result_sha256[pipeline_id] = VIEW._sha256_path(pipeline_dir / "result.json")
            completion_sha256[pipeline_id] = VIEW._sha256_path(pipeline_dir / "complete.json")
            public_metadata[pipeline_id] = {
                "skill_version": skill,
                "repeat": repeat,
            }
        bundles.append(
            SimpleNamespace(
                source_id=source_id,
                source_payload=source_payload,
                pipeline_ids=tuple(pipeline_ids),
                results_by_pipeline=results,
                source_public_position=source_position,
                pipeline_public_positions={
                    pipeline_id: position
                    for position, pipeline_id in enumerate(pipeline_ids, start=1)
                },
                pipeline_result_sha256=result_sha256,
                pipeline_completion_sha256=completion_sha256,
                pipeline_public_metadata=public_metadata,
            )
        )
    monkeypatch.setattr(
        VIEW,
        "_load_evaluation_contract",
        lambda _path: (evaluation, "a" * 64, {}, {}),
    )

    def load_bundles(_path: Path, observed_materials: Any) -> tuple[str, tuple[Any, ...]]:
        assert observed_materials is evaluation_materials
        return "experiment", tuple(bundles)

    harness_error = type("HarnessError", (RuntimeError,), {})
    judge_harness = SimpleNamespace(
        IntegrityError=harness_error,
        GeneratorMatrixIncomplete=harness_error,
        _load_evaluation_materials=lambda: evaluation_materials,
        _load_source_bundles=load_bundles,
    )
    monkeypatch.setattr(VIEW, "_load_pinned_judge_harness", lambda _artifacts: judge_harness)
    _evaluation_value, _sha, _sources_value, pipelines, input_sha, _positions = (
        VIEW._verify_formal_experiment(experiment)
    )
    assert len(pipelines) == 12
    assert len(input_sha) == 64

    tampered = experiment / "pipelines/pipeline_1_1/result.json"
    tampered.write_bytes(tampered.read_bytes() + b" ")
    VIEW._verify_formal_experiment(experiment)
    bundles[0].pipeline_result_sha256[bundles[0].pipeline_ids[0]] = "0" * 64
    with pytest.raises(VIEW.ReviewBuildError, match="snapshot or digest drifted"):
        VIEW._verify_formal_experiment(experiment)


@pytest.mark.parametrize("mutation", ["contract", "sha256"])
def test_formal_verification_requires_identical_judge_evaluation_materials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    evaluation = _evaluation()
    materials_contract = (
        {**evaluation, "human_review_mode": "required"} if mutation == "contract" else evaluation
    )
    materials_sha = "b" * 64 if mutation == "sha256" else "a" * 64
    monkeypatch.setattr(
        VIEW,
        "_load_evaluation_contract",
        lambda _path: (evaluation, "a" * 64, {}, {}),
    )
    harness_error = type("HarnessError", (RuntimeError,), {})
    judge_harness = SimpleNamespace(
        IntegrityError=harness_error,
        GeneratorMatrixIncomplete=harness_error,
        _load_evaluation_materials=lambda: SimpleNamespace(
            contract=materials_contract,
            contract_sha256=materials_sha,
        ),
    )
    monkeypatch.setattr(VIEW, "_load_pinned_judge_harness", lambda _artifacts: judge_harness)

    with pytest.raises(VIEW.ReviewBuildError, match="evaluation materials differ"):
        VIEW._verify_formal_experiment(experiment)


def test_source_set_drift_fails_before_any_review_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    evaluation = _evaluation()
    materials = SimpleNamespace(contract=evaluation, contract_sha256="a" * 64)
    monkeypatch.setattr(
        VIEW,
        "_load_evaluation_contract",
        lambda _path: (evaluation, "a" * 64, {}, {}),
    )

    def reject_source_drift(_path: Path, observed_materials: Any) -> Any:
        assert observed_materials is materials
        raise harness_error("generator source set differs from the evaluation contract")

    published: list[bool] = []
    harness_error = type("HarnessError", (RuntimeError,), {})
    judge_harness = SimpleNamespace(
        IntegrityError=harness_error,
        GeneratorMatrixIncomplete=harness_error,
        _load_evaluation_materials=lambda: materials,
        _load_source_bundles=reject_source_drift,
    )
    monkeypatch.setattr(VIEW, "_load_pinned_judge_harness", lambda _artifacts: judge_harness)
    monkeypatch.setattr(
        VIEW,
        "_publish_iteration",
        lambda *_args, **_kwargs: published.append(True),
    )

    with pytest.raises(VIEW.ReviewBuildError, match="source set differs"):
        VIEW.build_review(experiment, tmp_path / "reviews")
    assert published == []
    assert not (tmp_path / "reviews").exists()


def test_viewer_has_no_unblind_or_per_call_identity_mapping_reader() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "\nimport run_judges" not in source
    assert "anonymous_system_to_pipeline" not in source
    assert "global-unblind" not in source
    assert "per-call-mapping" not in source
