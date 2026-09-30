from collections import defaultdict
from datetime import date
from decimal import Decimal

from app.reasoning.rules import (
    R001_PAYMENT_GAP,
    R002_PAYMENT_CLAIM_CONFLICT,
    R003_DATE_CONFLICT,
    R004_EVIDENCE_GAP,
    R005_HUMAN_REVIEW,
    R006_SOURCE_AUTHORITY,
    SOURCE_AUTHORITY,
    SOURCE_LABELS,
    RuleDefinition,
)
from app.schemas.reasoning import RuleEvaluation, SemanticInterpretation, SemanticObservation


def _source_ids(observations: list[SemanticObservation]) -> list[str]:
    return [
        reference.evidence_id
        for observation in observations
        for reference in observation.evidence_refs
    ]


def _evaluation(
    definition: RuleDefinition,
    *,
    triggered: bool,
    explanation: str,
    observations: list[SemanticObservation] | None = None,
    result: dict | None = None,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=definition.rule_id,
        rule_name=definition.rule_name,
        version=definition.version,
        description=definition.description,
        condition=definition.condition,
        triggered=triggered,
        evidence_ids=_source_ids(observations or []),
        explanation=explanation,
        result=result or {},
    )


def _payment_gap_rule(observations: list[SemanticObservation]) -> RuleEvaluation:
    obligations = [
        item
        for item in observations
        if item.observation_type == "payment_obligation"
        and item.amount is not None
        and item.evidence_refs
    ]
    payments = [
        item
        for item in observations
        if item.observation_type == "payment_record"
        and item.amount is not None
        and item.evidence_refs
        and item.source_supported
    ]
    obligation_values = {(item.amount, item.currency) for item in obligations}
    if len(obligation_values) != 1 or not payments:
        return _evaluation(
            R001_PAYMENT_GAP,
            triggered=False,
            explanation="Required linked obligation and payment-record evidence was not available.",
        )

    obligation_amount, obligation_currency = next(iter(obligation_values))
    same_currency_payments = [
        item for item in payments if item.currency == obligation_currency
    ]
    if not same_currency_payments:
        return _evaluation(
            R001_PAYMENT_GAP,
            triggered=False,
            explanation="Payment evidence currency does not match the obligation currency.",
            observations=obligations + payments,
        )

    paid_total = sum(Decimal(str(item.amount)) for item in same_currency_payments)
    obligation_total = Decimal(str(obligation_amount))
    sources = obligations + same_currency_payments
    if paid_total >= obligation_total:
        return _evaluation(
            R001_PAYMENT_GAP,
            triggered=False,
            explanation="Available linked payment records do not show a shortfall against the obligation.",
            observations=sources,
            result={
                "obligation_amount": float(obligation_total),
                "recorded_payment": float(paid_total),
                "currency": obligation_currency,
            },
        )

    shortfall = obligation_total - paid_total
    return _evaluation(
        R001_PAYMENT_GAP,
        triggered=True,
        explanation=(
            "Linked payment-record evidence totals less than the recorded obligation; "
            "this identifies a potential shortfall, not legal liability."
        ),
        observations=sources,
        result={
            "obligation_amount": int(obligation_total) if obligation_total == obligation_total.to_integral_value() else float(obligation_total),
            "recorded_payment": int(paid_total) if paid_total == paid_total.to_integral_value() else float(paid_total),
            "potential_shortfall": int(shortfall) if shortfall == shortfall.to_integral_value() else float(shortfall),
            "currency": obligation_currency,
        },
    )


