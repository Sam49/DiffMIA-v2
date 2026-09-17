import { useRef, useState } from "react";
import { Labeled, Modal, PageHeader, Spinner, ErrorNotice, EmptyState } from "../components/ui";
import { api, ApiError, downloadFile } from "../services/api";
import { useCan } from "../hooks/useAuth";
import { useFetch } from "../hooks/useFetch";
import type { DatasetInfo, DatasetItemInfo } from "../types";

export default function DatasetsPage() {
  const canWrite = useCan("write");
  const [modalOpen, setModalOpen] = useState(false);
  const [viewItems, setViewItems] = useState<{ dataset: DatasetInfo; items: DatasetItemInfo[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [manual, setManual] = useState({ name: "", code: "", problem: "", externalId: "" });

  const datasets = useFetch(() => api.datasets(), []);

  const refresh = () => {
    datasets.reload();
    setModalOpen(false);
    setManual({ name: "", code: "", problem: "", externalId: "" });
    setError(null);
  };

  const upload = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", file.name.replace(/\.[^.]+$/, ""));
      const result = await api.uploadDataset(form);
      setNotice(`Imported ${result.items_added} items from ${file.name}.`);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const addManual = async () => {
    if (!manual.code.trim()) {
      setError("Code is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createDataset({
        name: manual.name.trim() || "Manual snippets",
        description: "Created from the web UI",
        items: [
          {
            external_id: manual.externalId || undefined,
            problem_statement: manual.problem,
            code: manual.code,
            language: "python",
            metadata: {},
          },
        ],
      });
      setNotice("Snippet added.");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create dataset.");
    } finally {
      setBusy(false);
    }
  };

  const openItems = async (dataset: DatasetInfo) => {
    try {
      const page = await api.datasetItems(dataset.id);
      setViewItems({ dataset, items: page.items });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load items.");
    }
  };

  const items = datasets.data?.items ?? [];
  return (
    <div className="space-y-4">
      <PageHeader
        title="Datasets"
        subtitle="Benchmark examples are stored as items with a problem statement and code. Code is parsed with the AST only — never executed."
        actions={
          canWrite && (
            <button className="btn-primary" onClick={() => setModalOpen(true)}>+ Add dataset</button>
          )
        }
      />
      {notice && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
          {notice}
        </div>
      )}
      {error && <ErrorNotice message={error} />}
      {datasets.loading && <Spinner />}
      {!datasets.loading && items.length === 0 && (
        <EmptyState
          title="No datasets yet"
          hint="Upload a .jsonl / .json / .csv / .py file, or add a single Python snippet."
          action={canWrite ? <button className="btn-primary mt-2" onClick={() => setModalOpen(true)}>Add dataset</button> : undefined}
        />
      )}
      {items.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-400 dark:bg-slate-900">
                  <th className="px-4 py-2 font-semibold">Dataset</th>
                  <th className="px-4 py-2 font-semibold">Items</th>
                  <th className="px-4 py-2 font-semibold">Format</th>
                  <th className="px-4 py-2 font-semibold">Content hash</th>
                  <th className="px-4 py-2 font-semibold">Created</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((dataset) => (
                  <tr key={dataset.id} className="border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-900">
                    <td className="px-4 py-3 font-medium">{dataset.name}</td>
                    <td className="px-4 py-3">{dataset.item_count}</td>
                    <td className="px-4 py-3"><span className="badge bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{dataset.source_format}</span></td>
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-400">{dataset.content_hash.slice(0, 16)}…</td>
                    <td className="px-4 py-3 text-xs text-slate-400">{dataset.created_at ? new Date(dataset.created_at).toLocaleString() : ""}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1">
                        <button className="btn-secondary !px-2.5 !py-1 text-xs" onClick={() => openItems(dataset)}>items</button>
                        <button
                          className="btn-secondary !px-2.5 !py-1 text-xs"
                          onClick={() => downloadFile(api.datasetExportUrl(dataset.id), `dataset-${dataset.id}.jsonl`).catch(() => undefined)}
                        >
                          ⤓
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Add dataset">
        <div className="space-y-4">
          <div>
            <div className="mb-1 text-xs font-medium text-slate-500">Upload file (.jsonl, .json, .csv, .py)</div>
            <input
              ref={fileInput}
              type="file"
              accept=".jsonl,.json,.csv,.py,.ndjson,.txt"
              className="block w-full text-sm text-slate-500 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-700 file:px-3 file:py-2 file:text-sm file:font-medium file:text-white"
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              disabled={busy}
            />
          </div>
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-slate-400">
            <span className="h-px flex-1 bg-slate-200 dark:bg-slate-800" /> or add one snippet <span className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
          </div>
          <Labeled label="Dataset name">
            <input className="input" value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} placeholder="my benchmark" />
          </Labeled>
          <Labeled label="External id">
            <input className="input" value={manual.externalId} onChange={(e) => setManual({ ...manual, externalId: e.target.value })} placeholder="sum_001 (optional)" />
          </Labeled>
          <Labeled label="Problem statement">
            <textarea className="input" rows={2} value={manual.problem} onChange={(e) => setManual({ ...manual, problem: e.target.value })} />
          </Labeled>
          <Labeled label="Python code">
            <textarea className="input mono" rows={6} value={manual.code} onChange={(e) => setManual({ ...manual, code: e.target.value })} placeholder={"def solution(numbers):\n    return sum(numbers)"} />
          </Labeled>
          {error && <p className="rounded-lg bg-rose-950 px-3 py-2 text-xs text-rose-300">{error}</p>}
          <button className="btn-primary w-full" disabled={busy} onClick={addManual}>
            {busy ? "Working…" : "Save snippet"}
          </button>
        </div>
      </Modal>

      <Modal open={viewItems !== null} onClose={() => setViewItems(null)} title={`Items — ${viewItems?.dataset.name ?? ""}`} wide>
        <div className="max-h-[65vh] space-y-3 overflow-y-auto">
          {viewItems?.items.map((item) => (
            <div key={item.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <div className="flex items-center justify-between text-xs">
                <span className="font-mono font-medium">{item.external_id}</span>
                <span className="text-slate-400">{item.language}</span>
              </div>
              <p className="mt-1 text-xs text-slate-500">{item.problem_statement}</p>
              <pre className="mono mt-2 overflow-x-auto rounded-lg bg-slate-950 p-2 text-[11px] leading-4 text-slate-200 dark:bg-black">{item.code}</pre>
            </div>
          ))}
          {viewItems && viewItems.items.length === 0 && <p className="py-6 text-center text-sm text-slate-400">Dataset is empty.</p>}
        </div>
      </Modal>
    </div>
  );
}
