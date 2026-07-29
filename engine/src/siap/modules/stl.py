"""STL seasonal decomposition (§6.4).

**Hard dependency on the M1 backfill.** STL cannot separate a seasonal component
from a trend without at least two full cycles; at `period=52` that is 104 weeks.
Data scraped forward from today accrues one day per day, so without the archive
this module could not run for two years. Below the coverage floor a commodity is
**skipped and the reason recorded** — never decomposed anyway to produce a
plausible-looking curve.

Weekly resampling, not daily: daily food prices are too noisy for a stable
annual seasonal estimate, and "which weeks are risky?" is a weekly question.

`robust=True` uses median-based fitting so a single spike does not bend the
trend around it. Indonesian chilli routinely doubles; a non-robust fit would
absorb those spikes into the seasonal component and then fail to flag the next
one.

The derived output is **"periode rawan naik"** — the calendar weeks whose mean
seasonal component sits in the top decile of that commodity's own cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from ..config import STLParams

log = logging.getLogger(__name__)


@dataclass
class SeasonalResult:
    commodity: str
    region: str
    weeks: int
    components: pd.DataFrame = field(default_factory=pd.DataFrame)
    rawan_weeks: list[int] = field(default_factory=list)
    seasonal_by_week: dict[int, float] = field(default_factory=dict)
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped is None


def to_weekly(frame: pd.DataFrame, params: STLParams) -> pd.Series:
    """Resample a daily price series to weekly means.

    The mean rather than the last value: a weekly close would inherit whichever
    weekday the source happened to publish, and PIHPS does not publish at
    weekends at all.
    """
    if frame.empty:
        return pd.Series(dtype="float64")
    work = frame.sort_values("obs_date")
    series = pd.Series(
        work["price"].astype(float).to_numpy(),
        index=pd.DatetimeIndex(work["obs_date"]),
    )
    return series.resample(params.resample_freq).mean()


def decompose(
    frame: pd.DataFrame, params: STLParams, commodity: str, region: str
) -> SeasonalResult:
    """Decompose one commodity x region series, or explain why it was skipped."""
    weekly = to_weekly(frame, params)
    # Interior gaps would break STL's fixed-period assumption; a weekly mean is
    # missing only when no day in that week was reported at all.
    weekly = weekly.interpolate(limit_area="inside")
    usable = weekly.dropna()

    result = SeasonalResult(commodity=commodity, region=region, weeks=len(usable))

    if len(usable) < params.min_weeks:
        result.skipped = (
            f"{len(usable)} weeks < {params.min_weeks} required "
            f"(2 x period); seasonal and trend are not separable"
        )
        return result

    fitted = STL(
        usable,
        period=params.period,
        seasonal=params.seasonal,
        robust=params.robust,
    ).fit()

    components = pd.DataFrame(
        {
            "period_start": usable.index.date,
            "observed": usable.to_numpy(),
            "trend": fitted.trend.to_numpy(),
            "seasonal": fitted.seasonal.to_numpy(),
            "resid": fitted.resid.to_numpy(),
        }
    )
    result.components = components

    # Average the seasonal component by ISO week number, so the three years of
    # history collapse into one representative cycle.
    weeks = pd.DatetimeIndex(usable.index).isocalendar().week.to_numpy()
    by_week = pd.Series(fitted.seasonal.to_numpy()).groupby(weeks).mean()
    result.seasonal_by_week = {int(w): float(v) for w, v in by_week.items()}

    cutoff = float(np.quantile(by_week.to_numpy(), params.rawan_quantile))
    result.rawan_weeks = sorted(int(w) for w, v in by_week.items() if v >= cutoff)

    return result


def iso_week_dates(week: int, year: int) -> tuple[date, date]:
    """Calendar span of an ISO week, so a human can check it against a season."""
    monday = date.fromisocalendar(year, week, 1)
    sunday = date.fromisocalendar(year, week, 7)
    return monday, sunday
