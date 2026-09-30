"""JSON-serializable request and audit-result contracts for symbolic rules."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleFact(RuleModel):
    fact_id: str | None = Field(default=None, min_length=1)
    fact_type: str = Field(min_length=1)
    value: Any
    evidence_ids: list[str] = Field(default_factory=list)


class RuleEvidence(RuleModel):
    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    fact_type: str = Field(min_length=1)
    value: Any
    source_quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_type: Literal["direct_documentary", "testimony", "indirect", "other"]


class RuleConflict(RuleModel):
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


class RuleExecution(RuleModel):
    rule_id: str
    rule_name: str
    input_evidence_ids: list[str]
    condition: str
    result: str
    explanation: str


class EvidenceGap(RuleModel):
    gap_id: str = Field(min_length=1)
    fact_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_evidence: str = Field(min_length=1)


class RuleEngineRequest(RuleModel):
    facts: list[RuleFact] = Field(default_factory=list)
    evidence: list[RuleEvidence] = Field(default_factory=list)
    conflicts: list[RuleConflict] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    critical_fact_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "RuleEngineRequest":
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        if len(evidence_by_id) != len(self.evidence):
            raise ValueError("evidence_id values must be unique")
        fact_ids = [item.fact_id for item in self.facts if item.fact_id is not None]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact_id values must be unique")
        conflict_ids = [item.conflict_id for item in self.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("conflict_id values must be unique")
        gap_ids = [item.gap_id for item in self.evidence_gaps]
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("gap_id values must be unique")

        for fact in self.facts:
            for evidence_id in fact.evidence_ids:
                if evidence_id not in evidence_by_id:
                    raise ValueError(f"fact {fact.fact_id} references unknown evidence {evidence_id}")
                if evidence_by_id[evidence_id].fact_type != fact.fact_type:
                    raise ValueError(f"fact {fact.fact_id} references evidence of another fact_type")
        for conflict in self.conflicts:
            for evidence_id in conflict.evidence_ids:
                if evidence_id not in evidence_by_id:
                    raise ValueError(
                        f"conflict {conflict.conflict_id} references unknown evidence {evidence_id}"
                    )
                if evidence_by_id[evidence_id].fact_type != conflict.fact_type:
                    raise ValueError(
                        f"conflict {conflict.conflict_id} references evidence of another fact_type"
                    )
        return self


class FactAssessment(RuleModel):
    fact_type: str
    values: list[Any]
    evidence_ids: list[str]
    fact_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    status: Literal[
        "strongly_supported", "uncertain", "conflicting", "insufficient_evidence"
    ]
    selected_value: Any | None = None
    explanation: str
    rule_ids: list[str]


class RuleEvaluation(RuleModel):
    rule_id: str
    rule_name: str
    description: str
    conditions_checked: list[str]
    condition_met: bool
    fired: bool
    input_fact_ids: list[str]
    input_evidence_ids: list[str]
    input_conflict_ids: list[str]
    input_gap_ids: list[str]
    result: str
    explanation: str
    missing_evidence: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class RuleEngineResult(RuleModel):
    assessments: list[FactAssessment]
    rules_evaluated: list[RuleEvaluation]
    rules_fired: list[RuleExecution]
    conflicts: list[RuleConflict]
    missing_evidence: list[str]
    uncertainties: list[str]