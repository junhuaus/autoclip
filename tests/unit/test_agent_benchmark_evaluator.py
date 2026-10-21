from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from liveclip.agent_runtime.models import (
    AgentArtifact,
    AgentEvent,
    AgentObservation,
    AgentRunResult,
    AgentTurn,
)
from scripts.evaluate_agent_benchmark import (
    STATUS_INVALID_EVIDENCE,
    STATUS_TECHNICAL_FAIL,
    STATUS_TECHNICAL_PASS_HUMAN_PENDING,
    evaluate_agent,
    main,
    technical_status,
)

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_PATH = ROOT / "liveclip_dual_profile_benchmark_v1.json"
BENCHMARK = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
ALLOWED_STATUSES = {
    STATUS_TECHNICAL_PASS_HUMAN_PENDING,
    STATUS_TECHNICAL_FAIL,
    STATUS_INVALID_EVIDENCE,
}
RGR02 = next(value for value in BENCHMARK["regressions"] if value["id"] == "RGR-02")


def _metadata() -> dict[str, object]:
    return {
        "prompt_sha256": "c" * 64,
        "call_records": [{"usage_json": {"input_tokens": 10, "output_tokens": 5}}],
    }


def _result(
    *,
    omit: str | None = None,
    omit_title: str | None = None,
    executed_profiles: list[str] | None = None,
    overrides: dict[str, dict[str, Any]] | None = None,
    extra: tuple[dict[str, Any], ...] = (),
    source_hash: str | None = None,
) -> AgentRunResult:
    candidates: list[AgentArtifact] = []
    titles: list[AgentArtifact] = []
    events: list[AgentEvent] = []
    anchors = [
        *(dict(value, profile="short_highlight") for value in BENCHMARK["gold_short"]),
        *(dict(value, profile="mini_lesson") for value in BENCHMARK["gold_mini_lesson"]),
        *(dict(value, profile="mini_lesson") for value in BENCHMARK["risk_anchors"]),
        *extra,
    ]
    turn = 0
    for anchor in anchors:
        anchor_id = str(anchor["id"])
        if anchor_id == omit:
            continue
        anchor.update((overrides or {}).get(anchor_id, {}))
        candidate_id = f"candidate_{anchor_id.lower()}"
        evidence = anchor.get("evidence", [int(anchor["cue_start"]), int(anchor["cue_end"])])
        candidate = AgentArtifact(
            artifact_id=candidate_id,
            artifact_type="clip_candidate",
            data={
                "profile": str(anchor["profile"]),
                "variant_group_id": f"vg_{anchor_id.lower()}",
                "source_candidate_ids": [],
                "start_cue_id": int(anchor["cue_start"]),
                "end_cue_id": int(anchor["cue_end"]),
                "start_ms": int(anchor["start_ms"]),
                "end_ms": int(anchor["end_ms"]),
                "duration_ms": int(anchor["end_ms"]) - int(anchor["start_ms"]),
                "score": int(anchor.get("score", 90)),
                "score_reason": "完整测试候选",
                "score_dimensions": [],
            },
            evidence=({"cue_ids": evidence},),
        )
        candidates.append(candidate)
        turn += 1
        events.append(
            AgentEvent(
                turn_number=turn,
                function_call_id=f"call_{turn}",
                action=AgentTurn(
                    action="call_tool",
                    tool="save_clip_candidate",
                    arguments_json=json.dumps({"artifact_id": candidate_id}),
                    summary="保存候选",
                ),
                observation=AgentObservation(
                    observation_id=f"obs_{turn:04d}",
                    tool="save_clip_candidate",
                    status="ok",
                    data={"artifact": candidate.model_dump(mode="json")},
                ),
                model_metadata=_metadata(),
            )
        )
        turn += 1
        events.append(
            AgentEvent(
                turn_number=turn,
                function_call_id=f"call_{turn}",
                action=AgentTurn(
                    action="call_tool",
                    tool="validate_clip_artifact",
                    arguments_json=json.dumps({"artifact_id": candidate_id}),
                    summary="技术校验",
                ),
                observation=AgentObservation(
                    observation_id=f"obs_{turn:04d}",
                    tool="validate_clip_artifact",
                    status="ok",
                ),
                model_metadata=_metadata(),
            )
        )
        if anchor_id != omit_title:
            titles.append(
                AgentArtifact(
                    artifact_id=f"title_{anchor_id.lower()}",
                    artifact_type="title_options",
                    data={"source_candidate_id": candidate_id},
                )
            )
    review_data: dict[str, object] = {
        "requested_profiles": ["short_highlight", "mini_lesson"],
        "final_candidate_ids": [value.artifact_id for value in candidates],
        "reviews": [
            {
                "candidate_artifact_id": value.artifact_id,
                "decision": "final",
            }
            for value in candidates
        ],
    }
    if executed_profiles is not None:
        review_data["executed_profiles"] = executed_profiles
    review = AgentArtifact(
        artifact_id="global_review_1",
        artifact_type="global_review",
        data=review_data,
    )
    artifacts = tuple([*candidates, review, *titles])
    turn += 1
    events.append(
        AgentEvent(
            turn_number=turn,
            function_call_id=f"call_{turn}",
            action=AgentTurn(
                action="finish",
                artifact_ids=tuple(value.artifact_id for value in artifacts),
                summary="完成",
            ),
            model_metadata=_metadata(),
        )
    )
    return AgentRunResult(
        run_id="agent_benchmark_fixture",
        run_identity_sha256="a" * 64,
        skill_version="agent_clipping_v2",
        skill_sha256="b" * 64,
        provider="fixture",
        model="fixture",
        initial_context={
            "source": {"transcript_sha256": source_hash or BENCHMARK["source"]["sha256"]}
        },
        events=tuple(events),
        artifacts=artifacts,
        summary="完成",
    )


