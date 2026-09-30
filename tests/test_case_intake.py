from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.case import (
    CaseDocumentReference,
    CaseIntakeRequest,
    CaseParty,
)
from app.schemas.conflict import Conflict, ConflictingValue
from app.schemas.document_classification import DocumentType
from app.schemas.evidence import Evidence, EvidenceAnalysisResult, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact
from app.services.case_intake_service import assemble_case
from app.services.conflict_detection_service import detect_conflicts
from app.services.document_classifier import classify_document
from app.services.evidence_gap_service import detect_evidence_gaps
from app.services.evidence_service import analyze_document
from app.services.pdf_service import extract_pdf

client = TestClient(app)
SAMPLE_PDF = (
    Path(__file__).parent.parent
    / "sample_data"
    / "documents"
    / "fictional_payment_agreement.pdf"
)


def make_fact(
    fact_id: str = "F0001",
    *,
    field: str = "seller",
    fact_type: str = "party",
    value: str = "ABC Industries",
    normalized_value: str | int | float = "ABC Industries",
    document_id: str | None = "DOC-104",
    page: int = 1,
) -> ExtractedFact:
    return ExtractedFact(
        fact_id=fact_id,
        fact_type=fact_type,
        field=field,
        value=value,
        normalized_value=normalized_value,
        document_id=document_id,
        page=page,
        quote=f"{field.replace('_', ' ').title()}: {value}",
        confidence=0.98,
        extraction_method="text",
    )


def make_evidence(fact: ExtractedFact) -> Evidence:
    return Evidence(
        evidence_id="E0001",
        evidence_type="contract_term",
        document_id=fact.document_id or "DOC-104",
        document_type="contract",
        page=fact.page,
        quote=fact.quote,
        normalized_value=fact.normalized_value,
        fact_id=fact.fact_id,
        confidence=fact.confidence,
        extraction_method=fact.extraction_method,
    )


def make_claim() -> ExtractedClaim:
    return ExtractedClaim(
        claim_id="CL-001",
        claimant="XYZ Traders",
        claim_type="payment_claim",
        claim_text="XYZ Traders claims payment is due.",
        normalized_claim="XYZ Traders claims payment is due.",
        document_id="DOC-104",
        document_type="claim_statement",
        page=2,
        quote="XYZ Traders claims payment is due.",
        confidence=0.9,
    )


def make_conflict() -> Conflict:
    return Conflict(
        conflict_id="C001",
        conflict_type="date_conflict",
        fact_type="date",
        description="Payment dates differ.",
        severity="high",
        conflicting_values=[
            ConflictingValue(
                value="10 Aug 2026", normalized_value="2026-08-10", fact_id="F1",
                evidence_id="E1", document_id="DOC-104", page=1,
                quote="Payment Date: 10 Aug 2026",
            ),
            ConflictingValue(
                value="12 Aug 2026", normalized_value="2026-08-12", fact_id="F2",
                evidence_id="E2", document_id="DOC-104", page=2,
                quote="Payment Date: 12 Aug 2026",
            ),
        ],
        evidence_ids=["E1", "E2"],
        document_ids=["DOC-104"],
        source_pages=[1, 2],
        quotes=["Payment Date: 10 Aug 2026", "Payment Date: 12 Aug 2026"],
        confidence=0.9,
    )


def make_gap() -> EvidenceGap:
    return EvidenceGap(
        gap_id="G001",
        gap_type="missing_payment_proof",
        description="Payment proof is missing.",
        importance="high",
        related_claim_ids=["CL-001"],
        related_document_ids=["DOC-104"],
        source_pages=[2],
        quotes=["XYZ Traders claims payment is due."],
        reason="No payment record was supplied.",
        confidence=0.9,
    )


