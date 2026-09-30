from datetime import datetime
from typing import Any, Optional

from pydantic import Field

from app.schemas.common import ORMModel


class AuditEventRead(ORMModel):
    id: str
    case_id: Optional[str]
    event_type: str
    actor: Optional[str]
    occurred_at: datetime
    resource_type: Optional[str]
    resource_id: Optional[str]
    analysis_run_id: Optional[str]
    metadata: dict[str, Any] = Field(validation_alias="event_metadata")
    correlation_id: Optional[str]
