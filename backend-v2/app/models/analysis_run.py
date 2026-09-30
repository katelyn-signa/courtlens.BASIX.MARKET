from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime, enum_column
from app.models.enums import RunStatus, StageStatus, TriggerType
from app.utils.identifiers import RUN, STAGE, new_id
from app.utils.time import utcnow


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint("case_id", "idempotency_key", name="uq_analysis_runs_case_idempotency"),
        CheckConstraint("attempt_number >= 1", name="attempt_positive"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(RUN))
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="RESTRICT"),
                                         nullable=False, index=True)
    trigger_type: Mapped[TriggerType] = mapped_column(enum_column(TriggerType, "trigger_type"),
                                                      nullable=False)
    status: Mapped[RunStatus] = mapped_column(enum_column(RunStatus, "status"),
                                              default=RunStatus.PENDING, nullable=False, index=True)
    current_stage: Mapped[Optional[str]] = mapped_column(String(60))
    requested_modules: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    error_summary: Mapped[Optional[str]] = mapped_column(Text)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    parent_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # [{"document_id", "version", "filename", "checksum_sha256"}] pinned at request time.
    input_documents: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(40), nullable=False)
    agent_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_refs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(120))
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))

    case = relationship("Case", back_populates="analysis_runs")
    stages = relationship("AnalysisStage", back_populates="run", order_by="AnalysisStage.sequence",
                          foreign_keys="AnalysisStage.run_id", passive_deletes="all")


class AnalysisStage(Base):
    """One pipeline stage of one run (persisted so status survives after the response)."""

    __tablename__ = "analysis_stages"
    __table_args__ = (
        UniqueConstraint("run_id", "stage_name", name="uq_analysis_stages_run_stage"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id(STAGE))
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="RESTRICT"),
                                        nullable=False, index=True)
    stage_name: Mapped[str] = mapped_column(String(60), nullable=False)
    agent_key: Mapped[str] = mapped_column(String(60), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[StageStatus] = mapped_column(enum_column(StageStatus, "status"),
                                                default=StageStatus.PENDING, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    error_code: Mapped[Optional[str]] = mapped_column(String(60))
    error_summary: Mapped[Optional[str]] = mapped_column(Text)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    agent_name: Mapped[Optional[str]] = mapped_column(String(100))
    agent_version: Mapped[Optional[str]] = mapped_column(String(50))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Run that actually produced this stage's stored output (differs from run_id when carried over).
    output_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="RESTRICT"))
    carried_over: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    run = relationship("AnalysisRun", back_populates="stages", foreign_keys=[run_id])
