"""Rule evaluation stage (neutral PASS/FAIL/WARNING/MANUAL_REVIEW style signals only)."""

from app.models.enums import ReviewSignal, RuleEvaluationStatus
from app.orchestration.contracts import (
    AgentResultStatus, ReasoningAgentInput, ReasoningAgentOutput, RuleEvaluation,
)


class DemoRuleAgent:
    name = "demo-rule-agent"
    version = "0.1-simulated"

    def evaluate(self, request: ReasoningAgentInput) -> ReasoningAgentOutput:
        missing = [c.missing_information for c in request.conflicts if c.missing_information]
        contradictions = [c for c in request.conflicts if c.conflict_type.value == "CONTRADICTION"]
        evaluations: list[RuleEvaluation] = []
        completeness = RuleEvaluation(
            rule_id="DOC-COMPLETENESS", rule_version="1.0",
            evaluation_status=RuleEvaluationStatus.EVALUATED,
            review_signal=ReviewSignal.INSUFFICIENT_INFORMATION if missing else ReviewSignal.NEEDS_HUMAN_REVIEW,
            explanation="[SIMULATED] Document completeness check (not a legal decision).",
            input_evidence_ids=[e.evidence_id for e in request.evidence],
            missing_prerequisites=[m for m in missing if m],
            limitations=["Simulated rule output only."],
        )
        evaluations.append(completeness)
        if contradictions:
            evaluations.append(RuleEvaluation(
                rule_id="EVIDENCE-CONFLICT", rule_version="1.0",
                evaluation_status=RuleEvaluationStatus.EVALUATED,
                review_signal=ReviewSignal.CONFLICTS_DETECTED,
                explanation="[SIMULATED] Conflicting evidence requires human reconciliation.",
                input_evidence_ids=[e.evidence_id for e in request.evidence],
                limitations=["Simulated rule output only."],
            ))
        return ReasoningAgentOutput(
            status=AgentResultStatus.SUCCESS, agent_name=self.name, agent_version=self.version,
            is_simulated=True, rule_set_id="DEMO-RULES", rule_set_version="1.0-simulated",
            evaluations=evaluations)
