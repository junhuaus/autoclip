# ruff: noqa: RUF001, RUF003
"""Pure customer-delivery rules for imported dual-profile clips (Stage 19).

An imported clip is immutable evidence from one dual-profile run: its routed
status (``selected`` or ``manual_review``) and its model-written title, hook
and summary never change. Reviewer decisions are an append-only, totally
ordered sequence per clip. Everything the customer may see is derived here from
those two inputs; nothing in this module touches storage.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from liveclip.domain.clip_profile import ClipProfile

TITLE_MAX_CHARS = 120
HOOK_MAX_CHARS = 600
SUMMARY_MAX_CHARS = 1_200

PROFILE_LABELS: dict[ClipProfile, Literal["短片", "小课"]] = {
    ClipProfile.SHORT_HIGHLIGHT: "短片",
    ClipProfile.MINI_LESSON: "小课",
}


class CustomerDeliveryRuleError(ValueError):
    """A reviewer decision or customer view violates the delivery contract."""


class ImportedClipStatus(StrEnum):
    """Routing outcome recorded by the dual-profile run; ``blocked`` is never imported."""

    SELECTED = "selected"
    MANUAL_REVIEW = "manual_review"


class ClipDecisionAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    SELECT = "select"
    DESELECT = "deselect"


_REVIEW_ACTIONS = frozenset({ClipDecisionAction.APPROVE, ClipDecisionAction.REJECT})
_SELECTION_ACTIONS = frozenset({ClipDecisionAction.SELECT, ClipDecisionAction.DESELECT})


@dataclass(frozen=True, slots=True)
class CustomerText:
    title: str
    hook: str
    summary: str


@dataclass(frozen=True, slots=True)
class ClipDecision:
    """One append-only reviewer decision; ``sequence`` orders decisions per clip."""

    sequence: int
    action: ClipDecisionAction
    title_override: str | None = None
    hook_override: str | None = None
    summary_override: str | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise CustomerDeliveryRuleError("decision sequence must be positive")
        if self.action is not ClipDecisionAction.APPROVE and self.has_override:
            raise CustomerDeliveryRuleError("only an approval may override customer text")
        for value, limit in (
            (self.title_override, TITLE_MAX_CHARS),
            (self.hook_override, HOOK_MAX_CHARS),
            (self.summary_override, SUMMARY_MAX_CHARS),
        ):
            if value is not None:
                validate_customer_text_field(value, max_chars=limit)

    @property
    def has_override(self) -> bool:
        return any(
            value is not None
            for value in (self.title_override, self.hook_override, self.summary_override)
        )


def validate_customer_text_field(value: str, *, max_chars: int) -> str:
    """Accept bounded, trimmed, printable customer text (newlines allowed)."""

    if not value or value != value.strip():
        raise CustomerDeliveryRuleError("customer text must be non-empty and trimmed")
    if len(value) > max_chars:
        raise CustomerDeliveryRuleError("customer text exceeds its length limit")
    for character in value:
        category = unicodedata.category(character)
        if category == "Cc" and character not in "\n\t":
            raise CustomerDeliveryRuleError("customer text contains a control character")
        if category in {"Cf", "Cs", "Co"}:
            # Format characters include bidi overrides/isolates (U+202A-U+202E,
            # U+2066-U+2069) and zero-width characters (U+200B-U+200D, U+2060,
            # U+FEFF), which can disguise customer-visible text.
            raise CustomerDeliveryRuleError(
                "customer text contains an invisible or formatting character"
            )
    return value


def ordered_decisions(decisions: Iterable[ClipDecision]) -> tuple[ClipDecision, ...]:
    values = tuple(sorted(decisions, key=lambda value: value.sequence))
    sequences = [value.sequence for value in values]
    if len(sequences) != len(set(sequences)):
        raise CustomerDeliveryRuleError("decision sequence numbers must be unique per clip")
    return values


def latest_review_decision(decisions: Iterable[ClipDecision]) -> ClipDecision | None:
    """The latest approve/reject decision, ignoring selection decisions."""

    reviews = [value for value in ordered_decisions(decisions) if value.action in _REVIEW_ACTIONS]
    return reviews[-1] if reviews else None


def latest_approval(decisions: Iterable[ClipDecision]) -> ClipDecision | None:
    approvals = [
        value
        for value in ordered_decisions(decisions)
        if value.action is ClipDecisionAction.APPROVE
    ]
    return approvals[-1] if approvals else None


def is_deliverable(status: ImportedClipStatus, decisions: Iterable[ClipDecision]) -> bool:
    """Deliverable iff ``selected``, or ``manual_review`` whose latest review is approve.

    Automatically selected clips need no approval; an explicit later rejection
    still removes them, because the customer must never receive a clip a
    reviewer rejected.
    """

    latest = latest_review_decision(decisions)
    if latest is not None and latest.action is ClipDecisionAction.REJECT:
        return False
    if status is ImportedClipStatus.SELECTED:
        return True
    return latest is not None and latest.action is ClipDecisionAction.APPROVE


def is_selected_for_delivery(
    status: ImportedClipStatus,
    decisions: Iterable[ClipDecision],
) -> bool:
    """Chosen for the next customer delivery.

    The clip must be deliverable, and the latest selection decision made after
    the clip's latest review decision (approve or reject) must be ``select``.
    A later review voids earlier selections: reject, or reject then approve,
    requires a fresh ``select``.
    """

    values = ordered_decisions(decisions)
    if not is_deliverable(status, values):
        return False
    latest_review = latest_review_decision(values)
    floor = latest_review.sequence if latest_review is not None else 0
    selections = [
        value for value in values if value.action in _SELECTION_ACTIONS and value.sequence > floor
    ]
    return bool(selections) and selections[-1].action is ClipDecisionAction.SELECT


def effective_customer_text(
    original: CustomerText,
    decisions: Iterable[ClipDecision],
) -> CustomerText:
    """Latest approval's override per field, else the immutable model original.

    Each approval states the complete customer text: a field that the latest
    approval does not override falls back to the model original, even if an
    earlier approval overrode it.
    """

    approval = latest_approval(decisions)
    if approval is None:
        return original
    return CustomerText(
        title=approval.title_override if approval.title_override is not None else original.title,
        hook=approval.hook_override if approval.hook_override is not None else original.hook,
        summary=(
            approval.summary_override if approval.summary_override is not None else original.summary
        ),
    )


# Customer-text meta-note guard (Stage 19d, Controller decision 2026-11-07).
# Model-written summaries sometimes contain reviewer-style notes ("…疑为转写错误",
# "…纳入后会超过时长上限，因此该单元…结束") or narration of how a clip ends
# ("以“OK”收束"). Those must not reach a customer unedited. The patterns live
# here only; each entry is (kind, compiled pattern, short Chinese message).
# "strong" warnings block an approval unless the reviewer explicitly keeps the
# text (acknowledge_warnings); "narration" warnings are advisory only.
WarningKind = Literal["strong", "narration"]
CustomerTextField = Literal["title", "hook", "summary"]
CUSTOMER_TEXT_WARNING_PATTERNS: tuple[tuple[WarningKind, re.Pattern[str], str], ...] = (
    ("strong", re.compile(r"误?转写"), "提及转写/误转写，属于审核备注"),
    ("strong", re.compile(r"疑为|疑似"), "“疑为/疑似”是审核推测，不应给客户看"),
    ("strong", re.compile(r"ASR", re.IGNORECASE), "提及 ASR 语音识别"),
    ("strong", re.compile(r"字幕(?:中|作|误作)|误作"), "提及字幕识别差异"),
    ("strong", re.compile(r"时长上限"), "提及切片时长上限"),
    ("strong", re.compile(r"纳入后"), "提及切片取舍（纳入后…）"),
    ("strong", re.compile(r"(?:该|本|这一?)单元"), "提及切片单元"),
    ("strong", re.compile(r"片段在[^。；;！!？?\n]{0,40}?结束"), "描述片段在哪里结束"),
    ("strong", re.compile(r"课程片段"), "提及课程片段"),
    ("strong", re.compile(r"不包含后面"), "说明片段未包含的内容"),
    ("strong", re.compile(r"区间(?:内|之内|之后|之前|以外|外)"), "提及切片区间"),
    ("strong", re.compile(r"\bcue\b", re.IGNORECASE), "包含内部字段 cue"),
    ("strong", re.compile(r"\d+\s*ms\b", re.IGNORECASE), "包含毫秒时间戳"),
    ("strong", re.compile(r"候选"), "提及候选切片"),
    ("strong", re.compile(r"边界"), "提及切片边界"),
    ("narration", re.compile(r"以[^。；;！!？?\n]{0,40}?收束"), "叙述片段如何收尾"),
    ("narration", re.compile(r"(?<!以)收束"), "叙述片段如何收尾"),
    ("narration", re.compile(r"约\s*\d+\s*秒"), "提及片段时长"),
)


@dataclass(frozen=True, slots=True)
class CustomerTextWarning:
    field: CustomerTextField
    kind: WarningKind
    start: int
    end: int
    match: str
    message: str


def customer_text_warnings(title: str, hook: str, summary: str) -> tuple[CustomerTextWarning, ...]:
    """Reviewer-style notes in customer-visible text, ordered by field then offset.

    Overlapping matches of the same kind are reported once (the earliest,
    longest match wins), so one note yields one warning per kind.
    """

    found: list[CustomerTextWarning] = []
    for field, text in (("title", title), ("hook", hook), ("summary", summary)):
        taken: dict[WarningKind, list[tuple[int, int]]] = {"strong": [], "narration": []}
        candidates = sorted(
            (
                (match.start(), -(match.end() - match.start()), kind, match, message)
                for kind, pattern, message in CUSTOMER_TEXT_WARNING_PATTERNS
                for match in pattern.finditer(text)
                if match.end() > match.start()
            ),
            key=lambda value: (value[0], value[1]),
        )
        for start, _, kind, match, message in candidates:
            end = match.end()
            if any(start < used_end and used_start < end for used_start, used_end in taken[kind]):
                continue
            taken[kind].append((start, end))
            found.append(
                CustomerTextWarning(
                    field=field,  # type: ignore[arg-type]
                    kind=kind,
                    start=start,
                    end=end,
                    match=match.group(0),
                    message=message,
                )
            )
    order = {"title": 0, "hook": 1, "summary": 2}
    return tuple(sorted(found, key=lambda value: (order[value.field], value.start, value.kind)))


def strong_customer_text_warnings(text: CustomerText) -> tuple[CustomerTextWarning, ...]:
    return tuple(
        value
        for value in customer_text_warnings(text.title, text.hook, text.summary)
        if value.kind == "strong"
    )


_SHARE_HREF = re.compile(r"/s/[A-Za-z0-9_-]{16,128}/clips/[1-9][0-9]{0,4}/(?:video|subtitle)")
_OFFLINE_HREF_PREFIXES = ("clips/short/", "clips/lesson/")
_OFFLINE_SUFFIXES = (".mp4", ".srt")
_OFFLINE_PROFILE_FOLDERS = {
    ClipProfile.SHORT_HIGHLIGHT: "clips/short/",
    ClipProfile.MINI_LESSON: "clips/lesson/",
}


def _is_offline_filename(name: str) -> bool:
    stem, _, suffix = name.rpartition(".")
    if not stem or f".{suffix}" not in _OFFLINE_SUFFIXES or len(name.encode("utf-8")) > 120:
        return False
    number, dash, title = stem.partition("-")
    if not (number.isascii() and number.isdigit() and 2 <= len(number) <= 4 and dash and title):
        return False
    return all(
        character in "-_" or unicodedata.category(character)[0] in {"L", "M", "N"}
        for character in title
    )


def _validate_href(value: str) -> str:
    """Accept only the two link shapes customer packages and share pages emit.

    Offline package: ``clips/short|lesson/NN-<safe title>.mp4|.srt`` (letters,
    marks, digits, ``-`` and ``_`` only). Share page:
    ``/s/<token>/clips/<ordinal>/video|subtitle``. Anything else, including every
    URL scheme (``javascript:``, ``data:``, ``mailto:``, ``http(s):``, ``file:``),
    protocol-relative ``//`` links, backslashes, dot segments, queries and
    fragments, is rejected.
    """

    if _SHARE_HREF.fullmatch(value):
        return value
    for prefix in _OFFLINE_HREF_PREFIXES:
        if value.startswith(prefix) and _is_offline_filename(value[len(prefix) :]):
            return value
    raise ValueError("customer link is not a safe relative or share-scoped path")


class CustomerClipView(BaseModel):
    """The complete, allowlisted set of fields an end customer may see for one clip.

    Internal evidence (score, flags, risks, routing status, review reasons,
    prompt hashes, candidate IDs, local paths) has no field here, and
    ``extra="forbid"`` rejects any attempt to add one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    ordinal: int = Field(ge=1, le=10_000)
    profile: ClipProfile
    profile_label: Literal["短片", "小课"]
    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    hook: str = Field(min_length=1, max_length=HOOK_MAX_CHARS)
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX_CHARS)
    duration_ms: int = Field(gt=0)
    video_href: str = Field(min_length=1, max_length=500)
    subtitle_href: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_view(self) -> CustomerClipView:
        if PROFILE_LABELS[self.profile] != self.profile_label:
            raise ValueError("customer profile label differs from the clip profile")
        for value, limit in (
            (self.title, TITLE_MAX_CHARS),
            (self.hook, HOOK_MAX_CHARS),
            (self.summary, SUMMARY_MAX_CHARS),
        ):
            try:
                validate_customer_text_field(value, max_chars=limit)
            except CustomerDeliveryRuleError as exc:
                raise ValueError(str(exc)) from exc
        _validate_href(self.video_href)
        _validate_href(self.subtitle_href)
        folder = _OFFLINE_PROFILE_FOLDERS[self.profile]
        for href in (self.video_href, self.subtitle_href):
            if href.startswith("clips/") and not href.startswith(folder):
                raise ValueError("customer link folder differs from the clip profile")
        return self


