import { api, resolvePath } from './client';
import { endpoints, type EndpointKey } from './endpoints';
import { NotConfiguredError } from './errors';
import { toList } from './adapters';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export async function getResource(key: EndpointKey, params: Record<string, string | undefined>, signal?: AbortSignal): Promise<unknown> {
  const tpl = endpoints[key];
  if (!tpl) throw new NotConfiguredError(`Endpoint "${key}"`);
  const { data } = await api.get<unknown>(resolvePath(tpl, params), { signal });

  // /history is a composite object. Adapt its UI-specific collections into
  // the array contract expected by ResourcePage.
  if (key === 'missingEvidence') {
    const records = Array.isArray(data)
      ? data
      : isRecord(data) && Array.isArray(data.items)
        ? data.items
        : [];
    return records.filter((item) =>
      isRecord(item) &&
      typeof item.missing_information === 'string' &&
      item.missing_information.trim().length > 0
    );
  }

  if (key === 'timeline' && isRecord(data)) {
    return isRecord(data.audit_events) && 'items' in data.audit_events
      ? toList(data.audit_events)
      : [];
  }
  if (key === 'evolution' && isRecord(data)) {
    return isRecord(data.analysis_runs) && 'items' in data.analysis_runs
      ? toList(data.analysis_runs)
      : [];
  }

  // ResourcePage expects arrays for collection endpoints. Preserve object responses
  // (case, status, history, etc.) and normalize only paginated collection payloads.
  if (Array.isArray(data)) return data;
  if (data && typeof data === 'object' && 'items' in data) return toList(data);
  return data;
}
