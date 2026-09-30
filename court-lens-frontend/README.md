# CourtLens Frontend

React + TypeScript + Vite + Tailwind + React Query. No backend data is invented: every endpoint, login field and response adapter is an explicit integration point until the backend spec is supplied.

## Setup
- Node.js 18.18+ (20 LTS recommended)
- `npm install`
- `cp .env.example .env` and set `VITE_API_BASE_URL` (use https in production), plus `VITE_MAX_UPLOAD_MB` and `VITE_ALLOWED_FILE_TYPES` (e.g. `.pdf,.png`) from the backend spec.
- `npm run dev` — dev server · `npm run build` — type-check + production build · `npm run preview` — serve the build

## Where the backend connects
1. `src/api/endpoints.ts` — endpoint paths (`{caseId}` placeholders), login fields, upload field name, case id field. All `undefined` now; unconfigured screens say so instead of showing fake data.
2. `src/api/auth.ts` — `toSession()` must map the backend response to `{ role }`. **The role comes from the backend**, never from the role card. Also set token handling here if the contract uses bearer tokens (`setAuthToken`, memory only) or set `VITE_API_WITH_CREDENTIALS=true` for cookie sessions.
3. `src/api/adapters.ts` — response-shape adapters. `ResourcePage` currently renders backend fields generically via `RecordCard`; replace with typed EvidenceCard/ConflictCard/ReasoningTrace/VersionComparison once schemas exist.
4. `src/api/documents.ts` — upload; shows the raw server response. Add polling only as the spec defines.

## Role-based access
`ProtectedRoute` redirects unauthenticated users to `/login` and sends a user with the wrong role to their own dashboard. This is a UX guard only: the backend must enforce authorization on every request.

## Security notes
No secrets, keys or credentials in source; tokens (if any) live in memory only; no sensitive logging; file type/size validated before upload. Do not describe the app as end-to-end encrypted: the backend must read documents for AI processing, so transport is HTTPS/TLS and any at-rest encryption is a backend concern.
