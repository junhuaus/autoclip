from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast

from sqlalchemy import and_, case, delete, func, insert, or_, select, update
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.project_discovery import (
    MAX_SAVED_PROJECT_VIEWS,
    CreateSavedProjectView,
    ProjectDiscoveryConflict,
    ProjectDiscoveryDenied,
    ProjectDiscoveryNotFound,
    ProjectSearchClipDocument,
    ProjectSearchCriteria,
    ProjectSearchCursor,
    ProjectSearchDocument,
    ProjectSearchReleaseDocument,
    ProjectSearchSelection,
    ProjectSearchSelectionItem,
    ProjectSearchSummary,
    SavedProjectView,
    UpdateSavedProjectView,
    encode_project_search_cursor,
    matching_lifecycles_for_query,
    matching_platforms_for_query,
)
from liveclip.db.base import new_id
from liveclip.db.engine import begin_immediate
from liveclip.db.idempotency import load_idempotent_resource, record_idempotent_resource
from liveclip.db.models import (
    CandidateClipRow,
    EditPlanRevisionRow,
    ProjectMemberRow,
    ProjectRow,
    ReleaseItemRow,
    SavedProjectViewRow,
    SourceMediaRow,
    WorkspaceUserRow,
)
from liveclip.domain.project_lifecycle import ProjectLifecycle, ProjectPriority
from liveclip.domain.releases import ReleasePlatform

_SQLITE_ID_BATCH = 400


class SqlAlchemyProjectDiscoveryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def search_projects(
        self,
        *,
        acting_user_id: str,
        criteria: ProjectSearchCriteria,
        limit: int,
        cursor: ProjectSearchCursor | None,
        now: datetime,
    ) -> ProjectSearchSelection:
        with self._engine.connect() as connection:
            _require_active_actor(connection, acting_user_id)
            authorized = _authorized_projects(acting_user_id)
            conditions = _search_conditions(
                authorized,
                criteria=criteria,
                acting_user_id=acting_user_id,
                now=now,
            )
            total_count = int(
                connection.scalar(
                    select(func.count())
                    .select_from(ProjectRow)
                    .join(authorized, authorized.c.project_id == ProjectRow.id)
                    .where(*conditions)
                )
                or 0
            )
            summary = _search_summary(connection, authorized, now=now)
            page_query = select(
                ProjectRow.id,
                ProjectRow.updated_at,
                ProjectRow.due_at,
                ProjectRow.priority,
                ProjectRow.name,
                _priority_expression().label("sort_priority"),
                case((ProjectRow.due_at.is_(None), 1), else_=0).label("sort_due_null"),
                func.liveclip_normalize(ProjectRow.name).label("sort_name"),
                authorized.c.current_role,
            ).join(authorized, authorized.c.project_id == ProjectRow.id)
            page_query = page_query.where(*conditions)
            page_query = _apply_cursor_and_order(page_query, criteria=criteria, cursor=cursor)
            rows = tuple(connection.execute(page_query.limit(limit + 1)).mappings())
            has_more = len(rows) > limit
            page_rows = rows[:limit]
            project_ids = tuple(str(row["id"]) for row in page_rows)
            documents = _load_page_documents(connection, project_ids)
            next_cursor = (
                encode_project_search_cursor(
                    _cursor_from_row(
                        criteria,
                        page_rows[-1],
                        acting_user_id=acting_user_id,
                        evaluated_at=now,
                    )
                )
                if has_more and page_rows
                else None
            )

        return ProjectSearchSelection(
            total_count=total_count,
            next_cursor=next_cursor,
            summary=summary,
            items=tuple(
                ProjectSearchSelectionItem(
                    project_id=project_id,
                    project_updated_at=cast(datetime, row["updated_at"]),
                    current_role=cast(Any, row["current_role"]),
                    document=documents[project_id],
                )
                for project_id, row in zip(project_ids, page_rows, strict=True)
            ),
        )

    def list_saved_views(self, *, acting_user_id: str) -> tuple[SavedProjectView, ...]:
        with self._engine.connect() as connection:
            _require_active_actor(connection, acting_user_id)
            rows = connection.execute(
                select(
                    SavedProjectViewRow.id,
                    SavedProjectViewRow.name,
                    SavedProjectViewRow.criteria_schema_version,
                    SavedProjectViewRow.criteria_json,
                    SavedProjectViewRow.version,
                    SavedProjectViewRow.created_at,
                    SavedProjectViewRow.updated_at,
                )
                .where(SavedProjectViewRow.user_id == acting_user_id)
                .order_by(
                    SavedProjectViewRow.updated_at.desc(),
                    SavedProjectViewRow.name_key,
                    SavedProjectViewRow.id,
                )
            ).mappings()
            views: list[SavedProjectView] = []
            for row in rows:
                try:
                    views.append(_saved_view(row))
                except ProjectDiscoveryConflict:
                    # One obsolete or damaged local view must not make the
                    # user's other valid views unavailable.
                    continue
            return tuple(views)

    def create_saved_view(
        self,
        command: CreateSavedProjectView,
        *,
        acting_user_id: str,
        idempotency: IdempotencyContext | None = None,
    ) -> SavedProjectView:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            _require_active_actor(connection, acting_user_id)
            replayed_id = load_idempotent_resource(
                connection,
                idempotency,
                resource_type="saved_project_view",
            )
            if replayed_id is not None:
                return _load_owned_saved_view(
                    connection,
                    replayed_id,
                    acting_user_id=acting_user_id,
                    replay=True,
                )
            count = connection.scalar(
                select(func.count())
                .select_from(SavedProjectViewRow)
                .where(SavedProjectViewRow.user_id == acting_user_id)
            )
            if int(count or 0) >= MAX_SAVED_PROJECT_VIEWS:
                raise ProjectDiscoveryConflict("saved project view limit reached")
            _require_name_available(
                connection,
                acting_user_id=acting_user_id,
                name_key=command.name_key,
            )
            view_id = new_id()
            connection.execute(
                insert(SavedProjectViewRow).values(
                    id=view_id,
                    user_id=acting_user_id,
                    name=command.name,
                    name_key=command.name_key,
                    criteria_schema_version="1",
                    criteria_json=command.criteria.model_dump(mode="json"),
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            record_idempotent_resource(
                connection,
                idempotency,
                resource_type="saved_project_view",
                resource_id=view_id,
                response_status_code=201,
            )
            return _load_owned_saved_view(
                connection,
                view_id,
                acting_user_id=acting_user_id,
            )

    def update_saved_view(
        self,
        view_id: str,
        command: UpdateSavedProjectView,
        *,
        acting_user_id: str,
    ) -> SavedProjectView:
        now = datetime.now(UTC)
        with begin_immediate(self._engine) as connection:
            _require_active_actor(connection, acting_user_id)
            row = connection.execute(
                select(SavedProjectViewRow.version).where(
                    SavedProjectViewRow.id == view_id,
                    SavedProjectViewRow.user_id == acting_user_id,
                )
            ).one_or_none()
            if row is None:
                raise ProjectDiscoveryNotFound("saved project view does not exist")
            if int(row.version) != command.expected_version:
                raise ProjectDiscoveryConflict("saved project view changed; reload and retry")
            _require_name_available(
                connection,
                acting_user_id=acting_user_id,
                name_key=command.name_key,
                excluding_view_id=view_id,
            )
            updated = connection.execute(
                update(SavedProjectViewRow)
                .where(
                    SavedProjectViewRow.id == view_id,
                    SavedProjectViewRow.user_id == acting_user_id,
                    SavedProjectViewRow.version == command.expected_version,
                )
                .values(
                    name=command.name,
                    name_key=command.name_key,
                    criteria_schema_version="1",
                    criteria_json=command.criteria.model_dump(mode="json"),
                    version=SavedProjectViewRow.version + 1,
                    updated_at=now,
                )
            )
            if updated.rowcount != 1:
                raise ProjectDiscoveryConflict("saved project view changed; reload and retry")
            return _load_owned_saved_view(
                connection,
                view_id,
                acting_user_id=acting_user_id,
            )

    def delete_saved_view(
        self,
        view_id: str,
        *,
        expected_version: int,
        acting_user_id: str,
    ) -> None:
        with begin_immediate(self._engine) as connection:
            _require_active_actor(connection, acting_user_id)
            row = connection.execute(
                select(SavedProjectViewRow.version).where(
                    SavedProjectViewRow.id == view_id,
                    SavedProjectViewRow.user_id == acting_user_id,
                )
            ).one_or_none()
            if row is None:
                raise ProjectDiscoveryNotFound("saved project view does not exist")
            if int(row.version) != expected_version:
                raise ProjectDiscoveryConflict("saved project view changed; reload and retry")
            removed = connection.execute(
                delete(SavedProjectViewRow).where(
                    SavedProjectViewRow.id == view_id,
                    SavedProjectViewRow.user_id == acting_user_id,
                    SavedProjectViewRow.version == expected_version,
                )
            )
            if removed.rowcount != 1:
                raise ProjectDiscoveryConflict("saved project view changed; reload and retry")


def _authorized_projects(acting_user_id: str) -> Any:
    membership = aliased(ProjectMemberRow, name="authorized_membership")
    return (
        select(
            ProjectRow.id.label("project_id"),
            case(
                (membership.role.is_not(None), membership.role),
                else_="viewer",
            ).label("current_role"),
        )
        .outerjoin(
            membership,
            and_(
                membership.project_id == ProjectRow.id,
                membership.user_id == acting_user_id,
            ),
        )
        .where(
            ProjectRow.current_pipeline_run_id.is_not(None),
            or_(
                membership.user_id == acting_user_id,
                ProjectRow.visibility == "workspace",
            ),
        )
        .cte("authorized_projects")
    )


def _search_conditions(
    authorized: Any,
    *,
    criteria: ProjectSearchCriteria,
    acting_user_id: str,
    now: datetime,
) -> tuple[Any, ...]:
    conditions: list[Any] = []
    if criteria.lifecycles:
        conditions.append(
            ProjectRow.lifecycle.in_(tuple(value.value for value in criteria.lifecycles))
        )
    if criteria.priorities:
        conditions.append(
            ProjectRow.priority.in_(tuple(value.value for value in criteria.priorities))
        )
    if criteria.roles:
        conditions.append(authorized.c.current_role.in_(criteria.roles))
    if criteria.visibilities:
        conditions.append(ProjectRow.visibility.in_(criteria.visibilities))
    if criteria.platforms:
        conditions.append(
            _current_release_exists(
                ReleaseItemRow.platform.in_(tuple(value.value for value in criteria.platforms))
            )
        )
    if criteria.assignee == "me":
        conditions.append(ProjectRow.assignee_user_id == acting_user_id)
    elif criteria.assignee == "unassigned":
        conditions.append(~_active_assignee_exists())
    elif criteria.assignee == "user":
        conditions.extend(
            (
                ProjectRow.assignee_user_id == criteria.assignee_user_id,
                _active_assignee_exists(),
            )
        )

    if criteria.due != "any":
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("project search time must include a timezone")
        if criteria.due == "overdue":
            conditions.extend(
                (
                    ProjectRow.due_at.is_not(None),
                    ProjectRow.due_at < now,
                    ProjectRow.lifecycle != ProjectLifecycle.ARCHIVED.value,
                )
            )
        elif criteria.due == "unscheduled":
            conditions.append(ProjectRow.due_at.is_(None))
        else:
            if criteria.due == "today":
                local_start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
                start = local_start.astimezone(UTC)
                end = (local_start + timedelta(days=1)).astimezone(UTC)
            else:
                start = now
                end = now + timedelta(days=7)
            conditions.extend(
                (
                    ProjectRow.due_at.is_not(None),
                    ProjectRow.due_at >= start,
                    ProjectRow.due_at < end,
                )
            )

    if criteria.query:
        needle = _normalized_search_text(criteria.query)
        text_conditions: list[Any] = [
            _contains(ProjectRow.name, needle),
            _contains(func.liveclip_basename(ProjectRow.source_request_path), needle),
            select(1)
            .select_from(SourceMediaRow)
            .where(
                SourceMediaRow.project_id == ProjectRow.id,
                _contains(SourceMediaRow.filename, needle),
            )
            .correlate(ProjectRow)
            .exists(),
            select(1)
            .select_from(WorkspaceUserRow)
            .where(
                WorkspaceUserRow.id == ProjectRow.assignee_user_id,
                WorkspaceUserRow.is_active.is_(True),
                or_(
                    _contains(WorkspaceUserRow.display_name, needle),
                    _contains(WorkspaceUserRow.username, needle),
                ),
            )
            .correlate(ProjectRow)
            .exists(),
            _current_clip_exists(
                or_(
                    _contains(EditPlanRevisionRow.title, needle),
                    _contains(EditPlanRevisionRow.hook, needle),
                    _contains(CandidateClipRow.transcript_text, needle),
                )
            ),
            _current_release_exists(
                or_(
                    _contains(ReleaseItemRow.title, needle),
                    _contains(ReleaseItemRow.account_label, needle),
                    _contains(func.liveclip_json_text(ReleaseItemRow.hashtags_json), needle),
                )
            ),
        ]
        lifecycle_aliases = matching_lifecycles_for_query(criteria.query)
        if lifecycle_aliases:
            text_conditions.append(
                ProjectRow.lifecycle.in_(tuple(value.value for value in lifecycle_aliases))
            )
        platform_aliases = matching_platforms_for_query(criteria.query)
        if platform_aliases:
            text_conditions.append(
                _current_release_exists(
                    ReleaseItemRow.platform.in_(tuple(value.value for value in platform_aliases))
                )
            )
        conditions.append(or_(*text_conditions))
    return tuple(conditions)


def _normalized_search_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _contains(column: Any, needle: str) -> Any:
    return func.instr(func.liveclip_normalize(func.coalesce(column, "")), needle) > 0


def _current_clip_exists(condition: Any) -> Any:
    return (
        select(1)
        .select_from(CandidateClipRow)
        .join(
            EditPlanRevisionRow,
            and_(
                EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id,
                EditPlanRevisionRow.revision == CandidateClipRow.current_revision,
            ),
        )
        .where(
            CandidateClipRow.project_id == ProjectRow.id,
            CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
            CandidateClipRow.selected_for_review.is_(True),
            CandidateClipRow.current_revision > 0,
            condition,
        )
        .correlate(ProjectRow)
        .exists()
    )


def _active_assignee_exists() -> Any:
    return (
        select(1)
        .select_from(WorkspaceUserRow)
        .where(
            WorkspaceUserRow.id == ProjectRow.assignee_user_id,
            WorkspaceUserRow.is_active.is_(True),
        )
        .correlate(ProjectRow)
        .exists()
    )


def _current_release_exists(condition: Any) -> Any:
    return (
        select(1)
        .select_from(ReleaseItemRow)
        .join(CandidateClipRow, CandidateClipRow.id == ReleaseItemRow.candidate_clip_id)
        .where(
            ReleaseItemRow.project_id == ProjectRow.id,
            CandidateClipRow.project_id == ProjectRow.id,
            CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
            CandidateClipRow.selected_for_review.is_(True),
            ReleaseItemRow.edit_plan_revision == CandidateClipRow.current_revision,
            condition,
        )
        .correlate(ProjectRow)
        .exists()
    )


def _priority_expression() -> Any:
    return case(
        (ProjectRow.priority == ProjectPriority.URGENT.value, 4),
        (ProjectRow.priority == ProjectPriority.HIGH.value, 3),
        (ProjectRow.priority == ProjectPriority.NORMAL.value, 2),
        (ProjectRow.priority == ProjectPriority.LOW.value, 1),
        else_=0,
    )


def _search_summary(
    connection: Connection,
    authorized: Any,
    *,
    now: datetime,
) -> ProjectSearchSummary:
    aggregate = (
        connection.execute(
            select(
                func.count().label("visible_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ProjectRow.lifecycle.in_(
                                    (
                                        ProjectLifecycle.NEEDS_ATTENTION.value,
                                        ProjectLifecycle.CHANGES_REQUESTED.value,
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("needs_attention"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ProjectRow.lifecycle.in_(
                                    (
                                        ProjectLifecycle.DRAFT.value,
                                        ProjectLifecycle.PROCESSING.value,
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("processing"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ProjectRow.lifecycle.in_(
                                    (
                                        ProjectLifecycle.EDITORIAL_REVIEW.value,
                                        ProjectLifecycle.APPROVAL.value,
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("review"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                ProjectRow.lifecycle.in_(
                                    (
                                        ProjectLifecycle.READY_TO_PUBLISH.value,
                                        ProjectLifecycle.PUBLISHED.value,
                                    )
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("publish"),
                func.coalesce(
                    func.sum(
                        case(
                            (ProjectRow.lifecycle == ProjectLifecycle.ARCHIVED.value, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("archived"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    ProjectRow.due_at.is_not(None),
                                    ProjectRow.due_at < now,
                                    ProjectRow.lifecycle != ProjectLifecycle.ARCHIVED.value,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("overdue"),
            )
            .select_from(ProjectRow)
            .join(authorized, authorized.c.project_id == ProjectRow.id)
        )
        .mappings()
        .one()
    )
    lifecycle_counts = {value.value: 0 for value in ProjectLifecycle}
    for lifecycle, count_value in connection.execute(
        select(ProjectRow.lifecycle, func.count())
        .join(authorized, authorized.c.project_id == ProjectRow.id)
        .group_by(ProjectRow.lifecycle)
    ):
        lifecycle_counts[str(lifecycle)] = int(count_value)
    priority_counts = {value.value: 0 for value in ProjectPriority}
    for priority, count_value in connection.execute(
        select(ProjectRow.priority, func.count())
        .join(authorized, authorized.c.project_id == ProjectRow.id)
        .group_by(ProjectRow.priority)
    ):
        priority_counts[str(priority)] = int(count_value)
    return ProjectSearchSummary(
        visible_total=int(aggregate["visible_total"]),
        needs_attention=int(aggregate["needs_attention"]),
        processing=int(aggregate["processing"]),
        review=int(aggregate["review"]),
        publish=int(aggregate["publish"]),
        archived=int(aggregate["archived"]),
        overdue=int(aggregate["overdue"]),
        lifecycle_counts=lifecycle_counts,
        priority_counts=priority_counts,
    )


def _apply_cursor_and_order(
    query: Select[Any],
    *,
    criteria: ProjectSearchCriteria,
    cursor: ProjectSearchCursor | None,
) -> Select[Any]:
    priority = _priority_expression()
    due_null = case((ProjectRow.due_at.is_(None), 1), else_=0)
    name = func.liveclip_normalize(ProjectRow.name)
    if criteria.sort == "updated_desc":
        if cursor is not None:
            updated_at = _cursor_datetime(cursor.primary)
            query = query.where(
                or_(
                    ProjectRow.updated_at < updated_at,
                    and_(
                        ProjectRow.updated_at == updated_at,
                        ProjectRow.id > cursor.project_id,
                    ),
                )
            )
        return query.order_by(ProjectRow.updated_at.desc(), ProjectRow.id)
    if criteria.sort == "due_asc":
        if cursor is not None:
            null_rank = _cursor_integer(cursor.primary, allowed={0, 1})
            if null_rank == 0:
                if cursor.secondary is None:
                    raise ValueError("project search cursor is invalid")
                due_at = _cursor_datetime(cursor.secondary)
                query = query.where(
                    or_(
                        due_null > null_rank,
                        and_(
                            due_null == null_rank,
                            or_(
                                ProjectRow.due_at > due_at,
                                and_(
                                    ProjectRow.due_at == due_at,
                                    ProjectRow.id > cursor.project_id,
                                ),
                            ),
                        ),
                    )
                )
            else:
                if cursor.secondary is not None:
                    raise ValueError("project search cursor is invalid")
                query = query.where(and_(due_null == 1, ProjectRow.id > cursor.project_id))
        return query.order_by(due_null, ProjectRow.due_at, ProjectRow.id)
    if criteria.sort == "priority_desc":
        if cursor is not None:
            priority_rank = _cursor_integer(cursor.primary, allowed={0, 1, 2, 3, 4})
            if cursor.secondary is None:
                raise ValueError("project search cursor is invalid")
            updated_at = _cursor_datetime(cursor.secondary)
            query = query.where(
                or_(
                    priority < priority_rank,
                    and_(
                        priority == priority_rank,
                        or_(
                            ProjectRow.updated_at < updated_at,
                            and_(
                                ProjectRow.updated_at == updated_at,
                                ProjectRow.id > cursor.project_id,
                            ),
                        ),
                    ),
                )
            )
        return query.order_by(priority.desc(), ProjectRow.updated_at.desc(), ProjectRow.id)
    if cursor is not None:
        query = query.where(
            or_(
                name > cursor.primary,
                and_(name == cursor.primary, ProjectRow.id > cursor.project_id),
            )
        )
    return query.order_by(name, ProjectRow.id)


def _cursor_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("project search cursor is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("project search cursor is invalid")
    return parsed


def _cursor_integer(value: str, *, allowed: set[int]) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("project search cursor is invalid") from exc
    if str(parsed) != value or parsed not in allowed:
        raise ValueError("project search cursor is invalid")
    return parsed


def _cursor_from_row(
    criteria: ProjectSearchCriteria,
    row: RowMapping,
    *,
    acting_user_id: str,
    evaluated_at: datetime,
) -> ProjectSearchCursor:
    common: dict[str, Any] = {
        "actor_user_id": acting_user_id,
        "criteria_fingerprint": criteria.fingerprint,
        "sort": criteria.sort,
        "evaluated_at": evaluated_at,
        "project_id": str(row["id"]),
    }
    if criteria.sort == "updated_desc":
        return ProjectSearchCursor(
            **common,
            primary=cast(datetime, row["updated_at"]).isoformat(),
        )
    if criteria.sort == "due_asc":
        due_at = cast(datetime | None, row["due_at"])
        return ProjectSearchCursor(
            **common,
            primary=str(int(cast(int, row["sort_due_null"]))),
            secondary=due_at.isoformat() if due_at is not None else None,
        )
    if criteria.sort == "priority_desc":
        return ProjectSearchCursor(
            **common,
            primary=str(int(cast(int, row["sort_priority"]))),
            secondary=cast(datetime, row["updated_at"]).isoformat(),
        )
    return ProjectSearchCursor(
        **common,
        primary=str(row["sort_name"]),
    )


def _load_page_documents(
    connection: Connection,
    project_ids: tuple[str, ...],
) -> dict[str, ProjectSearchDocument]:
    clip_documents: dict[str, list[ProjectSearchClipDocument]] = {
        project_id: [] for project_id in project_ids
    }
    release_documents: dict[str, list[ProjectSearchReleaseDocument]] = {
        project_id: [] for project_id in project_ids
    }
    for batch in _batches(project_ids):
        clip_rows = connection.execute(
            select(
                CandidateClipRow.project_id,
                CandidateClipRow.id,
                CandidateClipRow.transcript_text,
                EditPlanRevisionRow.title,
                EditPlanRevisionRow.hook,
            )
            .join(ProjectRow, ProjectRow.id == CandidateClipRow.project_id)
            .join(
                EditPlanRevisionRow,
                and_(
                    EditPlanRevisionRow.candidate_clip_id == CandidateClipRow.id,
                    EditPlanRevisionRow.revision == CandidateClipRow.current_revision,
                ),
            )
            .where(
                CandidateClipRow.project_id.in_(batch),
                CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
                CandidateClipRow.selected_for_review.is_(True),
                CandidateClipRow.current_revision > 0,
            )
            .order_by(CandidateClipRow.project_id, CandidateClipRow.rank, CandidateClipRow.id)
        )
        for clip_row in clip_rows:
            project_id = str(clip_row.project_id)
            clip_documents[project_id].append(
                ProjectSearchClipDocument(
                    clip_id=str(clip_row.id),
                    title=str(clip_row.title),
                    hook=str(clip_row.hook),
                    transcript_text=str(clip_row.transcript_text),
                )
            )
        release_rows = connection.execute(
            select(
                ReleaseItemRow.project_id,
                ReleaseItemRow.id,
                ReleaseItemRow.platform,
                ReleaseItemRow.title,
                ReleaseItemRow.account_label,
                ReleaseItemRow.hashtags_json,
            )
            .join(CandidateClipRow, CandidateClipRow.id == ReleaseItemRow.candidate_clip_id)
            .join(ProjectRow, ProjectRow.id == ReleaseItemRow.project_id)
            .where(
                ReleaseItemRow.project_id.in_(batch),
                CandidateClipRow.project_id == ReleaseItemRow.project_id,
                CandidateClipRow.pipeline_run_id == ProjectRow.current_pipeline_run_id,
                CandidateClipRow.selected_for_review.is_(True),
                ReleaseItemRow.edit_plan_revision == CandidateClipRow.current_revision,
            )
            .order_by(ReleaseItemRow.project_id, ReleaseItemRow.platform, ReleaseItemRow.id)
        )
        for release_row in release_rows:
            project_id = str(release_row.project_id)
            release_documents[project_id].append(
                ProjectSearchReleaseDocument(
                    release_item_id=str(release_row.id),
                    platform=ReleasePlatform(str(release_row.platform)),
                    title=str(release_row.title),
                    account_label=str(release_row.account_label),
                    hashtags=tuple(str(value) for value in release_row.hashtags_json),
                )
            )
    return {
        project_id: ProjectSearchDocument(
            project_id=project_id,
            clips=tuple(clip_documents[project_id]),
            releases=tuple(release_documents[project_id]),
        )
        for project_id in project_ids
    }


def _require_active_actor(connection: Connection, acting_user_id: str) -> None:
    active = connection.scalar(
        select(WorkspaceUserRow.is_active).where(WorkspaceUserRow.id == acting_user_id)
    )
    if active is not True:
        raise ProjectDiscoveryDenied("workspace account is no longer active")


def _batches(values: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
    for offset in range(0, len(values), _SQLITE_ID_BATCH):
        yield values[offset : offset + _SQLITE_ID_BATCH]


def _require_name_available(
    connection: Connection,
    *,
    acting_user_id: str,
    name_key: str,
    excluding_view_id: str | None = None,
) -> None:
    query = select(SavedProjectViewRow.id).where(
        SavedProjectViewRow.user_id == acting_user_id,
        SavedProjectViewRow.name_key == name_key,
    )
    if excluding_view_id is not None:
        query = query.where(SavedProjectViewRow.id != excluding_view_id)
    if connection.scalar(query.limit(1)) is not None:
        raise ProjectDiscoveryConflict("saved project view name already exists")


def _load_owned_saved_view(
    connection: Connection,
    view_id: str,
    *,
    acting_user_id: str,
    replay: bool = False,
) -> SavedProjectView:
    row = (
        connection.execute(
            select(
                SavedProjectViewRow.id,
                SavedProjectViewRow.name,
                SavedProjectViewRow.criteria_schema_version,
                SavedProjectViewRow.criteria_json,
                SavedProjectViewRow.version,
                SavedProjectViewRow.created_at,
                SavedProjectViewRow.updated_at,
            ).where(
                SavedProjectViewRow.id == view_id,
                SavedProjectViewRow.user_id == acting_user_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        if replay:
            raise ProjectDiscoveryConflict("saved project view replay is no longer available")
        raise ProjectDiscoveryNotFound("saved project view does not exist")
    return _saved_view(row)


def _saved_view(row: RowMapping) -> SavedProjectView:
    if str(row["criteria_schema_version"]) != "1":
        raise ProjectDiscoveryConflict("saved project view schema version is unsupported")
    payload = row["criteria_json"]
    try:
        criteria = ProjectSearchCriteria.model_validate_json(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    except Exception as exc:
        raise ProjectDiscoveryConflict("saved project view criteria is invalid") from exc
    return SavedProjectView(
        view_id=str(row["id"]),
        name=str(row["name"]),
        criteria_schema_version="1",
        criteria=criteria,
        version=int(cast(int, row["version"])),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
    )
