import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from '@/components/Layout';
import { RequireAuth } from '@/components/RequireAuth';
import { AuthProvider } from '@/lib/auth-context';
import { ThemeProvider } from '@/lib/theme';
import { AuditPage } from '@/pages/Audit';
import { ClientsPage } from '@/pages/Clients';
import { ConsultantsPage } from '@/pages/Consultants';
import { DashboardPage } from '@/pages/Dashboard';
import { LoginPage } from '@/pages/Login';
import { PoliciesPage } from '@/pages/Policies';
import { SystemPage } from '@/pages/System';

export function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<DashboardPage />} />
              <Route path="clients" element={<ClientsPage />} />
              <Route path="consultants" element={<ConsultantsPage />} />
              <Route path="policies" element={<PoliciesPage />} />
              <Route path="audit" element={<AuditPage />} />
              <Route path="system" element={<SystemPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
