from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from liveclip.domain.clip_profile import (
    MINI_LESSON_SPEC,
    SHORT_HIGHLIGHT_SPEC,
    ClipProfile,
    clip_profile_spec,
)
from liveclip.domain.semantic_validation import CURRENT_SEMANTIC_VALIDATION
from liveclip.domain.transcript import TranscriptDocument, TranscriptSegment, WordTimingStatus
from liveclip.pipeline.semantic_profiles import (
    BoundaryEvidenceV4,
    BoundaryReviewV4,
    CandidateDispositionV4,
    CandidateGlobalReviewV4,
    ChainCandidateV4,
    ContentDecisionV4,
    DiscoveryBatchOutputV4,
    GlobalReviewOutputV4,
    InterruptionReviewV4,
    InterruptionSeverityV4,
    LinkRelationshipV4,
    LinkReviewV4,
    LogicalWindowDiscoveryV4,
    MiniLessonScoresV4,
    PublishStatusV4,
    QualityFlagV4,
    RiskFlagV4,
    ShortHighlightScoresV4,
    TimeRangeV4,
    TopicBoundaryV4,
    TopicChainReviewV4,
    TopicChainStatusV4,
    TopicFragmentV4,
    UnifiedSemanticResultV4,
    assemble_topic_chains_v4,
    namespace_discovery_batch_v4,
    plan_followup_link_review_requests_v4,
    plan_link_review_requests_v4,
    validate_boundary_review_v4,
    validate_profile_global_review_v4,
    validate_topic_chain_review_v4,
)


@pytest.mark.parametrize(
    "changes",
    [
        {"opening_complete": False},
        {"ending_complete": False},
        {"central_objective_complete": False},
        {"opening_complete": False, "ending_complete": False},
        {"opening_complete": False, "central_objective_complete": False},
        {"ending_complete": False, "central_objective_complete": False},
        {
            "opening_complete": False,
            "ending_complete": False,
            "central_objective_complete": False,
        },
        {"contains_padding": True},
        {"internal_topic_switch": True},
        {"opening_relevance": "irrelevant"},
        {"ending_relevance": "redundant"},
        {"ending_relevance": "incomplete"},
        {"boundary_compactness": "contains_removable_context"},
    ],
)
def test_quality_contract_rejects_contradictory_boundary_without_changing_wire(changes):
    transcript = _transcript()
    candidate = _candidate()
    raw = _boundary_review(candidate).model_dump(mode="json")
    raw.update(changes)
    boundary = BoundaryReviewV4.model_validate_json(json.dumps(raw))
    original_boundary = boundary.model_dump_json()
    # Historical wire loading and business semantics remain readable/replayable.
    assert validate_boundary_review_v4(boundary, candidate=candidate, transcript=transcript)
    with pytest.raises(ValueError, match="Boundary quality consistency"):
        validate_boundary_review_v4(
            boundary,
            candidate=candidate,
            transcript=transcript,
            validation_contract=CURRENT_SEMANTIC_VALIDATION,
        )
    with pytest.raises(ValueError, match="Boundary quality consistency"):
        validate_profile_global_review_v4(
            GlobalReviewOutputV4(
                clip_profile=ClipProfile.MINI_LESSON, reviews=(_global_review(candidate),)
            ),
            candidates=(candidate,),
            boundary_reviews=(boundary,),
            transcript=transcript,
            profile=ClipProfile.MINI_LESSON,
            top_n=15,
            validation_contract=CURRENT_SEMANTIC_VALIDATION,
        )
    assert boundary.model_dump_json() == original_boundary


@pytest.mark.parametrize("size", [2, 3])
def test_quality_contract_rejects_duplicate_cycles_with_valid_wire(size):
    transcript = _transcript()
    candidates = []
    for i in range(size):
        raw = _candidate().model_dump(mode="json")
        raw["candidate_id"] = f"mini_candidate_{i}"
        candidates.append(ChainCandidateV4.model_validate_json(json.dumps(raw)))
    reviews = []
    for i, candidate in enumerate(candidates):
        raw = _global_review(candidate).model_dump(mode="json")
        raw.update(
            duplicate_of=candidates[(i + 1) % size].candidate_id,
            duplicate_group_id="duplicate_group",
            quality_flags=["duplicate_weaker"],
        )
        reviews.append(CandidateGlobalReviewV4.model_validate_json(json.dumps(raw)))
    output = GlobalReviewOutputV4(clip_profile=ClipProfile.MINI_LESSON, reviews=tuple(reviews))
    kwargs = dict(
        candidates=tuple(candidates),
        boundary_reviews=tuple(_boundary_review(c) for c in candidates),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert len(validate_profile_global_review_v4(output, **kwargs).rejected) == size
    with pytest.raises(ValueError, match="representative"):
        validate_profile_global_review_v4(
            output, **kwargs, validation_contract=CURRENT_SEMANTIC_VALIDATION
        )


@pytest.mark.parametrize(
    "disposition",
    ["auto", "manual", "blocked", "top_n", "low_score", "quality", "content", "weak", "missing"],
)
def test_quality_contract_checks_representatives_before_top_n(disposition):
    transcript = _transcript()
    candidates = []
    for i in range(3):
        raw = _candidate().model_dump(mode="json")
        raw["candidate_id"] = f"candidate_{i}"
        candidates.append(ChainCandidateV4.model_validate_json(json.dumps(raw)))
    raw = _global_review(candidates[0]).model_dump(mode="json")
    raw.update(
        duplicate_of=(
            "missing_candidate" if disposition == "missing" else candidates[1].candidate_id
        ),
        duplicate_group_id="duplicate_group",
        quality_flags=["duplicate_weaker"],
    )
    weaker = CandidateGlobalReviewV4.model_validate_json(json.dumps(raw))
    representative = _global_review(
        candidates[1],
        score=75 if disposition == "low_score" else 80,
        publish_status=(
            PublishStatusV4(disposition)
            if disposition in ("manual", "blocked")
            else PublishStatusV4.AUTO
        ),
        quality_flags=(QualityFlagV4.TOPIC_MIXED,) if disposition == "quality" else (),
    )
    raw = representative.model_dump(mode="json")
    if disposition == "content":
        raw["content_decision"] = "drop"
    elif disposition == "weak":
        raw.update(
            duplicate_of=candidates[2].candidate_id,
            duplicate_group_id="duplicate_group",
            quality_flags=["duplicate_weaker"],
        )
    representative = CandidateGlobalReviewV4.model_validate_json(json.dumps(raw))
    output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=(weaker, representative, _global_review(candidates[2], score=90)),
    )
    kwargs = dict(
        candidates=tuple(candidates),
        boundary_reviews=tuple(_boundary_review(c) for c in candidates),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=1 if disposition == "top_n" else 15,
        validation_contract=CURRENT_SEMANTIC_VALIDATION,
    )
    output = GlobalReviewOutputV4.model_validate_json(output.model_dump_json())
    if disposition in ("low_score", "quality", "content", "weak", "missing"):
        with pytest.raises(ValueError, match=r"representative|reference a candidate"):
            validate_profile_global_review_v4(output, **kwargs)
    else:
        result = validate_profile_global_review_v4(output, **kwargs)
        assert len(result.rejected) == 1
        assert len(result.top_n_excluded) == (1 if disposition == "top_n" else 0)


@pytest.mark.parametrize(
    "profile,duration,valid",
    [
        (ClipProfile.SHORT_HIGHLIGHT, 44, False),
        (ClipProfile.SHORT_HIGHLIGHT, 45, True),
        (ClipProfile.SHORT_HIGHLIGHT, 90, True),
        (ClipProfile.SHORT_HIGHLIGHT, 91, False),
        (ClipProfile.MINI_LESSON, 89, False),
        (ClipProfile.MINI_LESSON, 90, True),
        (ClipProfile.MINI_LESSON, 300, True),
        (ClipProfile.MINI_LESSON, 301, False),
    ],
)
@pytest.mark.parametrize("score", [75, 76])
@pytest.mark.parametrize("publish_status", list(PublishStatusV4))
def test_quality_contract_preserves_duration_score_and_publication_gates(
    profile, duration, valid, score, publish_status
):
    candidate = _candidate(profile, start_cue_id=1, end_cue_id=duration)
    boundary = BoundaryReviewV4.model_validate_json(_boundary_review(candidate).model_dump_json())
    output = GlobalReviewOutputV4.model_validate_json(
        GlobalReviewOutputV4(
            clip_profile=profile,
            reviews=(_global_review(candidate, score=score, publish_status=publish_status),),
        ).model_dump_json()
    )
    kwargs = dict(
        candidates=(candidate,),
        boundary_reviews=(boundary,),
        transcript=_transcript(),
        profile=profile,
        top_n=15,
        validation_contract=CURRENT_SEMANTIC_VALIDATION,
    )
    if not valid:
        with pytest.raises(ValueError, match="duration"):
            validate_profile_global_review_v4(output, **kwargs)
        return
    result = validate_profile_global_review_v4(output, **kwargs)
    assert len(result.selected) == int(score > 75 and publish_status == PublishStatusV4.AUTO)
    assert len(result.rejected) == int(score <= 75)
    assert len(result.manual_review) == int(score > 75 and publish_status == PublishStatusV4.MANUAL)
    assert len(result.blocked) == int(score > 75 and publish_status == PublishStatusV4.BLOCKED)


def test_quality_contract_consistent_incomplete_boundary_is_rejected_not_autopublished():
    transcript = _transcript()
    candidate = _candidate()
    raw = _boundary_review(candidate).model_dump(mode="json")
    raw.update(opening_complete=False, quality_flags=["context_dependent_opening"])
    boundary = BoundaryReviewV4.model_validate_json(json.dumps(raw))
    assert validate_boundary_review_v4(
        boundary,
        candidate=candidate,
        transcript=transcript,
        validation_contract=CURRENT_SEMANTIC_VALIDATION,
    )
    result = validate_profile_global_review_v4(
        GlobalReviewOutputV4(
            clip_profile=ClipProfile.MINI_LESSON, reviews=(_global_review(candidate),)
        ),
        candidates=(candidate,),
        boundary_reviews=(boundary,),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
        validation_contract=CURRENT_SEMANTIC_VALIDATION,
    )
    assert not result.selected
    assert len(result.rejected) == 1


