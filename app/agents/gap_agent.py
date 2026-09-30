from app.schemas.conflict import Conflict
from app.schemas.document_classification import DocumentClassificationResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap, EvidenceGapDetectionResult
from app.schemas.facts import ExtractedFact
from app.services.evidence_gap_service import detect_evidence_gaps


def run_gap_agent(
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
    conflicts: list[Conflict],
    classification: DocumentClassificationResult | None = None,
) -> EvidenceGapDetectionResult:
    gaps: list[EvidenceGap] = detect_evidence_gaps(
        facts,
        evidence,
        claims,
        conflicts,
        classification,
    )
    return EvidenceGapDetectionResult(gaps=gaps, gap_count=len(gaps))