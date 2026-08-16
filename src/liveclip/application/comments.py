from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from liveclip.application.idempotency import IdempotencyContext

CommentThreadStatus = Literal["open", "resolved"]
CommentRevisionScope = Literal["current", "all"]
CommentStatusFilter = Literal["open", "resolved", "all"]
CommentThreadAction = Literal["reply", "resolve", "reopen"]

MAX_COMMENT_BODY_CHARS = 2_000
MAX_COMMENT_MENTIONS = 20


class CommentConflict(RuntimeError):
    """A comment mutation conflicts with the current revision or thread version."""


class CommentResourceNotFound(LookupError):
    """A comment thread or its current clip context does not exist."""


class CommentIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    user_id: str | None
    username: str
    display_name: str


class ClipCommentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    comment_id: str
    author: CommentIdentity
    body: str = Field(min_length=1, max_length=MAX_COMMENT_BODY_CHARS)
    mentions: tuple[CommentIdentity, ...]
    created_at: datetime


class ClipCommentThread(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    thread_id: str
    project_id: str
    clip_id: str
    edit_plan_revision: int = Field(ge=1)
    current_revision: int = Field(ge=1)
    is_current_revision: bool
    is_current_generation: bool
    source_time_ms: int = Field(ge=0)
    clip_time_ms: int = Field(ge=0)
    current_clip_time_ms: int | None = Field(default=None, ge=0)
    status: CommentThreadStatus
    version: int = Field(ge=1)
    allowed_actions: tuple[CommentThreadAction, ...]
    created_by: CommentIdentity
    resolved_by: CommentIdentity | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    comments: tuple[ClipCommentMessage, ...]


class ClipCommentThreads(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    clip_id: str
    current_revision: int = Field(ge=1)
    total_count: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)
    threads: tuple[ClipCommentThread, ...]


class _CommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    body: str = Field(min_length=1, max_length=MAX_COMMENT_BODY_CHARS)
    mentioned_user_ids: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_COMMENT_MENTIONS,
    )

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("comment body cannot be blank")
        return normalized

    @field_validator("mentioned_user_ids")
    @classmethod
    def validate_mentions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or len(item) > 64 for item in value):
            raise ValueError("mentioned user IDs must be non-empty and at most 64 characters")
        if len(set(value)) != len(value):
            raise ValueError("mentioned user IDs must be unique")
        return value


class CreateClipCommentThread(_CommentBody):
    expected_revision: int = Field(ge=1)
    clip_time_ms: int = Field(ge=0)


class ReplyToClipCommentThread(_CommentBody):
    pass


class UpdateClipCommentThreadStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_thread_version: int = Field(ge=1)
    status: CommentThreadStatus


class ClipCommentRepository(Protocol):
    def list_threads(
        self,
        clip_id: str,
        *,
        acting_user_id: str,
        revision_scope: CommentRevisionScope = "current",
        status_filter: CommentStatusFilter = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> ClipCommentThreads: ...

    def get_thread(self, thread_id: str, *, acting_user_id: str) -> ClipCommentThread: ...

    def create_thread(
        self,
        clip_id: str,
        command: CreateClipCommentThread,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread: ...

    def reply(
        self,
        thread_id: str,
        command: ReplyToClipCommentThread,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread: ...

    def update_status(
        self,
        thread_id: str,
        command: UpdateClipCommentThreadStatus,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread: ...


class ClipCommentService:
    def __init__(self, repository: ClipCommentRepository) -> None:
        self._repository = repository

    def list_threads(
        self,
        clip_id: str,
        *,
        acting_user_id: str,
        revision_scope: CommentRevisionScope = "current",
        status_filter: CommentStatusFilter = "all",
        limit: int = 50,
        offset: int = 0,
    ) -> ClipCommentThreads:
        if not 1 <= limit <= 100:
            raise ValueError("comment thread limit must be between 1 and 100")
        if offset < 0:
            raise ValueError("comment thread offset cannot be negative")
        return self._repository.list_threads(
            clip_id,
            acting_user_id=acting_user_id,
            revision_scope=revision_scope,
            status_filter=status_filter,
            limit=limit,
            offset=offset,
        )

    def get_thread(self, thread_id: str, *, acting_user_id: str) -> ClipCommentThread:
        return self._repository.get_thread(thread_id, acting_user_id=acting_user_id)

    def create_thread(
        self,
        clip_id: str,
        command: CreateClipCommentThread,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread:
        return self._repository.create_thread(
            clip_id,
            command,
            acting_user_id=acting_user_id,
            correlation_id=correlation_id,
            idempotency=idempotency,
        )

    def reply(
        self,
        thread_id: str,
        command: ReplyToClipCommentThread,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread:
        return self._repository.reply(
            thread_id,
            command,
            acting_user_id=acting_user_id,
            correlation_id=correlation_id,
            idempotency=idempotency,
        )

    def update_status(
        self,
        thread_id: str,
        command: UpdateClipCommentThreadStatus,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread:
        return self._repository.update_status(
            thread_id,
            command,
            acting_user_id=acting_user_id,
            correlation_id=correlation_id,
            idempotency=idempotency,
        )
