from __future__ import annotations

from typing import Literal

from liveclip.application.workspace import WorkspaceRole

ProjectAction = Literal[
    "read",
    "manage_members",
    "run_pipeline",
    "edit_clip",
    "review_clip",
    "render",
    "deliver",
]
PROJECT_ACTION_ORDER: tuple[ProjectAction, ...] = (
    "read",
    "manage_members",
    "run_pipeline",
    "edit_clip",
    "review_clip",
    "render",
    "deliver",
)

_ALLOWED: dict[WorkspaceRole, frozenset[ProjectAction]] = {
    "owner": frozenset(
        {
            "read",
            "manage_members",
            "run_pipeline",
            "edit_clip",
            "review_clip",
            "render",
            "deliver",
        }
    ),
    "editor": frozenset({"read", "run_pipeline", "edit_clip", "render", "deliver"}),
    "reviewer": frozenset({"read", "review_clip"}),
    "viewer": frozenset({"read"}),
}


class ProjectActionDenied(PermissionError):
    """A project membership does not grant the requested business action."""


def require_project_action(role: WorkspaceRole, action: ProjectAction) -> None:
    if action not in _ALLOWED[role]:
        raise ProjectActionDenied("project role does not grant this action")


def project_actions(role: WorkspaceRole) -> tuple[ProjectAction, ...]:
    return tuple(action for action in PROJECT_ACTION_ORDER if action in _ALLOWED[role])
