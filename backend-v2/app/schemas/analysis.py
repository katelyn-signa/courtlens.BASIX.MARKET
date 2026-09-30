from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ReviewSignal, RunStatus, StageStatus, TriggerType
from app.schemas.common import ORMModel
from app.utils.identifiers import DOCUMENT, id_pattern


class AnalysisRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: Optional[list[str]] = Field(
        default=None, description="Specific document versions to analyse. Default: latest "
        "version of every document in the case.", max_length=500)
    requested_modules: Optional[list[str]] = Field(
        default=None, description="Subset of pipeline stages (dependencies are added automatically).")
    force: bool = Field(default=False, description="Create a new run even if an identical completed run exists.")
    reprocess_documents: bool = Field(default=False, description="Send already-PROCESSED documents to the document agent again.")
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=120)
    rule_config: Optional[dict[str, Any]] = None
    agent_config: Optional[dict[str, Any]] = None


class StageRead(ORMModel):
    id: str
    stage_name: str
    agent_key: str
    sequence: int
    required: bool
    status: StageStatus
    attempts: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_code: Optional[str]
    error_summary: Optional[str]
    warnings: list[Any]
    output_summary: dict[str, Any]
    agent_name: Optional[str]
    agent_version: Optional[str]
    is_simulated: bool
    output_run_id: Optional[str]
    carried_over: bool


class RunSummary(BaseModel):
    evidence_count: int = 0
    conflict_count: int = 0
    rule_result_count: int = 0
    review_signals: list[ReviewSignal] = Field(default_factory=list)
    analysis_outcome: Optional[ReviewSignal] = Field(
        default=None, description="ANALYSIS_INCOMPLETE when the run did not fully complete.")
    simulated_output: bool = False


class AnalysisRunRead(ORMModel):
    id: str
    case_id: str
    trigger_type: TriggerType
    status: RunStatus
    current_stage: Optional[str]
    requested_modules: list[str]
    options: dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_summary: Optional[str]
    diagnostics: dict[str, Any]
    parent_run_id: Optional[str]
    attempt_number: int
    input_documents: list[Any]
    pipeline_version: str
    agent_versions: dict[str, Any]
    output_refs: dict[str, Any]
    idempotency_key: Optional[str]
    is_stale: bool
    created_by: Optional[str]


class AnalysisRunDetail(AnalysisRunRead):
    stages: list[StageRead] = Field(default_factory=list)
    summary: RunSummary = Field(default_factory=RunSummary)
    reused_existing: bool = False
    message: Optional[str] = None
