import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ResultsView from "../components/ResultsView";
import { Disclaimer, ErrorNotice, PageHeader, ProgressBar, Spinner, StatusBadge } from "../components/ui";
import { api, ApiError, downloadFile } from "../services/api";
import { useCan } from "../hooks/useAuth";
import { useFetch } from "../hooks/useFetch";
import type { ExperimentDetail, ResultsBundle } from "../types";

const STAGE_LABEL: Record<string, string> = {
  queued: "Queued",
  processing: "Preparing provider…",
  mutation_generation: "Generating mutations",
  inference: "Scoring with the model",
  analysis: "Running differential analysis",
  completed: "Completed",
  failed: "Failed",
};

export default function ExperimentDetailPage() {
  const { id } = useParams();
  const experimentId = Number(id);
  const canWrite = useCan("write");
  const [tab, setTab] = useState<"overview" | "results">("overview");

  const experiment = useFetch<ExperimentDetail>(() => api.experiment(experimentId), [experimentId]);
  const detail = experiment.data;
  const active = detail?.status === "RUNNING" || detail?.status === "QUEUED";
  const completed = detail?.status === "COMPLETED";

  const results = useFetch<ResultsBundle>(
    () => (completed ? api.results(experimentId) : Promise.resolve(null as unknown as ResultsBundle)),
    [completed, experimentId]
  );
  const logs = useFetch(() => api.logs(experimentId).then((p) => p.items), [experimentId]);

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      experiment.reload();
      if (detail?.status === "COMPLETED") results.reload();
    }, 1200);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, detail?.status]);

  useEffect(() => {
    if (completed) setTab("results");
  }, [completed]);

  const run = async () => {
    try {
      await api.runExperiment(experimentId);
      experiment.reload();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Could not run experiment.");
    }
  };
  const cancel = async () => {
    try {
      await api.cancelExperiment(experimentId);
      experiment.reload();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Could not cancel experiment.");
    }
  };

  const isDemo = detail?.model?.provider === "mock";
  const config = useMemo(() => {
    if (!detail) return null;
    try {
      return JSON.parse(detail.config_json) as Record<string, unknown>;
    } catch {
      return {};
    }
  }, [detail]);

  if (experiment.loading) return <Spinner label="Loading experiment…" />;
  if (experiment.error || !detail) return <ErrorNotice message={experiment.error ?? "Not found"} onRetry={experiment.reload} />;

  return (
    <div className="space-y-4">
      <PageHeader
        title={detail.name}
        subtitle={detail.description || "Differential loss analysis experiment"}
        actions={
          <>
            <StatusBadge status={detail.status} />
            {isDemo && (
              <span className="badge bg-amber-100 text-amber-800 ring-1 ring-amber-300 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-800">
                ◉ DEMO MODE — synthetic mock losses
              </span>
            )}
            {active && canWrite && (
              <button className="btn-danger" onClick={cancel}>Cancel</button>
            )}
            {!active && canWrite && (
              <button className="btn-secondary" onClick={run}>↻ Rerun experiment</button>
            )}
          </>
        }
      />

      {detail.status === "FAILED" && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
          <b>{detail.error_code}</b> — {detail.error_message || "Experiment failed."}
        </div>
      )}

      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-800">
        {(["overview", "results"] as const).map((key) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`-mb-px rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium ${
              tab === key
                ? "border-brand-600 text-brand-700 dark:text-brand-400"
                : "border-transparent text-slate-400 hover:text-slate-600"
            }`}
          >
            {key === "overview" ? "Overview" : `Results${completed ? "" : ""}`}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="card">
              <div className="card-header">Configuration</div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-5 py-4 text-sm">
                {[
                  ["Mutations", `${detail.mutation_count} × ${detail.mutation_strategy}`],
                  ["Mutation seed", String(detail.mutation_seed)],
                  ["Mutation strength", String(detail.mutation_strength)],
                  ["Batch size", String(detail.batch_size)],
                  ["Max tokens", String(detail.max_tokens)],
                  ["Temperature", String(detail.temperature)],
                  ["Device", detail.device],
                  ["Thresholds", config?.thresholds ? "custom" : "defaults"],
                  ["Cache", config?.cache_enabled ? "enabled" : "disabled"],
                  ["Token losses", config?.token_losses_enabled ? "stored" : "summary only"],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-3">
                    <dt className="text-slate-400">{label}</dt>
                    <dd className="text-right font-mono text-xs text-slate-700 dark:text-slate-200">{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
            <div className="space-y-4">
              <div className="card">
                <div className="card-header">Model</div>
                <div className="px-5 py-4 text-sm">
                  <div className="font-medium">{detail.model?.display_name || detail.model_name || `model #${detail.model_id}`}</div>
                  <div className="mt-1 font-mono text-xs text-slate-400">{detail.model?.model_id}</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <span className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{detail.model?.provider}</span>
                    <span className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{detail.model_version}</span>
                  </div>
                </div>
              </div>
              <div className="card">
                <div className="card-header">Dataset</div>
                <div className="px-5 py-4 text-sm">
                  <div className="font-medium">{detail.dataset?.name}</div>
                  <div className="mt-1 font-mono text-[11px] text-slate-400">hash {detail.dataset_hash?.slice(0, 16)}…</div>
                  <div className="mt-1 text-xs text-slate-500">{detail.dataset?.item_count} items · {detail.dataset?.source_format}</div>
                </div>
              </div>
            </div>
          </div>

          {active && (
            <div className="card px-5 py-4">
              <div className="mb-2 flex items-center justify-between text-sm">
                <span className="font-semibold">{STAGE_LABEL[detail.current_stage] ?? detail.current_stage}</span>
                <span className="text-slate-400">{detail.progress_message}</span>
              </div>
              <ProgressBar value={detail.processed_items} max={detail.total_items} label={`${detail.processed_items} / ${detail.total_items} snippets`} />
            </div>
          )}

          {completed && (
            <div className="flex flex-wrap gap-2">
              {[
                ["CSV", "export/csv", "text/csv"],
                ["JSON", "export/json", "application/json"],
                ["Markdown", "export/markdown", "text/markdown"],
                ["PDF report", "export/pdf", "application/pdf"],
              ].map(([label, suffix]) => (
                <button
                  key={label}
                  className="btn-secondary"
                  onClick={() =>
                    downloadFile(
                      `/experiments/${experimentId}/${suffix}`,
                      `diffmia-experiment-${experimentId}-${label.toLowerCase().replace(/ /g, "-")}.${suffix.includes("csv") ? "csv" : suffix.includes("json") ? "json" : suffix.includes("pdf") ? "pdf" : "md"}`
                    ).catch((err: unknown) => alert(err instanceof Error ? err.message : "Download failed"))
                  }
                >
                  ⤓ {label}
                </button>
              ))}
            </div>
          )}

          <div className="card">
            <div className="card-header">Experiment log</div>
            <div className="max-h-64 overflow-y-auto px-4 py-2">
              {logs.loading && <Spinner />}
              {(logs.data ?? []).length === 0 && !logs.loading && (
                <p className="py-6 text-center text-sm text-slate-400">No log entries yet.</p>
              )}
              {(logs.data ?? []).map((entry) => (
                <div key={entry.id} className="flex gap-3 border-b border-slate-100 py-1.5 font-mono text-[11px] dark:border-slate-800">
                  <span className="text-slate-400">{entry.created_at ? new Date(entry.created_at).toISOString().slice(11, 19) : ""}</span>
                  <span className={entry.level === "ERROR" ? "text-rose-400" : "text-emerald-400"}>{entry.level}</span>
                  <span className="text-slate-600 dark:text-slate-300">{entry.message}</span>
                </div>
              ))}
            </div>
          </div>

          <Link to={`/experiments/${experimentId}/compare`} className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-400">
            Open code comparison view →
          </Link>
        </div>
      )}

      {tab === "results" && (
        <>
          {!completed && detail.status !== "FAILED" && <Disclaimer />}
          {results.loading && <Spinner label="Loading results…" />}
          {results.error && <ErrorNotice message={results.error} onRetry={results.reload} />}
          {results.data && <ResultsView bundle={results.data} showHeader />}
          {completed && !results.data && !results.loading && (
            <EmptyNote status={detail.status} />
          )}
        </>
      )}
    </div>
  );
}

function EmptyNote({ status }: { status: string }) {
  return (
    <div className="card px-5 py-10 text-center text-sm text-slate-400">
      No analysis rows available ({status}).
    </div>
  );
}
