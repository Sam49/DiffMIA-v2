import { useMemo, useState } from "react";
import { Disclaimer, EmptyState, ErrorNotice, PageHeader, Spinner } from "../components/ui";
import ConclusionCard from "../components/ConclusionCard";
import { api, downloadFile } from "../services/api";
import { useFetch } from "../hooks/useFetch";
import type { ResultsBundle } from "../types";

const FORMATS: Array<[string, string, string, string]> = [
  ["PDF report", "export/pdf", "pdf", "Server-rendered research report (reportlab)."],
  ["Markdown", "export/markdown", "md", "Same structure as the PDF, plain text."],
  ["CSV", "export/csv", "csv", "One row per snippet — analysis into a spreadsheet."],
  ["JSON (full)", "export/json", "json", "Everything: config, analyses, conclusion, distributions."],
];

export default function ReportsPage() {
  const experiments = useFetch(() => api.experiments(), []);
  const completed = useMemo(
    () => (experiments.data?.items ?? []).filter((e) => e.status === "COMPLETED"),
    [experiments.data]
  );
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const selected = selectedId ?? completed[0]?.id ?? null;

  // Reports are read-only downloads, so any signed-in role may produce them —
  // the export endpoints themselves only require authentication.
  const preview = useFetch<ResultsBundle | null>(
    () => (selected ? api.results(selected) : Promise.resolve(null)),
    [selected]
  );

  const download = (suffix: string, extension: string) =>
    downloadFile(`/experiments/${selected}/${suffix}`, `diffmia-experiment-${selected}-report.${extension}`).catch(
      (err: unknown) => alert(err instanceof Error ? err.message : "Download failed")
    );

  if (experiments.loading) return <Spinner label="Loading experiments…" />;
  if (experiments.error) return <ErrorNotice message={experiments.error} onRetry={experiments.reload} />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Research reports"
        subtitle="Generate a self-contained report of an experiment: conclusion, summary, methodology, statistics, top flagged examples, limitations and reproducibility metadata."
      />

      {completed.length === 0 && (
        <EmptyState
          title="Nothing to report yet"
          hint="Complete an experiment first — reports are generated from finished runs."
        />
      )}

      {completed.length > 0 && (
        <>
          <div className="card p-5">
            <div className="flex flex-wrap items-end gap-3">
              <label className="block min-w-[280px] flex-1">
                <span className="mb-1 block text-xs font-medium text-slate-500">Experiment</span>
                <select
                  className="input"
                  value={selected ?? ""}
                  onChange={(e) => setSelectedId(Number(e.target.value))}
                >
                  {completed.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name} — {e.dataset_name ?? `#${e.id}`}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex flex-wrap gap-2">
                {FORMATS.map(([label, suffix, extension, hint]) => (
                  <button
                    key={label}
                    className="btn-secondary"
                    title={hint}
                    onClick={() => download(suffix, extension)}
                  >
                    ⤓ {label}
                  </button>
                ))}
              </div>
            </div>
            {selected && (
              <p className="mt-3 text-[11px] text-slate-400">
                Downloads include the conclusion, per-snippet results, methodology and the
                reproducibility metadata recorded for experiment #{selected}.
              </p>
            )}
          </div>

          {preview.loading && <Spinner label="Loading the report conclusion…" />}
          {preview.data?.conclusion && <ConclusionCard conclusion={preview.data.conclusion} />}
        </>
      )}

      <Disclaimer />
      <div className="card px-5 py-4 text-xs leading-relaxed text-slate-500">
        <b>Report contents.</b> Conclusion and verdict · experiment and model configuration · dataset hash · mutation
        methodology (identifier renaming with deterministic seeds) · statistical methodology (CI, Z-scores, effect
        size, percentile ranks) · per-snippet table · top flagged examples · explicit scientific limitations ·
        reproducibility information. PDF exports are rendered server-side with reportlab.
      </div>
    </div>
  );
}
