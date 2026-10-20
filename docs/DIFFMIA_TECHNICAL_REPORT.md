# DiffMIA — Technical Report

**Audience:** engineers, reviewers and researchers who need to understand what this system does, how the code is organised, and what it can and cannot claim.

**How this document was produced:** by reading the source in this repository (file paths cited throughout) and checking claims against a running instance — 139 collected tests, live API responses, and the live SQLite database. Sections marked **Verified** were confirmed by execution; anything I could not confirm is labelled as such rather than asserted.

---

## 1. The problem

Benchmark scores are only meaningful if the benchmark was unseen during training. In practice, popular code benchmarks (HumanEval, MBPP) are scraped from public sources, so a model may have memorised benchmark examples verbatim. That inflates reported capability, and it is hard to detect because training corpora are usually unavailable.

Text-overlap detection needs the corpus. DiffMIA takes a different route: it never inspects training data. It infers *memorisation-like behaviour* from the model's own likelihood function.

---

## 2. The method

### 2.1 Hypothesis

> If a model memorised the exact text of a benchmark snippet, it should assign **lower loss (higher likelihood)** to that original text than to semantically equivalent variants of it, because the original is a familiar token sequence and the variants are not.

### 2.2 Operationalisation

For each benchmark snippet, DiffMIA generates *N* **identifier-renamed** variants. Renaming `total` → `acc` changes the surface token sequence while preserving what the program does. Then it scores the original and every variant under the model, and compares.

```
L_orig     = mean per-token NLL of the original code
L_mut[i]   = mean per-token NLL of variant i

Contamination Index:
    CI = (mean(L_mut) - L_orig) / max(|L_orig|, epsilon)
```

* `CI > 0` → the original is *easier* for the model than its equivalent renames → the signal direction consistent with memorisation.
* `CI ≈ 0` → no differential behaviour.
* `CI < 0` → the original is *harder* — the null/anti-signal.

CI is deliberately a **relative** signal normalised by the original's own loss, so it is comparable across snippets of different absolute difficulty. Source: [metrics.py](backend/app/analysis/metrics.py).

### 2.3 What the design is careful about

Three choices, each traceable to a specific risk:

1. **Renaming must not change behaviour.** Only names *bound inside a function body* are candidates; keywords, builtins, module-level `def`/`class` names, imports, attributes, keyword-argument names, string/comment contents, dunder names and closure-referenced names are never renamed. A new name is only used if it appears nowhere in the module, so it cannot shadow. Source: [identifiers.py](backend/app/mutation/identifiers.py).
2. **The system must never invent likelihoods.** If a provider cannot return input-token log-probabilities, it raises `LOGPROBS_UNSUPPORTED` instead of approximating. Source: [base.py](backend/app/inference/base.py), [deepseek.py](backend/app/inference/deepseek.py).
3. **Code is never executed.** Validation is `ast.parse` + `compile` — both parse-only. The module docstring in [validation.py](backend/app/mutation/validation.py) states this explicitly, and it is confirmed by inspection: no `exec`, `eval` or `subprocess` in the mutation path.

---

## 3. End-to-end walkthrough of one experiment

The whole pipeline lives in [run_pipeline.py](backend/app/workers/run_pipeline.py) as a single synchronous function, `run_experiment(experiment_id)`. It opens its own DB session, so it can be driven by a thread or a queue.

**Stage 1 — mutation generation.** For each dataset item:

* A per-snippet seed is derived as `sha256(mutation_seed : content_hash)` → deterministic and stable across runs.
* For `mutation_index` in `1..mutation_count`, the engine plans renames and applies them.
* Already-produced variants are passed in via `avoid`, so each index contributes **distinct** evidence. If only one variant exists, the index is recorded as `DUPLICATE` rather than silently double-counting one observation.

**Stage 2 — inference.** For each item, one `ScoreRequest` for the original plus one per *valid* mutation. Requests are processed in batches of `experiment.batch_size`:

