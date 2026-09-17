import type { Conclusion } from "../types";

const VERDICT_STYLES: Record<string, { ring: string; text: string; label: string }> = {
  STRONG_DIFFERENTIAL_SIGNAL: {
    ring: "border-rose-300 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40",
    text: "text-rose-800 dark:text-rose-200",
    label: "Strong differential signal",
  },
  ELEVATED_DIFFERENTIAL_SIGNAL: {
    ring: "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
    text: "text-amber-900 dark:text-amber-200",
    label: "Elevated differential signal",
  },
  NO_MATERIAL_SIGNAL: {
    ring: "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900",
    text: "text-slate-700 dark:text-slate-200",
    label: "No material signal",
  },
  NO_DATA: {
    ring: "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900",
    text: "text-slate-500 dark:text-slate-400",
    label: "No data",
  },
};

/**
 * The experiment's conclusion: what the numbers say, how strong the evidence
 * is, what it cannot show, and how to corroborate it. Kept deliberately
 * separate from the raw tables so a reader sees the verdict first.
 */
export function ConclusionCard({ conclusion }: { conclusion?: Conclusion }) {
  if (!conclusion) return null;
  const style =
    VERDICT_STYLES[conclusion.verdict] ?? VERDICT_STYLES.NO_MATERIAL_SIGNAL;

  return (
    <div className={`rounded-xl border px-5 py-4 ${style.ring}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            Conclusion
          </span>
          <span className={`text-sm font-bold ${style.text}`}>{style.label}</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-slate-500 dark:text-slate-400">
          <span>evidence: {conclusion.evidence_level}</span>
          <span className="tabular-nums">
            flagged {(conclusion.flagged_share * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      <p className="mt-2 text-sm leading-relaxed text-slate-700 dark:text-slate-200">
        {conclusion.headline}
      </p>

      <div className="mt-3 grid gap-4 md:grid-cols-3">
        <Section title="Observed" items={conclusion.observations} />
        <Section title="What this cannot show" items={conclusion.caveats} />
        <Section title="To corroborate or falsify" items={conclusion.corroboration} />
      </div>
    </div>
  );
}

function Section({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{title}</div>
      <ul className="mt-1 space-y-1 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">
        {(items ?? []).map((item, index) => (
          <li key={index} className="flex gap-1.5">
            <span className="text-slate-400">•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default ConclusionCard;
