#!/usr/bin/env python3
"""Iteration-2 input validation, capacity gates, and v1 baseline batching."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

INPUT_GATE_VERSION = "liveclip-highlight-agent-v2-input-gate-v2"
MAX_CANDIDATES = 60
MAX_BATCH_SIZE = 15
MAX_COMBINED_PAYLOAD_BYTES = 128 * 1024


class StrictWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="after")
    def _reject_whitespace_only_strings(self) -> StrictWireModel:
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            if isinstance(value, str) and value and not value.strip():
                raise ValueError("input strings cannot contain only whitespace")
        return self


class SourceEvidence(StrictWireModel):
    candidate_count: int = Field(ge=0, le=MAX_CANDIDATES)
    duration_ms: int = Field(gt=0)
    evidence_note: str = Field(min_length=1, max_length=300)
    filename: str = Field(min_length=1, max_length=255)
    rough_candidates_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    transcript_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _safe_filename(self) -> SourceEvidence:
        if (
            self.filename != self.filename.strip()
            or self.filename in {".", ".."}
            or "/" in self.filename
            or "\\" in self.filename
            or "\x00" in self.filename
        ):
            raise ValueError("source filename must be a plain basename")
        return self


class CandidateEvidence(StrictWireModel):
    allowed_end_ms: int = Field(gt=0)
    allowed_start_ms: int = Field(ge=0)
    candidate_id: str = Field(pattern=r"^candidate_[a-f0-9]{16}$")
    context_after: str = Field(max_length=30_000)
    context_before: str = Field(max_length=30_000)
    rule_reasons: tuple[str, ...] = Field(max_length=20)
    rule_score: float = Field(ge=0, le=100)
    source_end_ms: int = Field(gt=0)
    source_start_ms: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=50_000)

    @model_validator(mode="after")
    def _time_and_score_contract(self) -> CandidateEvidence:
        if not math.isfinite(self.rule_score):
            raise ValueError("rule_score must be finite")
        if not (
            self.allowed_start_ms
            <= self.source_start_ms
            < self.source_end_ms
            <= self.allowed_end_ms
        ):
            raise ValueError("candidate time bounds violate the allowed source window")
        if any(not reason.strip() for reason in self.rule_reasons):
            raise ValueError("rule reasons must not contain blank values")
        return self


class FrozenEvidence(StrictWireModel):
    candidates: tuple[CandidateEvidence, ...] = Field(max_length=MAX_CANDIDATES)
    source: SourceEvidence

    @model_validator(mode="after")
    def _complete_identity_contract(self) -> FrozenEvidence:
        if self.source.candidate_count != len(self.candidates):
            raise ValueError("source candidate_count does not match candidates")
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        if any(candidate.allowed_end_ms > self.source.duration_ms for candidate in self.candidates):
            raise ValueError("candidate allowed window exceeds source duration")
        return self


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def validate_frozen_evidence(raw: dict[str, Any]) -> FrozenEvidence:
    return FrozenEvidence.model_validate_json(canonical_json_bytes(raw), strict=True)


def evidence_set_sha256(evidence: FrozenEvidence) -> str:
    identity = {
        "input_gate_version": INPUT_GATE_VERSION,
        "source": evidence.source.model_dump(mode="json"),
        "candidates": [candidate.model_dump(mode="json") for candidate in evidence.candidates],
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def validate_combined_payload_capacity(payload: Any) -> int:
    """Fail closed when the exact Stage-A JSON payload exceeds the frozen cap."""

    size_bytes = len(canonical_json_bytes(payload))
    if size_bytes > MAX_COMBINED_PAYLOAD_BYTES:
        raise ValueError(
            "combined discovery payload exceeds the frozen capacity: "
            f"{size_bytes} > {MAX_COMBINED_PAYLOAD_BYTES} bytes"
        )
    return size_bytes


def deterministic_batches(
    evidence: FrozenEvidence, *, batch_size: int = MAX_BATCH_SIZE
) -> tuple[tuple[CandidateEvidence, ...], ...]:
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    return tuple(
        evidence.candidates[start : start + batch_size]
        for start in range(0, len(evidence.candidates), batch_size)
    )
