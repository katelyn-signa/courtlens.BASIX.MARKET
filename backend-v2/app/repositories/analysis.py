from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.analysis_run import AnalysisRun, AnalysisStage
from app.models.conflict import Conflict
from app.models.enums import (ConflictType, ReviewSignal, ResolutionStatus, RunStatus)
from app.models.evidence import Evidence
from app.models.rule_result import RuleResult
from app.repositories.base import PageResult, paginate

ACTIVE_STATUSES = (RunStatus.PENDING, RunStatus.RUNNING)


class AnalysisRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---- runs / stages ----
    def add_run(self, run: AnalysisRun) -> AnalysisRun:
        self.session.add(run)
        self.session.flush()
        return run

    def add_stage(self, stage: AnalysisStage) -> AnalysisStage:
        self.session.add(stage)
        self.session.flush()
        return stage

    def get_run(self, run_id: str) -> Optional[AnalysisRun]:
        return self.session.get(AnalysisRun, run_id)

    def list_runs(self, case_id: str, *, limit: int, offset: int,
                  status: Optional[RunStatus] = None) -> PageResult[AnalysisRun]:
        stmt = select(AnalysisRun).where(AnalysisRun.case_id == case_id)
        if status:
            stmt = stmt.where(AnalysisRun.status == status)
        stmt = stmt.order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def find_by_idempotency_key(self, case_id: str, key: str) -> Optional[AnalysisRun]:
        return self.session.scalar(select(AnalysisRun).where(
            AnalysisRun.case_id == case_id, AnalysisRun.idempotency_key == key))

    def active_run(self, case_id: str) -> Optional[AnalysisRun]:
        return self.session.scalar(select(AnalysisRun).where(
            AnalysisRun.case_id == case_id, AnalysisRun.status.in_(ACTIVE_STATUSES)).limit(1))

    def completed_with_fingerprint(self, case_id: str, fingerprint: str) -> Optional[AnalysisRun]:
        return self.session.scalar(select(AnalysisRun).where(
            AnalysisRun.case_id == case_id, AnalysisRun.input_fingerprint == fingerprint,
            AnalysisRun.status == RunStatus.COMPLETED)
            .order_by(AnalysisRun.created_at.desc()).limit(1))

    def child_of(self, run_id: str) -> Optional[AnalysisRun]:
        return self.session.scalar(select(AnalysisRun).where(AnalysisRun.parent_run_id == run_id)
                                   .limit(1))

    def mark_stale(self, case_id: str) -> list[str]:
        """Flag finished runs as stale (a newer document exists). Returns affected run IDs."""
        ids = list(self.session.scalars(select(AnalysisRun.id).where(
            AnalysisRun.case_id == case_id, AnalysisRun.is_stale.is_(False),
            AnalysisRun.status.in_((RunStatus.COMPLETED, RunStatus.PARTIALLY_COMPLETED)))))
        if ids:
            self.session.execute(update(AnalysisRun).where(AnalysisRun.id.in_(ids))
                                 .values(is_stale=True))
        return ids

    # ---- evidence ----
    def add_evidence(self, items: Sequence[Evidence]) -> None:
        self.session.add_all(items)
        self.session.flush()

    def evidence_for_documents(self, document_ids: Sequence[str]) -> list[Evidence]:
        """Current evidence: for each document only the newest extraction run is used."""
        if not document_ids:
            return []
        rows = self.session.scalars(select(Evidence).where(Evidence.document_id.in_(document_ids))
                                    .order_by(Evidence.extracted_at, Evidence.id)).all()
        newest_run: dict[str, Optional[str]] = {}
        for row in rows:
            newest_run[row.document_id] = row.extraction_run_id
        return [r for r in rows if r.extraction_run_id == newest_run[r.document_id]]

    def list_evidence(self, case_id: str, *, limit: int, offset: int,
                      document_id: Optional[str] = None, fact_type: Optional[str] = None,
                      extraction_run_id: Optional[str] = None) -> PageResult[Evidence]:
        stmt = select(Evidence).where(Evidence.case_id == case_id)
        if document_id:
            stmt = stmt.where(Evidence.document_id == document_id)
        if fact_type:
            stmt = stmt.where(Evidence.fact_type == fact_type)
        if extraction_run_id:
            stmt = stmt.where(Evidence.extraction_run_id == extraction_run_id)
        stmt = stmt.order_by(Evidence.extracted_at.desc(), Evidence.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)

    def existing_evidence_ids(self, case_id: str, ids: Sequence[str]) -> set[str]:
        if not ids:
            return set()
        return set(self.session.scalars(select(Evidence.id).where(
            Evidence.case_id == case_id, Evidence.id.in_(list(ids)))))

    # ---- conflicts ----
    def add_conflicts(self, items: Sequence[Conflict]) -> None:
        self.session.add_all(items)
        self.session.flush()

    def conflicts_for_run(self, run_id: str) -> list[Conflict]:
        return list(self.session.scalars(select(Conflict).where(Conflict.analysis_run_id == run_id)
                                         .order_by(Conflict.created_at, Conflict.id)))

    def list_conflicts(self, case_id: str, *, limit: int, offset: int,
                       analysis_run_id: Optional[str] = None,
                       conflict_type: Optional[ConflictType] = None,
                       resolution_status: Optional[ResolutionStatus] = None
                       ) -> PageResult[Conflict]:
        stmt = select(Conflict).where(Conflict.case_id == case_id)
        if analysis_run_id:
            stmt = stmt.where(Conflict.analysis_run_id == analysis_run_id)
        if conflict_type:
            stmt = stmt.where(Conflict.conflict_type == conflict_type)
        if resolution_status:
            stmt = stmt.where(Conflict.resolution_status == resolution_status)
        stmt = stmt.order_by(Conflict.created_at.desc(), Conflict.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)

    # ---- rule results ----
    def add_rule_results(self, items: Sequence[RuleResult]) -> None:
        self.session.add_all(items)
        self.session.flush()

    def rule_results_for_run(self, run_id: str) -> list[RuleResult]:
        return list(self.session.scalars(select(RuleResult).where(
            RuleResult.analysis_run_id == run_id).order_by(RuleResult.evaluated_at, RuleResult.id)))

    def list_rule_results(self, case_id: str, *, limit: int, offset: int,
                          analysis_run_id: Optional[str] = None, rule_id: Optional[str] = None,
                          review_signal: Optional[ReviewSignal] = None) -> PageResult[RuleResult]:
        stmt = select(RuleResult).where(RuleResult.case_id == case_id)
        if analysis_run_id:
            stmt = stmt.where(RuleResult.analysis_run_id == analysis_run_id)
        if rule_id:
            stmt = stmt.where(RuleResult.rule_id == rule_id)
        if review_signal:
            stmt = stmt.where(RuleResult.review_signal == review_signal)
        stmt = stmt.order_by(RuleResult.evaluated_at.desc(), RuleResult.id.desc())
        return paginate(self.session, stmt, limit=limit, offset=offset)
