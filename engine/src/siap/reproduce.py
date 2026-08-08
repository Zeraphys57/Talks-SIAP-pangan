"""Verify that a stored run can be reproduced exactly (§9).

The determinism claim in this project is specific: given the same input rows,
the same parameters and the same seed, the detectors produce the same numbers.
Every run records its git SHA, seed, parameters and library versions so that
claim can be checked rather than believed.

This module checks it. It reloads a completed run's **stored** parameters and
seed — not today's `analysis.yaml`, which may have moved — recomputes every
score from `price_daily_unified`, and compares against what that run wrote.

### What a failure would mean

    scores differ          the seed is not reaching the estimator, or something
                           in the pipeline depends on dict/row ordering
    row counts differ      the input data changed since the run, so the
                           comparison is not about determinism at all
    library versions differ a number in the paper is attributable to a version
                           nobody recorded

The three are reported separately, because they have different remedies and
conflating them would make the check useless.

### Why comparison is exact

Floating point is deterministic for a fixed sequence of operations on fixed
inputs. If the same code, seed and data produce a score that differs in the
twelfth decimal, something is genuinely non-deterministic — thread scheduling,
hash ordering, an unseeded RNG — and a tolerance would hide exactly the bug this
exists to find. The stored values are `numeric(12,6)`, so the comparison is made
at that precision, which is the precision the claim is actually about.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .config import AnalysisConfig, IForestParams, ZScoreParams
from .db import Conn, fetch_all
from .modules import iforest, zscore
from .runs import _TRACKED_PACKAGES, git_sha, lib_versions

log = logging.getLogger(__name__)

# The scale `anomaly_scores.raw_score` is stored at. Comparing at more precision
# than the database keeps would report differences that were never persisted.
STORED_SCALE = Decimal("0.000001")


@dataclass
class Mismatch:
    commodity: str
    region: str
    obs_date: Any
    method: str
    stored: Decimal | None
    recomputed: Decimal | None


@dataclass
class ReproduceReport:
    run_id: int
    run_git_sha: str | None = None
    current_git_sha: str | None = None
    seed: int | None = None

    series_checked: int = 0
    scores_compared: int = 0
    mismatches: list[Mismatch] = field(default_factory=list)

    stored_rows: int = 0
    recomputed_rows: int = 0

    version_drift: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def scores_match(self) -> bool:
        return not self.mismatches

    @property
    def counts_match(self) -> bool:
        return self.stored_rows == self.recomputed_rows

    @property
    def code_matches(self) -> bool:
        """Same commit, and not a dirty tree — otherwise the SHA means nothing."""
        if self.run_git_sha is None or self.current_git_sha is None:
            return False
        return self.run_git_sha == self.current_git_sha and not self.current_git_sha.endswith(
            "-dirty"
        )

    @property
    def ok(self) -> bool:
        """Determinism is about the numbers. Version drift is reported, not fatal."""
        return self.scores_match and self.counts_match


def load_run(conn: Conn, run_id: int) -> dict[str, Any] | None:
    rows = fetch_all(
        conn,
        """
        select id, run_type, status, git_sha, seed, params, lib_versions
          from public.analysis_runs where id = %s
        """,
        (run_id,),
    )
    return rows[0] if rows else None


def latest_anomaly_run(conn: Conn) -> int | None:
    """The newest anomaly run that actually wrote scores.

    `partial` counts. A run is partial when some series were skipped for a
    stated reason — Kota Yogyakarta has one week of history, far short of
    IsolationForest's 60-row minimum — and the scores it did write are exactly
    as reproducible as a fully successful run's. Excluding them would mean the
    verifier silently had nothing to check.
    """
    rows = fetch_all(
        conn,
        "select max(id) as id from public.analysis_runs "
        "where run_type = 'anomaly' and status in ('success', 'partial')",
    )
    return int(rows[0]["id"]) if rows and rows[0]["id"] is not None else None


def _quantise(value: Any) -> Decimal | None:
    """Normalise a score to what the database would hold.

    NaN becomes None, because that is exactly what `_persist` writes: a score
    inside the 30-day warm-up window is not a number and is stored as NULL.
    Without this, every warm-up row would be reported as a mismatch — and worse,
    would appear to mismatch *itself*, since NaN never compares equal to NaN.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    decimal = Decimal(str(value))
    if decimal.is_nan():
        return None
    return decimal.quantize(STORED_SCALE)


