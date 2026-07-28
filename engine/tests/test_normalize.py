"""Normalization tests.

These cover the three §10 traps directly. Every case here is drawn from a string
or unit actually observed on a live portal on 2026-07-28, not invented.
"""

from __future__ import annotations

from datetime import date

import pytest

from siap.config import load_reference, load_units
from siap.normalize import NormalizationError, parse_indonesian_number, parse_price
from siap.scrapers.base import RawObservation


# ---------------------------------------------------------------------------
# Indonesian number formatting
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Real strings from siskaperbapo's price table.
        ("12.508", 12508.0),
        ("116.461", 116461.0),
        ("15.031", 15031.0),
        ("1.929", 1929.0),
        ("69.824", 69824.0),
        # With currency decoration.
        ("Rp 13.862", 13862.0),
        ("Rp. 141.940", 141940.0),
        # Decimal comma.
        ("12.508,50", 12508.50),
        ("0,91", 0.91),
        # Already numeric — the SP2KP JSON path.
        (16236.727272727272, 16236.727272727272),
        (15491, 15491.0),
        # Plain integers with no separators.
        ("35000", 35000.0),
    ],
)
def test_parse_indonesian_number(text: str | float, expected: float) -> None:
    assert parse_indonesian_number(text) == pytest.approx(expected)


def test_thousands_dot_is_not_read_as_a_decimal_point() -> None:
    """The whole point: float("12.508") would be 12.508, a 1000x error."""
    assert parse_indonesian_number("12.508") == 12508.0
    assert parse_indonesian_number("12.508") != 12.508


def test_bare_comma_is_a_decimal_mark() -> None:
    assert parse_indonesian_number("38,33") == pytest.approx(38.33)


def test_unparseable_text_raises_rather_than_returning_zero() -> None:
    with pytest.raises(NormalizationError):
        parse_indonesian_number("tidak ada data")
    with pytest.raises(NormalizationError):
        parse_indonesian_number("")


# ---------------------------------------------------------------------------
# The two conventions are mutually unparseable
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Real strings from the PIHPS grid.
        ("16,200", 16200.0),
        ("14,750", 14750.0),
        ("147,450", 147450.0),
        ("16,200.50", 16200.50),
        ("20,500", 20500.0),
    ],
)
def test_parse_price_en_convention(text: str, expected: float) -> None:
    assert parse_price(text, style="en") == pytest.approx(expected)


def test_the_same_string_means_different_things_in_each_convention() -> None:
    """Why the style is declared in sources.yaml rather than sniffed.

    "16,200" is valid under both conventions and means sixteen thousand two
    hundred to PIHPS but sixteen-point-two to siskaperbapo. No heuristic can
    tell them apart, and guessing wrong is a 1000x error.
    """
    assert parse_price("16,200", style="en") == 16200.0
    assert parse_price("16,200", style="id") == pytest.approx(16.2)


def test_each_live_source_declares_a_number_format() -> None:
    """A source added without declaring its convention would silently use 'id'."""
    reference = load_reference()
    assert reference.source("pihps").number_format == "en"
    assert reference.source("siskaperbapo").number_format == "id"


def test_pihps_declares_the_unit_it_does_not_publish() -> None:
    """PIHPS emits no unit field; the assumption must live somewhere explicit."""
    assert load_reference().source("pihps").default_unit == "kg"
    # siskaperbapo labels every row, so it must NOT carry a blanket assumption.
    assert load_reference().source("siskaperbapo").default_unit is None


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
def test_unit_aliases_cover_what_the_portals_actually_publish() -> None:
    units = load_units()
    # Left side is the literal string seen on a live portal.
    assert units.canonical_token("kg") == "kg"
    assert units.canonical_token("Kg") == "kg"
    assert units.canonical_token("lt") == "liter"  # sp2kp
    assert units.canonical_token("1 liter") == "liter"  # siskaperbapo
    assert units.canonical_token("1 Liter") == "liter"  # siskaperbapo, different case
    assert units.canonical_token("ekor") == "ekor"  # daging ayam kampung


def test_unknown_unit_returns_none_rather_than_defaulting_to_kg() -> None:
    """Defaulting an unrecognised unit to kilograms is how 10x bugs get in."""
    units = load_units()
    assert units.canonical_token("gantang") is None
    assert units.canonical_token("per karung") is None


def test_kg_to_litre_conversion_applies_only_to_cooking_oil() -> None:
    units = load_units()
    assert units.factor_for("kg", "liter", "minyak-goreng-curah") == pytest.approx(0.91)
    # Rice has no physical justification for a volume conversion.
    assert units.factor_for("kg", "liter", "beras-medium") is None


def test_identical_units_convert_with_factor_one() -> None:
    units = load_units()
    assert units.factor_for("kg", "kg", "beras-medium") == 1.0


def test_siskaperbapo_curah_oil_conversion_lands_in_a_sane_place() -> None:
    """siskaperbapo publishes minyak goreng curah per kg; canonical is per litre.

    Observed 2026-07-27: Rp 20.326/kg. At 0.91 kg per litre that is ~18,497
    per litre, which must sit inside the commodity's plausible band.
    """
    units = load_units()
    factor = units.factor_for("kg", "liter", "minyak-goreng-curah")
    assert factor is not None
    per_litre = parse_indonesian_number("20.326") * factor
    assert 8000 <= per_litre <= 30000
    assert per_litre == pytest.approx(18496.66, abs=1.0)


# ---------------------------------------------------------------------------
# RawObservation plumbing
# ---------------------------------------------------------------------------
def test_raw_observation_keeps_the_portal_spelling_and_unit() -> None:
    """Raw name and unit survive to the database so bugs stay diagnosable."""
    raw = RawObservation(
        source_slug="siskaperbapo",
        region_slug="jawa_timur",
        obs_date=date(2026, 7, 27),
        commodity_name_raw="Minyak Goreng Curah",
        price_raw=20326.0,
        unit_raw="kg",
    )
    assert raw.commodity_name_raw == "Minyak Goreng Curah"
    assert raw.unit_raw == "kg"
    assert raw.snapshot_id is None
