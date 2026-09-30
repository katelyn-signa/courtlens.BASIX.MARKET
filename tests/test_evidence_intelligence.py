from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.schemas.document_classification import DocumentClassificationResult
from app.schemas.evidence import ClaimType
from app.schemas.facts import ExtractedFact
from app.services.claim_extraction_service import extract_claims
from app.services.evidence_service import (
    EvidenceExtractionError,
    analyze_document,
    evidence_from_facts,
)
from app.services.pdf_service import extract_pdf

client = TestClient(app)
SAMPLE_PDF = (
    Path(__file__).parent.parent
    / "sample_data"
    / "documents"
    / "fictional_payment_agreement.pdf"
)


def make_document(
    text: str,
    document_type: str,
    *,
    document_id: str = "DOC-001",
    page: int = 1,
) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        document_id=document_id,
        filename="synthetic-document.pdf",
        page_count=page,
        pages=[
            DocumentPage(
                page=page,
                text=text,
                extraction_method="text",
            )
        ],
    )


def classified(document_type: str) -> DocumentClassificationResult:
    return DocumentClassificationResult(
        document_type=document_type,
        confidence=0.9,
        matched_signals=[document_type],
    )


def analyze(text: str, document_type: str) -> dict:
    result = analyze_document(
        make_document(text, document_type),
        classified(document_type),
    )
    return result.model_dump()


