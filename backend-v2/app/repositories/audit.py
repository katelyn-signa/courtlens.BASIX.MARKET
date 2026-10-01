from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.repositories.base import PageResult, paginate


class AuditRepository:
    """Read + append only. There is intentionally no update or delete method."""

    def __init__(self, session: Session):
        self.session = session

    def add(self, event: AuditEvent) -> AuditEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def list(self, *, limit: int, offset: int, case_id: Optional[str] = None,
             analysis_run_id: Optional[str] = None, event_type: Optional[str] = None,
             actor: Optional[str] = None, since: Optional[datetime] = None,
             until: Optional[datetime] = None, newest_first: bool = False,
             event_types: Optional[list[str]] = None
             ) -> PageResult[AuditEvent]:
        stmt = select(AuditEvent)
        if case_id:
            stmt = stmt.where(AuditEvent.case_id == case_id)
        if analysis_run_id:
            stmt = stmt.where(AuditEvent.analysis_run_id == analysis_run_id)
        if event_type:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if event_types:
            stmt = stmt.where(AuditEvent.event_type.in_(event_types))
        if actor:
            stmt = stmt.where(AuditEvent.actor == actor)
        if since:
            stmt = stmt.where(AuditEvent.occurred_at >= since)
        if until:
            stmt = stmt.where(AuditEvent.occurred_at <= until)
        order = (AuditEvent.occurred_at.desc(), AuditEvent.id.desc()) if newest_first else \
            (AuditEvent.occurred_at.asc(), AuditEvent.id.asc())
        return paginate(self.session, stmt.order_by(*order), limit=limit, offset=offset)
