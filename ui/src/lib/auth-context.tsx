import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { Auth, clearTokens, getAccessToken, setTokens } from './api';

interface AuthState {
  email: string | null;
  role: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setLoading(false);
      return;
    }
    Auth.me()
      .then((me) => {
        setEmail(me.email);
        setRole(me.role);
      })
      .catch(() => {
        clearTokens();
      })
      .finally(() => setLoading(false));
  }, []);

  const login = async (eml: string, pwd: string) => {
    const tok = await Auth.login(eml, pwd);
    setTokens(tok.access_token, tok.refresh_token);
    const me = await Auth.me();
    setEmail(me.email);
    setRole(me.role);
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