def _payment_claim_conflict_rule(
    observations: list[SemanticObservation],
) -> RuleEvaluation:
    claims = [
        item
        for item in observations
        if item.observation_type == "payment_claim" and item.full_payment_claim
    ]
    obligations = [
        item
        for item in observations
        if item.observation_type == "payment_obligation" and item.amount is not None
    ]
    payments = [
        item
        for item in observations
        if item.observation_type == "payment_record"
        and item.amount is not None
        and item.source_supported
    ]
    if not claims or not payments:
        return _evaluation(
            R002_PAYMENT_CLAIM_CONFLICT,
            triggered=False,
            explanation="No full-payment claim with linked payment-record evidence was available for comparison.",
        )

    claimed_amounts = [item.amount for item in claims if item.amount is not None]
    expected_amount = claimed_amounts[0] if claimed_amounts else (
        obligations[0].amount if len(obligations) == 1 else None
    )
    if expected_amount is None:
        return _evaluation(
            R002_PAYMENT_CLAIM_CONFLICT,
            triggered=False,
            explanation="The full-payment claim could not be compared to one unambiguous amount.",
            observations=claims + payments,
        )

    matched_payments = [
        item for item in payments if item.currency == (claims[0].currency or (obligations[0].currency if obligations else None))
    ]
    if not matched_payments:
        return _evaluation(
            R002_PAYMENT_CLAIM_CONFLICT,
            triggered=False,
            explanation="No payment records in the comparable currency were available.",
            observations=claims + payments,
        )

    paid_total = sum(Decimal(str(item.amount)) for item in matched_payments)
    expected_total = Decimal(str(expected_amount))
    if paid_total >= expected_total:
        return _evaluation(
            R002_PAYMENT_CLAIM_CONFLICT,
            triggered=False,
            explanation="Available payment records are not below the amount asserted by the full-payment claim.",
            observations=claims + matched_payments,
        )
    return _evaluation(
        R002_PAYMENT_CLAIM_CONFLICT,
        triggered=True,
        explanation="Available payment-record evidence does not support the full-payment amount asserted in the claim.",
        observations=claims + matched_payments + obligations,
        result={
            "claimed_or_obligation_amount": float(expected_total),
            "recorded_payment": float(paid_total),
            "currency": matched_payments[0].currency,
        },
    )


def _date_conflict_rule(observations: list[SemanticObservation]) -> RuleEvaluation:
    events: dict[str, list[SemanticObservation]] = defaultdict(list)
    for item in observations:
        if item.observation_type == "date_event" and item.normalized_value is not None:
            events[item.event_type or item.field or ""].append(item)
    for event_type, event_items in events.items():
        values = {item.normalized_value for item in event_items}
        provenance_items = [item for item in event_items if item.evidence_refs]
        if len(values) < 2 or len(provenance_items) < 2:
            continue
        return _evaluation(
            R003_DATE_CONFLICT,
            triggered=True,
            explanation=f"Source evidence records differing dates for the same event '{event_type}'.",
            observations=provenance_items,
            result={"event_type": event_type, "dates": sorted(str(value) for value in values)},
        )

    supplied_conflicts = [
        item
        for item in observations
        if item.observation_type == "conflict"
        and item.conflict_type == "date_conflict"
        and item.event_type
        and len(item.evidence_refs) >= 2
    ]
    if supplied_conflicts:
        return _evaluation(
            R003_DATE_CONFLICT,
            triggered=True,
            explanation="The supplied analysis contains a date conflict requiring verification.",
            observations=supplied_conflicts,
            result={
                "event_type": supplied_conflicts[0].event_type,
                "conflict_ids": [item.conflict_id for item in supplied_conflicts],
            },
        )
    return _evaluation(
        R003_DATE_CONFLICT,
        triggered=False,
        explanation="No same-event date disagreement with source provenance was found.",
    )


def _source_authority_rule(
    observations: list[SemanticObservation],
) -> RuleEvaluation:
    hearing_dates = [
        item
        for item in observations
        if item.observation_type == "date_event"
        and item.event_type == "hearing_date"
        and item.normalized_value is not None
        and item.source_authority is not None
        and item.source_type in SOURCE_LABELS
        and item.evidence_refs
    ]
    if len({item.normalized_value for item in hearing_dates}) < 2:
        return _evaluation(
            R006_SOURCE_AUTHORITY,
            triggered=False,
            explanation="No conflicting hearing dates with configured source authority were found.",
        )

    highest_authority = max(item.source_authority for item in hearing_dates)
    highest_ranked = [
        item for item in hearing_dates if item.source_authority == highest_authority
    ]
    ranked_types = sorted(
        {item.source_type for item in hearing_dates},
        key=lambda source_type: (
            -SOURCE_AUTHORITY[source_type],
            SOURCE_LABELS[source_type],
        ),
    )
    hierarchy = " > ".join(SOURCE_LABELS[source_type] for source_type in ranked_types)

    if len({item.normalized_value for item in highest_ranked}) > 1:
        return _evaluation(
            R006_SOURCE_AUTHORITY,
            triggered=True,
            explanation="Source authority was evaluated, but the highest-ranked sources disagree.",
            observations=hearing_dates,
            result={"source_hierarchy": hierarchy, "authority_tie": True},
        )

    winner = sorted(highest_ranked, key=lambda item: item.document_id or "")[0]
    source_label = SOURCE_LABELS[winner.source_type]
    reason = (
        "Two documents contain different hearing dates. The "
        f"{source_label.casefold()} has higher configured source authority."
    )
    return _evaluation(
        R006_SOURCE_AUTHORITY,
        triggered=True,
        explanation="Source authority was evaluated against the configured hierarchy.",
        observations=hearing_dates,
        result={
            "recommended_value": str(winner.normalized_value),
            "recommendation_date": _display_date(str(winner.normalized_value)),
            "evidence_source": source_label,
            "source_type": winner.source_type,
            "document_id": winner.document_id,
            "authority": winner.source_authority,
            "source_hierarchy": hierarchy,
            "rule": hierarchy,
            "reason": reason,
            "configured_source_authority": SOURCE_AUTHORITY,
        },
    )


