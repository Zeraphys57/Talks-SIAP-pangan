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

### What the context deliberately does include

The operational definition (§7.2) is a change exceeding **+/-10% against the
trailing 30-day mean, sustained two days**. An annotator cannot apply that rule
without the trailing mean, so `context` carries it, and the window reaches 30
days back rather than 14 so the persistence half of the rule is visible too.

That is an input to the detector, not an output of it: the /lab chart draws a
+/-10% band around the mean and lets the annotator see how many days fall
outside it. Withholding the arithmetic would not make the labels more
independent, only noisier — and disagreement caused by mental arithmetic is
disagreement kappa cannot distinguish from disagreement about the market.

The judgement left to the human is the part that matters and cannot be coded:
whether a move that clears the bar is a real market event or a data artefact,
and whether anything in the world corroborates it.

Neither quantity reveals the stratum. Stratum A fires on |z| > 1.5 or a 7-day
change over 7%; the context shows a 30-day-mean deviation. Different baseline,
different threshold, so blinding holds.
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

# Context window, in days either side of the candidate date. Backwards reaches
# a full baseline period so the annotator can see what the trailing mean is made
# of; forwards covers the two-day persistence test with room to spare.
WINDOW_BEFORE = 30
WINDOW_AFTER = 14

# Trailing mean the operational definition is stated against.
BASELINE_DAYS = 30
BASELINE_MIN_OBS = 20

# The threshold in the definition itself, carried in the blob so the UI band and
# the paper cannot drift apart.
DEFINITION_PCT = 0.10


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
           and obs_date between %s - %s and %s + %s
         order by obs_date
        """,
        (commodity_id, region_id, obs_date, WINDOW_BEFORE, obs_date, WINDOW_AFTER),
    )

    # Trailing mean over real observations only. Averaging in interpolated days
    # would let a gap-filled stretch pull the baseline towards the very move
    # being judged.
    baseline = fetch_all(
        conn,
        """
        select avg(price_median) as mean_price, count(*) as n
          from public.price_daily_unified
         where commodity_id = %s and region_id = %s
           and obs_date between %s - %s and %s - 1
           and price_median is not null and not is_imputed
        """,
        (commodity_id, region_id, obs_date, BASELINE_DAYS, obs_date),
    )[0]
    n_baseline = int(baseline["n"] or 0)
    mean_price = float(baseline["mean_price"]) if n_baseline >= BASELINE_MIN_OBS else None

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
        "focus_date": str(obs_date),
        "baseline": {
            "days": BASELINE_DAYS,
            "n_obs": n_baseline,
            "min_obs": BASELINE_MIN_OBS,
            # None when the trailing period is too sparse to average honestly.
            # The UI then draws no band and says so, rather than drawing one
            # around a mean of four days.
            "mean_price": None if mean_price is None else round(mean_price, 2),
        },
        "definition_pct": DEFINITION_PCT,
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


def clear_pool(conn: Conn) -> int:
    """Discard the pool so it can be redrawn. Refuses once any label exists.

    Redrawing is legitimate exactly once: when the pool was sampled from data
    that has since grown, and nobody has labelled anything yet. After the first
    label, the pool is the thing the labels are a sample of — replacing it would
    silently change what every downstream number is a statement about, and no
    amount of re-running would reveal that it had happened.
    """
    n_labels = int(fetch_all(conn, "select count(*) as n from public.gt_labels")[0]["n"])
    if n_labels:
        raise ValueError(
            f"{n_labels} label(s) already exist. The pool is what those labels are a "
            f"sample of and must not be redrawn. If the pool genuinely has to change, "
            f"that is a new round: keep this one, report both, and say why in the paper."
        )
    with conn.cursor() as cur:
        cur.execute("delete from public.gt_candidates")
        removed = cur.rowcount
    conn.commit()
    return removed


def refresh_context(conn: Conn) -> int:
    """Recompute `context` for every existing candidate, in place.

    Membership is untouched. Which rows are in the pool was decided once by the
    seeded sampler and must stay decided: re-drawing it after labelling had
    begun would silently change what the labels are a sample of. Only the
    evidence shown alongside each row is rebuilt.
    """
    rows = fetch_all(
        conn, "select id, commodity_id, region_id, obs_date from public.gt_candidates order by id"
    )
    updated = 0
    for row in rows:
        blob = _context(conn, int(row["commodity_id"]), int(row["region_id"]), row["obs_date"])
        with conn.cursor() as cur:
            cur.execute(
                "update public.gt_candidates set context = %s where id = %s",
                (Json(blob), int(row["id"])),
            )
        updated += 1
    conn.commit()
    return updated


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
