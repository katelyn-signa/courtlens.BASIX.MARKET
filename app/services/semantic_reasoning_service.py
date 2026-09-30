import re

from app.schemas.analysis import CaseAnalysisResult
from app.schemas.reasoning import (
    ReasoningEvidenceReference,
    SemanticInterpretation,
    SemanticObservation,
)
from app.reasoning.rules import SOURCE_AUTHORITY

AMOUNT_PATTERN = re.compile(
    r"(?:\b(?:INR|Rs\.?)\s*(?P<prefix>\d[\d,]*(?:\.\d+)?)|"
    r"₹\s*(?P<rupee>\d[\d,]*(?:\.\d+)?)|"
    r"(?P<suffix>\d[\d,]*(?:\.\d+)?)\s*INR\b)",
    re.IGNORECASE,
)
FULL_PAYMENT_PATTERN = re.compile(
    r"\b(?:full\s+(?:payment|amount)|entire\s+(?:amount|balance)|"
    r"paid\s+(?:the\s+)?full(?:\s+amount)?|fully\s+paid|paid\s+in\s+full)\b",
    re.IGNORECASE,
)
PARTIAL_PAYMENT_PATTERN = re.compile(
    r"\b(?:part(?:ial(?:ly)?)?\s+payment|remaining\s+amount|balance\s+remaining)\b",
    re.IGNORECASE,
)


def _amount_from_text(text: str) -> int | float | None:
    match = AMOUNT_PATTERN.search(text)
    if match is None:
        return None
    token = next(value for value in match.groupdict().values() if value is not None)
    number = float(token.replace(",", ""))
    return int(number) if number.is_integer() else number


def _currency_from_text(text: str) -> str | None:
    if re.search(r"\bINR\b|\bRs\.?", text, re.IGNORECASE) or "₹" in text:
        return "INR"
    return None


def _evidence_references(evidence_items) -> list[ReasoningEvidenceReference]:
    return [
        ReasoningEvidenceReference(
            evidence_id=item.evidence_id,
            document_id=item.document_id,
            page=item.page,
            quote=item.quote,
            relevance=item.confidence,
        )
        for item in evidence_items
        if item.document_id and item.page >= 1 and item.quote.strip()
    ]


def interpret_case(case_analysis: CaseAnalysisResult) -> SemanticInterpretation:
    evidence_by_fact = {
        (item.document_id, item.fact_id): item
        for item in case_analysis.evidence
        if item.fact_id
    }
    evidence_by_id = {item.evidence_id: item for item in case_analysis.evidence}
    verified_evidence_ids = set(case_analysis.verified_evidence_ids)
    challenged_evidence_ids = set(case_analysis.challenged_evidence_ids)
    observations: list[SemanticObservation] = []

    for fact in case_analysis.facts:
        linked_evidence = evidence_by_fact.get((fact.document_id, fact.fact_id))
        evidence_refs = _evidence_references([linked_evidence] if linked_evidence else [])
        field = fact.field.casefold()
        normalized_value = fact.normalized_value
        amount = (
            normalized_value
            if fact.fact_type == "financial" and isinstance(normalized_value, (int, float))
            else None
        )
        if field in {"contract_amount", "total_contract_amount", "total_amount", "amount_due"}:
            observation_type = "payment_obligation"
        elif field in {"amount_paid", "payment_amount"}:
            observation_type = "payment_record"
        elif fact.fact_type == "date":
            observation_type = "date_event"
        elif fact.fact_type == "party":
            observation_type = "party_identity"
        else:
            continue

        observations.append(
            SemanticObservation(
                observation_id=f"fact:{fact.document_id}:{fact.fact_id}",
                observation_type=observation_type,
                statement=fact.quote,
                field=fact.field,
                normalized_value=normalized_value,
                amount=amount,
                currency=fact.currency,
                source_supported=(
                    observation_type == "payment_record"
                    and linked_evidence is not None
                    and linked_evidence.evidence_type == "payment_record"
                    and linked_evidence.evidence_id in verified_evidence_ids
                    and linked_evidence.evidence_id not in challenged_evidence_ids
                ),
                event_type=fact.field if observation_type == "date_event" else None,
                source_type=(linked_evidence.document_type if linked_evidence else None),
                source_authority=(
                    SOURCE_AUTHORITY.get(linked_evidence.document_type)
                    if linked_evidence
                    else None
                ),
                document_id=fact.document_id,
                page=fact.page,
                quote=fact.quote,
                fact_id=fact.fact_id,
                evidence_refs=evidence_refs,
            )
        )

    for claim in case_analysis.claims:
        amount = _amount_from_text(claim.claim_text)
        linked = [
            evidence_by_id[evidence_id]
            for evidence_id in claim.supporting_evidence_ids
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].document_id == claim.document_id
        ]
        observation_type = (
            "payment_claim"
            if claim.claim_type in {"payment_claim", "non_payment_claim"}
            else "claim_statement"
        )
        observations.append(
            SemanticObservation(
                observation_id=f"claim:{claim.document_id}:{claim.claim_id}",
                observation_type=observation_type,
                statement=claim.claim_text,
                amount=amount,
                currency=_currency_from_text(claim.claim_text),
                full_payment_claim=(
                    claim.claim_type == "payment_claim"
                    and bool(FULL_PAYMENT_PATTERN.search(claim.claim_text))
                ),
                document_id=claim.document_id,
                page=claim.page,
                quote=claim.quote,
                claim_id=claim.claim_id,
                evidence_refs=_evidence_references(linked),
            )
        )

    for conflict in case_analysis.conflicts:
        refs = []
        for value in conflict.conflicting_values:
            refs.append(
                ReasoningEvidenceReference(
                    evidence_id=value.evidence_id,
                    document_id=value.document_id,
                    page=value.page,
                    quote=value.quote,
                    relevance=conflict.confidence,
                )
            )
        observations.append(
            SemanticObservation(
                observation_id=f"conflict:{conflict.conflict_id}",
                observation_type="conflict",
                statement=conflict.description,
                field=conflict.fact_type,
                event_type=conflict.event_type,
                conflict_type=conflict.conflict_type,
                conflict_id=conflict.conflict_id,
                severity=conflict.severity,
                evidence_refs=refs,
            )
        )

    for gap in case_analysis.evidence_gaps:
        refs = [
            item
            for item in case_analysis.evidence
            if item.evidence_id in gap.related_evidence_ids
        ]
        observations.append(
            SemanticObservation(
                observation_id=f"gap:{gap.gap_id}",
                observation_type="evidence_gap",
                statement=gap.description,
                gap_id=gap.gap_id,
                evidence_refs=_evidence_references(refs),
            )
        )

    return SemanticInterpretation(observations=observations)