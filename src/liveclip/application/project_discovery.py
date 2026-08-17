from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import (
    PipelineResourceNotFound,
    PipelineService,
    ProjectSnapshot,
)
from liveclip.application.workspace import WorkspaceUser
from liveclip.domain.project_lifecycle import ProjectLifecycle, ProjectPriority
from liveclip.domain.releases import ReleasePlatform

MAX_PROJECT_SEARCH_QUERY_CHARS = 120
MAX_SAVED_PROJECT_VIEWS = 50
MAX_SAVED_VIEW_NAME_CHARS = 80
MAX_PROJECT_SEARCH_MATCHES = 8

ProjectRoleFilter = Literal["owner", "editor", "reviewer", "viewer"]
ProjectVisibilityFilter = Literal["private", "workspace"]
AssigneeFilter = Literal["any", "me", "unassigned", "user"]
DueFilter = Literal["any", "overdue", "today", "next_7_days", "unscheduled"]
ProjectSearchSort = Literal["updated_desc", "due_asc", "priority_desc", "name_asc"]
ProjectSearchMatchScope = Literal[
    "project",
    "source",
    "clip_title",
    "clip_hook",
    "transcript",
    "assignee",
    "lifecycle",
    "platform",
]


class ProjectDiscoveryConflict(RuntimeError):
    """A saved-view mutation conflicts with current persisted state."""


class ProjectDiscoveryNotFound(LookupError):
    """A user-owned saved view or authorized search resource is unavailable."""


class ProjectDiscoveryDenied(PermissionError):
    """The acting workspace account no longer has live authority."""


class ProjectSearchCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query: str = Field(default="", max_length=MAX_PROJECT_SEARCH_QUERY_CHARS)
    lifecycles: tuple[ProjectLifecycle, ...] = Field(default=(), max_length=9)
    priorities: tuple[ProjectPriority, ...] = Field(default=(), max_length=4)
    roles: tuple[ProjectRoleFilter, ...] = Field(default=(), max_length=4)
    visibilities: tuple[ProjectVisibilityFilter, ...] = Field(default=(), max_length=2)
    platforms: tuple[ReleasePlatform, ...] = Field(default=(), max_length=6)
    assignee: AssigneeFilter = "any"
    assignee_user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    due: DueFilter = "any"
    sort: ProjectSearchSort = "updated_desc"

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("project search query must be text")
        normalized = " ".join(unicodedata.normalize("NFKC", value).split())
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in normalized):
            raise ValueError("project search query contains control characters")
        return normalized

    @model_validator(mode="after")
    def validate_filters(self) -> ProjectSearchCriteria:
        for values, label in (
            (self.lifecycles, "lifecycle"),
            (self.priorities, "priority"),
            (self.roles, "role"),
            (self.visibilities, "visibility"),
            (self.platforms, "platform"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"project search {label} filters must be unique")
        if self.assignee == "user" and self.assignee_user_id is None:
            raise ValueError("assignee_user_id is required for the user assignee filter")
        if self.assignee != "user" and self.assignee_user_id is not None:
            raise ValueError("assignee_user_id is only valid for the user assignee filter")
        object.__setattr__(
            self,
            "lifecycles",
            tuple(sorted(self.lifecycles, key=lambda value: value.value)),
        )
        object.__setattr__(
            self,
            "priorities",
            tuple(sorted(self.priorities, key=lambda value: value.value)),
        )
        object.__setattr__(self, "roles", tuple(sorted(self.roles)))
        object.__setattr__(self, "visibilities", tuple(sorted(self.visibilities)))
        object.__setattr__(
            self,
            "platforms",
            tuple(sorted(self.platforms, key=lambda value: value.value)),
        )
        return self

    @property
    def fingerprint(self) -> str:
        normalized = self.model_dump(mode="json")
        normalized["query"] = _search_text(self.query)
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ProjectSearchClipDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    clip_id: str
    title: str
    hook: str
    transcript_text: str


class ProjectSearchReleaseDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    release_item_id: str
    platform: ReleasePlatform
    title: str
    account_label: str
    hashtags: tuple[str, ...] = ()


class ProjectSearchDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    clips: tuple[ProjectSearchClipDocument, ...] = ()
    releases: tuple[ProjectSearchReleaseDocument, ...] = ()


class ProjectSearchMatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scope: ProjectSearchMatchScope
    text: str = Field(min_length=1, max_length=220)
    clip_id: str | None = None
    release_item_id: str | None = None


class ProjectSearchItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project: ProjectSnapshot
    matches: tuple[ProjectSearchMatch, ...] = Field(
        default=(), max_length=MAX_PROJECT_SEARCH_MATCHES
    )


class ProjectSearchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    visible_total: int = Field(ge=0)
    needs_attention: int = Field(ge=0)
    processing: int = Field(ge=0)
    review: int = Field(ge=0)
    publish: int = Field(ge=0)
    archived: int = Field(ge=0)
    overdue: int = Field(ge=0)
    lifecycle_counts: dict[str, int]
    priority_counts: dict[str, int]


class ProjectSearchPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    criteria: ProjectSearchCriteria
    query_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluated_at: datetime
    timezone: str = Field(min_length=1, max_length=80)
    total_count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    next_cursor: str | None = Field(default=None, max_length=1_024)
    summary: ProjectSearchSummary
    items: tuple[ProjectSearchItem, ...]


class ProjectSearchCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1"] = "1"
    resource: Literal["projects"] = "projects"
    actor_user_id: str = Field(min_length=1, max_length=64)
    criteria_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    sort: ProjectSearchSort
    evaluated_at: datetime
    primary: str = Field(max_length=500)
    secondary: str | None = Field(default=None, max_length=80)
    project_id: str = Field(min_length=1, max_length=64)

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("project search cursor time must include a timezone")
        return value


class ProjectSearchSelectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    project_id: str
    project_updated_at: datetime
    current_role: ProjectRoleFilter
    document: ProjectSearchDocument


class ProjectSearchSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    total_count: int = Field(ge=0)
    next_cursor: str | None = Field(default=None, max_length=1_024)
    summary: ProjectSearchSummary
    items: tuple[ProjectSearchSelectionItem, ...]


class SavedProjectView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    view_id: str
    name: str = Field(min_length=1, max_length=MAX_SAVED_VIEW_NAME_CHARS)
    criteria_schema_version: Literal["1"] = "1"
    criteria: ProjectSearchCriteria
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


class CreateSavedProjectView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1, max_length=MAX_SAVED_VIEW_NAME_CHARS)
    criteria: ProjectSearchCriteria

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> str:
        return normalize_saved_view_name(value)

    @property
    def name_key(self) -> str:
        return self.name.casefold()


