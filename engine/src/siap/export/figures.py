"""Figures for the paper.

House style, applied once in `_style()` and not overridden per figure:

* **300 dpi**, PNG and PDF. PDF for the manuscript (vector, scales cleanly),
  PNG so the figure can be looked at without a LaTeX toolchain.
* **Greyscale-safe.** Series are distinguished by marker, dash pattern and
  direct labelling, never by hue alone. TALKS proceedings are printed in
  monochrome, and a figure whose meaning survives only in colour is a figure
  that fails in the medium it was written for.
* **No chartjunk.** No gridlines behind data, no boxes around plots, no legend
  where a direct label fits, no title inside the axes — the caption carries it.

Every figure is stamped with the run id it came from. A chart that cannot be
traced to a run, a seed and a git SHA is decoration.

The Agg backend is forced at import: these run in CI with no display, and a
figure module that opens a window on a headless machine hangs the job.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from ..db import Conn, fetch_all

log = logging.getLogger(__name__)

DPI = 300
INK = "#1a1a1a"
MUTED = "#8a8a8a"
BAND = "#d9d9d9"


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "savefig.bbox": "tight",
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 8,
            "axes.edgecolor": INK,
            "axes.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": False,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "xtick.color": INK,
            "ytick.color": INK,
            "text.color": INK,
            "lines.linewidth": 1.1,
            "legend.frameon": False,
            "legend.fontsize": 7,
        }
    )


def _date_axis(ax: Any, max_ticks: int = 6) -> None:
    """Readable date ticks.

    Matplotlib's default picks a tick per data unit here, which at 120 daily
    points overlaps every label into an unreadable smear. Capping the count and
    using a short month-year format is the whole fix.
    """
    # matplotlib ships no stubs for these two; the calls are correct, mypy just
    # cannot see their signatures.
    locator = mdates.AutoDateLocator(minticks=3, maxticks=max_ticks)  # type: ignore[no-untyped-call]
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))  # type: ignore[no-untyped-call]
    for label in ax.get_xticklabels():
        label.set_rotation(0)
        label.set_horizontalalignment("center")


def _stamp(fig: Figure, run_id: int | None, extra: str = "") -> None:
    """Provenance, small, bottom-left. Every number traces to a run."""
    label = f"run #{run_id}" if run_id is not None else "run: unrecorded"
    if extra:
        label = f"{label} · {extra}"
    fig.text(0.0, -0.02, label, fontsize=5.5, color=MUTED, ha="left", va="top")


def _save(fig: Figure, slug: str, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for suffix in ("pdf", "png"):
        path = directory / f"{slug}.{suffix}"
        fig.savefig(path)
        written.append(path)
    plt.close(fig)
    return written


@dataclass
class FigureSpec:
    slug: str
    caption: str
    paths: list[Path]


# ---------------------------------------------------------------------------
def k_silhouette(points: list[Any], run_id: int | None, directory: Path) -> FigureSpec:
    """Silhouette and inertia against k, with the excluded k shown as excluded."""
    _style()
    fig, ax = plt.subplots(figsize=(3.4, 2.2))

    ks = [p.k for p in points]
    sil = [p.silhouette for p in points]
    ax.plot(ks, sil, marker="o", markersize=3.5, color=INK, zorder=3)

    for point in points:
        if not point.eligible:
            # Hollow marker rather than a different colour: the distinction has
            # to survive a monochrome print.
            ax.plot(
                point.k,
                point.silhouette,
                marker="o",
                markersize=6,
                markerfacecolor="white",
                markeredgecolor=INK,
                zorder=4,
            )
            ax.annotate(
                "tidak memenuhi syarat\n(3 zona)",
                (point.k, point.silhouette),
                textcoords="offset points",
                xytext=(6, -2),
                fontsize=6,
                color=MUTED,
            )
        if point.selected:
            ax.plot(point.k, point.silhouette, marker="s", markersize=6, color=INK, zorder=5)
            ax.annotate(
                f"terpilih, k={point.k}",
                (point.k, point.silhouette),
                textcoords="offset points",
                xytext=(6, 6),
                fontsize=6.5,
                color=INK,
            )

    ax.set_xlabel("k")
    ax.set_ylabel("silhouette")
    ax.set_xticks(ks)
    _stamp(fig, run_id)
    return FigureSpec(
        "fig_k_silhouette",
        "Silhouette against k. k=2 scores highest but cannot be selected, because two "
        "clusters cannot populate a three-zone output; the point is plotted rather than "
        "dropped so the cost of that constraint is visible.",
        _save(fig, "fig_k_silhouette", directory),
    )


def contamination(points: list[Any], run_id: int | None, directory: Path) -> FigureSpec:
    """Flag volume against contamination, annotated with the overlap."""
    _style()
    fig, ax = plt.subplots(figsize=(3.4, 2.2))

    xs = [p.contamination for p in points]
    ys = [p.days_flagged for p in points]
    ax.plot(xs, ys, marker="o", markersize=3.5, color=INK)

    for point in points:
        if point.is_baseline:
            ax.plot(point.contamination, point.days_flagged, marker="s", markersize=6, color=INK)
            ax.annotate(
                "terpakai",
                (point.contamination, point.days_flagged),
                textcoords="offset points",
                xytext=(6, -3),
                fontsize=6.5,
            )

    ax.set_xlabel("contamination")
    ax.set_ylabel("hari ditandai")
    ax.set_xticks(xs)
    _stamp(fig, run_id)
    return FigureSpec(
        "fig_contamination",
        "Days flagged against the contamination parameter. Each flag set is a strict "
        "subset of the next larger one, so the parameter moves the cut point on a fixed "
        "ranking rather than changing which days are unusual.",
        _save(fig, "fig_contamination", directory),
    )


def weight_sensitivity(points: list[Any], run_id: int | None, directory: Path) -> FigureSpec:
    """How far the alert level distribution moves when one weight is nudged."""
    _style()
    usable = [p for p in points if p.ok]
    fig, ax = plt.subplots(figsize=(3.6, 2.4))

    labels = [f"{p.weight}\n{p.delta:+.2f}" for p in usable]
    positions = range(len(usable))
    changed = [p.level_changes for p in usable]

    bars = ax.bar(positions, changed, color=BAND, edgecolor=INK, linewidth=0.6)
    for bar, point in zip(bars, usable, strict=True):
        if point.inert_because:
            # Hatching, not colour: the reader must be able to see which bars
            # are meaningless in a monochrome print.
            bar.set_hatch("////")

    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels, fontsize=6)
    ax.set_ylabel("peringatan yang berubah tingkat")
    _stamp(fig, run_id, "hatched = term is constant, so the weight cannot reorder anything")
    return FigureSpec(
        "fig_weight_sensitivity",
        "Alerts changing level under a single-weight perturbation of +/-0.10, with the "
        "other weights rescaled to preserve the sum. Hatched bars mark a weight whose "
        "term is constant across the data, where a stable ranking indicates an inert "
        "parameter rather than a robust one.",
        _save(fig, "fig_weight_sensitivity", directory),
    )


def example_series(
    conn: Conn,
    anomaly_run_id: int,
    commodity_slug: str,
    region_slug: str,
    centre: date,
    directory: Path,
    span_days: int = 120,
) -> FigureSpec | None:
    """One real series with its detector flags, as the qualitative figure.

    Uses actual rows. If the series is too short to be worth plotting, returns
    None rather than a sparse chart implying data that is not there.
    """
    rows = fetch_all(
        conn,
        """
        select u.obs_date, u.price_median, u.is_imputed,
               max(case when a.method = 'zscore'  and a.is_flagged then 1 else 0 end) as z,
               max(case when a.method = 'iforest' and a.is_flagged then 1 else 0 end) as i
          from public.price_daily_unified u
          join public.commodities c on c.id = u.commodity_id
          join public.regions rg    on rg.id = u.region_id
          left join public.anomaly_scores a
                 on a.commodity_id = u.commodity_id
                and a.region_id    = u.region_id
                and a.obs_date     = u.obs_date
                and a.run_id       = %s
         where c.slug = %s and rg.slug = %s
           and u.obs_date between %s and %s
           and u.price_median is not null
         group by u.obs_date, u.price_median, u.is_imputed
         order by u.obs_date
        """,
        (
            anomaly_run_id,
            commodity_slug,
            region_slug,
            centre - timedelta(days=span_days // 2),
            centre + timedelta(days=span_days // 2),
        ),
    )
    if len(rows) < 30:
        return None

    _style()
    fig, ax = plt.subplots(figsize=(5.2, 2.4))

    dates = [r["obs_date"] for r in rows]
    prices = [float(r["price_median"]) for r in rows]
    ax.plot(dates, prices, color=INK, linewidth=1.0, zorder=2)

    z_days = [(r["obs_date"], float(r["price_median"])) for r in rows if r["z"]]
    i_days = [(r["obs_date"], float(r["price_median"])) for r in rows if r["i"]]

    if z_days:
        zx, zy = zip(*z_days, strict=True)
        ax.scatter(
            zx,
            zy,
            marker="o",
            s=26,
            facecolors="none",
            edgecolors=INK,
            linewidths=0.9,
            zorder=3,
            label="Z-Score",
        )
    if i_days:
        ix, iy = zip(*i_days, strict=True)
        ax.scatter(
            ix,
            iy,
            marker="x",
            s=26,
            color=INK,
            linewidths=0.9,
            zorder=4,
            label="Isolation Forest",
        )

    imputed = [(r["obs_date"], float(r["price_median"])) for r in rows if r["is_imputed"]]
    if imputed:
        mx, my = zip(*imputed, strict=True)
        ax.scatter(
            mx,
            my,
            marker=".",
            s=8,
            color=MUTED,
            zorder=1,
            label="interpolasi",
        )

    ax.set_ylabel("Rp / kg")
    # Legend above the axes, not inside: at this figure width it lands on the
    # data every time, and a legend over the series is worse than no legend.
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=4, borderaxespad=0)
    _date_axis(ax)
    _stamp(fig, anomaly_run_id, f"{commodity_slug} · {region_slug}")

    slug = f"fig_series_{commodity_slug.replace('-', '_')}_{region_slug}"
    return FigureSpec(
        slug,
        f"{commodity_slug} in {region_slug}: observed daily price with the days each "
        f"detector flagged. Hollow circles are the statistical arm, crosses the machine "
        f"learning arm; the two agree on only part of the series, which is the premise "
        f"of combining them.",
        _save(fig, slug, directory),
    )


def coverage(conn: Conn, directory: Path) -> FigureSpec:
    """Observations per month per source — the data-availability figure."""
    rows = fetch_all(
        conn,
        """
        select date_trunc('month', o.obs_date)::date as month,
               s.slug as source, count(*) as n
          from public.price_observations o
          join public.sources s on s.id = o.source_id
         group by 1, 2
         order by 1, 2
        """,
    )
    _style()
    fig, ax = plt.subplots(figsize=(5.2, 2.2))

    sources = sorted({str(r["source"]) for r in rows})
    styles = ["-", "--", "-.", ":", (0, (3, 1, 1, 1)), (0, (5, 2))]
    markers = ["o", "s", "^", "D", "v", "P"]

    for index, source in enumerate(sources):
        series = [(r["month"], int(r["n"])) for r in rows if r["source"] == source]
        if not series:
            continue
        months, counts = zip(*series, strict=True)
        ax.plot(
            months,
            counts,
            linestyle=styles[index % len(styles)],
            marker=markers[index % len(markers)],
            markersize=2.5,
            color=INK,
            label=source,
        )

    ax.set_ylabel("observasi per bulan")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=4, borderaxespad=0)
    _date_axis(ax)
    _stamp(fig, None, "from price_observations")
    return FigureSpec(
        "fig_coverage",
        "Observations collected per month per source. Gaps are real: a missing month is "
        "a portal that did not answer, recorded in fetch_failures rather than filled in.",
        _save(fig, "fig_coverage", directory),
    )


def write_all(specs: list[FigureSpec]) -> list[Path]:
    return [path for spec in specs for path in spec.paths]
