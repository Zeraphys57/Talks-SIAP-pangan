"""Configuration is reference data, so these tests assert against the real files.

If someone adds a commodity, renames a source, or fat-fingers a region slug,
these fail before any of it reaches the database.
"""

from __future__ import annotations

import pytest

from siap.config import (
    CommodityConfig,
    ConfigError,
    ReferenceConfig,
    ScrapingConduct,
    load_reference,
    normalize_alias,
)


@pytest.fixture(scope="module")
def ref() -> ReferenceConfig:
    return load_reference()


def test_reference_config_loads_and_cross_validates(ref: ReferenceConfig) -> None:
    assert len(ref.commodities) == 12
    assert len(ref.regions) == 5
    assert len(ref.sources) == 6


def test_slugs_are_unique(ref: ReferenceConfig) -> None:
    for label, slugs in (
        ("commodity", [c.slug for c in ref.commodities]),
        ("region", [r.slug for r in ref.regions]),
        ("source", [s.slug for s in ref.sources]),
    ):
        assert len(slugs) == len(set(slugs)), f"duplicate {label} slug"


def test_the_twelve_commodities_from_the_brief_are_present(ref: ReferenceConfig) -> None:
    expected = {
        "beras-medium",
        "beras-premium",
        "cabai-merah-keriting",
        "cabai-rawit-merah",
        "bawang-merah",
        "bawang-putih",
        "telur-ayam-ras",
        "daging-ayam-ras",
        "daging-sapi",
        "minyak-goreng-curah",
        "minyak-goreng-kemasan",
        "gula-pasir",
    }
    assert {c.slug for c in ref.commodities} == expected


def test_the_five_regions_from_the_brief_are_present(ref: ReferenceConfig) -> None:
    assert {r.slug for r in ref.regions} == {
        "nasional",
        "di_yogyakarta",
        "kota_yogyakarta",
        "jawa_tengah",
        "jawa_timur",
    }


def test_panelharga_and_sp2kp_are_modelled_as_separate_systems(ref: ReferenceConfig) -> None:
    """The original proposal conflates Bapanas' Panel Harga with Kemendag's SP2KP."""
    panelharga, sp2kp = ref.source("panelharga"), ref.source("sp2kp")
    assert panelharga.owner != sp2kp.owner
    assert panelharga.base_url != sp2kp.base_url


def test_siskaperbapo_is_jawa_timur_not_jawa_tengah(ref: ReferenceConfig) -> None:
    """The original proposal misattributes this portal. It is East Java."""
    siskaperbapo = ref.source("siskaperbapo")
    assert siskaperbapo.regions == ["jawa_timur"]
    assert "jawa_tengah" not in siskaperbapo.regions


def test_trends_is_not_a_price_source(ref: ReferenceConfig) -> None:
    assert ref.source("trends").is_price_source is False
    assert all(s.is_price_source for s in ref.sources if s.slug != "trends")


def test_alias_index_has_no_collisions(ref: ReferenceConfig) -> None:
    """A portal string resolving to two commodities makes normalization ambiguous."""
    index = ref.alias_index()
    assert len(index) > 0
    for (source_slug, alias), commodity_slug in index.items():
        assert source_slug in {s.slug for s in ref.sources}
        assert alias == normalize_alias(alias)
        assert commodity_slug in {c.slug for c in ref.commodities}


def test_every_commodity_declares_every_active_price_source(ref: ReferenceConfig) -> None:
    active = {s.slug for s in ref.sources if s.is_price_source and s.is_active}
    for c in ref.commodities:
        declared = set(c.source_aliases) | set(c.unavailable_at)
        assert active <= declared, f"{c.slug} says nothing about {sorted(active - declared)}"


def test_plausible_price_bands_are_ordered_and_positive(ref: ReferenceConfig) -> None:
    for c in ref.commodities:
        assert 0 < c.plausible_price.min < c.plausible_price.max


def test_volatile_commodities_have_wider_bands_than_staples(ref: ReferenceConfig) -> None:
    """A sanity check on the guards themselves, not on the market.

    Chilli genuinely swings by an order of magnitude; rice does not. If the rice
    band were as wide as the chilli band it would stop catching unit bugs.
    """

    def width(slug: str) -> float:
        c = ref.commodity(slug)
        return c.plausible_price.max / c.plausible_price.min

    assert width("cabai-rawit-merah") > width("beras-medium")


def test_normalize_alias_folds_case_and_collapses_whitespace() -> None:
    assert normalize_alias("CABAI RAWIT") == normalize_alias("Cabai  Rawit") == "cabai rawit"


def test_normalize_alias_does_not_conflate_distinct_spellings() -> None:
    """'Cabai' and 'Cabe' must be listed explicitly, never fuzzily matched."""
    assert normalize_alias("Cabai Rawit") != normalize_alias("Cabe Rawit")


def test_conduct_requires_a_reachable_contact_in_the_user_agent(ref: ReferenceConfig) -> None:
    assert "{contact}" in ref.conduct.user_agent
    resolved = ref.conduct.resolved_user_agent("someone@example.ac.id")
    assert "someone@example.ac.id" in resolved
    assert "{contact}" not in resolved


def test_conduct_enforces_the_politeness_floor(ref: ReferenceConfig) -> None:
    assert ref.conduct.min_delay_seconds >= 2.0
    assert ref.conduct.max_concurrent_per_host == 1
    assert ref.conduct.respect_robots_txt is True


def test_conduct_rejects_a_user_agent_without_contact() -> None:
    with pytest.raises(ValueError, match="contact"):
        ScrapingConduct(
            respect_robots_txt=True,
            min_delay_seconds=2.0,
            max_concurrent_per_host=1,
            user_agent="SIAP-PANGAN/0.1",
            timeout_seconds=30,
            max_retries=3,
            backoff_base_seconds=5,
        )


def test_unknown_yaml_key_is_rejected_rather_than_ignored() -> None:
    """A typo must fail loudly; silently dropping it looks like missing data later."""
    with pytest.raises(ValueError):
        CommodityConfig(
            slug="beras-medium",
            display_name="Beras medium",
            canonical_unit="kg",
            plausible_price={"min": 1000, "max": 2000},
            trends_keywords=["harga beras"],
            source_aliases={"panelharga": ["Beras Medium"]},
            trend_keywords=["typo"],  # type: ignore[call-arg]
        )


def test_inverted_plausible_band_is_rejected() -> None:
    with pytest.raises(ValueError):
        CommodityConfig(
            slug="beras-medium",
            display_name="Beras medium",
            canonical_unit="kg",
            plausible_price={"min": 20000, "max": 5000},
            trends_keywords=["harga beras"],
            source_aliases={"panelharga": ["Beras Medium"]},
        )


def test_config_error_is_raised_for_missing_files(tmp_path, monkeypatch) -> None:
    import siap.config as config_module

    monkeypatch.setattr(config_module, "config_dir", lambda: tmp_path)
    config_module.load_reference.cache_clear()
    try:
        with pytest.raises(ConfigError, match="missing configuration file"):
            config_module.load_reference()
    finally:
        config_module.load_reference.cache_clear()
