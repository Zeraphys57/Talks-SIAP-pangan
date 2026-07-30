"""Compute fusion alerts from the stored detector scores.

Reads the most recent `anomaly` run rather than re-scoring, so an alert is
always attributable to a specific detector run and the two cannot drift apart.

The corroboration term needs per-source movement, which the detectors do not
produce — they run on the reconciled median. A source is counted as flagging
when its **own** price moved by at least `pct_change_threshold` over seven days.
Comparing against `obs_date - 7` rather than "seven rows back" matters: PIHPS
publishes only on weekdays, so seven rows is nearly ten days for that source,
while a seven-day offset preserves the weekday and lines up correctly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Json

from .config import FusionConfig, load_fusion
from .db import Conn, fetch_all, fetch_value
from .modules.fusion import FusionInput, FusionResult, fuse
from .runs import start_run

log = logging.getLogger(__name__)


@dataclass
class FuseReport:
    run_id: int = 0
    source_run_id: int | None = None
    rows_written: int = 0
    level_counts: dict[str, int] = field(default_factory=dict)
    downgrades: dict[str, int] = field(default_factory=dict)


def latest_anomaly_run(conn: Conn) -> int | None:
    value = fetch_value(
        conn,
        "select id from public.analysis_runs "
        "where run_type = 'anomaly' and status in ('success', 'partial') "
        "order by id desc limit 1",
    )
    return int(value) if value is not None else None


def load_inputs(conn: Conn, anomaly_run_id: int, cfg: FusionConfig) -> list[dict[str, Any]]:
    """Everything fusion needs, one row per commodity x region x date."""
    return fetch_all(
        conn,
        """
        with scores as (
            select a.commodity_id, a.region_id, a.obs_date,
                   max(a.norm_score) filter (where a.method = 'zscore')  as norm_zscore,
                   max(a.norm_score) filter (where a.method = 'iforest') as norm_iforest,
                   bool_or(a.is_flagged) filter (where a.method = 'zscore')  as z_flag,
                   bool_or(a.is_flagged) filter (where a.method = 'iforest') as i_flag
              from public.anomaly_scores a
             where a.run_id = %(run)s
             group by a.commodity_id, a.region_id, a.obs_date
        ),
        -- The dates this run actually covers. `scores` is filtered by run_id;
        -- momentum and per_source were not, so their cost grew with the whole
        -- archive while every row outside this window was discarded by the joins
        -- below. Bounding them is output-identical by construction: the final
        -- select joins on `s.obs_date`, which cannot fall outside [lo, hi].
        bounds as (
            select min(obs_date) as lo, max(obs_date) as hi from scores
        ),
        momentum as (
            select u.commodity_id, u.region_id, u.obs_date,
                   u.price_median,
                   p.price_median as price_prev7
              from public.price_daily_unified u
              left join public.price_daily_unified p
                     on p.commodity_id = u.commodity_id
                    and p.region_id   = u.region_id
                    and p.obs_date    = u.obs_date - 7
             where u.obs_date between (select lo from bounds)
                                  and (select hi from bounds)
        ),
        per_source as (
            select o.commodity_id, o.region_id, o.obs_date,
                   count(*) as n_reporting,
                   count(*) filter (
                       where b.price_idr is not null and b.price_idr > 0
                         and abs(o.price_idr / b.price_idr - 1) >= %(thresh)s
                   ) as n_flagging
              from public.price_observations o
              left join public.price_observations b
                     on b.commodity_id = o.commodity_id
                    and b.region_id    = o.region_id
                    and b.source_id    = o.source_id
                    and b.obs_date     = o.obs_date - %(window)s
             where o.obs_date between (select lo from bounds)
                                  and (select hi from bounds)
             group by o.commodity_id, o.region_id, o.obs_date
        ),
        -- Deliberately NOT bounded: lifetime_sources means what it says, and a
        -- window would silently redefine "has this pair ever had one source".
        -- It is a grouped scan rather than a self-join, so it is cheap.
        coverage as (
            select commodity_id, region_id,
                   count(distinct source_id) as lifetime_sources
              from public.price_observations
             group by commodity_id, region_id
        ),
        demand as (
            select d.commodity_id, d.week_start, d.region_scope, d.interest_z52
              from public.demand_signals d
             where d.week_start <= (select hi from bounds)
        )
        select c.slug as commodity, rg.slug as region, s.obs_date,
               s.commodity_id, s.region_id,
               s.norm_zscore, s.norm_iforest, s.z_flag, s.i_flag,
               m.price_median, m.price_prev7,
               coalesce(ps.n_reporting, 0) as n_reporting,
               coalesce(ps.n_flagging, 0)  as n_flagging,
               cov.lifetime_sources,
               (select dd.interest_z52 from demand dd
                 where dd.commodity_id = s.commodity_id
                   and dd.week_start <= s.obs_date
                 order by dd.week_start desc limit 1) as demand_z52
          from scores s
          join public.commodities c on c.id = s.commodity_id
          join public.regions rg on rg.id = s.region_id
          left join momentum m
                 on m.commodity_id = s.commodity_id
                and m.region_id   = s.region_id
                and m.obs_date    = s.obs_date
          left join per_source ps
                 on ps.commodity_id = s.commodity_id
                and ps.region_id   = s.region_id
                and ps.obs_date    = s.obs_date
          left join coverage cov
                 on cov.commodity_id = s.commodity_id
                and cov.region_id   = s.region_id
         order by s.obs_date, rg.slug, c.slug
        """,
        {
            "run": anomaly_run_id,
            "thresh": cfg.corroboration.pct_change_threshold,
            "window": cfg.corroboration.pct_change_window_days,
        },
    )


def to_input(row: dict[str, Any]) -> FusionInput:
    price, prev7 = row.get("price_median"), row.get("price_prev7")
    pct_change = None
    if price is not None and prev7 not in (None, 0):
        pct_change = float(price) / float(prev7) - 1

    return FusionInput(
        norm_zscore=None if row["norm_zscore"] is None else float(row["norm_zscore"]),
        norm_iforest=None if row["norm_iforest"] is None else float(row["norm_iforest"]),
        zscore_flagged=bool(row["z_flag"]),
        iforest_flagged=bool(row["i_flag"]),
        pct_change_7d=pct_change,
        demand_z52=None if row["demand_z52"] is None else float(row["demand_z52"]),
        n_sources_reporting=int(row["n_reporting"]),
        n_sources_flagging=int(row["n_flagging"]),
        single_source_coverage=int(row["lifetime_sources"] or 0) <= 1,
    )


def run_fusion(conn: Conn, config: FusionConfig | None = None) -> FuseReport:
    cfg = config or load_fusion()
    report = FuseReport()

    anomaly_run = latest_anomaly_run(conn)
    report.source_run_id = anomaly_run

    run = start_run(
        conn,
        "fusion",
        params={
            "anomaly_run_id": anomaly_run,
            "weights": cfg.weights.model_dump(),
            "components": cfg.components.model_dump(),
            "thresholds": cfg.thresholds.model_dump(),
            "corroboration": cfg.corroboration.model_dump(),
        },
    )
    report.run_id = run.id

    status = "failed"
    try:
        if anomaly_run is None:
            run.note("no completed anomaly run; nothing to fuse")
            status = "partial"
            return report

        rows = load_inputs(conn, anomaly_run, cfg)
        payload = []
        for row in rows:
            result: FusionResult = fuse(to_input(row), cfg)
            report.level_counts[result.level] = report.level_counts.get(result.level, 0) + 1
            reason = result.components.get("reason")
            if reason:
                report.downgrades[str(reason)] = report.downgrades.get(str(reason), 0) + 1
            payload.append(
                (
                    run.id,
                    int(row["commodity_id"]),
                    int(row["region_id"]),
                    row["obs_date"],
                    result.score,
                    result.level,
                    Json(result.components),
                    result.corroboration,
                    result.recommendation_id,
                )
            )

        if payload:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    insert into public.alerts
                        (run_id, commodity_id, region_id, obs_date, fusion_score,
                         level, components, corroboration, recommendation_id)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (run_id, commodity_id, region_id, obs_date) do nothing
                    """,
                    payload,
                )
        conn.commit()
        report.rows_written = len(payload)

        run.note(
            f"fused {len(payload)} alerts from anomaly run #{anomaly_run}: "
            + ", ".join(f"{k}={v}" for k, v in sorted(report.level_counts.items()))
        )
        if report.downgrades:
            run.note(
                "downgrades: " + ", ".join(f"{k}={v}" for k, v in sorted(report.downgrades.items()))
            )
        run.note("demand_z52 unavailable for every row (Trends throttled); D contributed 0")
        status = "success"
    finally:
        run.finish(status)

    return report


