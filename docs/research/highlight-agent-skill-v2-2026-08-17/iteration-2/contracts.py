#!/usr/bin/env python3
# ruff: noqa: RUF001
"""Strict iteration-2 research contracts and deterministic highlight gates."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

CONTRACT_VERSION = "liveclip-highlight-agent-v2.iteration-2"
QUOTE_VALIDATOR_VERSION = "normalized-exact-substring-v2"
PORTFOLIO_ALGORITHM_VERSION = "quality-adaptive-topic-portfolio-v3"

DANGEROUS_MODEL_TEXT_RE = re.compile(
    r"(?ix)"
    r"(?:https?://|file://|```|\$[A-Z_][A-Z0-9_]*|(?:^|\s)~?/[^\s]+|[A-Z]:\\)"
    r"|(?:(?:^|[\s\"'])\.\.?/[^\s]+)"
    r"|(?:\b(?:bearer\s+[A-Za-z0-9._~+/=-]{8,}|sk-or-v1-[A-Za-z0-9_-]{8,}|"
    r"sk-[A-Za-z0-9_-]{12,}|[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET)\s*=))"
    r"|(?:\b(?:rm\s+-[a-z]*r[a-z]*f|sudo\s+|curl\s+-|wget\s+|chmod\s+|"
    r"chown\s+|echo\s+\S+|bash\s+(?:-c|[^\s]+)|zsh\s+(?:-c|[^\s]+)|"
    r"sh\s+-c|python\d*\s+(?:-c|[^\s]+\.py)|node\s+(?:-e|[^\s]+\.js)|"
    r"powershell\s+-|cmd\.exe\s+/|ffmpeg\s+-|ffprobe\s+-)\b)"
    r"|(?:\b(?:drop\s+(?:table|database)|create\s+table|alter\s+table|"
    r"truncate\s+table|insert\s+into|delete\s+from|update\s+.+\s+set|"
    r"select\s+.+\s+from|exec(?:ute)?\s+\S+)\b)"
    r"|(?:\[[0-9]+:[av]\]|(?:scale|crop|overlay|drawtext)\s*=)"
    r"|(?:ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|<\/?system>|tool_call)"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="after")
    def _safe_model_owned_text(self) -> StrictModel:
        def values(value: Any) -> Iterable[str]:
            if isinstance(value, str):
                yield value
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from values(child)
            elif isinstance(value, dict):
                for child in value.values():
                    yield from values(child)

        for field_name in type(self).model_fields:
            for value in values(getattr(self, field_name)):
                if value and not value.strip():
                    raise ValueError("model-owned strings cannot contain only whitespace")
                if any(unicodedata.category(character) == "Cf" for character in value):
                    raise ValueError("model-owned strings cannot contain format controls")
                if DANGEROUS_MODEL_TEXT_RE.search(value):
                    raise ValueError("model-owned strings cannot contain executable material")
        return self


class CandidateDisposition(StrEnum):
    ASSESSABLE = "assessable"
    UNUSABLE = "unusable"


class UnusableReason(StrEnum):
    NONE = "none"
    FRAGMENT_ONLY = "fragment_only"
    CONTEXT_DEPENDENT = "context_dependent"
    ASR_UNINTELLIGIBLE = "asr_unintelligible"
    UNSAFE_TO_PUBLISH = "unsafe_to_publish"


class AssessmentConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class UncertaintyFlag(StrEnum):
    ASR_AMBIGUITY = "asr_ambiguity"
    MISSING_QUESTION = "missing_question"
    MISSING_CONTEXT = "missing_context"
    MIXED_TOPICS = "mixed_topics"
    VISUAL_DEPENDENCY = "visual_dependency"
    CLAIM_AMBIGUITY = "claim_ambiguity"


class EvidenceFlag(StrEnum):
    ASR_UNCERTAIN = "asr_uncertain"
    CONTEXT_DEPENDENCY = "context_dependency"
    INCOMPLETE_CLAIM = "incomplete_claim"
    VISUAL_VERIFICATION_REQUIRED = "visual_verification_required"


class ContentRiskFlag(StrEnum):
    HEALTH_OR_SAFETY_CLAIM = "health_or_safety_claim"
    LEGAL_OR_FINANCIAL_CLAIM = "legal_or_financial_claim"
    PERSONAL_DATA = "personal_data"
    COPYRIGHT_OR_THIRD_PARTY = "copyright_or_third_party"
    REPUTATION_OR_DEFAMATION = "reputation_or_defamation"
    SPONSOR_OR_ADVERTISING = "sponsor_or_advertising"
    UNSAFE_INSTRUCTION = "unsafe_instruction"
    SENSITIVE_CONTENT = "sensitive_content"


class AuditVerdict(StrEnum):
    PASS = "pass"
    REPAIR = "repair"
    REJECT = "reject"


class AuditIssueCode(StrEnum):
    EVIDENCE_MISMATCH = "evidence_mismatch"
    OVERCLAIM = "overclaim"
    INCOMPLETE_STANDALONE = "incomplete_standalone"
    DUPLICATE_TOPIC = "duplicate_topic"
    RISK_MISCLASSIFIED = "risk_misclassified"
    EDITORIAL_COPY_WEAK = "editorial_copy_weak"


class AuditRepairTarget(StrEnum):
    TIER_1_ASSESSMENT = "tier_1_assessment"
    TIER_2_INVENTORY = "tier_2_inventory"
    TIER_4_EDITORIAL_COPY = "tier_4_editorial_copy"


class ClusterConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TopicRelationship(StrEnum):
    CORE = "core"
    SAME_CLAIM = "same_claim"
    ALTERNATE_ANGLE = "alternate_angle"


class SelectionDisposition(StrEnum):
    SELECTED = "selected"
    UNUSABLE = "unusable"
    BELOW_THRESHOLD = "below_threshold"
    LOWER_RANK_SAME_TOPIC = "lower_rank_same_topic"
    OVERLAP = "overlap"
    PORTFOLIO_LIMIT = "portfolio_limit"
    AUDIT_REJECTED = "audit_rejected"


class AtomicScores(StrictModel):
    content_value: int = Field(ge=0, le=4)
    hook_strength: int = Field(ge=0, le=4)
    standalone_completeness: int = Field(ge=0, le=4)
    evidence_fidelity: int = Field(ge=0, le=4)
    editorial_utility: int = Field(ge=0, le=4)


class CandidateAssessment(StrictModel):
    candidate_id: str = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    disposition: CandidateDisposition
    unusable_reason: UnusableReason
    topic_hypothesis: str | None = Field(min_length=1, max_length=80)
    primary_claim: str | None = Field(min_length=1, max_length=180)
    assessment_reason: str = Field(min_length=1, max_length=260)
    assessment_confidence: AssessmentConfidence
    uncertainty_flags: tuple[UncertaintyFlag, ...] = Field(max_length=6)
    scores: AtomicScores
    evidence_flags: tuple[EvidenceFlag, ...] = Field(max_length=4)
    content_risk_flags: tuple[ContentRiskFlag, ...] = Field(max_length=8)
    risk_summary: str = Field(max_length=240)

    @model_validator(mode="after")
    def _eligibility_contract(self) -> CandidateAssessment:
        if self.disposition == CandidateDisposition.ASSESSABLE:
            if self.unusable_reason != UnusableReason.NONE:
                raise ValueError("assessable candidate must use unusable_reason=none")
            if self.topic_hypothesis is None or self.primary_claim is None:
                raise ValueError("assessable candidate requires a Topic and primary claim")
        elif self.unusable_reason == UnusableReason.NONE:
            raise ValueError("unusable candidate requires a concrete unusable reason")
        for values, label in (
            (self.uncertainty_flags, "uncertainty flags"),
            (self.evidence_flags, "evidence flags"),
            (self.content_risk_flags, "content risk flags"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        has_flags = bool(self.evidence_flags or self.content_risk_flags)
        if has_flags != bool(self.risk_summary.strip()):
            raise ValueError("risk summary must be empty exactly when all risk flags are empty")
        return self


class AssessmentBatch(StrictModel):
    assessments: tuple[CandidateAssessment, ...] = Field(min_length=1, max_length=15)


class TopicMember(StrictModel):
    candidate_id: str = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    relationship: TopicRelationship
    member_angle: str = Field(min_length=1, max_length=80)
    relationship_reason: str = Field(min_length=1, max_length=240)


class TopicDraft(StrictModel):
    topic_label: str = Field(min_length=1, max_length=40)
    canonical_angle: str = Field(min_length=1, max_length=160)
    cluster_confidence: ClusterConfidence
    members: tuple[TopicMember, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _one_core_member(self) -> TopicDraft:
        if sum(member.relationship == TopicRelationship.CORE for member in self.members) != 1:
            raise ValueError("each Topic must contain exactly one core member")
        return self


class TopicInventoryDraft(StrictModel):
    inventory_summary: str = Field(min_length=1, max_length=600)
    topics: tuple[TopicDraft, ...] = Field(max_length=200)


class EditorialCopy(StrictModel):
    candidate_id: str = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    title: str = Field(min_length=1, max_length=40)
    hook: str = Field(min_length=1, max_length=80)
    evidence_quote: str = Field(min_length=4, max_length=220)
    edited_sentence: str = Field(min_length=1, max_length=140)
    script_description: str = Field(min_length=1, max_length=280)
    keywords: tuple[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)],
        ...,
    ] = Field(max_length=8)
    selection_reason: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def _copy_contract(self) -> EditorialCopy:
        if len(set(self.keywords)) != len(self.keywords):
            raise ValueError("keywords must be unique")
        return self


class EditorialCopyBatch(StrictModel):
    selection_summary: str = Field(min_length=1, max_length=600)
    copies: tuple[EditorialCopy, ...] = Field(max_length=20)


class Iteration2UnusableReason(StrEnum):
    NONE = "none"
    FRAGMENT_ONLY = "fragment_only"
    CONTEXT_UNRECOVERABLE = "context_unrecoverable"
    ASR_UNINTELLIGIBLE = "asr_unintelligible"
    UNSAFE_OR_PRIVATE = "unsafe_or_private"


class StandalonePublishability(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"


class PublishabilityBlocker(StrEnum):
    FRAGMENT_ONLY = "fragment_only"
    MISSING_PREMISE_OR_QUESTION = "missing_premise_or_question"
    UNFINISHED_CLAIM_OR_PAYOFF = "unfinished_claim_or_payoff"
    ASR_UNRELIABLE = "asr_unreliable"
    ESSENTIAL_VISUAL_MISSING = "essential_visual_missing"
    UNSAFE_OR_PRIVATE = "unsafe_or_private"


class EditorialValue(StrEnum):
    DISTINCTIVE = "distinctive"
    SOLID = "solid"
    THIN = "thin"


class CandidateAssessmentIteration2(StrictModel):
    candidate_id: str = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    disposition: CandidateDisposition
    unusable_reason: Iteration2UnusableReason
    primary_claim: str | None = Field(min_length=1, max_length=160)
    assessment_confidence: AssessmentConfidence
    standalone_publishability: StandalonePublishability
    publishability_blockers: tuple[PublishabilityBlocker, ...] = Field(max_length=6)
    editorial_value: EditorialValue | None
    editorial_value_reason: str = Field(max_length=180)
    scores: AtomicScores
    evidence_flags: tuple[EvidenceFlag, ...] = Field(max_length=4)
    content_risk_flags: tuple[ContentRiskFlag, ...] = Field(max_length=8)
    risk_summary: str = Field(max_length=220)

    @model_validator(mode="after")
    def _iteration2_cross_field_contract(self) -> CandidateAssessmentIteration2:
        for values, label in (
            (self.publishability_blockers, "publishability blockers"),
            (self.evidence_flags, "evidence flags"),
            (self.content_risk_flags, "content risk flags"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
        if self.standalone_publishability == StandalonePublishability.READY:
            if self.publishability_blockers:
                raise ValueError("ready candidate cannot have a publishability blocker")
        elif not self.publishability_blockers:
            raise ValueError("not_ready candidate requires a publishability blocker")
        if self.disposition == CandidateDisposition.ASSESSABLE:
            if self.unusable_reason != Iteration2UnusableReason.NONE:
                raise ValueError("assessable candidate must use unusable_reason=none")
            if self.primary_claim is None or self.editorial_value is None:
                raise ValueError("assessable candidate requires claim and editorial value")
            if not self.editorial_value_reason.strip():
                raise ValueError("assessable candidate requires editorial value reason")
        else:
            if self.unusable_reason == Iteration2UnusableReason.NONE:
                raise ValueError("unusable candidate requires a concrete reason")
            if self.standalone_publishability != StandalonePublishability.NOT_READY:
                raise ValueError("unusable candidate must be not_ready")
            if self.editorial_value is not None or self.editorial_value_reason:
                raise ValueError("unusable candidate cannot claim editorial value")
        has_risk = bool(self.evidence_flags or self.content_risk_flags)
        if has_risk != bool(self.risk_summary.strip()):
            raise ValueError("risk summary must be empty exactly when risk flags are empty")
        return self


class TopicMemberIteration2(StrictModel):
    candidate_id: str = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    relationship: TopicRelationship
    member_angle: str = Field(min_length=1, max_length=100)


class TopicDraftIteration2(StrictModel):
    topic_label: str = Field(min_length=1, max_length=40)
    canonical_angle: str = Field(min_length=1, max_length=160)
    cluster_confidence: ClusterConfidence
    members: tuple[TopicMemberIteration2, ...] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def _one_iteration2_core(self) -> TopicDraftIteration2:
        if sum(member.relationship == TopicRelationship.CORE for member in self.members) != 1:
            raise ValueError("each Topic must contain exactly one core member")
        return self


class CombinedDiscovery(StrictModel):
    assessments: tuple[CandidateAssessmentIteration2, ...] = Field(min_length=1, max_length=60)
    inventory_summary: str = Field(min_length=1, max_length=500)
    topics: tuple[TopicDraftIteration2, ...] = Field(max_length=60)


class SelectedCopyIteration2(StrictModel):
    candidate_id: str = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    title: str = Field(min_length=1, max_length=40)
    hook: str = Field(min_length=1, max_length=90)
    evidence_quote: str = Field(min_length=4, max_length=260)
    source_sentence: str = Field(min_length=4, max_length=180)
    script_description: str = Field(min_length=1, max_length=260)
    keywords: tuple[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=24)],
        ...,
    ] = Field(max_length=6)

    @model_validator(mode="after")
    def _unique_iteration2_keywords(self) -> SelectedCopyIteration2:
        if len(set(self.keywords)) != len(self.keywords):
            raise ValueError("keywords must be unique")
        return self


class SelectedCopyBatchIteration2(StrictModel):
    selection_summary: str = Field(min_length=1, max_length=500)
    copies: tuple[SelectedCopyIteration2, ...] = Field(max_length=12)


class AuditIssue(StrictModel):
    candidate_id: str | None = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    issue_code: AuditIssueCode
    repair_target: AuditRepairTarget
    reason: str = Field(min_length=1, max_length=240)


class IndependentAudit(StrictModel):
    verdict: AuditVerdict
    summary: str = Field(min_length=1, max_length=600)
    issues: tuple[AuditIssue, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def _verdict_matches_issues(self) -> IndependentAudit:
        if self.verdict == AuditVerdict.PASS and self.issues:
            raise ValueError("pass audit cannot contain issues")
        if self.verdict != AuditVerdict.PASS and not self.issues:
            raise ValueError("repair/reject audit requires at least one issue")
        keys = [
            (issue.candidate_id, issue.issue_code, issue.repair_target) for issue in self.issues
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("audit issues must be unique")
        return self


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


WireModel = TypeVar("WireModel", bound=StrictModel)


def validate_wire(model: type[WireModel], raw: dict[str, Any]) -> WireModel:
    """Validate a JSON-origin object strictly while accepting JSON arrays as tuples."""

    return model.model_validate_json(canonical_json_bytes(raw), strict=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def quality_total(scores: AtomicScores | dict[str, int]) -> float:
    return quality_score_x100(scores) / 100


def quality_score_x100(scores: AtomicScores | dict[str, int]) -> int:
    values = scores if isinstance(scores, dict) else scores.model_dump(mode="json")
    weighted_sum = (
        30 * values["content_value"]
        + 20 * values["hook_strength"]
        + 20 * values["standalone_completeness"]
        + 15 * values["evidence_fidelity"]
        + 15 * values["editorial_utility"]
    )
    return weighted_sum * 25


def _normalization_clusters(value: str) -> Iterable[tuple[int, int, str]]:
    """Yield small normalization-safe clusters with their raw spans."""

    def is_hangul_lead(character: str) -> bool:
        code = ord(character)
        return 0x1100 <= code <= 0x115F or 0xA960 <= code <= 0xA97F

    def is_hangul_vowel(character: str) -> bool:
        code = ord(character)
        return 0x1160 <= code <= 0x11A7 or 0xD7B0 <= code <= 0xD7C6

    def is_hangul_trail(character: str) -> bool:
        code = ord(character)
        return 0x11A8 <= code <= 0x11FF or 0xD7CB <= code <= 0xD7FB

    index = 0
    while index < len(value):
        start = index
        index += 1
        if is_hangul_lead(value[start]) and index < len(value) and is_hangul_vowel(value[index]):
            index += 1
            if index < len(value) and is_hangul_trail(value[index]):
                index += 1
        while index < len(value) and (
            unicodedata.combining(value[index]) != 0
            or unicodedata.category(value[index]).startswith("M")
        ):
            index += 1
        yield start, index, value[start:index]


def _kept_normalized_characters(value: str) -> tuple[str, list[tuple[int, int]]]:
    normalized: list[str] = []
    raw_spans: list[tuple[int, int]] = []
    for raw_start, raw_end, raw_cluster in _normalization_clusters(value):
        for character in unicodedata.normalize("NFKC", raw_cluster).casefold():
            category = unicodedata.category(character)
            if character.isspace() or category.startswith(("P", "Z", "C")):
                continue
            normalized.append(character)
            raw_spans.append((raw_start, raw_end))
    return "".join(normalized), raw_spans


def exact_quote_receipt(quote: str, candidate_text: str) -> dict[str, Any]:
    normalized_quote, _ = _kept_normalized_characters(quote)
    normalized_candidate, raw_spans = _kept_normalized_characters(candidate_text)
    normalized_start = normalized_candidate.find(normalized_quote) if normalized_quote else -1
    if normalized_start < 0:
        return {
            "status": "failed",
            "failure_code": "EVIDENCE_QUOTE_NOT_IN_CANDIDATE",
            "validator_version": QUOTE_VALIDATOR_VERSION,
            "candidate_text_sha256": sha256_bytes(candidate_text.encode("utf-8")),
            "quote_sha256": sha256_bytes(quote.encode("utf-8")),
            "normalized_quote": normalized_quote,
            "normalized_start": None,
            "normalized_end": None,
            "raw_start": None,
            "raw_end": None,
        }
    normalized_end = normalized_start + len(normalized_quote)
    raw_start = raw_spans[normalized_start][0]
    raw_end = raw_spans[normalized_end - 1][1]
    return {
        "status": "passed",
        "validator_version": QUOTE_VALIDATOR_VERSION,
        "candidate_text_sha256": sha256_bytes(candidate_text.encode("utf-8")),
        "quote_sha256": sha256_bytes(quote.encode("utf-8")),
        "normalized_quote": normalized_quote,
        "normalized_start": normalized_start,
        "normalized_end": normalized_end,
        "raw_start": raw_start,
        "raw_end": raw_end,
    }


def validate_assessment_batch(
    raw: dict[str, Any], expected_candidate_ids: Sequence[str]
) -> tuple[CandidateAssessment, ...]:
    batch = validate_wire(AssessmentBatch, raw)
    observed = [item.candidate_id for item in batch.assessments]
    if observed != list(expected_candidate_ids):
        raise ValueError("assessment batch must preserve and cover the exact candidate ID order")
    return batch.assessments


def validate_complete_assessments(
    assessments: Sequence[CandidateAssessment], expected_candidate_ids: Sequence[str]
) -> None:
    observed = [item.candidate_id for item in assessments]
    if len(observed) != len(set(observed)):
        raise ValueError("candidate assessments contain duplicate IDs")
    if set(observed) != set(expected_candidate_ids):
        raise ValueError("candidate assessments do not account for every input candidate")


def _topic_id(member_ids: Iterable[str]) -> str:
    identity = canonical_json_bytes(
        {
            "contract_version": CONTRACT_VERSION,
            "members": sorted(member_ids),
        }
    )
    return f"topic_{sha256_bytes(identity)[:16]}"


def validate_and_enrich_inventory(
    raw: dict[str, Any], assessments: Sequence[CandidateAssessment]
) -> dict[str, Any]:
    inventory = validate_wire(TopicInventoryDraft, raw)
    by_id = {item.candidate_id: item for item in assessments}
    assessable_ids = {
        item.candidate_id
        for item in assessments
        if item.disposition == CandidateDisposition.ASSESSABLE
    }
    unusable_ids = set(by_id) - assessable_ids
    member_ids = [member.candidate_id for topic in inventory.topics for member in topic.members]
    if len(member_ids) != len(set(member_ids)):
        raise ValueError("an assessable candidate appears in more than one primary Topic")
    if set(member_ids) != assessable_ids:
        raise ValueError("Topic members must exactly equal assessable candidate IDs")
    if set(member_ids) & unusable_ids:
        raise ValueError("an unusable candidate cannot be a Topic member")
    enriched_topics: list[dict[str, Any]] = []
    seen_topic_ids: set[str] = set()
    for topic in inventory.topics:
        topic_data = topic.model_dump(mode="json")
        topic_data["topic_id"] = _topic_id(member.candidate_id for member in topic.members)
        if topic_data["topic_id"] in seen_topic_ids:
            raise ValueError("two Topic drafts resolve to the same deterministic identity")
        seen_topic_ids.add(topic_data["topic_id"])
        enriched_topics.append(topic_data)
    return {
        "inventory_summary": inventory.inventory_summary,
        "topics": enriched_topics,
        "excluded_candidates": [
            {
                "candidate_id": item.candidate_id,
                "unusable_reason": item.unusable_reason.value,
            }
            for item in assessments
            if item.disposition == CandidateDisposition.UNUSABLE
        ],
        "accounting": {
            "assessable_count": len(assessable_ids),
            "topic_member_count": len(member_ids),
            "unusable_count": len(unusable_ids),
            "excluded_count": len(unusable_ids),
            "passed": True,
        },
    }


def normalize_text(value: str) -> str:
    return _kept_normalized_characters(value)[0]


def text_jaccard(left: str, right: str, *, n: int = 3) -> float:
    def shingles(value: str) -> set[str]:
        normalized = normalize_text(value)
        if len(normalized) < n:
            return {normalized} if normalized else set()
        return {normalized[index : index + n] for index in range(len(normalized) - n + 1)}

    left_values = shingles(left)
    right_values = shingles(right)
    union = left_values | right_values
    return len(left_values & right_values) / len(union) if union else 0.0


def interval_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    start = max(int(left["source_start_ms"]), int(right["source_start_ms"]))
    end = min(int(left["source_end_ms"]), int(right["source_end_ms"]))
    intersection = max(0, end - start)
    union = max(int(left["source_end_ms"]), int(right["source_end_ms"])) - min(
        int(left["source_start_ms"]), int(right["source_start_ms"])
    )
    return intersection / union if union > 0 else 0.0


def select_portfolio(
    candidates: Sequence[dict[str, Any]],
    assessments: Sequence[CandidateAssessment],
    inventory: dict[str, Any],
    *,
    top_n: int = 12,
    minimum_quality: float = 55.0,
    maximum_interval_iou: float = 0.45,
    maximum_text_jaccard: float = 0.65,
) -> dict[str, Any]:
    if not 1 <= top_n <= 20:
        raise ValueError("top_n must be between 1 and 20")
    if not 0 <= minimum_quality <= 100:
        raise ValueError("minimum quality must be on the 0-100 scale")
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    assessments_by_id = {item.candidate_id: item for item in assessments}
    if set(candidates_by_id) != set(assessments_by_id):
        raise ValueError("portfolio inputs disagree about candidate IDs")

    member_by_id: dict[str, dict[str, Any]] = {}
    topic_by_candidate: dict[str, dict[str, Any]] = {}
    for topic in inventory["topics"]:
        for member in topic["members"]:
            member_by_id[member["candidate_id"]] = member
            topic_by_candidate[member["candidate_id"]] = topic

    minimum_quality_x100 = round(minimum_quality * 100)

    def ranking_key(candidate_id: str) -> tuple[int, float, int, str]:
        assessment = assessments_by_id[candidate_id]
        candidate = candidates_by_id[candidate_id]
        return (
            -quality_score_x100(assessment.scores),
            -float(candidate["rule_score"]),
            int(candidate["source_start_ms"]),
            candidate_id,
        )

    qualified_by_topic: dict[str, list[str]] = {}
    below_threshold: set[str] = set()
    for topic in inventory["topics"]:
        ranked_ids = sorted(
            (member["candidate_id"] for member in topic["members"]),
            key=ranking_key,
        )
        qualified = [
            candidate_id
            for candidate_id in ranked_ids
            if quality_score_x100(assessments_by_id[candidate_id].scores) >= minimum_quality_x100
        ]
        below_threshold.update(set(ranked_ids) - set(qualified))
        if qualified:
            qualified_by_topic[topic["topic_id"]] = qualified

    selected_ids: list[str] = []
    overlap_ids: set[str] = set()
    representative_set: set[str] = set()
    portfolio_limit_ids: set[str] = set()

    def conflicts_with_selected(candidate_id: str) -> bool:
        candidate = candidates_by_id[candidate_id]
        return any(
            interval_iou(candidate, candidates_by_id[selected_id]) > maximum_interval_iou
            or text_jaccard(candidate["text"], candidates_by_id[selected_id]["text"])
            > maximum_text_jaccard
            for selected_id in selected_ids
        )

    ordered_topic_ids = sorted(
        qualified_by_topic,
        key=lambda topic_id: ranking_key(qualified_by_topic[topic_id][0]),
    )
    for topic_id in ordered_topic_ids:
        qualified = qualified_by_topic[topic_id]
        if len(selected_ids) >= top_n:
            portfolio_limit_ids.add(qualified[0])
            continue
        for candidate_id in qualified:
            if conflicts_with_selected(candidate_id):
                overlap_ids.add(candidate_id)
                continue
            selected_ids.append(candidate_id)
            representative_set.add(candidate_id)
            break

    secondary_pool = [
        candidate_id
        for qualified in qualified_by_topic.values()
        for candidate_id in qualified
        if candidate_id not in representative_set
        and member_by_id[candidate_id]["relationship"] == TopicRelationship.ALTERNATE_ANGLE
    ]
    for candidate_id in sorted(secondary_pool, key=ranking_key):
        if len(selected_ids) >= top_n:
            portfolio_limit_ids.add(candidate_id)
            continue
        if conflicts_with_selected(candidate_id):
            overlap_ids.add(candidate_id)
            continue
        selected_ids.append(candidate_id)

    ledger: list[dict[str, Any]] = []
    selected_set = set(selected_ids)
    assessable_ids = {
        item.candidate_id
        for item in assessments
        if item.disposition == CandidateDisposition.ASSESSABLE
    }
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        assessment = assessments_by_id[candidate_id]
        topic = topic_by_candidate.get(candidate_id)
        if candidate_id in selected_set:
            disposition = SelectionDisposition.SELECTED
            reason = "达到质量门槛，并提升当前组合的 Topic 覆盖或有效不同角度。"
        elif candidate_id not in assessable_ids:
            disposition = SelectionDisposition.UNUSABLE
            reason = f"Tier 1 不可用：{assessment.unusable_reason.value}."
        elif candidate_id in below_threshold:
            disposition = SelectionDisposition.BELOW_THRESHOLD
            reason = "系统计算质量分低于冻结门槛。"
        elif candidate_id in overlap_ids:
            disposition = SelectionDisposition.OVERLAP
            reason = "与已选片段触发冻结的时间或文本重复阈值。"
        elif candidate_id in portfolio_limit_ids:
            disposition = SelectionDisposition.PORTFOLIO_LIMIT
            reason = "Topic 代表项合格，但组合已达到 top_n 上限。"
        else:
            disposition = SelectionDisposition.LOWER_RANK_SAME_TOPIC
            reason = "同一 Topic 已有更高质量代表项，且没有足够增量价值。"
        ledger.append(
            {
                "candidate_id": candidate_id,
                "topic_id": topic["topic_id"] if topic else None,
                "quality_score_x100": quality_score_x100(assessment.scores),
                "disposition": disposition.value,
                "reason": reason,
            }
        )

    selected = []
    for rank, candidate_id in enumerate(selected_ids, start=1):
        assessment = assessments_by_id[candidate_id]
        topic = topic_by_candidate[candidate_id]
        selected.append(
            {
                "candidate_id": candidate_id,
                "rank": rank,
                "topic_id": topic["topic_id"],
                "topic_label": topic["topic_label"],
                "canonical_angle": topic["canonical_angle"],
                "quality_score_x100": quality_score_x100(assessment.scores),
                "scores": assessment.scores.model_dump(mode="json"),
                "evidence_flags": [value.value for value in assessment.evidence_flags],
                "content_risk_flags": [value.value for value in assessment.content_risk_flags],
            }
        )
    return {
        "algorithm_version": PORTFOLIO_ALGORITHM_VERSION,
        "configuration": {
            "top_n": top_n,
            "minimum_quality": minimum_quality,
            "maximum_interval_iou": maximum_interval_iou,
            "maximum_text_jaccard": maximum_text_jaccard,
        },
        "selected": selected,
        "ledger": ledger,
        "selected_count": len(selected),
    }


def validate_editorial_copies(
    raw: dict[str, Any],
    selected_candidate_ids: Sequence[str],
    candidates_by_id: dict[str, dict[str, Any]],
) -> tuple[EditorialCopyBatch, list[dict[str, Any]]]:
    batch = validate_wire(EditorialCopyBatch, raw)
    observed = [item.candidate_id for item in batch.copies]
    if observed != list(selected_candidate_ids):
        raise ValueError("editorial copies must preserve and cover selected candidate order")
    receipts: list[dict[str, Any]] = []
    for item in batch.copies:
        receipt = exact_quote_receipt(
            item.evidence_quote, candidates_by_id[item.candidate_id]["text"]
        )
        if len(receipt["normalized_quote"]) < 8:
            receipt["status"] = "failed"
            receipt["failure_code"] = "EVIDENCE_QUOTE_TOO_SHORT"
        receipts.append({"candidate_id": item.candidate_id, **receipt})
    failed = [
        {
            "candidate_id": item["candidate_id"],
            "failure_code": item.get("failure_code", "EVIDENCE_QUOTE_GATE_FAILED"),
        }
        for item in receipts
        if item["status"] != "passed"
    ]
    if failed:
        raise ValueError(
            "editorial evidence quote failed exact gate: "
            + json.dumps(failed, ensure_ascii=False, sort_keys=True)
        )
    return batch, receipts


AUDIT_TARGETS_BY_ISSUE: dict[AuditIssueCode, frozenset[AuditRepairTarget]] = {
    AuditIssueCode.EVIDENCE_MISMATCH: frozenset({AuditRepairTarget.TIER_4_EDITORIAL_COPY}),
    AuditIssueCode.OVERCLAIM: frozenset({AuditRepairTarget.TIER_4_EDITORIAL_COPY}),
    AuditIssueCode.INCOMPLETE_STANDALONE: frozenset(
        {
            AuditRepairTarget.TIER_1_ASSESSMENT,
            AuditRepairTarget.TIER_4_EDITORIAL_COPY,
        }
    ),
    AuditIssueCode.DUPLICATE_TOPIC: frozenset({AuditRepairTarget.TIER_2_INVENTORY}),
    AuditIssueCode.RISK_MISCLASSIFIED: frozenset({AuditRepairTarget.TIER_1_ASSESSMENT}),
    AuditIssueCode.EDITORIAL_COPY_WEAK: frozenset({AuditRepairTarget.TIER_4_EDITORIAL_COPY}),
}


def validate_independent_audit(
    raw: dict[str, Any], known_candidate_ids: Sequence[str]
) -> IndependentAudit:
    audit = validate_wire(IndependentAudit, raw)
    known = set(known_candidate_ids)
    if len(known) != len(known_candidate_ids):
        raise ValueError("known audit candidate IDs must be unique")
    for issue in audit.issues:
        if issue.candidate_id is not None and issue.candidate_id not in known:
            raise ValueError(f"audit issue contains unknown candidate ID: {issue.candidate_id}")
        if issue.candidate_id is None and issue.issue_code != AuditIssueCode.DUPLICATE_TOPIC:
            raise ValueError("only a duplicate Topic issue may omit candidate_id")
        if issue.repair_target not in AUDIT_TARGETS_BY_ISSUE[issue.issue_code]:
            raise ValueError(f"audit issue {issue.issue_code.value} has an invalid repair target")
    return audit


def compose_final_result(
    *,
    candidates: Sequence[dict[str, Any]],
    assessments: Sequence[CandidateAssessment],
    inventory: dict[str, Any],
    portfolio: dict[str, Any],
    copies: EditorialCopyBatch,
    receipts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    assessments_by_id = {item.candidate_id: item for item in assessments}
    selected_by_id = {item["candidate_id"]: item for item in portfolio["selected"]}
    receipt_by_id = {item["candidate_id"]: item for item in receipts}
    highlights: list[dict[str, Any]] = []
    for copy in copies.copies:
        candidate_id = copy.candidate_id
        candidate = candidates_by_id[candidate_id]
        assessment = assessments_by_id[candidate_id]
        selected = selected_by_id[candidate_id]
        receipt = dict(receipt_by_id[candidate_id])
        receipt.pop("candidate_id")
        highlights.append(
            {
                "candidate_id": candidate_id,
                "source_start_ms": candidate["source_start_ms"],
                "source_end_ms": candidate["source_end_ms"],
                "topic_id": selected["topic_id"],
                "topic": selected["topic_label"],
                "title": copy.title,
                "hook": copy.hook,
                "evidence_quote": copy.evidence_quote,
                "evidence_receipt": receipt,
                "edited_sentence": copy.edited_sentence,
                "script_description": copy.script_description,
                "keywords": list(copy.keywords),
                "quality_score_x100": selected["quality_score_x100"],
                "scores": assessment.scores.model_dump(mode="json"),
                "selection_reason": copy.selection_reason,
                "risk_flags": [
                    *(value.value for value in assessment.evidence_flags),
                    *(value.value for value in assessment.content_risk_flags),
                ],
            }
        )
    return {
        "schema_version": "2",
        "contract_version": CONTRACT_VERSION,
        "selection_summary": copies.selection_summary,
        "highlights": highlights,
        "topic_inventory": inventory,
        "portfolio": portfolio,
    }


def audit_v1_result(
    result: dict[str, Any], candidates_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    for highlight in result["highlights"]:
        candidate_id = highlight["candidate_id"]
        if candidate_id not in candidates_by_id:
            receipts.append({"candidate_id": candidate_id, "status": "unknown_candidate"})
            continue
        receipts.append(
            {
                "candidate_id": candidate_id,
                **exact_quote_receipt(
                    highlight["highlight_sentence"],
                    candidates_by_id[candidate_id]["text"],
                ),
            }
        )
    return {
        "selected_count": len(result["highlights"]),
        "passed_count": sum(item["status"] == "passed" for item in receipts),
        "failed_count": sum(item["status"] != "passed" for item in receipts),
        "receipts": receipts,
    }


def validate_combined_discovery(
    raw: dict[str, Any], expected_candidate_ids: Sequence[str]
) -> dict[str, Any]:
    discovery = validate_wire(CombinedDiscovery, raw)
    observed_ids = [item.candidate_id for item in discovery.assessments]
    if observed_ids != list(expected_candidate_ids):
        raise ValueError("CombinedDiscovery must preserve and cover candidate order")
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError("CombinedDiscovery contains duplicate candidate assessments")
    assessments_by_id = {item.candidate_id: item for item in discovery.assessments}
    assessable_ids = {
        item.candidate_id
        for item in discovery.assessments
        if item.disposition == CandidateDisposition.ASSESSABLE
    }
    member_ids = [member.candidate_id for topic in discovery.topics for member in topic.members]
    if len(member_ids) != len(set(member_ids)):
        raise ValueError("an assessable candidate appears in more than one Topic")
    if set(member_ids) != assessable_ids:
        raise ValueError("Topic members must exactly equal assessable candidate IDs")
    if any(candidate_id not in assessments_by_id for candidate_id in member_ids):
        raise ValueError("Topic inventory contains an unknown candidate")
    enriched_topics: list[dict[str, Any]] = []
    seen_topic_ids: set[str] = set()
    for topic in discovery.topics:
        topic_data = topic.model_dump(mode="json")
        topic_data["topic_id"] = _topic_id(member.candidate_id for member in topic.members)
        if topic_data["topic_id"] in seen_topic_ids:
            raise ValueError("two Topic drafts resolve to the same identity")
        seen_topic_ids.add(topic_data["topic_id"])
        enriched_topics.append(topic_data)
    unusable_count = len(discovery.assessments) - len(assessable_ids)
    return {
        "assessments": [item.model_dump(mode="json") for item in discovery.assessments],
        "inventory_summary": discovery.inventory_summary,
        "topics": enriched_topics,
        "excluded_candidates": [
            {
                "candidate_id": item.candidate_id,
                "unusable_reason": item.unusable_reason.value,
            }
            for item in discovery.assessments
            if item.disposition == CandidateDisposition.UNUSABLE
        ],
        "accounting": {
            "candidate_count": len(discovery.assessments),
            "assessable_count": len(assessable_ids),
            "topic_member_count": len(member_ids),
            "unusable_count": unusable_count,
            "passed": True,
        },
    }


def select_adaptive_portfolio(
    candidates: Sequence[dict[str, Any]],
    discovery: dict[str, Any],
    *,
    desired_minimum: int = 8,
    maximum_count: int = 12,
    base_minimum_quality: float = 65.0,
    maximum_interval_iou: float = 0.45,
    maximum_text_jaccard: float = 0.65,
) -> dict[str, Any]:
    if not 1 <= desired_minimum <= maximum_count <= 12:
        raise ValueError("adaptive portfolio requires 1 <= desired <= maximum <= 12")
    if not 0 <= base_minimum_quality <= 100:
        raise ValueError("base minimum quality must use the 0-100 scale")
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    assessments = [
        validate_wire(CandidateAssessmentIteration2, item) for item in discovery["assessments"]
    ]
    assessments_by_id = {item.candidate_id: item for item in assessments}
    if set(candidates_by_id) != set(assessments_by_id):
        raise ValueError("portfolio candidate and assessment inventories differ")
    topic_by_candidate: dict[str, dict[str, Any]] = {}
    member_by_candidate: dict[str, dict[str, Any]] = {}
    for topic in discovery["topics"]:
        for member in topic["members"]:
            candidate_id = member["candidate_id"]
            if candidate_id in topic_by_candidate:
                raise ValueError("portfolio Topic inventory contains duplicate candidate")
            topic_by_candidate[candidate_id] = topic
            member_by_candidate[candidate_id] = member

    minimum_x100 = round(base_minimum_quality * 100)

    def ranking_key(candidate_id: str) -> tuple[int, float, int, str]:
        assessment = assessments_by_id[candidate_id]
        candidate = candidates_by_id[candidate_id]
        return (
            -quality_score_x100(assessment.scores),
            -float(candidate["rule_score"]),
            int(candidate["source_start_ms"]),
            candidate_id,
        )

    def base_qualified(candidate_id: str) -> bool:
        assessment = assessments_by_id[candidate_id]
        scores = assessment.scores
        return (
            assessment.disposition == CandidateDisposition.ASSESSABLE
            and assessment.standalone_publishability == StandalonePublishability.READY
            and not assessment.publishability_blockers
            and assessment.editorial_value in {EditorialValue.SOLID, EditorialValue.DISTINCTIVE}
            and scores.content_value >= 2
            and scores.hook_strength >= 2
            and scores.standalone_completeness >= 3
            and scores.evidence_fidelity >= 3
            and scores.editorial_utility >= 2
            and quality_score_x100(scores) >= minimum_x100
        )

    def extension_qualified(candidate_id: str) -> bool:
        assessment = assessments_by_id[candidate_id]
        values = assessment.scores.model_dump(mode="json").values()
        return (
            base_qualified(candidate_id)
            and assessment.editorial_value == EditorialValue.DISTINCTIVE
            and all(value >= 3 for value in values)
        )

    qualified_by_topic: dict[str, list[str]] = {}
    for topic in discovery["topics"]:
        qualified = sorted(
            (
                member["candidate_id"]
                for member in topic["members"]
                if base_qualified(member["candidate_id"])
            ),
            key=ranking_key,
        )
        if qualified:
            qualified_by_topic[topic["topic_id"]] = qualified

    selected_ids: list[str] = []
    selection_phase: dict[str, str] = {}
    overlap_ids: set[str] = set()

    def conflicts(candidate_id: str) -> bool:
        candidate = candidates_by_id[candidate_id]
        return any(
            interval_iou(candidate, candidates_by_id[selected_id]) > maximum_interval_iou
            or text_jaccard(candidate["text"], candidates_by_id[selected_id]["text"])
            > maximum_text_jaccard
            for selected_id in selected_ids
        )

    representatives = sorted(
        (qualified[0] for qualified in qualified_by_topic.values()), key=ranking_key
    )
    material_alternates: list[str] = []
    for qualified in qualified_by_topic.values():
        representative = qualified[0]
        representative_relationship = member_by_candidate[representative]["relationship"]
        for candidate_id in qualified[1:]:
            relationship = member_by_candidate[candidate_id]["relationship"]
            if relationship == TopicRelationship.ALTERNATE_ANGLE or (
                relationship == TopicRelationship.CORE
                and representative_relationship == TopicRelationship.ALTERNATE_ANGLE
            ):
                material_alternates.append(candidate_id)
    alternates = sorted(material_alternates, key=ranking_key)

    for phase, pool in (
        ("base_topic_representative", representatives),
        ("base_alternate_angle", alternates),
    ):
        for candidate_id in pool:
            if len(selected_ids) >= desired_minimum:
                break
            if conflicts(candidate_id):
                overlap_ids.add(candidate_id)
                continue
            selected_ids.append(candidate_id)
            selection_phase[candidate_id] = phase

    extension_pool = sorted(
        (
            candidate_id
            for candidate_id in [*representatives, *alternates]
            if candidate_id not in selected_ids and extension_qualified(candidate_id)
        ),
        key=ranking_key,
    )
    for candidate_id in extension_pool:
        if len(selected_ids) >= maximum_count:
            break
        if conflicts(candidate_id):
            overlap_ids.add(candidate_id)
            continue
        selected_ids.append(candidate_id)
        selection_phase[candidate_id] = "distinctive_extension"

    selected_set = set(selected_ids)
    qualified_ids = {
        candidate_id for candidate_id in candidates_by_id if base_qualified(candidate_id)
    }
    extension_ids = {
        candidate_id for candidate_id in qualified_ids if extension_qualified(candidate_id)
    }
    ledger: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        assessment = assessments_by_id[candidate_id]
        member = member_by_candidate.get(candidate_id)
        topic = topic_by_candidate.get(candidate_id)
        if candidate_id in selected_set:
            disposition = "selected"
            reason = selection_phase[candidate_id]
        elif assessment.disposition == CandidateDisposition.UNUSABLE:
            disposition = "unusable"
            reason = assessment.unusable_reason.value
        elif assessment.standalone_publishability != StandalonePublishability.READY:
            disposition = "not_standalone_publishable"
            reason = ",".join(value.value for value in assessment.publishability_blockers)
        elif candidate_id not in qualified_ids:
            disposition = "below_base_quality_gate"
            reason = "failed one or more frozen atomic/editorial base gates"
        elif candidate_id in overlap_ids:
            disposition = "overlap"
            reason = "conflicts with an earlier selected candidate"
        elif member and member["relationship"] == TopicRelationship.SAME_CLAIM:
            disposition = "same_claim"
            reason = "same_claim never creates a second Topic selection"
        elif candidate_id not in extension_ids:
            disposition = "below_extension_gate"
            reason = "positions 9-12 require distinctive value and all atomic scores >=3"
        else:
            disposition = "portfolio_limit"
            reason = "adaptive portfolio reached its frozen maximum"
        ledger.append(
            {
                "candidate_id": candidate_id,
                "topic_id": topic["topic_id"] if topic else None,
                "quality_score_x100": quality_score_x100(assessment.scores),
                "disposition": disposition,
                "reason": reason,
            }
        )

    selected: list[dict[str, Any]] = []
    for rank, candidate_id in enumerate(selected_ids, start=1):
        assessment = assessments_by_id[candidate_id]
        topic = topic_by_candidate[candidate_id]
        selected.append(
            {
                "candidate_id": candidate_id,
                "rank": rank,
                "topic_id": topic["topic_id"],
                "topic_label": topic["topic_label"],
                "canonical_angle": topic["canonical_angle"],
                "quality_score_x100": quality_score_x100(assessment.scores),
                "scores": assessment.scores.model_dump(mode="json"),
                "editorial_value": assessment.editorial_value.value,
                "selection_phase": selection_phase[candidate_id],
                "selection_reason": (
                    "通过冻结的独立发布与编辑价值门，并作为 Topic 代表或真实增量角度入选。"
                    if rank <= desired_minimum
                    else "五项原子分均强且具有鲜明增量价值，获得自适应扩展名额。"
                ),
                "evidence_flags": [value.value for value in assessment.evidence_flags],
                "content_risk_flags": [value.value for value in assessment.content_risk_flags],
            }
        )
    return {
        "algorithm_version": PORTFOLIO_ALGORITHM_VERSION,
        "configuration": {
            "desired_minimum": desired_minimum,
            "maximum_count": maximum_count,
            "base_minimum_quality": base_minimum_quality,
            "extension_minimum_atomic_score": 3,
            "maximum_interval_iou": maximum_interval_iou,
            "maximum_text_jaccard": maximum_text_jaccard,
            "same_claim_second_selection": False,
        },
        "selected": selected,
        "ledger": ledger,
        "selected_count": len(selected),
        "underfilled_due_to_quality": len(selected) < desired_minimum,
    }


def validate_selected_copies_iteration2(
    raw: dict[str, Any],
    selected_candidate_ids: Sequence[str],
    candidates_by_id: Mapping[str, dict[str, Any]],
) -> tuple[SelectedCopyBatchIteration2, list[dict[str, Any]]]:
    batch = validate_wire(SelectedCopyBatchIteration2, raw)
    observed = [item.candidate_id for item in batch.copies]
    if observed != list(selected_candidate_ids):
        raise ValueError("SelectedCopy must preserve and cover deterministic order")
    receipts: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for item in batch.copies:
        quote_receipt = exact_quote_receipt(
            item.evidence_quote, candidates_by_id[item.candidate_id]["text"]
        )
        if len(quote_receipt["normalized_quote"]) < 8:
            quote_receipt["status"] = "failed"
            quote_receipt["failure_code"] = "EVIDENCE_QUOTE_TOO_SHORT"
        source_receipt = exact_quote_receipt(item.source_sentence, item.evidence_quote)
        if len(source_receipt["normalized_quote"]) < 8:
            source_receipt["status"] = "failed"
            source_receipt["failure_code"] = "SOURCE_SENTENCE_TOO_SHORT"
        if quote_receipt["status"] != "passed":
            failures.append(
                {
                    "candidate_id": item.candidate_id,
                    "failure_code": quote_receipt.get("failure_code", "EVIDENCE_QUOTE_GATE_FAILED"),
                }
            )
        if source_receipt["status"] != "passed":
            failures.append(
                {
                    "candidate_id": item.candidate_id,
                    "failure_code": source_receipt.get(
                        "failure_code", "SOURCE_SENTENCE_GATE_FAILED"
                    ),
                }
            )
        receipts.append(
            {
                "candidate_id": item.candidate_id,
                "evidence_quote": quote_receipt,
                "source_sentence": source_receipt,
            }
        )
    if failures:
        raise ValueError(
            "SelectedCopy exact evidence gate failed: "
            + json.dumps(failures, ensure_ascii=False, sort_keys=True)
        )
    return batch, receipts


def compose_iteration2_result(
    *,
    candidates: Sequence[dict[str, Any]],
    discovery: dict[str, Any],
    portfolio: dict[str, Any],
    copies: SelectedCopyBatchIteration2,
    receipts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    assessments_by_id = {
        item["candidate_id"]: validate_wire(CandidateAssessmentIteration2, item)
        for item in discovery["assessments"]
    }
    selected_by_id = {item["candidate_id"]: item for item in portfolio["selected"]}
    receipts_by_id = {item["candidate_id"]: item for item in receipts}
    highlights: list[dict[str, Any]] = []
    for copy in copies.copies:
        candidate_id = copy.candidate_id
        candidate = candidates_by_id[candidate_id]
        assessment = assessments_by_id[candidate_id]
        selected = selected_by_id[candidate_id]
        highlights.append(
            {
                "candidate_id": candidate_id,
                "source_start_ms": candidate["source_start_ms"],
                "source_end_ms": candidate["source_end_ms"],
                "topic_id": selected["topic_id"],
                "topic": selected["topic_label"],
                "title": copy.title,
                "hook": copy.hook,
                "evidence_quote": copy.evidence_quote,
                "source_sentence": copy.source_sentence,
                "highlight_sentence": copy.source_sentence,
                "evidence_receipt": receipts_by_id[candidate_id],
                "script_description": copy.script_description,
                "keywords": list(copy.keywords),
                "quality_score_x100": selected["quality_score_x100"],
                "scores": assessment.scores.model_dump(mode="json"),
                "selection_reason": selected["selection_reason"],
                "risk_flags": [
                    *(value.value for value in assessment.evidence_flags),
                    *(value.value for value in assessment.content_risk_flags),
                ],
            }
        )
    return {
        "schema_version": "3",
        "contract_version": CONTRACT_VERSION,
        "selection_summary": copies.selection_summary,
        "highlights": highlights,
        "topic_inventory": {
            "inventory_summary": discovery["inventory_summary"],
            "topics": discovery["topics"],
            "excluded_candidates": discovery["excluded_candidates"],
            "accounting": discovery["accounting"],
        },
        "portfolio": portfolio,
    }
