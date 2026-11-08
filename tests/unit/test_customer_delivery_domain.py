"""Stage 19a: pure eligibility, override and customer-view rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from liveclip.domain.clip_profile import ClipProfile
from liveclip.domain.customer_delivery import (
    ClipDecision,
    ClipDecisionAction,
    CustomerClipView,
    CustomerDeliveryRuleError,
    CustomerText,
    ImportedClipStatus,
    customer_clip_view,
    effective_customer_text,
    is_deliverable,
    is_selected_for_delivery,
    latest_review_decision,
)

APPROVE = ClipDecisionAction.APPROVE
REJECT = ClipDecisionAction.REJECT
SELECT = ClipDecisionAction.SELECT
DESELECT = ClipDecisionAction.DESELECT
SELECTED = ImportedClipStatus.SELECTED
MANUAL = ImportedClipStatus.MANUAL_REVIEW
TOKEN = "Abc_def-0123456789abcdefABCDEFghijklmnopqrstu"
ORIGINAL = CustomerText(title="原标题", hook="原钩子", summary="原摘要")


def _decisions(*actions: ClipDecisionAction) -> tuple[ClipDecision, ...]:
    return tuple(
        ClipDecision(sequence=index, action=action) for index, action in enumerate(actions, 1)
    )


@pytest.mark.parametrize(
    ("status", "actions", "deliverable"),
    [
        (SELECTED, (), True),
        (SELECTED, (APPROVE,), True),
        (SELECTED, (SELECT,), True),
        (SELECTED, (REJECT,), False),
        (SELECTED, (REJECT, APPROVE), True),
        (SELECTED, (APPROVE, REJECT), False),
        (MANUAL, (), False),
        (MANUAL, (SELECT,), False),
        (MANUAL, (APPROVE,), True),
        (MANUAL, (REJECT,), False),
        (MANUAL, (APPROVE, REJECT), False),
        (MANUAL, (REJECT, APPROVE), True),
        (MANUAL, (APPROVE, SELECT), True),
        (MANUAL, (APPROVE, SELECT, DESELECT), True),
        (MANUAL, (APPROVE, SELECT, REJECT), False),
        (MANUAL, (REJECT, SELECT, DESELECT, SELECT), False),
        (MANUAL, (APPROVE, APPROVE, REJECT, APPROVE), True),
    ],
)
def test_eligibility_truth_table(
    status: ImportedClipStatus,
    actions: tuple[ClipDecisionAction, ...],
    deliverable: bool,
) -> None:
    assert is_deliverable(status, _decisions(*actions)) is deliverable


def test_eligibility_uses_sequence_order_not_input_order() -> None:
    decisions = (
        ClipDecision(sequence=2, action=REJECT),
        ClipDecision(sequence=1, action=APPROVE),
    )
    assert is_deliverable(MANUAL, decisions) is False
    assert is_deliverable(MANUAL, tuple(reversed(decisions))) is False
    later = (*decisions, ClipDecision(sequence=3, action=APPROVE))
    assert is_deliverable(MANUAL, later) is True


def test_selection_decisions_never_count_as_review_decisions() -> None:
    decisions = _decisions(APPROVE, SELECT, DESELECT)
    latest = latest_review_decision(decisions)
    assert latest is not None and latest.action is APPROVE and latest.sequence == 1


def test_duplicate_sequence_numbers_are_rejected() -> None:
    decisions = (
        ClipDecision(sequence=1, action=APPROVE),
        ClipDecision(sequence=1, action=REJECT),
    )
    with pytest.raises(CustomerDeliveryRuleError):
        is_deliverable(MANUAL, decisions)


@pytest.mark.parametrize(
    ("status", "actions", "selected"),
    [
        (MANUAL, (SELECT,), False),
        (MANUAL, (APPROVE,), False),
        (MANUAL, (APPROVE, SELECT), True),
        (MANUAL, (SELECT, APPROVE), False),
        (MANUAL, (APPROVE, SELECT, REJECT, APPROVE), False),
        (MANUAL, (APPROVE, SELECT, REJECT, APPROVE, SELECT), True),
        (MANUAL, (APPROVE, SELECT, APPROVE), False),
        (MANUAL, (APPROVE, DESELECT, SELECT), True),
        (SELECTED, (SELECT, APPROVE), False),
        (SELECTED, (REJECT, APPROVE, SELECT), True),
        (MANUAL, (APPROVE, SELECT, DESELECT), False),
        (MANUAL, (APPROVE, SELECT, REJECT), False),
        (SELECTED, (), False),
        (SELECTED, (SELECT,), True),
        (SELECTED, (SELECT, REJECT), False),
    ],
)
def test_selected_for_delivery_requires_eligibility_and_latest_select(
    status: ImportedClipStatus,
    actions: tuple[ClipDecisionAction, ...],
    selected: bool,
) -> None:
    assert is_selected_for_delivery(status, _decisions(*actions)) is selected


def test_effective_text_is_model_original_without_approval() -> None:
    assert effective_customer_text(ORIGINAL, ()) == ORIGINAL
    assert effective_customer_text(ORIGINAL, _decisions(REJECT, SELECT)) == ORIGINAL


def test_effective_text_uses_latest_approval_overrides_per_field() -> None:
    decisions = (
        ClipDecision(sequence=1, action=APPROVE, title_override="审核标题"),
        ClipDecision(sequence=2, action=SELECT),
    )
    assert effective_customer_text(ORIGINAL, decisions) == CustomerText(
        title="审核标题", hook="原钩子", summary="原摘要"
    )


def test_latest_approval_states_complete_text_and_resets_earlier_overrides() -> None:
    decisions = (
        ClipDecision(
            sequence=1,
            action=APPROVE,
            title_override="第一次标题",
            hook_override="第一次钩子",
        ),
        ClipDecision(sequence=2, action=REJECT),
        ClipDecision(sequence=3, action=APPROVE, summary_override="第二次摘要"),
    )
    assert effective_customer_text(ORIGINAL, decisions) == CustomerText(
        title="原标题", hook="原钩子", summary="第二次摘要"
    )


def test_rejection_after_override_keeps_text_but_blocks_delivery() -> None:
    decisions = (
        ClipDecision(sequence=1, action=APPROVE, title_override="审核标题"),
        ClipDecision(sequence=2, action=REJECT),
    )
    assert is_deliverable(MANUAL, decisions) is False
    assert effective_customer_text(ORIGINAL, decisions).title == "审核标题"


@pytest.mark.parametrize("action", [REJECT, SELECT, DESELECT])
def test_only_approval_may_carry_overrides(action: ClipDecisionAction) -> None:
    with pytest.raises(CustomerDeliveryRuleError, match="only an approval"):
        ClipDecision(sequence=1, action=action, hook_override="改写")


@pytest.mark.parametrize(
    "value",
    ["", " 前导空格", "尾随空格 ", "含\x00字符", "含\x1b字符", "x" * 121],
)
def test_title_override_text_is_bounded_and_printable(value: str) -> None:
    with pytest.raises(CustomerDeliveryRuleError):
        ClipDecision(sequence=1, action=APPROVE, title_override=value)


def test_summary_override_allows_newlines() -> None:
    decision = ClipDecision(sequence=1, action=APPROVE, summary_override="第一行\n第二行")
    assert decision.has_override


def test_non_positive_sequence_is_rejected() -> None:
    with pytest.raises(CustomerDeliveryRuleError):
        ClipDecision(sequence=0, action=APPROVE)


def _view(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "ordinal": 1,
        "profile": ClipProfile.SHORT_HIGHLIGHT,
        "profile_label": "短片",
        "title": "标题",
        "hook": "钩子",
        "summary": "摘要",
        "duration_ms": 61_000,
        "video_href": "clips/short/01-标题.mp4",
        "subtitle_href": "clips/short/01-标题.srt",
    }
    values.update(overrides)
    return values


def test_customer_clip_view_allowlist_is_exact() -> None:
    assert set(CustomerClipView.model_fields) == {
        "ordinal",
        "profile",
        "profile_label",
        "title",
        "hook",
        "summary",
        "duration_ms",
        "video_href",
        "subtitle_href",
    }
    view = customer_clip_view(
        ordinal=2,
        profile=ClipProfile.MINI_LESSON,
        text=CustomerText(title="小课标题", hook="小课钩子", summary="小课摘要"),
        duration_ms=150_000,
        video_href=f"/s/{TOKEN}/clips/2/video",
        subtitle_href=f"/s/{TOKEN}/clips/2/subtitle",
    )
    assert view.profile_label == "小课"
    dumped = view.model_dump(mode="json")
    assert set(dumped) == set(CustomerClipView.model_fields)


@pytest.mark.parametrize(
    "field",
    [
        "score",
        "review_status",
        "routed_status",
        "review_reason",
        "quality_flags",
        "risk_tags",
        "prompt_hashes",
        "candidate_id",
        "video_path",
    ],
)
def test_customer_clip_view_forbids_internal_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        CustomerClipView(**_view(**{field: "internal"}))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "href",
    [
        "clips/short/01-标题.mp4",
        "clips/lesson/12-小课_标题-二.srt",
        "clips/short/001-Title9.mp4",
        f"/s/{TOKEN}/clips/1/video",
        f"/s/{TOKEN}/clips/12/subtitle",
    ],
)
def test_customer_clip_view_accepts_emitted_link_shapes(href: str) -> None:
    assert CustomerClipView(**_view(video_href=href)).video_href == href  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "href",
    [
        "/Users/someone/data/clip.mp4",
        "../escape.mp4",
        "clips/../../escape.mp4",
        "clips/short/../01-a.mp4",
        "file:///Users/someone/clip.mp4",
        "https://example.invalid/clip.mp4",
        "http://example.invalid/clip.mp4",
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "mailto:someone@example.invalid",
        "//example.invalid/clip.mp4",
        "clips\\short\\clip.mp4",
        "clips/short/01-标题.mp4?x=1",
        "clips/short/01-标题.mp4#frag",
        "clips/short/01-<b>.mp4",
        "clips/short/01-a:b.mp4",
        "clips/short/01-标题.exe",
        "clips/short/标题.mp4",
        "clips/other/01-标题.mp4",
        " clips/short/01-标题.mp4",
        "/s/short/clips/1/video",
        f"/s/{TOKEN}/clips/0/video",
        f"/s/{TOKEN}/clips/1/download",
        f"/s/{TOKEN}/clips/1/video/",
        f"/x/{TOKEN}/clips/1/video",
        "",
    ],
)
def test_customer_clip_view_rejects_unsafe_links(href: str) -> None:
    with pytest.raises(ValidationError):
        CustomerClipView(**_view(video_href=href))  # type: ignore[arg-type]


def test_customer_clip_view_label_must_match_profile() -> None:
    with pytest.raises(ValidationError):
        CustomerClipView(**_view(profile_label="小课"))  # type: ignore[arg-type]
