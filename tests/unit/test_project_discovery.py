from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from liveclip.application.project_discovery import (
    CreateSavedProjectView,
    ProjectDiscoveryConflict,
    ProjectDiscoveryService,
    ProjectSearchCriteria,
    ProjectSearchCursor,
    ProjectSearchSelection,
    ProjectSearchSummary,
    decode_project_search_cursor,
    encode_project_search_cursor,
)
from liveclip.application.workspace import WorkspaceUser
from liveclip.domain.project_lifecycle import ProjectLifecycle, ProjectPriority


def test_search_criteria_is_canonical_and_has_a_semantic_fingerprint() -> None:
    first = ProjectSearchCriteria(
        query="  ＡＢＣ  ",  # noqa: RUF001 - intentional NFKC coverage
        lifecycles=(ProjectLifecycle.PROCESSING, ProjectLifecycle.DRAFT),
        priorities=(ProjectPriority.URGENT, ProjectPriority.NORMAL),
        roles=("viewer", "owner"),
    )
    second = ProjectSearchCriteria(
        query="abc",
        lifecycles=(ProjectLifecycle.DRAFT, ProjectLifecycle.PROCESSING),
        priorities=(ProjectPriority.NORMAL, ProjectPriority.URGENT),
        roles=("owner", "viewer"),
    )

    assert first.query == "ABC"
    assert first.lifecycles == (ProjectLifecycle.DRAFT, ProjectLifecycle.PROCESSING)
    assert first.priorities == (ProjectPriority.NORMAL, ProjectPriority.URGENT)
    assert first.roles == ("owner", "viewer")
    assert first.fingerprint == second.fingerprint


def test_search_criteria_rejects_duplicate_and_incoherent_filters() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        ProjectSearchCriteria(lifecycles=(ProjectLifecycle.DRAFT, ProjectLifecycle.DRAFT))
    with pytest.raises(ValidationError, match="assignee_user_id is required"):
        ProjectSearchCriteria(assignee="user")
    with pytest.raises(ValidationError, match="only valid"):
        ProjectSearchCriteria(assignee="me", assignee_user_id="someone")
    with pytest.raises(ValidationError, match="String should match pattern"):
        ProjectSearchCriteria(assignee="user", assignee_user_id="../someone")


def test_search_cursor_is_bound_to_actor_and_canonical_filters() -> None:
    criteria = ProjectSearchCriteria(query="直播", sort="name_asc")
    encoded = encode_project_search_cursor(
        ProjectSearchCursor(
            actor_user_id="editor-a",
            criteria_fingerprint=criteria.fingerprint,
            sort=criteria.sort,
            evaluated_at=datetime(2026, 8, 16, tzinfo=UTC),
            primary="项目一",
            project_id="p" * 32,
        )
    )

    assert (
        decoded := decode_project_search_cursor(
            encoded,
            criteria,
            actor_user_id="editor-a",
        )
    )
    assert decoded.project_id == "p" * 32
    assert decoded.evaluated_at == datetime(2026, 8, 16, tzinfo=UTC)
    with pytest.raises(ValueError, match="does not match"):
        decode_project_search_cursor(
            encoded,
            criteria,
            actor_user_id="editor-b",
        )
    with pytest.raises(ValueError, match="does not match"):
        decode_project_search_cursor(
            encoded,
            ProjectSearchCriteria(query="另一条件", sort="name_asc"),
            actor_user_id="editor-a",
        )
    with pytest.raises(ValueError, match="invalid"):
        decode_project_search_cursor("not-base64!", criteria, actor_user_id="editor-a")


def test_saved_view_names_are_nfkc_trimmed_and_casefolded_for_uniqueness() -> None:
    command = CreateSavedProjectView(
        name="  Ｍｙ   View  ",  # noqa: RUF001 - intentional NFKC coverage
        criteria=ProjectSearchCriteria(),
    )

    assert command.name == "My View"
    assert command.name_key == "my view"


def test_search_rejects_metadata_that_changes_during_response_assembly() -> None:
    empty_summary = ProjectSearchSummary(
        visible_total=0,
        needs_attention=0,
        processing=0,
        review=0,
        publish=0,
        archived=0,
        overdue=0,
        lifecycle_counts={},
        priority_counts={},
    )
    changed_summary = empty_summary.model_copy(update={"visible_total": 1})
    repository = Mock()
    repository.search_projects.side_effect = (
        ProjectSearchSelection(total_count=0, summary=empty_summary, items=()),
        ProjectSearchSelection(total_count=1, summary=changed_summary, items=()),
    )
    service = ProjectDiscoveryService(repository, Mock())
    evaluated_at = datetime(2026, 8, 16, 23, 59, tzinfo=UTC)

    with pytest.raises(ProjectDiscoveryConflict, match="changed during response assembly"):
        service.search(
            WorkspaceUser(
                user_id="editor-a",
                username="editor-a",
                display_name="编辑 A",
            ),
            ProjectSearchCriteria(due="next_7_days"),
            now=evaluated_at,
        )

    calls = repository.search_projects.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["now"] == evaluated_at
    assert calls[1].kwargs["now"] == evaluated_at

    repository.reset_mock()
    stable_selection = ProjectSearchSelection(
        total_count=0,
        summary=empty_summary,
        items=(),
    )
    repository.search_projects.side_effect = (stable_selection, stable_selection)
    cursor_time = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    cursor = encode_project_search_cursor(
        ProjectSearchCursor(
            actor_user_id="editor-a",
            criteria_fingerprint=ProjectSearchCriteria(due="next_7_days").fingerprint,
            sort="updated_desc",
            evaluated_at=cursor_time,
            primary=cursor_time.isoformat(),
            project_id="p" * 32,
        )
    )
    page = service.search(
        WorkspaceUser(
            user_id="editor-a",
            username="editor-a",
            display_name="编辑 A",
        ),
        ProjectSearchCriteria(due="next_7_days"),
        cursor=cursor,
        now=datetime(2026, 8, 18, 8, 0, tzinfo=UTC),
    )
    assert page.evaluated_at == cursor_time
    assert all(
        call.kwargs["now"] == cursor_time for call in repository.search_projects.call_args_list
    )
