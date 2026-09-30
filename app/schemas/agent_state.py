from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.analysis import CaseAnalysisDocumentInput, DocumentAnalysisResult
from app.schemas.case import CaseDocumentReference, CaseMetadata, CaseParty
from app.schemas.conflict import Conflict
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact
from app.schemas.reasoning import ReasoningResult

AgentEventType = Literal[
    "CASE_CREATED",
    "DOCUMENT_ADDED",
    "DOCUMENT_CHANGED",
    "FACTS_EXTRACTED",
    "EVIDENCE_ADDED",
    "EVIDENCE_VERIFICATION_UPDATED",
    "CONFLICT_DETECTED",
    "CONFLICT_RESOLVED",
    "EVIDENCE_GAP_DETECTED",
    "EVIDENCE_GAP_RESOLVED",
    "REASONING_COMPLETED",
    "REASONING_UPDATED",
    "HUMAN_CHALLENGE_RECEIVED",
    "HUMAN_REVIEW_RECORDED",
    "HUMAN_OVERRIDE_APPLIED",
    "CASE_STATE_UPDATED",
]


class CaseChallengeRequest(BaseModel):
    target_id: str = Field(min_length=1)
    target_document_id: str | None = None
    challenge_type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class CaseChallenge(BaseModel):
    challenge_id: str
    target_id: str
    target_document_id: str | None = None
    challenge_type: str
    message: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    timestamp: datetime


class CaseHumanReviewRequest(BaseModel):
    decision: Literal["confirmed", "needs_more_evidence"]
    notes: str = Field(min_length=1)


class CaseHumanReview(BaseModel):
    review_id: str
    decision: Literal["confirmed", "needs_more_evidence", "overridden"]
    notes: str
    reasoning_id: str | None = None
    timestamp: datetime


class CaseOverrideRequest(BaseModel):
    recommendation: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CaseOverride(BaseModel):
    override_id: str
    previous_recommendation: str
    recommendation: str
    reason: str
    reasoning_id: str
    timestamp: datetime


class CaseWhatIfRequest(BaseModel):
    excluded_document_ids: list[str] = Field(default_factory=list)
    excluded_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_exclusions(self) -> "CaseWhatIfRequest":
        if not self.excluded_document_ids and not self.excluded_evidence_ids:
            raise ValueError("Specify at least one document or evidence ID to exclude.")
        return self


class CaseWhatIfResponse(BaseModel):
    case_id: str
    base_version: int
    excluded_document_ids: list[str]
    excluded_evidence_ids: list[str]
    simulated_reasoning: ReasoningResult
    state_persisted: Literal[False] = False


class AgentEvent(BaseModel):
    event_id: str
    case_id: str
    timestamp: datetime
    event_type: AgentEventType
    source: str
    description: str
    affected_ids: list[str] = Field(default_factory=list)
    previous_version: int
    new_version: int


class CaseAgentState(BaseModel):
    case_id: str
    version: int = Field(ge=1)
    metadata: CaseMetadata
    documents: list[CaseDocumentReference] = Field(default_factory=list)
    document_analyses: list[DocumentAnalysisResult] = Field(default_factory=list)
    document_fingerprints: dict[str, str] = Field(default_factory=dict)
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    reasoning_results: list[ReasoningResult] = Field(default_factory=list)
    challenges: list[CaseChallenge] = Field(default_factory=list)
    human_reviews: list[CaseHumanReview] = Field(default_factory=list)
    overrides: list[CaseOverride] = Field(default_factory=list)
    rules_triggered: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    challenged_ids: list[str] = Field(default_factory=list)
    verified_evidence_ids: list[str] = Field(default_factory=list)
    agent_events: list[AgentEvent] = Field(default_factory=list)


class AgentStartRequest(BaseModel):
    case_title: str | None = None
    case_type: str | None = None
    parties: list[CaseParty] | None = None
    source: str | None = "case_agent"
    documents: list[CaseAnalysisDocumentInput] = Field(default_factory=list)
    verified_evidence_ids: list[str] = Field(default_factory=list)


class AgentUpdateRequest(BaseModel):
    source: str | None = "case_agent"
    documents: list[CaseAnalysisDocumentInput] = Field(default_factory=list)
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    verified_evidence_ids: list[str] = Field(default_factory=list)


class CaseCounts(BaseModel):
    document_count: int
    fact_count: int
    evidence_count: int
    claim_count: int
    conflict_count: int
    evidence_gap_count: int


class CaseStateResponse(BaseModel):
    case_id: str
    version: int
    metadata: CaseMetadata
    counts: CaseCounts
    reasoning_summary: dict
    unresolved_questions: list[str]
    recent_events: list[AgentEvent]
    state: CaseAgentState


class CaseVersionSummary(BaseModel):
    version: int
    timestamp: datetime
    change_summary: str
    triggering_event: str


class CaseVersionsResponse(BaseModel):
    case_id: str
    versions: list[CaseVersionSummary]


class CaseEventsResponse(BaseModel):
    case_id: str
    events: list[AgentEvent]


class CaseVersionResponse(BaseModel):
    case_id: str
    version: int
    timestamp: datetime
    change_summary: str
    triggering_event: str
    state: CaseAgentState


class CaseStateDiff(BaseModel):
    case_id: str
    from_version: int
    to_version: int
    added_documents: list[str] = Field(default_factory=list)
    removed_documents: list[str] = Field(default_factory=list)
    changed_documents: list[str] = Field(default_factory=list)
    added_facts: list[str] = Field(default_factory=list)
    changed_facts: list[str] = Field(default_factory=list)
    added_evidence: list[str] = Field(default_factory=list)
    changed_evidence: list[str] = Field(default_factory=list)
    added_claims: list[str] = Field(default_factory=list)
    changed_claims: list[str] = Field(default_factory=list)
    verification_changes: list[str] = Field(default_factory=list)
    new_conflicts: list[str] = Field(default_factory=list)
    resolved_conflicts: list[str] = Field(default_factory=list)
    new_gaps: list[str] = Field(default_factory=list)
    resolved_gaps: list[str] = Field(default_factory=list)
    reasoning_changes: list[str] = Field(default_factory=list)
    human_review_changes: list[str] = Field(default_factory=list)
    override_changes: list[str] = Field(default_factory=list)


class AgentOperationResult(BaseModel):
    state: CaseAgentState
    changes: dict[str, list[str]]
    affected_evidence_ids: list[str] = Field(default_factory=list)
    affected_rule_ids: list[str] = Field(default_factory=list)
    reasoning_recomputed: bool