@pytest.mark.parametrize("repair_is_valid", [True, False])
@pytest.mark.parametrize("schema_invalid", [True, False])
def test_v4_openai_mixed_schema_quality_errors_get_one_complete_repair(
    repair_is_valid, schema_invalid
):
    from types import SimpleNamespace

    from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt
    from liveclip.providers.llm.structured import (
        OpenAIStructuredLLMProvider,
        StructuredProviderError,
    )
    from liveclip.providers.openai_retry import OpenAIRetryPolicy

    candidate = _candidate()
    valid = _boundary_review(candidate).model_dump(mode="json")
    invalid = {
        **valid,
        "opening_complete": False,
        "ending_complete": False,
        "candidate_id": "wrong",
    }
    if schema_invalid:
        invalid.pop("review_reason")
    else:
        BoundaryReviewV4.model_validate_json(json.dumps(invalid))
    calls = []

    class Responses:
        @property
        def with_raw_response(self):
            return self

        def parse(self, **kwargs):
            calls.append(kwargs)
            assert len(calls) <= 2
            data = invalid if len(calls) == 1 or not repair_is_valid else valid

            def parse_body():
                parsed = BoundaryReviewV4.model_validate_json(json.dumps(data))
                return SimpleNamespace(
                    status="completed",
                    output_parsed=parsed,
                    output=(
                        SimpleNamespace(
                            type="message", content=(SimpleNamespace(type="output_text"),)
                        ),
                    ),
                    usage=None,
                    _request_id="test-only",
                    model="fixture",
                )

            return SimpleNamespace(
                text=json.dumps(
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": json.dumps(data)}],
                            }
                        ],
                    }
                ),
                parse=parse_body,
            )

    prompt = load_semantic_topic_chain_prompt("boundary_review", "general", ClipProfile.MINI_LESSON)
    provider = OpenAIStructuredLLMProvider(
        prompts=prompt,
        model_name="fixture",
        api_key=None,
        timeout_seconds=30,
        retry_policy=OpenAIRetryPolicy(max_retries=0),
        client=SimpleNamespace(responses=Responses()),
    )
    request = {
        "schema_version": "4",
        "stage": "boundary_review",
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
        "candidate": candidate.model_dump(mode="json"),
        "clip_profile": "mini_lesson",
        "cues": _boundary_request(candidate)["cues"],
    }
    original_request = json.dumps(request, sort_keys=True)
    if repair_is_valid:
        result = provider.generate(
            subject_id="test-only", payload=request, response_model=BoundaryReviewV4
        )
        assert result.repaired
        assert result.output == BoundaryReviewV4.model_validate_json(json.dumps(valid))
        assert len(result.call_records) == 2
    else:
        with pytest.raises(StructuredProviderError) as error:
            provider.generate(
                subject_id="test-only", payload=request, response_model=BoundaryReviewV4
            )
        assert error.value.code == "STRUCTURED_OUTPUT_INVALID"
        assert len(error.value.call_records) == 2
    assert json.dumps(request, sort_keys=True) == original_request
    assert len(calls) == 2
    repair_text = calls[1]["input"][0]["content"][0]["text"]
    assert "review_reason" in repair_text
    assert "context_dependent_opening" in repair_text
    assert "incomplete_ending" in repair_text
    assert "candidate_id does not match its input" in repair_text
    assert "immutable_request" in repair_text
    assert candidate.candidate_id in repair_text


def test_current_contract_repair_does_not_truncate_combined_errors():
    from liveclip.providers.llm.structured import StructuredProviderError, _schema_repair_payload

    errors = [f"reviews.{index}.title: Field required [missing]" for index in range(250)]
    failure = StructuredProviderError(
        "STRUCTURED_OUTPUT_INVALID",
        (),
        repair_attempts=(
            {
                "phase": "initial",
                "validation_errors": errors,
                "invalid_output": {},
            },
        ),
    )
    payload = _schema_repair_payload(
        {"stage": "global_review", "validation_contract": CURRENT_SEMANTIC_VALIDATION},
        failure,
    )
    assert payload["validation_errors"] == errors


@pytest.mark.parametrize("review_count", [7, 20])
def test_current_contract_repair_retains_every_available_schema_error(review_count):
    from pydantic import ValidationError

    from liveclip.providers.llm.structured import (
        StructuredProviderError,
        _schema_repair_payload,
        _structured_invalid_attempt,
    )

    raw = {
        "clip_profile": "mini_lesson",
        "reviews": [
            {"candidate_id": f"candidate_{index}", "clip_profile": "mini_lesson"}
            for index in range(review_count)
        ],
    }
    with pytest.raises(ValidationError) as failure:
        GlobalReviewOutputV4.model_validate_json(json.dumps(raw))
    expected = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']} [{item['type']}]"
        for item in failure.value.errors(include_input=False, include_url=False)
    ]
    assert len(expected) > (100 if review_count == 7 else 200)
    attempt = _structured_invalid_attempt(
        phase="initial",
        raw_output=json.dumps(raw),
        error=failure.value,
        complete_errors=True,
    )
    error = StructuredProviderError("STRUCTURED_OUTPUT_INVALID", (), repair_attempts=(attempt,))
    repaired = _schema_repair_payload(
        {"stage": "global_review", "validation_contract": CURRENT_SEMANTIC_VALIDATION},
        error,
    )
    assert set(expected).issubset(repaired["validation_errors"])
    assert repaired["invalid_output"] == raw


@pytest.mark.parametrize("provider_kind", ["openai", "codex"])
def test_current_contract_oversized_repair_starts_no_provider_call(monkeypatch, provider_kind):
    import liveclip.providers.llm.codex as codex_module
    import liveclip.providers.llm.structured as structured_module
    from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt
    from liveclip.pipeline.semantic_global import SemanticGlobalConfig
    from liveclip.providers.openai_retry import OpenAIRetryPolicy

    def forbidden(*args, **kwargs):
        pytest.fail("over-budget repair must not start a network request or process")

    monkeypatch.setattr(structured_module, "run_cancellable_process", forbidden)
    monkeypatch.setattr(codex_module, "resolve_codex_executable", lambda executable: executable)
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda executable: "fixture")
    prompts = load_semantic_topic_chain_prompt(
        "boundary_review", "general", ClipProfile.MINI_LESSON
    )
    budget = SemanticGlobalConfig(model_context_tokens=16_000, output_reserve_tokens=2_000)
    if provider_kind == "openai":

        class ForbiddenClient:
            @property
            def responses(self):
                forbidden()

        provider = structured_module.OpenAIStructuredLLMProvider(
            prompts=prompts,
            model_name="fixture",
            api_key=None,
            timeout_seconds=30,
            retry_policy=OpenAIRetryPolicy(max_retries=0),
            client=ForbiddenClient(),
            semantic_budget=budget,
        )
    else:
        provider = structured_module.CodexStructuredLLMProvider(
            prompts=prompts,
            model_name="fixture",
            codex_executable="fixture-codex",
            timeout_seconds=30,
            contract_version="fixture",
            semantic_budget=budget,
        )
    payload = {
        "repair_only": True,
        "immutable_request": {"validation_contract": CURRENT_SEMANTIC_VALIDATION},
        "invalid_output": {"untrusted_text": "separate evidence tokens " * 20_000},
    }
    with pytest.raises(structured_module.StructuredProviderError) as failure:
        provider.repair(
            subject_id="fixture",
            payload=payload,
            response_model=BoundaryReviewV4,
            validation_errors=("complete synthetic error",),
        )
    assert failure.value.code == "STRUCTURED_REPAIR_BUDGET_EXCEEDED"
    assert failure.value.call_records == ()
    audit = failure.value.repair_attempts[0]
    assert audit["repair_call_executed"] is False
    assert audit["estimated_total_tokens"] > audit["budget_tokens"]


def _mixed_global_cross_field_errors(raw, case):
    if case in {"many_schema_100", "many_schema_200"}:
        from pydantic import ValidationError

        raw["reviews"] = [
            {"candidate_id": f"missing_{index}", "clip_profile": "mini_lesson"}
            for index in range(7 if case == "many_schema_100" else 20)
        ]
        with pytest.raises(ValidationError) as failure:
            GlobalReviewOutputV4.model_validate_json(json.dumps(raw))
        return [".".join(str(part) for part in item["loc"]) for item in failure.value.errors()]
    review = raw["reviews"][0]
    if case == "cycle":
        return ["representative"]
    # Keep the second candidate a valid representative so graph validation
    # cannot mask the missing wire cross-field errors.
    raw["reviews"][1].update(duplicate_of=None, duplicate_group_id=None, quality_flags=[])
    review.update(total_score=1, quality_flags=[], variant_of="other_variant")
    markers = [
        "total_score must equal the deterministic score dimensions",
        "duplicate_of and duplicate_weaker must describe the same weaker duplicate",
        "variant relation requires both fields",
    ]
    if case == "missing_group":
        review["duplicate_group_id"] = None
        markers.append("a weaker duplicate requires duplicate_group_id audit provenance")
    if case == "wrong_scorecard":
        review["scores"] = _global_review(
            _candidate(ClipProfile.SHORT_HIGHLIGHT, end_cue_id=60)
        ).model_dump(mode="json")["scores"]
        markers.append("mini_lesson requires the mini-lesson scorecard")
    # Actual wire loading must reject the Schema-invalid response, and still
    # reject the cross-field defects after only its missing field is restored.
    with pytest.raises(ValueError):
        GlobalReviewOutputV4.model_validate_json(json.dumps(raw))
    restored = json.loads(json.dumps(raw))
    restored["reviews"][0]["title"] = "Synthetic title"
    with pytest.raises(ValueError, match="total_score"):
        GlobalReviewOutputV4.model_validate_json(json.dumps(restored))
    return markers


@pytest.mark.parametrize(
    "changes,marker",
    [
        ({"duplicate_of": "same"}, "a duplicate cannot reference itself"),
        (
            {"duplicate_of": None, "quality_flags": ["duplicate_weaker"]},
            "duplicate_of and duplicate_weaker",
        ),
        (
            {"interruption_review": [{"severity": "material", "blocking": False}]},
            "unresolved material interruption must be blocking",
        ),
        (
            {"interruption_review": [{"severity": "none", "evidence_cue_ids": [1]}]},
            "none interruption cannot be blocking",
        ),
    ],
)
def test_v4_partial_cross_field_errors_are_independent_of_missing_schema_fields(changes, marker):
    from liveclip.pipeline.semantic_profiles import quality_preflight_errors_v4

    raw = {"clip_profile": "mini_lesson", "reviews": [{"candidate_id": "same", **changes}]}
    with pytest.raises(ValueError):
        GlobalReviewOutputV4.model_validate_json(json.dumps(raw))
    request = {"stage": "global_review", "validation_contract": CURRENT_SEMANTIC_VALIDATION}
    assert any(marker in error for error in quality_preflight_errors_v4(request, raw))
    assert quality_preflight_errors_v4({"stage": "global_review"}, raw) == []


def test_v4_partial_cross_field_checks_do_not_infer_missing_facts():
    from liveclip.pipeline.semantic_profiles import global_cross_field_errors_v4

    for raw in (
        {"duplicate_of": "other"},
        {"quality_flags": ["duplicate_weaker"]},
        {"variant_of": "other"},
        {"variant_relationship": "short_version_of"},
        {"total_score": 1, "scores": {"central_objective_clarity": 20}},
        {"interruption_review": [{"severity": "material"}]},
    ):
        assert global_cross_field_errors_v4(raw) == []


@pytest.mark.parametrize("decision", ["keep", "drop"])
def test_v4_partial_boundary_collects_proposal_pair_and_interruption_errors(decision):
    from liveclip.pipeline.semantic_profiles import quality_preflight_errors_v4

    raw = _boundary_review(_candidate()).model_dump(mode="json")
    raw.update(
        content_decision=decision,
        proposed_start_cue_id=None,
        interruption_review=[{"severity": "material", "blocking": False}],
    )
    raw.pop("review_reason")
    with pytest.raises(ValueError):
        BoundaryReviewV4.model_validate_json(json.dumps(raw))
    errors = quality_preflight_errors_v4(
        {"stage": "boundary_review", "validation_contract": CURRENT_SEMANTIC_VALIDATION}, raw
    )
    assert "boundary proposal requires both cue IDs" in errors
    assert "unresolved material interruption must be blocking" in errors
    assert ("kept or repaired boundary requires one concrete interval" in errors) == (
        decision == "keep"
    )


