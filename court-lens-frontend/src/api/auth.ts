import { api, setAuthToken } from './client';
import { endpoints } from './endpoints';
import { NotConfiguredError } from './errors';
import type { Role, Session } from '../types';

/**
 * BACKEND INTEGRATION POINT #2
 * Convert the backend's auth/me response into a Session. The role MUST come
 * from the backend, never from the role card the user clicked.
 */
export function toSession(_raw: unknown): Session {
  throw new NotConfiguredError('Auth response adapter (toSession)');
}

export async function login(selectedRole: Role, credentials: Record<string, string>): Promise<Session> {
  if (!endpoints.login) throw new NotConfiguredError('Login endpoint');
  // TODO(backend): match the real request body. selectedRole is sent only if the contract asks for it.
  void selectedRole;
  const { data } = await api.post<unknown>(endpoints.login, credentials);
  // TODO(backend): if the contract returns a token, call setAuthToken(token) here.
  return toSession(data);
}

export async function fetchSession(): Promise<Session> {
  if (!endpoints.me) throw new NotConfiguredError('Session endpoint');
  const { data } = await api.get<unknown>(endpoints.me);
  return toSession(data);
}

export async function logout(): Promise<void> {
  setAuthToken(null);
  if (endpoints.logout) await api.post(endpoints.logout);
}
