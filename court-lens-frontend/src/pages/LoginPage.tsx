import { Navigate, useNavigate } from 'react-router-dom';
import { Gavel, Scale, Users } from 'lucide-react';
import { useAuth } from '../services/AuthContext';
import type { Role } from '../types';

const roles: { id: Role; title: string; blurb: string; icon: typeof Gavel }[] = [
  { id: 'LAWYER', title: 'Lawyer', blurb: 'Investigate cases, review evidence and reasoning.', icon: Gavel },
  { id: 'GUARDIAN', title: 'Guardian / Relative', blurb: 'Follow the status of a case you are involved in.', icon: Users }
];

export function LoginPage() {
  const { session, login } = useAuth();
  const nav = useNavigate();

  if (session) return <Navigate to={`/${session.role.toLowerCase()}/dashboard`} replace />;

  function selectRole(role: Role) {
    void login(role, {}).then((s) => {
      nav(`/${s.role.toLowerCase()}/dashboard`, { replace: true });
    });
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center p-6">
      <div className="mb-8 flex items-center gap-3 font-serif text-4xl"><Scale className="h-8 w-8" aria-hidden /> CourtLens</div>
      <p className="mb-8 max-w-prose text-charcoal">Evidence intelligence for legal case investigation. Choose how you are signing in.</p>

      <div role="radiogroup" aria-label="Sign in as" className="mb-8 grid gap-4 sm:grid-cols-2">
        {roles.map((r) => (
          <button key={r.id} type="button" role="radio" onClick={() => selectRole(r.id)}
            className="rounded-lg border border-line bg-white p-5 text-left hover:border-charcoal">
            <r.icon className="mb-3 h-6 w-6" aria-hidden />
            <div className="font-semibold">{r.title}</div>
            <div className="text-sm text-charcoal">{r.blurb}</div>
          </button>
        ))}
      </div>
    </div>
  );
}
