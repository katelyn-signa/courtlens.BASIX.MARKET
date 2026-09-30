import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.reasoning_agent import reason_case
from app.main import app
from app.schemas.analysis import CaseAnalysisDocumentInput, CaseAnalysisRequest
from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.services.case_analysis_service import analyze_case

client = TestClient(app)
SAMPLE_PDF = (
    Path(__file__).parent.parent
    / "sample_data"
    / "documents"
    / "fictional_payment_agreement.pdf"
)


def agreement_document(
    document_id: str,
    amount: int,
) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        document_id=document_id,
        filename=f"{document_id}.pdf",
        page_count=1,
        pages=[
            DocumentPage(
                page=1,
                text=(
                    "COMMERCIAL PAYMENT AGREEMENT\n"
                    "Seller: ABC Industries\n"
                    "Buyer: XYZ Traders\n"
                    f"Contract Amount: INR {amount}\n"
                    "Payment Due Date: 10 August 2026"
                ),
                extraction_method="text",
            )
        ],
    )


def test_single_document_analysis_preserves_classification_and_facts() -> None:
    request = CaseAnalysisRequest(
        case_id="C-104",
        case_title="SME Payment Dispute",
        case_type="commercial_dispute",
        parties=[
            {"role": "seller", "name": "ABC Industries"},
            {"role": "buyer", "name": "XYZ Traders"},
        ],
        documents=[
            CaseAnalysisDocumentInput(
                extracted_document=agreement_document("DOC-1", 500000)
            )
        ],
    )

    result = analyze_case(request)

    assert result.case_intake.case.metadata.case_id == "C-104"
    assert result.case_intake.case.metadata.case_title == "SME Payment Dispute"
    assert result.documents[0].status == "processed"
    assert result.documents[0].classification.document_type == "contract"
    assert result.facts
    assert result.evidence
    assert result.analysis_summary.document_count == 1
    assert result.analysis_summary.fact_count == len(result.facts)
    assert result.analysis_summary.evidence_count == len(result.evidence)


def test_multiple_documents_create_conflict_and_keep_provenance() -> None:
    request = CaseAnalysisRequest(
        case_id="C-MULTI",
        documents=[
            CaseAnalysisDocumentInput(
                extracted_document=agreement_document("DOC-A", 500000)
            ),
            CaseAnalysisDocumentInput(
                extracted_document=agreement_document("DOC-B", 400000)
            ),
        ],
    )

    result = analyze_case(request)

    assert len(result.documents) == 2
    assert all(item.status == "processed" for item in result.documents)
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.conflict_type == "amount_conflict"
    assert {item.document_id for item in conflict.conflicting_values} == {"DOC-A", "DOC-B"}
    assert all(item.page == 1 and item.quote for item in conflict.conflicting_values)
    assert result.analysis_summary.high_severity_conflict_count == 1
    assert result.analysis_summary.review_signal == "conflicts_require_attention"


def test_c104_hearing_date_conflict_demo_end_to_end() -> None:
    documents = [
        ("DOC-001", None, "The matter is listed for hearing on 15 October 2026."),
        (
            "DOC-002",
            "advocate_note",
            "Client has been informed that the next hearing is scheduled for 8 October 2026.",
        ),
        (
            "DOC-003",
            "party_document",
            "Previous communication mentions an expected hearing during the second week of October 2026.",
        ),
    ]
    request = CaseAnalysisRequest(
        case_id="C-104",
        case_title="Hearing Date Conflict",
        documents=[
            CaseAnalysisDocumentInput(
                document_id=document_id,
                source_type=source_type,
                extracted_document=DocumentExtractionResult(
                    document_id=document_id,
                    filename=f"{document_id}.txt",
                    page_count=1,
                    pages=[DocumentPage(page=1, text=text, extraction_method="text")],
                ),
            )
            for document_id, source_type, text in documents
        ],
    )

    analysis = analyze_case(request)
    hearing_facts = {
        fact.document_id: fact
        for fact in analysis.facts
        if fact.field == "hearing_date"
    }

    assert analysis.documents[0].classification.document_type == "court_order"
    assert hearing_facts["DOC-001"].normalized_value == "2026-10-15"
    assert hearing_facts["DOC-002"].normalized_value == "2026-10-08"
    period_fact = next(
        fact for fact in analysis.facts if fact.field == "expected_hearing_period"
    )
    assert period_fact.document_id == "DOC-003"
    assert period_fact.normalized_value == "the second week of October 2026"

    conflict = next(item for item in analysis.conflicts if item.event_type == "hearing_date")
    assert {item.document_id for item in conflict.conflicting_values} == {"DOC-001", "DOC-002"}
    assert {item.normalized_value for item in conflict.conflicting_values} == {
        "2026-10-15",
        "2026-10-08",
    }
    court_evidence = next(item for item in analysis.evidence if item.document_id == "DOC-001")
    assert court_evidence.document_type == "court_order"
    assert court_evidence.page == 1
    assert court_evidence.quote == documents[0][2]
    assert court_evidence.normalized_value == "2026-10-15"
    assert court_evidence.confidence > 0

    reasoning = reason_case(analysis)
    authority_rule = next(
        item for item in reasoning.rules_evaluated if item.rule_id == "R006"
    )
    assert authority_rule.triggered
    assert authority_rule.result["recommended_value"] == "2026-10-15"
    assert authority_rule.result["configured_source_authority"] == {
        "court_order": 3,
        "advocate_note": 2,
        "party_document": 1,
    }
    assert reasoning.recommendation == (
        "Based on the configured source hierarchy, CourtLens recommends "
        "15 October 2026. Human confirmation is required."
    )
    assert reasoning.human_review_required
    assert reasoning.why_explanation.model_dump() == {
        "recommendation": "15 October 2026",
        "evidence": "Official Court Order",
        "rule": "Official Court Order > Advocate Note",
        "reason": (
            "Two documents contain different hearing dates. The official court order "
            "has higher configured source authority."
        ),
    }
    trace = " ".join(step.description for step in reasoning.reasoning_steps)
    required_trace = [
        "Documents analyzed",
        "Hearing date facts extracted",
        "Conflicting values detected",
        "Source authority evaluated",
        "Official Court Order ranked higher",
        "Recommendation generated",
        "Human confirmation required",
    ]
    positions = [trace.index(item) for item in required_trace]
    assert positions == sorted(positions)


