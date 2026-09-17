import type { ReactNode } from "react";
import type { ClassificationValue, ExperimentStatusValue } from "../types";

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
      {label}
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
      <div className="font-medium">Request failed</div>
      <div className="mt-1 opacity-90">{message}</div>
      {onRetry && (
        <button onClick={onRetry} className="btn-danger mt-2 !py-1 text-xs">
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="card flex flex-col items-center gap-3 px-6 py-14 text-center">
      <div className="text-3xl">🔬</div>
      <div className="text-sm font-semibold">{title}</div>
      {hint && <div className="max-w-md text-xs text-slate-500">{hint}</div>}
      {action}
    </div>
  );
}

export function StatCard({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: string; accent?: string }) {
  return (
    <div className="card px-4 py-3.5">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${accent ?? "text-slate-900 dark:text-white"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-slate-400">{sub}</div>}
    </div>
  );
}

export function ProgressBar({ value, max, label }: { value: number; max: number; label?: string }) {
  const percent = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div>
      {label && <div className="mb-1 text-xs text-slate-500">{label}</div>}
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
        <div
          className="h-full rounded-full bg-brand-600 transition-all"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

const STATUS_STYLE: Record<ExperimentStatusValue, string> = {
  QUEUED: "status-queued",
  RUNNING: "status-running",
  COMPLETED: "status-completed",
  FAILED: "status-failed",
  CANCELLED: "status-cancelled",
};

export function StatusBadge({ status }: { status: ExperimentStatusValue }) {
  return <span className={STATUS_STYLE[status] ?? "badge"}>{status}</span>;
}

const CLASS_STYLE: Record<ClassificationValue, string> = {
  NORMAL: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  LOW_EVIDENCE: "bg-slate-200 text-slate-500 dark:bg-slate-700 dark:text-slate-300",
  ELEVATED: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  POSSIBLE_CONTAMINATION: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
  HIGH_CONTAMINATION_SIGNAL: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
};

export function ClassificationBadge({ value }: { value: ClassificationValue }) {
  const cls = value === "POSSIBLE_CONTAMINATION" || value === "HIGH_CONTAMINATION_SIGNAL";
  return (
    <span className={`badge ${CLASS_STYLE[value] ?? "badge"}`} title={cls ? "behavioral signal, not provenance" : undefined}>
      {value}
    </span>
  );
}

export function Disclaimer() {
  return (
    <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-900 dark:border-amber-900/60 dark:bg-amber-950 dark:text-amber-200">
      <b>Important:</b> contamination scores indicate behavioral evidence consistent with memorization. They do
      not establish the provenance of training data. Identifier familiarity, tokenization effects and code-style
      priors can produce the same differential pattern.
    </div>
  );
}

export function Modal({ open, onClose, title, children, wide }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/50 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className={`card mt-8 w-full ${wide ? "max-w-4xl" : "max-w-xl"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-3 dark:border-slate-800">
          <div className="text-sm font-semibold">{title}</div>
          <button onClick={onClose} className="btn-ghost !px-2">✕</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-white">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-500">{label}</span>
      {children}
    </label>
  );
}
