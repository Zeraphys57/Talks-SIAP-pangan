"""Regime clustering: monthly feature construction, k-search, zone mapping."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from siap.config import load_analysis
from siap.modules import kmeans


def _daily(
    commodity: str, region: str, months: int = 6, level: float = 15_000.0, drift: float = 0.0
) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    start = date(2024, 1, 1)
    n = months * 30
    prices = [level * (1 + drift) ** i * (1 + rng.normal(0, 0.01)) for i in range(n)]
    return pd.DataFrame(
        {
            "commodity": commodity,
            "region": region,
            "obs_date": [start + timedelta(days=i) for i in range(n)],
            "price": prices,
        }
    )


def _params():
    return load_analysis().kmeans


# ---------------------------------------------------------------------------
# Monthly cells
# ---------------------------------------------------------------------------
def test_cells_are_commodity_region_month_not_commodity() -> None:
    """The core correction to the proposal: twelve commodities is twelve points."""
    frame = pd.concat([_daily("cabai", "jatim"), _daily("beras", "jatim")])
    cells = kmeans.build_cells(frame, _params())
    assert len(cells) > 2, "aggregation collapsed to one row per commodity"
    assert set(cells.columns) >= {"commodity", "region", "period_month", "volatility", "cum_change"}
    assert cells["period_month"].nunique() >= 5


def test_months_with_too_few_days_are_dropped() -> None:
    """A standard deviation from a handful of days describes the sample."""
    params = _params()
    frame = _daily("cabai", "jatim", months=2)
    # Keep only 5 days of the second month.
    keep = frame["obs_date"] < date(2024, 2, 6)
    cells = kmeans.build_cells(frame[keep], params)
    short = [c for c in cells.itertuples() if c.period_month == date(2024, 2, 1)]
    assert not short, "a month with 5 observations produced a volatility estimate"


def test_period_month_is_normalised_to_the_first(with_db: bool = False) -> None:
    """cluster_assignments has CHECK (extract(day from period_month) = 1)."""
    cells = kmeans.build_cells(_daily("cabai", "jatim"), _params())
    assert all(m.day == 1 for m in cells["period_month"])


def test_volatility_uses_log_returns_so_price_level_does_not_matter() -> None:
    """Raw returns would make daging-sapi look calm purely because it is dear."""
    params = _params()
    cheap = kmeans.build_cells(_daily("a", "r", level=13_000.0), params)
    dear = kmeans.build_cells(_daily("b", "r", level=130_000.0), params)
    assert cheap["volatility"].mean() == pytest.approx(dear["volatility"].mean(), rel=0.25)


# ---------------------------------------------------------------------------
# Zone mapping
# ---------------------------------------------------------------------------
def test_zones_rank_by_severity_not_by_cluster_id() -> None:
    """Cluster ids from KMeans are arbitrary; the mapping must be by centroid."""
    params = _params()
    # rows are [volatility, cum_change]; the calmest is deliberately id 1.
    centroids = np.array([[0.08, 0.60], [0.005, -0.01], [0.03, 0.10]])
    mapping = kmeans.assign_zones(centroids, params)
    assert mapping[0] == "merah"
    assert mapping[1] == "hijau"
    assert mapping[2] == "kuning"


def test_zone_mapping_covers_every_cluster() -> None:
    params = _params()
    rng = np.random.default_rng(3)
    for k in range(2, 9):
        centroids = rng.normal(size=(k, 2))
        mapping = kmeans.assign_zones(centroids, params)
        assert set(mapping) == set(range(k))
        assert set(mapping.values()) <= set(kmeans.ZONES)


def test_with_k_above_three_the_middle_merges_into_kuning() -> None:
    """Stated behaviour from the brief: k is not forced to 3."""
    params = _params()
    centroids = np.array([[0.10, 0.9], [0.001, -0.2], [0.03, 0.1], [0.05, 0.3], [0.02, 0.0]])
    mapping = kmeans.assign_zones(centroids, params)
    assert sum(1 for z in mapping.values() if z == "merah") == 1
    assert sum(1 for z in mapping.values() if z == "hijau") == 1
    assert sum(1 for z in mapping.values() if z == "kuning") == 3


def test_k_equals_two_produces_no_kuning_at_all() -> None:
    """Documented consequence, not an accident.

    The zone rule ranks clusters and takes the extremes, so with two clusters
    there is no middle rank and `kuning` is unreachable. On the real data the
    silhouette prefers k=2, which makes the three-zone scheme degenerate — see
    docs/changelog.md, M4.
    """
    params = _params()
    mapping = kmeans.assign_zones(np.array([[0.09, 0.7], [0.004, -0.02]]), params)
    assert set(mapping.values()) == {"merah", "hijau"}
    assert "kuning" not in mapping.values()


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------
def _mixed_cells(n: int = 120) -> pd.DataFrame:
    """Two well-separated regimes, so the structure is known in advance."""
    rng = np.random.default_rng(11)
    calm = pd.DataFrame(
        {
            "commodity": "beras",
            "region": "r",
            "period_month": [date(2024, 1 + i % 12, 1) for i in range(n)],
            "volatility": rng.normal(0.008, 0.001, n),
            "cum_change": rng.normal(0.00, 0.01, n),
        }
    )
    wild = pd.DataFrame(
        {
            "commodity": "cabai",
            "region": "r",
            "period_month": [date(2024, 1 + i % 12, 1) for i in range(n // 3)],
            "volatility": rng.normal(0.070, 0.008, n // 3),
            "cum_change": rng.normal(0.55, 0.08, n // 3),
        }
    )
    return pd.concat([calm, wild], ignore_index=True)


def test_fit_records_the_whole_k_search_not_just_the_winner() -> None:
    """The elbow curve is a required paper figure."""
    cfg = load_analysis()
    model = kmeans.fit(_mixed_cells(), cfg.kmeans, cfg.seed)
    ks = [e.k for e in model.k_search]
    assert ks == list(range(cfg.kmeans.k_min, cfg.kmeans.k_max + 1))
    assert all(e.inertia > 0 for e in model.k_search)


def test_fit_selects_the_k_with_the_highest_silhouette() -> None:
    cfg = load_analysis()
    model = kmeans.fit(_mixed_cells(), cfg.kmeans, cfg.seed)
    best = max(model.k_search, key=lambda e: e.silhouette)
    assert model.k_selected == best.k


def test_fit_separates_the_two_planted_regimes() -> None:
    cfg = load_analysis()
    model = kmeans.fit(_mixed_cells(), cfg.kmeans, cfg.seed)
    wild = model.assignments[model.assignments["commodity"] == "cabai"]
    calm = model.assignments[model.assignments["commodity"] == "beras"]
    # The volatile, sharply-rising regime must not be called safe.
    assert (wild["zone"] != "hijau").mean() > 0.9
    assert (calm["zone"] == "hijau").mean() > 0.9


def test_fit_refuses_too_few_cells() -> None:
    cfg = load_analysis()
    with pytest.raises(ValueError, match="min_cells"):
        kmeans.fit(_mixed_cells(n=5), cfg.kmeans, cfg.seed)


def test_fit_is_deterministic_for_a_fixed_seed() -> None:
    cfg = load_analysis()
    cells = _mixed_cells()
    first = kmeans.fit(cells, cfg.kmeans, cfg.seed)
    second = kmeans.fit(cells, cfg.kmeans, cfg.seed)
    assert first.k_selected == second.k_selected
    assert first.silhouette_avg == pytest.approx(second.silhouette_avg)
    assert list(first.assignments["zone"]) == list(second.assignments["zone"])


def test_scaler_params_are_persisted_for_reuse() -> None:
    """Stored so the transform can be reapplied without refitting."""
    cfg = load_analysis()
    model = kmeans.fit(_mixed_cells(), cfg.kmeans, cfg.seed)
    assert model.scaler_params["features"] == kmeans.FEATURES
    assert len(model.scaler_params["mean"]) == len(kmeans.FEATURES)
    assert len(model.scaler_params["scale"]) == len(kmeans.FEATURES)


def test_centroids_are_reported_in_original_units() -> None:
    """A human checks "0.07 sigma, +63%"; nobody can check "1.7 z-units"."""
    cfg = load_analysis()
    model = kmeans.fit(_mixed_cells(), cfg.kmeans, cfg.seed)
    vols = [c["volatility"] for c in model.centroids.values()]
    assert all(0 < v < 0.5 for v in vols), f"centroids look standardised: {vols}"
