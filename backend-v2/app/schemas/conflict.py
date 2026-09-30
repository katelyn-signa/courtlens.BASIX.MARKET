from datetime import datetime
from typing import Any, Optional

from app.models.enums import (ConflictType, ResolutionStatus, ReviewSignal, RuleEvaluationStatus,
                              Severity)
from app.schemas.common import ORMModel


class ConflictRead(ORMModel):
    id: str
    case_id: str
    analysis_run_id: str
    conflict_type: ConflictType
    description: str
    severity: Optional[Severity]
    related_evidence_ids: list[str]
    related_document_ids: list[str]
    conflicting_values: Optional[list[Any]]
    missing_information: Optional[str]
    resolution_status: ResolutionStatus
    resolution_notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    agent_name: Optional[str]
    agent_version: Optional[str]
    is_simulated: bool


class RuleResultRead(ORMModel):
    id: str
    case_id: str
    analysis_run_id: str
    rule_id: str
    rule_version: str
    evaluation_status: RuleEvaluationStatus
    input_evidence_ids: list[str]
    review_signal: Optional[ReviewSignal]
    explanation: str
    missing_prerequisites: list[str]
    limitations: list[str]
    evaluated_at: datetime
    output_schema_version: str
    agent_name: Optional[str]
    agent_version: Optional[str]
    is_simulated: bool
    notice: str = "Rule evaluation output for human review. Not a legal or judicial decision."
