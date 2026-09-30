"""Person 3 integration point.

Replace with the real module via ``REASONING_AGENT_CLASS=person3_pkg.agent:ReasoningAgent`` or
``registry.register("reasoning", MyAgent())``.

``DemoReasoningAgent`` is SIMULATED. It contains NO legal rule: it only maps the shape of the
stored data to a neutral process label so the pipeline can be tested.
"""

from app.models.enums import ReviewSignal, RuleEvaluationStatus
from app.orchestration.contracts import (
    AgentResultStatus, ReasoningAgentInput, ReasoningAgentOutput, RuleEvaluation,
)


class DemoReasoningAgent:
    name = "demo-reasoning-agent"
    version = "0.0-simulated"

    def evaluate(self, request: ReasoningAgentInput) -> ReasoningAgentOutput:
        missing = [c.missing_information for c in request.conflicts if c.missing_information]
        contradictions = [c for c in request.conflicts if c.conflict_type.value == "CONTRADICTION"]
        if contradictions:
            signal, explanation = ReviewSignal.CONFLICTS_DETECTED, \
                "[SIMULATED] Conflicting evidence was reported; a human should reconcile it."
        elif missing:
            signal, explanation = ReviewSignal.INSUFFICIENT_INFORMATION, \
                "[SIMULATED] Some expected information is missing."
        else:
            signal, explanation = ReviewSignal.NEEDS_HUMAN_REVIEW, \
                "[SIMULATED] No automated findings; human review is still required."
        evaluation = RuleEvaluation(
            rule_id="DEMO-PROCESS-CHECK", rule_version="0.0-simulated",
            evaluation_status=RuleEvaluationStatus.EVALUATED, review_signal=signal,
            explanation=explanation, input_evidence_ids=[e.evidence_id for e in request.evidence],
            missing_prerequisites=[m for m in missing if m],
            limitations=["Simulated demo output. Not a legal rule and not a decision."])
        return ReasoningAgentOutput(
            status=AgentResultStatus.SUCCESS, agent_name=self.name, agent_version=self.version,
            is_simulated=True, rule_set_id="DEMO", rule_set_version="0.0-simulated",
            evaluations=[evaluation])
