"""Read-only retrieval of stored agent outputs (case memory). No analysis logic lives here."""

from typing import Optional

from fastapi import APIRouter, Depends

from app.api.deps import CaseId, CaseServiceDep, PageDep, SessionDep
from app.core.security import ANALYSIS_READ, Actor, require_permission
from app.models.enums import ConflictType, ResolutionStatus, ReviewSignal
from app.repositories.analysis import AnalysisRepository
from app.schemas.common import Page, page_of
from app.schemas.conflict import ConflictRead, RuleResultRead
from app.schemas.evidence import EvidenceRead
from app.utils.identifiers import DOCUMENT, RUN, id_pattern
import re

router = APIRouter(prefix="/cases/{case_id}", tags=["findings"])


def _check(value: Optional[str], prefix: str, label: str) -> Optional[str]:
    if value is not None and not re.match(id_pattern(prefix), value):
        from app.core.exceptions import InvalidInputError
        raise InvalidInputError(f"Invalid {label} format.")
    return value


@router.get("/evidence", response_model=Page[EvidenceRead],
            summary="Stored evidence with provenance")
def list_evidence(case_id: CaseId, cases: CaseServiceDep, session: SessionDep, page: PageDep,
                  document_id: Optional[str] = None, fact_type: Optional[str] = None,
                  extraction_run_id: Optional[str] = None,
                  _actor: Actor = Depends(require_permission(ANALYSIS_READ))):
    cases.get_case(case_id)
    result = AnalysisRepository(session).list_evidence(
        case_id, limit=page.limit, offset=page.offset,
        document_id=_check(document_id, DOCUMENT, "document_id"), fact_type=fact_type,
        extraction_run_id=_check(extraction_run_id, RUN, "extraction_run_id"))
    return page_of(result, EvidenceRead)


@router.get("/conflicts", response_model=Page[ConflictRead],
            summary="Stored conflict and evidence-gap findings")
def list_conflicts(case_id: CaseId, cases: CaseServiceDep, session: SessionDep, page: PageDep,
                   analysis_run_id: Optional[str] = None,
                   conflict_type: Optional[ConflictType] = None,
                   resolution_status: Optional[ResolutionStatus] = None,
                   _actor: Actor = Depends(require_permission(ANALYSIS_READ))):
    cases.get_case(case_id)
    result = AnalysisRepository(session).list_conflicts(
        case_id, limit=page.limit, offset=page.offset,
        analysis_run_id=_check(analysis_run_id, RUN, "analysis_run_id"),
        conflict_type=conflict_type, resolution_status=resolution_status)
    return page_of(result, ConflictRead)


@router.get("/rule-results", response_model=Page[RuleResultRead],
            summary="Stored rule-evaluation / reasoning records (not legal decisions)")
def list_rule_results(case_id: CaseId, cases: CaseServiceDep, session: SessionDep, page: PageDep,
                      analysis_run_id: Optional[str] = None, rule_id: Optional[str] = None,
                      review_signal: Optional[ReviewSignal] = None,
                      _actor: Actor = Depends(require_permission(ANALYSIS_READ))):
    cases.get_case(case_id)
    result = AnalysisRepository(session).list_rule_results(
        case_id, limit=page.limit, offset=page.offset,
        analysis_run_id=_check(analysis_run_id, RUN, "analysis_run_id"), rule_id=rule_id,
        review_signal=review_signal)
    return page_of(result, RuleResultRead)
