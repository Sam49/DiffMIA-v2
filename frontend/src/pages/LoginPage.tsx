import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ApiError, api } from "../services/api";
import { Labeled } from "../components/ui";

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  OAUTH_NOT_CONFIGURED:
    "Google sign-in is not configured on this server. Set GOOGLE_CLIENT_ID and " +
    "GOOGLE_CLIENT_SECRET in the backend environment, then restart it.",
  OAUTH_CANCELLED: "Google sign-in was cancelled or was denied.",
  OAUTH_STATE_INVALID:
    "This sign-in attempt expired, was already used, or was started in another browser session.",
  OAUTH_TOKEN_EXCHANGE: "Google refused the sign-in while exchanging the authorization code.",
  OAUTH_ACCOUNT_DISABLED: "That account is disabled. Ask an administrator to re-enable it.",
  OAUTH_GOOGLE_ERROR: "Google returned an error instead of completing the sign-in.",
  OAUTH_INVALID_RESPONSE: "Google returned an unexpected response.",
  OAUTH_FAILED: "Google sign-in could not be completed.",
};

/** Longest server-supplied detail we will render verbatim. */
const MAX_OAUTH_DETAIL = 400;

const USERNAME_PATTERN = /^[A-Za-z0-9_.-]{3,64}$/;
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Official Google sign-in branding (multi-color G). */
function GoogleIcon() {
  return (
    <svg viewBox="0 0 48 48" className="h-4 w-4" aria-hidden="true">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

function tabClass(active: boolean): string {
  return [
    "rounded-md px-3 py-1.5 text-xs font-semibold transition",
    active
      ? "bg-white text-slate-900 shadow-sm dark:bg-slate-950 dark:text-white"
      : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200",
  ].join(" ");
}

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [selfRegistration, setSelfRegistration] = useState(false);

  // Sign-in fields
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");

  // Unverified-account recovery
  const [unverified, setUnverified] = useState(false);
  const [resendEmail, setResendEmail] = useState("");
  const [resendSent, setResendSent] = useState(false);
  const [resendDevToken, setResendDevToken] = useState<string | null>(null);
  const [resendBusy, setResendBusy] = useState(false);

  // Sign-up fields
  const [suUsername, setSuUsername] = useState("");
  const [suEmail, setSuEmail] = useState("");
  const [suPassword, setSuPassword] = useState("");
  const [suConfirm, setSuConfirm] = useState("");

  useEffect(() => {
    api
      .oauthStatus()
      .then((status) => {
        setGoogleEnabled(status.google_enabled);
        setSelfRegistration(status.self_registration);
      })
      .catch(() => {
        setGoogleEnabled(false);
        setSelfRegistration(false);
      });
  }, []);

  // Surface errors handed back from the OAuth callback redirect. The backend's
  // `message` carries the specific cause (which Google error code came back, which
  // redirect URI to register), so prefer it over the generic per-code text. It is
  // only trusted for codes we recognise and only up to a bounded length, so
  // arbitrary query text can never be rendered here.
  useEffect(() => {
    const oauthError = searchParams.get("oauth_error");
    if (!oauthError) return;
    const known = OAUTH_ERROR_MESSAGES[oauthError];
    const detail = (searchParams.get("message") ?? "").trim();
    setError(
      known && detail && detail.length <= MAX_OAUTH_DETAIL
        ? detail
        : (known ?? "Google sign-in failed."),
    );
    // Clean the query string so a refresh doesn't re-show the error.
    window.history.replaceState(null, "", "/login");
  }, [searchParams]);

  const switchMode = (next: "signin" | "signup") => {
    setMode(next);
    setError(null);
    setNotice(null);
  };

  const validateSignup = (): string | null => {
    if (!USERNAME_PATTERN.test(suUsername.trim())) {
      return "Username must be 3–64 characters (letters, numbers, dot, dash, underscore).";
    }
    if (!EMAIL_PATTERN.test(suEmail.trim())) {
      return "Enter a valid email address.";
    }
    if (suPassword.length < 8) {
      return "Password must be at least 8 characters.";
    }
    if (suPassword !== suConfirm) {
      return "Passwords do not match.";
    }
    return null;
  };

  const submitSignIn = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setUnverified(false);
    try {
      await login(username, password);
      navigate("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.code === "EMAIL_NOT_VERIFIED") {
        setUnverified(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Login failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  const resendVerification = async () => {
    setResendBusy(true);
    setError(null);
    try {
      const response = await api.resendVerificationEmail(resendEmail.trim());
      setResendSent(true);
      setResendDevToken(response.development_token ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not resend the email.");
    } finally {
      setResendBusy(false);
    }
  };

  const submitSignUp = async (event: FormEvent) => {
    event.preventDefault();
    const problem = validateSignup();
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await register(suUsername.trim(), suEmail.trim(), suPassword);
      if (result.verified) {
        navigate("/dashboard");
      } else {
        // Verification email is on its way — ask the user to confirm first.
        setMode("signin");
        setNotice("Account created. Check your email for a verification link, then sign in.");
        setSuUsername("");
        setSuEmail("");
        setSuPassword("");
        setSuConfirm("");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Registration failed.");
    } finally {
      setBusy(false);
    }
  };

  const startGoogleSignIn = () => {
    setError(null);
    if (!googleEnabled) {
      // The button stays visible either way; say what the server is missing
      // instead of hiding a supported sign-in method.
      setError(
        "Google sign-in is not configured on this server. Set GOOGLE_CLIENT_ID and " +
          "GOOGLE_CLIENT_SECRET in the backend environment, then restart it.",
      );
      return;
    }
    // Full navigation: the backend 302s to Google's consent screen.
    window.location.href = "/api/auth/google/authorize";
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">𝓓</div>
          <span className="text-xl font-bold text-white">DiffMIA</span>
        </Link>
        <div className="card p-6 dark:border-slate-800 dark:bg-slate-900">
          <h1 className="text-lg font-bold text-slate-900 dark:text-white">
            {mode === "signin" ? "Sign in" : "Create account"}
          </h1>
          <p className="mb-5 mt-1 text-xs text-slate-500">
            {mode === "signin"
              ? "Research dashboard for contamination detection."
              : "Register a research account to get started."}
          </p>

          {notice && (
            <p className="mb-4 rounded-lg bg-emerald-950 px-3 py-2 text-xs text-emerald-300">{notice}</p>
          )}

          <button
            type="button"
            onClick={startGoogleSignIn}
            title={
              googleEnabled
                ? "Sign in with your Google account"
                : "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to enable this"
            }
            className={`flex w-full items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700 ${
              googleEnabled ? "" : "opacity-60"
            }`}
          >
            <GoogleIcon />
            Continue with Google
          </button>
          <div className="my-5 flex items-center gap-3" aria-hidden="true">
            <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">or</span>
            <div className="h-px flex-1 bg-slate-200 dark:bg-slate-700" />
          </div>

          {selfRegistration && (
            <div className="mb-5 grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
              <button type="button" onClick={() => switchMode("signin")} className={tabClass(mode === "signin")}>
                Sign in
              </button>
              <button type="button" onClick={() => switchMode("signup")} className={tabClass(mode === "signup")}>
                Create account
              </button>
            </div>
          )}

          {mode === "signin" ? (
            <form onSubmit={submitSignIn} className="space-y-4">
              <Labeled label="Username">
                <input
                  autoFocus
                  className="input"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                />
              </Labeled>
              <Labeled label="Password">
                <input
                  type="password"
                  className="input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </Labeled>
              {error && (
                <p className="break-words rounded-lg bg-rose-950 px-3 py-2 text-xs leading-relaxed text-rose-300">
                  {error}
                </p>
              )}
              {unverified && !resendSent && (
                <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2.5 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
                  <b>Email not verified.</b> Enter your address to receive a new verification link.
                  <div className="mt-2 flex gap-2">
                    <input
                      type="email"
                      required
                      className="input !py-1.5 !text-xs"
                      placeholder="you@example.com"
                      value={resendEmail}
                      onChange={(e) => setResendEmail(e.target.value)}
                    />
                    <button type="button" className="btn-primary !py-1.5 !px-3 !text-xs" disabled={resendBusy || !resendEmail.includes("@")} onClick={() => void resendVerification()}>
                      {resendBusy ? "…" : "Resend"}
                    </button>
                  </div>
                </div>
              )}
              {unverified && resendSent && (
                <div className="rounded-lg bg-emerald-950 px-3 py-2 text-xs text-emerald-300">
                  Verification email sent{resendDevToken ? " — developer mode: check the backend log for the link" : ". Check your inbox."}
                </div>
              )}
              <button className="btn-primary w-full !py-2.5" disabled={busy}>
                {busy ? "Signing in…" : "Sign in"}
              </button>
              <p className="text-center text-xs text-slate-500">
                <Link to="/forgot-password" className="underline hover:text-slate-300">
                  Forgot your password?
                </Link>
              </p>
            </form>
          ) : (
            <form onSubmit={submitSignUp} className="space-y-4">
              <Labeled label="Username">
                <input
                  autoFocus
                  className="input"
                  value={suUsername}
                  onChange={(e) => setSuUsername(e.target.value)}
                  autoComplete="username"
                  placeholder="jane_doe"
                />
              </Labeled>
              <Labeled label="Email">
                <input
                  type="email"
                  className="input"
                  value={suEmail}
                  onChange={(e) => setSuEmail(e.target.value)}
                  autoComplete="email"
                  placeholder="jane@example.com"
                />
              </Labeled>
              <Labeled label="Password">
                <input
                  type="password"
                  className="input"
                  value={suPassword}
                  onChange={(e) => setSuPassword(e.target.value)}
                  autoComplete="new-password"
                  placeholder="At least 8 characters"
                />
              </Labeled>
              <Labeled label="Confirm password">
                <input
                  type="password"
                  className="input"
                  value={suConfirm}
                  onChange={(e) => setSuConfirm(e.target.value)}
                  autoComplete="new-password"
                />
              </Labeled>
              {error && (
                <p className="break-words rounded-lg bg-rose-950 px-3 py-2 text-xs leading-relaxed text-rose-300">
                  {error}
                </p>
              )}
              <button className="btn-primary w-full !py-2.5" disabled={busy}>
                {busy ? "Creating account…" : "Create account"}
              </button>
              <p className="text-center text-[11px] text-slate-500">
                We'll send a verification email to confirm your address before you can sign in.
              </p>
            </form>
          )}
        </div>
        <p className="mt-4 text-center text-xs text-slate-600">
          Roles: ADMIN · RESEARCHER · VIEWER — permissions enforced on every endpoint.
        </p>
      </div>
    </div>
  );
}