def field_maps(result: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    facts = {fact["field"]: fact for fact in result["facts"]}
    evidence = {item["fact_id"]: item for item in result["evidence"]}
    return facts, evidence


def test_contract_facts_become_provenance_preserving_evidence() -> None:
    result = analyze(
        "COMMERCIAL PAYMENT AGREEMENT\nSeller: ABC Industries\nBuyer: XYZ Traders\n"
        "Contract Amount: INR 5,00,000\nDelivery Date: 5 August 2026\n"
        "Payment Due Date: 10 August 2026",
        "contract",
    )
    facts, evidence_by_fact = field_maps(result)

    for field in ("contract_amount", "delivery_date", "payment_due_date"):
        fact = facts[field]
        evidence = evidence_by_fact[fact["fact_id"]]
        assert evidence["evidence_type"] == "contract_term"
        assert evidence["fact_id"] == fact["fact_id"]
        assert evidence["normalized_value"] == fact["normalized_value"]
        assert evidence["quote"] == fact["quote"]
        assert evidence["document_id"] == "DOC-001"
        assert evidence["page"] == 1


def test_payment_record_evidence_preserves_transaction_and_amount() -> None:
    result = analyze(
        "BANK TRANSACTION\nTransaction ID: TXN-001\n"
        "Payment Date: 12 August 2026\nAmount Paid: INR 2,00,000",
        "payment_record",
    )
    facts, evidence_by_fact = field_maps(result)

    transaction = facts["transaction_id"]
    transaction_evidence = evidence_by_fact[transaction["fact_id"]]
    assert transaction["normalized_value"] == "TXN-001"
    assert transaction_evidence["evidence_type"] == "identity_record"
    assert transaction_evidence["quote"] == "Transaction ID: TXN-001"

    amount = facts["amount_paid"]
    amount_evidence = evidence_by_fact[amount["fact_id"]]
    assert amount["normalized_value"] == 200000
    assert amount_evidence["evidence_type"] == "payment_record"
    assert amount_evidence["quote"] == "Amount Paid: INR 2,00,000"
    assert facts["payment_date"]["normalized_value"] == "2026-08-12"


def test_invoice_facts_become_invoice_and_identity_evidence() -> None:
    result = analyze(
        "TAX INVOICE\nInvoice Number: INV-1001\n"
        "Invoice Amount: INR 75000",
        "invoice",
    )
    facts, evidence_by_fact = field_maps(result)

    invoice_number = facts["invoice_number"]
    assert invoice_number["normalized_value"] == "INV-1001"
    assert evidence_by_fact[invoice_number["fact_id"]]["evidence_type"] == "identity_record"
    amount = facts["invoice_amount"]
    assert amount["normalized_value"] == 75000
    assert evidence_by_fact[amount["fact_id"]]["evidence_type"] == "invoice"


def test_delivery_date_becomes_delivery_evidence() -> None:
    result = analyze(
        "DELIVERY RECEIPT\nDelivery Date: 5 August 2026",
        "delivery_receipt",
    )
    facts, evidence_by_fact = field_maps(result)
    delivery_date = facts["delivery_date"]

    assert evidence_by_fact[delivery_date["fact_id"]]["evidence_type"] == "delivery_record"
    assert evidence_by_fact[delivery_date["fact_id"]]["normalized_value"] == "2026-08-05"


def test_adjustment_claim_remains_unverified_without_support() -> None:
    text = "XYZ Traders claims that the remaining amount was adjusted against a credit note."
    result = analyze(text, "claim_statement")
    claim = result["claims"][0]

    assert claim["claimant"] == "XYZ Traders"
    assert claim["claim_type"] == "adjustment_claim"
    assert claim["status"] == "unverified"
    assert claim["supporting_evidence_ids"] == []
    assert claim["claim_text"] == text


def test_exact_payment_evidence_supports_matching_payment_claim() -> None:
    result = analyze(
        "BANK TRANSACTION\nTransaction ID: TXN-001\nAmount Paid: INR 2,00,000\n"
        "XYZ Traders claims that payment reference TXN-001 confirms payment of INR 200000 was made.",
        "payment_record",
    )
    claim = result["claims"][0]
    paid_evidence = next(
        item for item in result["evidence"] if item["evidence_type"] == "payment_record"
    )

    assert claim["claim_type"] == "payment_claim"
    assert claim["status"] == "supported"
    assert claim["supporting_evidence_ids"] == [paid_evidence["evidence_id"]]


def test_partial_payment_does_not_support_full_payment_claim() -> None:
    result = analyze(
        "BANK TRANSACTION\nTransaction ID: TXN-001\nAmount Paid: INR 200000\n"
        "XYZ Traders claims that full payment of INR 500000 was made.",
        "payment_record",
    )

    claim = result["claims"][0]
    assert claim["status"] == "unverified"
    assert claim["supporting_evidence_ids"] == []


@pytest.mark.parametrize(
    ("text", "expected_type"),
    [
        (
            "XYZ Traders claims that the remaining amount was adjusted against a credit note.",
            "adjustment_claim",
        ),
        (
            "XYZ Traders claims that payment of INR 200000 was made.",
            "payment_claim",
        ),
    ],
)
def test_claim_extraction_types(text: str, expected_type: ClaimType) -> None:
    document = make_document(text, "claim_statement")
    claims = extract_claims(document, "claim_statement")

    assert len(claims) == 1
    assert claims[0].claim_type == expected_type
    assert claims[0].status == "unverified"


def test_generic_text_does_not_generate_claims() -> None:
    result = analyze("Hello. This is an ordinary general note.", "other")

    assert result["claims"] == []
    assert result["evidence"] == []


def test_evidence_and_claims_preserve_provenance_and_confidence() -> None:
    result = analyze(
        "Contract Amount: INR 500000\n"
        "XYZ Traders claims that the remaining amount was adjusted against a credit note.",
        "contract",
    )

    for evidence in result["evidence"]:
        assert evidence["document_id"] == "DOC-001"
        assert evidence["document_type"] == "contract"
        assert evidence["page"] == 1
        assert evidence["quote"]
        assert 0 <= evidence["confidence"] <= 1
    for claim in result["claims"]:
        assert claim["document_id"] == "DOC-001"
        assert claim["document_type"] == "contract"
        assert claim["page"] == 1
        assert claim["quote"] == claim["claim_text"]
        assert 0 <= claim["confidence"] <= 1


def test_every_evidence_fact_reference_resolves() -> None:
    result = analyze(
        "BANK TRANSACTION\nTransaction ID: TXN-001\nAmount Paid: INR 200000",
        "payment_record",
    )
    fact_ids = {fact["fact_id"] for fact in result["facts"]}

    assert result["evidence"]
    assert all(item["fact_id"] in fact_ids for item in result["evidence"])


def test_evidence_rejects_missing_document_provenance() -> None:
    fact = ExtractedFact(
        fact_id="F0001",
        fact_type="financial",
        field="contract_amount",
        value="INR 500000",
        normalized_value=500000,
        document_id=None,
        page=1,
        quote="Contract Amount: INR 500000",
        confidence=0.98,
        extraction_method="text",
    )

    with pytest.raises(EvidenceExtractionError, match="document ID"):
        evidence_from_facts([fact], "contract")


def test_api_returns_facts_evidence_and_claims() -> None:
    document = make_document(
        "COMMERCIAL PAYMENT AGREEMENT\nSeller: ABC Industries\n"
        "Buyer: XYZ Traders\nContract Amount: INR 500000\n"
        "XYZ Traders claims that the remaining amount was adjusted against a credit note.",
        "contract",
    )
    response = client.post(
        "/api/documents/extract-evidence",
        json={"document": document.model_dump()},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["document_type"] == "contract"
    assert result["facts"]
    assert result["evidence"]
    assert result["claims"][0]["status"] == "unverified"
    assert result["evidence"][0]["document_id"] == "DOC-001"
    assert result["evidence"][0]["page"] == 1
    assert result["evidence"][0]["quote"]


def test_api_rejects_invalid_evidence_request() -> None:
    response = client.post("/api/documents/extract-evidence", json={})

    assert response.status_code == 422


def test_api_rejects_empty_document_text() -> None:
    document = make_document(" \n ", "other")
    response = client.post(
        "/api/documents/extract-evidence",
        json={"document": document.model_dump()},
    )

    assert response.status_code == 400


def test_api_rejects_invalid_source_page_number() -> None:
    document = make_document("Seller: ABC Industries", "contract")
    document.pages[0].page = 0
    response = client.post(
        "/api/documents/extract-evidence",
        json={"document": document.model_dump()},
    )

    assert response.status_code == 400


def test_existing_synthetic_pdf_runs_complete_evidence_pipeline() -> None:
    document = extract_pdf(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    result = analyze_document(document)
    facts = {fact.field: fact for fact in result.facts}
    evidence_by_fact = {item.fact_id: item for item in result.evidence}

    assert result.document_type == "contract"
    assert facts["contract_amount"].normalized_value == 500000
    assert facts["delivery_date"].normalized_value == "2026-08-05"
    assert result.evidence
    assert all(item.fact_id in evidence_by_fact for item in result.facts)
    assert any(claim.claim_type == "delivery_claim" for claim in result.claims)