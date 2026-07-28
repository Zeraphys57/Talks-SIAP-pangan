"""`siap` command line interface.

Commands are kept thin: they resolve settings, call a module, and format output.
All logic lives in the modules so it stays testable without a subprocess.

Output is deliberately ASCII-only. Windows consoles default to cp1252, and a
gate checklist that raises UnicodeEncodeError before printing its result is a
gate that cannot be verified.
"""

from __future__ import annotations

import sys
from datetime import date, datetime

import click

from . import __version__
from .config import ConfigError, load_reference
from .db import DatabaseError, connect, server_version
from .doctor import run_all
from .migrate import MigrationError, apply_all, status
from .paths import repo_root
from .seed import seed as run_seed
from .settings import MissingSetting, database_url, redact_dsn

OK = "  ok  "
BAD = " FAIL "


def _fatal(message: str) -> None:
    click.echo(click.style(f"\n{message}\n", fg="red"), err=True)
    sys.exit(1)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="siap")
def cli() -> None:
    """SIAP-PANGAN analysis engine.

    Descriptive and diagnostic only: this system detects anomalies that have
    already happened. It does not forecast prices.
    """


# ---------------------------------------------------------------------------
@cli.command("config")
def config_cmd() -> None:
    """Validate engine/config/*.yaml and print a summary."""
    try:
        ref = load_reference()
    except ConfigError as exc:
        _fatal(f"configuration is invalid:\n{exc}")
        return

    click.echo(f"repo root : {repo_root()}")
    click.echo(f"commodities: {len(ref.commodities)}")
    for c in sorted(ref.commodities, key=lambda x: x.sort_order):
        aliased = len(c.source_aliases)
        click.echo(
            f"  {c.slug:<24} {c.display_name:<24} per {c.canonical_unit:<6} "
            f"IDR {c.plausible_price.min:>9,.0f}-{c.plausible_price.max:<9,.0f} "
            f"{aliased} source alias set(s)"
        )
    click.echo(f"regions: {len(ref.regions)}")
    for r in ref.regions:
        parent = f" <- {r.parent_slug}" if r.parent_slug else ""
        click.echo(f"  {r.slug:<20} {r.display_name:<20} {r.level}{parent}")
    click.echo(f"sources: {len(ref.sources)}")
    for s in ref.sources:
        click.echo(f"  {s.slug:<14} {s.cadence:<7} {', '.join(s.regions):<52} {s.base_url}")

    index = ref.alias_index()
    click.echo(f"\nalias index: {len(index)} (source, name) pairs resolve to a commodity")
    click.echo(
        f"conduct    : >={ref.conduct.min_delay_seconds}s delay, "
        f"<={ref.conduct.max_concurrent_per_host} concurrent/host, "
        f"robots.txt respected={ref.conduct.respect_robots_txt}"
    )


# ---------------------------------------------------------------------------
@cli.command("migrate")
@click.option(
    "--status", "show_status", is_flag=True, help="Show applied/pending without applying."
)
@click.option("--dry-run", is_flag=True, help="List what would be applied, then exit.")
def migrate_cmd(show_status: bool, dry_run: bool) -> None:
    """Apply supabase/migrations/*.sql in order."""
    try:
        with connect() as conn:
            click.echo(f"database: {redact_dsn(database_url())}")
            click.echo(f"server  : {server_version(conn).split(' on ')[0]}\n")

            if show_status:
                for migration, applied in status(conn):
                    marker = "applied" if applied else "PENDING"
                    click.echo(f"  [{marker:>7}] {migration.filename}  {migration.checksum[:12]}")
                return

            results = apply_all(conn, dry_run=dry_run)
            if not results:
                click.echo("  nothing to apply; database is up to date")
                return
            for result in results:
                verb = "would apply" if dry_run else "applied"
                timing = "" if dry_run else f"  ({result.execution_ms} ms)"
                click.echo(f"  {verb} {result.migration.filename}{timing}")
            click.echo(f"\n{len(results)} migration(s) {'pending' if dry_run else 'applied'}")
    except (MissingSetting, DatabaseError, MigrationError) as exc:
        _fatal(str(exc))


