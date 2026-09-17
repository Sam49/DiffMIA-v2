import { PageHeader, Spinner, ErrorNotice } from "../components/ui";
import { api } from "../services/api";
import { useFetch } from "../hooks/useFetch";
import type { ModelInfo } from "../types";

function ProviderBadge({ provider }: { provider: string }) {
  const style: Record<string, string> = {
    mock: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
    transformers: "bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
    openai_compatible: "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
    deepseek: "bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-950 dark:text-fuchsia-300",
  };
  return <span className={`badge ${style[provider] ?? "badge"}`}>{provider}</span>;
}

export default function ModelsPage() {
  const models = useFetch(() => api.models(), []);
  if (models.loading) return <Spinner label="Loading model registry…" />;
  if (models.error) return <ErrorNotice message={models.error} onRetry={models.reload} />;

  const items = (models.data?.items ?? []) as (ModelInfo & { is_mock?: boolean; supports_logprobs?: boolean })[];
  return (
    <div className="space-y-4">
      <PageHeader
        title="Models"
        subtitle="Providers are configured in configs/models.yaml — never in code or the database. Secrets resolve from environment variables."
      />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((model) => (
          <div key={model.id} className="card p-5">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold">{model.display_name || model.name}</div>
                <div className="font-mono text-[11px] text-slate-400">{model.model_id}</div>
              </div>
              <ProviderBadge provider={model.provider} />
            </div>
            <p className="mt-2 min-h-[3rem] text-xs leading-relaxed text-slate-500">{model.description}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {model.is_mock && <span className="badge bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">◉ DEMO MODE</span>}
              <span className={`badge ${model.supports_logprobs ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300" : "bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400"}`}>
                {model.supports_logprobs ? "input logprobs ✓" : "no input logprobs"}
              </span>
              {!model.is_active && <span className="badge bg-slate-200 text-slate-500">inactive</span>}
            </div>
          </div>
        ))}
      </div>
      <div className="card px-5 py-4 text-xs leading-relaxed text-slate-500">
        <b>Note on API models:</b> differential-loss analysis requires <i>input-token</i> log probabilities.
        Chat-style hosted APIs (OpenAI, DeepSeek chat) do not expose them — DiffMIA reports{" "}
        <code className="mono text-rose-500">LOGPROBS_UNSUPPORTED</code> instead of fabricating values. Self-hosted
        serving stacks (vLLM, llama.cpp, TGI) with <code className="mono">/completions</code> echo logprobs can be
        registered with <code className="mono">supports_logprobs: true</code>.
      </div>
    </div>
  );
}
