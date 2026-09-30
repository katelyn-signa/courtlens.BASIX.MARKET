from typing import Literal

from pydantic import BaseModel


class DocumentPage(BaseModel):
    page: int
    text: str
    extraction_method: Literal["text", "ocr"]


class DocumentExtractionResult(BaseModel):
    document_id: str
    filename: str
    page_count: int
    pages: list[DocumentPage]