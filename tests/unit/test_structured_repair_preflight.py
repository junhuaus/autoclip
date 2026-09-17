from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest

from liveclip.clipping_skills.semantic_windowed_v1 import (
    load_semantic_windowed_discovery_prompt,
)
from liveclip.pipeline.semantic_global import DiscoveryOutput
from liveclip.providers.llm.structured import (
    OpenAIStructuredLLMProvider,
    StructuredProviderError,
    _global_reason_preflight_errors,
    _schema_repair_payload,
    _structured_preflight_errors,
    _structured_repair_evidence,
    global_review_response_model,
)
from liveclip.providers.openai_retry import OpenAIRetryPolicy


class _FakeResponses:
    def __init__(self, *responses: object) -> None:
        self._responses = list(responses)

    def parse(self, **_kwargs: object) -> object:
        if not self._responses:
            raise AssertionError("unexpected extra structured Provider call")
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, *responses: object) -> None:
        self.responses = _FakeResponses(*responses)


def _response(parsed: DiscoveryOutput, request_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="completed",
        output_parsed=parsed,
        output=(
            SimpleNamespace(
                type="message",
                content=(SimpleNamespace(type="output_text"),),
            ),
        ),
        usage=None,
        _request_id=request_id,
        model="gpt-5.6-terra",
    )


def _cues(start: int = 90, end: int = 100) -> list[dict[str, object]]:
    return [
        {
            "cue_id": cue_id,
            "segment_id": f"segment_{cue_id}",
            "start_ms": (cue_id - start) * 10_000,
            "end_ms": (cue_id - start) * 10_000 + 9_000,
            "original_text": f"cue {cue_id}",
            "normalized_text": None,
            "normalization_note": None,
        }
        for cue_id in range(start, end + 1)
    ]


def _error(invalid_output: dict[str, object]) -> StructuredProviderError:
    return StructuredProviderError(
        "STRUCTURED_OUTPUT_INVALID",
        (),
        repair_attempts=(
            {
                "phase": "initial",
                "validation_errors": ["topic_units.0: synthetic schema error"],
                "invalid_output": invalid_output,
            },
        ),
    )


def _discovery_payload() -> dict[str, object]:
    return {
        "schema_version": "2",
        "source_id": "source_8163",
        "input_mode": "full_context",
        "input_unit_id": "full_context",
        "source_range": {"start_cue_id": 90, "end_cue_id": 100},
        "runtime": {
            "minimum_duration_sec": 1,
            "target_duration_sec": 30,
            "maximum_duration_sec": 90,
        },
        "cues": _cues(),
    }


def _overlapping_discovery_output() -> dict[str, object]:
    return {
        "source_id": "source_8163",
        "source_range": {"start_cue_id": 90, "end_cue_id": 100},
        "starts_inside_open_topic": False,
        "ends_inside_open_topic": False,
        "boundary_topics": [],
        "topic_units": [
            {
                "topic_id": "topic_001",
                "start_cue_id": 90,
                "end_cue_id": 96,
                "summary": "first topic",
                "value_density": "low",
                "candidate_ids": [],
                "candidate_status": "no_candidate",
                "no_candidate_reason_code": "no_general_value",
            },
            {
                "topic_id": "topic_002",
                "start_cue_id": 96,
                "end_cue_id": 100,
                "summary": "second topic",
                "value_density": "low",
                "candidate_ids": [],
                "candidate_status": "no_candidate",
                "no_candidate_reason_code": "no_general_value",
            },
        ],
        "candidates": [],
    }


def test_global_review_schema_requires_exact_windowed_coverage_cardinality() -> None:
    payload: dict[str, object] = {
        "discovery": {
            "review_scope": "candidate_topics_and_boundary_bridges",
            "topic_units": [
                {
                    "topic_id": "topic_candidate",
                    "value_density": "high",
                    "candidate_ids": ["candidate_001"],
                },
                {
                    "topic_id": "bridge_001",
                    "value_density": "high",
                    "candidate_ids": [],
                },
                {
                    "topic_id": "topic_transport_only",
                    "value_density": "medium",
                    "candidate_ids": [],
                },
                {
                    "topic_id": "topic_low_candidate",
                    "value_density": "low",
                    "candidate_ids": ["candidate_002"],
                },
            ],
        }
    }

    response_model = global_review_response_model(payload)
    coverage_schema = response_model.model_json_schema(mode="validation")["properties"][
        "coverage_decisions"
    ]

    assert response_model.__name__ == "GlobalReviewOutput"
    assert coverage_schema["minItems"] == 2
    assert coverage_schema["maxItems"] == 2


