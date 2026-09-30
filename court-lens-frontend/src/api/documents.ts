import { api, resolvePath } from './client';
import { endpoints, uploadFieldName } from './endpoints';
import { NotConfiguredError } from './errors';

/** Returns the raw backend response so the UI can show exactly what the server said. */
export async function uploadDocument(
  caseId: string,
  file: File,
  onProgress: (pct: number) => void,
  signal: AbortSignal
): Promise<unknown> {
  if (!endpoints.upload || !uploadFieldName) throw new NotConfiguredError('Upload endpoint / field name');
  const form = new FormData();
  form.append(uploadFieldName, file);
  const { data } = await api.post<unknown>(resolvePath(endpoints.upload, { caseId }), form, {
    signal,
    onUploadProgress: (e) => { if (e.total) onProgress(Math.round((e.loaded / e.total) * 100)); }
  });
  return data;
}
