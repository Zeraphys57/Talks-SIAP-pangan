"""Fusion engine: component arithmetic and the corroboration rules.

The brief names fusion as the core contribution and never defines it, so these
tests are the executable specification. The arithmetic case is deliberately
hand-checkable — an alert nobody can decompose is an alert nobody can defend.
"""

from __future__ import annotations

import pytest

from siap.config import load_fusion
from siap.modules.fusion import (
    FusionInput,
    anomaly_term,
    assign_level,
    corroboration_term,
    demand_term,
    fuse,
    momentum_term,
)


def _cfg():
    return load_fusion()


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
def test_weights_sum_to_one() -> None:
    """Otherwise the siaga threshold is unreachable and M7's sweep is unreadable."""
    w = _cfg().weights
    assert w.anomaly + w.momentum + w.demand + w.corroboration == pytest.approx(1.0)


def test_weights_match_the_brief() -> None:
    w = _cfg().weights
    assert (w.anomaly, w.momentum, w.demand, w.corroboration) == (0.45, 0.25, 0.20, 0.10)


# ---------------------------------------------------------------------------
# A — anomaly
# ---------------------------------------------------------------------------
def test_anomaly_takes_the_stronger_detector() -> None:
    cfg = _cfg()
    a, both = anomaly_term(FusionInput(norm_zscore=0.3, norm_iforest=0.8), cfg)
    assert a == pytest.approx(0.8)
    assert both is False


def test_both_flagged_earns_the_bonus_but_stays_capped() -> None:
    cfg = _cfg()
    a, both = anomaly_term(
        FusionInput(norm_zscore=0.5, norm_iforest=0.6, zscore_flagged=True, iforest_flagged=True),
        cfg,
    )
    assert both is True
    assert a == pytest.approx(0.6 * 1.15)

    saturated, _ = anomaly_term(
        FusionInput(norm_zscore=1.0, norm_iforest=1.0, zscore_flagged=True, iforest_flagged=True),
        cfg,
    )
    assert saturated == 1.0, "the bonus must not push A above 1"


def test_anomaly_is_undefined_when_neither_detector_scored() -> None:
    """None, not 0.0 — the distinction the fourth level is built on.

    A = 0 says both detectors looked and found nothing unusual. A = None says
    neither could look: too little history in the window, or a baseline too
    stale to divide by. Returning 0.0 for the second made absence of evidence
    render as evidence of safety.
    """
    a, both = anomaly_term(FusionInput(), _cfg())
    assert a is None and both is False


# ---------------------------------------------------------------------------
# M — momentum
# ---------------------------------------------------------------------------
def test_momentum_saturates_at_the_configured_scale() -> None:
    cfg = _cfg()
    assert momentum_term(FusionInput(pct_change_7d=0.15), cfg) == pytest.approx(1.0)
    assert momentum_term(FusionInput(pct_change_7d=0.30), cfg) == 1.0
    assert momentum_term(FusionInput(pct_change_7d=0.075), cfg) == pytest.approx(0.5)


def test_momentum_is_two_sided() -> None:
    """A collapse is as much an event as a spike."""
    cfg = _cfg()
    assert momentum_term(FusionInput(pct_change_7d=-0.20), cfg) == 1.0


def test_momentum_is_zero_without_a_comparison_price() -> None:
    assert momentum_term(FusionInput(pct_change_7d=None), _cfg()) == 0.0


# ---------------------------------------------------------------------------
# D — demand
# ---------------------------------------------------------------------------
def test_demand_is_one_sided() -> None:
    """Falling search interest is not a reason to warn, so it contributes 0."""
    cfg = _cfg()
    assert demand_term(FusionInput(demand_z52=-2.0), cfg) == 0.0
    assert demand_term(FusionInput(demand_z52=1.5), cfg) == pytest.approx(0.5)
    assert demand_term(FusionInput(demand_z52=9.0), cfg) == 1.0


