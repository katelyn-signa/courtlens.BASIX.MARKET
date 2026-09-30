# CourtLens Backend — Person 4 (shared backend, case memory, orchestration, audit)

CourtLens is a **legal decision-support** tool. This backend stores case facts, agent outputs,
human-review records and an audit trail. **It never decides, grants or refuses bail.** Rule
results are neutral *review signals* (`POTENTIAL_REVIEW_SIGNAL`, `NEEDS_HUMAN_REVIEW`,
`INSUFFICIENT_INFORMATION`, `CONFLICTS_DETECTED`, `ANALYSIS_INCOMPLETE`) with sources,
limitations and missing information.

## 1. Scope

| Owner | Responsibility |
|---|---|
| **Person 4 (this repo)** | FastAPI app, SQLAlchemy models, Alembic, case memory, orchestration, contracts, registry, reviews, audit, tests, docs |
| Person 1 | Document/OCR extraction → implements `DocumentIntelligenceAgent` |
| Person 2 | Conflict / evidence-gap detection → implements `ConflictDetectionAgent` |
| Person 3 | Explainable reasoning + legal rule engine → implements `ReasoningAgent` |
| Nobody here | Frontend, final legal/judicial decisions |

The `Demo*Agent` classes in `app/integrations/` are **simulated** test adapters (flagged
`is_simulated=true`); they contain no OCR and no legal rule.

## 2. Architecture

```
HTTP -> app/api (routers, Pydantic schemas, permission deps)
          -> app/services (transactions, business rules, audit)
               -> app/repositories (queries, pagination)  -> SQLAlchemy models -> SQLite/PostgreSQL
               -> app/orchestration (Orchestrator, pipeline, registry, contracts, handlers)
                        -> app/integrations (agent adapters: Person 1/2/3 or demo)
          every state change -> AuditService -> audit_events (append-only)
```

* `AnalysisService` creates a persisted run, then the `Orchestrator` executes it stage by stage
  (`document_intelligence → conflict_detection → reasoning`). Each stage commits its outputs,
  status, attempts and errors, so history survives the response.
* Execution is synchronous inside the request but split into *create run* / *execute run* so it
  can move to a background worker later without API changes.
* Schema creation is done **only by Alembic** (auto-applied at startup when `AUTO_MIGRATE=true`).

## 3. Folder structure

```
courtlens-backend/
├── app/
│   ├── main.py  config.py
│   ├── api/            router.py health.py cases.py documents.py findings.py analysis.py reviews.py audit.py deps.py
│   ├── core/           exceptions.py logging.py security.py state.py
│   ├── db/             base.py session.py types.py migrate.py init_db.py
│   ├── models/         enums.py case.py document.py evidence.py conflict.py analysis_run.py rule_result.py review.py audit_event.py
│   ├── schemas/        common.py case.py document.py evidence.py conflict.py analysis.py review.py audit.py
│   ├── repositories/   base.py cases.py documents.py analysis.py reviews.py audit.py
│   ├── services/       case_service.py document_service.py analysis_service.py review_service.py audit_service.py storage.py
│   ├── orchestration/  orchestrator.py contracts.py registry.py pipeline.py handlers.py
│   ├── integrations/   document_agent.py conflict_agent.py reasoning_agent.py   (demo adapters)
│   └── utils/          identifiers.py time.py
├── alembic/            env.py script.py.mako versions/0001_initial_schema.py
├── tests/              conftest.py agents.py test_health.py test_cases.py test_database.py test_analysis.py test_orchestrator.py test_reviews.py test_audit.py
├── .env.example  .gitignore  alembic.ini  pytest.ini  requirements.txt  README.md
```

## 4. Windows setup (PowerShell)

1. Install Python 3.12 (3.11+ works) from https://www.python.org/downloads/ and tick **Add python.exe to PATH**. Check: `python --version`.
2. Open PowerShell in the project folder (File Explorer → folder → *Open in Terminal*), or:

```powershell
cd path\to\courtlens-backend

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

Copy-Item .env.example .env
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

* Swagger UI: http://127.0.0.1:8000/docs
* Health: http://127.0.0.1:8000/api/health
* Tests: `python -m pytest`
* The SQLite file `courtlens.db` is created in the project folder by `alembic upgrade head`
  (also done automatically on server start). Change `DATABASE_URL` in `.env` to use another database.

**If activation is blocked** (`running scripts is disabled on this system`), allow scripts for
*this PowerShell window only* (no machine-wide change):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

**Troubleshooting**

| Symptom | Fix |
|---|---|
| `python` not recognised | Reinstall Python with *Add to PATH*, or use `py -3.12 -m venv .venv` |
| `alembic` not recognised | Activate the venv first; or `python -m alembic upgrade head` |
| `ModuleNotFoundError: app` | Run commands from the `courtlens-backend` folder |
| Port 8000 busy | `--port 8001` |
| `unable to open database file` | Run from the project folder / check `DATABASE_URL` path |
| Demo results look fake | They are: `ENABLE_DEMO_AGENTS=true` gives *simulated* agents. Set `false` + `*_AGENT_CLASS` for real modules |
| Want a clean database | Stop the server, delete `courtlens.db`, run `alembic upgrade head` |

## 5. Migrations

```powershell
alembic upgrade head                                   # apply
alembic current                                        # show version
alembic revision --autogenerate -m "describe change"   # after editing app/models/*
alembic upgrade head
alembic downgrade -1                                   # roll back one step
alembic check                                          # models == migrations?
```
Review every autogenerated file before applying (SQLite uses batch mode; enum columns are
`VARCHAR` + named `CHECK`, portable to PostgreSQL). Run `python -m app.db.init_db` for a scripted upgrade.

## 6. Key policies

**Run status.** All stages `SUCCEEDED` → `COMPLETED`; at least one stage produced output but not
all succeeded → `PARTIALLY_COMPLETED`; nothing produced → `FAILED`. Stage statuses:
`PENDING, RUNNING, SUCCEEDED, PARTIAL, FAILED, SKIPPED, NOT_CONFIGURED, NOT_IMPLEMENTED`.
A stage whose dependency did not produce output is `SKIPPED`. Missing agent → `NOT_CONFIGURED`;
agent raising `NotImplementedError` → `NOT_IMPLEMENTED`. Nothing is ever fabricated.

**Run states:** `PENDING→RUNNING→{COMPLETED|PARTIALLY_COMPLETED|FAILED}`, `CANCELLED` from
`PENDING/RUNNING`; terminal states never change.

**Idempotency.** (1) `Idempotency-Key` header / `idempotency_key` returns the existing run.
(2) An identical *COMPLETED* run (same document checksums, modules, options, pipeline version) is
returned with `200` and `reused_existing=true` unless `force=true`. (3) A second run while one is
`PENDING/RUNNING` → `409 ANALYSIS_ALREADY_RUNNING`. (4) Re-registering a document with the same
filename and checksum returns the existing record.

**Retry.** `POST /analysis-runs/{id}/retry` on a `FAILED`/`PARTIALLY_COMPLETED` run creates a *new*
run (`parent_run_id`, `attempt_number+1`, trigger `RETRY`). Stages that already succeeded are
**carried over** (not recomputed); the rest re-run. Only the newest attempt can be retried, at most
`MAX_RUN_RETRIES` times. Inside a stage, only retryable errors (timeout/unavailable) are retried,
up to `AGENT_MAX_ATTEMPTS`.

**Reprocessing after new evidence.** A new document (or changed checksum → version N+1) is stored,
audited, sets `case.analysis_needs_refresh=true` and flags earlier finished runs `is_stale=true`.
Nothing is overwritten or deleted. The next run (manual, or automatic with
`AUTO_REANALYZE_ON_NEW_DOCUMENT=true`) analyses the latest version of every filename; documents
already `PROCESSED` are not re-sent to Person 1 (no duplicate evidence) unless
`reprocess_documents=true`. Each run records the exact document versions/checksums it used.

**Evidence/conflict scope.** Conflicts and rule results are stored per run (`analysis_run_id`), so
earlier runs stay retrievable (`?analysis_run_id=`). Person 2/3 receive the *current* evidence of the
run's document set (newest extraction per document).

**Audit.** Append-only: no update/delete API, ORM guards reject modification, FKs are `RESTRICT`.
Metadata is sanitised (no `text/quote/content/notes/secrets`, long strings truncated). Logs carry
IDs, counts and error *types* only.

**Security boundary.** Optional `API_KEY` header check + unverified `X-Actor-Id` audit label. This is
**not production authentication** — see `app/core/security.py` (`authenticate`, `authorize`).
There is intentionally no file-download endpoint. Uploads: extension + MIME allow-list, magic-byte
check, size cap, generated storage names, traversal-safe resolution, private `STORAGE_DIR`.
Use synthetic data only.

## 7. API reference (`/api/v1`, JSON)

Errors always look like `{"error": {"code": "...", "message": "...", "details": ..., "request_id": "..."}}`.
Common: `401 AUTHENTICATION_REQUIRED` (if `API_KEY` set), `404 *_NOT_FOUND`, `422 VALIDATION_ERROR`
(malformed IDs/bodies), `409 DATABASE_INTEGRITY_ERROR`, `500 INTERNAL_ERROR`. IDs: `case_…`, `doc_…`,
`run_…`, `rev_…`, `evd_…`, `cfl_…`, `rul_…`. List endpoints take `limit` (1–200, default 50) and
`offset`, and return `{items,total,limit,offset}`.

| Method | URL | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/v1/health` | Liveness + DB check (`503` if DB down) |
| GET | `/api/v1/system/status` | Configured/unavailable agents, pipeline, limits (no secrets) |
| POST | `/api/v1/cases` | Create case → `201` |
| GET | `/api/v1/cases` | List (`status`, `court_name`, `fir_number`, `search`) |
| GET | `/api/v1/cases/{case_id}` | Get case |
| PATCH | `/api/v1/cases/{case_id}` | Update permitted metadata; `409 INVALID_STATE_TRANSITION` for bad status change |
| GET | `/api/v1/cases/{case_id}/history` | Case + documents + runs + reviews + latest audit events (`limit` per section) |
| POST | `/api/v1/cases/{case_id}/documents` | Register metadata (`201` new / `200` existing); `415`, `413`, `422` |
| POST | `/api/v1/cases/{case_id}/documents/upload` | Multipart file upload (`file`, optional `document_type`) |
| GET | `/api/v1/cases/{case_id}/documents` | List (`processing_status`, `document_type`) |
| GET | `/api/v1/documents/{document_id}` | Document metadata |
| GET | `/api/v1/documents/{document_id}/status` | Processing status + evidence count |
| GET | `/api/v1/cases/{case_id}/evidence` | Evidence + provenance (`document_id`, `fact_type`, `extraction_run_id`) |
| GET | `/api/v1/cases/{case_id}/conflicts` | Findings (`analysis_run_id`, `conflict_type`, `resolution_status`) |
| GET | `/api/v1/cases/{case_id}/rule-results` | Rule/reasoning records (`analysis_run_id`, `rule_id`, `review_signal`) |
| POST | `/api/v1/cases/{case_id}/analysis-runs` | Request + execute run (`201` new / `200` reused); `409 ANALYSIS_ALREADY_RUNNING`, `422 NO_DOCUMENTS` |
| GET | `/api/v1/cases/{case_id}/analysis-runs` | List runs newest first (`status`) |
| GET | `/api/v1/analysis-runs/{run_id}` | Run with stages + summary |
| GET | `/api/v1/analysis-runs/{run_id}/stages` | Stage statuses |
| POST | `/api/v1/analysis-runs/{run_id}/retry` | Retry as new linked run; `409 RETRY_NOT_ALLOWED / RETRY_LIMIT_REACHED` |
| POST | `/api/v1/cases/{case_id}/reviews` | Create review → `201` |
| GET | `/api/v1/cases/{case_id}/reviews` | List (`status`, `analysis_run_id`, `reviewer_id`) |
| GET / PATCH | `/api/v1/reviews/{review_id}` | Get / update status, notes, action, refs |
| POST | `/api/v1/reviews/{review_id}/request-information` | Record information request |
| GET | `/api/v1/cases/{case_id}/audit-events` | Audit trail (`event_type`, `actor`, `since`, `until`, `analysis_run_id`, `newest_first`) |
| GET | `/api/v1/analysis-runs/{run_id}/audit-events` | Audit trail of one run |

