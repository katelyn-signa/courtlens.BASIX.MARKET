"""Deterministic lawyer-facing presentation of an existing reasoning result."""

from typing import Any

from pydantic import Field

from backend.app.agents.reasoning.schemas import ContractModel, ReasoningResponse


class ExplanationReferences(ContractModel):
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    evidence_gap_ids: list[str] = Field(default_factory=list)


class LawyerFinding(ContractModel):
    statement: str
    references: ExplanationReferences


class SupportingEvidence(ContractModel):
    evidence_id: str
    document_id: str
    page_number: int
    fact_type: str
    value: Any


class LawyerConflict(ContractModel):
    conflict_id: str
    fact_type: str
    description: str
    evidence_ids: list[str]
    competing_values: list[Any]
    explanation: str


class LawyerEvidenceGap(ContractModel):
    gap_id: str
    description: str
    effect: str
    references: ExplanationReferences


class AppliedRule(ContractModel):
    rule_id: str
    name: str
    explanation: str
    references: ExplanationReferences


class HumanReview(ContractModel):
    required: bool
    reasons: list[str]


class LawyerExplanation(ContractModel):
    case_id: str
    analysis_version: int
    summary: str
    key_findings: list[LawyerFinding]
    supporting_evidence: list[SupportingEvidence]
    conflicts: list[LawyerConflict]
    conflict_note: str
    evidence_gaps: list[LawyerEvidenceGap]
    rules_applied: list[AppliedRule]
    reasoning: list[LawyerFinding]
    human_review: HumanReview
    limitations: list[str]


