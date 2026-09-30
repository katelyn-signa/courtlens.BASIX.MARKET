"""Read-only audit endpoints. There is deliberately no POST/PUT/PATCH/DELETE here."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import AnalysisServiceDep, CaseId, CaseServiceDep, PageDep, RunId, SessionDep
from app.core.security import AUDIT_READ, Actor, require_permission
from app.repositories.audit import AuditRepository
from app.schemas.audit import AuditEventRead
from app.schemas.common import Page, page_of

router = APIRouter(tags=["audit"])


@router.get("/cases/{case_id}/audit-events", response_model=Page[AuditEventRead],
            summary="Audit trail of a case (oldest first unless newest_first=true)")
def case_audit(case_id: CaseId, cases: CaseServiceDep, session: SessionDep, page: PageDep,
               event_type: Optional[str] = Query(None, max_length=60),
               actor: Optional[str] = Query(None, max_length=100),
               since: Optional[datetime] = None, until: Optional[datetime] = None,
               newest_first: bool = False, analysis_run_id: Optional[str] = None,
               _actor: Actor = Depends(require_permission(AUDIT_READ))):
    cases.get_case(case_id)
    return page_of(AuditRepository(session).list(
        case_id=case_id, limit=page.limit, offset=page.offset, event_type=event_type, actor=actor,
        since=since, until=until, newest_first=newest_first, analysis_run_id=analysis_run_id),
        AuditEventRead)


@router.get("/analysis-runs/{run_id}/audit-events", response_model=Page[AuditEventRead],
            summary="Audit trail of one analysis run")
def run_audit(run_id: RunId, analysis: AnalysisServiceDep, session: SessionDep, page: PageDep,
              event_type: Optional[str] = Query(None, max_length=60),
              since: Optional[datetime] = None, until: Optional[datetime] = None,
              newest_first: bool = False,
              _actor: Actor = Depends(require_permission(AUDIT_READ))):
    analysis.get_run(run_id)
    return page_of(AuditRepository(session).list(
        analysis_run_id=run_id, limit=page.limit, offset=page.offset, event_type=event_type,
        since=since, until=until, newest_first=newest_first), AuditEventRead)
