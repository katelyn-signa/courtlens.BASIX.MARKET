from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReviewStatus, WorkflowAction
from app.schemas.common import ORMModel


class FindingRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["conflict", "rule_result", "evidence"]
    id: str = Field(min_length=1, max_length=60)


class ReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_run_id: Optional[str] = None
    reviewer_id: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=10000)
    reviewed_finding_refs: list[FindingRef] = Field(default_factory=list, max_length=500)


class ReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Optional[ReviewStatus] = None
    notes: Optional[str] = Field(default=None, max_length=10000)
    workflow_action: Optional[WorkflowAction] = None
    reviewer_id: Optional[str] = Field(default=None, max_length=100)
    reviewed_finding_refs: Optional[list[FindingRef]] = Field(default=None, max_length=500)


class InformationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_text: str = Field(min_length=1, max_length=5000)


class ReviewRead(ORMModel):
    id: str
    case_id: str
    analysis_run_id: Optional[str]
    reviewer_id: Optional[str]
    status: ReviewStatus
    notes: Optional[str]
    workflow_action: WorkflowAction
    reviewed_finding_refs: list[Any]
    additional_evidence_requested: bool
    additional_information_request: Optional[str]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    created_by: Optional[str]
    notice: str = ("Human review record. A completed review is a workflow state, "
                   "not a court order or a grant/refusal of bail.")
