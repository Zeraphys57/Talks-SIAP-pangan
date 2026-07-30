"""Assemble every export and write the provenance README.

The README is the part that matters most. `paper-exports/` is gitignored, so a
reader who receives these files has no repository context; the README is what
makes each artefact traceable to a run, a git SHA, a seed and a set of
parameters, and what says plainly which numbers do not exist yet and why.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import AnalysisConfig, FusionConfig
from ..db import Conn, fetch_all
from ..evaluate.ablation import AblationReport, nesting_note
from . import figures, tables

log = logging.getLogger(__name__)


@dataclass
class ExportReport:
    directory: Path
    figures: list[figures.FigureSpec] = field(default_factory=list)
    tables: list[tables.Table] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _run_row(conn: Conn, run_id: int) -> dict[str, Any] | None:
    rows = fetch_all(
        conn,
        """
        select id, run_type, status, git_sha, seed, started_at, finished_at, params
          from public.analysis_runs where id = %s
        """,
        (run_id,),
    )
    return rows[0] if rows else None


def _pick_example(conn: Conn, anomaly_run_id: int) -> dict[str, Any] | None:
    """The series with the strongest flagged move, for the qualitative figure.

    Chosen by measurement rather than by eye, so nobody has to defend having
    picked the prettiest chart.
    """
    rows = fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region, a.obs_date,
               abs(a.raw_score) as strength
          from public.anomaly_scores a
          join public.commodities c on c.id = a.commodity_id
          join public.regions rg on rg.id = a.region_id
         where a.run_id = %s and a.is_flagged and a.method = 'zscore'
           and a.raw_score is not null
         order by abs(a.raw_score) desc
         limit 1
        """,
        (anomaly_run_id,),
    )
    return rows[0] if rows else None


def run(
    conn: Conn,
    directory: Path,
    anomaly_run_id: int,
    cluster_run_id: int | None,
    fusion_run_id: int | None,
    ablation: AblationReport,
    analysis: AnalysisConfig,
    fusion_cfg: FusionConfig,
) -> ExportReport:
    report = ExportReport(directory=directory)
    directory.mkdir(parents=True, exist_ok=True)

    # --- figures ------------------------------------------------------------
    if ablation.k_points:
        report.figures.append(figures.k_silhouette(ablation.k_points, cluster_run_id, directory))
    else:
        report.skipped.append("fig_k_silhouette: no monthly cells met min_days_in_month")

    if ablation.contamination_points:
        report.figures.append(
            figures.contamination(ablation.contamination_points, anomaly_run_id, directory)
        )
    if ablation.weight_points:
        report.figures.append(
            figures.weight_sensitivity(ablation.weight_points, fusion_run_id, directory)
        )

    report.figures.append(figures.coverage(conn, directory))

    example = _pick_example(conn, anomaly_run_id)
    if example is None:
        report.skipped.append("fig_series_*: no flagged days in the anomaly run")
    else:
        spec = figures.example_series(
            conn,
            anomaly_run_id,
            str(example["commodity"]),
            str(example["region"]),
            example["obs_date"],
            directory,
        )
        if spec is None:
            report.skipped.append(
                f"fig_series_*: {example['commodity']}/{example['region']} has fewer than "
                f"30 observed days around {example['obs_date']}; a sparse chart would "
                f"imply data that is not there"
            )
        else:
            report.figures.append(spec)

    # --- tables -------------------------------------------------------------
    report.tables += [
        tables.commodities_table(conn),
        tables.sources_table(conn),
        tables.coverage_table(conn),
        tables.flag_counts_table(conn, anomaly_run_id),
    ]
    if cluster_run_id is not None:
        report.tables.append(tables.zone_counts_table(conn, cluster_run_id))

    if ablation.k_points:
        report.tables.append(
            tables.k_search_table(
                [
                    {
                        "k": p.k,
                        "silhouette": round(p.silhouette, 6),
                        "inertia": round(p.inertia, 4),
                        "eligible": p.eligible,
                        "selected": p.selected,
                    }
                    for p in ablation.k_points
                ]
            )
        )
    if ablation.contamination_points:
        report.tables.append(
            tables.contamination_table(
                [
                    {
                        "contamination": p.contamination,
                        "days_scored": p.days_scored,
                        "days_flagged": p.days_flagged,
                        "flag_rate": round(p.flag_rate, 6),
                        "jaccard_vs_configured": round(p.jaccard_vs_baseline, 6),
                    }
                    for p in ablation.contamination_points
                ],
                nesting_note(ablation.contamination_points),
            )
        )
    if ablation.weight_points:
        report.tables.append(
            tables.weight_sensitivity_table(
                [
                    {
                        "weight": p.weight,
                        "delta": p.delta,
                        "value": round(p.value, 4),
                        "spearman": round(p.spearman, 6),
                        "levels_changed": p.level_changes,
                        "siaga": p.siaga,
                        "waspada": p.waspada,
                        "tenang": p.tenang,
                        "belum_dapat_dinilai": p.belum_dapat_dinilai,
                        "inert": bool(p.inert_because),
                    }
                    for p in ablation.weight_points
                    if p.ok
                ],
                "A weight marked inert multiplies a term that is constant across the data; "
                "its perfect rank correlation reflects that the parameter cannot reorder "
                "anything, not that the model is robust to it.",
            )
        )

    if not ablation.accuracy_available:
        report.skipped.append(
            "tab_evaluation_results and fig_precision_recall: " + ablation.accuracy_blocked_because
        )

    report.files = figures.write_all(report.figures) + tables.write_all(report.tables, directory)
    report.files.append(
        _write_readme(
            conn,
            report,
            anomaly_run_id,
            cluster_run_id,
            fusion_run_id,
            ablation,
            analysis,
            fusion_cfg,
        )
    )
    return report


