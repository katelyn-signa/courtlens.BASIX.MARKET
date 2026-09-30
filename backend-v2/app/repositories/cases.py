from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.enums import CaseStatus
from app.repositories.base import PageResult, paginate


class CaseRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, case: Case) -> Case:
        self.session.add(case)
        self.session.flush()
        return case

    def get(self, case_id: str) -> Optional[Case]:
        return self.session.get(Case, case_id)

    def get_by_external_reference(self, ref: str) -> Optional[Case]:
        return self.session.scalar(select(Case).where(Case.external_reference == ref))

    def list(self, *, limit: int, offset: int, status: Optional[CaseStatus] = None,
             court_name: Optional[str] = None, fir_number: Optional[str] = None,
             search: Optional[str] = None) -> PageResult[Case]:
        stmt = select(Case)
        if status:
            stmt = stmt.where(Case.status == status)
        if court_name:
            stmt = stmt.where(Case.court_name == court_name)
        if fir_number:
            stmt = stmt.where(Case.fir_number == fir_number)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(Case.title.ilike(like), Case.external_reference.ilike(like),
                                  Case.fir_number.ilike(like)))
        stmt = stmt.order_by(Case.created_at.desc(), Case.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)
