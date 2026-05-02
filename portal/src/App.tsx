import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ConsumePage } from '@/pages/Consume';
import { DashboardPage } from '@/pages/Dashboard';
import { LoginPage } from '@/pages/Login';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/consume" element={<ConsumePage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
