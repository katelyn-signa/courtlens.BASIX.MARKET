import { useQuery } from '@tanstack/react-query';
import { getResource } from '../api/resources';
import type { EndpointKey } from '../api/endpoints';
import { classifyError } from '../api/errors';

export function useResource(key: EndpointKey, params: Record<string, string | undefined> = {}) {
  return useQuery({
    queryKey: [key, params],
    queryFn: ({ signal }) => getResource(key, params, signal),
    retry: (count, err) => classifyError(err) === 'network' && count < 2
  });
}
