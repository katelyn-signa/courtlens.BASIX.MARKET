from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import CaseNotFoundError, DuplicateRequestError
from app.core.state import CASE_TRANSITIONS, ensure_transition
from app.models.audit_event import AuditEvent
from app.models.case import Case
from app.models.enums import AuditEventType, CaseStatus
from app.repositories.analysis import AnalysisRepository
from app.repositories.audit import AuditRepository
from app.repositories.cases import CaseRepository
from app.repositories.documents import DocumentRepository
from app.repositories.reviews import ReviewRepository
from app.schemas.case import CaseCreate, CaseUpdate
from app.services.audit_service import AuditService


class CaseService:
    def __init__(self, session: Session):
        self.session = session
        self.cases = CaseRepository(session)
        self.audit = AuditService(session)

    def get_case(self, case_id: str) -> Case:
        case = self.cases.get(case_id)
        if case is None:
            raise CaseNotFoundError()
        return case

    def create_case(self, data: CaseCreate, actor: str) -> Case:
        if data.external_reference and self.cases.get_by_external_reference(data.external_reference):
            raise DuplicateRequestError("A case with this external_reference already exists.",
                                        code="DUPLICATE_CASE_REFERENCE")
        case = Case(
            external_reference=data.external_reference, fir_number=data.fir_number,
            police_station=data.police_station, court_name=data.court_name, title=data.title,
            jurisdiction=data.jurisdiction,
            statutory_sections=[s.model_dump() for s in data.statutory_sections],
            case_metadata=data.metadata, created_by=actor)
        self.cases.add(case)
        self.audit.record(AuditEventType.CASE_CREATED, case_id=case.id, actor=actor,
                          resource_type="case", resource_id=case.id)
        self.session.commit()
        return case

    def update_case(self, case_id: str, data: CaseUpdate, actor: str) -> Case:
        case = self.get_case(case_id)
        changes = data.model_dump(exclude_unset=True)
        changed: list[str] = []
        if "external_reference" in changes and changes["external_reference"] != case.external_reference:
            ref = changes["external_reference"]
            other = self.cases.get_by_external_reference(ref) if ref else None
            if other and other.id != case.id:
                raise DuplicateRequestError("A case with this external_reference already exists.",
                                            code="DUPLICATE_CASE_REFERENCE")
        if "status" in changes:
            ensure_transition(case.status, changes["status"], CASE_TRANSITIONS, "Case status")
        previous_values: dict[str, object] = {}
        new_values: dict[str, object] = {}
        for field, value in changes.items():
            attr = "case_metadata" if field == "metadata" else field
            if field == "statutory_sections":
                value = [s if isinstance(s, dict) else s.model_dump() for s in value]
            current = getattr(case, attr)
            if current != value:
                previous_values[field] = current
                new_values[field] = value
                setattr(case, attr, value)
                changed.append(field)
        if changed:
            self.audit.record(AuditEventType.CASE_UPDATED, case_id=case.id, actor=actor,
                              resource_type="case", resource_id=case.id,
                              metadata={"changed_fields": sorted(changed),
                                        "previous_value": previous_values,
                                        "new_value": new_values})
        self.session.commit()
        return case

    def history(self, case_id: str, limit: int) -> dict:
        case = self.get_case(case_id)
        docs = DocumentRepository(self.session).list_for_case(case_id, limit=limit, offset=0)
        runs = AnalysisRepository(self.session).list_runs(case_id, limit=limit, offset=0)
        reviews = ReviewRepository(self.session).list_for_case(case_id, limit=limit, offset=0)
        audit = AuditRepository(self.session).list(case_id=case_id, limit=limit, offset=0,
                                                   newest_first=True)
        return {"case": case, "documents": docs, "analysis_runs": runs, "reviews": reviews,
                "audit_events": audit}