Examples (full schemas are in Swagger `/docs`):

```jsonc
// POST /api/v1/cases
{"title":"State v. Synthetic","fir_number":"FIR-2024-001","court_name":"Demo Sessions Court",
 "statutory_sections":[{"act":"Demo Act","section":"12"}],"metadata":{"note":"synthetic"}}
// 201 -> {"id":"case_0006...","status":"OPEN","analysis_needs_refresh":false,"statutory_sections":[...],...}

// POST /api/v1/cases/{case_id}/documents
{"filename":"fir.pdf","mime_type":"application/pdf","size_bytes":10,
 "checksum_sha256":"<64 hex chars>","document_type":"FIR"}
// 201 -> {"document":{"id":"doc_...","version":1,"processing_status":"PENDING",...},
//         "created":true,"analysis_needs_refresh":true,"triggered_analysis_run_id":null}

// POST /api/v1/cases/{case_id}/analysis-runs   (body optional)
{"document_ids":null,"requested_modules":null,"force":false,"reprocess_documents":false,
 "idempotency_key":null,"rule_config":{"rule_set_id":"R","rule_set_version":"1"}}
// 201 -> {"id":"run_...","status":"COMPLETED","stages":[{"stage_name":"document_intelligence","status":"SUCCEEDED",...},...],
//         "summary":{"evidence_count":2,"conflict_count":1,"rule_result_count":1,
//                    "review_signals":["INSUFFICIENT_INFORMATION"],"analysis_outcome":null,"simulated_output":true},
//         "reused_existing":false}

// POST /api/v1/cases/{case_id}/reviews
{"analysis_run_id":"run_...","reviewer_id":"reviewer-1","notes":"Initial look",
 "reviewed_finding_refs":[{"type":"conflict","id":"cfl_..."}]}
// PATCH /api/v1/reviews/{id}      {"status":"IN_REVIEW"}  then  {"status":"REVIEW_COMPLETED","notes":"..."}
// POST  /api/v1/reviews/{id}/request-information   {"request_text":"Please upload the remand order."}
```
Review transitions: `PENDING_REVIEW→IN_REVIEW|ADDITIONAL_INFORMATION_REQUESTED`,
`IN_REVIEW→ADDITIONAL_INFORMATION_REQUESTED|REVIEW_COMPLETED`,
`ADDITIONAL_INFORMATION_REQUESTED→IN_REVIEW|REVIEW_COMPLETED`; completed reviews are immutable.
Reviews never modify evidence, conflicts or rule results.

