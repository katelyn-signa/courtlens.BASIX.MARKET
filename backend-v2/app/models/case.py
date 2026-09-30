from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, enum_column
from app.models.enums import CaseStatus
from app.utils.identifiers import CASE, new_id
from app.utils.time import utcnow


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(CASE))
    external_reference: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    fir_number: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    police_station: Mapped[Optional[str]] = mapped_column(String(200))
    court_name: Mapped[Optional[str]] = mapped_column(String(200))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    jurisdiction: Mapped[Optional[str]] = mapped_column(String(200))
    statutory_sections: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[CaseStatus] = mapped_column(
        enum_column(CaseStatus, "status"), default=CaseStatus.OPEN, nullable=False, index=True)
    # True when documents were registered after the latest analysis (refresh needed).
    analysis_needs_refresh: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    case_metadata: Mapped[dict[str, Any]] = mapped_column("metadata_json", JSON, default=dict,
                                                           nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow,
                                                  nullable=False)

    documents = relationship("Document", back_populates="case", passive_deletes="all",
                             order_by="Document.uploaded_at")
    analysis_runs = relationship("AnalysisRun", back_populates="case", passive_deletes="all",
                                 order_by="AnalysisRun.created_at")
    reviews = relationship("Review", back_populates="case", passive_deletes="all",
                           order_by="Review.created_at")
