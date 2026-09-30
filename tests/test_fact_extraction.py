from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.schemas.document_classification import DocumentClassificationResult
from app.services.document_classifier import classify_document
from app.services.fact_extraction_service import extract_facts

client = TestClient(app)
SAMPLE_PDF = (
    Path(__file__).parent.parent
    / "sample_data"
    / "documents"
    / "fictional_payment_agreement.pdf"
)


def make_document(
    text: str,
    *,
    document_type: str,
    document_id: str = "D001",
    page_number: int = 1,
) -> DocumentExtractionResult:
    return DocumentExtractionResult(
        document_id=document_id,
        filename="synthetic.pdf",
        page_count=page_number,
        pages=[
            DocumentPage(
                page=page_number,
                text=text,
                extraction_method="text",
            )
        ],
    )


def extract_for(text: str, document_type: str) -> list[dict]:
    document = make_document(text, document_type=document_type)
    classification = DocumentClassificationResult(
        document_type=document_type,
        confidence=0.9,
        matched_signals=[document_type],
    )
    return [
        fact.model_dump()
        for fact in extract_facts(document, classification).facts
    ]


def fields(facts: list[dict]) -> dict[str, dict]:
    return {fact["field"]: fact for fact in facts}


def test_contract_extracts_parties_amount_and_dates() -> None:
    facts = fields(
        extract_for(
            "COMMERCIAL PAYMENT AGREEMENT\n"
            "Seller: ABC Industries\nBuyer: XYZ Traders\n"
            "Contract Amount: INR 5,00,000\n"
            "Delivery Date: 5 August 2026\n"
            "Payment Due Date: 10 August 2026",
            "contract",
        )
    )

    assert facts["seller"]["value"] == "ABC Industries"
    assert facts["buyer"]["value"] == "XYZ Traders"
    assert facts["contract_amount"]["normalized_value"] == 500000
    assert facts["contract_amount"]["currency"] == "INR"
    assert facts["delivery_date"]["normalized_value"] == "2026-08-05"
    assert facts["payment_due_date"]["normalized_value"] == "2026-08-10"


def test_invoice_extracts_number_date_parties_and_amount() -> None:
    facts = fields(
        extract_for(
            "TAX INVOICE\nInvoice Number: INV-1042\nInvoice Date: 05 Aug 2026\n"
            "Seller: ABC Industries\nBuyer: XYZ Traders\nInvoice Amount: INR 500000",
            "invoice",
        )
    )

    assert facts["invoice_number"]["normalized_value"] == "INV-1042"
    assert facts["invoice_date"]["normalized_value"] == "2026-08-05"
    assert facts["seller"]["normalized_value"] == "ABC Industries"
    assert facts["buyer"]["normalized_value"] == "XYZ Traders"
    assert facts["invoice_amount"]["normalized_value"] == 500000


def test_payment_record_extracts_transaction_date_and_amount() -> None:
    facts = fields(
        extract_for(
            "BANK TRANSACTION\nTransaction ID: TX-771\nPayment Date: 2026-08-05\n"
            "Amount Paid: Rs. 5,00,000",
            "payment_record",
        )
    )

    assert facts["transaction_id"]["normalized_value"] == "TX-771"
    assert facts["payment_date"]["normalized_value"] == "2026-08-05"
    assert facts["amount_paid"]["normalized_value"] == 500000
    assert facts["amount_paid"]["currency"] == "INR"


def test_purchase_order_extracts_number_date_and_parties() -> None:
    facts = fields(
        extract_for(
            "PURCHASE ORDER\nPO Number: PO-55\nOrder Date: 05/08/2026\n"
            "Buyer: XYZ Traders\nSeller: ABC Industries",
            "purchase_order",
        )
    )

    assert facts["purchase_order_number"]["normalized_value"] == "PO-55"
    assert facts["order_date"]["normalized_value"] == "2026-08-05"
    assert facts["buyer"]["normalized_value"] == "XYZ Traders"
    assert facts["seller"]["normalized_value"] == "ABC Industries"
    assert facts["order_date"]["confidence"] < 0.98


def test_delivery_receipt_extracts_delivery_date_and_parties() -> None:
    facts = fields(
        extract_for(
            "DELIVERY RECEIPT\nDelivery Date: 5 Aug 2026\n"
            "Seller: ABC Industries\nBuyer: XYZ Traders",
            "delivery_receipt",
        )
    )

    assert facts["delivery_date"]["normalized_value"] == "2026-08-05"
    assert facts["seller"]["normalized_value"] == "ABC Industries"
    assert facts["buyer"]["normalized_value"] == "XYZ Traders"


def test_court_order_extracts_case_parties_and_order_date() -> None:
    facts = fields(
        extract_for(
            "COURT ORDER\nCase ID: CIV-2026-14\nClaimant: ABC Industries\n"
            "Respondent: XYZ Traders\nOrder Date: 2026-08-05",
            "court_order",
        )
    )

    assert facts["case_id"]["normalized_value"] == "CIV-2026-14"
    assert facts["claimant"]["normalized_value"] == "ABC Industries"
    assert facts["respondent"]["normalized_value"] == "XYZ Traders"
    assert facts["order_date"]["normalized_value"] == "2026-08-05"


