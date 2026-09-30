"""Adapts reasoning API inputs to the deterministic symbolic Rule Engine."""

from backend.app.agents.reasoning.schemas import (
	FactRecord,
	InferenceRecord,
	ReasoningRequest,
	ReasoningResponse,
	ReasoningTraceStep,
	RuleExecution,
)
from backend.app.rules.rule_engine import RuleEngine
from backend.app.rules.rules import RULES, value_key
from backend.app.rules.schemas import (
	RuleConflict,
	RuleEngineRequest,
	RuleEvidence,
	RuleFact,
)


class ReasoningService:
	"""Runs symbolic rules and turns their structured outcomes into an explanation."""

	def __init__(self, rule_engine: RuleEngine | None = None) -> None:
		self.rule_engine = rule_engine or RuleEngine()
		self.rules_by_id = {rule.rule_id: rule for rule in RULES}

	def analyze(self, request: ReasoningRequest) -> ReasoningResponse:
		selected_engine = self._engine_for_request(request)
		engine_request = RuleEngineRequest(
			facts=[
				RuleFact(
					fact_id=fact.fact_id,
					fact_type=fact.fact_type,
					value=fact.value,
					evidence_ids=fact.evidence_ids,
				)
				for fact in request.facts
			],
			evidence=[RuleEvidence.model_validate(item.model_dump()) for item in request.evidence],
			conflicts=[RuleConflict.model_validate(item.model_dump()) for item in request.conflicts],
			evidence_gaps=request.evidence_gaps,
			critical_fact_types=request.critical_fact_types,
		)
		result = selected_engine.evaluate(engine_request)
		steps = self._reasoning_steps(request, result)
		inferences = [
			InferenceRecord(
				fact_type=assessment.fact_type,
				assessment=assessment.status,
				explanation=assessment.explanation,
				evidence_ids=assessment.evidence_ids,
				rule_ids=assessment.rule_ids,
				selected_value=assessment.selected_value,
			)
			for assessment in result.assessments
		]
		status = self._overall_status(result)
		conclusion = self._conclusion(status, result)
		rules_used = list(dict.fromkeys(item.rule_id for item in result.rules_fired))
		conflict_evidence_ids = {
			evidence_id
			for conflict in result.conflicts
			for evidence_id in conflict.evidence_ids
		}
		unresolved_types = {
			assessment.fact_type
			for assessment in result.assessments
			if assessment.status == "conflicting"
		}
		conflict_evidence_ids.update(
			item.evidence_id
			for item in request.evidence
			if item.fact_type in unresolved_types
		)
		supporting_evidence = [
			item
			for item in request.evidence
			if any(
				assessment.fact_type == item.fact_type
				and assessment.status == "strongly_supported"
				and assessment.selected_value is not None
				and value_key(item.value) == value_key(assessment.selected_value)
				for assessment in result.assessments
			)
		]
		contradicting_evidence = [
			item for item in request.evidence if item.evidence_id in conflict_evidence_ids
		]
		missing_evidence = result.missing_evidence
		uncertainties = result.uncertainties
		what_could_change = list(
			dict.fromkeys(gap.required_evidence for gap in request.evidence_gaps)
		)
		what_could_change.extend(
			f"Additional direct documentary support for {assessment.fact_type!r}."
			for assessment in result.assessments
			if assessment.status == "uncertain"
		)
		needs_human_review = status != "supported" or bool(request.evidence_gaps)

		return ReasoningResponse(
			case_id=request.case_id,
			analysis_version=request.analysis_version,
			status=status,
			reasoning_summary=conclusion,
			facts_considered=request.facts,
			supporting_evidence=supporting_evidence,
			contradicting_evidence=contradicting_evidence,
			conflicts=request.conflicts,
			rules_fired=[
				RuleExecution.model_validate(item.model_dump()) for item in result.rules_fired
			],
			inferences=inferences,
			reasoning_trace=steps,
			missing_evidence=missing_evidence,
			uncertainties=uncertainties,
			assumptions=[
				"Facts and evidence are upstream claims and have not been independently authenticated."
			],
			what_could_change_reasoning=what_could_change,
			confidence=0.0,
			reasoning_steps=steps,
			rules_used=rules_used,
			rule_evaluations=result.rules_evaluated,
			conclusion=conclusion,
			needs_human_review=needs_human_review,
		)

	def _engine_for_request(self, request: ReasoningRequest) -> RuleEngine:
		if not request.rules:
			return self.rule_engine
		unknown_ids = set(request.rules) - self.rules_by_id.keys()
		if unknown_ids:
			raise ValueError(f"unknown rule IDs: {', '.join(sorted(unknown_ids))}")
		mandatory_ids = {"R001", "R004", "R005", "R006"}
		selected_ids = set(request.rules) | mandatory_ids
		return RuleEngine([rule for rule in RULES if rule.rule_id in selected_ids])

	@staticmethod
	def _overall_status(result) -> str:
		if any(item.status == "conflicting" for item in result.assessments):
			return "conflicting"
		if not result.assessments or any(
			item.status in {"uncertain", "insufficient_evidence"}
			for item in result.assessments
		):
			return "insufficient_evidence"
		return "supported"

	@staticmethod
	def _conclusion(status: str, result) -> str:
		if status == "conflicting":
			fact_types = sorted(
				item.fact_type
				for item in result.assessments
				if item.status == "conflicting"
			)
			return (
				f"The Rule Engine found unresolved conflicting values for "
				f"{', '.join(fact_types)}. No competing value is selected."
			)
		if status == "supported":
			statements = [
				f"{item.fact_type}={item.selected_value!r} is strongly supported by the supplied inputs"
				for item in result.assessments
			]
			return "The Rule Engine assessment is limited to: " + "; ".join(statements) + "."
		details = list(dict.fromkeys(result.missing_evidence + result.uncertainties))
		if details:
			return "The Rule Engine found insufficient support: " + " ".join(details)
		return "The Rule Engine produced no supported assessment; no conclusion is established."

	@staticmethod
	def _reasoning_steps(request: ReasoningRequest, result) -> list[ReasoningTraceStep]:
		steps: list[ReasoningTraceStep] = []

		def add_step(
			step_type: str,
			description: str,
			*,
			fact_ids: list[str] | None = None,
			evidence_ids: list[str] | None = None,
			conflict_ids: list[str] | None = None,
			evidence_gap_ids: list[str] | None = None,
			rule_ids: list[str] | None = None,
			rule_id: str | None = None,
		) -> None:
			steps.append(
				ReasoningTraceStep(
					step=len(steps) + 1,
					type=step_type,
					description=description,
					fact_ids=fact_ids or [],
					evidence_ids=evidence_ids or [],
					conflict_ids=conflict_ids or [],
					evidence_gap_ids=evidence_gap_ids or [],
					rule_ids=rule_ids or [],
					rule_id=rule_id,
				)
			)

		for fact in request.facts:
			fact_ids = [fact.fact_id] if fact.fact_id is not None else []
			if fact_ids or fact.evidence_ids:
				add_step(
					"fact",
					f"An upstream fact record reports {fact.fact_type}={fact.value!r}.",
					fact_ids=fact_ids,
					evidence_ids=fact.evidence_ids,
				)
		fact_ids_by_evidence: dict[str, list[str]] = {}
		for fact in request.facts:
			if fact.fact_id is not None:
				for evidence_id in fact.evidence_ids:
					fact_ids_by_evidence.setdefault(evidence_id, []).append(fact.fact_id)
		for evidence in request.evidence:
			add_step(
				"evidence",
				f"{evidence.evidence_id} reports {evidence.fact_type}={evidence.value!r}: {evidence.source_quote}",
				fact_ids=fact_ids_by_evidence.get(evidence.evidence_id, []),
				evidence_ids=[evidence.evidence_id],
			)
		for gap in request.evidence_gaps:
			add_step(
				"evidence_gap",
				f"{gap.description} Required evidence: {gap.required_evidence}",
				evidence_gap_ids=[gap.gap_id],
			)
		for evaluation in result.rules_evaluated:
			if not evaluation.fired:
				continue
			add_step(
				"rule",
				f"{evaluation.rule_name}: {evaluation.explanation}",
				fact_ids=evaluation.input_fact_ids,
				evidence_ids=evaluation.input_evidence_ids,
				conflict_ids=evaluation.input_conflict_ids,
				evidence_gap_ids=evaluation.input_gap_ids,
				rule_ids=[evaluation.rule_id],
				rule_id=evaluation.rule_id,
			)
		for conflict in result.conflicts:
			add_step(
				"conflict",
				conflict.description,
				evidence_ids=conflict.evidence_ids,
				conflict_ids=[conflict.conflict_id],
			)
		for assessment in result.assessments:
			add_step(
				"inference",
				assessment.explanation,
				fact_ids=assessment.fact_ids,
				evidence_ids=assessment.evidence_ids,
				conflict_ids=assessment.conflict_ids,
				rule_ids=assessment.rule_ids,
			)
		for evaluation in result.rules_evaluated:
			for uncertainty in evaluation.uncertainties:
				add_step(
					"uncertainty",
					uncertainty,
					fact_ids=evaluation.input_fact_ids,
					evidence_ids=evaluation.input_evidence_ids,
					conflict_ids=evaluation.input_conflict_ids,
					evidence_gap_ids=evaluation.input_gap_ids,
					rule_ids=[evaluation.rule_id],
				)
		return steps
