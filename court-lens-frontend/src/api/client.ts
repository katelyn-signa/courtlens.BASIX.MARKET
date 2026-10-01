import axios from 'axios';

let authToken: string | null = null;
/** Kept in memory only for future bearer-token authentication. */
export const setAuthToken = (t: string | null) => { authToken = t; };

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || undefined,
  withCredentials: import.meta.env.VITE_API_WITH_CREDENTIALS === 'true'
});

api.interceptors.request.use((config) => {
  if (authToken) config.headers.set('Authorization', `Bearer ${authToken}`);

  const apiKey = import.meta.env.VITE_API_KEY;
  const actorId = import.meta.env.VITE_API_ACTOR_ID;
  if (apiKey) config.headers.set('X-API-Key', apiKey);
  if (actorId) config.headers.set('X-Actor-Id', actorId);

  return config;
});

export const resolvePath = (tpl: string, params: Record<string, string | undefined>) =>
  tpl.replace(/\\{(\\w+)\\}/g, (_, k: string) => encodeURIComponent(params[k] ?? ''));
