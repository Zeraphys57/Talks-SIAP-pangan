"""Coverage reporting — the M1 stop-gate evidence.

Two outputs, both required by the gate:

1. A coverage table per source x commodity x region: earliest date, latest date,
   row count and the percentage of days missing between the two.
2. A random sample of stored observations printed with the URL and fetch
   timestamp they came from, so a human can open those URLs and confirm the
   numbers independently.

The second is the point. A gate that can be passed by reading code proves
nothing; this one can only be passed by checking against the live portals.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from typing import Any

from .db import Conn, fetch_all


@dataclass
class CoverageRow:
    source: str
    commodity: str
    region: str
    first_date: date
    last_date: date
    n_rows: int
    expected_days: int

    @property
    def missing_pct(self) -> float:
        if self.expected_days <= 0:
            return 0.0
        return max(0.0, (1 - self.n_rows / self.expected_days) * 100)


def coverage_by_source(conn: Conn) -> list[dict[str, Any]]:
    """One row per source: overall span, row count and distinct coverage."""
    return fetch_all(
        conn,
        """
        select s.slug            as source,
               count(*)          as n_rows,
               min(o.obs_date)   as first_date,
               max(o.obs_date)   as last_date,
               count(distinct o.obs_date)     as distinct_days,
               count(distinct o.commodity_id) as n_commodities,
               count(distinct o.region_id)    as n_regions
          from public.price_observations o
          join public.sources s on s.id = o.source_id
         group by s.slug
         order by s.slug
        """,
    )


def coverage_detail(conn: Conn) -> list[CoverageRow]:
    """source x commodity x region coverage, with a missing-day percentage.

    "Expected days" is the inclusive span between the first and last observation
    for that combination — the fraction missing therefore measures gaps *within*
    the period actually covered, not the portal's failure to exist earlier.
    """
    rows = fetch_all(
        conn,
        """
        select s.slug  as source,
               c.slug  as commodity,
               rg.slug as region,
               min(o.obs_date) as first_date,
               max(o.obs_date) as last_date,
               count(*) as n_rows,
               (max(o.obs_date) - min(o.obs_date) + 1) as expected_days
          from public.price_observations o
          join public.sources s     on s.id  = o.source_id
          join public.commodities c on c.id  = o.commodity_id
          join public.regions rg    on rg.id = o.region_id
         group by s.slug, c.slug, rg.slug
         order by s.slug, rg.slug, c.slug
        """,
    )
    return [
        CoverageRow(
            source=str(r["source"]),
            commodity=str(r["commodity"]),
            region=str(r["region"]),
            first_date=r["first_date"],
            last_date=r["last_date"],
            n_rows=int(r["n_rows"]),
            expected_days=int(r["expected_days"]),
        )
        for r in rows
    ]


def weeks_covered(conn: Conn) -> list[dict[str, Any]]:
    """Distinct weeks per commodity x region — the M5 STL feasibility check.

    STL needs >= 104 weeks (two full seasonal cycles at period=52). This is
    computed on the reconciled view a human cares about — any source counts,
    because M2 merges them — so it answers "can seasonality run here at all".
    """
    return fetch_all(
        conn,
        """
        select c.slug as commodity,
               rg.slug as region,
               count(distinct date_trunc('week', o.obs_date)) as n_weeks,
               min(o.obs_date) as first_date,
               max(o.obs_date) as last_date
          from public.price_observations o
          join public.commodities c on c.id  = o.commodity_id
          join public.regions rg    on rg.id = o.region_id
         group by c.slug, rg.slug
         order by rg.slug, c.slug
        """,
    )


def random_samples(conn: Conn, n: int = 5, seed: int | None = None) -> list[dict[str, Any]]:
    """`n` observations drawn across different sources, with full provenance.

    Sampling is spread over sources rather than taken uniformly: a uniform draw
    from a table dominated by one backfill would verify the same scraper five
    times over.
    """
    rng = random.Random(seed)
    sources = [
        str(r["slug"])
        for r in fetch_all(
            conn,
            "select distinct s.slug from public.price_observations o "
            "join public.sources s on s.id = o.source_id order by s.slug",
        )
    ]
    if not sources:
        return []

    picks: list[dict[str, Any]] = []
    for i in range(n):
        source = sources[i % len(sources)]
        candidates = fetch_all(
            conn,
            """
            select c.slug as commodity, rg.slug as region, o.obs_date,
                   o.price_idr, o.canonical_unit, o.raw_unit, o.unit_factor,
                   s.slug as source, snap.url, snap.fetched_at, snap.http_status,
                   snap.parser_version
              from public.price_observations o
              join public.commodities c on c.id = o.commodity_id
              join public.regions rg    on rg.id = o.region_id
              join public.sources s     on s.id = o.source_id
              left join public.raw_snapshots snap on snap.id = o.snapshot_id
             where s.slug = %s
             order by random()
             limit 25
            """,
            (source,),
        )
        if not candidates:
            continue
        picks.append(rng.choice(candidates))
    return picks


def gaps(conn: Conn, limit: int = 15) -> list[dict[str, Any]]:
    """Recorded fetch failures, newest first — the other half of provenance.

    Every gap in the series above should be explainable by a row here.
    """
    return fetch_all(
        conn,
        """
        select coalesce(s.slug, '(unknown)') as source, f.attempted_at,
               f.error_class, left(coalesce(f.error_detail, ''), 120) as detail, f.url
          from public.fetch_failures f
          left join public.sources s on s.id = f.source_id
         order by f.attempted_at desc
         limit %s
        """,
        (limit,),
    )
