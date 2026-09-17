from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from liveclip.application.completion import CompletionOptions, CompletionRepository
from liveclip.application.completion_runner import CompletionRunner, ReconciliationResult
from liveclip.application.completion_service import CompletionService
from liveclip.application.idempotency import build_idempotency_context
from liveclip.application.pipeline import PipelineRunConfig


@pytest.mark.parametrize("source", ["relative.mp4", "../escape.mp4", "outside", "data", "symlink"])
def test_source_boundary_rejects_at_correct_create_phase(tmp_path: Path, source: str) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    forbidden = allowed / "data"
    forbidden.mkdir()
    alias = allowed / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    paths = {
        "relative.mp4": Path("relative.mp4"),
        "../escape.mp4": allowed / ".." / "escape.mp4",
        "outside": tmp_path / "source.mp4",
        "data": forbidden / "source.mp4",
        "symlink": alias / "source.mp4",
    }
    (tmp_path / "source.mp4").write_bytes(b"synthetic")
    (forbidden / "source.mp4").write_bytes(b"synthetic")
    repository = Mock(spec=CompletionRepository)
    service = CompletionService(
        repository, allowed_source_roots=(allowed,), forbidden_source_roots=(forbidden,)
    )
    arguments = dict(
        source_path=paths[source],
        config=Mock(spec=PipelineRunConfig),
        max_stage_retries=3,
        actor_user_id="actor",
        options=CompletionOptions(),
        idempotency=build_idempotency_context(
            raw_key="synthetic",
            caller_scope="actor",
            operation_scope="create",
            request_payload={},
        ),
        readiness_guard=lambda: None,
    )
    if source in {"relative.mp4", "../escape.mp4"}:
        with pytest.raises(ValueError):
            service.create_project_and_run_with_goal(**arguments)
        repository.create_project_and_run_with_goal.assert_not_called()
    else:
        service.create_project_and_run_with_goal(**arguments)
        guard = repository.create_project_and_run_with_goal.call_args.kwargs["fresh_source_guard"]
        with pytest.raises(ValueError):
            guard(paths[source])


def test_completion_runner_claims_supported_completion_targets() -> None:
    lease = Mock()
    queue = Mock()
    queue.claim_completion.return_value = lease
    repository = Mock()
    repository.reconcile_completion.return_value = ReconciliationResult.DEFERRED

    result = CompletionRunner(queue, repository).run_once(worker_id="worker")

    assert result == ReconciliationResult.DEFERRED
    queue.claim_completion.assert_called_once_with(worker_id="worker", now=None)
    repository.reconcile_completion.assert_called_once_with(lease, now=None)


def test_completion_runner_is_idle_without_a_completion_claim() -> None:
    queue = Mock()
    queue.claim_completion.return_value = None
    repository = Mock()

    assert (
        CompletionRunner(queue, repository).run_once(worker_id="worker")
        == ReconciliationResult.IDLE
    )
    repository.reconcile_completion.assert_not_called()
