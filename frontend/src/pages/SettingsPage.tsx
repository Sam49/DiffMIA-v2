import { useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "../components/ui";
import { api, ApiError } from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { useFetch } from "../hooks/useFetch";

const GOOGLE_ERROR_TEXT: Record<string, string> = {
  GOOGLE_ALREADY_LINKED: "That Google account is already linked to another DiffMIA account.",
  GOOGLE_LINK_CONFLICT: "This account is already linked to a different Google account.",
  OAUTH_CANCELLED: "Google linking was cancelled or was denied.",
  OAUTH_STATE_INVALID:
    "This linking attempt expired, was already used, or was started in another browser session.",
  OAUTH_TOKEN_EXCHANGE: "Google refused the linking while exchanging the authorization code.",
  OAUTH_FAILED: "Google could not be linked. Please try again.",
  OAUTH_NOT_CONFIGURED: "Google sign-in is not configured on this server.",
};

/** Longest server-supplied detail we will render verbatim. */
const MAX_GOOGLE_DETAIL = 400;

export default function SettingsPage() {
  const { user, refreshUser } = useAuth();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [googleError, setGoogleError] = useState<string | null>(null);

  const oauth = useFetch(() => api.oauthStatus(), []);
  const googleEnabled = oauth.data?.google_enabled ?? false;
  const googleLinked = user?.google_linked ?? false;

  // The OAuth callback returns here: a success fragment or an error query.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("google_error");
    const linked = window.location.hash.includes("google=linked");
    if (linked) {
      setMessage("Google account linked.");
      void refreshUser().catch(() => undefined);
    }
    if (code) {
      // Prefer the backend's specific reason (same trust rules as the login page):
      // only for codes we recognise, and only up to a bounded length.
      const known = GOOGLE_ERROR_TEXT[code];
      const detail = (params.get("message") ?? "").trim();
      setGoogleError(
        known && detail && detail.length <= MAX_GOOGLE_DETAIL
          ? detail
          : (known ?? "Google linking failed."),
      );
    }
    if (code || linked) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, [refreshUser]);

  const changePassword = async (event: FormEvent) => {
    event.preventDefault();
    setMessage(null);
    setError(null);
    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (newPassword !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(oldPassword, newPassword);
      setMessage("Password updated.");
      setOldPassword("");
      setNewPassword("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change password.");
    } finally {
      setBusy(false);
    }
  };

  const linkGoogle = async () => {
    setMessage(null);
    setGoogleError(null);
    setGoogleBusy(true);
    try {
      const { authorize_url } = await api.googleLinkStart();
      // Full-page navigation to Google's consent screen; the server binds this
      // account into the signed state, so no token travels in the URL.
      window.location.href = authorize_url;
    } catch (err) {
      setGoogleError(err instanceof ApiError ? err.message : "Could not start Google linking.");
      setGoogleBusy(false);
    }
  };

  const unlinkGoogle = async () => {
    setMessage(null);
    setGoogleError(null);
    setGoogleBusy(true);
    try {
      await api.googleUnlink();
      await refreshUser();
      setMessage("Google account unlinked.");
    } catch (err) {
      setGoogleError(err instanceof ApiError ? err.message : "Could not unlink Google.");
    } finally {
      setGoogleBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader title="Settings" subtitle="Account, appearance and system access." />
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card">
          <div className="card-header">Account</div>
          <div className="space-y-3 px-5 py-4 text-sm">
            <div className="flex justify-between"><span className="text-slate-400">Username</span><span className="font-medium">{user?.username}</span></div>
            <div className="flex justify-between"><span className="text-slate-400">Email</span><span>{user?.email || "—"}</span></div>
            <div className="flex justify-between"><span className="text-slate-400">Role</span><span className="badge bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300">{user?.role}</span></div>
            <div className="flex justify-between"><span className="text-slate-400">Email verified</span><span>{user?.email_verified ? "Yes" : "No"}</span></div>
          </div>
        </div>
        <div className="card">
          <div className="card-header">Connected accounts</div>
          <div className="space-y-3 px-5 py-4 text-sm">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-medium">Google</div>
                <p className="mt-0.5 text-xs text-slate-500">
                  {googleLinked
                    ? "Linked — you can sign in with Google as well as your password."
                    : "Not linked. Linking lets you sign in with Google; your password keeps working."}
                </p>
              </div>
              {googleLinked ? (
                <button className="btn-ghost" onClick={unlinkGoogle} disabled={googleBusy}>
                  {googleBusy ? "Unlinking…" : "Unlink"}
                </button>
              ) : (
                <button
                  className="btn-primary whitespace-nowrap"
                  onClick={linkGoogle}
                  disabled={googleBusy || !googleEnabled}
                  title={googleEnabled ? undefined : "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable."}
                >
                  {googleBusy ? "Redirecting…" : "Link Google account"}
                </button>
              )}
            </div>
            {!googleEnabled && !oauth.loading && (
              <p className="text-xs text-slate-500">
                Google sign-in is switched off on this server. Set{" "}
                <code className="mono">GOOGLE_CLIENT_ID</code> and{" "}
                <code className="mono">GOOGLE_CLIENT_SECRET</code> to enable it.
              </p>
            )}
            {googleError && (
              <p className="break-words rounded-lg bg-rose-950 px-3 py-2 text-xs leading-relaxed text-rose-300">
                {googleError}
              </p>
            )}
          </div>
        </div>
        <div className="card md:col-span-2">
          <div className="card-header">Change password</div>
          <form onSubmit={changePassword} className="space-y-3 px-5 py-4">
            <input type="password" className="input" placeholder="Current password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} required />
            <input type="password" className="input" placeholder="New password (≥ 6 chars)" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required />
            <input type="password" className="input" placeholder="Confirm new password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            {message && <p className="rounded-lg bg-emerald-950 px-3 py-2 text-xs text-emerald-300">{message}</p>}
            {error && <p className="rounded-lg bg-rose-950 px-3 py-2 text-xs text-rose-300">{error}</p>}
            <button className="btn-primary" disabled={busy}>{busy ? "Updating…" : "Update password"}</button>
          </form>
        </div>
      </div>
      <div className="card px-5 py-4 text-xs leading-relaxed text-slate-500">
        <b>Access &amp; science.</b> Passwords are stored with PBKDF2-HMAC-SHA256; sessions use signed HS256 JWT
        tokens with role-based authorization (ADMIN / RESEARCHER / VIEWER). Contamination scores are behavioural
        signals, not proof of training-data membership — see the README's research-limitations section for details.
        API documentation is served by FastAPI at <code className="mono">/docs</code> and{" "}
        <code className="mono">/openapi.json</code>.
      </div>
    </div>
  );
}
