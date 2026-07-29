"""Fit the regime clustering and persist the model and its assignments.

One model per run, covering every commodity x region x month cell at once.
Fitting per commodity would defeat the purpose: the point is to place a
commodity-month against the whole population of commodity-months, so that
"cabai in DIY in March 2024" can be called volatile *relative to everything
else observed*, not relative to cabai's own history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    dropped_months: int = 0


def load_cells(conn: Conn, config: AnalysisConfig) -> pd.DataFrame:
    """Every real daily observation, ready for monthly aggregation."""
    clause = "and not u.is_imputed" if config.input.exclude_imputed else ""
    rows = fetch_all(
        conn,
        f"""
        select c.slug as commodity, rg.slug as region,
               u.obs_date, u.price_median as price
          from public.price_daily_unified u
          join public.commodities c on c.id = u.commodity_id
          join public.regions rg on rg.id = u.region_id
         where u.price_median is not null
           {clause}
         order by c.slug, rg.slug, u.obs_date
        """,
    )
    return (
        pd.DataFrame(rows)
        if rows
        else pd.DataFrame(columns=["commodity", "region", "obs_date", "price"])
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
                    float(row.volatility),
                    float(row.cum_change),
                    int(row.cluster_id),
                    str(row.zone),
                    float(row.silhouette_sample),
                )
            )
        if payload:
            cur.executemany(
                """
                insert into public.cluster_assignments
                    (run_id, commodity_id, region_id, period_month,
                     feat_volatility, feat_cum_change, cluster_id, zone,
                     silhouette_sample)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        daily = load_cells(conn, cfg)
        cells = kmeans.build_cells(daily, cfg.kmeans)
        report.cells = len(cells)

        if cells.empty:
            run.note("no monthly cells met min_days_in_month; nothing to cluster")
            status = "partial"
            return report

        model = kmeans.fit(cells, cfg.kmeans, cfg.seed)
        report.model = model
        report.assignments_written = _persist(conn, run.id, model)
        conn.commit()

        run.note(
            f"k search {cfg.kmeans.k_min}..{cfg.kmeans.k_max} over {len(cells)} cells; "
            f"selected k={model.k_selected} on silhouette {model.silhouette_avg:.4f}"
        )
        if model.k_selected > 3:
            run.note(
                f"k={model.k_selected} > 3, so the middle clusters merge into kuning "
                f"(see docs/methods.md); k was not forced to 3"
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
               a.silhouette_sample
          from public.cluster_assignments a
          join public.commodities c on c.id = a.commodity_id
          join public.regions rg on rg.id = a.region_id
         where a.run_id = %s
           and a.period_month = coalesce(
                 %s,
                 (select max(period_month) from public.cluster_assignments where run_id = %s))
         order by a.zone desc, a.feat_volatility desc
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
               count(*) as total,
               round(avg(a.feat_volatility)::numeric, 5) as avg_volatility
          from public.cluster_assignments a
          join public.commodities c on c.id = a.commodity_id
         where a.run_id = %s
         group by c.slug, c.sort_order
         order by c.sort_order
        """,
        (run_id,),
    )