def test_absent_demand_contributes_zero_not_an_error() -> None:
    """Trends is throttled; fusion must still produce a score."""
    assert demand_term(FusionInput(demand_z52=None), _cfg()) == 0.0


# ---------------------------------------------------------------------------
# C — corroboration
# ---------------------------------------------------------------------------
def test_corroboration_is_the_flagging_fraction() -> None:
    assert corroboration_term(FusionInput(n_sources_reporting=3, n_sources_flagging=2)) == (
        pytest.approx(2 / 3)
    )


def test_corroboration_is_none_when_nothing_reported() -> None:
    assert corroboration_term(FusionInput(n_sources_reporting=0)) is None


# ---------------------------------------------------------------------------
# Level assignment — the rules that stop a lone portal raising an alarm
# ---------------------------------------------------------------------------
def test_high_score_with_real_corroboration_is_siaga() -> None:
    cfg = _cfg()
    inp = FusionInput(n_sources_reporting=3, n_sources_flagging=2)
    level, reason = assign_level(0.85, 2 / 3, inp, cfg)
    assert level == "siaga" and reason is None


def test_one_source_reporting_cannot_reach_siaga() -> None:
    """C = 1/1 = 1.0 satisfies any ratio while corroborating nothing.

    This is not hypothetical: the newest day in the archive is routinely covered
    by one portal only, because the others publish later. Without this gate
    every "today" alert would claim unanimous agreement from a single voice.
    """
    cfg = _cfg()
    inp = FusionInput(n_sources_reporting=1, n_sources_flagging=1)
    level, reason = assign_level(0.90, 1.0, inp, cfg)
    assert level == "waspada"
    assert reason == "single_source_reporting"


def test_lifetime_single_source_coverage_caps_at_waspada() -> None:
    """nasional and kota_yogyakarta each have exactly one source, ever."""
    cfg = _cfg()
    inp = FusionInput(n_sources_reporting=1, n_sources_flagging=1, single_source_coverage=True)
    level, reason = assign_level(0.95, 1.0, inp, cfg)
    assert level == "waspada"
    assert reason == "single_source_coverage"


def test_weak_agreement_among_many_sources_is_downgraded() -> None:
    cfg = _cfg()
    inp = FusionInput(n_sources_reporting=4, n_sources_flagging=1)
    level, reason = assign_level(0.80, 0.25, inp, cfg)
    assert level == "waspada"
    assert reason == "insufficient_corroboration"


def test_thresholds_partition_the_score_range() -> None:
    cfg = _cfg()
    inp = FusionInput(n_sources_reporting=3, n_sources_flagging=3)
    assert assign_level(0.0, 1.0, inp, cfg)[0] == "tenang"
    assert assign_level(0.39, 1.0, inp, cfg)[0] == "tenang"
    assert assign_level(0.40, 1.0, inp, cfg)[0] == "waspada"
    assert assign_level(0.69, 1.0, inp, cfg)[0] == "waspada"
    assert assign_level(0.70, 1.0, inp, cfg)[0] == "siaga"


# ---------------------------------------------------------------------------
# End to end — the hand-checkable case from the M6 gate
# ---------------------------------------------------------------------------
def test_worked_example_matches_hand_arithmetic() -> None:
    """jawa_timur / cabai-rawit-merah / 2023-08-28, verified at the M6 gate.

    price   39,380 -> 29,442  = -25.24% over 7 days
    zscore  norm 0.739792, flagged
    iforest norm 0.981668, flagged
    sources 2 flagging of 2 reporting

    A = min(max(0.739792, 0.981668) * 1.15, 1) = 1.0
    M = min(0.2524 / 0.15, 1)                  = 1.0
    D = 0                                       (Trends throttled)
    C = 2 / 2                                   = 1.0
    F = 0.45 + 0.25 + 0.00 + 0.10               = 0.80
    """
    cfg = _cfg()
    result = fuse(
        FusionInput(
            norm_zscore=0.739792,
            norm_iforest=0.981668,
            zscore_flagged=True,
            iforest_flagged=True,
            pct_change_7d=-0.2524,
            demand_z52=None,
            n_sources_reporting=2,
            n_sources_flagging=2,
        ),
        cfg,
    )
    assert result.components["A"] == pytest.approx(1.0)
    assert result.components["M"] == pytest.approx(1.0)
    assert result.components["D"] == pytest.approx(0.0)
    assert result.components["C"] == pytest.approx(1.0)
    assert result.score == pytest.approx(0.80)
    assert result.level == "siaga"


