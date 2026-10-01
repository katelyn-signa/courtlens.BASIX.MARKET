import type { ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { AlertCircle, Inbox, Loader2 } from 'lucide-react';
import { classifyError, errorMessage, type ErrorKind } from '../api/errors';
import { isEmpty } from '../api/adapters';

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-3 p-8 text-charcoal">
      <Loader2 className="h-5 w-5 animate-spin" aria-hidden /> <span>{label}</span>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line bg-white p-10 text-center text-charcoal">
      <Inbox className="h-6 w-6" aria-hidden /> <p>{message}</p>
    </div>
  );
}

const messages: Record<ErrorKind, string> = {
  not_configured: 'This screen is waiting for a backend endpoint. Connect it in src/api/endpoints.ts.',
  network: 'Unable to connect to CourtLens server.',
  unauthorized: 'Your session has expired. Sign in again.',
  forbidden: 'You do not have permission to view this information.',
  other: 'Unable to load this information. Please try again.'
};

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const kind = classifyError(error);
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-conflict/30 bg-conflict/5 p-5 text-conflict">
      <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden />
      <div>
        <p>{messages[kind]}</p>
        {kind === 'other' && <p className="mt-1 text-sm text-conflict/80">{errorMessage(error)}</p>}
        {onRetry && kind !== 'not_configured' && kind !== 'forbidden' && (
          <button onClick={onRetry} className="mt-2 text-sm underline">Try again</button>
        )}
      </div>
    </div>
  );
}

/** Handles loading / error / empty for any query, then hands real data to children. */
export function QueryView({ query, empty, loadingLabel, children }: {
  query: UseQueryResult<unknown>;
  empty: string;
  loadingLabel?: string;
  children: (data: unknown) => ReactNode;
}) {
  if (query.isPending) return <LoadingState label={loadingLabel} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (isEmpty(query.data)) return <EmptyState message={empty} />;
  return <>{children(query.data)}</>;
}
