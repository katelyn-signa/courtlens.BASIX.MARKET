from uuid import uuid4

from app.reasoning.metta_adapter import evaluate_rules
from app.reasoning.rule_engine import evaluate_human_review
from app.schemas.analysis import CaseAnalysisResult
from app.schemas.reasoning import (
    ReasoningEvidenceReference,
    ReasoningResult,
    ReasoningStep,
    RuleEvaluation,
    SemanticInterpretation,
    WhyExplanation,
)
from app.services.semantic_reasoning_service import interpret_case


def _unique_evidence(
    observations,
) -> list[ReasoningEvidenceReference]:
    unique = {}
    for observation in observations:
        for reference in observation.evidence_refs:
            unique.setdefault((reference.document_id, reference.evidence_id), reference)
    return list(unique.values())


def _confidence(
    interpretation: SemanticInterpretation,
    evaluations: list[RuleEvaluation],
) -> tuple[float, str]:
    evidence_used = _unique_evidence(interpretation.observations)
    if not evidence_used:
        return 0.0, "low"

    score = min(1.0, len(evidence_used) / 3)
    if any(item.rule_id == "R002" and item.triggered for item in evaluations):
        score -= 0.2
    if any(item.rule_id == "R003" and item.triggered for item in evaluations):
        score -= 0.2
    gap_count = sum(
        item.observation_type == "evidence_gap"
        for item in interpretation.observations
    )
    score -= 0.15 * gap_count
    score = round(max(0.0, min(1.0, score)), 2)

    if score >= 0.8:
        return score, "high"
    if score >= 0.45:
        return score, "medium"
    return score, "low"


def _recommendation(evaluations: list[RuleEvaluation]) -> str:
    triggered = {item.rule_id for item in evaluations if item.triggered}
    authority = next(
        (item for item in evaluations if item.rule_id == "R006" and item.triggered),
        None,
    )
    if authority is not None and authority.result.get("recommendation_date"):
        return (
            "Based on the configured source hierarchy, CourtLens recommends "
            f"{authority.result['recommendation_date']}. Human confirmation is required."
        )
    if authority is not None:
        return "Conflicting hearing dates require human confirmation; no source was ranked above the others."
    if "R002" in triggered:
        return "Payment evidence conflict requires human verification."
    if "R003" in triggered:
        return "Evidence conflict requires human verification."
    if "R001" in triggered:
        return "Potential payment shortfall identified."
    if "R004" in triggered:
        return "Supporting evidence gaps require verification."
    return "No configured payment shortfall or material conflict was identified in the supplied structured evidence."


