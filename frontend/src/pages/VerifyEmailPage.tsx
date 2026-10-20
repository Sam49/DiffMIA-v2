import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../services/api";

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setMessage("This page needs a verification token — use the link from your email.");
      return;
    }
    let cancelled = false;
    api
      .verifyEmail(token)
      .then(() => {
        if (!cancelled) setState("ok");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState("error");
        setMessage(err instanceof ApiError ? err.message : "Verification failed.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-4">
      <div className="w-full max-w-sm">
        <Link to="/" className="mb-6 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">𝓓</div>
          <span className="text-xl font-bold text-white">DiffMIA</span>
        </Link>
        <div className="card p-6 text-center dark:border-slate-800 dark:bg-slate-900">
          {state === "working" && (
            <>
              <div className="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
              <p className="mt-4 text-sm text-slate-400">Verifying your email…</p>
            </>
          )}
          {state === "ok" && (
            <>
              <div className="text-3xl">✅</div>
              <h1 className="mt-3 text-lg font-bold text-slate-900 dark:text-white">Email verified</h1>
              <p className="mt-1 text-xs text-slate-500">Your account is active.</p>
              <Link to="/dashboard" className="btn-primary mt-5 block w-full !py-2.5 text-center">
                Continue to DiffMIA
              </Link>
            </>
          )}
          {state === "error" && (
            <>
              <div className="text-3xl">⚠️</div>
              <h1 className="mt-3 text-lg font-bold text-slate-900 dark:text-white">Verification failed</h1>
              <p className="mt-1 text-xs text-slate-500">{message}</p>
              <div className="mt-5 flex gap-2">
                <Link to="/dashboard" className="btn-ghost flex-1 !py-2.5 text-center">
                  Continue to DiffMIA
                </Link>
                <Link to="/forgot-password" className="btn-primary flex-1 !py-2.5 text-center">
                  Resend link
                </Link>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
