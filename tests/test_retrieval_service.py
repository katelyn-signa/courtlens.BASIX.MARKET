from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.case_agent import CaseAgent
from app.database import SQLiteDatabase
from app.main import app
from app.schemas.agent_state import AgentStartRequest
from app.schemas.analysis import CaseAnalysisDocumentInput
from app.schemas.conflict import Conflict, ConflictingValue
from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact
from app.schemas.retrieval import CaseEvidenceSearchRequest, RetrievalRequest
from app.services.evidence_service import analyze_document
from app.services.pdf_service import extract_pdf
from app.services.retrieval_service import search
from app.services.retrieval_service import search_case_evidence
from app.services.case_memory_service import CaseMemoryService

client = TestClient(app)
SAMPLE_PDF = (
    Path(__file__).parent.parent
    / "sample_data"
    / "documents"
    / "fictional_payment_agreement.pdf"
)


def make_fact(
    field: str,
    value: str,
    *,
    document_id: str | None = "DOC-001",
    page: int = 1,
) -> ExtractedFact:
    return ExtractedFact(
        fact_id=f"F-{document_id}-{field}",
        fact_type="financial",
        field=field,
        value=value,
        normalized_value=value,
        document_id=document_id,
        page=page,
        quote=f"{field.replace('_', ' ').title()}: {value}",
        confidence=0.91,
        extraction_method="text",
    )


def make_evidence(
    *,
    evidence_id: str,
    quote: str,
    evidence_type: str = "payment_record",
    document_id: str = "DOC-001",
    page: int = 1,
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        document_id=document_id,
        document_type="payment_record",
        page=page,
        quote=quote,
        normalized_value=None,
        fact_id=None,
        confidence=0.94,
        extraction_method="text",
    )


def make_document(document_id: str, filename: str, pages: list[str]) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        document_id=document_id,
        filename=filename,
        page_count=len(pages),
        pages=[
            DocumentPage(page=index, text=text, extraction_method="text")
            for index, text in enumerate(pages, start=1)
        ],
    )


def test_exact_keyword_retrieval() -> None:
    evidence = make_evidence(
        evidence_id="E-1",
        quote="Payment Date: 12 August 2026",
    )

    result = search(RetrievalRequest(query="payment", evidence=[evidence]))

    assert result.total == 1
    assert result.results[0].result_type == "evidence"
    assert result.results[0].score == 1.0


def test_partial_keyword_retrieval_scores_below_exact_match() -> None:
    document = make_document("DOC-1", "payment.pdf", ["Payment received."])

    exact = search(RetrievalRequest(query="payment", documents=[document]))
    partial = search(RetrievalRequest(query="pay", documents=[document]))

    assert exact.results[0].score > partial.results[0].score > 0


def test_multiple_query_terms_increase_relevance() -> None:
    full = make_evidence(
        evidence_id="E-FULL",
        quote="Payment due date: 10 August 2026",
    )
    partial = make_evidence(
        evidence_id="E-PARTIAL",
        quote="Payment received on 10 August 2026",
    )

    result = search(
        RetrievalRequest(query="payment due", evidence=[full, partial])
    )

    assert result.results[0].evidence_id == "E-FULL"
    assert result.results[0].score > result.results[1].score


def test_search_is_case_insensitive() -> None:
    evidence = make_evidence(evidence_id="E-1", quote="PAYMENT RECEIVED")

    lower = search(RetrievalRequest(query="payment", evidence=[evidence]))
    mixed = search(RetrievalRequest(query="PaYmEnT", evidence=[evidence]))

    assert lower.results == mixed.results


def test_exact_matches_rank_above_partial_matches() -> None:
    documents = [
        make_document("DOC-EXACT", "exact.pdf", ["payment is recorded"]),
        make_document("DOC-PARTIAL", "partial.pdf", ["payments are recorded"]),
    ]

    result = search(RetrievalRequest(query="payment", documents=documents))

    assert result.results[0].document_id == "DOC-EXACT"
    assert result.results[0].score > result.results[1].score