def verify(conn: Conn, run_id: int, config: AnalysisConfig | None = None) -> ReproduceReport:
    """Recompute a stored anomaly run and compare it row by row."""
    from .analyze import demand_scope, load_demand, load_series

    record = load_run(conn, run_id)
    if record is None:
        raise ValueError(f"no analysis_runs row with id {run_id}")
    if record["run_type"] != "anomaly":
        raise ValueError(
            f"run #{run_id} is a {record['run_type']!r} run. Determinism is verified "
            f"against an 'anomaly' run, whose scores are stored row by row."
        )

    report = ReproduceReport(run_id=run_id)
    report.run_git_sha = record["git_sha"]
    report.current_git_sha = git_sha()
    report.seed = record["seed"]

    # The run's OWN parameters, not the current YAML. Reproducing a run means
    # reproducing what it did, and `analysis.yaml` may legitimately have moved
    # on since.
    params = record["params"] or {}
    if "zscore" not in params or "iforest" not in params:
        raise ValueError(
            f"run #{run_id} did not record its detector parameters, so it cannot be "
            f"reproduced. Runs written before parameters were captured are not "
            f"verifiable and should not be cited."
        )
    z_params = ZScoreParams(**params["zscore"])
    i_params = IForestParams(**params["iforest"])
    exclude_imputed = bool(params.get("exclude_imputed", True))
    seed = int(record["seed"]) if record["seed"] is not None else 0

    report.version_drift = _version_drift(record["lib_versions"])

    stored = _stored_scores(conn, run_id)
    report.stored_rows = sum(len(v) for v in stored.values())

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

    for pair in pairs:
        commodity_id, region_id = int(pair["commodity_id"]), int(pair["region_id"])
        frame = load_series(conn, commodity_id, region_id, exclude_imputed)
        if frame.empty:
            continue
        report.series_checked += 1
        # The same rule `analyze` applied, from the same place. Deriving it a
        # second time here is what made this check compare two different models.
        demand = load_demand(conn, commodity_id, demand_scope(str(pair["region"])))

        for method, recomputed in (
            (zscore.METHOD, zscore.compute(frame, z_params)),
            (iforest.METHOD, iforest.compute(frame, i_params, seed, demand)),
        ):
            if recomputed.empty:
                continue
            for row in recomputed.itertuples(index=False):
                report.recomputed_rows += 1
                key = (commodity_id, region_id, row.obs_date, method)
                new = _quantise(row.raw_score)
                old = stored.get(method, {}).get((commodity_id, region_id, row.obs_date))

                report.scores_compared += 1
                if old != new:
                    report.mismatches.append(
                        Mismatch(
                            commodity=str(pair["commodity"]),
                            region=str(pair["region"]),
                            obs_date=key[2],
                            method=method,
                            stored=old,
                            recomputed=new,
                        )
                    )

    if not report.counts_match:
        report.notes.append(
            f"{report.stored_rows} score(s) stored but {report.recomputed_rows} recomputed. "
            f"The input data has changed since the run, so a score difference would not "
            f"prove non-determinism. Re-run the analysis before drawing conclusions."
        )
    return report


def _stored_scores(
    conn: Conn, run_id: int
) -> dict[str, dict[tuple[int, int, Any], Decimal | None]]:
    out: dict[str, dict[tuple[int, int, Any], Decimal | None]] = {}
    for row in fetch_all(
        conn,
        """
        select method, commodity_id, region_id, obs_date, raw_score
          from public.anomaly_scores where run_id = %s
        """,
        (run_id,),
    ):
        method = str(row["method"])
        out.setdefault(method, {})[
            (int(row["commodity_id"]), int(row["region_id"]), row["obs_date"])
        ] = _quantise(row["raw_score"])
    return out


def _version_drift(recorded: Any) -> dict[str, tuple[str | None, str | None]]:
    """Packages whose version now differs from the one the run recorded."""
    if not isinstance(recorded, dict):
        return {}
    current = lib_versions()
    drift: dict[str, tuple[str | None, str | None]] = {}
    for package in _TRACKED_PACKAGES:
        was = recorded.get(package)
        now = current.get(package)
        if was != now:
            drift[package] = (was, now)
    return drift