## 8. Integration guide for Persons 1, 2 and 3

All contracts live in **`app/orchestration/contracts.py`** (single source of truth — do not copy
or fork). Do not add API routes or DB models; only implement the agent class.

| Person | Implement | Method | Input model → Output model | File to own |
|---|---|---|---|---|
| 1 | `DocumentIntelligenceAgent` | `extract(request)` | `DocumentAgentInput → DocumentAgentOutput` | your package (replaces `app/integrations/document_agent.py` demo) |
| 2 | `ConflictDetectionAgent` | `analyze(request)` | `ConflictAgentInput → ConflictAgentOutput` | your package |
| 3 | `ReasoningAgent` | `evaluate(request)` | `ReasoningAgentInput → ReasoningAgentOutput` | your package |

Every agent is a plain class with `name`, `version` and its one method (sync, no-arg constructor,
must be **idempotent** because timeouts/retries can call it again).

**Wire rules (contract 1.0).** IDs `case_/doc_/evd_/cfl_/run_` + 21 hex; timestamps timezone-aware
ISO-8601; dates `YYYY-MM-DD` or `null` (a `null` date requires `verification_status=UNKNOWN` —
never guess); statuses `SUCCESS|PARTIAL|FAILED`; output `contract_version` major must be `1`;
extra input fields are forbidden, output extras are ignored. Every output must carry
`agent_name`, `agent_version`, `is_simulated`.

