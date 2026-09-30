import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Gavel, Scale, Users } from 'lucide-react';
import { useAuth } from '../services/AuthContext';
import { authFields } from '../api/endpoints';
import { classifyError } from '../api/errors';
import type { Role } from '../types';

const roles: { id: Role; title: string; blurb: string; icon: typeof Gavel }[] = [
  { id: 'LAWYER', title: 'Lawyer', blurb: 'Investigate cases, review evidence and reasoning.', icon: Gavel },
  { id: 'GUARDIAN', title: 'Guardian / Relative', blurb: 'Follow the status of a case you are involved in.', icon: Users }
];

export function LoginPage() {
  const { session, login } = useAuth();
  const nav = useNavigate();
  const [role, setRole] = useState<Role | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (session) return <Navigate to={`/${session.role.toLowerCase()}/dashboard`} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!role) return;
    setBusy(true); setError(null);
    try {
      const s = await login(role, values);
      nav(`/${s.role.toLowerCase()}/dashboard`, { replace: true }); // role comes from the backend
    } catch (err) {
      const k = classifyError(err);
      setError(k === 'not_configured' ? 'Sign-in is waiting for the backend authentication contract (src/api/auth.ts).'
        : k === 'network' ? 'Unable to connect to CourtLens server.'
        : 'Sign-in failed. Check your details and try again.');
    } finally { setBusy(false); }
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center p-6">
      <div className="mb-8 flex items-center gap-3 font-serif text-4xl"><Scale className="h-8 w-8" aria-hidden /> CourtLens</div>
      <p className="mb-8 max-w-prose text-charcoal">Evidence intelligence for legal case investigation. Choose how you are signing in.</p>

      <div role="radiogroup" aria-label="Sign in as" className="mb-8 grid gap-4 sm:grid-cols-2">
        {roles.map((r) => (
          <button key={r.id} type="button" role="radio" aria-checked={role === r.id} onClick={() => setRole(r.id)}
            className={`rounded-lg border p-5 text-left ${role === r.id ? 'border-ink bg-ink text-white' : 'border-line bg-white hover:border-charcoal'}`}>
            <r.icon className="mb-3 h-6 w-6" aria-hidden />
            <div className="font-semibold">{r.title}</div>
            <div className={`text-sm ${role === r.id ? 'text-white/80' : 'text-charcoal'}`}>{r.blurb}</div>
          </button>
        ))}
      </div>

      {role && (
        <form onSubmit={(e) => void submit(e)} className="grid gap-4 rounded-lg border border-line bg-white p-6">
          {authFields.length === 0 && <p className="text-sm text-charcoal">Login fields are not defined yet. Set them in src/api/endpoints.ts once the backend contract is available.</p>}
          {authFields.map((f) => (
            <label key={f.name} className="grid gap-1 text-sm">
              {f.label}
              <input required type={f.type} value={values[f.name] ?? ''} autoComplete="off"
                onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))}
                className="rounded-md border border-line px-3 py-2" />
            </label>
          ))}
          {error && <p role="alert" className="text-sm text-conflict">{error}</p>}
          <button disabled={busy} className="rounded-md bg-ink px-4 py-2 text-white disabled:opacity-50">{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>
      )}
    </div>
  );
}
