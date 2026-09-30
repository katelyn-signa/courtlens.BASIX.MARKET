from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.document import DocumentExtractionResult
from app.schemas.document_classification import (
    DocumentClassificationResult,
    DocumentType,
)
from app.schemas.facts import ExtractedFact, FactValue

EvidenceType = Literal[
    "contract_term",
    "invoice",
    "payment_record",
    "delivery_record",
    "purchase_order",
    "email_statement",
    "party_statement",
    "court_record",
    "identity_record",
    "other",
]
ClaimType = Literal[
    "payment_claim",
    "non_payment_claim",
    "delivery_claim",
    "non_delivery_claim",
    "amount_claim",
    "breach_claim",
    "adjustment_claim",
    "contractual_obligation_claim",
    "general_statement",
]
ClaimStatus = Literal[
    "unverified",
    "partially_supported",
    "supported",
    "contradicted",
]


class Evidence(BaseModel):
    evidence_id: str
    evidence_type: EvidenceType
    document_id: str
    document_type: DocumentType
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    normalized_value: FactValue | None = None
    fact_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    extraction_method: Literal["text", "ocr"] | None = None
    source_party: str | None = None
    verification_status: Literal["unverified"] = "unverified"


class ExtractedClaim(BaseModel):
    claim_id: str
    claimant: str | None = None
    claim_type: ClaimType
    claim_text: str = Field(min_length=1)
    normalized_claim: str = Field(min_length=1)
    document_id: str
    document_type: DocumentType
    page: int = Field(ge=1)
    quote: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimStatus = "unverified"


class EvidenceExtractionRequest(BaseModel):
    document: DocumentExtractionResult
    classification: DocumentClassificationResult | None = None


class EvidenceAnalysisResult(BaseModel):
    document_id: str
    document_type: DocumentType
    facts: list[ExtractedFact]
    evidence: list[Evidence]
    claims: list[ExtractedClaim]