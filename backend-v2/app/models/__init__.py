"""Import every model so ``Base.metadata`` is complete (Alembic autogenerate relies on this)."""

from app.models.analysis_run import AnalysisRun, AnalysisStage
from app.models.audit_event import AuditEvent, AuditImmutableError
from app.models.case import Case
from app.models.conflict import Conflict
from app.models.document import Document
from app.models.evidence import Evidence
from app.models.review import Review
from app.models.rule_result import RuleResult

__all__ = [
    "AnalysisRun", "AnalysisStage", "AuditEvent", "AuditImmutableError", "Case", "Conflict",
    "Document", "Evidence", "Review", "RuleResult",
]