def test_accuracy_first_global_review_schema_requires_one_scorecard_per_candidate() -> None:
    payload: dict[str, object] = {
        "candidate_assessment_contract": {
            "required": True,
            "strict_score_threshold_exclusive": 75,
        },
        "discovery": {
            "review_scope": "candidate_topics_and_boundary_bridges",
            "topic_units": [
                {
                    "topic_id": "topic_candidate",
                    "value_density": "high",
                    "candidate_ids": ["candidate_001", "candidate_002"],
                },
            ],
            "candidates": [
                {"candidate_id": "candidate_001"},
                {"candidate_id": "candidate_002"},
            ],
        },
    }

    response_model = global_review_response_model(
        payload,
        require_candidate_assessments=True,
    )
    schema = response_model.model_json_schema(mode="validation")
    assessments_schema = schema["properties"]["candidate_assessments"]

    assert response_model.__name__ == "GlobalReviewOutputV2"
    assert assessments_schema["minItems"] == 2
    assert assessments_schema["maxItems"] == 2


def test_accuracy_first_preflight_rejects_observed_thirty_candidate_score_suppression() -> None:
    candidate_ids = [f"candidate_{index:03d}" for index in range(30)]
    score_76 = {
        "standalone": 16,
        "general_value": 16,
        "interest": 16,
        "completeness": 16,
        "evidence": 6,
        "edit_cleanliness": 6,
    }
    payload: dict[str, object] = {
        "candidate_assessment_contract": {
            "required": True,
            "candidate_count": 30,
            "strict_score_threshold_exclusive": 75,
        },
        "runtime": {"minimum_duration_sec": 45, "maximum_duration_sec": 90},
        "discovery": {
            "review_scope": "candidate_topics_and_boundary_bridges",
            "topic_units": [
                {
                    "topic_id": "topic_001",
                    "value_density": "high",
                    "candidate_ids": candidate_ids,
                },
            ],
            "candidates": [{"candidate_id": candidate_id} for candidate_id in candidate_ids],
        },
    }
    invalid_output: dict[str, object] = {
        "clips": [],
        "rejected_candidates": [
            {
                "candidate_ids": candidate_ids,
                "topic_ids": ["topic_001"],
                "reason_code": "no_general_value",
                "reason": "bulk rejection",
                "duplicate_of_clip_id": None,
                "duplicate_of_topic_id": None,
                "ideal_start_cue_id": None,
                "ideal_end_cue_id": None,
                "model_claimed_duration_sec": None,
                "boundary_alternatives": [],
                "risks": [],
            },
        ],
        "coverage_decisions": [],
        "candidate_assessments": [
            {
                "candidate_id": candidate_id,
                "disposition": "reject",
                "score_dimensions": score_76,
                "result_clip_id": None,
            }
            for candidate_id in candidate_ids
        ],
    }

    repair = _schema_repair_payload(payload, _error(invalid_output))
    errors = cast(list[str], repair["validation_errors"])

    assert any(
        "candidate_000: no_general_value cannot suppress score 76" in error for error in errors
    )
    assert any(
        "candidate_029: no_general_value cannot suppress score 76" in error for error in errors
    )


def test_schema_repair_rehydrates_compact_global_review_candidate_and_topic_ids() -> None:
    payload: dict[str, object] = {
        "mode": "semantic_context",
        "discovery": {
            "transport_format": "rows_follow_declared_columns",
            "candidate_columns": ["candidate_id", "start_cue_id", "end_cue_id"],
            "candidates": [["candidate_001", 10, 20], ["candidate_002", 30, 40]],
            "topic_unit_columns": ["topic_id", "value_density", "candidate_ids"],
            "topic_units": [
                ["topic_001", "high", ["candidate_001"]],
                ["topic_002", "medium", ["candidate_002"]],
            ],
        },
    }
    invalid_output: dict[str, object] = {
        "clips": [],
        "rejected_candidates": [],
        "coverage_decisions": [],
    }

    repair = _schema_repair_payload(payload, _error(invalid_output))

    assert repair["valid_discovery_candidate_ids"] == ["candidate_001", "candidate_002"]
    assert repair["valid_discovery_topic_ids"] == ["topic_001", "topic_002"]


