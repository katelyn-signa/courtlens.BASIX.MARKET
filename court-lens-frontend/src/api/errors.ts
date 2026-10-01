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

export function errorMessage(e: unknown, fallback = 'Request failed. Please try again.'): string {
  if (e instanceof NotConfiguredError) return e.message;
  if (axios.isAxiosError(e)) {
    const data = e.response?.data as unknown;
    if (typeof data === 'object' && data !== null && 'error' in data) {
      const body = (data as { error?: unknown }).error;
      if (typeof body === 'object' && body !== null && 'message' in body) {
        const message = (body as { message?: unknown }).message;
        if (typeof message === 'string' && message.trim()) return message;
      }
    }
    if (typeof e.message === 'string' && e.message.trim()) return e.message;
  }
  if (e instanceof Error && e.message.trim()) return e.message;
  return fallback;
}
