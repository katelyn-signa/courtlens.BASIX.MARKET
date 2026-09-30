import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import * as authApi from '../api/auth';
import type { Role, Session } from '../types';

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
    authApi.fetchSession().then(setSession).catch(() => setSession(null)).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (role: Role, creds: Record<string, string>) => {
    const s = await authApi.login(role, creds);
    setSession(s);
    return s;
  }, []);
  const logout = useCallback(async () => {
    try { await authApi.logout(); } finally { setSession(null); }
  }, []);

  const value = useMemo(() => ({ session, loading, login, logout }), [session, loading, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth must be used inside AuthProvider');
  return v;
}
