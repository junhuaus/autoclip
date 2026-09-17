"""Pure, opt-in ADR041 contracts. No runtime dispatch or semantic inference.

V4 projections below are validation-only; authoritative storage is explicitly V5.
Raw diagnostics deliberately run independently of whole-response schema parsing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from types import UnionType
from typing import Annotated, Any, Literal, TypeVar, Union, get_args, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from liveclip.domain.clip_profile import ClipProfile, clip_profile_spec
from liveclip.domain.semantic_validation import CURRENT_SEMANTIC_VALIDATION
from liveclip.domain.transcript import TranscriptDocument
from liveclip.pipeline.semantic_global import SemanticCue, SemanticInputUnit, transcript_cues
from liveclip.pipeline.semantic_profiles import (
    BLOCKING_QUALITY_FLAGS_V4,
    BoundaryReviewV4,
    BoundedText,
    ChainCandidateV4,
    DiscoveryBatchOutputV4,
    LogicalWindowDiscoveryV4,
    RiskFlagV4,
    TimeRangeV4,
    TopicBoundaryV4,
    TopicChainReviewV4,
    TopicChainStatusV4,
    TopicChainV4,
    TopicFragmentV4,
    boundary_consistency_errors_v4,
    build_discovery_payload_v4,
    validate_boundary_review_v4,
    validate_discovery_batch_v4,
    validate_topic_chain_review_v4,
)

LINEAGE_CONTRACT: Literal["semantic-v5-lineage-v1"] = "semantic-v5-lineage-v1"
SafeID = Annotated[str, StringConstraints(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")]
CueID = Annotated[int, Field(ge=1)]
Evidence = Annotated[tuple[CueID, ...], Field(min_length=1)]
FinalDisposition = Literal["selected", "manual", "blocked", "rejected", "top_n_excluded"]
TreatmentKind = Literal[
    "applies", "uncertain", "outside_final_span", "resolved_in_context", "dropped_candidate"
]


class FrozenV5(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class LogicalWindowAuthorityV5(TimeRangeV4):
    """Request-owned window identity and bounds, before output namespacing."""

    logical_window_id: SafeID


class VersionedV5(FrozenV5):
    schema_version: Literal["5"] = "5"
    contract_version: Literal["semantic-v5-lineage-v1"] = LINEAGE_CONTRACT


class DiscoveryRiskV5(FrozenV5):
    risk_id: SafeID
    flag: RiskFlagV4
    reason: BoundedText
    evidence_cue_ids: Evidence


class DiscoveryCandidateV5(FrozenV5):
    candidate_id: SafeID
    source_topic_id: SafeID
    topic_fragment_ids: tuple[SafeID, ...] = Field(min_length=1, max_length=80)
    topic_summary: BoundedText = Field(max_length=320)
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    start_cue_id: CueID
    end_cue_id: CueID
    evidence_cue_ids: Evidence
    possible_profiles: tuple[ClipProfile, ...] = Field(min_length=1, max_length=2)
    risks: tuple[DiscoveryRiskV5, ...]
    source_window_ids: tuple[SafeID, ...] = Field(min_length=1, max_length=20)
    source_batch_id: SafeID

    @model_validator(mode="after")
    def validate_structure(self) -> DiscoveryCandidateV5:
        if self.end_cue_id < self.start_cue_id:
            raise ValueError("Discovery interval is reversed")
        for values in (
            self.possible_profiles,
            self.topic_fragment_ids,
            self.source_window_ids,
            tuple(r.risk_id for r in self.risks),
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate Discovery reference or risk ID")
        return self


class TopicBoundaryV5(TopicBoundaryV4):
    related_candidate_ids: tuple[SafeID, ...] = ()
    related_fragment_ids: tuple[SafeID, ...] = ()


class TopicFragmentV5(TopicFragmentV4):
    topic_fragment_id: SafeID
    logical_window_id: SafeID
    source_batch_id: SafeID


class LogicalWindowDiscoveryV5(LogicalWindowDiscoveryV4):
    logical_window_id: SafeID
    candidate_ids: tuple[SafeID, ...] = ()
    fragment_ids: tuple[SafeID, ...] = ()
    left_boundary: TopicBoundaryV5
    right_boundary: TopicBoundaryV5


class DiscoveryBatchOutputV5(VersionedV5):
    batch_id: SafeID
    batch_context: TimeRangeV4
    ownership_interval: TimeRangeV4
    logical_windows: tuple[LogicalWindowDiscoveryV5, ...] = Field(min_length=1, max_length=4)
    candidates: tuple[DiscoveryCandidateV5, ...]
    topic_fragments: tuple[TopicFragmentV5, ...]


class AttributedRiskV5(DiscoveryRiskV5):
    local_risk_id: SafeID
    original_candidate_id: SafeID
    source_batch_id: SafeID
    source_window_ids: tuple[SafeID, ...] = Field(min_length=1)
    source_fragment_ids: tuple[SafeID, ...] = Field(min_length=1)


class SourceRouteV5(FrozenV5):
    original_candidate_id: SafeID
    topic_chain_id: SafeID


class SourceDispositionV5(SourceRouteV5):
    derived_unit_ids: tuple[SafeID, ...]
    rejection_reason: BoundedText | None
    evidence_cue_ids: Evidence

    @model_validator(mode="after")
    def validate_disposition(self) -> SourceDispositionV5:
        if bool(self.derived_unit_ids) == (self.rejection_reason is not None):
            raise ValueError("source requires derived units OR explicit rejection")
        if len(set(self.derived_unit_ids)) != len(self.derived_unit_ids):
            raise ValueError("duplicate derived edge")
        return self


class ChainCandidateV5(ChainCandidateV4):
    candidate_id: SafeID
    source_topic_id: SafeID
    topic_chain_id: SafeID
    source_fragment_ids: tuple[SafeID, ...] = Field(min_length=1)
    variant_of: SafeID | None = None
    origin_kind: Literal["derived", "chain_new"]
    original_candidate_ids: tuple[SafeID, ...]
    origin_reason: BoundedText

    @model_validator(mode="after")
    def validate_origins(self) -> ChainCandidateV5:
        if (self.origin_kind == "derived") != bool(self.original_candidate_ids):
            raise ValueError("derived requires origins; chain_new forbids origins")
        if len(set(self.original_candidate_ids)) != len(self.original_candidate_ids):
            raise ValueError("duplicate origin")
        return self


class TopicChainReviewV5(VersionedV5):
    topic_chain_id: SafeID
    central_question: BoundedText = Field(max_length=320)
    learning_outcome: BoundedText = Field(max_length=320)
    topic_outline: tuple[BoundedText, ...] = Field(min_length=1, max_length=30)
    left_closed: bool
    right_closed: bool
    chain_status: TopicChainStatusV4
    candidates: tuple[ChainCandidateV5, ...]
    rejection_reason: (
        Literal[
            "topic_too_long_without_natural_split",
            "topic_not_closed",
            "no_complete_profile_candidate",
            "not_a_single_teaching_objective",
        ]
        | None
    )
    evidence_cue_ids: Evidence
    source_dispositions: tuple[SourceDispositionV5, ...]

    @model_validator(mode="after")
    def validate_disposition(self) -> TopicChainReviewV5:
        _fail(topic_chain_structure_errors_v5(self.model_dump(mode="json")))
        return self


class RiskTreatmentV5(FrozenV5):
    risk_id: SafeID
    treatment: TreatmentKind
    reason: BoundedText
    evidence_cue_ids: Evidence


class BoundaryReviewV5(BoundaryReviewV4):
    schema_version: Literal["5"] = "5"
    contract_version: Literal["semantic-v5-lineage-v1"] = LINEAGE_CONTRACT
    candidate_id: SafeID
    risk_treatments: tuple[RiskTreatmentV5, ...]


class FinalPartitionV5(FrozenV5):
    selected: tuple[SafeID, ...]
    manual: tuple[SafeID, ...]
    blocked: tuple[SafeID, ...]
    rejected: tuple[SafeID, ...]
    top_n_excluded: tuple[SafeID, ...]


class BoundaryAuthorityV5(FrozenV5):
    candidate_id: SafeID
    context_cue_ids: Evidence
    risks: tuple[AttributedRiskV5, ...]


class UnitOutcomeV5(FrozenV5):
    unit: ChainCandidateV5
    disposition: FinalDisposition
    authority: BoundaryAuthorityV5
    boundary: BoundaryReviewV5


class TerminalPathV5(SourceRouteV5):
    unit_id: SafeID | None
    disposition: FinalDisposition
    rejection_reason: BoundedText | None
    evidence_cue_ids: tuple[CueID, ...]


class OriginalLineageV5(FrozenV5):
    original: DiscoveryCandidateV5
    risks: tuple[AttributedRiskV5, ...]
    paths: tuple[TerminalPathV5, ...]


class LineageCountsV5(FrozenV5):
    originals: int = Field(ge=0)
    units: int = Field(ge=0)
    derived_units: int = Field(ge=0)
    chain_new_units: int = Field(ge=0)
    terminal_paths: int = Field(ge=0)
    rejected_source_paths: int = Field(ge=0)
    selected: int = Field(ge=0)
    manual: int = Field(ge=0)
    blocked: int = Field(ge=0)
    rejected: int = Field(ge=0)
    top_n_excluded: int = Field(ge=0)


class LineageLedgerV5(VersionedV5):
    batches: tuple[DiscoveryBatchOutputV5, ...]
    chains: tuple[TopicChainV4, ...]
    reviews: tuple[TopicChainReviewV5, ...]
    originals: tuple[OriginalLineageV5, ...]
    outcomes: tuple[UnitOutcomeV5, ...]
    chain_new_outcomes: tuple[UnitOutcomeV5, ...]
    partition: FinalPartitionV5
    counts: LineageCountsV5

    @model_validator(mode="after")
    def validate_recorded_graph(self) -> LineageLedgerV5:
        _validate_ledger_records(self)
        return self


class LineageErrorV5(FrozenV5):
    location: tuple[str | int, ...]
    code: str
    message: str


class LineageValidationError(ValueError):
    def __init__(self, errors: Sequence[LineageErrorV5]):
        self.errors = tuple(errors)
        super().__init__(" | ".join(f"{e.location}: {e.code}: {e.message}" for e in errors))


def _fail(errors: Sequence[LineageErrorV5]) -> None:
    if errors:
        raise LineageValidationError(errors)


def _error(errors: list[LineageErrorV5], loc: tuple[str | int, ...], code: str) -> None:
    errors.append(LineageErrorV5(location=loc, code=code, message=code.replace("_", " ")))


def _rows(value: object) -> list[tuple[int, dict[str, Any]]]:
    return (
        [(i, v) for i, v in enumerate(value) if isinstance(v, dict)]
        if isinstance(value, list)
        else []
    )


def _contract_defaults_v5(model: type[BaseModel], raw: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize only checked-in optional defaults, preserving every supplied wire value."""
    result = dict(raw)
    for name, field in model.model_fields.items():
        if name in raw:
            result[name] = _nested_contract_defaults_v5(field.annotation, raw[name])
        elif not field.is_required():
            # The frozen contracts use only literal defaults and empty tuples.
            # Never execute a factory, construct a missing model, or coerce input.
            if field.default_factory is tuple:
                result[name] = []
            elif field.default_factory is not None:
                raise ValueError("unsupported factory in lineage contract")
            elif isinstance(field.default, tuple) and not field.default:
                result[name] = []
            elif field.default is None or type(field.default) in (str, bool, int):
                result[name] = field.default
            else:
                raise ValueError("unsupported default in lineage contract")
    return result


def _nested_contract_defaults_v5(annotation: Any, value: Any) -> Any:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _contract_defaults_v5(annotation, value) if isinstance(value, dict) else value
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        return _nested_contract_defaults_v5(arguments[0], value)
    if origin is tuple and len(arguments) == 2 and arguments[1] is Ellipsis:
        return (
            [_nested_contract_defaults_v5(arguments[0], item) for item in value]
            if isinstance(value, list)
            else value
        )
    if origin in (Union, UnionType):
        choices = [argument for argument in arguments if argument is not type(None)]
        if len(choices) == 1:
            return _nested_contract_defaults_v5(choices[0], value)
    return value


def _known_flattened_prefix_v5(value: object, field: str) -> list[Any]:
    """Keep declared positions until a missing list makes later offsets unknown."""
    result: list[Any] = []
    if isinstance(value, list):
        for row in value:
            if not isinstance(row, dict) or not isinstance(row.get(field), list):
                break
            result.extend(row[field])
    return result


