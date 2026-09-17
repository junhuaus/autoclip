"""Durable completion identities and legal goal transitions.

The goal is separate from the processing run. A successful processing run is not
implicitly a delivered package, and a parked goal is not a completed task.
"""

from __future__ import annotations

from enum import StrEnum

from liveclip.domain.state_transitions import InvalidStateTransition


class CompletionTarget(StrEnum):
    PROCESS_ONLY = "process_only"
    DELIVERY = "delivery"


class CompletionSelectionPolicy(StrEnum):
    DEFAULT = "default"
    MANUAL = "manual"


class CompletionIntentStatus(StrEnum):
    QUEUED = "queued"
    WAITING_WORK = "waiting_work"
    WAITING_SELECTION = "waiting_selection"
    NEEDS_ACTION = "needs_action"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"


class CompletionOutcome(StrEnum):
    PROCESSED = "processed"
    DELIVERED = "delivered"
    NO_ELIGIBLE_CLIPS = "no_eligible_clips"
    NO_SELECTED_CLIPS = "no_selected_clips"
    CANCELLED = "cancelled"


_TRANSITIONS = {
    CompletionIntentStatus.QUEUED: frozenset(
        {
            CompletionIntentStatus.WAITING_WORK,
            CompletionIntentStatus.WAITING_SELECTION,
            CompletionIntentStatus.NEEDS_ACTION,
            CompletionIntentStatus.SUCCEEDED,
            CompletionIntentStatus.CANCELLED,
        }
    ),
    CompletionIntentStatus.WAITING_WORK: frozenset(
        {
            CompletionIntentStatus.QUEUED,
            CompletionIntentStatus.WAITING_SELECTION,
            CompletionIntentStatus.NEEDS_ACTION,
            CompletionIntentStatus.SUCCEEDED,
            CompletionIntentStatus.CANCELLED,
        }
    ),
    CompletionIntentStatus.WAITING_SELECTION: frozenset(
        {
            CompletionIntentStatus.QUEUED,
            CompletionIntentStatus.NEEDS_ACTION,
            CompletionIntentStatus.SUCCEEDED,
            CompletionIntentStatus.CANCELLED,
        }
    ),
    CompletionIntentStatus.NEEDS_ACTION: frozenset(
        {
            CompletionIntentStatus.QUEUED,
            CompletionIntentStatus.CANCELLED,
        }
    ),
    CompletionIntentStatus.SUCCEEDED: frozenset(),
    CompletionIntentStatus.CANCELLED: frozenset(),
}


def transition_completion(
    current: CompletionIntentStatus, target: CompletionIntentStatus
) -> CompletionIntentStatus:
    if current == target:
        return current
    if target not in _TRANSITIONS[current]:
        raise InvalidStateTransition(
            f"illegal completion transition: {current.value} -> {target.value}"
        )
    return target
