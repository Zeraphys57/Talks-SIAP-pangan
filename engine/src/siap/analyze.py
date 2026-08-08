"""Run the anomaly detectors over every series and persist their scores.

Both arms run over the same input under the same run record, so `zscore_only`,
`iforest_only` and `union` in M7's ablation are computed from scores that saw
identical data. If the two methods were fed different rows, the comparison
between them would be meaningless.

Imputed rows are excluded before scoring — see `input.exclude_imputed` in
analysis.yaml for why, and note the consequence: a region whose only source is
PIHPS loses roughly 2/7 of its days to weekend imputation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .config import AnalysisConfig, load_analysis
from .db import Conn, fetch_all, refresh_statistics
from .modules import iforest, zscore
from .runs import Run, start_run

log = logging.getLogger(__name__)


@dataclass
class SeriesResult:
    commodity: str
    region: str
    n_rows: int
    zscore_flagged: int = 0
    iforest_flagged: int = 0
    zscore_null: int = 0
    iforest_null: int = 0
    skipped: str | None = None


@dataclass
class AnalyzeReport:
    run_id: int = 0
    series: list[SeriesResult] = field(default_factory=list)
    rows_written: int = 0

    @property
    def skipped(self) -> list[SeriesResult]:
        return [s for s in self.series if s.skipped]


def load_series(
    conn: Conn, commodity_id: int, region_id: int, exclude_imputed: bool
) -> pd.DataFrame:
    """Real observations for one series, oldest first."""
    clause = "and not u.is_imputed" if exclude_imputed else ""
    rows = fetch_all(
        conn,
        f"""
        select u.obs_date, u.price_median as price
          from public.price_daily_unified u
         where u.commodity_id = %s and u.region_id = %s
           and u.price_median is not null
           {clause}
         order by u.obs_date
        """,
        (commodity_id, region_id),
    )
    return (
        pd.DataFrame(rows, columns=["obs_date", "price"])
        if rows
        else pd.DataFrame(columns=["obs_date", "price"])
    )


# Trends is collected for two scopes only; every other region is scored against
# the national signal.
DEMAND_SCOPES = ("nasional", "di_yogyakarta")


def demand_scope(region_slug: str) -> str:
    """The `demand_signals.region_scope` a region's series is scored against.

    Shared with `siap reproduce` deliberately. Reproduce used to derive this
    itself from `regions.level` — 'province', 'city', 'national' — which matches
    no `region_scope` at all, so `load_demand` returned nothing and the check
    refitted every forest on a constant `demand_z52` before comparing it against
    a model fitted on the real one. 37,597 of 79,114 scores "differed".

    It went unnoticed because Trends was throttled: both sides got an empty
    series and agreed. The moment Trends returned, the verifier started failing
    on a difference it was creating itself. Two copies of a lookup rule is one
    copy too many when one of them exists to check the other.
    """
    return region_slug if region_slug in DEMAND_SCOPES else "nasional"


def load_demand(conn: Conn, commodity_id: int, region_scope: str) -> pd.Series:
    """Weekly `interest_z52`, indexed by week_start. Empty when Trends has no data."""
    rows = fetch_all(
        conn,
        """
        select week_start, interest_z52
          from public.demand_signals
         where commodity_id = %s and region_scope = %s and interest_z52 is not null
         order by week_start
        """,
        (commodity_id, region_scope),
    )
    if not rows:
        return pd.Series(dtype="float64")
    frame = pd.DataFrame(rows)
    return pd.Series(
        frame["interest_z52"].astype(float).to_numpy(),
        index=pd.DatetimeIndex(frame["week_start"]),
    )


def _persist(
    conn: Conn, run_id: int, commodity_id: int, region_id: int, method: str, scored: pd.DataFrame
) -> int:
    payload = [
        (
            run_id,
            commodity_id,
            region_id,
            row.obs_date,
            method,
            None if pd.isna(row.raw_score) else float(row.raw_score),
            None if pd.isna(row.norm_score) else float(row.norm_score),
            bool(row.is_flagged),
            None if pd.isna(row.threshold_used) else float(row.threshold_used),
        )
        for row in scored.itertuples(index=False)
    ]
    if not payload:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.anomaly_scores
                (run_id, commodity_id, region_id, obs_date, method,
                 raw_score, norm_score, is_flagged, threshold_used)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, commodity_id, region_id, obs_date, method) do nothing
            """,
            payload,
        )
    return len(payload)


