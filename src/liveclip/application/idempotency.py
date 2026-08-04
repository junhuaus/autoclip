from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


class IdempotencyConflict(RuntimeError):
    """An idempotency key was reused for a different canonical request."""


class IdempotencyContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    caller_scope: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    operation_scope: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:/-]+$")
    key_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    canonical_schema_version: str = Field(default="1", pattern=r"^1$")


def build_idempotency_context(
    *,
    raw_key: str,
    caller_scope: str,
    operation_scope: str,
    request_payload: object,
) -> IdempotencyContext:
    if not raw_key or len(raw_key.encode("utf-8")) > 200:
        raise ValueError("Idempotency-Key must contain between 1 and 200 UTF-8 bytes")
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in raw_key):
        raise ValueError("Idempotency-Key must contain visible ASCII characters only")
    canonical = json.dumps(
        request_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return IdempotencyContext(
        caller_scope=caller_scope,
        operation_scope=operation_scope,
        key_hash=hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
        request_hash=hashlib.sha256(canonical).hexdigest(),
    )