BOTH = ["short_highlight", "mini_lesson"]


def _gates(report: dict[str, Any]) -> set[str]:
    return {str(value["gate"]) for value in report["not_evaluable"]}


def test_agent_evaluator_never_emits_plain_pass_for_complete_fixture() -> None:
    report = evaluate_agent(BENCHMARK, _result())

    assert report["status"] in ALLOWED_STATUSES
    assert report["status"] != "PASS"
    assert report["status"] == STATUS_TECHNICAL_FAIL
    assert report["contract_mode"] == "agent_v2_technical_provisional"
    assert report["short_hits"] == 8
    assert report["mini_lesson_hits"] == 6
    assert report["matched_p0"] == ["L01", "L02", "L03"]
    assert report["audit"]["consistent"] is True
    # Execution is never inferred from saved candidates.
    assert report["executed_profiles_recorded"] is False
    assert report["executed_profiles"] == []
    assert "executed_profiles" in _gates(report)
    assert report["components"]["both_profiles_executed"] == 0
    assert "missing_executed_profile" not in report["hard_failures"]


def test_not_evaluable_gates_block_technical_pass() -> None:
    report = evaluate_agent(BENCHMARK, _result(executed_profiles=BOTH))

    assert report["hard_failures"] == []
    assert report["executed_profiles"] == BOTH
    assert report["components"]["both_profiles_executed"] == 15
    assert report["audit"]["items"] == {
        "profile_counts": True,
        "candidate_dispositions": True,
        "version_hash": True,
        "call_data": True,
        "cache_repair_records": False,
    }
    # 15 + 20 + 30 + 15 + risk(unscored) 0 + audit 8
    assert report["score"] == 88
    assert _gates(report) == {
        "match_decision_buckets",
        "automatic_selection_score_gate",
        "forbidden_quality_flags",
        "risk_routing",
    }
    assert report["status"] == STATUS_TECHNICAL_FAIL
    assert "semantic_and_editorial_review" in report["human_required"]


