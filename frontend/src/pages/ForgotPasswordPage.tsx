import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../services/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await api.forgotPassword(email.trim());
      setSent(true);
      setDevToken(response.development_token ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">𝓓</div>
          <span className="text-xl font-bold text-white">DiffMIA</span>
        </Link>
        <div className="card p-6 dark:border-slate-800 dark:bg-slate-900">
          <h1 className="text-lg font-bold text-slate-900 dark:text-white">Reset your password</h1>
          <p className="mb-5 mt-1 text-xs text-slate-500">
            Enter your account email and we'll send you a reset link.
          </p>

          {sent ? (
            <div className="space-y-4">
              <p className="rounded-lg bg-emerald-950 px-3 py-2 text-xs text-emerald-300">
                If an account exists for that address, a reset link is on its way.
              </p>
              {devToken && (
                <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
                  <b>Developer mode:</b> no SMTP server is configured, so here is the link directly:
                  <Link to={`/reset-password?token=${encodeURIComponent(devToken)}`} className="mt-2 block break-all font-medium underline">
                    Open reset page →
                  </Link>
                </div>
              )}
              <Link to="/login" className="btn-primary block w-full !py-2.5 text-center">
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-500">Email</span>
                <input
                  type="email"
                  autoFocus
                  required
                  className="input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  placeholder="you@example.com"
                />
              </label>
              {error && <p className="rounded-lg bg-rose-950 px-3 py-2 text-xs text-rose-300">{error}</p>}
              <button className="btn-primary w-full !py-2.5" disabled={busy}>
                {busy ? "Sending…" : "Send reset link"}
              </button>
              <p className="text-center text-xs text-slate-500">
                <Link to="/login" className="underline hover:text-slate-300">
                  Back to sign in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
