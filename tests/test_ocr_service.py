from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import pdf_service
from app.services.ocr_service import (
    DEFAULT_TESSDATA_PATH,
    OcrServiceError,
    get_tessdata_path,
    is_usable_text,
)
from app.services.pdf_service import PdfExtractionError, extract_pdf

client = TestClient(app)
DOCUMENTS_DIR = Path(__file__).parent.parent / "sample_data" / "documents"
NORMAL_PDF = DOCUMENTS_DIR / "fictional_payment_agreement.pdf"
SCANNED_PDF = DOCUMENTS_DIR / "fictional_scanned_ocr.pdf"


def test_normal_text_page_does_not_invoke_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_ocr(page: pymupdf.Page) -> str:
        raise AssertionError("OCR must not run for usable normal text.")

    monkeypatch.setattr(pdf_service, "extract_ocr_text", unexpected_ocr)
    result = extract_pdf(NORMAL_PDF.read_bytes(), filename=NORMAL_PDF.name)

    assert [page.extraction_method for page in result.pages] == ["text", "text"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("   \n", False), ("--- !!!", False), ("Invoice 500000", True)],
)
def test_text_usability_heuristic(text: str, expected: bool) -> None:
    assert is_usable_text(text) is expected


def test_image_only_page_runs_real_ocr_and_preserves_page_number() -> None:
    with pymupdf.open(SCANNED_PDF) as source_document:
        assert source_document[1].get_text().strip() == ""

    result = extract_pdf(SCANNED_PDF.read_bytes(), filename=SCANNED_PDF.name)

    assert result.page_count == 2
    assert [page.page for page in result.pages] == [1, 2]
    assert result.pages[0].extraction_method == "text"
    assert result.pages[1].extraction_method == "ocr"
    assert is_usable_text(result.pages[1].text)
    normalized_ocr = " ".join(result.pages[1].text.split())
    assert "COURTLENS OCR TEST" in normalized_ocr
    assert "ABC Industries" in normalized_ocr
    assert "XYZ Traders" in normalized_ocr
    assert "INR 500000" in normalized_ocr
    assert "5 August 2026" in normalized_ocr


def test_invalid_tessdata_configuration_has_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "missing-tessdata"))

    with pytest.raises(OcrServiceError, match="TESSDATA_PREFIX"):
        get_tessdata_path()


def test_pdf_extraction_reports_tessdata_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "missing-tessdata"))

    with pytest.raises(PdfExtractionError, match="TESSDATA_PREFIX"):
        extract_pdf(SCANNED_PDF.read_bytes(), filename=SCANNED_PDF.name)


def test_default_tessdata_path_matches_documented_configuration() -> None:
    assert DEFAULT_TESSDATA_PATH == r"C:\Program Files\Tesseract-OCR\tessdata"


def test_extract_endpoint_uses_ocr_for_scanned_page() -> None:
    response = client.post(
        "/api/documents/extract",
        files={
            "file": (
                SCANNED_PDF.name,
                SCANNED_PDF.read_bytes(),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    result = response.json()
    assert result["filename"] == SCANNED_PDF.name
    assert result["page_count"] == 2
    assert [page["page"] for page in result["pages"]] == [1, 2]
    assert [page["extraction_method"] for page in result["pages"]] == ["text", "ocr"]
    assert "COURTLENS OCR TEST" in result["pages"][1]["text"]