def test_schema_repair_preflight_catches_r11_evidence_before_candidate_start() -> None:
    invalid_output: dict[str, object] = {
        "source_id": "source_8163",
        "source_range": {"start_cue_id": 90, "end_cue_id": 100},
        "topic_units": [
            {
                "topic_id": "topic_001",
                "start_cue_id": 90,
                "end_cue_id": 100,
                "candidate_ids": ["candidate_001"],
            }
        ],
        "candidates": [
            {
                "candidate_id": "candidate_001",
                "start_cue_id": 94,
                "end_cue_id": 96,
                "evidence_cue_ids": [93, 94, 95, 96],
                "source_opening_quote": "cue 94",
                "opening_relevance": "direct",
                "topic_core_start_cue_id": 94,
                "topic_core_end_cue_id": 96,
                "irrelevant_intro_cue_ids": [],
                "irrelevant_outro_cue_ids": [],
                "quality_flags": [],
                "risks": [],
            }
        ],
    }

    repair = _schema_repair_payload(_discovery_payload(), _error(invalid_output))
    errors = cast(list[str], repair["validation_errors"])

    assert "topic_units.0: synthetic schema error" in errors
    assert "candidate_001: evidence cue IDs outside candidate interval 94-96: [93]" in errors


def test_discovery_no_candidate_duration_audit_does_not_force_repair() -> None:
    invalid_output: dict[str, object] = {
        "source_id": "source_8163",
        "source_range": {"start_cue_id": 90, "end_cue_id": 100},
        "topic_units": [
            {
                "topic_id": "topic_duration",
                "start_cue_id": 90,
                "end_cue_id": 100,
                "candidate_ids": [],
                "candidate_status": "no_candidate",
                "no_candidate_reason_code": "duration_too_long",
                "ideal_start_cue_id": None,
                "ideal_end_cue_id": None,
                "model_claimed_duration_sec": None,
            }
        ],
        "candidates": [],
    }

    repair = _schema_repair_payload(_discovery_payload(), _error(invalid_output))
    errors = cast(list[str], repair["validation_errors"])

    assert not any("duration reason requires ideal cue boundaries" in value for value in errors)
    assert not any("model_claimed_duration_sec" in value for value in errors)


def test_discovery_exact_domain_validation_runs_before_the_one_repair() -> None:
    payload = _discovery_payload()
    runtime = cast(dict[str, object], payload["runtime"])
    runtime.update(
        {
            "score_threshold_exclusive": 75.0,
            "max_clips": 15,
            "window_duration_sec": 120,
            "window_overlap_sec": 60,
        }
    )
    invalid_output = _overlapping_discovery_output()

    errors = "\n".join(_structured_preflight_errors(payload, invalid_output))

    assert "Discovery domain validation" in errors
    assert "topic map contains overlapping cue ranges: [(96, 96)]" in errors


def test_repaired_discovery_is_revalidated_against_the_original_unit() -> None:
    payload = _discovery_payload()
    runtime = cast(dict[str, object], payload["runtime"])
    runtime.update(
        {
            "score_threshold_exclusive": 75.0,
            "max_clips": 15,
            "window_duration_sec": 120,
            "window_overlap_sec": 60,
        }
    )
    invalid = DiscoveryOutput.model_validate_json(json.dumps(_overlapping_discovery_output()))
    provider = OpenAIStructuredLLMProvider(
        prompts=load_semantic_windowed_discovery_prompt("general"),
        model_name="gpt-5.6-terra",
        api_key=None,
        timeout_seconds=30,
        retry_policy=OpenAIRetryPolicy(max_retries=0),
        client=_FakeClient(
            _response(invalid, "req_initial"),
            _response(invalid, "req_repair"),
        ),
    )

    with pytest.raises(StructuredProviderError) as captured:
        provider.generate(
            subject_id="full_context",
            payload=payload,
            response_model=DiscoveryOutput,
        )

    assert captured.value.code == "STRUCTURED_OUTPUT_INVALID"
    assert len(captured.value.call_records) == 2
    assert [record.status.value for record in captured.value.call_records] == [
        "invalid",
        "invalid",
    ]


