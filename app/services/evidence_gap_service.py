from decimal import Decimal

from app.schemas.conflict import Conflict
from app.schemas.document_classification import DocumentClassificationResult
from app.schemas.evidence import Evidence, ExtractedClaim
from app.schemas.evidence_gap import EvidenceGap, EvidenceGapType, GapImportance
from app.schemas.facts import ExtractedFact

FULL_PAYMENT_PHRASES = (
    "full payment",
    "full amount",
    "entire amount",
    "entire balance",
    "paid in full",
    "fully paid",
)
PARTY_FIELDS = {"seller", "buyer", "claimant", "respondent", "sender", "recipient"}
CONTRACT_BASIS_FIELDS = {
    "contract_amount",
    "total_contract_amount",
    "total_amount",
    "payment_due_date",
    "amount_due",
    "payment_obligation",
    "delivery_obligation",
}
PAYMENT_CLAIM_TYPES = {
    "payment_claim",
    "non_payment_claim",
    "amount_claim",
    "contractual_obligation_claim",
    "breach_claim",
}


def _unique(values: list[str | int]) -> list:
    return list(dict.fromkeys(value for value in values if value))


def _make_gap(
    number: int,
    gap_type: EvidenceGapType,
    description: str,
    importance: GapImportance,
    reason: str,
    confidence: float,
    *,
    facts: list[ExtractedFact] | None = None,
    evidence: list[Evidence] | None = None,
    claims: list[ExtractedClaim] | None = None,
    conflicts: list[Conflict] | None = None,
    suggested_evidence: list[str] | None = None,
) -> EvidenceGap:
    facts = facts or []
    evidence = evidence or []
    claims = claims or []
    conflicts = conflicts or []
    conflict_evidence_ids = [value for conflict in conflicts for value in conflict.evidence_ids]
    conflict_document_ids = [value for conflict in conflicts for value in conflict.document_ids]
    conflict_pages = [value for conflict in conflicts for value in conflict.source_pages]
    conflict_quotes = [value for conflict in conflicts for value in conflict.quotes]

    return EvidenceGap(
        gap_id=f"G{number:03d}",
        gap_type=gap_type,
        description=description,
        importance=importance,
        related_fact_types=_unique([fact.fact_type for fact in facts]),
        related_claim_ids=_unique(
            [claim.claim_id for claim in claims]
            + [claim_id for conflict in conflicts for claim_id in conflict.claim_ids]
        ),
        related_evidence_ids=_unique(
            [item.evidence_id for item in evidence] + conflict_evidence_ids
        ),
        related_conflict_ids=_unique([conflict.conflict_id for conflict in conflicts]),
        related_document_ids=_unique(
            [fact.document_id for fact in facts if fact.document_id]
            + [item.document_id for item in evidence]
            + [claim.document_id for claim in claims]
            + conflict_document_ids
        ),
        source_pages=(
            [fact.page for fact in facts]
            + [item.page for item in evidence]
            + [claim.page for claim in claims]
            + conflict_pages
        ),
        quotes=(
            [fact.quote for fact in facts]
            + [item.quote for item in evidence]
            + [claim.quote for claim in claims]
            + conflict_quotes
        ),
        suggested_evidence=suggested_evidence or [],
        reason=reason,
        confidence=confidence,
    )


def _payment_gaps(
    start_number: int,
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
) -> list[EvidenceGap]:
    full_payment_claims = [
        claim
        for claim in claims
        if claim.claim_type == "payment_claim"
        and any(phrase in claim.claim_text.casefold() for phrase in FULL_PAYMENT_PHRASES)
    ]
    if not full_payment_claims:
        return []

    payment_evidence = [item for item in evidence if item.evidence_type == "payment_record"]
    obligation_fields = CONTRACT_BASIS_FIELDS | {"invoice_amount"}
    obligation_facts = [
        fact
        for fact in facts
        if fact.field in obligation_fields
        and isinstance(fact.normalized_value, (int, float))
    ]
    payment_facts = [
        fact
        for fact in facts
        if fact.field in {"amount_paid", "payment_amount"}
        and isinstance(fact.normalized_value, (int, float))
        and any(
            item.evidence_type == "payment_record"
            and item.fact_id == fact.fact_id
            and item.document_id == fact.document_id
            for item in evidence
        )
    ]

    amount_known = len(obligation_facts) == 1 and len(payment_facts) == 1
    if amount_known:
        obligation_amount = Decimal(str(obligation_facts[0].normalized_value))
        payment_amount = Decimal(str(payment_facts[0].normalized_value))
        if payment_amount >= obligation_amount:
            return []
        relevant_facts = [obligation_facts[0], payment_facts[0]]
        relevant_fact_keys = {
            (fact.document_id, fact.fact_id) for fact in relevant_facts
        }
        relevant_evidence = [
            item
            for item in evidence
            if (item.document_id, item.fact_id) in relevant_fact_keys
        ]
        reason = (
            f"The full-payment claim references an obligation of {obligation_amount} "
            f"but the available payment evidence totals {payment_amount}; proof for "
            "the remaining amount is not present."
        )
        confidence = 0.96
    else:
        relevant_facts = obligation_facts + payment_facts
        relevant_evidence = payment_evidence + [
            item
            for item in evidence
            if item.evidence_type == "contract_term"
            and item.fact_id
            and any(fact.fact_id == item.fact_id for fact in obligation_facts)
        ]
        reason = (
            "The claim asserts full payment, but the available records do not establish "
            "the full obligation and payment amounts."
        )
        confidence = 0.9 if not payment_evidence else 0.76

    return [
        _make_gap(
            start_number,
            "missing_payment_proof",
            "Payment proof is not available for the full-payment claim.",
            "high",
            reason,
            confidence,
            facts=relevant_facts,
            evidence=relevant_evidence,
            claims=full_payment_claims,
            suggested_evidence=[
                "Bank statement, payment receipt, transaction confirmation, or equivalent proof for the full claimed amount."
            ],
        )
    ]


