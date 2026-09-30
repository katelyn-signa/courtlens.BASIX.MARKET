import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../services/AuthContext';
import { LoadingState } from '../components/States';
import type { Role } from '../types';

export function ProtectedRoute({ role, children }: { role: Role; children: ReactNode }) {
  const { session, loading } = useAuth();
  if (loading) return <LoadingState label="Checking your session…" />;
  if (!session) return <Navigate to="/login" replace />;
  if (session.role !== role) return <Navigate to={`/${session.role.toLowerCase()}/dashboard`} replace />;
  return <>{children}</>;
}
