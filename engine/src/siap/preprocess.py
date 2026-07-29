"""Reconcile per-source observations into one daily series per commodity x region.

Reads `price_observations` (one row per source) and writes `price_daily_unified`
(one row per calendar day), which is the single input to every analysis module
from M3 onward.

Four decisions shape this module, all of them consequences of what the data
turned out to be:

**Rebase before reconciling.** The sources do not measure the same thing. PIHPS
samples traditional-market retail, SP2KP is Kemendag's panel, Siskaperbapo is
East Java's provincial survey, and they sit systematically apart — 5.2% pooled,
18% for beras-medium in Jawa Tengah. Taking a median across whichever of them
reported on a given day produced a series that *stepped* whenever the membership
changed, and 673 of 2,979 Z-Score flags sat on exactly such a step. Each source
is therefore multiplied onto a per-series reference level first (see
`source_offsets` and migration 0009), so a source dropping out no longer looks
like a price move.

**Median, not mean.** With two to four sources, one portal publishing a stale or
mistyped figure would drag a mean noticeably; a median is what keeps that from
distorting the series. Rebasing does not make this redundant — it removes the
*systematic* level gap, and the median still absorbs the occasional bad reading.
The spread is recorded alongside rather than averaged away, and now that it is
computed on the rebased scale it measures genuine same-day disagreement instead
of the constant offset between survey frames.

**A complete calendar.** Rows are materialised for every day between a series'
first and last observation, including days nothing was reported. STL in M5 needs
regular spacing, and an absent row is indistinguishable from a row nobody has
computed yet. A day with no usable price gets `price_median = NULL`.

**Interpolation only across short gaps.** The brief permits filling gaps of at
most three days. Longer gaps stay NULL. Every filled row carries
`is_imputed = true` and the method used, because those rows are excluded from
ground-truth evaluation in M7 and drawn differently in the dashboard.

Note on PIHPS: it publishes Monday to Friday, so its weekend gaps are exactly
two days and therefore fall inside the interpolation window. That is defensible
— the markets themselves trade at weekends, PIHPS simply does not survey then —
but it means a region covered only by PIHPS will show roughly 2/7 of its days
imputed. The completeness report makes that explicit rather than burying it.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .db import Conn, fetch_all
from .paths import docs_dir
from .runs import Run

log = logging.getLogger(__name__)

# The brief's rule: interpolation is permitted across gaps of at most this many
# consecutive missing days. Anything longer stays NULL.
MAX_INTERPOLATION_GAP_DAYS = 3

# A spread this wide between sources on the same day is almost certainly a unit
# or parsing bug rather than a market: portals disagree by percentages, not by
# factors. Flagged for the M2 gate, not silently dropped.
SUSPICIOUS_SPREAD_PCT = 100.0

# Overlapping days required before one source can be linked to another. Below
# this the factor is an average of too little, and a wrong factor is worse than
# an excluded source: it moves every price in the series by a fixed error that
# nothing downstream can detect.
MIN_LINK_OVERLAP_DAYS = 30

# Above this ratio dispersion, a single factor stops describing the relationship
# between two sources well. Reported, not enforced: the affected series are the
# volatile ones (chillies, garlic), where 6-9% day-to-day divergence between two
# surveys of different markets is real heterogeneity rather than a broken link.
# Dropping the second source there would cost genuine corroboration on exactly
# the commodities that matter most.
#
# Measured consequence, after linking: on series below this threshold a change
# in source composition predicts a >5% move 1.37% of the time, *below* the 2.88%
# base rate for days with no composition change — the artefact is gone. On
# series above it the rate is 24.5%, so that is where the residual lives, and
# `source_offsets.ratio_cv_pct` is how a reader identifies it.
WEAK_LINK_CV_PCT = 5.0


@dataclass
class SourceOffset:
    """How to put one source onto the series' reference level."""

    source: str
    reference: str
    factor: float
    n_overlap: int
    ratio_cv_pct: float | None = None
    ratio_drift_pct: float | None = None
    excluded_reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.excluded_reason is None