def test_global_review_preflight_does_not_require_discovery_source_id() -> None:
    payload: dict[str, object] = {
        "source_id": "source_8163",
        "runtime": {},
        "discovery": {"topic_units": [], "candidates": []},
    }
    global_output: dict[str, object] = {
        "review_summary": {"global_notes": []},
        "clips": [],
        "rejected_candidates": [],
        "coverage_decisions": [],
        "coverage_notes": [],
    }

    errors = _structured_preflight_errors(payload, global_output)

    assert not any("source_id must equal" in value for value in errors)


def test_repair_evidence_budget_keeps_late_candidates_instead_of_whole_topic_map() -> None:
    payload = _discovery_payload()
    payload["source_range"] = {"start_cue_id": 1, "end_cue_id": 701}
    payload["cues"] = _cues(1, 701)
    invalid_output: dict[str, object] = {
        "source_id": "source_long",
        "source_range": {"start_cue_id": 1, "end_cue_id": 701},
        "topic_units": [
            {
                "topic_id": "topic_whole_source",
                "start_cue_id": 1,
                "end_cue_id": 701,
                "candidate_ids": ["candidate_late"],
            }
        ],
        "candidates": [
            {
                "candidate_id": "candidate_late",
                "start_cue_id": 650,
                "end_cue_id": 660,
            }
        ],
    }

    repair = _schema_repair_payload(payload, _error(invalid_output))
    evidence = cast(list[dict[str, object]], repair["affected_evidence"])
    evidence_ids = {int(value["cue_id"]) for value in evidence}

    assert 650 in evidence_ids
    assert 660 in evidence_ids
    assert 1 not in evidence_ids


def test_repair_evidence_preserves_boundaries_across_many_long_video_clips() -> None:
    payload = _discovery_payload()
    payload["source_range"] = {"start_cue_id": 1, "end_cue_id": 1_329}
    payload["cues"] = _cues(1, 1_329)
    clips = [
        {
            "clip_id": f"clip_{index:03d}",
            "start_cue_id": start,
            "end_cue_id": start + 20,
        }
        for index, start in enumerate(range(60, 1_261, 80), start=1)
    ]
    invalid_output: dict[str, object] = {
        "clips": clips,
        "coverage_decisions": [],
        "rejected_candidates": [],
    }

    evidence = _structured_repair_evidence(payload, invalid_output)
    evidence_ids = {int(value["cue_id"]) for value in evidence}

    assert {60, 80, 1_260, 1_280} <= evidence_ids
    assert len(evidence_ids) < len(cast(list[dict[str, object]], payload["cues"]))


def test_repair_evidence_includes_risk_cues_from_rejected_items() -> None:
    payload = _discovery_payload()
    payload["source_range"] = {"start_cue_id": 1, "end_cue_id": 701}
    payload["cues"] = _cues(1, 701)
    invalid_output: dict[str, object] = {
        "clips": [],
        "coverage_decisions": [],
        "rejected_candidates": [
            {
                "candidate_ids": ["candidate_risk"],
                "reason_code": "no_general_value",
                "risks": [{"source_cue_ids": [650]}],
            }
        ],
    }

    evidence = _structured_repair_evidence(payload, invalid_output)
    evidence_ids = {int(value["cue_id"]) for value in evidence}

    assert 650 in evidence_ids


def test_duration_rejection_boundary_may_cross_but_must_overlap_source_topic() -> None:
    cues = _cues(90, 110)
    cue_objects = {int(value["cue_id"]): value for value in cues}
    value: dict[str, object] = {
        "reason_code": "duration_too_long",
        "ideal_start_cue_id": 90,
        "ideal_end_cue_id": 100,
        "model_claimed_duration_sec": 108.5,
        "boundary_alternatives": [
            {
                "start_cue_id": 91,
                "end_cue_id": 99,
                "viewer_promise": "A narrower independently reviewable promise",
                "completeness": "incomplete",
                "reason": "The answer still depends on material outside this subrange.",
            }
        ],
    }
    common = {
        "cue_objects": cue_objects,
        "minimum": 45,
        "maximum": 90,
        "clip_map": {},
        "topic_map": {"topic_source": {"start_cue_id": 95, "end_cue_id": 97}},
        "source_topic_ids": ["topic_source"],
        "source_candidate_ids": [],
        "candidate_records": [],
    }

    assert _global_reason_preflight_errors("coverage", value, **common) == []

    non_overlapping = {**value, "ideal_start_cue_id": 100, "ideal_end_cue_id": 110}
    errors = _global_reason_preflight_errors("coverage", non_overlapping, **common)

    assert any(
        "duration boundaries must overlap a referenced topic/candidate" in error for error in errors
    )


