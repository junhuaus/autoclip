"""Guard-safe construction of persisted pipeline EditPlans from reviewed model text.

The persisted pipeline edit stages copy the Global Review title, hook and reason
into ``EditPlan``. Those fields are product text (web review, release description,
review package and burned title), so they stay model-authored, but every one of
them must pass the unchanged ``reject_executable_text`` guard that ``EditPlan``
enforces.

A hit is handled in two steps:

1. The stage validator raises ``DeferredValidationError`` after every shared
   validator has passed, so the existing repair loop asks the model to rewrite the
   text once.
2. When no repair remains, the loop accepts the output and the functions below
   deterministically block (or, for the legacy contract without a blocked bucket,
   reject) only the affected candidate. Python never rewrites model text and never
   promotes another candidate.

The shared validators (``validate_profile_global_review_v4``,
``validate_global_review_v3``, ``validate_global_review``) are intentionally
untouched because dual-profile evaluation and benchmarks share them.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence

from pydantic import ValidationError

from liveclip.domain.edit_plan import (
    CaptionTemplate,
    EditPlan,
    Effect,
    Layout,
    executable_text_match,
)
from liveclip.pipeline.semantic_executor import DeferredValidationError
from liveclip.pipeline.semantic_global import (
    ClipOrigin,
    PublishStatusV3,
    ReviewDecision,
    ValidatedCandidateReviewV3,
    ValidatedGlobalClip,
    ValidatedGlobalReview,
    ValidatedGlobalReviewV3,
)
from liveclip.pipeline.semantic_profiles import (
    CandidateDispositionV4,
    ValidatedCandidateV4,
    ValidatedProfileResultV4,
)

EDIT_PLAN_HOOK_CHARACTERS = 80
EDIT_PLAN_REASON_CHARACTERS = 240
EDIT_PLAN_RISK_FLAG_LIMIT = 8
PROFILE_V4_PROMPT_VERSION = "semantic_topic_chain_v1.global_review"
TEXT_GUARD_BLOCK_NOTE = "deterministic_text_guard_gate"
TEXT_GUARD_REJECT_NOTE = "deterministic_text_guard_changed_kept_to_rejected"
TEXT_GUARD_ERROR_PREFIX = "Deterministic text guard: "
# The instruction comes first so that a legacy contract, which truncates the repair
# message to 240 characters, always keeps it; field details follow.
TEXT_GUARD_INSTRUCTION = (
    "rewrite each listed field as plain prose with the same meaning; "
    "no command words, file paths or shell syntax."
)
TEXT_GUARD_TOKEN_CHARACTERS = 40

_PROBE_FIELDS: dict[str, object] = {
    "candidate_id": "text_guard_probe",
    "source_start_ms": 0,
    "source_end_ms": 1,
    "score": 0.0,
    "title": "probe",
    "hook": "probe",
    "reason": "probe",
    "layout": Layout.CENTER_CROP,
    "caption_template": CaptionTemplate.CLEAN_ZH_V1,
    "effect": Effect.NONE,
    "risk_flags": (),
    "prompt_version": "text-guard-probe",
    "model": "text-guard-probe",
    "degraded": False,
}


def build_ai_edit_plan(
    *,
    candidate_id: str,
    source_start_ms: int,
    source_end_ms: int,
    score: float,
    title: str,
    hook: str,
    reason: str,
    risk_flags: tuple[str, ...],
    prompt_version: str,
    model: str,
) -> EditPlan:
    """The single AI EditPlan construction used by every build and replay site."""

    return EditPlan(
        candidate_id=candidate_id,
        source_start_ms=source_start_ms,
        source_end_ms=source_end_ms,
        score=score,
        title=title,
        hook=hook[:EDIT_PLAN_HOOK_CHARACTERS],
        reason=reason[:EDIT_PLAN_REASON_CHARACTERS],
        layout=Layout.CENTER_CROP,
        caption_template=CaptionTemplate.CLEAN_ZH_V1,
        effect=Effect.NONE,
        risk_flags=risk_flags,
        prompt_version=prompt_version,
        model=model,
        degraded=False,
    )


def profile_v4_edit_plan(
    selected: ValidatedCandidateV4, *, candidate_id: str, model: str
) -> EditPlan:
    review = selected.review
    return build_ai_edit_plan(
        candidate_id=candidate_id,
        source_start_ms=selected.start_ms,
        source_end_ms=selected.end_ms,
        score=float(review.total_score),
        title=review.title,
        hook=review.learning_outcome,
        reason=review.review_reason,
        risk_flags=tuple(value.value for value in review.risk_flags)[:EDIT_PLAN_RISK_FLAG_LIMIT],
        prompt_version=PROFILE_V4_PROMPT_VERSION,
        model=model,
    )


def edit_plan_text_errors(
    candidate_id: str,
    *,
    title: tuple[str, str],
    hook: tuple[str, str],
    reason: tuple[str, str],
) -> tuple[str, ...]:
    """Return one finding per text field that EditPlan would reject.

    Each pair is ``(source field name, model text)``. Every field is probed through
    the real ``EditPlan`` model with safe values elsewhere, so the check mirrors
    its exact text constraints (stripping, length, display normalization and the
    unchanged executable-text guard) on the same truncated value. A finding names
    the candidate, the source field and the matched substring of the model's own
    field text; ``text_guard_message`` turns findings into the repair message.
    """

    errors: list[str] = []
    for plan_field, (source_field, value), limit in (
        ("title", title, None),
        ("hook", hook, EDIT_PLAN_HOOK_CHARACTERS),
        ("reason", reason, EDIT_PLAN_REASON_CHARACTERS),
    ):
        text = value if limit is None else value[:limit]
        try:
            EditPlan.model_validate({**_PROBE_FIELDS, plan_field: text})
        except ValidationError:
            scope = "" if limit is None else f" (first {limit} chars)"
            token = executable_text_match(text.strip())
            detail = (
                "fails the EditPlan text limits"
                if token is None
                else "matched "
                + json.dumps(token[:TEXT_GUARD_TOKEN_CHARACTERS], ensure_ascii=False)
            )
            errors.append(f"candidate {candidate_id} {source_field}{scope} {detail}")
    return tuple(errors)


def text_guard_message(errors: Sequence[str]) -> str:
    """One repair message: prefix and instruction first, then every finding."""

    return f"{TEXT_GUARD_ERROR_PREFIX}{TEXT_GUARD_INSTRUCTION} " + "; ".join(errors)


def _profile_v4_candidate_errors(value: ValidatedCandidateV4) -> tuple[str, ...]:
    review = value.review
    return edit_plan_text_errors(
        review.candidate_id,
        title=("title", review.title),
        hook=("learning_outcome", review.learning_outcome),
        reason=("review_reason", review.review_reason),
    )


def _global_v3_candidate_errors(value: ValidatedCandidateReviewV3) -> tuple[str, ...]:
    review = value.review
    return edit_plan_text_errors(
        review.candidate_id,
        title=("title", review.title),
        hook=("hook", review.hook),
        reason=("review_reason", review.review_reason),
    )


def _global_clip_errors(value: ValidatedGlobalClip) -> tuple[str, ...]:
    clip = value.clip
    return edit_plan_text_errors(
        clip.clip_id,
        title=("title", clip.title),
        hook=("hook", clip.hook),
        reason=("review_reason", clip.review_reason),
    )


def profile_v4_text_errors(result: ValidatedProfileResultV4) -> tuple[str, ...]:
    """Only selected candidates become EditPlans in the V4/V5 Profile paths."""

    return tuple(
        error for value in result.selected for error in _profile_v4_candidate_errors(value)
    )


def global_review_text_errors(
    result: ValidatedGlobalReview | ValidatedGlobalReviewV3,
) -> tuple[str, ...]:
    """v3 materializes selected rows; the legacy contract also materializes manual rows."""

    if isinstance(result, ValidatedGlobalReviewV3):
        return tuple(
            error for value in result.selected for error in _global_v3_candidate_errors(value)
        )
    return tuple(
        error
        for value in (*result.selected, *result.manual_review)
        for error in _global_clip_errors(value)
    )


def raise_for_text_guard(errors: Sequence[str], *, accepted: object) -> None:
    """Request the repair loop's rewrite; without a repair the output is accepted."""

    if errors:
        raise DeferredValidationError(text_guard_message(errors), accepted=accepted)


