"""Run records.

Every ingestion and every analysis executes inside an `analysis_runs` row that
captures the git SHA, the seed, the resolved parameters and the library versions
in effect. Ingestion uses `run_type='ingest'` or `'backfill'`; the analysis
modules added in M3+ use their own types.

The point is traceability: any row in the database can name the run that wrote
it, and that run can name the exact commit and configuration behind it.
"""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any

from psycopg.types.json import Json

from .db import Conn, fetch_value
from .paths import repo_root

# Packages whose versions are recorded on every run. A number in the paper must
# be attributable to the library version that produced it.
_TRACKED_PACKAGES = (
    "httpx",
    "beautifulsoup4",
    "lxml",
    "pytrends",
    "pandas",
    "numpy",
    "scikit-learn",
    "statsmodels",
    "psycopg",
)


def git_sha() -> str | None:
    """Current commit SHA, with a `-dirty` suffix when the tree has changes.

    Returns None outside a git repository or before the first commit, rather
    than inventing a value — an unknown provenance must look unknown.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if sha.returncode != 0:
            return None
        head = sha.stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return f"{head}-dirty" if dirty.stdout.strip() else head
    except Exception:
        return None


def lib_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": platform.python_version()}
    for name in _TRACKED_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions


@dataclass
class Run:
    """An open run. Call `finish()` exactly once."""

    id: int
    conn: Conn
    run_type: str
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        """Record a skip, degradation or anything else a reader must know.

        These end up in `analysis_runs.notes`. A run that silently did less than
        it claims is worse than one that failed.
        """
        self.notes.append(message)

    def finish(self, status: str = "success") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "update public.analysis_runs "
                "set finished_at = now(), status = %s, notes = %s where id = %s",
                (status, "\n".join(self.notes) or None, self.id),
            )
        self.conn.commit()


def list_runs(conn: Conn, limit: int = 20) -> list[dict[str, Any]]:
    from .db import fetch_all

    return fetch_all(
        conn,
        """
        select id, run_type, status, started_at, finished_at, git_sha,
               params::text as params, left(coalesce(notes, ''), 200) as notes
          from public.analysis_runs
         order by id desc
         limit %s
        """,
        (limit,),
    )


def close_stale(conn: Conn, older_than_hours: float = 6.0) -> list[int]:
    """Mark abandoned runs as failed.

    A process killed mid-run — Ctrl-C, a timed-out CI job, a laptop asleep —
    leaves its row at `status='running'` forever. Left alone those rows quietly
    accumulate and make "which runs actually completed?" unanswerable, which
    matters directly for the reproducibility claim in M9.

    They are marked `failed`, never `success`: the run genuinely did not finish,
    and whatever it wrote is partial.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            update public.analysis_runs
               set status = 'failed',
                   finished_at = now(),
                   notes = concat_ws(
                       E'\\n', notes,
                       'Marked failed by `siap runs --close-stale`: still running after '
                       || %s || ' hour(s). The process did not finish, so any rows it '
                       || 'wrote are partial.')
             where status = 'running'
               and started_at < now() - make_interval(hours => %s)
            returning id
            """,
            (older_than_hours, older_than_hours),
        )
        closed = [int(r["id"]) for r in cur.fetchall()]
    conn.commit()
    return closed


def start_run(
    conn: Conn,
    run_type: str,
    *,
    params: dict[str, Any] | None = None,
    seed: int | None = None,
) -> Run:
    """Open an `analysis_runs` row and return a handle to it."""
    run_id = fetch_value(
        conn,
        """
        insert into public.analysis_runs (run_type, status, git_sha, seed, params, lib_versions)
        values (%s, 'running', %s, %s, %s, %s)
        returning id
        """,
        (run_type, git_sha(), seed, Json(params or {}), Json(lib_versions())),
    )
    conn.commit()
    return Run(id=int(run_id), conn=conn, run_type=run_type)
