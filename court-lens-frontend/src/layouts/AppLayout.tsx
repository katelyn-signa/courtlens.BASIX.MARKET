import { NavLink, Outlet } from 'react-router-dom';
import { Bell, Briefcase, FileText, LayoutDashboard, LogOut, Scale, type LucideIcon } from 'lucide-react';
import { useAuth } from '../services/AuthContext';
import type { Role } from '../types';

interface Item { to: string; label: string; icon: LucideIcon }

const nav: Record<Role, Item[]> = {
  LAWYER: [
    { to: '/lawyer/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/lawyer/cases', label: 'My cases', icon: Briefcase },
    { to: '/lawyer/notifications', label: 'Notifications', icon: Bell }
  ],
  GUARDIAN: [
    { to: '/guardian/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/guardian/cases', label: 'Cases', icon: Briefcase },
    { to: '/guardian/documents', label: 'Documents', icon: FileText },
    { to: '/guardian/notifications', label: 'Notifications', icon: Bell }
  ]
};

const link = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-3 rounded-md px-3 py-2 text-sm ${isActive ? 'bg-ink text-white' : 'text-charcoal hover:bg-line'}`;

export function AppLayout({ role }: { role: Role }) {
  const { logout } = useAuth();
  const items = nav[role];
  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-white p-4 md:flex">
        <div className="mb-6 flex items-center gap-2 font-serif text-xl"><Scale className="h-5 w-5" aria-hidden /> CourtLens</div>
        <nav aria-label="Main" className="flex flex-1 flex-col gap-1">
          {items.map((i) => <NavLink key={i.to} to={i.to} className={link}><i.icon className="h-4 w-4" aria-hidden />{i.label}</NavLink>)}
        </nav>
        <button onClick={() => void logout()} className="flex items-center gap-3 px-3 py-2 text-sm text-charcoal"><LogOut className="h-4 w-4" aria-hidden />Sign out</button>
      </aside>
      <main className="flex-1 p-5 pb-24 md:p-10 md:pb-10"><Outlet /></main>
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-10 flex justify-around border-t border-line bg-white p-2 md:hidden">
        {items.map((i) => (
          <NavLink key={i.to} to={i.to} className={({ isActive }) => `flex flex-col items-center gap-1 px-3 py-1 text-xs ${isActive ? 'font-semibold text-ink' : 'text-charcoal'}`}>
            <i.icon className="h-5 w-5" aria-hidden />{i.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
