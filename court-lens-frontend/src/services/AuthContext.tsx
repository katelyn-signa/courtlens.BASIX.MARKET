import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Role, Session } from '../types';

/** Hackathon demo only — replace with real auth when the backend is ready. */
const DEMO_SESSION_KEY = 'courtlens_demo_session';

interface DemoStoredSession {
  role: Role;
  name: string;
}

function readDemoSession(): Session | null {
  try {
    const raw = localStorage.getItem(DEMO_SESSION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DemoStoredSession;
    if (parsed.role !== 'LAWYER' && parsed.role !== 'GUARDIAN') return null;
    return { role: parsed.role, displayName: parsed.name };
  } catch {
    return null;
  }
}

function writeDemoSession(role: Role): Session {
  const stored: DemoStoredSession = { role, name: 'Demo User' };
  localStorage.setItem(DEMO_SESSION_KEY, JSON.stringify(stored));
  return { role, displayName: 'Demo User' };
}

function clearDemoSession(): void {
  localStorage.removeItem(DEMO_SESSION_KEY);
}

interface AuthValue {
  session: Session | null;
  loading: boolean;
  login: (role: Role, creds: Record<string, string>) => Promise<Session>;
  logout: () => Promise<void>;
}
const Ctx = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setSession(readDemoSession());
    setLoading(false);
  }, []);

  const login = useCallback(async (role: Role, _creds: Record<string, string>) => {
    void _creds;
    const s = writeDemoSession(role);
    setSession(s);
    return s;
  }, []);
  const logout = useCallback(async () => {
    clearDemoSession();
    setSession(null);
  }, []);

  const value = useMemo(() => ({ session, loading, login, logout }), [session, loading, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth must be used inside AuthProvider');
  return v;
}