* Each request gets a cache key; hits are served from the DB with `latency_ms = 0` and `cache_hit = True`.
* Misses go to the provider in one batched call.
* Identical texts inside a batch are deduplicated (`dedupe_by_cache_key`) so the provider is called once per distinct input while every request is still persisted.

**Stage 3 — analysis.** [analyzer.py](backend/app/analysis/analyzer.py) groups runs by snippet, computes per-snippet statistics, builds the baseline, classifies every snippet, and writes `AnalysisResult` rows. Then the experiment is marked `COMPLETED`.

**Progress model:** `QUEUED → mutation_generation → inference → analysis → COMPLETED`. A rerun (`processed_items > 0` or status ≠ `QUEUED`) first deletes prior mutations, runs, and analysis rows so the result is reproducible rather than accumulated. Cancellation is checked between items via `_still_running()`.

---

## 4. The statistics

All helpers are pure functions (no numpy/scipy dependency) in [metrics.py](backend/app/analysis/metrics.py).

| Quantity | Definition | Why |
|---|---|---|
| `contamination_index` | `(mean(mut) − orig) / max(abs(orig), 1e-9)` | Scale-free main signal |
| `absolute_delta` | `mean(mut) − orig` | Interpretable in nats |
| `relative_delta` | `delta / max(abs(orig), eps)` | Same as CI, kept explicit |
| `effect_size` | `(mean(mut) − orig) / std(mutations, ddof=1)` | Signed magnitude in units of mutation spread |
| `z_score` | `leave_one_out_z_score(ci, dataset_cis)` | Outlier-ness within the dataset |
| `z_score_global` | `leave_one_out_z_score(ci, all CIs for this model)` | Outlier-ness across experiments |
| `percentile_rank` | mid-rank, ties get half credit | Robust position in the distribution |

**Important subtlety — `effect_size` is not Cohen's d.** There is only one original sequence, so a two-sample statistic is not available; the code says so in the docstring. Treat it as a signed mutation gap normalised by mutation variability.

**Important subtlety — leave-one-out z-scores.** Including the candidate in its own reference population shrinks its own z-score, which on small datasets can make the configured threshold mathematically unreachable. `leave_one_out_z_score` removes one numerically matching occurrence first.

**Baseline availability.** A z-score is only computed when at least `min_items_for_baseline` (default 3) CIs exist. When unavailable, the snippet is not quietly treated as normal — the classifier falls back to `LOW_EVIDENCE` unless CI is clearly below threshold, and records the reason.

Distributions for the charts (histogram + Gaussian KDE with Silverman bandwidth) are also pure Python, in [distributions.py](backend/app/analysis/distributions.py).

---

## 5. Classification

[classifier.py](backend/app/analysis/classifier.py) maps statistics to five buckets. Defaults:

| Class | Condition |
|---|---|
| `LOW_EVIDENCE` | no original loss, no valid mutations, or >50% of requested mutations failed |
| `NORMAL` | below all thresholds |
| `ELEVATED` | `CI ≥ 0.05` or `Z ≥ 1.3` |
| `POSSIBLE_CONTAMINATION` | `CI > 0.15` or `Z > 2.0` |
| `HIGH_CONTAMINATION_SIGNAL` | `CI > 0.35` or `Z > 3.5` |

Every decision carries a `classification_reason` string (e.g. `CI=0.412 >= 0.35 | Z=3.81 >= 3.5`) which is persisted and shown in the UI, so a classification is always auditable rather than a bare label. Thresholds are configurable per experiment and recorded in `config_json` for reproducibility.

---

## 6. From numbers to a verdict

[conclusion.py](backend/app/analysis/conclusion.py) turns the results bundle into a defensible narrative. Thresholds: **≥30%** flagged → `STRONG_DIFFERENTIAL_SIGNAL`; **≥10%** → `ELEVATED_DIFFERENTIAL_SIGNAL`; otherwise `NO_MATERIAL_SIGNAL`; no analysed snippets → `NO_DATA`.

