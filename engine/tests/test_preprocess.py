"""Reconciliation and gap handling.

The interpolation rule is the part most likely to go quietly wrong: a fill that
runs one day too far, or that extrapolates past the end of a series, produces
numbers nobody observed and that nothing downstream can distinguish from data.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

import pytest

from siap.preprocess import (
    MAX_INTERPOLATION_GAP_DAYS,
    MIN_LINK_OVERLAP_DAYS,
    SeriesPoint,
    _interpolate,
    _reconcile_day,
    build_series,
    compute_offsets,
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


# ---------------------------------------------------------------------------
# Source linking (0009)
#
# The defect these guard: price_median used to be a median across sources with
# systematically different levels, so it stepped whenever a source dropped out.
# 673 of 2,979 Z-Score flags sat on such a step.
# ---------------------------------------------------------------------------
def _two_source_days(n: int, base: float, ratio: float, extra_reference_days: int = 5):
    """`n` overlapping days where 'aaa_rich' reports `base` and 'zzz_cheap' base/ratio.

    The reference gets extra solo days so it wins on coverage rather than on the
    alphabetical tie-break, which keeps these tests about the linking arithmetic
    instead of about the tie rule.
    """
    days = {
        date(2024, 1, 1) + timedelta(days=i): [("aaa_rich", base), ("zzz_cheap", base / ratio)]
        for i in range(n)
    }
    for i in range(n, n + extra_reference_days):
        days[date(2024, 1, 1) + timedelta(days=i)] = [("aaa_rich", base)]
    return days


def test_the_best_covered_source_becomes_the_reference() -> None:
    by_day = {
        date(2024, 1, 1): [("zzz_rich", 100.0), ("aaa_cheap", 80.0)],
        date(2024, 1, 2): [("zzz_rich", 100.0)],
        date(2024, 1, 3): [("zzz_rich", 100.0)],
    }
    offsets = compute_offsets(by_day)
    assert offsets["zzz_rich"].reference == "zzz_rich", "coverage must beat alphabetical order"
    assert offsets["zzz_rich"].factor == 1.0


def test_the_reference_is_stable_under_a_tie() -> None:
    """A re-run must not silently pick a different basis and shift every price."""
    by_day = {date(2024, 1, 1): [("bbb", 100.0), ("aaa", 80.0)]}
    assert compute_offsets(by_day)["aaa"].reference == "aaa"
    assert compute_offsets(dict(reversed(list(by_day.items()))))["aaa"].reference == "aaa"


def test_a_cheaper_source_is_scaled_up_to_the_reference() -> None:
    offsets = compute_offsets(_two_source_days(60, 100.0, 1.25))
    assert offsets["zzz_cheap"].factor == pytest.approx(1.25)
    assert offsets["zzz_cheap"].reference == "aaa_rich"


def test_the_factor_resists_a_single_mistyped_price() -> None:
    """Median, not mean: one bad ratio would shift every rebased price."""
    by_day = _two_source_days(60, 100.0, 1.25)
    by_day[date(2024, 1, 10)] = [("aaa_rich", 100.0), ("zzz_cheap", 0.8)]  # dropped a decimal
    assert compute_offsets(by_day)["zzz_cheap"].factor == pytest.approx(1.25)


def test_a_source_with_too_little_overlap_is_excluded_not_guessed() -> None:
    """A wrong factor is worse than a missing source: it is undetectable downstream."""
    by_day = {
        date(2024, 1, 1) + timedelta(days=i): [("aaa_rich", 100.0)]
        for i in range(MIN_LINK_OVERLAP_DAYS + 10)
    }
    for i in range(MIN_LINK_OVERLAP_DAYS - 1):
        by_day[date(2024, 1, 1) + timedelta(days=i)].append(("rare", 80.0))

    offset = compute_offsets(by_day)["rare"]
    assert not offset.usable
    assert "below the" in (offset.excluded_reason or "")


def test_the_residual_and_drift_of_the_link_are_recorded() -> None:
    """The constant-factor assumption has to be auditable, not assumed."""
    offsets = compute_offsets(_two_source_days(60, 100.0, 1.25))
    offset = offsets["zzz_cheap"]
    assert offset.ratio_cv_pct == pytest.approx(0.0, abs=1e-9)
    assert offset.ratio_drift_pct == pytest.approx(0.0, abs=1e-9)


def test_drift_is_measured_along_the_date_order() -> None:
    by_day = {}
    for i in range(60):
        ratio = 1.0 if i < 30 else 1.2
        by_day[date(2024, 1, 1) + timedelta(days=i)] = [
            ("aaa_rich", 120.0),
            ("zzz_cheap", 120.0 / ratio),
        ]
    for i in range(60, 65):
        by_day[date(2024, 1, 1) + timedelta(days=i)] = [("aaa_rich", 120.0)]
    assert compute_offsets(by_day)["zzz_cheap"].ratio_drift_pct == pytest.approx(20.0, rel=1e-6)


def test_a_source_dropping_out_no_longer_moves_the_level(monkeypatch) -> None:
    """The regression this whole migration exists for.

    Two sources 25% apart. On day 40 the cheaper one is silent. Before linking,
    the median jumped to the expensive source's level; after, it does not move.
    """
    by_day = _two_source_days(80, 100.0, 1.25)
    gap_day = date(2024, 1, 1) + timedelta(days=40)
    by_day[gap_day] = [("aaa_rich", 100.0)]

    offsets = compute_offsets(by_day)
    rebased = {
        day: statistics.median([price * offsets[s].factor for s, price in observed])
        for day, observed in by_day.items()
    }
    assert rebased[gap_day] == pytest.approx(100.0)
    assert rebased[gap_day - timedelta(days=1)] == pytest.approx(100.0)

    raw = {day: statistics.median([p for _, p in obs]) for day, obs in by_day.items()}
    assert raw[gap_day] == pytest.approx(100.0)
    assert raw[gap_day - timedelta(days=1)] == pytest.approx(90.0)
    assert abs(raw[gap_day] / raw[gap_day - timedelta(days=1)] - 1) > 0.10, (
        "the un-rebased series must show the >10% step this fix removes, "
        "or this test is not exercising the defect"
    )


def test_build_series_returns_the_offsets_it_used(monkeypatch) -> None:
    """A rebased price whose factor is not recorded is a number nobody can check."""
    rows = [
        {"obs_date": date(2024, 1, 1) + timedelta(days=i), "price_idr": p, "source": s}
        for i in range(40)
        for s, p in (("aaa_rich", 100.0), ("zzz_cheap", 80.0))
    ] + [
        {"obs_date": date(2024, 1, 1) + timedelta(days=i), "price_idr": 100.0, "source": "aaa_rich"}
        for i in range(40, 45)
    ]
    monkeypatch.setattr("siap.preprocess.fetch_all", lambda *a, **k: rows)

    series, _suspicious, offsets = build_series(object(), 1, 1)
    assert set(offsets) == {"aaa_rich", "zzz_cheap"}
    assert offsets["zzz_cheap"].factor == pytest.approx(1.25)
    assert all(p.price_median == pytest.approx(100.0) for p in series if p.price_median)


def test_spread_is_measured_after_rebasing(monkeypatch) -> None:
    """Otherwise the 'disagreement' report just re-reports the constant offset."""
    rows = [
        {"obs_date": date(2024, 1, 1) + timedelta(days=i), "price_idr": p, "source": s}
        for i in range(40)
        for s, p in (("aaa_rich", 100.0), ("zzz_cheap", 80.0))
    ] + [
        {"obs_date": date(2024, 1, 1) + timedelta(days=i), "price_idr": 100.0, "source": "aaa_rich"}
        for i in range(40, 45)
    ]
    monkeypatch.setattr("siap.preprocess.fetch_all", lambda *a, **k: rows)

    series, _suspicious, _offsets = build_series(object(), 1, 1)
    assert all(p.spread_pct == pytest.approx(0.0) for p in series if p.spread_pct is not None)