@pytest.mark.parametrize(
    "case",
    [
        "cycle",
        "cross_fields",
        "missing_group",
        "wrong_scorecard",
        "many_schema_100",
        "many_schema_200",
    ],
)
@pytest.mark.parametrize("repair_is_valid", [True, False])
def test_v4_actual_openai_sdk_preserves_nested_schema_and_duplicate_errors(repair_is_valid, case):
    import httpx
    from openai import OpenAI

    from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt
    from liveclip.providers.llm.structured import (
        OpenAIStructuredLLMProvider,
        StructuredProviderError,
    )
    from liveclip.providers.openai_retry import OpenAIRetryPolicy

    candidates = [
        _candidate().model_copy(update={"candidate_id": f"candidate_{i}"}) for i in range(2)
    ]
    valid = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=tuple(_global_review(candidate) for candidate in candidates),
    ).model_dump(mode="json")
    invalid = json.loads(json.dumps(valid))
    for index, review in enumerate(invalid["reviews"]):
        review.update(
            duplicate_of=candidates[1 - index].candidate_id,
            duplicate_group_id="cycle",
            quality_flags=["duplicate_weaker"],
        )
    invalid["reviews"][0].pop("title")
    markers = _mixed_global_cross_field_errors(invalid, case)
    calls = []

    def transport(request):
        calls.append(json.loads(request.content))
        assert len(calls) <= 2
        data = invalid if len(calls) == 1 or not repair_is_valid else valid
        return httpx.Response(
            200,
            headers={"x-request-id": f"fixture-{len(calls)}"},
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "fixture",
                "output": [
                    {
                        "id": "msg_fixture",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": json.dumps(data), "annotations": []}
                        ],
                    }
                ],
                "parallel_tool_calls": False,
                "tools": [],
                "tool_choice": "none",
            },
        )

    request = {
        "schema_version": "4",
        "stage": "global_review",
        "clip_profile": "mini_lesson",
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
        "score_threshold_exclusive": 75,
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "boundary_reviews": [_boundary_review(c).model_dump(mode="json") for c in candidates],
    }
    with OpenAI(
        api_key="test-only-not-a-credential",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        provider = OpenAIStructuredLLMProvider(
            prompts=load_semantic_topic_chain_prompt(
                "global_review", "general", ClipProfile.MINI_LESSON
            ),
            model_name="fixture",
            api_key=None,
            timeout_seconds=30,
            retry_policy=OpenAIRetryPolicy(max_retries=0),
            client=client,
        )
        if repair_is_valid:
            result = provider.generate(
                subject_id="fixture", payload=request, response_model=GlobalReviewOutputV4
            )
            assert result.repaired and len(result.call_records) == 2
            assert result.output.model_dump(mode="json") == valid
        else:
            with pytest.raises(StructuredProviderError) as error:
                provider.generate(
                    subject_id="fixture", payload=request, response_model=GlobalReviewOutputV4
                )
            assert len(error.value.call_records) == 2
    assert len(calls) == 2
    repair_text = calls[1]["input"][0]["content"][0]["text"]
    assert "title" in repair_text
    assert all(marker in repair_text for marker in markers)
    assert "immutable_request" in repair_text


@pytest.mark.parametrize("score,declared,representative_error", [(75, 76, True), (76, 75, False)])
def test_v4_raw_preflight_uses_validated_score_dimensions(score, declared, representative_error):
    from liveclip.pipeline.semantic_profiles import quality_preflight_errors_v4

    first, second = [
        _candidate().model_copy(update={"candidate_id": f"candidate_{i}"}) for i in range(2)
    ]
    weak = _global_review(first).model_dump(mode="json")
    weak.update(
        duplicate_of=second.candidate_id,
        duplicate_group_id="group",
        quality_flags=["duplicate_weaker"],
    )
    representative = _global_review(second, score=score).model_dump(mode="json")
    representative["total_score"] = declared
    errors = quality_preflight_errors_v4(
        {
            "validation_contract": CURRENT_SEMANTIC_VALIDATION,
            "stage": "global_review",
            "clip_profile": "mini_lesson",
            "score_threshold_exclusive": 75,
        },
        {"clip_profile": "mini_lesson", "reviews": [weak, representative]},
    )
    assert any("representative" in error for error in errors) == representative_error


@pytest.mark.parametrize("output_profile", [None, "short_highlight", []])
@pytest.mark.parametrize("duration", [89, 90])
def test_v4_partial_profile_uses_authoritative_duration(output_profile, duration):
    from liveclip.pipeline.semantic_profiles import quality_preflight_errors_v4

    candidate = _candidate()
    raw = _boundary_review(candidate).model_dump(mode="json")
    raw.update(content_decision="repair_boundary", proposed_end_cue_id=50 + duration)
    if output_profile is None:
        raw.pop("clip_profile")
    else:
        raw["clip_profile"] = output_profile
    errors = quality_preflight_errors_v4(_boundary_request(candidate), raw)
    assert any("duration" in error for error in errors) == (duration == 89)


@pytest.mark.parametrize("decision", [None, "invalid", []])
def test_v4_unknown_decision_does_not_invent_retained_obligation(decision):
    from liveclip.pipeline.semantic_profiles import quality_preflight_errors_v4

    candidate = _candidate()
    raw = _boundary_review(candidate).model_dump(mode="json")
    raw.update(
        proposed_start_cue_id=None,
        proposed_end_cue_id=None,
        continuous_source_interval=False,
        quality_flags=["multi_interval_edit"],
    )
    if decision is None:
        raw.pop("content_decision")
    else:
        raw["content_decision"] = decision
    assert quality_preflight_errors_v4(_boundary_request(candidate), raw) == []
    raw["evidence"]["opening_cue_ids"] = [999]
    assert any(
        "evidence.opening" in e
        for e in quality_preflight_errors_v4(_boundary_request(candidate), raw)
    )


def test_v4_invalid_id_type_does_not_hide_known_unknown_or_duplicate_ids():
    from liveclip.pipeline.semantic_profiles import quality_preflight_errors_v4

    candidate = _candidate()
    request = {
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
        "stage": "global_review",
        "clip_profile": "mini_lesson",
        "candidates": [candidate.model_dump(mode="json")],
    }
    output = {
        "clip_profile": "mini_lesson",
        "reviews": [
            {"candidate_id": None},
            {"candidate_id": "unknown"},
            {"candidate_id": "unknown"},
        ],
    }
    errors = quality_preflight_errors_v4(request, output)
    assert any("unknown candidate" in e for e in errors)
    assert any("duplicate candidate" in e for e in errors)
    assert not any("exactly once" in e for e in errors)


def _boundary_request(candidate, transcript=None):
    from liveclip.pipeline.semantic_profiles import TopicChainV4, build_boundary_review_payload_v4

    chain = TopicChainV4(
        topic_chain_id=candidate.topic_chain_id,
        fragment_ids=candidate.source_fragment_ids,
        central_question=candidate.central_question,
        learning_outcome=candidate.learning_outcome,
        topic_outline=("Explain and demonstrate.",),
        source_start_cue_id=candidate.start_cue_id,
        source_end_cue_id=candidate.end_cue_id,
        left_closed=True,
        right_closed=True,
        chain_status=TopicChainStatusV4.CLOSED,
    )
    return {
        **build_boundary_review_payload_v4(
            candidate,
            chain=chain,
            transcript=transcript or _transcript(),
            source_hash="a" * 64,
            prompt_hash="b" * 64,
            discovery_evidence=(),
            link_reviews=(),
        ),
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
    }


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"proposed_end_cue_id": 999}, "interval"),
        ({"proposed_start_cue_id": 320, "proposed_end_cue_id": 51}, "reversed"),
        ({"proposed_end_cue_id": 139}, "duration"),
        (
            {"continuous_source_interval": False, "quality_flags": ["multi_interval_edit"]},
            "continuous",
        ),
        (
            {"evidence": {"opening_cue_ids": [999], "core_cue_ids": [52], "ending_cue_ids": [320]}},
            "evidence.opening",
        ),
    ],
)
def test_v4_preflight_collects_boundary_references_alongside_schema_errors(changes, expected):
    from liveclip.providers.llm.structured import StructuredProviderError, _schema_repair_payload

    candidate = _candidate()
    invalid = _boundary_review(candidate).model_dump(mode="json")
    invalid.update(changes)
    invalid.pop("review_reason")
    error = StructuredProviderError(
        "STRUCTURED_OUTPUT_INVALID",
        (),
        repair_attempts=(
            {
                "phase": "initial",
                "invalid_output": invalid,
                "validation_errors": ["review_reason: missing"],
            },
        ),
    )
    repair = _schema_repair_payload(_boundary_request(candidate), error)
    joined = "\n".join(repair["validation_errors"])
    assert "review_reason" in joined and expected in joined
    # The same field constraints remain enforced by the strict final validator.
    raw = {**invalid, "review_reason": "Test-only reason."}
    from pydantic import ValidationError

    with pytest.raises((ValueError, ValidationError)):
        review = BoundaryReviewV4.model_validate_json(json.dumps(raw))
        validate_boundary_review_v4(
            review,
            candidate=candidate,
            transcript=_transcript(),
            validation_contract=CURRENT_SEMANTIC_VALIDATION,
        )


@pytest.mark.parametrize("duration", [90, 300])
def test_v4_boundary_preflight_accepts_exact_limits_background_and_drop(duration):
    from liveclip.pipeline.semantic_profiles import quality_preflight_errors_v4

    candidate = _candidate(start_cue_id=101, end_cue_id=100 + duration)
    raw = _boundary_review(candidate).model_dump(mode="json")
    raw["evidence"]["opening_cue_ids"] = [71]  # In local background, not the clip.
    request = _boundary_request(candidate)
    assert quality_preflight_errors_v4(request, raw) == []
    raw.update(
        content_decision="drop",
        proposed_start_cue_id=None,
        proposed_end_cue_id=None,
        continuous_source_interval=False,
        quality_flags=["multi_interval_edit"],
    )
    assert quality_preflight_errors_v4(request, raw) == []
    review = BoundaryReviewV4.model_validate_json(json.dumps(raw))
    assert (
        validate_boundary_review_v4(
            review,
            candidate=candidate,
            transcript=_transcript(),
            validation_contract=CURRENT_SEMANTIC_VALIDATION,
        )
        == review
    )
    raw["evidence"]["opening_cue_ids"] = [999]
    assert any("evidence.opening" in e for e in quality_preflight_errors_v4(request, raw))


def test_v4_global_evidence_is_candidate_local_and_boundary_context_stays_original():
    from liveclip.pipeline.semantic_profiles import (
        build_global_review_payload_v4,
        quality_preflight_errors_v4,
    )

    transcript = _transcript()
    candidates = [
        _candidate(start_cue_id=51, end_cue_id=150),
        _candidate(start_cue_id=351, end_cue_id=450),
    ]
    candidates = [
        ChainCandidateV4.model_validate_json(
            json.dumps(
                {
                    **c.model_dump(mode="json"),
                    "candidate_id": f"candidate_{i}",
                }
            )
        )
        for i, c in enumerate(candidates)
    ]
    boundaries = tuple(_boundary_review(c) for c in candidates)
    raw = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON, reviews=tuple(_global_review(c) for c in candidates)
    ).model_dump(mode="json")
    request = {
        **build_global_review_payload_v4(
            candidates,
            boundary_reviews=boundaries,
            topic_chains=(),
            transcript=transcript,
            source_hash="a" * 64,
            profile=ClipProfile.MINI_LESSON,
            prompt_hash="b" * 64,
            top_n=15,
        ),
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
    }
    assert quality_preflight_errors_v4(request, raw) == []
    raw["reviews"][0]["evidence_cue_ids"] = [400]
    assert any("out-of-context" in e for e in quality_preflight_errors_v4(request, raw))
    raw["reviews"][0]["evidence_cue_ids"] = [51]
    interruption = InterruptionReviewV4(
        type="other",
        severity=InterruptionSeverityV4.MINOR,
        blocking=False,
        evidence_cue_ids=(400,),
        description="Test-only unrelated reference.",
    )
    raw["reviews"][0]["interruption_review"] = [interruption.model_dump(mode="json")]
    assert any("interruption_review" in e for e in quality_preflight_errors_v4(request, raw))
    output = GlobalReviewOutputV4.model_validate_json(json.dumps(raw))
    kwargs = dict(
        candidates=candidates,
        boundary_reviews=boundaries,
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    validate_profile_global_review_v4(output, **kwargs)  # Historical behavior unchanged.
    with pytest.raises(ValueError, match="interruption_review"):
        validate_profile_global_review_v4(
            output, **kwargs, validation_contract=CURRENT_SEMANTIC_VALIDATION
        )


def test_v4_repaired_global_context_does_not_restrict_original_boundary_evidence():
    from liveclip.pipeline.semantic_profiles import (
        build_global_review_payload_v4,
        quality_preflight_errors_v4,
    )

    candidate = _candidate(start_cue_id=51, end_cue_id=150)
    boundary_raw = _boundary_review(candidate).model_dump(mode="json")
    boundary_raw.update(
        content_decision="repair_boundary", proposed_start_cue_id=81, proposed_end_cue_id=180
    )
    boundary_raw["evidence"]["opening_cue_ids"] = [21]
    boundary = BoundaryReviewV4.model_validate_json(json.dumps(boundary_raw))
    review_raw = _global_review(candidate).model_dump(mode="json")
    review_raw.update(start_cue_id=81, end_cue_id=180, evidence_cue_ids=[81, 180])
    output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=(CandidateGlobalReviewV4.model_validate_json(json.dumps(review_raw)),),
    )
    request = {
        **build_global_review_payload_v4(
            (candidate,),
            boundary_reviews=(boundary,),
            topic_chains=(),
            transcript=_transcript(),
            source_hash="a" * 64,
            profile=ClipProfile.MINI_LESSON,
            prompt_hash="b" * 64,
            top_n=15,
        ),
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
    }
    assert 21 not in {cue["cue_id"] for cue in request["candidate_contexts"][0]["cues"]}
    assert quality_preflight_errors_v4(request, output.model_dump(mode="json")) == []
    result = validate_profile_global_review_v4(
        output,
        candidates=(candidate,),
        boundary_reviews=(boundary,),
        transcript=_transcript(),
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
        validation_contract=CURRENT_SEMANTIC_VALIDATION,
    )
    assert len(result.selected) == 1


