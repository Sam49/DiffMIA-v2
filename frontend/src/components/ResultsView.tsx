import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fmt } from "../services/api";
import type { Analysis, ClassificationValue, ResultsBundle } from "../types";
import {
  ChartCard,
  ClassificationCounts,
  HistogramWithThreshold,
  KdeChart,
  LossScatter,
  SignalEffectScatter,
  SignalRankingChart,
  ZScoreChart,
} from "./charts";
import { ClassificationBadge, Disclaimer, StatCard } from "./ui";
import ConclusionCard from "./ConclusionCard";

const ORIGINAL_COLOR = "#0ea5e9";
const MUTATION_COLOR = "#f59e0b";

function AnalysisRow({ row, experimentId, open, onToggle }: {
  row: Analysis;
  experimentId: number;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr
        onClick={onToggle}
        className={`cursor-pointer border-t border-slate-100 text-sm hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900 ${
          row.flagged ? "bg-rose-50/40 dark:bg-rose-950/20" : ""
        }`}
      >
        <td className="max-w-[150px] truncate px-3 py-2 font-mono text-xs">{row.external_id}</td>
        <td className="px-3 py-2 tabular-nums">{fmt(row.original_loss)}</td>
        <td className="px-3 py-2 tabular-nums">{fmt(row.mean_mutation_loss)}</td>
        <td className={`px-3 py-2 font-semibold tabular-nums ${row.flagged ? "text-rose-600 dark:text-rose-400" : ""}`}>
          {fmt(row.contamination_index)}
        </td>
        <td className="px-3 py-2 tabular-nums">{fmt(row.z_score)}</td>
        <td className="px-3 py-2"><ClassificationBadge value={row.classification} /></td>
        <td className="px-3 py-2">
          <Link
            to={`/experiments/${experimentId}/compare?snippet=${row.snippet_id}`}
            className="rounded px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50 dark:text-brand-400 dark:hover:bg-brand-950"
            onClick={(e) => e.stopPropagation()}
          >
            Compare →
          </Link>
        </td>
      </tr>
      {open && (
        <tr className="border-t border-slate-100 dark:border-slate-800">
          <td colSpan={7} className="px-5 py-3">
            <div className="grid gap-3 text-xs md:grid-cols-2">
              <div>
                <div className="mb-1 font-semibold text-slate-500">Problem statement</div>
                <p className="text-slate-600 dark:text-slate-300">{row.problem_statement || "—"}</p>
                <div className="mt-2 font-semibold text-slate-500">Why this label</div>
                <p className="text-slate-600 dark:text-slate-300">{row.classification_reason}</p>
                <div className="mt-2 flex flex-wrap gap-3 text-slate-500 dark:text-slate-400">
                  <span>median mut. loss {fmt(row.median_mutation_loss)}</span>
                  <span>std {fmt(row.std_mutation_loss)}</span>
                  <span>effect size {fmt(row.effect_size)}</span>
                  <span>percentile {fmt(row.percentile_rank, 1)}</span>
                  <span>mutations used {row.mutation_count_used}/{row.mutation_count_requested}</span>
                </div>
              </div>
              <pre className="mono overflow-x-auto rounded-lg bg-slate-950 p-3 text-[11px] leading-5 text-slate-200 dark:bg-black">
                {row.code}
              </pre>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function ResultsView({ bundle, showHeader = false }: {
  bundle: ResultsBundle;
  showHeader?: boolean;
}) {
  const { stats, analyses, distributions, classifications, experiment } = bundle;
  const [query, setQuery] = useState("");
  const [classFilter, setClassFilter] = useState<"ALL" | ClassificationValue>("ALL");
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [sortKey, setSortKey] = useState<"contamination_index" | "z_score" | "original_loss">("contamination_index");
  const [expanded, setExpanded] = useState<number | null>(null);

  const rows = useMemo(() => {
    const filtered = analyses.filter((row) => {
      if (flaggedOnly && !row.flagged) return false;
      if (classFilter !== "ALL" && row.classification !== classFilter) return false;
      if (query) {
        const haystack = `${row.external_id} ${row.problem_statement} ${row.code}`.toLowerCase();
        if (!haystack.includes(query.toLowerCase())) return false;
      }
      return true;
    });
    const sorted = [...filtered].sort((a, b) => {
      const av = a[sortKey] ?? -Infinity;
      const bv = b[sortKey] ?? -Infinity;
      return bv - av;
    });
    return sorted;
  }, [analyses, flaggedOnly, classFilter, query, sortKey]);

  const ciDist = distributions.ci;
  const zDist = distributions.z;
  const lossSeries = [
    { name: "original loss", color: ORIGINAL_COLOR, x: distributions.original_loss?.kde_x ?? [], y: distributions.original_loss?.kde_y ?? [] },
    { name: "mean mutated loss", color: MUTATION_COLOR, x: distributions.mutation_loss?.kde_x ?? [], y: distributions.mutation_loss?.kde_y ?? [] },
  ];
  const signalPoints = analyses.map((row) => ({
    label: row.external_id,
    contaminationIndex: row.contamination_index,
    effectSize: row.effect_size,
    classification: row.classification,
  }));

  return (
    <div className="space-y-4">
      {showHeader && <Disclaimer />}

      <ConclusionCard conclusion={bundle.conclusion} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard label="Analyzed" value={stats.analyzed_count} sub={`of ${experiment.total_items} snippets`} />
        <StatCard label="Flagged" value={stats.flagged_count} accent="text-rose-600 dark:text-rose-400"
          sub="possible-contamination or higher" />
        <StatCard label="High signal" value={stats.high_signal_count} accent="text-orange-600 dark:text-orange-400" />
        <StatCard label="Mean CI" value={fmt(stats.mean_ci)} sub={`median ${fmt(stats.median_ci)}`} />
        <StatCard label="Mean Z" value={fmt(stats.mean_z)} sub={`mean orig ${fmt(stats.mean_original_loss)}`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard title="Loss distribution" hint="Gaussian KDE">
          <KdeChart series={lossSeries} height={230} />
        </ChartCard>
        <ChartCard title="Contamination Index histogram" hint={`threshold 0.15 (${ciDist?.values.length ?? 0} snippets)`}>
          {ciDist && ciDist.histogram_x.length ? (
            <HistogramWithThreshold x={ciDist.histogram_x} y={ciDist.histogram_y} color="#8b5cf6" threshold={0.15} height={230} label="count" />
          ) : (
            <div className="py-16 text-center text-sm text-slate-400">No analyzable CI values</div>
          )}
        </ChartCard>
        <ChartCard title="Dataset-normalized Z-scores" hint="red line z = 2">
          {zDist?.values.length ? (
            <ZScoreChart zScores={zDist.values} height={230} />
          ) : (
            <div className="py-16 text-center text-sm text-slate-400">Baseline too small for Z-scores</div>
          )}
        </ChartCard>
        <ChartCard title="Classification counts">
          <ClassificationCounts counts={classifications} height={230} />
        </ChartCard>
        <ChartCard title="Highest contamination signals" hint="top 12; dashed lines at 0.15 and 0.35">
          <SignalRankingChart points={signalPoints} height={230} />
        </ChartCard>
        <ChartCard title="Signal strength vs consistency" hint="positive standardized gap means original is easier">
          {signalPoints.some((point) => point.effectSize !== null) ? (
            <SignalEffectScatter points={signalPoints} height={230} />
          ) : (
            <div className="py-16 text-center text-sm text-slate-400">At least two mutations are needed for a standardized gap</div>
          )}
        </ChartCard>
        <ChartCard title="Original vs mutated mean loss" hint="above y = x suggests memorization signal" className="xl:col-span-2">
          {bundle.pairs.length ? (
            <LossScatter pairs={bundle.pairs} height={260} />
          ) : (
            <div className="py-16 text-center text-sm text-slate-400">No scored pairs</div>
          )}
        </ChartCard>
      </div>

      <div className="card overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <input
            className="input max-w-xs !py-1.5 text-xs"
            placeholder="Filter by id, statement, code…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            className="input max-w-[220px] !py-1.5 text-xs"
            value={classFilter}
            onChange={(e) => setClassFilter(e.target.value as typeof classFilter)}
          >
            <option value="ALL">All classifications</option>
            <option value="HIGH_CONTAMINATION_SIGNAL">HIGH_CONTAMINATION_SIGNAL</option>
            <option value="POSSIBLE_CONTAMINATION">POSSIBLE_CONTAMINATION</option>
            <option value="ELEVATED">ELEVATED</option>
            <option value="NORMAL">NORMAL</option>
            <option value="LOW_EVIDENCE">LOW_EVIDENCE</option>
          </select>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-500">
            <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
            flagged only
          </label>
          <div className="ml-auto flex items-center gap-1 text-xs text-slate-400">
            sort
            <select className="input max-w-[170px] !py-1 text-xs" value={sortKey} onChange={(e) => setSortKey(e.target.value as typeof sortKey)}>
              <option value="contamination_index">CI</option>
              <option value="z_score">Z-score</option>
              <option value="original_loss">original loss</option>
            </select>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-400 dark:bg-slate-900">
                <th className="px-3 py-2 font-semibold">Snippet</th>
                <th className="px-3 py-2 font-semibold">Orig. loss</th>
                <th className="px-3 py-2 font-semibold">Mut. mean loss</th>
                <th className="px-3 py-2 font-semibold">CI</th>
                <th className="px-3 py-2 font-semibold">Z</th>
                <th className="px-3 py-2 font-semibold">Classification</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <AnalysisRow
                  key={row.snippet_id}
                  row={row}
                  experimentId={experiment.id}
                  open={expanded === row.snippet_id}
                  onToggle={() => setExpanded(expanded === row.snippet_id ? null : row.snippet_id)}
                />
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-sm text-slate-400">
                    No snippets match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