def test_narrative_date_events_are_returned_chronologically() -> None:
    event_documents = [
        ("DOC-HEARING", "court_order", "The matter is listed for hearing on 15 October 2026.\nFiled on 2 October 2026."),
        ("DOC-PAYMENT", "payment_record", "Payment was made on 3 October 2026."),
        ("DOC-DELIVERY", "delivery_receipt", "Goods were delivered on 4 October 2026."),
        ("DOC-DATED", "contract", "Document dated 1 October 2026."),
    ]
    analysis = analyze_case(
        CaseAnalysisRequest(
            case_id="C-TIMELINE",
            documents=[
                CaseAnalysisDocumentInput(
                    document_id=document_id,
                    source_type=document_type,
                    extracted_document=DocumentExtractionResult(
                        document_id=document_id,
                        filename=f"{document_id}.txt",
                        page_count=1,
                        pages=[DocumentPage(page=1, text=text, extraction_method="text")],
                    ),
                )
                for document_id, document_type, text in event_documents
            ],
        )
    )

    events = analysis.case_intake.timeline_candidates
    assert [event.event_type for event in events] == [
        "document_date",
        "filing_date",
        "payment_date",
        "delivery_date",
        "hearing_date",
    ]
    assert [event.date.isoformat() for event in events] == [
        "2026-10-01",
        "2026-10-02",
        "2026-10-03",
        "2026-10-04",
        "2026-10-15",
    ]
    assert [event.source_document_id for event in events] == [
        "DOC-DATED",
        "DOC-HEARING",
        "DOC-PAYMENT",
        "DOC-DELIVERY",
        "DOC-HEARING",
    ]
    assert all(event.page == 1 and event.quote and event.confidence > 0 for event in events)


def test_failed_document_does_not_abort_successful_document() -> None:
    request = CaseAnalysisRequest(
        documents=[
            CaseAnalysisDocumentInput(
                extracted_document=agreement_document("DOC-OK", 500000)
            ),
            CaseAnalysisDocumentInput(
                document_id="DOC-BAD",
                filename="broken.pdf",
                content_base64="not base64!!!",
            ),
        ]
    )

    result = analyze_case(request)

    assert result.documents[0].status == "processed"
    assert result.documents[1].status == "failed"
    assert result.documents[1].error.error_type == "extraction_error"
    assert result.documents[1].facts == []
    assert result.documents[1].evidence == []
    assert all(fact.document_id != "DOC-BAD" for fact in result.facts)
    assert result.analysis_summary.document_count == 2
    assert result.analysis_summary.fact_count > 0


def test_failed_fact_extraction_does_not_create_facts_or_evidence() -> None:
    document = DocumentExtractionResult(
        document_id="DOC-EMPTY",
        filename="empty-text.pdf",
        page_count=1,
        pages=[DocumentPage(page=1, text="  ", extraction_method="text")],
    )

    result = analyze_case(
        CaseAnalysisRequest(
            documents=[CaseAnalysisDocumentInput(extracted_document=document)]
        )
    )

    assert result.documents[0].status == "failed"
    assert result.documents[0].error.error_type == "fact_extraction_error"
    assert result.documents[0].facts == []
    assert result.documents[0].evidence == []
    assert result.facts == []
    assert result.evidence == []


