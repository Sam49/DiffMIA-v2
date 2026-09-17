import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { ApiError } from "../services/api";

/**
 * Landing target for the Google OAuth redirect. The backend sends the
 * one-time handoff token in the URL fragment (#token=...), which browsers
 * never transmit to servers. We swap it for a normal session immediately
 * and strip it from the address bar.
 */
export default function OAuthCallbackPage() {
  const { loginWithGoogleToken } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const attempted = useRef(false);

  useEffect(() => {
    if (attempted.current) return; // React 18 StrictMode double-invoke guard
    attempted.current = true;

    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const token = fragment.get("token");
    if (!token) {
      setError("No sign-in token was received. Please restart the Google sign-in.");
      return;
    }
    loginWithGoogleToken(token)
      .then(() => {
        // Remove the fragment from history/address bar.
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        navigate("/dashboard", { replace: true });
      })
      .catch((err) => {
        setError(
          err instanceof ApiError
            ? `Sign-in failed: ${err.message}`
            : "Sign-in failed. Please try again.",
        );
      });
  }, [loginWithGoogleToken, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm text-center">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">𝓓</div>
          <span className="text-xl font-bold text-white">DiffMIA</span>
        </Link>
        <div className="card p-8 dark:border-slate-800 dark:bg-slate-900">
          {error ? (
            <>
              <p className="mb-3 text-sm font-semibold text-rose-300">Google sign-in failed</p>
              <p className="mb-5 text-xs text-slate-400">{error}</p>
              <Link to="/login" className="btn-primary inline-block w-full !py-2.5 text-center">
                Back to sign in
              </Link>
            </>
          ) : (
            <>
              <div className="mx-auto mb-4 h-6 w-6 animate-spin rounded-full border-2 border-slate-600 border-t-brand-500" />
              <p className="text-sm text-slate-300">Completing Google sign-in…</p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