def test_components_carry_everything_needed_to_decompose_an_alert() -> None:
    result = fuse(FusionInput(norm_zscore=0.5, pct_change_7d=0.05, n_sources_reporting=2), _cfg())
    for key in ("A", "M", "D", "C", "both_flagged", "n_sources_reporting", "weights"):
        assert key in result.components, f"components missing {key}"


def test_a_quiet_day_is_tenang_and_recommends_nothing_alarming() -> None:
    cfg = _cfg()
    result = fuse(FusionInput(norm_zscore=0.05, pct_change_7d=0.002, n_sources_reporting=3), cfg)
    assert result.level == "tenang"
    assert result.recommendation_id == cfg.recommendations["tenang"]


# ---------------------------------------------------------------------------
# The fourth level — absence of a judgement, not a quiet one
# ---------------------------------------------------------------------------
def test_an_unscored_date_does_not_fall_through_to_the_calmest_band() -> None:
    """41.31% of nasional dates used to render as `hijau` on this path."""
    cfg = _cfg()
    result = fuse(FusionInput(n_sources_reporting=3, n_sources_flagging=0), cfg)
    assert result.level == "belum_dapat_dinilai"
    assert result.score is None, "an unscored date must not carry a number"
    assert result.components["A"] is None


def test_an_unscored_date_offers_no_recommendation() -> None:
    """Advice derived from an absent observation is the thing to avoid."""
    cfg = _cfg()
    result = fuse(FusionInput(), cfg)
    assert result.recommendation_id is None
    assert "belum_dapat_dinilai" not in cfg.recommendations


def test_movement_alone_does_not_make_a_date_scorable() -> None:
    """M is observable without either detector; F is not.

    A 20% weekly move on a date no detector could score is still a date no
    detector could score. Letting M carry the row would produce a level from a
    quarter of the model and present it as the whole.
    """
    cfg = _cfg()
    result = fuse(FusionInput(pct_change_7d=0.20, n_sources_reporting=2), cfg)
    assert result.level == "belum_dapat_dinilai"
    # The observable parts are still recorded — they are the audit trail.
    assert result.components["M"] == pytest.approx(1.0)


def test_one_detector_is_enough_to_score() -> None:
    """The gate is on *neither* detector scoring, not on both."""
    cfg = _cfg()
    result = fuse(FusionInput(norm_zscore=0.9, n_sources_reporting=2), cfg)
    assert result.level != "belum_dapat_dinilai"
    assert result.score is not None


def test_assign_level_propagates_the_missing_score() -> None:
    cfg = _cfg()
    inp = FusionInput(n_sources_reporting=3, n_sources_flagging=3)
    level, reason = assign_level(None, 1.0, inp, cfg)
    assert level == "belum_dapat_dinilai"
    assert reason == "no_detector_score"


def test_score_is_bounded() -> None:
    cfg = _cfg()
    extreme = fuse(
        FusionInput(
            norm_zscore=1.0,
            norm_iforest=1.0,
            zscore_flagged=True,
            iforest_flagged=True,
            pct_change_7d=5.0,
            demand_z52=99.0,
            n_sources_reporting=4,
            n_sources_flagging=4,
        ),
        cfg,
    )
    assert extreme.score == pytest.approx(1.0)
    assert 0.0 <= extreme.score <= 1.0