def _ratio_stats(ratios: list[float]) -> tuple[float, float | None, float | None]:
    """Median ratio, its coefficient of variation, and its drift across the span.

    The median resists a single mistyped price in a way the mean does not, which
    matters because one bad ratio would shift every rebased price in the series.

    Drift compares the first and last third: it is the diagnostic for the
    constant-factor assumption itself, reported rather than corrected because a
    time-varying factor would also absorb genuine divergence between markets.
    """
    median = statistics.median(ratios)
    cv = (statistics.stdev(ratios) / median * 100) if len(ratios) > 1 and median else None

    drift: float | None = None
    third = len(ratios) // 3
    if third >= 2:
        first = statistics.median(ratios[:third])
        last = statistics.median(ratios[-third:])
        drift = (last / first - 1) * 100 if first else None
    return median, cv, drift


def compute_offsets(by_day: dict[date, list[tuple[str, float]]]) -> dict[str, SourceOffset]:
    """Link every source in a series onto the best-covered one.

    Pure function over the series' observations, so the linking rule is testable
    without a database. The reference is whichever source reported most often —
    ties broken by name so a re-run cannot silently pick a different basis and
    shift every price in the series.
    """
    days_by_source: dict[str, int] = {}
    for observed in by_day.values():
        for source, _ in observed:
            days_by_source[source] = days_by_source.get(source, 0) + 1
    if not days_by_source:
        return {}

    reference = min(days_by_source, key=lambda s: (-days_by_source[s], s))

    # Ratios in date order, because drift is measured along that order.
    ratios: dict[str, list[float]] = {}
    for day in sorted(by_day):
        prices = dict(by_day[day])
        base = prices.get(reference)
        if base is None:
            continue
        for source, price in prices.items():
            if source == reference or price <= 0:
                continue
            ratios.setdefault(source, []).append(base / price)

    offsets = {
        reference: SourceOffset(
            source=reference,
            reference=reference,
            factor=1.0,
            n_overlap=days_by_source[reference],
        )
    }
    for source in days_by_source:
        if source == reference:
            continue
        overlap = ratios.get(source, [])
        if len(overlap) < MIN_LINK_OVERLAP_DAYS:
            offsets[source] = SourceOffset(
                source=source,
                reference=reference,
                factor=1.0,
                n_overlap=len(overlap),
                excluded_reason=(
                    f"only {len(overlap)} day(s) overlap with {reference}, "
                    f"below the {MIN_LINK_OVERLAP_DAYS} needed to link them; "
                    f"this source is on an unknown basis and is excluded from the level"
                ),
            )
            continue
        factor, cv, drift = _ratio_stats(overlap)
        offsets[source] = SourceOffset(
            source=source,
            reference=reference,
            factor=factor,
            n_overlap=len(overlap),
            ratio_cv_pct=cv,
            ratio_drift_pct=drift,
        )
    return offsets


@dataclass
class SeriesPoint:
    obs_date: date
    price_median: float | None
    price_min: float | None
    price_max: float | None
    n_sources: int
    spread_pct: float | None
    is_imputed: bool
    imputation_method: str | None


@dataclass
class PreprocessReport:
    series_built: int = 0
    rows_written: int = 0
    rows_real: int = 0
    rows_imputed: int = 0
    rows_null: int = 0
    suspicious: list[dict[str, object]] = field(default_factory=list)
    offsets: list[dict[str, Any]] = field(default_factory=list)

    @property
    def excluded_sources(self) -> list[dict[str, Any]]:
        return [o for o in self.offsets if o.get("excluded_reason")]

    @property
    def linked_sources(self) -> list[dict[str, Any]]:
        """Non-reference sources that were actually rebased."""
        return [
            o
            for o in self.offsets
            if not o.get("excluded_reason") and o.get("source") != o.get("reference")
        ]

    @property
    def weak_links(self) -> list[dict[str, Any]]:
        """Links a single factor describes poorly. Where the residual artefact lives."""
        return [o for o in self.linked_sources if (o.get("ratio_cv_pct") or 0) >= WEAK_LINK_CV_PCT]

    @property
    def completeness_pct(self) -> float:
        if not self.rows_written:
            return 0.0
        return (self.rows_real + self.rows_imputed) / self.rows_written * 100

    @property
    def imputation_pct(self) -> float:
        if not self.rows_written:
            return 0.0
        return self.rows_imputed / self.rows_written * 100


def _reconcile_day(prices: list[float]) -> tuple[float, float, float, int, float | None]:
    """Collapse one day's per-source prices into median, min, max, n, spread."""
    median = statistics.median(prices)
    low, high = min(prices), max(prices)
    spread = ((high - low) / median * 100) if median else None
    return median, low, high, len(prices), spread


