"""Turn raw scraped rows into `price_observations`.

Three failure modes are handled explicitly, because each corresponds to a trap
named in the build brief:

1. **Unmapped commodity name.** A portal renames "Daging Sapi Murni" to
   "Daging Sapi Paha Belakang" and the series silently goes missing. Detected by
   checking, per source and date, that every commodity we *expect* from that
   source was actually found. Rows the portal publishes that we do not track
   (cement, rebar, fertiliser on siskaperbapo) are ignored — they are out of
   scope, not missing.

2. **Unit chaos.** An unrecognised unit stops the row rather than defaulting to
   kilograms. Conversions come from units.yaml and are restricted to named
   commodities.

3. **Implausible price.** A parse or conversion error of an order of magnitude
   is caught by the per-commodity band in commodities.yaml before it reaches the
   database, where it would look exactly like a finding.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from .config import ReferenceConfig, UnitsConfig, load_reference, load_units, normalize_alias
from .db import Conn, fetch_all
from .scrapers.base import RawObservation

log = logging.getLogger(__name__)


class NormalizationError(ValueError):
    """Raised when a raw row cannot be turned into a trustworthy observation."""


# ---------------------------------------------------------------------------
# Number parsing
# ---------------------------------------------------------------------------
_CURRENCY_STRIP = re.compile(r"(?i)\b(rp|idr)\b|[^\d.,\-]")


def parse_indonesian_number(text: str | float | int) -> float:
    """Parse an Indonesian-formatted price string.

    Indonesian uses '.' as the thousands separator and ',' as the decimal mark,
    the reverse of English. `float("12.508")` silently yields 12.508 instead of
    12508 — a 1000x error that would present as a spectacular anomaly.

        "12.508"      -> 12508.0
        "Rp 116.461"  -> 116461.0
        "12.508,50"   -> 12508.5
        "38,330"      -> 38.33     (comma is a decimal mark, not a separator)
    """
    if isinstance(text, (int, float)):
        return float(text)

    cleaned = _CURRENCY_STRIP.sub("", str(text)).strip()
    # "Rp. 141.940" leaves a leading separator once the currency word is gone.
    # Strip separators that cannot be part of a number at either end.
    cleaned = cleaned.strip(".,")
    if not cleaned or not any(ch.isdigit() for ch in cleaned):
        raise NormalizationError(f"no numeric content in {text!r}")

    has_dot, has_comma = "." in cleaned, "," in cleaned
    if has_dot and has_comma:
        # Whichever appears last is the decimal mark.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif has_dot:
        # '.' is a thousands separator when it groups digits in threes.
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", cleaned):
            cleaned = cleaned.replace(".", "")
    elif has_comma:
        cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError as exc:
        raise NormalizationError(f"cannot parse {text!r} as a number") from exc


# ---------------------------------------------------------------------------
# Result of normalizing one raw row
# ---------------------------------------------------------------------------
@dataclass
class NormalizedObservation:
    commodity_id: int
    commodity_slug: str
    source_id: int
    region_id: int
    obs_date: date
    price_idr: float
    raw_unit: str | None
    canonical_unit: str
    unit_factor: float
    snapshot_id: int | None
    matched_alias: str


@dataclass
class NormalizeReport:
    accepted: list[NormalizedObservation]
    rejected: list[tuple[RawObservation, str]]
    ignored_names: set[str]
    missing_commodities: dict[str, set[str]]  # region_slug -> commodity slugs

    @property
    def ok(self) -> bool:
        return not self.rejected and not self.missing_commodities


# ---------------------------------------------------------------------------
class Normalizer:
    def __init__(self, conn: Conn) -> None:
        self.conn = conn
        self.reference: ReferenceConfig = load_reference()
        self.units: UnitsConfig = load_units()

        self.commodity_ids = {
            str(r["slug"]): int(r["id"])
            for r in fetch_all(conn, "select id, slug from public.commodities")
        }
        self.region_ids = {
            str(r["slug"]): int(r["id"])
            for r in fetch_all(conn, "select id, slug from public.regions")
        }
        self.source_ids = {
            str(r["slug"]): int(r["id"])
            for r in fetch_all(conn, "select id, slug from public.sources")
        }
        self.alias_index = self.reference.alias_index()

    # -- alias resolution ---------------------------------------------------
    def resolve_commodity(self, source_slug: str, raw_name: str) -> str | None:
        """Commodity slug for a portal's name, or None when we do not track it."""
        return self.alias_index.get((source_slug, normalize_alias(raw_name)))

    def alias_rank(self, source_slug: str, commodity_slug: str, raw_name: str) -> int:
        """Position of `raw_name` in the commodity's alias list for this source.

        Lower wins. This implements the "first listed alias present in the
        response is canonical" rule from commodities.yaml, which is what keeps
        SP2KP's four beef cuts from colliding on the UNIQUE constraint.
        """
        aliases = self.reference.commodity(commodity_slug).source_aliases.get(source_slug, [])
        needle = normalize_alias(raw_name)
        for position, alias in enumerate(aliases):
            if normalize_alias(alias) == needle:
                return position
        return len(aliases)

    # -- one row ------------------------------------------------------------
    def normalize_one(self, raw: RawObservation) -> NormalizedObservation:
        commodity_slug = self.resolve_commodity(raw.source_slug, raw.commodity_name_raw)
        if commodity_slug is None:
            raise NormalizationError(f"untracked commodity {raw.commodity_name_raw!r}")

        commodity = self.reference.commodity(commodity_slug)

        raw_token = self.units.canonical_token(raw.unit_raw)
        if raw.unit_raw is not None and raw_token is None:
            raise NormalizationError(
                f"unrecognised unit {raw.unit_raw!r} for {commodity_slug}; "
                f"add it to units.yaml rather than assuming kilograms"
            )
        # A source that publishes no unit at all is trusted to already be
        # canonical, which is true for the JSON APIs where the unit is a
        # property of the variant rather than the row.
        from_unit = raw_token or commodity.canonical_unit

        factor = self.units.factor_for(from_unit, commodity.canonical_unit, commodity_slug)
        if factor is None:
            raise NormalizationError(
                f"no justified conversion from {from_unit!r} to "
                f"{commodity.canonical_unit!r} for {commodity_slug}"
            )

        price = parse_indonesian_number(raw.price_raw) * factor

        band = commodity.plausible_price
        if not (band.min <= price <= band.max):
            raise NormalizationError(
                f"{commodity_slug} price {price:,.2f} IDR/{commodity.canonical_unit} is outside "
                f"the plausible band {band.min:,.0f}-{band.max:,.0f} "
                f"(raw={raw.price_raw!r} unit={raw.unit_raw!r} factor={factor}). "
                f"This is a unit or parsing bug, not a market move."
            )

        if raw.region_slug not in self.region_ids:
            raise NormalizationError(f"unknown region {raw.region_slug!r}")

        return NormalizedObservation(
            commodity_id=self.commodity_ids[commodity_slug],
            commodity_slug=commodity_slug,
            source_id=self.source_ids[raw.source_slug],
            region_id=self.region_ids[raw.region_slug],
            obs_date=raw.obs_date,
            price_idr=round(price, 2),
            raw_unit=raw.unit_raw,
            canonical_unit=commodity.canonical_unit,
            unit_factor=factor,
            snapshot_id=raw.snapshot_id,
            matched_alias=raw.commodity_name_raw,
        )

    # -- a batch ------------------------------------------------------------
    def normalize_batch(
        self, raws: list[RawObservation], *, expect_commodities: set[str] | None = None
    ) -> NormalizeReport:
        """Normalize rows, deduplicate by alias rank, and report what went missing.

        `expect_commodities` is the set of commodity slugs this source is
        supposed to publish. Anything expected but absent is reported — that is
        the signal that a portal renamed something under us.
        """
        best: dict[tuple[str, str, date], tuple[int, NormalizedObservation]] = {}
        rejected: list[tuple[RawObservation, str]] = []
        ignored: set[str] = set()

        for raw in raws:
            slug = self.resolve_commodity(raw.source_slug, raw.commodity_name_raw)
            if slug is None:
                ignored.add(raw.commodity_name_raw)
                continue
            try:
                observation = self.normalize_one(raw)
            except NormalizationError as exc:
                rejected.append((raw, str(exc)))
                continue

            key = (slug, raw.region_slug, raw.obs_date)
            rank = self.alias_rank(raw.source_slug, slug, raw.commodity_name_raw)
            existing = best.get(key)
            if existing is None or rank < existing[0]:
                best[key] = (rank, observation)

        accepted = [obs for _, obs in best.values()]

        missing: dict[str, set[str]] = {}
        if expect_commodities is not None:
            seen_by_region: dict[str, set[str]] = {}
            for slug, region_slug, _ in best:
                seen_by_region.setdefault(region_slug, set()).add(slug)
            for region_slug, seen in seen_by_region.items():
                absent = expect_commodities - seen
                if absent:
                    missing[region_slug] = absent

        return NormalizeReport(
            accepted=accepted,
            rejected=rejected,
            ignored_names=ignored,
            missing_commodities=missing,
        )

    # -- persistence --------------------------------------------------------
    def persist(self, observations: list[NormalizedObservation]) -> int:
        """Upsert observations. Re-ingesting the same day is idempotent."""
        if not observations:
            return 0
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.price_observations
                    (commodity_id, source_id, region_id, obs_date, price_idr,
                     raw_unit, canonical_unit, unit_factor, snapshot_id)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (commodity_id, source_id, region_id, obs_date) do update set
                    price_idr      = excluded.price_idr,
                    raw_unit       = excluded.raw_unit,
                    canonical_unit = excluded.canonical_unit,
                    unit_factor    = excluded.unit_factor,
                    snapshot_id    = excluded.snapshot_id,
                    ingested_at    = now()
                """,
                [
                    (
                        o.commodity_id,
                        o.source_id,
                        o.region_id,
                        o.obs_date,
                        o.price_idr,
                        o.raw_unit,
                        o.canonical_unit,
                        o.unit_factor,
                        o.snapshot_id,
                    )
                    for o in observations
                ],
            )
        self.conn.commit()
        return len(observations)
