from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.document import DocumentExtractionResult
from app.schemas.document_classification import (
    DocumentClassificationResult,
    DocumentType,
)

FactType = Literal[
    "party",
    "identity",
    "financial",
    "date",
    "obligation",
    "claim",
    "communication",
]
FactValue = str | int | float


class ExtractedFact(BaseModel):
    fact_id: str
    fact_type: FactType
    field: str
    value: str
    normalized_value: FactValue
    document_id: str | None = None
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    currency: str | None = None
    extraction_method: Literal["text", "ocr"] | None = None


class FactExtractionRequest(BaseModel):
    document: DocumentExtractionResult
    classification: DocumentClassificationResult | None = None


class FactExtractionResult(BaseModel):
    document_type: DocumentType
    document_id: str | None = None
    fact_count: int = Field(ge=0)
    facts: list[ExtractedFact]