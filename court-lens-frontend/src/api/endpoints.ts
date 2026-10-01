/** CourtLens backend v2 API contract. */
export type EndpointKey =
  | 'login' | 'logout' | 'me'
  | 'dashboard' | 'cases' | 'case'
  | 'evidence' | 'conflicts' | 'missingEvidence' | 'reasoning'
  | 'timeline' | 'evolution' | 'status'
  | 'documents' | 'notifications' | 'upload';

export const endpoints: Record<EndpointKey, string | undefined> = {
  // The backend currently uses development API-key auth, not a login/session API.
  login: undefined,
  logout: undefined,
  me: undefined,

  // Existing backend resources.
  dashboard: '/cases',
  cases: '/cases',
  case: '/cases/{caseId}',
  evidence: '/cases/{caseId}/evidence',
  conflicts: '/cases/{caseId}/conflicts',
  reasoning: '/cases/{caseId}/analysis-runs',
  timeline: '/cases/{caseId}/history',
  evolution: '/cases/{caseId}/history',
  status: '/cases/{caseId}',

  // These UI concepts do not currently have a matching backend v1 route.
  // Backend conflicts explicitly include evidence-gap findings, so this is the closest supported resource.
  missingEvidence: '/cases/{caseId}/conflicts',
  notifications: '/notifications',
  documents: '/documents',

  upload: '/cases/{caseId}/documents/upload'
};

export interface AuthField {
  name: string;
  label: string;
  type: 'text' | 'email' | 'password' | 'tel';
}

// Authentication is configured through VITE_API_KEY for the current dev backend.
export const authFields: AuthField[] = [];

/** Multipart field required by POST /cases/{caseId}/documents/upload. */
export const uploadFieldName = 'file' as const;

/** Primary identifier returned by CaseRead. */
export const caseIdField = 'id' as const;
