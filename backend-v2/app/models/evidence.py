from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, enum_column
from app.models.enums import VerificationStatus
from app.utils.identifiers import EVIDENCE, new_id
from app.utils.time import utcnow


class Evidence(Base):
    """An extracted fact plus its provenance. Written only from validated Person 1 output."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
                        name="confidence_range"),
        CheckConstraint("source_page IS NULL OR source_page >= 1", name="page_positive"),
        CheckConstraint(
            "(char_start IS NULL AND char_end IS NULL) OR "
            "(char_start IS NOT NULL AND char_end IS NOT NULL AND char_start >= 0 "
            "AND char_end >= char_start)", name="offsets_valid"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(EVIDENCE))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"),
                                             nullable=False, index=True)
    fact_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    fact_value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    entity_ref: Mapped[Optional[str]] = mapped_column(String(200))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    source_page: Mapped[Optional[int]] = mapped_column(Integer)
    quote: Mapped[Optional[str]] = mapped_column(Text)
    char_start: Mapped[Optional[int]] = mapped_column(Integer)
    char_end: Mapped[Optional[int]] = mapped_column(Integer)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_column(VerificationStatus, "verification_status"),
        default=VerificationStatus.UNVERIFIED, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    extraction_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"), index=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    agent_name: Mapped[Optional[str]] = mapped_column(String(100))
    agent_version: Mapped[Optional[str]] = mapped_column(String(50))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    document = relationship("Document", back_populates="evidence_items")
