import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader, StatusBadge, Modal, Labeled, ErrorNotice, Spinner, EmptyState } from "../components/ui";
import { api, ApiError } from "../services/api";
import { useCan } from "../hooks/useAuth";
import { useFetch } from "../hooks/useFetch";
import type { DatasetInfo, ExperimentSummary, ModelInfo } from "../types";

const DEFAULTS = { mutationCount: 5, mutationSeed: 42, mutationStrength: 0.3, batchSize: 4, maxTokens: 4096 };

function statusOf(row: ExperimentSummary) {
  return row.status;
}

export default function ExperimentsPage() {
  const navigate = useNavigate();
  const canWrite = useCan("write");
  const [createOpen, setCreateOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    name: "",
    description: "",
    datasetId: "",
    modelId: "",
    mutationCount: String(DEFAULTS.mutationCount),
    mutationSeed: String(DEFAULTS.mutationSeed),
    mutationStrength: String(DEFAULTS.mutationStrength),
    batchSize: String(DEFAULTS.batchSize),
    maxTokens: String(DEFAULTS.maxTokens),
    temperature: "0",
    device: "auto",
  });

  const experiments = useFetch(() => api.experiments(), []);
  const datasets = useFetch(() => api.datasets(), []);
  const models = useFetch(() => api.models(), []);
  const hasActive = (experiments.data?.items ?? []).some((e) => e.status === "RUNNING" || e.status === "QUEUED");

  // Poll while jobs are active so progress updates in real time.
  useEffect(() => {
    if (!hasActive) return;
    const timer = setInterval(() => experiments.reload(), 1500);
    return () => clearInterval(timer);
  }, [hasActive, experiments]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const created = await api.createExperiment({
        name: form.name.trim(),
        description: form.description,
        dataset_id: Number(form.datasetId),
        model_id: Number(form.modelId),
        mutation_count: Number(form.mutationCount),
        mutation_seed: Number(form.mutationSeed),
        mutation_strength: Number(form.mutationStrength),
        batch_size: Number(form.batchSize),
        max_tokens: Number(form.maxTokens),
        temperature: Number(form.temperature),
        device: form.device,
        mutation_strategy: "identifier_rename",
      });
      navigate(`/experiments/${created.id}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Could not create experiment.");
    } finally {
      setSaving(false);
    }
  };

  const run = async (id: number) => {
    try {
      await api.runExperiment(id);
      experiments.reload();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to start experiment");
    }
  };

  const cancel = async (id: number) => {
    try {
      await api.cancelExperiment(id);
      experiments.reload();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Failed to cancel experiment");
    }
  };

  const items = experiments.data?.items ?? [];
  const datasetsItems = datasets.data?.items ?? [];
  const modelsItems = models.data?.items ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Experiments"
        subtitle="Every experiment is reproducible: seed, dataset hash, model version and configuration are recorded."
        actions={
          canWrite && (
            <button className="btn-primary" onClick={() => setCreateOpen(true)}>+ New experiment</button>
          )
        }
      />

      {experiments.error && <ErrorNotice message={experiments.error} onRetry={experiments.reload} />}
      {experiments.loading && <Spinner />}
      {!experiments.loading && items.length === 0 && (
        <EmptyState
          title="No experiments yet"
          hint="Create one from an uploaded dataset, or use the one-click demo."
          action={
            canWrite ? (
              <button className="btn-primary mt-2" onClick={() => setCreateOpen(true)}>New experiment</button>
            ) : undefined
          }
        />
      )}

      {items.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-400 dark:bg-slate-900">
                  <th className="px-4 py-2 font-semibold">Experiment</th>
                  <th className="px-4 py-2 font-semibold">Model</th>
                  <th className="px-4 py-2 font-semibold">Dataset</th>
                  <th className="px-4 py-2 font-semibold">Status</th>
                  <th className="px-4 py-2 font-semibold">Progress</th>
                  <th className="px-4 py-2 font-semibold">Created</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((row) => {
                  const running = row.status === "RUNNING" || row.status === "QUEUED";
                  const percent = row.total_items ? Math.round((row.processed_items / row.total_items) * 100) : 0;
                  return (
                    <tr key={row.id} className="border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900">
                      <td className="px-4 py-3">
                        <Link to={`/experiments/${row.id}`} className="font-medium text-brand-700 hover:underline dark:text-brand-400">
                          {row.name}
                        </Link>
                        <div className="text-[11px] text-slate-400">#{row.id} · {row.mutation_count} mutations · seed {row.mutation_seed}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-xs font-medium">{row.model_name ?? `model ${row.model_id}`}</div>
                        {row.model_id && <div className="text-[11px] text-slate-400">{row.model_version}</div>}
                      </td>
                      <td className="max-w-[160px] px-4 py-3 text-xs text-slate-500">{row.dataset_name}</td>
                      <td className="px-4 py-3"><StatusBadge status={statusOf(row)} /></td>
                      <td className="w-40 px-4 py-3">
                        <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                          <div className="h-full bg-brand-600" style={{ width: `${percent}%` }} />
                        </div>
                        <div className="mt-1 truncate text-[11px] text-slate-400">
                          {row.processed_items}/{row.total_items} · {row.current_stage}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-400">
                        {row.created_at ? new Date(row.created_at).toLocaleString() : ""}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          {(row.status === "COMPLETED" || row.status === "FAILED" || row.status === "CANCELLED") && canWrite && (
                            <button className="btn-secondary !px-2.5 !py-1 text-xs" onClick={() => run(row.id)}>
                              ↻ rerun
                            </button>
                          )}
                          {running && canWrite && (
                            <button className="btn-danger !px-2.5 !py-1 text-xs" onClick={() => cancel(row.id)}>
                              cancel
                            </button>
                          )}
                          {row.status === "COMPLETED" && (
                            <Link className="btn-secondary !px-2.5 !py-1 text-xs" to={`/experiments/${row.id}`}>
                              open
                            </Link>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="New experiment" wide>
        <form onSubmit={submit} className="grid gap-4 md:grid-cols-2">
          <div className="md:col-span-2">
            <Labeled label="Experiment name">
              <input required className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Llama-3 contamination scan — HumanEval" />
            </Labeled>
          </div>
          <div className="md:col-span-2">
            <Labeled label="Description">
              <textarea className="input" rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </Labeled>
          </div>
          <Labeled label="Dataset">
            <select required className="input" value={form.datasetId} onChange={(e) => setForm({ ...form, datasetId: e.target.value })}>
              <option value="">Select dataset…</option>
              {datasetsItems.map((dataset: DatasetInfo) => (
                <option key={dataset.id} value={dataset.id}>{dataset.name} ({dataset.item_count} items)</option>
              ))}
            </select>
          </Labeled>
          <Labeled label="Model">
            <select required className="input" value={form.modelId} onChange={(e) => setForm({ ...form, modelId: e.target.value })}>
              <option value="">Select model…</option>
              {modelsItems.map((model: ModelInfo) => (
                <option key={model.id} value={model.id}>
                  {model.display_name || model.name} · {model.provider}
                </option>
              ))}
            </select>
          </Labeled>
          <Labeled label="Mutations">
            <input type="number" min={1} max={20} className="input" value={form.mutationCount} onChange={(e) => setForm({ ...form, mutationCount: e.target.value })} />
          </Labeled>
          <Labeled label="Mutation seed">
            <input type="number" className="input" value={form.mutationSeed} onChange={(e) => setForm({ ...form, mutationSeed: e.target.value })} />
          </Labeled>
          <Labeled label="Mutation strength">
            <input type="number" step={0.05} min={0.05} max={1} className="input" value={form.mutationStrength} onChange={(e) => setForm({ ...form, mutationStrength: e.target.value })} />
          </Labeled>
          <Labeled label="Batch size">
            <select className="input" value={form.batchSize} onChange={(e) => setForm({ ...form, batchSize: e.target.value })}>
              {[1, 2, 4, 8, 16].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </Labeled>
          <Labeled label="Max tokens">
            <input type="number" min={1} className="input" value={form.maxTokens} onChange={(e) => setForm({ ...form, maxTokens: e.target.value })} />
          </Labeled>
          <Labeled label="Temperature">
            <input type="number" step={0.1} min={0} max={2} className="input" value={form.temperature} onChange={(e) => setForm({ ...form, temperature: e.target.value })} />
          </Labeled>
          <Labeled label="Device">
            <select className="input" value={form.device} onChange={(e) => setForm({ ...form, device: e.target.value })}>
              {["auto", "cpu", "cuda", "mps"].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </Labeled>
          <div className="md:col-span-2">
            {formError && <p className="mb-2 rounded-lg bg-rose-950 px-3 py-2 text-xs text-rose-300">{formError}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setCreateOpen(false)}>Cancel</button>
              <button className="btn-primary" disabled={saving || !form.name || !form.datasetId || !form.modelId}>
                {saving ? "Creating…" : "Create experiment"}
              </button>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  );
}