The conclusion has four mandated sections: the verdict, `OBSERVED` (counts, mean/median/sd, direction, strongest signal, scope, exclusions), `WHAT THIS CANNOT SHOW` (caveats), and `TO CORROBORATE OR FALSIFY` (concrete next steps). When the provider is the mock, a caveat is *inserted* saying the numbers demonstrate the pipeline and support no claim about a real model.

One definition of "the conclusion" is shared by the UI and every export format — [report_service.py](backend/app/services/report_service.py) renders the same object rather than maintaining parallel copies.

---

## 7. Data model

[experiment.py](backend/app/models/experiment.py), with enums in [enums.py](backend/app/models/enums.py):

* **`Experiment`** — configuration (`mutation_count`, `mutation_seed`, `mutation_strength`, `mutation_strategy`, `temperature`, `max_tokens`, `batch_size`, `device`, `config_json`) plus execution state and a reproducibility fingerprint (`dataset_hash`, `model_version`).
* **`Mutation`** — `original_code`, `mutated_code`, `mapping_json` (seed, rename map, attempt count), `validation_status`, `validation_score`. Unique on `(experiment_id, snippet_id, mutation_index)`.
* **`InferenceRun`** — one scored sequence: `variant` (`original`/`mutation`), `mutation_index`, `mean_loss`, `total_loss`, `token_count`, `perplexity`, `truncated`, `cache_hit`, `latency_ms`, `provider`, `model_version`.
* **`TokenLoss`** — optional per-token breakdown when token logging is enabled.
* **`AnalysisResult`** — every statistic above plus `classification`, `classification_reason`, `flagged`. Unique on `(experiment_id, snippet_id)`.
* **`ExperimentLog`** — structured progress/error log with JSON context.

**On `truncated`:** providers explicitly mark sequences that exceeded `max_tokens`, and the first token is never scored (no predecessor), special/padding tokens are excluded. Silent truncation would otherwise make a short original look artificially comparable to a long variant.

---

## 8. Providers

[registry.py](backend/app/inference/registry.py) reads `configs/models.yaml` and instantiates providers. `${VAR}` / `${VAR:-default}` references are resolved from the environment at load time, so secrets stay out of the YAML, the DB and the repo.

| Name in `models.yaml` | Provider | Logprobs | Notes |
|---|---|---|---|
| `diffmia-mock` | `mock` | ✅ | DEMO MODE; deterministic synthetic losses |
| `llama-3-8b`, `llama-3-70b`, `codellama-7b/13b/34b` | `transformers` | ✅ | Local HF causal LMs, lazy torch import, model cache |
| `vllm-local` | `openai_compatible` | ✅ (declared) | `/completions` with `echo` logprobs |
| `openai-gpt` | `openai_compatible` | ❌ | Declared unsupported → fails fast |
| `deepseek-coder` | `deepseek` | ❌ | Chat API has no input logprobs → `LOGPROBS_UNSUPPORTED` |

**The mock provider** ([mock.py](backend/app/inference/mock.py)) is what makes the product demonstrable without a GPU. A snippet is "memorised" if its metadata says so, otherwise by a stable hash against `memorization_ratio` (default 0.35). Memorised originals get a lower loss (shifted by `memorization_delta`, default 0.9); non-memorised items get a roughly symmetric difference so the CI distribution contains both near-zero and clearly positive values. It is marked `is_mock=True` and the UI shows **DEMO MODE**.

**The transformers provider** ([transformers_provider.py](backend/app/inference/transformers_provider.py)) does teacher-forced scoring correctly: logits are shifted by one (`logits[:, :-1]` against `input_ids[:, 1:]`), `log_softmax` is taken, the target token's value is gathered and negated. Requests are chunked against a token budget (6000 on CUDA, 2000 on CPU) to bound memory.

---

## 9. Execution and caching