def make_request() -> dict:
    seller = make_fact()
    delivery = make_fact(
        "F0002",
        field="delivery_date",
        fact_type="date",
        value="5 August 2026",
        normalized_value="2026-08-05",
        page=2,
    )
    evidence = make_evidence(seller)
    return {
        "case_id": "C-104",
        "case_title": "SME Payment Dispute",
        "case_type": "commercial_dispute",
        "parties": [
            {"role": "seller", "name": "ABC Industries"},
            {"role": "buyer", "name": "XYZ Traders"},
        ],
        "created_at": None,
        "source": "hackathon_test",
        "documents": [
            {
                "document_id": "DOC-104",
                "filename": "agreement.pdf",
                "document_type": "contract",
                "source_type": "pdf_upload",
                "page_count": 2,
            }
        ],
        "facts": [seller.model_dump(), delivery.model_dump()],
        "evidence": [evidence.model_dump()],
        "claims": [make_claim().model_dump()],
        "conflicts": [make_conflict().model_dump()],
        "gaps": [make_gap().model_dump()],
    }


def test_case_metadata_is_preserved() -> None:
    result = assemble_case(CaseIntakeRequest.model_validate(make_request()))

    assert result.case.metadata.case_id == "C-104"
    assert result.case.metadata.case_title == "SME Payment Dispute"
    assert result.case.metadata.case_type == "commercial_dispute"
    assert result.case.metadata.source == "hackathon_test"


def test_document_reference_is_preserved() -> None:
    result = assemble_case(CaseIntakeRequest.model_validate(make_request()))
    document = result.case.documents[0]

    assert document.document_id == "DOC-104"
    assert document.filename == "agreement.pdf"
    assert document.document_type == "contract"
    assert document.source_type == "pdf_upload"
    assert document.page_count == 2


def test_facts_evidence_claims_conflicts_and_gaps_are_preserved() -> None:
    request = CaseIntakeRequest.model_validate(make_request())
    result = assemble_case(request)

    assert result.case.facts == request.facts
    assert result.case.evidence == request.evidence
    assert result.case.claims == request.claims
    assert result.case.conflicts == request.conflicts
    assert result.case.gaps == request.gaps
    assert result.case.facts[0].fact_id == "F0001"
    assert result.case.evidence[0].evidence_id == "E0001"
    assert result.case.claims[0].claim_id == "CL-001"
    assert result.case.conflicts[0].conflict_id == "C001"
    assert result.case.gaps[0].gap_id == "G001"


def test_counts_match_supplied_records() -> None:
    result = assemble_case(CaseIntakeRequest.model_validate(make_request()))

    assert result.counts.model_dump() == {
        "document_count": 1,
        "fact_count": 2,
        "evidence_count": 1,
        "claim_count": 1,
        "conflict_count": 1,
        "evidence_gap_count": 1,
    }


def test_status_signals_are_deterministic_and_explain_reasons() -> None:
    result = assemble_case(CaseIntakeRequest.model_validate(make_request()))
    signals = {item.signal: item.reason for item in result.status_signals}

    assert "conflicts_detected" in signals
    assert "evidence_gaps_present" in signals
    assert "unsupported_claims_present" in signals
    assert "requires_review" in signals
    assert all(signals.values())


def test_no_conflict_signal_when_no_conflicts_supplied() -> None:
    request = CaseIntakeRequest.model_validate({"case_id": "C-EMPTY", "conflicts": []})

    result = assemble_case(request)

    assert result.status_signals[0].signal == "no_conflicts_detected"
    assert "No structured conflicts" in result.status_signals[0].reason


def test_timeline_candidates_keep_date_provenance() -> None:
    request = CaseIntakeRequest.model_validate(make_request())

    result = assemble_case(request)

    assert len(result.timeline_candidates) == 1
    timeline = result.timeline_candidates[0]
    assert timeline.date == date(2026, 8, 5)
    assert timeline.event_type == "delivery_date"
    assert timeline.source_document_id == "DOC-104"
    assert timeline.filename == "agreement.pdf"
    assert timeline.page == 2
    assert timeline.quote == "Delivery Date: 5 August 2026"
    assert timeline.fact_id == "F0002"


def test_optional_metadata_remains_null() -> None:
    result = assemble_case(CaseIntakeRequest.model_validate({"case_id": "C-NULL"}))

    assert result.case.metadata.case_title is None
    assert result.case.metadata.case_type is None
    assert result.case.metadata.created_at is None
    assert result.case.metadata.source is None
    assert result.case.metadata.parties == []


