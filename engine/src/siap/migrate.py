"""Migration runner for `supabase/migrations/*.sql`.

Deliberately small and boring. It does three things the Supabase CLI would also
do, but without requiring the CLI to be installed on every machine that needs to
reproduce the database:

  * applies numbered migrations in order, each inside its own transaction;
  * records a sha256 of every applied file;
  * refuses to run if a previously applied file has changed on disk.

That last property is the point. Migrations are the schema source of truth for
the reproducibility claim in M9 — silently editing an applied migration would
mean a fresh clone builds a different database than the one the paper's numbers
came from.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .db import Conn, execute_script, fetch_all
from .paths import migrations_dir

MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

_TRACKING_TABLE = """
create table if not exists public.schema_migrations (
    filename     text        primary key,
    checksum     text        not null,
    applied_at   timestamptz not null default now(),
    execution_ms integer
);
comment on table public.schema_migrations is
    'Applied migrations and their sha256. Managed by engine/src/siap/migrate.py.';
"""


class MigrationError(RuntimeError):
    """Raised when migrations are malformed, out of order, or have drifted."""


@dataclass(frozen=True)
class Migration:
    path: Path
    sequence: int
    filename: str
    checksum: str
    sql: str

    @property
    def label(self) -> str:
        return self.filename


def _checksum(text: str) -> str:
    """sha256 over LF-normalised content.

    Windows checkouts hold CRLF. Hashing raw bytes would make the same migration
    look different on a teammate's machine and trip the drift guard for no
    reason.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def discover(directory: Path | None = None) -> list[Migration]:
    """Load every migration file in sequence order, validating names and gaps."""
    root = directory or migrations_dir()
    if not root.is_dir():
        raise MigrationError(f"migrations directory not found: {root}")

    migrations: list[Migration] = []
    unexpected: list[str] = []

    for path in sorted(root.iterdir()):
        if path.is_dir():
            continue
        match = MIGRATION_RE.match(path.name)
        if not match:
            unexpected.append(path.name)
            continue
        text = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                path=path,
                sequence=int(match.group(1)),
                filename=path.name,
                checksum=_checksum(text),
                sql=text,
            )
        )

    if unexpected:
        raise MigrationError(
            f"unrecognised file(s) in {root}: {', '.join(unexpected)}. "
            f"Migrations must be named NNNN_lower_snake_case.sql"
        )
    if not migrations:
        raise MigrationError(f"no migrations found in {root}")

    sequences = [m.sequence for m in migrations]
    duplicates = {s for s in sequences if sequences.count(s) > 1}
    if duplicates:
        raise MigrationError(f"duplicate migration sequence number(s): {sorted(duplicates)}")
    expected = list(range(1, len(migrations) + 1))
    if sequences != expected:
        raise MigrationError(
            f"migration sequence has gaps or does not start at 0001: got {sequences}, "
            f"expected {expected}"
        )
    return migrations


def ensure_tracking_table(conn: Conn) -> None:
    execute_script(conn, _TRACKING_TABLE)
    conn.commit()


def applied_checksums(conn: Conn) -> dict[str, str]:
    rows = fetch_all(conn, "select filename, checksum from public.schema_migrations")
    return {str(r["filename"]): str(r["checksum"]) for r in rows}


def check_drift(migrations: list[Migration], applied: dict[str, str]) -> None:
    """Raise if an already-applied migration has been edited on disk."""
    drifted = [
        m.filename
        for m in migrations
        if m.filename in applied and applied[m.filename] != m.checksum
    ]
    if drifted:
        raise MigrationError(
            "these migrations were already applied but have since been edited:\n  - "
            + "\n  - ".join(drifted)
            + "\nEditing an applied migration breaks reproducibility. Add a new "
            "migration that alters the schema forward instead."
        )
    orphans = sorted(set(applied) - {m.filename for m in migrations})
    if orphans:
        raise MigrationError(
            "the database records migrations that no longer exist on disk:\n  - "
            + "\n  - ".join(orphans)
            + "\nThe working tree is older than the database, or a migration was deleted."
        )


def pending(migrations: list[Migration], applied: dict[str, str]) -> list[Migration]:
    return [m for m in migrations if m.filename not in applied]


@dataclass
class AppliedResult:
    migration: Migration
    execution_ms: int


def apply_all(conn: Conn, *, dry_run: bool = False) -> list[AppliedResult]:
    """Apply every pending migration in order. Returns what was applied."""
    ensure_tracking_table(conn)
    migrations = discover()
    applied = applied_checksums(conn)
    check_drift(migrations, applied)

    results: list[AppliedResult] = []
    for migration in pending(migrations, applied):
        if dry_run:
            results.append(AppliedResult(migration=migration, execution_ms=0))
            continue
        started = time.perf_counter()
        try:
            execute_script(conn, migration.sql)
        except Exception as exc:
            conn.rollback()
            raise MigrationError(
                f"migration {migration.filename} failed and was rolled back:\n  {exc}"
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        with conn.cursor() as cur:
            cur.execute(
                "insert into public.schema_migrations (filename, checksum, execution_ms) "
                "values (%s, %s, %s)",
                (migration.filename, migration.checksum, elapsed_ms),
            )
        conn.commit()
        results.append(AppliedResult(migration=migration, execution_ms=elapsed_ms))

    return results


def status(conn: Conn) -> list[tuple[Migration, bool]]:
    """(migration, is_applied) for every migration on disk."""
    ensure_tracking_table(conn)
    migrations = discover()
    applied = applied_checksums(conn)
    check_drift(migrations, applied)
    return [(m, m.filename in applied) for m in migrations]
