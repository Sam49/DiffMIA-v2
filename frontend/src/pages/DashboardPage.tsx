import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ResultsView from "../components/ResultsView";
import { EmptyState, ErrorNotice, Spinner } from "../components/ui";
import { api, ApiError } from "../services/api";
import { useFetch } from "../hooks/useFetch";
import { useAuth, useCan } from "../hooks/useAuth";
import type { ResultsBundle } from "../types";

export default function DashboardPage() {
  const { user } = useAuth();
  const canWrite = useCan("write");
  const navigate = useNavigate();
  const [selected, setSelected] = useState<number | null>(null);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const experiments = useFetch(() => api.experiments(), []);
  const completed = useMemo(
    () => (experiments.data?.items ?? []).filter((e) => e.status === "COMPLETED"),
    [experiments.data]
  );
  const running = (experiments.data?.items ?? []).filter(
    (e) => e.status === "RUNNING" || e.status === "QUEUED"
  );

  const activeId = selected ?? completed[0]?.id ?? null;
  const bundle = useFetch<ResultsBundle>(
    () => (activeId ? api.results(activeId) : Promise.resolve(null as unknown as ResultsBundle)),
    [activeId]
  );

  const runDemo = async () => {
    setDemoError(null);
    setStarting(true);
    try {
      const result = await api.demoRun();
      navigate(`/experiments/${result.experiment_id}`);
    } catch (err) {
      setDemoError(err instanceof ApiError ? err.message : "Could not start demo.");
    } finally {
      setStarting(false);
    }
  };

  if (experiments.loading) return <Spinner label="Loading experiments…" />;
  if (experiments.error) return <ErrorNotice message={experiments.error} onRetry={experiments.reload} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900 dark:text-white">
            Research Dashboard
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Detect benchmark memorization through differential model behavior.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {completed.length > 1 && (
            <select className="input max-w-xs" value={activeId ?? ""} onChange={(e) => setSelected(Number(e.target.value))}>
              {completed.map((experiment) => (
                <option key={experiment.id} value={experiment.id}>
                  {experiment.name} · {experiment.dataset_name ?? `#${experiment.id}`}
                </option>
              ))}
            </select>
          )}
          <Link to="/experiments" className="btn-secondary">Experiments</Link>
          {canWrite && (
            <button onClick={runDemo} disabled={starting} className="btn-primary">
              {starting ? "Starting…" : "Run demo experiment"}
            </button>
          )}
        </div>
      </div>

      {demoError && <ErrorNotice message={demoError} />}

      {running.length > 0 && (
        <div className="card border-sky-200 px-4 py-3 text-sm text-sky-800 dark:border-sky-900 dark:text-sky-300">
          {running.length} experiment(s) in progress —{" "}
          <Link className="font-medium underline" to={`/experiments/${running[0].id}`}>
            open {running[0].name} to follow live progress →
          </Link>
        </div>
      )}

      {bundle.loading && activeId && <Spinner label="Loading results…" />}
      {bundle.error && <ErrorNotice message={bundle.error} onRetry={bundle.reload} />}
      {bundle.data && activeId ? (
        <ResultsView bundle={bundle.data} />
      ) : (
        !bundle.loading && (
          <EmptyState
            title="No completed experiments yet"
            hint={
              user?.role === "VIEWER"
                ? "Ask a researcher to run an experiment, or review existing experiments."
                : "Run the one-click demo (mock provider, no GPU/API needed) or upload a JSONL dataset and start a real experiment."
            }
            action={
              canWrite ? (
                <div className="mt-2 flex gap-2">
                  <button onClick={runDemo} disabled={starting} className="btn-primary">
                    ▶ Run Demo
                  </button>
                  <Link to="/datasets" className="btn-secondary">Upload dataset</Link>
                </div>
              ) : (
                <Link to="/experiments" className="btn-secondary">Browse experiments</Link>
              )
            }
          />
        )
      )}
    </div>
  );
}
