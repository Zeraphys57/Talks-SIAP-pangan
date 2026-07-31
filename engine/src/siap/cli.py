"""`siap` command line interface.

Commands are kept thin: they resolve settings, call a module, and format output.
All logic lives in the modules so it stays testable without a subprocess.

Output is deliberately ASCII-only. Windows consoles default to cp1252, and a
gate checklist that raises UnicodeEncodeError before printing its result is a
gate that cannot be verified.
"""

from __future__ import annotations

import statistics
import sys
import textwrap
from datetime import date, datetime
from typing import Any

import click

from . import __version__
from .config import ConfigError, load_reference
from .db import DatabaseError, connect, fetch_all, fetch_value, server_version
from .doctor import run_all
from .migrate import MigrationError, apply_all, status
from .paths import repo_root
from .seed import seed as run_seed
from .settings import MissingSetting, database_url, redact_dsn

OK = "  ok  "
BAD = " FAIL "

# Two vocabularies, deliberately: the cluster zone keeps the colour words the
# proposal committed to, the fusion level uses escalation words that mean
# something read aloud. Keeping the maps separate is what stops one being
# rendered with the other's palette. `belum_dapat_dinilai` gets no colour at
# all — it is the absence of a judgement, not a quiet one.
ZONE_COLOUR = {"merah": "red", "kuning": "yellow", "hijau": "green"}
LEVEL_COLOUR: dict[str, str | None] = {
    "siaga": "red",
    "waspada": "yellow",
    "tenang": "green",
    "belum_dapat_dinilai": None,
}


def _fatal(message: str) -> None:
    click.echo(click.style(f"\n{message}\n", fg="red"), err=True)
    sys.exit(1)


