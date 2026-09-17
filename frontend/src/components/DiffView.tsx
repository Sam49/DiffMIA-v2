import { Fragment } from "react";
import { ClassificationBadge, StatusBadge } from "./ui";
import type { Analysis, ClassificationValue, ExperimentStatusValue } from "../types";

interface DiffViewProps {
  originalCode: string;
  mutatedCode: string;
  mapping: Record<string, string>;
  mutationIndex: number;
  seed: number;
  validationStatus: string;
  validationScore: number;
}

const TOKEN_RE = /(\s+|[A-Za-z_$][A-Za-z0-9_$]*|[^\sA-Za-z0-9_$])/g;

function HighlightedCode({ code, highlighted, tone }: { code: string; highlighted: Set<string>; tone: "old" | "new"; }) {
  const parts = code.split(TOKEN_RE).filter((part) => part !== undefined && part !== "");
  return (
    <pre className="mono overflow-x-auto whitespace-pre p-3 text-[12px] leading-5 text-slate-200">
      {parts.map((part, index) =>
        highlighted.has(part) ? (
          <span key={index} className={tone === "old" ? "diff-old" : "diff-new"}>
            {part}
          </span>
        ) : (
          <Fragment key={index}>{part}</Fragment>
        )
      )}
    </pre>
  );
}

export default function DiffView({
  originalCode,
  mutatedCode,
  mapping,
  mutationIndex,
  seed,
  validationStatus,
  validationScore,
}: DiffViewProps) {
  const oldNames = new Set(Object.keys(mapping));
  const newNames = new Set(Object.values(mapping));
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          Mutation #{mutationIndex}
        </span>
        <span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          seed {seed}
        </span>
        {validationStatus === "VALID" ? (
          <StatusBadge status="COMPLETED" />
        ) : (
          <span className="status-cancelled">{validationStatus}</span>
        )}
        <span className="rounded-md bg-slate-100 px-2 py-1 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          validation score {validationScore.toFixed(2)}
        </span>
      </div>

      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs dark:border-slate-800 dark:bg-slate-900">
        <span className="font-semibold text-slate-500">identifier mapping</span>
        {Object.entries(mapping).length === 0 && <span className="text-slate-400">no identifiers renamed</span>}
        {Object.entries(mapping).map(([oldName, newName]) => (
          <span key={oldName} className="mono">
            <span className="diff-old">{oldName}</span>
            <span className="mx-1 text-slate-400">→</span>
            <span className="diff-new">{newName}</span>
          </span>
        ))}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="overflow-hidden rounded-lg border border-slate-700">
          <div className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:border-slate-800 dark:bg-slate-950">
            Original
          </div>
          <HighlightedCode code={originalCode} highlighted={oldNames} tone="old" />
        </div>
        <div className="overflow-hidden rounded-lg border border-slate-700">
          <div className="flex items-center justify-between border-b border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400 dark:border-slate-800 dark:bg-slate-950">
            Mutated
          </div>
          <HighlightedCode code={mutatedCode} highlighted={newNames} tone="new" />
        </div>
      </div>
    </div>
  );
}

export function MappingInfo({ mappingJson }: { mappingJson: string }) {
  let parsed: { mapping: Record<string, string>; seed: number; attempts?: number } | null = null;
  try {
    parsed = JSON.parse(mappingJson);
  } catch {
    parsed = null;
  }
  if (!parsed) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span className="mono inline-flex max-w-[320px] flex-wrap gap-x-2 gap-y-0.5 text-[11px]">
      {Object.entries(parsed.mapping).map(([oldName, newName]) => (
        <span key={oldName}>
          <span className="text-rose-400">{oldName}</span>→<span className="text-emerald-400">{newName}</span>
        </span>
      ))}
    </span>
  );
}

// Small color/status helpers reused across tables
export const CLASS_LABEL_COLOR: Record<ClassificationValue, string> = {
  NORMAL: "text-slate-500",
  LOW_EVIDENCE: "text-slate-400",
  ELEVATED: "text-amber-500",
  POSSIBLE_CONTAMINATION: "text-orange-500",
  HIGH_CONTAMINATION_SIGNAL: "text-rose-500",
};

export function StatusText({ status }: { status: ExperimentStatusValue }) {
  const map: Record<ExperimentStatusValue, string> = {
    QUEUED: "bg-amber-100 text-amber-800",
    RUNNING: "bg-sky-100 text-sky-800",
    COMPLETED: "bg-emerald-100 text-emerald-800",
    FAILED: "bg-rose-100 text-rose-800",
    CANCELLED: "bg-slate-200 text-slate-600",
  };
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${map[status]}`}>{status}</span>;
}

export { ClassificationBadge };
export type { Analysis };
