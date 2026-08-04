from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from liveclip.application.idempotency import IdempotencyConflict, IdempotencyContext
from liveclip.db.base import new_id
from liveclip.db.models import IdempotencyRecordRow


def load_idempotent_resource(
    connection: Connection,
    context: IdempotencyContext | None,
    *,
    resource_type: str,
) -> str | None:
    if context is None:
        return None
    row = connection.execute(
        select(
            IdempotencyRecordRow.request_hash,
            IdempotencyRecordRow.canonical_schema_version,
            IdempotencyRecordRow.resource_type,
            IdempotencyRecordRow.resource_id,
            IdempotencyRecordRow.status,
        ).where(
            IdempotencyRecordRow.caller_scope == context.caller_scope,
            IdempotencyRecordRow.operation_scope == context.operation_scope,
            IdempotencyRecordRow.key_hash == context.key_hash,
        )
    ).one_or_none()
    if row is None:
        return None
    if (
        str(row.request_hash) != context.request_hash
        or str(row.canonical_schema_version) != context.canonical_schema_version
        or str(row.resource_type) != resource_type
    ):
        raise IdempotencyConflict("Idempotency-Key was already used for a different request")
    if row.status != "completed":
        raise IdempotencyConflict("the original idempotent request has not completed")
    return str(row.resource_id)


def record_idempotent_resource(
    connection: Connection,
    context: IdempotencyContext | None,
    *,
    resource_type: str,
    resource_id: str,
    response_status_code: int = 202,
) -> None:
    if context is None:
        return
    now = datetime.now(UTC)
    connection.execute(
        insert(IdempotencyRecordRow).values(
            id=new_id(),
            caller_scope=context.caller_scope,
            operation_scope=context.operation_scope,
            key_hash=context.key_hash,
            request_hash=context.request_hash,
            canonical_schema_version=context.canonical_schema_version,
            resource_type=resource_type,
            resource_id=resource_id,
            status="completed",
            response_status_code=response_status_code,
            created_at=now,
            completed_at=now,
        )
    )
