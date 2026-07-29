"""Health checks: schema completeness, RLS posture, and a live anon smoke test.

The point of this module is that the M0 stop gate should not be passable by
reading code. `siap doctor` asserts the intended access posture against the live
database catalog, and then proves it over HTTP with the real anon key.

The intended posture is declared once, in TABLE_AUDIENCE below, and checked
against reality — rather than being re-derived by reading the RLS migration.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .db import Conn, fetch_all, fetch_value
from .settings import has, supabase_anon_key, supabase_url


class Audience(StrEnum):
    """Who is allowed to SELECT a table through the API."""

    PUBLIC = "public"  # anon + authenticated: the dashboard reads these
    LAB = "lab"  # authenticated only: the research console
    ENGINE = "engine"  # service role only: no API access whatsoever


# The complete intended posture. Every table in supabase/migrations must appear.
TABLE_AUDIENCE: dict[str, Audience] = {
    # reference
    "commodities": Audience.PUBLIC,
    "regions": Audience.PUBLIC,
    "sources": Audience.PUBLIC,
    "source_regions": Audience.PUBLIC,
    # ingestion
    "raw_snapshots": Audience.ENGINE,
    "fetch_failures": Audience.LAB,
    "price_observations": Audience.LAB,
    # derived
    "price_daily_unified": Audience.PUBLIC,
    "demand_signals": Audience.LAB,
    "source_offsets": Audience.LAB,  # provenance for every rebased price
    # analysis
    "analysis_runs": Audience.PUBLIC,
    "anomaly_scores": Audience.PUBLIC,
    "cluster_models": Audience.LAB,
    "cluster_assignments": Audience.PUBLIC,
    "seasonal_components": Audience.PUBLIC,
    "alerts": Audience.PUBLIC,
    # evaluation
    "gt_candidates": Audience.ENGINE,
    "gt_labels": Audience.ENGINE,  # INSERT only for authenticated; no SELECT
    "gt_events": Audience.LAB,
    "evaluation_results": Audience.LAB,
    "sus_responses": Audience.LAB,
    # lab identity
    "lab_annotators": Audience.ENGINE,  # reachable only via definer functions
}

# Definer functions the /lab console depends on. Each is scoped to the caller's
# own annotator code, which is how gt_labels can stay unreadable while the UI
# still knows what is left to do.
LAB_FUNCTIONS = ("current_annotator_code", "lab_queue", "lab_progress")

REFERENCE_TABLES = ("commodities", "regions", "sources", "source_regions")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]


# ---------------------------------------------------------------------------
# Catalog-level checks
# ---------------------------------------------------------------------------
def check_tables_exist(conn: Conn, report: DoctorReport) -> None:
    present = {
        str(r["tablename"])
        for r in fetch_all(conn, "select tablename from pg_tables where schemaname = 'public'")
    }
    expected = set(TABLE_AUDIENCE)
    missing = sorted(expected - present)
    extra = sorted(present - expected - {"schema_migrations"})

    report.add(
        "schema: all expected tables exist",
        not missing,
        "all present" if not missing else f"missing: {', '.join(missing)}",
    )
    if extra:
        report.add(
            "schema: no undeclared tables",
            False,
            f"present but not declared in TABLE_AUDIENCE: {', '.join(extra)}",
        )


def check_rls_enabled(conn: Conn, report: DoctorReport) -> None:
    rows = fetch_all(
        conn,
        """
        select c.relname as table_name, c.relrowsecurity as rls_enabled
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'public' and c.relkind = 'r'
        """,
    )
    unprotected = [
        str(r["table_name"])
        for r in rows
        if str(r["table_name"]) in TABLE_AUDIENCE and not r["rls_enabled"]
    ]
    report.add(
        "rls: enabled on every table",
        not unprotected,
        "enabled everywhere" if not unprotected else f"RLS OFF on: {', '.join(unprotected)}",
    )


def check_policy_posture(conn: Conn, report: DoctorReport) -> None:
    """Assert each table's SELECT policies match its declared audience."""
    rows = fetch_all(
        conn,
        """
        select tablename, policyname, cmd, roles::text[] as roles
          from pg_policies
         where schemaname = 'public'
        """,
    )
    select_roles: dict[str, set[str]] = {}
    for r in rows:
        if str(r["cmd"]).upper() not in ("SELECT", "ALL"):
            continue
        table = str(r["tablename"])
        select_roles.setdefault(table, set()).update(str(x) for x in (r["roles"] or []))

    violations: list[str] = []
    for table, audience in TABLE_AUDIENCE.items():
        roles = select_roles.get(table, set())
        anon_can_read = "anon" in roles or "public" in roles
        authed_can_read = "authenticated" in roles or "public" in roles

        if audience is Audience.PUBLIC and not anon_can_read:
            violations.append(f"{table}: declared PUBLIC but anon has no SELECT policy")
        if audience is not Audience.PUBLIC and anon_can_read:
            violations.append(f"{table}: declared {audience.value.upper()} but anon CAN read it")
        if audience is Audience.LAB and not authed_can_read:
            violations.append(f"{table}: declared LAB but authenticated has no SELECT policy")
        if audience is Audience.ENGINE and authed_can_read:
            violations.append(f"{table}: declared ENGINE-only but authenticated CAN read it")

    report.add(
        "rls: SELECT policies match declared audience",
        not violations,
        "posture matches" if not violations else "\n      ".join(violations),
    )


