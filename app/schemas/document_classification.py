from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.document import DocumentExtractionResult

DocumentType = Literal[
    "contract",
    "purchase_order",
    "invoice",
    "payment_record",
    "delivery_receipt",
    "email",
    "court_order",
    "advocate_note",
    "party_document",
    "claim_statement",
    "other",
]


class DocumentClassificationRequest(BaseModel):
    text: str | None = None
    document: DocumentExtractionResult | None = None

    @model_validator(mode="after")
    def require_one_source(self) -> "DocumentClassificationRequest":
        if (self.text is None) == (self.document is None):
            raise ValueError("Provide exactly one of 'text' or 'document'.")
        return self


class DocumentClassificationResult(BaseModel):
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    matched_signals: list[str]