class ExplanationService:
    """Presents a ReasoningResponse without changing its decisions or references."""

    def explain(self, result: ReasoningResponse) -> LawyerExplanation:
        rules_fired = {item.rule_id: item for item in result.rules_fired}
        evaluations = {
            item.rule_id: item for item in result.rule_evaluations if item.fired
        }
        evidence_by_id = {
            item.evidence_id: item
            for item in result.supporting_evidence + result.contradicting_evidence
        }

        findings = [
            LawyerFinding(
                statement=step.description,
                references=self._references(step),
            )
            for step in result.reasoning_steps
        ]
        supporting = [
            SupportingEvidence(
                evidence_id=item.evidence_id,
                document_id=item.document_id,
                page_number=item.page_number,
                fact_type=item.fact_type,
                value=item.value,
            )
            for item in result.supporting_evidence
        ]

        conflicts = []
        for conflict in result.conflicts:
            related_evidence = [
                evidence_by_id[evidence_id]
                for evidence_id in conflict.evidence_ids
                if evidence_id in evidence_by_id
            ]
            competing_values = self._unique_values(item.value for item in related_evidence)
            conflicts.append(
                LawyerConflict(
                    conflict_id=conflict.conflict_id,
                    fact_type=conflict.fact_type,
                    description=conflict.description,
                    evidence_ids=list(conflict.evidence_ids),
                    competing_values=competing_values,
                    explanation=(
                        f"Conflict {conflict.conflict_id} remains unresolved. The available "
                        "records report competing values; the system has not selected either "
                        "value as authoritative."
                    ),
                )
            )

        gaps = self._evidence_gaps(result)
        applied_rules = []
        for fired in result.rules_fired:
            rule_id = fired.rule_id
            evaluation = evaluations.get(rule_id)
            source_explanation = (
                evaluation.explanation if evaluation is not None else fired.explanation
            )
            applied_rules.append(
                AppliedRule(
                    rule_id=rule_id,
                    name=(evaluation.rule_name if evaluation is not None else fired.rule_name),
                    explanation=source_explanation,
                    references=self._rule_references(result, rule_id),
                )
            )

        review_reasons = self._review_reasons(result)
        limitations = self._limitations(result)
        return LawyerExplanation(
            case_id=result.case_id,
            analysis_version=result.analysis_version,
            summary=self._summary(result),
            key_findings=findings,
            supporting_evidence=supporting,
            conflicts=conflicts,
            conflict_note=self._conflict_note(result),
            evidence_gaps=gaps,
            rules_applied=applied_rules,
            reasoning=findings,
            human_review=HumanReview(
                required=result.needs_human_review,
                reasons=review_reasons,
            ),
            limitations=limitations,
        )

    @staticmethod
    def _references(step) -> ExplanationReferences:
        return ExplanationReferences(
            fact_ids=list(step.fact_ids),
            evidence_ids=list(step.evidence_ids),
            conflict_ids=list(step.conflict_ids),
            rule_ids=list(step.rule_ids),
            evidence_gap_ids=list(step.evidence_gap_ids),
        )

    @staticmethod
    def _rule_references(result: ReasoningResponse, rule_id: str) -> ExplanationReferences:
        references = ExplanationReferences()
        for evaluation in result.rule_evaluations:
            if evaluation.rule_id != rule_id or not evaluation.fired:
                continue
            references.fact_ids.extend(evaluation.input_fact_ids)
            references.evidence_ids.extend(evaluation.input_evidence_ids)
            references.conflict_ids.extend(evaluation.input_conflict_ids)
            references.evidence_gap_ids.extend(evaluation.input_gap_ids)
        for step in result.reasoning_steps:
            if rule_id not in step.rule_ids:
                continue
            references.fact_ids.extend(step.fact_ids)
            references.evidence_ids.extend(step.evidence_ids)
            references.conflict_ids.extend(step.conflict_ids)
            references.evidence_gap_ids.extend(step.evidence_gap_ids)
        for field_name in (
            "fact_ids",
            "evidence_ids",
            "conflict_ids",
            "evidence_gap_ids",
        ):
            setattr(references, field_name, list(dict.fromkeys(getattr(references, field_name))))
        references.rule_ids = [rule_id]
        return references

    @staticmethod
    def _unique_values(values) -> list[Any]:
        unique: list[Any] = []
        for value in values:
            if value not in unique:
                unique.append(value)
        return unique

    @staticmethod
    def _evidence_gaps(result: ReasoningResponse) -> list[LawyerEvidenceGap]:
        gaps_by_id: dict[str, LawyerEvidenceGap] = {}
        for step in result.reasoning_steps:
            if step.type != "evidence_gap":
                continue
            for gap_id in step.evidence_gap_ids:
                gaps_by_id[gap_id] = LawyerEvidenceGap(
                    gap_id=gap_id,
                    description=step.description,
                    effect=(
                        "This supplied evidence gap is part of the reasoning record; "
                        "the stated missing-support assessment remains unchanged."
                    ),
                    references=ExplanationReferences(
                        fact_ids=list(step.fact_ids),
                        evidence_ids=list(step.evidence_ids),
                        conflict_ids=list(step.conflict_ids),
                        rule_ids=list(step.rule_ids),
                        evidence_gap_ids=[gap_id],
                    ),
                )
        return list(gaps_by_id.values())

    @staticmethod
    def _summary(result: ReasoningResponse) -> str:
        fired_rule_ids = {item.rule_id for item in result.rules_fired}
        if result.status == "conflicting":
            return "Conflicting evidence prevents the system from selecting a single supported value."
        if result.status == "supported" and "R003" in fired_rule_ids:
            return "Available evidence provides strong documentary support for the stated fact."
        if "R002" in fired_rule_ids and "R003" not in fired_rule_ids:
            return (
                "Evidence is consistent across multiple documents, but the available support "
                "does not meet the strong-support threshold."
            )
        if "R006" in fired_rule_ids:
            return "Critical supporting evidence is missing."
        if result.status == "insufficient_evidence":
            return "The available evidence does not establish a supported conclusion."
        return result.conclusion

    @staticmethod
    def _conflict_note(result: ReasoningResponse) -> str:
        if result.conflicts:
            return "Conflicts are present in the reasoning result and remain unresolved."
        if result.status == "conflicting":
            return (
                "The reasoning result reports conflicting values, but no conflict record or "
                "conflict ID was supplied; none has been added by this explanation."
            )
        return "No material conflicts are recorded in the current reasoning result."

    @staticmethod
    def _review_reasons(result: ReasoningResponse) -> list[str]:
        reasons: list[str] = []
        if result.status == "conflicting":
            reasons.append("The reasoning result contains unresolved conflict.")
        if result.status == "insufficient_evidence":
            reasons.append("The reasoning result reports insufficient evidence.")
        if result.uncertainties:
            reasons.extend(result.uncertainties)
        if result.needs_human_review and not reasons:
            reasons.append("The ReasoningService marked this result for human review.")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _limitations(result: ReasoningResponse) -> list[str]:
        limitations: list[str] = []
        fired_rule_ids = {item.rule_id for item in result.rules_fired}
        if result.status == "conflicting":
            limitations.append("The evidence contains an unresolved conflict.")
        if "R006" in fired_rule_ids:
            limitations.append("Critical supporting evidence is missing.")
        if result.status == "insufficient_evidence" and "R006" not in fired_rule_ids:
            limitations.append("The available evidence does not establish the assessed conclusion.")
        if "R002" in fired_rule_ids and "R003" not in fired_rule_ids:
            limitations.append(
                "The available evidence is consistent but does not meet the strong-support threshold."
            )
        if result.needs_human_review:
            limitations.append("The conclusion depends on evidence requiring human review.")
        return list(dict.fromkeys(limitations))