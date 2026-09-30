"""Deterministic evaluator for the explicit CourtLens evidence rules."""

from collections import defaultdict

from backend.app.rules.rules import (
	RULES,
	RuleContext,
	value_key,
)
from backend.app.rules.schemas import (
	FactAssessment,
	RuleEngineRequest,
	RuleEngineResult,
	RuleExecution,
	RuleEvaluation,
)


class RuleEngine:
	"""Evaluates all registered rules and returns complete per-rule audit outcomes."""

	def __init__(self, rules=RULES) -> None:
		self.rules = tuple(rules)
		rule_ids = [rule.rule_id for rule in self.rules]
		if len(rule_ids) != len(set(rule_ids)):
			raise ValueError("rule_id values must be unique")

	def evaluate(self, request: RuleEngineRequest) -> RuleEngineResult:
		evidence_by_type = defaultdict(list)
		facts_by_type = defaultdict(list)
		conflicts_by_type = defaultdict(list)
		gaps_by_type = defaultdict(list)
		for item in request.evidence:
			evidence_by_type[item.fact_type].append(item)
		for item in request.facts:
			facts_by_type[item.fact_type].append(item)
		for item in request.conflicts:
			conflicts_by_type[item.fact_type].append(item)
		for item in request.evidence_gaps:
			gaps_by_type[item.fact_type].append(item)

		fact_types = sorted(
			set(evidence_by_type)
			| set(facts_by_type)
			| set(conflicts_by_type)
			| set(gaps_by_type)
			| set(request.critical_fact_types)
		)
		rule_evaluations: list[RuleEvaluation] = []
		assessments: list[FactAssessment] = []
		missing_evidence: list[str] = []
		uncertainties: list[str] = []

		for fact_type in fact_types:
			facts = sorted(
				facts_by_type[fact_type],
				key=lambda item: (item.fact_id is None, item.fact_id or "", value_key(item.value)),
			)
			evidence = sorted(evidence_by_type[fact_type], key=lambda item: item.evidence_id)
			conflicts = sorted(conflicts_by_type[fact_type], key=lambda item: item.conflict_id)
			gaps = sorted(gaps_by_type[fact_type], key=lambda item: item.gap_id)
			context = RuleContext(
				fact_type=fact_type,
				facts=facts,
				evidence=evidence,
				conflicts=conflicts,
				evidence_gaps=gaps,
				critical=fact_type in request.critical_fact_types,
			)

			current_fact_evaluations: list[RuleEvaluation] = []
			for rule in self.rules:
				decision = rule.evaluate(context)
				evidence_ids = {item.evidence_id for item in evidence}
				evidence_ids.update(
					evidence_id for conflict in conflicts for evidence_id in conflict.evidence_ids
				)
				evaluation = RuleEvaluation(
						rule_id=rule.rule_id,
						rule_name=rule.name,
						description=rule.description,
						conditions_checked=[
							rule.description,
							decision.explanation,
						],
						condition_met=decision.condition_met,
						fired=decision.condition_met,
						input_fact_ids=[item.fact_id for item in facts if item.fact_id is not None],
						input_evidence_ids=sorted(evidence_ids),
						input_conflict_ids=[item.conflict_id for item in conflicts],
						input_gap_ids=[item.gap_id for item in gaps],
						result=decision.result,
						explanation=decision.explanation,
						missing_evidence=list(decision.missing_evidence),
						uncertainties=list(decision.uncertainties),
					)
				current_fact_evaluations.append(evaluation)
				rule_evaluations.append(evaluation)
				missing_evidence.extend(decision.missing_evidence)
				uncertainties.extend(decision.uncertainties)

			candidate_values = {value_key(item.value): item.value for item in facts}
			candidate_values.update(
				{value_key(item.value): item.value for item in evidence}
			)
			ordered_keys = sorted(candidate_values)
			values = [candidate_values[key] for key in ordered_keys]
			fact_rule_evaluations = current_fact_evaluations
			fired_ids = [item.rule_id for item in fact_rule_evaluations if item.fired]
			has_conflict = any(
				item.rule_id == "R001" and item.fired for item in fact_rule_evaluations
			)
			has_gap = any(
				item.rule_id in {"R005", "R006"} and item.fired
				for item in fact_rule_evaluations
			)
			has_strong = any(
				item.rule_id == "R003" and item.fired
				for item in fact_rule_evaluations
			)
			if has_conflict:
				status = "conflicting"
				selected_value = None
				explanation = f"Conflicting values for {fact_type!r} are retained; no value is selected."
			elif has_gap:
				status = "insufficient_evidence"
				selected_value = None
				explanation = f"Required evidence for {fact_type!r} is missing or was not supplied."
			elif has_strong:
				status = "strongly_supported"
				selected_value = values[0] if len(values) == 1 else None
				explanation = f"The supplied evidence strongly supports one reported value for {fact_type!r}."
			elif any(item.rule_id == "R004" and item.fired for item in fact_rule_evaluations):
				status = "uncertain"
				selected_value = None
				explanation = f"The supplied evidence for {fact_type!r} is weak or indirect."
			else:
				status = "insufficient_evidence"
				selected_value = None
				explanation = f"No rule established sufficient support for {fact_type!r}."

			assessments.append(
				FactAssessment(
					fact_type=fact_type,
					values=values,
					evidence_ids=[item.evidence_id for item in evidence],
					fact_ids=[item.fact_id for item in facts if item.fact_id is not None],
					conflict_ids=[item.conflict_id for item in conflicts],
					status=status,
					selected_value=selected_value,
					explanation=explanation,
					rule_ids=fired_ids,
				)
			)

		fired_evaluations = [item for item in rule_evaluations if item.fired]
		legacy_fired = [
			RuleExecution(
				rule_id=item.rule_id,
				rule_name=item.rule_name,
				input_evidence_ids=item.input_evidence_ids,
				condition="; ".join(item.conditions_checked),
				result=item.result,
				explanation=item.explanation,
			)
			for item in fired_evaluations
		]
		return RuleEngineResult(
			assessments=assessments,
			rules_evaluated=rule_evaluations,
			rules_fired=legacy_fired,
			conflicts=request.conflicts,
			missing_evidence=list(dict.fromkeys(missing_evidence)),
			uncertainties=list(dict.fromkeys(uncertainties)),
		)
