from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, insert, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.orm import aliased

from liveclip.application.authorization import (
    ProjectAction,
    project_actions,
    require_project_action,
)
from liveclip.application.comments import (
    ClipCommentMessage,
    ClipCommentThread,
    ClipCommentThreads,
    CommentConflict,
    CommentIdentity,
    CommentResourceNotFound,
    CommentRevisionScope,
    CommentStatusFilter,
    CommentThreadAction,
    CreateClipCommentThread,
    ReplyToClipCommentThread,
    UpdateClipCommentThreadStatus,
)
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.workspace import WorkspaceRole
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    AuditEventRow,
    CandidateClipRow,
    ClipCommentMentionRow,
    ClipCommentRow,
    ClipCommentThreadRow,
    EditPlanRevisionRow,
    ProjectMemberRow,
    ProjectRow,
    WorkspaceUserRow,
)
from liveclip.db.workspace_repository import WorkspacePermissionDenied


@dataclass(frozen=True, slots=True)
class _ActorContext:
    project_id: str
    lifecycle: str
    role: WorkspaceRole
    user_id: str
    username: str
    display_name: str

    @property
    def can_comment(self) -> bool:
        return "comment" in project_actions(
            self.role,
            archived=self.lifecycle == "archived",
        )


class SqlAlchemyClipCommentRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid comment thread page")
        with self._engine.connect() as connection:
            clip = _load_current_clip(connection, clip_id)
            actor = _require_actor(
                connection,
                project_id=str(clip["project_id"]),
                acting_user_id=acting_user_id,
                action="read",
            )
            conditions = [EditPlanRevisionRow.candidate_clip_id == clip_id]
            if revision_scope == "current":
                conditions.append(EditPlanRevisionRow.revision == int(clip["current_revision"]))
            if status_filter != "all":
                conditions.append(ClipCommentThreadRow.status == status_filter)
            base = (
                select(ClipCommentThreadRow.id)
                .join(
                    EditPlanRevisionRow,
                    EditPlanRevisionRow.id == ClipCommentThreadRow.edit_plan_revision_id,
                )
                .where(*conditions)
            )
            total_count = int(
                connection.scalar(select(func.count()).select_from(base.subquery())) or 0
            )
            thread_ids = tuple(
                str(value)
                for value in connection.scalars(
                    base.order_by(
                        case((ClipCommentThreadRow.status == "open", 0), else_=1),
                        ClipCommentThreadRow.source_time_ms,
                        ClipCommentThreadRow.created_at,
                        ClipCommentThreadRow.id,
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            threads = tuple(
                _load_thread(connection, thread_id, actor=actor) for thread_id in thread_ids
            )
            next_offset = offset + len(threads) if offset + len(threads) < total_count else None
            return ClipCommentThreads(
                clip_id=clip_id,
                current_revision=int(clip["current_revision"]),
                total_count=total_count,
                next_offset=next_offset,
                threads=threads,
            )

    def get_thread(self, thread_id: str, *, acting_user_id: str) -> ClipCommentThread:
        with self._engine.connect() as connection:
            context = _load_current_thread_context(connection, thread_id)
            actor = _require_actor(
                connection,
                project_id=str(context["project_id"]),
                acting_user_id=acting_user_id,
                action="read",
            )
            return _load_thread(connection, thread_id, actor=actor)

    def create_thread(
        self,
        clip_id: str,
        command: CreateClipCommentThread,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            clip = _load_current_clip(connection, clip_id)
            actor = _require_actor(
                connection,
                project_id=str(clip["project_id"]),
                acting_user_id=acting_user_id,
                action="comment",
            )
            replayed_thread_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="clip_comment_thread",
            )
            if replayed_thread_id is not None:
                replay = _load_thread(connection, replayed_thread_id, actor=actor)
                if replay.clip_id != clip_id:
                    raise CommentConflict("comment replay does not match this clip")
                return replay
            if command.expected_revision != int(clip["current_revision"]):
                raise CommentConflict("clip revision changed; reload before adding a comment")
            duration_ms = int(clip["source_end_ms"]) - int(clip["source_start_ms"])
            if command.clip_time_ms > duration_ms:
                raise CommentConflict("comment timecode is outside the current clip")
            mentions = _resolve_mentions(
                connection,
                project_id=actor.project_id,
                mentioned_user_ids=command.mentioned_user_ids,
            )
            thread_id = new_id()
            comment_id = new_id()
            source_time_ms = int(clip["source_start_ms"]) + command.clip_time_ms
            connection.execute(
                insert(ClipCommentThreadRow).values(
                    id=thread_id,
                    edit_plan_revision_id=str(clip["revision_id"]),
                    source_time_ms=source_time_ms,
                    clip_time_ms=command.clip_time_ms,
                    status="open",
                    version=1,
                    created_by_user_id=actor.user_id,
                    created_by_username=actor.username,
                    created_by_display_name=actor.display_name,
                    resolved_by_user_id=None,
                    resolved_by_username=None,
                    resolved_by_display_name=None,
                    created_at=now,
                    updated_at=now,
                    resolved_at=None,
                )
            )
            _insert_comment(
                connection,
                comment_id=comment_id,
                thread_id=thread_id,
                sequence=1,
                actor=actor,
                body=command.body,
                mentions=mentions,
                now=now,
            )
            _audit(
                connection,
                actor=actor,
                action="comment.thread_created",
                thread_id=thread_id,
                before=None,
                after={
                    "comment_id": comment_id,
                    "clip_id": clip_id,
                    "edit_plan_revision_id": str(clip["revision_id"]),
                    "edit_plan_revision": int(clip["current_revision"]),
                    "source_time_ms": source_time_ms,
                    "clip_time_ms": command.clip_time_ms,
                    "thread_version": 1,
                    "mention_count": len(mentions),
                },
                correlation_id=correlation_id,
                now=now,
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="clip_comment_thread",
                resource_id=thread_id,
                response_status_code=201,
            )
            return _load_thread(connection, thread_id, actor=actor)

    def reply(
        self,
        thread_id: str,
        command: ReplyToClipCommentThread,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            context = _load_current_thread_context(connection, thread_id)
            actor = _require_actor(
                connection,
                project_id=str(context["project_id"]),
                acting_user_id=acting_user_id,
                action="comment",
            )
            replayed_thread_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="clip_comment_thread",
            )
            if replayed_thread_id is not None:
                if replayed_thread_id != thread_id:
                    raise CommentConflict("comment replay does not match this thread")
                return _load_thread(connection, thread_id, actor=actor)
            if str(context["status"]) != "open":
                raise CommentConflict("resolved comment threads must be reopened before replying")
            mentions = _resolve_mentions(
                connection,
                project_id=actor.project_id,
                mentioned_user_ids=command.mentioned_user_ids,
            )
            next_sequence = (
                int(
                    connection.scalar(
                        select(func.max(ClipCommentRow.sequence)).where(
                            ClipCommentRow.thread_id == thread_id
                        )
                    )
                    or 0
                )
                + 1
            )
            next_version = int(context["version"]) + 1
            changed = connection.execute(
                update(ClipCommentThreadRow)
                .where(
                    ClipCommentThreadRow.id == thread_id,
                    ClipCommentThreadRow.status == "open",
                    ClipCommentThreadRow.version == int(context["version"]),
                )
                .values(version=next_version, updated_at=now)
                .returning(ClipCommentThreadRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise CommentConflict("comment thread changed; reload before replying")
            comment_id = new_id()
            _insert_comment(
                connection,
                comment_id=comment_id,
                thread_id=thread_id,
                sequence=next_sequence,
                actor=actor,
                body=command.body,
                mentions=mentions,
                now=now,
            )
            _audit(
                connection,
                actor=actor,
                action="comment.reply_created",
                thread_id=thread_id,
                before={"thread_version": int(context["version"])},
                after={
                    "comment_id": comment_id,
                    "clip_id": str(context["clip_id"]),
                    "comment_sequence": next_sequence,
                    "thread_version": next_version,
                    "mention_count": len(mentions),
                },
                correlation_id=correlation_id,
                now=now,
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="clip_comment_thread",
                resource_id=thread_id,
                response_status_code=201,
            )
            return _load_thread(connection, thread_id, actor=actor)

    def update_status(
        self,
        thread_id: str,
        command: UpdateClipCommentThreadStatus,
        *,
        acting_user_id: str,
        correlation_id: str | None = None,
        idempotency: IdempotencyContext | None = None,
    ) -> ClipCommentThread:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            context = _load_current_thread_context(connection, thread_id)
            actor = _require_actor(
                connection,
                project_id=str(context["project_id"]),
                acting_user_id=acting_user_id,
                action="comment",
            )
            replayed_thread_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="clip_comment_thread",
            )
            if replayed_thread_id is not None:
                if replayed_thread_id != thread_id:
                    raise CommentConflict("comment replay does not match this thread")
                return _load_thread(connection, thread_id, actor=actor)
            current_status = str(context["status"])
            if command.expected_thread_version != int(context["version"]):
                raise CommentConflict("comment thread changed; reload before changing its status")
            if command.status == current_status:
                raise CommentConflict("comment thread already has the requested status")
            next_version = int(context["version"]) + 1
            resolving = command.status == "resolved"
            changed = connection.execute(
                update(ClipCommentThreadRow)
                .where(
                    ClipCommentThreadRow.id == thread_id,
                    ClipCommentThreadRow.status == current_status,
                    ClipCommentThreadRow.version == command.expected_thread_version,
                )
                .values(
                    status=command.status,
                    version=next_version,
                    resolved_by_user_id=actor.user_id if resolving else None,
                    resolved_by_username=actor.username if resolving else None,
                    resolved_by_display_name=actor.display_name if resolving else None,
                    resolved_at=now if resolving else None,
                    updated_at=now,
                )
                .returning(ClipCommentThreadRow.id)
            ).scalar_one_or_none()
            if changed is None:
                raise CommentConflict("comment thread changed; reload before changing its status")
            action = "comment.thread_resolved" if resolving else "comment.thread_reopened"
            _audit(
                connection,
                actor=actor,
                action=action,
                thread_id=thread_id,
                before={"status": current_status, "thread_version": int(context["version"])},
                after={
                    "status": command.status,
                    "thread_version": next_version,
                    "clip_id": str(context["clip_id"]),
                    "actor_identity": {
                        "user_id": actor.user_id,
                        "username": actor.username,
                        "display_name": actor.display_name,
                    },
                },
                correlation_id=correlation_id,
                now=now,
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="clip_comment_thread",
                resource_id=thread_id,
                response_status_code=200,
            )
            return _load_thread(connection, thread_id, actor=actor)


def _load_current_clip(connection: Connection, clip_id: str) -> RowMapping:
    row = (
        connection.execute(
            select(
                CandidateClipRow.id.label("clip_id"),
                CandidateClipRow.project_id,
                CandidateClipRow.pipeline_run_id,
                CandidateClipRow.current_revision,
                EditPlanRevisionRow.id.label("revision_id"),
                EditPlanRevisionRow.source_start_ms,
                EditPlanRevisionRow.source_end_ms,
                ProjectRow.current_pipeline_run_id,
                ProjectRow.current_generation,
            )
            .join(
                EditPlanRevisionRow,
                (EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id)
                & (EditPlanRevisionRow.revision == CandidateClipRow.current_revision),
            )
            .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
            .where(
                CandidateClipRow.id == clip_id,
                CandidateClipRow.selected_for_review.is_(True),
                CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CommentResourceNotFound("clip does not exist in the current project generation")
    return row


def _load_current_thread_context(connection: Connection, thread_id: str) -> RowMapping:
    row = (
        connection.execute(
            select(
                ClipCommentThreadRow.id,
                ClipCommentThreadRow.status,
                ClipCommentThreadRow.version,
                EditPlanRevisionRow.candidate_clip_id.label("clip_id"),
                CandidateClipRow.project_id,
                CandidateClipRow.pipeline_run_id,
                CandidateClipRow.current_revision,
                ProjectRow.current_pipeline_run_id,
                ProjectRow.current_generation,
            )
            .join(
                EditPlanRevisionRow,
                EditPlanRevisionRow.id == ClipCommentThreadRow.edit_plan_revision_id,
            )
            .join(CandidateClipRow, CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id)
            .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
            .where(
                ClipCommentThreadRow.id == thread_id,
                CandidateClipRow.selected_for_review.is_(True),
                CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CommentResourceNotFound("comment thread does not exist in the current generation")
    return row


def _require_actor(
    connection: Connection,
    *,
    project_id: str,
    acting_user_id: str,
    action: ProjectAction,
) -> _ActorContext:
    project = connection.execute(
        select(ProjectRow.visibility, ProjectRow.lifecycle).where(ProjectRow.id == project_id)
    ).one_or_none()
    user = connection.execute(
        select(
            WorkspaceUserRow.id,
            WorkspaceUserRow.username,
            WorkspaceUserRow.display_name,
        ).where(
            WorkspaceUserRow.id == acting_user_id,
            WorkspaceUserRow.is_active.is_(True),
        )
    ).one_or_none()
    if project is None or user is None:
        raise WorkspacePermissionDenied("active project access is required")
    role_value = connection.scalar(
        select(ProjectMemberRow.role).where(
            ProjectMemberRow.project_id == project_id,
            ProjectMemberRow.user_id == acting_user_id,
        )
    )
    if role_value is None:
        if str(project.visibility) != "workspace":
            raise CommentResourceNotFound("comment resource does not exist")
        role: WorkspaceRole = "viewer"
    else:
        raw_role = str(role_value)
        if raw_role not in {"owner", "editor", "reviewer", "viewer"}:
            raise WorkspacePermissionDenied("project membership role is invalid")
        role = raw_role  # type: ignore[assignment]
    require_project_action(role, action, archived=str(project.lifecycle) == "archived")
    return _ActorContext(
        project_id=project_id,
        lifecycle=str(project.lifecycle),
        role=role,
        user_id=str(user.id),
        username=str(user.username),
        display_name=str(user.display_name),
    )


def _resolve_mentions(
    connection: Connection,
    *,
    project_id: str,
    mentioned_user_ids: tuple[str, ...],
) -> tuple[CommentIdentity, ...]:
    if not mentioned_user_ids:
        return ()
    rows = connection.execute(
        select(
            WorkspaceUserRow.id,
            WorkspaceUserRow.username,
            WorkspaceUserRow.display_name,
        )
        .join(ProjectMemberRow, ProjectMemberRow.user_id == WorkspaceUserRow.id)
        .where(
            ProjectMemberRow.project_id == project_id,
            WorkspaceUserRow.id.in_(mentioned_user_ids),
            WorkspaceUserRow.is_active.is_(True),
        )
    )
    by_id = {
        str(row.id): CommentIdentity(
            user_id=str(row.id),
            username=str(row.username),
            display_name=str(row.display_name),
        )
        for row in rows
    }
    if set(by_id) != set(mentioned_user_ids):
        raise CommentConflict("mentions must target active explicit project members")
    return tuple(by_id[user_id] for user_id in mentioned_user_ids)


def _insert_comment(
    connection: Connection,
    *,
    comment_id: str,
    thread_id: str,
    sequence: int,
    actor: _ActorContext,
    body: str,
    mentions: tuple[CommentIdentity, ...],
    now: datetime,
) -> None:
    connection.execute(
        insert(ClipCommentRow).values(
            id=comment_id,
            thread_id=thread_id,
            sequence=sequence,
            author_user_id=actor.user_id,
            author_username=actor.username,
            author_display_name=actor.display_name,
            body=body,
            created_at=now,
        )
    )
    for index, mention in enumerate(mentions):
        connection.execute(
            insert(ClipCommentMentionRow).values(
                id=new_id(),
                comment_id=comment_id,
                user_id=mention.user_id,
                username=mention.username,
                display_name=mention.display_name,
                mention_index=index,
            )
        )


def _load_thread(
    connection: Connection,
    thread_id: str,
    *,
    actor: _ActorContext,
) -> ClipCommentThread:
    current_revision = aliased(EditPlanRevisionRow)
    row = (
        connection.execute(
            select(
                ClipCommentThreadRow.id,
                ClipCommentThreadRow.source_time_ms,
                ClipCommentThreadRow.clip_time_ms,
                ClipCommentThreadRow.status,
                ClipCommentThreadRow.version,
                ClipCommentThreadRow.created_by_user_id,
                ClipCommentThreadRow.created_by_username,
                ClipCommentThreadRow.created_by_display_name,
                ClipCommentThreadRow.resolved_by_user_id,
                ClipCommentThreadRow.resolved_by_username,
                ClipCommentThreadRow.resolved_by_display_name,
                ClipCommentThreadRow.created_at,
                ClipCommentThreadRow.updated_at,
                ClipCommentThreadRow.resolved_at,
                EditPlanRevisionRow.candidate_clip_id.label("clip_id"),
                EditPlanRevisionRow.revision.label("thread_revision"),
                EditPlanRevisionRow.source_start_ms.label("thread_start_ms"),
                EditPlanRevisionRow.source_end_ms.label("thread_end_ms"),
                CandidateClipRow.project_id,
                CandidateClipRow.pipeline_run_id,
                CandidateClipRow.current_revision.label("current_revision_number"),
                ProjectRow.current_pipeline_run_id,
                current_revision.source_start_ms.label("current_start_ms"),
                current_revision.source_end_ms.label("current_end_ms"),
            )
            .join(
                EditPlanRevisionRow,
                EditPlanRevisionRow.id == ClipCommentThreadRow.edit_plan_revision_id,
            )
            .join(CandidateClipRow, CandidateClipRow.id == EditPlanRevisionRow.candidate_clip_id)
            .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
            .join(
                current_revision,
                (current_revision.candidate_clip_id == CandidateClipRow.id)
                & (current_revision.revision == CandidateClipRow.current_revision),
            )
            .where(
                ClipCommentThreadRow.id == thread_id,
                CandidateClipRow.selected_for_review.is_(True),
                CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise CommentResourceNotFound("comment thread does not exist in the current generation")
    if str(row["project_id"]) != actor.project_id:
        raise CommentResourceNotFound("comment resource does not exist")
    source_time_ms = int(row["source_time_ms"])
    clip_time_ms = int(row["clip_time_ms"])
    if not (
        int(row["thread_start_ms"]) <= source_time_ms <= int(row["thread_end_ms"])
        and source_time_ms == int(row["thread_start_ms"]) + clip_time_ms
    ):
        raise CommentConflict("comment time anchor is inconsistent with its revision")
    current_start_ms = int(row["current_start_ms"])
    current_end_ms = int(row["current_end_ms"])
    current_clip_time_ms = (
        source_time_ms - current_start_ms
        if current_start_ms <= source_time_ms <= current_end_ms
        else None
    )
    messages: list[ClipCommentMessage] = []
    for message in connection.execute(
        select(
            ClipCommentRow.id,
            ClipCommentRow.author_user_id,
            ClipCommentRow.author_username,
            ClipCommentRow.author_display_name,
            ClipCommentRow.body,
            ClipCommentRow.created_at,
        )
        .where(ClipCommentRow.thread_id == thread_id)
        .order_by(ClipCommentRow.sequence, ClipCommentRow.id)
    ):
        mentions = tuple(
            CommentIdentity(
                user_id=str(mention.user_id) if mention.user_id is not None else None,
                username=str(mention.username),
                display_name=str(mention.display_name),
            )
            for mention in connection.execute(
                select(
                    ClipCommentMentionRow.user_id,
                    ClipCommentMentionRow.username,
                    ClipCommentMentionRow.display_name,
                )
                .where(ClipCommentMentionRow.comment_id == message.id)
                .order_by(ClipCommentMentionRow.mention_index, ClipCommentMentionRow.id)
            )
        )
        messages.append(
            ClipCommentMessage(
                comment_id=str(message.id),
                author=CommentIdentity(
                    user_id=(
                        str(message.author_user_id) if message.author_user_id is not None else None
                    ),
                    username=str(message.author_username),
                    display_name=str(message.author_display_name),
                ),
                body=str(message.body),
                mentions=mentions,
                created_at=message.created_at,
            )
        )
    status = str(row["status"])
    if status not in {"open", "resolved"}:
        raise CommentConflict("comment thread status is invalid")
    resolver = (
        CommentIdentity(
            user_id=(
                str(row["resolved_by_user_id"]) if row["resolved_by_user_id"] is not None else None
            ),
            username=str(row["resolved_by_username"]),
            display_name=str(row["resolved_by_display_name"]),
        )
        if status == "resolved"
        else None
    )
    allowed_actions: tuple[CommentThreadAction, ...] = (
        (("reply", "resolve") if status == "open" else ("reopen",)) if actor.can_comment else ()
    )
    return ClipCommentThread(
        thread_id=str(row["id"]),
        project_id=str(row["project_id"]),
        clip_id=str(row["clip_id"]),
        edit_plan_revision=int(row["thread_revision"]),
        current_revision=int(row["current_revision_number"]),
        is_current_revision=(int(row["thread_revision"]) == int(row["current_revision_number"])),
        is_current_generation=(str(row["pipeline_run_id"]) == str(row["current_pipeline_run_id"])),
        source_time_ms=source_time_ms,
        clip_time_ms=clip_time_ms,
        current_clip_time_ms=current_clip_time_ms,
        status=status,  # type: ignore[arg-type]
        version=int(row["version"]),
        allowed_actions=allowed_actions,
        created_by=CommentIdentity(
            user_id=(
                str(row["created_by_user_id"]) if row["created_by_user_id"] is not None else None
            ),
            username=str(row["created_by_username"]),
            display_name=str(row["created_by_display_name"]),
        ),
        resolved_by=resolver,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        resolved_at=row["resolved_at"],
        comments=tuple(messages),
    )


def _audit(
    connection: Connection,
    *,
    actor: _ActorContext,
    action: str,
    thread_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    correlation_id: str | None,
    now: datetime,
) -> None:
    connection.execute(
        insert(AuditEventRow).values(
            id=new_id(),
            actor_user_id=actor.user_id,
            actor_username=actor.username,
            action=action,
            target_type="clip_comment_thread",
            target_id=thread_id,
            project_id=actor.project_id,
            before_json=before,
            after_json=after,
            correlation_id=correlation_id,
            created_at=now,
        )
    )
