/**
 * BACKEND INTEGRATION POINT #1
 * Fill these in from the backend specification. Use {param} for path params.
 * Left undefined on purpose: the frontend never guesses endpoint URLs.
 */
export type EndpointKey =
  | 'login' | 'logout' | 'me'
  | 'dashboard' | 'cases' | 'case'
  | 'evidence' | 'conflicts' | 'missingEvidence' | 'reasoning'
  | 'timeline' | 'evolution' | 'status'
  | 'documents' | 'notifications' | 'upload';

export const endpoints: Record<EndpointKey, string | undefined> = {
  login: undefined,
  logout: undefined,
  me: undefined,
  dashboard: undefined,
  cases: undefined,
  case: undefined,           // e.g. '/…/{caseId}'
  evidence: undefined,
  conflicts: undefined,
  missingEvidence: undefined,
  reasoning: undefined,
  timeline: undefined,
  evolution: undefined,
  status: undefined,
  documents: undefined,
  notifications: undefined,
  upload: undefined
};

/** Login fields required by the backend auth contract (email, phone, OTP, …). */
export interface AuthField {
  name: string;
  label: string;
  type: 'text' | 'email' | 'password' | 'tel';
}
export const authFields: AuthField[] = [];

/** Multipart field name expected by the upload endpoint. */
export const uploadFieldName: string | undefined = undefined;

/** Name of the case identifier field in backend case records (used to link cards). */
export const caseIdField: string | undefined = undefined;
