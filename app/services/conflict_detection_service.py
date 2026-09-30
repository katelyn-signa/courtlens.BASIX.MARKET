import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from itertools import combinations

from app.schemas.conflict import (
    Conflict,
    ConflictSeverity,
    ConflictType,
    ConflictingValue,
)
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.facts import ExtractedFact

DATE_FIELDS = {
    "contract_date",
    "effective_date",
    "delivery_date",
    "payment_due_date",
    "due_date",
    "payment_date",
    "invoice_date",
    "order_date",
    "hearing_date",
}
PARTY_FIELDS = {
    "seller",
    "buyer",
    "claimant",
    "respondent",
    "sender",
    "recipient",
}
IDENTITY_FIELDS = {
    "case_id",
    "invoice_number",
    "purchase_order_number",
    "agreement_id",
    "transaction_id",
}
TOTAL_AMOUNT_FIELDS = {"contract_amount", "total_contract_amount", "total_amount"}
FULL_PAYMENT_PATTERN = re.compile(
    r"\b(?:full\s+(?:payment|amount)|entire\s+(?:amount|balance)|"
    r"paid\s+(?:the\s+)?full(?:\s+amount)?|fully\s+paid)\b",
    re.IGNORECASE,
)


def _canonical_field(fact: ExtractedFact) -> str:
    field = fact.field.casefold().strip()
    if fact.fact_type == "date" and field == "due_date":
        return "payment_due_date"
    if fact.fact_type == "financial" and field == "total_contract_amount":
        return "contract_amount"
    return field


def _semantic_group(fact: ExtractedFact) -> tuple[str, str, ConflictType] | None:
    field = _canonical_field(fact)
    if fact.fact_type == "date" and field in DATE_FIELDS:
        return "date", field, "date_conflict"
    if fact.fact_type == "financial" and field:
        return "financial", field, "amount_conflict"
    if fact.fact_type == "party" and field in PARTY_FIELDS:
        return "party", field, "party_conflict"
    if fact.fact_type == "identity" and field in IDENTITY_FIELDS:
        conflict_type: ConflictType = (
            "case_id_conflict" if field == "case_id" else "generic_fact_conflict"
        )
        return "identity", field, conflict_type
    if fact.fact_type == "obligation" and field:
        return "obligation", field, "obligation_conflict"
    if fact.fact_type in {"claim", "communication"} and field:
        return fact.fact_type, field, "generic_fact_conflict"
    return None


