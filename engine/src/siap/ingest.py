"""Ingestion orchestration: fetch, normalize, persist, report.

Everything here runs inside an `analysis_runs` row, so a day's data can always
be traced to the code and configuration that produced it. Nothing is ever
invented: a source that fails leaves a `fetch_failures` row and a gap, and a
source that renames a commodity produces a loud "expected but missing" report
rather than a quietly shorter series.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import load_reference
from .db import Conn
from .normalize import Normalizer
from .runs import Run, start_run
from .scrapers.base import BaseScraper, FetchError, PoliteClient
from .scrapers.jogja import JogjaScraper
from .scrapers.panelharga import PanelhargaScraper
from .scrapers.pihps import PihpsScraper
from .scrapers.siskaperbapo import SiskaperbapoScraper
from .scrapers.sp2kp import Sp2kpScraper
from .settings import contact_email

log = logging.getLogger(__name__)

# Scrapers implemented so far. Sources present in sources.yaml but absent here
# are reported as not-yet-implemented rather than silently skipped.
SCRAPERS: dict[str, type[BaseScraper]] = {
    "sp2kp": Sp2kpScraper,
    "siskaperbapo": SiskaperbapoScraper,
    "pihps": PihpsScraper,
    "jogja": JogjaScraper,
    # Disabled in sources.yaml (upstream outage). Present so that an explicit
    # run still records a fetch_failures row rather than reporting "no scraper".
    "panelharga": PanelhargaScraper,
}


@dataclass
class DayReport:
    source_slug: str
    obs_date: date
    raw_rows: int = 0
    persisted: int = 0
    rejected: list[str] = field(default_factory=list)
    ignored_names: set[str] = field(default_factory=set)
    missing: dict[str, set[str]] = field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.rejected and not self.missing


def ingest_day(
    conn: Conn,
    client: PoliteClient,
    run: Run,
    source_slug: str,
    obs_date: date,
) -> DayReport:
    """Ingest one source for one date."""
    report = DayReport(source_slug=source_slug, obs_date=obs_date)
    scraper_cls = SCRAPERS.get(source_slug)
    if scraper_cls is None:
        report.error = f"no scraper implemented for source {source_slug!r}"
        return report

    scraper = scraper_cls(conn, client, run)
    normalizer = Normalizer(conn)

    try:
        raws = scraper.fetch_day(obs_date)
    except FetchError as exc:
        report.error = f"{exc.error_class}: {exc}"
        run.note(f"{source_slug} {obs_date}: {report.error}")
        return report
    except Exception as exc:
        # A parsing bug or an unexpected payload in one source must not abort
        # the whole daily run — the other sources still have data to collect.
        # The failure is recorded so the resulting gap stays explainable.
        report.error = f"{type(exc).__name__}: {exc}"
        run.note(f"{source_slug} {obs_date}: {report.error}")
        try:
            scraper.record_failure(None, type(exc).__name__, str(exc))
        except Exception:  # pragma: no cover - never mask the original error
            log.exception("could not record failure for %s", source_slug)
        return report

    report.raw_rows = len(raws)

    expected = {c.slug for c in load_reference().commodities if source_slug in c.source_aliases}
    result = normalizer.normalize_batch(raws, expect_commodities=expected)

    report.persisted = normalizer.persist(result.accepted)
    report.rejected = [
        f"{raw.commodity_name_raw} @ {raw.region_slug}: {why}" for raw, why in result.rejected
    ]
    report.ignored_names = result.ignored_names
    report.missing = result.missing_commodities

    for why in report.rejected:
        run.note(f"{source_slug} {obs_date}: REJECTED {why}")
    for region_slug, absent in report.missing.items():
        run.note(
            f"{source_slug} {obs_date}: expected but absent in {region_slug}: "
            f"{sorted(absent)} — the portal may have renamed them"
        )
    return report


def ingest_daily(
    conn: Conn,
    source_slugs: list[str] | None = None,
    obs_date: date | None = None,
) -> list[DayReport]:
    """Daily incremental run across the active sources."""
    reference = load_reference()
    target = obs_date or date.today()
    slugs = source_slugs or [s.slug for s in reference.sources if s.is_active and s.is_price_source]

    run = start_run(
        conn,
        "ingest",
        params={"date": target.isoformat(), "sources": slugs},
    )
    reports: list[DayReport] = []
    try:
        with PoliteClient(reference.conduct, contact_email()) as client:
            for slug in slugs:
                reports.append(ingest_day(conn, client, run, slug, target))
    finally:
        failed = [r for r in reports if r.error]
        status = (
            "failed"
            if failed and len(failed) == len(reports)
            else ("partial" if failed or any(not r.ok for r in reports) else "success")
        )
        run.finish(status)
    return reports


def ingest_backfill(
    conn: Conn,
    source_slug: str,
    start: date,
    end: date,
    *,
    skip_existing: bool = True,
) -> list[DayReport]:
    """Historical backfill, day by day, resumable.

    `skip_existing` makes the backfill restartable: a run interrupted after four
    hours resumes where it stopped instead of re-fetching everything. It skips a
    date only when observations for that source and date already exist.
    """
    reference = load_reference()
    run = start_run(
        conn,
        "backfill",
        params={
            "source": source_slug,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "skip_existing": skip_existing,
        },
    )

    reports: list[DayReport] = []
    try:
        with PoliteClient(reference.conduct, contact_email()) as client:
            scraper_cls = SCRAPERS.get(source_slug)
            if scraper_cls is None:
                run.note(f"no scraper implemented for {source_slug}")
                return reports

            scraper = scraper_cls(conn, client, run)
            normalizer = Normalizer(conn)

            # Sources whose API accepts a date range are backfilled in one shot.
            # PIHPS covers three years in three requests this way instead of
            # 1,095 — the difference between seconds and hours of polite waiting.
            if hasattr(scraper, "fetch_range"):
                for chunk_start, chunk_end in _chunks(start, end, scraper.range_chunk_days):
                    try:
                        raws = scraper.fetch_range(chunk_start, chunk_end)
                        result = normalizer.normalize_batch(raws)
                        persisted = normalizer.persist(result.accepted)
                        run.note(
                            f"{source_slug}: {chunk_start}..{chunk_end} -> {persisted} "
                            f"observation(s) from {len(raws)} raw point(s)"
                        )
                        reports.append(
                            DayReport(
                                source_slug=f"{source_slug}:range",
                                obs_date=chunk_end,
                                raw_rows=len(raws),
                                persisted=persisted,
                                rejected=[
                                    f"{r.commodity_name_raw}: {w}" for r, w in result.rejected[:10]
                                ],
                                ignored_names=result.ignored_names,
                            )
                        )
                    except FetchError as exc:
                        # One failed window must not abandon the rest of the
                        # backfill; the gap is recorded and the walk continues.
                        run.note(f"{source_slug}: {chunk_start}..{chunk_end} failed: {exc}")
                        reports.append(
                            DayReport(
                                source_slug=f"{source_slug}:range",
                                obs_date=chunk_end,
                                error=f"{exc.error_class}: {exc}",
                            )
                        )
                return reports

            # National history arrives as one range request per commodity, so it
            # is fetched once rather than per day.
            if hasattr(scraper, "fetch_national_range"):
                try:
                    national = scraper.fetch_national_range(start, end)
                    result = normalizer.normalize_batch(national)
                    persisted = normalizer.persist(result.accepted)
                    run.note(
                        f"{source_slug}: national range {start}..{end} -> "
                        f"{persisted} observation(s) from {len(national)} raw point(s)"
                    )
                    reports.append(
                        DayReport(
                            source_slug=f"{source_slug}:national-range",
                            obs_date=end,
                            raw_rows=len(national),
                            persisted=persisted,
                            rejected=[f"{r.commodity_name_raw}: {w}" for r, w in result.rejected],
                        )
                    )
                except FetchError as exc:
                    run.note(f"{source_slug}: national range failed: {exc}")

            existing = _dates_with_data(conn, source_slug) if skip_existing else set()

            current = start
            while current <= end:
                if current in existing:
                    current += timedelta(days=1)
                    continue
                reports.append(ingest_day(conn, client, run, source_slug, current))
                current += timedelta(days=1)
    finally:
        run.finish("partial" if any(not r.ok for r in reports) else "success")
    return reports


def _chunks(start: date, end: date, chunk_days: int | None) -> list[tuple[date, date]]:
    """Split [start, end] into inclusive windows of at most `chunk_days`."""
    if chunk_days is None or chunk_days <= 0:
        return [(start, end)]
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=chunk_days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def _dates_with_data(conn: Conn, source_slug: str) -> set[date]:
    from .db import fetch_all

    rows = fetch_all(
        conn,
        """
        select distinct o.obs_date
          from public.price_observations o
          join public.sources s on s.id = o.source_id
         where s.slug = %s and o.region_id <> (
               select id from public.regions where slug = 'nasional')
        """,
        (source_slug,),
    )
    return {r["obs_date"] for r in rows}
