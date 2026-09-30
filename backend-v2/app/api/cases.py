from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import CaseId, CaseServiceDep, PageDep
from app.core.security import CASES_READ, CASES_WRITE, Actor, require_permission
from app.models.enums import CaseStatus
from app.schemas.analysis import AnalysisRunRead
from app.schemas.audit import AuditEventRead
from app.schemas.case import CaseCreate, CaseRead, CaseUpdate
from app.schemas.common import Page, page_of
from app.schemas.document import DocumentRead
from app.schemas.review import ReviewRead

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseRead, status_code=201, summary="Create a case")
def create_case(body: CaseCreate, service: CaseServiceDep,
                actor: Actor = Depends(require_permission(CASES_WRITE))):
    return service.create_case(body, actor.id)


@router.get("", response_model=Page[CaseRead], summary="List cases")
def list_cases(service: CaseServiceDep, page: PageDep,
               status: Optional[CaseStatus] = None, court_name: Optional[str] = None,
               fir_number: Optional[str] = None,
               search: Optional[str] = Query(None, max_length=100),
               _actor: Actor = Depends(require_permission(CASES_READ))):
    result = service.cases.list(limit=page.limit, offset=page.offset, status=status,
                                court_name=court_name, fir_number=fir_number, search=search)
    return page_of(result, CaseRead)


@router.get("/{case_id}", response_model=CaseRead, summary="Get a case")
def get_case(case_id: CaseId, service: CaseServiceDep,
             _actor: Actor = Depends(require_permission(CASES_READ))):
    return service.get_case(case_id)


@router.patch("/{case_id}", response_model=CaseRead, summary="Update permitted case metadata")
def update_case(case_id: CaseId, body: CaseUpdate, service: CaseServiceDep,
                actor: Actor = Depends(require_permission(CASES_WRITE))):
    return service.update_case(case_id, body, actor.id)


@router.get("/{case_id}/history", summary="Case history: documents, runs, reviews, audit trail")
def case_history(case_id: CaseId, service: CaseServiceDep,
                 limit: int = Query(50, ge=1, le=200),
                 _actor: Actor = Depends(require_permission(CASES_READ))):
    h = service.history(case_id, limit)
    return {
        "case": CaseRead.model_validate(h["case"]),
        "documents": page_of(h["documents"], DocumentRead),
        "analysis_runs": page_of(h["analysis_runs"], AnalysisRunRead),
        "reviews": page_of(h["reviews"], ReviewRead),
        "audit_events": page_of(h["audit_events"], AuditEventRead),
    }
