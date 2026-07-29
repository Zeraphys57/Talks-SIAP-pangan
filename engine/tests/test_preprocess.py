"""Reconciliation and gap handling.

The interpolation rule is the part most likely to go quietly wrong: a fill that
runs one day too far, or that extrapolates past the end of a series, produces
numbers nobody observed and that nothing downstream can distinguish from data.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from siap.preprocess import (
    MAX_INTERPOLATION_GAP_DAYS,
    SeriesPoint,
    _interpolate,
    _reconcile_day,
)


def _series(values: list[float | None], start: date = date(2024, 1, 1)) -> dict[date, SeriesPoint]:
    return {
        start + timedelta(days=i): SeriesPoint(
            obs_date=start + timedelta(days=i),
            price_median=v,
            price_min=v,
            price_max=v,
            n_sources=1 if v is not None else 0,
            spread_pct=None,
            is_imputed=False,
            imputation_method=None,
        )
        for i, v in enumerate(values)
    }


def _run(values: list[float | None]) -> list[SeriesPoint]:
    start = date(2024, 1, 1)
    points = _series(values, start)
    _interpolate(points, start, start + timedelta(days=len(values) - 1))
    return [points[start + timedelta(days=i)] for i in range(len(values))]


# ---------------------------------------------------------------------------
# Reconciliation across sources
# ---------------------------------------------------------------------------
def test_median_not_mean_across_sources() -> None:
    """One outlying portal must not drag the series.

    M1 measured PIHPS running well above SP2KP for real methodological reasons.
    With three sources the median ignores the outlier; a mean would not.
    """
    median, low, high, n, spread = _reconcile_day([10_000, 10_100, 14_000])
    assert median == 10_100  # a mean would be 11,366
    assert (low, high, n) == (10_000, 14_000, 3)
    assert spread == pytest.approx((14_000 - 10_000) / 10_100 * 100)


def test_single_source_day_has_zero_spread() -> None:
    median, low, high, n, spread = _reconcile_day([12_345])
    assert median == low == high == 12_345
    assert n == 1
    assert spread == 0.0


def test_two_sources_median_is_the_midpoint() -> None:
    median, *_ = _reconcile_day([10_000, 12_000])
    assert median == 11_000


# ---------------------------------------------------------------------------
# Gap filling
# ---------------------------------------------------------------------------
def test_short_gap_is_filled_linearly_and_flagged() -> None:
    out = _run([100.0, None, None, 400.0])
    assert [p.price_median for p in out] == [100.0, 200.0, 300.0, 400.0]
    assert [p.is_imputed for p in out] == [False, True, True, False]
    assert out[1].imputation_method == "linear_2d"
    # The observed endpoints must not be relabelled as imputed.
    assert out[0].imputation_method is None
    assert out[3].imputation_method is None


def test_gap_of_exactly_the_limit_is_filled() -> None:
    out = _run([100.0, None, None, None, 500.0])
    assert all(p.price_median is not None for p in out)
    assert sum(p.is_imputed for p in out) == MAX_INTERPOLATION_GAP_DAYS


def test_gap_one_day_over_the_limit_stays_null() -> None:
    """The brief permits <=3 days. Four must remain NULL, not be filled."""
    out = _run([100.0, None, None, None, None, 600.0])
    assert [p.price_median for p in out] == [100.0, None, None, None, None, 600.0]
    assert not any(p.is_imputed for p in out)


def test_trailing_gap_is_never_extrapolated() -> None:
    """Filling past the last observation would invent a present, not a past."""
    out = _run([100.0, 200.0, None, None])
    assert [p.price_median for p in out] == [100.0, 200.0, None, None]
    assert not any(p.is_imputed for p in out)


def test_leading_gap_is_never_extrapolated() -> None:
    out = _run([None, None, 300.0, 400.0])
    assert [p.price_median for p in out] == [None, None, 300.0, 400.0]
    assert not any(p.is_imputed for p in out)


def test_weekend_shaped_gap_is_filled() -> None:
    """PIHPS publishes Mon-Fri, so its gaps are exactly two days.

    Those fall inside the rule and are filled — but must still be flagged, since
    M7 excludes imputed rows from ground-truth evaluation.
    """
    out = _run([15_000.0, None, None, 15_300.0])
    assert out[1].is_imputed and out[2].is_imputed
    assert out[1].imputation_method == "linear_2d"
    assert 15_000 < out[1].price_median < out[2].price_median < 15_300  # type: ignore[operator]


def test_multiple_gaps_are_handled_independently() -> None:
    out = _run([10.0, None, 30.0, None, None, None, None, 80.0, None, 100.0])
    assert out[1].price_median == 20.0 and out[1].is_imputed  # 1-day: filled
    assert [p.price_median for p in out[3:7]] == [None] * 4  # 4-day: NULL
    assert out[8].price_median == 90.0 and out[8].is_imputed  # 1-day: filled


def test_a_fully_observed_series_is_left_alone() -> None:
    out = _run([1.0, 2.0, 3.0, 4.0])
    assert not any(p.is_imputed for p in out)
    assert [p.price_median for p in out] == [1.0, 2.0, 3.0, 4.0]


def test_imputed_rows_carry_a_method_for_the_check_constraint() -> None:
    """price_daily_unified has CHECK (is_imputed = false or method is not null)."""
    out = _run([100.0, None, 300.0])
    for point in out:
        assert (point.imputation_method is not None) == point.is_imputed
