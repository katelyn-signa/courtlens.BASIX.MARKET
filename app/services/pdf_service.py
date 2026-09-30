from uuid import uuid4

import pymupdf

from app.schemas.document import DocumentExtractionResult, DocumentPage
from app.services.ocr_service import OcrServiceError, extract_ocr_text, is_usable_text


class PdfExtractionError(ValueError):
    """Raised when a PDF cannot be opened or completely extracted."""


def extract_pdf(pdf_bytes: bytes, filename: str) -> DocumentExtractionResult:
    if not pdf_bytes:
        raise PdfExtractionError("The uploaded PDF is empty.")

    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise PdfExtractionError("The uploaded file is not a valid or readable PDF.") from exc

    try:
        with document:
            page_count = document.page_count
            if page_count == 0:
                raise PdfExtractionError("The PDF contains no pages.")

            pages = []
            for page_number, page in enumerate(document, start=1):
                try:
                    text = page.get_text("text")
                except (RuntimeError, ValueError) as exc:
                    raise PdfExtractionError(
                        f"Could not extract text from page {page_number}."
                    ) from exc

                if is_usable_text(text):
                    extraction_method = "text"
                else:
                    try:
                        text = extract_ocr_text(page)
                    except OcrServiceError as exc:
                        raise PdfExtractionError(
                            f"Could not OCR page {page_number}: {exc}"
                        ) from exc
                    extraction_method = "ocr"

                pages.append(
                    DocumentPage(
                        page=page_number,
                        text=text,
                        extraction_method=extraction_method,
                    )
                )

            return DocumentExtractionResult(
                document_id=str(uuid4()),
                filename=filename,
                page_count=page_count,
                pages=pages,
            )
    except PdfExtractionError:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise PdfExtractionError("The PDF could not be completely read.") from exc