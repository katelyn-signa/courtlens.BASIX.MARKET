import { api, resolvePath } from './client';
import { endpoints, type EndpointKey } from './endpoints';
import { NotConfiguredError } from './errors';

export async function getResource(key: EndpointKey, params: Record<string, string | undefined>, signal?: AbortSignal): Promise<unknown> {
  const tpl = endpoints[key];
  if (!tpl) throw new NotConfiguredError(`Endpoint "${key}"`);
  const { data } = await api.get<unknown>(resolvePath(tpl, params), { signal });
  return data;
}
