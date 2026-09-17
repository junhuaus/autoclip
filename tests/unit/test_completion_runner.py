from unittest.mock import Mock

import pytest

from liveclip.application.completion_runner import CompletionRunner, ReconciliationResult
from liveclip.application.tasks import TaskQueueTransientError


def test_claim_contention_is_busy_without_reconciliation():
    queue, repository = Mock(), Mock()
    queue.claim_completion.side_effect = TaskQueueTransientError("locked")
    assert CompletionRunner(queue, repository).run_once(worker_id="worker") == "busy"
    repository.reconcile_completion.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("defect"), KeyboardInterrupt()])
@pytest.mark.parametrize("during_claim", [True, False])
def test_nonclaim_errors_and_shutdown_propagate(error, during_claim):
    queue, repository = Mock(), Mock()
    target = queue.claim_completion if during_claim else repository.reconcile_completion
    target.side_effect = error
    with pytest.raises(type(error)):
        CompletionRunner(queue, repository).run_once(worker_id="worker")


def test_reconciliation_transient_error_is_not_hidden_as_busy():
    queue, repository = Mock(), Mock()
    repository.reconcile_completion.side_effect = TaskQueueTransientError("write failed")
    with pytest.raises(TaskQueueTransientError):
        CompletionRunner(queue, repository).run_once(worker_id="worker")


def test_empty_claim_is_idle():
    queue, repository = Mock(), Mock()
    queue.claim_completion.return_value = None
    assert (
        CompletionRunner(queue, repository).run_once(worker_id="worker")
        == ReconciliationResult.IDLE
    )
    repository.reconcile_completion.assert_not_called()
