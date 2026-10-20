# DiffMIA Project Report

## Executive Summary

**DiffMIA (Differential Loss Analysis for LLM Data Contamination Detection)** is a production-ready research platform designed to detect benchmark data contamination in Large Language Models (LLMs) through behavioral analysis of token-level likelihood differentials. Unlike traditional approaches that rely on external training data provenance or string matching, DiffMIA measures how models behave on original benchmark code versus semantically equivalent mutations — providing evidence of memorization-like behavior directly from model internals.

---

## 1. Problem Statement

### The Data Contamination Crisis

LLM benchmark evaluation faces a fundamental threat: **data contamination** (also called data leakage). This occurs when benchmark examples appear in a model's training corpus, artificially inflating performance scores. Since popular benchmarks (HumanEval, MBPP, etc.) are scraped from public GitHub repositories, web crawls, and instruction-tuning datasets, contamination is nearly inevitable and difficult to detect.

**Traditional detection methods fail because:**
- Training data is often proprietary or unavailable for inspection
- String matching misses semantic equivalents (renamed variables, reformatted code)
- N-gram overlap doesn't capture behavioral memorization
- No ground truth labels exist for most models

---

## 2. Core Innovation: The Differential-Loss Hypothesis

DiffMIA operationalizes a novel scientific hypothesis:

> **If a model memorized the exact text of a benchmark snippet, it should assign significantly LOWER loss (higher likelihood) to that original than to semantically equivalent, never-seen mutations of it.**

### Key Insight
- **Loss = mean per-token negative log-likelihood** over scored tokens
- **Contamination Index (CI)** = (MeanMutatedLoss − L_orig) / max(|L_orig|, ε)
- CI > 0 → Original is "easier" for model → evidence consistent with memorization
- CI ≈ 0 → No differential behavior
- CI < 0 → Original is harder → null/anti-signal

This approach **never requires training data access** — everything derives from the model's own internal likelihood behavior.

---

## 3. System Architecture

### 3.1 Three-Tier Interface
| Interface | Purpose | Port |
|-----------|---------|------|
| **React Dashboard** | Production UI for researchers/analysts | 8080 |
| **Streamlit Research App** | Rapid prototyping & exploration | 8501 |
| **REST API (OpenAPI)** | Programmatic integration, automation | 8000 |

### 3.2 Backend Pipeline (FastAPI + Celery)

```
Benchmark Item → Dataset Parser → Original Code
                                      ↓
                    ┌────────────────┴────────────────┐
                    ↓                                 ↓
            Mutation Engine                    LLM Inference
            (AST-based rename)              (Token log-probs)
                    ↓                                 ↓
                    └────────────────┬────────────────┘
                                     ↓
                          Loss per Variant (NLL/Perplexity)
                                     ↓
                          Differential Analysis (CI, z-score, effect size)
                                     ↓
                          Baseline Normalization (dataset-level, leave-one-out)
                                     ↓
                          Statistical Classification
                                     ↓
                          Database → Dashboard/API/Reports
```

### 3.3 Inference Provider Registry (Provider-Agnostic)

| Provider | Type | Log-Probs Support | Use Case |
|----------|------|-------------------|----------|
| **MockLLMProvider** | Deterministic synthetic | ✅ Full | Demo, testing, CI/CD |
| **TransformersProvider** | Local HF models | ✅ Full | Llama 3, CodeLlama, etc. |
| **OpenAICompatibleProvider** | vLLM, llama.cpp, TGI | ✅ If `echo=true` | API-backed local serving |
| **DeepSeekProvider** | DeepSeek API | ❌ Chat only | Flagged as `LOGPROBS_UNSUPPORTED` |

**Critical design principle:** Providers that cannot expose input-token log-probabilities are **honestly reported as unsupported** — DiffMIA never fabricates likelihood values.

---

## 4. Key Features

### 4.1 Deterministic Mutation Engine
- **AST-based identifier renaming** using Python's `ast` module — guarantees semantic equivalence
- **Validation**: Every mutation passes `ast.parse` + runtime execution check
- **Deduplication**: Mutations distinct from each other and original; duplicates marked `DUPLICATE` and excluded
- **Reproducibility**: Seeded RNG (default 42), per-mutation metadata persisted
- **Configurable**: Mutation count (1–20), strength (0.0–1.0), strategy

