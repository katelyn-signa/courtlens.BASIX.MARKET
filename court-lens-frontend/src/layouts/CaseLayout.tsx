import { NavLink, Outlet } from 'react-router-dom';
import type { Role } from '../types';

const tabs: Record<Role, { to: string; label: string; end?: boolean }[]> = {
  LAWYER: [
    { to: '', label: 'Overview', end: true },
    { to: 'evidence', label: 'Evidence' },
    { to: 'conflicts', label: 'Conflicts' },
    { to: 'missing-evidence', label: 'Missing evidence' },
    { to: 'reasoning', label: 'Reasoning' },
    { to: 'timeline', label: 'Timeline' },
    { to: 'evolution', label: 'Case evolution' }
  ],
  GUARDIAN: [
    { to: '', label: 'Overview', end: true },
    { to: 'status', label: 'Status' },
    { to: 'timeline', label: 'Timeline' }
  ]
};

export function CaseLayout({ role }: { role: Role }) {
  return (
    <div>
      <nav aria-label="Case sections" className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
        {tabs[role].map((t) => (
          <NavLink key={t.label} to={t.to} end={t.end}
            className={({ isActive }) => `whitespace-nowrap border-b-2 px-3 py-2 text-sm ${isActive ? 'border-ink font-semibold' : 'border-transparent text-charcoal'}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