@pytest.mark.parametrize(
    "case",
    [
        "cycle",
        "cross_fields",
        "missing_group",
        "wrong_scorecard",
        "many_schema_100",
        "many_schema_200",
    ],
)
@pytest.mark.parametrize("repair_is_valid", [True, False])
def test_v4_codex_mixed_schema_duplicate_errors_get_one_repair(monkeypatch, repair_is_valid, case):
    import subprocess

    import liveclip.providers.llm.codex as codex_module
    import liveclip.providers.llm.structured as structured_module
    from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt

    candidates = [
        ChainCandidateV4.model_validate_json(
            json.dumps(
                {
                    **_candidate().model_dump(mode="json"),
                    "candidate_id": f"candidate_{i}",
                }
            )
        )
        for i in range(2)
    ]
    valid = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON, reviews=tuple(_global_review(c) for c in candidates)
    ).model_dump(mode="json")
    invalid = json.loads(json.dumps(valid))
    for i, review in enumerate(invalid["reviews"]):
        review.update(
            duplicate_of=candidates[1 - i].candidate_id,
            duplicate_group_id="group",
            quality_flags=["duplicate_weaker"],
        )
    invalid["reviews"][0].pop("title")
    markers = _mixed_global_cross_field_errors(invalid, case)
    prompts, schemas = [], []
    contract = "codex-cli-editorial-v2.0.147.0." + "a" * 64
    monkeypatch.setattr(codex_module, "codex_cli_contract_version", lambda _: contract)
    monkeypatch.setattr(structured_module, "codex_cli_contract_version", lambda _: contract)

    def fake_run(argv, **kwargs):
        prompts.append(kwargs["stdin_stream"].read().decode())
        assert len(prompts) <= 2
        schemas.append(json.loads(Path(argv[argv.index("--output-schema") + 1]).read_text()))
        result_path = Path(argv[argv.index("--output-last-message") + 1])
        result_path.write_text(
            json.dumps(valid if len(prompts) == 2 and repair_is_valid else invalid)
        )
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(structured_module, "run_cancellable_process", fake_run)
    provider = structured_module.CodexStructuredLLMProvider(
        prompts=load_semantic_topic_chain_prompt(
            "global_review", "general", ClipProfile.MINI_LESSON
        ),
        model_name="fixture",
        codex_executable="/usr/bin/true",
        timeout_seconds=30,
        contract_version=contract,
    )
    request = {
        "schema_version": "4",
        "stage": "global_review",
        "clip_profile": "mini_lesson",
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
        "score_threshold_exclusive": 75,
        "candidates": [c.model_dump(mode="json") for c in candidates],
        "boundary_reviews": [_boundary_review(c).model_dump(mode="json") for c in candidates],
    }
    before = json.dumps(request, sort_keys=True)
    if repair_is_valid:
        result = provider.generate(
            subject_id="fixture", payload=request, response_model=GlobalReviewOutputV4
        )
        assert result.repaired and result.output.model_dump(mode="json") == valid
        assert len(result.call_records) == 2
    else:
        with pytest.raises(structured_module.StructuredProviderError) as error:
            provider.generate(
                subject_id="fixture", payload=request, response_model=GlobalReviewOutputV4
            )
        assert len(error.value.call_records) == 2
    assert len(prompts) == 2
    for marker in ("title", *markers, CURRENT_SEMANTIC_VALIDATION, "immutable_request"):
        assert marker in prompts[1]
    assert json.dumps(request, sort_keys=True) == before
    assert (
        schemas
        == [
            structured_module._strict_codex_schema(
                GlobalReviewOutputV4.model_json_schema(mode="validation")
            )
        ]
        * 2
    )