def _normalize_party(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    suffixes = {"ltd": "limited", "pvt": "private", "corp": "corporation"}
    return " ".join(suffixes.get(token, token) for token in tokens)


def _normalized_key(fact: ExtractedFact, group: str) -> tuple[str, str]:
    value = fact.normalized_value
    if group == "party":
        normalized = _normalize_party(str(value))
    elif group == "identity":
        normalized = re.sub(r"[^a-z0-9]", "", str(value).casefold())
    elif isinstance(value, (int, float)):
        normalized = str(Decimal(str(value)).normalize())
    else:
        normalized = re.sub(r"\s+", " ", str(value).casefold()).strip()
    return group, normalized


def _severity(group: str, field: str, conflict_type: ConflictType) -> ConflictSeverity:
    if group == "party" or conflict_type == "case_id_conflict":
        return "high"
    if group == "identity":
        return "medium"
    if group == "date":
        return "high" if field in DATE_FIELDS else "medium"
    if group == "financial":
        return "high" if field in TOTAL_AMOUNT_FIELDS else "medium"
    if group == "obligation":
        return "medium"
    return "low"


def _unique(values: list[str | int]) -> list[str | int]:
    return list(dict.fromkeys(values))


def _make_conflicting_value(fact: ExtractedFact, evidence: Evidence) -> ConflictingValue:
    if not fact.document_id or not fact.quote or fact.page < 1:
        raise ValueError("Conflict sources require document, page, and quote provenance.")
    return ConflictingValue(
        value=fact.value,
        normalized_value=fact.normalized_value,
        fact_id=fact.fact_id,
        evidence_id=evidence.evidence_id,
        document_id=fact.document_id,
        page=fact.page,
        quote=fact.quote,
    )


def _make_fact_conflict(
    conflict_number: int,
    group: str,
    field: str,
    conflict_type: ConflictType,
    sources: list[tuple[ExtractedFact, Evidence]],
) -> Conflict:
    conflicting_values = [_make_conflicting_value(fact, evidence) for fact, evidence in sources]
    values = _unique([str(item.normalized_value) for item in conflicting_values])
    confidence = round(
        min(0.99, sum(fact.confidence for fact, _ in sources) / len(sources)),
        2,
    )
    return Conflict(
        conflict_id=f"C{conflict_number:03d}",
        conflict_type=conflict_type,
        fact_type=group,
        event_type=field,
        description=f"Conflicting values for {field}: {', '.join(values)}.",
        severity=_severity(group, field, conflict_type),
        conflicting_values=conflicting_values,
        evidence_ids=[evidence.evidence_id for _, evidence in sources],
        document_ids=_unique([fact.document_id for fact, _ in sources if fact.document_id]),
        source_pages=[fact.page for fact, _ in sources],
        quotes=[fact.quote for fact, _ in sources],
        confidence=confidence,
    )


def _find_claim_evidence_conflicts(
    first_conflict_number: int,
    facts: list[ExtractedFact],
    evidence_by_fact: dict[tuple[str, str], Evidence],
    claims: list[ExtractedClaim],
) -> list[Conflict]:
    obligation_facts = [
        fact
        for fact in facts
        if fact.field in TOTAL_AMOUNT_FIELDS | {"amount_due"}
        and isinstance(fact.normalized_value, (int, float))
    ]
    payment_facts = [
        fact
        for fact in facts
        if fact.field == "amount_paid"
        and isinstance(fact.normalized_value, (int, float))
    ]
    if len(obligation_facts) != 1 or len(payment_facts) != 1:
        return []

    obligation = obligation_facts[0]
    payment = payment_facts[0]
    obligation_evidence = evidence_by_fact.get((obligation.document_id or "", obligation.fact_id))
    payment_evidence = evidence_by_fact.get((payment.document_id or "", payment.fact_id))
    if obligation_evidence is None or payment_evidence is None:
        return []
    if obligation.normalized_value <= payment.normalized_value:
        return []

    conflicts = []
    for claim in claims:
        if claim.claim_type != "payment_claim" or FULL_PAYMENT_PATTERN.search(claim.claim_text) is None:
            continue
        sources = [
            (obligation, obligation_evidence),
            (payment, payment_evidence),
        ]
        conflicting_values = [_make_conflicting_value(fact, item) for fact, item in sources]
        evidence_ids = [item.evidence_id for _, item in sources]
        document_ids = _unique(
            [fact.document_id for fact, _ in sources if fact.document_id]
            + ([claim.document_id] if claim.document_id else [])
        )
        source_pages = [fact.page for fact, _ in sources] + [claim.page]
        quotes = [fact.quote for fact, _ in sources] + [claim.quote]
        confidence = round(
            min(claim.confidence, obligation.confidence, payment.confidence),
            2,
        )
        conflicts.append(
            Conflict(
                conflict_id=f"C{first_conflict_number + len(conflicts):03d}",
                conflict_type="claim_evidence_conflict",
                fact_type="payment_claim",
                event_type="payment_amount",
                description=(
                    "The claim of full payment is not supported by the currently "
                    "extracted payment evidence."
                ),
                severity="high",
                conflicting_values=conflicting_values,
                evidence_ids=evidence_ids,
                document_ids=document_ids,
                source_pages=source_pages,
                quotes=quotes,
                claim_ids=[claim.claim_id],
                confidence=confidence,
            )
        )
    return conflicts


def detect_conflicts(
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
) -> list[Conflict]:
    evidence_by_fact = {
        (item.document_id, item.fact_id): item
        for item in evidence
        if item.fact_id and item.document_id
    }
    groups: dict[tuple[str, str], list[tuple[ExtractedFact, Evidence]]] = defaultdict(list)

    for fact in facts:
        if not fact.document_id:
            continue
        evidence_item = evidence_by_fact.get((fact.document_id, fact.fact_id))
        semantic_group = _semantic_group(fact)
        if evidence_item is None or semantic_group is None:
            continue
        group, field, conflict_type = semantic_group
        groups[(group, field)].append((fact, evidence_item))

    conflicts = []
    for (group, field), sources in groups.items():
        normalized_values = {
            _normalized_key(fact, group)[1]
            for fact, _ in sources
        }
        if len(normalized_values) < 2:
            continue
        conflict_type = _semantic_group(sources[0][0])[2]
        conflicts.append(
            _make_fact_conflict(
                len(conflicts) + 1,
                group,
                field,
                conflict_type,
                sources,
            )
        )

    conflicts.extend(
        _find_claim_evidence_conflicts(
            len(conflicts) + 1,
            facts,
            evidence_by_fact,
            claims,
        )
    )
    return conflicts