from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.conflict import Conflict
from app.schemas.document_classification import DocumentType
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact

PartyRole = Literal["seller", "buyer", "claimant", "respondent", "sender", "recipient", "other"]
CaseSignalType = Literal[
    "no_conflicts_detected",
    "conflicts_detected",
    "evidence_gaps_present",
    "unsupported_claims_present",
    "requires_review",
]


class CaseParty(BaseModel):
    role: PartyRole
    name: str = Field(min_length=1)


class CaseMetadata(BaseModel):
    case_id: str
    case_title: str | None = None
    case_type: str | None = None
    parties: list[CaseParty] = Field(default_factory=list)
    created_at: datetime | None = None
    source: str | None = None


class CaseDocumentReference(BaseModel):
    document_id: str
    filename: str | None = None
    document_type: DocumentType | None = None
    source_type: str | None = None
    page_count: int | None = Field(default=None, ge=0)


class CaseIntakeRequest(BaseModel):
    case_id: str | None = None
    case_title: str | None = None
    case_type: str | None = None
    parties: list[CaseParty] | None = None
    created_at: datetime | None = None
    source: str | None = None
    documents: list[CaseDocumentReference] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[EvidenceGap] = Field(default_factory=list)


class CaseIntake(BaseModel):
    metadata: CaseMetadata
    documents: list[CaseDocumentReference]
    facts: list[ExtractedFact]
    evidence: list[Evidence]
    claims: list[ExtractedClaim]
    conflicts: list[Conflict]
    gaps: list[EvidenceGap]


class CaseSummaryCounts(BaseModel):
    document_count: int = Field(ge=0)
    fact_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    evidence_gap_count: int = Field(ge=0)


class CaseStatusSignal(BaseModel):
    signal: CaseSignalType
    reason: str


class CaseTimelineCandidate(BaseModel):
    date: date
    event_type: str
    description: str
    source_document_id: str | None = None
    filename: str | None = None
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    fact_id: str
    evidence_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class CaseIntakeResult(BaseModel):
    case: CaseIntake
    counts: CaseSummaryCounts
    status_signals: list[CaseStatusSignal]
    timeline_candidates: list[CaseTimelineCandidate]