from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services.document_classifier import classify_document

client = TestClient(app)

CLASSIFICATION_CASES = [
    (
        "contract",
        "COMMERCIAL PAYMENT AGREEMENT Seller: ABC Industries Buyer: XYZ Traders "
        "Contract Amount: INR 500000 Delivery Date: 5 August 2026 "
        "Payment Due Date: 10 August 2026",
    ),
    (
        "invoice",
        "TAX INVOICE Invoice Number: INV-1042 Bill To: ABC Industries "
        "Total Amount: INR 500000",
    ),
    (
        "purchase_order",
        "PURCHASE ORDER PO Number: PO-55 Order Quantity: 20 units",
    ),
    (
        "payment_record",
        "BANK TRANSACTION Payment Reference: TX-771 Amount Paid: INR 500000",
    ),
    (
        "delivery_receipt",
        "DELIVERY RECEIPT Goods Received: 20 units Received By: ABC Industries "
        "Delivery Date: 5 August 2026",
    ),
    (
        "email",
        "From: clerk@example.test To: buyer@example.test Subject: Delivery "
        "Sent: 5 August 2026 Dear Buyer, the goods arrived.",
    ),
    (
        "court_order",
        "IN THE COURT OF JUSTICE Judge: A. Smith Petitioner: ABC Industries "
        "Respondent: XYZ Traders The court hereby ordered the matter disposed.",
    ),
    (
        "claim_statement",
        "STATEMENT OF CLAIM Claimant alleges a disputed amount of INR 500000. "
        "Relief sought: payment of the disputed amount.",
    ),
    ("other", "A short note describing ordinary daily events and observations."),
]


@pytest.mark.parametrize(("expected_type", "text"), CLASSIFICATION_CASES)
def test_classifies_document_types(expected_type: str, text: str) -> None:
    result = classify_document(text)

    assert result.document_type == expected_type
    assert 0 <= result.confidence <= 1
    if expected_type != "other":
        assert result.matched_signals


def test_unknown_document_has_no_matched_signals() -> None:
    result = classify_document("A short note describing ordinary daily events.")

    assert result.document_type == "other"
    assert result.matched_signals == []


def test_api_classifies_extracted_text() -> None:
    response = client.post(
        "/api/documents/classify",
        json={"text": "TAX INVOICE Invoice Number: INV-1042 Bill To: XYZ Traders"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["document_type"] == "invoice"
    assert 0 <= result["confidence"] <= 1
    assert "tax invoice" in result["matched_signals"]


def test_api_classifies_existing_extraction_result() -> None:
    response = client.post(
        "/api/documents/classify",
        json={
            "document": {
                "document_id": "D001",
                "filename": "agreement.pdf",
                "page_count": 1,
                "pages": [
                    {
                        "page": 1,
                        "text": "COMMERCIAL PAYMENT AGREEMENT Contract Amount: INR 500000",
                        "extraction_method": "text",
                    }
                ],
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["document_type"] == "contract"


def test_api_returns_other_for_unknown_document() -> None:
    response = client.post(
        "/api/documents/classify",
        json={"text": "A note about the weather and an ordinary workday."},
    )

    assert response.status_code == 200
    assert response.json()["document_type"] == "other"


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "   \n\t"}])
def test_api_rejects_empty_text(payload: dict[str, str]) -> None:
    response = client.post("/api/documents/classify", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Document text must not be empty."


def test_api_rejects_missing_classification_input() -> None:
    response = client.post("/api/documents/classify", json={})

    assert response.status_code == 422