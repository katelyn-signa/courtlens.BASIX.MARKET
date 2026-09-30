import axios from 'axios';

export class NotConfiguredError extends Error {
  constructor(public what: string) {
    super(`${what} is not configured`);
  }
}

export type ErrorKind = 'not_configured' | 'network' | 'unauthorized' | 'forbidden' | 'other';

export function classifyError(e: unknown): ErrorKind {
  if (e instanceof NotConfiguredError) return 'not_configured';
  if (axios.isAxiosError(e)) {
    if (!e.response) return 'network';
    if (e.response.status === 401) return 'unauthorized';
    if (e.response.status === 403) return 'forbidden';
  }
  return 'other';
}
