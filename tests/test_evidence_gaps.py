from fastapi.testclient import TestClient

from app.main import app
from app.schemas.conflict import Conflict, ConflictingValue
from app.schemas.document_classification import DocumentClassificationResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGapDetectionRequest
from app.schemas.facts import ExtractedFact
from app.services.evidence_gap_service import detect_evidence_gaps

client = TestClient(app)


def make_fact(
    field: str,
    value: str,
    normalized_value: str | int | float,
    *,
    fact_type: str = "financial",
    document_id: str = "DOC-001",
    page: int = 1,
) -> ExtractedFact:
    fact_id = f"F-{document_id}-{field}"
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


def make_evidence(
    fact: ExtractedFact,
    evidence_type: str,
    *,
    document_type: str = "contract",
) -> Evidence:
    return Evidence(
        evidence_id=f"E-{fact.document_id}-{fact.field}",
        evidence_type=evidence_type,
        document_id=fact.document_id,
        document_type=document_type,
        page=fact.page,
        quote=fact.quote,
        normalized_value=fact.normalized_value,
        fact_id=fact.fact_id,
        confidence=fact.confidence,
        extraction_method=fact.extraction_method,
    )


def make_claim(
    text: str,
    claim_type: str = "payment_claim",
    *,
    claim_id: str = "CL-001",
    document_id: str = "DOC-CLAIM",
    page: int = 1,
    supporting_evidence_ids: list[str] | None = None,
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id=claim_id,
        claimant="Buyer",
        claim_type=claim_type,
        claim_text=text,
        normalized_claim=text,
        document_id=document_id,
        document_type="claim_statement",
        page=page,
        quote=text,
        confidence=0.92,
        supporting_evidence_ids=supporting_evidence_ids or [],
    )


def make_conflict() -> Conflict:
    return Conflict(
        conflict_id="C001",
        conflict_type="date_conflict",
        fact_type="date",
        description="Conflicting payment dates were found.",
        severity="high",
        conflicting_values=[
            ConflictingValue(
                value="10 August 2026",
                normalized_value="2026-08-10",
                fact_id="F1",
                evidence_id="E1",
                document_id="DOC-A",
                page=1,
                quote="Payment Date: 10 August 2026",
            ),
            ConflictingValue(
                value="12 August 2026",
                normalized_value="2026-08-12",
                fact_id="F2",
                evidence_id="E2",
                document_id="DOC-B",
                page=2,
                quote="Payment Date: 12 August 2026",
            ),
        ],
        evidence_ids=["E1", "E2"],
        document_ids=["DOC-A", "DOC-B"],
        source_pages=[1, 2],
        quotes=["Payment Date: 10 August 2026", "Payment Date: 12 August 2026"],
        confidence=0.98,
    )


def test_full_payment_claim_without_payment_proof_creates_gap() -> None:
    claim = make_claim("Buyer has paid the full amount.")
    gaps = detect_evidence_gaps([], [], [claim], [])

    payment_gap = next(gap for gap in gaps if gap.gap_type == "missing_payment_proof")
    assert payment_gap.importance == "high"
    assert payment_gap.related_claim_ids == [claim.claim_id]
    assert "payment receipt" in payment_gap.suggested_evidence[0].casefold()


def test_partial_payment_with_full_payment_claim_requests_remaining_proof() -> None:
    contract_fact = make_fact("contract_amount", "INR 500000", 500000)
    payment_fact = make_fact(
        "amount_paid", "INR 200000", 200000, document_id="DOC-PAYMENT"
    )
    facts = [contract_fact, payment_fact]
    evidence = [
        make_evidence(contract_fact, "contract_term"),
        make_evidence(payment_fact, "payment_record", document_type="payment_record"),
    ]
    claim = make_claim("Buyer has paid the full amount.")

    gaps = detect_evidence_gaps(facts, evidence, [claim], [])

    payment_gap = next(gap for gap in gaps if gap.gap_type == "missing_payment_proof")
    assert "remaining amount" in payment_gap.reason
    assert len(payment_gap.related_evidence_ids) == 2
    assert payment_gap.related_claim_ids == [claim.claim_id]


def test_delivery_claim_without_delivery_record_creates_gap() -> None:
    claim = make_claim("Goods were delivered to the buyer.", "delivery_claim")
    gaps = detect_evidence_gaps([], [], [claim], [])

    delivery_gap = next(gap for gap in gaps if gap.gap_type == "missing_delivery_proof")
    assert delivery_gap.related_claim_ids == [claim.claim_id]
    assert "transport record" in delivery_gap.suggested_evidence[0]


def test_delivery_record_prevents_missing_delivery_gap() -> None:
    claim = make_claim("Goods were delivered to the buyer.", "delivery_claim")
    delivery_fact = make_fact("delivery_date", "5 August 2026", "2026-08-05", fact_type="date")
    delivery_evidence = make_evidence(delivery_fact, "delivery_record", document_type="delivery_receipt")

    gaps = detect_evidence_gaps([delivery_fact], [delivery_evidence], [claim], [])

    assert "missing_delivery_proof" not in {gap.gap_type for gap in gaps}


def test_claim_without_party_facts_creates_party_identity_gap() -> None:
    claim = make_claim("The payment was made.")

    gaps = detect_evidence_gaps([], [], [claim], [])

    party_gap = next(gap for gap in gaps if gap.gap_type == "missing_party_identity")
    assert party_gap.related_claim_ids == [claim.claim_id]
    assert party_gap.suggested_evidence


