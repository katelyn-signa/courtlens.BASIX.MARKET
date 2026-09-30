# Synthetic Reasoning Demo Scenarios

These examples exercise only the existing reasoning endpoint with synthetic structured inputs. They are **not** outputs of a Document Intelligence Agent, Conflict / Evidence Gap Agent, Orchestrator, or database; none of those components is present in this workspace. The evidence records below are supplied directly to the reasoning subsystem. No real legal authority or case information is used.

Run the API as documented in `reasoning-quickstart.md`, then submit each JSON body to `POST /api/reasoning/analyze`.

## Scenario A — Consistent Strong Documentary Support

Synthetic evidence from two document IDs reports the same hearing date. The two evidence records meet the configured direct-documentary confidence threshold.

```json
{
  "case_id": "synthetic-strong-demo",
  "analysis_version": 1,
  "question": "What hearing date is supported?",
  "facts": [
    {
      "fact_id": "F-DEMO-1",
      "fact_type": "hearing_date",
      "value": "2026-10-15",
      "evidence_ids": ["E-DEMO-1", "E-DEMO-2"]
    }
  ],
  "evidence": [
    {
      "evidence_id": "E-DEMO-1",
      "document_id": "DOC-DEMO-A",
      "page_number": 2,
      "fact_type": "hearing_date",
      "value": "2026-10-15",
      "source_quote": "The matter is listed for hearing on 15 October 2026.",
      "confidence": 0.96,
      "evidence_type": "direct_documentary"
    },
    {
      "evidence_id": "E-DEMO-2",
      "document_id": "DOC-DEMO-B",
      "page_number": 1,
      "fact_type": "hearing_date",
      "value": "2026-10-15",
      "source_quote": "The next hearing is scheduled for 15 October 2026.",
      "confidence": 0.93,
      "evidence_type": "direct_documentary"
    }
  ],
  "conflicts": [],
  "evidence_gaps": [],
  "rules": [],
  "critical_fact_types": ["hearing_date"]
}
```

Observed reasoning result:

- Fact: `F-DEMO-1` reports `hearing_date=2026-10-15`.
- Supporting evidence: `E-DEMO-1` and `E-DEMO-2`.
- Rules used: `R002` (consistent independent support), `R003` (strong direct documentary support).
- Inference: `strongly_supported`; selected value `2026-10-15`.
- Status: `supported`; `needs_human_review=false`.
- The deterministic `LawyerExplanation` summarizes strong documentary support and includes the source IDs.

## Scenario B — Conflicting Documentary Values

Two synthetic documents report different dates. The conflict record is supplied as input; the reasoning subsystem does not generate the upstream conflict agent's output.

```json
{
  "case_id": "synthetic-conflict-demo",
  "analysis_version": 1,
  "question": "What hearing date is supported?",
  "facts": [],
  "evidence": [
    {
      "evidence_id": "E-DEMO-3",
      "document_id": "DOC-DEMO-C",
      "page_number": 2,
      "fact_type": "hearing_date",
      "value": "2026-10-15",
      "source_quote": "The matter is listed for hearing on 15 October 2026.",
      "confidence": 0.96,
      "evidence_type": "direct_documentary"
    },
    {
      "evidence_id": "E-DEMO-4",
      "document_id": "DOC-DEMO-D",
      "page_number": 1,
      "fact_type": "hearing_date",
      "value": "2026-10-20",
      "source_quote": "The next hearing is scheduled for 20 October 2026.",
      "confidence": 0.96,
      "evidence_type": "direct_documentary"
    }
  ],
  "conflicts": [
    {
      "conflict_id": "C-DEMO-1",
      "fact_type": "hearing_date",
      "evidence_ids": ["E-DEMO-3", "E-DEMO-4"],
      "description": "Synthetic documents report different hearing dates.",
      "severity": "high"
    }
  ],
  "evidence_gaps": [],
  "rules": [],
  "critical_fact_types": ["hearing_date"]
}
```

Observed reasoning result:

- Evidence: `E-DEMO-3` reports `2026-10-15`; `E-DEMO-4` reports `2026-10-20`.
- Conflict: `C-DEMO-1` references both evidence IDs.
- Rule used: `R001` (conflicting reported values).
- Inference: `conflicting`; `selected_value=null`.
- Status: `conflicting`; `needs_human_review=true`.
- The deterministic conclusion says the conflict is unresolved and no competing value is selected. The `LawyerExplanation` conflict section preserves `C-DEMO-1` and both evidence IDs.

Neither scenario performs document upload, extraction, conflict detection, orchestration, persistence, or result retrieval. Those full lifecycle demos remain blocked until the actual teammate components and their contracts are added to this workspace.