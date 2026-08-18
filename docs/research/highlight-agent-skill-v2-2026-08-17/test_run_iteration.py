# ruff: noqa: RUF001 -- Chinese strings are intentional mock editorial data.
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

MODULE_PATH = Path(__file__).with_name("run_iteration.py")
SPEC = importlib.util.spec_from_file_location("highlight_v2_runner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


def _payload(prompt: str) -> dict[str, Any]:
    marker = "<untrusted_frozen_input>\n"
    value = prompt.split(marker, 1)[1].split("\n</untrusted_frozen_input>", 1)[0]
    return json.loads(value)


def _mock_invoke_factory(counter: list[str]):
    def invoke(*, label: str, prompt: str, schema_path: Path):
        counter.append(label)
        payload = _payload(prompt)
        name = schema_path.name
        if name == "v1.json":
            candidate = payload["candidates"][0]
            raw = {
                "selection_summary": "选择一条可验证的基准候选。",
                "highlights": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "topic": "基准主题",
                        "title": "基准高光",
                        "highlight_sentence": candidate["text"][:40],
                        "script_description": "用于验证 fresh v1 的隔离执行路径。",
                        "score": 80,
                        "hook": "这条候选包含一个完整观点。",
                        "selection_reason": "候选结构完整，适合进入比较。",
                        "risk_flags": [],
                    }
                ],
            }
        elif name.startswith("v2-tier1-b"):
            raw = {
                "assessments": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "disposition": "assessable",
                        "unusable_reason": "none",
                        "topic_hypothesis": "自由发现主题",
                        "primary_claim": "该候选表达了一个可独立分析的观点。",
                        "assessment_reason": "正文足以支持独立评估。",
                        "assessment_confidence": "high",
                        "uncertainty_flags": [],
                        "scores": {
                            "content_value": 4,
                            "hook_strength": 3,
                            "standalone_completeness": 4,
                            "evidence_fidelity": 4,
                            "editorial_utility": 3,
                        },
                        "evidence_flags": [],
                        "content_risk_flags": [],
                        "risk_summary": "",
                    }
                    for candidate in payload["batch"]["candidates"]
                ]
            }
        elif name == "v2-tier2.json":
            raw = {
                "inventory_summary": "按冻结证据自由发现全部候选主题。",
                "topics": [
                    {
                        "topic_label": f"主题 {index + 1}",
                        "canonical_angle": "该候选具有一个独立的编辑角度。",
                        "cluster_confidence": "high",
                        "members": [
                            {
                                "candidate_id": candidate["candidate_id"],
                                "relationship": "core",
                                "member_angle": "独立观点",
                                "relationship_reason": "该候选独立构成此主题。",
                            }
                        ],
                    }
                    for index, candidate in enumerate(payload["candidates"])
                ],
            }
        elif name == "v2-tier4.json":
            selected = payload["selected_candidates_in_required_order"]
            raw = {
                "selection_summary": "为确定性入选候选生成可追溯编辑文案。",
                "copies": [
                    {
                        "candidate_id": item["candidate"]["candidate_id"],
                        "title": "可追溯高光",
                        "hook": "这段内容给出了一个明确观点。",
                        "evidence_quote": item["candidate"]["text"][:40],
                        "edited_sentence": "保留原意的编辑关键句。",
                        "script_description": "供编辑审核候选内容与证据关系。",
                        "keywords": ["高光", "证据"],
                        "selection_reason": "通过确定性质量与去重规则。",
                    }
                    for item in selected
                ],
            }
        else:
            raise AssertionError(f"unexpected mock Schema: {schema_path}")
        metadata = {
            "label": label,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "medium",
            "request_id": f"mock-{len(counter)}",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "started_at": "2026-08-17T00:00:00+00:00",
            "completed_at": "2026-08-17T00:00:01+00:00",
            "elapsed_seconds": 0.001,
            "unsafe_tool_event": False,
        }
        return raw, metadata, ""

    return invoke


def test_mock_sentinel_resumes_to_full_matrix_and_detects_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    counter: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(counter))

    sentinel = RUNNER._run_experiment(prepared, sentinel=True)
    assert sentinel["status"] == "generation_partial"
    assert sentinel["completed_pipeline_count"] == 2
    assert sentinel["remaining_pipeline_count"] == 10

    first_pipeline_id = prepared.public_plan["schedule"][0]["pipelines"][0][
        "pipeline_id"
    ]
    first_pipeline_dir = prepared.experiment_dir / "pipelines" / first_pipeline_id
    (first_pipeline_dir / "complete.json").unlink()
    calls_before_recovery = len(counter)
    recovered = RUNNER._run_experiment(prepared, sentinel=True)
    assert recovered["completed_pipeline_count"] == 2
    assert len(counter) == calls_before_recovery
    assert (first_pipeline_dir / "complete.json").is_file()

    complete = RUNNER._run_experiment(prepared)
    assert complete["status"] == "generation_completed"
    assert complete["completed_pipeline_count"] == 12
    assert len(counter) == 36

    resumed = RUNNER._run_experiment(prepared)
    assert resumed["completed_pipeline_count"] == 12
    assert len(counter) == 36

    pipeline_contract = json.loads(
        (first_pipeline_dir / "pipeline-contract.json").read_text(encoding="utf-8")
    )
    call_id = pipeline_contract["required_call_ids"][0]
    events_path = prepared.experiment_dir / "calls" / call_id / "events.jsonl"
    events = events_path.read_bytes()
    events_path.unlink()
    with pytest.raises(RuntimeError, match="pipeline call artifact drift"):
        RUNNER._run_experiment(prepared, sentinel=True)
    events_path.write_bytes(events)

    result_path = first_pipeline_dir / "result.json"
    result_path.write_bytes(result_path.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="artifact drift"):
        RUNNER._run_experiment(prepared, sentinel=True)


def test_empty_portfolio_skips_tier4_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RUNNER, "MINIMUM_QUALITY", 100.0)
    prepared = RUNNER._prepare_experiment(tmp_path / "experiments")
    counter: list[str] = []
    monkeypatch.setattr(RUNNER, "_invoke_codex", _mock_invoke_factory(counter))
    result = RUNNER._run_experiment(prepared, sentinel=True)
    assert result["completed_pipeline_count"] == 2
    assert len(counter) == 5
    assert not any("v2-tier4" in label for label in counter)
    v2_summary = next(
        summary
        for summary in result["completed_pipelines"]
        if "tier_call_elapsed_seconds" in summary
    )
    assert v2_summary["selected_count"] == 0
    assert v2_summary["tier_call_elapsed_seconds"]["tier4"] == 0.0
