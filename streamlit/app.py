"""DiffMIA — Streamlit research interface.

A lightweight research dashboard that drives the DiffMIA backend through its
public REST API. This keeps a single source of truth: the Streamlit app talks
to exactly the same endpoints as the React frontend, so it works unchanged in
DEMO MODE and against a deployed backend.

Run (with the backend reachable, default http://127.0.0.1:8000):

    streamlit run streamlit/app.py

Configuration (optional, environment variables or .streamlit/secrets.toml):

    DIFFMIA_API_URL   backend base URL, default http://127.0.0.1:8000/api
    DIFFMIA_USERNAME  default admin
    DIFFMIA_PASSWORD  default admin
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(
    page_title="DiffMIA · Research",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_API = os.environ.get("DIFFMIA_API_URL", "http://127.0.0.1:8000/api")
DISCLAIMER = (
    "Contamination scores indicate **behavioral evidence consistent with memorization**. "
    "They do **not** establish the provenance of training data. A high differential loss "
    "can also arise from identifier familiarity, tokenization effects, code-style "
    "familiarity, or mutation artifacts."
)


def _cfg(key: str, default: str) -> str:
    return os.environ.get(key) or st.secrets.get(key, default)  # type: ignore[attr-defined]


@dataclass
class Api:
    base: str
    token: str

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, **params: Any) -> Any:
        resp = requests.get(f"{self.base}{path}", params=params, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        resp = requests.post(f"{self.base}{path}", json=json or {}, headers=self._headers(), timeout=600)
        resp.raise_for_status()
        return resp.json()


# ── Sidebar: connection + experiment configuration ─────────────────
st.sidebar.title("🧬 DiffMIA")
st.sidebar.caption("LLM benchmark contamination detection · differential loss analysis")
st.sidebar.markdown("---")

with st.sidebar.expander("Backend connection", expanded=True):
    api_url = st.text_input("API base URL", value=_cfg("DIFFMIA_API_URL", DEFAULT_API))
    username = st.text_input("Username", value=_cfg("DIFFMIA_USERNAME", "admin"))
    password = st.text_input("Password", value=_cfg("DIFFMIA_PASSWORD", "admin"), type="password")


def login(api_url: str, username: str, password: str) -> Api | None:
    try:
        resp = requests.post(
            f"{api_url}/auth/login",
            json={"username": username, "password": password},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        api = Api(base=api_url.rstrip("/"), token=payload["access_token"])
        st.session_state["api"] = api
        st.session_state["user"] = payload.get("user", {})
        return api
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not reach the backend at {api_url}: {exc}")
        return None


if "api" not in st.session_state:
    st.session_state["api"] = None
if st.sidebar.button("Connect", type="primary", use_container_width=True):
    login(api_url, username, password)

api: Api | None = st.session_state["api"]  # type: ignore[assignment]
if api is None:
    st.title("🧬 DiffMIA Research")
    st.info(
        "Connect to the DiffMIA backend to begin. Start it with:\n\n"
        "```bash\n# terminal 1 — backend (DEMO MODE by default)\n"
        "cd backend && uvicorn app.main:app --port 8000\n"
        "```\n\nThen press **Connect**. DEMO MODE uses the deterministic mock provider — "
        "no GPU, Hugging Face token, or API key is required."
    )
    st.stop()

user = st.session_state.get("user", {})
role = (user or {}).get("role", "")
is_researcher = role in ("ADMIN", "RESEARCHER")

try:
    health = requests.get(f"{api.base}/health", timeout=10).json()
    st.sidebar.success(f"Connected · {health.get('app', 'DiffMIA')} v{health.get('version', '')}")
    try:
        demo = requests.get(f"{api.base}/demo/status", timeout=10).json()
        is_demo = bool(demo.get("mode") == "DEMO" and demo.get("model_ready"))
    except Exception:  # noqa: BLE001
        is_demo = False
    if is_demo:
        st.sidebar.warning("DEMO MODE — deterministic synthetic losses, no real model.")
except Exception:  # noqa: BLE001
    st.sidebar.warning("Backend unreachable — check the API URL.")

try:
    models = api.get("/models")["items"]
    datasets = api.get("/datasets")["items"]
except Exception as exc:  # noqa: BLE001
    st.error(f"Failed to list models/datasets: {exc}")
    st.stop()

model_names = [m["name"] for m in models]
dataset_labels = [f'{d["id"]} · {d["name"]} ({d["item_count"]} items)' for d in datasets]

st.sidebar.markdown("---")
st.sidebar.subheader("New experiment")

st.sidebar.caption("Model")
model_name = st.sidebar.selectbox("Model", model_names)
model = next(m for m in models if m["name"] == model_name)
if model.get("is_mock"):
    st.sidebar.caption("🟡 **DEMO MODE** — mock provider")
elif not model.get("supports_logprobs"):
    st.sidebar.warning("This provider does not expose token log-probabilities — "
                       "differential-loss analysis is unsupported.")
st.sidebar.caption("Dataset")
dataset_label = st.sidebar.selectbox("Dataset", dataset_labels)
dataset_id = int(dataset_label.split(" · ")[0])

mutation_count = st.sidebar.slider("Mutations per snippet", 1, 10, 5)
mutation_seed = st.sidebar.number_input("Mutation seed", value=42, step=1)
mutation_strength = st.sidebar.slider("Mutation strength", 0.1, 1.0, 0.3, step=0.05)
batch_size = st.sidebar.selectbox("Batch size", [1, 2, 4, 8, 16], index=2)
temperature = st.sidebar.number_input("Temperature", 0.0, 2.0, 0.0, step=0.1)
device = st.sidebar.text_input("Device", value="auto")

run_clicked = st.sidebar.button(
    "▶ Run experiment", type="primary", use_container_width=True, disabled=not is_researcher
)
if not is_researcher:
    st.sidebar.caption("Your role is VIEWER — only researchers can launch experiments.")

# ── Main area ──────────────────────────────────────────────────────
st.title("🧬 DiffMIA Research Dashboard")
st.caption("Detecting LLM benchmark contamination through differential loss analysis.")

c1, c2, c3 = st.columns([1, 1, 3])
with c1:
    st.metric("Model", model_name)
with c2:
    st.metric("Dataset", dataset_id)
with c3:
    st.info(DISCLAIMER, icon="ℹ️")


def run_experiment() -> dict[str, Any]:
    payload = {
        "name": f"streamlit-{datetime.now():%Y%m%d-%H%M%S}",
        "description": "Launched from the Streamlit research interface.",
        "dataset_id": dataset_id,
        "model_id": model["id"],
        "mutation_count": int(mutation_count),
        "mutation_seed": int(mutation_seed),
        "mutation_strength": float(mutation_strength),
        "mutation_strategy": "identifier_rename",
        "temperature": float(temperature),
        "batch_size": int(batch_size),
        "device": device or None,
    }
    created = api.post("/experiments", json=payload)
    experiment_id = created["id"]
    api.post(f"/experiments/{experiment_id}/run", json={})
    return _poll(experiment_id)


def _poll(experiment_id: int) -> dict[str, Any]:
    progress_bar = st.progress(0.0, text="Queued…")
    status_placeholder = st.empty()
    last_stage = ""
    while True:
        detail = api.get(f"/experiments/{experiment_id}")
        status = detail["status"]
        stage = detail["current_stage"]
        total = detail["total_items"] or 1
        processed = detail["processed_items"]
        message = detail["progress_message"] or ""
        fraction = min(processed / total, 1.0)
        progress_bar.progress(fraction, text=f"{stage} — {processed}/{total}: {message}")
        status_placeholder.caption(f"Status: **{status}** · {stage}")
        if status == "COMPLETED":
            progress_bar.progress(1.0, text="Completed.")
            return api.get(f"/experiments/{experiment_id}/results")
        if status in ("FAILED", "CANCELLED"):
            st.error(f"Experiment {status}: {detail.get('error_message') or detail.get('error_code')}")
            raise RuntimeError(f"experiment {status}")
        time.sleep(0.6)


if run_clicked:
    with st.spinner("Running experiment…"):
        results = run_experiment()
    st.session_state["results"] = results
    st.session_state["experiment_id"] = results["experiment"]["id"]
    st.toast(f"Experiment {results['experiment']['id']} completed", icon="✅")

# Allow loading an existing completed experiment for inspection.
try:
    experiments = api.get("/experiments", limit=200)["items"]
    completed = [e for e in experiments if e["status"] == "COMPLETED"]
except Exception:  # noqa: BLE001
    completed = []
if completed:
    with st.expander("📂 Load a completed experiment", expanded=("results" not in st.session_state)):
        options = {f'#{e["id"]} · {e["name"]} ({e["model_name"]}, {e["dataset_name"]})': e["id"] for e in completed}
        choice = st.selectbox("Completed experiments", list(options))
        if st.button("Load results", type="primary"):
            st.session_state["results"] = api.get(f"/experiments/{options[choice]}/results")
            st.rerun()

results = st.session_state.get("results")
if results is None:
    st.info(
        "Configure the experiment in the sidebar and press **▶ Run experiment**, "
        "or load an existing completed experiment above.\n\n"
        "The pipeline compares the model's token-level likelihood on original benchmark "
        "code against semantically equivalent identifier-renamed mutations."
    )
    st.stop()

exp = results["experiment"]
stats = results["stats"]
analyses = results["analyses"]
distributions = results["distributions"]
classifications = results["classifications"]
pairs = results["pairs"]

st.markdown(f"## Experiment #{exp['id']} — {exp['name']}")
meta_cols = st.columns(5)
meta_cols[0].metric("Model", exp["model"]["display_name"] if exp.get("model") else "")
meta_cols[1].metric("Dataset", exp["dataset"]["name"] if exp.get("dataset") else "")
meta_cols[2].metric("Mutations", f'{exp["mutation_count"]} × seed {exp["mutation_seed"]}')
meta_cols[3].metric("Batch size", exp["batch_size"])
meta_cols[4].metric("Temperature", f'{exp["temperature"]:g}')

st.markdown("### Global statistics")
gcols = st.columns(6)
gcols[0].metric("Analyzed", stats["analyzed_count"])
gcols[1].metric("Flagged", stats["flagged_count"])
gcols[2].metric("High-signal", stats["high_signal_count"])
gcols[3].metric("Mean CI", f'{stats["mean_ci"]:.4f}' if stats["mean_ci"] is not None else "—")
gcols[4].metric("Median CI", f'{stats["median_ci"]:.4f}' if stats["median_ci"] is not None else "—")
gcols[5].metric("Std CI", f'{stats["std_ci"]:.4f}' if stats["std_ci"] is not None else "—")

_ = st.columns(1)[0].markdown(
    "**Contamination Index (CI)** = (mean mutated loss − original loss) / max(|original loss|, ε). "
    "A positive CI means the original reads as *easier* to the model than its equivalent "
    "mutations — consistent with memorization."
)

# ── Charts ─────────────────────────────────────────────────────────
st.markdown("### Distributions")
d1, d2 = st.columns(2)

with d1:
    st.markdown("**KDE loss distribution — original vs mutations**")
    if distributions["original_loss"]["kde_x"] and distributions["mutation_loss"]["kde_x"]:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=distributions["original_loss"]["kde_x"], y=distributions["original_loss"]["kde_y"],
            mode="lines", name="Original loss", line=dict(color="#2563eb", width=2)))
        fig.add_trace(go.Scatter(
            x=distributions["mutation_loss"]["kde_x"], y=distributions["mutation_loss"]["kde_y"],
            mode="lines", name="Mean mutated loss", line=dict(color="#f59e0b", width=2)))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="mean per-token NLL", yaxis_title="density")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No loss distribution available.")

with d2:
    st.markdown("**Contamination Index distribution**")
    if distributions["ci"]["histogram_x"]:
        fig = px.bar(x=distributions["ci"]["histogram_x"], y=distributions["ci"]["histogram_y"],
                     labels={"x": "Contamination Index", "y": "count"}, color_discrete_sequence=["#8b5cf6"])
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No CI distribution available.")

d3, d4 = st.columns(2)

with d3:
    st.markdown("**Z-score distribution**")
    if distributions["z"]["histogram_x"]:
        fig = px.bar(x=distributions["z"]["histogram_x"], y=distributions["z"]["histogram_y"],
                     labels={"x": "Dataset-normalized Z-score", "y": "count"},
                     color_discrete_sequence=["#06b6d4"])
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("Z-scores require ≥3 analyzed snippets with variance.")

with d4:
    st.markdown("**Original vs mutation loss (per snippet)**")
    if pairs:
        df_pairs = pd.DataFrame(pairs, columns=["original_loss", "mean_mutation_loss"])
        max_val = max(df_pairs.max().max(), 1e-9)
        fig = px.scatter(df_pairs, x="original_loss", y="mean_mutation_loss",
                         opacity=0.65, color_discrete_sequence=["#10b981"])
        fig.add_trace(go.Scatter(x=[0, max_val], y=[0, max_val], mode="lines",
                                 line=dict(dash="dot", color="#64748b"), name="y = x"))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="original loss", yaxis_title="mean mutated loss")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No per-snippet pairs available.")

# ── Ranking ────────────────────────────────────────────────────────
st.markdown("### Contamination ranking")
ranked = [a for a in analyses if a["contamination_index"] is not None]
ranked = sorted(ranked, key=lambda a: a["contamination_index"], reverse=True)[:20]
if ranked:
    top_df = pd.DataFrame([
        {
            "snippet": a["external_id"],
            "CI": round(a["contamination_index"], 4),
            "z": round(a["z_score"], 3) if a["z_score"] is not None else None,
            "classification": a["classification"],
        }
        for a in ranked
    ])
    fig = px.bar(top_df.sort_values("CI"), x="CI", y="snippet", orientation="h",
                 color="classification", color_discrete_map={
                     "NORMAL": "#94a3b8", "LOW_EVIDENCE": "#cbd5e1", "ELEVATED": "#f59e0b",
                     "POSSIBLE_CONTAMINATION": "#f97316", "HIGH_CONTAMINATION_SIGNAL": "#dc2626",
                 })
    fig.update_layout(height=max(320, 22 * len(top_df)), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

# ── Detailed table ─────────────────────────────────────────────────
st.markdown("### Per-snippet results")
table_rows = [
    {
        "snippet": a["external_id"],
        "original_loss": a["original_loss"],
        "mutation_loss": a["mean_mutation_loss"],
        "CI": a["contamination_index"],
        "z_score": a["z_score"],
        "effect_size": a["effect_size"],
        "percentile": a["percentile_rank"],
        "classification": a["classification"],
        "flagged": a["flagged"],
    }
    for a in analyses
]
table_df = pd.DataFrame(table_rows)
if not table_df.empty:
    flagged_filter = st.multiselect("Classification filter", sorted(set(table_df["classification"])),
                                    default=[c for c in sorted(set(table_df["classification"]))])
    shown = table_df[table_df["classification"].isin(flagged_filter)]
    st.dataframe(
        shown.style.format(
            {"original_loss": "{:.4f}", "mutation_loss": "{:.4f}", "CI": "{:.4f}",
             "z_score": "{:.2f}", "effect_size": "{:.2f}", "percentile": "{:.1f}"},
            na_rep="—"),
        use_container_width=True,
        height=min(420, 35 * (len(shown) + 1)),
    )

# ── Snippet drill-down ─────────────────────────────────────────────
if analyses:
    with st.expander("🔬 Inspect a snippet (original vs mutations)"):
        options = {f'{a["external_id"]} — CI {a["contamination_index"]:.4f}' if a["contamination_index"] is not None else a["external_id"]: a for a in analyses}
        pick = st.selectbox("Snippet", list(options))
        row = options[pick]
        st.markdown("**Problem statement**")
        st.write(row["problem_statement"] or "—")
        left, right = st.columns(2)
        left.markdown("**Original code**")
        left.code(row["code"], language="python")
        try:
            mutations = api.get(f'/experiments/{exp["id"]}/mutations', snippet_id=row["snippet_id"])["items"]
        except Exception:  # noqa: BLE001
            mutations = []
        if mutations:
            idx = st.selectbox("Mutation", range(1, len(mutations) + 1), format_func=lambda i: f"Mutation {i}")
            mutation = next(m for m in mutations if m["mutation_index"] == idx)
            right.markdown(f"**Mutation {mutation['mutation_index']}** (seed {mutation['seed']})")
            right.code(mutation["mutated_code"], language="python")
            st.markdown(
                f"Validation: **{mutation['validation_status']}** · score {mutation['validation_score']} · "
                f"mapping `{mutation['mapping_json']}`")
        else:
            right.caption("No mutations recorded.")

st.sidebar.markdown("---")
if st.sidebar.button("↻ Reconnect / clear session"):
    st.session_state.clear()
    st.rerun()
