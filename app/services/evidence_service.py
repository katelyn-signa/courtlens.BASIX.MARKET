import re
from decimal import Decimal, InvalidOperation

from app.schemas.document import DocumentExtractionResult
from app.schemas.document_classification import (
    DocumentClassificationResult,
    DocumentType,
)
from app.schemas.evidence import (
    Evidence,
    EvidenceAnalysisResult,
    EvidenceType,
    ExtractedClaim,
)
from app.schemas.facts import ExtractedFact
from app.services.claim_extraction_service import extract_claims
from app.services.document_classifier import classify_document
from app.services.fact_extraction_service import FactExtractionError, extract_facts

EVIDENCE_TYPE_BY_DOCUMENT: dict[DocumentType, EvidenceType] = {
    "contract": "contract_term",
    "purchase_order": "purchase_order",
    "invoice": "invoice",
    "payment_record": "payment_record",
    "delivery_receipt": "delivery_record",
    "email": "email_statement",
    "court_order": "court_record",
    "advocate_note": "email_statement",
    "party_document": "party_statement",
    "claim_statement": "party_statement",
    "other": "other",
}
IDENTITY_FIELDS = {
    "case_id",
    "invoice_number",
    "purchase_order_number",
    "transaction_id",
    "delivery_reference",
}
CLAIM_AMOUNT_PATTERN = re.compile(
    r"(?:\b(?:INR|Rs\.?)\s*(?P<prefix_amount>\d[\d,]*(?:\.\d+)?)|"
    r"₹\s*(?P<rupee_amount>\d[\d,]*(?:\.\d+)?)|"
    r"(?P<suffix_amount>\d[\d,]*(?:\.\d+)?)\s*INR\b)",
    re.IGNORECASE,
)


class EvidenceExtractionError(ValueError):
    """Raised when evidence analysis cannot preserve source provenance."""


def _evidence_type(document_type: DocumentType, fact: ExtractedFact) -> EvidenceType:
    if fact.field in IDENTITY_FIELDS:
        return "identity_record"
    return EVIDENCE_TYPE_BY_DOCUMENT[document_type]


def evidence_from_facts(
    facts: list[ExtractedFact], document_type: DocumentType
) -> list[Evidence]:
    evidence = []
    for fact in facts:
        if not fact.document_id or not fact.quote.strip() or fact.page < 1:
            raise EvidenceExtractionError(
                "Evidence requires a document ID, source quote, and valid page number."
            )
        evidence.append(
            Evidence(
                evidence_id=f"E{len(evidence) + 1:04d}",
                evidence_type=_evidence_type(document_type, fact),
                document_id=fact.document_id,
                document_type=document_type,
                page=fact.page,
                quote=fact.quote,
                normalized_value=fact.normalized_value,
                fact_id=fact.fact_id,
                confidence=fact.confidence,
                extraction_method=fact.extraction_method,
            )
        )
    return evidence


def _claim_amount(claim: ExtractedClaim) -> int | float | None:
    match = CLAIM_AMOUNT_PATTERN.search(claim.claim_text)
    if match is None:
        return None
    amount_text = next(value for value in match.groupdict().values() if value is not None)
    try:
        amount = Decimal(amount_text.replace(",", ""))
    except InvalidOperation:
        return None
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def map_claims_to_evidence(
    claims: list[ExtractedClaim],
    facts: list[ExtractedFact],
    evidence: list[Evidence],
) -> list[ExtractedClaim]:
    evidence_by_fact = {item.fact_id: item for item in evidence if item.fact_id}
    mapped_claims = []
    for original_claim in claims:
        claim = original_claim.model_copy(
            update={"supporting_evidence_ids": [], "status": "unverified"}
        )
        amount = _claim_amount(claim)
        if claim.claim_type == "payment_claim" and amount is not None:
            for fact in facts:
                evidence_item = evidence_by_fact.get(fact.fact_id)
                if (
                    fact.field == "amount_paid"
                    and fact.normalized_value == amount
                    and evidence_item is not None
                    and evidence_item.evidence_type == "payment_record"
                ):
                    claim.supporting_evidence_ids.append(evidence_item.evidence_id)
            if claim.supporting_evidence_ids:
                claim.status = "supported"
        mapped_claims.append(claim)
    return mapped_claims


def analyze_document(
    document: DocumentExtractionResult,
    classification: DocumentClassificationResult | None = None,
) -> EvidenceAnalysisResult:
    full_text = "\n".join(page.text for page in document.pages)
    if not full_text.strip():
        raise EvidenceExtractionError("Document contains no text to analyze.")
    if any(page.page < 1 for page in document.pages):
        raise EvidenceExtractionError("Every source page must have a page number of at least 1.")

    selected_classification = classification or classify_document(full_text)
    try:
        fact_result = extract_facts(document, selected_classification)
    except FactExtractionError as exc:
        raise EvidenceExtractionError(str(exc)) from exc

    evidence = evidence_from_facts(
        fact_result.facts,
        selected_classification.document_type,
    )
    claims = extract_claims(document, selected_classification.document_type)
    claims = map_claims_to_evidence(claims, fact_result.facts, evidence)
    return EvidenceAnalysisResult(
        document_id=document.document_id,
        document_type=selected_classification.document_type,
        facts=fact_result.facts,
        evidence=evidence,
        claims=claims,
    )