class UpdateSavedProjectView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=MAX_SAVED_VIEW_NAME_CHARS)
    criteria: ProjectSearchCriteria

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> str:
        return normalize_saved_view_name(value)

    @property
    def name_key(self) -> str:
        return self.name.casefold()


class ProjectDiscoveryRepository(Protocol):
    def search_projects(
        self,
        *,
        acting_user_id: str,
        criteria: ProjectSearchCriteria,
        limit: int,
        cursor: ProjectSearchCursor | None,
        now: datetime,
    ) -> ProjectSearchSelection: ...

    def list_saved_views(self, *, acting_user_id: str) -> tuple[SavedProjectView, ...]: ...

    def create_saved_view(
        self,
        command: CreateSavedProjectView,
        *,
        acting_user_id: str,
        idempotency: IdempotencyContext | None = None,
    ) -> SavedProjectView: ...

    def update_saved_view(
        self,
        view_id: str,
        command: UpdateSavedProjectView,
        *,
        acting_user_id: str,
    ) -> SavedProjectView: ...

    def delete_saved_view(
        self,
        view_id: str,
        *,
        expected_version: int,
        acting_user_id: str,
    ) -> None: ...


class ProjectDiscoveryService:
    def __init__(
        self,
        repository: ProjectDiscoveryRepository,
        pipeline_service: PipelineService,
    ) -> None:
        self._repository = repository
        self._pipeline_service = pipeline_service

    def search(
        self,
        actor: WorkspaceUser,
        criteria: ProjectSearchCriteria,
        *,
        limit: int = 20,
        cursor: str | None = None,
        now: datetime | None = None,
    ) -> ProjectSearchPage:
        if not 1 <= limit <= 100:
            raise ValueError("project search limit must be between 1 and 100")
        decoded_cursor = (
            decode_project_search_cursor(cursor, criteria, actor_user_id=actor.user_id)
            if cursor
            else None
        )
        evaluated_at = (
            decoded_cursor.evaluated_at if decoded_cursor else now or datetime.now().astimezone()
        )
        selection = self._repository.search_projects(
            acting_user_id=actor.user_id,
            criteria=criteria,
            limit=limit,
            cursor=decoded_cursor,
            now=evaluated_at,
        )
        page_items: list[ProjectSearchItem] = []
        for selected in selection.items:
            try:
                project = self._pipeline_service.get_project(
                    selected.project_id,
                    user_id=actor.user_id,
                )
            except PipelineResourceNotFound:
                # Authority is rechecked during hydration. A concurrent revoke
                # may shorten one page but can never disclose the Project.
                continue
            matches = _query_matches(project, selected.document, criteria.query)
            if criteria.query and not matches:
                raise ProjectDiscoveryConflict(
                    "project search evidence changed during result hydration"
                )
            page_items.append(ProjectSearchItem(project=project, matches=matches))
        confirmed = self._repository.search_projects(
            acting_user_id=actor.user_id,
            criteria=criteria,
            limit=limit,
            cursor=decoded_cursor,
            now=evaluated_at,
        )
        if confirmed != selection:
            raise ProjectDiscoveryConflict(
                "project search results changed during response assembly; retry"
            )
        return ProjectSearchPage(
            criteria=criteria,
            query_fingerprint=criteria.fingerprint,
            evaluated_at=evaluated_at,
            timezone=str(evaluated_at.tzinfo or "UTC"),
            total_count=selection.total_count,
            limit=limit,
            next_cursor=selection.next_cursor,
            summary=selection.summary,
            items=tuple(page_items),
        )

    def list_saved_views(self, actor: WorkspaceUser) -> tuple[SavedProjectView, ...]:
        return self._repository.list_saved_views(acting_user_id=actor.user_id)

    def create_saved_view(
        self,
        actor: WorkspaceUser,
        command: CreateSavedProjectView,
        *,
        idempotency: IdempotencyContext | None = None,
    ) -> SavedProjectView:
        return self._repository.create_saved_view(
            command,
            acting_user_id=actor.user_id,
            idempotency=idempotency,
        )

    def update_saved_view(
        self,
        actor: WorkspaceUser,
        view_id: str,
        command: UpdateSavedProjectView,
    ) -> SavedProjectView:
        return self._repository.update_saved_view(
            view_id,
            command,
            acting_user_id=actor.user_id,
        )

    def delete_saved_view(
        self,
        actor: WorkspaceUser,
        view_id: str,
        *,
        expected_version: int,
    ) -> None:
        if expected_version < 1:
            raise ValueError("saved view version must be positive")
        self._repository.delete_saved_view(
            view_id,
            expected_version=expected_version,
            acting_user_id=actor.user_id,
        )


