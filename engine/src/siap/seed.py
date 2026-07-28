"""Seed reference tables from `engine/config/*.yaml`.

Idempotent: every write is an upsert keyed on the natural slug, so `siap seed`
can be re-run after editing a YAML file and will converge the database onto it.

Rows present in the database but absent from YAML are REPORTED, never deleted.
A commodity or source that disappears from configuration may still be referenced
by thousands of observations; silently cascading that away would destroy
provenance. Removal is a deliberate act, done with a migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from psycopg.types.json import Json

from .config import ReferenceConfig, load_reference
from .db import Conn, fetch_all

_LEVEL_ORDER = {"national": 0, "province": 1, "city": 2}


@dataclass
class SeedReport:
    inserted: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    coverage_links: int = 0
    orphans: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_orphans(self) -> bool:
        return any(self.orphans.values())


def _upsert_regions(conn: Conn, ref: ReferenceConfig, report: SeedReport) -> None:
    # Parents before children: regions.parent_slug is a self-referential FK.
    ordered = sorted(ref.regions, key=lambda r: (_LEVEL_ORDER[r.level], r.slug))
    inserted = updated = 0
    with conn.cursor() as cur:
        for region in ordered:
            cur.execute(
                """
                insert into public.regions (slug, display_name, level, parent_slug, bps_code)
                values (%s, %s, %s, %s, %s)
                on conflict (slug) do update set
                    display_name = excluded.display_name,
                    level        = excluded.level,
                    parent_slug  = excluded.parent_slug,
                    bps_code     = excluded.bps_code
                returning (xmax = 0) as was_inserted
                """,
                (
                    region.slug,
                    region.display_name,
                    region.level,
                    region.parent_slug,
                    region.bps_code,
                ),
            )
            row = cur.fetchone()
            if row and row["was_inserted"]:
                inserted += 1
            else:
                updated += 1
    report.inserted["regions"] = inserted
    report.updated["regions"] = updated


def _upsert_commodities(conn: Conn, ref: ReferenceConfig, report: SeedReport) -> None:
    inserted = updated = 0
    with conn.cursor() as cur:
        for c in ref.commodities:
            aliases = dict(c.source_aliases)
            if c.unavailable_at:
                # Preserved in the same jsonb column so the mapping story for a
                # commodity is readable from one place in the database.
                aliases["__unavailable_at__"] = list(c.unavailable_at)
            cur.execute(
                """
                insert into public.commodities (
                    slug, display_name, canonical_unit, sort_order,
                    price_min_plausible, price_max_plausible,
                    trends_keywords, source_aliases
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (slug) do update set
                    display_name        = excluded.display_name,
                    canonical_unit      = excluded.canonical_unit,
                    sort_order          = excluded.sort_order,
                    price_min_plausible = excluded.price_min_plausible,
                    price_max_plausible = excluded.price_max_plausible,
                    trends_keywords     = excluded.trends_keywords,
                    source_aliases      = excluded.source_aliases,
                    updated_at          = now()
                returning (xmax = 0) as was_inserted
                """,
                (
                    c.slug,
                    c.display_name,
                    c.canonical_unit,
                    c.sort_order,
                    c.plausible_price.min,
                    c.plausible_price.max,
                    c.trends_keywords,
                    Json(aliases),
                ),
            )
            row = cur.fetchone()
            if row and row["was_inserted"]:
                inserted += 1
            else:
                updated += 1
    report.inserted["commodities"] = inserted
    report.updated["commodities"] = updated


def _upsert_sources(conn: Conn, ref: ReferenceConfig, report: SeedReport) -> None:
    inserted = updated = 0
    with conn.cursor() as cur:
        for s in ref.sources:
            cur.execute(
                """
                insert into public.sources (
                    slug, display_name, owner, base_url, robots_url,
                    scope, cadence, obs_date_convention, is_active, notes
                )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (slug) do update set
                    display_name        = excluded.display_name,
                    owner               = excluded.owner,
                    base_url            = excluded.base_url,
                    robots_url          = excluded.robots_url,
                    scope               = excluded.scope,
                    cadence             = excluded.cadence,
                    obs_date_convention = excluded.obs_date_convention,
                    is_active           = excluded.is_active,
                    notes               = excluded.notes,
                    updated_at          = now()
                returning (xmax = 0) as was_inserted
                """,
                (
                    s.slug,
                    s.display_name,
                    s.owner,
                    s.base_url,
                    s.robots_url,
                    s.scope,
                    s.cadence,
                    s.obs_date_convention,
                    s.is_active,
                    (s.notes or "").strip() or None,
                ),
            )
            row = cur.fetchone()
            if row and row["was_inserted"]:
                inserted += 1
            else:
                updated += 1
    report.inserted["sources"] = inserted
    report.updated["sources"] = updated


def _sync_coverage(conn: Conn, ref: ReferenceConfig, report: SeedReport) -> None:
    """Rebuild source_regions to match the declared coverage exactly.

    This table is pure configuration — it holds no observations — so replacing
    stale links is safe, unlike deleting a source or commodity.
    """
    total = 0
    with conn.cursor() as cur:
        for s in ref.sources:
            cur.execute(
                """
                delete from public.source_regions sr
                using public.sources src
                where sr.source_id = src.id
                  and src.slug = %s
                  and sr.region_id not in (
                      select id from public.regions where slug = any(%s)
                  )
                """,
                (s.slug, s.regions),
            )
            cur.execute(
                """
                insert into public.source_regions (source_id, region_id)
                select src.id, r.id
                  from public.sources src
                  join public.regions r on r.slug = any(%s)
                 where src.slug = %s
                on conflict do nothing
                """,
                (s.regions, s.slug),
            )
            total += len(s.regions)
    report.coverage_links = total


def _find_orphans(conn: Conn, ref: ReferenceConfig, report: SeedReport) -> None:
    for table, configured in (
        ("commodities", {c.slug for c in ref.commodities}),
        ("regions", {r.slug for r in ref.regions}),
        ("sources", {s.slug for s in ref.sources}),
    ):
        rows = fetch_all(conn, f'select slug from public."{table}" order by slug')
        report.orphans[table] = [str(r["slug"]) for r in rows if str(r["slug"]) not in configured]


def seed(conn: Conn) -> SeedReport:
    """Load YAML reference data into the database. Returns what changed."""
    ref = load_reference()
    report = SeedReport()

    _upsert_regions(conn, ref, report)
    _upsert_commodities(conn, ref, report)
    _upsert_sources(conn, ref, report)
    _sync_coverage(conn, ref, report)
    conn.commit()

    _find_orphans(conn, ref, report)
    return report