def _wrap(text: str, width: int = 78) -> list[str]:
    """Wrap a note for the fixed-width gate output."""
    return textwrap.wrap(text, width=width) or [""]


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
@cli.command("lab-annotator")
@click.option("--email", help="Email of an existing Supabase Auth user.")
@click.option("--code", help="Pseudonymous annotator code, e.g. A1.")
def lab_annotator_cmd(email: str | None, code: str | None) -> None:
    """List annotators, or register an existing auth user as one.

    Accounts themselves are created by the coordinator in the Supabase
    dashboard; this only maps an existing user to a pseudonymous code. Passwords
    never pass through this tool.
    """
    try:
        with connect() as conn:
            if not email and not code:
                rows = fetch_all(
                    conn,
                    """
                    select la.annotator_code, la.display_name, u.email, la.created_at
                      from public.lab_annotators la
                      left join auth.users u on u.id = la.user_id
                     order by la.annotator_code
                    """,
                )
                if not rows:
                    click.echo(
                        "  no annotators registered.\n\n"
                        "  1. Supabase dashboard -> Authentication -> Users -> Add user\n"
                        "  2. siap lab-annotator --email <their email> --code A1\n"
                    )
                    return
                for r in rows:
                    who = str(r["email"] or "(user deleted)")
                    code_shown = str(r["annotator_code"])
                    click.echo(f"  {code_shown:<6} {who:<34} registered {r['created_at']:%Y-%m-%d}")
                return

            if not (email and code):
                _fatal("--email and --code must be given together")
                return

            user_id = fetch_value(conn, "select id from auth.users where email = %s", (email,))
            if user_id is None:
                _fatal(
                    f"no Supabase Auth user with email {email!r}. Create the account first "
                    f"(dashboard -> Authentication -> Users -> Add user), then re-run this."
                )
                return

            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into public.lab_annotators (user_id, annotator_code, display_name)
                    values (%s, %s, %s)
                    on conflict (user_id) do update set annotator_code = excluded.annotator_code
                    """,
                    (user_id, code, email.split("@")[0]),
                )
            conn.commit()
    except (MissingSetting, DatabaseError) as exc:
        _fatal(str(exc))
        return

    click.echo(f"  {email} is now annotator {code}")
    click.echo(
        "\n  Remind them: work alone, and do not discuss candidates with the other\n"
        "  annotator until both lists are finished. Kappa only means something if\n"
        "  the two judgements are independent."
    )


@cli.command("lab-check")
def lab_check_cmd() -> None:
    """Attack the /lab access model as an annotator, then roll back.

    Verifies from the client side what `doctor` verifies from the catalog: that
    one annotator cannot read the other's labels, write under their code, or
    tell which stratum a candidate came from.
    """
    from .labcheck import run as run_lab_check

    try:
        with connect() as conn:
            click.echo(f"database: {redact_dsn(database_url())}\n")
            report = run_lab_check(conn)
    except (MissingSetting, DatabaseError) as exc:
        _fatal(str(exc))
        return

    for attempt in report.attempts:
        marker = click.style(OK, fg="green") if attempt.ok else click.style(BAD, fg="red")
        click.echo(f"[{marker}] {attempt.name}")
        click.echo(f"         {attempt.detail}")

    click.echo()
    if report.ok:
        click.echo(
            click.style(
                f"{len(report.attempts)} attempt(s) behaved as required. "
                "Fixture rows were rolled back.",
                fg="green",
            )
        )
    else:
        click.echo(
            click.style(
                f"{len(report.failures)} of {len(report.attempts)} FAILED. "
                "Do not begin labelling: the two label sets would not be independent.",
                fg="red",
            )
        )
        sys.exit(1)


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


@cli.command("runs")
@click.option("--limit", default=15, show_default=True, help="How many runs to list.")
@click.option(
    "--close-stale",
    type=float,
    default=None,
    metavar="HOURS",
    help="Mark runs still 'running' after HOURS as failed. Never marks them succeeded.",
)
def runs_cmd(limit: int, close_stale: float | None) -> None:
    """List analysis runs, and optionally reconcile abandoned ones.

    A process killed mid-run leaves its row at 'running' forever. Left alone
    those rows make "which runs actually completed?" unanswerable, which the
    reproducibility claim in M9 depends on.
    """
    from .runs import close_stale as close_stale_runs
    from .runs import list_runs

    try:
        with connect() as conn:
            if close_stale is not None:
                closed = close_stale_runs(conn, close_stale)
                if closed:
                    click.echo(
                        click.style(
                            f"  marked {len(closed)} abandoned run(s) as failed: {closed}",
                            fg="yellow",
                        )
                    )
                else:
                    click.echo("  no abandoned runs found")
                click.echo()
            rows = list_runs(conn, limit)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo(f"  {'id':>5}  {'type':<10}{'status':<10}{'started':<10}{'git':<10}params")
    for r in rows:
        colour = {
            "success": "green",
            "running": "cyan",
            "partial": "yellow",
            "failed": "red",
        }.get(str(r["status"]))
        status = click.style(f"{r['status']:<10}", fg=colour) if colour else f"{r['status']:<10}"
        sha = (str(r["git_sha"]) or "")[:8] if r["git_sha"] else "-"
        click.echo(
            f"  {int(r['id']):>5}  {r['run_type']:<10}{status}"
            f"{r['started_at']:%H:%M:%S}  {sha:<10}{str(r['params'])[:70]}"
        )


@cli.command("preprocess")
@click.option("--disagreements", default=10, show_default=True, help="Widest spreads to print.")
@click.option(
    "--report/--no-report",
    "write_report",
    default=True,
    help="Regenerate docs/data-quality.md.",
)
def preprocess_cmd(disagreements: int, write_report: bool) -> None:
    """Rebuild price_daily_unified from price_observations — the M2 gate output."""
    from .preprocess import (
        completeness_by_commodity,
        largest_disagreements,
        rebuild,
        write_data_quality_report,
    )
    from .runs import start_run

    try:
        with connect() as conn:
            run = start_run(conn, "preprocess", params={"max_gap_days": 3})
            status = "failed"
            try:
                report = rebuild(conn, run)
                status = "success"
            finally:
                run.finish(status)
            completeness = completeness_by_commodity(conn)
            spreads = largest_disagreements(conn, disagreements)
            report_path = write_data_quality_report(conn) if write_report else None
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo("=" * 96)
    click.echo("SOURCE LINKING — every source put on one level before reconciling")
    click.echo("=" * 96)
    linked = report.linked_sources
    if not linked:
        click.echo("  no series has more than one source; nothing to link")
    else:
        cvs = [o["ratio_cv_pct"] for o in linked if o["ratio_cv_pct"] is not None]
        drifts = [abs(o["ratio_drift_pct"]) for o in linked if o["ratio_drift_pct"] is not None]
        click.echo(
            f"  {len(linked)} source(s) rebased across "
            f"{len({(o['commodity'], o['region']) for o in linked})} series"
        )
        if cvs:
            click.echo(
                f"  residual after linking (ratio cv): median {statistics.median(cvs):.1f}%, "
                f"max {max(cvs):.1f}%"
            )
        if drifts:
            over = sum(1 for d in drifts if d > 5)
            click.echo(
                f"  factor drift first->last third:   median {statistics.median(drifts):.1f}%, "
                f"max {max(drifts):.1f}%  ({over} series above 5%)"
            )
        widest = sorted(linked, key=lambda o: -abs(o["factor"] - 1))[:5]
        click.echo("\n  largest corrections:")
        for o in widest:
            commodity, region = str(o["commodity"]), str(o["region"])
            click.echo(
                f"    {commodity:<24}{region:<15}"
                f"{o['source']} x{o['factor']:.4f} -> {o['reference']}"
                f"   (n={o['n_overlap']}, cv={o['ratio_cv_pct']:.1f}%)"
            )
        weak = report.weak_links
        if weak:
            click.echo(
                click.style(
                    f"\n  {len(weak)} link(s) with residual >= 5% — a single factor "
                    f"describes these poorly:",
                    fg="yellow",
                )
            )
            for o in sorted(weak, key=lambda x: -(x["ratio_cv_pct"] or 0)):
                commodity, region = str(o["commodity"]), str(o["region"])
                click.echo(
                    f"    {commodity:<24}{region:<15}"
                    f"{o['source']}/{o['reference']}  cv={o['ratio_cv_pct']:.1f}%"
                )
            click.echo(
                "    Kept, not dropped: this is real divergence between surveys of\n"
                "    different markets, and removing the second source would cost\n"
                "    corroboration on the most volatile commodities. See\n"
                "    source_offsets.ratio_cv_pct to identify affected days."
            )

    for o in report.excluded_sources:
        click.echo(
            click.style(
                f"  EXCLUDED {o['commodity']}/{o['region']}: {o['source']} — {o['excluded_reason']}",
                fg="yellow",
            )
        )

    click.echo()
    click.echo("=" * 96)
    click.echo("COMPLETENESS PER COMMODITY x REGION")
    click.echo("=" * 96)
    click.echo(
        f"  {'region':<17}{'commodity':<24}{'days':>6}{'obs':>7}{'imp':>6}{'null':>6}"
        f"{'src':>6}   complete"
    )
    for r in completeness:
        days = int(r["days"])
        filled = int(r["observed"]) + int(r["imputed"])
        pct = filled / days * 100 if days else 0.0
        colour = "green" if pct >= 95 else ("yellow" if pct >= 80 else "red")
        click.echo(
            f"  {r['region']!s:<17}{r['commodity']!s:<24}{days:>6}{int(r['observed']):>7}"
            f"{int(r['imputed']):>6}{int(r['missing']):>6}{float(r['avg_sources']):>6.2f}   "
            + click.style(f"{pct:5.1f}%", fg=colour)
        )

    click.echo()
    click.echo("=" * 96)
    click.echo(
        f"OVERALL: {report.completeness_pct:.1f}% complete, "
        f"{report.imputation_pct:.1f}% imputed, {report.rows_written:,} daily rows"
    )
    click.echo("=" * 96)

    click.echo()
    click.echo("=" * 96)
    click.echo(f"{len(spreads)} LARGEST CROSS-SOURCE DISAGREEMENTS")
    click.echo("  a 10x spread is a unit bug, not a market — check these by eye")
    click.echo("=" * 96)
    click.echo(
        f"  {'region':<17}{'commodity':<24}{'date':<12}{'min':>11}{'max':>11}{'n':>3}  spread"
    )
    for r in spreads:
        spread = float(r["source_spread_pct"])
        spread_colour = "red" if spread >= 100 else ("yellow" if spread >= 30 else "")
        text = f"{spread:6.1f}%"
        click.echo(
            f"  {r['region']!s:<17}{r['commodity']!s:<24}{r['obs_date']!s:<12}"
            f"{float(r['price_min']):>11,.0f}{float(r['price_max']):>11,.0f}"
            f"{int(r['n_sources']):>3}  "
            + (click.style(text, fg=spread_colour) if spread_colour else text)
        )
    if not spreads:
        click.echo("  (no day yet has more than one reporting source)")

    if report.suspicious:
        click.echo()
        click.echo(
            click.style(
                f"  {len(report.suspicious)} day(s) exceeded the 100% spread threshold "
                f"— see the run notes",
                fg="red",
            )
        )

    if report_path is not None:
        click.echo(f"\n  wrote {report_path}")


@cli.command("analyze")
@click.option("--top", default=10, show_default=True, help="Strongest flags to print.")
def analyze_cmd(top: int) -> None:
    """Run Z-Score and Isolation Forest over every series — the M3 gate output."""
    from .analyze import flag_counts, run_detectors, top_flagged

    try:
        with connect() as conn:
            report = run_detectors(conn)
            counts = flag_counts(conn, report.run_id)
            strongest = top_flagged(conn, report.run_id, top)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo(
        f"run #{report.run_id}: {len(report.series)} series, {report.rows_written:,} score rows\n"
    )

    click.echo("=" * 96)
    click.echo("FLAG COUNTS PER COMMODITY PER METHOD")
    click.echo("=" * 96)
    click.echo(f"  {'commodity':<24}{'method':<10}{'flagged':>9}{'scored':>9}{'total':>8}   rate")
    for r in counts:
        scored = int(r["scored"])
        flagged = int(r["flagged"])
        rate = flagged / scored * 100 if scored else 0.0
        click.echo(
            f"  {r['commodity']!s:<24}{r['method']!s:<10}{flagged:>9}{scored:>9}"
            f"{int(r['total']):>8}   {rate:5.2f}%"
        )

    click.echo()
    click.echo("=" * 96)
    click.echo(f"TOP {len(strongest)} FLAGGED DATES — do any match a price event you recall?")
    click.echo("=" * 96)
    for r in strongest:
        price = r["price_median"]
        prev = r["prev_price"]
        move = ""
        if price is not None and prev not in (None, 0):
            move = f"  {(float(price) / float(prev) - 1) * 100:+6.1f}% vs prev day"
        price_text = f"Rp {float(price):>10,.0f}" if price is not None else " " * 13
        click.echo(
            f"  {r['obs_date']!s}  {r['region']!s:<17}{r['commodity']!s:<24}"
            f"{r['method']!s:<9}{price_text}{move}"
        )

    if report.skipped:
        click.echo()
        click.echo(click.style(f"  {len(report.skipped)} series skipped or partial:", fg="yellow"))
        for s in report.skipped[:10]:
            click.echo(f"      {s.region}/{s.commodity}: {s.skipped}")


def _echo_within_commodity(pair: tuple[Any, Any]) -> None:
    """Print the two models side by side — the point is the comparison."""
    glob, within = pair

    click.echo("=" * 96)
    click.echo("SECONDARY ANALYSIS — FEATURES STANDARDISED WITHIN EACH COMMODITY")
    click.echo("=" * 96)
    click.echo(
        "  The global model answers 'which commodity-months are extreme against the whole\n"
        "  population'. This one removes the between-commodity level first, so what is left\n"
        "  is temporal: 'is this commodity unusual FOR ITSELF this month'.\n"
        "  Centroid units differ between the two and are NOT comparable.\n"
    )
    click.echo(f"  {'':<20}{'global':>12}{'within-commodity':>20}")
    click.echo(f"  {'k selected':<20}{glob.k_selected:>12}{within.k_selected:>20}")
    click.echo(f"  {'silhouette':<20}{glob.silhouette_avg:>12.4f}{within.silhouette_avg:>20.4f}")
    click.echo(f"  {'cells fitted':<20}{glob.n_samples:>12,}{within.n_samples:>20,}")

    for label, model in (("GLOBAL", glob), ("WITHIN-COMMODITY", within)):
        click.echo()
        click.echo(f"  {label} — commodity composition of each zone")
        assigned = model.assignments[model.assignments["zone"].notna()]
        for zone in ("merah", "kuning", "hijau"):
            sub = assigned[assigned["zone"] == zone]
            if sub.empty:
                continue
            top = sub["commodity"].value_counts().head(4)
            spread = ", ".join(f"{c} {100 * n / len(sub):.0f}%" for c, n in top.items())
            click.echo(
                f"    {zone:<7}{len(sub):>6} cells  "
                f"{sub['commodity'].nunique():>2}/12 commodities   {spread}"
            )

    click.echo()
    click.echo("  zone stability (share of consecutive month pairs that change zone)")
    for label, model in (("global", glob), ("within-commodity", within)):
        assigned = model.assignments[model.assignments["zone"].notna()]
        seq = assigned.sort_values(["commodity", "region", "period_month"]).copy()
        seq["prev"] = seq.groupby(["commodity", "region"])["zone"].shift()
        trans = seq.dropna(subset=["prev"])
        if trans.empty:
            continue
        flips = int((trans["zone"] != trans["prev"]).sum())
        click.echo(
            f"    {label:<20}{flips:>6} of {len(trans):>6}  ({100 * flips / len(trans):5.2f}%)"
        )


@cli.command("cluster")
@click.option(
    "--within-commodity",
    is_flag=True,
    help="Report the secondary variant (features standardised inside each commodity). "
    "Reports only; the persisted model is always the global one.",
)
def cluster_cmd(within_commodity: bool) -> None:
    """Fit the regime clustering — the M4 gate output."""
    from .cluster import (
        report_within_commodity,
        run_clustering,
        zone_counts_by_commodity,
        zone_table,
    )

    if within_commodity:
        try:
            with connect() as conn:
                _echo_within_commodity(report_within_commodity(conn))
        except (MissingSetting, DatabaseError, ConfigError, ValueError) as exc:
            _fatal(str(exc))
        return

    try:
        with connect() as conn:
            report = run_clustering(conn)
            if report.model is None:
                _fatal("no monthly cells met the minimum-days threshold; nothing to cluster")
                return
            zones = zone_table(conn, report.run_id)
            counts = zone_counts_by_commodity(conn, report.run_id)
    except (MissingSetting, DatabaseError, ConfigError, ValueError) as exc:
        _fatal(str(exc))
        return

    model = report.model
    click.echo(
        f"run #{report.run_id}: {report.cells:,} cells "
        f"(commodity x region x month), {report.assignments_written:,} assignments\n"
    )

    click.echo("=" * 96)
    click.echo("PROVENANCE GATE — excluded from the fit, kept in the table")
    click.echo("=" * 96)
    coverage = (model.n_samples / report.cells * 100) if report.cells else 0.0
    click.echo(
        f"  fitted {model.n_samples:,} of {report.cells:,} cells ({coverage:.1f}% coverage); "
        f"{model.n_gated:,} gated"
    )
    for reason, count in sorted(model.gate_reasons.items(), key=lambda kv: -kv[1]):
        click.echo(f"    {reason:<32}{count:>7,}")
    if not model.gate_reasons:
        click.echo("    (no cell was gated)")

    click.echo()
    click.echo("=" * 96)
    click.echo("K SEARCH — silhouette selects k, the elbow is recorded for the paper")
    click.echo("=" * 96)
    click.echo(f"  {'k':>3}{'inertia':>14}{'silhouette':>13}")
    for entry in model.k_search:
        mark = click.style("  <-- selected", fg="green") if entry.k == model.k_selected else ""
        click.echo(f"  {entry.k:>3}{entry.inertia:>14,.1f}{entry.silhouette:>13.4f}{mark}")
    click.echo(f"\n  selected k = {model.k_selected}  (silhouette {model.silhouette_avg:.4f})")
    if model.k_selected > 3:
        click.echo(
            click.style(
                "  k > 3, so middle clusters merge into kuning — k was not forced to 3",
                fg="yellow",
            )
        )

    click.echo()
    click.echo("=" * 96)
    click.echo("CENTROIDS (original units) AND ZONE MAPPING")
    click.echo("=" * 96)
    click.echo(f"  {'cluster':>8}{'volatility':>13}{'cum_change':>13}{'cells':>8}   zone")
    for cluster_id, centroid in sorted(model.centroids.items()):
        zone = model.zone_mapping[cluster_id]
        colour = ZONE_COLOUR[zone]
        click.echo(
            f"  {cluster_id:>8}{centroid['volatility']:>13.5f}"
            f"{centroid['cum_change'] * 100:>12.2f}%{centroid['n_cells']:>8}   "
            + click.style(zone, fg=colour)
        )

    click.echo()
    click.echo("=" * 96)
    click.echo("ZONE FREQUENCY PER COMMODITY — cabai/bawang should dominate merah")
    click.echo("=" * 96)
    click.echo(
        f"  {'commodity':<24}{'merah':>7}{'kuning':>8}{'hijau':>7}{'gated':>7}{'total':>7}"
        f"{'avg volatility':>16}"
    )
    for r in counts:
        total = int(r["total"]) or 1
        # Percentage of the cells that were actually zoned. Counting gated cells
        # in the denominator would let a commodity look calm because most of its
        # months could not be judged.
        zoned = total - int(r["gated"]) or 1
        merah_pct = int(r["merah"]) / zoned * 100
        merah_colour = "red" if merah_pct >= 25 else ("yellow" if merah_pct >= 10 else "")
        volatility = r["avg_volatility"]
        line = (
            f"  {r['commodity']!s:<24}{int(r['merah']):>7}{int(r['kuning']):>8}"
            f"{int(r['hijau']):>7}{int(r['gated']):>7}{total:>7}"
            f"{('n/a' if volatility is None else f'{float(volatility):.5f}'):>16}"
        )
        click.echo(click.style(line, fg=merah_colour) if merah_colour else line)

    click.echo()
    click.echo("=" * 96)
    click.echo(f"ZONES FOR THE MOST RECENT MONTH ({zones[0]['period_month'] if zones else '-'})")
    click.echo("=" * 96)
    for r in zones:
        # A gated cell has no zone; it still prints, because the whole point of
        # keeping the row was that its exclusion stays visible.
        zone = str(r["zone"]) if r["zone"] else "-gated-"
        colour = ZONE_COLOUR.get(zone)
        badge = click.style(zone.upper().ljust(7), fg=colour)
        vol = r["feat_volatility"]
        change = r["feat_cum_change"]
        click.echo(
            f"  {badge}{r['region']!s:<17}{r['commodity']!s:<24}"
            f"vol {('    n/a' if vol is None else f'{float(vol):7.5f}')}  "
            f"change {('    n/a' if change is None else f'{float(change) * 100:+7.2f}%')}"
            f"  {r['quality_reason'] or ''}"
        )


@cli.command("seasonal")
@click.option("--year", default=2026, show_default=True, help="Calendar year for week dates.")
def seasonal_cmd(year: int) -> None:
    """Run STL decomposition — the M5 gate output."""
    from .modules.stl import iso_week_dates
    from .seasonal import run_seasonal

    try:
        with connect() as conn:
            report = run_seasonal(conn)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo(
        f"run #{report.run_id}: {len(report.decomposed)} decomposed, "
        f"{len(report.skipped)} skipped, {report.rows_written:,} weekly rows\n"
    )

    click.echo("=" * 96)
    click.echo("COVERAGE AND 'PERIODE RAWAN NAIK' (top-decile seasonal weeks)")
    click.echo("=" * 96)

    for result in report.decomposed:
        spans = []
        for week in result.rawan_weeks:
            try:
                monday, sunday = iso_week_dates(week, year)
            except ValueError:
                continue
            spans.append(f"W{week:02d} ({monday:%d %b}-{sunday:%d %b})")
        click.echo(f"\n  {result.region}/{result.commodity}  —  {result.weeks} weeks")
        click.echo(f"      {', '.join(spans) if spans else '(none)'}")

    if report.skipped:
        click.echo()
        click.echo("=" * 96)
        click.echo(f"SKIPPED ({len(report.skipped)}) — coverage guard, not a failure")
        click.echo("=" * 96)
        for result in report.skipped:
            click.echo(
                click.style(f"  {result.region}/{result.commodity}: {result.skipped}", fg="yellow")
            )


@cli.command("fuse")
@click.option("--board", default=25, show_default=True, help="Rows of the alert board to print.")
def fuse_cmd(board: int) -> None:
    """Compute fusion alerts — the M6 gate output."""
    from .config import load_fusion
    from .fuse import alert_board, run_fusion, strongest_alert
    from .modules.fusion import explain

    try:
        cfg = load_fusion()
        with connect() as conn:
            report = run_fusion(conn, cfg)
            rows = alert_board(conn, report.run_id)
            worked = strongest_alert(conn, report.run_id)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo(
        f"run #{report.run_id} from anomaly run #{report.source_run_id}: "
        f"{report.rows_written:,} alerts  "
        + ", ".join(f"{k}={v:,}" for k, v in sorted(report.level_counts.items()))
    )
    if report.downgrades:
        click.echo(
            "  downgrades: " + ", ".join(f"{k}={v:,}" for k, v in sorted(report.downgrades.items()))
        )

    click.echo()
    click.echo("=" * 112)
    click.echo(f"ALERT BOARD — {rows[0]['obs_date'] if rows else '(none)'}")
    click.echo("=" * 112)
    click.echo(
        f"  {'level':<20}{'region':<17}{'commodity':<24}"
        f"{'F':>8}{'A':>8}{'M':>8}{'D':>8}{'C':>8}  both  src  reason"
    )
    for r in rows[:board]:
        comp = r["components"]
        level = str(r["level"])
        colour = LEVEL_COLOUR.get(level)

        def num(value: Any) -> str:
            """`n/a` rather than 0.0000 — an unscored date is not a calm one."""
            return "     n/a" if value is None else f"{float(value):>8.4f}"

        click.echo(
            f"  {click.style(level.ljust(20), fg=colour)}"
            f"{r['region']!s:<17}{r['commodity']!s:<24}"
            f"{num(r['fusion_score'])}{num(comp.get('A'))}{num(comp.get('M'))}"
            f"{num(comp.get('D'))}{num(comp.get('C'))}"
            f"{str(comp['both_flagged'])[:1]:>6}"
            f"{int(comp['n_sources_reporting']):>5}  {comp.get('reason', '')}"
        )

    if worked:
        comp = worked["components"]
        click.echo()
        click.echo("=" * 112)
        click.echo("WORKED EXAMPLE — check this arithmetic by hand")
        click.echo("=" * 112)
        click.echo(f"  {worked['region']} / {worked['commodity']} / {worked['obs_date']}")
        if worked["price_median"] is not None and worked["price_prev7"] is not None:
            now, before = float(worked["price_median"]), float(worked["price_prev7"])
            click.echo(
                f"    price  : Rp {before:,.0f} (7d ago) -> Rp {now:,.0f}"
                f"   = {(now / before - 1) * 100:+.2f}%"
            )
        click.echo(f"    zscore norm={comp.get('norm_zscore')}  flagged={comp['both_flagged']}")
        click.echo(f"    iforest norm={comp.get('norm_iforest')}")
        click.echo(
            f"    sources: {comp['n_sources_flagging']} flagging "
            f"of {comp['n_sources_reporting']} reporting"
        )
        click.echo(
            f"    demand : {'absent (Trends throttled)' if not comp.get('demand_available') else comp.get('demand_z52')}"
        )
        click.echo()
        from .modules.fusion import FusionResult

        click.echo(
            explain(
                FusionResult(
                    score=float(worked["fusion_score"]),
                    level=str(worked["level"]),
                    components=comp,
                    corroboration=worked["corroboration"],
                ),
                cfg,
            )
        )


@cli.command("gt-pool")
@click.option(
    "--refresh-context",
    is_flag=True,
    help="Rebuild the evidence blob of existing candidates. Membership is untouched.",
)
@click.option(
    "--redraw",
    is_flag=True,
    help="Discard and re-sample the pool. Refuses once any label exists.",
)
def gt_pool_cmd(refresh_context: bool, redraw: bool) -> None:
    """Generate the stratified ground-truth candidate pool (§7.1)."""
    from .config import load_analysis
    from .evaluate.groundtruth import clear_pool, generate_pool, labelling_progress, pool_summary
    from .evaluate.groundtruth import refresh_context as refresh_candidate_context
    from .fuse import latest_anomaly_run
    from .runs import start_run

    if refresh_context:
        try:
            with connect() as conn:
                updated = refresh_candidate_context(conn)
        except (MissingSetting, DatabaseError) as exc:
            _fatal(str(exc))
            return
        click.echo(f"  context rebuilt for {updated} candidate(s); pool membership unchanged")
        return

    try:
        cfg = load_analysis()
        with connect() as conn:
            anomaly_run = latest_anomaly_run(conn)
            if anomaly_run is None:
                _fatal("no completed anomaly run; run `siap analyze` first")
                return
            if redraw:
                removed = clear_pool(conn)
                click.echo(f"  discarded {removed} candidate(s); re-sampling\n")
            run = start_run(
                conn,
                "gt_pool",
                seed=cfg.seed,
                params={"evaluation": cfg.evaluation.model_dump(), "anomaly_run": anomaly_run},
            )
            status = "failed"
            try:
                report = generate_pool(conn, anomaly_run, cfg.evaluation, cfg.seed, run.id)
                run.note(
                    f"pool: {report.stratum_a} rule_flagged + {report.stratum_b} "
                    f"random_control = {report.total}; {report.written} written, "
                    f"{report.skipped_existing} already present"
                )
                status = "success"
            finally:
                run.finish(status)
            summary = pool_summary(conn)
            progress = labelling_progress(conn)
    except (MissingSetting, DatabaseError, ConfigError) as exc:
        _fatal(str(exc))
        return

    click.echo(
        f"run #{run.id}: {report.written} candidate(s) written "
        f"({report.skipped_existing} already present)\n"
    )
    click.echo("=" * 84)
    click.echo("CANDIDATE POOL")
    click.echo("=" * 84)
    for r in summary:
        click.echo(
            f"  {r['sampling_stratum']!s:<16}{int(r['n']):>6}   "
            f"{r['first_date']} .. {r['last_date']}"
        )
    total = sum(int(r["n"]) for r in summary)
    click.echo(f"  {'TOTAL':<16}{total:>6}")
    click.echo(
        "\n  Stratum B exists so recall is computable. Annotators see the\n"
        "  stratum-blind gt_labeling_queue view and cannot tell them apart."
    )

    click.echo()
    click.echo("=" * 84)
    click.echo("LABELLING PROGRESS")
    click.echo("=" * 84)
    if not progress:
        click.echo(
            click.style(
                "  No labels yet. Two annotators must label independently before\n"
                "  kappa, the ablation, or any M7 number can be computed.",
                fg="yellow",
            )
        )
    for r in progress:
        pool = int(r["pool"]) or 1
        done = int(r["labelled"])
        click.echo(
            f"  {r['annotator_code']!s:<10}{done:>5}/{pool}  ({done / pool * 100:5.1f}%)   "
            f"anomali={int(r['anomali'])} normal={int(r['normal'])} ragu={int(r['ragu'])}"
        )


@cli.command("ablate")
def ablate_cmd() -> None:
    """Parameter sensitivity for the paper (§7.5).

    Runs the sweeps that need no labels: k against silhouette, contamination
    against flag volume and overlap, and fusion weights against ranking
    stability. Per-setting precision and recall need adjudicated events and are
    refused until they exist.
    """
    from .config import load_analysis, load_fusion
    from .evaluate.ablation import nesting_note
    from .evaluate.ablation import run as run_ablation
    from .fuse import latest_anomaly_run
    from .runs import start_run

    try:
        cfg, fcfg = load_analysis(), load_fusion()
        with connect() as conn:
            anomaly_run = latest_anomaly_run(conn)
            if anomaly_run is None:
                _fatal("no completed anomaly run; run `siap analyze` first")
                return
            run = start_run(
                conn,
                "ablation",
                seed=cfg.seed,
                params={"anomaly_run": anomaly_run},
            )
            status = "failed"
            try:
                report = run_ablation(conn, anomaly_run, cfg, fcfg)
                report.run_id = run.id
                run.note(
                    f"k curve {len(report.k_points)} point(s); "
                    f"contamination {len(report.contamination_points)} setting(s); "
                    f"weight perturbations {len(report.weight_points)}"
                )
                if not report.accuracy_available:
                    run.note(
                        "per-setting accuracy NOT computed: " + report.accuracy_blocked_because
                    )
                status = "success"
            finally:
                run.finish(status)
    except (MissingSetting, DatabaseError, ConfigError, ValueError) as exc:
        _fatal(str(exc))
        return

    click.echo("=" * 84)
    click.echo("K vs SILHOUETTE")
    click.echo("=" * 84)
    click.echo(f"  {'k':>3}  {'silhouette':>11}  {'inertia':>12}  note")
    for point in report.k_points:
        note = "SELECTED" if point.selected else ""
        click.echo(f"  {point.k:>3}  {point.silhouette:>11.4f}  {point.inertia:>12.2f}  {note}")

    click.echo()
    click.echo("=" * 84)
    click.echo("ISOLATIONFOREST CONTAMINATION")
    click.echo("=" * 84)
    click.echo(
        f"  {'contam':>7}  {'series':>7}  {'days':>8}  {'flagged':>8}  "
        f"{'rate':>7}  {'Jaccard vs base':>16}"
    )
    for cpoint in report.contamination_points:
        marker = "  <- configured" if cpoint.is_baseline else ""
        click.echo(
            f"  {cpoint.contamination:>7.2f}  {cpoint.series_scored:>7}  "
            f"{cpoint.days_scored:>8}  {cpoint.days_flagged:>8}  "
            f"{cpoint.flag_rate:>7.3f}  {cpoint.jaccard_vs_baseline:>16.3f}{marker}"
        )
    note = nesting_note(report.contamination_points)
    if note:
        click.echo()
        for line in _wrap(note):
            click.echo(f"  {line}")

    click.echo()
    click.echo("=" * 84)
    click.echo("FUSION WEIGHT SENSITIVITY")
    click.echo("=" * 84)
    base = report.weight_baseline
    if base is not None:
        click.echo(
            f"  baseline: {base.n_scored} scored, "
            f"siaga={base.siaga} waspada={base.waspada} tenang={base.tenang} "
            f"belum_dapat_dinilai={base.belum_dapat_dinilai}"
        )
    click.echo(
        f"\n  {'weight':<14} {'delta':>6} {'value':>6} {'spearman':>9} "
        f"{'lvl changed':>12} {'siaga':>7} {'waspada':>8}"
    )
    for wpoint in report.weight_points:
        if not wpoint.ok:
            click.echo(
                f"  {wpoint.weight:<14} {wpoint.delta:>+6.2f} {'skipped':>6}  {wpoint.skipped}"
            )
            continue
        flag = "  (*)" if wpoint.inert_because else ""
        click.echo(
            f"  {wpoint.weight:<14} {wpoint.delta:>+6.2f} {wpoint.value:>6.2f} "
            f"{wpoint.spearman:>9.4f} {wpoint.level_changes:>12} "
            f"{wpoint.siaga:>7} {wpoint.waspada:>8}{flag}"
        )

    inert = {p.weight: p.inert_because for p in report.weight_points if p.inert_because}
    for weight, why in inert.items():
        click.echo()
        click.echo(click.style(f"  (*) {weight}: ", fg="yellow"), nl=False)
        click.echo(why)

    click.echo()
    if report.accuracy_available:
        click.echo("  gt_events present: per-setting accuracy can now be added to this sweep.")
    else:
        click.echo(click.style("  PER-SETTING ACCURACY NOT COMPUTED", fg="yellow"))
        for line in report.accuracy_blocked_because.split(". "):
            if line.strip():
                click.echo(f"    {line.strip().rstrip('.')}.")


@cli.command("reproduce")
@click.option("--run", "run_id", type=int, default=None, help="Anomaly run to verify.")
def reproduce_cmd(run_id: int | None) -> None:
    """Recompute a stored anomaly run and compare it row by row (§9).

    Uses the run's own recorded parameters and seed, not the current YAML —
    reproducing a run means reproducing what it did.
    """
    from .reproduce import latest_anomaly_run, verify

    try:
        with connect() as conn:
            target = run_id if run_id is not None else latest_anomaly_run(conn)
            if target is None:
                _fatal("no successful anomaly run to verify; run `siap analyze` first")
                return
            click.echo(f"  recomputing run #{target}; this refits every series...\n")
            report = verify(conn, target)
    except (MissingSetting, DatabaseError, ConfigError, ValueError) as exc:
        _fatal(str(exc))
        return

    click.echo("=" * 84)
    click.echo(f"REPRODUCIBILITY — run #{report.run_id}")
    click.echo("=" * 84)
    click.echo(f"  seed          : {report.seed}")
    click.echo(f"  run commit    : {report.run_git_sha or '(unrecorded)'}")
    click.echo(f"  current commit: {report.current_git_sha or '(not a git checkout)'}")
    click.echo(f"  same code     : {'yes' if report.code_matches else 'NO'}")
    click.echo(f"\n  series recomputed : {report.series_checked}")
    click.echo(f"  scores compared   : {report.scores_compared:,}")
    click.echo(f"  stored / recomputed: {report.stored_rows:,} / {report.recomputed_rows:,}")

    marker = click.style(OK, fg="green") if report.scores_match else click.style(BAD, fg="red")
    click.echo(f"\n[{marker}] every score identical to six decimal places")
    if report.mismatches:
        click.echo(f"         {len(report.mismatches):,} differing score(s); first 10:")
        for m in report.mismatches[:10]:
            click.echo(
                f"           {m.obs_date} {m.commodity}/{m.region} {m.method}: "
                f"stored={m.stored} recomputed={m.recomputed}"
            )

    marker = click.style(OK, fg="green") if report.counts_match else click.style(BAD, fg="red")
    click.echo(f"[{marker}] the input data is unchanged since the run")

    if report.version_drift:
        click.echo(click.style("\n  LIBRARY VERSIONS HAVE MOVED SINCE THIS RUN", fg="yellow"))
        for package, (was, now) in sorted(report.version_drift.items()):
            click.echo(f"    {package:<16} run={was or '-':<12} now={now or '-'}")
        click.echo(
            "    Scores still matched, so the drift did not change the result here.\n"
            "    Cite the versions the run recorded, not the ones installed today."
        )

    for note in report.notes:
        click.echo()
        for line in _wrap(note):
            click.echo(f"  {line}")

    click.echo()
    if report.ok:
        click.echo(click.style("Run reproduced exactly.", fg="green"))
    else:
        click.echo(
            click.style(
                "NOT REPRODUCED. The determinism claim does not hold for this run; "
                "do not cite its numbers until this is understood.",
                fg="red",
            )
        )
        sys.exit(1)


@cli.command("export")
@click.option(
    "--out",
    "out_dir",
    default=None,
    help="Output directory. Defaults to paper-exports/ at the repository root.",
)
def export_cmd(out_dir: str | None) -> None:
    """Write figures and tables for the paper into paper-exports/."""
    from pathlib import Path

    from .config import load_analysis, load_fusion
    from .evaluate.ablation import run as run_ablation
    from .export import run_export
    from .fuse import latest_anomaly_run

    directory = Path(out_dir) if out_dir else repo_root() / "paper-exports"

    try:
        cfg, fcfg = load_analysis(), load_fusion()
        with connect() as conn:
            anomaly_run = latest_anomaly_run(conn)
            if anomaly_run is None:
                _fatal("no completed anomaly run; run `siap analyze` first")
                return
            cluster_run = fetch_value(
                conn,
                "select max(id) from public.analysis_runs "
                "where run_type = 'cluster' and status = 'success'",
            )
            fusion_run = fetch_value(
                conn,
                "select max(id) from public.analysis_runs "
                "where run_type = 'fusion' and status = 'success'",
            )
            click.echo("  running the sweeps the figures are drawn from...")
            ablation = run_ablation(conn, anomaly_run, cfg, fcfg)
            report = run_export(
                conn,
                directory,
                anomaly_run,
                None if cluster_run is None else int(cluster_run),
                None if fusion_run is None else int(fusion_run),
                ablation,
                cfg,
                fcfg,
            )
    except (MissingSetting, DatabaseError, ConfigError, ValueError) as exc:
        _fatal(str(exc))
        return

    click.echo(f"\n  {directory}\n")
    for spec in report.figures:
        click.echo(f"    figure  {spec.slug}.pdf / .png")
    for table in report.tables:
        click.echo(f"    table   {table.slug}.csv / .tex   ({len(table.rows)} row(s))")
    click.echo("    readme  README.md")

    if report.skipped:
        click.echo(click.style("\n  NOT EXPORTED", fg="yellow"))
        for reason in report.skipped:
            for index, line in enumerate(_wrap(reason, 74)):
                click.echo(f"    {'- ' if index == 0 else '  '}{line}")

    click.echo(f"\n  {len(report.files)} file(s) written.")


@cli.command("kappa")
@click.option("--a", "annotator_a", default=None, help="First annotator code.")
@click.option("--b", "annotator_b", default=None, help="Second annotator code.")
def kappa_cmd(annotator_a: str | None, annotator_b: str | None) -> None:
    """Cohen's kappa between two annotators — the M7 stop condition."""
    from .config import load_analysis
    from .evaluate.kappa import annotators, compute

    try:
        cfg = load_analysis()
        with connect() as conn:
            found = annotators(conn)
            if len(found) < 2:
                _fatal(
                    f"need two annotators, found {found or 'none'}. "
                    f"Kappa measures agreement; it cannot be computed from one person."
                )
                return
            # Cohen's kappa is defined for exactly two raters. With three or more
            # having labelled, picking the first two silently would report a
            # number that quietly ignores somebody's work — and nothing in the
            # output would say so.
            if len(found) > 2 and not (annotator_a and annotator_b):
                _fatal(
                    f"{len(found)} annotators have labelled: {', '.join(found)}. "
                    f"Cohen's kappa is defined for a pair, so name which two:\n"
                    f"    siap kappa --a {found[0]} --b {found[1]}\n"
                    f"If a third person is the adjudicator, they should be resolving "
                    f"disagreements into gt_events rather than labelling blind."
                )
                return
            result = compute(conn, annotator_a or found[0], annotator_b or found[1])
    except (MissingSetting, DatabaseError, ConfigError, ValueError) as exc:
        _fatal(str(exc))
        return

    click.echo(f"  annotators      : {result.annotator_a} vs {result.annotator_b}")
    click.echo(f"  paired labels   : {result.n_paired}")
    click.echo(f"  observed agree  : {result.observed_agreement:.4f}")
    click.echo(f"  expected agree  : {result.expected_agreement:.4f}")
    passed = result.passes(cfg.evaluation.min_kappa)
    click.echo(
        "  Cohen's kappa   : "
        + click.style(f"{result.kappa:.4f}", fg="green" if passed else "red")
        + f"   ({result.interpretation})"
    )
    click.echo(f"  gate            : >= {cfg.evaluation.min_kappa}")

    click.echo(f"\n  confusion (rows = {result.annotator_a}, cols = {result.annotator_b}):")
    labels = ("anomali", "normal", "ragu")
    click.echo("      " + "".join(f"{c:>10}" for c in labels))
    for row_label in labels:
        click.echo(
            f"  {row_label:<8}" + "".join(f"{result.confusion[row_label][c]:>10}" for c in labels)
        )

    if result.disagreements:
        click.echo(f"\n  {len(result.disagreements)} disagreement(s) for adjudication:")
        for d in result.disagreements[:15]:
            click.echo(
                f"      #{d['candidate_id']:<5} {d['region']!s:<16}{d['commodity']!s:<22}"
                f"{d['obs_date']}   {d[result.annotator_a]} / {d[result.annotator_b]}"
            )

    if not passed:
        click.echo()
        _fatal(
            f"kappa {result.kappa:.4f} is below the {cfg.evaluation.min_kappa} gate.\n"
            f"  The brief is explicit: do not proceed. The operational definition is\n"
            f"  too ambiguous. Revise it, re-label, and report both rounds."
        )


if __name__ == "__main__":  # pragma: no cover
    cli()