def normalize_saved_view_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("saved view name must be text")
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not normalized:
        raise ValueError("saved view name cannot be empty")
    if len(normalized) > MAX_SAVED_VIEW_NAME_CHARS:
        raise ValueError("saved view name is too long")
    if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in normalized):
        raise ValueError("saved view name contains control characters")
    return normalized


def encode_project_search_cursor(cursor: ProjectSearchCursor) -> str:
    payload = cursor.model_dump_json().encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    if len(encoded) > 1_024:
        raise ValueError("project search cursor is too large")
    return encoded


def decode_project_search_cursor(
    raw_cursor: str,
    criteria: ProjectSearchCriteria,
    *,
    actor_user_id: str,
) -> ProjectSearchCursor:
    if not raw_cursor or len(raw_cursor) > 1_024:
        raise ValueError("project search cursor is invalid")
    try:
        padding = "=" * (-len(raw_cursor) % 4)
        decoded = base64.b64decode(
            (raw_cursor + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        cursor = ProjectSearchCursor.model_validate_json(decoded)
    except Exception as exc:
        raise ValueError("project search cursor is invalid") from exc
    if (
        cursor.actor_user_id != actor_user_id
        or cursor.criteria_fingerprint != criteria.fingerprint
        or cursor.sort != criteria.sort
    ):
        raise ValueError("project search cursor does not match the current filters")
    return cursor


_LIFECYCLE_TEXT = {
    ProjectLifecycle.DRAFT: "draft 草稿",
    ProjectLifecycle.PROCESSING: "processing 处理中",
    ProjectLifecycle.NEEDS_ATTENTION: "needs_attention 需要处理",
    ProjectLifecycle.EDITORIAL_REVIEW: "editorial_review 编辑审核",
    ProjectLifecycle.CHANGES_REQUESTED: "changes_requested 需要修改",
    ProjectLifecycle.APPROVAL: "approval 审批",
    ProjectLifecycle.READY_TO_PUBLISH: "ready_to_publish 待发布",
    ProjectLifecycle.PUBLISHED: "published 已发布",
    ProjectLifecycle.ARCHIVED: "archived 已归档",
}

_PLATFORM_TEXT = {
    ReleasePlatform.DOUYIN: "douyin 抖音",
    ReleasePlatform.XIAOHONGSHU: "xiaohongshu 小红书",
    ReleasePlatform.BILIBILI_VERTICAL: "bilibili_vertical 哔哩哔哩 B站",
    ReleasePlatform.YOUTUBE_SHORTS: "youtube_shorts YouTube Shorts",
    ReleasePlatform.TIKTOK: "tiktok TikTok",
    ReleasePlatform.GENERIC_VERTICAL: "generic_vertical 通用竖屏",
}


def matching_lifecycles_for_query(query: str) -> tuple[ProjectLifecycle, ...]:
    needle = _search_text(query)
    if not needle:
        return ()
    return tuple(
        lifecycle
        for lifecycle, search_text in _LIFECYCLE_TEXT.items()
        if needle in _search_text(search_text)
    )


def matching_platforms_for_query(query: str) -> tuple[ReleasePlatform, ...]:
    needle = _search_text(query)
    if not needle:
        return ()
    return tuple(
        platform
        for platform, search_text in _PLATFORM_TEXT.items()
        if needle in _search_text(search_text)
    )


def _query_matches(
    project: ProjectSnapshot,
    document: ProjectSearchDocument,
    query: str,
) -> tuple[ProjectSearchMatch, ...]:
    if not query:
        return ()
    needle = _search_text(query)
    matches: list[ProjectSearchMatch] = []

    def add(
        scope: ProjectSearchMatchScope,
        value: str,
        *,
        clip_id: str | None = None,
        release_item_id: str | None = None,
        snippet: bool = False,
    ) -> None:
        if len(matches) >= MAX_PROJECT_SEARCH_MATCHES or needle not in _search_text(value):
            return
        text = _snippet(value, query) if snippet else " ".join(value.split())[:220]
        matches.append(
            ProjectSearchMatch(
                scope=scope,
                text=text or query,
                clip_id=clip_id,
                release_item_id=release_item_id,
            )
        )

    add("project", project.name)
    add("source", project.source_filename)
    if project.assignee is not None:
        add("assignee", project.assignee.display_name)
        add("assignee", project.assignee.username)
    add("lifecycle", _LIFECYCLE_TEXT[project.lifecycle])
    for clip in document.clips:
        add("clip_title", clip.title, clip_id=clip.clip_id)
        add("clip_hook", clip.hook, clip_id=clip.clip_id)
        add("transcript", clip.transcript_text, clip_id=clip.clip_id, snippet=True)
    for release in document.releases:
        platform_text = " ".join(
            (
                _PLATFORM_TEXT[release.platform],
                release.title,
                release.account_label,
                *release.hashtags,
            )
        )
        add(
            "platform",
            platform_text,
            release_item_id=release.release_item_id,
            snippet=True,
        )
    return tuple(matches)


def _search_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _snippet(value: str, query: str) -> str:
    compact = " ".join(value.split())
    if len(compact) <= 220:
        return compact
    index = _search_text(compact).find(_search_text(query))
    if index < 0:
        return compact[:217] + "…"
    start = max(0, index - 80)
    end = min(len(compact), index + len(query) + 120)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"[:220]
