"""Per-stage handlers: build agent input, validate agent output, persist it.

Handlers own the *integration* work for a stage (never the agent's own logic).
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import AgentInvalidOutputError
from app.config import Settings
from app.models.analysis_run import AnalysisRun
from app.models.case import Case
from app.models.conflict import Conflict
from app.models.document import Document
from app.models.enums import (AuditEventType, DocumentProcessingStatus, StageStatus)
from app.models.evidence import Evidence
from app.models.rule_result import RuleResult
from app.orchestration.contracts import (
    AgentOutputBase, AgentResultStatus, CaseSnapshot, ConflictAgentInput, ConflictAgentOutput,
    ConflictRecord, DocumentRef, DocumentResultStatus, EvidenceAgentInput, EvidenceAgentOutput,
    EvidenceRecord, OcrAgentInput, OcrAgentOutput, ReasoningAgentInput, ReasoningAgentOutput,
    RuleConfig, SummaryAgentInput, SummaryAgentOutput, CONTRACT_VERSION,
)
from app.orchestration.registry import AgentKey
from app.repositories.analysis import AnalysisRepository
from app.services.audit_service import AuditService
from app.services.storage import LocalFileStorage
from app.core.logging import get_request_id
from app.utils.time import utcnow


def safe_text(value: Optional[str], limit: int = 300) -> str:
    text = " ".join((value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class StageOutcome:
    status: StageStatus
    summary: dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    error_summary: Optional[str] = None


@dataclass
class StageContext:
    session: Session
    settings: Settings
    storage: LocalFileStorage
    run: AnalysisRun
    case: Case
    documents: list[Document]
    actor: str
    repo: AnalysisRepository
    audit: AuditService
    # stage_name -> run id that produced its stored output (self, or a parent for carried stages)
    output_run_ids: dict[str, str] = field(default_factory=dict)
    scratch: dict[str, Any] = field(default_factory=dict)


def _case_snapshot(case: Case) -> CaseSnapshot:
    return CaseSnapshot(
        case_id=case.id, external_reference=case.external_reference, fir_number=case.fir_number,
        police_station=case.police_station, court_name=case.court_name,
        jurisdiction=case.jurisdiction, statutory_sections=list(case.statutory_sections or []),
        status=case.status.value)


def _doc_ref(doc: Document, storage: LocalFileStorage) -> DocumentRef:
    return DocumentRef(
        document_id=doc.id, version=doc.version, filename=doc.filename,
        document_type=doc.document_type, mime_type=doc.mime_type, size_bytes=doc.size_bytes,
        checksum_sha256=doc.checksum_sha256, storage_key=doc.storage_key,
        content_path=storage.content_path_if_present(doc.storage_key))


def _evidence_record(e: Evidence) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=e.id, document_id=e.document_id, fact_type=e.fact_type, fact_value=e.fact_value,
        entity_ref=e.entity_ref, category=e.category, source_page=e.source_page, quote=e.quote,
        char_start=e.char_start, char_end=e.char_end, confidence=e.confidence,
        verification_status=e.verification_status, provenance=e.provenance or {})


def _warnings(output: AgentOutputBase) -> list[dict[str, str]]:
    return [{"code": w.code, "message": safe_text(w.message)} for w in output.warnings]


class StageHandler:
    agent_key: AgentKey
    output_model: type[AgentOutputBase]

    def build_request(self, ctx: StageContext):  # -> BaseModel | None
        raise NotImplementedError

    def before_call(self, ctx: StageContext, request) -> None:
        return None

    def validate(self, ctx: StageContext, request, output) -> None:
        return None

    def persist(self, ctx: StageContext, request, output) -> StageOutcome:
        raise NotImplementedError

    def on_failure(self, ctx: StageContext, request, outcome: StageOutcome) -> None:
        return None

    @staticmethod
    def _common(ctx: StageContext) -> dict[str, Any]:
        cid = get_request_id()
        return {"contract_version": CONTRACT_VERSION, "run_id": ctx.run.id,
                "correlation_id": None if cid == "-" else cid, "case": _case_snapshot(ctx.case),
                "config": dict((ctx.run.options or {}).get("agent_config", {}))}

    @staticmethod
    def _stage_status(output: AgentOutputBase) -> StageStatus:
        return StageStatus.PARTIAL if output.status == AgentResultStatus.PARTIAL else StageStatus.SUCCEEDED


# ---- Stage 1: OCR ----------------------------------------------------------------------

class OcrHandler(StageHandler):
    agent_key = AgentKey.OCR
    output_model = OcrAgentOutput

    def build_request(self, ctx):
        reprocess = bool((ctx.run.options or {}).get("reprocess_documents"))
        todo = [d for d in ctx.documents
                if reprocess or d.processing_status != DocumentProcessingStatus.PROCESSED]
        ctx.scratch["docs_to_process"] = todo
        if not todo:
            return None
        return OcrAgentInput(**self._common(ctx), documents=[_doc_ref(d, ctx.storage) for d in todo])

    def before_call(self, ctx, request):
        for doc in ctx.scratch["docs_to_process"]:
            doc.processing_status = DocumentProcessingStatus.PROCESSING
            doc.processing_error = None
            doc.processing_updated_at = utcnow()
            ctx.audit.record(AuditEventType.DOCUMENT_PROCESSING_STARTED, case_id=ctx.case.id,
                             actor="system", resource_type="document", resource_id=doc.id,
                             analysis_run_id=ctx.run.id, metadata={"version": doc.version, "stage": "ocr"})

    def validate(self, ctx, request, output: OcrAgentOutput):
        expected = [d.document_id for d in request.documents]
        got = [r.document_id for r in output.document_results]
        if sorted(got) != sorted(expected):
            raise AgentInvalidOutputError(
                "document_results must contain exactly one entry per input document.",
                details={"expected": len(expected), "received": len(got)})

    def persist(self, ctx, request, output: OcrAgentOutput) -> StageOutcome:
        docs = {d.id: d for d in ctx.scratch["docs_to_process"]}
        failed_ids: list[str] = []
        for res in output.document_results:
            doc = docs[res.document_id]
            doc.processing_updated_at = utcnow()
            if res.status == DocumentResultStatus.SUCCESS:
                doc.ocr_artifacts = {
                    "pages": [p.model_dump() for p in res.pages],
                    "full_text": res.full_text,
                    "confidence": res.confidence,
                    "extraction_run_id": ctx.run.id,
                }
            else:
                failed_ids.append(doc.id)
                doc.processing_error = safe_text(
                    f"{res.error.code}: {res.error.message}" if res.error else "OCR failed.")
                ctx.audit.record(AuditEventType.DOCUMENT_PROCESSING_FAILED, case_id=ctx.case.id,
                                 actor="system", resource_type="document", resource_id=doc.id,
                                 analysis_run_id=ctx.run.id,
                                 metadata={"error_code": res.error.code if res.error else None, "stage": "ocr"})
        summary = {"documents_ocrd": len(docs) - len(failed_ids), "documents_failed": len(failed_ids),
                     "warnings": len(output.warnings)}
        if failed_ids and len(failed_ids) == len(docs):
            return StageOutcome(StageStatus.FAILED, summary, "OCR_FAILED", "All documents failed OCR.")
        status = StageStatus.PARTIAL if failed_ids else self._stage_status(output)
        return StageOutcome(status, summary)

    def on_failure(self, ctx, request, outcome):
        for doc in ctx.scratch.get("docs_to_process", []):
            doc = ctx.session.get(Document, doc.id)
            if doc and doc.processing_status == DocumentProcessingStatus.PROCESSING:
                doc.processing_status = DocumentProcessingStatus.FAILED
                doc.processing_error = safe_text(f"{outcome.error_code}: {outcome.error_summary}")
                doc.processing_updated_at = utcnow()


# ---- Stage 2: evidence extraction ------------------------------------------------------

class EvidenceExtractionHandler(StageHandler):
    agent_key = AgentKey.EVIDENCE_EXTRACTION
    output_model = EvidenceAgentOutput

    def build_request(self, ctx):
        reprocess = bool((ctx.run.options or {}).get("reprocess_documents"))
        todo = [d for d in ctx.documents
                if reprocess or d.processing_status != DocumentProcessingStatus.PROCESSED]
        ctx.scratch["docs_to_process"] = todo
        if not todo:
            return None
        ocr_map = {d.id: dict(d.ocr_artifacts or {}) for d in todo}
        return EvidenceAgentInput(
            **self._common(ctx), documents=[_doc_ref(d, ctx.storage) for d in todo],
            ocr_by_document_id=ocr_map)

    def validate(self, ctx, request, output: EvidenceAgentOutput):
        expected = [d.document_id for d in request.documents]
        got = [r.document_id for r in output.document_results]
        if sorted(got) != sorted(expected):
            raise AgentInvalidOutputError(
                "document_results must contain exactly one entry per input document.",
                details={"expected": len(expected), "received": len(got)})
        failed = {r.document_id for r in output.document_results
                  if r.status == DocumentResultStatus.FAILED}
        for fact in output.facts:
            if fact.source_document_id not in expected:
                raise AgentInvalidOutputError("A fact references a document that was not requested.")
            if fact.source_document_id in failed:
                raise AgentInvalidOutputError("A fact was returned for a document reported as FAILED.")

    def persist(self, ctx, request, output: EvidenceAgentOutput) -> StageOutcome:
        docs = {d.id: d for d in ctx.scratch["docs_to_process"]}
        failed_ids: list[str] = []
        for res in output.document_results:
            doc = docs[res.document_id]
            doc.processing_updated_at = utcnow()
            if res.status == DocumentResultStatus.SUCCESS:
                doc.processing_status = DocumentProcessingStatus.PROCESSED
                doc.processing_error = None
                ctx.audit.record(AuditEventType.DOCUMENT_PROCESSING_COMPLETED, case_id=ctx.case.id,
                                 actor="system", resource_type="document", resource_id=doc.id,
                                 analysis_run_id=ctx.run.id)
            else:
                failed_ids.append(doc.id)
                doc.processing_status = DocumentProcessingStatus.FAILED
                doc.processing_error = safe_text(
                    f"{res.error.code}: {res.error.message}" if res.error else "Extraction failed.")
        rows = [Evidence(
            case_id=ctx.case.id, document_id=f.source_document_id, fact_type=f.fact_type.value,
            fact_value=f.value, entity_ref=f.entity_ref, category=f.category,
            source_page=f.source_page, quote=f.quote, char_start=f.char_start, char_end=f.char_end,
            confidence=f.confidence, verification_status=f.verification_status,
            extraction_run_id=ctx.run.id, provenance=f.provenance, agent_name=output.agent_name,
            agent_version=output.agent_version, is_simulated=output.is_simulated) for f in output.facts]
        ctx.repo.add_evidence(rows)
        if rows:
            ctx.audit.record(AuditEventType.EVIDENCE_STORED, case_id=ctx.case.id, actor="system",
                             resource_type="evidence", analysis_run_id=ctx.run.id,
                             metadata={"count": len(rows), "agent": output.agent_name,
                                       "simulated": output.is_simulated})
        summary = {"documents_processed": len(docs) - len(failed_ids),
                   "documents_failed": len(failed_ids), "evidence_count": len(rows),
                   "evidence_ids": [r.id for r in rows], "warnings": len(output.warnings)}
        if failed_ids and len(failed_ids) == len(docs):
            return StageOutcome(StageStatus.FAILED, summary, "EVIDENCE_EXTRACTION_FAILED",
                                "All documents failed evidence extraction.")
        status = StageStatus.PARTIAL if failed_ids else self._stage_status(output)
        return StageOutcome(status, summary)


# ---- Person 2 ---------------------------------------------------------------------------

class ConflictDetectionHandler(StageHandler):
    agent_key = AgentKey.CONFLICT_DETECTION
    output_model = ConflictAgentOutput

    def build_request(self, ctx):
        evidence = ctx.repo.evidence_for_documents([d.id for d in ctx.documents])
        ctx.scratch["evidence_ids"] = {e.id for e in evidence}
        return ConflictAgentInput(
            **self._common(ctx), documents=[_doc_ref(d, ctx.storage) for d in ctx.documents],
            evidence=[_evidence_record(e) for e in evidence],
            new_evidence_ids=[e.id for e in evidence if e.extraction_run_id == ctx.run.id])

    def validate(self, ctx, request, output: ConflictAgentOutput):
        known_evidence = {e.evidence_id for e in request.evidence}
        known_docs = {d.document_id for d in request.documents}
        for f in output.findings:
            if not set(f.related_evidence_ids) <= known_evidence:
                raise AgentInvalidOutputError("A finding references unknown evidence IDs.")
            if not set(f.related_document_ids) <= known_docs:
                raise AgentInvalidOutputError("A finding references documents outside this run.")

    def persist(self, ctx, request, output: ConflictAgentOutput) -> StageOutcome:
        rows = [Conflict(
            case_id=ctx.case.id, analysis_run_id=ctx.run.id, conflict_type=f.finding_type,
            description=f.description, severity=f.severity,
            related_evidence_ids=list(f.related_evidence_ids),
            related_document_ids=list(f.related_document_ids),
            conflicting_values=f.conflicting_values, missing_information=f.missing_information,
            resolution_status=f.resolution_status, resolution_notes=f.resolution_notes,
            agent_name=output.agent_name, agent_version=output.agent_version,
            is_simulated=output.is_simulated) for f in output.findings]
        ctx.repo.add_conflicts(rows)
        ctx.audit.record(AuditEventType.CONFLICTS_STORED, case_id=ctx.case.id, actor="system",
                         resource_type="conflict", analysis_run_id=ctx.run.id,
                         metadata={"count": len(rows), "agent": output.agent_name,
                                   "simulated": output.is_simulated})
        return StageOutcome(self._stage_status(output),
                            {"conflict_count": len(rows), "conflict_ids": [r.id for r in rows],
                             "warnings": len(output.warnings)})


# ---- Stage 4: rule evaluation ----------------------------------------------------------

class RuleEvaluationHandler(StageHandler):
    agent_key = AgentKey.RULE_EVALUATION
    output_model = ReasoningAgentOutput

    def build_request(self, ctx):
        evidence = ctx.repo.evidence_for_documents([d.id for d in ctx.documents])
        conflict_run = ctx.output_run_ids.get("conflict_detection")
        conflicts = ctx.repo.conflicts_for_run(conflict_run) if conflict_run else []
        return ReasoningAgentInput(
            **self._common(ctx), documents=[_doc_ref(d, ctx.storage) for d in ctx.documents],
            evidence=[_evidence_record(e) for e in evidence],
            conflicts=[ConflictRecord(
                conflict_id=c.id, conflict_type=c.conflict_type, description=c.description,
                severity=c.severity, related_evidence_ids=c.related_evidence_ids,
                related_document_ids=c.related_document_ids,
                missing_information=c.missing_information,
                resolution_status=c.resolution_status) for c in conflicts],
            rule_config=RuleConfig(**((ctx.run.options or {}).get("rule_config") or {})))

    def validate(self, ctx, request, output: ReasoningAgentOutput):
        known = {e.evidence_id for e in request.evidence}
        seen: set[tuple[str, str]] = set()
        for ev in output.evaluations:
            if not set(ev.input_evidence_ids) <= known:
                raise AgentInvalidOutputError("An evaluation references unknown evidence IDs.")
            key = (ev.rule_id, ev.rule_version)
            if key in seen:
                raise AgentInvalidOutputError("Duplicate (rule_id, rule_version) in one output.")
            seen.add(key)

    def persist(self, ctx, request, output: ReasoningAgentOutput) -> StageOutcome:
        now = utcnow()
        rows = [RuleResult(
            case_id=ctx.case.id, analysis_run_id=ctx.run.id, rule_id=ev.rule_id,
            rule_version=ev.rule_version, evaluation_status=ev.evaluation_status,
            input_evidence_ids=list(ev.input_evidence_ids), review_signal=ev.review_signal,
            explanation=ev.explanation, missing_prerequisites=list(ev.missing_prerequisites),
            limitations=list(ev.limitations), evaluated_at=ev.evaluated_at or now,
            output_schema_version=ev.output_schema_version, agent_name=output.agent_name,
            agent_version=output.agent_version, is_simulated=output.is_simulated)
            for ev in output.evaluations]
        ctx.repo.add_rule_results(rows)
        ctx.audit.record(AuditEventType.RULE_RESULTS_STORED, case_id=ctx.case.id, actor="system",
                         resource_type="rule_result", analysis_run_id=ctx.run.id,
                         metadata={"count": len(rows), "agent": output.agent_name,
                                   "rule_set_id": output.rule_set_id,
                                   "rule_set_version": output.rule_set_version,
                                   "simulated": output.is_simulated})
        return StageOutcome(self._stage_status(output),
                            {"rule_result_count": len(rows), "rule_result_ids": [r.id for r in rows],
                             "rule_set_id": output.rule_set_id,
                             "rule_set_version": output.rule_set_version,
                             "warnings": len(output.warnings)})


# ---- Stage 5: summary generation -------------------------------------------------------

class SummaryGenerationHandler(StageHandler):
    agent_key = AgentKey.SUMMARY_GENERATION
    output_model = SummaryAgentOutput

    def build_request(self, ctx):
        evidence = ctx.repo.evidence_for_documents([d.id for d in ctx.documents])
        conflict_run = ctx.output_run_ids.get("conflict_detection")
        conflicts = ctx.repo.conflicts_for_run(conflict_run) if conflict_run else []
        rule_run = ctx.output_run_ids.get("rule_evaluation")
        rules = ctx.repo.rule_results_for_run(rule_run) if rule_run else []
        from app.orchestration.contracts import RuleEvaluation
        return SummaryAgentInput(
            **self._common(ctx), documents=[_doc_ref(d, ctx.storage) for d in ctx.documents],
            evidence=[_evidence_record(e) for e in evidence],
            conflicts=[ConflictRecord(
                conflict_id=c.id, conflict_type=c.conflict_type, description=c.description,
                severity=c.severity, related_evidence_ids=c.related_evidence_ids,
                related_document_ids=c.related_document_ids,
                missing_information=c.missing_information,
                resolution_status=c.resolution_status) for c in conflicts],
            rule_evaluations=[RuleEvaluation(
                rule_id=r.rule_id, rule_version=r.rule_version,
                evaluation_status=r.evaluation_status, review_signal=r.review_signal,
                explanation=r.explanation, input_evidence_ids=r.input_evidence_ids,
                missing_prerequisites=r.missing_prerequisites, limitations=r.limitations,
                evaluated_at=r.evaluated_at, output_schema_version=r.output_schema_version)
                for r in rules])

    def persist(self, ctx, request, output: SummaryAgentOutput) -> StageOutcome:
        block = output.summary
        summary = {
            "case_summary": block.case_summary[:500],
            "timeline_events": len(block.timeline),
            "key_evidence_count": len(block.key_evidence),
            "missing_evidence_count": len(block.missing_evidence),
            "review_recommendations_count": len(block.review_recommendations),
            "full_summary": block.model_dump(),
        }
        ctx.scratch["case_summary"] = block.model_dump()
        return StageOutcome(self._stage_status(output), summary)


HANDLERS: dict[AgentKey, StageHandler] = {
    AgentKey.OCR: OcrHandler(),
    AgentKey.EVIDENCE_EXTRACTION: EvidenceExtractionHandler(),
    AgentKey.CONFLICT_DETECTION: ConflictDetectionHandler(),
    AgentKey.RULE_EVALUATION: RuleEvaluationHandler(),
    AgentKey.SUMMARY_GENERATION: SummaryGenerationHandler(),
}
