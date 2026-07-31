"""K-Means regime clustering (§6.3).

The unit of observation is **commodity x region x month**, and that is the most
consequential correction this project makes to the original proposal.

Clustering twelve commodities gives twelve points. A silhouette score computed
on twelve points while searching k up to 8 is noise: adding or dropping a single
commodity would swing the selected k, and nothing distinguishes real structure
from an arbitrary partition of a tiny sample. Widening the unit to
(commodity, region, month) yields on the order of a thousand cells.

It also changes what a cluster *means*. "Cabai is a volatile commodity" is
static and unfalsifiable; "cabai in DIY during March 2024 sat in a
high-volatility, rising regime" is a claim about a period, lets the same
commodity move between zones over time, and is what a warung owner actually
needs to hear.

Two features per cell:

* `volatility`  — standard deviation of daily log returns within the month
* `cum_change`  — (last - first) / first within the month

Zones are assigned **post hoc**, after k is chosen, by ranking cluster centroids
on a weighted sum of their standardised coordinates. Selection is floored at
`k_select_min` rather than pinned: see `search_k` for what that floor costs and
why it is there.

## The provenance gate

Not every cell describes a month of trading. Some describe a portal that stopped
resurveying: M2 found PIHPS pinned to an identical rupiah for days at a time, and
in 2023 it was the only source for jawa_tengah and di_yogyakarta. Such a cell has
a real, low, entirely meaningless volatility, and feeding it to K-Means lets a
publication cadence shape the centroids.

The gate is on **provenance, not on the feature value**. A volatility threshold
would have been a line of code and is indefensible: it cannot distinguish a
genuinely stable price from a stuck feed, so it would suppress real stable
commodities in order to hide a data problem. Instead each cell carries four
measurements of where its numbers came from — real observation count, distinct
real values, the share of observations inside a carry-forward run, and the
imputed share — and fails on those.

A gated cell **keeps its row**, with its features, `zone = NULL` and a
`quality_reason`. It is excluded from the fit, not from the table. Deleting it
would destroy the audit trail and make coverage unreportable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_samples, silhouette_score
from sklearn.preprocessing import StandardScaler

from ..config import CellQualityParams, KMeansParams

log = logging.getLogger(__name__)

FEATURES = ["volatility", "cum_change"]
ZONES = ("hijau", "kuning", "merah")

# Provenance measurements carried on every cell, gated or not. Stored so the
# thresholds can be argued from the observed distribution rather than asserted.
QUALITY_FEATURES = ["real_obs", "distinct_real", "stale_fraction", "imputed_fraction"]


@dataclass
class KSearchEntry:
    k: int
    inertia: float
    silhouette: float

    def as_dict(self) -> dict[str, float | int]:
        return {"k": self.k, "inertia": self.inertia, "silhouette": self.silhouette}


@dataclass
class ClusterModel:
    k_selected: int
    k_search: list[KSearchEntry]
    silhouette_avg: float
    centroids: dict[int, dict[str, float]]
    # Holds the fitted mean/scale plus the feature names they belong to, so the
    # transform can be reapplied later without guessing column order.
    scaler_params: dict[str, Any]
    zone_mapping: dict[int, str]
    # Cells the fit actually saw, which is no longer the same as the number of
    # rows written: gated cells are persisted and excluded.
    n_samples: int
    n_gated: int = 0
    gate_reasons: dict[str, int] = field(default_factory=dict)
    #: "global" (primary, persisted) or "within_commodity" (secondary, reported).
    #: Centroid units differ between the two and are not comparable.
    variant: str = "global"
    assignments: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def k_search_json(self) -> list[dict[str, float | int]]:
        return [entry.as_dict() for entry in self.k_search]


def gate_reason(
    real_obs: int,
    distinct_real: int,
    stale_fraction: float,
    imputed_fraction: float,
    quality: CellQualityParams,
) -> str | None:
    """Why this cell must not enter the fit, or None if it may.

    First failure wins, so the reason names the most fundamental problem rather
    than the last one checked: a cell with 3 real observations is reported as
    thin, not as stale, even though it is technically both.
    """
    if real_obs < quality.min_real_obs:
        return "insufficient_real_obs"
    if distinct_real < quality.min_distinct_real:
        return "insufficient_distinct_values"
    if stale_fraction >= quality.max_stale_fraction:
        return "stale_dominated"
    if (
        quality.max_imputed_fraction is not None
        and imputed_fraction >= quality.max_imputed_fraction
    ):
        return "imputation_dominated"
    return None


def _stale_flags(real: pd.DataFrame, run_days: int) -> pd.Series:
    """Per real observation: is it inside a run of `run_days` identical prices?

    Runs are found on the whole series for a commodity x region, not per month.
    A portal that carries the same value from late March into early April is
    doing the same thing on both sides of the boundary, and computing runs
    per-month would reset the counter and let the longest carry-forwards through.
    """
    if real.empty:
        return pd.Series(dtype=bool)
    by_series = real.groupby(["commodity", "region"], sort=False)["price"]
    run_id = by_series.transform(lambda s: (s != s.shift()).cumsum())
    run_length = real.assign(_run=run_id).groupby(["commodity", "region", "_run"])["price"]
    return run_length.transform("size") >= run_days


def build_cells(frame: pd.DataFrame, params: KMeansParams) -> pd.DataFrame:
    """Aggregate a daily series into monthly regime features plus provenance.

    `frame` needs `commodity`, `region`, `obs_date`, `price`, `is_imputed`.

    Every (commodity, region, month) with at least one observation produces a
    row. Features are computed from **real** observations only — an interpolated
    value lies exactly on the line between its neighbours, so including it would
    shrink the very standard deviation being measured. Cells that cannot support
    a feature at all (fewer than three real observations, so fewer than two log
    returns) still produce a row, with null features and a `quality_reason`.
    """
    columns = [
        "commodity",
        "region",
        "period_month",
        *FEATURES,
        *QUALITY_FEATURES,
        "n_days",
        "quality_reason",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    # reset_index because the staleness flags are written back by label. A
    # caller that built this frame with pd.concat carries duplicate labels, and
    # the assignment would fail or, worse, broadcast to the wrong rows.
    work = frame.copy().reset_index(drop=True)
    work["obs_date"] = pd.to_datetime(work["obs_date"])
    if "is_imputed" not in work.columns:
        work["is_imputed"] = False
    work["is_imputed"] = work["is_imputed"].fillna(False).astype(bool)
    work = work.sort_values(["commodity", "region", "obs_date"])
    work["period_month"] = work["obs_date"].dt.to_period("M").dt.to_timestamp()

    real = work.loc[~work["is_imputed"]]
    work["is_stale"] = False
    if not real.empty:
        work.loc[real.index, "is_stale"] = _stale_flags(real, params.quality.stale_run_days)

    rows: list[dict[str, Any]] = []
    for (commodity, region, month), group in work.groupby(
        ["commodity", "region", "period_month"], sort=True
    ):
        real_rows = group.loc[~group["is_imputed"]]
        prices = real_rows["price"].astype(float).to_numpy()
        real_obs = len(prices)

        stale_fraction = float(real_rows["is_stale"].sum()) / real_obs if real_obs else 1.0
        imputed_fraction = float((len(group) - real_obs) / len(group))
        distinct_real = int(real_rows["price"].nunique())

        # Log returns: a 10% move costs the same at any price level, so
        # volatility is comparable across commodities an order of magnitude
        # apart. Raw returns would make daging-sapi look calm by construction.
        #
        # Each return is then divided by sqrt(days elapsed). Imputed rows are
        # excluded, so consecutive real observations are not consecutive days: a
        # Friday->Monday step is one return covering three days, and the
        # variance of a 3-day return is about 3x a 1-day return. Left raw, that
        # inflates the standard deviation by ~1.73x on every such step — and the
        # steps are not evenly distributed across regions. jawa_timur has none
        # (mean gap exactly 1.000 days), di_yogyakarta has one most weeks (mean
        # gap 1.373). All regions then enter ONE K-Means, so DIY was measured as
        # 22.8% more volatile than jawa_timur partly as an artefact of when its
        # portal publishes. Dividing by sqrt(dt) puts every return on a per-day
        # footing before they are compared.
        volatility = cum_change = float("nan")
        if real_obs >= 3:
            log_returns = np.diff(np.log(prices))
            elapsed = np.diff(real_rows["obs_date"].to_numpy()).astype("timedelta64[D]")
            elapsed = elapsed.astype(float)
            # Same-day duplicates cannot occur in price_daily_unified, but a
            # zero here would divide by zero rather than fail loudly.
            elapsed[elapsed <= 0] = 1.0
            volatility = float(np.std(log_returns / np.sqrt(elapsed), ddof=1))
            cum_change = float((prices[-1] - prices[0]) / prices[0])

        rows.append(
            {
                "commodity": commodity,
                "region": region,
                "period_month": month.date(),
                "volatility": volatility,
                "cum_change": cum_change,
                "real_obs": real_obs,
                "distinct_real": distinct_real,
                "stale_fraction": stale_fraction,
                "imputed_fraction": imputed_fraction,
                "n_days": len(group),
                "quality_reason": gate_reason(
                    real_obs, distinct_real, stale_fraction, imputed_fraction, params.quality
                ),
            }
        )

    cells = pd.DataFrame(rows, columns=columns)
    # A cell can pass every provenance check and still have no computable
    # feature if its real observations carry a non-positive price. Nothing in
    # the archive does, but a NaN reaching KMeans would be a crash rather than a
    # reported exclusion, so it is named here.
    unusable = cells["quality_reason"].isna() & cells[FEATURES].isna().any(axis=1)
    cells.loc[unusable, "quality_reason"] = "features_uncomputable"
    return cells


def search_k(scaled: np.ndarray, params: KMeansParams, seed: int) -> tuple[list[KSearchEntry], int]:
    """Fit every k in range, recording inertia and silhouette. Returns the best k.

    The whole curve is returned, not just the winner — it is a required paper
    figure, and keeping only the selected k would make it unreproducible without
    a re-run.

    **k is selected, not forced.** There was a `k_select_min = 3` floor here,
    because on the raw features the silhouette preferred k=2 (0.7896 against
    0.7057 for k=3, run #68) and two clusters leave `kuning` unreachable. That
    floor was removed once measurement 1 showed *why* k=2 won: the volatility
    feature was inflated on regions whose portals skip days, which smeared the
    middle of the distribution. With returns normalised by sqrt(days elapsed),
    k=3 wins the silhouette outright (0.8009 against 0.7983 for k=2, run #80)
    and no floor is needed. Every figure quoting this margin computes it from
    the run it draws, because the fit moves — run #70 measured 0.8019/0.7984.

    If some future data does select k=2, the honest output is two zones, and the
    zone table will say so rather than a floor manufacturing a third.
    """
    entries: list[KSearchEntry] = []
    # Silhouette needs at least k+1 samples and at least 2 clusters.
    k_ceiling = min(params.k_max, len(scaled) - 1)

    for k in range(params.k_min, k_ceiling + 1):
        model = KMeans(
            n_clusters=k, n_init=params.n_init, max_iter=params.max_iter, random_state=seed
        )
        labels = model.fit_predict(scaled)
        if len(set(labels)) < 2:
            continue
        entries.append(
            KSearchEntry(
                k=k,
                inertia=float(model.inertia_),
                silhouette=float(silhouette_score(scaled, labels)),
            )
        )

    if not entries:
        raise ValueError("no k in the configured range produced more than one cluster")

    best = max(entries, key=lambda e: e.silhouette)
    return entries, best.k


def assign_zones(centroids: np.ndarray, params: KMeansParams) -> dict[int, str]:
    """Map cluster ids to zones, post hoc, by ranking centroid severity.

    Score = w_v * z(volatility) + w_c * z(max(0, cum_change)), on the
    *standardised* centroid coordinates. Highest -> merah, lowest -> hijau,
    everything between -> kuning. With k > 3 the middle clusters merge,
    deliberately.

    **Only upward cumulative movement contributes.** The reader is a buyer: a
    month whose price fell is not a risk to them, so a falling cluster should
    not be pushed *down* the ranking by how far it fell — it should be ranked on
    its volatility alone, like a flat one. Clamping at zero does that.

    `abs(cum_change)` would be the wrong fix: it would rank a price collapse as
    `merah`, telling a warung owner to worry about the one movement that is in
    their favour.

    Volatility contributes in full and unsigned, because unpredictability blocks
    planning in both directions — a price that swings wildly is hard to buy
    against whichever way it ends the month.
    """
    volatility = centroids[:, 0]
    cum_change = np.maximum(0.0, centroids[:, 1])

    def z(values: np.ndarray) -> np.ndarray:
        spread = values.std()
        return (values - values.mean()) / spread if spread > 0 else np.zeros_like(values)

    severity = params.zone_weight_volatility * z(volatility) + params.zone_weight_cum_change * z(
        cum_change
    )
    order = np.argsort(severity)  # ascending: calmest first

    mapping: dict[int, str] = {}
    for rank, cluster_id in enumerate(order):
        if rank == 0:
            mapping[int(cluster_id)] = "hijau"
        elif rank == len(order) - 1:
            mapping[int(cluster_id)] = "merah"
        else:
            mapping[int(cluster_id)] = "kuning"

    # With k == 2 there is no middle; the ranking still yields one of each.
    return mapping


def scale_within_commodity(fittable: pd.DataFrame) -> np.ndarray:
    """Standardise each feature *within* its commodity.

    The secondary analysis. The global fit answers "which commodity-months are
    extreme against the whole population", and measurably answers it by
    recovering commodity identity: `merah` is 100% cabai and bawang-merah, and
    eight of twelve commodities never leave one zone. That is a defensible
    answer to Tujuan 3, which asks for commodities grouped by volatility — but
    it is not a claim about *periods*, which is what the dashboard says it is.

    Normalising within commodity removes the between-commodity level so the
    remaining structure is temporal: "is cabai unusually volatile **for cabai**
    this month". A commodity with only one month, or with no spread on a
    feature, standardises to zero rather than to a division by zero.
    """
    out = fittable[FEATURES].astype(float).copy()
    for feature in FEATURES:
        grouped = out.groupby(fittable["commodity"])[feature]
        spread = grouped.transform("std")
        centred = out[feature] - grouped.transform("mean")
        out[feature] = np.where(spread > 0, centred / spread, 0.0)
    # Annotated because pandas ships no type information: `to_numpy` is typed as
    # returning Any, and returning it bare would silently widen this signature.
    scaled: np.ndarray = out.to_numpy(dtype=float)
    return scaled


def fit(
    cells: pd.DataFrame,
    params: KMeansParams,
    seed: int,
    *,
    within_commodity: bool = False,
) -> ClusterModel:
    """Standardise, search k, fit the winner, and assign zones.

    Only cells that cleared the provenance gate are fitted. The gated ones are
    returned in `assignments` with a null zone and cluster, so the caller can
    persist them and coverage stays reportable.

    `within_commodity` selects the secondary variant described in
    `scale_within_commodity`. It is a reporting path: the primary, persisted
    model is the global one, because Tujuan 3 asks for commodities grouped by
    volatility.
    """
    gated = cells[cells["quality_reason"].notna()]
    fittable = cells[cells["quality_reason"].isna()]

    if len(fittable) < params.min_cells:
        raise ValueError(
            f"only {len(fittable)} cells cleared the provenance gate "
            f"({len(gated)} gated of {len(cells)}); below min_cells={params.min_cells}. "
            f"Clustering this few points would describe the sample, not the market."
        )

    matrix = fittable[FEATURES].to_numpy(dtype=float)
    scaler = StandardScaler()
    if within_commodity:
        # Still fitted, so `scaler_params` records a real transform; the matrix
        # it standardises has already had the commodity level removed.
        scaled = scaler.fit_transform(scale_within_commodity(fittable))
    else:
        scaled = scaler.fit_transform(matrix)

    entries, k = search_k(scaled, params, seed)
    model = KMeans(n_clusters=k, n_init=params.n_init, max_iter=params.max_iter, random_state=seed)
    labels = model.fit_predict(scaled)

    zone_mapping = assign_zones(model.cluster_centers_, params)
    sample_silhouette = silhouette_samples(scaled, labels)

    # Centroids are reported in original units, not standardised ones: a
    # centroid of "0.043 daily log-return sigma, +12% over the month" is
    # checkable by a human, whereas "1.7 standard deviations" is not.
    #
    # For the within-commodity variant this inverts only the outer scaler, so
    # the numbers are in units of "standard deviations of this commodity's own
    # history" and are NOT comparable with the global model's. `variant` on the
    # returned model says which, so a reader cannot mistake one for the other.
    original = scaler.inverse_transform(model.cluster_centers_)
    centroids = {
        int(cluster_id): {
            "volatility": float(original[cluster_id, 0]),
            "cum_change": float(original[cluster_id, 1]),
            "n_cells": int((labels == cluster_id).sum()),
        }
        for cluster_id in range(k)
    }

    # Gated rows stay in the frame and take nulls. Assigning by the fittable
    # index rather than by position is what keeps a gated cell from silently
    # inheriting its neighbour's cluster.
    assignments = cells.copy()
    assignments["cluster_id"] = pd.Series(labels, index=fittable.index, dtype="Int64")
    assignments["zone"] = pd.Series(
        [zone_mapping[int(label)] for label in labels], index=fittable.index, dtype="object"
    )
    assignments["silhouette_sample"] = pd.Series(sample_silhouette, index=fittable.index)

    return ClusterModel(
        k_selected=k,
        k_search=entries,
        silhouette_avg=float(silhouette_score(scaled, labels)),
        centroids=centroids,
        scaler_params={
            "mean": [float(v) for v in scaler.mean_],
            "scale": [float(v) for v in scaler.scale_],
            "features": FEATURES,
        },
        zone_mapping=zone_mapping,
        n_samples=len(fittable),
        n_gated=len(gated),
        variant="within_commodity" if within_commodity else "global",
        gate_reasons={
            str(reason): int(count)
            for reason, count in gated["quality_reason"].value_counts().items()
        },
        assignments=assignments,
    )


def latest_month(cells: pd.DataFrame) -> date | None:
    return None if cells.empty else max(cells["period_month"])