@pytest.mark.parametrize(
    "failure_location",
    [
        "provider_repair",
        "stage_only_reference",
        "repair_budget",
        "initial_incomplete",
        "repair_incomplete",
        "initial_multipart",
        "repair_multipart",
        "completed_multipart",
        "schema_multipart",
        "initial_incomplete_schema",
        "repair_incomplete_schema",
        "initial_incomplete_schema_multipart",
        "repair_incomplete_schema_multipart",
        "initial_refusal_schema",
        "repair_refusal_schema",
        "initial_unexpected_schema",
        "repair_unexpected_schema",
        "repair_schema_multipart",
        "initial_refusal_schema_multipart",
        "repair_refusal_schema_multipart",
        "initial_unexpected_schema_multipart",
        "repair_unexpected_schema_multipart",
    ],
)
def test_v4_stage_failure_preserves_sibling_cache_and_spent_repair(
    tmp_path, failure_location, request, monkeypatch
):
    from collections import Counter
    from functools import partial
    from threading import Lock

    import httpx
    from openai import OpenAI

    from liveclip.application.pipeline import LeaseIdentity, PipelineRunConfigV11, StageWork
    from liveclip.application.stage_execution import StageMutationFence
    from liveclip.bootstrap import pipeline_config_from_settings
    from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt
    from liveclip.config.settings import Settings
    from liveclip.domain.state_transitions import PipelineStage
    from liveclip.media.artifacts import ArtifactPublicationError
    from liveclip.pipeline.semantic_cache import SemanticStageCacheRecord
    from liveclip.pipeline.semantic_global import SemanticGlobalConfig
    from liveclip.pipeline.stage_handlers import PipelineStageHandlers
    from liveclip.providers.llm.structured import (
        OpenAIStructuredLLMProvider,
        StructuredProviderError,
    )
    from liveclip.providers.openai_retry import OpenAIRetryPolicy

    transcript = _transcript()
    candidates = [
        ChainCandidateV4.model_validate_json(
            json.dumps(
                {
                    **_candidate().model_dump(mode="json"),
                    "candidate_id": f"candidate_{i}",
                }
            )
        )
        for i in range(3)
    ]
    config = pipeline_config_from_settings(
        Settings(_env_file=None, ai_provider="mock"),
        clipping_algorithm="semantic_windowed",
        clip_profile=ClipProfile.MINI_LESSON,
    )
    # This is a V11 compatibility test for the historical V4 cache path.
    legacy = config.model_dump(mode="python")
    legacy.pop("semantic_execution_contract")
    legacy["schema_version"] = "11"
    config = PipelineRunConfigV11.model_validate(legacy)
    work = StageWork(
        task_id="1" * 32,
        stage_run_id="2" * 32,
        run_id="3" * 32,
        project_id="4" * 32,
        stage=PipelineStage.EDIT,
        source_path=tmp_path / "not-read.mp4",
        config=config,
        input_fingerprint="a" * 64,
        generation=1,
        revision_epoch=0,
        already_succeeded=False,
        cancellation_requested=False,
    )
    from datetime import UTC, datetime

    from sqlalchemy import insert, select

    from liveclip.db.assets import AssetReservationError, SqlAlchemyAssetStore
    from liveclip.db.base import Base
    from liveclip.db.engine import create_sqlite_engine
    from liveclip.db.models import (
        AssetRow,
        PipelineRunRow,
        ProjectRow,
        StageRunRow,
        TaskAttemptRow,
        TaskRow,
    )
    from liveclip.db.pipeline_repository import SqlAlchemyPipelineRepository
    from liveclip.db.task_queue import SQLiteTaskQueue, TaskSpec
    from liveclip.domain.state_transitions import ResourceClass, TaskKind

    engine = create_sqlite_engine(tmp_path / "audit.sqlite3", busy_timeout_ms=250)
    request.addfinalizer(engine.dispose)
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        connection.execute(
            insert(ProjectRow).values(
                id=work.project_id,
                name="Synthetic audit",
                source_request_path="/allowed/source.mp4",
                current_generation=1,
                current_pipeline_run_id=work.run_id,
                revision_epoch=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(PipelineRunRow).values(
                id=work.run_id,
                project_id=work.project_id,
                generation=1,
                status="running",
                config_json=config.model_dump(mode="json"),
                config_fingerprint=config.fingerprint,
                progress=0,
                manual_retry_count=0,
                created_at=now,
                updated_at=now,
            )
        )
    with engine.begin() as connection:
        connection.execute(
            insert(StageRunRow).values(
                id=work.stage_run_id,
                pipeline_run_id=work.run_id,
                stage=PipelineStage.EDIT.value,
                ordinal=4,
                status="queued",
            )
        )
    project_dir = tmp_path / work.project_id
    project_dir.mkdir()
    queue = SQLiteTaskQueue(engine, lease_seconds=60, data_dir=tmp_path)
    queue.enqueue(
        TaskSpec(
            kind=TaskKind.STAGE,
            target_id=work.stage_run_id,
            stage_run_id=work.stage_run_id,
            operation_key="synthetic-audit",
            input_fingerprint="d" * 64,
            pipeline_run_id=work.run_id,
            resource_class=ResourceClass.HEAVY,
            expected_generation=1,
            max_retries=0,  # Isolate semantic call counts from production stage retries.
        ),
        now=now,
    )
    claimed = queue.claim(worker_id="fixture", now=now)
    assert claimed is not None
    lease = LeaseIdentity(
        task_id=claimed.task_id, worker_id="fixture", lease_token=claimed.lease_token
    )
    work = work.model_copy(update={"task_id": claimed.task_id})
    assets = SqlAlchemyAssetStore(engine)
    audit_secret = "synthetic-opaque-audit-credential"
    calls, records, lock = Counter(), [], Lock()
    recovered = False

    class RecordingState:
        def record_provider_calls(self, fence, values, *, cache_hit):
            assert fence.project_id == work.project_id and not cache_hit
            records.extend(values)

    handler = PipelineStageHandlers(
        data_dir=tmp_path,
        allowed_media_roots=(tmp_path,),
        assets=assets,
        state=RecordingState(),
        openai_api_key=audit_secret,
    )
    requests = []
    for candidate in candidates:
        payload = _boundary_request(candidate, transcript)
        if failure_location == "stage_only_reference" and candidate != candidates[0]:
            # Fault injection: incomplete request authority, retained final Stage
            # transcript still detects invalidity after the Provider spent repair.
            payload.pop("cues")
        requests.append(
            (
                candidate.candidate_id,
                payload,
                partial(
                    validate_boundary_review_v4,
                    candidate=candidate,
                    transcript=transcript,
                    validation_contract=CURRENT_SEMANTIC_VALIDATION,
                ),
            )
        )

    combined_case = "_schema" in failure_location and failure_location != "schema_multipart"
    combined_initial = combined_case and failure_location.startswith("initial_")
    combined_code = (
        "STRUCTURED_RESPONSE_INCOMPLETE"
        if "incomplete" in failure_location
        else "STRUCTURED_RESPONSE_REFUSED"
        if "refusal" in failure_location
        else "STRUCTURED_UNEXPECTED_OUTPUT"
    )
    expected_parts = {}
    multipart_cases = {
        "initial_multipart",
        "repair_multipart",
        "completed_multipart",
        "schema_multipart",
    }

    if failure_location.endswith("_schema_multipart"):
        multipart_cases.add(failure_location)

    def transport(request):
        body = json.loads(request.content)
        wrapped = body["input"][0]["content"][0]["text"]
        payload = json.loads(wrapped.split("<untrusted_json>")[1].split("</untrusted_json>")[0])
        authority = payload.get("immutable_request", payload)
        identifier = authority["candidate"]["candidate_id"]
        with lock:
            calls[identifier] += 1
            count = calls[identifier]
        candidate = next(c for c in candidates if c.candidate_id == identifier)
        data = _boundary_review(candidate).model_dump(mode="json")
        failing = identifier != candidates[0].candidate_id and not recovered
        response_failure = combined_case and failing and (combined_initial or count == 2)
        multipart = (
            failing
            and failure_location in multipart_cases
            and (not failure_location.startswith("repair_") or count == 2)
        )
        if failing:
            assert count <= 2, "unexpected third implicit semantic call"
            if failure_location not in {
                "initial_incomplete",
                "initial_multipart",
                "completed_multipart",
                "schema_multipart",
            } and (count == 1 or failure_location == "provider_repair"):
                data.update(opening_complete=False)
                data.pop("review_reason")
                if failure_location == "repair_budget":
                    data["oversized_untrusted_text"] = "separate evidence tokens " * 20_000
                data["untrusted_extra"] = {
                    "api_key": "sk-synthetic-private-key",
                    "password": "synthetic-password",
                    "ordinary": audit_secret,
                }
            elif failure_location == "stage_only_reference":
                data.update(content_decision="repair_boundary", proposed_end_cue_id=999)
        if response_failure:
            data.pop("review_reason", None)
        incomplete = failing and (
            failure_location in {"initial_incomplete", "initial_multipart"}
            or (failure_location in {"repair_incomplete", "repair_multipart"} and count == 2)
        )
        incomplete = incomplete or (response_failure and "incomplete" in failure_location)
        if multipart:
            data["opening_complete"] = False
            if "schema" in failure_location:
                data.pop("review_reason", None)
        message = {
            "id": "msg_fixture",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(data), "annotations": []}],
        }
        output = [message]
        if multipart:
            second = {
                **data,
                "review_reason": "distinct multipart second output",
                "opening_complete": True,
                "contains_padding": True,
            }
            if "schema" in failure_location:
                second.pop("opening_complete")
            if failure_location == "schema_multipart":
                second["untrusted_private"] = {
                    "password": "synthetic-password",
                    "api_key": "sk-synthetic-private-key",
                    "ordinary": audit_secret,
                }
            second_part = {"type": "output_text", "text": json.dumps(second), "annotations": []}
            if failure_location.startswith("repair_"):
                output.append(
                    {
                        "id": "reasoning_fixture",
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "synthetic-hidden-reasoning"}],
                    }
                )
                output.append({**message, "id": "msg_second", "content": [second_part]})
            else:
                message["content"].append(second_part)
            with lock:
                expected_parts[identifier] = [
                    {"output_index": i, "content_index": j, "output_text": part["text"]}
                    for i, item in enumerate(output)
                    if item["type"] == "message"
                    for j, part in enumerate(item["content"])
                ]
        if response_failure and "refusal" in failure_location:
            message["content"].append({"type": "refusal", "refusal": "fixture refusal"})
        if response_failure and "unexpected" in failure_location:
            output.append(
                {
                    "type": "function_call",
                    "id": "fc_fixture",
                    "call_id": "fixture_call",
                    "name": "forbidden_fixture",
                    "arguments": "{}",
                    "status": "completed",
                }
            )
        return httpx.Response(
            200,
            headers={
                "x-request-id": f"fixture-{identifier}-{count}",
                "x-private-secret": audit_secret,
            },
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 0,
                "status": "incomplete" if incomplete else "completed",
                "incomplete_details": {"reason": "max_output_tokens"} if incomplete else None,
                "model": "fixture",
                "output": output,
                "parallel_tool_calls": False,
                "tools": [],
                "tool_choice": "none",
            },
        )

    def run(provider, generation):
        current = work.model_copy(update={"generation": generation})
        fence = StageMutationFence(
            lease=lease,
            project_id=work.project_id,
            run_id=work.run_id,
            stage_run_id=work.stage_run_id,
            generation=generation,
        )
        return handler._run_v4_requests(
            current,
            fence=fence,
            project_dir=tmp_path / work.project_id,
            generation_dir=tmp_path / work.project_id / f"runs/g{generation:03d}",
            stage="boundary_review",
            provider=provider,
            response_model=BoundaryReviewV4,
            requests=tuple(requests),
            cancel_requested=lambda: False,
        )

    with OpenAI(
        api_key="test-only-not-a-credential",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(transport)),
    ) as client:
        provider = OpenAIStructuredLLMProvider(
            prompts=load_semantic_topic_chain_prompt(
                "boundary_review", "general", ClipProfile.MINI_LESSON
            ),
            model_name="fixture",
            api_key=None,
            timeout_seconds=30,
            retry_policy=OpenAIRetryPolicy(max_retries=0),
            client=client,
            semantic_budget=(
                SemanticGlobalConfig(model_context_tokens=16_000, output_reserve_tokens=2_000)
                if failure_location == "repair_budget"
                else None
            ),
        )
        with pytest.raises(StructuredProviderError) as failure:
            run(provider, 1)
        expected_code = (
            combined_code
            if combined_case
            else "STRUCTURED_REPAIR_BUDGET_EXCEEDED"
            if failure_location == "repair_budget"
            else "STRUCTURED_RESPONSE_INCOMPLETE"
            if failure_location
            in {"initial_incomplete", "repair_incomplete", "initial_multipart", "repair_multipart"}
            else "STRUCTURED_UNEXPECTED_OUTPUT"
            if failure_location in {"completed_multipart", "schema_multipart"}
            else "STRUCTURED_OUTPUT_INVALID"
        )
        spent_calls = (
            (1 if combined_initial else 2)
            if combined_case
            else 1
            if failure_location
            in {
                "repair_budget",
                "initial_incomplete",
                "initial_multipart",
                "completed_multipart",
                "schema_multipart",
            }
            else 2
        )
        assert failure.value.code == expected_code
        audits = list((tmp_path / work.project_id / "runs/g001/semantic-audit").glob("*.json"))
        assert audits, "failed V4 subjects must leave reloadable immutable repair audit"
        manifest_path = project_dir / failure.value.diagnostic_relative_path
        manifest = json.loads(manifest_path.read_text())
        assert manifest["complete"] is True and len(manifest["failed_subjects"]) == 2
        if manifest_path not in audits:
            audits.append(manifest_path)
        retained_bytes = {path: path.read_bytes() for path in audits}
        for entry in manifest["failed_subjects"]:
            path = project_dir / entry["relative_path"]
            evidence = json.loads(path.read_text())
            encoded = path.read_text()
            assert audit_secret not in encoded and "synthetic-password" not in encoded
            assert "sk-synthetic-private-key" not in encoded
            assert evidence["subject_id"] == entry["subject_id"]
            assert evidence["validation_contract"] == CURRENT_SEMANTIC_VALIDATION
            assert len(evidence["call_ids"]) == spent_calls
            attempts = evidence["provider_attempts"]
            if failure_location not in multipart_cases - {"repair_multipart"}:
                assert any(a["phase"] == "initial" and a["invalid_output"] for a in attempts)
            if failure_location in multipart_cases:
                phase = "repair" if failure_location.startswith("repair_") else "initial"
                record = next(a for a in attempts if a["phase"] == phase)
                assert record["failure_code"] == expected_code
                actual_parts = record["business_output_parts"]
                expected = expected_parts[entry["subject_id"]]
                assert len(actual_parts) == 2
                for actual_part, expected_part in zip(actual_parts, expected, strict=True):
                    assert actual_part["output_index"] == expected_part["output_index"]
                    assert actual_part["content_index"] == expected_part["content_index"]
                    if failure_location == "schema_multipart" or combined_case:
                        parsed = json.loads(expected_part["output_text"])
                        for key in ("untrusted_private", "untrusted_extra"):
                            if key in parsed:
                                parsed[key] = dict.fromkeys(parsed[key], "[REDACTED]")
                        assert json.loads(actual_part["output_text"]) == parsed
                    else:
                        assert actual_part["output_text"] == expected_part["output_text"]
                assert "synthetic-hidden-reasoning" not in encoded
                first_errors = actual_parts[0]["validation_errors"]
                second_errors = actual_parts[1]["validation_errors"]
                assert any("context_dependent_opening" in e for e in first_errors)
                assert any("padded_to_min_duration" in e for e in second_errors)
                if "schema" in failure_location:
                    assert any("review_reason: Field required" in e for e in first_errors)
                    assert any("opening_complete: Field required" in e for e in second_errors)
                for part in actual_parts:
                    prefix = f"output[{part['output_index']}].content[{part['content_index']}]: "
                    assert all(
                        prefix + e in record["validation_errors"] for e in part["validation_errors"]
                    )
            elif combined_case:
                phase = "initial" if combined_initial else "repair"
                response_attempt = next(a for a in attempts if a["phase"] == phase)
                assert response_attempt["failure_code"] == expected_code
                assert "review_reason" not in response_attempt["invalid_output"]
                assert any(
                    "review_reason" in error for error in response_attempt["validation_errors"]
                )
            elif failure_location in {"initial_incomplete", "repair_incomplete"}:
                phase = "initial" if failure_location == "initial_incomplete" else "repair"
                incomplete_attempt = next(a for a in attempts if a["phase"] == phase)
                assert incomplete_attempt["failure_code"] == "STRUCTURED_RESPONSE_INCOMPLETE"
                candidate = next(c for c in candidates if c.candidate_id == entry["subject_id"])
                assert incomplete_attempt["invalid_output"] == _boundary_review(
                    candidate
                ).model_dump(mode="json")
            elif failure_location == "provider_repair":
                assert any(a["phase"] == "repair" and a["invalid_output"] for a in attempts)
            elif failure_location == "repair_budget":
                rejected = next(a for a in attempts if a["phase"] == "repair_budget")
                assert rejected["repair_call_executed"] is False
                assert rejected["estimated_total_tokens"] > rejected["budget_tokens"]
            else:
                assert evidence["agent_outputs"] and evidence["validation_events"]
            if failure_location not in {
                "initial_incomplete",
                "initial_multipart",
                "completed_multipart",
                "schema_multipart",
            }:
                assert any("review_reason" in e for a in attempts for e in a["validation_errors"])
            with engine.connect() as connection:
                row = (
                    connection.execute(select(AssetRow).where(AssetRow.id == entry["asset_id"]))
                    .mappings()
                    .one()
                )
            assert row["status"] == "committed" and row["sha256"] == entry["sha256"]
        first, second, third = (c.candidate_id for c in candidates)
        assert calls == {first: 1, second: spent_calls, third: spent_calls}
        assert len(records) == 1 + 2 * spent_calls
        cached = list(
            (tmp_path / work.project_id / "runs/g001/semantic-cache/boundary_review").glob("*.json")
        )
        assert len(cached) == 1
        before = cached[0].read_bytes()
        assert SemanticStageCacheRecord.model_validate_json(before).output["candidate_id"] == first
        recovered = True  # Explicit new-generation resume, not another hidden repair.
        resolved, audit = run(provider, 2)
        assert set(resolved) == {first, second, third}
        assert calls == {first: 1, second: spent_calls + 1, third: spent_calls + 1}
        assert len(records) == 3 + 2 * spent_calls
        assert audit["cache_hits"] == {first: True, second: False, third: False}
        assert cached[0].read_bytes() == before
        new_cache = list(
            (tmp_path / work.project_id / "runs/g002/semantic-cache/boundary_review").glob("*.json")
        )
        assert len(new_cache) == 2
        assert {
            SemanticStageCacheRecord.model_validate_json(path.read_bytes()).output["candidate_id"]
            for path in new_cache
        } == {second, third}
        assert all(path.read_bytes() == data for path, data in retained_bytes.items())
        # Same lease and subject identities cannot replace committed evidence.
        original_failures = [
            (
                entry["subject_id"],
                json.loads((project_dir / entry["relative_path"]).read_text())[
                    "request_fingerprint"
                ],
                StructuredProviderError(expected_code, ()),
            )
            for entry in manifest["failed_subjects"]
        ]
        with pytest.raises(ArtifactPublicationError):
            handler._persist_v4_failure_audit(
                work,
                fence=StageMutationFence(
                    lease=lease,
                    project_id=work.project_id,
                    run_id=work.run_id,
                    stage_run_id=work.stage_run_id,
                    generation=1,
                ),
                project_dir=project_dir,
                stage="boundary_review",
                provider=provider,
                failures=original_failures,
                agent_outputs=[],
                validation_events=[],
                subject_call_ids={},
            )
        assert all(path.read_bytes() == data for path, data in retained_bytes.items())
        stale = StageMutationFence(
            lease=LeaseIdentity(
                task_id=lease.task_id, worker_id=lease.worker_id, lease_token="0" * 64
            ),
            project_id=work.project_id,
            run_id=work.run_id,
            stage_run_id=work.stage_run_id,
            generation=1,
        )
        with pytest.raises(AssetReservationError):
            handler._persist_v4_failure_audit(
                work,
                fence=stale,
                project_dir=project_dir,
                stage="boundary_review",
                provider=provider,
                failures=[
                    (second, "e" * 64, StructuredProviderError("STRUCTURED_OUTPUT_INVALID", ()))
                ],
                agent_outputs=[],
                validation_events=[],
                subject_call_ids={},
            )
        assert all(path.read_bytes() == data for path, data in retained_bytes.items())

        from liveclip.application.stage_execution import StageExecutionError
        from liveclip.application.stage_runner import RunOneOutcome, StageTaskRunner

        repository = SqlAlchemyPipelineRepository(engine)

        def replay_failure(*args, **kwargs):
            raise failure.value

        with monkeypatch.context() as patch:
            patch.setattr(handler, "_edit", replay_failure)
            with pytest.raises(StageExecutionError) as mapped:
                handler.execute(work, lease, cancel_requested=lambda: False)
        runner = StageTaskRunner(
            queue=queue,
            repository=repository,
            pipeline_service=object(),
            handler=handler,
            heartbeat_seconds=10,
        )
        assert runner._record_failure(claimed, lease, mapped.value) == RunOneOutcome.FAILED
        with engine.connect() as connection:
            attempt = (
                connection.execute(
                    select(TaskAttemptRow).where(TaskAttemptRow.lease_token == lease.lease_token)
                )
                .mappings()
                .one()
            )
            assert attempt["outcome"] == "failed"
            assert attempt["error_code"] == mapped.value.error_code
            assert attempt["diagnostic_relative_path"] == failure.value.diagnostic_relative_path
            assert (
                connection.scalar(select(TaskRow.status).where(TaskRow.id == lease.task_id))
                == "failed"
            )
            assert (
                connection.scalar(
                    select(StageRunRow.status).where(StageRunRow.id == work.stage_run_id)
                )
                == "failed"
            )
            assert (
                connection.scalar(
                    select(PipelineRunRow.status).where(PipelineRunRow.id == work.run_id)
                )
                == "failed"
            )
        reloaded = json.loads((project_dir / attempt["diagnostic_relative_path"]).read_text())
        assert reloaded == manifest

        from liveclip.media.artifacts import cleanup_attempt_worktree

        cleanup_attempt_worktree(
            project_dir,
            task_id=lease.task_id,
            lease_token=lease.lease_token,
            preserve_diagnostics=True,
        )
        assert json.loads(manifest_path.read_text()) == manifest
        assert all(path.read_bytes() == data for path, data in retained_bytes.items())