def test_party_fact_with_linked_evidence_prevents_party_identity_gap() -> None:
    party_fact = make_fact("buyer", "XYZ Traders", "XYZ Traders", fact_type="party")
    party_evidence = make_evidence(party_fact, "contract_term")

    gaps = detect_evidence_gaps([party_fact], [party_evidence], [], [])

    assert "missing_party_identity" not in {gap.gap_type for gap in gaps}


def test_payment_claim_without_contract_basis_creates_gap() -> None:
    claim = make_claim("Buyer claims that payment is due.")

    gaps = detect_evidence_gaps([], [], [claim], [])

    contract_gap = next(gap for gap in gaps if gap.gap_type == "missing_contract")
    assert claim.claim_id in contract_gap.related_claim_ids
    assert "underlying contractual basis" in contract_gap.description


def test_contract_term_evidence_prevents_missing_contract_gap() -> None:
    fact = make_fact("contract_amount", "INR 500000", 500000)
    evidence = make_evidence(fact, "contract_term")
    claim = make_claim("Buyer claims that payment is due.")

    gaps = detect_evidence_gaps([fact], [evidence], [claim], [])

    assert "missing_contract" not in {gap.gap_type for gap in gaps}


def test_open_conflict_becomes_unresolved_conflict_gap() -> None:
    conflict = make_conflict()

    gaps = detect_evidence_gaps([], [], [], [conflict])

    conflict_gap = next(gap for gap in gaps if gap.gap_type == "unresolved_conflict")
    assert conflict_gap.related_conflict_ids == ["C001"]
    assert conflict_gap.related_evidence_ids == ["E1", "E2"]
    assert conflict_gap.related_document_ids == ["DOC-A", "DOC-B"]
    assert conflict_gap.source_pages == [1, 2]


def test_low_severity_conflict_does_not_create_gap() -> None:
    conflict = make_conflict().model_copy(update={"severity": "low"})

    gaps = detect_evidence_gaps([], [], [], [conflict])

    assert "unresolved_conflict" not in {gap.gap_type for gap in gaps}


def test_confidence_provenance_and_gap_ids_are_deterministic() -> None:
    claim = make_claim("Buyer has paid the full amount.", page=2)
    first = detect_evidence_gaps([], [], [claim], [])
    second = detect_evidence_gaps([], [], [claim], [])

    assert first == second
    assert [gap.gap_id for gap in first] == [f"G{index:03d}" for index in range(1, len(first) + 1)]
    assert all(0 <= gap.confidence <= 1 for gap in first)
    payment_gap = next(gap for gap in first if gap.gap_type == "missing_payment_proof")
    assert payment_gap.related_claim_ids == [claim.claim_id]
    assert payment_gap.related_document_ids == [claim.document_id]
    assert payment_gap.source_pages == [2]
    assert payment_gap.quotes == [claim.quote]


def test_partial_payment_without_full_payment_claim_is_not_payment_gap() -> None:
    contract_fact = make_fact("contract_amount", "INR 500000", 500000)
    payment_fact = make_fact("amount_paid", "INR 200000", 200000, document_id="DOC-PAYMENT")
    evidence = [
        make_evidence(contract_fact, "contract_term"),
        make_evidence(payment_fact, "payment_record", document_type="payment_record"),
    ]

    gaps = detect_evidence_gaps([contract_fact, payment_fact], evidence, [], [])

    assert "missing_payment_proof" not in {gap.gap_type for gap in gaps}


def test_absent_invoice_is_not_a_gap_without_relevant_trigger() -> None:
    gaps = detect_evidence_gaps([], [], [], [])

    assert gaps == []


def test_empty_input_returns_no_gaps() -> None:
    assert detect_evidence_gaps([], [], [], []) == []


def test_multiple_triggers_produce_distinct_gap_ids() -> None:
    claims = [
        make_claim("Buyer has paid the full amount.", claim_id="CL-PAY"),
        make_claim("Goods were delivered.", "delivery_claim", claim_id="CL-DELIVERY"),
    ]

    gaps = detect_evidence_gaps([], [], claims, [make_conflict()])

    types = {gap.gap_type for gap in gaps}
    assert {"missing_payment_proof", "missing_delivery_proof", "unsupported_claim", "unresolved_conflict"} <= types
    assert len({gap.gap_id for gap in gaps}) == len(gaps)


def test_api_detects_structured_evidence_gaps() -> None:
    claim = make_claim("Buyer has paid the full amount.")
    response = client.post(
        "/api/documents/detect-gaps",
        json={"facts": [], "evidence": [], "claims": [claim.model_dump()], "conflicts": []},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["gap_count"] == len(result["gaps"])
    assert "missing_payment_proof" in {gap["gap_type"] for gap in result["gaps"]}


def test_api_accepts_optional_classification_and_empty_input() -> None:
    classification = DocumentClassificationResult(
        document_type="payment_record",
        confidence=0.9,
        matched_signals=["payment"],
    )
    response = client.post(
        "/api/documents/detect-gaps",
        json={"classification": classification.model_dump()},
    )

    assert response.status_code == 200
    assert response.json() == {"gaps": [], "gap_count": 0}


def test_api_rejects_invalid_gap_input() -> None:
    response = client.post(
        "/api/documents/detect-gaps",
        json={"facts": [{"fact_id": "F001", "page": 0}]},
    )

    assert response.status_code == 422