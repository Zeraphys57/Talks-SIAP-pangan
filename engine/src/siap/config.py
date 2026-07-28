"""Typed loaders for `engine/config/*.yaml`.

Two rules shape this module:

1. `extra="forbid"` everywhere. A typo in a YAML key raises at load time instead
   of being silently ignored and discovered as missing data weeks later.
2. Cross-file references are validated. A `source_aliases` entry naming a portal
   that does not exist in sources.yaml, or a source declaring coverage of a
   region that is not in regions.yaml, is a configuration bug and is reported as
   one — with the offending key named.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .paths import config_dir

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REGION_SLUG_RE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)*$")


class ConfigError(RuntimeError):
    """Raised when configuration is malformed or internally inconsistent."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# commodities.yaml
# ---------------------------------------------------------------------------
class PlausiblePrice(_Strict):
    """Sanity band in IDR per canonical unit.

    Wide on purpose. This catches order-of-magnitude unit-conversion mistakes
    (a per-litre figure read as per-kg, a per-ekor price read as per-kg), not
    market anomalies. Anomaly detection is a separate concern entirely.
    """

    min: float = Field(gt=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> PlausiblePrice:
        if self.max <= self.min:
            raise ValueError(f"plausible_price.max ({self.max}) must exceed min ({self.min})")
        return self


class CommodityConfig(_Strict):
    slug: str
    display_name: str
    canonical_unit: Literal["kg", "liter", "butir", "ikat"]
    sort_order: int = 0
    plausible_price: PlausiblePrice
    trends_keywords: list[str] = Field(min_length=1)
    source_aliases: dict[str, list[str]]

    # Portals that genuinely do not publish this commodity. Every active price
    # source must appear in either source_aliases or here, so "we have no
    # mapping yet" is never indistinguishable from "this portal doesn't carry
    # it". Populated in M1 when a portal's real commodity list is known.
    unavailable_at: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def _slug_format(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError(f"commodity slug {v!r} must be lower-case hyphen-separated")
        return v

    @field_validator("source_aliases")
    @classmethod
    def _aliases_non_empty(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for source_slug, aliases in v.items():
            if not aliases:
                raise ValueError(f"source_aliases[{source_slug}] is empty; omit the key instead")
        return v

    def alias_lookup(self) -> dict[tuple[str, str], str]:
        """Map (source_slug, normalized_alias) -> commodity slug.

        Normalization is case-folding plus whitespace collapse, which is enough
        to absorb 'CABAI RAWIT' vs 'Cabai  Rawit'. It deliberately does NOT
        absorb 'Cabai' vs 'Cabe' — those are listed explicitly so that an
        unfamiliar spelling raises rather than being fuzzily matched to the
        wrong commodity.
        """
        return {
            (source_slug, normalize_alias(alias)): self.slug
            for source_slug, aliases in self.source_aliases.items()
            for alias in aliases
        }


def normalize_alias(name: str) -> str:
    """Case-fold and collapse whitespace for alias matching."""
    return " ".join(name.split()).casefold()


# ---------------------------------------------------------------------------
# regions.yaml
# ---------------------------------------------------------------------------
class RegionConfig(_Strict):
    slug: str
    display_name: str
    level: Literal["national", "province", "city"]
    parent_slug: str | None = None
    bps_code: str | None = None

    @field_validator("slug", "parent_slug")
    @classmethod
    def _slug_format(cls, v: str | None) -> str | None:
        if v is not None and not REGION_SLUG_RE.match(v):
            raise ValueError(f"region slug {v!r} must be lower-case underscore-separated")
        return v


# ---------------------------------------------------------------------------
# sources.yaml
# ---------------------------------------------------------------------------
class ScrapingConduct(_Strict):
    """Politeness settings applied centrally to every HTTP source.

    Kept in one place rather than per-scraper so a new scraper cannot forget to
    be polite. Enforced by the scraper base class in M1.
    """

    respect_robots_txt: bool
    min_delay_seconds: float = Field(ge=1.0)
    max_concurrent_per_host: int = Field(ge=1, le=1)
    user_agent: str
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    backoff_base_seconds: float = Field(gt=0)

    @field_validator("user_agent")
    @classmethod
    def _identifies_contact(cls, v: str) -> str:
        if "{contact}" not in v:
            raise ValueError(
                "user_agent must contain the {contact} placeholder so every request "
                "carries a reachable address for the portal operator"
            )
        return v

    def resolved_user_agent(self, contact: str) -> str:
        return self.user_agent.replace("{contact}", contact)


class SourceConfig(_Strict):
    slug: str
    display_name: str
    owner: str
    base_url: str
    robots_url: str | None = None
    scope: str
    cadence: Literal["daily", "weekly"]
    regions: list[str] = Field(min_length=1)
    obs_date_convention: str | None = None
    is_active: bool = True
    notes: str | None = None

    @field_validator("base_url", "robots_url")
    @classmethod
    def _https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError(f"{v!r} must be an https:// URL")
        return v

    @property
    def is_price_source(self) -> bool:
        """Google Trends is a demand proxy, never a price source."""
        return self.slug != "trends"


# ---------------------------------------------------------------------------
# The validated whole
# ---------------------------------------------------------------------------
class ReferenceConfig(_Strict):
    """All three reference files, validated together."""

    commodities: tuple[CommodityConfig, ...]
    regions: tuple[RegionConfig, ...]
    sources: tuple[SourceConfig, ...]
    conduct: ScrapingConduct

    @model_validator(mode="after")
    def _cross_references_resolve(self) -> ReferenceConfig:
        region_slugs = {r.slug for r in self.regions}
        source_slugs = {s.slug for s in self.sources}
        problems: list[str] = []

        for region in self.regions:
            if region.parent_slug and region.parent_slug not in region_slugs:
                problems.append(
                    f"regions.yaml: {region.slug}.parent_slug -> unknown region "
                    f"{region.parent_slug!r}"
                )

        for source in self.sources:
            for region_slug in source.regions:
                if region_slug not in region_slugs:
                    problems.append(
                        f"sources.yaml: {source.slug}.regions -> unknown region {region_slug!r}"
                    )

        for commodity in self.commodities:
            for source_slug in commodity.source_aliases:
                if source_slug not in source_slugs:
                    problems.append(
                        f"commodities.yaml: {commodity.slug}.source_aliases -> unknown source "
                        f"{source_slug!r}"
                    )
            for source_slug in commodity.unavailable_at:
                if source_slug not in source_slugs:
                    problems.append(
                        f"commodities.yaml: {commodity.slug}.unavailable_at -> unknown source "
                        f"{source_slug!r}"
                    )
            both = set(commodity.source_aliases) & set(commodity.unavailable_at)
            if both:
                problems.append(
                    f"commodities.yaml: {commodity.slug} lists {sorted(both)} as both aliased "
                    f"and unavailable; pick one"
                )
            active_price_sources = {
                s.slug for s in self.sources if s.is_price_source and s.is_active
            }
            undeclared = (
                active_price_sources - set(commodity.source_aliases) - set(commodity.unavailable_at)
            )
            if undeclared:
                problems.append(
                    f"commodities.yaml: {commodity.slug} says nothing about active price "
                    f"source(s) {sorted(undeclared)}; add aliases, or list them under "
                    f"unavailable_at if the portal genuinely does not publish it"
                )

        if problems:
            raise ValueError(
                "configuration cross-references do not resolve:\n  - " + "\n  - ".join(problems)
            )
        return self

    def commodity(self, slug: str) -> CommodityConfig:
        for c in self.commodities:
            if c.slug == slug:
                return c
        raise KeyError(f"unknown commodity slug {slug!r}")

    def source(self, slug: str) -> SourceConfig:
        for s in self.sources:
            if s.slug == slug:
                return s
        raise KeyError(f"unknown source slug {slug!r}")

    def alias_index(self) -> dict[tuple[str, str], str]:
        """Global (source_slug, normalized_alias) -> commodity_slug map.

        Collisions raise: the same portal string mapping to two commodities would
        make normalization non-deterministic.
        """
        index: dict[tuple[str, str], str] = {}
        for commodity in self.commodities:
            for key, slug in commodity.alias_lookup().items():
                if key in index and index[key] != slug:
                    raise ConfigError(
                        f"alias collision: source {key[0]!r} string {key[1]!r} maps to both "
                        f"{index[key]!r} and {slug!r}"
                    )
                index[key] = slug
        return index


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing configuration file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path.name} must contain a YAML mapping at the top level")
    return loaded


def _versioned(path: Path, key: str) -> list[dict[str, Any]]:
    doc = _read_yaml(path)
    if key not in doc:
        raise ConfigError(f"{path.name} has no top-level {key!r} list")
    items = doc[key]
    if not isinstance(items, list) or not items:
        raise ConfigError(f"{path.name}: {key!r} must be a non-empty list")
    return items


@lru_cache(maxsize=1)
def load_reference() -> ReferenceConfig:
    """Load and cross-validate commodities.yaml, regions.yaml and sources.yaml."""
    cfg = config_dir()
    sources_doc = _read_yaml(cfg / "sources.yaml")
    if "conduct" not in sources_doc:
        raise ConfigError("sources.yaml has no top-level 'conduct' block")

    try:
        return ReferenceConfig(
            commodities=tuple(
                CommodityConfig(**item)
                for item in _versioned(cfg / "commodities.yaml", "commodities")
            ),
            regions=tuple(
                RegionConfig(**item) for item in _versioned(cfg / "regions.yaml", "regions")
            ),
            sources=tuple(
                SourceConfig(**item) for item in _versioned(cfg / "sources.yaml", "sources")
            ),
            conduct=ScrapingConduct(**sources_doc["conduct"]),
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


# ---------------------------------------------------------------------------
# units.yaml
# ---------------------------------------------------------------------------
class UnitConversion(BaseModel):
    """A justified rewrite of a price from one unit to another.

    `price_canonical = price_raw * factor`. Conversions are restricted to named
    commodities: a density that is right for cooking oil is wrong for rice, and
    a global factor would eventually be applied to the wrong thing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    from_unit: str = Field(alias="from")
    to_unit: str = Field(alias="to")
    factor: float = Field(gt=0)
    applies_to: list[str] = Field(min_length=1)
    note: str | None = None


class UnitsConfig(_Strict):
    aliases: dict[str, list[str]]
    conversions: tuple[UnitConversion, ...]

    def canonical_token(self, raw_unit: str | None) -> str | None:
        """Map a portal's unit string to a canonical token, or None if unknown.

        Returning None rather than defaulting to 'kg' is deliberate: an
        unrecognised unit must stop the row, not silently become a weight.
        """
        if raw_unit is None:
            return None
        needle = " ".join(raw_unit.split()).casefold()
        for token, spellings in self.aliases.items():
            if needle == token or needle in {s.casefold() for s in spellings}:
                return token
        return None

    def factor_for(self, from_unit: str, to_unit: str, commodity_slug: str) -> float | None:
        """Conversion multiplier, or None when no justified conversion exists."""
        if from_unit == to_unit:
            return 1.0
        for conversion in self.conversions:
            if (
                conversion.from_unit == from_unit
                and conversion.to_unit == to_unit
                and commodity_slug in conversion.applies_to
            ):
                return conversion.factor
        return None


@lru_cache(maxsize=1)
def load_units() -> UnitsConfig:
    """Load and validate units.yaml."""
    doc = _read_yaml(config_dir() / "units.yaml")
    for key in ("aliases", "conversions"):
        if key not in doc:
            raise ConfigError(f"units.yaml has no top-level {key!r}")
    try:
        return UnitsConfig(
            aliases=doc["aliases"],
            conversions=tuple(UnitConversion(**c) for c in doc["conversions"]),
        )
    except ValueError as exc:
        raise ConfigError(f"units.yaml is invalid: {exc}") from exc


def config_fingerprint() -> dict[str, str | int | None]:
    """Summary of the loaded reference data, for `analysis_runs.params`."""
    ref = load_reference()
    versions: dict[str, str | int | None] = {}
    for name in ("commodities", "regions", "sources"):
        doc = _read_yaml(config_dir() / f"{name}.yaml")
        raw = doc.get("updated")
        versions[f"{name}_version"] = doc.get("version")
        versions[f"{name}_updated"] = raw.isoformat() if isinstance(raw, date) else raw
    versions["n_commodities"] = len(ref.commodities)
    versions["n_regions"] = len(ref.regions)
    versions["n_sources"] = len(ref.sources)
    return versions