def _transcript(seconds: int = 500) -> TranscriptDocument:
    return TranscriptDocument(
        source_duration_ms=seconds * 1_000,
        word_timing_status=WordTimingStatus.UNAVAILABLE,
        segments=tuple(
            TranscriptSegment(
                segment_id=f"segment_{index:04d}",
                start_ms=index * 1_000,
                end_ms=(index + 1) * 1_000,
                text=f"cue {index + 1}",
            )
            for index in range(seconds)
        ),
    )


@pytest.mark.parametrize("stage", ["boundary_review", "global_review"])
def test_quality_contract_cache_roundtrip_cannot_reuse_legacy_output(tmp_path, stage):
    from liveclip.clipping_skills.semantic_topic_chain_v1 import load_semantic_topic_chain_prompt
    from liveclip.domain.semantic_validation import LEGACY_SEMANTIC_VALIDATION
    from liveclip.pipeline.semantic_cache import (
        load_semantic_stage_cache,
        semantic_stage_cache_key,
        semantic_validation_cache_settings,
        write_semantic_stage_cache,
    )
    from liveclip.providers.llm.structured import MockStructuredLLMProvider

    candidate = _candidate()
    output = (
        _boundary_review(candidate)
        if stage == "boundary_review"
        else GlobalReviewOutputV4(
            clip_profile=ClipProfile.MINI_LESSON, reviews=(_global_review(candidate),)
        )
    )
    provider = MockStructuredLLMProvider(
        prompts=load_semantic_topic_chain_prompt(stage, "general", ClipProfile.MINI_LESSON),
        model_name="fixture",
    )
    common = dict(stage=stage, payload={"candidate_id": candidate.candidate_id}, provider=provider)
    old_settings = semantic_validation_cache_settings(
        {"profile": "mini_lesson"},
        stage=stage,
        contract=LEGACY_SEMANTIC_VALIDATION,
    )
    new_settings = semantic_validation_cache_settings(
        {"profile": "mini_lesson"},
        stage=stage,
        contract=CURRENT_SEMANTIC_VALIDATION,
    )
    old_key = semantic_stage_cache_key(
        **common, model_settings=old_settings, output_model=type(output)
    )
    new_key = semantic_stage_cache_key(
        **common, model_settings=new_settings, output_model=type(output)
    )
    assert old_key != new_key
    write_semantic_stage_cache(
        **common,
        cache_dir=tmp_path,
        cache_key=old_key,
        model_settings=old_settings,
        output=output,
    )
    assert (
        load_semantic_stage_cache(
            **common,
            cache_dirs=(tmp_path,),
            cache_key=new_key,
            model_settings=new_settings,
            output_model=type(output),
        )
        is None
    )
    # Even a forced old filename cannot bypass the record's settings fingerprint.
    with pytest.raises(ValueError, match="identity"):
        load_semantic_stage_cache(
            **common,
            cache_dirs=(tmp_path,),
            cache_key=old_key,
            model_settings=new_settings,
            output_model=type(output),
        )
    write_semantic_stage_cache(
        **common,
        cache_dir=tmp_path,
        cache_key=new_key,
        model_settings=new_settings,
        output=output,
    )
    assert (
        load_semantic_stage_cache(
            **common,
            cache_dirs=(tmp_path,),
            cache_key=new_key,
            model_settings=new_settings,
            output_model=type(output),
        )
        == output
    )


def _fragment(
    index: int,
    *,
    start_cue_id: int,
    end_cue_id: int,
    left_complete: bool,
    right_complete: bool,
) -> TopicFragmentV4:
    return TopicFragmentV4(
        topic_fragment_id=f"fragment_{index:03d}",
        logical_window_id=f"window_{index:03d}",
        topic_summary=f"lesson part {index}",
        central_question="How does the complete lesson work?",
        learning_outcome="Apply every step in order.",
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        touches_left_boundary=not left_complete,
        touches_right_boundary=not right_complete,
        left_complete=left_complete,
        right_complete=right_complete,
        evidence_cue_ids=(start_cue_id, end_cue_id),
        possible_profiles=(ClipProfile.MINI_LESSON,),
        source_batch_id=f"batch_{index // 4:03d}",
    )


def _boundary(*, left: bool, right: bool, fragment_id: str) -> TopicBoundaryV4:
    return TopicBoundaryV4(
        continues_previous_topic=left,
        topic_unfinished=right,
        topic_summary="one lesson" if left or right else "",
        central_question="one objective" if left or right else "",
        continuation_expected=right,
        evidence_cue_ids=(1,) if left or right else (),
        related_fragment_ids=(fragment_id,) if left or right else (),
    )


def _window(index: int, fragment: TopicFragmentV4) -> LogicalWindowDiscoveryV4:
    return LogicalWindowDiscoveryV4(
        logical_window_id=fragment.logical_window_id,
        window_start_ms=(index - 1) * 60_000,
        window_end_ms=(index + 1) * 60_000,
        fragment_ids=(fragment.topic_fragment_id,),
        left_boundary=_boundary(
            left=index > 1,
            right=False,
            fragment_id=fragment.topic_fragment_id,
        ),
        right_boundary=_boundary(
            left=False,
            right=index < 4,
            fragment_id=fragment.topic_fragment_id,
        ),
    )


def _batch(index: int, window: LogicalWindowDiscoveryV4, fragment: TopicFragmentV4):
    return DiscoveryBatchOutputV4(
        batch_id=f"batch_{index:03d}",
        batch_context=TimeRangeV4(
            start_ms=window.window_start_ms,
            end_ms=window.window_end_ms,
        ),
        ownership_interval=TimeRangeV4(
            start_ms=window.window_start_ms,
            end_ms=window.window_end_ms,
        ),
        logical_windows=(window,),
        topic_fragments=(fragment,),
    )


def _link(left: TopicFragmentV4, right: TopicFragmentV4, index: int) -> LinkReviewV4:
    return LinkReviewV4(
        link_review_id=f"link_{index:03d}",
        left_fragment_id=left.topic_fragment_id,
        right_fragment_id=right.topic_fragment_id,
        same_topic=True,
        same_central_objective=True,
        relationship=LinkRelationshipV4.NEXT_STEP_SAME_LESSON,
        merged_topic_summary="one lesson with ordered steps",
        central_question=left.central_question,
        learning_outcome=left.learning_outcome,
        topic_closed_on_right=right.right_complete,
        needs_next_boundary=not right.right_complete,
        evidence_cue_ids=(left.end_cue_id, right.start_cue_id),
        confidence=0.95,
    )