# ---------------------------------------------------------------------------
# Reporting for the M6 gate
# ---------------------------------------------------------------------------
def alert_board(conn: Conn, run_id: int, obs_date: Any = None) -> list[dict[str, Any]]:
    """One day's alerts with every component column visible."""
    return fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region, a.obs_date,
               a.fusion_score, a.level, a.corroboration, a.recommendation_id,
               a.components
          from public.alerts a
          join public.commodities c on c.id = a.commodity_id
          join public.regions rg on rg.id = a.region_id
         where a.run_id = %s
           and a.obs_date = coalesce(
                 %s, (select max(obs_date) from public.alerts where run_id = %s))
         order by a.fusion_score desc, rg.slug, c.slug
        """,
        (run_id, obs_date, run_id),
    )


def strongest_alert(conn: Conn, run_id: int) -> dict[str, Any] | None:
    """The highest-scoring alert overall — the gate's worked example."""
    rows = fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region, a.obs_date,
               a.fusion_score, a.level, a.corroboration, a.components,
               u.price_median, p.price_median as price_prev7
          from public.alerts a
          join public.commodities c on c.id = a.commodity_id
          join public.regions rg on rg.id = a.region_id
          left join public.price_daily_unified u
                 on u.commodity_id = a.commodity_id and u.region_id = a.region_id
                and u.obs_date = a.obs_date
          left join public.price_daily_unified p
                 on p.commodity_id = a.commodity_id and p.region_id = a.region_id
                and p.obs_date = a.obs_date - 7
         where a.run_id = %s
         order by a.fusion_score desc
         limit 1
        """,
        (run_id,),
    )
    return rows[0] if rows else None
