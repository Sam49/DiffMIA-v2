import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../services/api";

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Reset failed.");
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <Shell>
        <p className="rounded-lg bg-rose-950 px-3 py-2 text-xs text-rose-300">
          This page needs a reset token — use the link from your email.
        </p>
        <Link to="/forgot-password" className="btn-primary mt-4 block w-full !py-2.5 text-center">
          Request a new link
        </Link>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell>
        <p className="rounded-lg bg-emerald-950 px-3 py-2 text-xs text-emerald-300">
          Password updated. You can now sign in with your new password.
        </p>
        <button className="btn-primary mt-4 w-full !py-2.5" onClick={() => navigate("/login")}>
          Go to sign in
        </button>
      </Shell>
    );
  }

  return (
    <Shell>
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">New password</span>
          <input
            type="password"
            autoFocus
            required
            minLength={8}
            className="input"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            placeholder="At least 8 characters"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-slate-500">Confirm new password</span>
          <input
            type="password"
            required
            className="input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </label>
        {error && <p className="rounded-lg bg-rose-950 px-3 py-2 text-xs text-rose-300">{error}</p>}
        <button className="btn-primary w-full !py-2.5" disabled={busy}>
          {busy ? "Updating…" : "Set new password"}
        </button>
      </form>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">𝓓</div>
          <span className="text-xl font-bold text-white">DiffMIA</span>
        </Link>
        <div className="card p-6 dark:border-slate-800 dark:bg-slate-900">
          <h1 className="text-lg font-bold text-slate-900 dark:text-white">Choose a new password</h1>
          <p className="mb-5 mt-1 text-xs text-slate-500">Reset links are single-use and expire after one hour.</p>
          {children}
        </div>
      </div>
    </div>
  );
}