**Dispatch** ([executor.py](backend/app/workers/executor.py)): `dispatch()` tries Celery first when `WORKER_MODE=celery`, using an explicit kombu connection with `max_retries=0` and a 2 s timeout — Celery's default producer would otherwise run a ~20-retry reconnect loop and stall dispatch for minutes on an unreachable broker. On failure it falls back to the in-process worker thread, which is idempotent and serialises jobs FIFO. Queue depth and active count are exposed via `/metrics`.

**Cache** ([cache_service.py](backend/app/services/cache_service.py)): key = `sha256` over `(schema v1, model key, model version, input text, inference config)`, so a changed model, version or sampling config cannot silently reuse a stale score. Writes are **atomic upserts** (`ON CONFLICT DO UPDATE`) per dialect, with a portable fallback that also inspects pending objects in the session — a select-then-insert broke under same-transaction duplicates because sessions use `autoflush=False`.

---

## 10. API surface

Mounted under `/api` ([router.py](backend/app/api/router.py)). Verified from the decorators:

* **Health/metrics** — `GET /health`, `GET /metrics`
* **Auth** — `POST /auth/login`, `POST /auth/auto-login`, `GET /auth/me`, `POST /auth/change-password`, `GET|POST /users`, `PATCH /users/{id}`, `GET /auth/oauth/status`, `GET /auth/registration/status`, `POST /auth/register`, `POST /auth/verify-email`, `POST /auth/forgot-password`, `POST /auth/resend-verification-email`, `POST /auth/reset-password`, `GET /auth/google/authorize`, `POST /auth/google/link/start`, `POST /auth/google/unlink`, `GET /auth/google/callback`, `POST /auth/oauth/exchange`
* **Datasets** — `GET /datasets`, `GET /datasets/{id}`, `GET /datasets/{id}/items`, `GET /datasets/{id}/export`, `POST /datasets`, `POST /datasets/upload`, `DELETE /datasets/{id}`
* **Models** — `GET /models`, `GET /models/status`, `GET /models/{id}/status`, `POST /models`, `POST /models/{id}/load`, `POST /models/{id}/unload`
* **Experiments** — `GET|POST /experiments`, `GET /experiments/{id}`, `POST /experiments/{id}/run`, `POST /experiments/{id}/cancel`, `GET /experiments/{id}/results`, `/mutations`, `/logs`, and `/export/{json,csv,markdown,pdf}`
* **Snippets** — `GET /snippets/{id}`, `GET /snippets/{id}/mutations`
* **Demo** — `GET /demo/status`, `POST /demo/bootstrap`, `POST /demo/run`

---

## 11. Frontend

React + TypeScript + Vite. Vite proxies `/api` to the backend with `changeOrigin: true` ([vite.config.ts](frontend/vite.config.ts)), so the browser only ever talks to one origin.

Routes ([App.tsx](frontend/src/App.tsx)): `/` (landing), `/oauth/callback`, `/forgot-password`, `/reset-password`, `/verify-email`, then the authenticated shell with `/dashboard`, `/experiments`, `/experiments/:id`, `/experiments/:id/compare`, `/datasets`, `/models`, `/results`, `/reports`, `/settings`, `/users`. Unknown paths redirect to `/`.

Notable components: [ConclusionCard.tsx](frontend/src/components/ConclusionCard.tsx) (verdict + evidence + caveats), [ResultsView.tsx](frontend/src/components/ResultsView.tsx) (sortable per-snippet table), [DiffView.tsx](frontend/src/components/DiffView.tsx) (original vs mutant with the rename map), [charts.tsx](frontend/src/components/charts.tsx) (Recharts).

### Session bootstrap — there is no login page

This build deliberately ships **without** a sign-in screen. [useAuth.tsx](frontend/src/hooks/useAuth.tsx) calls `POST /api/auth/auto-login` at startup when no session is stored, and renders the app. Consequences encoded in the code:

* A stored token the server rejects is replaced automatically, with a 10 s guard in the API client so a rejecting server cannot cause a reload loop.
* If auto-login fails, protected pages render the server's reason plus a retry — not a sign-in form.
* There is no Sign out control, because there is nowhere to sign in again. The account chip reads `ADMIN · auto`.
* `logout()` re-establishes a session immediately when the session was automatic.