# ---------------------------------------------------------------------------
@cli.command("seed")
def seed_cmd() -> None:
    """Load reference data from engine/config/*.yaml into the database."""
    try:
        load_reference()  # fail on bad config before touching the database
        with connect() as conn:
            report = run_seed(conn)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    for table in ("regions", "commodities", "sources"):
        click.echo(
            f"  {table:<14} {report.inserted.get(table, 0):>3} inserted, "
            f"{report.updated.get(table, 0):>3} updated"
        )
    click.echo(f"  {'source_regions':<14} {report.coverage_links:>3} coverage link(s) synced")

    if report.has_orphans:
        click.echo(
            click.style(
                "\nRows present in the database but absent from YAML "
                "(not deleted; removal needs a migration):",
                fg="yellow",
            )
        )
        for table, slugs in report.orphans.items():
            if slugs:
                click.echo(f"  {table}: {', '.join(slugs)}")


# ---------------------------------------------------------------------------
@cli.command("doctor")
def doctor_cmd() -> None:
    """Verify schema completeness, RLS posture and seeded reference data."""
    try:
        with connect() as conn:
            click.echo(f"database: {redact_dsn(database_url())}\n")
            report = run_all(conn)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    for check in report.checks:
        marker = click.style(OK, fg="green") if check.ok else click.style(BAD, fg="red")
        click.echo(f"[{marker}] {check.name}")
        click.echo(f"         {check.detail}")

    click.echo()
    if report.ok:
        click.echo(click.style(f"{len(report.checks)} check(s) passed.", fg="green"))
    else:
        click.echo(
            click.style(
                f"{len(report.failures)} of {len(report.checks)} check(s) FAILED.", fg="red"
            )
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
def _print_day_report(report: object) -> None:
    from .ingest import DayReport

    assert isinstance(report, DayReport)
    marker = click.style(OK, fg="green") if report.ok else click.style(BAD, fg="yellow")
    click.echo(
        f"[{marker}] {report.source_slug:<22} {report.obs_date}  "
        f"raw={report.raw_rows:<5} stored={report.persisted}"
    )
    if report.error:
        click.echo(click.style(f"         error: {report.error}", fg="red"))
    for why in report.rejected[:10]:
        click.echo(click.style(f"         rejected: {why}", fg="yellow"))
    for region_slug, absent in report.missing.items():
        click.echo(click.style(f"         MISSING in {region_slug}: {sorted(absent)}", fg="yellow"))
    if report.ignored_names:
        preview = sorted(report.ignored_names)[:6]
        click.echo(
            f"         ignored {len(report.ignored_names)} untracked name(s), e.g. {preview}"
        )


@cli.command("ingest")
@click.option(
    "--source", "sources", multiple=True, help="Source slug; repeatable. Default: all active."
)
@click.option(
    "--date", "obs_date", type=click.DateTime(formats=["%Y-%m-%d"]), help="Default: today."
)
def ingest_cmd(sources: tuple[str, ...], obs_date: datetime | None) -> None:
    """Fetch one day from the active sources and store observations."""
    from .ingest import ingest_daily

    target = obs_date.date() if obs_date is not None else date.today()
    try:
        with connect() as conn:
            reports = ingest_daily(conn, list(sources) or None, target)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return
    for report in reports:
        _print_day_report(report)


@cli.command("backfill")
@click.option("--source", required=True, help="Source slug to backfill.")
@click.option("--start", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--end", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--no-skip-existing", is_flag=True, help="Re-fetch dates that already have data.")
def backfill_cmd(source: str, start: datetime, end: datetime, no_skip_existing: bool) -> None:
    """Backfill a source over a date range. Resumable; safe to interrupt."""
    from .ingest import ingest_backfill

    try:
        with connect() as conn:
            reports = ingest_backfill(
                conn,
                source,
                start.date(),
                end.date(),
                skip_existing=not no_skip_existing,
            )
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return
    for report in reports[:40]:
        _print_day_report(report)
    total = sum(r.persisted for r in reports)
    click.echo(f"\n{len(reports)} day(s) processed, {total} observation(s) stored")


@cli.command("trends")
@click.option(
    "--timeframe",
    default="today 5-y",
    show_default=True,
    help="pytrends timeframe string, e.g. 'today 5-y' or '2023-07-29 2026-07-29'.",
)
def trends_cmd(timeframe: str) -> None:
    """Collect the Google Trends demand signal into demand_signals.

    Best effort by design: pytrends wraps an undocumented, rate-limited
    endpoint. Failures are recorded and the fusion D term degrades to 0 rather
    than the run failing.
    """
    from .runs import start_run
    from .scrapers.trends import TrendsCollector, TrendsReport

    report = TrendsReport()
    try:
        with connect() as conn:
            run = start_run(conn, "trends", params={"timeframe": timeframe})
            status = "failed"
            try:
                report = TrendsCollector(conn, run).collect(timeframe)
                status = "success" if report.ok else "partial"
            finally:
                run.finish(status)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo(f"  requested : {report.requested}")
    click.echo(f"  stored    : {report.stored} weekly point(s)")
    if report.failures:
        click.echo(click.style(f"  failures  : {len(report.failures)}", fg="yellow"))
        for why in report.failures[:10]:
            click.echo(f"      {why}")


@cli.command("coverage")
@click.option("--samples", default=5, show_default=True, help="Random observations to print.")
@click.option("--seed", default=None, type=int, help="Seed the sample draw for reproducibility.")
@click.option("--detail/--no-detail", default=False, help="Per commodity x region breakdown.")
def coverage_cmd(samples: int, seed: int | None, detail: bool) -> None:
    """Coverage table and provenance samples — the M1 stop-gate evidence."""
    from .coverage import (
        coverage_by_source,
        coverage_detail,
        gaps,
        random_samples,
        weeks_covered,
    )

    try:
        with connect() as conn:
            by_source = coverage_by_source(conn)
            detail_rows = coverage_detail(conn) if detail else []
            weeks = weeks_covered(conn)
            picks = random_samples(conn, samples, seed)
            failures = gaps(conn)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo("=" * 96)
    click.echo("COVERAGE BY SOURCE")
    click.echo("=" * 96)
    click.echo(f"  {'source':<14}{'rows':>9}{'days':>7}{'com':>5}{'reg':>5}   first        last")
    for r in by_source:
        click.echo(
            f"  {r['source']!s:<14}{int(r['n_rows']):>9,}{int(r['distinct_days']):>7}"
            f"{int(r['n_commodities']):>5}{int(r['n_regions']):>5}   "
            f"{r['first_date']}   {r['last_date']}"
        )
    if not by_source:
        click.echo("  (no observations yet)")

    click.echo()
    click.echo("=" * 96)
    click.echo("WEEKS COVERED PER COMMODITY x REGION  (M5 STL needs >= 104)")
    click.echo("=" * 96)
    for r in weeks:
        n_weeks = int(r["n_weeks"])
        mark = "ok " if n_weeks >= 104 else "SHORT"
        colour = "green" if n_weeks >= 104 else "yellow"
        click.echo(
            f"  [{click.style(mark, fg=colour)}] {r['region']!s:<17}{r['commodity']!s:<24}"
            f"{n_weeks:>5} wk   {r['first_date']} .. {r['last_date']}"
        )

    if detail:
        click.echo()
        click.echo("=" * 96)
        click.echo("COVERAGE DETAIL  (source x commodity x region)")
        click.echo("=" * 96)
        for row in detail_rows:
            click.echo(
                f"  {row.source:<14}{row.region:<17}{row.commodity:<24}"
                f"{row.n_rows:>6} rows  {row.first_date} .. {row.last_date}"
                f"  missing {row.missing_pct:5.1f}%"
            )

    click.echo()
    click.echo("=" * 96)
    click.echo(f"RANDOM SAMPLES  ({len(picks)}) — OPEN THESE URLS AND CHECK THE NUMBERS")
    click.echo("=" * 96)
    for i, p in enumerate(picks, start=1):
        click.echo(f"\n  [{i}] {p['source']} / {p['region']} / {p['commodity']}  {p['obs_date']}")
        click.echo(
            f"      price          : Rp {float(p['price_idr']):,.2f} per {p['canonical_unit']}"
            f"   (raw_unit={p['raw_unit']}, factor={p['unit_factor']})"
        )
        click.echo(f"      url            : {p['url']}")
        click.echo(f"      fetched_at     : {p['fetched_at']}")
        click.echo(f"      http_status    : {p['http_status']}")
        click.echo(f"      parser_version : {p['parser_version']}")

    click.echo()
    click.echo("=" * 96)
    click.echo(f"RECORDED FETCH FAILURES  (most recent {len(failures)})")
    click.echo("=" * 96)
    for f in failures:
        click.echo(
            f"  {f['attempted_at']:%Y-%m-%d %H:%M}  {f['source']!s:<14}"
            f"{f['error_class']!s:<20} {str(f['detail'])[:70]}"
        )
    if not failures:
        click.echo("  (none)")


if __name__ == "__main__":  # pragma: no cover
    cli()