def test_party_information_can_be_projected_from_party_facts() -> None:
    request_data = make_request()
    request_data.pop("parties")
    request = CaseIntakeRequest.model_validate(request_data)

    result = assemble_case(request)

    assert result.case.metadata.parties == [CaseParty(role="seller", name="ABC Industries")]


def test_supplied_case_id_is_never_replaced() -> None:
    request_data = make_request()
    request_data["case_id"] = "C-104"

    result = assemble_case(CaseIntakeRequest.model_validate(request_data))

    assert result.case.metadata.case_id == "C-104"


def test_empty_case_is_assembled_with_uuid_and_zero_counts() -> None:
    result = assemble_case(CaseIntakeRequest())

    UUID(result.case.metadata.case_id)
    assert result.counts.document_count == 0
    assert result.counts.fact_count == 0
    assert result.counts.evidence_count == 0
    assert result.counts.claim_count == 0
    assert result.counts.conflict_count == 0
    assert result.counts.evidence_gap_count == 0
    assert result.case.metadata.case_title is None


def test_document_references_are_assembled_from_supplied_record_provenance() -> None:
    fact = make_fact(document_id="DOC-FACT")
    request = CaseIntakeRequest(facts=[fact])

    result = assemble_case(request)

    assert result.case.documents == [CaseDocumentReference(document_id="DOC-FACT")]
    assert result.case.documents[0].filename is None
    assert result.case.documents[0].page_count is None


def test_api_returns_case_intake_result() -> None:
    response = client.post("/api/cases/intake", json=make_request())

    assert response.status_code == 200
    result = response.json()
    assert result["case"]["metadata"]["case_id"] == "C-104"
    assert result["counts"]["document_count"] == 1
    assert result["counts"]["fact_count"] == 2
    assert result["case"]["facts"][0]["fact_id"] == "F0001"


def test_api_rejects_invalid_intake_payload() -> None:
    response = client.post(
        "/api/cases/intake",
        json={"case_id": "C-INVALID", "facts": [{"fact_id": "F001", "page": 0}]},
    )

    assert response.status_code == 422


def test_synthetic_agreement_outputs_assemble_into_one_case() -> None:
    document = extract_pdf(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    analysis = analyze_document(document)
    conflicts = detect_conflicts(analysis.facts, analysis.evidence, analysis.claims)
    gaps = detect_evidence_gaps(
        analysis.facts,
        analysis.evidence,
        analysis.claims,
        conflicts,
    )
    request = CaseIntakeRequest(
        case_id="C-104",
        case_title="SME Payment Dispute",
        case_type="commercial_dispute",
        documents=[
            CaseDocumentReference(
                document_id=document.document_id,
                filename=document.filename,
                document_type=analysis.document_type,
                source_type="pdf_upload",
                page_count=document.page_count,
            )
        ],
        facts=analysis.facts,
        evidence=analysis.evidence,
        claims=analysis.claims,
        conflicts=conflicts,
        gaps=gaps,
    )

    result = assemble_case(request)

    assert result.case.metadata.case_id == "C-104"
    assert result.case.documents[0].filename == "fictional_payment_agreement.pdf"
    assert result.counts.document_count == len(request.documents)
    assert result.counts.fact_count == len(request.facts)
    assert result.counts.evidence_count == len(request.evidence)
    assert result.counts.claim_count == len(request.claims)
    assert result.counts.conflict_count == len(request.conflicts)
    assert result.counts.evidence_gap_count == len(request.gaps)
    assert result.case.facts[0].fact_id == analysis.facts[0].fact_id
    assert result.timeline_candidates


def test_api_rejects_invalid_case_document_page_count() -> None:
    response = client.post(
        "/api/cases/intake",
        json={
            "documents": [
                {"document_id": "DOC-1", "filename": "x.pdf", "page_count": -1}
            ]
        },
    )

    assert response.status_code == 422