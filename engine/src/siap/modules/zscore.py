"""Z-Score anomaly detection — the statistical baseline (§6.1).

    z_t = (log p_t - mean(log p_{t-30..t-1})) / std(log p_{t-30..t-1})

Three properties matter, and each is a deliberate answer to a way this can go
wrong:

**The window is trailing only.** Day *t* is excluded from its own baseline. If
it were included, a spike would raise the mean and inflate the standard
deviation it is being measured against, partially cancelling itself — the leak
that makes a naive rolling z-score systematically under-detect exactly the
events it exists to find.

**The window is measured in calendar days, not rows.** Imputed rows are dropped
before scoring, so consecutive rows are not consecutive days. A row-count window
of 30 would silently span six weeks in a sparse region. A `30D` time window with
a minimum-observation floor keeps the baseline anchored to real time.

**It runs on log price.** The proposal itself names the normality assumption as
Z-Score's weakness. Prices are right-skewed and move multiplicatively — a 10%
rise costs the same in log space whether the commodity trades at 13,000 or
130,000 — so taking logs is the mitigation, and it belongs in the paper.

Where the window holds fewer than `min_observations` real prices, the score is
NULL. A number computed from too little history is worse than no number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import ZScoreParams

METHOD = "zscore"


def compute(frame: pd.DataFrame, params: ZScoreParams) -> pd.DataFrame:
    """Score one commodity x region series.

    `frame` needs `obs_date` (date) and `price` (float), already filtered to
    real observations. Returns one row per input row with `raw_score` (the
    signed z), `norm_score`, `is_flagged` and `threshold_used`. Rows whose
    window is too thin carry NULL scores and `is_flagged = False`.
    """
    if frame.empty:
        return _empty()

    work = frame.sort_values("obs_date").reset_index(drop=True)
    values = work["price"].astype(float)
    if params.use_log_price:
        values = np.log(values)

    indexed = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(work["obs_date"]))

    # closed="left" excludes the right endpoint — the day being scored — so the
    # baseline is strictly the days before it.
    window = indexed.rolling(
        f"{params.window_days}D", closed="left", min_periods=params.min_observations
    )
    mean = window.mean()
    std = window.std()  # ddof=1: the baseline is a sample, not a population

    # A baseline that barely moved cannot support a z-score. Some portals carry
    # a value forward between surveys rather than resurveying, which gives a
    # window a standard deviation near floating-point zero; the first real
    # movement then divides by almost nothing and scores in the millions. Those
    # are artefacts of the source's publication cadence, not anomalies, so the
    # window is declared unusable instead.
    degenerate = std < params.min_baseline_std
    std = std.where(~degenerate)

    with np.errstate(invalid="ignore", divide="ignore"):
        z = (indexed - mean) / std
    # Belt and braces: an exact zero would still produce an infinity.
    z = z.replace([np.inf, -np.inf], np.nan)

    norm = (z.abs() / params.norm_divisor).clip(upper=1.0)
    flagged = z.abs() >= params.threshold

    return pd.DataFrame(
        {
            "obs_date": work["obs_date"].to_numpy(),
            "raw_score": z.to_numpy(),
            "norm_score": norm.to_numpy(),
            # NaN comparisons are False, so a thin window is never flagged.
            "is_flagged": flagged.fillna(False).to_numpy(),
            "threshold_used": params.threshold,
        }
    )


def _empty() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "obs_date": pd.Series(dtype="object"),
            "raw_score": pd.Series(dtype="float64"),
            "norm_score": pd.Series(dtype="float64"),
            "is_flagged": pd.Series(dtype="bool"),
            "threshold_used": pd.Series(dtype="float64"),
        }
    )
