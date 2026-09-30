from datetime import date
from uuid import uuid4

from app.schemas.case import (
    CaseDocumentReference,
    CaseIntake,
    CaseIntakeRequest,
    CaseIntakeResult,
    CaseMetadata,
    CaseParty,
    CaseSignalType,
    CaseStatusSignal,
    CaseSummaryCounts,
    CaseTimelineCandidate,
)
from app.schemas.evidence import Evidence
from app.schemas.facts import ExtractedFact

PARTY_ROLES = {"seller", "buyer", "claimant", "respondent", "sender", "recipient"}


def _assemble_document_references(request: CaseIntakeRequest) -> list[CaseDocumentReference]:
    references = {item.document_id: item for item in request.documents}
    document_types = {
        item.document_id: item.document_type
        for item in request.evidence
    }
    document_types.update({item.document_id: item.document_type for item in request.claims})

    source_document_ids = [
        fact.document_id for fact in request.facts if fact.document_id
    ] + [item.document_id for item in request.evidence] + [
        item.document_id for item in request.claims
    ] + [
        document_id
        for conflict in request.conflicts
        for document_id in conflict.document_ids
    ] + [
        document_id
        for gap in request.gaps
        for document_id in gap.related_document_ids
    ]

    for document_id in source_document_ids:
        if document_id in references:
            current = references[document_id]
            if current.document_type is None and document_types.get(document_id) is not None:
                references[document_id] = current.model_copy(
                    update={"document_type": document_types[document_id]}
                )
            continue
        references[document_id] = CaseDocumentReference(
            document_id=document_id,
            document_type=document_types.get(document_id),
        )
    return list(references.values())


def _parties_from_facts(facts: list[ExtractedFact]) -> list[CaseParty]:
    parties = []
    seen = set()
    for fact in facts:
        if fact.fact_type != "party" or fact.field not in PARTY_ROLES:
            continue
        name = fact.normalized_value if isinstance(fact.normalized_value, str) else fact.value
        name = name.strip()
        key = (fact.field, name.casefold())
        if not name or key in seen:
            continue
        parties.append(CaseParty(role=fact.field, name=name))
        seen.add(key)
    return parties


def _status_signals(request: CaseIntakeRequest) -> list[CaseStatusSignal]:
    signals: list[CaseStatusSignal] = []
    if request.conflicts:
        signals.append(
            CaseStatusSignal(
                signal="conflicts_detected",
                reason="One or more structured conflicts were supplied.",
            )
        )
    else:
        signals.append(
            CaseStatusSignal(
                signal="no_conflicts_detected",
                reason="No structured conflicts were supplied.",
            )
        )
    if request.gaps:
        signals.append(
            CaseStatusSignal(
                signal="evidence_gaps_present",
                reason="One or more evidence gaps were supplied.",
            )
        )
    unsupported_claims = [
        claim
        for claim in request.claims
        if not claim.supporting_evidence_ids or claim.status == "unverified"
    ]
    if unsupported_claims:
        signals.append(
            CaseStatusSignal(
                signal="unsupported_claims_present",
                reason="One or more claims are unverified or have no supporting evidence IDs.",
            )
        )
    if request.conflicts or request.gaps or unsupported_claims:
        signals.append(
            CaseStatusSignal(
                signal="requires_review",
                reason="Supplied conflicts, evidence gaps, or unsupported claims need review.",
            )
        )
    return signals


def _timeline_candidates(
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    documents: list[CaseDocumentReference],
) -> list[CaseTimelineCandidate]:
    evidence_by_fact = {
        (item.document_id, item.fact_id): item
        for item in evidence
        if item.fact_id
    }
    document_by_id = {item.document_id: item for item in documents}
    timeline = []
    for fact in facts:
        if fact.fact_type != "date" or not isinstance(fact.normalized_value, str):
            continue
        try:
            event_date = date.fromisoformat(fact.normalized_value)
        except ValueError:
            continue
        document = document_by_id.get(fact.document_id or "")
        source_evidence = evidence_by_fact.get((fact.document_id, fact.fact_id))
        timeline.append(
            CaseTimelineCandidate(
                date=event_date,
                event_type=fact.field,
                description=f"{fact.field.replace('_', ' ').capitalize()}: {fact.value}",
                source_document_id=fact.document_id,
                filename=document.filename if document else None,
                page=fact.page,
                quote=fact.quote,
                fact_id=fact.fact_id,
                evidence_id=source_evidence.evidence_id if source_evidence else None,
                confidence=fact.confidence,
            )
        )
    timeline.sort(
        key=lambda item: (
            item.date,
            item.source_document_id or "",
            item.page,
            item.fact_id,
        )
    )
    return timeline


def assemble_case(request: CaseIntakeRequest) -> CaseIntakeResult:
    case_id = request.case_id.strip() if request.case_id and request.case_id.strip() else str(uuid4())
    parties = request.parties if request.parties is not None else _parties_from_facts(request.facts)
    documents = _assemble_document_references(request)
    metadata = CaseMetadata(
        case_id=case_id,
        case_title=request.case_title,
        case_type=request.case_type,
        parties=parties,
        created_at=request.created_at,
        source=request.source,
    )
    case = CaseIntake(
        metadata=metadata,
        documents=documents,
        facts=request.facts,
        evidence=request.evidence,
        claims=request.claims,
        conflicts=request.conflicts,
        gaps=request.gaps,
    )
    counts = CaseSummaryCounts(
        document_count=len(documents),
        fact_count=len(request.facts),
        evidence_count=len(request.evidence),
        claim_count=len(request.claims),
        conflict_count=len(request.conflicts),
        evidence_gap_count=len(request.gaps),
    )
    return CaseIntakeResult(
        case=case,
        counts=counts,
        status_signals=_status_signals(request),
        timeline_candidates=_timeline_candidates(
            request.facts,
            request.evidence,
            documents,
        ),
    )