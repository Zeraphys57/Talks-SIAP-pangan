"""Fit the regime clustering and persist the model and its assignments.

One model per run, covering every commodity x region x month cell at once.
Fitting per commodity would defeat the purpose: the point is to place a
commodity-month against the whole population of commodity-months, so that
"cabai in DIY in March 2024" can be called volatile *relative to everything
else observed*, not relative to cabai's own history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from psycopg.types.json import Json

from .config import AnalysisConfig, load_analysis
from .db import Conn, fetch_all
from .modules import kmeans
from .runs import start_run

log = logging.getLogger(__name__)


@dataclass
class ClusterReport:
    run_id: int = 0
    model: kmeans.ClusterModel | None = None
    cells: int = 0
    assignments_written: int = 0
    gated: int = 0
    gate_reasons: dict[str, int] = field(default_factory=dict)


def load_cells(conn: Conn) -> pd.DataFrame:
    """Every daily observation with its imputation flag, ready for aggregation.

    Imputed rows are **selected, not filtered**. The clustering still computes
    its features from real observations only, but it cannot measure how much of
    a month was imputed if the imputed rows never arrive — and the imputed share
    is one of the four provenance measurements stored on every cell.

    `analysis.input.exclude_imputed` deliberately does not gate this query: that
    setting is written about the two detectors, and applying it here would make
    the provenance metrics a function of a detector policy.
    """
    rows = fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region,
               u.obs_date, u.price_median as price, u.is_imputed
          from public.price_daily_unified u
          join public.commodities c on c.id = u.commodity_id
          join public.regions rg on rg.id = u.region_id
         where u.price_median is not null
         order by c.slug, rg.slug, u.obs_date
        """,
    )
    return (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(columns=["commodity", "region", "obs_date", "price", "is_imputed"])
    )


def _persist(conn: Conn, run_id: int, model: kmeans.ClusterModel) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into public.cluster_models
                (run_id, k_selected, k_search, silhouette_avg, centroids,
                 scaler_params, zone_mapping, n_samples, feature_names)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                model.k_selected,
                Json(model.k_search_json),
                model.silhouette_avg,
                Json({str(k): v for k, v in model.centroids.items()}),
                Json(model.scaler_params),
                Json({str(k): v for k, v in model.zone_mapping.items()}),
                model.n_samples,
                kmeans.FEATURES,
            ),
        )

        lookup = {
            (str(r["commodity"]), str(r["region"])): (int(r["cid"]), int(r["rid"]))
            for r in fetch_all(
                conn,
                """
                select c.slug as commodity, rg.slug as region,
                       c.id as cid, rg.id as rid
                  from public.commodities c cross join public.regions rg
                """,
            )
        }

        def maybe(value: Any, cast: Any) -> Any:
            """NULL for a missing number, rather than a plausible-looking zero."""
            return None if value is None or pd.isna(value) else cast(value)

        payload = []
        for row in model.assignments.itertuples(index=False):
            ids = lookup.get((str(row.commodity), str(row.region)))
            if ids is None:
                continue
            payload.append(
                (
                    run_id,
                    ids[0],
                    ids[1],
                    row.period_month,
                    maybe(row.volatility, float),
                    maybe(row.cum_change, float),
                    maybe(row.cluster_id, int),
                    maybe(row.zone, str),
                    maybe(row.silhouette_sample, float),
                    maybe(row.quality_reason, str),
                )
            )
        if payload:
            cur.executemany(
                """
                insert into public.cluster_assignments
                    (run_id, commodity_id, region_id, period_month,
                     feat_volatility, feat_cum_change, cluster_id, zone,
                     silhouette_sample, quality_reason)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                payload,
            )
    return len(payload)


def run_clustering(conn: Conn, config: AnalysisConfig | None = None) -> ClusterReport:
    cfg = config or load_analysis()
    report = ClusterReport()

    run = start_run(conn, "cluster", seed=cfg.seed, params={"kmeans": cfg.kmeans.model_dump()})
    report.run_id = run.id

    status = "failed"
    try:
        daily = load_cells(conn)
        cells = kmeans.build_cells(daily, cfg.kmeans)
        report.cells = len(cells)

        if cells.empty:
            run.note("no monthly cells could be built; nothing to cluster")
            status = "partial"
            return report

        model = kmeans.fit(cells, cfg.kmeans, cfg.seed)
        report.model = model
        report.gated = model.n_gated
        report.gate_reasons = model.gate_reasons
        report.assignments_written = _persist(conn, run.id, model)
        conn.commit()

        run.note(
            f"k search {cfg.kmeans.k_min}..{cfg.kmeans.k_max} over {model.n_samples} fitted "
            f"cells; selected k={model.k_selected} on silhouette {model.silhouette_avg:.4f}"
        )
        run.note(
            f"provenance gate: {model.n_gated} of {len(cells)} cells excluded from the fit "
            f"and kept with zone=NULL ("
            + ", ".join(f"{k}={v}" for k, v in sorted(model.gate_reasons.items()))
            + f"); thresholds {cfg.kmeans.quality.model_dump()}"
        )
        if model.k_selected > 3:
            run.note(
                f"k={model.k_selected} > 3, so the middle clusters merge into kuning "
                f"(see docs/methods.md); k was not pinned at 3"
            )
        status = "success"
    finally:
        run.finish(status)

    return report


# ---------------------------------------------------------------------------
# Reporting for the M4 gate
# ---------------------------------------------------------------------------
def zone_table(conn: Conn, run_id: int, period_month: Any = None) -> list[dict[str, Any]]:
    """Zone per commodity x region for one month — the gate's sanity check."""
    return fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region, a.period_month,
               a.zone, a.cluster_id, a.feat_volatility, a.feat_cum_change,
               a.silhouette_sample, a.quality_reason
          from public.cluster_assignments a
          join public.commodities c on c.id = a.commodity_id
          join public.regions rg on rg.id = a.region_id
         where a.run_id = %s
           and a.period_month = coalesce(
                 %s,
                 (select max(period_month) from public.cluster_assignments where run_id = %s))
         -- `nulls last` on both: under DESC Postgres sorts NULLs first, which
         -- would open the gate's sanity check with the rows it excluded.
         order by a.zone desc nulls last, a.feat_volatility desc nulls last
        """,
        (run_id, period_month, run_id),
    )


def zone_counts_by_commodity(conn: Conn, run_id: int) -> list[dict[str, Any]]:
    """How often each commodity lands in each zone, across all months."""
    return fetch_all(
        conn,
        """
        select c.slug as commodity,
               count(*) filter (where a.zone = 'merah')  as merah,
               count(*) filter (where a.zone = 'kuning') as kuning,
               count(*) filter (where a.zone = 'hijau')  as hijau,
               count(*) filter (where a.zone is null)    as gated,
               count(*) as total,
               round(avg(a.feat_volatility) filter (where a.zone is not null)::numeric, 5)
                   as avg_volatility
          from public.cluster_assignments a
          join public.commodities c on c.id = a.commodity_id
         where a.run_id = %s
         group by c.slug, c.sort_order
         order by c.sort_order
        """,
        (run_id,),
    )
