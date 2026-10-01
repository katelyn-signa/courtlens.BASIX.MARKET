# CourtLens — Integrated Project Architecture

> Current integration target: **React/Vite frontend + FastAPI backend-v2 + SQLite/Alembic**.  
> The backend exposes its shared API under `/api/v1`; the frontend is configured to consume that contract.

## Current architecture

```
Browser
  │
  │ React 18 + TypeScript + Vite
  │ Axios + TanStack Query
  ▼
court-lens-frontend
  │
  │ HTTP / JSON + multipart upload
  │ X-API-Key (optional) + X-Actor-Id
  ▼
backend-v2
  │
  ├── FastAPI /api/v1
  ├── Cases
  ├── Documents & uploads
  ├── Evidence / conflicts / rule results
  ├── Analysis runs
  ├── Reviews
  ├── Audit events
  └── System metrics/health
  │
  ├── SQLAlchemy
  ├── Alembic migrations
  ├── SQLite (local/demo)
  ├── private local storage
  └── orchestration / agents
```

### Integration contract

- Frontend API base: `http://localhost:8000/api/v1`
- Public health: `http://localhost:8000/api/health`
- Frontend dev server: `http://localhost:5173`
- Backend CORS allows the two local Vite origins by default.
- Backend API-key authentication is optional in development.
- Frontend authentication is currently a **demo role/session layer** because backend login/session endpoints are not implemented. It must not be presented as production authentication.
- Backend outputs are decision-support/workflow signals and require human review; they do not make legal decisions.

## Run the integrated stack

### Terminal 1 — Backend

```powershell
cd backend-v2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

### Terminal 2 — Frontend

```powershell
cd court-lens-frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open the Vite URL shown in the terminal, normally `http://localhost:5173`.

### Optional API key

If you set `API_KEY` in `backend-v2/.env`, put the same value in `court-lens-frontend/.env` as `VITE_API_KEY`. The frontend sends it as `X-API-Key`.

## Verification checklist

1. Open `http://localhost:8000/api/health` — backend should return a healthy response.
2. Open the frontend at `http://localhost:5173`.
3. Sign in using the existing demo role flow.
4. Case lists should load from `GET /api/v1/cases`.
5. Case pages should resolve `{caseId}` correctly.
6. Evidence, conflicts, analysis runs and history should consume their backend v1 resources.
7. Evidence/document upload should use `POST /api/v1/cases/{caseId}/documents/upload`.
8. Do not commit either `.env` file; only the example files belong in Git.

---

# CourtLens Member 2: Document Intelligence

## What this module does

CourtLens Member 2 is responsible for document and evidence intelligence: extracting text from documents, classifying documents, supporting case intake, extracting evidence and claims, mapping evidence to claims, and identifying conflicts and evidence gaps. Those capabilities are planned for later phases.

## Phase 1 status

Phase 1 established the Python project, FastAPI application, and health endpoint.

## PHASE 2 - PDF DOCUMENT EXTRACTION

The PDF extraction flow is:

```text
PDF
↓
PyMuPDF
↓
page-by-page text
↓
structured JSON
```

The extraction service preserves every page boundary and uses page numbers starting at 1. Each page includes its `extraction_method` (`text` or `ocr`). Invalid PDFs and zero-page PDFs return an API error.

### API endpoint

`POST /api/documents/extract` accepts a multipart form upload with the field name `file`.

Sample request:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/documents/extract" `
	-F "file=@sample_data/documents/fictional_payment_agreement.pdf;type=application/pdf"