def test_technical_status_vocabulary() -> None:
    assert (
        technical_status(invalid_evidence=[], hard_failures=[], not_evaluable=[])
        == STATUS_TECHNICAL_PASS_HUMAN_PENDING
    )
    assert (
        technical_status(
            invalid_evidence=[], hard_failures=[], not_evaluable=[{"gate": "risk_routing"}]
        )
        == STATUS_TECHNICAL_FAIL
    )
    assert (
        technical_status(
            invalid_evidence=[], hard_failures=["irrelevant_padding"], not_evaluable=[]
        )
        == STATUS_TECHNICAL_FAIL
    )
    assert (
        technical_status(
            invalid_evidence=["source_hash_mismatch"], hard_failures=[], not_evaluable=[]
        )
        == STATUS_INVALID_EVIDENCE
    )


def test_agent_source_hash_mismatch_is_invalid_evidence() -> None:
    report = evaluate_agent(BENCHMARK, _result(source_hash="0" * 64))

    assert report["status"] == STATUS_INVALID_EVIDENCE
    assert report["invalid_evidence"] == ["source_hash_mismatch"]


def test_agent_evaluator_fails_missing_p0_and_missing_title_audit() -> None:
    report = evaluate_agent(BENCHMARK, _result(omit="L03", omit_title="S01"))

    assert report["status"] == STATUS_TECHNICAL_FAIL
    assert "missing_any_p0_mini_lesson" in report["hard_failures"]
    assert "untraceable_or_inconsistent_audit" in report["hard_failures"]
    assert report["audit"]["missing_titles"] == ["candidate_s01"]


def test_agent_semantic_only_match_is_manual_not_a_hit() -> None:
    l02 = next(value for value in BENCHMARK["gold_mini_lesson"] if value["id"] == "L02")
    report = evaluate_agent(
        BENCHMARK,
        _result(
            executed_profiles=BOTH,
            overrides={
                "L02": {
                    "start_ms": int(l02["start_ms"]) - 6_000,
                    "cue_start": int(l02["cue_start"]) - 1,
                }
            },
        ),
    )

    assert "L02" not in {value["anchor_id"] for value in report["mini_lesson_matches"]}
    assert [value["anchor_id"] for value in report["manual_adjudication_required"]] == ["L02"]
    assert "missing_any_p0_mini_lesson" in report["hard_failures"]


def test_agent_padding_and_composite_are_mechanical_failures() -> None:
    n07 = next(value for value in BENCHMARK["negative_anchors"] if value["id"] == "N07")
    composite = BENCHMARK["forbidden_composite_intervals"][0]
    report = evaluate_agent(
        BENCHMARK,
        _result(
            executed_profiles=BOTH,
            extra=(
                {
                    "id": "PAD",
                    "profile": "short_highlight",
                    "start_ms": int(n07["start_ms"]) + 1_000,
                    "end_ms": int(n07["start_ms"]) + 61_000,
                    "cue_start": 1000,
                    "cue_end": 1020,
                },
                {
                    "id": "COMPOSITE",
                    "profile": "mini_lesson",
                    "start_ms": int(composite["start_ms"]),
                    "end_ms": int(composite["start_ms"]) + 138_000,
                    "cue_start": 200,
                    "cue_end": 260,
                },
            ),
        ),
    )

    assert report["status"] == STATUS_TECHNICAL_FAIL
    assert "irrelevant_padding" in report["hard_failures"]
    assert "forbidden_composite_interval" in report["hard_failures"]
    assert [value["candidate_id"] for value in report["padding_findings"]] == ["candidate_pad"]
    assert [value["candidate_id"] for value in report["forbidden_composite_findings"]] == [
        "candidate_composite"
    ]


def test_agent_s08_inside_n09_is_not_padding() -> None:
    report = evaluate_agent(BENCHMARK, _result(executed_profiles=BOTH))
    assert "S08" in {value["anchor_id"] for value in report["short_matches"]}
    assert report["padding_findings"] == []