def _complete_ids(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _known_chain_new_prefix_v5(units: Sequence[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, dict) or unit.get("origin_kind") not in ("derived", "chain_new"):
            break
        if unit["origin_kind"] == "chain_new":
            result.append(unit)
    return result


def _ids(value: object) -> list[str] | None:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return None


def _indexed_ids(value: object) -> list[tuple[int, str]]:
    """Keep wire positions when malformed siblings cannot supply an ID."""
    return (
        [(i, v) for i, v in enumerate(value) if isinstance(v, str)]
        if isinstance(value, list)
        else []
    )


def _unique_refs(
    value: object,
    known: set[str] | None,
    loc: tuple[str | int, ...],
    errors: list[LineageErrorV5],
) -> None:
    if not isinstance(value, list):
        return
    seen: set[str] = set()
    for i, v in enumerate(value):
        if not isinstance(v, str):
            continue
        if v in seen:
            _error(errors, (*loc, i), "duplicate_id")
        if known is not None and v not in known:
            _error(errors, (*loc, i), "unknown_id")
        seen.add(v)


def _index(
    value: object,
    field: str,
    loc: tuple[str | int, ...],
    errors: list[LineageErrorV5],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for i, row in _rows(value):
        key = row.get(field)
        if isinstance(key, str):
            if key in result:
                _error(errors, (*loc, i, field), "duplicate_id")
            else:
                result[key] = row
    return result


def _claims_by_id_v5(value: object, field: str) -> dict[str, list[dict[str, Any]]]:
    """Keep every claim; duplicate rejection must not choose semantic authority."""
    result: dict[str, list[dict[str, Any]]] = {}
    for _, row in _rows(value):
        key = row.get(field)
        if isinstance(key, str):
            result.setdefault(key, []).append(row)
    return result


def _any_scope_v5(scopes: Sequence[bool | None]) -> bool | None:
    if any(scope is True for scope in scopes):
        return True
    return False if scopes and all(scope is False for scope in scopes) else None


def _claim_reference_scope_v5(
    claims: Sequence[Mapping[str, Any]], field: str, reference: str
) -> bool | None:
    return _any_scope_v5(
        [_intersection_scope_v5(claim.get(field), [reference], str) for claim in claims]
    )


def _chain_claim_authority_v5(claims: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Union positive scopes; only complete claims establish the outer bounds."""
    if not claims:
        return {}
    result = {
        key: value
        for key, value in claims[0].items()
        if all(key in claim and claim[key] == value for claim in claims)
    }
    fragments: list[object] = []
    fragments.extend(
        sorted({value for claim in claims for _, value in _indexed_ids(claim.get("fragment_ids"))})
    )
    if not all(_complete_ids(claim.get("fragment_ids")) for claim in claims):
        fragments.append(None)
    result["fragment_ids"] = fragments
    for field, bound in (("source_start_cue_id", min), ("source_end_cue_id", max)):
        values = [claim.get(field) for claim in claims]
        if all(type(value) is int for value in values):
            result[field] = bound(value for value in values if type(value) is int)
    return result


def _risk_order_errors_v5(
    expected: Sequence[str],
    actual: object,
    loc: tuple[str | int, ...],
    errors: list[LineageErrorV5],
) -> None:
    """Compare known unique identities without guessing missing or duplicate rows."""
    indexed = [
        (i, row["risk_id"]) for i, row in _rows(actual) if isinstance(row.get("risk_id"), str)
    ]
    counts: dict[str, int] = {}
    for _, key in indexed:
        counts[key] = counts.get(key, 0) + 1
    expected_counts: dict[str, int] = {}
    for key in expected:
        expected_counts[key] = expected_counts.get(key, 0) + 1
    comparable = [key for key in expected if counts.get(key) == expected_counts[key] == 1]
    known = set(comparable)
    observed = [(i, key) for i, key in indexed if key in known]
    for (i, key), expected_key in zip(observed, comparable, strict=True):
        if key != expected_key:
            _error(errors, (*loc, i, "risk_id"), "risk_order_mismatch")


def _authority_ids(value: object, key: str) -> set[str] | None:
    if not isinstance(value, list) or any(
        not isinstance(row, dict) or not isinstance(row.get(key), str) for row in value
    ):
        return None
    return {row[key] for row in value}


def validate_cues_v5(
    cues: Sequence[SemanticCue], *, transcript: TranscriptDocument | None = None
) -> None:
    """Validate actual local records without manufacturing an excerpt transcript."""
    full = {cue.cue_id: cue for cue in transcript_cues(transcript)} if transcript else None
    seen: set[int] = set()
    for cue in cues:
        if not isinstance(cue, SemanticCue) or cue.cue_id in seen:
            raise ValueError("invalid or duplicate cue authority")
        if full is not None and full.get(cue.cue_id) != cue:
            raise ValueError("local cue authority disagrees with the full transcript")
        seen.add(cue.cue_id)


def _cue_map_v5(
    transcript: TranscriptDocument | None, cues: Sequence[SemanticCue] | None = None
) -> dict[int, SemanticCue]:
    if cues is not None:
        validate_cues_v5(cues, transcript=transcript)
    records = transcript_cues(transcript) if transcript is not None else cues or ()
    return {cue.cue_id: cue for cue in records}


def _cue_authority_v5(
    known_cue_ids: set[int] | None,
    transcript: TranscriptDocument | None,
    cues: Sequence[SemanticCue] | None = None,
) -> set[int] | None:
    """Intersect supplied evidence scopes; absent transcript never invents cue existence."""
    if transcript is None and cues is None:
        return set(known_cue_ids) if known_cue_ids is not None else None
    available = set(_cue_map_v5(transcript, cues))
    if cues is not None:
        available &= {cue.cue_id for cue in cues}
    return available if known_cue_ids is None else available & known_cue_ids


def _evidence(
    value: object,
    known: set[int] | None,
    loc: tuple[str | int, ...],
    errors: list[LineageErrorV5],
) -> None:
    if known is not None and isinstance(value, list):
        for i, v in enumerate(value):
            if type(v) is int and v not in known:
                _error(errors, (*loc, i), "unknown_cue")


def discovery_errors_v5(
    raw: Mapping[str, Any], known_cue_ids: set[int] | None
) -> list[LineageErrorV5]:
    errors: list[LineageErrorV5] = []
    _index(raw.get("logical_windows"), "logical_window_id", ("logical_windows",), errors)
    _index(raw.get("topic_fragments"), "topic_fragment_id", ("topic_fragments",), errors)
    _index(raw.get("candidates"), "candidate_id", ("candidates",), errors)
    window_ids = _authority_ids(raw.get("logical_windows"), "logical_window_id")
    fragment_ids = _authority_ids(raw.get("topic_fragments"), "topic_fragment_id")
    candidate_ids = _authority_ids(raw.get("candidates"), "candidate_id")
    for field in ("candidates", "topic_fragments"):
        for i, row in _rows(raw.get(field)):
            loc = (field, i)
            if (
                "source_batch_id" in row
                and "batch_id" in raw
                and (row["source_batch_id"] != raw["batch_id"])
            ):
                _error(errors, (*loc, "source_batch_id"), "batch_mismatch")
            for key in ("start_cue_id", "end_cue_id"):
                cue = row.get(key)
                if known_cue_ids is not None and type(cue) is int and cue not in known_cue_ids:
                    _error(errors, (*loc, key), "unknown_cue")
            start, end = row.get("start_cue_id"), row.get("end_cue_id")
            if type(start) is int and type(end) is int and end < start:
                _error(errors, loc, "reversed_interval")
            _evidence(
                row.get("evidence_cue_ids"), known_cue_ids, (*loc, "evidence_cue_ids"), errors
            )
            _unique_refs(row.get("possible_profiles"), None, (*loc, "possible_profiles"), errors)
            if field == "candidates":
                for key, authority in (
                    ("topic_fragment_ids", fragment_ids),
                    ("source_window_ids", window_ids),
                ):
                    _unique_refs(row.get(key), authority, (*loc, key), errors)
                _index(row.get("risks"), "risk_id", (*loc, "risks"), errors)
                for j, risk in _rows(row.get("risks")):
                    _evidence(
                        risk.get("evidence_cue_ids"),
                        known_cue_ids,
                        (*loc, "risks", j, "evidence_cue_ids"),
                        errors,
                    )
            elif (
                isinstance(row.get("logical_window_id"), str)
                and window_ids is not None
                and row["logical_window_id"] not in window_ids
            ):
                _error(errors, (*loc, "logical_window_id"), "unknown_id")
    for i, row in _rows(raw.get("logical_windows")):
        loc = ("logical_windows", i)
        for key, authority in (("candidate_ids", candidate_ids), ("fragment_ids", fragment_ids)):
            _unique_refs(row.get(key), authority, (*loc, key), errors)
        for side in ("left_boundary", "right_boundary"):
            boundary = row.get(side)
            if isinstance(boundary, dict):
                for key, authority in (
                    ("related_candidate_ids", candidate_ids),
                    ("related_fragment_ids", fragment_ids),
                ):
                    _unique_refs(boundary.get(key), authority, (*loc, side, key), errors)
                _evidence(
                    boundary.get("evidence_cue_ids"),
                    known_cue_ids,
                    (*loc, side, "evidence_cue_ids"),
                    errors,
                )
    return errors


def _discovery_ownership_errors_v5(
    raw: Mapping[str, Any],
    transcript: TranscriptDocument | None,
    cues: Sequence[SemanticCue] | None = None,
) -> list[LineageErrorV5]:
    """Check transport ownership when both cue timing and declared bounds are known."""
    if not isinstance(raw.get("ownership_interval"), dict):
        return []
    ownership = raw["ownership_interval"]
    lower, upper = ownership.get("start_ms"), ownership.get("end_ms")
    if type(lower) is not int or type(upper) is not int:
        return []
    cue_map = _cue_map_v5(transcript, cues)
    errors: list[LineageErrorV5] = []
    for i, candidate in _rows(raw.get("candidates")):
        start_id = candidate.get("start_cue_id")
        start = cue_map.get(start_id) if type(start_id) is int else None
        if start is not None and not lower <= start.start_ms < upper:
            _error(errors, ("candidates", i, "start_cue_id"), "outside_batch_ownership")
    return errors


T = TypeVar("T", bound=BaseModel)


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON object member")
        value[key] = item
    return value


def _reject_constant(value: str) -> Any:
    raise ValueError("nonfinite JSON constant")


def parse_response_v5(model: type[T], text: str) -> T:
    """Strict wire parsing also rejects duplicate keys and nonstandard constants."""
    parse_raw_response_v5(text)
    return model.model_validate_json(text)


def parse_raw_response_v5(text: str) -> Any:
    """Keep original partial objects and indices while enforcing strict JSON syntax."""
    return json.loads(text, object_pairs_hook=_strict_object, parse_constant=_reject_constant)


def discovery_request_errors_v5(
    raw: Mapping[str, Any],
    *,
    expected_batch_id: str,
    expected_context: TimeRangeV4,
    expected_ownership: TimeRangeV4,
    expected_windows: Sequence[TimeRangeV4],
    cues: Sequence[SemanticCue],
) -> tuple[LineageErrorV5, ...]:
    errors: list[LineageErrorV5] = []
    for field, expected in (
        ("batch_id", expected_batch_id),
        ("batch_context", expected_context.model_dump(mode="json")),
        ("ownership_interval", expected_ownership.model_dump(mode="json")),
    ):
        if field in raw:
            _compare_available_v5(
                expected, raw[field], (field,), errors, code="immutable_request_mismatch"
            )
    windows = raw.get("logical_windows")
    if isinstance(windows, list):
        if len(windows) != len(expected_windows):
            _error(errors, ("logical_windows",), "window_count_mismatch")
        for index, window in _rows(windows):
            if index < len(expected_windows):
                expected_window = expected_windows[index]
                if (
                    isinstance(expected_window, LogicalWindowAuthorityV5)
                    and "logical_window_id" in window
                ):
                    _compare_available_v5(
                        expected_window.logical_window_id,
                        window["logical_window_id"],
                        ("logical_windows", index, "logical_window_id"),
                        errors,
                        code="immutable_request_mismatch",
                    )
                for field, value in (
                    ("window_start_ms", expected_window.start_ms),
                    ("window_end_ms", expected_window.end_ms),
                ):
                    if field in window:
                        _compare_available_v5(
                            value,
                            window[field],
                            ("logical_windows", index, field),
                            errors,
                            code="immutable_request_mismatch",
                        )
    errors.extend(
        _discovery_ownership_errors_v5(
            dict(raw, ownership_interval=expected_ownership.model_dump(mode="json")), None, cues
        )
    )
    return tuple(errors)


def _projection(value: BaseModel, model: type[T]) -> T:
    raw = value.model_dump(mode="json")
    return model.model_validate_json(
        json.dumps({k: v for k, v in raw.items() if k in model.model_fields})
    )


def validate_discovery_batch_v5(
    output: DiscoveryBatchOutputV5,
    *,
    expected_batch_id: str,
    expected_context: TimeRangeV4,
    expected_ownership: TimeRangeV4,
    expected_windows: Sequence[TimeRangeV4],
    transcript: TranscriptDocument,
    available_cue_ids: Sequence[int] | None = None,
) -> DiscoveryBatchOutputV5:
    known = {c.cue_id for c in transcript_cues(transcript)}
    if available_cue_ids is not None:
        known &= set(available_cue_ids)
    raw = output.model_dump(mode="json")
    _fail(discovery_errors_v5(raw, known))
    _fail(
        discovery_request_errors_v5(
            raw,
            expected_batch_id=expected_batch_id,
            expected_context=expected_context,
            expected_ownership=expected_ownership,
            expected_windows=expected_windows,
            cues=tuple(c for c in transcript_cues(transcript) if c.cue_id in known),
        )
    )
    # Typed risk records are never converted to a second semantic risk channel.
    projection = dict(raw, schema_version="4")
    projection.pop("contract_version")
    projection["candidates"] = [
        {k: v for k, v in row.items() if k != "risks"} for row in raw["candidates"]
    ]
    validate_discovery_batch_v4(
        DiscoveryBatchOutputV4.model_validate_json(json.dumps(projection)),
        expected_batch_id=expected_batch_id,
        expected_context=expected_context,
        expected_ownership=expected_ownership,
        expected_windows=tuple(
            TimeRangeV4(start_ms=window.start_ms, end_ms=window.end_ms)
            for window in expected_windows
        ),
        transcript=transcript,
        available_cue_ids=available_cue_ids,
    )
    return output


def _identity(kind: str, *parts: str) -> str:
    # Tuple framing avoids ambiguous prefixes; the map builder also detects collisions.
    digest = hashlib.sha256(json.dumps((kind, *parts), ensure_ascii=True).encode()).hexdigest()
    return f"{kind}_{digest}"


def namespace_discovery_batch_v5(output: DiscoveryBatchOutputV5) -> DiscoveryBatchOutputV5:
    raw = output.model_dump(mode="json")
    known = {v for row in raw["candidates"] for v in row["evidence_cue_ids"]}
    # Reference/duplicate validation is independent of transcript cue validation here.
    errors = [e for e in discovery_errors_v5(raw, known) if e.code != "unknown_cue"]
    _fail(errors)
    maps: dict[str, dict[str, str]] = {}
    for kind, values in (
        ("candidate", [v.candidate_id for v in output.candidates]),
        ("fragment", [v.topic_fragment_id for v in output.topic_fragments]),
        ("window", [v.logical_window_id for v in output.logical_windows]),
        ("topic", sorted({v.source_topic_id for v in output.candidates})),
    ):
        maps[kind] = {v: _identity(kind, output.batch_id, v) for v in values}
        if len(set(maps[kind].values())) != len(values):
            raise ValueError("namespace identity collision")
    for row in raw["candidates"]:
        row["candidate_id"] = maps["candidate"][row["candidate_id"]]
        row["source_topic_id"] = maps["topic"][row["source_topic_id"]]
        row["topic_fragment_ids"] = [maps["fragment"][v] for v in row["topic_fragment_ids"]]
        row["source_window_ids"] = [maps["window"][v] for v in row["source_window_ids"]]
    for row in raw["topic_fragments"]:
        row["topic_fragment_id"] = maps["fragment"][row["topic_fragment_id"]]
        row["logical_window_id"] = maps["window"][row["logical_window_id"]]
    for row in raw["logical_windows"]:
        row["logical_window_id"] = maps["window"][row["logical_window_id"]]
        row["candidate_ids"] = [maps["candidate"][v] for v in row["candidate_ids"]]
        row["fragment_ids"] = [maps["fragment"][v] for v in row["fragment_ids"]]
        for side in ("left_boundary", "right_boundary"):
            for field, kind in (
                ("related_candidate_ids", "candidate"),
                ("related_fragment_ids", "fragment"),
            ):
                row[side][field] = [maps[kind][v] for v in row[side][field]]
    return DiscoveryBatchOutputV5.model_validate_json(json.dumps(raw))


def attribute_risks_v5(originals: Sequence[DiscoveryCandidateV5]) -> tuple[AttributedRiskV5, ...]:
    result: list[AttributedRiskV5] = []
    seen_originals: set[str] = set()
    seen: set[str] = set()
    for original in originals:
        if original.candidate_id in seen_originals:
            raise ValueError("duplicate original ID")
        seen_originals.add(original.candidate_id)
        for risk in original.risks:
            risk_id = _identity(
                "risk", original.source_batch_id, original.candidate_id, risk.risk_id
            )
            if risk_id in seen:
                raise ValueError("duplicate risk identity")
            seen.add(risk_id)
            result.append(
                AttributedRiskV5(
                    risk_id=risk_id,
                    local_risk_id=risk.risk_id,
                    flag=risk.flag,
                    reason=risk.reason,
                    evidence_cue_ids=risk.evidence_cue_ids,
                    original_candidate_id=original.candidate_id,
                    source_batch_id=original.source_batch_id,
                    source_window_ids=original.source_window_ids,
                    source_fragment_ids=original.topic_fragment_ids,
                )
            )
    return tuple(result)


def expected_routes_v5(
    originals: Sequence[DiscoveryCandidateV5],
    chains: Sequence[TopicChainV4],
    fragments: Sequence[TopicFragmentV4],
) -> tuple[SourceRouteV5, ...]:
    return _source_routes_v5(originals, chains, fragments, require_all_originals=True)


def routes_for_chain_v5(
    originals: Sequence[DiscoveryCandidateV5],
    chain: TopicChainV4,
    fragments: Sequence[TopicFragmentV4],
) -> tuple[SourceRouteV5, ...]:
    return _source_routes_v5(originals, (chain,), fragments, require_all_originals=False)


def _source_routes_v5(
    originals: Sequence[DiscoveryCandidateV5],
    chains: Sequence[TopicChainV4],
    fragments: Sequence[TopicFragmentV4],
    *,
    require_all_originals: bool,
) -> tuple[SourceRouteV5, ...]:
    for values in (
        [o.candidate_id for o in originals],
        [c.topic_chain_id for c in chains],
        [f.topic_fragment_id for f in fragments],
    ):
        if len(set(values)) != len(values):
            raise ValueError("duplicate authority ID")
    known = {f.topic_fragment_id for f in fragments}
    for ids in (*[o.topic_fragment_ids for o in originals], *[c.fragment_ids for c in chains]):
        if len(set(ids)) != len(ids) or not set(ids) <= known:
            raise ValueError("unknown or duplicate fragment reference")
    routes = tuple(
        SourceRouteV5(original_candidate_id=o.candidate_id, topic_chain_id=c.topic_chain_id)
        for o in originals
        for c in chains
        if set(o.topic_fragment_ids) & set(c.fragment_ids)
    )
    if require_all_originals and {o.candidate_id for o in originals} != {
        r.original_candidate_id for r in routes
    }:
        raise ValueError("unrouted original")
    return routes


def topic_chain_structure_errors_v5(raw: Mapping[str, Any]) -> list[LineageErrorV5]:
    """The unchanged V4 review invariants, checked only from present claims."""
    errors: list[LineageErrorV5] = []
    candidates = raw.get("candidates")
    if isinstance(candidates, list) and "rejection_reason" in raw:
        reason = raw["rejection_reason"]
        if candidates and isinstance(reason, str):
            _error(errors, ("rejection_reason",), "candidates_with_rejection")
        if not candidates and reason is None:
            _error(errors, ("rejection_reason",), "empty_chain_without_rejection")
    if raw.get("chain_status") == "closed" and (
        raw.get("left_closed") is False or raw.get("right_closed") is False
    ):
        _error(errors, ("chain_status",), "closed_chain_requires_closed_sides")
    return errors


def topic_chain_errors_v5(
    raw: Mapping[str, Any],
    *,
    chain: TopicChainV4,
    routes: Sequence[SourceRouteV5],
    known_cue_ids: set[int],
    unit_ids: set[str] | None = None,
    transcript: TranscriptDocument | None = None,
) -> list[LineageErrorV5]:
    return _topic_chain_errors_raw_v5(
        raw,
        chain=chain.model_dump(mode="json"),
        expected={
            r.original_candidate_id for r in routes if r.topic_chain_id == chain.topic_chain_id
        },
        known_cue_ids=known_cue_ids,
        unit_ids=unit_ids,
        transcript=transcript,
    )


def _unit_constraints_raw_v5(
    raw: Mapping[str, Any],
    *,
    chain: Mapping[str, Any],
    unit_ids: set[str] | None,
    transcript: TranscriptDocument | None,
    cues: Sequence[SemanticCue] | None = None,
) -> list[LineageErrorV5]:
    """Check available unit claims without requiring valid prose or a whole model."""
    errors: list[LineageErrorV5] = []
    cue_map = _cue_map_v5(transcript, cues)
    chain_start, chain_end = chain.get("source_start_cue_id"), chain.get("source_end_cue_id")
    mini_maximum_ms = clip_profile_spec(ClipProfile.MINI_LESSON).maximum_duration_ms
    long_chain = (
        type(chain_start) is int
        and type(chain_end) is int
        and chain_start in cue_map
        and chain_end in cue_map
        and cue_map[chain_end].end_ms - cue_map[chain_start].start_ms > mini_maximum_ms
    )
    for i, row in _rows(raw.get("candidates")):
        loc = ("candidates", i)
        variant = row.get("variant_of")
        if isinstance(variant, str):
            if variant == row.get("candidate_id"):
                _error(errors, (*loc, "variant_of"), "self_variant_reference")
            elif unit_ids is not None and variant not in unit_ids:
                _error(errors, (*loc, "variant_of"), "unknown_variant_reference")
        if (
            "variant_of" in row
            and "variant_relationship" in row
            and (variant is None or isinstance(variant, str))
            and row["variant_relationship"] in (None, "short_version_of", "long_version_of")
            and (variant is None) != (row["variant_relationship"] is None)
        ):
            _error(errors, (*loc, "variant_relationship"), "incomplete_variant_relationship")
        start, end = row.get("start_cue_id"), row.get("end_cue_id")
        if type(start) is int and type(end) is int:
            if end < start:
                _error(errors, (*loc, "end_cue_id"), "reversed_interval")
            if (type(chain_start) is int and start < chain_start) or (
                type(chain_end) is int and end > chain_end
            ):
                _error(errors, (*loc, "end_cue_id"), "unit_escapes_chain")
            if (
                start in cue_map
                and end in cue_map
                and start <= end
                and row.get("clip_profile") in ("mini_lesson", "short_highlight")
            ):
                spec = clip_profile_spec(row["clip_profile"])
                duration = cue_map[end].end_ms - cue_map[start].start_ms
                if not spec.minimum_duration_ms <= duration <= spec.maximum_duration_ms:
                    _error(errors, (*loc, "end_cue_id"), "profile_duration_violation")
        if row.get("natural_subunit") is True and row.get("natural_split_evidence_cue_ids") == []:
            _error(
                errors, (*loc, "natural_split_evidence_cue_ids"), "missing_natural_split_evidence"
            )
        if (
            long_chain
            and row.get("clip_profile") == "mini_lesson"
            and row.get("natural_subunit") is False
        ):
            _error(errors, (*loc, "natural_subunit"), "requires_natural_teaching_subunits")
    if (
        long_chain
        and raw.get("candidates") == []
        and "rejection_reason" in raw
        and raw["rejection_reason"] != "topic_too_long_without_natural_split"
    ):
        _error(errors, ("rejection_reason",), "unsplit_long_chain_requires_rejection")
    return errors


def _topic_chain_errors_raw_v5(
    raw: Mapping[str, Any],
    *,
    chain: Mapping[str, Any],
    expected: set[str] | None,
    known_cue_ids: set[int] | None,
    unit_ids: set[str] | None = None,
    transcript: TranscriptDocument | None = None,
    source_membership: Mapping[str, bool | None] | None = None,
    source_universe_complete: bool = False,
    cues: Sequence[SemanticCue] | None = None,
) -> list[LineageErrorV5]:
    raw = _contract_defaults_v5(TopicChainReviewV5, raw)
    known_cue_ids = _cue_authority_v5(known_cue_ids, transcript, cues)
    lower, upper = chain.get("source_start_cue_id"), chain.get("source_end_cue_id")

    def invalid_cue(cue: object) -> bool:
        if type(cue) is not int:
            return False
        return (
            (known_cue_ids is not None and cue not in known_cue_ids)
            or (type(lower) is int and cue < lower)
            or (type(upper) is int and cue > upper)
        )

    def evidence(value: object, location: tuple[str | int, ...]) -> None:
        # Chain bounds constrain scope even when actual cue existence is unknown.
        # Inspect only supplied claims, retaining malformed siblings' wire positions.
        if isinstance(value, list):
            for index, cue in enumerate(value):
                if invalid_cue(cue):
                    _error(errors, (*location, index), "unknown_cue")

    errors = topic_chain_structure_errors_v5(raw)
    errors.extend(
        _unit_constraints_raw_v5(
            raw, chain=chain, unit_ids=unit_ids, transcript=transcript, cues=cues
        )
    )
    chain_id = chain.get("topic_chain_id")
    if isinstance(chain_id, str) and "topic_chain_id" in raw and raw["topic_chain_id"] != chain_id:
        _error(errors, ("topic_chain_id",), "chain_mismatch")
    _index(raw.get("candidates"), "candidate_id", ("candidates",), errors)
    _index(
        raw.get("source_dispositions"), "original_candidate_id", ("source_dispositions",), errors
    )
    units = _claims_by_id_v5(raw.get("candidates"), "candidate_id")
    dispositions = _claims_by_id_v5(raw.get("source_dispositions"), "original_candidate_id")
    membership = source_membership or {}

    def forbidden_source(source: str) -> bool:
        return (
            (expected is not None and source not in expected)
            or membership.get(source) is False
            or (source_universe_complete and source not in membership)
        )

    required_sources = (expected or set()) | {
        source for source, included in membership.items() if included is True
    }
    if isinstance(raw.get("source_dispositions"), list):
        for original in sorted(required_sources - dispositions.keys()):
            _error(errors, ("source_dispositions", original), "missing_source_disposition")
    for i, row in _rows(raw.get("source_dispositions")):
        loc = ("source_dispositions", i)
        source = row.get("original_candidate_id")
        if isinstance(source, str) and forbidden_source(source):
            _error(errors, (*loc, "original_candidate_id"), "unexpected_source")
        if (
            isinstance(chain_id, str)
            and "topic_chain_id" in row
            and row["topic_chain_id"] != chain_id
        ):
            _error(errors, (*loc, "topic_chain_id"), "chain_mismatch")
        _unique_refs(
            row.get("derived_unit_ids"),
            _authority_ids(raw.get("candidates"), "candidate_id"),
            (*loc, "derived_unit_ids"),
            errors,
        )
        ids = _ids(row.get("derived_unit_ids"))
        if ids is not None and "rejection_reason" in row:
            reason = row["rejection_reason"]
            if (ids and reason is not None) or (not ids and not reason):
                _error(errors, loc, "invalid_source_disposition")
        evidence(row.get("evidence_cue_ids"), (*loc, "evidence_cue_ids"))
        if ids is not None:
            for j, unit_id in _indexed_ids(row.get("derived_unit_ids")):
                if (
                    isinstance(source, str)
                    and _claim_reference_scope_v5(
                        units.get(unit_id, []), "original_candidate_ids", source
                    )
                    is False
                ):
                    _error(errors, (*loc, "derived_unit_ids", j), "missing_reverse_origin")
    for i, row in _rows(raw.get("candidates")):
        loc = ("candidates", i)
        if (
            isinstance(chain_id, str)
            and "topic_chain_id" in row
            and row["topic_chain_id"] != chain_id
        ):
            _error(errors, (*loc, "topic_chain_id"), "chain_mismatch")
        _unique_refs(
            row.get("source_fragment_ids"),
            set(chain["fragment_ids"]) if _complete_ids(chain.get("fragment_ids")) else None,
            (*loc, "source_fragment_ids"),
            errors,
        )
        _unique_refs(
            row.get("original_candidate_ids"), None, (*loc, "original_candidate_ids"), errors
        )
        for j, source in _indexed_ids(row.get("original_candidate_ids")):
            if forbidden_source(source):
                _error(errors, (*loc, "original_candidate_ids", j), "unknown_id")
        origins = _ids(row.get("original_candidate_ids"))
        if origins is not None:
            if row.get("origin_kind") == "derived" and not origins:
                _error(errors, (*loc, "original_candidate_ids"), "derived_requires_origin")
            if row.get("origin_kind") == "chain_new" and origins:
                _error(errors, (*loc, "original_candidate_ids"), "chain_new_forbids_origins")
            for j, source in _indexed_ids(row.get("original_candidate_ids")):
                if (
                    isinstance(row.get("candidate_id"), str)
                    and _claim_reference_scope_v5(
                        dispositions.get(source, []), "derived_unit_ids", row["candidate_id"]
                    )
                    is False
                ):
                    _error(errors, (*loc, "original_candidate_ids", j), "missing_forward_edge")
        for key in ("evidence_cue_ids", "natural_split_evidence_cue_ids"):
            evidence(row.get(key), (*loc, key))
        for key in ("start_cue_id", "end_cue_id"):
            cue = row.get(key)
            if invalid_cue(cue):
                _error(errors, (*loc, key), "unknown_cue")
    evidence(raw.get("evidence_cue_ids"), ("evidence_cue_ids",))
    return errors


def validate_graph_v5(
    originals: Sequence[DiscoveryCandidateV5],
    chains: Sequence[TopicChainV4],
    fragments: Sequence[TopicFragmentV4],
    reviews: Sequence[TopicChainReviewV5],
    *,
    transcript: TranscriptDocument,
) -> tuple[SourceRouteV5, ...]:
    routes = expected_routes_v5(originals, chains, fragments)
    review_ids = [r.topic_chain_id for r in reviews]
    if len(set(review_ids)) != len(review_ids) or set(review_ids) != {
        c.topic_chain_id for c in chains
    }:
        raise ValueError("duplicate, missing or unknown chain review; expected exact partition")
    unit_ids = [u.candidate_id for r in reviews for u in r.candidates]
    if len(set(unit_ids)) != len(unit_ids):
        raise ValueError("duplicate unit ID across chains")
    chain_map = {c.topic_chain_id: c for c in chains}
    for review in reviews:
        chain = chain_map[review.topic_chain_id]
        known = {
            c.cue_id
            for c in transcript_cues(transcript)
            if chain.source_start_cue_id <= c.cue_id <= chain.source_end_cue_id
        }
        _fail(
            topic_chain_errors_v5(
                review.model_dump(mode="json"),
                chain=chain,
                routes=routes,
                known_cue_ids=known,
                unit_ids=set(unit_ids),
                transcript=transcript,
            )
        )
        raw = review.model_dump(mode="json")
        projection = {k: v for k, v in raw.items() if k in TopicChainReviewV4.model_fields}
        projection["candidates"] = [
            _projection(u, ChainCandidateV4).model_dump(mode="json") for u in review.candidates
        ]
        validate_topic_chain_review_v4(
            TopicChainReviewV4.model_validate_json(json.dumps(projection)),
            chain=chain,
            transcript=transcript,
        )
    return routes


def build_boundary_authority_v5(
    unit: ChainCandidateV5,
    *,
    chain: TopicChainV4,
    originals: Sequence[DiscoveryCandidateV5],
    context_cue_ids: Sequence[int],
) -> BoundaryAuthorityV5:
    if unit.topic_chain_id != chain.topic_chain_id:
        raise ValueError("boundary chain mismatch")
    if not set(unit.source_fragment_ids) <= set(chain.fragment_ids):
        raise ValueError("boundary unit escapes chain fragments")
    if not set(unit.original_candidate_ids) <= {o.candidate_id for o in originals}:
        raise ValueError("unknown boundary origin")
    if any(
        o.candidate_id in unit.original_candidate_ids
        and not set(o.topic_fragment_ids) & set(chain.fragment_ids)
        for o in originals
    ):
        raise ValueError("boundary origin belongs to another chain")
    context = set(context_cue_ids)
    if len(context) != len(context_cue_ids):
        raise ValueError("duplicate Boundary context cue")
    risks = tuple(
        r
        for r in attribute_risks_v5(originals)
        if (
            r.original_candidate_id in unit.original_candidate_ids
            or set(r.source_fragment_ids) & set(chain.fragment_ids)
            or set(r.evidence_cue_ids) & context
        )
    )
    return BoundaryAuthorityV5(
        candidate_id=unit.candidate_id, context_cue_ids=tuple(context_cue_ids), risks=risks
    )


def boundary_treatment_errors_v5(
    raw: Mapping[str, Any],
    *,
    authority: BoundaryAuthorityV5,
) -> list[LineageErrorV5]:
    return _boundary_treatment_errors_raw_v5(raw, authority=authority.model_dump(mode="json"))


def _boundary_treatment_errors_raw_v5(
    raw: Mapping[str, Any],
    *,
    authority: Mapping[str, Any],
    known_cue_ids: set[int] | None = None,
) -> list[LineageErrorV5]:
    """Transcript-independent treatment invariants, shared by wire and contextual validation."""
    raw = _contract_defaults_v5(BoundaryReviewV5, raw)
    errors: list[LineageErrorV5] = []
    known_cue_ids = _boundary_context_ids_v5(authority, known_cue_ids)
    risks = _claims_by_id_v5(authority.get("risks"), "risk_id")
    treatments = _index(raw.get("risk_treatments"), "risk_id", ("risk_treatments",), errors)
    if isinstance(raw.get("risk_treatments"), list):
        for missing_id in sorted(risks.keys() - treatments.keys()):
            _error(errors, ("risk_treatments", missing_id), "missing_risk_treatment")
    decision = raw.get("content_decision")
    if decision == "drop" and any(
        raw.get(k) is not None for k in ("proposed_start_cue_id", "proposed_end_cue_id")
    ):
        _error(errors, ("proposed_start_cue_id",), "drop_forbids_final_span")
    flags = _ids(raw.get("risk_flags"))
    for i, row in _rows(raw.get("risk_treatments")):
        loc = ("risk_treatments", i)
        _evidence(row.get("evidence_cue_ids"), known_cue_ids, (*loc, "evidence_cue_ids"), errors)
        risk_id = row.get("risk_id")
        claims = risks.get(risk_id, []) if isinstance(risk_id, str) else []
        if (
            isinstance(risk_id, str)
            and not claims
            and authority.get("membership_complete", True)
            and _authority_ids(authority.get("risks"), "risk_id") is not None
        ):
            _error(errors, (*loc, "risk_id"), "unknown_risk")
        treatment = row.get("treatment")
        if decision == "drop" and isinstance(treatment, str) and treatment != "dropped_candidate":
            _error(errors, (*loc, "treatment"), "drop_requires_dropped_candidate")
        if decision in ("keep", "repair_boundary") and treatment == "dropped_candidate":
            _error(errors, (*loc, "treatment"), "retained_forbids_dropped_candidate")
        if (
            treatment in ("applies", "uncertain")
            and flags is not None
            and any(
                isinstance(risk.get("flag"), str) and risk["flag"] not in flags for risk in claims
            )
        ):
            _error(errors, (*loc, "treatment"), "missing_source_flag")
        if treatment == "uncertain" and flags is not None and "sensitivity_review" not in flags:
            _error(errors, (*loc, "treatment"), "missing_sensitivity_review")
    return errors


def boundary_errors_v5(
    raw: Mapping[str, Any],
    *,
    authority: BoundaryAuthorityV5,
    unit: ChainCandidateV5,
    transcript: TranscriptDocument,
) -> list[LineageErrorV5]:
    return _boundary_errors_raw_v5(
        raw,
        authority=authority.model_dump(mode="json"),
        unit=unit.model_dump(mode="json"),
        transcript=transcript,
    )


def _boundary_identity_errors_raw_v5(
    raw: Mapping[str, Any], unit: Mapping[str, Any]
) -> list[LineageErrorV5]:
    """Compare supplied unit claims without requiring transcript or risk authority."""
    errors: list[LineageErrorV5] = []
    if (
        "candidate_id" in raw
        and "candidate_id" in unit
        and raw["candidate_id"] != unit["candidate_id"]
    ):
        _error(errors, ("candidate_id",), "candidate_mismatch")
    if (
        "clip_profile" in raw
        and "clip_profile" in unit
        and raw["clip_profile"] != unit["clip_profile"]
    ):
        _error(errors, ("clip_profile",), "profile_mismatch")
    proposed = (raw.get("proposed_start_cue_id"), raw.get("proposed_end_cue_id"))
    original = (unit.get("start_cue_id"), unit.get("end_cue_id"))
    if raw.get("content_decision") == "keep":
        for edge, claimed, expected in zip(("start", "end"), proposed, original, strict=True):
            if type(claimed) is int and type(expected) is int and claimed != expected:
                _error(errors, (f"proposed_{edge}_cue_id",), "keep_changed_span")
    if (
        raw.get("content_decision") == "repair_boundary"
        and all(type(value) is int for value in (*proposed, *original))
        and proposed == original
    ):
        _error(errors, ("proposed_start_cue_id",), "repair_unchanged_span")
    return errors


def _boundary_quality_errors_v5(raw: Mapping[str, Any]) -> list[LineageErrorV5]:
    errors = [
        LineageErrorV5(location=(), code="current_quality", message=message)
        for message in boundary_consistency_errors_v4(raw)
    ]
    if raw.get("content_decision") in ("keep", "repair_boundary"):
        if raw.get("continuous_source_interval") is False:
            errors.append(
                LineageErrorV5(
                    location=(),
                    code="current_quality",
                    message="the first mini-lesson release supports one continuous interval only",
                )
            )
        start, end = raw.get("proposed_start_cue_id"), raw.get("proposed_end_cue_id")
        if type(start) is int and type(end) is int and end < start:
            _error(errors, ("proposed_end_cue_id",), "reversed_interval")
    return errors


def _boundary_context_ids_v5(
    authority: Mapping[str, Any],
    known_cue_ids: set[int] | None,
) -> set[int] | None:
    context = authority.get("context_cue_ids")
    if isinstance(context, list) and all(type(cue) is int for cue in context):
        supplied = set(context)
        return supplied if known_cue_ids is None else supplied & known_cue_ids
    return known_cue_ids


def _boundary_references_v5(
    raw: Mapping[str, Any],
    known: set[int] | None,
) -> list[LineageErrorV5]:
    errors: list[LineageErrorV5] = []
    evidence = raw.get("evidence")
    if isinstance(evidence, dict):
        for field in ("opening_cue_ids", "core_cue_ids", "ending_cue_ids"):
            _evidence(evidence.get(field), known, ("evidence", field), errors)
    for i, row in _rows(raw.get("interruption_review")):
        _evidence(
            row.get("evidence_cue_ids"),
            known,
            ("interruption_review", i, "evidence_cue_ids"),
            errors,
        )
    if raw.get("content_decision") in ("keep", "repair_boundary") and known is not None:
        for field in ("proposed_start_cue_id", "proposed_end_cue_id"):
            cue = raw.get(field)
            if type(cue) is int and cue not in known:
                _error(errors, (field,), "unknown_cue")
    return errors


def _boundary_errors_raw_v5(
    raw: Mapping[str, Any],
    *,
    authority: Mapping[str, Any],
    unit: Mapping[str, Any],
    transcript: TranscriptDocument | None,
    known_cue_ids: set[int] | None = None,
    cues: Sequence[SemanticCue] | None = None,
) -> list[LineageErrorV5]:
    raw = _contract_defaults_v5(BoundaryReviewV5, raw)
    errors = _boundary_identity_errors_raw_v5(raw, unit)
    all_cues = _cue_map_v5(transcript, cues)
    known = _cue_authority_v5(known_cue_ids, transcript, cues)
    # Actual unit times establish its allowed expansion scope even when a
    # redundant authority copy is absent. Never fabricate timing for local IDs.
    unit_start, unit_end = unit.get("start_cue_id"), unit.get("end_cue_id")
    if (
        type(unit_start) is int
        and type(unit_end) is int
        and unit_start <= unit_end
        and unit_start in all_cues
        and unit_end in all_cues
    ):
        allowed = {
            cue.cue_id
            for cue in all_cues.values()
            if cue.end_ms > max(0, all_cues[unit_start].start_ms - 30_000)
            and cue.start_ms < all_cues[unit_end].end_ms + 30_000
        }
        known = allowed if known is None else known & allowed
    known = _boundary_context_ids_v5(authority, known)
    errors.extend(_boundary_quality_errors_v5(raw))
    errors.extend(_boundary_references_v5(raw, known))
    errors.extend(_boundary_treatment_errors_raw_v5(raw, authority=authority, known_cue_ids=known))
    risks = _claims_by_id_v5(authority.get("risks"), "risk_id")
    start, end = raw.get("proposed_start_cue_id"), raw.get("proposed_end_cue_id")
    span = (start, end) if type(start) is int and type(end) is int and start <= end else None
    final_times = (
        (all_cues[span[0]].start_ms, all_cues[span[1]].end_ms)
        if span and span[0] in all_cues and span[1] in all_cues
        else None
    )
    decision = raw.get("content_decision")
    if (
        final_times
        and decision in ("keep", "repair_boundary")
        and unit.get("clip_profile") in ("mini_lesson", "short_highlight")
    ):
        spec = clip_profile_spec(unit["clip_profile"])
        if (
            not spec.minimum_duration_ms
            <= final_times[1] - final_times[0]
            <= spec.maximum_duration_ms
        ):
            errors.append(
                LineageErrorV5(
                    location=(),
                    code="current_quality",
                    message="Boundary Review duration is outside its Profile",
                )
            )
    for i, row in _rows(raw.get("risk_treatments")):
        loc = ("risk_treatments", i)
        risk_id = row.get("risk_id")
        claims = risks.get(risk_id, []) if isinstance(risk_id, str) else []
        treatment = row.get("treatment")
        if final_times and decision in ("keep", "repair_boundary"):
            if treatment == "outside_final_span" and any(
                type(c) is int
                and c in all_cues
                and all_cues[c].end_ms > final_times[0]
                and all_cues[c].start_ms < final_times[1]
                for risk in claims
                if isinstance(risk.get("evidence_cue_ids"), list)
                for c in risk["evidence_cue_ids"]
            ):
                _error(errors, (*loc, "treatment"), "source_evidence_inside_final_span")
            if treatment == "resolved_in_context" and isinstance(row.get("evidence_cue_ids"), list):
                for j, cue in enumerate(row["evidence_cue_ids"]):
                    if (
                        type(cue) is int
                        and cue in all_cues
                        and not (
                            final_times[0] <= all_cues[cue].start_ms
                            and all_cues[cue].end_ms <= final_times[1]
                        )
                    ):
                        _error(
                            errors, (*loc, "evidence_cue_ids", j), "resolution_outside_final_span"
                        )
    return errors


def validate_boundary_review_v5(
    review: BoundaryReviewV5,
    *,
    authority: BoundaryAuthorityV5,
    unit: ChainCandidateV5,
    transcript: TranscriptDocument,
) -> BoundaryReviewV5:
    if authority.candidate_id != unit.candidate_id:
        raise ValueError("authority candidate mismatch")
    risk_ids = [r.risk_id for r in authority.risks]
    if len(set(risk_ids)) != len(risk_ids):
        raise ValueError("duplicate risk authority")
    cues = {c.cue_id: c for c in transcript_cues(transcript)}
    if unit.start_cue_id not in cues or unit.end_cue_id not in cues:
        raise ValueError("unknown Boundary unit endpoint")
    start, end = cues[unit.start_cue_id], cues[unit.end_cue_id]
    expected_context = tuple(
        c.cue_id
        for c in cues.values()
        if c.end_ms > max(0, start.start_ms - 30_000)
        and c.start_ms < min(transcript.source_duration_ms, end.end_ms + 30_000)
    )
    if authority.context_cue_ids != expected_context:
        raise ValueError("Boundary authority must cover the complete allowed context")
    _fail(
        boundary_errors_v5(
            review.model_dump(mode="json"), authority=authority, unit=unit, transcript=transcript
        )
    )
    validate_boundary_review_v4(
        _projection(review, BoundaryReviewV4),
        candidate=_projection(unit, ChainCandidateV4),
        transcript=transcript,
        validation_contract=CURRENT_SEMANTIC_VALIDATION,
    )
    return review


def partition_errors_v5(raw: Mapping[str, Any], unit_ids: set[str] | None) -> list[LineageErrorV5]:
    errors: list[LineageErrorV5] = []
    seen: set[str] = set()
    complete = True
    for field in FinalPartitionV5.model_fields:
        ids = _ids(raw.get(field))
        if ids is None:
            complete = False
            continue
        for i, unit_id in _indexed_ids(raw.get(field)):
            if unit_id in seen:
                _error(errors, (field, i), "duplicate_final_disposition")
            if unit_ids is not None and unit_id not in unit_ids:
                _error(errors, (field, i), "unknown_unit")
            seen.add(unit_id)
    if complete and unit_ids is not None:
        for unit_id in sorted(unit_ids - seen):
            _error(errors, (unit_id,), "missing_final_disposition")
    return errors


def boundary_disposition_errors_v5(
    boundary: Mapping[str, Any], disposition: object
) -> list[LineageErrorV5]:
    """Necessary Boundary gates only; absent Global decisions are never inferred."""
    errors: list[LineageErrorV5] = []
    if disposition not in ("selected", "manual", "blocked", "rejected", "top_n_excluded"):
        return errors
    quality = set(_ids(boundary.get("quality_flags")) or [])
    risks = set(_ids(boundary.get("risk_flags")) or [])
    if boundary.get("content_decision") == "drop" and disposition != "rejected":
        _error(errors, (), "dropped_unit_must_be_rejected")
    if quality & BLOCKING_QUALITY_FLAGS_V4 and disposition != "rejected":
        _error(errors, (), "blocking_quality_requires_rejected")
    if boundary.get("continuous_source_interval") is False and disposition != "rejected":
        _error(errors, (), "discontinuous_unit_requires_rejected")
    if (
        any(row.get("blocking") is True for _, row in _rows(boundary.get("interruption_review")))
        and disposition != "rejected"
    ):
        _error(errors, (), "blocking_interruption_requires_rejected")
    if "medical_claim" in risks and disposition not in ("blocked", "rejected"):
        _error(errors, (), "medical_risk_requires_blocked_or_rejected")
    if disposition in ("selected", "top_n_excluded") and (quality or risks):
        _error(errors, (), "automatic_unit_contradicts_boundary_gate")
    return errors


def build_lineage_ledger_v5(
    *,
    batches: Sequence[DiscoveryBatchOutputV5],
    chains: Sequence[TopicChainV4],
    reviews: Sequence[TopicChainReviewV5],
    boundaries: Sequence[BoundaryReviewV5],
    partition: FinalPartitionV5,
    transcript: TranscriptDocument,
) -> LineageLedgerV5:
    batch_ids = [b.batch_id for b in batches]
    if len(set(batch_ids)) != len(batch_ids):
        raise ValueError("duplicate batch ID")
    for batch in batches:
        validate_discovery_batch_v5(
            batch,
            expected_batch_id=batch.batch_id,
            expected_context=batch.batch_context,
            expected_ownership=batch.ownership_interval,
            expected_windows=tuple(
                TimeRangeV4(start_ms=w.window_start_ms, end_ms=w.window_end_ms)
                for w in batch.logical_windows
            ),
            transcript=transcript,
        )
    originals = tuple(o for b in batches for o in b.candidates)
    fragments = tuple(f for b in batches for f in b.topic_fragments)
    validate_graph_v5(originals, chains, fragments, reviews, transcript=transcript)
    units = tuple(u for r in reviews for u in r.candidates)
    raw_partition = partition.model_dump(mode="json")
    _fail(partition_errors_v5(raw_partition, {u.candidate_id for u in units}))
    boundary_ids = [b.candidate_id for b in boundaries]
    if len(set(boundary_ids)) != len(boundary_ids) or set(boundary_ids) != {
        u.candidate_id for u in units
    }:
        raise ValueError("boundaries must exactly partition units")
    boundary_map = {b.candidate_id: b for b in boundaries}
    chain_map = {c.topic_chain_id: c for c in chains}
    dispositions: dict[str, FinalDisposition] = {}
    for field in FinalPartitionV5.model_fields:
        for unit_id in getattr(partition, field):
            dispositions[unit_id] = field  # type: ignore[assignment]
    cue_map = {c.cue_id: c for c in transcript_cues(transcript)}
    outcomes: list[UnitOutcomeV5] = []
    for unit in units:
        start, end = cue_map[unit.start_cue_id], cue_map[unit.end_cue_id]
        context = tuple(
            c.cue_id
            for c in cue_map.values()
            if c.end_ms > max(0, start.start_ms - 30_000)
            and c.start_ms < min(transcript.source_duration_ms, end.end_ms + 30_000)
        )
        authority = build_boundary_authority_v5(
            unit, chain=chain_map[unit.topic_chain_id], originals=originals, context_cue_ids=context
        )
        boundary = validate_boundary_review_v5(
            boundary_map[unit.candidate_id], authority=authority, unit=unit, transcript=transcript
        )
        _fail(
            boundary_disposition_errors_v5(
                boundary.model_dump(mode="json"), dispositions[unit.candidate_id]
            )
        )
        outcomes.append(
            UnitOutcomeV5(
                unit=unit,
                disposition=dispositions[unit.candidate_id],
                authority=authority,
                boundary=boundary,
            )
        )
    risks = attribute_risks_v5(originals)
    records: list[OriginalLineageV5] = []
    for original in originals:
        paths: list[TerminalPathV5] = []
        for review in reviews:
            for source in review.source_dispositions:
                if source.original_candidate_id != original.candidate_id:
                    continue
                for unit_id in source.derived_unit_ids or (None,):
                    paths.append(
                        TerminalPathV5(
                            original_candidate_id=original.candidate_id,
                            topic_chain_id=review.topic_chain_id,
                            unit_id=unit_id,
                            disposition=dispositions[unit_id] if unit_id else "rejected",
                            rejection_reason=source.rejection_reason,
                            evidence_cue_ids=source.evidence_cue_ids,
                        )
                    )
        records.append(
            OriginalLineageV5(
                original=original,
                paths=tuple(paths),
                risks=tuple(r for r in risks if r.original_candidate_id == original.candidate_id),
            )
        )
    new = tuple(o for o in outcomes if o.unit.origin_kind == "chain_new")
    return LineageLedgerV5(
        batches=tuple(batches),
        chains=tuple(chains),
        reviews=tuple(reviews),
        originals=tuple(records),
        outcomes=tuple(outcomes),
        chain_new_outcomes=new,
        partition=partition,
        counts=LineageCountsV5(
            originals=len(originals),
            units=len(units),
            derived_units=len(units) - len(new),
            chain_new_units=len(new),
            terminal_paths=sum(len(r.paths) for r in records),
            rejected_source_paths=sum(p.unit_id is None for r in records for p in r.paths),
            **{f: len(getattr(partition, f)) for f in FinalPartitionV5.model_fields},
        ),
    )


def _validate_ledger_records(ledger: LineageLedgerV5) -> None:
    """Check serialized duplication against its authoritative V5 records, without I/O.

    Transcript-dependent validation belongs to the builder; deserialization still
    cannot rewrite provenance, terminal paths, partitions or counts silently.
    """
    batch_ids = [batch.batch_id for batch in ledger.batches]
    if len(batch_ids) != len(set(batch_ids)):
        raise ValueError("duplicate ledger batch ID")
    for batch in ledger.batches:
        _fail(discovery_errors_v5(batch.model_dump(mode="json"), None))
    originals = tuple(o for b in ledger.batches for o in b.candidates)
    risks = attribute_risks_v5(originals)
    fragments = tuple(f for b in ledger.batches for f in b.topic_fragments)
    routes = expected_routes_v5(originals, ledger.chains, fragments)
    chain_ids = [c.topic_chain_id for c in ledger.chains]
    if sorted(r.topic_chain_id for r in ledger.reviews) != sorted(chain_ids):
        raise ValueError("ledger reviews do not match chains")
    units = tuple(u for r in ledger.reviews for u in r.candidates)
    unit_ids = [u.candidate_id for u in units]
    if len(set(unit_ids)) != len(unit_ids):
        raise ValueError("duplicate ledger unit")
    _fail(partition_errors_v5(ledger.partition.model_dump(mode="json"), set(unit_ids)))
    if tuple(o.original for o in ledger.originals) != originals:
        raise ValueError("ledger original provenance changed")
    if tuple(o.unit for o in ledger.outcomes) != units:
        raise ValueError("ledger unit provenance changed")
    dispositions = {
        unit_id: field
        for field in FinalPartitionV5.model_fields
        for unit_id in getattr(ledger.partition, field)
    }
    chain_map = {c.topic_chain_id: c for c in ledger.chains}
    for review in ledger.reviews:
        chain = chain_map[review.topic_chain_id]
        # This set checks chain scope only; the builder also checks actual cue existence.
        evidence = {
            c
            for u in review.candidates
            for c in (
                *u.evidence_cue_ids,
                *u.natural_split_evidence_cue_ids,
                u.start_cue_id,
                u.end_cue_id,
            )
        }
        evidence.update(review.evidence_cue_ids)
        evidence.update(c for s in review.source_dispositions for c in s.evidence_cue_ids)
        known = {c for c in evidence if chain.source_start_cue_id <= c <= chain.source_end_cue_id}
        _fail(
            topic_chain_errors_v5(
                review.model_dump(mode="json"),
                chain=chain,
                routes=routes,
                known_cue_ids=known,
                unit_ids=set(unit_ids),
            )
        )
    for outcome in (*ledger.outcomes, *ledger.chain_new_outcomes):
        _fail(
            _boundary_errors_raw_v5(
                outcome.boundary.model_dump(mode="json"),
                authority=outcome.authority.model_dump(mode="json"),
                unit=outcome.unit.model_dump(mode="json"),
                transcript=None,
            )
        )
    for outcome in ledger.outcomes:
        unit = outcome.unit
        if outcome.disposition != dispositions[unit.candidate_id]:
            raise ValueError("ledger final disposition changed")
        authority = build_boundary_authority_v5(
            unit,
            chain=chain_map[unit.topic_chain_id],
            originals=originals,
            context_cue_ids=outcome.authority.context_cue_ids,
        )
        if outcome.authority != authority:
            raise ValueError("ledger risk authority changed")
        _fail(
            boundary_disposition_errors_v5(
                outcome.boundary.model_dump(mode="json"), outcome.disposition
            )
        )
    expected_new = tuple(o for o in ledger.outcomes if o.unit.origin_kind == "chain_new")
    if ledger.chain_new_outcomes != expected_new:
        raise ValueError("ledger chain_new outcomes changed")
    for record in ledger.originals:
        source_id = record.original.candidate_id
        if record.risks != tuple(r for r in risks if r.original_candidate_id == source_id):
            raise ValueError("ledger original risks changed")
        expected_paths = [
            (
                s.topic_chain_id,
                unit_id,
                dispositions[unit_id] if unit_id else "rejected",
                s.rejection_reason,
                s.evidence_cue_ids,
            )
            for review in ledger.reviews
            for s in review.source_dispositions
            if s.original_candidate_id == source_id
            for unit_id in s.derived_unit_ids or (None,)
        ]
        actual_paths = [
            (p.topic_chain_id, p.unit_id, p.disposition, p.rejection_reason, p.evidence_cue_ids)
            for p in record.paths
            if p.original_candidate_id == source_id
        ]
        if len(actual_paths) != len(record.paths) or actual_paths != expected_paths:
            raise ValueError("ledger terminal paths changed")
    counts = dict(
        originals=len(originals),
        units=len(units),
        derived_units=len(units) - len(expected_new),
        chain_new_units=len(expected_new),
        terminal_paths=sum(len(o.paths) for o in ledger.originals),
        rejected_source_paths=sum(p.unit_id is None for o in ledger.originals for p in o.paths),
        **{field: len(getattr(ledger.partition, field)) for field in FinalPartitionV5.model_fields},
    )
    if ledger.counts.model_dump() != counts:
        raise ValueError("ledger counts changed")


def validate_lineage_ledger_v5(
    ledger: LineageLedgerV5,
    *,
    transcript: TranscriptDocument,
) -> LineageLedgerV5:
    """Require transcript authority before accepting loaded final-span claims.

    Strict JSON loading checks internal structure and treatment/flag consistency;
    it cannot certify source cue existence, actual times or full expansion context.
    Rebuild through the same contextual gates as initial ledger construction.
    """
    validated = build_lineage_ledger_v5(
        batches=ledger.batches,
        chains=ledger.chains,
        reviews=ledger.reviews,
        boundaries=tuple(o.boundary for o in ledger.outcomes),
        partition=ledger.partition,
        transcript=transcript,
    )
    if ledger != validated:
        raise ValueError("loaded ledger differs from contextual authority")
    return ledger


def collect_response_errors_v5(
    model: type[BaseModel],
    text: str,
    *,
    known_cue_ids: set[int] | None = None,
    chain: TopicChainV4 | None = None,
    routes: Sequence[SourceRouteV5] = (),
    authority: BoundaryAuthorityV5 | None = None,
    unit: ChainCandidateV5 | None = None,
    transcript: TranscriptDocument | None = None,
    unit_ids: set[str] | None = None,
    cues: Sequence[SemanticCue] | None = None,
) -> tuple[LineageErrorV5, ...]:
    if cues is not None:
        if model not in (DiscoveryBatchOutputV5, TopicChainReviewV5, BoundaryReviewV5):
            raise ValueError("local cue authority supports only provider response models")
        validate_cues_v5(cues, transcript=transcript)
    errors: list[LineageErrorV5] = []
    try:
        model.model_validate_json(text)
    except ValidationError as exc:
        errors.extend(
            LineageErrorV5(location=tuple(e["loc"]), code="schema", message=e["msg"])
            for e in exc.errors(include_url=False, include_input=False)
        )
    try:
        raw = parse_raw_response_v5(text)
    except (ValueError, TypeError) as exc:
        errors.append(LineageErrorV5(location=(), code="json", message=str(exc)))
        return tuple(errors)
    if not isinstance(raw, dict):
        return tuple(errors)
    if model is DiscoveryBatchOutputV5:
        cue_ids = _cue_authority_v5(known_cue_ids, transcript, cues)
        errors.extend(discovery_errors_v5(raw, cue_ids))
        errors.extend(_discovery_ownership_errors_v5(raw, transcript, cues))
    if model is TopicChainReviewV5:
        errors.extend(
            _topic_chain_errors_raw_v5(
                raw,
                chain=chain.model_dump(mode="json") if chain is not None else {},
                expected={
                    r.original_candidate_id
                    for r in routes
                    if r.topic_chain_id == chain.topic_chain_id
                }
                if chain is not None
                else None,
                known_cue_ids=known_cue_ids,
                unit_ids=unit_ids,
                transcript=transcript,
                cues=cues,
            )
        )
    if model is BoundaryReviewV5:
        errors.extend(
            _boundary_errors_raw_v5(
                raw,
                authority=authority.model_dump(mode="json") if authority is not None else {},
                unit=unit.model_dump(mode="json") if unit is not None else {},
                transcript=transcript,
                known_cue_ids=known_cue_ids,
                cues=cues,
            )
        )
    if model is FinalPartitionV5:
        errors.extend(partition_errors_v5(raw, unit_ids))
    if model is LineageLedgerV5:
        errors.extend(ledger_errors_v5(raw, transcript=transcript))
    return tuple(errors)


def ledger_errors_v5(
    raw: Mapping[str, Any],
    *,
    transcript: TranscriptDocument | None,
) -> list[LineageErrorV5]:
    raw = _contract_defaults_v5(LineageLedgerV5, raw)
    errors: list[LineageErrorV5] = []

    def extend(prefix: tuple[str | int, ...], found: Sequence[LineageErrorV5]) -> None:
        errors.extend(
            LineageErrorV5(location=(*prefix, *e.location), code=e.code, message=e.message)
            for e in found
        )

    cue_ids = {c.cue_id for c in transcript_cues(transcript)} if transcript is not None else None
    _index(raw.get("batches"), "batch_id", ("batches",), errors)
    originals: list[dict[str, Any]] = []
    batches = raw.get("batches")
    originals_complete = isinstance(batches, list) and len(_rows(batches)) == len(batches)
    fragments_complete = originals_complete
    fragment_ids: set[str] = set()
    original_ids: set[str] = set()
    for i, batch in _rows(batches):
        extend(("batches", i), discovery_errors_v5(batch, cue_ids))
        extend(("batches", i), _discovery_ownership_errors_v5(batch, transcript))
        candidates = batch.get("candidates")
        if _authority_ids(candidates, "candidate_id") is None:
            originals_complete = False
        batch_original_ids: set[str] = set()
        for j, original in _rows(candidates):
            original_id = original.get("candidate_id")
            if isinstance(original_id, str):
                # Discovery already reports repeats within this batch. Add the
                # first cross-batch repeat without duplicating that diagnostic.
                if original_id in original_ids and original_id not in batch_original_ids:
                    _error(
                        errors,
                        ("batches", i, "candidates", j, "candidate_id"),
                        "duplicate_id",
                    )
                batch_original_ids.add(original_id)
        original_ids.update(batch_original_ids)
        originals.extend(row for _, row in _rows(candidates))
        if _authority_ids(batch.get("topic_fragments"), "topic_fragment_id") is None:
            fragments_complete = False
        for j, fragment in _rows(batch.get("topic_fragments")):
            fragment_id = fragment.get("topic_fragment_id")
            if isinstance(fragment_id, str):
                if fragment_id in fragment_ids:
                    _error(
                        errors,
                        ("batches", i, "topic_fragments", j, "topic_fragment_id"),
                        "duplicate_id",
                    )
                fragment_ids.add(fragment_id)
    source_universe_complete = originals_complete
    originals_complete = originals_complete and all(
        _complete_ids(o.get("topic_fragment_ids")) for o in originals
    )
    # Routing needs only declared identities and fragments, never risk reasons,
    # proposal prose, or successful whole-model parsing.
    _index(raw.get("chains"), "topic_chain_id", ("chains",), errors)
    chain_map = {
        key: _chain_claim_authority_v5(claims)
        for key, claims in _claims_by_id_v5(raw.get("chains"), "topic_chain_id").items()
    }
    for i, chain_row in _rows(raw.get("chains")):
        _unique_refs(
            chain_row.get("fragment_ids"),
            fragment_ids if fragments_complete else None,
            ("chains", i, "fragment_ids"),
            errors,
        )
    chains_complete = _authority_ids(raw.get("chains"), "topic_chain_id") is not None and all(
        _complete_ids(c.get("fragment_ids")) for c in chain_map.values()
    )
    if chains_complete:
        for i, batch in _rows(batches):
            for j, original in _rows(batch.get("candidates")):
                if _complete_ids(original.get("topic_fragment_ids")) and not any(
                    set(original["topic_fragment_ids"]) & set(c["fragment_ids"])
                    for c in chain_map.values()
                ):
                    _error(errors, ("batches", i, "candidates", j), "unrouted_original")
    _index(raw.get("reviews"), "topic_chain_id", ("reviews",), errors)
    review_ids = _authority_ids(raw.get("reviews"), "topic_chain_id")
    if review_ids is not None:
        for chain_id in sorted(chain_map.keys() - review_ids):
            _error(errors, ("reviews", chain_id), "missing_chain_review")
    ordered_units = _known_flattened_prefix_v5(raw.get("reviews"), "candidates")
    units_complete = review_ids is not None
    variant_units_complete = units_complete and all(
        _authority_ids(review.get("candidates"), "candidate_id") is not None
        for _, review in _rows(raw.get("reviews"))
    )
    variant_unit_ids = (
        {
            candidate["candidate_id"]
            for _, review in _rows(raw.get("reviews"))
            for _, candidate in _rows(review.get("candidates"))
        }
        if variant_units_complete
        else None
    )
    for i, review in _rows(raw.get("reviews")):
        requested_chain = review.get("topic_chain_id")
        chain = chain_map.get(requested_chain) if isinstance(requested_chain, str) else None
        if (
            isinstance(requested_chain, str)
            and chain is None
            and _authority_ids(raw.get("chains"), "topic_chain_id") is not None
        ):
            _error(errors, ("reviews", i, "topic_chain_id"), "unknown_id")
        # Even absent chain authority leaves inverse edges and the review's
        # declared chain identity checkable. Never invent missing fragments.
        chain_authority = chain if chain is not None else {"topic_chain_id": requested_chain}
        # A known intersecting fragment proves a route even when unrelated
        # originals or other list slots prevent complete membership authority.
        membership = _route_membership_raw_v5(originals, chain_authority)
        expected = None
        if originals_complete and _complete_ids(chain_authority.get("fragment_ids")):
            expected = {
                o["candidate_id"]
                for o in originals
                if set(o["topic_fragment_ids"]) & set(chain_authority["fragment_ids"] or [])
            }
        known = cue_ids
        start, end = (
            chain_authority.get("source_start_cue_id"),
            chain_authority.get("source_end_cue_id"),
        )
        if known is not None and type(start) is int and type(end) is int:
            known = {c for c in known if start <= c <= end}
        extend(
            ("reviews", i),
            _topic_chain_errors_raw_v5(
                review,
                chain=chain_authority,
                expected=expected,
                known_cue_ids=known,
                unit_ids=variant_unit_ids,
                transcript=transcript,
                source_membership=membership,
                source_universe_complete=source_universe_complete,
            ),
        )
        if _authority_ids(review.get("candidates"), "candidate_id") is None:
            units_complete = False
    units: dict[str, dict[str, Any]] = {}
    for i, review in _rows(raw.get("reviews")):
        for j, candidate in _rows(review.get("candidates")):
            candidate_id = candidate.get("candidate_id")
            if isinstance(candidate_id, str):
                if candidate_id in units:
                    _error(errors, ("reviews", i, "candidates", j, "candidate_id"), "duplicate_id")
                else:
                    units[candidate_id] = candidate
    source_risks = _attributed_risks_raw_v5(originals)
    risk_universe_complete = (
        isinstance(batches, list)
        and len(_rows(batches)) == len(batches)
        and all(
            isinstance(b.get("candidates"), list)
            and len(_rows(b["candidates"])) == len(b["candidates"])
            for _, b in _rows(batches)
        )
        and _risk_ids_complete_v5(originals)
    )
    partition = raw.get("partition")
    if isinstance(partition, dict):
        # Repeated assignments contradict each other even when malformed reviews
        # leave the complete unit universe unknown.
        extend(
            ("partition",), partition_errors_v5(partition, set(units) if units_complete else None)
        )
    records = [
        (field, i, outcome, declared)
        for field, declared in (
            ("outcomes", ordered_units),
            ("chain_new_outcomes", _known_chain_new_prefix_v5(ordered_units)),
        )
        for i, outcome in _rows(raw.get(field))
    ]
    for field, i, outcome, declared in records:
        prefix = (field, i)
        boundary, authority, unit = (
            outcome.get("boundary"),
            outcome.get("authority"),
            outcome.get("unit"),
        )
        if isinstance(boundary, dict):
            extend(
                (*prefix, "disposition"),
                boundary_disposition_errors_v5(boundary, outcome.get("disposition")),
            )
        supplied = authority if isinstance(authority, dict) else {}
        # The duplicated outcome must not define which source risks it is allowed
        # to omit. Use review units and immutable Discovery risk identities.
        # The wire contract repeats review units in the same declared order.
        # This is structural redundancy, not inferred semantic identity. Preserve
        # malformed siblings' positions, and stop before any unknown list offset.
        if i < len(declared) and isinstance(declared[i], dict):
            unit = declared[i]
        elif isinstance(unit, dict) and isinstance(unit.get("candidate_id"), str):
            unit = units.get(unit["candidate_id"], unit)
        if isinstance(unit, dict) and isinstance(boundary, dict) and isinstance(partition, dict):
            for field in FinalPartitionV5.model_fields:
                for j, unit_id in _indexed_ids(partition.get(field)):
                    if unit_id == unit.get("candidate_id"):
                        extend(
                            ("partition", field, j),
                            boundary_disposition_errors_v5(boundary, field),
                        )
        outcome_chain_id = unit.get("topic_chain_id") if isinstance(unit, dict) else None
        chain_raw = chain_map.get(outcome_chain_id, {}) if isinstance(outcome_chain_id, str) else {}
        expected_authority = _expected_authority_raw_v5(
            unit if isinstance(unit, dict) else {}, chain_raw, source_risks, supplied, transcript
        )
        if "context_cue_ids" in supplied and isinstance(
            expected_authority.get("context_cue_ids"), list
        ):
            _compare_available_v5(
                expected_authority["context_cue_ids"],
                supplied["context_cue_ids"],
                (*prefix, "authority", "context_cue_ids"),
                errors,
                code="boundary_context_mismatch",
            )
        provided_risks = _index(
            supplied.get("risks"), "risk_id", (*prefix, "authority", "risks"), errors
        )
        _risk_order_errors_v5(
            [risk["risk_id"] for _, risk in _rows(expected_authority["risks"])],
            supplied.get("risks"),
            (*prefix, "authority", "risks"),
            errors,
        )
        scopes = {
            key: _any_scope_v5(
                [
                    _risk_scope_raw_v5(
                        risk,
                        unit if isinstance(unit, dict) else {},
                        chain_raw,
                        expected_authority.get("context_cue_ids"),
                    )
                    for risk in claims
                ]
            )
            for key, claims in source_risks.items()
        }
        invalid_risk_ids: set[str] = set()
        for j, risk in _rows(supplied.get("risks")):
            risk_id = risk.get("risk_id")
            if not isinstance(risk_id, str):
                continue
            code = (
                "unknown_source_risk"
                if risk_universe_complete and risk_id not in source_risks
                else "unexpected_risk_authority"
                if scopes.get(risk_id) is False
                else None
            )
            if code:
                invalid_risk_ids.add(risk_id)
                _error(errors, (*prefix, "authority", "risks", j, "risk_id"), code)
        if isinstance(supplied.get("risks"), list):
            for _, risk in _rows(expected_authority["risks"]):
                if risk["risk_id"] not in provided_risks:
                    _error(
                        errors,
                        (*prefix, "authority", "risks", risk["risk_id"]),
                        "missing_risk_authority",
                    )
        if not isinstance(boundary, dict):
            continue
        for j, treatment in _rows(boundary.get("risk_treatments")):
            risk_id = treatment.get("risk_id")
            if isinstance(risk_id, str) and (
                (risk_universe_complete and risk_id not in source_risks)
                or scopes.get(risk_id) is False
            ):
                _error(
                    errors,
                    (*prefix, "boundary", "risk_treatments", j, "risk_id"),
                    "unknown_risk",
                )
        # Supplied additional risks still receive their own checks. Canonical
        # source fields override any altered copies for known risk identities.
        merged = {
            key: source_risks.get(key, claims)
            for key, claims in _claims_by_id_v5(supplied.get("risks"), "risk_id").items()
            if key not in invalid_risk_ids
        }
        merged.update(_claims_by_id_v5(expected_authority["risks"], "risk_id"))
        # Unknown membership is checked above only when source/scope authority
        # proves it. The merged partial list cannot certify excluded identities.
        authority = dict(
            expected_authority,
            risks=[risk for claims in merged.values() for risk in claims],
            membership_complete=False,
        )
        found = _boundary_errors_raw_v5(
            boundary,
            authority=authority,
            unit=unit if isinstance(unit, dict) else {},
            transcript=transcript,
            # Expected context establishes complete risk membership; supplied
            # context remains an independent constraint on Boundary references.
            known_cue_ids=_boundary_context_ids_v5(supplied, None),
        )
        extend((*prefix, "boundary"), found)
    errors.extend(_ledger_record_errors_raw_v5(raw))
    return errors


def _attributed_risks_raw_v5(originals: object) -> dict[str, list[dict[str, Any]]]:
    """Attribute each available identity independently of prose/schema validity."""
    result: dict[str, list[dict[str, Any]]] = {}
    for _, original in _rows(originals):
        for _, risk in _rows(original.get("risks")):
            if not all(
                isinstance(v, str)
                for v in (
                    original.get("candidate_id"),
                    original.get("source_batch_id"),
                    risk.get("risk_id"),
                )
            ):
                continue
            generated_id = _identity(
                "risk", original["source_batch_id"], original["candidate_id"], risk["risk_id"]
            )
            attributed = {k: risk[k] for k in ("flag", "reason", "evidence_cue_ids") if k in risk}
            attributed.update(
                risk_id=generated_id,
                local_risk_id=risk["risk_id"],
                original_candidate_id=original["candidate_id"],
                source_batch_id=original["source_batch_id"],
            )
            for source_key, target in (
                ("source_window_ids", "source_window_ids"),
                ("topic_fragment_ids", "source_fragment_ids"),
            ):
                if source_key in original:
                    attributed[target] = original[source_key]
            result.setdefault(generated_id, []).append(attributed)
    return result


def _risk_ids_complete_v5(originals: object) -> bool:
    return (
        isinstance(originals, list)
        and len(_rows(originals)) == len(originals)
        and all(
            isinstance(o.get("candidate_id"), str)
            and isinstance(o.get("source_batch_id"), str)
            and _authority_ids(o.get("risks"), "risk_id") is not None
            for _, o in _rows(originals)
        )
    )


def _intersection_scope_v5(left: object, right: object, kind: type[str] | type[int]) -> bool | None:
    """Known intersections prove presence; a complete empty side proves absence."""
    left_ids = {value for value in left if type(value) is kind} if isinstance(left, list) else set()
    right_ids = (
        {value for value in right if type(value) is kind} if isinstance(right, list) else set()
    )
    if left_ids & right_ids:
        return True
    left_complete = isinstance(left, list) and all(type(value) is kind for value in left)
    right_complete = isinstance(right, list) and all(type(value) is kind for value in right)
    if (
        (left_complete and not left_ids)
        or (right_complete and not right_ids)
        or (left_complete and right_complete)
    ):
        return False
    return None


def _route_membership_raw_v5(
    originals: Sequence[Mapping[str, Any]], chain: Mapping[str, Any]
) -> dict[str, bool | None]:
    scopes: dict[str, list[bool | None]] = {}
    for original in originals:
        candidate_id = original.get("candidate_id")
        if isinstance(candidate_id, str):
            scopes.setdefault(candidate_id, []).append(
                _intersection_scope_v5(
                    original.get("topic_fragment_ids"), chain.get("fragment_ids"), str
                )
            )
    return {
        candidate_id: True
        if any(scope is True for scope in claims)
        else False
        if all(scope is False for scope in claims)
        else None
        for candidate_id, claims in scopes.items()
    }


def _risk_scope_raw_v5(
    risk: Mapping[str, Any],
    unit: Mapping[str, Any],
    chain: Mapping[str, Any],
    context: object,
) -> bool | None:
    """Positive membership needs one known edge; exclusion needs every edge ruled out."""
    origins = unit.get("original_candidate_ids")
    source = risk.get("original_candidate_id")
    origin_scope = (
        True
        if isinstance(source, str) and source in (_ids(origins) or [])
        else False
        if _complete_ids(origins) and (isinstance(source, str) or origins == [])
        else None
    )
    scopes = (
        origin_scope,
        _intersection_scope_v5(chain.get("fragment_ids"), risk.get("source_fragment_ids"), str),
        _intersection_scope_v5(context, risk.get("evidence_cue_ids"), int),
    )
    if any(scope is True for scope in scopes):
        return True
    if all(scope is False for scope in scopes):
        return False
    return None


def _expected_authority_raw_v5(
    unit: Mapping[str, Any],
    chain: Mapping[str, Any],
    source_risks: Mapping[str, list[dict[str, Any]]],
    supplied: Mapping[str, Any],
    transcript: TranscriptDocument | None,
) -> dict[str, Any]:
    context = supplied.get("context_cue_ids")
    if transcript is not None:
        cues = {c.cue_id: c for c in transcript_cues(transcript)}
        start, end = unit.get("start_cue_id"), unit.get("end_cue_id")
        if type(start) is int and type(end) is int and start in cues and end in cues:
            context = [
                c.cue_id
                for c in cues.values()
                if c.end_ms > max(0, cues[start].start_ms - 30_000)
                and c.start_ms < min(transcript.source_duration_ms, cues[end].end_ms + 30_000)
            ]
    risks = [
        risk
        for claims in source_risks.values()
        if any(_risk_scope_raw_v5(risk, unit, chain, context) is True for risk in claims)
        for risk in claims
    ]
    return dict(
        supplied, candidate_id=unit.get("candidate_id"), context_cue_ids=context, risks=risks
    )


def _compare_available_v5(
    expected: object,
    actual: object,
    loc: tuple[str | int, ...],
    errors: list[LineageErrorV5],
    *,
    code: str = "provenance_mismatch",
) -> None:
    """Compare supplied claims only. Missing fields remain schema errors, not guesses."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() & actual.keys()):
            _compare_available_v5(expected[key], actual[key], (*loc, key), errors, code=code)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            _error(errors, loc, "record_count_mismatch")
        for i, (left, right) in enumerate(zip(expected, actual, strict=False)):
            _compare_available_v5(left, right, (*loc, i), errors, code=code)
    elif (
        not isinstance(expected, (dict, list))
        and not isinstance(actual, (dict, list))
        and expected != actual
    ):
        _error(errors, loc, code)


def _ledger_record_errors_raw_v5(raw: Mapping[str, Any]) -> list[LineageErrorV5]:
    """Ledger redundancy is checkable from raw identities, even with invalid prose."""
    errors: list[LineageErrorV5] = []

    def flatten(parent: str, child: str) -> list[Any] | None:
        rows = raw.get(parent)
        if not isinstance(rows, list) or any(
            not isinstance(r, dict) or not isinstance(r.get(child), list) for r in rows
        ):
            return None
        return [item for row in rows for item in row[child]]

    originals = flatten("batches", "candidates")
    ordered_originals = _known_flattened_prefix_v5(raw.get("batches"), "candidates")

    def original_authority(index: int, record: Mapping[str, Any]) -> object:
        # These are declared redundant copies, not inferred semantic identities.
        # Keep malformed sibling slots; an unknown list length ends positional authority.
        if index < len(ordered_originals) and isinstance(ordered_originals[index], dict):
            return ordered_originals[index]
        return record.get("original")

    units = flatten("reviews", "candidates")
    ordered_units = _known_flattened_prefix_v5(raw.get("reviews"), "candidates")

    def unit_authority(index: int, outcome: object) -> object:
        if index < len(ordered_units) and isinstance(ordered_units[index], dict):
            return ordered_units[index]
        return outcome.get("unit") if isinstance(outcome, dict) else None

    sources = flatten("reviews", "source_dispositions")
    counts: dict[str, int] = {}
    partition = raw.get("partition")
    dispositions: dict[str, str] = {}
    if isinstance(partition, dict):
        assignments: dict[str, list[str]] = {}
        for field in FinalPartitionV5.model_fields:
            values = partition.get(field)
            if isinstance(values, list):
                counts[field] = len(values)
                for value in values:
                    if isinstance(value, str):
                        assignments.setdefault(value, []).append(field)
        dispositions = {key: values[0] for key, values in assignments.items() if len(values) == 1}
    if originals is not None:
        counts["originals"] = len(originals)
        recorded = raw.get("originals")
        if isinstance(recorded, list) and len(recorded) != len(originals):
            _error(errors, ("originals",), "record_count_mismatch")
    for i, record in _rows(raw.get("originals")):
        if i < len(ordered_originals) and "original" in record:
            _compare_available_v5(
                ordered_originals[i], record["original"], ("originals", i, "original"), errors
            )
    if units is not None:
        counts["units"] = len(units)
        if all(
            isinstance(u, dict) and u.get("origin_kind") in ("derived", "chain_new") for u in units
        ):
            counts["derived_units"] = sum(u["origin_kind"] == "derived" for u in units)
            counts["chain_new_units"] = len(units) - counts["derived_units"]
        outcomes = raw.get("outcomes")
        if isinstance(outcomes, list) and len(outcomes) != len(units):
            _error(errors, ("outcomes",), "record_count_mismatch")
    for i, outcome in _rows(raw.get("outcomes")):
        if i < len(ordered_units) and "unit" in outcome:
            _compare_available_v5(
                ordered_units[i], outcome["unit"], ("outcomes", i, "unit"), errors
            )
    if sources is not None and all(
        isinstance(s, dict) and _complete_ids(s.get("derived_unit_ids")) for s in sources
    ):
        counts["terminal_paths"] = sum(max(1, len(s["derived_unit_ids"])) for s in sources)
        counts["rejected_source_paths"] = sum(not s["derived_unit_ids"] for s in sources)
    actual_counts = raw.get("counts")
    if isinstance(actual_counts, dict):
        for field, expected_count in counts.items():
            if type(actual_counts.get(field)) is int and actual_counts[field] != expected_count:
                _error(errors, ("counts", field), "count_mismatch")

    # Unknown later collections do not erase earlier declared path positions.
    # Stop at the first source whose contribution to this original is unknown;
    # only a complete collection can establish the total number of paths.
    ordered_sources = _known_flattened_prefix_v5(raw.get("reviews"), "source_dispositions")
    for i, record in _rows(raw.get("originals")):
        original = original_authority(i, record)
        if not isinstance(original, dict) or not isinstance(original.get("candidate_id"), str):
            continue
        source_id = original["candidate_id"]
        expected_paths: list[dict[str, Any]] = []
        complete = sources is not None
        for source in ordered_sources:
            if not isinstance(source, dict) or not isinstance(
                source.get("original_candidate_id"), str
            ):
                complete = False
                break
            if source["original_candidate_id"] != source_id:
                continue
            if not _complete_ids(source.get("derived_unit_ids")):
                complete = False
                break
            for unit_id in source["derived_unit_ids"] or [None]:
                path = {
                    key: source[key]
                    for key in (
                        "original_candidate_id",
                        "topic_chain_id",
                        "rejection_reason",
                        "evidence_cue_ids",
                    )
                    if key in source
                }
                path["unit_id"] = unit_id
                if unit_id is None:
                    path["disposition"] = "rejected"
                elif unit_id in dispositions:
                    path["disposition"] = dispositions[unit_id]
                expected_paths.append(path)
        actual_paths = record.get("paths")
        if complete:
            _compare_available_v5(
                expected_paths,
                actual_paths,
                ("originals", i, "paths"),
                errors,
                code="terminal_path_mismatch",
            )
        elif isinstance(actual_paths, list):
            for j, (expected_path, actual_path) in enumerate(
                zip(expected_paths, actual_paths, strict=False)
            ):
                _compare_available_v5(
                    expected_path,
                    actual_path,
                    ("originals", i, "paths", j),
                    errors,
                    code="terminal_path_mismatch",
                )

    source_risks = _attributed_risks_raw_v5(
        [
            candidate
            for _, batch in _rows(raw.get("batches"))
            for _, candidate in _rows(batch.get("candidates"))
        ]
    )
    for i, record in _rows(raw.get("originals")):
        original = original_authority(i, record)
        _index(record.get("risks"), "risk_id", ("originals", i, "risks"), errors)
        if isinstance(original, dict) and isinstance(record.get("risks"), list):
            expected_order = [
                key
                for key, claims in source_risks.items()
                if any(
                    value["original_candidate_id"] == original.get("candidate_id")
                    for value in claims
                )
            ]
            _risk_order_errors_v5(
                expected_order, record["risks"], ("originals", i, "risks"), errors
            )
            expected_ids = set(expected_order)
            recorded_ids = {
                r.get("risk_id")
                for _, r in _rows(record["risks"])
                if isinstance(r.get("risk_id"), str)
            }
            for missing_risk_id in sorted(expected_ids - recorded_ids):
                _error(errors, ("originals", i, "risks", missing_risk_id), "missing_original_risk")
        for j, risk in _rows(record.get("risks")):
            risk_id = risk.get("risk_id")
            if isinstance(risk_id, str) and (
                (_risk_ids_complete_v5(originals) and risk_id not in source_risks)
                or (
                    risk_id in source_risks
                    and isinstance(original, dict)
                    and isinstance(original.get("candidate_id"), str)
                    and all(
                        claim["original_candidate_id"] != original["candidate_id"]
                        for claim in source_risks[risk_id]
                    )
                )
            ):
                _error(errors, ("originals", i, "risks", j, "risk_id"), "unexpected_original_risk")
            if isinstance(risk_id, str) and risk_id in source_risks:
                for claim in source_risks[risk_id]:
                    _compare_available_v5(claim, risk, ("originals", i, "risks", j), errors)
    for field, declared in (
        ("outcomes", ordered_units),
        ("chain_new_outcomes", _known_chain_new_prefix_v5(ordered_units)),
    ):
        for i, outcome in _rows(raw.get(field)):
            unit, authority, boundary = (
                declared[i]
                if i < len(declared) and isinstance(declared[i], dict)
                else outcome.get("unit"),
                outcome.get("authority"),
                outcome.get("boundary"),
            )
            if isinstance(unit, dict):
                unit_id = unit.get("candidate_id")
                if isinstance(unit_id, str):
                    if (
                        unit_id in dispositions
                        and "disposition" in outcome
                        and outcome["disposition"] != dispositions[unit_id]
                    ):
                        _error(errors, (field, i, "disposition"), "disposition_mismatch")
                    for name, value in (("authority", authority), ("boundary", boundary)):
                        if (
                            isinstance(value, dict)
                            and "candidate_id" in value
                            and value["candidate_id"] != unit_id
                        ):
                            _error(errors, (field, i, name, "candidate_id"), "candidate_mismatch")
            if isinstance(authority, dict):
                for j, risk in _rows(authority.get("risks")):
                    risk_id = risk.get("risk_id")
                    if isinstance(risk_id, str) and risk_id in source_risks:
                        for claim in source_risks[risk_id]:
                            _compare_available_v5(
                                claim, risk, (field, i, "authority", "risks", j), errors
                            )
    outcomes = raw.get("outcomes")
    resolved_units = units
    if resolved_units is None and isinstance(outcomes, list):
        resolved_units = [unit_authority(i, outcome) for i, outcome in enumerate(outcomes)]
    if (
        resolved_units is not None
        and all(
            isinstance(u, dict) and u.get("origin_kind") in ("derived", "chain_new")
            for u in resolved_units
        )
        and isinstance(raw.get("chain_new_outcomes"), list)
    ):
        expected_new = []
        for i, unit in enumerate(resolved_units):
            if unit["origin_kind"] != "chain_new":
                continue
            # Missing outcome payload leaves only the canonical unit known; do
            # not invent Boundary decisions, evidence, risk treatments or spans.
            recorded_outcome = (
                outcomes[i] if isinstance(outcomes, list) and i < len(outcomes) else None
            )
            expected = dict(recorded_outcome) if isinstance(recorded_outcome, dict) else {}
            expected["unit"] = unit
            unit_id = unit.get("candidate_id")
            if isinstance(unit_id, str) and unit_id in dispositions:
                expected["disposition"] = dispositions[unit_id]
            expected_new.append(expected)
        _compare_available_v5(
            expected_new, raw["chain_new_outcomes"], ("chain_new_outcomes",), errors
        )
    return errors


def _payload_identity(
    stage: str, source_id: str, source_hash: str, prompt_hash: str, semantic_profile: str
) -> dict[str, object]:
    if semantic_profile not in ("general", "vocal_coach_live"):
        raise ValueError("unsupported semantic profile")
    return {
        "schema_version": "5",
        "contract_version": LINEAGE_CONTRACT,
        "validation_contract": CURRENT_SEMANTIC_VALIDATION,
        "stage": stage,
        "source_id": source_id,
        "source_hash": source_hash,
        "prompt_hash": prompt_hash,
        "semantic_profile": semantic_profile,
        "clip_profile": "mini_lesson",
    }


def build_discovery_payload_v5(
    unit: SemanticInputUnit,
    *,
    source_id: str,
    source_hash: str,
    prompt_hash: str,
    semantic_profile: str,
) -> dict[str, object]:
    payload = build_discovery_payload_v4(
        unit,
        source_id=source_id,
        source_hash=source_hash,
        profile=ClipProfile.MINI_LESSON,
        prompt_hash=prompt_hash,
    )
    payload.update(
        _payload_identity("discovery", source_id, source_hash, prompt_hash, semantic_profile)
    )
    return payload


def build_topic_chain_payload_v5(
    chain: TopicChainV4,
    *,
    batches: Sequence[DiscoveryBatchOutputV5],
    chains: Sequence[TopicChainV4],
    transcript: TranscriptDocument,
    source_id: str,
    source_hash: str,
    prompt_hash: str,
    semantic_profile: str,
) -> dict[str, object]:
    originals = tuple(o for b in batches for o in b.candidates)
    routes = expected_routes_v5(
        originals, chains, tuple(f for b in batches for f in b.topic_fragments)
    )
    if chain not in chains:
        raise ValueError("unknown requested chain")
    return {
        **_payload_identity("topic_chain", source_id, source_hash, prompt_hash, semantic_profile),
        "topic_chain": chain.model_dump(mode="json"),
        "batches": [b.model_dump(mode="json") for b in batches],
        "expected_routes": [
            r.model_dump(mode="json") for r in routes if r.topic_chain_id == chain.topic_chain_id
        ],
        "source_risks": [r.model_dump(mode="json") for r in attribute_risks_v5(originals)],
        "cues": [
            c.model_dump(mode="json")
            for c in transcript_cues(transcript)
            if chain.source_start_cue_id <= c.cue_id <= chain.source_end_cue_id
        ],
    }


def build_boundary_payload_v5(
    unit: ChainCandidateV5,
    *,
    chain: TopicChainV4,
    originals: Sequence[DiscoveryCandidateV5],
    transcript: TranscriptDocument,
    source_id: str,
    source_hash: str,
    prompt_hash: str,
    semantic_profile: str,
) -> dict[str, object]:
    cues = {c.cue_id: c for c in transcript_cues(transcript)}
    start, end = cues[unit.start_cue_id], cues[unit.end_cue_id]
    context = tuple(
        c
        for c in cues.values()
        if c.end_ms > max(0, start.start_ms - 30_000)
        and c.start_ms < min(transcript.source_duration_ms, end.end_ms + 30_000)
    )
    authority = build_boundary_authority_v5(
        unit, chain=chain, originals=originals, context_cue_ids=tuple(c.cue_id for c in context)
    )
    return {
        **_payload_identity(
            "boundary_review", source_id, source_hash, prompt_hash, semantic_profile
        ),
        "candidate": unit.model_dump(mode="json"),
        "topic_chain": chain.model_dump(mode="json"),
        "originals": [o.model_dump(mode="json") for o in originals],
        "authority": authority.model_dump(mode="json"),
        "cues": [c.model_dump(mode="json") for c in context],
    }
