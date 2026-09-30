"""Explicit deterministic rules for evidence support and insufficiency."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
from typing import Any

from backend.app.rules.schemas import EvidenceGap, RuleConflict, RuleEvidence, RuleFact


HIGH_CONFIDENCE_THRESHOLD = 0.85


@dataclass(frozen=True)
class RuleContext:
	fact_type: str
	facts: Sequence[RuleFact]
	evidence: Sequence[RuleEvidence]
	conflicts: Sequence[RuleConflict]
	evidence_gaps: Sequence[EvidenceGap]
	critical: bool


@dataclass(frozen=True)
class RuleDecision:
	condition_met: bool
	result: str
	explanation: str
	missing_evidence: tuple[str, ...] = ()
	uncertainties: tuple[str, ...] = ()


RuleEvaluator = Callable[[RuleContext], RuleDecision]


def value_key(value: Any) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True)
class SymbolicRule:
	rule_id: str
	name: str
	description: str
	evaluate: RuleEvaluator


def _has_conflict(context: RuleContext) -> RuleDecision:
	conflict_ids = [item.conflict_id for item in context.conflicts]
	values = {value_key(item.value) for item in context.evidence}
	fact_values = {value_key(item.value) for item in context.facts}
	disagreement = len(values | fact_values) > 1
	met = bool(context.conflicts) or disagreement
	used = ", ".join(conflict_ids) if conflict_ids else "no supplied conflict record"
	explanation = (
		f"Competing values are present for {context.fact_type!r}; {used}. No value is selected."
		if met
		else f"No supplied conflict or differing reported values were found for {context.fact_type!r}."
	)
	uncertainty = (
		(f"The available inputs do not establish which reported value for {context.fact_type!r} is authoritative.",)
		if met
		else ()
	)
	return RuleDecision(met, "conflicting" if met else "no_conflict_detected", explanation, uncertainties=uncertainty)


def _has_consistent_independent_support(context: RuleContext) -> RuleDecision:
	document_ids = {item.document_id for item in context.evidence}
	values = {value_key(item.value) for item in context.evidence}
	values.update(value_key(item.value) for item in context.facts)
	met = len(document_ids) >= 2 and len(values) == 1 and not context.conflicts
	explanation = (
		f"At least two documents consistently report one value for {context.fact_type!r}."
		if met
		else "Consistent evidence from at least two distinct documents was not established."
	)
	return RuleDecision(met, "consistent_independent_support" if met else "not_established", explanation)


def _has_strong_direct_support(context: RuleContext) -> RuleDecision:
	qualifying = [
		item
		for item in context.evidence
		if item.evidence_type == "direct_documentary"
		and item.confidence >= HIGH_CONFIDENCE_THRESHOLD
	]
	values = {value_key(item.value) for item in context.evidence}
	values.update(value_key(item.value) for item in context.facts)
	met = bool(qualifying) and len(values) <= 1 and not context.conflicts
	ids = ", ".join(sorted(item.evidence_id for item in qualifying))
	explanation = (
		f"{ids} meet the direct-documentary confidence threshold of "
		f"{HIGH_CONFIDENCE_THRESHOLD:.2f} for {context.fact_type!r}."
		if met
		else "No uncontradicted direct documentary evidence meets the configured confidence threshold."
	)
	return RuleDecision(met, "strongly_supported" if met else "not_established", explanation)


def _has_weak_evidence(context: RuleContext) -> RuleDecision:
	qualifying = any(
		item.evidence_type == "direct_documentary"
		and item.confidence >= HIGH_CONFIDENCE_THRESHOLD
		for item in context.evidence
	)
	met = bool(context.evidence or context.facts) and not qualifying
	explanation = (
		f"Inputs exist for {context.fact_type!r}, but none meets the direct-documentary "
		f"confidence threshold of {HIGH_CONFIDENCE_THRESHOLD:.2f}."
		if met
		else "No weak-only evidence condition was found."
	)
	uncertainty = (
		(f"Evidence for {context.fact_type!r} does not meet the configured support threshold.",)
		if met
		else ()
	)
	return RuleDecision(met, "uncertain" if met else "not_established", explanation, uncertainties=uncertainty)


def _has_explicit_evidence_gap(context: RuleContext) -> RuleDecision:
	gaps = [gap for gap in context.evidence_gaps if gap.fact_type == context.fact_type]
	descriptions = tuple(gap.required_evidence for gap in gaps)
	met = bool(gaps)
	explanation = (
		f"Evidence gap(s) {', '.join(gap.gap_id for gap in gaps)} identify missing support for "
		f"{context.fact_type!r}."
		if met
		else "No explicit evidence gap was supplied for this fact."
	)
	return RuleDecision(
		met,
		"insufficient_evidence" if met else "no_gap_reported",
		explanation,
		missing_evidence=descriptions,
	)


def _has_missing_critical_support(context: RuleContext) -> RuleDecision:
	linked_fact_evidence = any(item.evidence_ids for item in context.facts)
	met = context.critical and not context.evidence and not linked_fact_evidence
	missing = (
		(f"Provide evidence responsive to critical fact {context.fact_type!r}.",)
		if met
		else ()
	)
	explanation = (
		f"Critical fact {context.fact_type!r} has no supporting fact or evidence input."
		if met
		else "The critical-fact-without-support condition was not met."
	)
	return RuleDecision(met, "insufficient_evidence" if met else "support_present_or_not_critical", explanation, missing_evidence=missing)


R001 = SymbolicRule(
	"R001", "Conflicting reported values", "Retain conflicts; never choose between competing reported values.", _has_conflict
)
R002 = SymbolicRule(
	"R002", "Consistent independent support", "Recognize a single value consistently reported by at least two distinct documents.", _has_consistent_independent_support
)
R003 = SymbolicRule(
	"R003", "Strong direct documentary support", "Recognize uncontradicted direct documentary evidence at or above the configured confidence threshold.", _has_strong_direct_support
)
R004 = SymbolicRule(
	"R004", "Low-confidence or indirect evidence", "Mark supplied evidence uncertain when none meets the direct-documentary confidence threshold.", _has_weak_evidence
)
R005 = SymbolicRule(
	"R005", "Explicit evidence gap", "Report required evidence named by an upstream evidence-gap record.", _has_explicit_evidence_gap
)
R006 = SymbolicRule(
	"R006", "Missing critical support", "Mark a named critical fact insufficient when no supporting fact or evidence was supplied.", _has_missing_critical_support
)

RULES: tuple[SymbolicRule, ...] = (R001, R002, R003, R004, R005, R006)
