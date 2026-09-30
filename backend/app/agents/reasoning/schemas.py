"""Input and output contracts for the reasoning API."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.rules.schemas import EvidenceGap, RuleEvaluation


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(ContractModel):
    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    fact_type: str = Field(min_length=1)
    value: Any
    source_quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_type: Literal[
        "direct_documentary",
        "testimony",
        "indirect",
        "other",
    ]


class Conflict(ContractModel):
    conflict_id: str = Field(min_length=1)
    fact_type: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=2)
    description: str = Field(min_length=1)
    severity: Literal["low", "medium", "high", "critical"]

    @field_validator("evidence_ids")
    @classmethod
    def require_distinct_evidence_ids(cls, evidence_ids: list[str]) -> list[str]:
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("conflict evidence_ids must be distinct")
        return evidence_ids


class FactRecord(ContractModel):
    """A candidate factual claim supplied upstream, not independently verified."""

    fact_id: str | None = Field(default=None, min_length=1)
    fact_type: str = Field(min_length=1)
    value: Any
    evidence_ids: list[str] = Field(default_factory=list)
    epistemic_status: Literal["evidence_reported"] = "evidence_reported"


class ReasoningRequest(ContractModel):
    case_id: str = Field(min_length=1)
    analysis_version: int = Field(default=1, ge=1)
    facts: list[FactRecord] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    rules: list[str] = Field(default_factory=list)
    question: str = Field(min_length=1)
    critical_fact_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_references(self) -> "ReasoningRequest":
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("evidence_id values must be unique")
        fact_ids = [item.fact_id for item in self.facts if item.fact_id is not None]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact_id values must be unique")
        gap_ids = [item.gap_id for item in self.evidence_gaps]
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("gap_id values must be unique")
        if len(self.rules) != len(set(self.rules)):
            raise ValueError("rules must not contain duplicate rule IDs")

        for fact in self.facts:
            for evidence_id in fact.evidence_ids:
                if evidence_id not in evidence_by_id:
                    raise ValueError(f"fact {fact.fact_id or fact.fact_type} references unknown evidence {evidence_id}")
                if evidence_by_id[evidence_id].fact_type != fact.fact_type:
                    raise ValueError("fact evidence must match its fact_type")

        for conflict in self.conflicts:
            unknown_ids = set(conflict.evidence_ids) - evidence_by_id.keys()
            if unknown_ids:
                raise ValueError(
                    f"conflict {conflict.conflict_id} references unknown evidence: "
                    f"{', '.join(sorted(unknown_ids))}"
                )
            mismatched_ids = [
                evidence_id
                for evidence_id in conflict.evidence_ids
                if evidence_by_id[evidence_id].fact_type != conflict.fact_type
            ]
            if mismatched_ids:
                raise ValueError(
                    f"conflict {conflict.conflict_id} evidence must match its fact_type"
                )

        if len(self.critical_fact_types) != len(set(self.critical_fact_types)):
            raise ValueError("critical_fact_types values must be unique")
        return self


class RuleExecution(ContractModel):
    rule_id: str
    rule_name: str
    input_evidence_ids: list[str]
    condition: str
    result: str
    explanation: str


class InferenceRecord(ContractModel):
    fact_type: str
    assessment: Literal[
        "strongly_supported", "uncertain", "conflicting", "insufficient_evidence"
    ]
    explanation: str
    evidence_ids: list[str]
    rule_ids: list[str]
    selected_value: Any | None = None


class ReasoningTraceStep(ContractModel):
    step: int = Field(ge=1)
    type: Literal[
        "fact", "evidence", "evidence_gap", "rule", "conflict", "inference", "uncertainty"
    ]
    description: str
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    evidence_gap_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    rule_id: str | None = None


class ReasoningResponse(ContractModel):
    case_id: str
    analysis_version: int = 1
    status: Literal["supported", "conflicting", "insufficient_evidence"]
    reasoning_summary: str
    facts_considered: list[FactRecord]
    supporting_evidence: list[Evidence]
    contradicting_evidence: list[Evidence]
    conflicts: list[Conflict]
    rules_fired: list[RuleExecution]
    inferences: list[InferenceRecord]
    reasoning_trace: list[ReasoningTraceStep]
    missing_evidence: list[str]
    uncertainties: list[str]
    assumptions: list[str]
    what_could_change_reasoning: list[str]
    reasoning_steps: list[ReasoningTraceStep] = Field(default_factory=list)
    rules_used: list[str] = Field(default_factory=list)
    rule_evaluations: list[RuleEvaluation] = Field(default_factory=list)
    conclusion: str = ""
    needs_human_review: bool = True
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="A coarse system assessment indicator, not a probability or legal certainty.",
    )