```

Sample response (text may include line breaks extracted from the PDF):

```json
{
	"document_id": "a2a5f6b6-eac5-45a3-bf79-5bd5eb0768b6",
	"filename": "fictional_payment_agreement.pdf",
	"page_count": 2,
	"pages": [
		{
			"page": 1,
			"text": "COMMERCIAL PAYMENT AGREEMENT\nSeller: ABC Industries\nBuyer: XYZ Traders\nTotal Contract Amount: INR 500000\nPayment Due Date: 10 August 2026\n",
			"extraction_method": "text"
		},
		{
			"page": 2,
			"text": "DELIVERY AND PAYMENT\nGoods were delivered on 5 August 2026.\nPayment shall be made according to the agreement.\n",
			"extraction_method": "text"
		}
	]
}
```

No AI processing or database is included in Phase 2.

## Phase 3 - OCR Fallback

Normal PyMuPDF text extraction is attempted first. Tesseract OCR runs only when a page has no usable text; usable normal text is kept without OCR. OCR uses PyMuPDF's built-in `page.get_textpage_ocr()` integration at 200 DPI, balancing legibility for scanned pages with processing time. OCR is slower than normal text extraction. Each page reports `extraction_method` as `text` or `ocr`.

Tesseract 5 and its English `eng.traineddata` file are required for image-only pages. The tessdata directory is configured with `TESSDATA_PREFIX`. If it is unset, the service uses `C:\Program Files\Tesseract-OCR\tessdata`. On Windows, the standard Tesseract installation location is checked when the executable is not on `PATH`.

Windows PowerShell configuration example:

```powershell
$env:TESSDATA_PREFIX = 'C:\Program Files\Tesseract-OCR\tessdata'
```

## Phase 4A - Document Classification

The extraction pipeline now continues from page-by-page text into a deterministic local classifier:

1. PDF text is extracted normally.
2. OCR is used only when normal text is unusable.
3. The resulting extracted text is passed to the classifier.
4. The classifier selects one controlled document type using weighted keyword and phrase rules.
5. The result includes matched signals so the decision is transparent.

Supported categories: `contract`, `purchase_order`, `invoice`, `payment_record`, `delivery_receipt`, `email`, `court_order`, `claim_statement`, and `other`.

The confidence value represents rule-based classification strength, not a calibrated statistical probability. Documents with insufficient or tied signals are classified as `other`.

`POST /api/documents/classify` accepts either extracted text or an existing extraction result.

Example with text:

```json
{
	"text": "TAX INVOICE Invoice Number: INV-1042 Bill To: XYZ Traders"
}
```

Example response:

```json
{
	"document_type": "invoice",
	"confidence": 0.925,
	"matched_signals": ["tax invoice", "invoice number", "invoice", "bill to"]
}
```

## Phase 4B — Structured Fact Extraction

The current pipeline is:

```text
PDF/OCR extraction
→ document classification
→ deterministic fact extraction
→ provenance-preserving structured facts
```

Fact extraction uses local label-based rules, regular expressions, and date/amount normalization. Each fact retains its document ID when available, source page, original quote, extraction method, normalized value, and deterministic extraction confidence. Supported facts cover parties, identifiers, financial amounts, dates, obligations, claims, and email subjects.

`POST /api/documents/extract-facts` accepts the existing extracted document representation and an optional classification result. When classification is omitted, the existing local document classifier is used.

This phase uses deterministic extraction rules. It does not provide legal conclusions.

## Phase 5 — Evidence and Claim Intelligence

The pipeline now continues from structured facts into evidence and claim candidates:

```text
documents
→ facts
→ evidence
→ claims
```

Facts are extracted values. Each evidence item links back to its fact ID and preserves the source document, page, original quote, and extraction method. Claims are attributed statements that may require verification; they are not automatically treated as facts. Payment claims are marked supported only when an exact amount matches an extracted payment-record amount. Other claims remain unverified unless there is similarly clear deterministic support.

`POST /api/documents/extract-evidence` accepts an extracted document and optional classification, then returns facts, evidence, and claims together. Extraction confidence reflects how clearly a value or statement was extracted; it does not represent legal truth. Claim status is not a legal conclusion.

## Phase 6 — Conflict Detection

The deterministic conflict engine compares facts only when they share a semantic field/event and have linked evidence. It detects amount, date, party, case ID, obligation, claim/evidence, timeline, and generic fact conflicts. Different fields such as `contract_amount` and `amount_paid` are not treated as contradictory; common company suffix and punctuation differences are normalized.

`POST /api/documents/detect-conflicts` accepts flat `facts`, `evidence`, and `claims` arrays or multiple Phase 5 results under `analyses`.

Example response:

```json
{
	"conflict_count": 1,
	"conflicts": [
		{
			"conflict_id": "C001",
			"conflict_type": "date_conflict",
			"fact_type": "date",
			"description": "Conflicting values for payment_date: 2026-08-10, 2026-08-12.",
			"severity": "high",
			"status": "open",
			"conflicting_values": [
				{
					"value": "10 August 2026",
					"normalized_value": "2026-08-10",
					"fact_id": "F001",
					"evidence_id": "E0001",
					"document_id": "DOC-A",
					"page": 1,
					"quote": "Payment Date: 10 August 2026"
				},
				{
					"value": "12 August 2026",
					"normalized_value": "2026-08-12",
					"fact_id": "F001",
					"evidence_id": "E0001",
					"document_id": "DOC-B",
					"page": 1,
					"quote": "Payment Date: 12 August 2026"
				}
			],
			"evidence_ids": ["E0001", "E0001"],
			"document_ids": ["DOC-A", "DOC-B"],
			"source_pages": [1, 1],
			"quotes": ["Payment Date: 10 August 2026", "Payment Date: 12 August 2026"],
			"confidence": 0.98,
			"detected_by": "deterministic_conflict_engine"
		}
	]
}
```

Conflicts remain open for review and are not legal conclusions. Run the complete suite with `\.venv\Scripts\python.exe -m pytest -q`.

## Phase 7 — Evidence Gap Detection

The deterministic gap engine identifies evidence that may be missing without treating gaps as conflicts or making legal conclusions. It checks for missing payment proof, delivery proof, party identity, contractual basis, unsupported claims, and unresolved material conflicts. It does not request an invoice just because one is absent.

`POST /api/documents/detect-gaps` accepts facts, evidence, claims, conflicts, and optional classification.

Example response:

```json
{
	"gap_count": 1,
	"gaps": [
		{
			"gap_id": "G001",
			"gap_type": "missing_payment_proof",
			"description": "Payment proof is not available for the full-payment claim.",
			"importance": "high",
			"status": "open",
			"related_fact_types": [],
			"related_claim_ids": ["CL-001"],
			"related_evidence_ids": [],
			"related_conflict_ids": [],
			"related_document_ids": ["DOC-001"],
			"source_pages": [1],
			"quotes": ["Buyer has paid the full amount."],
			"suggested_evidence": ["Bank statement, payment receipt, or equivalent proof."],
			"reason": "The full-payment claim has no linked payment record.",
			"confidence": 0.96,
			"detected_by": "deterministic_evidence_gap_engine"
		}
	]
}
```

Run the full suite with `\.venv\Scripts\python.exe -m pytest -q`.

## Phase 8 — Evidence Retrieval and Search

`POST /api/documents/search` ranks supplied facts, evidence, claims, conflicts, gaps, and extracted page passages using deterministic, case-insensitive keyword matching. Exact terms and phrases score above partial substring matches; matching more query terms increases relevance. Results retain their available document, page, quote, and record IDs.

Example request:

```json
{
	"query": "payment",
	"top_k": 10,
	"documents": [
		{
			"document_id": "D001",
			"filename": "contract.pdf",
			"page_count": 1,
			"pages": [
				{
					"page": 1,
					"text": "Payment Date: 12 August 2026",
					"extraction_method": "text"
				}
			]
		}
	]
}
```

Example result:

```json
{
	"query": "payment",
	"total": 1,
	"results": [
		{
			"result_id": "document:D001:page:1",
			"result_type": "document_passage",
			"score": 1.0,
			"title": "contract.pdf - Page 1",
			"snippet": "Payment Date: 12 August 2026",
			"document_id": "D001",
			"filename": "contract.pdf",
			"page": 1,
			"quote": "Payment Date: 12 August 2026",
			"confidence": null
		}
	]
}
```

This baseline uses keyword matching, not semantic understanding; it can miss relevant passages that use different wording. Run the complete suite with `\.venv\Scripts\python.exe -m pytest -q`.

## Phase 9 — Case Intake and Structure

`POST /api/cases/intake` assembles supplied document references, facts, evidence, claims, conflicts, and gaps into an in-memory case structure. Existing record IDs are preserved. The service calculates record counts, transparent review signals, and date timeline candidates from normalized facts. Missing metadata remains `null`; parties may be supplied directly or projected from existing party facts.

Example request:

```json
{
	"case_id": "C-104",
	"case_title": "SME Payment Dispute",
	"case_type": "commercial_dispute",
	"documents": [
		{
			"document_id": "D001",
			"filename": "fictional_payment_agreement.pdf",
			"document_type": "contract",
			"source_type": "pdf_upload",
			"page_count": 2
		}
	],
	"facts": [],
	"evidence": [],
	"claims": [],
	"conflicts": [],
	"gaps": []
}
```

The result includes the structured case, deterministic counts, status signals, and source-linked timeline candidates. This phase is in-memory only and does not make legal decisions.

## Phase 10 — Unified Case Analysis

`POST /api/cases/analyze` accepts case metadata and a list of documents. Each document may provide `content_base64` plus `filename` for PDF extraction/OCR, or an existing `extracted_document` object. The pipeline reuses existing extraction, classification, fact, evidence, claim, conflict, gap, and case-intake services; per-document errors are returned with that document and do not discard successful analyses.

The response is a structured handoff package containing per-document status/classification, case intake, facts, evidence, claims, conflicts, evidence gaps, counts, and a deterministic workflow review signal. Record IDs and provenance are preserved. The result supports downstream reasoning/orchestration and does not provide legal conclusions.

Example request:

```json
{
	"case_id": "C-104",
	"case_title": "SME Payment Dispute",
	"case_type": "commercial_dispute",
	"documents": [
		{
			"document_id": "DOC-001",
			"filename": "fictional_payment_agreement.pdf",
			"content_base64": "<base64-encoded PDF bytes>"
		}
	]
}
```

The `content_base64` value is the PDF file bytes encoded with standard Base64. Run the complete suite with `\.venv\Scripts\python.exe -m pytest -q`.

## Phase 11 — Auditable Reasoning Foundation

The reasoning handoff is:

```text
Structured Evidence
→ Semantic Interpretation
→ Symbolic Rules
→ Reasoning Trace
→ Human Review Signal
```

`POST /api/cases/reason` accepts a Phase 10 `CaseAnalysisResult` and returns semantic observations, evidence references, versioned rule evaluations, ordered reasoning steps, unresolved questions, a workflow recommendation, and a human-review flag. Rules R001–R005 are deterministic Python rules; the semantic adapter only maps existing structured records and does not execute rules.

Payment records are not considered verified merely because they were extracted. A caller must explicitly populate `verified_evidence_ids` with IDs for payment-record evidence it has verified. The request model validates that every selected ID exists and references `payment_record` evidence. The reasoning layer trusts this caller assertion; it does not independently verify the underlying bank or receipt source.

The `evidence_support_score` is a deterministic workflow score, not statistical confidence: start with the number of unique provenance-complete evidence references divided by three (capped at 1); subtract 0.20 for a triggered payment-claim conflict, 0.20 for a triggered date conflict, and 0.15 for each supplied evidence-gap observation; clamp the result to [0, 1]. Categories are `low` below 0.45, `medium` from 0.45 to below 0.80, and `high` at or above 0.80. This is not a calibrated probability.

MeTTa is not installed or required. Current implementation uses deterministic symbolic rules. MeTTa integration is isolated behind an adapter for later integration when the runtime is available. Gemini is not required. Outputs are not legal advice; human review remains required for unresolved evidence and conflicts.

## Phase 12 — Stateful Case Agent

The agent continues from persistent case state:

```text
Document → Evidence → Reasoning → Case Memory
→ New Evidence → Change Detection → Targeted Re-Reasoning → New Case Version
```

SQLite stores a case head, immutable JSON snapshots for each version, and an append-only event log. Set `COURTLENS_SQLITE_PATH` to choose the database file; otherwise the database is `.courtlens/cases.sqlite3` (ignored by Git). Updates merge by document/record IDs, retain previous snapshots, record changes, and refresh dependent rules plus the human-review rule. Duplicate documents and records do not create new versions. Challenges are persisted as state/events; a challenged evidence item is excluded from the verified-payment set and receives a source-linked verification gap.

Endpoints: `POST /api/cases/{case_id}/agent/start`, `POST /api/cases/{case_id}/agent/update`, `GET /api/cases/{case_id}/state`, `GET /api/cases/{case_id}/versions`, `GET /api/cases/{case_id}/versions/{version}`, `GET /api/cases/{case_id}/events`, `GET /api/cases/{case_id}/versions/{from_version}/{to_version}/diff`, and `POST /api/cases/{case_id}/agent/challenge`.

Versions are immutable and events are append-only. Outputs remain workflow/evidence signals, not legal advice or decisions.

## Setup

From the project directory, create the virtual environment:

```powershell
python -m venv .venv
```

Activate it in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run tests

```powershell
python -m pytest
```

## Start FastAPI

```powershell
python -m uvicorn app.main:app --reload
```

The health endpoint is available at http://127.0.0.1:8000/api/health.