def _trace(
    interpretation: SemanticInterpretation,
    evaluations: list[RuleEvaluation],
    recommendation: str,
    human_review_required: bool,
    analyzed_document_ids: list[str],
) -> tuple[list[ReasoningStep], list[str]]:
    steps: list[ReasoningStep] = []
    unresolved_questions: list[str] = []
    seen_references = set()

    if analyzed_document_ids:
        steps.append(
            ReasoningStep(
                step_id=f"S{len(steps) + 1:03d}",
                step_type="documents_analyzed",
                description=f"Documents analyzed: {', '.join(analyzed_document_ids)}.",
            )
        )
    hearing_date_observations = [
        item
        for item in interpretation.observations
        if item.observation_type == "date_event" and item.event_type == "hearing_date"
    ]
    if hearing_date_observations:
        hearing_dates = ", ".join(
            str(item.normalized_value) for item in hearing_date_observations
        )
        steps.append(
            ReasoningStep(
                step_id=f"S{len(steps) + 1:03d}",
                step_type="facts_extracted",
                description=f"Hearing date facts extracted: {hearing_dates}.",
                evidence_ids=[
                    reference.evidence_id
                    for item in hearing_date_observations
                    for reference in item.evidence_refs
                ],
            )
        )

    for observation in interpretation.observations:
        if observation.observation_type == "conflict":
            steps.append(
                ReasoningStep(
                    step_id=f"S{len(steps) + 1:03d}",
                    step_type="conflict_identified",
                    description=f"Conflicting values detected: {observation.statement}",
                    evidence_ids=[ref.evidence_id for ref in observation.evidence_refs],
                )
            )
            continue
        if observation.observation_type == "evidence_gap":
            steps.append(
                ReasoningStep(
                    step_id=f"S{len(steps) + 1:03d}",
                    step_type="gap_identified",
                    description=observation.statement,
                    evidence_ids=[ref.evidence_id for ref in observation.evidence_refs],
                )
            )
            unresolved_questions.append(observation.statement)
            continue
        for reference in observation.evidence_refs:
            key = (reference.document_id, reference.evidence_id)
            if key in seen_references:
                continue
            seen_references.add(key)
            steps.append(
                ReasoningStep(
                    step_id=f"S{len(steps) + 1:03d}",
                    step_type="evidence_observed",
                    description=observation.statement,
                    evidence_ids=[reference.evidence_id],
                )
            )

    for evaluation in evaluations:
        steps.append(
            ReasoningStep(
                step_id=f"S{len(steps) + 1:03d}",
                step_type="rule_evaluated",
                description=evaluation.explanation,
                evidence_ids=evaluation.evidence_ids,
                rule_ids=[evaluation.rule_id],
            )
        )
        if evaluation.triggered:
            if evaluation.rule_id == "R006":
                steps.append(
                    ReasoningStep(
                        step_id=f"S{len(steps) + 1:03d}",
                        step_type="source_authority_evaluated",
                        description=(
                            "Source authority evaluated using configured hierarchy: "
                            f"{evaluation.result.get('source_hierarchy', 'not configured')}."
                        ),
                        evidence_ids=evaluation.evidence_ids,
                        rule_ids=[evaluation.rule_id],
                    )
                )
                if evaluation.result.get("evidence_source"):
                    steps.append(
                        ReasoningStep(
                            step_id=f"S{len(steps) + 1:03d}",
                            step_type="source_ranked",
                            description=(
                                f"{evaluation.result['evidence_source']} ranked higher "
                                "under configured source authority."
                            ),
                            evidence_ids=evaluation.evidence_ids,
                            rule_ids=[evaluation.rule_id],
                        )
                    )
            steps.append(
                ReasoningStep(
                    step_id=f"S{len(steps) + 1:03d}",
                    step_type="rule_triggered",
                    description=evaluation.explanation,
                    evidence_ids=evaluation.evidence_ids,
                    rule_ids=[evaluation.rule_id],
                )
            )
        if evaluation.rule_id in {"R002", "R003"} and evaluation.triggered:
            unresolved_questions.append(evaluation.explanation)

    steps.append(
        ReasoningStep(
            step_id=f"S{len(steps) + 1:03d}",
            step_type="recommendation_generated",
            description=f"Recommendation generated: {recommendation}",
            rule_ids=[item.rule_id for item in evaluations if item.triggered],
            evidence_ids=[
                evidence_id
                for item in evaluations if item.triggered
                for evidence_id in item.evidence_ids
            ],
        )
    )
    if human_review_required:
        steps.append(
            ReasoningStep(
                step_id=f"S{len(steps) + 1:03d}",
                step_type="human_review_required",
                description="Human confirmation required; human review remains required for unresolved or contradictory evidence.",
                rule_ids=["R005"],
                evidence_ids=next(
                    (item.evidence_ids for item in evaluations if item.rule_id == "R005"),
                    [],
                ),
            )
        )
    return steps, list(dict.fromkeys(unresolved_questions))


def _why_explanation(evaluations: list[RuleEvaluation]) -> WhyExplanation | None:
    authority = next(
        (
            item
            for item in evaluations
            if item.rule_id == "R006"
            and item.triggered
            and item.result.get("recommendation_date")
        ),
        None,
    )
    if authority is None:
        return None
    return WhyExplanation(
        recommendation=authority.result["recommendation_date"],
        evidence=authority.result["evidence_source"],
        rule=authority.result["rule"],
        reason=authority.result["reason"],
    )


def reason_case(
    case_analysis: CaseAnalysisResult,
    *,
    refresh_rule_ids: set[str] | None = None,
    previous_result: ReasoningResult | None = None,
) -> ReasoningResult:
    interpretation = interpret_case(case_analysis)
    refreshed_evaluations = evaluate_rules(interpretation, refresh_rule_ids)
    if previous_result is None or refresh_rule_ids is None:
        evaluations = refreshed_evaluations
    else:
        evaluations_by_id = {
            item.rule_id: item for item in previous_result.rules_evaluated
        }
        evaluations_by_id.update(
            {item.rule_id: item for item in refreshed_evaluations}
        )
        evaluations = [evaluations_by_id[key] for key in sorted(evaluations_by_id)]
        evaluations = [
            item for item in evaluations if item.rule_id != "R005"
        ] + [evaluate_human_review(interpretation, evaluations)]
    human_review_required = any(
        item.rule_id == "R005" and item.triggered for item in evaluations
    )
    recommendation = _recommendation(evaluations)
    evidence_support_score, confidence = _confidence(interpretation, evaluations)
    steps, unresolved_questions = _trace(
        interpretation,
        evaluations,
        recommendation,
        human_review_required,
        [
            item.document_id
            for item in case_analysis.documents
            if item.status == "processed"
        ],
    )
    return ReasoningResult(
        reasoning_id=str(uuid4()),
        recommendation=recommendation,
        confidence=confidence,
        evidence_support_score=evidence_support_score,
        semantic_observations=interpretation.observations,
        evidence_used=_unique_evidence(interpretation.observations),
        rules_evaluated=evaluations,
        reasoning_steps=steps,
        unresolved_questions=unresolved_questions,
        human_review_required=human_review_required,
        why_explanation=_why_explanation(evaluations),
    )