def test_claim_statement_extracts_claimants_and_claimed_amount() -> None:
    facts = fields(
        extract_for(
            "STATEMENT OF CLAIM\nClaimant: ABC Industries\nRespondent: XYZ Traders\n"
            "Claimed Amount: INR 5,00,000\nClaim Description: Unpaid balance",
            "claim_statement",
        )
    )

    assert facts["claimant"]["normalized_value"] == "ABC Industries"
    assert facts["respondent"]["normalized_value"] == "XYZ Traders"
    assert facts["claimed_amount"]["normalized_value"] == 500000
    assert facts["claim_description"]["normalized_value"] == "Unpaid balance"


def test_email_extracts_sender_recipient_date_and_subject() -> None:
    facts = fields(
        extract_for(
            "From: sender@example.test\nTo: recipient@example.test\n"
            "Sent: 5 August 2026\nSubject: Payment status",
            "email",
        )
    )

    assert facts["sender"]["normalized_value"] == "sender@example.test"
    assert facts["recipient"]["normalized_value"] == "recipient@example.test"
    assert facts["email_date"]["normalized_value"] == "2026-08-05"
    assert facts["subject"]["normalized_value"] == "Payment status"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("INR 5,00,000", 500000), ("Rs. 5,00,000", 500000), ("₹5,00,000", 500000)],
)
def test_amount_normalization(amount: str, expected: int) -> None:
    facts = fields(extract_for(f"Contract Amount: {amount}", "contract"))

    assert facts["contract_amount"]["value"] == amount
    assert facts["contract_amount"]["normalized_value"] == expected
    assert facts["contract_amount"]["currency"] == "INR"


@pytest.mark.parametrize(
    ("date_text", "expected"),
    [
        ("5 August 2026", "2026-08-05"),
        ("05 Aug 2026", "2026-08-05"),
        ("2026-08-05", "2026-08-05"),
    ],
)
def test_date_normalization(date_text: str, expected: str) -> None:
    facts = fields(extract_for(f"Delivery Date: {date_text}", "contract"))

    assert facts["delivery_date"]["normalized_value"] == expected


def test_facts_preserve_document_page_quote_and_confidence() -> None:
    document = make_document(
        "Seller: ABC Industries\nDelivery Date: 5 August 2026",
        document_type="contract",
        document_id="D-PROV",
        page_number=3,
    )
    classification = DocumentClassificationResult(
        document_type="contract",
        confidence=0.9,
        matched_signals=["contract"],
    )

    result = extract_facts(document, classification)

    assert result.document_id == "D-PROV"
    assert result.fact_count == len(result.facts)
    for fact in result.facts:
        assert fact.document_id == "D-PROV"
        assert fact.page == 3
        assert fact.quote in document.pages[0].text
        assert 0 <= fact.confidence <= 1


def test_general_note_does_not_invent_facts() -> None:
    document = make_document(
        "Hello. This is a general note.",
        document_type="other",
    )

    result = extract_facts(document)

    assert result.document_type == "other"
    assert result.facts == []


def test_api_extracts_facts_from_existing_document() -> None:
    document = make_document(
        "COMMERCIAL PAYMENT AGREEMENT\nSeller: ABC Industries\n"
        "Buyer: XYZ Traders\nContract Amount: INR 500000\n"
        "Delivery Date: 5 August 2026\nPayment Due Date: 10 August 2026",
        document_type="contract",
    )

    response = client.post(
        "/api/documents/extract-facts",
        json={"document": document.model_dump()},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["document_type"] == "contract"
    assert result["fact_count"] >= 5
    seller = next(fact for fact in result["facts"] if fact["field"] == "seller")
    assert seller["document_id"] == "D001"
    assert seller["page"] == 1
    assert seller["quote"] == "Seller: ABC Industries"


def test_api_rejects_empty_document_text() -> None:
    document = make_document(" \n ", document_type="other")
    response = client.post(
        "/api/documents/extract-facts",
        json={"document": document.model_dump()},
    )

    assert response.status_code == 400
    assert "no text" in response.json()["detail"]


def test_api_rejects_invalid_document_payload() -> None:
    response = client.post(
        "/api/documents/extract-facts",
        json={"document": {"document_id": "D001", "pages": []}},
    )

    assert response.status_code == 422


def test_existing_sample_pdf_runs_extraction_classification_and_fact_pipeline() -> None:
    with pymupdf.open(SAMPLE_PDF) as pdf:
        pages = [
            DocumentPage(
                page=index,
                text=page.get_text("text"),
                extraction_method="text",
            )
            for index, page in enumerate(pdf, start=1)
        ]
    document = DocumentExtractionResult(
        document_id="D-SAMPLE",
        filename=SAMPLE_PDF.name,
        page_count=len(pages),
        pages=pages,
    )

    classification = classify_document("\n".join(page.text for page in pages))
    result = extract_facts(document, classification)
    facts = fields([fact.model_dump() for fact in result.facts])

    assert classification.document_type == "contract"
    assert result.document_type == "contract"
    assert facts["seller"]["normalized_value"] == "ABC Industries"
    assert facts["buyer"]["normalized_value"] == "XYZ Traders"
    assert facts["contract_amount"]["normalized_value"] == 500000
    assert facts["delivery_date"]["normalized_value"] == "2026-08-05"
    assert facts["payment_due_date"]["normalized_value"] == "2026-08-10"