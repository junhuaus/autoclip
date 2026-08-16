from __future__ import annotations

from typing import Literal

from liveclip.application.workspace import WorkspaceRole

ProjectAction = Literal[
    "read",
    "manage_members",
    "manage_project",
    "run_pipeline",
    "edit_clip",
    "review_clip",
    "comment",
    "render",
    "export",
    "deliver",
    "manage_release",
    "approve_release",
]
PROJECT_ACTION_ORDER: tuple[ProjectAction, ...] = (
    "read",
    "manage_members",
    "manage_project",
    "run_pipeline",
    "edit_clip",
    "review_clip",
    "comment",
    "render",
    "export",
    "deliver",
    "manage_release",
    "approve_release",
)

_ALLOWED: dict[WorkspaceRole, frozenset[ProjectAction]] = {
    "owner": frozenset(
        {
            "read",
            "manage_members",
            "manage_project",
            "run_pipeline",
            "edit_clip",
            "review_clip",
            "comment",
            "render",
            "export",
            "deliver",
            "manage_release",
            "approve_release",
        }
    ),
    "editor": frozenset(
        {
            "read",
            "run_pipeline",
            "edit_clip",
            "comment",
            "render",
            "export",
            "deliver",
            "manage_release",
        }
    ),
    "reviewer": frozenset({"read", "review_clip", "comment", "approve_release"}),
    "viewer": frozenset({"read"}),
}


class ProjectActionDenied(PermissionError):
    """A project membership does not grant the requested business action."""


def require_project_action(
    role: WorkspaceRole,
    action: ProjectAction,
    *,
    archived: bool = False,
) -> None:
    if archived and action not in {"read", "manage_project"}:
        raise ProjectActionDenied("archived projects are read-only")
    if action not in _ALLOWED[role]:
        raise ProjectActionDenied("project role does not grant this action")


def project_actions(role: WorkspaceRole, *, archived: bool = False) -> tuple[ProjectAction, ...]:
    return tuple(
        action
        for action in PROJECT_ACTION_ORDER
        if action in _ALLOWED[role] and (not archived or action in {"read", "manage_project"})
    )
