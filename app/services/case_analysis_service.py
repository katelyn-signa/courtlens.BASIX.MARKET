import base64
import binascii
from uuid import uuid4

from app.schemas.analysis import (
    AnalysisSummary,
    CaseAnalysisDocumentInput,
    CaseAnalysisRequest,
    CaseAnalysisResult,
    DocumentAnalysisError,
    DocumentAnalysisErrorType,
    DocumentAnalysisResult,
)
from app.schemas.case import CaseDocumentReference, CaseIntakeRequest
from app.schemas.document import DocumentExtractionResult
from app.schemas.document_classification import DocumentClassificationResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.facts import ExtractedFact
from app.services.case_intake_service import assemble_case
from app.services.claim_extraction_service import extract_claims
from app.services.conflict_detection_service import detect_conflicts
from app.services.document_classifier import classify_document
from app.services.evidence_gap_service import detect_evidence_gaps
from app.services.evidence_service import EvidenceExtractionError, evidence_from_facts
from app.services.fact_extraction_service import FactExtractionError, extract_facts
from app.services.pdf_service import extract_pdf


def _failed_document(
    document_id: str,
    filename: str,
    error_type: DocumentAnalysisErrorType,
    message: str,
) -> DocumentAnalysisResult:
    return DocumentAnalysisResult(
        document_id=document_id,
        filename=filename,
        page_count=None,
        status="failed",
        error=DocumentAnalysisError(error_type=error_type, message=message),
    )


def _load_document(
    document_input: CaseAnalysisDocumentInput,
) -> tuple[DocumentExtractionResult | None, str, str, DocumentAnalysisResult | None]:
    if document_input.extracted_document is not None:
        extracted_document = document_input.extracted_document
        filename = document_input.filename or extracted_document.filename
        document_id = document_input.document_id or extracted_document.document_id
        if document_id != extracted_document.document_id:
            extracted_document = extracted_document.model_copy(
                update={"document_id": document_id}
            )
        return extracted_document, document_id, filename, None

    filename = document_input.filename or "uploaded.pdf"
    document_id = document_input.document_id or str(uuid4())
    try:
        pdf_bytes = base64.b64decode(document_input.content_base64 or "", validate=True)
        document = extract_pdf(pdf_bytes, filename=filename)
    except (binascii.Error, ValueError) as exc:
        return None, document_id, filename, _failed_document(
            document_id,
            filename,
            "extraction_error",
            str(exc) or "The uploaded PDF could not be decoded or extracted.",
        )

    document = document.model_copy(update={"document_id": document_id})
    return document, document_id, filename, None


def _analyze_one_document(
    document_input: CaseAnalysisDocumentInput,
) -> tuple[DocumentAnalysisResult, DocumentExtractionResult | None]:
    document, document_id, filename, failed = _load_document(document_input)
    if failed is not None or document is None:
        return failed, None

    try:
        full_text = "\n".join(page.text for page in document.pages)
        classification = (
            DocumentClassificationResult(
                document_type=document_input.source_type,
                confidence=1.0,
                matched_signals=["declared source type"],
            )
            if document_input.source_type is not None
            else classify_document(full_text)
        )
    except Exception as exc:
        return (
            _failed_document(
                document_id,
                filename,
                "classification_error",
                str(exc) or "Document classification failed.",
            ),
            None,
        )

    try:
        fact_result = extract_facts(document, classification)
        facts = fact_result.facts
    except FactExtractionError as exc:
        return (
            DocumentAnalysisResult(
                document_id=document_id,
                filename=filename,
                page_count=document.page_count,
                status="failed",
                classification=classification,
                error=DocumentAnalysisError(
                    error_type="fact_extraction_error",
                    message=str(exc),
                ),
            ),
            document,
        )

    try:
        evidence = evidence_from_facts(facts, classification.document_type)
        claims = extract_claims(document, classification.document_type)
    except EvidenceExtractionError as exc:
        return (
            DocumentAnalysisResult(
                document_id=document_id,
                filename=filename,
                page_count=document.page_count,
                status="failed",
                classification=classification,
                facts=facts,
                error=DocumentAnalysisError(
                    error_type="analysis_error",
                    message=str(exc),
                ),
            ),
            document,
        )
    except Exception as exc:
        return (
            DocumentAnalysisResult(
                document_id=document_id,
                filename=filename,
                page_count=document.page_count,
                status="failed",
                classification=classification,
                facts=facts,
                error=DocumentAnalysisError(
                    error_type="analysis_error",
                    message=str(exc) or "Document analysis failed.",
                ),
            ),
            document,
        )

    return (
        DocumentAnalysisResult(
            document_id=document_id,
            filename=filename,
            page_count=document.page_count,
            status="processed",
            classification=classification,
            facts=facts,
            evidence=evidence,
            claims=claims,
        ),
        document,
    )


def _review_signal(conflicts, gaps, claims) -> str:
    if any(conflict.severity == "high" for conflict in conflicts):
        return "conflicts_require_attention"
    if gaps:
        return "evidence_gaps_require_attention"
    if conflicts or any(claim.status == "unverified" for claim in claims):
        return "review_recommended"
    return "no_review_signal"


def analyze_case(request: CaseAnalysisRequest) -> CaseAnalysisResult:
    document_results = []
    for document_input in request.documents:
        document_result, extracted_document = _analyze_one_document(document_input)
        document_results.append(document_result)

    facts: list[ExtractedFact] = [
        fact for item in document_results if item.status == "processed" for fact in item.facts
    ]
    evidence: list[Evidence] = [
        item for result in document_results if result.status == "processed" for item in result.evidence
    ]
    claims: list[ExtractedClaim] = [
        claim for result in document_results if result.status == "processed" for claim in result.claims
    ]
    conflicts = detect_conflicts(facts, evidence, claims)
    gaps = detect_evidence_gaps(facts, evidence, claims, conflicts)

    document_references = [
        CaseDocumentReference(
            document_id=result.document_id,
            filename=result.filename,
            document_type=(
                result.classification.document_type if result.classification else None
            ),
            source_type="pdf_upload",
            page_count=result.page_count,
        )
        for result in document_results
    ]
    intake_request = CaseIntakeRequest(
        case_id=request.case_id,
        case_title=request.case_title,
        case_type=request.case_type,
        parties=request.parties,
        source="case_analysis_pipeline",
        documents=document_references,
        facts=facts,
        evidence=evidence,
        claims=claims,
        conflicts=conflicts,
        gaps=gaps,
    )
    case_intake = assemble_case(intake_request)
    summary = AnalysisSummary(
        document_count=len(document_results),
        fact_count=len(facts),
        evidence_count=len(evidence),
        claim_count=len(claims),
        conflict_count=len(conflicts),
        evidence_gap_count=len(gaps),
        high_severity_conflict_count=sum(
            conflict.severity == "high" for conflict in conflicts
        ),
        review_signal=_review_signal(conflicts, gaps, claims),
    )
    return CaseAnalysisResult(
        case_intake=case_intake,
        documents=document_results,
        facts=facts,
        evidence=evidence,
        claims=claims,
        conflicts=conflicts,
        evidence_gaps=gaps,
        analysis_summary=summary,
    )