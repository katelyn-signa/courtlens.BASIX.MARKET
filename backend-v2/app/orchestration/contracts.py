"""Integration contracts between Person 4's orchestrator and the Person 1/2/3 agents.

Wire rules (contract version 1.x)
---------------------------------
* IDs: ``case_<21 hex>``, ``doc_<21 hex>``, ``evd_<21 hex>``, ``cfl_<21 hex>``, ``run_<21 hex>``.
  Evidence IDs are assigned by the backend when Person 1's facts are stored.
* Timestamps: timezone-aware ISO-8601 (UTC recommended, e.g. ``2026-01-31T10:15:00Z``).
  Dates inside fact values: ``YYYY-MM-DD`` or ``null`` when unknown (never guessed).
* Status values: ``SUCCESS | PARTIAL | FAILED`` for agent results.
* Errors: raise ``AgentUnavailableError`` / ``AgentProcessingError`` (or return ``FAILED`` with
  ``errors``); raise ``NotImplementedError`` for a stage that is a stub -> NOT_IMPLEMENTED.
* Versioning: ``contract_version`` is ``"MAJOR.MINOR"``. Output whose MAJOR differs is rejected.
* Timeout/retry: each call is bounded by AGENT_TIMEOUT_SECONDS and retried only for retryable
  errors (timeout / unavailable) up to AGENT_MAX_ATTEMPTS. Agents must therefore be idempotent.
* Validation: every output is re-validated with these models plus cross-reference checks
  (known document/evidence IDs). Invalid output is rejected and nothing is stored for the stage.
"""

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.exceptions import (  # re-exported for agent authors
    AgentInvalidOutputError, AgentProcessingError, AgentTimeoutError, AgentUnavailableError,
)
from app.models.enums import (
    ConflictType, FactType, ResolutionStatus, ReviewSignal, RuleEvaluationStatus, Severity,
    VerificationStatus,
)
from app.utils.identifiers import id_pattern, CASE, CONFLICT, DOCUMENT, EVIDENCE, RUN
from app.utils.time import utcnow

__all__ = [
    "CONTRACT_VERSION", "AgentInvalidOutputError", "AgentProcessingError", "AgentTimeoutError",
    "AgentUnavailableError",
]

CONTRACT_VERSION = "1.0"
CONTRACT_MAJOR = CONTRACT_VERSION.split(".")[0]

CASE_ID = id_pattern(CASE)
DOC_ID = id_pattern(DOCUMENT)
EVD_ID = id_pattern(EVIDENCE)
CFL_ID = id_pattern(CONFLICT)
RUN_ID = id_pattern(RUN)

_DATE_FACTS = {FactType.ARREST_DATE, FactType.CUSTODY_START_DATE, FactType.CHARGE_SHEET_DATE,
               FactType.HEARING_DATE}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- shared building blocks ------------------------------------------------------------

class AgentResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class AgentIssue(_Strict):
    """Common error/warning structure used by every agent."""

    code: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class CaseSnapshot(_Strict):
    case_id: str = Field(pattern=CASE_ID)
    external_reference: Optional[str] = None
    fir_number: Optional[str] = None
    police_station: Optional[str] = None
    court_name: Optional[str] = None
    jurisdiction: Optional[str] = None
    statutory_sections: list[Any] = Field(default_factory=list)
    status: str


class DocumentRef(_Strict):
    document_id: str = Field(pattern=DOC_ID)
    version: int = Field(ge=1)
    filename: str
    document_type: Optional[str] = None
    mime_type: str
    size_bytes: int = Field(ge=0)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storage_key: Optional[str] = None
    # Absolute local path when the file is held in this backend's private storage, else None.
    content_path: Optional[str] = None


class EvidenceRecord(_Strict):
    """Stored evidence as handed to Person 2 / Person 3."""

    evidence_id: str = Field(pattern=EVD_ID)
    document_id: str = Field(pattern=DOC_ID)
    fact_type: str
    fact_value: dict[str, Any]
    entity_ref: Optional[str] = None
    category: Optional[str] = None
    source_page: Optional[int] = None
    quote: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    confidence: Optional[float] = None
    verification_status: VerificationStatus
    provenance: dict[str, Any] = Field(default_factory=dict)


class ConflictRecord(_Strict):
    """Stored finding as handed to Person 3."""

    conflict_id: str = Field(pattern=CFL_ID)
    conflict_type: ConflictType
    description: str
    severity: Optional[Severity] = None
    related_evidence_ids: list[str] = Field(default_factory=list)
    related_document_ids: list[str] = Field(default_factory=list)
    missing_information: Optional[str] = None
    resolution_status: ResolutionStatus


class AgentInputBase(_Strict):
    contract_version: str = CONTRACT_VERSION
    run_id: str = Field(pattern=RUN_ID)
    correlation_id: Optional[str] = None
    case: CaseSnapshot
    config: dict[str, Any] = Field(default_factory=dict)


class AgentOutputBase(BaseModel):
    """Fields every agent output must carry (extra keys are ignored for forward-compat)."""

    contract_version: str = CONTRACT_VERSION
    status: AgentResultStatus
    agent_name: str = Field(min_length=1, max_length=100)
    agent_version: str = Field(min_length=1, max_length=50)
    is_simulated: bool = False
    warnings: list[AgentIssue] = Field(default_factory=list)
    errors: list[AgentIssue] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)

    @field_validator("contract_version")
    @classmethod
    def _major_matches(cls, v: str) -> str:
        if v.split(".")[0] != CONTRACT_MAJOR:
            raise ValueError(f"Unsupported contract_version {v!r}; backend speaks {CONTRACT_VERSION}.")
        return v

    @field_validator("generated_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware.")
        return v


