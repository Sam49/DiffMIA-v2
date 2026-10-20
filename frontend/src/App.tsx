import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import Layout from "./components/Layout";
import LandingPage from "./pages/LandingPage";
import OAuthCallbackPage from "./pages/OAuthCallbackPage";
import DashboardPage from "./pages/DashboardPage";
import ExperimentsPage from "./pages/ExperimentsPage";
import ExperimentDetailPage from "./pages/ExperimentDetailPage";
import ComparisonPage from "./pages/ComparisonPage";
import DatasetsPage from "./pages/DatasetsPage";
import ModelsPage from "./pages/ModelsPage";
import ResultsPage from "./pages/ResultsPage";
import ReportsPage from "./pages/ReportsPage";
import SettingsPage from "./pages/SettingsPage";
import UsersPage from "./pages/UsersPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import VerifyEmailPage from "./pages/VerifyEmailPage";

/** Shown while the startup session is being established, and when it fails. */
function SessionScreen({
  title,
  message,
  onRetry,
}: {
  title: string;
  message?: string | null;
  onRetry?: () => void;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-slate-200">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/60 p-8 text-center">
        <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-brand-700 font-bold text-white">
          𝓓
        </div>
        <h1 className="mt-4 text-lg font-bold text-white">{title}</h1>
        {message && <p className="mt-3 text-sm text-rose-400">{message}</p>}
        {onRetry && (
          <>
            <button onClick={onRetry} className="btn-primary mt-5">
              Try again
            </button>
            <p className="mt-4 text-xs leading-relaxed text-slate-500">
              DiffMIA opens without a login page, so the backend provides the session:
              set AUTO_LOGIN_ENABLED=true and point AUTO_LOGIN_USERNAME at an active,
              verified account.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready, startupError, startSession } = useAuth();
  if (user) return <>{children}</>;
  if (!ready) return <SessionScreen title="Starting DiffMIA…" />;
  return (
    <SessionScreen
      title="Could not start a session"
      message={startupError ?? "The server did not return a session."}
      onRetry={() => void startSession()}
    />
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/oauth/callback" element={<OAuthCallbackPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/experiments" element={<ExperimentsPage />} />
        <Route path="/experiments/:id" element={<ExperimentDetailPage />} />
        <Route path="/experiments/:id/compare" element={<ComparisonPage />} />
        <Route path="/datasets" element={<DatasetsPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/results" element={<ResultsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/users" element={<UsersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
