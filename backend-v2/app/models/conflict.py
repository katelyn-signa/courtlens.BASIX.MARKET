from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, enum_column
from app.models.enums import ConflictType, ResolutionStatus, Severity
from app.utils.identifiers import CONFLICT, new_id
from app.utils.time import utcnow


class Conflict(Base):
    """Conflict / evidence-gap finding stored from Person 2 output."""

    __tablename__ = "conflicts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(CONFLICT))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
                                                 nullable=False, index=True)
    conflict_type: Mapped[ConflictType] = mapped_column(enum_column(ConflictType, "conflict_type"),
                                                        nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Optional[Severity]] = mapped_column(enum_column(Severity, "severity"))
    related_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    related_document_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    conflicting_values: Mapped[Optional[list[Any]]] = mapped_column(JSON)
    missing_information: Mapped[Optional[str]] = mapped_column(Text)
    resolution_status: Mapped[ResolutionStatus] = mapped_column(
        enum_column(ResolutionStatus, "resolution_status"),
        default=ResolutionStatus.UNRESOLVED, nullable=False, index=True)
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow,
                                                  nullable=False)
    agent_name: Mapped[Optional[str]] = mapped_column(String(100))
    agent_version: Mapped[Optional[str]] = mapped_column(String(50))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