def _iso_or_none(value: Any, label: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date string (YYYY-MM-DD) or null.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} is not a valid ISO date.") from exc


# ---- Person 1: document intelligence ---------------------------------------------------

class DocumentAgentInput(AgentInputBase):
    documents: list[DocumentRef] = Field(min_length=1)


class ExtractedFact(_Strict):
    fact_type: FactType
    value: dict[str, Any] = Field(min_length=1)
    source_document_id: str = Field(pattern=DOC_ID)
    entity_ref: Optional[str] = Field(default=None, max_length=200)
    category: Optional[str] = Field(default=None, max_length=100)
    source_page: Optional[int] = Field(default=None, ge=1)
    quote: Optional[str] = Field(default=None, max_length=5000)
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "ExtractedFact":
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start and char_end must be provided together.")
        if self.char_start is not None and self.char_end < self.char_start:
            raise ValueError("char_end must be >= char_start.")
        if self.fact_type in _DATE_FACTS:
            if "date" not in self.value:
                raise ValueError(f"{self.fact_type.value} requires value.date (ISO date or null).")
            _iso_or_none(self.value["date"], "value.date")
            if self.value["date"] is None and self.verification_status != VerificationStatus.UNKNOWN:
                raise ValueError("A missing date must be reported as UNKNOWN, never assumed.")
        if self.fact_type == FactType.REMAND_PERIOD:
            for key in ("start_date", "end_date"):
                if key not in self.value:
                    raise ValueError(f"REMAND_PERIOD requires value.{key} (ISO date or null).")
                _iso_or_none(self.value[key], f"value.{key}")
            s, e = self.value["start_date"], self.value["end_date"]
            if s and e and date.fromisoformat(e) < date.fromisoformat(s):
                raise ValueError("REMAND_PERIOD end_date precedes start_date.")
        return self


class DocumentResultStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class DocumentProcessingResult(_Strict):
    document_id: str = Field(pattern=DOC_ID)
    status: DocumentResultStatus
    error: Optional[AgentIssue] = None


class DocumentAgentOutput(AgentOutputBase):
    facts: list[ExtractedFact] = Field(default_factory=list)
    # Exactly one result per input document is required.
    document_results: list[DocumentProcessingResult] = Field(default_factory=list)


# ---- Person 2: conflict / evidence-gap detection ---------------------------------------

class ConflictAgentInput(AgentInputBase):
    documents: list[DocumentRef] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    new_evidence_ids: list[str] = Field(default_factory=list)


class ConflictFinding(_Strict):
    finding_type: ConflictType
    description: str = Field(min_length=1, max_length=2000)
    severity: Optional[Severity] = None
    related_evidence_ids: list[str] = Field(default_factory=list)
    related_document_ids: list[str] = Field(default_factory=list)
    conflicting_values: Optional[list[dict[str, Any]]] = None
    missing_information: Optional[str] = Field(default=None, max_length=2000)
    resolution_status: ResolutionStatus = ResolutionStatus.UNRESOLVED
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check(self) -> "ConflictFinding":
        if self.finding_type == ConflictType.MISSING_EVIDENCE and not self.missing_information:
            raise ValueError("MISSING_EVIDENCE findings must describe missing_information.")
        if self.finding_type == ConflictType.CONTRADICTION and not (
                self.related_evidence_ids or self.conflicting_values):
            raise ValueError("CONTRADICTION findings need related_evidence_ids or conflicting_values.")
        return self


class ConflictAgentOutput(AgentOutputBase):
    findings: list[ConflictFinding] = Field(default_factory=list)


# ---- Person 3: explainable reasoning / rule engine -------------------------------------

class RuleConfig(_Strict):
    rule_set_id: Optional[str] = None
    rule_set_version: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class ReasoningAgentInput(AgentInputBase):
    documents: list[DocumentRef] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    rule_config: RuleConfig = Field(default_factory=RuleConfig)


class RuleEvaluation(_Strict):
    rule_id: str = Field(min_length=1, max_length=100)
    rule_version: str = Field(min_length=1, max_length=50)
    evaluation_status: RuleEvaluationStatus
    review_signal: Optional[ReviewSignal] = None
    explanation: str = Field(min_length=1, max_length=5000)
    input_evidence_ids: list[str] = Field(default_factory=list)
    missing_prerequisites: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evaluated_at: Optional[datetime] = None
    output_schema_version: str = "1.0"

    @model_validator(mode="after")
    def _check(self) -> "RuleEvaluation":
        if self.evaluation_status == RuleEvaluationStatus.EVALUATED and self.review_signal is None:
            raise ValueError("An EVALUATED rule must carry a neutral review_signal.")
        if self.evaluated_at is not None and self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware.")
        return self


class ReasoningAgentOutput(AgentOutputBase):
    rule_set_id: Optional[str] = None
    rule_set_version: Optional[str] = None
    evaluations: list[RuleEvaluation] = Field(default_factory=list)


# ---- Python interfaces (what Persons 1/2/3 implement) ----------------------------------

@runtime_checkable
class DocumentIntelligenceAgent(Protocol):
    name: str
    version: str

    def extract(self, request: DocumentAgentInput) -> DocumentAgentOutput: ...


@runtime_checkable
class ConflictDetectionAgent(Protocol):
    name: str
    version: str

    def analyze(self, request: ConflictAgentInput) -> ConflictAgentOutput: ...


@runtime_checkable
class ReasoningAgent(Protocol):
    name: str
    version: str

    def evaluate(self, request: ReasoningAgentInput) -> ReasoningAgentOutput: ...
