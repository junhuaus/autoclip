"""Stage 19b: ProjectSnapshot ties source_kind to run identity and generation."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from liveclip.application.pipeline import ProjectSnapshot, WorkspaceMember
from liveclip.domain.state_transitions import ProjectStatus

OWNER = WorkspaceMember(user_id="u1", username="owner", display_name="Owner", role="owner")


def _snapshot(**overrides: Any) -> ProjectSnapshot:
    values: dict[str, Any] = {
        "project_id": "p1",
        "name": "项目",
        "source_filename": "live.mp4",
        "status": ProjectStatus.PENDING_REVIEW,
        "current_run_id": "run-1",
        "generation": 1,
        "owner": OWNER,
        "members": (OWNER,),
        "current_user_role": "owner",
    }
    values.update(overrides)
    return ProjectSnapshot(**values)


def test_pipeline_and_imported_shapes_are_accepted() -> None:
    assert _snapshot().source_kind == "pipeline"
    imported = _snapshot(source_kind="dual_profile_import", current_run_id="", generation=0)
    assert imported.current_run_id == ""


@pytest.mark.parametrize(
    "overrides",
    [
        {"current_run_id": ""},
        {"generation": 0},
        {"source_kind": "dual_profile_import"},
        {"source_kind": "dual_profile_import", "current_run_id": "", "generation": 1},
        {"source_kind": "dual_profile_import", "current_run_id": "run-1", "generation": 0},
    ],
)
def test_inconsistent_source_kind_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**overrides)