def test_evidence_result_preserves_provenance() -> None:
    evidence = make_evidence(
        evidence_id="E-9",
        quote="Amount Paid: INR 200000",
        document_id="DOC-9",
        page=3,
    )

    result = search(RetrievalRequest(query="payment", evidence=[evidence])).results[0]

    assert result.result_type == "evidence"
    assert result.document_id == "DOC-9"
    assert result.page == 3
    assert result.quote == "Amount Paid: INR 200000"
    assert result.evidence_id == "E-9"
    assert result.confidence == 0.94


def test_fact_result_preserves_provenance_and_linked_evidence() -> None:
    fact = make_fact("payment_date", "2026-08-10", page=2)
    evidence = Evidence(
        evidence_id="E-FACT",
        evidence_type="payment_record",
        document_id="DOC-001",
        document_type="payment_record",
        page=2,
        quote=fact.quote,
        normalized_value=fact.normalized_value,
        fact_id=fact.fact_id,
        confidence=0.91,
        extraction_method="text",
    )

    results = search(
        RetrievalRequest(query="payment date", facts=[fact], evidence=[evidence])
    ).results
    result = next(item for item in results if item.result_type == "fact")

    assert result.result_type == "fact"
    assert result.fact_id == fact.fact_id
    assert result.evidence_id == "E-FACT"
    assert result.document_id == "DOC-001"
    assert result.page == 2
    assert result.quote == fact.quote


def test_claim_result_preserves_provenance() -> None:
    claim = ExtractedClaim(
        claim_id="CL-1",
        claimant="XYZ Traders",
        claim_type="payment_claim",
        claim_text="XYZ Traders claims that payment was made.",
        normalized_claim="XYZ Traders claims that payment was made.",
        document_id="DOC-CLAIM",
        document_type="claim_statement",
        page=2,
        quote="XYZ Traders claims that payment was made.",
        confidence=0.88,
    )

    result = search(RetrievalRequest(query="payment", claims=[claim])).results[0]

    assert result.result_type == "claim"
    assert result.claim_id == "CL-1"
    assert result.document_id == "DOC-CLAIM"
    assert result.page == 2
    assert result.quote == claim.quote


def test_document_passage_search_returns_page_provenance() -> None:
    document = make_document(
        "DOC-PDF",
        "contract.pdf",
        ["Seller and buyer terms.", "Payment shall be made on the due date."],
    )

    result = search(RetrievalRequest(query="payment", documents=[document])).results[0]

    assert result.result_type == "document_passage"
    assert result.document_id == "DOC-PDF"
    assert result.filename == "contract.pdf"
    assert result.page == 2
    assert result.quote == "Payment shall be made on the due date."


def test_unknown_query_returns_empty_results() -> None:
    evidence = make_evidence(evidence_id="E-1", quote="Payment received")

    result = search(RetrievalRequest(query="credit note", evidence=[evidence]))

    assert result.results == []
    assert result.total == 0


def test_top_k_limits_results_and_total_reports_all_matches() -> None:
    documents = [
        make_document("DOC-1", "a.pdf", ["Payment date recorded."]),
        make_document("DOC-2", "b.pdf", ["Payment date confirmed."]),
    ]

    result = search(RetrievalRequest(query="payment", top_k=1, documents=documents))

    assert len(result.results) == 1
    assert result.total == 2


def test_missing_document_provenance_remains_null() -> None:
    fact = make_fact("reference", "Payment receipt", document_id=None)

    result = search(RetrievalRequest(query="payment", facts=[fact])).results[0]

    assert result.document_id is None
    assert result.filename is None
    assert result.page == 1
    assert result.fact_id == fact.fact_id


