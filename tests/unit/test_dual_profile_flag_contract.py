"""Stage 12: the dual-profile flag contract in prompts matches the code."""

from __future__ import annotations

import re

import pytest

from liveclip.clipping_skills.dual_profile_v1 import load_dual_profile_prompt
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    AUTO_BLOCKING_QUALITY_FLAGS,
    MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS,
    DualQualityFlag,
)

GATED_LABEL = "Gated flags (Python forces `blocked`):"
ADVISORY_LABEL = "Advisory flags (Python only forbids `selected`):"


def _text(stage: str, profile: ClipProfile) -> str:
    return " ".join(load_dual_profile_prompt(stage, profile).instructions.split())


def _listed(text: str, label: str) -> set[str]:
    assert text.count(label) == 1, label
    sentence = text.split(label, 1)[1].split(".", 1)[0]
    return set(re.findall(r"`([a-z_]+)`", sentence))


@pytest.mark.parametrize("stage", ["global_review", "global_audit"])
@pytest.mark.parametrize("profile", list(ClipProfile))
def test_review_prompts_list_exactly_the_gated_and_advisory_flags(
    stage: str, profile: ClipProfile
) -> None:
    text = _text(stage, profile)
    gated = {flag.value for flag in MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS}
    advisory = {
        flag.value for flag in AUTO_BLOCKING_QUALITY_FLAGS - MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS
    }
    assert _listed(text, GATED_LABEL) == gated
    assert _listed(text, ADVISORY_LABEL) == advisory
    assert gated | advisory == {flag.value for flag in DualQualityFlag}
    assert not gated & advisory
    # The old over-claim drove coherent advisory-only candidates to `blocked`.
    assert "enforces every unresolved flag" not in text
    assert "Boundary Review quality flags are cumulative" in text
    assert "state the disagreement in `review_reason`" in text


def test_advisory_set_is_the_documented_context_and_title_flags() -> None:
    assert {
        DualQualityFlag.CONTEXT_DEPENDENT_OPENING,
        DualQualityFlag.MISSING_REQUIRED_PRIOR_STEPS,
        DualQualityFlag.SOURCE_TITLE_MISMATCH,
    } == AUTO_BLOCKING_QUALITY_FLAGS - MANUAL_REVIEW_BLOCKING_QUALITY_FLAGS


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_boundary_prompt_states_the_opening_flag_invariant(profile: ClipProfile) -> None:
    text = _text("boundary_review", profile)
    assert (
        "A review item that keeps `context_dependent_opening` must set `opening_complete` to false"
        in text
    )


@pytest.mark.parametrize("profile", list(ClipProfile))
def test_audit_prompt_allows_duplicate_pairs_through_a_shared_representative(
    profile: ClipProfile,
) -> None:
    text = _text("global_audit", profile)
    assert "duplicates of the same third representative" in text
