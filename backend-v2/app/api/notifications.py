"""Workflow notifications derived from the append-only audit trail.

The current backend has no user-notification persistence/read-state model, so this
endpoint exposes recent actionable workflow events as notification-style records.
It is intentionally read-only and uses the existing audit permission.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import PageDep, SessionDep
from app.core.security import AUDIT_READ, Actor, require_permission
from app.repositories.audit import AuditRepository
from app.schemas.audit import AuditEventRead
from app.schemas.common import Page, page_of

router = APIRouter(tags=["notifications"])

_NOTIFICATION_EVENTS = (
    "DOCUMENT_REGISTERED",
    "DOCUMENT_PROCESSING_FAILED",
    "CONFLICTS_STORED",
    "RULE_RESULTS_STORED",
    "ANALYSIS_RUN_COMPLETED",
    "ANALYSIS_RUN_PARTIALLY_COMPLETED",
    "ANALYSIS_RUN_FAILED",
    "ANALYSIS_RERUN_TRIGGERED",
    "ADDITIONAL_INFORMATION_REQUESTED",
    "REVIEW_CREATED",
    "REVIEW_UPDATED",
)


@router.get("/notifications", response_model=Page[AuditEventRead],
            summary="List recent workflow notifications derived from audit events")
def list_notifications(
    session: SessionDep,
    page: PageDep,
    case_id: Optional[str] = Query(None, max_length=40),
    _actor: Actor = Depends(require_permission(AUDIT_READ)),
):
    repo = AuditRepository(session)
    result = repo.list(
        case_id=case_id,
        limit=page.limit,
        offset=page.offset,
        newest_first=True,
        event_types=list(_NOTIFICATION_EVENTS),
    )
    return Page[AuditEventRead](
        items=[AuditEventRead.model_validate(event) for event in result.items],
        total=result.total,
        limit=page.limit,
        offset=page.offset,
    )