def block_profile_v4_text_violations(result: ValidatedProfileResultV4) -> ValidatedProfileResultV4:
    """Move each selected candidate whose text EditPlan rejects to ``blocked``."""

    violating = {
        value.review.candidate_id
        for value in result.selected
        if _profile_v4_candidate_errors(value)
    }
    if not violating:
        return result
    selected = tuple(
        value for value in result.selected if value.review.candidate_id not in violating
    )
    demoted = tuple(
        value.model_copy(
            update={
                "disposition": CandidateDispositionV4.BLOCKED,
                "validation_notes": (*value.validation_notes, TEXT_GUARD_BLOCK_NOTE),
            }
        )
        for value in result.selected
        if value.review.candidate_id in violating
    )
    blocked = tuple(
        sorted(
            (*result.blocked, *demoted),
            key=lambda value: (value.start_ms, value.review.candidate_id),
        )
    )
    statistics = result.statistics.model_copy(
        update={
            "qualified_before_top_n": result.statistics.qualified_before_top_n - len(demoted),
            "selected_count": len(selected),
            "blocked_count": len(blocked),
        }
    )
    return result.model_copy(
        update={"selected": selected, "blocked": blocked, "statistics": statistics}
    )


def block_global_review_text_violations(
    result: ValidatedGlobalReview | ValidatedGlobalReviewV3,
) -> ValidatedGlobalReview | ValidatedGlobalReviewV3:
    if isinstance(result, ValidatedGlobalReviewV3):
        return _block_global_v3_text_violations(result)
    return _reject_global_text_violations(result)