def _candidate(
    profile: ClipProfile = ClipProfile.MINI_LESSON,
    *,
    start_cue_id: int = 51,
    end_cue_id: int = 320,
) -> ChainCandidateV4:
    return ChainCandidateV4(
        candidate_id=f"{profile.value}_candidate_001",
        clip_profile=profile,
        source_topic_id="topic_001",
        topic_chain_id="chain_001",
        source_fragment_ids=("fragment_001",),
        start_cue_id=start_cue_id,
        end_cue_id=end_cue_id,
        central_question="How does the complete lesson work?",
        learning_outcome="Apply every step in order.",
        title="Complete lesson",
        summary="A complete teaching unit.",
        evidence_cue_ids=(start_cue_id, end_cue_id),
    )


def _boundary_review(
    candidate: ChainCandidateV4,
    *,
    interruptions: tuple[InterruptionReviewV4, ...] = (),
    flags: tuple[QualityFlagV4, ...] = (),
) -> BoundaryReviewV4:
    return BoundaryReviewV4(
        candidate_id=candidate.candidate_id,
        clip_profile=candidate.clip_profile,
        content_decision=ContentDecisionV4.KEEP,
        proposed_start_cue_id=candidate.start_cue_id,
        proposed_end_cue_id=candidate.end_cue_id,
        opening_complete=True,
        ending_complete=True,
        central_objective_complete=True,
        boundary_compactness="shortest_complete",
        opening_relevance="necessary_context",
        ending_relevance="necessary_conclusion",
        internal_topic_switch=False,
        contains_padding=False,
        interruption_review=interruptions,
        quality_flags=flags,
        evidence=BoundaryEvidenceV4(
            opening_cue_ids=(candidate.start_cue_id,),
            core_cue_ids=(candidate.start_cue_id + 1,),
            ending_cue_ids=(candidate.end_cue_id,),
        ),
        review_reason="The supplied interval is the shortest complete continuous unit.",
    )


def _global_review(
    candidate: ChainCandidateV4,
    *,
    score: int = 80,
    publish_status: PublishStatusV4 = PublishStatusV4.AUTO,
    risk_flags: tuple[RiskFlagV4, ...] = (),
    quality_flags: tuple[QualityFlagV4, ...] = (),
    interruptions: tuple[InterruptionReviewV4, ...] = (),
) -> CandidateGlobalReviewV4:
    if candidate.clip_profile == ClipProfile.MINI_LESSON:
        values = _bounded_score_values(score, (20, 20, 15, 15, 10, 10, 10))
        scores = MiniLessonScoresV4(
            central_objective_clarity=values[0],
            completeness_and_closure=values[1],
            teaching_structure=values[2],
            standalone_understanding=values[3],
            information_density=values[4],
            edit_cleanliness=values[5],
            title_summary_fidelity=values[6],
        )
    else:
        values = _bounded_score_values(score, (20, 20, 15, 20, 15, 10))
        scores = ShortHighlightScoresV4(
            independence=values[0],
            completeness=values[1],
            single_topic=values[2],
            viewer_value=values[3],
            source_fidelity=values[4],
            edit_cleanliness=values[5],
        )
    assert scores.total == score
    return CandidateGlobalReviewV4(
        candidate_id=candidate.candidate_id,
        clip_profile=candidate.clip_profile,
        source_topic_id=candidate.source_topic_id,
        topic_chain_id=candidate.topic_chain_id,
        source_fragment_ids=candidate.source_fragment_ids,
        start_cue_id=candidate.start_cue_id,
        end_cue_id=candidate.end_cue_id,
        central_question=candidate.central_question,
        learning_outcome=candidate.learning_outcome,
        title=candidate.title,
        summary=candidate.summary,
        content_decision=ContentDecisionV4.KEEP,
        publish_status=publish_status,
        quality_flags=quality_flags,
        risk_flags=risk_flags,
        interruption_review=interruptions,
        scores=scores,
        total_score=score,
        evidence_cue_ids=candidate.evidence_cue_ids,
        review_reason="Deterministic test review.",
    )


def _bounded_score_values(total: int, capacities: tuple[int, ...]) -> tuple[int, ...]:
    remaining = total
    values: list[int] = []
    for capacity in capacities:
        value = min(capacity, remaining)
        values.append(value)
        remaining -= value
    assert remaining == 0
    return tuple(values)


def test_profiles_keep_exact_independent_bounds() -> None:
    assert clip_profile_spec(ClipProfile.SHORT_HIGHLIGHT) == SHORT_HIGHLIGHT_SPEC
    assert clip_profile_spec(ClipProfile.MINI_LESSON) == MINI_LESSON_SPEC
    assert (
        SHORT_HIGHLIGHT_SPEC.minimum_duration_ms,
        SHORT_HIGHLIGHT_SPEC.target_duration_ms,
        SHORT_HIGHLIGHT_SPEC.maximum_duration_ms,
    ) == (45_000, 60_000, 90_000)
    assert (
        MINI_LESSON_SPEC.minimum_duration_ms,
        MINI_LESSON_SPEC.target_duration_ms,
        MINI_LESSON_SPEC.maximum_duration_ms,
    ) == (90_000, 180_000, 300_000)


def test_one_sided_open_boundary_routes_link_review() -> None:
    left_fragment = _fragment(
        1, start_cue_id=51, end_cue_id=120, left_complete=True, right_complete=False
    )
    right_fragment = _fragment(
        2, start_cue_id=111, end_cue_id=180, left_complete=False, right_complete=True
    )
    left_window = _window(1, left_fragment)
    right_window = _window(2, right_fragment).model_copy(
        update={
            "left_boundary": TopicBoundaryV4(),
            "right_boundary": TopicBoundaryV4(),
        }
    )
    requests = plan_link_review_requests_v4(
        (_batch(1, left_window, left_fragment), _batch(2, right_window, right_fragment))
    )
    assert len(requests) == 1
    assert requests[0].left_fragment.topic_fragment_id == "fragment_001"
    assert requests[0].right_fragment.topic_fragment_id == "fragment_002"
    assert requests[0].context_range.end_ms - requests[0].context_range.start_ms == 180_000


def test_positive_open_link_routes_the_next_boundary_iteratively() -> None:
    fragments = (
        _fragment(1, start_cue_id=1, end_cue_id=120, left_complete=True, right_complete=False),
        _fragment(2, start_cue_id=61, end_cue_id=180, left_complete=False, right_complete=False),
        _fragment(3, start_cue_id=121, end_cue_id=240, left_complete=False, right_complete=True),
    )
    windows = tuple(
        _window(index, fragment).model_copy(
            update={"left_boundary": TopicBoundaryV4(), "right_boundary": TopicBoundaryV4()}
        )
        for index, fragment in enumerate(fragments, start=1)
    )
    outputs = tuple(
        _batch(index, window, fragment)
        for index, (window, fragment) in enumerate(zip(windows, fragments, strict=True), start=1)
    )
    first_request = plan_link_review_requests_v4(
        (
            outputs[0].model_copy(
                update={
                    "logical_windows": (
                        windows[0].model_copy(
                            update={
                                "right_boundary": _boundary(
                                    left=False,
                                    right=True,
                                    fragment_id=fragments[0].topic_fragment_id,
                                )
                            }
                        ),
                    )
                }
            ),
            outputs[1],
        )
    )[0]
    first_review = _link(fragments[0], fragments[1], 1)
    followup = plan_followup_link_review_requests_v4(
        outputs,
        existing_requests=(first_request,),
        completed_reviews=(first_review,),
    )
    assert len(followup) == 1
    assert followup[0].left_fragment.topic_fragment_id == fragments[1].topic_fragment_id
    assert followup[0].right_fragment.topic_fragment_id == fragments[2].topic_fragment_id


def test_discovery_transport_ids_are_namespaced_without_semantic_changes() -> None:
    fragment = _fragment(
        1, start_cue_id=1, end_cue_id=120, left_complete=True, right_complete=True
    ).model_copy(
        update={
            "topic_fragment_id": "fragment_local",
            "logical_window_id": "window_local",
            "source_batch_id": "batch_001",
        }
    )
    candidate = _candidate(start_cue_id=1, end_cue_id=120).model_dump(mode="json")
    output = DiscoveryBatchOutputV4.model_validate_json(
        json.dumps(
            {
                "schema_version": "4",
                "batch_id": "batch_001",
                "batch_context": {"start_ms": 0, "end_ms": 120_000},
                "ownership_interval": {"start_ms": 0, "end_ms": 120_000},
                "logical_windows": [
                    {
                        "logical_window_id": "window_local",
                        "window_start_ms": 0,
                        "window_end_ms": 120_000,
                        "candidate_ids": ["candidate_local"],
                        "fragment_ids": ["fragment_local"],
                        "left_boundary": {},
                        "right_boundary": {},
                        "coverage_notes": [],
                    }
                ],
                "candidates": [
                    {
                        "candidate_id": "candidate_local",
                        "source_topic_id": "topic_local",
                        "topic_fragment_ids": ["fragment_local"],
                        "topic_summary": "one topic",
                        "central_question": candidate["central_question"],
                        "learning_outcome": candidate["learning_outcome"],
                        "start_cue_id": 1,
                        "end_cue_id": 120,
                        "evidence_cue_ids": [1, 120],
                        "possible_profiles": ["mini_lesson"],
                        "risk_flags": [],
                        "source_window_ids": ["window_local"],
                        "source_batch_id": "batch_001",
                    }
                ],
                "topic_fragments": [fragment.model_dump(mode="json")],
            },
            ensure_ascii=False,
        )
    )
    normalized, notes = namespace_discovery_batch_v4(output)
    assert notes == ("transport_ids_namespaced",)
    assert normalized.candidates[0].candidate_id == "batch_001_candidate_local"
    assert normalized.topic_fragments[0].topic_fragment_id == "batch_001_fragment_local"
    assert normalized.candidates[0].central_question == output.candidates[0].central_question


def test_checked_in_v4_schemas_match_runtime_models() -> None:
    root = Path(__file__).parents[2] / "src/liveclip/schemas/semantic_v4"
    expected = {
        "discovery-batch-v4.schema.json": DiscoveryBatchOutputV4,
        "link-review-v4.schema.json": LinkReviewV4,
        "topic-chain-review-v4.schema.json": TopicChainReviewV4,
        "boundary-review-v4.schema.json": BoundaryReviewV4,
        "global-review-v4.schema.json": GlobalReviewOutputV4,
        "final-validated-v4.schema.json": UnifiedSemanticResultV4,
    }
    for filename, model in expected.items():
        assert json.loads((root / filename).read_text(encoding="utf-8")) == (
            model.model_json_schema(mode="validation")
        )


def test_270_second_topic_chains_across_every_confirmed_boundary() -> None:
    fragments = (
        _fragment(1, start_cue_id=51, end_cue_id=120, left_complete=True, right_complete=False),
        _fragment(2, start_cue_id=111, end_cue_id=180, left_complete=False, right_complete=False),
        _fragment(3, start_cue_id=171, end_cue_id=240, left_complete=False, right_complete=False),
        _fragment(4, start_cue_id=231, end_cue_id=320, left_complete=False, right_complete=True),
    )
    links = tuple(
        _link(left, right, index)
        for index, (left, right) in enumerate(pairwise(fragments), start=1)
    )
    chains = assemble_topic_chains_v4(fragments, links)
    assert len(chains) == 1
    chain = chains[0]
    assert chain.fragment_ids == tuple(value.topic_fragment_id for value in fragments)
    assert chain.link_review_ids == ("link_001", "link_002", "link_003")
    assert chain.chain_status == TopicChainStatusV4.CLOSED
    assert chain.source_start_cue_id == 51
    assert chain.source_end_cue_id == 320


