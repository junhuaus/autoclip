"""Stage 19 freeze guard: the dual-profile benchmark closure must not drift.

The benchmark freeze (user decision 2026-11-07) covers only the dual-profile
benchmark closure frozen at ``f525338ed9427b0fcac9925bac6075d60af13e69``
(Stage 18, strict acceptance 2/2 by cold-35 and cold-36). This test pins every
prompt identity the real loaders compute, plus the routing policy and the
algorithm version recorded by the counted runs. The expected values are the
Stage 18b "after" column in ``STATUS.md``. A failure here means a frozen prompt,
routing policy or algorithm changed: that starts a new freeze and a zero
consecutive-PASS count, so it needs an explicit user decision; never re-pin
these values to make the test pass.
"""

from __future__ import annotations

from typing import get_args

import pytest

from liveclip.clipping_skills.dual_profile_v1 import (
    DualProfileStage,
    load_dual_profile_prompt,
    load_dual_profile_variant_link_prompt,
)
from liveclip.domain.clip_profile import ClipProfile
from liveclip.pipeline.dual_profile import (
    DUAL_PROFILE_ALGORITHM_VERSION,
    DUAL_PROFILE_ROUTING_POLICY_VERSION,
)

FREEZE_SHA = "f525338ed9427b0fcac9925bac6075d60af13e69"

STAGE_18B_PROMPT_IDENTITIES: dict[str, str] = {
    "short_highlight.discovery": (
        "c2d9dfc5d9602a6691a7dfdf249f4685ff84950968d6603061952570e70ca1e5"
    ),
    "short_highlight.coverage_audit": (
        "b3237e3dcf88c17f85642127bb7711bbe6f376e1012d5e0d6eb5748df69c564a"
    ),
    "short_highlight.precision_audit": (
        "f955e61abaf482fd594cb875498524bf6ac4d078f3e13663a5378c2d1f47af78"
    ),
    "short_highlight.precision_confirmation": (
        "0784d166170419526247b24427207457ce3b1903634f31482784dc6e7d2297fb"
    ),
    "short_highlight.risk_discovery": (
        "8315d03f096e04eae886cd73cf4d922cd886483e8d84e0d0d5b8450cd9797ccd"
    ),
    "short_highlight.boundary_review": (
        "4c8621c0a77613b6070b3d2aabeaac11519dfbac0bb1e7d0a976eab370c9b939"
    ),
    "short_highlight.global_review": (
        "89cd790f3860e8881fd6ded8c577979fb9698e8fc677c59e343a83b605961543"
    ),
    "short_highlight.global_audit": (
        "070b605413e4caaa9ce1d74bd534eb61d36def4c7db9a453cd991a23c9243a54"
    ),
    "mini_lesson.discovery": ("b93d1d564b1a675bc675f13859dd6a133288fae4bbba0c76434755cebd1c82f8"),
    "mini_lesson.coverage_audit": (
        "80480fb064d1afe7dcc4ea9ade1b930e9c376d9b5d7f6b1057a9890827d07692"
    ),
    "mini_lesson.precision_audit": (
        "0894b7d32611b30d4f344b1f435f2ec4021f27dd3859b1126036969bcaeaec11"
    ),
    "mini_lesson.precision_confirmation": (
        "e2350c1ec657bc1118e399bdf983c8cbe0e9e53d6e2384597daf5c15df58c642"
    ),
    "mini_lesson.risk_discovery": (
        "dd5c1ef7bc839c613f5b5ccaca367a6eff3b9d4de5b7448fbfbf7f5d0cdf1182"
    ),
    "mini_lesson.boundary_review": (
        "5907d96caaf97020891dddf9a017908caed3ec6eb2779f61ae8584bfcbef688c"
    ),
    "mini_lesson.global_review": (
        "af68fc7c175ad07bd879fbc6576f0720c883c66e795229c958ff35f20c1097dd"
    ),
    "mini_lesson.global_audit": (
        "bd7f9654717c8dcafc868f52767d8deebb765268153fd2b2fa7b9f120e522dc9"
    ),
    "variant_link": "def25b05bd987a293cf74d5f964ca00504d8d247cfd8b1d4af17299289152aef",
}

FROZEN_PROFILES = (ClipProfile.SHORT_HIGHLIGHT, ClipProfile.MINI_LESSON)


def _computed_prompt_identities() -> dict[str, str]:
    load_dual_profile_prompt.cache_clear()
    load_dual_profile_variant_link_prompt.cache_clear()
    identities = {
        f"{profile.value}.{stage}": load_dual_profile_prompt(stage, profile).sha256
        for profile in FROZEN_PROFILES
        for stage in get_args(DualProfileStage)
    }
    identities["variant_link"] = load_dual_profile_variant_link_prompt().sha256
    return identities


def test_pin_table_has_exactly_seventeen_identities() -> None:
    assert len(get_args(DualProfileStage)) == 8
    assert len(STAGE_18B_PROMPT_IDENTITIES) == 17
    assert len(set(STAGE_18B_PROMPT_IDENTITIES.values())) == 17


def test_all_seventeen_prompt_identities_match_the_frozen_stage_18b_table() -> None:
    computed = _computed_prompt_identities()

    assert computed.keys() == STAGE_18B_PROMPT_IDENTITIES.keys()
    mismatches = {
        name: computed[name]
        for name, expected in STAGE_18B_PROMPT_IDENTITIES.items()
        if computed[name] != expected
    }
    assert mismatches == {}, (
        f"dual-profile prompt identities drifted from freeze {FREEZE_SHA}: {mismatches}"
    )


@pytest.mark.parametrize("name", sorted(STAGE_18B_PROMPT_IDENTITIES))
def test_each_prompt_identity_is_pinned(name: str) -> None:
    assert _computed_prompt_identities()[name] == STAGE_18B_PROMPT_IDENTITIES[name]


def test_routing_policy_is_frozen_v9() -> None:
    assert DUAL_PROFILE_ROUTING_POLICY_VERSION == "quality-gate-risk-routing-v9"


def test_algorithm_version_is_frozen_direct_v1() -> None:
    assert DUAL_PROFILE_ALGORITHM_VERSION == "dual-profile-direct-v1"
