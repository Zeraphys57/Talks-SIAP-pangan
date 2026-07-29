"""Evaluation protocol: agreement, matching, and the four ablation arms.

Everything here is a pure function tested against constructed inputs. No test
in this file invents a ground-truth label — those come from two people, and the
harness exists to measure them, not to substitute for them.
"""

from __future__ import annotations

from datetime import date

import pytest

from siap.config import load_analysis
from siap.evaluate.kappa import cohens_kappa
from siap.evaluate.metrics import ARMS, Detection, Event, score


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------
def test_perfect_agreement_is_kappa_one() -> None:
    pairs = [("anomali", "anomali")] * 10 + [("normal", "normal")] * 10
    assert cohens_kappa(pairs).kappa == pytest.approx(1.0)


def test_chance_level_agreement_is_kappa_zero() -> None:
    """Why kappa and not accuracy.

    Two annotators who each say "normal" 90% of the time agree ~82% of the time
    while sharing no judgement at all. Accuracy would call that excellent.
    """
    pairs = (
        [("normal", "normal")] * 81
        + [("normal", "anomali")] * 9
        + [("anomali", "normal")] * 9
        + [("anomali", "anomali")] * 1
    )
    result = cohens_kappa(pairs)
    assert result.observed_agreement == pytest.approx(0.82)
    assert abs(result.kappa) < 0.05, "independent labelling must give kappa near 0"


def test_systematic_disagreement_is_negative() -> None:
    pairs = [("anomali", "normal")] * 10 + [("normal", "anomali")] * 10
    assert cohens_kappa(pairs).kappa < 0


def test_single_label_used_throughout_is_kappa_zero_not_one() -> None:
    """Total agreement carrying no information must not read as perfect."""
    result = cohens_kappa([("normal", "normal")] * 50)
    assert result.observed_agreement == 1.0
    assert result.kappa == 0.0


def test_ragu_participates_in_the_confusion_matrix() -> None:
    pairs = [("anomali", "ragu"), ("ragu", "ragu"), ("normal", "normal")]
    result = cohens_kappa(pairs)
    assert result.confusion["anomali"]["ragu"] == 1
    assert result.confusion["ragu"]["ragu"] == 1


def test_empty_pairing_raises_rather_than_returning_a_number() -> None:
    with pytest.raises(ValueError, match="no paired labels"):
        cohens_kappa([])


def test_interpretation_bands_are_reported() -> None:
    assert (
        cohens_kappa([("anomali", "anomali")] * 5 + [("normal", "normal")] * 5).interpretation
        == "almost perfect"
    )


def test_the_kappa_gate_is_configured_at_sixty() -> None:
    """The brief makes this a stop condition, not a metric to report and move on."""
    assert load_analysis().evaluation.min_kappa == 0.60


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def _event(start: str, end: str, commodity: int = 1, region: int = 1, eid: int = 1) -> Event:
    return Event(eid, commodity, region, date.fromisoformat(start), date.fromisoformat(end))


def _det(day: str, commodity: int = 1, region: int = 1) -> Detection:
    return Detection(commodity, region, date.fromisoformat(day))


def test_detection_inside_the_event_window_is_a_hit() -> None:
    result = score([_det("2024-03-15")], [_event("2024-03-14", "2024-03-18")], 3, "x")
    assert (result.tp, result.fp, result.fn) == (1, 0, 0)


def test_detection_within_tolerance_of_the_window_is_a_hit() -> None:
    """+/- 3 days: a detector that is two days early has still found the event."""
    result = score([_det("2024-03-11")], [_event("2024-03-14", "2024-03-18")], 3, "x")
    assert result.tp == 1


def test_detection_outside_tolerance_is_a_false_positive() -> None:
    result = score([_det("2024-03-09")], [_event("2024-03-14", "2024-03-18")], 3, "x")
    assert (result.tp, result.fp, result.fn) == (0, 1, 1)


def test_an_event_nobody_detected_is_a_false_negative() -> None:
    result = score([], [_event("2024-03-14", "2024-03-18")], 3, "x")
    assert (result.tp, result.fp, result.fn) == (0, 0, 1)


def test_matching_respects_commodity_and_region() -> None:
    """A cabai event in Jatim is not found by a beras detection in Jateng."""
    event = _event("2024-03-14", "2024-03-18", commodity=1, region=1)
    assert score([_det("2024-03-15", commodity=2)], [event], 3, "x").tp == 0
    assert score([_det("2024-03-15", region=2)], [event], 3, "x").tp == 0