def _write_readme(
    conn: Conn,
    report: ExportReport,
    anomaly_run_id: int,
    cluster_run_id: int | None,
    fusion_run_id: int | None,
    ablation: AblationReport,
    analysis: AnalysisConfig,
    fusion_cfg: FusionConfig,
) -> Path:
    lines: list[str] = [
        "# SIAP-PANGAN — paper exports",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `siap export`.",
        "",
        "Regenerated on demand and never committed. Every artefact below traces to a",
        "row in `analysis_runs`, which carries the git SHA, the seed, the parameters and",
        "the library versions that produced it.",
        "",
        "## Provenance",
        "",
        "| artefact source | run | type | status | git sha | seed | finished |",
        "|---|---|---|---|---|---|---|",
    ]
    for label, run_id in (
        ("detectors", anomaly_run_id),
        ("clustering", cluster_run_id),
        ("fusion", fusion_run_id),
        ("ablation", ablation.run_id),
    ):
        if run_id is None:
            lines.append(f"| {label} | — | — | not run | — | — | — |")
            continue
        row = _run_row(conn, run_id)
        if row is None:
            lines.append(f"| {label} | {run_id} | — | missing | — | — | — |")
            continue
        finished = row["finished_at"]
        lines.append(
            f"| {label} | #{row['id']} | {row['run_type']} | {row['status']} | "
            f"`{str(row['git_sha'])[:8]}` | {row['seed']} | "
            f"{finished:%Y-%m-%d %H:%M} |"
            if finished
            else f"| {label} | #{row['id']} | {row['run_type']} | {row['status']} | "
            f"`{str(row['git_sha'])[:8]}` | {row['seed']} | — |"
        )

    lines += [
        "",
        f"Analysis seed: `{analysis.seed}`. Fusion weights: "
        f"A={fusion_cfg.weights.anomaly}, M={fusion_cfg.weights.momentum}, "
        f"D={fusion_cfg.weights.demand}, C={fusion_cfg.weights.corroboration}.",
        "",
        "## Figures",
        "",
    ]
    for spec in report.figures:
        lines += [f"### `{spec.slug}`", "", spec.caption, ""]

    lines += ["## Tables", ""]
    for table in report.tables:
        lines += [
            f"### `{table.slug}`",
            "",
            f"{table.caption} ({len(table.rows)} row(s); `.csv` and `.tex`)",
            "",
        ]
        if table.note:
            lines += [f"> {table.note}", ""]

    lines += [
        "## Not exported",
        "",
        "These are absent because the inputs do not exist, not because they were",
        "forgotten. Nothing here is estimated, and no placeholder zeros are written:",
        "an empty column is a fact, a zero is a claim.",
        "",
    ]
    if report.skipped:
        for reason in report.skipped:
            lines.append(f"- {reason}")
    else:
        lines.append("- nothing; every artefact had its inputs.")

    lines += [
        "",
        "## Scope",
        "",
        "This system is descriptive and diagnostic. It characterises price behaviour",
        "that has already happened. It does not forecast, and no figure or table here",
        "should be read as a prediction of tomorrow's price.",
        "",
    ]

    path = report.directory / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
