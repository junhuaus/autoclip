"""Validated completion commands; observation never drives work."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from liveclip.application.completion import (
    CompletionOptions,
    CompletionRepository,
    CompletionSelectionSubmission,
    CompletionSnapshot,
)
from liveclip.application.idempotency import IdempotencyContext
from liveclip.application.pipeline import PipelineRunConfig


class CompletionService:
    def __init__(
        self,
        repository: CompletionRepository,
        *,
        allowed_source_roots: tuple[Path, ...],
        forbidden_source_roots: tuple[Path, ...],
    ) -> None:
        self._repository = repository
        self._allowed = tuple(root.resolve(strict=False) for root in allowed_source_roots)
        self._forbidden = tuple(root.resolve(strict=False) for root in forbidden_source_roots)

    def _validate_fresh_source(self, source_path: Path) -> Path:
        """Run only for a genuinely new goal, inside its create transaction."""

        try:
            source = source_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("source media does not exist or cannot be resolved") from exc
        if not self._allowed or not any(
            source == root or root in source.parents for root in self._allowed
        ):
            raise ValueError("source media must be inside configured allowed roots")
        if any(source == root or root in source.parents for root in self._forbidden):
            raise ValueError("source media must be outside the LiveClip data directory")
        if not source.is_file():
            raise ValueError("source media must be a readable regular file")
        try:
            with source.open("rb"):
                pass
        except OSError as exc:
            raise ValueError("source media must be a readable regular file") from exc
        return source

    def create_for_existing_run(
        self,
        *,
        project_id: str,
        run_id: str,
        actor_user_id: str,
        options: CompletionOptions,
        idempotency: IdempotencyContext,
    ) -> CompletionSnapshot:
        return self._repository.create_for_existing_run(
            project_id=project_id,
            run_id=run_id,
            actor_user_id=actor_user_id,
            options=options,
            idempotency=idempotency,
        )

    def create_project_and_run_with_goal(
        self,
        *,
        source_path: Path,
        config: PipelineRunConfig,
        max_stage_retries: int,
        actor_user_id: str,
        options: CompletionOptions,
        idempotency: IdempotencyContext,
        readiness_guard: Callable[[], None],
    ) -> CompletionSnapshot:
        if not source_path.is_absolute() or ".." in source_path.parts:
            raise ValueError("source path must be absolute and cannot contain '..'")
        if (
            isinstance(max_stage_retries, bool)
            or not isinstance(max_stage_retries, int)
            or max_stage_retries < 0
        ):
            raise ValueError("max stage retries must be nonnegative")

        def fresh_source_guard(requested: Path) -> Path:
            validated = self._validate_fresh_source(requested)
            readiness_guard()
            return validated

        return self._repository.create_project_and_run_with_goal(
            source_path=source_path,
            config=config,
            max_stage_retries=max_stage_retries,
            actor_user_id=actor_user_id,
            options=options,
            idempotency=idempotency,
            fresh_source_guard=fresh_source_guard,
        )

    def get(self, intent_id: str, *, actor_user_id: str) -> CompletionSnapshot:
        return self._repository.get(intent_id, actor_user_id=actor_user_id)

    def list_for_project(
        self, project_id: str, *, actor_user_id: str
    ) -> tuple[CompletionSnapshot, ...]:
        """Read authorized goals without claiming, waking or resuming work."""

        return self._repository.list_for_project(project_id, actor_user_id=actor_user_id)

    def resume(
        self, intent_id: str, *, actor_user_id: str, expected_version: int
    ) -> CompletionSnapshot:
        return self._repository.resume(
            intent_id,
            actor_user_id=actor_user_id,
            expected_version=expected_version,
        )

    def cancel(
        self, intent_id: str, *, actor_user_id: str, expected_version: int
    ) -> CompletionSnapshot:
        return self._repository.cancel(
            intent_id,
            actor_user_id=actor_user_id,
            expected_version=expected_version,
        )

    def submit_selection(
        self, intent_id: str, submission: CompletionSelectionSubmission, *, actor_user_id: str
    ) -> CompletionSnapshot:
        return self._repository.submit_selection(
            intent_id,
            submission,
            actor_user_id=actor_user_id,
        )