@pytest.mark.parametrize("end_ms", [int(RGR02["end_ms"]), 2_160_060])
def test_agent_final_candidate_at_rgr02_opening_fails(end_ms: int) -> None:
    report = evaluate_agent(
        BENCHMARK,
        _result(
            executed_profiles=BOTH,
            extra=(
                {
                    "id": "RGR",
                    "profile": "short_highlight",
                    "start_ms": int(RGR02["start_ms"]),
                    "end_ms": end_ms,
                    "cue_start": 862,
                    "cue_end": 939,
                },
            ),
        ),
    )

    assert "RGR-02_auto_selected" in report["hard_failures"]
    assert report["regressions"][0]["auto_selected"] == ["candidate_rgr"]
    if end_ms == int(RGR02["end_ms"]):
        assert "RGR-02_required_quality_flags" in _gates(report)


def test_agent_full_l02_does_not_trip_rgr02() -> None:
    report = evaluate_agent(BENCHMARK, _result(executed_profiles=BOTH))
    assert report["regressions"][0]["auto_selected"] == []
    assert not any(value.startswith("RGR-02") for value in report["hard_failures"])
    assert not any(str(value["gate"]).startswith("RGR-02") for value in report["not_evaluable"])


def test_agent_matching_is_one_to_one() -> None:
    s01 = next(value for value in BENCHMARK["gold_short"] if value["id"] == "S01")
    report = evaluate_agent(
        BENCHMARK,
        _result(executed_profiles=BOTH, extra=(dict(s01, id="S01DUP", profile="short_highlight"),)),
    )

    assert report["short_hits"] == 8
    matched = [value["candidate_id"] for value in report["short_matches"]]
    assert len(matched) == len(set(matched))
    assert [value["anchor_id"] for value in report["short_matches"]].count("S01") == 1


def test_agent_duration_outside_profile_bounds_fails() -> None:
    s01 = next(value for value in BENCHMARK["gold_short"] if value["id"] == "S01")
    report = evaluate_agent(
        BENCHMARK,
        _result(
            executed_profiles=BOTH,
            overrides={"S01": {"end_ms": int(s01["start_ms"]) + 44_999}},
        ),
    )

    assert "duration_out_of_profile_bounds" in report["hard_failures"]
    assert report["duration_violations"][0]["candidate_id"] == "candidate_s01"
    assert "S01" not in {value["anchor_id"] for value in report["short_matches"]}


def test_agent_risk_discovery_requires_anchor_evidence_cues() -> None:
    r01 = next(value for value in BENCHMARK["risk_anchors"] if value["id"] == "R01")
    report = evaluate_agent(
        BENCHMARK,
        _result(
            executed_profiles=BOTH,
            overrides={
                "R01": {
                    "cue_start": int(r01["cue_start"]) - 2,
                    "evidence": [int(r01["cue_start"]) - 2],
                }
            },
        ),
    )

    assert "risk_discovery_without_evidence_cues" in report["hard_failures"]
    assert "risk_suppressed_during_discovery" not in report["hard_failures"]
    assert report["risk_findings"]["R01"]["missing_evidence_cues"][0]["candidate_id"] == (
        "candidate_r01"
    )
    assert "risk_routing" in _gates(report)


def test_agent_risk_absent_is_suppressed_during_discovery() -> None:
    report = evaluate_agent(BENCHMARK, _result(executed_profiles=BOTH, omit="R02"))
    assert "risk_suppressed_during_discovery" in report["hard_failures"]


def test_agent_cli_publishes_new_reports_and_refuses_existing_output(tmp_path: Path) -> None:
    result_path = tmp_path / "agent-run-result.json"
    result_path.write_text(_result().model_dump_json(), encoding="utf-8")
    output = tmp_path / "report"

    assert main([str(BENCHMARK_PATH), str(result_path), "--output-dir", str(output)]) == 1
    saved = json.loads((output / "benchmark-result.json").read_text(encoding="utf-8"))
    assert saved["status"] == STATUS_TECHNICAL_FAIL
    assert "TECHNICAL_FAIL" in (output / "benchmark-report.md").read_text(encoding="utf-8")
    before = (output / "benchmark-result.json").read_bytes()

    with pytest.raises(SystemExit) as exc:
        main([str(BENCHMARK_PATH), str(result_path), "--output-dir", str(output)])
    assert exc.value.code == 2
    assert (output / "benchmark-result.json").read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "agent-run-result.json",
        "report",
    ]