def _interpolate(points: dict[date, SeriesPoint], start: date, end: date) -> None:
    """Fill NULL runs of at most MAX_INTERPOLATION_GAP_DAYS, in place.

    Linear in price. Over a gap of three days or fewer the difference between
    interpolating price and interpolating log price is far below the precision
    of the underlying survey, and a linear fill is the easier claim to defend.
    """
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    run_start: int | None = None
    for i, day in enumerate(days):
        missing = points[day].price_median is None
        if missing and run_start is None:
            run_start = i
        elif not missing and run_start is not None:
            _fill_run(points, days, run_start, i)
            run_start = None
    # A gap running to the end of the series has no right-hand anchor, so it is
    # left NULL: extrapolation is not interpolation.


def _fill_run(
    points: dict[date, SeriesPoint], days: list[date], gap_start: int, gap_end: int
) -> None:
    """Fill days[gap_start:gap_end] if the run is short enough and bounded."""
    length = gap_end - gap_start
    if length > MAX_INTERPOLATION_GAP_DAYS or gap_start == 0:
        return  # too long, or no left-hand anchor

    before = points[days[gap_start - 1]].price_median
    after = points[days[gap_end]].price_median
    if before is None or after is None:
        return

    step = (after - before) / (length + 1)
    for offset in range(length):
        point = points[days[gap_start + offset]]
        point.price_median = round(before + step * (offset + 1), 2)
        point.is_imputed = True
        point.imputation_method = f"linear_{length}d"


def build_series(
    conn: Conn, commodity_id: int, region_id: int
) -> tuple[list[SeriesPoint], list[dict[str, object]], dict[str, SourceOffset]]:
    """Reconcile and gap-fill one commodity x region series.

    Returns the daily points, anything suspicious, and the offsets used — the
    last of these so the caller can persist them. A rebased price whose factor
    is not recorded is a number nobody can check.
    """
    rows = fetch_all(
        conn,
        """
        select o.obs_date, o.price_idr, s.slug as source
          from public.price_observations o
          join public.sources s on s.id = o.source_id
         where o.commodity_id = %s and o.region_id = %s
         order by o.obs_date
        """,
        (commodity_id, region_id),
    )
    if not rows:
        return [], [], {}

    by_day: dict[date, list[tuple[str, float]]] = {}
    for r in rows:
        by_day.setdefault(r["obs_date"], []).append((str(r["source"]), float(r["price_idr"])))

    offsets = compute_offsets(by_day)

    start, end = min(by_day), max(by_day)
    points: dict[date, SeriesPoint] = {}
    suspicious: list[dict[str, object]] = []

    day = start
    while day <= end:
        observed = by_day.get(day) or []
        # Rebase before reconciling. A source that could not be linked is
        # dropped rather than mixed in: its price is on an unknown basis, and
        # including it would reintroduce the very step this removes.
        rebased = [
            (source, price * offsets[source].factor)
            for source, price in observed
            if offsets[source].usable
        ]
        if rebased:
            prices = [p for _, p in rebased]
            median, low, high, n, spread = _reconcile_day(prices)
            points[day] = SeriesPoint(day, median, low, high, n, spread, False, None)
            if spread is not None and spread >= SUSPICIOUS_SPREAD_PCT:
                suspicious.append(
                    {
                        "obs_date": day,
                        "spread_pct": spread,
                        "sources": dict(rebased),
                    }
                )
        else:
            points[day] = SeriesPoint(day, None, None, None, 0, None, False, None)
        day += timedelta(days=1)

    _interpolate(points, start, end)
    return (
        [points[start + timedelta(days=i)] for i in range((end - start).days + 1)],
        suspicious,
        offsets,
    )


