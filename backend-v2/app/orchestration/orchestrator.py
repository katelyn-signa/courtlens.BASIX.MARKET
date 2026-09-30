"""Stateful orchestrator: runs a persisted analysis run stage by stage.

Policy (documented in README):
* Every state change is committed, so status/errors survive the HTTP response.
* Each stage's outputs are persisted atomically with its status; a later failure never
  removes earlier stage outputs.
* Run status: all stages SUCCEEDED -> COMPLETED; no stage produced output (SUCCEEDED/PARTIAL)
  -> FAILED; anything in between -> PARTIALLY_COMPLETED.
* Stage failures: NOT_CONFIGURED / NOT_IMPLEMENTED / FAILED (timeout, unavailable, invalid
  output, processing error) -> later dependent stages are SKIPPED.
"""

import contextvars
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import (
    AgentError, AgentInvalidOutputError, AgentProcessingError, AgentTimeoutError,
    AnalysisRunNotFoundError,
)
from app.core.logging import get_logger
from app.core.state import RUN_TRANSITIONS, ensure_transition
from app.models.analysis_run import AnalysisRun, AnalysisStage
from app.models.case import Case
from app.models.document import Document
from app.models.enums import AuditEventType, RunStatus, StageStatus
from app.orchestration.contracts import AgentResultStatus
from app.orchestration.handlers import (
    HANDLERS, StageContext, StageHandler, StageOutcome, safe_text,
)
from app.orchestration.pipeline import DEFAULT_PIPELINE, PipelineDefinition
from app.orchestration.registry import AgentRegistry
from app.repositories.analysis import AnalysisRepository
from app.services.audit_service import AuditService
from app.services.storage import LocalFileStorage
from app.utils.time import utcnow

log = get_logger("orchestrator")

_PRODUCED = (StageStatus.SUCCEEDED, StageStatus.PARTIAL)