def test_conflict_and_gap_records_are_searchable() -> None:
    conflict = Conflict(
        conflict_id="C-1",
        conflict_type="date_conflict",
        fact_type="date",
        description="Payment dates differ.",
        severity="high",
        conflicting_values=[
            ConflictingValue(value="Aug 10", normalized_value="2026-08-10", fact_id="F1", evidence_id="E1", document_id="D1", page=1, quote="Payment date: Aug 10"),
            ConflictingValue(value="Aug 12", normalized_value="2026-08-12", fact_id="F2", evidence_id="E2", document_id="D2", page=1, quote="Payment date: Aug 12"),
        ],
        evidence_ids=["E1", "E2"],
        document_ids=["D1", "D2"],
        source_pages=[1, 1],
        quotes=["Payment date: Aug 10", "Payment date: Aug 12"],
        confidence=0.9,
    )
    gap = EvidenceGap(
        gap_id="G-1",
        gap_type="missing_payment_proof",
        description="Payment proof is missing.",
        importance="high",
        related_claim_ids=["CL-1"],
        related_document_ids=["D3"],
        source_pages=[2],
        quotes=["Buyer claims full payment."],
        suggested_evidence=["Bank statement"],
        reason="No payment record was supplied.",
        confidence=0.95,
    )

    result = search(RetrievalRequest(query="payment", conflicts=[conflict], gaps=[gap]))

    assert {item.result_type for item in result.results} == {"conflict", "evidence_gap"}


def test_api_returns_search_results() -> None:
    evidence = make_evidence(
        evidence_id="E-API",
        quote="Payment Date: 12 August 2026",
        document_id="DOC-API",
        page=2,
    )
    response = client.post(
        "/api/documents/search",
        json={"query": "payment", "top_k": 10, "evidence": [evidence.model_dump()]},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["query"] == "payment"
    assert result["total"] == 1
    assert result["results"][0]["evidence_id"] == "E-API"
    assert result["results"][0]["page"] == 2


def test_existing_synthetic_case_retrieves_payment_delivery_and_amount() -> None:
    document = extract_pdf(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    analysis = analyze_document(document)

    def retrieve(query: str):
        return search(
            RetrievalRequest(
                query=query,
                facts=analysis.facts,
                evidence=analysis.evidence,
                claims=analysis.claims,
                documents=[document],
            )
        )

    payment_results = retrieve("payment").results
    assert any(
        result.result_type == "evidence"
        and result.document_id == document.document_id
        and result.page == 1
        for result in payment_results
    )

    delivery_results = retrieve("delivery").results
    assert any(
        result.result_type == "document_passage"
        and result.page == 2
        and "delivered" in (result.quote or "").casefold()
        for result in delivery_results
    )

    amount_results = retrieve("contract amount").results
    assert any(
        result.result_type == "fact"
        and result.normalized_value == 500000
        and result.filename == SAMPLE_PDF.name
        for result in amount_results
    )

    credit_note_results = retrieve("credit note").results
    assert credit_note_results == []


def test_api_rejects_invalid_top_k() -> None:
    response = client.post("/api/documents/search", json={"query": "payment", "top_k": 0})

    assert response.status_code == 422


def test_persisted_case_search_retrieves_fact_linked_evidence_deterministically(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "case-search.sqlite3"
    monkeypatch.setenv("COURTLENS_SQLITE_PATH", str(database_path))
    document = make_document(
        "DOC-HEARING",
        "court-order.txt",
        ["The matter is listed for hearing on 15 October 2026."],
    )
    agent = CaseAgent(CaseMemoryService(SQLiteDatabase(database_path)))
    state = agent.start(
        "C-SEARCH",
        AgentStartRequest(
            documents=[CaseAnalysisDocumentInput(extracted_document=document)]
        ),
    ).state
    hearing_fact = next(item for item in state.facts if item.field == "hearing_date")
    expected_evidence = next(
        item for item in state.evidence if item.fact_id == hearing_fact.fact_id
    )
    request = CaseEvidenceSearchRequest(fact_id=hearing_fact.fact_id)

    first = search_case_evidence(state, request)
    second = search_case_evidence(state, request)
    assert first == second
    assert first.results[0].evidence_id == expected_evidence.evidence_id
    assert first.results[0].document_id == "DOC-HEARING"
    assert first.results[0].page == 1
    assert first.results[0].quote == document.pages[0].text

    response = client.post(
        "/api/cases/C-SEARCH/evidence/search",
        json={"fact_id": hearing_fact.fact_id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["evidence_id"] == expected_evidence.evidence_id