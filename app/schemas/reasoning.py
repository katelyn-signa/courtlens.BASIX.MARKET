from typing import Any, Literal

from pydantic import BaseModel, Field

ConfidenceLevel = Literal["low", "medium", "high"]
SemanticObservationType = Literal[
    "payment_obligation",
    "payment_record",
    "payment_claim",
    "claim_statement",
    "date_event",
    "party_identity",
    "conflict",
    "evidence_gap",
]
ReasoningStepType = Literal[
    "evidence_observed",
    "conflict_identified",
    "rule_evaluated",
    "rule_triggered",
    "gap_identified",
    "documents_analyzed",
    "facts_extracted",
    "source_authority_evaluated",
    "source_ranked",
    "recommendation_generated",
    "human_review_required",
]


class ReasoningEvidenceReference(BaseModel):
    evidence_id: str
    document_id: str
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    relevance: float = Field(ge=0.0, le=1.0)


class SemanticObservation(BaseModel):
    observation_id: str
    observation_type: SemanticObservationType
    statement: str
    field: str | None = None
    normalized_value: str | int | float | None = None
    amount: int | float | None = None
    currency: str | None = None
    full_payment_claim: bool = False
    source_supported: bool = False
    event_type: str | None = None
    source_type: str | None = None
    source_authority: int | None = Field(default=None, ge=0)
    conflict_type: str | None = None
    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    quote: str | None = None
    fact_id: str | None = None
    claim_id: str | None = None
    conflict_id: str | None = None
    gap_id: str | None = None
    severity: Literal["low", "medium", "high"] | None = None
    evidence_refs: list[ReasoningEvidenceReference] = Field(default_factory=list)


class SemanticInterpretation(BaseModel):
    observations: list[SemanticObservation]
    adapter: Literal["deterministic_semantic_adapter"] = "deterministic_semantic_adapter"


class RuleEvaluation(BaseModel):
    rule_id: str
    rule_name: str
    version: str
    description: str
    condition: str
    triggered: bool
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str
    result: dict[str, Any] = Field(default_factory=dict)


class WhyExplanation(BaseModel):
    recommendation: str
    evidence: str
    rule: str
    reason: str


class ReasoningStep(BaseModel):
    step_id: str
    step_type: ReasoningStepType
    description: str
    evidence_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)


class ReasoningResult(BaseModel):
    reasoning_id: str
    status: Literal["completed"] = "completed"
    recommendation: str
    confidence: ConfidenceLevel
    evidence_support_score: float = Field(ge=0.0, le=1.0)
    semantic_observations: list[SemanticObservation]
    evidence_used: list[ReasoningEvidenceReference]
    rules_evaluated: list[RuleEvaluation]
    reasoning_steps: list[ReasoningStep]
    unresolved_questions: list[str] = Field(default_factory=list)
    human_review_required: bool
    why_explanation: WhyExplanation | None = None