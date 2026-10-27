import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from '@/auth';
import { AppShell } from '@/components/AppShell';
import { LoginPage } from '@/pages/LoginPage';
import { OverviewPage } from '@/pages/OverviewPage';
import { ImportPage } from '@/pages/ImportPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { BankPage } from '@/pages/BankPage';
import { PracticePage } from '@/pages/PracticePage';
import { ExamPage } from '@/pages/ExamPage';

function RequireAuth() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-canvas">
        <span className="text-[13px] text-ink-faint">载入中</span>
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  return <AppShell />;
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/bank" element={<BankPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/practice" element={<PracticePage />} />
            <Route path="/exam" element={<ExamPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
