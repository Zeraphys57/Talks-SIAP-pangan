"""Matching and metrics for the four ablation arms (§7.4).

    zscore_only    the statistical baseline alone
    iforest_only   the ML arm alone
    union          naive OR of the two — the cheap-hybrid strawman
    fusion          the proposed contribution

**The fusion arm must beat the baselines, or that is what gets reported.** A
negative result honestly reported is publishable; an unsupported "hybrid lebih
baik" is not.

### Matching

A detection matches a ground-truth event when its date falls within
`tolerance_days` of the event window, for the same commodity and region. Events
have extent because the operational definition requires persistence for two or
more days, so a single detection anywhere inside the window counts as finding
it.

    precision = detections that hit an event / all detections
    recall    = events hit by >= 1 detection / all events
    F1        = harmonic mean

Precision counts detections and recall counts events, deliberately: firing five
times inside one event is one discovery, not five, but each of those five is a
separate demand on the user's attention.

### The evaluation universe

Metrics are computed **only over dates in `gt_candidates`**. The pool is a
stratified sample, so a detection on an unlabelled date is neither a hit nor a
false positive — nobody has said what it is. Counting those as false positives
would penalise the detectors for the sampler's choices and make precision a
function of pool size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..db import Conn, fetch_all

log = logging.getLogger(__name__)

ARMS = ("zscore_only", "iforest_only", "union", "fusion")


@dataclass
class ArmMetrics:
    method: str
    tp: int
    fp: int
    fn: int
    tolerance_days: int
    split: str = "test"

    @property
    def precision(self) -> float:
        denominator = self.tp + self.fp
        return self.tp / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.tp + self.fn
        return self.tp / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_row(self, run_id: int) -> tuple[Any, ...]:
        return (
            run_id,
            self.method,
            self.tolerance_days,
            self.tp,
            self.fp,
            self.fn,
            round(self.precision, 6),
            round(self.recall, 6),
            round(self.f1, 6),
            self.split,
            None,
        )


@dataclass
class Detection:
    commodity_id: int
    region_id: int
    obs_date: date


@dataclass
class Event:
    id: int
    commodity_id: int
    region_id: int
    start_date: date
    end_date: date

    def covers(self, detection: Detection, tolerance: int) -> bool:
        if detection.commodity_id != self.commodity_id:
            return False
        if detection.region_id != self.region_id:
            return False
        return (
            self.start_date - timedelta(days=tolerance)
            <= detection.obs_date
            <= self.end_date + timedelta(days=tolerance)
        )


def score(
    detections: list[Detection],
    events: list[Event],
    tolerance_days: int,
    method: str,
    split: str = "test",
) -> ArmMetrics:
    """Count TP / FP / FN for one arm. Pure, so it is testable without a database."""
    matched_events: set[int] = set()
    tp = fp = 0

    for detection in detections:
        hits = [e for e in events if e.covers(detection, tolerance_days)]
        if hits:
            tp += 1
            matched_events.update(e.id for e in hits)
        else:
            fp += 1

    fn = len(events) - len(matched_events)
    return ArmMetrics(
        method=method, tp=tp, fp=fp, fn=fn, tolerance_days=tolerance_days, split=split
    )


# ---------------------------------------------------------------------------
# Loading from the database
# ---------------------------------------------------------------------------
def load_events(conn: Conn) -> list[Event]:
    return [
        Event(
            id=int(r["id"]),
            commodity_id=int(r["commodity_id"]),
            region_id=int(r["region_id"]),
            start_date=r["start_date"],
            end_date=r["end_date"],
        )
        for r in fetch_all(
            conn,
            "select id, commodity_id, region_id, start_date, end_date "
            "from public.gt_events order by start_date",
        )
    ]


def load_detections(
    conn: Conn, arm: str, anomaly_run_id: int, fusion_run_id: int | None
) -> list[Detection]:
    """Detections for one arm, restricted to the labelled candidate universe."""
    if arm in ("zscore_only", "iforest_only", "union"):
        method_filter = {
            "zscore_only": "and a.method = 'zscore'",
            "iforest_only": "and a.method = 'iforest'",
            "union": "",
        }[arm]
        rows = fetch_all(
            conn,
            f"""
            select distinct a.commodity_id, a.region_id, a.obs_date
              from public.anomaly_scores a
              join public.gt_candidates gc
                on gc.commodity_id = a.commodity_id
               and gc.region_id   = a.region_id
               and gc.obs_date    = a.obs_date
             where a.run_id = %s and a.is_flagged {method_filter}
            """,
            (anomaly_run_id,),
        )
    elif arm == "fusion":
        if fusion_run_id is None:
            return []
        rows = fetch_all(
            conn,
            """
            select distinct al.commodity_id, al.region_id, al.obs_date
              from public.alerts al
              join public.gt_candidates gc
                on gc.commodity_id = al.commodity_id
               and gc.region_id   = al.region_id
               and gc.obs_date    = al.obs_date
             where al.run_id = %s and al.level in ('merah', 'kuning')
            """,
            (fusion_run_id,),
        )
    else:
        raise ValueError(f"unknown arm {arm!r}; expected one of {ARMS}")

    return [Detection(int(r["commodity_id"]), int(r["region_id"]), r["obs_date"]) for r in rows]


def evaluate_all_arms(
    conn: Conn,
    anomaly_run_id: int,
    fusion_run_id: int | None,
    tolerance_days: int,
    split: str = "test",
) -> list[ArmMetrics]:
    events = load_events(conn)
    if not events:
        raise ValueError(
            "no adjudicated gt_events. Metrics cannot be computed before two "
            "annotators have labelled and their disagreements have been resolved."
        )
    return [
        score(
            load_detections(conn, arm, anomaly_run_id, fusion_run_id),
            events,
            tolerance_days,
            arm,
            split,
        )
        for arm in ARMS
    ]


def persist(conn: Conn, run_id: int, results: list[ArmMetrics]) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into public.evaluation_results
                (run_id, method, tolerance_days, tp, fp, fn,
                 precision, recall, f1, split, notes)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (run_id, method, tolerance_days, split) do nothing
            """,
            [r.as_row(run_id) for r in results],
        )
    conn.commit()
    return len(results)
