"""Adapt immutable provider requests to the shared V5 contract validators."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from liveclip.clipping_skills.semantic_global_v1 import SemanticGlobalPromptBundle
from liveclip.domain.semantic_validation import CURRENT_SEMANTIC_VALIDATION
from liveclip.pipeline.semantic_global import SemanticCue
from liveclip.pipeline.semantic_lineage import (
    LINEAGE_CONTRACT,
    AttributedRiskV5,
    BoundaryAuthorityV5,
    BoundaryReviewV5,
    ChainCandidateV5,
    DiscoveryBatchOutputV5,
    DiscoveryCandidateV5,
    LogicalWindowAuthorityV5,
    SourceRouteV5,
    TopicChainReviewV5,
    attribute_risks_v5,
    build_boundary_authority_v5,
    collect_response_errors_v5,
    discovery_request_errors_v5,
    parse_raw_response_v5,
    routes_for_chain_v5,
    validate_cues_v5,
)
from liveclip.pipeline.semantic_profiles import TimeRangeV4, TopicChainV4

_STAGES: dict[type[BaseModel], str] = {
    DiscoveryBatchOutputV5: "discovery",
    TopicChainReviewV5: "topic_chain",
    BoundaryReviewV5: "boundary_review",
}
T = TypeVar("T", bound=BaseModel)


def is_lineage_response(model: type[BaseModel]) -> bool:
    return model in _STAGES


def _model(model: type[T], raw: object) -> T:
    return model.model_validate_json(json.dumps(raw, ensure_ascii=False, allow_nan=False))


def _models(model: type[T], raw: object) -> tuple[T, ...]:
    if not isinstance(raw, list):
        raise ValueError("required lineage request collection is missing or malformed")
    return tuple(_model(model, value) for value in raw)


@dataclass(frozen=True)
class LineageResponseContext:
    model: type[BaseModel]
    cues: tuple[SemanticCue, ...]
    chain: TopicChainV4 | None = None
    routes: tuple[SourceRouteV5, ...] = ()
    unit: ChainCandidateV5 | None = None
    authority: BoundaryAuthorityV5 | None = None
    batch_id: str | None = None
    batch_context: TimeRangeV4 | None = None
    ownership: TimeRangeV4 | None = None
    windows: tuple[LogicalWindowAuthorityV5, ...] = ()

    def errors(self, text: str) -> list[str]:
        errors = list(
            collect_response_errors_v5(
                self.model,
                text,
                cues=self.cues,
                chain=self.chain,
                routes=self.routes,
                unit=self.unit,
                authority=self.authority,
            )
        )
        if self.model is DiscoveryBatchOutputV5:
            try:
                raw = parse_raw_response_v5(text)
            except (TypeError, ValueError):
                raw = None
            if isinstance(raw, dict):
                assert (
                    self.batch_id is not None
                    and self.batch_context is not None
                    and self.ownership is not None
                )
                errors.extend(
                    discovery_request_errors_v5(
                        raw,
                        expected_batch_id=self.batch_id,
                        expected_context=self.batch_context,
                        expected_ownership=self.ownership,
                        expected_windows=self.windows,
                        cues=self.cues,
                    )
                )
        return list(
            dict.fromkeys(
                f"{'.'.join(str(part) for part in error.location)}: {error.message} [{error.code}]"
                for error in errors
            )
        )


def prepare_lineage_context(
    payload: dict[str, object],
    response_model: type[BaseModel],
    *,
    prompts: SemanticGlobalPromptBundle | None = None,
) -> LineageResponseContext | None:
    """Reject malformed authority before I/O; return only immutable typed facts."""
    if not is_lineage_response(response_model):
        if payload.get("contract_version") == LINEAGE_CONTRACT or any(
            issubclass(response_model, model) for model in _STAGES
        ):
            raise ValueError("invalid immutable lineage request context")
        return None
    try:
        return _prepare_context(payload, response_model, prompts)
    except (TypeError, ValueError, KeyError):
        # Request content may contain source text or secrets. Never echo it.
        raise ValueError("invalid immutable lineage request context") from None


def _prepare_context(
    payload: dict[str, object],
    response_model: type[BaseModel],
    prompts: SemanticGlobalPromptBundle | None,
) -> LineageResponseContext:
    stage = _STAGES[response_model]
    if (
        payload.get("schema_version") != "5"
        or payload.get("contract_version") != LINEAGE_CONTRACT
        or payload.get("validation_contract") != CURRENT_SEMANTIC_VALIDATION
        or payload.get("stage") != stage
        or payload.get("clip_profile") != "mini_lesson"
        or payload.get("semantic_profile") not in ("general", "vocal_coach_live")
        or not isinstance(payload.get("source_id"), str)
        or not payload["source_id"]
    ):
        raise ValueError("lineage request identity mismatch")
    for field in ("source_hash", "prompt_hash"):
        value = payload.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("invalid lineage request hash")
    if prompts is not None and (
        prompts.version != "semantic_topic_chain_v2"
        or prompts.stage != stage
        or prompts.profile != payload["semantic_profile"]
        or prompts.sha256 != payload["prompt_hash"]
    ):
        raise ValueError("lineage prompt identity mismatch")
    cues = _models(SemanticCue, payload.get("cues"))
    validate_cues_v5(cues)
    if tuple(sorted(cues, key=lambda cue: cue.cue_id)) != cues:
        raise ValueError("lineage cues are not in source order")
    cue_ids = {cue.cue_id for cue in cues}
    if stage == "discovery":
        batch_id = payload.get("batch_id")
        if not isinstance(batch_id, str) or not batch_id:
            raise ValueError("missing lineage batch identity")
        context = _model(TimeRangeV4, payload.get("batch_context"))
        ownership = _model(TimeRangeV4, payload.get("ownership_interval"))
        windows = _models(LogicalWindowAuthorityV5, payload.get("logical_windows"))
        if len({window.logical_window_id for window in windows}) != len(windows):
            raise ValueError("duplicate immutable logical window identity")
        if not context.start_ms <= ownership.start_ms < ownership.end_ms <= context.end_ms:
            raise ValueError("ownership escapes batch context")
        if any(
            not context.start_ms <= window.start_ms < window.end_ms <= context.end_ms
            for window in windows
        ):
            raise ValueError("logical window escapes batch context")
        if any(cue.end_ms <= context.start_ms or cue.start_ms >= context.end_ms for cue in cues):
            raise ValueError("cue escapes batch context")
        return LineageResponseContext(
            response_model,
            cues,
            batch_id=batch_id,
            batch_context=context,
            ownership=ownership,
            windows=windows,
        )
    chain = _model(TopicChainV4, payload.get("topic_chain"))
    if stage == "topic_chain":
        batches = _models(DiscoveryBatchOutputV5, payload.get("batches"))
        originals = tuple(original for batch in batches for original in batch.candidates)
        fragments = tuple(fragment for batch in batches for fragment in batch.topic_fragments)
        routes = _models(SourceRouteV5, payload.get("expected_routes"))
        if routes != routes_for_chain_v5(originals, chain, fragments):
            raise ValueError("immutable lineage routes differ from source authority")
        if _models(AttributedRiskV5, payload.get("source_risks")) != attribute_risks_v5(originals):
            raise ValueError("immutable source risks differ from originals")
        if not {chain.source_start_cue_id, chain.source_end_cue_id} <= cue_ids or any(
            not chain.source_start_cue_id <= cue.cue_id <= chain.source_end_cue_id for cue in cues
        ):
            raise ValueError("lineage chain cue scope is incomplete or invalid")
        return LineageResponseContext(response_model, cues, chain=chain, routes=routes)
    unit = _model(ChainCandidateV5, payload.get("candidate"))
    originals = _models(DiscoveryCandidateV5, payload.get("originals"))
    authority = _model(BoundaryAuthorityV5, payload.get("authority"))
    expected = build_boundary_authority_v5(
        unit, chain=chain, originals=originals, context_cue_ids=tuple(cue.cue_id for cue in cues)
    )
    if authority != expected or not {unit.start_cue_id, unit.end_cue_id} <= cue_ids:
        raise ValueError("immutable Boundary authority differs from sources or cues")
    return LineageResponseContext(response_model, cues, chain=chain, unit=unit, authority=authority)
