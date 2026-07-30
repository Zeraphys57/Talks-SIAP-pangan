"""Postgres connection layer.

The engine talks to Postgres directly rather than through the Supabase REST API.
Three reasons, recorded here because it is a design decision that will be asked
about:

1. Migrations are DDL. PostgREST cannot run DDL at all.
2. Ingestion writes tens of thousands of rows per backfill. `COPY` and multi-row
   `execute_many` are orders of magnitude faster than HTTP round trips.
3. The engine connects as the database owner, which is not subject to RLS at all,
   so the API layer would add latency without adding a safety property. There is
   deliberately no `service_role` key in this project; nothing here reads one.

The Next.js app is the opposite case and uses the REST API with the anon key,
constrained by the policies in supabase/migrations/0006_rls.sql.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .settings import database_url, redact_dsn

log = logging.getLogger(__name__)

Row = dict[str, Any]
Conn = psycopg.Connection[Row]

# psycopg accepts either positional (%s) or named (%(name)s) parameters. Both
# are used here: positional for short queries, named where a CTE references the
# same value more than once and repeating it positionally invites mismatches.
Params = Sequence[Any] | Mapping[str, Any] | None


class DatabaseError(RuntimeError):
    """Raised when the database is unreachable or misconfigured."""


@contextmanager
def connect(*, autocommit: bool = False, dsn: str | None = None) -> Iterator[Conn]:
    """Open a connection, yielding dict rows.

    Commits on clean exit, rolls back on exception. Never swallows the original
    error: a failed migration must surface the Postgres message verbatim.
    """
    target = dsn or database_url()
    try:
        conn = psycopg.connect(target, row_factory=dict_row, autocommit=autocommit)
    except psycopg.OperationalError as exc:
        raise DatabaseError(
            f"Could not connect to {redact_dsn(target)}.\n"
            f"  {exc}\n"
            f"  Check DATABASE_URL, that the Supabase project is not paused, and "
            f"that you are using the session pooler (port 5432) rather than the "
            f"transaction pooler (6543), which cannot run DDL."
        ) from exc

    log.debug("connected to %s", redact_dsn(target))
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def fetch_all(conn: Conn, sql: str, params: Params = None) -> list[Row]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(conn: Conn, sql: str, params: Params = None) -> Row | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetch_value(conn: Conn, sql: str, params: Params = None) -> Any:
    """Return the first column of the first row, or None."""
    row = fetch_one(conn, sql, params)
    if row is None:
        return None
    return next(iter(row.values()))


def execute(conn: Conn, sql: str, params: Params = None) -> int:
    """Execute one statement; return the affected row count."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def execute_script(conn: Conn, sql: str) -> None:
    """Execute a multi-statement SQL script.

    psycopg3 uses the simple query protocol when no parameters are bound, so the
    whole file runs as one implicit transaction — a migration either applies
    completely or not at all.
    """
    with conn.cursor() as cur:
        cur.execute(sql)


def table_counts(conn: Conn, tables: Sequence[str]) -> dict[str, int]:
    """Row counts for the named public tables, in the order given.

    Used by the milestone gates. Table names are validated against the catalog
    before interpolation, since they cannot be bound as parameters.
    """
    known = {
        r["table_name"]
        for r in fetch_all(
            conn,
            "select table_name from information_schema.tables where table_schema = 'public'",
        )
    }
    counts: dict[str, int] = {}
    for table in tables:
        if table not in known:
            raise DatabaseError(f"table public.{table} does not exist")
        counts[table] = int(fetch_value(conn, f'select count(*) from public."{table}"') or 0)
    return counts


def refresh_statistics(conn: Conn, *tables: str) -> None:
    """Update planner statistics for tables that were just bulk-written.

    A bulk insert, or a truncate-and-rewrite, leaves `pg_statistic` describing the
    table as it was beforehand, and the planner chooses its join strategy from
    those numbers. Autovacuum catches up on its own schedule — which, inside a
    pipeline, is after the next command has already planned against stale
    estimates. `siap fuse` hit exactly that: its query completes in seconds once
    statistics have settled, and was cancelled by `statement_timeout` when run
    immediately after `preprocess` rewrote price_daily_unified while
    price_observations still carried a day-old sample.

    ANALYZE is permitted inside a transaction block, unlike VACUUM, and on tables
    of this size costs a fraction of a second. Table names are validated against
    the catalog because they cannot be bound as parameters.
    """
    known = {
        r["table_name"]
        for r in fetch_all(
            conn,
            "select table_name from information_schema.tables where table_schema = 'public'",
        )
    }
    with conn.cursor() as cur:
        for table in tables:
            if table not in known:
                raise DatabaseError(f"table public.{table} does not exist")
            cur.execute(f'analyze public."{table}"')
    conn.commit()
    log.debug("refreshed planner statistics for %s", ", ".join(tables))


def server_version(conn: Conn) -> str:
    return str(fetch_value(conn, "select version()"))
