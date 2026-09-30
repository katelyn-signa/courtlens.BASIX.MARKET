from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, ForeignKey, Index, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime
from app.utils.identifiers import AUDIT, new_id
from app.utils.time import utcnow


class AuditEvent(Base):
    """Append-only audit trail. ORM updates/deletes are rejected (see listeners below)."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_case_time", "case_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(AUDIT))
    case_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"),
                                                   index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    actor: Mapped[Optional[str]] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(60))
    resource_id: Mapped[Optional[str]] = mapped_column(String(60))
    analysis_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"), index=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column("metadata_json", JSON, default=dict,
                                                            nullable=False)
    correlation_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)


class AuditImmutableError(RuntimeError):
    """Raised when code attempts to modify or delete an audit event."""


@event.listens_for(AuditEvent, "before_update")
def _reject_update(mapper, connection, target):
    raise AuditImmutableError("Audit events are append-only and cannot be modified.")


@event.listens_for(AuditEvent, "before_delete")
def _reject_delete(mapper, connection, target):
    raise AuditImmutableError("Audit events are append-only and cannot be deleted.")
