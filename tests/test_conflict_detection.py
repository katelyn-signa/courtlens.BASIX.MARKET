from fastapi.testclient import TestClient

from app.main import app
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.facts import ExtractedFact
from app.services.conflict_detection_service import detect_conflicts

client = TestClient(app)
EVIDENCE_TYPE = {
    "contract": "contract_term",
    "payment_record": "payment_record",
    "invoice": "invoice",
}


def make_fact(
    document_id: str,
    document_type: str,
    field: str,
    value: str,
    normalized_value: str | int | float,
    fact_type: str,
    *,
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


def make_evidence(fact: ExtractedFact, document_type: str) -> Evidence:
    evidence_type = (
        "identity_record"
        if fact.fact_type == "identity"
        else EVIDENCE_TYPE[document_type]
    )
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


def run_detection(facts: list[ExtractedFact], claims: list[ExtractedClaim] | None = None):
    document_types = {
        fact.document_id: "payment_record" if fact.field == "amount_paid" else "contract"
        for fact in facts
    }
    evidence = [make_evidence(fact, document_types[fact.document_id]) for fact in facts]
    return detect_conflicts(facts, evidence, claims or [])


def make_claim(
    claim_text: str,
    *,
    document_id: str = "DOC-CLAIM",
    page: int = 1,
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_id="CL-001",
        claimant="Buyer",
        claim_type="payment_claim",
        claim_text=claim_text,
        normalized_claim=claim_text,
        document_id=document_id,
        document_type="claim_statement",
        page=page,
        quote=claim_text,
        confidence=0.9,
    )


def test_detects_date_conflict_for_same_event() -> None:
    facts = [
        make_fact("DOC-A", "payment_record", "payment_date", "10 Aug 2026", "2026-08-10", "date"),
        make_fact("DOC-B", "payment_record", "payment_date", "12 Aug 2026", "2026-08-12", "date"),
    ]

    conflicts = run_detection(facts)

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "date_conflict"
    assert conflicts[0].severity == "high"
    assert {item.normalized_value for item in conflicts[0].conflicting_values} == {
        "2026-08-10",
        "2026-08-12",
    }


def test_detects_amount_conflict_for_same_total_amount() -> None:
    facts = [
        make_fact("DOC-A", "contract", "total_amount", "INR 500000", 500000, "financial"),
        make_fact("DOC-B", "invoice", "total_amount", "INR 400000", 400000, "financial"),
    ]

    conflicts = run_detection(facts)

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "amount_conflict"
    assert conflicts[0].severity == "high"


def test_partial_payment_is_not_total_amount_conflict() -> None:
    facts = [
        make_fact("DOC-A", "contract", "contract_amount", "INR 500000", 500000, "financial"),
        make_fact("DOC-B", "payment_record", "amount_paid", "INR 200000", 200000, "financial"),
    ]

    assert run_detection(facts) == []


def test_detects_party_conflict_with_high_severity() -> None:
    facts = [
        make_fact("DOC-A", "contract", "buyer", "XYZ Traders", "XYZ Traders", "party"),
        make_fact("DOC-B", "invoice", "buyer", "ABC Traders", "ABC Traders", "party"),
    ]

    conflicts = run_detection(facts)

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "party_conflict"
    assert conflicts[0].severity == "high"


def test_party_formatting_difference_is_normalized() -> None:
    facts = [
        make_fact("DOC-A", "contract", "buyer", "XYZ TRADERS LTD.", "XYZ TRADERS LTD.", "party"),
        make_fact("DOC-B", "invoice", "buyer", "XYZ Traders Ltd", "XYZ Traders Ltd", "party"),
    ]

    assert run_detection(facts) == []


def test_detects_case_id_conflict() -> None:
    facts = [
        make_fact("DOC-A", "contract", "case_id", "CASE-100", "CASE-100", "identity"),
        make_fact("DOC-B", "invoice", "case_id", "CASE-200", "CASE-200", "identity"),
    ]

    conflicts = run_detection(facts)

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "case_id_conflict"
    assert conflicts[0].severity == "high"


def test_non_case_identity_conflict_has_medium_severity() -> None:
    facts = [
        make_fact("DOC-A", "invoice", "invoice_number", "INV-1", "INV-1", "identity"),
        make_fact("DOC-B", "invoice", "invoice_number", "INV-2", "INV-2", "identity"),
    ]

    conflicts = run_detection(facts)

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "generic_fact_conflict"
    assert conflicts[0].severity == "medium"


def test_full_payment_claim_conflicts_with_lower_payment_evidence() -> None:
    facts = [
        make_fact("DOC-CONTRACT", "contract", "contract_amount", "INR 500000", 500000, "financial"),
        make_fact("DOC-PAYMENT", "payment_record", "amount_paid", "INR 200000", 200000, "financial"),
    ]
    claim = make_claim("Buyer has paid the full amount.")

    conflicts = run_detection(facts, [claim])

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.conflict_type == "claim_evidence_conflict"
    assert conflict.severity == "high"
    assert conflict.claim_ids == [claim.claim_id]
    assert "not supported" in conflict.description
    assert len(conflict.evidence_ids) == 2


def test_different_date_events_are_not_conflicts() -> None:
    facts = [
        make_fact("DOC-A", "contract", "contract_date", "1 Aug 2026", "2026-08-01", "date"),
        make_fact("DOC-A", "contract", "delivery_date", "5 Aug 2026", "2026-08-05", "date"),
    ]

    assert run_detection(facts) == []


def test_conflict_provenance_and_deterministic_ids() -> None:
    facts = [
        make_fact("DOC-A", "contract", "payment_date", "10 Aug 2026", "2026-08-10", "date", page=2),
        make_fact("DOC-B", "payment_record", "payment_date", "12 Aug 2026", "2026-08-12", "date", page=3),
    ]

    first = run_detection(facts)
    second = run_detection(facts)

    assert first[0].conflict_id == "C001"
    assert first == second
    for source in first[0].conflicting_values:
        assert source.evidence_id
        assert source.document_id in {"DOC-A", "DOC-B"}
        assert source.page in {2, 3}
        assert source.quote
        assert source.normalized_value
    assert first[0].evidence_ids
    assert first[0].document_ids == ["DOC-A", "DOC-B"]
    assert first[0].source_pages == [2, 3]


def test_repeated_local_evidence_ids_remain_paired_to_each_document() -> None:
    facts = [
        make_fact("DOC-A", "contract", "payment_date", "10 Aug", "2026-08-10", "date"),
        make_fact("DOC-B", "payment_record", "payment_date", "12 Aug", "2026-08-12", "date"),
    ]
    evidence = [
        make_evidence(facts[0], "contract").model_copy(update={"evidence_id": "E0001"}),
        make_evidence(facts[1], "payment_record").model_copy(update={"evidence_id": "E0001"}),
    ]

    conflict = detect_conflicts(facts, evidence, [])[0]

    assert conflict.evidence_ids == ["E0001", "E0001"]
    assert [value.document_id for value in conflict.conflicting_values] == ["DOC-A", "DOC-B"]


def test_multiple_semantic_conflicts_get_distinct_ids() -> None:
    facts = [
        make_fact("DOC-A", "contract", "total_amount", "500000", 500000, "financial"),
        make_fact("DOC-B", "invoice", "total_amount", "400000", 400000, "financial"),
        make_fact("DOC-C", "payment_record", "payment_date", "10 Aug", "2026-08-10", "date"),
        make_fact("DOC-D", "payment_record", "payment_date", "12 Aug", "2026-08-12", "date"),
    ]

    conflicts = run_detection(facts)

    assert len(conflicts) == 2
    assert [conflict.conflict_id for conflict in conflicts] == ["C001", "C002"]
    assert {conflict.conflict_type for conflict in conflicts} == {
        "amount_conflict",
        "date_conflict",
    }


def test_api_detects_conflicts_from_flat_structured_input() -> None:
    facts = [
        make_fact("DOC-A", "contract", "total_amount", "500000", 500000, "financial"),
        make_fact("DOC-B", "invoice", "total_amount", "400000", 400000, "financial"),
    ]
    evidence = [
        make_evidence(facts[0], "contract"),
        make_evidence(facts[1], "invoice"),
    ]
    response = client.post(
        "/api/documents/detect-conflicts",
        json={
            "facts": [fact.model_dump() for fact in facts],
            "evidence": [item.model_dump() for item in evidence],
            "claims": [],
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["conflict_count"] == 1
    assert result["conflicts"][0]["conflict_type"] == "amount_conflict"
    assert result["conflicts"][0]["conflicting_values"][0]["quote"]


def test_api_empty_input_returns_no_conflicts() -> None:
    response = client.post("/api/documents/detect-conflicts", json={})

    assert response.status_code == 200
    assert response.json() == {"conflicts": [], "conflict_count": 0}


def test_api_rejects_invalid_structured_input() -> None:
    response = client.post(
        "/api/documents/detect-conflicts",
        json={"facts": [{"fact_id": "F001", "page": 0}]},
    )

    assert response.status_code == 422