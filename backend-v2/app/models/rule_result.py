from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, enum_column
from app.models.enums import ReviewSignal, RuleEvaluationStatus
from app.utils.identifiers import RULE_RESULT, new_id
from app.utils.time import utcnow


class RuleResult(Base):
    """A rule-evaluation / reasoning record from Person 3. NOT a legal decision."""

    __tablename__ = "rule_results"
    __table_args__ = (
        UniqueConstraint("analysis_run_id", "rule_id", "rule_version",
                         name="uq_rule_results_run_rule_version"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True,
                                    default=lambda: new_id(RULE_RESULT))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
                                                 nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    rule_version: Mapped[str] = mapped_column(String(50), nullable=False)
    evaluation_status: Mapped[RuleEvaluationStatus] = mapped_column(
        enum_column(RuleEvaluationStatus, "evaluation_status"), nullable=False)
    input_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    review_signal: Mapped[Optional[ReviewSignal]] = mapped_column(
        enum_column(ReviewSignal, "review_signal"))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    missing_prerequisites: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    output_schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_name: Mapped[Optional[str]] = mapped_column(String(100))
    agent_version: Mapped[Optional[str]] = mapped_column(String(50))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