### 4.2 Statistical Analysis Pipeline
- **Per-snippet metrics**: CI, absolute/relative loss deltas, median/std of mutations
- **Effect sizes**: Standardized mutation-gap effect size (Cohen's d)
- **Dataset-normalized baselines**: Leave-one-out z-scores (candidate cannot dilute its own anomaly)
- **Percentile ranks**: Tie-aware mid-rank within dataset distribution
- **Global baselines**: Optional cross-dataset normalization

### 4.3 Configurable Classification Thresholds
| Class | Condition (default) |
|-------|---------------------|
| `LOW_EVIDENCE` | Loss below noise floor |
| `NORMAL` | Baseline range |
| `ELEVATED` | CI ≥ 0.05 **or** z ≥ 1.3 |
| `POSSIBLE_CONTAMINATION` | CI > 0.15 **or** z > 2.0 |
| `HIGH_CONTAMINATION_SIGNAL` | CI > 0.35 **or** z > 3.5 |

*All thresholds configurable per experiment and recorded for reproducibility.*

### 4.4 Inference Caching (Atomic Upsert)
- **Content-addressable keys**: Cache by (model, text, config hash)
- **Atomic upsert**: Concurrent workers scoring same text → single cache row, no duplicate-key errors
- **Reuse safety**: Cache invalidated on model/config changes
- **Token-loss storage**: Optional per-token breakdown for deep analysis

### 4.5 Async Experiment Execution
- **Thread mode**: In-process thread pool (simple local dev)
- **Celery mode**: Dedicated Redis-backed workers (production, multi-GPU scale-out)
- **Live progress**: `QUEUED → mutation_generation → inference → analysis → COMPLETED`
- **Cancellation**: Graceful interrupt at any stage

### 4.6 Reproducibility & Audit Trail
Every experiment persists:
- Random seeds (mutation, sampling)
- Model ID + tokenizer version + provider config
- Dataset fingerprint (content hash)
- Full threshold configuration
- Timestamps for each pipeline stage
- Hardware/device info

### 4.7 Comprehensive Reporting
- **Interactive Dashboard**: Charts (distributions, per-snippet tables, diff views)
- **Side-by-side Diff View**: Original vs mutation with rename mappings
- **Exports**: JSON, CSV, Markdown, PDF (ReportLab)
- **Conclusion Narrative**: Auto-generated with verdict, evidence level, flagged share, strongest signal, caveats, and concrete next steps for corroboration

### 4.8 Authentication & Access Control
- **JWT-based auth** with roles: `ADMIN`, `RESEARCHER`, `VIEWER`
- **Google OAuth SSO** (optional, one-click login)
- **Self-service registration** (optional, email verification)
- **Password reset** (secure, constant-time responses)
- **Rate limiting**: Sliding window per IP+endpoint
- **Audit logging**: Structured JSON logs with request IDs

### 4.9 Bundled Benchmarks (Idempotent Import)
| Dataset | Items | Source | License |
|---------|-------|--------|---------|
| `humaneval` | 164 | OpenAI HumanEval | MIT |
| `mbpp_sanitized` | 420 | Google MBPP | CC-BY-4.0 |
| `diffmia_sample_algorithms` | 12 | First-party | Project license |

Auto-imported on startup via content-hash deduplication — restart-safe, no duplicates.

---

## 5. Comparison with Existing Solutions

| Feature | DiffMIA | Traditional N-gram Overlap | String Matching | Training Data Provenance | Perplexity-only Scoring |
|---------|---------|---------------------------|-----------------|--------------------------|------------------------|
| **No training data needed** | ✅ | ❌ | ❌ | ❌ | ✅ |
| **Semantic equivalence aware** | ✅ (AST) | ❌ | ❌ | N/A | ❌ |
| **Behavioral evidence (not textual)** | ✅ | ❌ | ❌ | ❌ | Partial |
| **Statistical rigor (CI, z-score, effect size)** | ✅ | ❌ | ❌ | N/A | ❌ |
| **Dataset-normalized baselines** | ✅ (leave-one-out) | ❌ | ❌ | N/A | ❌ |
| **Provider-agnostic (local + API)** | ✅ | N/A | N/A | N/A | Limited |
| **Honest about log-probs limitations** | ✅ | N/A | N/A | N/A | ❌ |
| **Reproducible (seeds, configs, versions)** | ✅ | Partial | Partial | N/A | Partial |
| **Async, production-ready** | ✅ (Celery) | ❌ | ❌ | N/A | ❌ |
| **Multi-format reports** | ✅ (4 formats) | ❌ | ❌ | N/A | ❌ |
| **Interactive diff visualization** | ✅ | ❌ | ❌ | N/A | ❌ |
| **Open source / self-hostable** | ✅ (MIT) | Varies | Varies | Usually proprietary | Varies |

### Why DiffMIA is Superior

1. **Measures what matters**: Model *behavior* (likelihood), not surface text overlap
2. **Controls for confounders**: Semantic equivalence via AST mutation isolates memorization signal from tokenization/style effects
3. **Statistically principled**: Leave-one-out baselines, effect sizes, configurable thresholds — not heuristic rules
4. **Honest about limitations**: Explicitly flags providers that can't support the method; classifies as "evidence consistent with memorization" — never "proven contamination"
5. **Production-grade**: Not a research script — full auth, async workers, caching, monitoring, Docker deployment
6. **Extensible provider registry**: Add new LLMs without code changes (YAML config)
7. **Three interfaces**: Serves researchers (Streamlit), analysts (React), and automation (API) simultaneously

---

## 6. Technical Stack

| Layer | Technology |
|-------|------------|
| **Backend API** | FastAPI 0.115+, Python 3.10+ |
| **Database** | PostgreSQL (prod) / SQLite (dev) via SQLAlchemy 2.0 + Alembic |
| **Async Workers** | Celery + Redis |
| **Inference** | Hugging Face Transformers, vLLM/llama.cpp (OpenAI-compatible), DeepSeek |
| **Frontend** | React 18 + TypeScript + Vite + Tailwind CSS + Recharts |
| **Research UI** | Streamlit + Plotly/Altair |
| **Containerization** | Docker Compose (CPU + GPU overlay) |
| **Testing** | pytest (133 tests), coverage: mutation, analysis, API, auth, pipeline |

---

## 7. Deployment Options

### 7.1 Local Development (No Docker)
```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
DATABASE_URL="sqlite:///./data/dev.db" uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

### 7.2 Docker Compose (Production-Ready)
```bash
docker compose up --build                    # CPU stack
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build  # + NVIDIA GPU
```

Services: `frontend` (nginx), `backend` (FastAPI + migrations), `worker` (Celery), `postgres`, `redis`

### 7.3 GPU Inference
- Requires NVIDIA Container Toolkit
- Set `DEVICE=cuda` in `.env` or compose
- Register transformers model in `configs/models.yaml`
- Scale workers: `docker compose up -d --scale worker=N` (one per GPU)

---

## 8. Research Limitations (Honest Disclosure)

Per the project documentation, DiffMIA **cannot prove** training data provenance. Differential loss can also reflect:
- Identifier/format familiarity from *similar* (not identical) code
- Tokenization boundary changes from renaming
- Distributional differences and naming convention priors
- Mutation artifacts or imperfect semantic equivalence
- Prompt/style effects independent of content memorization

**Use case**: Prioritize suspicious items for manual inspection + external verification — **never as standalone accusation**.

---

## 9. Project Structure

```
diffmia/
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── api/               # REST endpoints
│   │   ├── analysis/          # CI, z-score, classifier, baselines
│   │   ├── inference/         # Provider registry (mock, HF, OpenAI, DeepSeek)
│   │   ├── mutation/          # AST-based identifier renaming
│   │   ├── workers/           # Celery tasks + thread executor
│   │   ├── services/          # Business logic (datasets, experiments, cache, reports)
│   │   ├── schemas/           # Pydantic models
│   │   ├── db/                # SQLAlchemy models + session
│   │   └── core/              # Config, security, logging, exceptions
│   ├── tests/                 # 133 unit/integration tests
│   └── requirements*.txt
├── frontend/                   # React + TypeScript + Vite
│   ├── src/
│   │   ├── pages/             # 15 pages (Dashboard, Experiments, Models, etc.)
│   │   ├── components/        # Reusable UI (charts, diff view, conclusion card)
│   │   └── hooks/             # Auth, API clients
│   └── package.json
├── streamlit/                  # Research app
├── configs/models.yaml         # Model registry (YAML → DB on startup)
├── datasets/                   # Bundled benchmarks (JSONL)
├── docker-compose.yml          # CPU stack
├── docker-compose.gpu.yml      # GPU overlay
└── .env.example                # Configuration template
```

---

## 10. Conclusion

DiffMIA represents a **paradigm shift** in contamination detection:
- From **textual overlap** → **behavioral differential analysis**
- From **heuristic rules** → **statistical classification with baselines**
- From **research scripts** → **production platform** with auth, async, caching, reporting
- From **single-provider** → **provider-agnostic registry**
- From **opaque results** → **auditable, reproducible experiments with caveats**

It is the first system to make differential-loss contamination detection **accessible, rigorous, and deployable** — enabling the LLM community to evaluate benchmarks with honest, evidence-based signals rather than blind trust.

---

*Report generated from codebase analysis (September 2026)*