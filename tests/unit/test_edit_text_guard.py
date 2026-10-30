"""Stage 11: guard-safe text in persisted pipeline EditPlans (unit level)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import BaseModel

from liveclip.domain.edit_plan import (
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    reject_executable_text,
)
from liveclip.pipeline.edit_text_guard import (
    TEXT_GUARD_BLOCK_NOTE,
    TEXT_GUARD_ERROR_PREFIX,
    TEXT_GUARD_REJECT_NOTE,
    block_global_review_text_violations,
    block_profile_v4_text_violations,
    build_ai_edit_plan,
    edit_plan_text_errors,
    global_review_text_errors,
    profile_v4_edit_plan,
    profile_v4_text_errors,
    raise_for_text_guard,
)
from liveclip.pipeline.semantic_executor import (
    DeferredValidationError,
    SemanticUnitRequest,
    execute_semantic_unit,
    validate_or_accept_deferred,
)
from liveclip.pipeline.semantic_global import (
    ClipOrigin,
    GlobalReviewStatistics,
    GlobalReviewStatisticsV3,
    PublishStatusV3,
    ReviewDecision,
    ValidatedCandidateReviewV3,
    ValidatedGlobalClip,
    ValidatedGlobalReview,
    ValidatedGlobalReviewV3,
)
from liveclip.pipeline.semantic_profiles import (
    CandidateDispositionV4,
    CandidateGlobalReviewV4,
    ProfileStatisticsV4,
    ValidatedCandidateV4,
    ValidatedProfileResultV4,
)
from liveclip.providers.llm.structured import StructuredCallResult
from liveclip.providers.telemetry import ProviderCallRecord, ProviderCallStatus

# The cold-27 false positive: an English review reason that uses the verb "make".
MAKE_REASON = "Cues 704 through 719 make a complete, shortest boundary for this lesson."
FFMPEG_TITLE = "ffmpeg 入门"
SAFE_REASON = "这段从提问到练习完整闭合 边界最短且自足"
SAFE_TITLE = "气声与漏气的区别"


def test_plain_make_reason_is_the_isolated_false_positive() -> None:
    # Only the verb "make" trips the unchanged guard; no other command syntax.
    with pytest.raises(ValueError, match="executable"):
        reject_executable_text(MAKE_REASON)
    errors = edit_plan_text_errors(
        "unit_a",
        title=("title", SAFE_TITLE),
        hook=("learning_outcome", "学会区分气声与漏气。"),
        reason=("review_reason", MAKE_REASON),
    )
    assert len(errors) == 1
    assert errors[0].startswith(f"{TEXT_GUARD_ERROR_PREFIX}candidate unit_a: review_reason")
    assert "first 240 characters" in errors[0]


def test_ffmpeg_title_and_hook_are_reported_by_source_field() -> None:
    errors = edit_plan_text_errors(
        "unit_b",
        title=("title", FFMPEG_TITLE),
        hook=("hook", "run ffmpeg to learn"),
        reason=("review_reason", SAFE_REASON),
    )
    assert len(errors) == 2
    assert errors[0].startswith(f"{TEXT_GUARD_ERROR_PREFIX}candidate unit_b: title is rejected")
    assert errors[1].startswith(
        f"{TEXT_GUARD_ERROR_PREFIX}candidate unit_b: hook (its first 80 characters) is rejected"
    )


def test_guard_check_mirrors_editplan_truncation_and_stripping() -> None:
    # "make" beyond the 240-character reason window never reaches EditPlan.
    tail = "x" * 236 + " make sense of it"
    assert not edit_plan_text_errors(
        "unit_c",
        title=("title", SAFE_TITLE),
        hook=("hook", "y" * 80 + " make it"),
        reason=("review_reason", tail),
    )
    # A trailing space after "make" is stripped by EditPlan, so it is not a hit.
    assert not edit_plan_text_errors(
        "unit_d",
        title=("title", SAFE_TITLE),
        hook=("hook", "we make "),
        reason=("review_reason", SAFE_REASON),
    )
    build_ai_edit_plan(
        candidate_id="unit_d",
        source_start_ms=0,
        source_end_ms=1,
        score=1.0,
        title=SAFE_TITLE,
        hook="we make ",
        reason=tail,
        risk_flags=(),
        prompt_version="p",
        model="m",
    )


def test_build_ai_edit_plan_is_byte_identical_to_the_previous_inline_plan() -> None:
    long_hook = "学" * 120
    long_reason = "理" * 400
    inline = EditPlan(
        candidate_id="slot_0001",
        source_start_ms=1_000,
        source_end_ms=95_000,
        score=88.0,
        title=SAFE_TITLE,
        hook=long_hook[:80],
        reason=long_reason[:240],
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=("commercial_claim",),
        prompt_version="semantic_topic_chain_v1.global_review",
        model="mock-llm-v1",
        degraded=False,
    )
    helper = build_ai_edit_plan(
        candidate_id="slot_0001",
        source_start_ms=1_000,
        source_end_ms=95_000,
        score=88.0,
        title=SAFE_TITLE,
        hook=long_hook,
        reason=long_reason,
        risk_flags=("commercial_claim",),
        prompt_version="semantic_topic_chain_v1.global_review",
        model="mock-llm-v1",
    )
    assert helper == inline
    assert helper.model_dump_json() == inline.model_dump_json()


def _v4_review(candidate_id: str, *, title: str = SAFE_TITLE, reason: str = SAFE_REASON):
    return CandidateGlobalReviewV4.model_validate_json(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "clip_profile": "mini_lesson",
                "source_topic_id": f"topic_{candidate_id}",
                "topic_chain_id": f"chain_{candidate_id}",
                "source_fragment_ids": [f"fragment_{candidate_id}"],
                "start_cue_id": 1,
                "end_cue_id": 2,
                "central_question": "怎样区分气声与漏气",
                "learning_outcome": "学会区分气声与漏气。",
                "title": title,
                "summary": "完整讲解与示范。",
                "content_decision": "keep",
                "publish_status": "auto",
                "scores": {
                    "central_objective_clarity": 20,
                    "completeness_and_closure": 20,
                    "teaching_structure": 15,
                    "standalone_understanding": 15,
                    "information_density": 10,
                    "edit_cleanliness": 10,
                    "title_summary_fidelity": 10,
                },
                "total_score": 100,
                "evidence_cue_ids": [1],
                "review_reason": reason,
            },
            ensure_ascii=False,
        )
    )


def _v4_candidate(candidate_id, start_ms, disposition=CandidateDispositionV4.SELECTED, **text):
    return ValidatedCandidateV4(
        review=_v4_review(candidate_id, **text),
        disposition=disposition,
        start_ms=start_ms,
        end_ms=start_ms + 120_000,
        duration_ms=120_000,
    )


def _v4_result(selected, blocked=(), top_n_excluded=()):
    return ValidatedProfileResultV4(
        selected=tuple(selected),
        blocked=tuple(blocked),
        top_n_excluded=tuple(top_n_excluded),
        statistics=ProfileStatisticsV4(
            discovery_candidate_count=len(selected) + len(blocked) + len(top_n_excluded),
            boundary_candidate_count=len(selected) + len(blocked) + len(top_n_excluded),
            qualified_before_top_n=len(selected) + len(top_n_excluded),
            selected_count=len(selected),
            manual_count=0,
            blocked_count=len(blocked),
            rejected_count=0,
            top_n_excluded_count=len(top_n_excluded),
        ),
    )


def test_profile_v4_gate_blocks_only_the_violating_candidate_without_promotion() -> None:
    kept = _v4_candidate("lesson_keep", 300_000)
    unsafe = _v4_candidate("lesson_make", 10_000, reason=MAKE_REASON)
    prior_block = _v4_candidate("lesson_prior", 200_000, CandidateDispositionV4.BLOCKED)
    excluded = _v4_candidate("lesson_excluded", 500_000, CandidateDispositionV4.TOP_N_EXCLUDED)
    result = _v4_result((unsafe, kept), blocked=(prior_block,), top_n_excluded=(excluded,))

    assert len(profile_v4_text_errors(result)) == 1
    gated = block_profile_v4_text_violations(result)

    assert [value.review.candidate_id for value in gated.selected] == ["lesson_keep"]
    assert [value.review.candidate_id for value in gated.blocked] == [
        "lesson_make",
        "lesson_prior",
    ]
    demoted = gated.blocked[0]
    assert demoted.disposition == CandidateDispositionV4.BLOCKED
    assert demoted.validation_notes[-1] == TEXT_GUARD_BLOCK_NOTE
    assert demoted.review == unsafe.review  # model text is never rewritten
    assert gated.top_n_excluded == result.top_n_excluded  # Python never promotes
    assert gated.statistics.selected_count == 1
    assert gated.statistics.blocked_count == 2
    assert gated.statistics.qualified_before_top_n == 2
    assert not profile_v4_text_errors(gated)


def test_profile_v4_gate_is_identity_for_guard_passing_text() -> None:
    result = _v4_result((_v4_candidate("lesson_keep", 0),))
    assert block_profile_v4_text_violations(result) is result
    plan = profile_v4_edit_plan(result.selected[0], candidate_id="slot_1", model="mock-llm-v1")
    assert plan.reason == SAFE_REASON and plan.title == SAFE_TITLE


def _v3_candidate(candidate_id, start_ms, *, title=SAFE_TITLE, hook="练习方法", reason=SAFE_REASON):
    return ValidatedCandidateReviewV3(
        review=SimpleNamespace(
            candidate_id=candidate_id, title=title, hook=hook, review_reason=reason
        ),  # type: ignore[arg-type]
        discovery_candidate=None,  # type: ignore[arg-type]
        boundary_review=None,  # type: ignore[arg-type]
        decision=ReviewDecision.SELECTED,
        publish_status=PublishStatusV3.AUTO,
        start_ms=start_ms,
        end_ms=start_ms + 6_000,
        duration_ms=6_000,
        final_score=90,
        quality_flags=(),
        risk_flags=(),
        validation_notes=(),
    )


def test_global_v3_gate_blocks_selected_title_violation() -> None:
    unsafe = _v3_candidate("cand_ffmpeg", 1_000, title=FFMPEG_TITLE)
    kept = _v3_candidate("cand_keep", 9_000)
    result = ValidatedGlobalReviewV3(
        selected=(unsafe, kept),
        manual_review=(),
        blocked=(),
        rejected=(),
        top_n_excluded=(),
        statistics=GlobalReviewStatisticsV3(
            discovery_candidate_count=2,
            boundary_kept_count=2,
            boundary_repaired_count=0,
            boundary_dropped_count=0,
            eligible_before_top_n_count=2,
            selected_count=2,
            manual_count=0,
            blocked_count=0,
            rejected_count=0,
            top_n_excluded_count=0,
            suspicious_exact_top_n=False,
        ),
        validation_notes=(),
    )
    assert len(global_review_text_errors(result)) == 1
    gated = block_global_review_text_violations(result)
    assert isinstance(gated, ValidatedGlobalReviewV3)
    assert [value.review.candidate_id for value in gated.selected] == ["cand_keep"]
    (blocked,) = gated.blocked
    assert blocked.publish_status == PublishStatusV3.BLOCKED
    assert blocked.decision == ReviewDecision.MANUAL_REVIEW
    assert blocked.validation_notes == (TEXT_GUARD_BLOCK_NOTE,)
    assert gated.statistics.selected_count == 1
    assert gated.statistics.blocked_count == 1
    assert gated.statistics.eligible_before_top_n_count == 1
    assert gated.validation_notes == (f"cand_ffmpeg:{TEXT_GUARD_BLOCK_NOTE}",)
    assert block_global_review_text_violations(gated) is gated


def _legacy_clip(clip_id, start_ms, decision, *, title=SAFE_TITLE, reason=SAFE_REASON):
    return ValidatedGlobalClip(
        clip=SimpleNamespace(  # type: ignore[arg-type]
            clip_id=clip_id,
            title=title,
            hook="练习方法",
            review_reason=reason,
            origin=ClipOrigin.DISCOVERY,
        ),
        decision=decision,
        start_ms=start_ms,
        end_ms=start_ms + 6_000,
        duration_ms=6_000,
        final_score=90,
        validation_notes=(),
    )


def test_legacy_global_gate_rejects_selected_and_manual_violations() -> None:
    selected_unsafe = _legacy_clip("clip_make", 0, ReviewDecision.SELECTED, reason=MAKE_REASON)
    manual_unsafe = _legacy_clip(
        "clip_ffmpeg", 7_000, ReviewDecision.MANUAL_REVIEW, title=FFMPEG_TITLE
    )
    kept = _legacy_clip("clip_keep", 14_000, ReviewDecision.SELECTED)
    result = ValidatedGlobalReview(
        selected=(selected_unsafe, kept),
        manual_review=(manual_unsafe,),
        rejected=(),
        rejected_candidates=(),
        coverage_decisions=(),
        global_review_summary=GlobalReviewStatistics(
            discovery_candidate_count=3,
            globally_recovered_clip_count=0,
            kept_clip_count=3,
            selected_clip_count=2,
            manual_review_clip_count=1,
            rejected_candidate_group_count=0,
            rejected_clip_count=0,
            rejected_topic_count=0,
        ),
        validation_notes=(),
    )
    assert len(global_review_text_errors(result)) == 2
    gated = block_global_review_text_violations(result)
    assert isinstance(gated, ValidatedGlobalReview)
    assert [value.clip.clip_id for value in gated.selected] == ["clip_keep"]
    assert gated.manual_review == ()
    assert [value.clip.clip_id for value in gated.rejected] == ["clip_make", "clip_ffmpeg"]
    assert all(value.decision == ReviewDecision.REJECTED for value in gated.rejected)
    assert all(value.validation_notes == (TEXT_GUARD_REJECT_NOTE,) for value in gated.rejected)
    summary = gated.global_review_summary
    assert (summary.kept_clip_count, summary.selected_clip_count) == (1, 1)
    assert (summary.manual_review_clip_count, summary.rejected_clip_count) == (0, 2)
    assert summary.global_notes[-1] == f"clip_ffmpeg:{TEXT_GUARD_REJECT_NOTE}"


class _Answer(BaseModel):
    value: str


def _record(subject: str, phase: str) -> ProviderCallRecord:
    return ProviderCallRecord(
        call_id=uuid4().hex,
        operation_key="a" * 64,
        subject_id=subject,
        provider="mock",
        operation=f"responses.semantic.global_review.{phase}",
        model="fixture",
        request_count=1,
        retry_count=0,
        latency_ms=1,
        status=ProviderCallStatus.SUCCEEDED,
        called_at=datetime.now(UTC),
    )


def _guarded(value: _Answer) -> _Answer:
    if value.value == "broken":
        raise ValueError("hard schema authority failure")
    raise_for_text_guard(
        edit_plan_text_errors(
            "unit",
            title=("title", SAFE_TITLE),
            hook=("hook", "练习"),
            reason=("review_reason", value.value),
        ),
        accepted=value,
    )
    return value


class _Provider:
    def __init__(self, initial: str, repaired: str | None, *, schema_repaired: bool = False):
        self.initial, self.repaired, self.schema_repaired = initial, repaired, schema_repaired
        self.repairs: list[tuple[str, ...]] = []

    def generate(self, *, subject_id, **_):
        phase = "repair" if self.schema_repaired else "initial"
        return StructuredCallResult(
            output=_Answer(value=self.initial),
            call_records=(_record(subject_id, phase),),
            repaired=self.schema_repaired,
        )

    def repair(self, *, subject_id, validation_errors, **_):
        self.repairs.append(validation_errors)
        assert self.repaired is not None
        return StructuredCallResult(
            output=_Answer(value=self.repaired),
            call_records=(_record(subject_id, "repair"),),
            repaired=True,
        )


def _unit() -> SemanticUnitRequest:
    return SemanticUnitRequest.snapshot(
        subject_id="run.global_review.global",
        payload={"request": 1},
        response_model=_Answer,
        validate=_guarded,
        repair_payload=lambda original, output, errors: {**original, "errors": list(errors)},
    )


def test_executor_spends_the_sole_repair_on_a_guard_hit_and_uses_the_rewrite() -> None:
    provider = _Provider(MAKE_REASON, SAFE_REASON)
    outcome = execute_semantic_unit(_unit(), provider, cancel_requested=lambda: False)
    assert outcome.disposition == "succeeded" and outcome.repair_spent
    assert outcome.validated_output == {"value": SAFE_REASON}
    assert provider.repairs and TEXT_GUARD_ERROR_PREFIX in provider.repairs[0][0]
    assert outcome.validation_events[0]["deferred"] is True


def test_executor_accepts_a_rewrite_that_still_trips_the_guard() -> None:
    provider = _Provider(MAKE_REASON, MAKE_REASON)
    outcome = execute_semantic_unit(_unit(), provider, cancel_requested=lambda: False)
    assert outcome.disposition == "succeeded" and outcome.repair_spent
    assert outcome.validated_output == {"value": MAKE_REASON}
    assert [event["phase"] for event in outcome.validation_events] == ["initial", "repair"]
    assert all(event["deferred"] is True for event in outcome.validation_events)


def test_executor_accepts_a_guard_hit_when_schema_repair_spent_the_repair() -> None:
    provider = _Provider(MAKE_REASON, None, schema_repaired=True)
    outcome = execute_semantic_unit(_unit(), provider, cancel_requested=lambda: False)
    assert outcome.disposition == "succeeded"
    assert outcome.validated_output == {"value": MAKE_REASON}
    assert provider.repairs == []


def test_executor_still_fails_hard_validation_errors_after_repair() -> None:
    provider = _Provider("broken", "broken")
    outcome = execute_semantic_unit(_unit(), provider, cancel_requested=lambda: False)
    assert outcome.disposition == "exhausted"
    assert outcome.failure_code == "STRUCTURED_OUTPUT_INVALID"


def test_validate_or_accept_deferred_only_relaxes_the_deferred_rule() -> None:
    assert validate_or_accept_deferred(_guarded, _Answer(value=MAKE_REASON)).value == MAKE_REASON
    with pytest.raises(ValueError, match="hard schema"):
        validate_or_accept_deferred(_guarded, _Answer(value="broken"))
    with pytest.raises(DeferredValidationError):
        _guarded(_Answer(value=MAKE_REASON))
