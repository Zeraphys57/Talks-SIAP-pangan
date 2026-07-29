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
on a weighted sum of their standardised coordinates. k is never forced to 3;
when the silhouette prefers k > 3 the middle clusters merge into `kuning`. This
is what resolves the proposal's contradiction between "find the optimal K" and
"three zones".
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

from ..config import KMeansParams

log = logging.getLogger(__name__)

FEATURES = ["volatility", "cum_change"]
ZONES = ("hijau", "kuning", "merah")


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
    n_samples: int
    assignments: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def k_search_json(self) -> list[dict[str, float | int]]:
        return [entry.as_dict() for entry in self.k_search]


def build_cells(frame: pd.DataFrame, params: KMeansParams) -> pd.DataFrame:
    """Aggregate a daily series into monthly regime features.

    `frame` needs `commodity`, `region`, `obs_date`, `price`. Months with fewer
    than `min_days_in_month` real observations are dropped: a standard deviation
    from a handful of days describes the sample, not the month.
    """
    if frame.empty:
        return pd.DataFrame(columns=["commodity", "region", "period_month", *FEATURES])

    work = frame.copy()
    work["obs_date"] = pd.to_datetime(work["obs_date"])
    work = work.sort_values(["commodity", "region", "obs_date"])
    work["period_month"] = work["obs_date"].dt.to_period("M").dt.to_timestamp()

    rows: list[dict[str, Any]] = []
    for (commodity, region, month), group in work.groupby(
        ["commodity", "region", "period_month"], sort=True
    ):
        prices = group["price"].astype(float).to_numpy()
        if len(prices) < params.min_days_in_month:
            continue
        # Log returns: a 10% move costs the same at any price level, so
        # volatility is comparable across commodities an order of magnitude
        # apart. Raw returns would make daging-sapi look calm by construction.
        log_returns = np.diff(np.log(prices))
        if log_returns.size < 2:
            continue
        rows.append(
            {
                "commodity": commodity,
                "region": region,
                "period_month": month.date(),
                "volatility": float(np.std(log_returns, ddof=1)),
                "cum_change": float((prices[-1] - prices[0]) / prices[0]),
                "n_days": len(prices),
            }
        )

    return pd.DataFrame(rows)


def search_k(scaled: np.ndarray, params: KMeansParams, seed: int) -> tuple[list[KSearchEntry], int]:
    """Fit every k in range, recording inertia and silhouette. Returns the best k.

    The whole curve is returned, not just the winner — it is a required paper
    figure, and keeping only the selected k would make it unreproducible without
    a re-run.
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

    Score = w_v * z(volatility) + w_c * z(cum_change), on the *standardised*
    centroid coordinates. Highest -> merah, lowest -> hijau, everything between
    -> kuning. With k > 3 the middle clusters merge, deliberately.

    Note the sign convention: `cum_change` is signed, so a month that fell
    sharply scores *low* and lands in hijau. That is the intended reading — the
    zones answer "should I buy now?", and a collapsing price is not a warning.
    """
    volatility = centroids[:, 0]
    cum_change = centroids[:, 1]

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


def fit(cells: pd.DataFrame, params: KMeansParams, seed: int) -> ClusterModel:
    """Standardise, search k, fit the winner, and assign zones."""
    if len(cells) < params.min_cells:
        raise ValueError(
            f"only {len(cells)} cells; below min_cells={params.min_cells}. "
            f"Clustering this few points would describe the sample, not the market."
        )

    matrix = cells[FEATURES].to_numpy(dtype=float)
    scaler = StandardScaler()
    scaled = scaler.fit_transform(matrix)

    entries, k = search_k(scaled, params, seed)
    model = KMeans(n_clusters=k, n_init=params.n_init, max_iter=params.max_iter, random_state=seed)
    labels = model.fit_predict(scaled)

    zone_mapping = assign_zones(model.cluster_centers_, params)
    sample_silhouette = silhouette_samples(scaled, labels)

    # Centroids are reported in original units, not standardised ones: a
    # centroid of "0.043 daily log-return sigma, +12% over the month" is
    # checkable by a human, whereas "1.7 standard deviations" is not.
    original = scaler.inverse_transform(model.cluster_centers_)
    centroids = {
        int(cluster_id): {
            "volatility": float(original[cluster_id, 0]),
            "cum_change": float(original[cluster_id, 1]),
            "n_cells": int((labels == cluster_id).sum()),
        }
        for cluster_id in range(k)
    }

    assignments = cells.copy()
    assignments["cluster_id"] = labels
    assignments["zone"] = [zone_mapping[int(label)] for label in labels]
    assignments["silhouette_sample"] = sample_silhouette

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
        n_samples=len(cells),
        assignments=assignments,
    )


def latest_month(cells: pd.DataFrame) -> date | None:
    return None if cells.empty else max(cells["period_month"])
