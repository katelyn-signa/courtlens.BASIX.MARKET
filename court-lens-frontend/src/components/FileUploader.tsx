import { useRef, useState, type DragEvent } from 'react';
import { UploadCloud } from 'lucide-react';
import { uploadDocument } from '../api/documents';
import { classifyError } from '../api/errors';
import { uploadRules, validateFile } from '../utils/upload';
import { StatusBadge } from './StatusBadge';
import { RecordCard } from './RecordCard';
import type { AnyRecord } from '../types';
import { useQueryClient } from '@tanstack/react-query';

type Phase = 'idle' | 'uploading' | 'done' | 'error';

export function FileUploader({ caseId }: { caseId: string }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [phase, setPhase] = useState<Phase>('idle');
  const [file, setFile] = useState<File | null>(null);
  const [pct, setPct] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [response, setResponse] = useState<unknown>(null);

  async function start(f: File) {
    const problem = validateFile(f, uploadRules());
    setFile(f); setResponse(null);
    if (problem) { setPhase('error'); setMessage(problem); return; }
    abort.current = new AbortController();
    setPhase('uploading'); setPct(0); setMessage(null);
    try {
      const data = await uploadDocument(caseId, f, setPct, abort.current.signal);
      setResponse(data); setPhase('done');
      void qc.invalidateQueries({ queryKey: ['evidence'] });
      void qc.invalidateQueries({ queryKey: ['documents'] });
    } catch (e) {
      if (abort.current?.signal.aborted) { setPhase('idle'); setMessage('Upload cancelled.'); return; }
      setPhase('error');
      setMessage(classifyError(e) === 'not_configured'
        ? 'Upload is waiting for a backend endpoint (src/api/endpoints.ts).'
        : 'Upload failed. Check the file and try again.');
    }
  }

  const onDrop = (e: DragEvent) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) void start(f); };

  return (
    <section aria-label="Upload document" className="mb-6 rounded-lg border border-line bg-white p-5">
      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-charcoal/40 p-8 text-center"
      >
        <UploadCloud className="h-6 w-6" aria-hidden />
        <p className="text-sm">Drag a document here, or</p>
        <button type="button" onClick={() => input.current?.click()} className="rounded-md bg-ink px-4 py-2 text-sm text-white">
          Choose file
        </button>
        <input ref={input} type="file" className="sr-only" aria-label="Choose a document to upload"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void start(f); e.target.value = ''; }} />
      </div>

      {file && (
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm" aria-live="polite">
          <span className="font-medium">{file.name}</span>
          {phase === 'uploading' && <><StatusBadge tone="info">Uploading {pct}%</StatusBadge>
            <button onClick={() => abort.current?.abort()} className="underline">Cancel</button></>}
          {phase === 'done' && <StatusBadge tone="success">Upload accepted</StatusBadge>}
          {phase === 'error' && <><StatusBadge tone="conflict">Not uploaded</StatusBadge>
            <button onClick={() => void start(file)} className="underline">Retry</button></>}
        </div>
      )}
      {message && <p role="alert" className="mt-2 text-sm text-charcoal">{message}</p>}
      {phase === 'done' && response !== null && typeof response === 'object' && !Array.isArray(response) && (
        <div className="mt-4">
          <p className="mb-2 text-sm font-medium">Server response</p>
          <RecordCard record={response as AnyRecord} />
        </div>
      )}
    </section>
  );
}
