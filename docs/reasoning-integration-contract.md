# CourtLens Reasoning Integration Contract

## Purpose and Boundary

This package accepts structured facts, evidence, conflicts, evidence gaps, and optional registered rule IDs. `ReasoningService` adapts those inputs to the deterministic Rule Engine, then returns an auditable reasoning result. `ExplanationService` renders a deterministic `LawyerExplanation`. An optional LLM explanation wrapper can produce a subordinate narrative; it is disabled by default.

This subsystem does not extract documents, create facts, analyze conflicts, manage cases, persist analyses, or own a frontend. Document Intelligence will eventually provide facts and evidence. A separate Conflict / Evidence Gap Agent will eventually provide conflicts and gaps. A future CourtLens Orchestrator will call this subsystem. Those components are not present here.

## Input Contract

The API and service input is `ReasoningRequest`, defined in `backend/app/agents/reasoning/schemas.py`:

| Field | Shape | Notes |
|---|---|---|
| `case_id` | non-empty string | Caller-provided case identifier; no Case model exists here. |
| `analysis_version` | integer, default `1`, minimum `1` | Passed through to results; no version history is stored. |
| `facts` | list of `FactRecord` | Each has optional `fact_id`, `fact_type`, JSON-compatible `value`, `evidence_ids`, and fixed `epistemic_status="evidence_reported"`. |
| `evidence` | list of `Evidence` | `evidence_id`, `document_id`, `page_number`, `fact_type`, `value`, `source_quote`, confidence in `[0,1]`, and evidence type. |
| `conflicts` | list of `Conflict` | `conflict_id`, `fact_type`, evidence IDs, description, severity. |
| `evidence_gaps` | list of rules-layer `EvidenceGap` | `gap_id`, `fact_type`, description, required evidence. |
| `rules` | list of strings, default empty | Optional registered rule IDs. Unknown IDs raise `ValueError`. Conflict, weak-evidence, gap, and missing-support safeguards remain mandatory when a subset is requested. |
| `question` | non-empty string | Caller context; rule evaluation is keyed by the supplied fact types, not free-text interpretation. |
| `critical_fact_types` | list of strings | Names facts for which missing support must be reported. |

Facts and evidence IDs must be unique where validated. Fact/evidence and conflict/evidence references must resolve to evidence of the same `fact_type`. Evidence gaps are not required to refer to evidence. Pydantic input validation failures at the FastAPI boundary return HTTP 422. Unknown rule IDs are currently raised as `ValueError` by `ReasoningService`; the API route does not map this exception to a custom HTTP response.

The rules layer uses separate `RuleFact`, `RuleEvidence`, and `RuleConflict` Pydantic models in `backend/app/rules/schemas.py`. `ReasoningService` performs the existing boundary conversion with the supplied IDs intact. Do not bypass that conversion or synthesize IDs.

## Deterministic Rules

The explicit rules are in `backend/app/rules/rules.py`; evaluation is in `backend/app/rules/rule_engine.py`:

| ID | Rule | Effect |
|---|---|---|
| `R001` | Conflicting reported values | Retains competing values and reports uncertainty; does not select a winner. |
| `R002` | Consistent independent support | Detects the same value across distinct document IDs. Consistency alone does not establish strong support. |
| `R003` | Strong direct documentary support | Requires uncontradicted direct documentary evidence with confidence at least `0.85`. |
| `R004` | Low-confidence or indirect evidence | Marks supplied inputs uncertain when none meets the direct-documentary threshold. |
| `R005` | Explicit evidence gap | Reports the supplied required-evidence text for a fact type. |
| `R006` | Missing critical support | Reports insufficient evidence for a named critical fact with no supporting evidence. |

For each relevant fact type the engine returns all evaluated rules, including non-firing rules, with rule ID/name, description, conditions, condition outcome, fired state, fact/evidence/conflict/gap IDs, result, explanation, missing evidence, and uncertainties. `rules_fired` is the compatibility list of fired executions. The overall `RuleEngineResult` also contains assessments, conflicts, missing evidence, and uncertainties.

## Reasoning Result

The API output type is `ReasoningResponse` in `backend/app/agents/reasoning/schemas.py` (there is no class named `ReasoningResult`). It includes:

- `case_id`, `analysis_version`, `status` (`supported`, `conflicting`, or `insufficient_evidence`), `reasoning_summary`, and `conclusion`.
- `facts_considered`, `supporting_evidence`, `contradicting_evidence`, `conflicts`, and `inferences`.
- `rules_fired`, `rules_used`, and detailed `rule_evaluations`.
- `reasoning_trace` and its compatibility alias `reasoning_steps`. Each trace step has a sequence number, type, statement, and ID lists for facts, evidence, conflicts, gaps, and rules.
- `missing_evidence`, `uncertainties`, `assumptions`, `what_could_change_reasoning`, `needs_human_review`, and a coarse `confidence` indicator.

`needs_human_review` is set by `ReasoningService`, not by the explanation layer. Unresolved conflicts are not assigned a selected value. Confidence is not a calibrated probability or legal certainty.

## Lawyer Explanation

`ExplanationService.explain(ReasoningResponse)` returns `LawyerExplanation` in `backend/app/agents/reasoning/explanation_service.py`. Its fields are:

- `case_id`, `analysis_version`, and deterministic `summary`.
- `key_findings` and `reasoning`, each containing a statement and structured references (`fact_ids`, `evidence_ids`, `conflict_ids`, `rule_ids`, `evidence_gap_ids`).
- `supporting_evidence` with only existing evidence IDs and metadata: document ID, page, fact type, and value.
- `conflicts` with original conflict/evidence IDs and competing values available from the reasoning result, plus `conflict_note`.
- `evidence_gaps` with IDs and descriptions present in the reasoning trace.
- `rules_applied`, limited to fired rules, with source IDs and explanations.
- `human_review` (required boolean and reasons) and `limitations`.

The deterministic explanation does not invent a conflict ID when the reasoning result has conflict status without a supplied conflict record.

## Optional LLM Explanation

`LLMExplanationService` and `LLMExplainer` are in `backend/app/agents/reasoning/llm_explainer.py`. When enabled, the provider receives only `LawyerExplanation.model_dump(mode="json")`, not the request or hidden application state. The wrapper returns the original deterministic `LawyerExplanation` separately from an optional structured `LawyerNarrative`. Generated IDs are checked against IDs in the source explanation. The conflict statement and human-review note/boolean are locked to deterministic source data. Failure or invalid output leaves the deterministic explanation available and does not create a fallback narrative.

The OpenAI-compatible standard-library HTTP adapter is disabled by default. Environment variables are shown in `.env.example`; the application does not automatically load `.env` files. No live key is needed for the subsystem or tests. The LLM is not the rule evaluator and is not called by the current reasoning API endpoint.

## Validation and Errors

- Pydantic models reject extra fields and validate IDs, field constraints, evidence types, confidence bounds, and references.
- FastAPI request validation returns HTTP 422.
- `ReasoningService` rejects unknown rule IDs with `ValueError`; no custom API error mapping is currently installed.
- LLM status is `disabled`, `generated`, `unavailable`, or `invalid_output`. Provider errors are intentionally returned without leaking provider exception details.
- There is no case persistence or version-history storage. `analysis_version` is an input/output field only.

## API

The mounted reasoning router in `backend/app/api/reasoning.py` provides:

- `POST /api/reasoning/analyze` — JSON `ReasoningRequest` to `ReasoningResponse`.
- `GET /api/reasoning/health` — `{ "status": "ok", "service": "court-lens-reasoning" }`.

The ASGI application is `backend.app.main:app`. No case lifecycle, upload, or result-persistence endpoint is provided.

Example input:

```json
{
  "case_id": "case-demo-1",
  "analysis_version": 1,
  "question": "What hearing date is supported by the supplied record?",
  "facts": [
    {
      "fact_id": "F-102",
      "fact_type": "hearing_date",
      "value": "2026-10-15",
      "evidence_ids": ["E-27"]
    }
  ],
  "evidence": [
    {
      "evidence_id": "E-27",
      "document_id": "doc-001",
      "page_number": 2,
      "fact_type": "hearing_date",
      "value": "2026-10-15",
      "source_quote": "The matter is listed for hearing on 15 October 2026.",
      "confidence": 0.95,
      "evidence_type": "direct_documentary"
    }
  ],
  "conflicts": [],
  "evidence_gaps": [],
  "rules": [],
  "critical_fact_types": ["hearing_date"]
}
```

The response is a `ReasoningResponse`; representative fields include `status: "supported"`, `rules_used: ["R003"]`, `conclusion`, `reasoning_steps` with references such as `F-102`, `E-27`, and `R003`, and `needs_human_review: false`. Actual rules and output depend only on supplied facts/evidence/conflicts/gaps and registered deterministic rules.

## Future Orchestrator Call

The future orchestrator can construct the existing `ReasoningRequest` from its upstream agents and call:

```python
from backend.app.agents.reasoning.reasoning_service import ReasoningService
from backend.app.agents.reasoning.schemas import ReasoningRequest

request = ReasoningRequest.model_validate(orchestrator_payload)
reasoning_response = ReasoningService().analyze(request)
lawyer_explanation = ExplanationService().explain(reasoning_response)
```

`orchestrator_payload` must use the request fields documented above. The future Document Intelligence component owns document processing and production of facts/evidence; the future Conflict / Evidence Gap Agent owns production of conflict/gap records; the future Orchestrator owns case coordination and persistence. Those components must not alter the Rule Engine result.

## CURRENT ARCHITECTURE

Caller
 ↓
Reasoning API / ReasoningService
 ↓
Rule Engine
 ↓
ReasoningResponse
 ↓
ExplanationService
 ↓
Optional LLM explanation

## FUTURE COURTLENS ARCHITECTURE

Document Intelligence (FUTURE)
 ↓
Facts + Evidence
 ↓
Conflict / Evidence Gap Agent (FUTURE)
 ↓
Conflicts + Gaps
 ↓
CourtLens Orchestrator (FUTURE)
 ↓
YOUR REASONING SUBSYSTEM
 ↓
ReasoningResponse
 ↓
LawyerExplanation
 ↓
Case Memory (FUTURE)
 ↓
Frontend (FUTURE)