class Orchestrator:
    def __init__(self, session: Session, registry: AgentRegistry, settings: Settings,
                 storage: LocalFileStorage, pipeline: PipelineDefinition = DEFAULT_PIPELINE):
        self.session = session
        self.registry = registry
        self.settings = settings
        self.storage = storage
        self.pipeline = pipeline
        self.repo = AnalysisRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ public

    def execute_run(self, run_id: str, actor: str = "system") -> AnalysisRun:
        run = self.repo.get_run(run_id)
        if run is None:
            raise AnalysisRunNotFoundError()
        ensure_transition(run.status, RunStatus.RUNNING, RUN_TRANSITIONS, "Analysis run",
                          allow_same=False)
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        self.audit.record(AuditEventType.ANALYSIS_RUN_STARTED, case_id=run.case_id, actor=actor,
                          resource_type="analysis_run", resource_id=run.id, analysis_run_id=run.id,
                          metadata={"attempt": run.attempt_number, "trigger": run.trigger_type.value})
        self.session.commit()
        try:
            self._execute_stages(run, actor)
            self._finalize(run, actor)
        except Exception as exc:  # noqa: BLE001 - last-resort guard, never leaks details
            self.session.rollback()
            log.error("Orchestrator internal error for %s: %s", run_id, type(exc).__name__)
            self._fail_internal(run_id, exc)
        self.session.refresh(run)
        return run

    # ------------------------------------------------------------------ internals

    def _execute_stages(self, run: AnalysisRun, actor: str) -> None:
        case = self.session.get(Case, run.case_id)
        pinned = [d["document_id"] for d in run.input_documents]
        docs_by_id = {d.id: d for d in self.session.query(Document).filter(Document.id.in_(pinned))}
        documents = [docs_by_id[i] for i in pinned if i in docs_by_id]
        ctx = StageContext(session=self.session, settings=self.settings, storage=self.storage,
                           run=run, case=case, documents=documents, actor=actor, repo=self.repo,
                           audit=self.audit)
        stages = list(run.stages)
        by_name = {s.stage_name: s for s in stages}
        for stage in stages:
            definition = self.pipeline.get(stage.stage_name)
            if stage.carried_over:
                ctx.output_run_ids[stage.stage_name] = stage.output_run_id or run.id
                continue
            unmet = [d for d in definition.depends_on
                     if d in by_name and by_name[d].status not in _PRODUCED]
            if unmet:
                self._finish_stage(ctx, stage, StageOutcome(
                    StageStatus.SKIPPED, {}, "DEPENDENCY_NOT_SATISFIED",
                    f"Skipped because {', '.join(unmet)} did not produce output."))
                continue
            self._run_stage(ctx, stage, HANDLERS[definition.agent_key], definition)

    def _run_stage(self, ctx: StageContext, stage: AnalysisStage, handler: StageHandler,
                   definition) -> None:
        run = ctx.run
        run.current_stage = stage.stage_name
        stage.status = StageStatus.RUNNING
        stage.started_at = utcnow()
        self.session.commit()

        attempts = {"n": 0}
        request = None
        output = None
        try:
            request = handler.build_request(ctx)
            if request is None:
                outcome = StageOutcome(StageStatus.SUCCEEDED, {"note": "Nothing required processing."})
            else:
                registration = self.registry.get(definition.agent_key)
                if registration is None:
                    outcome = StageOutcome(StageStatus.NOT_CONFIGURED, {}, "NOT_CONFIGURED",
                                           "No agent is registered for this stage.")
                else:
                    stage.agent_name = getattr(registration.agent, "name", None)
                    stage.agent_version = getattr(registration.agent, "version", None)
                    stage.is_simulated = registration.source == "demo"
                    handler.before_call(ctx, request)
                    self.session.commit()
                    raw = self._call_agent(getattr(registration.agent, definition.method),
                                           request, attempts)
                    output = self._coerce(handler, raw)
                    if output.status == AgentResultStatus.FAILED:
                        first = output.errors[0] if output.errors else None
                        raise AgentProcessingError(
                            first.message if first else "Agent reported failure.",
                            code=first.code if first else None)
                    handler.validate(ctx, request, output)
                    outcome = handler.persist(ctx, request, output)
        except NotImplementedError:
            self.session.rollback()
            outcome = StageOutcome(StageStatus.NOT_IMPLEMENTED, {}, "NOT_IMPLEMENTED",
                                   "The agent for this stage is a stub (not implemented).")
        except AgentError as exc:
            self.session.rollback()
            outcome = StageOutcome(StageStatus.FAILED, {}, exc.code, safe_text(exc.message))
        except SQLAlchemyError as exc:
            self.session.rollback()
            log.error("Persistence error in stage %s: %s", stage.stage_name, type(exc).__name__)
            outcome = StageOutcome(StageStatus.FAILED, {}, "PERSISTENCE_ERROR",
                                   "Stage output could not be stored; nothing was saved for it.")
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            log.error("Unexpected agent error in stage %s: %s", stage.stage_name, type(exc).__name__)
            outcome = StageOutcome(StageStatus.FAILED, {}, "AGENT_UNEXPECTED_ERROR",
                                   f"Unexpected error: {type(exc).__name__}")

        # after a rollback ORM state is refreshed from the last commit; re-apply run-time facts
        run = self.session.get(AnalysisRun, ctx.run.id)
        stage = self.session.get(AnalysisStage, stage.id)
        ctx.run = run
        stage.attempts = attempts["n"]
        if outcome.status not in _PRODUCED and request is not None:
            handler.on_failure(ctx, request, outcome)
        if output is not None and outcome.status in _PRODUCED:
            stage.agent_name, stage.agent_version = output.agent_name, output.agent_version
            stage.is_simulated = output.is_simulated
            stage.warnings = [{"code": w.code, "message": safe_text(w.message)}
                              for w in output.warnings]
        self._finish_stage(ctx, stage, outcome)

    def _finish_stage(self, ctx: StageContext, stage: AnalysisStage, outcome: StageOutcome) -> None:
        stage.status = outcome.status
        stage.completed_at = utcnow()
        stage.error_code = outcome.error_code
        stage.error_summary = outcome.error_summary
        stage.output_summary = outcome.summary
        if outcome.status in _PRODUCED:
            stage.output_run_id = ctx.run.id
            ctx.output_run_ids[stage.stage_name] = ctx.run.id
        ok = outcome.status in _PRODUCED
        self.audit.record(
            AuditEventType.ANALYSIS_STAGE_COMPLETED if ok else AuditEventType.ANALYSIS_STAGE_FAILED,
            case_id=ctx.run.case_id, actor="system", resource_type="analysis_stage",
            resource_id=stage.id, analysis_run_id=ctx.run.id,
            metadata={"stage": stage.stage_name, "status": outcome.status.value,
                      "error_code": outcome.error_code, "attempts": stage.attempts})
        log.info("Run %s stage %s -> %s", ctx.run.id, stage.stage_name, outcome.status.value)
        self.session.commit()

    def _finalize(self, run: AnalysisRun, actor: str) -> None:
        run = self.session.get(AnalysisRun, run.id)
        stages = list(run.stages)
        statuses = [s.status for s in stages]
        if all(s == StageStatus.SUCCEEDED for s in statuses):
            final = RunStatus.COMPLETED
        elif not any(s in _PRODUCED for s in statuses):
            final = RunStatus.FAILED
        else:
            final = RunStatus.PARTIALLY_COMPLETED
        ensure_transition(run.status, final, RUN_TRANSITIONS, "Analysis run", allow_same=False)
        problems = [f"{s.stage_name}: {s.status.value}" + (f" ({s.error_code})" if s.error_code else "")
                    for s in stages if s.status != StageStatus.SUCCEEDED]
        refs: dict[str, Any] = {"evidence_ids": [], "conflict_ids": [], "rule_result_ids": [],
                                "stages": {}}
        for s in stages:
            summ = s.output_summary or {}
            for key in ("evidence_ids", "conflict_ids", "rule_result_ids"):
                refs[key].extend(summ.get(key, []))
            refs["stages"][s.stage_name] = {"status": s.status.value,
                                            "output_run_id": s.output_run_id}
        run.status = final
        run.completed_at = utcnow()
        run.current_stage = None
        run.error_summary = "; ".join(problems) if problems else None
        run.output_refs = refs
        run.agent_versions = {s.stage_name: {"agent": s.agent_name, "version": s.agent_version,
                                             "simulated": s.is_simulated} for s in stages}
        run.diagnostics = {**(run.diagnostics or {}),
                           "stage_statuses": {s.stage_name: s.status.value for s in stages},
                           "stage_error_codes": {s.stage_name: s.error_code for s in stages
                                                 if s.error_code}}
        event = {RunStatus.COMPLETED: AuditEventType.ANALYSIS_RUN_COMPLETED,
                 RunStatus.PARTIALLY_COMPLETED: AuditEventType.ANALYSIS_RUN_PARTIALLY_COMPLETED,
                 RunStatus.FAILED: AuditEventType.ANALYSIS_RUN_FAILED}[final]
        self.audit.record(event, case_id=run.case_id, actor=actor, resource_type="analysis_run",
                          resource_id=run.id, analysis_run_id=run.id,
                          metadata={"status": final.value, "stages": run.diagnostics["stage_statuses"],
                                    "pipeline_version": run.pipeline_version})
        self.session.commit()
        log.info("Run %s finished: %s", run.id, final.value)

    def _fail_internal(self, run_id: str, exc: Exception) -> None:
        run = self.session.get(AnalysisRun, run_id)
        if run is None or run.status != RunStatus.RUNNING:
            return
        run.status = RunStatus.FAILED
        run.completed_at = utcnow()
        run.current_stage = None
        run.error_summary = f"INTERNAL_ERROR: {type(exc).__name__}"
        self.audit.record(AuditEventType.ANALYSIS_RUN_FAILED, case_id=run.case_id, actor="system",
                          resource_type="analysis_run", resource_id=run.id, analysis_run_id=run.id,
                          metadata={"error_code": "INTERNAL_ERROR"})
        self.session.commit()

    # ---- agent invocation ---------------------------------------------------------------

    def _call_agent(self, fn, request: BaseModel, attempts: dict[str, int]) -> Any:
        max_attempts = max(1, self.settings.agent_max_attempts)
        for attempt in range(1, max_attempts + 1):
            attempts["n"] = attempt
            try:
                return self._call_with_timeout(fn, request)
            except AgentError as exc:
                if exc.retryable and attempt < max_attempts:
                    log.warning("Retryable agent error %s (attempt %d/%d)", exc.code, attempt,
                                max_attempts)
                    time.sleep(self.settings.agent_retry_delay_seconds)
                    continue
                raise

    def _call_with_timeout(self, fn, request: BaseModel) -> Any:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="courtlens-agent")
        ctx = contextvars.copy_context()
        future = executor.submit(ctx.run, fn, request.model_copy(deep=True))
        try:
            return future.result(timeout=self.settings.agent_timeout_seconds)
        except FutureTimeout:
            raise AgentTimeoutError(
                f"Agent exceeded {self.settings.agent_timeout_seconds:g}s timeout.") from None
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _coerce(handler: StageHandler, raw: Any):
        """Always re-validate agent output (also when a model instance is returned)."""
        payload = raw.model_dump() if isinstance(raw, BaseModel) else raw
        if not isinstance(payload, dict):
            raise AgentInvalidOutputError("Agent returned no structured output.")
        try:
            return handler.output_model.model_validate(payload)
        except ValidationError as exc:
            problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}"
                        for e in exc.errors(include_input=False, include_context=False)[:5]]
            raise AgentInvalidOutputError(
                "Agent output failed validation (" + "; ".join(problems) + ").",
                details={"error_count": exc.error_count()}) from None