def test_duration_rejection_preflight_accepts_optional_complete_alternative_audit() -> None:
    cues = _cues(90, 110)
    cue_objects = {int(value["cue_id"]): value for value in cues}
    value: dict[str, object] = {
        "reason_code": "duration_too_long",
        "ideal_start_cue_id": 90,
        "ideal_end_cue_id": 100,
        "model_claimed_duration_sec": 108.5,
        "boundary_alternatives": [
            {
                "start_cue_id": 91,
                "end_cue_id": 99,
                "viewer_promise": "A narrower independently reviewable promise",
                "completeness": "complete",
                "reason": "The promise is fully paid off inside the legal subrange.",
            }
        ],
    }

    errors = _global_reason_preflight_errors(
        "coverage",
        value,
        cue_objects=cue_objects,
        minimum=45,
        maximum=90,
        clip_map={},
        topic_map={"topic_source": {"start_cue_id": 95, "end_cue_id": 97}},
        source_topic_ids=["topic_source"],
        source_candidate_ids=[],
        candidate_records=[],
    )

    assert errors == []


def test_incomplete_rejection_preflight_accepts_optional_complete_extension_audit() -> None:
    cues = _cues(90, 110)
    cue_objects = {int(value["cue_id"]): value for value in cues}
    value: dict[str, object] = {
        "reason_code": "incomplete_topic",
        "ideal_start_cue_id": 90,
        "ideal_end_cue_id": 97,
        "model_claimed_duration_sec": 79,
        "boundary_alternatives": [
            {
                "start_cue_id": 90,
                "end_cue_id": 98,
                "viewer_promise": "An adjacent cue closes the same promise",
                "completeness": "complete",
                "reason": "The extension supplies the missing payoff.",
            }
        ],
    }

    errors = _global_reason_preflight_errors(
        "coverage",
        value,
        cue_objects=cue_objects,
        minimum=45,
        maximum=90,
        clip_map={},
        topic_map={"topic_source": {"start_cue_id": 90, "end_cue_id": 97}},
        source_topic_ids=["topic_source"],
        source_candidate_ids=[],
        candidate_records=[],
    )

    assert errors == []


def test_incomplete_rejection_preflight_does_not_require_mechanical_end_extension() -> None:
    cues = _cues(90, 110)
    cue_objects = {int(value["cue_id"]): value for value in cues}
    value: dict[str, object] = {
        "reason_code": "cannot_form_continuous_clip",
        "ideal_start_cue_id": 90,
        "ideal_end_cue_id": 97,
        "model_claimed_duration_sec": 79,
        "boundary_alternatives": [
            {
                "start_cue_id": 91,
                "end_cue_id": 97,
                "viewer_promise": "Only a shorter prefix was reviewed",
                "completeness": "incomplete",
                "reason": "It still lacks a payoff.",
            }
        ],
    }

    errors = _global_reason_preflight_errors(
        "coverage",
        value,
        cue_objects=cue_objects,
        minimum=45,
        maximum=90,
        clip_map={},
        topic_map={"topic_source": {"start_cue_id": 90, "end_cue_id": 97}},
        source_topic_ids=["topic_source"],
        source_candidate_ids=[],
        candidate_records=[],
    )

    assert errors == []


def test_schema_repair_supplies_exact_immediate_following_cue() -> None:
    invalid_output: dict[str, object] = {
        "clips": [
            {
                "clip_id": "clip_boundary",
                "start_cue_id": 94,
                "end_cue_id": 96,
            }
        ],
        "coverage_decisions": [],
        "rejected_candidates": [],
    }

    repair = _schema_repair_payload(_discovery_payload(), _error(invalid_output))
    options = cast(list[dict[str, object]], repair["authoritative_boundary_quote_options"])

    assert options == [
        {
            "item_id": "clip_boundary",
            "start_cue_id": 94,
            "end_cue_id": 96,
            "exact_opening_quote_options": ["cue 94", "cue 95"],
            "exact_closing_quote_options": ["cue 95", "cue 96"],
            "immediate_following_cue_id": 97,
            "exact_following_cue_quote": "cue 97",
        }
    ]


