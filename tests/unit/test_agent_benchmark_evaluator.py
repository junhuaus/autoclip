from __future__ import annotations

import json
from pathlib import Path

from liveclip.agent_runtime.models import (
    AgentArtifact,
    AgentEvent,
    AgentObservation,
    AgentRunResult,
    AgentTurn,
)
from scripts.evaluate_agent_benchmark import evaluate_agent

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = json.loads(
    (ROOT / "liveclip_dual_profile_benchmark_v1.json").read_text(encoding="utf-8")
)


def _result(*, omit: str | None = None, omit_title: str | None = None) -> AgentRunResult:
    candidates: list[AgentArtifact] = []
    titles: list[AgentArtifact] = []
    events: list[AgentEvent] = []
    anchors = [
        *(dict(value, profile="short_highlight") for value in BENCHMARK["gold_short"]),
        *(dict(value, profile="mini_lesson") for value in BENCHMARK["gold_mini_lesson"]),
        *(dict(value, profile="mini_lesson") for value in BENCHMARK["risk_anchors"]),
    ]
    turn = 0
    for anchor in anchors:
        anchor_id = str(anchor["id"])
        if anchor_id == omit:
            continue
        candidate_id = f"candidate_{anchor_id.lower()}"
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
                "score": 90,
                "score_reason": "完整测试候选",
                "score_dimensions": [],
            },
            evidence=({"cue_ids": [int(anchor["cue_start"]), int(anchor["cue_end"])]},),
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
    review = AgentArtifact(
        artifact_id="global_review_1",
        artifact_type="global_review",
        data={
            "requested_profiles": ["short_highlight", "mini_lesson"],
            "final_candidate_ids": [value.artifact_id for value in candidates],
            "reviews": [
                {
                    "candidate_artifact_id": value.artifact_id,
                    "decision": "final",
                }
                for value in candidates
            ],
        },
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
        )
    )
    return AgentRunResult(
        run_id="agent_benchmark_fixture",
        run_identity_sha256="a" * 64,
        skill_version="agent_clipping_v2",
        skill_sha256="b" * 64,
        provider="fixture",
        model="fixture",
        initial_context={"source": {"transcript_sha256": BENCHMARK["source"]["sha256"]}},
        events=tuple(events),
        artifacts=artifacts,
        summary="完成",
    )


def test_agent_evaluator_passes_score_only_contract_without_fabricated_risk_routes() -> None:
    report = evaluate_agent(BENCHMARK, _result())

    assert report["status"] == "PASS"
    assert report["score"] == 100
    assert report["short_hits"] == 8
    assert report["mini_lesson_hits"] == 6
    assert report["matched_p0"] == ["L01", "L02", "L03"]
    assert report["contract_mode"] == "agent_v2_score_only_no_risk_routing"
    assert report["audit"]["consistent"] is True


def test_agent_evaluator_fails_missing_p0_and_missing_title_audit() -> None:
    report = evaluate_agent(BENCHMARK, _result(omit="L03", omit_title="S01"))

    assert report["status"] == "FAIL"
    assert "missing_any_p0_mini_lesson" in report["hard_failures"]
    assert "untraceable_or_inconsistent_audit" in report["hard_failures"]
    assert report["audit"]["missing_titles"] == ["candidate_s01"]
