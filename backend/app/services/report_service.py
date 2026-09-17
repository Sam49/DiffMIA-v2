"""Research report generation: JSON, CSV, Markdown and PDF exports."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import __version__
from app.services.results_service import build_results

DISCLAIMER = (
    "IMPORTANT LIMITATION: contamination scores indicate behavioral evidence "
    "consistent with memorization. They do NOT establish the provenance of "
    "training data. A high differential loss can also be caused by identifier "
    "familiarity, tokenization effects, distributional differences, model "
    "biases, mutation artifacts, prompt effects or code-style familiarity. "
    "These results are 'contamination signals', never 'confirmed contamination', "
    "unless corroborated by independent external evidence."
)

METHODOLOGY_MD = """
## Methodology

For every benchmark snippet DiffMIA scores the *original* code and *N
semantically equivalent identifier-renamed mutations* under the model, using
teacher-forced per-token negative log likelihood (NLL) over content tokens.

Contamination Index for a snippet:

    CI = (mean(mutated_losses) - original_loss) / max(|original_loss|, epsilon)

A positive CI means the model assigns lower loss to the original than to
equivalent renames — the behavioural signature consistent with memorization of
the original example. Z-scores are computed against a leave-one-out dataset
baseline (optionally a global baseline across experiments on the same model),
so a snippet does not dampen its own anomaly score.
"""


def _conclusion_markdown(bundle: dict) -> list[str]:
    """Conclusion section: the verdict, then the evidence behind it."""
    conclusion = bundle.get("conclusion") or {}
    lines = ["## Conclusion", ""]
    if not conclusion:
        lines += ["No conclusion is available for this experiment.", ""]
        return lines
    lines.append(f"**Verdict: {str(conclusion.get('verdict', '')).replace('_', ' ')}** "
                 f"(evidence level: {conclusion.get('evidence_level', 'n/a')})")
    lines.append("")
    lines.append(conclusion.get("headline", ""))
    lines.append("")
    lines.append("### Observed")
    lines.append("")
    for item in conclusion.get("observations", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("### Limitations of this conclusion")
    lines.append("")
    for item in conclusion.get("caveats", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("### Recommended next steps to corroborate or falsify")
    lines.append("")
    for item in conclusion.get("corroboration", []):
        lines.append(f"- {item}")
    lines.append("")
    return lines


def _bundle(db: Session, experiment_id: int) -> dict:
    bundle = build_results(db, experiment_id)
    bundle["disclaimer"] = DISCLAIMER
    bundle["generated_at"] = datetime.now(timezone.utc).isoformat()
    bundle["software_version"] = f"DiffMIA {__version__}"
    return bundle


def export_json(db: Session, experiment_id: int) -> str:
    return json.dumps(_bundle(db, experiment_id), indent=2, default=str)


def export_csv(db: Session, experiment_id: int) -> str:
    bundle = build_results(db, experiment_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "snippet_id", "external_id", "language", "original_loss",
            "mean_mutation_loss", "median_mutation_loss", "contamination_index",
            "abs_loss_delta", "rel_loss_delta", "z_score", "z_score_global",
            "effect_size", "percentile_rank", "classification", "flagged",
            "classification_reason",
        ]
    )
    for row in bundle["analyses"]:
        writer.writerow(
            [
                row["snippet_id"], row["external_id"], row["language"],
                row["original_loss"], row["mean_mutation_loss"], row["median_mutation_loss"],
                row["contamination_index"], row["abs_loss_delta"], row["rel_loss_delta"],
                row["z_score"], row["z_score_global"], row["effect_size"],
                row["percentile_rank"], row["classification"], row["flagged"],
                row["classification_reason"],
            ]
        )
    return buffer.getvalue()


def export_markdown(db: Session, experiment_id: int) -> str:
    bundle = _bundle(db, experiment_id)
    exp = bundle["experiment"]
    stats = bundle["stats"]
    lines: list[str] = []
    lines.append(f"# DiffMIA Research Report — {exp['name']}")
    lines.append("")
    lines.append(f"*Generated {bundle['generated_at']} · {bundle['software_version']}*")
    lines.append("")
    lines.append(f"> {DISCLAIMER}")
    lines.append("")
    lines.append("## Experiment")
    lines.append("")
    lines.append(f"- **Status**: {exp['status']}")
    lines.append(f"- **Model**: {exp['model']['display_name'] if exp['model'] else exp['model_id']} "
                 f"({exp['model']['provider'] if exp['model'] else '?'})")
    lines.append(f"- **Dataset**: {exp['dataset']['name']} — {exp['dataset']['item_count']} items "
                 f"(hash {exp['dataset_hash'][:16]}…)")
    lines.append(f"- **Mutations**: {exp['mutation_count']} × identifier_rename, seed {exp['mutation_seed']}, "
                 f"strength {exp['mutation_strength']}")
    lines.append(f"- **Temperature**: {exp['temperature']} · **max_tokens**: {exp['max_tokens']} · "
                 f"**batch_size**: {exp['batch_size']} · **device**: {exp['device']}")
    lines.append("")
    lines.append("## Results summary")
    lines.append("")
    lines.append(f"- Snippets analyzed: {stats['analyzed_count']}")
    lines.append(f"- Flagged (POSSIBLE_CONTAMINATION or higher): {stats['flagged_count']}")
    lines.append(f"- High-signal: {stats['high_signal_count']} · Low-evidence: {stats['low_evidence_count']}")
    lines.append(f"- Mean CI: {_fmt(stats['mean_ci'])} · Median CI: {_fmt(stats['median_ci'])} · "
                 f"Std CI: {_fmt(stats['std_ci'])}")
    lines.append("")
    lines.extend(_conclusion_markdown(bundle))
    lines.append(METHODOLOGY_MD)
    lines.append("")
    lines.append("## Per-snippet results")
    lines.append("")
    lines.append("| Snippet | Original loss | Mean mut. loss | CI | Z | Classification |")
    lines.append("|---|---|---|---|---|---|")
    for row in sorted(bundle["analyses"], key=lambda r: -(r["contamination_index"] or 0.0)):
        lines.append(
            f"| {row['external_id']} | {_fmt(row['original_loss'])} | {_fmt(row['mean_mutation_loss'])} "
            f"| {_fmt(row['contamination_index'])} | {_fmt(row['z_score'])} | {row['classification']} |"
        )
    lines.append("")
    flagged_rows = sorted(
        [r for r in bundle["analyses"] if r["flagged"]],
        key=lambda r: -(r["contamination_index"] or 0.0),
    )
    if flagged_rows:
        lines.append("## Top flagged examples")
        lines.append("")
        for row in flagged_rows[:10]:
            lines.append(f"### {row['external_id']} — {row['classification']} "
                         f"(CI={_fmt(row['contamination_index'])}, Z={_fmt(row['z_score'])})")
            lines.append("")
            lines.append(f"*{row['problem_statement'][:300]}*")
            lines.append("")
            lines.append(f"Reason: {row['classification_reason']}")
            lines.append("")
    lines.append("## Reproducibility")
    lines.append("")
    lines.append(f"- Experiment id: {exp['id']} · dataset hash: {exp['dataset_hash']}")
    lines.append(f"- Mutation seed: {exp['mutation_seed']} · model version: {exp['model_version']}")
    lines.append(f"- Configuration: `{exp['config_json']}`")
    lines.append("")
    lines.append("_DiffMIA is a research/evaluation tool. It never executes benchmark code._")
    lines.append("")
    return "\n".join(lines)


def export_pdf(db: Session, experiment_id: int) -> bytes:
    """Render the report as a PDF using reportlab (pure Python, no browser)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    markdown = export_markdown(db, experiment_id)
    bundle = _bundle(db, experiment_id)
    exp = bundle["experiment"]
    stats = bundle["stats"]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, title=f"DiffMIA Report {exp['name']}")

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=18, spaceAfter=6)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#0f172a"))
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9, leading=13)
    small = ParagraphStyle("Small", parent=body, fontSize=8, textColor=colors.HexColor("#475569"))

    elements = [
        Paragraph(f"DiffMIA Research Report — {exp['name']}", h1),
        Paragraph(f"Generated {bundle['generated_at']} · {bundle['software_version']}", small),
        Spacer(1, 6),
        Paragraph(f"<b>Limitation:</b> {DISCLAIMER}", small),
        Spacer(1, 4),
        Paragraph("Experiment configuration", h2),
    ]
    config_rows = [
        ["Status", exp["status"]],
        ["Model", (exp["model"]["display_name"] if exp["model"] else exp["model_id"])
         + (f" ({exp['model']['provider']})" if exp["model"] else "")],
        ["Dataset", f"{exp['dataset']['name']} · {exp['dataset']['item_count']} items · hash {exp['dataset_hash'][:16]}…"],
        ["Mutation config", f"{exp['mutation_count']}× identifier_rename · seed {exp['mutation_seed']} · strength {exp['mutation_strength']}"],
        ["Inference config", f"temperature {exp['temperature']} · max_tokens {exp['max_tokens']} · batch {exp['batch_size']} · {exp['device']}"],
        ["Analyzed / Flagged", f"{stats['analyzed_count']} / {stats['flagged_count']} (high signal {stats['high_signal_count']})"],
        ["Mean / Median CI", f"{_fmt(stats['mean_ci'])} / {_fmt(stats['median_ci'])}"],
    ]
    table = Table(config_rows, colWidths=[45 * mm, 120 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements += [table, Spacer(1, 6), Paragraph(METHODOLOGY_MD.split("\n\n", 1)[1].strip(), body)]

    conclusion = bundle.get("conclusion") or {}
    if conclusion:
        elements.append(Paragraph("Conclusion", h2))
        elements.append(
            Paragraph(
                f"<b>Verdict: {str(conclusion.get('verdict', '')).replace('_', ' ')}</b> "
                f"(evidence level: {conclusion.get('evidence_level', 'n/a')})",
                body,
            )
        )
        elements.append(Spacer(1, 3))
        elements.append(Paragraph(conclusion.get("headline", ""), body))
        elements.append(Spacer(1, 3))
        elements.append(Paragraph("Observed", body))
        for item in conclusion.get("observations", []):
            elements.append(Paragraph(f"&bull; {item}", small))
        elements.append(Spacer(1, 3))
        elements.append(Paragraph("Limitations of this conclusion", body))
        for item in conclusion.get("caveats", []):
            elements.append(Paragraph(f"&bull; {item}", small))
        elements.append(Spacer(1, 3))
        elements.append(Paragraph("Recommended next steps to corroborate or falsify", body))
        for item in conclusion.get("corroboration", []):
            elements.append(Paragraph(f"&bull; {item}", small))
        elements.append(Spacer(1, 6))

    elements.append(Paragraph("Per-snippet results", h2))
    header = ["Snippet", "Orig", "Mut mean", "CI", "Z", "Class"]
    data = [header]
    for row in sorted(bundle["analyses"], key=lambda r: -(r["contamination_index"] or 0.0)):
        data.append([
            row["external_id"][:22], _fmt(row["original_loss"]), _fmt(row["mean_mutation_loss"]),
            _fmt(row["contamination_index"]), _fmt(row["z_score"]), row["classification"],
        ])
    results_table = Table(data, colWidths=[45 * mm, 20 * mm, 25 * mm, 25 * mm, 18 * mm, 42 * mm], repeatRows=1)
    results_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    elements += [results_table]

    flagged = sorted([r for r in bundle["analyses"] if r["flagged"]],
                     key=lambda r: -(r["contamination_index"] or 0.0))[:5]
    if flagged:
        elements.append(Paragraph("Top flagged examples", h2))
        for row in flagged:
            elements.append(
                Paragraph(
                    f"<b>{row['external_id']}</b> — {row['classification']} (CI={_fmt(row['contamination_index'])}, "
                    f"Z={_fmt(row['z_score'])}): {row['classification_reason']}",
                    body,
                )
            )
            elements.append(Spacer(1, 3))

    elements += [PageBreak(), Paragraph("Reproducibility & limitations", h2)]
    elements.append(Paragraph(
        "Mutation generation is deterministic (seed + mutation index). Dataset hash, model version, thresholds and "
        "the full configuration are recorded with the experiment. Running the same experiment twice reuses cached "
        "inference results where enabled. Code is never executed during analysis.",
        body,
    ))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(DISCLAIMER, small))

    doc.build(elements)
    return buffer.getvalue()


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)