def _delivery_gaps(
    start_number: int,
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
) -> list[EvidenceGap]:
    delivery_claims = [claim for claim in claims if claim.claim_type == "delivery_claim"]
    if not delivery_claims or any(item.evidence_type == "delivery_record" for item in evidence):
        return []
    return [
        _make_gap(
            start_number,
            "missing_delivery_proof",
            "A delivery claim is present, but no delivery record was found.",
            "high",
            "The claim text indicates delivery; the supplied evidence contains no delivery receipt or equivalent record.",
            0.9,
            claims=delivery_claims,
            suggested_evidence=[
                "Delivery receipt, acknowledgement, transport record, or equivalent delivery evidence."
            ],
        )
    ]


def _unsupported_claim_gaps(
    start_number: int,
    claims: list[ExtractedClaim],
    evidence: list[Evidence],
) -> list[EvidenceGap]:
    available_ids = {(item.document_id, item.evidence_id) for item in evidence}
    gaps = []
    for claim in claims:
        linked_ids = [
            evidence_id
            for evidence_id in claim.supporting_evidence_ids
            if (claim.document_id, evidence_id) in available_ids
        ]
        if linked_ids:
            continue
        gaps.append(
            _make_gap(
                start_number + len(gaps),
                "unsupported_claim",
                "The claim has no linked supporting evidence in the supplied records.",
                "medium",
                "The claim is an extracted statement and is not independently supported by linked evidence.",
                0.92,
                claims=[claim],
                suggested_evidence=[
                    "A relevant primary document or record that independently supports the claim."
                ],
            )
        )
    return gaps


def _conflict_gaps(start_number: int, conflicts: list[Conflict]) -> list[EvidenceGap]:
    unresolved = [
        conflict
        for conflict in conflicts
        if conflict.status == "open" and conflict.severity in {"high", "medium"}
    ]
    return [
        _make_gap(
            start_number + offset,
            "unresolved_conflict",
            "An open conflict remains unresolved; additional verification is required.",
            conflict.severity,
            conflict.description,
            min(0.95, conflict.confidence),
            conflicts=[conflict],
            suggested_evidence=[
                "An authoritative record or independent source that resolves the conflicting values."
            ],
        )
        for offset, conflict in enumerate(unresolved)
    ]


def _party_identity_gap(
    start_number: int,
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
) -> EvidenceGap | None:
    known_party_fact_ids = {
        (fact.document_id, fact.fact_id)
        for fact in facts
        if fact.fact_type == "party" and fact.field in PARTY_FIELDS
    }
    supported_party_facts = {
        (item.document_id, item.fact_id)
        for item in evidence
        if item.fact_id and (item.document_id, item.fact_id) in known_party_fact_ids
    }
    if not facts and not claims or supported_party_facts:
        return None
    return _make_gap(
        start_number,
        "missing_party_identity",
        "Party information is present in the case records, but no supported party identity fact was found.",
        "medium",
        "The supplied facts and claims do not link a named party to source evidence.",
        0.82,
        facts=facts,
        evidence=evidence,
        claims=claims,
        suggested_evidence=[
            "Verified party identification or an authoritative case record."
        ],
    )


def _contract_basis_gap(
    start_number: int,
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
    classification: DocumentClassificationResult | None,
) -> EvidenceGap | None:
    relevant_claims = [claim for claim in claims if claim.claim_type in PAYMENT_CLAIM_TYPES]
    if not relevant_claims:
        return None
    fact_fields = {
        (fact.document_id, fact.fact_id): fact.field
        for fact in facts
    }
    has_contract_basis = any(
        item.evidence_type == "contract_term"
        and item.fact_id
        and fact_fields.get((item.document_id, item.fact_id)) in CONTRACT_BASIS_FIELDS
        for item in evidence
    )
    if has_contract_basis:
        return None
    if classification and classification.document_type == "contract":
        reason = (
            "The document is classified as a contract, but no linked evidence establishes "
            "the payment or obligation terms stated in the claim."
        )
    else:
        reason = "No linked contract-term evidence establishes the claimed payment or obligation terms."
    return _make_gap(
        start_number,
        "missing_contract",
        "The available documents contain a payment or obligation claim, but the underlying contractual basis was not found.",
        "high",
        reason,
        0.88,
        facts=facts,
        evidence=evidence,
        claims=relevant_claims,
        suggested_evidence=[
            "The signed contract, agreement, purchase order, or other authoritative obligation record."
        ],
    )


def detect_evidence_gaps(
    facts: list[ExtractedFact],
    evidence: list[Evidence],
    claims: list[ExtractedClaim],
    conflicts: list[Conflict],
    classification: DocumentClassificationResult | None = None,
) -> list[EvidenceGap]:
    gaps: list[EvidenceGap] = []
    gaps.extend(_payment_gaps(len(gaps) + 1, facts, evidence, claims))
    gaps.extend(_delivery_gaps(len(gaps) + 1, evidence, claims))
    gaps.extend(_unsupported_claim_gaps(len(gaps) + 1, claims, evidence))
    gaps.extend(_conflict_gaps(len(gaps) + 1, conflicts))

    party_gap = _party_identity_gap(len(gaps) + 1, facts, evidence, claims)
    if party_gap is not None:
        gaps.append(party_gap)
    contract_gap = _contract_basis_gap(
        len(gaps) + 1,
        facts,
        evidence,
        claims,
        classification,
    )
    if contract_gap is not None:
        gaps.append(contract_gap)
    return gaps