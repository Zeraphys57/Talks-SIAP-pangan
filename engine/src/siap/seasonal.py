"""Run STL over every series and persist the components.

Skips are first-class output here. A commodity below the coverage floor is
recorded in `analysis_runs.notes` with its actual week count, so "why is there
no seasonality for kota_yogyakarta?" has an answer in the database rather than
in someone's memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from .config import AnalysisConfig, load_analysis
from .db import Conn, fetch_all
from .modules import stl
from .runs import start_run

log = logging.getLogger(__name__)


@dataclass
class SeasonalReport:
    run_id: int = 0
    results: list[stl.SeasonalResult] = field(default_factory=list)
    rows_written: int = 0

    @property
    def decomposed(self) -> list[stl.SeasonalResult]:
        return [r for r in self.results if r.ok]

    @property
    def skipped(self) -> list[stl.SeasonalResult]:
        return [r for r in self.results if not r.ok]


def load_series(
    conn: Conn, commodity_id: int, region_id: int, exclude_imputed: bool
) -> pd.DataFrame:
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
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["obs_date", "price"])


def _persist(
    conn: Conn,
    run_id: int,
    commodity_id: int,
    region_id: int,
    result: stl.SeasonalResult,
    freq: str,
) -> int:
    if result.components.empty:
        return 0
    payload = [
        (
            run_id,
            commodity_id,
            region_id,
            row.period_start,
            float(row.observed),
            float(row.trend),
            float(row.seasonal),
            float(row.resid),
            freq,
        )
        for row in result.components.itertuples(index=False)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.seasonal_components
                (run_id, commodity_id, region_id, period_start,
                 observed, trend, seasonal, resid, resample_freq)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, commodity_id, region_id, period_start) do nothing
            """,
            payload,
        )
    return len(payload)


def run_seasonal(conn: Conn, config: AnalysisConfig | None = None) -> SeasonalReport:
    cfg = config or load_analysis()
    report = SeasonalReport()

    run = start_run(conn, "seasonal", seed=cfg.seed, params={"stl": cfg.stl.model_dump()})
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
    try:
        for pair in pairs:
            commodity_id, region_id = int(pair["commodity_id"]), int(pair["region_id"])
            frame = load_series(conn, commodity_id, region_id, cfg.input.exclude_imputed)
            result = stl.decompose(frame, cfg.stl, str(pair["commodity"]), str(pair["region"]))
            report.results.append(result)

            if not result.ok:
                run.note(f"{result.region}/{result.commodity}: SKIPPED — {result.skipped}")
                continue

            report.rows_written += _persist(
                conn, run.id, commodity_id, region_id, result, cfg.stl.resample_freq
            )

        conn.commit()
        run.note(
            f"decomposed {len(report.decomposed)} of {len(report.results)} series; "
            f"{report.rows_written} weekly component rows"
        )
        status = "partial" if report.skipped else "success"
    finally:
        run.finish(status)

    return report