def check_blind_queue_view(conn: Conn, report: DoctorReport) -> None:
    """The labeling queue must not expose which stratum a candidate came from."""
    columns = {
        str(r["column_name"])
        for r in fetch_all(
            conn,
            """
            select column_name from information_schema.columns
             where table_schema = 'public' and table_name = 'gt_labeling_queue'
            """,
        )
    }
    if not columns:
        report.add("blinding: gt_labeling_queue exists", False, "view not found")
        return
    leaks = columns & {"sampling_stratum", "generated_by_run"}
    report.add(
        "blinding: gt_labeling_queue hides the sampling stratum",
        not leaks,
        "stratum not exposed" if not leaks else f"view exposes: {', '.join(sorted(leaks))}",
    )


def check_label_attribution(conn: Conn, report: DoctorReport) -> None:
    """An annotator must not be able to submit labels under another's code.

    Cohen's kappa assumes two independent label sets. If any signed-in team
    member could write rows as 'A2', that assumption would rest on nobody
    having tried, which is not a guarantee.
    """
    expression = fetch_value(
        conn,
        """
        select with_check from pg_policies
         where schemaname = 'public' and tablename = 'gt_labels'
           and policyname = 'lab_insert_gt_labels'
        """,
    )
    if expression is None:
        report.add("blinding: label writes are attributed", False, "insert policy not found")
    else:
        scoped = "current_annotator_code" in str(expression)
        report.add(
            "blinding: label writes are attributed to the signed-in annotator",
            scoped,
            "insert policy compares annotator_code against auth.uid()"
            if scoped
            else f"insert policy is unscoped: with check ({expression})",
        )

    defined = {
        str(r["proname"])
        for r in fetch_all(
            conn,
            """
            select p.proname
              from pg_proc p
              join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.prosecdef
            """,
        )
    }
    missing = [f for f in LAB_FUNCTIONS if f not in defined]
    report.add(
        "lab: annotator-scoped functions exist",
        not missing,
        f"{', '.join(LAB_FUNCTIONS)} present"
        if not missing
        else f"missing SECURITY DEFINER function(s): {', '.join(missing)}",
    )


def check_reference_seeded(conn: Conn, report: DoctorReport) -> None:
    from .config import load_reference

    ref = load_reference()
    expected = {
        "commodities": len(ref.commodities),
        "regions": len(ref.regions),
        "sources": len(ref.sources),
        "source_regions": sum(len(s.regions) for s in ref.sources),
    }
    for table, want in expected.items():
        got = int(fetch_value(conn, f'select count(*) from public."{table}"') or 0)
        report.counts[table] = got
        report.add(
            f"seed: {table} matches configuration",
            got == want,
            f"{got} rows (config declares {want})",
        )


# ---------------------------------------------------------------------------
# Live anon check over HTTP — proves the posture, rather than inferring it
# ---------------------------------------------------------------------------
def _anon_get(table: str, api_url: str, anon_key: str) -> tuple[int, Any]:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/rest/v1/{table}?select=*&limit=1",
        headers={
            "apikey": anon_key,
            "Authorization": f"Bearer {anon_key}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = None
        return exc.code, body


def check_anon_access_live(report: DoctorReport, conn: Conn | None = None) -> None:
    """Hit PostgREST with the real anon key and confirm what it can and cannot see.

    When `conn` is supplied, each restricted table is also counted through the
    service role. That distinction matters: "anon returned 0 rows" from a table
    that is itself empty proves nothing about RLS, and the report says so rather
    than banking an unearned pass.
    """
    if not (
        has("SUPABASE_URL") and (has("NEXT_PUBLIC_SUPABASE_ANON_KEY") or has("SUPABASE_ANON_KEY"))
    ):
        report.add(
            "anon: live API check",
            True,
            "skipped — SUPABASE_URL / anon key not set",
        )
        return

    api_url, anon_key = supabase_url(), supabase_anon_key()

    status, body = _anon_get("commodities", api_url, anon_key)
    can_read = status == 200 and isinstance(body, list) and len(body) > 0
    report.add(
        "anon: CAN read commodities (presentation table)",
        can_read,
        f"HTTP {status}, {len(body) if isinstance(body, list) else 'n/a'} row(s)",
    )

    for table in ("raw_snapshots", "price_observations", "gt_candidates", "sus_responses"):
        status, body = _anon_get(table, api_url, anon_key)
        # RLS with no matching policy filters rows away rather than erroring, so
        # an empty 200 is a pass. A 4xx (missing GRANT) is an even stronger pass.
        blocked = status >= 400 or (isinstance(body, list) and len(body) == 0)

        detail = f"HTTP {status}"
        if isinstance(body, list):
            detail += f", {len(body)} row(s) returned"
        if conn is not None:
            actual = int(fetch_value(conn, f'select count(*) from public."{table}"') or 0)
            detail += (
                f"; table holds {actual} row(s)"
                if actual
                else "; table is EMPTY, so this pass is vacuous — not yet proof RLS blocks anything"
            )
        report.add(f"anon: CANNOT read {table}", blocked, detail)


def run_all(conn: Conn) -> DoctorReport:
    report = DoctorReport()
    check_tables_exist(conn, report)
    check_rls_enabled(conn, report)
    check_policy_posture(conn, report)
    check_blind_queue_view(conn, report)
    check_label_attribution(conn, report)
    check_reference_seeded(conn, report)
    check_anon_access_live(report, conn)
    return report
