"""Summary generation — descriptive only; never recommends granting or denying bail."""

from app.orchestration.contracts import (
    AgentResultStatus, CaseSummaryBlock, SummaryAgentInput, SummaryAgentOutput,
)


class DemoSummaryAgent:
    name = "demo-summary-agent"
    version = "0.1-simulated"

    def summarize(self, request: SummaryAgentInput) -> SummaryAgentOutput:
        ev_count = len(request.evidence)
        conflict_notes = [c.description[:200] for c in request.conflicts[:5]]
        missing = [c.missing_information for c in request.conflicts if c.missing_information]
        timeline = []
        for ev in request.evidence:
            if ev.fact_type.endswith("_DATE") and ev.fact_value.get("date"):
                timeline.append({"date": ev.fact_value["date"], "fact_type": ev.fact_type,
                                 "document_id": ev.document_id})
        timeline.sort(key=lambda x: x.get("date") or "")
        block = CaseSummaryBlock(
            case_summary=(
                f"[SIMULATED] Case {request.case.case_id} has {ev_count} evidence item(s) "
                f"across {len(request.documents)} document(s)."
            ),
            document_summary="; ".join(d.filename for d in request.documents[:10]) or "No documents",
            timeline=timeline[:20],
            key_evidence=[e.evidence_id for e in request.evidence[:10]],
            conflicts_overview=conflict_notes,
            missing_evidence=[m for m in missing if m][:10],
            review_recommendations=[
                "Human review recommended for all simulated outputs.",
                "Do not treat this summary as a bail or judicial decision.",
            ],
        )
        return SummaryAgentOutput(
            status=AgentResultStatus.SUCCESS, agent_name=self.name, agent_version=self.version,
            is_simulated=True, summary=block)
