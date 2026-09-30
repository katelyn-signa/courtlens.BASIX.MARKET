import type { AnyRecord } from '../types';

function Value({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="text-charcoal/50">—</span>;
  if (typeof v === 'object') {
    return <pre className="max-h-48 overflow-auto rounded bg-paper p-2 text-xs">{JSON.stringify(v, null, 2)}</pre>;
  }
  return <span className="break-words">{String(v)}</span>;
}

/** Renders whatever fields the backend returned. Replace with typed cards once the spec exists. */
export function RecordCard({ record }: { record: AnyRecord }) {
  return (
    <article className="rounded-lg border border-line bg-white p-5 shadow-sm">
      <dl className="grid gap-3">
        {Object.entries(record).map(([k, v]) => (
          <div key={k}>
            <dt className="text-xs font-medium text-charcoal/70">{k}</dt>
            <dd className="text-sm"><Value v={v} /></dd>
          </div>
        ))}
      </dl>
    </article>
  );
}