The backend refuses to mint a session unless `AUTO_LOGIN_ENABLED=true` (403) and refuses accounts that are missing, disabled or unverified (401 naming the reason). It shares the login rate limiter and logs every session it issues. **This is not a public backdoor: the flag is off by default in `.env.example`.**

---

## 12. Auth, roles and account lifecycle

Roles are `ADMIN`, `RESEARCHER`, `VIEWER` ([enums.py](backend/app/models/enums.py)). Beyond auto-login the system retains a complete account lifecycle:

* **Self-registration** (when `REGISTRATION_ENABLED=true`) with an optional email-verification token required before login.
* **Password reset** via a signed, single-use, time-limited link, with a uniform response to avoid account enumeration.
* **Google sign-in** with signed `state`, a handoff-token exchange, and account linking/unlinking. Provisioned Google users get `OAUTH_DEFAULT_ROLE` (`VIEWER` by default).
* **Admin Users page** — promote roles, enable/disable, and see auth provider, email-verified status and Google linkage.

Two hardening details worth noting, both in [google_oauth.py](backend/app/core/google_oauth.py) / [user.py](backend/app/models/user.py): `google_sub` is **unique when set** via a partial index (`WHERE google_sub != ''` — a plain UNIQUE is impossible because every local account legitimately shares the empty string), and provisioning **fails closed** when a Google token carries no subject, because the empty subject would otherwise match a local account.

---

## 13. Reporting and exports

[report_service.py](backend/app/services/report_service.py) produces four formats from one bundle:

* **JSON** — the full structured bundle (experiment, config, stats, per-snippet analyses, conclusion, disclaimer, generated-at, software version).
* **CSV** — flat per-snippet table with all statistics and the classification reason.
* **Markdown** — experiment config, results summary, conclusion, methodology, per-snippet table, top flagged examples, reproducibility section.
* **PDF** — ReportLab, server-side, no browser: config table, methodology, conclusion, results table, top flagged examples, then a reproducibility & limitations page.

Every export embeds the same `DISCLAIMER`: these are *contamination signals*, never *confirmed contamination*. The Markdown export ends with the line *"DiffMIA is a research/evaluation tool. It never executes benchmark code."*

---

## 14. Testing

**Verified:** `pytest --collect-only` reports **139 tests** across **16 test modules** (plus `conftest.py`), including dedicated suites for the mutation engine, the statistical classifier, the analysis pipeline, the mock provider, the OpenAI-compatible provider, dataset ingestion and seeding, OAuth and account linking, registration, password reset, caching, validation, and the API. Tests pin `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` to empty in [conftest.py](backend/tests/conftest.py) so a real client in `.env` can never flip test outcomes.

---

## 15. Deployment

`docker-compose.yml` defines five services — **frontend**, **backend**, **worker** (`celery -A app.workers.tasks:celery_app worker`), **postgres:16-alpine**, **redis:7-alpine** — with an optional NVIDIA GPU overlay (`docker-compose.gpu.yml`). A first-party Streamlit exploration app lives in [streamlit/app.py](streamlit/app.py).

The frontend container is a two-stage build: `node:20-alpine` compiles the bundle, then `nginx:1.27-alpine` serves it with [nginx.conf](frontend/nginx.conf) proxying `/api` — so no backend URL is baked into the bundle. Compose publishes it on `${FRONTEND_PORT:-8080} → nginx :80`.

For local, non-Docker use the app runs with zero infrastructure: SQLite + the in-process thread worker. **Verified live:** the backend reports `{"status":"ok","database":"ok","worker":"celery","environment":"production"}` and `google_enabled: true`. The live SQLite DB at `backend/data/diffmia.db` held, at the time of this review, **3 datasets, 4 completed experiments and 2 user accounts** — these are working data that grow as you run experiments, not fixed seed values.

