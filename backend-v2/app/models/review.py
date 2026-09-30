from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, enum_column
from app.models.enums import ReviewStatus, WorkflowAction
from app.utils.identifiers import REVIEW, new_id
from app.utils.time import utcnow


class Review(Base):
    """Human review record. Kept separate from (and never edits) AI-generated results."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(REVIEW))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    analysis_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"), index=True)
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[ReviewStatus] = mapped_column(enum_column(ReviewStatus, "status"),
                                                 default=ReviewStatus.PENDING_REVIEW,
                                                 nullable=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    workflow_action: Mapped[WorkflowAction] = mapped_column(
        enum_column(WorkflowAction, "workflow_action"), default=WorkflowAction.NONE, nullable=False)
    # [{"type": "conflict"|"rule_result"|"evidence", "id": "..."}]
    reviewed_finding_refs: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    additional_evidence_requested: Mapped[bool] = mapped_column(Boolean, default=False,
                                                                 nullable=False)
    additional_information_request: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow,
                                                  nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))

    case = relationship("Case", back_populates="reviews")
