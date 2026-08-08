"""Determinism verification.

The comparison logic is what these guard. A verifier that reports spurious
mismatches gets ignored, and a verifier that silently passes everything is
worse than none — it converts an unchecked claim into a checked-looking one.

Both failure modes actually happened while building this: NaN scores compared
unequal to the NULLs they were stored as, and `partial` runs were excluded from
selection so there was nothing to verify.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from siap.reproduce import STORED_SCALE, ReproduceReport, _quantise, _version_drift


# ---------------------------------------------------------------------------
# Score normalisation
# ---------------------------------------------------------------------------
def test_nan_is_normalised_to_null() -> None:
    """A warm-up score is NaN in pandas and NULL in Postgres. Same fact.

    Without this the 30-day warm-up of every series reports as a mismatch — and
    would appear to mismatch itself, since NaN never equals NaN.
    """
    assert _quantise(float("nan")) is None
    assert _quantise(None) is None
    assert _quantise(Decimal("NaN")) is None


def test_nan_and_null_compare_equal_after_normalising() -> None:
    assert _quantise(float("nan")) == _quantise(None)


def test_scores_are_compared_at_the_precision_the_database_keeps() -> None:
    """anomaly_scores.raw_score is numeric(12,6); comparing deeper is noise."""
    assert Decimal("0.000001") == STORED_SCALE
    assert _quantise(1.23456789) == Decimal("1.234568")
    assert _quantise(Decimal("1.234568")) == _quantise(1.23456789)


def test_a_real_difference_is_not_rounded_away() -> None:
    """The check must still fail on a difference the database would have kept."""
    assert _quantise(1.234568) != _quantise(1.234569)


def test_negative_and_zero_scores_round_trip() -> None:
    assert _quantise(-2.5) == Decimal("-2.500000")
    assert _quantise(0.0) == Decimal("0.000000")


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------
def test_a_clean_report_is_ok() -> None:
    report = ReproduceReport(run_id=1, stored_rows=10, recomputed_rows=10)
    assert report.scores_match
    assert report.counts_match
    assert report.ok


def test_differing_row_counts_fail_even_with_no_mismatches() -> None:
    """Nothing mismatched because there was nothing to compare against."""
    report = ReproduceReport(run_id=1, stored_rows=10, recomputed_rows=7)
    assert report.scores_match
    assert not report.ok


def test_version_drift_alone_does_not_fail_the_run() -> None:
    """Determinism is about the numbers.

    A newer statsmodels that produced identical scores is worth reporting, not
    worth failing — the point is that the reader cites the recorded versions.
    """
    report = ReproduceReport(run_id=1, stored_rows=5, recomputed_rows=5)
    report.version_drift = {"statsmodels": ("0.14.5", "0.14.6")}
    assert report.ok


def test_a_dirty_tree_means_the_commit_does_not_identify_the_code() -> None:
    report = ReproduceReport(run_id=1)
    report.run_git_sha = "abc123-dirty"
    report.current_git_sha = "abc123-dirty"
    assert not report.code_matches, "a dirty tree cannot certify which code ran"

    report.run_git_sha = report.current_git_sha = "abc123"
    assert report.code_matches


def test_missing_provenance_is_not_treated_as_a_match() -> None:
    report = ReproduceReport(run_id=1)
    report.run_git_sha = None
    report.current_git_sha = "abc123"
    assert not report.code_matches


# ---------------------------------------------------------------------------
# Version drift
# ---------------------------------------------------------------------------
def test_version_drift_reports_both_sides() -> None:
    drift = _version_drift({"pandas": "2.2.0", "numpy": "2.5.1"})
    assert "pandas" in drift, "a version that moved must be reported"
    was, now = drift["pandas"]
    assert was == "2.2.0"
    assert now != "2.2.0"


def test_version_drift_ignores_a_malformed_record() -> None:
    """Runs written before lib_versions existed must not crash the verifier."""
    assert _version_drift(None) == {}
    assert _version_drift("not a dict") == {}


def test_matching_versions_report_no_drift() -> None:
    from siap.runs import lib_versions

    assert _version_drift(lib_versions()) == {}


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------
def test_the_lock_file_pins_every_analysis_library() -> None:
    """A range does not identify the scikit-learn that produced a figure."""
    from siap.paths import repo_root

    lock = (repo_root() / "engine" / "requirements.lock").read_text(encoding="utf-8")
    for package in ("scikit-learn", "statsmodels", "pandas", "numpy"):
        assert f"\n{package}==" in lock, f"{package} is not pinned in requirements.lock"


def test_the_lock_uses_exact_pins_only() -> None:
    from siap.paths import repo_root

    lock = (repo_root() / "engine" / "requirements.lock").read_text(encoding="utf-8")
    for line in lock.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        assert "==" in entry, f"{entry!r} is not an exact pin"


@pytest.mark.parametrize("run_type", ["cluster", "fusion", "gt_pool", "preprocess"])
def test_only_anomaly_runs_are_verifiable(run_type: str) -> None:
    """Other run types do not store a score per row, so there is nothing to diff.

    Refusing is the honest answer; silently reporting success would make the
    check meaningless for exactly the runs it cannot inspect.
    """
    from siap.reproduce import verify

    class _Conn:
        pass

    import siap.reproduce as module

    original = module.load_run
    module.load_run = lambda conn, run_id: {  # type: ignore[assignment]
        "id": run_id,
        "run_type": run_type,
        "status": "success",
        "git_sha": "abc",
        "seed": 1,
        "params": {},
        "lib_versions": {},
    }
    try:
        with pytest.raises(ValueError, match="anomaly"):
            verify(_Conn(), 1)  # type: ignore[arg-type]
    finally:
        module.load_run = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# The demand scope, which the verifier once derived for itself
# ---------------------------------------------------------------------------
def test_every_region_maps_to_a_scope_trends_is_actually_collected_for() -> None:
    """Regions outside Trends' two scopes fall back to national, never to nothing."""
    from siap.analyze import DEMAND_SCOPES, demand_scope

    for slug in ("nasional", "di_yogyakarta", "jawa_tengah", "jawa_timur", "kota_yogyakarta"):
        assert demand_scope(slug) in DEMAND_SCOPES


def test_the_two_collected_scopes_map_to_themselves() -> None:
    from siap.analyze import demand_scope

    assert demand_scope("nasional") == "nasional"
    assert demand_scope("di_yogyakarta") == "di_yogyakarta"


def test_a_region_level_is_not_a_demand_scope() -> None:
    """The regression itself.

    `verify` passed `regions.level` — 'province', 'city', 'national' — where a
    `region_scope` was wanted. It matched no row, `load_demand` returned empty,
    and every forest was refitted on a constant `demand_z52` and then compared
    against one fitted on the real signal. Silent while Trends was throttled.
    """
    from siap.analyze import DEMAND_SCOPES

    for level in ("province", "city", "national"):
        assert level not in DEMAND_SCOPES


def test_the_verifier_resolves_demand_through_the_shared_rule() -> None:
    """Guards against the two copies drifting apart a second time."""
    import inspect

    from siap.reproduce import verify

    source = inspect.getsource(verify)
    assert "demand_scope(" in source, "verify must use analyze's rule, not its own"
    assert "region_level" not in source, "regions.level is not a demand scope"
