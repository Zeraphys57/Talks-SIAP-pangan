"""STL decomposition: coverage guard, weekly resampling, periode rawan."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from siap.config import load_analysis
from siap.modules import stl


def _seasonal_daily(
    years: float = 3.0, peak_week: int = 10, level: float = 20_000.0
) -> pd.DataFrame:
    """A daily series with a clean annual bump centred on `peak_week`."""
    n = int(years * 365)
    start = date(2023, 1, 2)  # a Monday
    prices = []
    for i in range(n):
        day = start + timedelta(days=i)
        week = day.isocalendar().week
        # Gaussian bump around the peak week, wrapping the year.
        distance = min(abs(week - peak_week), 52 - abs(week - peak_week))
        bump = 0.35 * math.exp(-((distance / 3.0) ** 2))
        prices.append(level * (1 + bump))
    return pd.DataFrame(
        {"obs_date": [start + timedelta(days=i) for i in range(n)], "price": prices}
    )


def _params():
    return load_analysis().stl


# ---------------------------------------------------------------------------
# Coverage guard — the M1 dependency, enforced
# ---------------------------------------------------------------------------
def test_series_below_two_cycles_is_skipped_not_decomposed() -> None:
    """Below 104 weeks the components are an artefact, so nothing is produced."""
    short = _seasonal_daily(years=1.2)
    result = stl.decompose(short, _params(), "cabai", "jatim")
    assert not result.ok
    assert "104" in (result.skipped or "")
    assert result.components.empty


def test_skip_reason_states_the_actual_week_count() -> None:
    """'Why is there no seasonality here?' must be answerable from the record."""
    result = stl.decompose(_seasonal_daily(years=1.0), _params(), "beras", "diy")
    assert result.skipped is not None
    assert str(result.weeks) in result.skipped


def test_an_empty_series_is_skipped_cleanly() -> None:
    result = stl.decompose(pd.DataFrame(columns=["obs_date", "price"]), _params(), "x", "y")
    assert not result.ok
    assert result.weeks == 0


def test_three_years_clears_the_guard() -> None:
    result = stl.decompose(_seasonal_daily(years=3.0), _params(), "cabai", "jatim")
    assert result.ok, result.skipped
    assert result.weeks >= _params().min_weeks


# ---------------------------------------------------------------------------
# Weekly resampling
# ---------------------------------------------------------------------------
def test_weekly_resampling_uses_the_mean_not_the_last_value() -> None:
    """A weekly close would inherit whichever weekday the source published.

    PIHPS does not publish at weekends at all, so 'last value' would silently
    mean Friday for one source and Sunday for another.
    """
    start = date(2024, 1, 1)
    frame = pd.DataFrame(
        {
            "obs_date": [start + timedelta(days=i) for i in range(7)],
            "price": [100.0, 100, 100, 100, 100, 100, 800.0],
        }
    )
    weekly = stl.to_weekly(frame, _params())
    assert weekly.iloc[0] == pytest.approx(200.0)  # mean, not 800


# ---------------------------------------------------------------------------
# Periode rawan
# ---------------------------------------------------------------------------
def test_rawan_weeks_land_on_the_planted_peak() -> None:
    """The whole point: a known seasonal bump must be recovered."""
    peak = 10
    result = stl.decompose(_seasonal_daily(peak_week=peak), _params(), "cabai", "jatim")
    assert result.ok
    assert result.rawan_weeks, "no periode rawan derived"
    # The planted peak must be within the detected window.
    nearest = min(result.rawan_weeks, key=lambda w: min(abs(w - peak), 52 - abs(w - peak)))
    assert min(abs(nearest - peak), 52 - abs(nearest - peak)) <= 2


def test_rawan_is_the_top_decile_so_it_stays_a_short_list() -> None:
    """A 'risky period' covering half the year would be useless advice."""
    result = stl.decompose(_seasonal_daily(), _params(), "cabai", "jatim")
    assert result.ok
    assert 0 < len(result.rawan_weeks) <= 10, result.rawan_weeks


def test_seasonal_by_week_covers_the_calendar() -> None:
    result = stl.decompose(_seasonal_daily(), _params(), "cabai", "jatim")
    assert result.ok
    assert len(result.seasonal_by_week) >= 52
    assert all(1 <= w <= 53 for w in result.seasonal_by_week)


def test_components_reconstruct_the_observed_series() -> None:
    """trend + seasonal + resid == observed, or the decomposition is wrong."""
    result = stl.decompose(_seasonal_daily(), _params(), "cabai", "jatim")
    assert result.ok
    c = result.components
    reconstructed = c["trend"] + c["seasonal"] + c["resid"]
    pd.testing.assert_series_equal(reconstructed, c["observed"], check_names=False, rtol=1e-8)


def test_iso_week_dates_are_calendar_checkable() -> None:
    """The gate needs weeks as dates a human can compare against Ramadan."""
    monday, sunday = stl.iso_week_dates(12, 2026)
    assert monday.isocalendar().week == 12
    assert (sunday - monday).days == 6
    assert monday.weekday() == 0


def test_robust_fitting_is_configured() -> None:
    """A non-robust fit would absorb chilli spikes into the seasonal component."""
    assert _params().robust is True


def test_min_weeks_is_at_least_two_full_cycles() -> None:
    params = _params()
    assert params.min_weeks >= 2 * params.period
