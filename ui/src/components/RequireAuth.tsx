import { type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '@/lib/auth-context';

export function RequireAuth({ children }: { children: ReactNode }) {
  const { email, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return <div className="container py-16 text-center text-muted-foreground">Loading…</div>;
  }
  if (!email) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <>{children}</>;
}
