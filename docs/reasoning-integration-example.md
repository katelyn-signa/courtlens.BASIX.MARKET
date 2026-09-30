# Future Reasoning Integration Example

This is an interface example for future teammates. The upstream agents, orchestrator, memory, database, and frontend below are **FUTURE** and are not implemented in this workspace.

```text
Document Intelligence (FUTURE)
        |
        v
Facts + Evidence
        |
        v
Conflict / Evidence Gap Agent (FUTURE)
        |
        v
Facts + Evidence + Conflicts + Gaps
        |
        v
Future CourtLens Orchestrator
        |
        v
ReasoningService
        |
        v
Deterministic Rule Engine (R001-R006)
        |
        v
ReasoningResponse
        |
        v
ExplanationService
        |
        v
LawyerExplanation
        |
        v
Future Case Memory (FUTURE)
        |
        v
Frontend (FUTURE)
```

## Call Shape

The future orchestrator should translate its existing agent outputs into the current `ReasoningRequest` shape. This subsystem already contains a narrow internal translation from reasoning `FactRecord`/`Evidence`/`Conflict` inputs to rules-layer `RuleFact`/`RuleEvidence`/`RuleConflict` inputs; callers should not duplicate that business logic.

```python
from backend.app.agents.reasoning.explanation_service import ExplanationService
from backend.app.agents.reasoning.reasoning_service import ReasoningService
from backend.app.agents.reasoning.schemas import ReasoningRequest

request = ReasoningRequest.model_validate({
    "case_id": case_id,
    "analysis_version": analysis_version,
    "question": question,
    "facts": facts_from_document_agent,
    "evidence": evidence_from_document_agent,
    "conflicts": conflicts_from_conflict_agent,
    "evidence_gaps": gaps_from_conflict_agent,
    "rules": [],
    "critical_fact_types": critical_fact_types,
})

reasoning_result = reasoning_service.analyze(request)
lawyer_explanation = explanation_service.explain(reasoning_result)
```

The real upstream agents should supply stable IDs. Do not synthesize or renumber fact/evidence/conflict/gap IDs while adapting. The Rule Engine remains authoritative; the Conflict Agent reports conflicts but does not select a winner, and the optional LLM layer only explains the approved `LawyerExplanation`.

Persistence and retrieval are responsibilities of the future case-memory/database component. No save/load interface is defined here. The API currently accepts direct reasoning input; it is not a case lifecycle API.