from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentProcessingStatus
from app.schemas.common import ORMModel


class DocumentRegister(BaseModel):
    """Metadata-only registration (file already held by the document-intelligence module)."""

    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=150)
    size_bytes: int = Field(ge=0)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    document_type: Optional[str] = Field(default=None, max_length=100)
    storage_key: Optional[str] = Field(default=None, max_length=255)
    source_reference: Optional[str] = Field(default=None, max_length=255)


class DocumentRead(ORMModel):
    id: str
    case_id: str
    filename: str
    document_type: Optional[str]
    mime_type: str
    size_bytes: int
    storage_key: Optional[str]
    checksum_sha256: str
    uploaded_at: datetime
    processing_status: DocumentProcessingStatus
    processing_error: Optional[str]
    version: int
    uploaded_by: Optional[str]
    source_reference: Optional[str]


class DocumentRegistrationResult(BaseModel):
    document: DocumentRead
    created: bool
    analysis_needs_refresh: bool
    triggered_analysis_run_id: Optional[str] = None


class DocumentStatusRead(BaseModel):
    document_id: str
    version: int
    processing_status: DocumentProcessingStatus
    processing_error: Optional[str]
    processing_updated_at: datetime
    evidence_count: int