**Person 1** receives `documents[]` (`document_id`, `version`, `filename`, `mime_type`,
`checksum_sha256`, `storage_key`, `content_path` — an absolute path only for files uploaded through
this backend) and returns `facts[]` (`fact_type` ∈ `ARREST_DATE, CUSTODY_START_DATE, REMAND_PERIOD,
CHARGE_SHEET_DATE, COURT_ORDER, HEARING_DATE, FIR_REFERENCE, STATUTORY_SECTION, OTHER`, `value`,
`source_document_id`, `source_page`, `quote`, `char_start/char_end`, `confidence`, `provenance`) and
**exactly one** `document_results[]` entry per input document (`SUCCESS|FAILED` + error). Evidence IDs
are assigned by the backend.

**Person 2** receives `evidence[]` with backend `evidence_id`s and returns `findings[]`
(`finding_type` ∈ `CONTRADICTION, DUPLICATE_EVIDENCE, AMBIGUOUS_FACT, WEAKLY_SUPPORTED,
MISSING_EVIDENCE`, `description`, `severity`, `related_evidence_ids`, `related_document_ids`,
`conflicting_values`, `missing_information`, `resolution_status`). Referenced IDs must exist.

**Person 3** receives evidence, `conflicts[]` and `rule_config` and returns `evaluations[]`
(`rule_id`, `rule_version`, `evaluation_status`, neutral `review_signal`, `explanation`,
`input_evidence_ids`, `missing_prerequisites`, `limitations`, `output_schema_version`). Rule
validity is owned by Person 3 and legal reviewers; `(rule_id, rule_version)` must be unique per output.

**Register an agent** (either way; no backend code changes):
1. `.env`: `DOCUMENT_AGENT_CLASS=person1_pkg.agent:MyDocumentAgent` (likewise `CONFLICT_AGENT_CLASS`,
   `REASONING_AGENT_CLASS`) and `ENABLE_DEMO_AGENTS=false`. The package must be importable
   (`pip install -e ../person1_pkg`). A bad path is reported under `configuration_error` in
   `/api/v1/system/status`; startup never fails.
2. Or in code: `registry.register("reasoning", MyAgent())` (`app.state.registry`).

**How it runs.** Orchestrator builds the typed input from the DB → calls your method in a worker
thread with `AGENT_TIMEOUT_SECONDS` → re-validates your output with the contract models plus
cross-reference checks → persists it in one transaction with the stage status and audit events.
**Failure representation:** raise `AgentUnavailableError` / `AgentProcessingError(message, code=…)` from
`app.orchestration.contracts` (or return `status=FAILED` with `errors[]`); `AgentUnavailableError` and
timeouts are retried; `NotImplementedError` → `NOT_IMPLEMENTED`; invalid output → `AGENT_INVALID_OUTPUT`
and nothing from that stage is stored. Keep error messages free of document text (they are stored,
truncated to 300 chars; unexpected exceptions record only the exception type).

**Test your integration** before merging:
```powershell
# 1. contract check
python -c "from app.orchestration.contracts import DocumentAgentOutput; print(DocumentAgentOutput.model_validate(my_output_dict))"
# 2. end to end with your agent registered (see tests/agents.py full_registry for the pattern)
python -m pytest
```
Then start the server, register a synthetic document, `POST …/analysis-runs`, and check
`GET /api/v1/analysis-runs/{id}` shows your stage `SUCCEEDED` with `is_simulated=false`.

## 9. Verification checklist

Run these locally (results below marked ✔ were executed in the development sandbox).

- [ ] App starts: `python -m uvicorn app.main:app --port 8000` (✔ smoke-tested)
- [ ] Migrations: `alembic upgrade head`, `alembic check` → "No new upgrade operations detected" (✔)
- [ ] `GET /api/health` → `{"status":"ok"...}` (✔)
- [ ] Case creation via Swagger `/docs` (✔ automated + smoke)
- [ ] Document registration → `processing_status: PENDING` (✔)
- [ ] Analysis run → `COMPLETED`, 3 stages `SUCCEEDED`, `simulated_output: true` (✔)
- [ ] Findings/rule results via `/evidence`, `/conflicts`, `/rule-results` (✔)
- [ ] Human review lifecycle + information request (✔ tests)
- [ ] Audit events persist and cannot be changed via API/ORM (✔ tests)
- [ ] `python -m pytest` → **69 passed** (✔ in sandbox; re-run on your machine)

Not verified in the sandbox: Windows/PowerShell itself (commands written for it but executed on
Linux), PostgreSQL (schema is written to be portable, only SQLite was run).