def _block_global_v3_text_violations(result: ValidatedGlobalReviewV3) -> ValidatedGlobalReviewV3:
    violating = {
        value.review.candidate_id for value in result.selected if _global_v3_candidate_errors(value)
    }
    if not violating:
        return result
    selected = tuple(
        value for value in result.selected if value.review.candidate_id not in violating
    )
    # A v3 blocked row is a non-selected, non-rejected row with publish status blocked.
    demoted = tuple(
        dataclasses.replace(
            value,
            decision=ReviewDecision.MANUAL_REVIEW,
            publish_status=PublishStatusV3.BLOCKED,
            validation_notes=(*value.validation_notes, TEXT_GUARD_BLOCK_NOTE),
        )
        for value in result.selected
        if value.review.candidate_id in violating
    )
    blocked = tuple(
        sorted(
            (*result.blocked, *demoted),
            key=lambda value: (value.start_ms, value.review.candidate_id),
        )
    )
    statistics = result.statistics.model_copy(
        update={
            "eligible_before_top_n_count": (
                result.statistics.eligible_before_top_n_count - len(demoted)
            ),
            "selected_count": len(selected),
            "blocked_count": len(blocked),
            # Recomputed exactly: the validator sets it when the discovery count and
            # the eligible count both equal the Top-N ceiling, so it was true only
            # with eligible == discovery count, and any demotion breaks that. The
            # ceiling itself is not needed and no count can rise.
            "suspicious_exact_top_n": (
                result.statistics.suspicious_exact_top_n
                and result.statistics.eligible_before_top_n_count - len(demoted)
                == result.statistics.discovery_candidate_count
            ),
        }
    )
    return dataclasses.replace(
        result,
        selected=selected,
        blocked=blocked,
        statistics=statistics,
        validation_notes=(
            *result.validation_notes,
            *(f"{value.review.candidate_id}:{TEXT_GUARD_BLOCK_NOTE}" for value in demoted),
        ),
    )


def _reject_global_text_violations(result: ValidatedGlobalReview) -> ValidatedGlobalReview:
    """The legacy contract has no blocked bucket; rejection keeps the clip undelivered."""

    violating = {
        value.clip.clip_id
        for value in (*result.selected, *result.manual_review)
        if _global_clip_errors(value)
    }
    if not violating:
        return result
    selected = tuple(value for value in result.selected if value.clip.clip_id not in violating)
    manual = tuple(value for value in result.manual_review if value.clip.clip_id not in violating)
    demoted = tuple(
        dataclasses.replace(
            value,
            decision=ReviewDecision.REJECTED,
            validation_notes=(*value.validation_notes, TEXT_GUARD_REJECT_NOTE),
        )
        for value in (*result.selected, *result.manual_review)
        if value.clip.clip_id in violating
    )
    rejected = tuple(
        sorted(
            (*result.rejected, *demoted),
            key=lambda value: (value.start_ms, value.clip.clip_id),
        )
    )
    kept = (*selected, *manual)
    notes = tuple(f"{value.clip.clip_id}:{TEXT_GUARD_REJECT_NOTE}" for value in demoted)
    summary = result.global_review_summary.model_copy(
        update={
            "globally_recovered_clip_count": sum(
                value.clip.origin == ClipOrigin.GLOBAL_REVIEW_RECOVERY for value in kept
            ),
            "kept_clip_count": len(kept),
            "selected_clip_count": len(selected),
            "manual_review_clip_count": len(manual),
            "rejected_clip_count": len(rejected),
            "global_notes": (*result.global_review_summary.global_notes, *notes)[-60:],
        }
    )
    return dataclasses.replace(
        result,
        selected=selected,
        manual_review=manual,
        rejected=rejected,
        global_review_summary=summary,
        validation_notes=(*result.validation_notes, *notes),
    )
