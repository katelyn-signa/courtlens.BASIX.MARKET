from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.evidence import EvidenceAnalysisResult, Evidence, ExtractedClaim
from app.schemas.facts import ExtractedFact, FactValue

ConflictType = Literal[
    "date_conflict",
    "amount_conflict",
    "party_conflict",
    "case_id_conflict",
    "obligation_conflict",
    "claim_evidence_conflict",
    "timeline_conflict",
    "generic_fact_conflict",
]
ConflictSeverity = Literal["low", "medium", "high"]


class ConflictingValue(BaseModel):
    value: FactValue
    normalized_value: FactValue
    fact_id: str
    evidence_id: str
    document_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)


class Conflict(BaseModel):
    conflict_id: str
    conflict_type: ConflictType
    fact_type: str
    event_type: str | None = None
    description: str
    severity: ConflictSeverity
    status: Literal["open"] = "open"
    conflicting_values: list[ConflictingValue] = Field(min_length=2)
    evidence_ids: list[str]
    document_ids: list[str]
    source_pages: list[int]
    quotes: list[str]
    claim_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    detected_by: Literal["deterministic_conflict_engine"] = "deterministic_conflict_engine"


class ConflictDetectionRequest(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    analyses: list[EvidenceAnalysisResult] = Field(default_factory=list)


class ConflictDetectionResult(BaseModel):
    conflicts: list[Conflict]
    conflict_count: int = Field(ge=0)