def test_failed_document_has_supplied_document_id_and_filename() -> None:
    request = CaseAnalysisRequest(
        documents=[
            CaseAnalysisDocumentInput(
                document_id="DOC-INVALID",
                filename="invalid.pdf",
                content_base64=base64.b64encode(b"invalid pdf bytes").decode("ascii"),
            )
        ]
    )

    result = analyze_case(request)

    assert result.documents[0].document_id == "DOC-INVALID"
    assert result.documents[0].filename == "invalid.pdf"
    assert result.documents[0].error.message


def test_summary_review_signal_is_deterministic_without_issues() -> None:
    result = analyze_case(CaseAnalysisRequest())

    assert result.analysis_summary.review_signal == "no_review_signal"
    assert result.analysis_summary.document_count == 0
    assert result.case_intake.case.metadata.case_title is None


def test_summary_reports_gap_signal_and_counts() -> None:
    result = analyze_case(
        CaseAnalysisRequest(
            documents=[
                CaseAnalysisDocumentInput(
                    extracted_document=agreement_document("DOC-1", 500000)
                )
            ]
        )
    )

    assert result.analysis_summary.document_count == len(result.documents)
    assert result.analysis_summary.fact_count == len(result.facts)
    assert result.analysis_summary.evidence_count == len(result.evidence)
    assert result.analysis_summary.claim_count == len(result.claims)
    assert result.analysis_summary.conflict_count == len(result.conflicts)
    assert result.analysis_summary.evidence_gap_count == len(result.evidence_gaps)
    if result.evidence_gaps:
        assert result.analysis_summary.review_signal == "evidence_gaps_require_attention"


def test_api_analyzes_uploaded_synthetic_pdf_end_to_end() -> None:
    encoded_pdf = base64.b64encode(SAMPLE_PDF.read_bytes()).decode("ascii")
    response = client.post(
        "/api/cases/analyze",
        json={
            "case_id": "C-104",
            "case_title": "SME Payment Dispute",
            "case_type": "commercial_dispute",
            "parties": [
                {"role": "seller", "name": "ABC Industries"},
                {"role": "buyer", "name": "XYZ Traders"},
            ],
            "documents": [
                {
                    "filename": SAMPLE_PDF.name,
                    "document_id": "DOC-SYNTHETIC",
                    "content_base64": encoded_pdf,
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["case_intake"]["case"]["metadata"]["case_id"] == "C-104"
    assert result["documents"][0]["classification"]["document_type"] == "contract"
    assert result["documents"][0]["status"] == "processed"
    assert result["facts"]
    assert result["evidence"]
    assert result["claims"]
    assert result["case_intake"]["counts"]["fact_count"] == len(result["facts"])
    assert any(fact["field"] == "contract_amount" for fact in result["facts"])
    assert all(fact["document_id"] == "DOC-SYNTHETIC" for fact in result["facts"])
    assert all(evidence["document_id"] == "DOC-SYNTHETIC" for evidence in result["evidence"])


def test_api_returns_document_level_failure_without_crashing() -> None:
    response = client.post(
        "/api/cases/analyze",
        json={
            "documents": [
                {
                    "document_id": "DOC-BAD",
                    "filename": "broken.pdf",
                    "content_base64": "not base64!!!",
                }
            ]
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["documents"][0]["status"] == "failed"
    assert result["documents"][0]["error"]["error_type"] == "extraction_error"
    assert result["facts"] == []
    assert result["evidence"] == []


@pytest.mark.parametrize(
    "document_payload",
    [
        {"filename": "missing-source.pdf"},
        {"filename": "both-sources.pdf", "content_base64": "", "extracted_document": {}},
    ],
)
def test_api_rejects_invalid_document_source(document_payload: dict) -> None:
    response = client.post(
        "/api/cases/analyze",
        json={"documents": [document_payload]},
    )

    assert response.status_code == 422


def test_pre_extracted_document_input_is_supported() -> None:
    document = agreement_document("DOC-EXTRACTED", 500000)
    result = analyze_case(
        CaseAnalysisRequest(
            documents=[CaseAnalysisDocumentInput(extracted_document=document)]
        )
    )

    assert result.documents[0].document_id == "DOC-EXTRACTED"
    assert result.documents[0].filename == "DOC-EXTRACTED.pdf"
    assert result.documents[0].status == "processed"


def test_document_failure_types_are_isolated_per_document() -> None:
    empty_text = DocumentExtractionResult(
        document_id="DOC-EMPTY",
        filename="empty.pdf",
        page_count=1,
        pages=[DocumentPage(page=1, text="", extraction_method="text")],
    )
    request = CaseAnalysisRequest(
        documents=[
            CaseAnalysisDocumentInput(extracted_document=empty_text),
            CaseAnalysisDocumentInput(
                document_id="DOC-BAD",
                filename="bad.pdf",
                content_base64="%%%",
            ),
        ]
    )

    result = analyze_case(request)

    assert [item.error.error_type for item in result.documents] == [
        "fact_extraction_error",
        "extraction_error",
    ]
    assert result.analysis_summary.document_count == 2