"""Append-only audit recording with metadata sanitisation."""

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_request_id
from app.models.audit_event import AuditEvent
from app.models.enums import AuditEventType
from app.repositories.audit import AuditRepository

# Keys that could carry confidential content or secrets are never persisted.
_BLOCKED_KEYS = {"text", "quote", "content", "extracted_text", "document_text", "raw", "body",
                 "password", "token", "secret", "api_key", "authorization", "notes"}
_MAX_STR = 200
_MAX_ITEMS = 50


def sanitize_metadata(value: Any, _depth: int = 0) -> Any:
    if _depth > 4:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:_MAX_ITEMS]:
            key = str(k)
            out[key] = "[REDACTED]" if key.lower() in _BLOCKED_KEYS else sanitize_metadata(v, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        return [sanitize_metadata(v, _depth + 1) for v in list(value)[:_MAX_ITEMS]]
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else f"[TRUNCATED len={len(value)}]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(type(value).__name__)


class AuditService:
    def __init__(self, session: Session):
        self.repo = AuditRepository(session)

    def record(self, event_type: AuditEventType, *, case_id: Optional[str] = None,
               actor: Optional[str] = "system", resource_type: Optional[str] = None,
               resource_id: Optional[str] = None, analysis_run_id: Optional[str] = None,
               metadata: Optional[dict[str, Any]] = None) -> AuditEvent:
        """Adds the event to the caller's transaction (committed together with the change)."""
        cid = get_request_id()
        return self.repo.add(AuditEvent(
            case_id=case_id, event_type=event_type.value, actor=actor,
            resource_type=resource_type, resource_id=resource_id, analysis_run_id=analysis_run_id,
            event_metadata=sanitize_metadata(metadata or {}),
            correlation_id=None if cid == "-" else cid))
