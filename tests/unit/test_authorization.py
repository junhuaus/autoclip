from __future__ import annotations

import pytest

from liveclip.application.authorization import (
    ProjectActionDenied,
    project_actions,
    require_project_action,
)


@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        ("owner", "manage_members", None),
        ("editor", "edit_clip", "review_clip"),
        ("reviewer", "review_clip", "edit_clip"),
        ("viewer", "read", "render"),
    ],
)
def test_project_actions_are_centrally_authorized(
    role: str,
    allowed: str,
    denied: str | None,
) -> None:
    require_project_action(role, allowed)  # type: ignore[arg-type]
    if denied is not None:
        with pytest.raises(ProjectActionDenied):
            require_project_action(role, denied)  # type: ignore[arg-type]


def test_capability_list_comes_from_the_same_policy_matrix() -> None:
    assert project_actions("viewer") == ("read",)
    assert project_actions("reviewer") == ("read", "review_clip")
