import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { Auth, clearTokens, getAccessToken, setTokens } from './api';
import { isDemo } from './demo';

interface AuthState {
  email: string | null;
  role: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

interface JwtPayload {
  sub?: string;
  role?: string;
  exp?: number;
}

/**
 * Decodifica o JWT no cliente — não temos endpoint `/auth/me` no core ainda
 * (rota não foi implementada na Fase 8), então ler o `sub` do access token é
 * suficiente para popular o contexto. Validação de assinatura fica a cargo do
 * backend nas chamadas autenticadas.
 */
function decodeJwt(token: string): JwtPayload | null {
  try {
    const [, payload] = token.split('.');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}

function userFromToken(token: string | null): { email: string | null; role: string | null } {
  if (!token) return { email: null, role: null };
  const claims = decodeJwt(token);
  if (!claims) return { email: null, role: null };
  if (claims.exp && claims.exp * 1000 < Date.now()) {
    return { email: null, role: null };
  }
  return { email: claims.sub ?? null, role: claims.role ?? 'admin' };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    const token = getAccessToken();
    if (token) {
      const u = userFromToken(token);
      setEmail(u.email);
      setRole(u.role);
    }
    // Em modo demo, finge sessão viva mesmo sem token salvo
    if (!token && isDemo()) {
      const me = { email: 'admin', role: 'admin' };
      setEmail(me.email);
      setRole(me.role);
    }
    setLoading(false);
  }, []);

  const login = async (eml: string, pwd: string) => {
    const tok = await Auth.login(eml, pwd);
    setTokens(tok.access_token, tok.refresh_token);
    const u = userFromToken(tok.access_token);
    setEmail(u.email ?? eml);
    setRole(u.role ?? 'admin');
  };

  const logout = () => {
    clearTokens();
    setEmail(null);
    setRole(null);
  };

  return (
    <AuthContext.Provider value={{ email, role, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>');
  }
  return ctx;
}
