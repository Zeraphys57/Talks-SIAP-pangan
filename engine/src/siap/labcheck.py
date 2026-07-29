"""Adversarial check on the /lab access model.

The entire evaluation rests on two annotators judging the same items
independently. If either could read the other's labels, or tell a `rule_flagged`
candidate from a `random_control` one, Cohen's kappa would be measuring
contamination and every number downstream of it would be void.

`doctor` asserts the posture from the catalog: RLS is on, this policy exists,
that column is absent. This module asserts it from the *other side* — it becomes
an annotator and tries the attacks:

    read the pool directly              must return nothing
    read the other annotator's labels   must return nothing
    write a label as the other annotator must be refused
    see which stratum a candidate is in must be impossible

Everything happens inside a transaction that is rolled back, so the two fixture
annotators and their labels never reach the real data. It writes nothing, but it
is not `doctor`: a command that inserts rows, even transactionally, should be
run deliberately rather than as a health check.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from psycopg import Rollback

from .db import Conn, fetch_all, fetch_value

log = logging.getLogger(__name__)

A_UUID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
B_UUID = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
A_CODE = "Z1"
B_CODE = "Z2"


@dataclass
class Attempt:
    name: str
    ok: bool
    detail: str


@dataclass
class LabCheckReport:
    attempts: list[Attempt] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.attempts.append(Attempt(name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(a.ok for a in self.attempts)

    @property
    def failures(self) -> list[Attempt]:
        return [a for a in self.attempts if not a.ok]


def _become(conn: Conn, user_id: uuid.UUID) -> None:
    """Assume the `authenticated` role carrying this user's JWT subject."""
    with conn.cursor() as cur:
        cur.execute("reset role")
        cur.execute(
            "select set_config('request.jwt.claims', %s, true)", (f'{{"sub":"{user_id}"}}',)
        )
        cur.execute("set local role authenticated")


def _as_postgres(conn: Conn) -> None:
    with conn.cursor() as cur:
        cur.execute("reset role")


def _denied(conn: Conn, sql: str, params: tuple[object, ...] = ()) -> str | None:
    """Run a statement expected to fail; return the SQLSTATE, or None if it succeeded.

    The statement runs in its own savepoint. A denial aborts that savepoint
    only, so the outer transaction survives to run the next attempt — and a
    statement that unexpectedly *succeeds* is undone by the explicit `Rollback`,
    which psycopg swallows. Catching the error inside the savepoint instead
    would leave the transaction aborted and every later check unrunnable.
    """
    succeeded = False
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql, list(params))
            succeeded = True
            # Swallowed by the transaction context manager, which has already
            # undone the savepoint by the time control reaches the return below.
            raise Rollback()
    except Exception as exc:
        if not succeeded:
            return getattr(exc, "sqlstate", None) or type(exc).__name__
    return None


