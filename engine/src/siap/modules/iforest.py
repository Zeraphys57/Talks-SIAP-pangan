"""Isolation Forest anomaly detection — the multivariate arm (§6.2).

Fitted **per commodity x region**, never globally. Daging sapi trades around
130,000 and beras around 13,000; a single global model would spend its splits
separating commodities from one another rather than finding anomalies within
each. That is the most consequential design point in this module.

Features: `log_price`, `pct_change_1d`, `pct_change_7d`, `rolling_std_14d`,
`demand_z52`, `dow`. Price *level* alone says little — a high price is not an
anomaly — so the model is given momentum, local volatility and a demand proxy
alongside it.

`score_samples` returns lower values for more anomalous points, on a scale that
is not comparable between models. Since one model is fitted per series, raw
scores from different commodities cannot be compared at all. They are therefore
converted to a **percentile rank within that series' own history**, which is
what makes `norm_score` mean the same thing everywhere and lets fusion combine
it with the Z-Score arm.

`contamination` is read from configuration and swept in M7 on a held-out split.
Tuning it against the labels the paper reports would be leakage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ..config import IForestParams

METHOD = "iforest"


def build_features(
    frame: pd.DataFrame, params: IForestParams, demand: pd.Series | None = None
) -> pd.DataFrame:
    """Derive the feature matrix from a price series.

    `frame` needs `obs_date` and `price`. `demand` is an optional weekly
    `interest_z52` series indexed by date; it is forward-filled within the week,
    never interpolated into a daily curve the source cannot support.
    """
    work = frame.sort_values("obs_date").reset_index(drop=True)
    dates = pd.DatetimeIndex(work["obs_date"])
    price = work["price"].astype(float)

    features = pd.DataFrame(index=work.index)
    features["log_price"] = np.log(price)
    features["pct_change_1d"] = price.pct_change(1)
    features["pct_change_7d"] = price.pct_change(7)
    features["rolling_std_14d"] = (
        np.log(price).diff().rolling(params.rolling_std_window, min_periods=3).std()
    )

    if demand is not None and not demand.empty:
        aligned = demand.reindex(dates.normalize(), method="ffill")
        features["demand_z52"] = aligned.to_numpy()
    else:
        features["demand_z52"] = np.nan

    features["dow"] = dates.dayofweek.to_numpy()

    # Google Trends is throttled to zero at time of writing, so demand_z52 is
    # entirely absent. Filling with a configured constant rather than dropping
    # the column keeps the feature matrix identical between runs whether or not
    # Trends happened to work — a constant column yields no splits, so the model
    # behaves as if the feature were absent, but reproducibly so.
    features["demand_z52"] = features["demand_z52"].fillna(params.demand_missing_fill)

    ordered = [f for f in params.features if f in features.columns]
    return features[ordered]


def compute(
    frame: pd.DataFrame,
    params: IForestParams,
    seed: int,
    demand: pd.Series | None = None,
) -> pd.DataFrame:
    """Score one commodity x region series.

    Returns `obs_date`, `raw_score` (sklearn's `score_samples`, lower = more
    anomalous), `norm_score` (percentile rank within this series, higher = more
    anomalous), `is_flagged` and `threshold_used`.

    A series shorter than `min_observations` is returned unscored rather than
    fitted: an Isolation Forest on a few dozen points describes its own sample,
    not the commodity.
    """
    work = frame.sort_values("obs_date").reset_index(drop=True)
    if len(work) < params.min_observations:
        return _unscored(work)

    features = build_features(work, params, demand)

    # Early rows lack the history for pct_change_7d and the rolling std. They
    # are excluded from fitting rather than zero-filled, which would teach the
    # model that "no momentum" is normal and depress scores at every series
    # start.
    usable = features.notna().all(axis=1)
    if int(usable.sum()) < params.min_observations:
        return _unscored(work)

    model = IsolationForest(
        n_estimators=params.n_estimators,
        contamination=params.contamination,
        random_state=seed,
        n_jobs=1,  # determinism over speed
    )
    fitted_rows = features[usable]
    model.fit(fitted_rows)

    raw = pd.Series(np.nan, index=work.index, dtype="float64")
    flags = pd.Series(False, index=work.index, dtype="bool")
    raw.loc[usable] = model.score_samples(fitted_rows)
    flags.loc[usable] = model.predict(fitted_rows) == -1

    # Lower score_samples = more anomalous, so rank ascending and the most
    # anomalous point lands nearest 1.0.
    norm = (-raw).rank(pct=True, na_option="keep")

    return pd.DataFrame(
        {
            "obs_date": work["obs_date"].to_numpy(),
            "raw_score": raw.to_numpy(),
            "norm_score": norm.to_numpy(),
            "is_flagged": flags.to_numpy(),
            "threshold_used": params.contamination,
        }
    )


def _unscored(work: pd.DataFrame) -> pd.DataFrame:
    """Rows with no score — too little history to fit anything meaningful."""
    return pd.DataFrame(
        {
            "obs_date": work["obs_date"].to_numpy(),
            "raw_score": np.nan,
            "norm_score": np.nan,
            "is_flagged": False,
            "threshold_used": np.nan,
        }
    )
