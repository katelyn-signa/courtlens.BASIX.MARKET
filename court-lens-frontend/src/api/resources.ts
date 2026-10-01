import { api, resolvePath } from './client';
import { endpoints, type EndpointKey } from './endpoints';
import { NotConfiguredError } from './errors';
import { toList } from './adapters';

export async function getResource(key: EndpointKey, params: Record<string, string | undefined>, signal?: AbortSignal): Promise<unknown> {
  const tpl = endpoints[key];
  if (!tpl) throw new NotConfiguredError(`Endpoint "${key}"`);
  const { data } = await api.get<unknown>(resolvePath(tpl, params), { signal });

  // ResourcePage expects arrays for collection endpoints. Preserve object responses
  // (case, status, history, etc.) and normalize only paginated collection payloads.
  if (Array.isArray(data)) return data;
  if (data && typeof data === 'object' && 'items' in data) return toList(data);
  return data;
}
