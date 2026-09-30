from app.schemas.conflict import Conflict, ConflictDetectionResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.facts import ExtractedFact
from app.services.conflict_detection_service import detect_conflicts


def run_conflict_agent(
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
) -> ConflictDetectionResult:
    conflicts: list[Conflict] = detect_conflicts(facts, evidence, claims)
    return ConflictDetectionResult(
        conflicts=conflicts,
        conflict_count=len(conflicts),
    )