def _display_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.day} {parsed.strftime('%B %Y')}"


def _evidence_gap_rule(observations: list[SemanticObservation]) -> RuleEvaluation:
    gaps = [item for item in observations if item.observation_type == "evidence_gap"]
    return _evaluation(
        R004_EVIDENCE_GAP,
        triggered=bool(gaps),
        explanation=(
            "One or more supplied evidence gaps remain unresolved."
            if gaps
            else "No evidence gaps were supplied."
        ),
        observations=gaps,
        result={"gap_ids": [item.gap_id for item in gaps if item.gap_id]},
    )


def _human_review_rule(
    observations: list[SemanticObservation],
    evaluations: list[RuleEvaluation],
) -> RuleEvaluation:
    conflicts = [
        item
        for item in observations
        if item.observation_type == "conflict" and item.severity == "high"
    ]
    gaps = [item for item in observations if item.observation_type == "evidence_gap"]
    contradictory_rules = [
        evaluation
        for evaluation in evaluations
        if evaluation.rule_id in {"R001", "R002", "R003"} and evaluation.triggered
    ]
    triggered = bool(conflicts or gaps or contradictory_rules)
    relevant = conflicts + gaps
    if contradictory_rules:
        evidence_ids = [
            evidence_id
            for evaluation in contradictory_rules
            for evidence_id in evaluation.evidence_ids
        ]
        relevant.extend(
            item
            for item in observations
            if any(ref.evidence_id in evidence_ids for ref in item.evidence_refs)
        )
    return _evaluation(
        R005_HUMAN_REVIEW,
        triggered=triggered,
        explanation=(
            "Human review is required because high-severity conflicts, unresolved gaps, "
            "or contradictory evidence affect this result."
            if triggered
            else "No configured conflict or evidence-gap condition currently requires human review."
        ),
        observations=relevant,
        result={
            "high_severity_conflict_count": len(conflicts),
            "evidence_gap_count": len(gaps),
            "contradictory_rule_ids": [item.rule_id for item in contradictory_rules],
        },
    )


def evaluate_rules(
    interpretation: SemanticInterpretation,
    rule_ids: set[str] | None = None,
) -> list[RuleEvaluation]:
    rule_functions = (
        ("R001", lambda: _payment_gap_rule(interpretation.observations)),
        ("R002", lambda: _payment_claim_conflict_rule(interpretation.observations)),
        ("R003", lambda: _date_conflict_rule(interpretation.observations)),
        ("R004", lambda: _evidence_gap_rule(interpretation.observations)),
    )
    evaluations = [
        function()
        for rule_id, function in rule_functions
        if rule_ids is None or rule_id in rule_ids
    ]
    authority_evaluation = _source_authority_rule(interpretation.observations)
    if authority_evaluation.triggered or (rule_ids and "R006" in rule_ids):
        evaluations.append(authority_evaluation)
    evaluations.append(_human_review_rule(interpretation.observations, evaluations))
    return evaluations


def evaluate_human_review(
    interpretation: SemanticInterpretation,
    evaluations: list[RuleEvaluation],
) -> RuleEvaluation:
    applicable = [item for item in evaluations if item.rule_id != "R005"]
    return _human_review_rule(interpretation.observations, applicable)