def test_schema_repair_preflight_aggregates_discovery_cross_field_errors() -> None:
    invalid_output: dict[str, object] = {
        "source_id": "source_8163",
        "source_range": {"start_cue_id": 90, "end_cue_id": 100},
        "topic_units": [
            {
                "topic_id": "topic_001",
                "start_cue_id": 90,
                "end_cue_id": 100,
                "candidate_ids": ["candidate_core", "missing_candidate"],
            }
        ],
        "candidates": [
            {
                "candidate_id": "candidate_bad",
                "start_cue_id": 94,
                "end_cue_id": 96,
                "evidence_cue_ids": [96, 93, 93],
                "source_opening_quote": "fabricated opening",
                "opening_relevance": "irrelevant",
                "topic_core_start_cue_id": 95,
                "topic_core_end_cue_id": 95,
                "irrelevant_intro_cue_ids": [96, 93],
                "irrelevant_outro_cue_ids": [94],
                "quality_flags": [],
                "risks": [{"source_cue_ids": [96, 93, 93]}],
            },
            {
                "candidate_id": "candidate_core",
                "start_cue_id": 94,
                "end_cue_id": 96,
                "evidence_cue_ids": [94],
                "source_opening_quote": "cue 94",
                "opening_relevance": "direct",
                "topic_core_start_cue_id": 97,
                "topic_core_end_cue_id": 93,
                "irrelevant_intro_cue_ids": [],
                "irrelevant_outro_cue_ids": [],
                "quality_flags": [],
                "risks": [],
            },
        ],
    }

    repair = _schema_repair_payload(_discovery_payload(), _error(invalid_output))
    joined = "\n".join(cast(list[str], repair["validation_errors"]))

    assert "references unknown candidate IDs ['missing_candidate']" in joined
    assert "candidate_bad: candidate is not referenced by any topic unit" in joined
    assert "candidate_core: topic core must use existing ordered cue IDs" in joined
    assert "candidate_bad: source_opening_quote must be copied" in joined
    assert "candidate_bad: evidence cue IDs must be unique" in joined
    assert "candidate_bad: evidence cue IDs must be in source order" in joined
    assert "candidate_bad: irrelevant intro cue IDs must precede selected start" in joined
    assert "candidate_bad: irrelevant outro cue IDs must follow selected end" in joined
    assert "candidate_bad: risk[0] source cue IDs outside candidate interval" in joined


def test_schema_repair_preflight_aggregates_global_review_errors() -> None:
    cues = _cues()
    payload: dict[str, object] = {
        "schema_version": "2",
        "mode": "full_context",
        "runtime": {
            "minimum_duration_sec": 1,
            "target_duration_sec": 30,
            "maximum_duration_sec": 90,
        },
        "discovery": {
            "candidates": [{"candidate_id": "candidate_001"}],
            "topic_units": [
                {
                    "topic_id": "topic_high",
                    "start_cue_id": 90,
                    "end_cue_id": 100,
                    "summary": "High topic",
                    "value_density": "high",
                },
                {
                    "topic_id": "topic_medium",
                    "start_cue_id": 90,
                    "end_cue_id": 100,
                    "summary": "Medium topic",
                    "value_density": "medium",
                },
            ],
        },
        "evidence": {"full_transcript": cues},
    }
    invalid_output: dict[str, object] = {
        "review_summary": {"global_notes": []},
        "clips": [
            {
                "clip_id": "clip_001",
                "source_candidate_ids": ["candidate_001"],
                "source_topic_ids": ["topic_high"],
                "origin": "discovery",
                "editorial_decision": "keep",
                "review_status": "clear",
                "start_cue_id": 94,
                "end_cue_id": 96,
                "source_opening_quote": "fabricated opening",
                "source_closing_quote": "fabricated closing",
                "opening_relevance": "direct",
                "ending_complete": False,
                "first_complete_payoff_cue_id": 95,
                "boundary_compactness": "contains_removable_context",
                "source_fidelity": "unsupported_reframe",
                "source_fidelity_notes": "标题改变了原话立场",
                "topic_core_start_cue_id": 95,
                "topic_core_end_cue_id": 96,
                "irrelevant_intro_cue_ids": [94],
                "irrelevant_outro_cue_ids": [],
                "quality_flags": ["irrelevant_intro"],
                "score_dimensions": {
                    "standalone": 16,
                    "general_value": 16,
                    "interest": 16,
                    "completeness": 16,
                    "evidence": 8,
                    "edit_cleanliness": 10,
                },
                "risks": [{"source_cue_ids": [93]}],
            }
        ],
        "rejected_candidates": [],
        "coverage_decisions": [
            {
                "topic_id": "topic_high",
                "decision": "represented",
                "clip_ids": ["missing_clip"],
                "reason_code": "represented_by_clip",
            }
        ],
        "coverage_notes": [],
    }

    repair = _schema_repair_payload(payload, _error(invalid_output))
    joined = "\n".join(cast(list[str], repair["validation_errors"]))

    assert "clip_001: source_opening_quote must be copied" in joined
    assert "clip_001: source_closing_quote must be copied" in joined
    assert "clip_001: incomplete ending cannot be kept" in joined
    assert "clip_001: first payoff already forms a legal" in joined
    assert "clip_001: kept clip must use the shortest complete boundary" in joined
    assert "clip_001: unsupported title/hook/payoff reframe cannot be kept" in joined
    assert "clip_001: irrelevant intro requires edit_cleanliness <= 5" in joined
    assert "clip_001: risk[0] source cue IDs outside candidate interval 94-96: [93]" in joined
    assert "missing=['topic_medium']" in joined
    assert "coverage topic_id=topic_high: references unknown clip IDs ['missing_clip']" in joined


