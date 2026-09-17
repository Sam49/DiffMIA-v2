import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { useTheme } from "../hooks/useTheme";
import { Disclaimer } from "../components/ui";

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button onClick={toggle} className="rounded-lg px-3 py-2 text-sm text-slate-400 hover:text-slate-200">
      {theme === "dark" ? "☀ Light" : "☾ Dark"}
    </button>
  );
}

export default function LandingPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runDemo = async () => {
    setError(null);
    if (!user) {
      navigate("/login");
      return;
    }
    setBusy(true);
    try {
      const result = await api.demoRun();
      navigate(`/experiments/${result.experiment_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Demo could not be started.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">𝓓</div>
          <span className="text-lg font-bold text-white">DiffMIA</span>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {user ? (
            <Link to="/dashboard" className="btn-primary">Open dashboard →</Link>
          ) : (
            <Link to="/login" className="btn-primary">Sign in</Link>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6">
        <section className="py-16 text-center md:py-24">
          <span className="badge bg-brand-950 text-brand-400 ring-1 ring-brand-800">LLM research instrumentation</span>
          <h1 className="mx-auto mt-5 max-w-4xl text-4xl font-black tracking-tight text-white md:text-6xl">
            Detecting LLM benchmark contamination through{" "}
            <span className="bg-gradient-to-r from-brand-400 to-fuchsia-400 bg-clip-text text-transparent">
              differential loss analysis
            </span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-base text-slate-400 md:text-lg">
            DiffMIA measures whether a model assigns lower likelihood to an original benchmark
            example than to semantically equivalent identifier-mutated versions of the same code —
            the behavioural signature consistent with memorization.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <button onClick={runDemo} disabled={busy} className="btn-primary !px-6 !py-3 text-base">
              {busy ? "Starting…" : "▶ Run Demo"}
            </button>
            <Link to={user ? "/dashboard" : "/login"} className="btn-secondary !px-6 !py-3 text-base">
              Start Experiment
            </Link>
          </div>
          {error && <p className="mt-3 text-sm text-rose-400">{error}</p>}
          <p className="mx-auto mt-10 max-w-xl text-xs text-slate-500">
            Demo mode runs entirely locally with a deterministic mock model — no GPU, no API key,
            no model download required.
          </p>
        </section>

        <section className="grid gap-4 md:grid-cols-3" id="sections">
          {[
            {
              title: "The problem",
              body: "LLMs trained on public benchmarks can memorize exact examples, inflating reported accuracy. Static decontamination lists are incomplete and leaky.",
            },
            {
              title: "The method",
              body: "Mutate benchmark code with deterministic identifier renames, then compare the model's per-token negative log likelihood on original vs mutated variants.",
            },
            {
              title: "The signal",
              body: "CI = (mean mutated loss − original loss) / |original loss|. A large positive CI means the model found the original 'easier' — evidence consistent with memorization.",
            },
          ].map((card) => (
            <div key={card.title} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
              <h3 className="text-sm font-bold uppercase tracking-wider text-brand-400">{card.title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-slate-400">{card.body}</p>
            </div>
          ))}
        </section>

        <section className="mt-16">
          <h2 className="text-center text-2xl font-bold text-white">Pipeline</h2>
          <div className="mx-auto mt-6 max-w-4xl overflow-x-auto">
            <ol className="mono flex min-w-max items-center gap-2 text-[11px]">
              {[
                "Benchmark dataset", "AST identifier analysis", "N semantic mutations",
                "Token-level LLM scoring", "Differential loss stats", "CI / Z classification",
                "Dashboard + report",
              ].map((step, index) => (
                <li key={step} className="flex items-center gap-2">
                  <span className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-slate-300">
                    <span className="mr-1 text-brand-500">{index + 1}</span>
                    {step}
                  </span>
                  {index < 6 && <span className="text-slate-600">→</span>}
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="mt-16 grid gap-6 md:grid-cols-2">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
            <h3 className="text-sm font-bold uppercase tracking-wider text-brand-400">Supported models</h3>
            <ul className="mt-3 space-y-2 text-sm text-slate-400">
              <li>• Local Hugging Face Transformers (Llama family, CodeLlama) with CUDA / MPS / CPU</li>
              <li>• OpenAI-compatible endpoints that expose input-token log-probabilities (self-hosted vLLM, llama.cpp, TGI)</li>
              <li>• DeepSeek API detection with honest unsupported-logprobs reporting</li>
              <li>• Deterministic mock provider for zero-setup DEMO MODE</li>
            </ul>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
            <h3 className="text-sm font-bold uppercase tracking-wider text-brand-400">Reproducibility</h3>
            <ul className="mt-3 space-y-2 text-sm text-slate-400">
              <li>• Deterministic mutations from fixed seeds; reruns produce identical variants</li>
              <li>• Dataset hash, model version, thresholds and configuration stored per experiment</li>
              <li>• Cached inference keyed by model + input + configuration</li>
              <li>• Exportable JSON / CSV / Markdown / PDF research reports</li>
            </ul>
          </div>
        </section>

        <section className="mt-16 pb-20">
          <Disclaimer />
          <p className="mt-6 text-center text-xs text-slate-600">
            DiffMIA is a research/evaluation tool. It never executes benchmark code, never fabricates
            likelihood values, and never claims confirmed contamination without external evidence.
          </p>
        </section>
      </main>
    </div>
  );
}
