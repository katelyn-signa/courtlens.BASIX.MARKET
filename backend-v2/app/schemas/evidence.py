from datetime import datetime
from typing import Any, Optional

from app.models.enums import VerificationStatus
from app.schemas.common import ORMModel


class EvidenceRead(ORMModel):
    id: str
    case_id: str
    document_id: str
    fact_type: str
    fact_value: dict[str, Any]
    entity_ref: Optional[str]
    category: Optional[str]
    source_page: Optional[int]
    quote: Optional[str]
    char_start: Optional[int]
    char_end: Optional[int]
    confidence: Optional[float]
    verification_status: VerificationStatus
    extracted_at: datetime
    extraction_run_id: Optional[str]
    provenance: dict[str, Any]
    agent_name: Optional[str]
    agent_version: Optional[str]
    is_simulated: bool
