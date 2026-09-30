from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.pdf_service import PdfExtractionError, extract_pdf

client = TestClient(app)
SAMPLE_PDF = (
    Path(__file__).parent.parent
    / "sample_data"
    / "documents"
    / "fictional_payment_agreement.pdf"
)


def test_extract_pdf_preserves_pages_and_text() -> None:
    result = extract_pdf(SAMPLE_PDF.read_bytes(), filename=SAMPLE_PDF.name)

    assert result.filename == SAMPLE_PDF.name
    assert result.page_count == 2
    assert [page.page for page in result.pages] == [1, 2]
    assert [page.extraction_method for page in result.pages] == ["text", "text"]
    assert "COMMERCIAL PAYMENT AGREEMENT" in result.pages[0].text
    assert "ABC Industries" in result.pages[0].text
    assert "DELIVERY AND PAYMENT" not in result.pages[0].text
    assert "DELIVERY AND PAYMENT" in result.pages[1].text
    assert "5 August 2026" in result.pages[1].text


def test_empty_page_does_not_fail_extraction() -> None:
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    pdf_bytes = document.tobytes()
    document.close()

    result = extract_pdf(pdf_bytes, filename="blank-page.pdf")

    assert result.page_count == 2
    assert [page.page for page in result.pages] == [1, 2]
    assert result.pages[0].text == ""
    assert result.pages[1].text == ""
    assert [page.extraction_method for page in result.pages] == ["ocr", "ocr"]


def test_zero_page_pdf_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    class ZeroPageDocument:
        page_count = 0

        def __enter__(self) -> "ZeroPageDocument":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def __iter__(self):
            return iter(())

    monkeypatch.setattr(
        "app.services.pdf_service.pymupdf.open",
        lambda **kwargs: ZeroPageDocument(),
    )
    with pytest.raises(PdfExtractionError, match="no pages"):
        extract_pdf(b"pdf bytes", filename="empty-document.pdf")


@pytest.mark.parametrize("pdf_bytes", [b"", b"not a PDF"])
def test_empty_or_invalid_pdf_is_rejected(pdf_bytes: bytes) -> None:
    with pytest.raises(PdfExtractionError):
        extract_pdf(pdf_bytes, filename="invalid.pdf")


def test_extract_endpoint_returns_structured_result() -> None:
    response = client.post(
        "/api/documents/extract",
        files={
            "file": (
                SAMPLE_PDF.name,
                SAMPLE_PDF.read_bytes(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["document_id"]
    assert result["filename"] == SAMPLE_PDF.name
    assert result["page_count"] == 2
    assert [page["page"] for page in result["pages"]] == [1, 2]
    assert [page["extraction_method"] for page in result["pages"]] == ["text", "text"]
    assert "COMMERCIAL PAYMENT AGREEMENT" in result["pages"][0]["text"]
    assert "DELIVERY AND PAYMENT" in result["pages"][1]["text"]


def test_extract_endpoint_rejects_non_pdf_upload() -> None:
    response = client.post(
        "/api/documents/extract",
        files={"file": ("notes.txt", b"plain text, not a PDF", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file is not a valid or readable PDF."


def test_extract_endpoint_rejects_missing_file() -> None:
    response = client.post("/api/documents/extract")

    assert response.status_code == 422