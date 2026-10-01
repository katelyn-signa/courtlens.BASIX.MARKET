"""CourtLens hackathon agents for the C-104 hearing-date demonstration.

These agents are deterministic and auditable. They are deliberately scoped to the
CourtLens evidence-reconciliation demo and do not provide legal advice.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.models.enums import (
    ConflictType,
    FactType,
    ResolutionStatus,
    ReviewSignal,
    RuleEvaluationStatus,
    Severity,
    VerificationStatus,
)
from app.orchestration.contracts import (
    AgentResultStatus,
    ConflictAgentInput,
    ConflictAgentOutput,
    ConflictFinding,
    DocumentProcessingResult,
    DocumentResultStatus,
    EvidenceAgentInput,
    EvidenceAgentOutput,
    ExtractedFact,
    ReasoningAgentInput,
    ReasoningAgentOutput,
    RuleEvaluation,
    SummaryAgentInput,
    SummaryAgentOutput,
    CaseSummaryBlock,
)

DATE_RE = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>\d{4})",
    re.I,
)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

AUTHORITY = {
    "official_court_order": 3,
    "court_order": 3,
    "advocate_note": 2,
    "party_document": 1,
}


def _source_type(document_type: str | None, filename: str) -> str:
    value = (document_type or filename).lower()
    if "court" in value and "order" in value:
        return "official_court_order"
    if "advocate" in value:
        return "advocate_note"
    if "party" in value:
        return "party_document"
    return "unknown"


def _date_from_text(text: str) -> str | None:
    match = DATE_RE.search(text)
    if not match:
        return None
    month = MONTHS[match.group("month").lower()]
    return f"{int(match.group('year')):04d}-{month:02d}-{int(match.group('day')):02d}"


def _display_date(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return f"{dt.day} {dt.strftime('%B %Y')}"


class CourtLensEvidenceAgent:
    name = "courtlens-document-agent"
    version = "1.0-c104"

    def extract(self, request: EvidenceAgentInput) -> EvidenceAgentOutput:
        facts: list[ExtractedFact] = []
        results: list[DocumentProcessingResult] = []

        for doc in request.documents:
            ocr = request.ocr_by_document_id.get(doc.document_id) or {}
            text = str(ocr.get("full_text") or "").strip()
            source_type = _source_type(doc.document_type, doc.filename)
            confidence = float(ocr.get("confidence") or 0.7)

            if not text:
                results.append(DocumentProcessingResult(
                    document_id=doc.document_id,
                    status=DocumentResultStatus.FAILED,
                ))
                continue

            hearing_date = _date_from_text(text)
            if hearing_date:
                quote = text[:500]
                facts.append(ExtractedFact(
                    fact_type=FactType.HEARING_DATE,
                    value={"date": hearing_date},
                    source_document_id=doc.document_id,
                    source_page=1,
                    quote=quote,
                    char_start=0,
                    char_end=min(len(text), len(quote)),
                    confidence=min(confidence, 0.98) if source_type == "official_court_order" else min(confidence, 0.94),
                    verification_status=VerificationStatus.UNVERIFIED,
                    provenance={
                        "document_id": doc.document_id,
                        "document_type": doc.document_type,
                        "source_type": source_type,
                        "page": 1,
                        "original_text": quote,
                        "normalized_value": hearing_date,
                        "extraction_confidence": min(confidence, 0.98),
                    },
                ))
            elif source_type == "party_document" and "second week" in text.lower():
                quote = text[:500]
                facts.append(ExtractedFact(
                    fact_type=FactType.HEARING_DATE,
                    value={"date": None, "period": "second week of October 2026"},
                    source_document_id=doc.document_id,
                    source_page=1,
                    quote=quote,
                    char_start=0,
                    char_end=min(len(text), len(quote)),
                    confidence=min(confidence, 0.88),
                    verification_status=VerificationStatus.UNKNOWN,
                    provenance={
                        "document_id": doc.document_id,
                        "document_type": doc.document_type,
                        "source_type": source_type,
                        "page": 1,
                        "original_text": quote,
                        "normalized_value": "second week of October 2026",
                        "extraction_confidence": min(confidence, 0.88),
                    },
                ))

            results.append(DocumentProcessingResult(
                document_id=doc.document_id,
                status=DocumentResultStatus.SUCCESS,
            ))

        return EvidenceAgentOutput(
            status=AgentResultStatus.SUCCESS,
            agent_name=self.name,
            agent_version=self.version,
            is_simulated=False,
            facts=facts,
            document_results=results,
        )


class CourtLensConflictAgent:
    name = "courtlens-conflict-agent"
    version = "1.0-c104"

    def analyze(self, request: ConflictAgentInput) -> ConflictAgentOutput:
        hearing = [e for e in request.evidence if e.fact_type == FactType.HEARING_DATE.value]
        exact = [e for e in hearing if e.fact_value.get("date")]
        periods = [e for e in hearing if e.fact_value.get("period")]

        findings: list[ConflictFinding] = []
        values = {e.fact_value.get("date") for e in exact}

        if len(values) > 1 or (exact and periods):
            findings.append(ConflictFinding(
                finding_type=ConflictType.CONTRADICTION,
                severity=Severity.HIGH,
                description="Hearing date information differs across the uploaded documents.",
                related_evidence_ids=[e.evidence_id for e in hearing],
                related_document_ids=sorted({e.document_id for e in hearing}),
                conflicting_values=[
                    {
                        "evidence_id": e.evidence_id,
                        "document_id": e.document_id,
                        "value": e.fact_value,
                    }
                    for e in hearing
                ],
                resolution_status=ResolutionStatus.UNRESOLVED,
            ))

        findings.append(ConflictFinding(
            finding_type=ConflictType.MISSING_EVIDENCE,
            severity=Severity.MEDIUM,
            description="The uploaded documents do not establish which hearing date is currently authoritative.",
            related_evidence_ids=[e.evidence_id for e in hearing],
            related_document_ids=sorted({e.document_id for e in hearing}),
            missing_information="Latest verified registry record",
            resolution_status=ResolutionStatus.UNRESOLVED,
        ))

        return ConflictAgentOutput(
            status=AgentResultStatus.SUCCESS,
            agent_name=self.name,
            agent_version=self.version,
            is_simulated=False,
            findings=findings,
        )


class CourtLensRuleAgent:
    name = "courtlens-rule-agent"
    version = "1.0-c104"

    def evaluate(self, request: ReasoningAgentInput) -> ReasoningAgentOutput:
        hearing = [e for e in request.evidence if e.fact_type == FactType.HEARING_DATE.value]
        exact = [e for e in hearing if e.fact_value.get("date")]

        ranked = sorted(
            exact,
            key=lambda e: AUTHORITY.get(
                str(e.provenance.get("source_type") or ""), 0
            ),
            reverse=True,
        )

        evaluations: list[RuleEvaluation] = []
        input_ids = [e.evidence_id for e in hearing]

        if ranked:
            winner = ranked[0]
            winner_date = winner.fact_value["date"]
            source = str(winner.provenance.get("source_type") or "unknown")
            authority = AUTHORITY.get(source, 0)

            evaluations.append(RuleEvaluation(
                rule_id="SOURCE-AUTHORITY",
                rule_version="1.0",
                evaluation_status=RuleEvaluationStatus.EVALUATED,
                review_signal=ReviewSignal.NEEDS_HUMAN_REVIEW,
                explanation=(
                    f"Based on the configured source hierarchy, CourtLens recommends "
                    f"{_display_date(winner_date)}. The {source.replace('_', ' ')} "
                    f"has configured authority {authority}. Human confirmation is required."
                ),
                input_evidence_ids=input_ids,
                limitations=[
                    "This is an evidence-reconciliation recommendation, not legal advice.",
                    "A later verified official record could change the recommendation.",
                ],
                evaluated_at=datetime.now(timezone.utc),
            ))

            evaluations.append(RuleEvaluation(
                rule_id="OFFICIAL-ORDER-OVER-ADVOCATE-NOTE",
                rule_version="1.0",
                evaluation_status=RuleEvaluationStatus.EVALUATED,
                review_signal=ReviewSignal.CONFLICTS_DETECTED,
                explanation=(
                    "Official Court Order > Advocate Note > Party Document. "
                    "The documents contain differing hearing-date information."
                ),
                input_evidence_ids=input_ids,
                evaluated_at=datetime.now(timezone.utc),
            ))
        else:
            evaluations.append(RuleEvaluation(
                rule_id="SOURCE-AUTHORITY",
                rule_version="1.0",
                evaluation_status=RuleEvaluationStatus.INSUFFICIENT_INFORMATION,
                review_signal=ReviewSignal.INSUFFICIENT_INFORMATION,
                explanation="No exact hearing date could be established from the available evidence.",
                input_evidence_ids=input_ids,
                missing_prerequisites=["Verified hearing date"],
                evaluated_at=datetime.now(timezone.utc),
            ))

        return ReasoningAgentOutput(
            status=AgentResultStatus.SUCCESS,
            agent_name=self.name,
            agent_version=self.version,
            is_simulated=False,
            rule_set_id="COURTLENS-SOURCE-HIERARCHY",
            rule_set_version="1.0-c104",
            evaluations=evaluations,
        )


class CourtLensSummaryAgent:
    name = "courtlens-summary-agent"
    version = "1.0-c104"

    def summarize(self, request: SummaryAgentInput) -> SummaryAgentOutput:
        hearing = [e for e in request.evidence if e.fact_type == FactType.HEARING_DATE.value]
        conflicts = [c.description for c in request.conflicts]
        recommendation = next(
            (r.explanation for r in request.rule_evaluations
             if r.rule_id == "SOURCE-AUTHORITY"),
            "Human review required because the available evidence is insufficient.",
        )

        timeline = []
        for e in hearing:
            timeline.append({
                "date": e.fact_value.get("date"),
                "fact_type": e.fact_type,
                "document_id": e.document_id,
            })

        return SummaryAgentOutput(
            status=AgentResultStatus.SUCCESS,
            agent_name=self.name,
            agent_version=self.version,
            is_simulated=False,
            summary=CaseSummaryBlock(
                case_summary=(
                    "C-104 contains conflicting hearing-date information across three documents. "
                    + recommendation
                ),
                document_summary="; ".join(d.filename for d in request.documents),
                timeline=timeline,
                key_evidence=[e.evidence_id for e in hearing],
                conflicts_overview=conflicts,
                missing_evidence=[
                    c.missing_information for c in request.conflicts if c.missing_information
                ],
                review_recommendations=[
                    "Human confirmation is required.",
                    "A later official court order or verified registry record could change the recommendation.",
                ],
            ),
        )