def run(conn: Conn) -> LabCheckReport:
    report = LabCheckReport()

    n_candidates = int(fetch_value(conn, "select count(*) from public.gt_candidates") or 0)
    if n_candidates == 0:
        report.add(
            "pool exists",
            False,
            "gt_candidates is empty; run `siap gt-pool` before checking the lab access model",
        )
        return report

    # Everything below is inside one transaction that is rolled back at the end.
    with conn.cursor() as cur:
        cur.execute("savepoint labcheck")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into public.lab_annotators (user_id, annotator_code, display_name) "
                "values (%s, %s, 'labcheck fixture'), (%s, %s, 'labcheck fixture')",
                (A_UUID, A_CODE, B_UUID, B_CODE),
            )

        # --- as annotator A --------------------------------------------------
        _become(conn, A_UUID)

        code = fetch_value(conn, "select public.current_annotator_code()")
        report.add(
            "identity comes from the session, not the client",
            code == A_CODE,
            f"current_annotator_code() = {code!r} for A's JWT subject",
        )

        queue = fetch_all(conn, "select * from public.lab_queue(5)")
        report.add(
            "the queue is readable by an annotator",
            len(queue) > 0,
            f"lab_queue(5) returned {len(queue)} candidate(s)",
        )

        leaked = sorted(set(queue[0].keys()) & {"sampling_stratum", "shuffle_key"}) if queue else []
        report.add(
            "the queue does not reveal the sampling stratum",
            not leaked,
            "stratum absent from the returned columns"
            if not leaked
            else f"lab_queue exposes: {', '.join(leaked)}",
        )

        direct = fetch_all(conn, "select * from public.gt_candidates limit 5")
        report.add(
            "the unblinded pool is unreachable",
            len(direct) == 0,
            f"direct select on gt_candidates returned {len(direct)} row(s) "
            f"of {n_candidates} present",
        )

        first_id = int(queue[0]["candidate_id"]) if queue else 0
        second_id = int(queue[1]["candidate_id"]) if len(queue) > 1 else first_id

        state = _denied(
            conn,
            "insert into public.gt_labels (candidate_id, annotator_code, label) "
            "values (%s, %s, 'normal')",
            (first_id, B_CODE),
        )
        report.add(
            "an annotator cannot write under another annotator's code",
            state is not None,
            f"insert as {B_CODE} refused ({state})"
            if state
            else f"ACCEPTED an insert attributed to {B_CODE} — labels are not independent",
        )

        with conn.cursor() as cur:
            cur.execute(
                "insert into public.gt_labels (candidate_id, annotator_code, label, evidence_note) "
                "values (%s, %s, 'anomali', 'labcheck fixture')",
                (first_id, A_CODE),
            )
        report.add(
            "an annotator can write under their own code",
            True,
            f"insert as {A_CODE} accepted",
        )

        own = fetch_all(conn, "select * from public.gt_labels limit 5")
        report.add(
            "labels are write-only, even one's own",
            len(own) == 0,
            f"select on gt_labels returned {len(own)} row(s)",
        )

        after = fetch_all(conn, "select * from public.lab_queue(5)")
        report.add(
            "a labelled candidate leaves the queue",
            all(int(r["candidate_id"]) != first_id for r in after),
            "the just-labelled candidate is gone from lab_queue"
            if all(int(r["candidate_id"]) != first_id for r in after)
            else "lab_queue still offers a candidate this annotator has labelled",
        )

        progress = fetch_all(conn, "select * from public.lab_progress()")
        report.add(
            "progress is reported for the caller only",
            len(progress) == 1
            and progress[0]["annotator_code"] == A_CODE
            and int(progress[0]["labeled"]) == 1,
            f"lab_progress() = {progress}",
        )

        # --- as annotator B --------------------------------------------------
        _become(conn, B_UUID)

        b_progress = fetch_all(conn, "select * from public.lab_progress()")
        report.add(
            "one annotator's progress does not show the other's work",
            len(b_progress) == 1
            and b_progress[0]["annotator_code"] == B_CODE
            and int(b_progress[0]["labeled"]) == 0,
            f"lab_progress() = {b_progress}",
        )

        b_queue = fetch_all(conn, "select * from public.lab_queue(5)")
        report.add(
            "what A labelled is still offered to B",
            any(int(r["candidate_id"]) == first_id for r in b_queue),
            "B is still shown the candidate A has already judged"
            if any(int(r["candidate_id"]) == first_id for r in b_queue)
            else "B's queue was filtered by A's work — the two label sets are not independent",
        )

        b_sees = fetch_all(conn, "select * from public.gt_labels limit 5")
        report.add(
            "one annotator cannot read the other's judgements",
            len(b_sees) == 0,
            f"select on gt_labels as {B_CODE} returned {len(b_sees)} row(s)",
        )

        # --- as an authenticated user who is not an annotator ----------------
        _become(conn, uuid.uuid4())

        stranger_queue = fetch_all(conn, "select * from public.lab_queue(5)")
        stranger_state = _denied(
            conn,
            "insert into public.gt_labels (candidate_id, annotator_code, label) "
            "values (%s, %s, 'normal')",
            (second_id, A_CODE),
        )
        report.add(
            "a signed-in non-annotator gets nothing and writes nothing",
            len(stranger_queue) == 0 and stranger_state is not None,
            f"queue returned {len(stranger_queue)} row(s); "
            f"insert {'refused (' + str(stranger_state) + ')' if stranger_state else 'ACCEPTED'}",
        )

        # --- as anon ---------------------------------------------------------
        with conn.cursor() as cur:
            cur.execute("reset role")
            cur.execute("select set_config('request.jwt.claims', '', true)")
            cur.execute("set local role anon")

        anon_state = _denied(conn, "select * from public.lab_queue(5)")
        report.add(
            "anon cannot execute the lab functions at all",
            anon_state is not None,
            f"lab_queue() as anon refused ({anon_state})"
            if anon_state
            else "ACCEPTED — the public dashboard role can read the labelling queue",
        )
    finally:
        _as_postgres(conn)
        with conn.cursor() as cur:
            cur.execute("rollback to savepoint labcheck")
            cur.execute("release savepoint labcheck")
        conn.rollback()

    return report
