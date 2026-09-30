import type { ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useResource } from '../hooks/useResource';
import { QueryView } from '../components/States';
import { RecordCard } from '../components/RecordCard';
import { caseIdField, type EndpointKey } from '../api/endpoints';
import { useAuth } from '../services/AuthContext';
import type { AnyRecord } from '../types';

interface Props {
  title: string;
  resource: EndpointKey;
  empty: string;
  loadingLabel?: string;
  before?: (caseId: string) => ReactNode;
}

/** One data-driven page: fetch → loading/error/empty → render backend records as-is. */
export function ResourcePage({ title, resource, empty, loadingLabel, before }: Props) {
  const { caseId } = useParams();
  const { session } = useAuth();
  const query = useResource(resource, { caseId });
  const base = session ? `/${session.role.toLowerCase()}/cases` : '';

  return (
    <section>
      <h1 className="mb-6 font-serif text-3xl">{title}</h1>
      {before && caseId && before(caseId)}
      <QueryView query={query} empty={empty} loadingLabel={loadingLabel}>
        {(data) =>
          Array.isArray(data) ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {(data as AnyRecord[]).map((rec, i) => {
                const id = resource === 'cases' && caseIdField ? String(rec[caseIdField] ?? '') : '';
                return id ? (
                  <Link key={id} to={`${base}/${encodeURIComponent(id)}`} className="block rounded-lg focus-visible:ring-2">
                    <RecordCard record={rec} />
                  </Link>
                ) : <RecordCard key={i} record={rec} />;
              })}
            </div>
          ) : typeof data === 'object' && data !== null ? (
            <RecordCard record={data as AnyRecord} />
          ) : (
            <p>{String(data)}</p>
          )
        }
      </QueryView>
    </section>
  );
}
