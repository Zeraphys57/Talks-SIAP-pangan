"""Anomaly detectors, against synthetic series with spikes at known indices.

The brief requires both detectors to recover injected spikes. These tests also
pin the properties that would silently degrade detection if they regressed:
the trailing-only window, the minimum-observation floor, and the refusal to fit
a forest on too little history.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from siap.config import IForestParams, ZScoreParams, load_analysis
from siap.modules import iforest, zscore

SPIKE_INDEX = 200


def _flat_series(n: int = 400, level: float = 15_000.0, noise: float = 0.004) -> pd.DataFrame:
    """A calm daily series with mild multiplicative noise, deterministic."""
    rng = np.random.default_rng(20260729)
    start = date(2024, 1, 1)
    prices = level * (1 + rng.normal(0, noise, n))
    return pd.DataFrame(
        {"obs_date": [start + timedelta(days=i) for i in range(n)], "price": prices}
    )


def _with_spike(frame: pd.DataFrame, index: int = SPIKE_INDEX, factor: float = 1.6) -> pd.DataFrame:
    out = frame.copy()
    out.loc[index, "price"] = float(out.loc[index, "price"]) * factor
    return out


def _params() -> ZScoreParams:
    return load_analysis().zscore


# ---------------------------------------------------------------------------
# Z-Score
# ---------------------------------------------------------------------------
def test_zscore_recovers_an_injected_spike() -> None:
    scored = zscore.compute(_with_spike(_flat_series()), _params())
    flagged = set(np.flatnonzero(scored["is_flagged"].to_numpy()))
    assert SPIKE_INDEX in flagged, "the injected spike was not detected"


def test_zscore_false_positive_rate_on_noise_matches_theory() -> None:
    """The baseline's intrinsic false-positive rate, measured rather than assumed.

    On pure Gaussian noise a |z| >= 2.5 rule fires about 1.2% of the time if the
    baseline mean and standard deviation were known exactly. They are not — they
    are estimated from ~30 samples — so the sampling distribution has heavier
    tails than normal and the observed rate is roughly 2-3%.

    This is correct behaviour, not a defect, but it bounds what the
    `zscore_only` arm can achieve in M7: on a three-year daily series it will
    produce tens of flags per commodity from noise alone. Precision for that arm
    should be read with this floor in mind, and it is exactly why the fusion arm
    has to earn its complexity against it.
    """
    scored = zscore.compute(_flat_series(), _params())
    scored_rows = int(scored["raw_score"].notna().sum())
    flagged = int(scored["is_flagged"].sum())
    rate = flagged / scored_rows
    assert scored_rows > 300
    # Generous upper bound: the point is that it is a few percent, not tens.
    assert rate < 0.05, f"{flagged}/{scored_rows} = {rate:.1%} is far above the ~2-3% expected"


def test_zscore_leaves_early_rows_null_rather_than_guessing() -> None:
    """Before the window holds min_observations, the score must be NULL."""
    params = _params()
    scored = zscore.compute(_flat_series(n=60), params)
    early = scored.head(params.min_observations)
    assert early["raw_score"].isna().all()
    assert not early["is_flagged"].any()


def test_zscore_window_excludes_the_day_being_scored() -> None:
    """The leakage guard, checked arithmetically rather than by inspection.

    A constant history followed by one different value: the baseline standard
    deviation must be zero (so z is undefined), NOT small-but-positive, which is
    what including the scored day would produce.
    """
    n = 60
    start = date(2024, 1, 1)
    prices = [10_000.0] * n
    prices[-1] = 20_000.0
    frame = pd.DataFrame(
        {"obs_date": [start + timedelta(days=i) for i in range(n)], "price": prices}
    )
    scored = zscore.compute(frame, _params())
    # The baseline for the last row is entirely constant -> std 0 -> NaN, not inf.
    last = scored.iloc[-1]
    assert pd.isna(last["raw_score"])
    assert not bool(last["is_flagged"])


def test_zscore_is_computed_on_log_price() -> None:
    """A proportional move must score the same at any price level.

    This is the documented mitigation for the normality assumption: on raw
    prices a +60% move on an expensive commodity would dominate the same
    proportional move on a cheap one.
    """
    cheap = zscore.compute(_with_spike(_flat_series(level=13_000.0)), _params())
    dear = zscore.compute(_with_spike(_flat_series(level=130_000.0)), _params())
    assert cheap.loc[SPIKE_INDEX, "raw_score"] == pytest.approx(
        dear.loc[SPIKE_INDEX, "raw_score"], rel=0.02
    )


def test_zscore_norm_score_is_bounded_and_saturates() -> None:
    scored = zscore.compute(_with_spike(_flat_series(), factor=5.0), _params())
    norm = scored["norm_score"].dropna()
    assert ((norm >= 0) & (norm <= 1)).all()
    assert scored.loc[SPIKE_INDEX, "norm_score"] == 1.0  # |z| >= 4 saturates


def test_zscore_flags_a_crash_as_well_as_a_spike() -> None:
    """|z| is two-sided: a collapse is an anomaly a warung owner cares about."""
    scored = zscore.compute(_with_spike(_flat_series(), factor=0.55), _params())
    assert bool(scored.loc[SPIKE_INDEX, "is_flagged"])
    assert float(scored.loc[SPIKE_INDEX, "raw_score"]) < 0


def test_zscore_refuses_a_baseline_that_barely_moved() -> None:
    """Regression guard for the stale-source bug found on real data.

    PIHPS carries values forward between surveys, and in 2023 it was the only
    source for two regions. A 30-day window over a stale feed has a standard
    deviation near floating-point zero, so the first real movement divides by
    almost nothing. The first production run scored z = -20,824,185 on exactly
    this shape. The window must be declared unusable, not scored.
    """
    n = 80
    start = date(2024, 1, 1)
    # A month of a source repeating itself to the rupiah, then a real move.
    prices = [120_000.0] * (n - 1) + [125_000.0]
    frame = pd.DataFrame(
        {"obs_date": [start + timedelta(days=i) for i in range(n)], "price": prices}
    )
    scored = zscore.compute(frame, _params())
    assert scored["raw_score"].isna().all(), "a stale baseline produced a score"
    assert not scored["is_flagged"].any()


def test_zscore_scores_stay_within_arithmetic_reason() -> None:
    """Guards the degenerate-baseline bug, not large-but-honest scores.

    A big move against a quiet baseline legitimately scores in the hundreds:
    doubling a price is log(2) = 0.69 against a 0.004 daily sigma, i.e. ~170.
    The bug this guards produced 2e7, four orders of magnitude beyond that, by
    dividing by a standard deviation of ~1e-16.
    """
    scored = zscore.compute(_with_spike(_flat_series(), factor=2.0), _params())
    finite = scored["raw_score"].dropna().abs()
    assert finite.max() < 1_000, f"implausible z of {finite.max():,.0f} — check the std floor"


def test_zscore_still_detects_after_a_quiet_but_not_frozen_period() -> None:
    """The floor must not suppress genuine detection on merely calm series.

    0.05% daily variation is the cutoff; 0.4% is calm but real, and a spike
    against it must still flag.
    """
    scored = zscore.compute(_with_spike(_flat_series(noise=0.004)), _params())
    assert bool(scored.loc[SPIKE_INDEX, "is_flagged"])


def test_zscore_handles_an_empty_series() -> None:
    out = zscore.compute(pd.DataFrame(columns=["obs_date", "price"]), _params())
    assert out.empty


# ---------------------------------------------------------------------------
# Isolation Forest
# ---------------------------------------------------------------------------
def _iforest_params() -> IForestParams:
    return load_analysis().iforest


def test_iforest_recovers_an_injected_spike() -> None:
    seed = load_analysis().seed
    scored = iforest.compute(_with_spike(_flat_series()), _iforest_params(), seed)
    assert bool(scored.loc[SPIKE_INDEX, "is_flagged"]), "the injected spike was not detected"


def test_iforest_ranks_the_spike_among_the_most_anomalous() -> None:
    seed = load_analysis().seed
    scored = iforest.compute(_with_spike(_flat_series()), _iforest_params(), seed)
    assert float(scored.loc[SPIKE_INDEX, "norm_score"]) > 0.98


def test_iforest_is_deterministic_for_a_fixed_seed() -> None:
    """Determinism is a stated contract: the same seed must give the same scores."""
    frame = _with_spike(_flat_series())
    params, seed = _iforest_params(), load_analysis().seed
    first = iforest.compute(frame, params, seed)
    second = iforest.compute(frame, params, seed)
    pd.testing.assert_frame_equal(first, second)


def test_iforest_refuses_to_fit_on_too_little_history() -> None:
    """A forest on a few dozen points describes its sample, not the commodity."""
    params = _iforest_params()
    scored = iforest.compute(_flat_series(n=params.min_observations - 1), params, 1)
    assert scored["raw_score"].isna().all()
    assert not scored["is_flagged"].any()


def test_iforest_norm_score_is_bounded() -> None:
    scored = iforest.compute(_with_spike(_flat_series()), _iforest_params(), 1)
    norm = scored["norm_score"].dropna()
    assert ((norm >= 0) & (norm <= 1)).all()


def test_iforest_features_are_built_in_configured_order() -> None:
    params = _iforest_params()
    features = iforest.build_features(_flat_series(), params)
    assert list(features.columns) == params.features


def test_iforest_fills_absent_demand_rather_than_dropping_the_column() -> None:
    """Trends is throttled; the feature matrix must not change shape as a result.

    A model whose feature set depends on whether an unreliable upstream happened
    to respond is not reproducible.
    """
    params = _iforest_params()
    features = iforest.build_features(_flat_series(), params, demand=None)
    assert "demand_z52" in features.columns
    assert (features["demand_z52"] == params.demand_missing_fill).all()
    assert features["demand_z52"].notna().all()


# ---------------------------------------------------------------------------
# Both arms together — the basis of M7's union and fusion comparisons
# ---------------------------------------------------------------------------
def test_both_detectors_recover_the_same_injected_spike() -> None:
    frame = _with_spike(_flat_series())
    cfg = load_analysis()
    zs = zscore.compute(frame, cfg.zscore)
    forest = iforest.compute(frame, cfg.iforest, cfg.seed)
    assert bool(zs.loc[SPIKE_INDEX, "is_flagged"])
    assert bool(forest.loc[SPIKE_INDEX, "is_flagged"])


def test_detectors_return_one_row_per_input_row() -> None:
    """Both arms must align row-for-row, or M7's union is comparing offsets."""
    frame = _with_spike(_flat_series())
    cfg = load_analysis()
    zs = zscore.compute(frame, cfg.zscore)
    forest = iforest.compute(frame, cfg.iforest, cfg.seed)
    assert len(zs) == len(forest) == len(frame)
    assert list(zs["obs_date"]) == list(frame["obs_date"])
    assert list(forest["obs_date"]) == list(frame["obs_date"])


def test_multiple_spikes_are_all_recovered_by_zscore() -> None:
    frame = _flat_series()
    for index in (120, 220, 320):
        frame = _with_spike(frame, index=index, factor=1.7)
    scored = zscore.compute(frame, _params())
    flagged = set(np.flatnonzero(scored["is_flagged"].to_numpy()))
    assert {120, 220, 320} <= flagged


def test_a_gradual_trend_is_not_flagged_as_an_anomaly() -> None:
    """A slow drift is not an anomaly; flagging it would drown the real events."""
    n = 400
    start = date(2024, 1, 1)
    prices = [15_000.0 * math.exp(0.0008 * i) for i in range(n)]  # ~+38% over the year
    frame = pd.DataFrame(
        {"obs_date": [start + timedelta(days=i) for i in range(n)], "price": prices}
    )
    scored = zscore.compute(frame, _params())
    scored_rows = int(scored["raw_score"].notna().sum())
    flagged = int(scored["is_flagged"].sum())
    assert flagged / scored_rows < 0.05, f"a smooth trend produced {flagged} flags"