def test_adjacent_different_questions_are_not_merged() -> None:
    left = _fragment(1, start_cue_id=51, end_cue_id=120, left_complete=True, right_complete=False)
    right = _fragment(2, start_cue_id=111, end_cue_id=180, left_complete=False, right_complete=True)
    rejected_link = LinkReviewV4(
        link_review_id="link_001",
        left_fragment_id=left.topic_fragment_id,
        right_fragment_id=right.topic_fragment_id,
        same_topic=False,
        same_central_objective=False,
        relationship=LinkRelationshipV4.TOPIC_SWITCH,
        merged_topic_summary="Adjacent but separate lessons.",
        central_question="Are these the same teaching objective?",
        learning_outcome="Keep the two questions separate.",
        topic_closed_on_right=True,
        needs_next_boundary=False,
        evidence_cue_ids=(left.end_cue_id, right.start_cue_id),
        confidence=0.99,
    )
    chains = assemble_topic_chains_v4((left, right), (rejected_link,))
    assert len(chains) == 2


def test_over_300_chain_requires_natural_subunit_or_explicit_rejection() -> None:
    transcript = _transcript()
    fragment = _fragment(1, start_cue_id=1, end_cue_id=400, left_complete=True, right_complete=True)
    chain = assemble_topic_chains_v4((fragment,), ())[0]
    wrong_rejection = TopicChainReviewV4(
        topic_chain_id=chain.topic_chain_id,
        central_question=chain.central_question,
        learning_outcome=chain.learning_outcome,
        topic_outline=chain.topic_outline,
        left_closed=True,
        right_closed=True,
        chain_status=TopicChainStatusV4.REJECTED,
        candidates=(),
        rejection_reason="no_complete_profile_candidate",
        evidence_cue_ids=(1, 400),
    )
    with pytest.raises(ValueError, match="too-long rejection"):
        validate_topic_chain_review_v4(wrong_rejection, chain=chain, transcript=transcript)
    accepted_rejection = wrong_rejection.model_copy(
        update={"rejection_reason": "topic_too_long_without_natural_split"}
    )
    assert (
        validate_topic_chain_review_v4(
            accepted_rejection,
            chain=chain,
            transcript=transcript,
        )
        == accepted_rejection
    )


def test_over_300_chain_accepts_agent_natural_teaching_subunits() -> None:
    transcript = _transcript()
    fragment = _fragment(1, start_cue_id=1, end_cue_id=400, left_complete=True, right_complete=True)
    chain = assemble_topic_chains_v4((fragment,), ())[0]
    candidates = tuple(
        _candidate(start_cue_id=start, end_cue_id=end).model_copy(
            update={
                "candidate_id": f"mini_lesson_candidate_{index:03d}",
                "topic_chain_id": chain.topic_chain_id,
                "natural_subunit": True,
                "natural_split_evidence_cue_ids": (end,),
            }
        )
        for index, (start, end) in enumerate(((1, 180), (181, 400)), start=1)
    )
    review = TopicChainReviewV4(
        topic_chain_id=chain.topic_chain_id,
        central_question=chain.central_question,
        learning_outcome=chain.learning_outcome,
        topic_outline=chain.topic_outline,
        left_closed=True,
        right_closed=True,
        chain_status=TopicChainStatusV4.CLOSED,
        candidates=candidates,
        evidence_cue_ids=(1, 180, 181, 400),
    )
    assert validate_topic_chain_review_v4(review, chain=chain, transcript=transcript) == review


@pytest.mark.parametrize(
    ("profile", "start", "end"),
    (
        (ClipProfile.SHORT_HIGHLIGHT, 1, 45),
        (ClipProfile.SHORT_HIGHLIGHT, 1, 90),
        (ClipProfile.MINI_LESSON, 1, 90),
        (ClipProfile.MINI_LESSON, 1, 300),
    ),
)
def test_profile_duration_endpoints_are_inclusive(
    profile: ClipProfile,
    start: int,
    end: int,
) -> None:
    transcript = _transcript()
    candidate = _candidate(profile, start_cue_id=start, end_cue_id=end)
    boundary = _boundary_review(candidate)
    assert validate_boundary_review_v4(boundary, candidate=candidate, transcript=transcript)


def test_75_score_does_not_pass_and_top_n_never_pads() -> None:
    transcript = _transcript()
    candidates = (
        _candidate(),
        _candidate(start_cue_id=201, end_cue_id=320).model_copy(
            update={"candidate_id": "mini_lesson_candidate_002"}
        ),
    )
    boundaries = tuple(_boundary_review(value) for value in candidates)
    output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=(_global_review(candidates[0], score=75), _global_review(candidates[1])),
    )
    validated = validate_profile_global_review_v4(
        output,
        candidates=candidates,
        boundary_reviews=boundaries,
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert not validated.selected or len(validated.selected) == 1
    assert len(validated.selected) == 1
    assert len(validated.rejected) == 1
    assert validated.statistics.qualified_before_top_n == 1


def test_profiles_have_independent_top_n_and_cross_profile_variants_survive() -> None:
    transcript = _transcript()
    mini = _candidate()
    short = _candidate(ClipProfile.SHORT_HIGHLIGHT, start_cue_id=51, end_cue_id=110).model_copy(
        update={"candidate_id": "short_highlight_candidate_001"}
    )
    short_review = _global_review(short).model_copy(
        update={
            "variant_of": mini.candidate_id,
            "variant_relationship": "short_version_of",
        }
    )
    short_result = validate_profile_global_review_v4(
        GlobalReviewOutputV4(
            clip_profile=ClipProfile.SHORT_HIGHLIGHT,
            reviews=(short_review,),
        ),
        candidates=(short,),
        boundary_reviews=(_boundary_review(short),),
        transcript=transcript,
        profile=ClipProfile.SHORT_HIGHLIGHT,
        top_n=1,
    )
    mini_result = validate_profile_global_review_v4(
        GlobalReviewOutputV4(
            clip_profile=ClipProfile.MINI_LESSON,
            reviews=(_global_review(mini),),
        ),
        candidates=(mini,),
        boundary_reviews=(_boundary_review(mini),),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=1,
    )
    assert len(short_result.selected) == len(mini_result.selected) == 1
    assert (
        short_result.selected[0].review.source_topic_id
        == mini_result.selected[0].review.source_topic_id
    )


def test_manual_and_blocked_results_never_enter_selected_render_set() -> None:
    transcript = _transcript()
    manual = _candidate()
    blocked = manual.model_copy(update={"candidate_id": "mini_lesson_candidate_002"})
    output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=(
            _global_review(manual, risk_flags=(RiskFlagV4.MUSIC_RIGHTS_REVIEW,)),
            _global_review(blocked, risk_flags=(RiskFlagV4.MEDICAL_CLAIM,)),
        ),
    )
    result = validate_profile_global_review_v4(
        output,
        candidates=(manual, blocked),
        boundary_reviews=(_boundary_review(manual), _boundary_review(blocked)),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert result.selected == ()
    assert len(result.manual_review) == 1
    assert len(result.blocked) == 1


def test_blocking_quality_and_material_interruption_cannot_be_compensated() -> None:
    transcript = _transcript()
    candidate = _candidate()
    material = InterruptionReviewV4(
        severity=InterruptionSeverityV4.MATERIAL,
        type="equipment_adjustment",
        evidence_cue_ids=(100,),
        description="The teaching stops for an unrelated equipment adjustment.",
        blocking=True,
    )
    output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=(_global_review(candidate, score=95, interruptions=(material,)),),
    )
    result = validate_profile_global_review_v4(
        output,
        candidates=(candidate,),
        boundary_reviews=(_boundary_review(candidate),),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert result.selected == ()
    assert result.rejected[0].disposition == CandidateDispositionV4.REJECTED
    assert "blocking_interruption_gate" in result.rejected[0].validation_notes


def test_minor_interruption_can_remain_nonblocking() -> None:
    transcript = _transcript()
    candidate = _candidate()
    minor = InterruptionReviewV4(
        severity=InterruptionSeverityV4.MINOR,
        type="brief_live_thanks",
        evidence_cue_ids=(100,),
        description="One brief thanks does not change the teaching structure.",
        blocking=False,
    )
    output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=(_global_review(candidate, interruptions=(minor,)),),
    )
    result = validate_profile_global_review_v4(
        output,
        candidates=(candidate,),
        boundary_reviews=(_boundary_review(candidate),),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert len(result.selected) == 1


def test_context_dependent_opening_cannot_auto_publish() -> None:
    transcript = _transcript()
    candidate = _candidate()
    output = GlobalReviewOutputV4(
        clip_profile=ClipProfile.MINI_LESSON,
        reviews=(
            _global_review(
                candidate,
                score=95,
                quality_flags=(QualityFlagV4.CONTEXT_DEPENDENT_OPENING,),
            ),
        ),
    )
    result = validate_profile_global_review_v4(
        output,
        candidates=(candidate,),
        boundary_reviews=(_boundary_review(candidate),),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert result.selected == ()
    assert "blocking_quality_gate" in result.rejected[0].validation_notes


def test_weaker_duplicate_requires_explicit_audit_and_is_rejected() -> None:
    transcript = _transcript()
    stronger = _candidate()
    weaker = _candidate(start_cue_id=201, end_cue_id=320).model_copy(
        update={"candidate_id": "mini_lesson_candidate_002"}
    )
    raw_weaker_review = _global_review(weaker).model_dump()
    raw_weaker_review.update(
        {
            "duplicate_group_id": "duplicate_group_001",
            "duplicate_of": stronger.candidate_id,
            "quality_flags": (QualityFlagV4.DUPLICATE_WEAKER,),
        }
    )
    weaker_review = CandidateGlobalReviewV4.model_validate(raw_weaker_review)
    result = validate_profile_global_review_v4(
        GlobalReviewOutputV4(
            clip_profile=ClipProfile.MINI_LESSON,
            reviews=(_global_review(stronger), weaker_review),
        ),
        candidates=(stronger, weaker),
        boundary_reviews=(_boundary_review(stronger), _boundary_review(weaker)),
        transcript=transcript,
        profile=ClipProfile.MINI_LESSON,
        top_n=15,
    )
    assert len(result.selected) == 1
    assert result.rejected[0].review.duplicate_of == stronger.candidate_id
    assert "blocking_quality_gate" in result.rejected[0].validation_notes


def test_duplicate_reference_without_duplicate_flag_is_invalid() -> None:
    raw = _global_review(_candidate()).model_dump()
    raw.update(
        {
            "duplicate_group_id": "duplicate_group_001",
            "duplicate_of": "mini_lesson_candidate_002",
        }
    )
    with pytest.raises(ValueError, match="duplicate_of and duplicate_weaker"):
        CandidateGlobalReviewV4.model_validate(raw)


def test_boundary_review_cannot_reference_cues_outside_its_local_context() -> None:
    transcript = _transcript()
    candidate = _candidate(start_cue_id=100, end_cue_id=220)
    boundary = _boundary_review(candidate).model_copy(
        update={
            "content_decision": ContentDecisionV4.REPAIR_BOUNDARY,
            "proposed_start_cue_id": 1,
            "evidence": BoundaryEvidenceV4(
                opening_cue_ids=(1,),
                core_cue_ids=(100,),
                ending_cue_ids=(220,),
            ),
        }
    )
    with pytest.raises(ValueError, match="unknown cue ID"):
        validate_boundary_review_v4(boundary, candidate=candidate, transcript=transcript)


def test_global_review_evidence_must_come_from_actual_local_interval() -> None:
    transcript = _transcript()
    candidate = _candidate(start_cue_id=100, end_cue_id=220)
    review = _global_review(candidate).model_copy(update={"evidence_cue_ids": (1,)})
    with pytest.raises(ValueError, match="unknown cue ID"):
        validate_profile_global_review_v4(
            GlobalReviewOutputV4(
                clip_profile=ClipProfile.MINI_LESSON,
                reviews=(review,),
            ),
            candidates=(candidate,),
            boundary_reviews=(_boundary_review(candidate),),
            transcript=transcript,
            profile=ClipProfile.MINI_LESSON,
            top_n=15,
        )
