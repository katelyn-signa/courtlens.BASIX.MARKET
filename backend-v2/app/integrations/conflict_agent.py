"""Person 2 integration point.

Replace with the real module via ``CONFLICT_AGENT_CLASS=person2_pkg.agent:ConflictAgent`` or
``registry.register("conflict_detection", MyAgent())``.

``DemoConflictAgent`` is SIMULATED and deliberately trivial (test/demo only): it flags differing
values for the same date fact type, and reports a missing CHARGE_SHEET_DATE fact. It is not a
legal or evidentiary analysis.
"""

from collections import defaultdict

from app.models.enums import ConflictType, Severity
from app.orchestration.contracts import (
    AgentResultStatus, ConflictAgentInput, ConflictAgentOutput, ConflictFinding,
)


class DemoConflictAgent:
    name = "demo-conflict-agent"
    version = "0.0-simulated"

    def analyze(self, request: ConflictAgentInput) -> ConflictAgentOutput:
        findings: list[ConflictFinding] = []
        by_type = defaultdict(list)
        for ev in request.evidence:
            if ev.fact_type.endswith("_DATE") and ev.fact_value.get("date"):
                by_type[ev.fact_type].append(ev)
        for fact_type, items in sorted(by_type.items()):
            if len({e.fact_value["date"] for e in items}) > 1:
                findings.append(ConflictFinding(
                    finding_type=ConflictType.CONTRADICTION, severity=Severity.MEDIUM,
                    description=f"[SIMULATED] Differing {fact_type} values across documents.",
                    related_evidence_ids=[e.evidence_id for e in items],
                    related_document_ids=sorted({e.document_id for e in items}),
                    conflicting_values=[{"evidence_id": e.evidence_id, "date": e.fact_value["date"]}
                                        for e in items]))
        if not any(e.fact_type == "CHARGE_SHEET_DATE" for e in request.evidence):
            findings.append(ConflictFinding(
                finding_type=ConflictType.MISSING_EVIDENCE, severity=Severity.LOW,
                description="[SIMULATED] No charge-sheet date evidence available.",
                missing_information="Charge-sheet / final-report date"))
        return ConflictAgentOutput(status=AgentResultStatus.SUCCESS, agent_name=self.name,
                                   agent_version=self.version, is_simulated=True, findings=findings)