def run_detectors(conn: Conn, config: AnalysisConfig | None = None) -> AnalyzeReport:
    """Score every series with both detectors under one run record."""
    cfg = config or load_analysis()
    report = AnalyzeReport()

    run: Run = start_run(
        conn,
        "anomaly",
        seed=cfg.seed,
        params={
            "exclude_imputed": cfg.input.exclude_imputed,
            "zscore": cfg.zscore.model_dump(),
            "iforest": cfg.iforest.model_dump(),
        },
    )
    report.run_id = run.id

    pairs = fetch_all(
        conn,
        """
        select distinct u.commodity_id, u.region_id,
               c.slug as commodity, rg.slug as region
          from public.price_daily_unified u
          join public.commodities c on c.id = u.commodity_id
          join public.regions rg on rg.id = u.region_id
         order by rg.slug, c.slug
        """,
    )

    status = "failed"
    with_demand = 0
    try:
        for pair in pairs:
            commodity_id, region_id = int(pair["commodity_id"]), int(pair["region_id"])
            frame = load_series(conn, commodity_id, region_id, cfg.input.exclude_imputed)
            result = SeriesResult(
                commodity=str(pair["commodity"]), region=str(pair["region"]), n_rows=len(frame)
            )

            if frame.empty:
                result.skipped = "no real observations"
                report.series.append(result)
                continue

            zs = zscore.compute(frame, cfg.zscore)
            report.rows_written += _persist(
                conn, run.id, commodity_id, region_id, zscore.METHOD, zs
            )
            result.zscore_flagged = int(zs["is_flagged"].sum())
            result.zscore_null = int(zs["raw_score"].isna().sum())

            demand = load_demand(conn, commodity_id, demand_scope(result.region))
            if not demand.empty:
                with_demand += 1

            forest = iforest.compute(frame, cfg.iforest, cfg.seed, demand)
            report.rows_written += _persist(
                conn, run.id, commodity_id, region_id, iforest.METHOD, forest
            )
            result.iforest_flagged = int(forest["is_flagged"].sum())
            result.iforest_null = int(forest["raw_score"].isna().sum())

            if len(frame) < cfg.iforest.min_observations:
                result.skipped = (
                    f"iforest not fitted: {len(frame)} rows < {cfg.iforest.min_observations}"
                )
                run.note(f"{result.region}/{result.commodity}: {result.skipped}")

            report.series.append(result)

        conn.commit()

        # anomaly_scores just grew by tens of thousands of rows and is the driving
        # table of the fusion query that runs next. See db.refresh_statistics.
        refresh_statistics(conn, "anomaly_scores")

        if not any((s.iforest_flagged or s.iforest_null < s.n_rows) for s in report.series):
            run.note("no series produced Isolation Forest scores")
        # Measured, not assumed. This note asserted "Trends throttled" on every
        # run regardless, and kept asserting it after Trends came back — a run
        # record claiming less than the run actually used.
        run.note(
            f"scored {len(report.series)} series, {report.rows_written} score rows; "
            + (
                f"demand_z52 present for {with_demand} series"
                if with_demand
                else f"demand_z52 unavailable for every series and filled with "
                f"{cfg.iforest.demand_missing_fill}"
            )
        )
        status = "partial" if report.skipped else "success"
    finally:
        run.finish(status)

    return report


# ---------------------------------------------------------------------------
# Reporting for the M3 gate
# ---------------------------------------------------------------------------
def flag_counts(conn: Conn, run_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        select c.slug as commodity, a.method,
               count(*) filter (where a.is_flagged) as flagged,
               count(*) filter (where a.raw_score is not null) as scored,
               count(*) as total
          from public.anomaly_scores a
          join public.commodities c on c.id = a.commodity_id
         where a.run_id = %s
         group by c.slug, a.method, c.sort_order
         order by c.sort_order, a.method
        """,
        (run_id,),
    )


def top_flagged(conn: Conn, run_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Strongest flags, with the price move that produced them."""
    return fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region, a.obs_date, a.method,
               a.raw_score, a.norm_score, u.price_median,
               lag(u.price_median) over (
                   partition by a.commodity_id, a.region_id order by a.obs_date
               ) as prev_price
          from public.anomaly_scores a
          join public.commodities c on c.id = a.commodity_id
          join public.regions rg on rg.id = a.region_id
          left join public.price_daily_unified u
                 on u.commodity_id = a.commodity_id
                and u.region_id = a.region_id
                and u.obs_date = a.obs_date
         where a.run_id = %s and a.is_flagged
         order by a.norm_score desc nulls last, abs(a.raw_score) desc
         limit %s
        """,
        (run_id, limit),
    )
