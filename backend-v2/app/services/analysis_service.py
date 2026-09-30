"""Analysis-run requests, idempotency, retry, and read models. Execution is delegated to the
Orchestrator so it can later be moved to a background worker without API changes."""

import hashlib
import json
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import (AnalysisRunNotFoundError, CaseNotFoundError, DocumentNotFoundError,
                                 DuplicateRequestError, InvalidInputError,
                                 InvalidStateTransitionError)
from app.models.analysis_run import AnalysisRun, AnalysisStage
from app.models.case import Case
from app.models.enums import (AuditEventType, ReviewSignal, RunStatus, StageStatus, TriggerType)
from app.orchestration.orchestrator import Orchestrator
from app.orchestration.pipeline import DEFAULT_PIPELINE, PipelineDefinition
from app.orchestration.registry import AgentRegistry
from app.repositories.analysis import AnalysisRepository
from app.repositories.cases import CaseRepository
from app.repositories.documents import DocumentRepository
from app.schemas.analysis import AnalysisRunCreate, AnalysisRunDetail, RunSummary, StageRead
from app.services.audit_service import AuditService
from app.services.storage import LocalFileStorage

_RETRYABLE = (RunStatus.FAILED, RunStatus.PARTIALLY_COMPLETED)


def _fingerprint(docs: list[dict], modules: list[str], pipeline_version: str, options: dict) -> str:
    payload = {"docs": sorted((d["document_id"], d["checksum_sha256"]) for d in docs),
               "modules": sorted(modules), "pipeline": pipeline_version,
               "reprocess": bool(options.get("reprocess_documents")),
               "rule_config": options.get("rule_config") or {},
               "agent_config": options.get("agent_config") or {}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


class AnalysisService:
    def __init__(self, session: Session, settings: Settings, registry: AgentRegistry,
                 storage: LocalFileStorage, pipeline: PipelineDefinition = DEFAULT_PIPELINE):
        self.session = session
        self.settings = settings
        self.registry = registry
        self.storage = storage
        self.pipeline = pipeline
        self.cases = CaseRepository(session)
        self.docs = DocumentRepository(session)
        self.runs = AnalysisRepository(session)
        self.audit = AuditService(session)

    # ---- lookups ----
    def get_run(self, run_id: str) -> AnalysisRun:
        run = self.runs.get_run(run_id)
        if run is None:
            raise AnalysisRunNotFoundError()
        return run

    def _case(self, case_id: str) -> Case:
        case = self.cases.get(case_id)
        if case is None:
            raise CaseNotFoundError()
        return case

    # ---- request a run ----
    def request_run(self, case_id: str, data: AnalysisRunCreate, actor: str,
                    trigger: TriggerType = TriggerType.MANUAL) -> tuple[AnalysisRun, bool]:
        """Create (and synchronously execute) a run. Returns (run, reused_existing)."""
        case = self._case(case_id)
        if data.idempotency_key:
            existing = self.runs.find_by_idempotency_key(case_id, data.idempotency_key)
            if existing:
                return existing, True

        if data.document_ids:
            wanted = list(dict.fromkeys(data.document_ids))
            found = {d.id: d for d in self.docs.get_many(case_id, wanted)}
            missing = [i for i in wanted if i not in found]
            if missing:
                raise DocumentNotFoundError("Some documents were not found in this case.",
                                            details={"missing_document_ids": missing})
            documents = [found[i] for i in wanted]
        else:
            documents = self.docs.latest_versions_for_case(case_id)
        if not documents:
            raise InvalidInputError("The case has no documents to analyse.", code="NO_DOCUMENTS")

        stages = self.pipeline.resolve(data.requested_modules)
        modules = [s.name for s in stages]
        input_docs = [{"document_id": d.id, "version": d.version, "filename": d.filename,
                       "checksum_sha256": d.checksum_sha256} for d in documents]
        options = {k: v for k, v in {"reprocess_documents": data.reprocess_documents,
                                     "rule_config": data.rule_config,
                                     "agent_config": data.agent_config}.items() if v}
        fingerprint = _fingerprint(input_docs, modules, self.pipeline.version, options)

        active = self.runs.active_run(case_id)
        if active:
            raise DuplicateRequestError("An analysis run is already in progress for this case.",
                                        code="ANALYSIS_ALREADY_RUNNING",
                                        details={"run_id": active.id})
        if not data.force:
            done = self.runs.completed_with_fingerprint(case_id, fingerprint)
            if done:
                return done, True

        run = AnalysisRun(
            case_id=case_id, trigger_type=trigger, status=RunStatus.PENDING,
            requested_modules=modules, options=options, input_documents=input_docs,
            pipeline_version=self.pipeline.version, input_fingerprint=fingerprint,
            idempotency_key=data.idempotency_key, created_by=actor,
            diagnostics={"registered_agents": {k: v["status"] for k, v in
                                               self.registry.describe().items()}})
        try:
            self.runs.add_run(run)
            for seq, stage in enumerate(stages, start=1):
                self.runs.add_stage(AnalysisStage(
                    run_id=run.id, stage_name=stage.name, agent_key=stage.agent_key.value,
                    sequence=seq, required=stage.required))
            self.audit.record(AuditEventType.ANALYSIS_RUN_CREATED, case_id=case_id, actor=actor,
                              resource_type="analysis_run", resource_id=run.id,
                              analysis_run_id=run.id,
                              metadata={"trigger": trigger.value, "modules": modules,
                                        "document_ids": [d["document_id"] for d in input_docs]})
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise DuplicateRequestError("Duplicate analysis request.",
                                        code="DUPLICATE_ANALYSIS_REQUEST") from None
        return self._execute(run.id, actor), False

    # ---- retry ----
    def retry_run(self, run_id: str, actor: str) -> AnalysisRun:
        """Retry a FAILED / PARTIALLY_COMPLETED run as a NEW linked run (attempt N+1).

        Stages that already SUCCEEDED are carried over (their stored outputs are reused, not
        recomputed); the rest are executed again. History is never overwritten.
        """
        parent = self.get_run(run_id)
        if parent.status not in _RETRYABLE:
            raise InvalidStateTransitionError(
                f"Only FAILED or PARTIALLY_COMPLETED runs can be retried (run is {parent.status.value}).",
                code="RETRY_NOT_ALLOWED")
        if self.runs.child_of(parent.id):
            raise InvalidStateTransitionError("This run was already retried; retry the latest attempt.",
                                              code="RETRY_NOT_ALLOWED")
        if parent.attempt_number > self.settings.max_run_retries:
            raise InvalidStateTransitionError(
                f"Retry limit reached ({self.settings.max_run_retries}).", code="RETRY_LIMIT_REACHED")
        active = self.runs.active_run(parent.case_id)
        if active:
            raise DuplicateRequestError("An analysis run is already in progress for this case.",
                                        code="ANALYSIS_ALREADY_RUNNING", details={"run_id": active.id})
        run = AnalysisRun(
            case_id=parent.case_id, trigger_type=TriggerType.RETRY, status=RunStatus.PENDING,
            requested_modules=list(parent.requested_modules), options=dict(parent.options or {}),
            input_documents=list(parent.input_documents), pipeline_version=self.pipeline.version,
            input_fingerprint=parent.input_fingerprint, parent_run_id=parent.id,
            attempt_number=parent.attempt_number + 1, created_by=actor,
            diagnostics={"retry_of": parent.id})
        self.runs.add_run(run)
        parent_stages = {s.stage_name: s for s in parent.stages}
        for seq, name in enumerate(run.requested_modules, start=1):
            definition = self.pipeline.get(name)
            prior = parent_stages.get(name)
            carried = prior is not None and prior.status == StageStatus.SUCCEEDED
            self.runs.add_stage(AnalysisStage(
                run_id=run.id, stage_name=name, agent_key=definition.agent_key.value, sequence=seq,
                required=definition.required,
                status=StageStatus.SUCCEEDED if carried else StageStatus.PENDING,
                carried_over=carried,
                output_run_id=(prior.output_run_id or prior.run_id) if carried else None,
                output_summary=dict(prior.output_summary) if carried else {},
                agent_name=prior.agent_name if carried else None,
                agent_version=prior.agent_version if carried else None,
                is_simulated=prior.is_simulated if carried else False,
                started_at=prior.started_at if carried else None,
                completed_at=prior.completed_at if carried else None))
        self.audit.record(AuditEventType.ANALYSIS_RERUN_TRIGGERED, case_id=parent.case_id,
                          actor=actor, resource_type="analysis_run", resource_id=run.id,
                          analysis_run_id=run.id,
                          metadata={"parent_run_id": parent.id, "attempt": run.attempt_number})
        self.session.commit()
        return self._execute(run.id, actor)

    def _execute(self, run_id: str, actor: str) -> AnalysisRun:
        orchestrator = Orchestrator(self.session, self.registry, self.settings, self.storage,
                                    self.pipeline)
        run = orchestrator.execute_run(run_id, actor)
        if run.status in (RunStatus.COMPLETED, RunStatus.PARTIALLY_COMPLETED):
            case = self.cases.get(run.case_id)
            latest = {d["document_id"] for d in run.input_documents}
            current = {d.id for d in self.docs.latest_versions_for_case(run.case_id)}
            if case is not None and current <= latest:
                case.analysis_needs_refresh = False
                self.session.commit()
        return run

    # ---- read models ----
    def detail(self, run: AnalysisRun, *, reused: bool = False,
               message: Optional[str] = None) -> AnalysisRunDetail:
        stages = list(run.stages)
        summary = RunSummary()
        by_name = {s.stage_name: s for s in stages}
        ev = by_name.get("document_intelligence")
        summary.evidence_count = len(run.output_refs.get("evidence_ids", [])) if run.output_refs \
            else int((ev.output_summary or {}).get("evidence_count", 0)) if ev else 0
        cs, rs = by_name.get("conflict_detection"), by_name.get("reasoning")
        if cs and cs.output_run_id:
            summary.conflict_count = len(self.runs.conflicts_for_run(cs.output_run_id))
        if rs and rs.output_run_id:
            results = self.runs.rule_results_for_run(rs.output_run_id)
            summary.rule_result_count = len(results)
            summary.review_signals = sorted({r.review_signal for r in results if r.review_signal},
                                            key=lambda s: s.value)
        if run.status in (RunStatus.PENDING, RunStatus.RUNNING, RunStatus.FAILED,
                          RunStatus.PARTIALLY_COMPLETED, RunStatus.CANCELLED):
            summary.analysis_outcome = ReviewSignal.ANALYSIS_INCOMPLETE
        summary.simulated_output = any(s.is_simulated for s in stages)
        detail = AnalysisRunDetail.model_validate(run)
        detail.stages = [StageRead.model_validate(s) for s in stages]
        detail.summary = summary
        detail.reused_existing = reused
        detail.message = message
        return detail