def test_repair_response_reuses_authoritative_context_for_cross_field_preflight() -> None:
    cues = _cues()
    payload: dict[str, object] = {
        "schema_version": "2",
        "mode": "full_context",
        "runtime": {
            "minimum_duration_sec": 1,
            "target_duration_sec": 30,
            "maximum_duration_sec": 90,
        },
        "discovery": {
            "candidates": [{"candidate_id": "candidate_001"}],
            "topic_units": [
                {
                    "topic_id": "topic_a",
                    "start_cue_id": 90,
                    "end_cue_id": 93,
                    "summary": "Topic A",
                    "value_density": "medium",
                },
                {
                    "topic_id": "topic_b",
                    "start_cue_id": 94,
                    "end_cue_id": 100,
                    "summary": "Topic B",
                    "value_density": "medium",
                },
            ],
        },
        "evidence": {"full_transcript": cues},
    }
    repaired_output: dict[str, object] = {
        "review_summary": {"global_notes": []},
        "clips": [
            {
                "clip_id": "clip_001",
                "source_candidate_ids": ["candidate_001"],
                "source_topic_ids": ["topic_a"],
                "origin": "discovery",
                "editorial_decision": "keep",
                "review_status": "clear",
                "start_cue_id": 94,
                "end_cue_id": 100,
                "source_opening_quote": "cue 94",
                "source_closing_quote": "cue 100",
                "opening_relevance": "direct",
                "ending_complete": True,
                "first_complete_payoff_cue_id": 100,
                "minimum_duration_extension_cue_ids": [],
                "boundary_compactness": "shortest_complete",
                "source_fidelity": "faithful",
                "source_fidelity_notes": "faithful",
                "topic_core_start_cue_id": 94,
                "topic_core_end_cue_id": 100,
                "irrelevant_intro_cue_ids": [],
                "irrelevant_outro_cue_ids": [],
                "quality_flags": [],
                "score_dimensions": {
                    "standalone": 16,
                    "general_value": 16,
                    "interest": 16,
                    "completeness": 16,
                    "evidence": 8,
                    "edit_cleanliness": 8,
                },
                "risks": [],
            }
        ],
        "rejected_candidates": [],
        "coverage_decisions": [
            {
                "topic_id": "topic_a",
                "decision": "represented",
                "clip_ids": ["clip_001"],
                "reason_code": "represented_by_clip",
            },
            {
                "topic_id": "topic_b",
                "decision": "represented",
                "clip_ids": ["clip_001"],
                "reason_code": "represented_by_clip",
            },
        ],
        "coverage_notes": [],
    }

    repair_payload = _schema_repair_payload(payload, _error(repaired_output))
    errors = "\n".join(_structured_preflight_errors(repair_payload, repaired_output))

    assert "clip_001 must trace source topic topic_b" in errors
    assert "clip_001 must overlap source topic topic_a" in errors