def customer_clip_view(
    *,
    ordinal: int,
    profile: ClipProfile,
    text: CustomerText,
    duration_ms: int,
    video_href: str,
    subtitle_href: str,
) -> CustomerClipView:
    return CustomerClipView(
        ordinal=ordinal,
        profile=profile,
        profile_label=PROFILE_LABELS[profile],
        title=text.title,
        hook=text.hook,
        summary=text.summary,
        duration_ms=duration_ms,
        video_href=video_href,
        subtitle_href=subtitle_href,
    )


__all__ = [
    "CUSTOMER_TEXT_WARNING_PATTERNS",
    "HOOK_MAX_CHARS",
    "PROFILE_LABELS",
    "SUMMARY_MAX_CHARS",
    "TITLE_MAX_CHARS",
    "ClipDecision",
    "ClipDecisionAction",
    "CustomerClipView",
    "CustomerDeliveryRuleError",
    "CustomerText",
    "CustomerTextWarning",
    "ImportedClipStatus",
    "customer_clip_view",
    "customer_text_warnings",
    "effective_customer_text",
    "is_deliverable",
    "is_selected_for_delivery",
    "latest_approval",
    "latest_review_decision",
    "ordered_decisions",
    "strong_customer_text_warnings",
    "validate_customer_text_field",
]
