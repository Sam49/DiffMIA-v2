import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ResultsView from "../components/ResultsView";
import { EmptyState, ErrorNotice, PageHeader, Spinner, StatusBadge } from "../components/ui";
import { api } from "../services/api";
import { useFetch } from "../hooks/useFetch";
import type { ResultsBundle } from "../types";

export default function ResultsPage() {
  const experiments = useFetch(() => api.experiments(), []);
  const completed = useMemo(
    () => (experiments.data?.items ?? []).filter((e) => e.status === "COMPLETED"),
    [experiments.data]
  );
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = selectedId ?? completed[0]?.id ?? null;
  const bundle = useFetch<ResultsBundle>(
    () => (selected ? api.results(selected) : Promise.resolve(null as unknown as ResultsBundle)),
    [selected]
  );

  if (experiments.loading) return <Spinner label="Loading experiments…" />;
  if (experiments.error) return <ErrorNotice message={experiments.error} onRetry={experiments.reload} />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Results"
        subtitle="Browse differential-analysis results across completed experiments."
        actions={
          completed.length > 1 ? (
            <select className="input max-w-sm" value={selected ?? ""} onChange={(e) => setSelectedId(Number(e.target.value))}>
              {completed.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name} — {e.dataset_name ?? `#${e.id}`}
                </option>
              ))}
            </select>
          ) : undefined
        }
      />

      {completed.length === 0 && (
        <EmptyState title="No completed experiments" hint="Results appear here after an experiment finishes." />
      )}

      {completed.length > 0 && (
        <div className="card">
          <div className="card-header">Experiments</div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-400 dark:bg-slate-900">
                  <th className="px-4 py-2 font-semibold">Experiment</th>
                  <th className="px-4 py-2 font-semibold">Status</th>
                  <th className="px-4 py-2 font-semibold">Model</th>
                  <th className="px-4 py-2 font-semibold">Dataset</th>
                  <th className="px-4 py-2 text-right font-semibold">Analyzed</th>
                  <th className="px-4 py-2 text-right font-semibold">Flagged</th>
                  <th className="px-4 py-2 text-right font-semibold">Mean CI</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {completed.map((e) => (
                  <tr key={e.id} className="border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900">
                    <td className="px-4 py-3 font-medium">{e.name}</td>
                    <td className="px-4 py-3"><StatusBadge status={e.status} /></td>
                    <td className="px-4 py-3 text-xs text-slate-500">{e.model_name ?? `model ${e.model_id}`}</td>
                    <td className="px-4 py-3 text-xs text-slate-500">{e.dataset_name}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{e.processed_items}</td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-400">—</td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-400">—</td>
                    <td className="px-4 py-3 text-right">
                      <Link className="btn-secondary !px-2.5 !py-1 text-xs" to={`/experiments/${e.id}`}>open</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {bundle.loading && <Spinner label="Loading results…" />}
      {bundle.error && <ErrorNotice message={bundle.error} onRetry={bundle.reload} />}
      {bundle.data && <ResultsView bundle={bundle.data} showHeader />}
    </div>
  );
}
