"""Run records: closing a run must survive the failure that closed it.

Every analysis module calls `Run.finish()` from a `finally`, so the path that
matters most is the one reached by an exception. If the failure was a database
error the transaction is already aborted, and an aborted transaction refuses
every further statement — including the UPDATE that records the failure.
"""

from __future__ import annotations

from types import SimpleNamespace

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from siap.runs import Run


class _Cursor:
    """Refuses statements on an aborted transaction, as Postgres does."""

    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        if self.conn.info.transaction_status == TransactionStatus.INERROR:
            raise psycopg.errors.InFailedSqlTransaction(
                "current transaction is aborted, commands ignored until end of transaction block"
            )
        self.conn.executed.append((sql, params))


class _Conn:
    def __init__(self, status: TransactionStatus = TransactionStatus.INTRANS) -> None:
        self.info = SimpleNamespace(transaction_status=status)
        self.executed: list[tuple[str, object]] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        self.info.transaction_status = TransactionStatus.IDLE


# ---------------------------------------------------------------------------
# The mechanism the rollback exists for
# ---------------------------------------------------------------------------
def test_an_aborted_transaction_refuses_the_update_that_would_record_the_failure() -> None:
    """Why `finish` cannot simply run the UPDATE: this is what fusion #79 hit."""
    conn = _Conn(TransactionStatus.INERROR)
    with pytest.raises(psycopg.errors.InFailedSqlTransaction), conn.cursor() as cur:
        cur.execute("update public.analysis_runs set status = 'failed'")


# ---------------------------------------------------------------------------
# finish()
# ---------------------------------------------------------------------------
def test_a_run_that_failed_on_a_database_error_still_records_failed() -> None:
    conn = _Conn(TransactionStatus.INERROR)
    Run(id=79, conn=conn, run_type="fusion").finish("failed")

    assert conn.rollbacks == 1, "the aborted transaction must be cleared first"
    assert len(conn.executed) == 1, "the status update must reach the database"
    assert conn.executed[0][1][0] == "failed"
    assert conn.commits == 1


def test_a_healthy_run_is_not_rolled_back() -> None:
    """The rollback is a recovery path, not something every run pays for."""
    conn = _Conn(TransactionStatus.INTRANS)
    Run(id=72, conn=conn, run_type="fusion").finish("success")

    assert conn.rollbacks == 0
    assert conn.executed[0][1][0] == "success"


def test_notes_survive_the_rollback() -> None:
    """Notes live in Python, so what the run learned before failing is kept."""
    run = Run(id=79, conn=(conn := _Conn(TransactionStatus.INERROR)), run_type="fusion")
    run.note("fused 0 alerts")
    run.note("level 'hijau' rejected by alerts_level_known")
    run.finish("failed")

    notes = conn.executed[0][1][1]
    assert "fused 0 alerts" in notes
    assert "alerts_level_known" in notes


def test_a_run_with_nothing_to_say_stores_null_rather_than_an_empty_string() -> None:
    conn = _Conn()
    Run(id=72, conn=conn, run_type="fusion").finish("success")

    assert conn.executed[0][1][1] is None
