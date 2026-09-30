# Reasoning Subsystem Quickstart

## Available Setup

This workspace has no `requirements.txt`, `pyproject.toml`, or lock file. Do not treat `.env.example` as a dependency manifest or as automatically loaded configuration. The existing local `.venv` currently contains FastAPI, Pydantic, Uvicorn, HTTPX, and pytest; this workspace-specific environment is not a reproducible install specification.

From the workspace root, run tests with the existing Windows venv:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The shell command `pytest -q` also works when pytest's Scripts directory is on `PATH`. In the current workspace shell it was not on `PATH`, so use the venv command above.

## Start API

`backend/app/main.py` exposes `app` and mounts the existing reasoning router:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

The server listens at `http://127.0.0.1:8000` by default. Interactive API docs are at `http://127.0.0.1:8000/docs`.

## Endpoints

- `GET /api/reasoning/health`
- `POST /api/reasoning/analyze`

There are no case creation, document upload, case-analysis orchestration, persistence, or case-result retrieval endpoints in this subsystem.

## Example Request

```json
{
  "case_id": "case-demo-1",
  "analysis_version": 1,
  "question": "What hearing date is supported?",
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

The request must provide evidence metadata; document extraction is not performed here. Rule IDs are optional. If supplied, they must be registered; conflict, weak-evidence, explicit-gap, and missing-critical-support safeguards remain active.

## Response and Review

The endpoint returns `ReasoningResponse` JSON: case/version, status, summary/conclusion, facts considered, supporting and contradicting evidence, conflicts, fired rules and all rule evaluations, inferences, trace steps, missing evidence, uncertainties, assumptions, changes that could affect reasoning, confidence indicator, and `needs_human_review`. An unresolved conflict is not assigned a winning value. Weak or insufficient evidence can produce `needs_human_review: true`. The confidence field is not a calibrated probability or legal certainty.

`ExplanationService` can turn a `ReasoningResponse` into a deterministic `LawyerExplanation`. The optional LLM explanation wrapper consumes that structured explanation only and never replaces it. The current API endpoint returns the reasoning response; it does not call the explanation layer or return an LLM narrative. No API key is needed for tests, reasoning, or deterministic explanations.

## Integration Rules

The future Document Intelligence Agent supplies facts/evidence. The future Conflict / Evidence Gap Agent supplies conflicts/gaps. A future orchestrator should call `ReasoningService.analyze(ReasoningRequest)` and then `ExplanationService.explain(ReasoningResponse)`. These upstream agents, orchestrator, database/case memory, and frontend are future components, not part of this workspace. Preserve IDs and do not let upstream agents, an LLM, or a UI change deterministic rule outcomes.