def _persist_offsets(
    conn: Conn,
    run: Run,
    commodity_id: int,
    region_id: int,
    offsets: dict[str, SourceOffset],
    source_ids: dict[str, int],
) -> None:
    if not offsets:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.source_offsets
                (run_id, commodity_id, region_id, source_id, reference_source_id,
                 factor, n_overlap, ratio_cv_pct, ratio_drift_pct, excluded_reason)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, commodity_id, region_id, source_id) do nothing
            """,
            [
                (
                    run.id,
                    commodity_id,
                    region_id,
                    source_ids[offset.source],
                    source_ids[offset.reference],
                    round(offset.factor, 6),
                    offset.n_overlap,
                    None if offset.ratio_cv_pct is None else round(offset.ratio_cv_pct, 4),
                    None if offset.ratio_drift_pct is None else round(offset.ratio_drift_pct, 4),
                    offset.excluded_reason,
                )
                for offset in offsets.values()
            ],
        )


def rebuild(conn: Conn, run: Run) -> PreprocessReport:
    """Rebuild `price_daily_unified` from `price_observations`.

    Idempotent by construction: the table is truncated and rewritten, so a
    re-run after more backfill lands simply produces the corrected series rather
    than layering partial results on top of each other.
    """
    report = PreprocessReport()

    pairs = fetch_all(
        conn,
        """
        select distinct o.commodity_id, o.region_id, c.slug as commodity, rg.slug as region
          from public.price_observations o
          join public.commodities c on c.id = o.commodity_id
          join public.regions rg on rg.id = o.region_id
         order by rg.slug, c.slug
        """,
    )

    with conn.cursor() as cur:
        cur.execute("truncate table public.price_daily_unified")

    source_ids = {
        str(r["slug"]): int(r["id"]) for r in fetch_all(conn, "select id, slug from public.sources")
    }

    for pair in pairs:
        series, suspicious, offsets = build_series(
            conn, int(pair["commodity_id"]), int(pair["region_id"])
        )
        if not series:
            continue
        report.series_built += 1
        _persist_offsets(
            conn, run, int(pair["commodity_id"]), int(pair["region_id"]), offsets, source_ids
        )
        report.offsets.extend(
            {**vars(offset), "commodity": pair["commodity"], "region": pair["region"]}
            for offset in offsets.values()
        )
        for offset in offsets.values():
            if not offset.usable:
                run.note(
                    f"{pair['commodity']}/{pair['region']}: {offset.source} excluded "
                    f"from the level — {offset.excluded_reason}"
                )

        for item in suspicious:
            item["commodity"] = pair["commodity"]
            item["region"] = pair["region"]
            report.suspicious.append(item)
            run.note(
                f"suspicious spread {item['spread_pct']:.0f}% for "
                f"{pair['commodity']}/{pair['region']} on {item['obs_date']}: {item['sources']}"
            )

        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.price_daily_unified
                    (commodity_id, region_id, obs_date, price_median, price_min, price_max,
                     n_sources, source_spread_pct, is_imputed, imputation_method)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        pair["commodity_id"],
                        pair["region_id"],
                        p.obs_date,
                        p.price_median,
                        p.price_min,
                        p.price_max,
                        p.n_sources,
                        p.spread_pct,
                        p.is_imputed,
                        p.imputation_method,
                    )
                    for p in series
                ],
            )

        report.rows_written += len(series)
        report.rows_real += sum(
            1 for p in series if p.price_median is not None and not p.is_imputed
        )
        report.rows_imputed += sum(1 for p in series if p.is_imputed)
        report.rows_null += sum(1 for p in series if p.price_median is None)

    conn.commit()
    run.note(
        f"rebuilt {report.series_built} series: {report.rows_real} observed, "
        f"{report.rows_imputed} imputed, {report.rows_null} left NULL"
    )
    return report


# ---------------------------------------------------------------------------
# Reporting for the M2 gate
# ---------------------------------------------------------------------------
def completeness_by_commodity(conn: Conn) -> list[dict[str, Any]]:
    return fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region,
               count(*) as days,
               count(*) filter (where u.price_median is not null and not u.is_imputed) as observed,
               count(*) filter (where u.is_imputed) as imputed,
               count(*) filter (where u.price_median is null) as missing,
               min(u.obs_date) as first_date, max(u.obs_date) as last_date,
               round(avg(u.n_sources)::numeric, 2) as avg_sources
          from public.price_daily_unified u
          join public.commodities c on c.id = u.commodity_id
          join public.regions rg on rg.id = u.region_id
         group by c.slug, rg.slug, c.sort_order
         order by rg.slug, c.sort_order
        """,
    )


def largest_disagreements(conn: Conn, limit: int = 10) -> list[dict[str, Any]]:
    """The widest cross-source spreads — the M2 gate's unit-bug check.

    Only days with more than one reporting source can disagree, so single-source
    days are excluded rather than appearing as a spread of zero.
    """
    return fetch_all(
        conn,
        """
        select c.slug as commodity, rg.slug as region, u.obs_date,
               u.price_median, u.price_min, u.price_max, u.n_sources, u.source_spread_pct
          from public.price_daily_unified u
          join public.commodities c on c.id = u.commodity_id
          join public.regions rg on rg.id = u.region_id
         where u.n_sources > 1 and u.source_spread_pct is not null
         order by u.source_spread_pct desc
         limit %s
        """,
        (limit,),
    )


