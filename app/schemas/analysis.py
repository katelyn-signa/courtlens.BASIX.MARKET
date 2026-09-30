from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.case import CaseIntakeResult, CaseParty
from app.schemas.conflict import Conflict
from app.schemas.document import DocumentExtractionResult
from app.schemas.document_classification import DocumentClassificationResult, DocumentType
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap
from app.schemas.facts import ExtractedFact

DocumentAnalysisStatus = Literal["processed", "failed"]
DocumentAnalysisErrorType = Literal[
    "extraction_error",
    "classification_error",
    "fact_extraction_error",
    "analysis_error",
]
ReviewSignal = Literal[
    "no_review_signal",
    "review_recommended",
    "conflicts_require_attention",
    "evidence_gaps_require_attention",
]


class CaseAnalysisDocumentInput(BaseModel):
    filename: str | None = None
    document_id: str | None = None
    source_type: DocumentType | None = None
    content_base64: str | None = None
    extracted_document: DocumentExtractionResult | None = None

    @model_validator(mode="after")
    def require_one_document_source(self) -> "CaseAnalysisDocumentInput":
        if (self.content_base64 is None) == (self.extracted_document is None):
            raise ValueError(
                "Provide exactly one of 'content_base64' or 'extracted_document'."
            )
        if self.content_base64 is not None and not self.filename:
            raise ValueError("A filename is required when providing PDF content.")
        return self


class CaseAnalysisRequest(BaseModel):
    case_id: str | None = None
    case_title: str | None = None
    case_type: str | None = None
    parties: list[CaseParty] | None = None
    documents: list[CaseAnalysisDocumentInput] = Field(default_factory=list)


class DocumentAnalysisError(BaseModel):
    error_type: DocumentAnalysisErrorType
    message: str


class DocumentAnalysisResult(BaseModel):
    document_id: str
    filename: str
    page_count: int | None = None
    status: DocumentAnalysisStatus
    classification: DocumentClassificationResult | None = None
    facts: list[ExtractedFact] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)
    error: DocumentAnalysisError | None = None


class AnalysisSummary(BaseModel):
    document_count: int = Field(ge=0)
    fact_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    claim_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    evidence_gap_count: int = Field(ge=0)
    high_severity_conflict_count: int = Field(ge=0)
    review_signal: ReviewSignal


class CaseAnalysisResult(BaseModel):
    case_intake: CaseIntakeResult
    documents: list[DocumentAnalysisResult]
    facts: list[ExtractedFact]
    evidence: list[Evidence]
    claims: list[ExtractedClaim]
    conflicts: list[Conflict]
    evidence_gaps: list[EvidenceGap]
    analysis_summary: AnalysisSummary
    verified_evidence_ids: list[str] = Field(default_factory=list)
    challenged_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_verified_evidence(self) -> "CaseAnalysisResult":
        evidence_by_id = {item.evidence_id: item for item in self.evidence}
        for evidence_id in self.verified_evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                raise ValueError(f"Verified evidence ID '{evidence_id}' is not present in evidence.")
            if evidence.evidence_type != "payment_record":
                raise ValueError(
                    f"Verified evidence ID '{evidence_id}' must reference payment_record evidence."
                )
        unknown_challenges = set(self.challenged_evidence_ids) - set(evidence_by_id)
        if unknown_challenges:
            raise ValueError(
                f"Challenged evidence IDs are not present in evidence: {sorted(unknown_challenges)}"
            )
        return self