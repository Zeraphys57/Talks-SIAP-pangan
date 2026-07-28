"""Google Trends demand signal.

The z-score here has the same leakage hazard as the price Z-Score module in
M3: if the week being scored is inside its own baseline, a spike partly
cancels itself and the signal is damped exactly when it matters.
"""

from __future__ import annotations

import pytest

from siap.scrapers.trends import MIN_WEEKS_FOR_Z52, TrendsCollector


def _flat_series(n: int, value: float = 50.0) -> dict[str, float]:
    """n consecutive weekly points, all identical."""
    from datetime import date, timedelta

    start = date(2024, 1, 7)
    return {(start + timedelta(weeks=i)).isoformat(): value for i in range(n)}


def test_z_scores_are_none_until_a_full_baseline_exists() -> None:
    """A partial window must yield NULL, not a number computed from too little."""
    series = _flat_series(MIN_WEEKS_FOR_Z52 + 5)
    zs = TrendsCollector.z_scores(series)
    weeks = sorted(series)
    for week in weeks[:MIN_WEEKS_FOR_Z52]:
        assert zs[week] is None, f"{week} scored with an incomplete baseline"


def test_flat_series_has_no_z_score_because_stdev_is_zero() -> None:
    """Dividing by a zero standard deviation must yield None, not inf or a crash."""
    series = _flat_series(MIN_WEEKS_FOR_Z52 + 10)
    zs = TrendsCollector.z_scores(series)
    weeks = sorted(series)
    assert all(zs[w] is None for w in weeks[MIN_WEEKS_FOR_Z52:])


def test_a_spike_scores_positive_against_its_trailing_baseline() -> None:
    from datetime import date, timedelta

    start = date(2024, 1, 7)
    series: dict[str, float] = {}
    for i in range(MIN_WEEKS_FOR_Z52):
        # Small alternation so the baseline has non-zero variance.
        series[(start + timedelta(weeks=i)).isoformat()] = 50.0 + (i % 2)
    spike_week = (start + timedelta(weeks=MIN_WEEKS_FOR_Z52)).isoformat()
    series[spike_week] = 100.0

    zs = TrendsCollector.z_scores(series)
    assert zs[spike_week] is not None
    assert zs[spike_week] > 5, "a doubling against a near-flat baseline should score high"


def test_the_scored_week_is_excluded_from_its_own_baseline() -> None:
    """The leakage guard, stated directly.

    Two series identical except for the value of the final week must produce
    the same baseline, so the larger value must score strictly higher. If the
    week leaked into its own window, the spike would partly cancel itself.
    """
    from datetime import date, timedelta

    start = date(2024, 1, 7)
    base = {
        (start + timedelta(weeks=i)).isoformat(): 50.0 + (i % 2) for i in range(MIN_WEEKS_FOR_Z52)
    }
    final_week = (start + timedelta(weeks=MIN_WEEKS_FOR_Z52)).isoformat()

    modest = TrendsCollector.z_scores({**base, final_week: 60.0})[final_week]
    extreme = TrendsCollector.z_scores({**base, final_week: 200.0})[final_week]

    assert modest is not None and extreme is not None
    assert extreme > modest * 5, "the baseline must not absorb the week being scored"


def test_geo_codes_cover_the_configured_scopes() -> None:
    """A scope in sources.yaml with no Google geo code would be silently skipped."""
    from siap.config import load_reference
    from siap.scrapers.trends import GEO_BY_SCOPE

    configured = set(load_reference().source("trends").regions)
    assert configured <= set(GEO_BY_SCOPE), (
        f"trends scopes without a geo code: {sorted(configured - set(GEO_BY_SCOPE))}"
    )


def test_trends_is_never_treated_as_a_price_source() -> None:
    from siap.config import load_reference

    assert load_reference().source("trends").is_price_source is False


@pytest.mark.parametrize("scope,geo", [("nasional", "ID"), ("di_yogyakarta", "ID-YO")])
def test_geo_codes_are_the_expected_google_regions(scope: str, geo: str) -> None:
    from siap.scrapers.trends import GEO_BY_SCOPE

    assert GEO_BY_SCOPE[scope] == geo