def write_data_quality_report(conn: Conn, path: Path | None = None) -> Path:
    """Generate docs/data-quality.md from the database.

    Generated rather than hand-written so it cannot drift from the data it
    describes, and so `make paper` in M9 can regenerate it from a clean clone.
    """
    target = path or (docs_dir() / "data-quality.md")
    rows = completeness_by_commodity(conn)
    spreads = largest_disagreements(conn, 15)

    totals = fetch_all(
        conn,
        """
        select count(*) as days,
               count(*) filter (where price_median is not null and not is_imputed) as observed,
               count(*) filter (where is_imputed) as imputed,
               count(*) filter (where price_median is null) as missing,
               min(obs_date) as first_date, max(obs_date) as last_date
          from public.price_daily_unified
        """,
    )[0]

    per_source = fetch_all(
        conn,
        """
        select s.slug as source, count(*) as rows_n,
               min(o.obs_date) as first_date, max(o.obs_date) as last_date
          from public.price_observations o
          join public.sources s on s.id = o.source_id
         group by s.slug order by s.slug
        """,
    )

    days = int(totals["days"]) or 1
    lines: list[str] = [
        "# Data quality report",
        "",
        "**Generated** by `siap preprocess --report`. Do not edit by hand — it is",
        "rebuilt from `price_daily_unified` and will be overwritten.",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, covering "
        f"{totals['first_date']} to {totals['last_date']}.",
        "",
        "## Overall",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| daily rows | {int(totals['days']):,} |",
        f"| observed | {int(totals['observed']):,} ({int(totals['observed']) / days * 100:.1f}%) |",
        f"| imputed | {int(totals['imputed']):,} ({int(totals['imputed']) / days * 100:.1f}%) |",
        f"| still missing | {int(totals['missing']):,} "
        f"({int(totals['missing']) / days * 100:.1f}%) |",
        "",
        "Imputation is linear and capped at three consecutive days. Longer gaps",
        "stay NULL. Every imputed row is flagged `is_imputed` and is excluded from",
        "ground-truth evaluation in M7.",
        "",
        "## Contributing sources",
        "",
        "| source | observations | first | last |",
        "|---|---:|---|---|",
    ]
    lines += [
        f"| `{r['source']}` | {int(r['rows_n']):,} | {r['first_date']} | {r['last_date']} |"
        for r in per_source
    ]

    lines += [
        "",
        "## Completeness per commodity x region",
        "",
        "| region | commodity | days | observed | imputed | missing | avg sources | complete |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        n = int(r["days"]) or 1
        filled = int(r["observed"]) + int(r["imputed"])
        lines.append(
            f"| {r['region']} | {r['commodity']} | {n:,} | {int(r['observed']):,} | "
            f"{int(r['imputed']):,} | {int(r['missing']):,} | {float(r['avg_sources']):.2f} | "
            f"{filled / n * 100:.1f}% |"
        )

    lines += [
        "",
        "## Largest cross-source disagreements",
        "",
        "A spread of a factor of ten is a unit-conversion bug, not a market. These",
        "are the widest observed, for inspection at the M2 gate.",
        "",
        "| region | commodity | date | min | max | sources | spread |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {r['region']} | {r['commodity']} | {r['obs_date']} | "
        f"{float(r['price_min']):,.0f} | {float(r['price_max']):,.0f} | "
        f"{int(r['n_sources'])} | {float(r['source_spread_pct']):.1f}% |"
        for r in spreads
    ]
    lines.append("")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def sources_for_day(
    conn: Conn, commodity: str, region: str, obs_date: date
) -> list[dict[str, Any]]:
    """Per-source prices behind one unified row, for inspecting a disagreement."""
    return fetch_all(
        conn,
        """
        select s.slug as source, o.price_idr, o.raw_unit, o.unit_factor
          from public.price_observations o
          join public.sources s on s.id = o.source_id
          join public.commodities c on c.id = o.commodity_id
          join public.regions rg on rg.id = o.region_id
         where c.slug = %s and rg.slug = %s and o.obs_date = %s
         order by o.price_idr
        """,
        (commodity, region, obs_date),
    )
