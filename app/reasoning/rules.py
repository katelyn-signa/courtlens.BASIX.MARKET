from dataclasses import dataclass


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    rule_name: str
    version: str
    description: str
    condition: str


SOURCE_AUTHORITY = {
    "court_order": 3,
    "advocate_note": 2,
    "party_document": 1,
}
SOURCE_LABELS = {
    "court_order": "Official Court Order",
    "advocate_note": "Advocate Note",
    "party_document": "Party Document",
}


R001_PAYMENT_GAP = RuleDefinition(
    rule_id="R001",
    rule_name="payment_gap_v1",
    version="1",
    description="Identify a potential shortfall between an obligation and source-supported payment records.",
    condition=(
        "One unique monetary payment obligation and one or more linked, high-confidence "
        "payment-record facts exist in the same currency, and recorded payment is lower."
    ),
)
R002_PAYMENT_CLAIM_CONFLICT = RuleDefinition(
    rule_id="R002",
    rule_name="payment_claim_conflict_v1",
    version="1",
    description="Identify a full-payment claim not supported by available payment records.",
    condition=(
        "A full-payment claim exists, payment-record evidence exists, and the recorded "
        "payment amount is below the linked obligation or claimed amount."
    ),
)
R003_DATE_CONFLICT = RuleDefinition(
    rule_id="R003",
    rule_name="date_conflict_v1",
    version="1",
    description="Identify differing dates for the same named event when both values have evidence provenance.",
    condition="At least two date observations share an event field and have different normalized dates.",
)
R004_EVIDENCE_GAP = RuleDefinition(
    rule_id="R004",
    rule_name="evidence_gap_v1",
    version="1",
    description="Carry existing evidence-gap findings into the reasoning trace.",
    condition="One or more evidence-gap observations are present.",
)
R005_HUMAN_REVIEW = RuleDefinition(
    rule_id="R005",
    rule_name="human_review_v1",
    version="1",
    description="Require human review when material conflicts or missing evidence affect the result.",
    condition=(
        "A high-severity conflict, any unresolved evidence gap, or a triggered payment "
        "claim/date conflict is present."
    ),
)
R006_SOURCE_AUTHORITY = RuleDefinition(
    rule_id="R006",
    rule_name="source_authority_v1",
    version="1",
    description="Rank conflicting hearing-date sources using configured source authority.",
    condition=(
        "Conflicting hearing dates have source types with configured authority levels; "
        "the highest-ranked source informs a recommendation for human confirmation."
    ),
)

RULE_DEFINITIONS = (
    R001_PAYMENT_GAP,
    R002_PAYMENT_CLAIM_CONFLICT,
    R003_DATE_CONFLICT,
    R004_EVIDENCE_GAP,
    R005_HUMAN_REVIEW,
    R006_SOURCE_AUTHORITY,
)