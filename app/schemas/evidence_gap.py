from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.conflict import Conflict
from app.schemas.document_classification import DocumentClassificationResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.facts import ExtractedFact

EvidenceGapType = Literal[
    "missing_contract",
    "missing_invoice",
    "missing_payment_proof",
    "missing_delivery_proof",
    "missing_party_identity",
    "missing_case_identifier",
    "missing_supporting_document",
    "missing_verification",
    "unresolved_conflict",
    "unsupported_claim",
    "insufficient_evidence",
    "generic_evidence_gap",
]
GapImportance = Literal["low", "medium", "high"]


class EvidenceGap(BaseModel):
    gap_id: str
    gap_type: EvidenceGapType
    description: str
    importance: GapImportance
    status: Literal["open"] = "open"
    related_fact_types: list[str] = Field(default_factory=list)
    related_claim_ids: list[str] = Field(default_factory=list)
    related_evidence_ids: list[str] = Field(default_factory=list)
    related_conflict_ids: list[str] = Field(default_factory=list)
    related_document_ids: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    suggested_evidence: list[str] = Field(default_factory=list)
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    detected_by: Literal["deterministic_evidence_gap_engine"] = (
        "deterministic_evidence_gap_engine"
    )


class EvidenceGapDetectionRequest(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    classification: DocumentClassificationResult | None = None


class EvidenceGapDetectionResult(BaseModel):
    gaps: list[EvidenceGap]
    gap_count: int = Field(ge=0)