---

## 16. Limitations and threats to validity

Stated in the code and repeated in every report, because they are the difference between a useful instrument and a false accusation:

1. **Behaviour ≠ provenance.** A differential loss is behavioural. Identifier familiarity from *similar* code, tokenisation effects from renaming, code-style priors and distributional differences all produce the same pattern.
2. **Interpretation:** a flag is a prompt for corroboration, not a verdict.
3. **Sparse identifiers weaken evidence.** Snippets with few renameable names yield fewer distinct mutants; the requested mutation count is an upper bound on distinct variants, and heavy failure rates push the snippet to `LOW_EVIDENCE`.
4. **The mock provider proves the pipeline, not the model.** Any demo run using it demonstrates measurement mechanics only.
5. **Python only, today.** `identifier_rename` is implemented for Python; experiment creation rejects datasets containing non-Python items rather than silently skipping them.

---

## 17. Verified inconsistencies and gaps

Found while reading; none are fatal, but they are worth fixing and are recorded here rather than glossed over.

1. **`ValidationStatus` is missing `DUPLICATE`.** [engine.py](backend/app/mutation/engine.py#L178) sets `result.status = "DUPLICATE"`, and the pipeline persists it, but [enums.py](backend/app/models/enums.py#L48) declares only `VALID`, `INVALID`, `RETRY_LIMIT`, `NO_CANDIDATES`. The column is a plain `String`, so storage works — but any future code that validates or filters against the enum would treat real rows as unknown.
2. **`RETRY_LIMIT` is declared but never emitted.** Dead enum member; the engine reports `INVALID` with an attempt count instead.
3. **`Mutation.validation_score` is written but never read.** It is stored and exposed in a schema, yet no decision path consumes it, so a low-fidelity mutation (partial rename coverage) does not currently influence classification.
4. **`WORKER_MODE=celery` with no broker.** The fallback in `dispatch()` is correct and logged, so jobs still run — but the log line *"Worker mode is 'celery' — run `celery ...` separately"* appears on every boot while the system is in fact using the thread worker. This is confusing during incident triage (it cost time in this project).

---

## 18. Corrections to the earlier project report

`DIFFMIA_PROJECT_REPORT.md` (untracked, at the repo root) predates recent work and contains claims that do not match this code. I left that file untouched and record the differences instead:

| Earlier report | Actual |
|---|---|
| React dashboard on port **8080** | Not wrong, but incomplete: **8080** is the Docker host port (`${FRONTEND_PORT:-8080} → nginx :80`). The local dev server is **5173**, proxying `/api` → 8000 |
| Effect size described as **Cohen's d** | Explicitly **not** Cohen's d — there is one original sequence; it is a signed gap normalised by mutation spread |
| *"Every mutation passes `ast.parse` + **runtime execution check**"* | **No execution ever happens** — `ast.parse` + `compile` (parse-only) plus structural AST equivalence. The report's wording overstated, and mis-stated, a deliberate safety property |
| **133 tests** | **139 tests** |
| Global baselines: *"optional cross-dataset normalization"* | `z_score_global` is computed against CIs from **other experiments on the same model**, not cross-dataset normalisation |
| No mention of the login page being removed | The app now has **no login page**; startup uses `POST /auth/auto-login` guarded by `AUTO_LOGIN_ENABLED` |
| Account features limited to JWT + OAuth | Plus **email verification**, **password reset**, and an **admin Users page** |

---

## 19. Summary

DiffMIA is a research instrument that converts an unobservable question (*was this example in the training data?*) into a measurable one (*is the original easier for the model than its equivalent renames?*), with statistics chosen to make the answer honest on small samples, a provider layer that refuses to fabricate likelihoods, deterministic mutations for reproducibility, and reports that state their own limits up front. Its weakest points are the ones inherent to the method — behavioural evidence is not provenance — and they are documented in the code, in the UI and in every export rather than buried.

*Report generated from direct source inspection and live verification.*
