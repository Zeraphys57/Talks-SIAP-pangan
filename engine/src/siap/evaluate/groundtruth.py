"""Stratified candidate pool for ground-truth labelling (§7.1).

Two strata, shuffled together:

**Stratum A — `rule_flagged`.** Dates where `|z| > 1.5` OR `|Δ7d| > 7%`. This is
deliberately *more permissive* than the detection thresholds (`|z| >= 2.5`,
contamination 0.03), so the pool is not a subset of what the model already
found.

**Stratum B — `random_control`.** A random sample of dates neither rule touched.
**This is what makes recall computable.** If annotators only ever saw dates the
model flagged, a miss could never be observed and recall would be undefined —
the single most common way an anomaly-detection evaluation quietly becomes
meaningless.

Candidates carry a `shuffle_key` drawn from the configured seed, and the
labelling UI reads the stratum-blind `gt_labeling_queue` view. An annotator who
could tell which stratum a candidate came from would be labelling the sampler,
not the market.

The `context` blob shows the surrounding price window and **never** contains
model output. Showing an annotator the anomaly score would make the label a
judgement about the model rather than independent evidence about the world.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

from psycopg.types.json import Json

from ..config import EvaluationParams
from ..db import Conn, fetch_all

log = logging.getLogger(__name__)

STRATUM_FLAGGED = "rule_flagged"
STRATUM_CONTROL = "random_control"


@dataclass
class PoolReport:
    stratum_a: int = 0
    stratum_b: int = 0
    written: int = 0
    skipped_existing: int = 0

    @property
    def total(self) -> int:
        return self.stratum_a + self.stratum_b


def _candidate_rows(
    conn: Conn, anomaly_run_id: int, params: EvaluationParams
) -> list[dict[str, Any]]:
    """Every scored day, tagged with whether either permissive rule fires."""
    return fetch_all(
        conn,
        """
        with z as (
            select a.commodity_id, a.region_id, a.obs_date, a.raw_score as z
              from public.anomaly_scores a
             where a.run_id = %(run)s and a.method = 'zscore'
        ),
        prices as (
            select u.commodity_id, u.region_id, u.obs_date, u.price_median,
                   p.price_median as prev7, u.is_imputed
              from public.price_daily_unified u
              left join public.price_daily_unified p
                     on p.commodity_id = u.commodity_id
                    and p.region_id    = u.region_id
                    and p.obs_date     = u.obs_date - 7
             where u.price_median is not null and not u.is_imputed
        )
        select c.slug as commodity, rg.slug as region,
               pr.commodity_id, pr.region_id, pr.obs_date,
               pr.price_median, pr.prev7, z.z,
               case
                 when abs(coalesce(z.z, 0)) > %(absz)s then true
                 when pr.prev7 is not null and pr.prev7 > 0
                      and abs(pr.price_median / pr.prev7 - 1) > %(pct)s then true
                 else false
               end as rule_hit
          from prices pr
          join public.commodities c on c.id = pr.commodity_id
          join public.regions rg on rg.id = pr.region_id
          left join z on z.commodity_id = pr.commodity_id
                     and z.region_id   = pr.region_id
                     and z.obs_date    = pr.obs_date
         order by pr.obs_date
        """,
        {
            "run": anomaly_run_id,
            "absz": params.stratum_a_abs_z,
            "pct": params.stratum_a_pct_change_7d,
        },
    )


def _context(conn: Conn, commodity_id: int, region_id: int, obs_date: Any) -> dict[str, Any]:
    """Price window around a candidate — evidence only, never model output."""
    window = fetch_all(
        conn,
        """
        select obs_date, price_median, is_imputed, n_sources
          from public.price_daily_unified
         where commodity_id = %s and region_id = %s
           and obs_date between %s - 14 and %s + 14
         order by obs_date
        """,
        (commodity_id, region_id, obs_date, obs_date),
    )
    return {
        "window": [
            {
                "date": str(r["obs_date"]),
                "price": None if r["price_median"] is None else float(r["price_median"]),
                "imputed": bool(r["is_imputed"]),
                "sources": int(r["n_sources"]),
            }
            for r in window
        ],
    }


def generate_pool(
    conn: Conn, anomaly_run_id: int, params: EvaluationParams, seed: int, run_id: int | None = None
) -> PoolReport:
    """Build the stratified pool. Idempotent: existing candidates are left alone."""
    report = PoolReport()
    rng = random.Random(seed)

    rows = _candidate_rows(conn, anomaly_run_id, params)
    flagged = [r for r in rows if r["rule_hit"]]
    control_source = [r for r in rows if not r["rule_hit"]]

    # Cap stratum A first, then size B relative to what A actually became.
    a_cap = int(params.max_candidates / (1 + params.stratum_b_fraction))
    if len(flagged) > a_cap:
        flagged = rng.sample(flagged, a_cap)

    b_target = min(int(len(flagged) * params.stratum_b_fraction), len(control_source))
    control = rng.sample(control_source, b_target) if b_target else []

    report.stratum_a, report.stratum_b = len(flagged), len(control)

    existing = {
        (int(r["commodity_id"]), int(r["region_id"]), r["obs_date"])
        for r in fetch_all(
            conn, "select commodity_id, region_id, obs_date from public.gt_candidates"
        )
    }

    payload = []
    for row, stratum in [(r, STRATUM_FLAGGED) for r in flagged] + [
        (r, STRATUM_CONTROL) for r in control
    ]:
        key = (int(row["commodity_id"]), int(row["region_id"]), row["obs_date"])
        if key in existing:
            report.skipped_existing += 1
            continue
        payload.append(
            (
                int(row["commodity_id"]),
                int(row["region_id"]),
                row["obs_date"],
                stratum,
                rng.random(),
                Json(
                    _context(conn, int(row["commodity_id"]), int(row["region_id"]), row["obs_date"])
                ),
                run_id,
            )
        )

    if payload:
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.gt_candidates
                    (commodity_id, region_id, obs_date, sampling_stratum,
                     shuffle_key, context, generated_by_run)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (commodity_id, region_id, obs_date) do nothing
                """,
                payload,
            )
        conn.commit()
    report.written = len(payload)
    return report


def pool_summary(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        select sampling_stratum, count(*) as n,
               min(obs_date) as first_date, max(obs_date) as last_date
          from public.gt_candidates
         group by sampling_stratum
         order by sampling_stratum
        """,
    )


def labelling_progress(conn: Conn) -> list[dict[str, Any]]:
    """How far each annotator has got. Read under the service role only."""
    return fetch_all(
        conn,
        """
        select l.annotator_code,
               count(*) as labelled,
               count(*) filter (where l.label = 'anomali') as anomali,
               count(*) filter (where l.label = 'normal')  as normal,
               count(*) filter (where l.label = 'ragu')    as ragu,
               (select count(*) from public.gt_candidates) as pool
          from public.gt_labels l
         group by l.annotator_code
         order by l.annotator_code
        """,
    )
