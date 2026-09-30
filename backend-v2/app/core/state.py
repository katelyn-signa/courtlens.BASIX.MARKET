"""Explicit, validated state machines."""

from typing import Mapping

from app.core.exceptions import InvalidStateTransitionError
from app.models.enums import CaseStatus, ReviewStatus, RunStatus

CASE_TRANSITIONS: Mapping[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset({CaseStatus.UNDER_REVIEW, CaseStatus.CLOSED, CaseStatus.ARCHIVED}),
    CaseStatus.UNDER_REVIEW: frozenset({CaseStatus.OPEN, CaseStatus.CLOSED}),
    CaseStatus.CLOSED: frozenset({CaseStatus.OPEN, CaseStatus.ARCHIVED}),
    CaseStatus.ARCHIVED: frozenset(),
}

RUN_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset({
        RunStatus.COMPLETED, RunStatus.PARTIALLY_COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED,
    }),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.PARTIALLY_COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}

REVIEW_TRANSITIONS: Mapping[ReviewStatus, frozenset[ReviewStatus]] = {
    ReviewStatus.PENDING_REVIEW: frozenset({
        ReviewStatus.IN_REVIEW, ReviewStatus.ADDITIONAL_INFORMATION_REQUESTED,
    }),
    ReviewStatus.IN_REVIEW: frozenset({
        ReviewStatus.ADDITIONAL_INFORMATION_REQUESTED, ReviewStatus.REVIEW_COMPLETED,
    }),
    ReviewStatus.ADDITIONAL_INFORMATION_REQUESTED: frozenset({
        ReviewStatus.IN_REVIEW, ReviewStatus.REVIEW_COMPLETED,
    }),
    ReviewStatus.REVIEW_COMPLETED: frozenset(),
}


def ensure_transition(current, new, allowed: Mapping, label: str, *, allow_same: bool = True) -> None:
    """Raise ``InvalidStateTransitionError`` unless ``current -> new`` is permitted."""
    if current == new and allow_same:
        return
    if new not in allowed.get(current, frozenset()):
        raise InvalidStateTransitionError(
            f"{label}: transition {current.value} -> {new.value} is not allowed.",
            details={"from": current.value, "to": new.value,
                     "allowed": sorted(s.value for s in allowed.get(current, frozenset()))},
        )
