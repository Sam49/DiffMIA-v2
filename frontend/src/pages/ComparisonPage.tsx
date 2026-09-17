import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import DiffView from "../components/DiffView";
import { ClassificationBadge, EmptyState, ErrorNotice, PageHeader, Spinner } from "../components/ui";
import { api, fmt } from "../services/api";
import { useFetch } from "../hooks/useFetch";
import type { MutationInfo } from "../types";

export default function ComparisonPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const experimentId = Number(id);
  const initialSnippet = params.get("snippet") ? Number(params.get("snippet")) : null;

  const results = useFetch(() => api.results(experimentId), [experimentId]);
  const analyses = results.data?.analyses ?? [];
  const firstSnippetId = initialSnippet ?? analyses[0]?.snippet_id ?? null;

  const [snippetId, setSnippetId] = useState<number | null>(firstSnippetId);
  const [activeMutation, setActiveMutation] = useState<number | null>(1);

  useEffect(() => {
    if (snippetId === null && analyses.length > 0) setSnippetId(analyses[0].snippet_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analyses.length]);

  const analysis = analyses.find((a) => a.snippet_id === snippetId);
  const mutations = useFetch<MutationInfo[]>(
    () => (experimentId && snippetId ? api.mutations(experimentId, snippetId).then((p) => p.items) : Promise.resolve([])),
    [experimentId, snippetId]
  );
  const mutationList = mutations.data ?? [];
  const selected = mutationList.find((m) => m.mutation_index === activeMutation) ?? mutationList[0] ?? null;

  useEffect(() => {
    if (mutationList.length > 0 && !selected) {
      setActiveMutation(mutationList[0].mutation_index);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mutationList.length]);

  const mapping = useMemo(() => {
    if (!selected) return {};
    try {
      const parsed = JSON.parse(selected.mapping_json) as { mapping: Record<string, string> };
      return parsed.mapping ?? {};
    } catch {
      return {};
    }
  }, [selected]);

  if (results.loading || (snippetId && mutations.loading)) return <Spinner label="Loading comparison…" />;
  if (results.error) return <ErrorNotice message={results.error} onRetry={results.reload} />;

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Code comparison — ${analysis?.external_id ?? `snippet #${snippetId ?? ""}`}`}
        subtitle="Original benchmark code vs deterministic identifier-mutated equivalents. Renamed identifiers are highlighted."
        actions={
          <Link to={`/experiments/${experimentId}`} className="btn-secondary">← back to experiment</Link>
        }
      />

      {analysis && (
        <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-slate-400">snippet</span>
            <select className="input max-w-[200px] !py-1 text-xs" value={snippetId ?? ""} onChange={(e) => setSnippetId(Number(e.target.value))}>
              {analyses.map((a) => (
                <option key={a.snippet_id} value={a.snippet_id}>{a.external_id}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span>original loss <b className="tabular-nums">{fmt(analysis.original_loss)}</b></span>
            <span>mean mutated <b className="tabular-nums">{fmt(analysis.mean_mutation_loss)}</b></span>
            <span className={analysis.flagged ? "text-rose-600 dark:text-rose-400" : ""}>
              CI <b className="tabular-nums">{fmt(analysis.contamination_index)}</b>
            </span>
            <span>Z <b className="tabular-nums">{fmt(analysis.z_score)}</b></span>
            <ClassificationBadge value={analysis.classification} />
          </div>
        </div>
      )}

      {snippetId && (
        <div className="card px-4 py-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs font-semibold text-slate-400">mutation</span>
            {mutationList.map((mutation) => (
              <button
                key={mutation.id}
                onClick={() => setActiveMutation(mutation.mutation_index)}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium ${
                  selected?.mutation_index === mutation.mutation_index
                    ? "bg-brand-700 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
                }`}
              >
                #{mutation.mutation_index}
              </button>
            ))}
            {mutationList.length === 0 && <span className="text-xs text-slate-400">No valid mutations for this snippet</span>}
          </div>
        </div>
      )}

      {!snippetId && !results.loading && (
        <EmptyState title="Nothing to compare" hint="Run an experiment first so mutations and losses exist." />
      )}

      {selected ? (
        <div className="space-y-2">
          {analysis && (
            <p className="text-xs text-slate-500">
              {analysis.problem_statement || "No problem statement."} —{" "}
              <span className="text-slate-400">{analysis.classification_reason}</span>
            </p>
          )}
          <DiffView
            originalCode={selected.original_code}
            mutatedCode={selected.mutated_code}
            mapping={mapping}
            mutationIndex={selected.mutation_index}
            seed={selected.seed}
            validationStatus={selected.validation_status}
            validationScore={selected.validation_score}
          />
        </div>
      ) : (
        !results.loading && !mutations.loading && (
          <EmptyState title="No mutation selected" hint="Choose a mutation above." />
        )
      )}
    </div>
  );
}