def test_several_detections_in_one_event_count_once_for_recall() -> None:
    """Firing five times inside one event is one discovery, five demands on attention."""
    event = _event("2024-03-14", "2024-03-18")
    detections = [_det(f"2024-03-1{d}") for d in (4, 5, 6, 7, 8)]
    result = score(detections, [event], 3, "x")
    assert result.tp == 5  # precision counts detections
    assert result.fn == 0  # recall counts events
    assert result.recall == pytest.approx(1.0)
    assert result.precision == pytest.approx(1.0)


def test_precision_recall_f1_arithmetic() -> None:
    result = score(
        [_det("2024-03-15"), _det("2024-06-01")],
        [_event("2024-03-14", "2024-03-18"), _event("2024-09-01", "2024-09-05", eid=2)],
        3,
        "x",
    )
    assert (result.tp, result.fp, result.fn) == (1, 1, 1)
    assert result.precision == pytest.approx(0.5)
    assert result.recall == pytest.approx(0.5)
    assert result.f1 == pytest.approx(0.5)


def test_metrics_are_zero_not_undefined_when_nothing_is_detected() -> None:
    result = score([], [], 3, "x")
    assert (result.precision, result.recall, result.f1) == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# The ablation itself
# ---------------------------------------------------------------------------
def test_all_four_arms_are_declared() -> None:
    """The comparison is meaningless without the naive strawman in it."""
    assert ARMS == ("zscore_only", "iforest_only", "union", "fusion")


def test_union_is_expected_to_trade_precision_for_recall() -> None:
    """Sanity check on the arms' relationship, using constructed detections.

    union sees everything either arm saw, so it can only match more events and
    can only accrue more false positives. If a run ever shows union with both
    higher precision and higher recall than a single arm, something is wrong
    with how detections were loaded.
    """
    events = [_event("2024-03-14", "2024-03-18")]
    zscore = [_det("2024-03-15")]
    iforest = [_det("2024-03-15"), _det("2024-07-01")]
    union = zscore + [d for d in iforest if d not in zscore]

    z = score(zscore, events, 3, "zscore_only")
    u = score(union, events, 3, "union")
    assert u.recall >= z.recall
    assert u.precision <= z.precision


def test_tolerance_is_configured_at_three_days() -> None:
    assert load_analysis().evaluation.tolerance_days == 3


def test_dev_and_test_splits_are_distinguished() -> None:
    """evaluation_results records the split so leakage cannot be silent."""
    result = score([], [], 3, "fusion", split="dev")
    assert result.split == "dev"
    row = result.as_row(run_id=1)
    assert "dev" in row


# ---------------------------------------------------------------------------
# What the annotator is shown
# ---------------------------------------------------------------------------
def test_the_context_window_covers_the_baseline_the_definition_names() -> None:
    """The rule is '10% against the trailing 30-day mean, sustained two days'.

    A window that reached back only 14 days would show the annotator less than
    the baseline they are asked to judge against.
    """
    from siap.evaluate.groundtruth import BASELINE_DAYS, WINDOW_AFTER, WINDOW_BEFORE

    assert WINDOW_BEFORE >= BASELINE_DAYS
    assert WINDOW_AFTER >= 2, "the persistence half of the definition must be visible"


def test_the_definition_threshold_has_one_home() -> None:
    """The band drawn in /lab and the number quoted in the paper are the same constant."""
    from siap.evaluate.groundtruth import DEFINITION_PCT

    assert DEFINITION_PCT == 0.10


def test_the_baseline_is_refused_rather_than_estimated_from_too_little() -> None:
    from siap.evaluate.groundtruth import BASELINE_DAYS, BASELINE_MIN_OBS

    assert 0 < BASELINE_MIN_OBS <= BASELINE_DAYS
    assert BASELINE_MIN_OBS >= 20, (
        "a mean over a handful of days is not the baseline the definition names; "
        "the UI must be able to say so instead of drawing a band around noise"
    )


def test_the_stratum_rule_and_the_shown_baseline_are_different_quantities() -> None:
    """Blinding check.

    Stratum A fires on a 7-day change over 7%; the annotator sees deviation from
    a 30-day mean against a 10% bar. If these coincided, showing the context
    would tell the annotator which stratum the candidate came from.
    """
    from siap.evaluate.groundtruth import BASELINE_DAYS, DEFINITION_PCT

    params = load_analysis().evaluation
    assert params.stratum_a_pct_change_7d != DEFINITION_PCT
    assert BASELINE_DAYS != 7
