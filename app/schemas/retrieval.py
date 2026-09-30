from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.conflict import Conflict
from app.schemas.document import DocumentExtractionResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact, FactValue

RetrievalResultType = Literal[
    "fact",
    "evidence",
    "claim",
    "conflict",
    "evidence_gap",
    "document_passage",
]


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[EvidenceGap] = Field(default_factory=list)
    documents: list[DocumentExtractionResult] = Field(default_factory=list)


class CaseEvidenceSearchRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1)
    fact_id: str | None = None
    claim_id: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def require_search_target(self) -> "CaseEvidenceSearchRequest":
        if not self.query and not self.fact_id and not self.claim_id:
            raise ValueError("Provide query text, a fact_id, or a claim_id.")
        return self


class RetrievalResult(BaseModel):
    result_id: str
    result_type: RetrievalResultType
    score: float = Field(ge=0.0, le=1.0)
    title: str
    snippet: str
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    filename: str | None = None
    page: int | None = Field(default=None, ge=1)
    source_pages: list[int] = Field(default_factory=list)
    quote: str | None = None
    normalized_value: FactValue | None = None
    fact_id: str | None = None
    evidence_id: str | None = None
    claim_id: str | None = None
    conflict_id: str | None = None
    gap_id: str | None = None
    related_evidence_ids: list[str] = Field(default_factory=list)
    related_claim_ids: list[str] = Field(default_factory=list)
    related_conflict_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    extraction_method: Literal["text", "ocr"] | None = None


class RetrievalResponse(BaseModel):
    query: str
    results: list[RetrievalResult]
    total: int = Field(ge=0)