"""Google Trends demand signal, via the unofficial `pytrends` wrapper.

This is **not** a price source and does not produce `price_observations`. It
fills `demand_signals`, which supplies the `D` term of the fusion score.

Three properties the build brief demands, implemented here:

1. **Best effort, never fatal.** pytrends wraps an undocumented endpoint that
   Google rate-limits aggressively; HTTP 429 is routine. A failure records a
   `fetch_failures` row and leaves the signal absent, so fusion's `D` degrades
   to 0 with a recorded reason rather than the whole run collapsing.
2. **Cached to disk.** Repeated runs must not re-hammer the endpoint. Responses
   are cached under `engine/.cache/trends/` keyed by commodity, scope and
   timeframe.
3. **Weekly stays weekly.** Google returns weekly interest. It is stored weekly
   and forward-filled at join time in M2. Interpolating it into a fake daily
   curve would invent resolution the source does not have.

`interest` is Google's 0-100 index, which is normalised *within the requested
window* and is therefore not comparable across requests. `interest_z52` — the
z-score against a trailing 52-week baseline — is what fusion consumes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from psycopg.types.json import Json

from ..config import CommodityConfig, load_reference
from ..db import Conn
from ..paths import repo_root
from ..runs import Run

log = logging.getLogger(__name__)

# Google geo codes. 'ID' is Indonesia; 'ID-YO' is Daerah Istimewa Yogyakarta.
GEO_BY_SCOPE = {"nasional": "ID", "di_yogyakarta": "ID-YO"}

# A trailing year of weeks is the minimum for a meaningful z52 baseline.
MIN_WEEKS_FOR_Z52 = 52


@dataclass
class TrendsReport:
    requested: int = 0
    stored: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


class TrendsCollector:
    """Collects weekly search interest per commodity and scope."""

    source_slug = "trends"
    parser_version = "trends-pytrends-2026-07-29"

    def __init__(self, conn: Conn, run: Run) -> None:
        self.conn = conn
        self.run = run
        self.reference = load_reference()
        self.cache_dir = repo_root() / "engine" / ".cache" / "trends"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.source_id = self._source_id()

    def _source_id(self) -> int | None:
        from ..db import fetch_value

        value = fetch_value(
            self.conn, "select id from public.sources where slug = %s", (self.source_slug,)
        )
        return int(value) if value is not None else None

    # -- failure recording --------------------------------------------------
    def record_failure(self, keyword: str, error_class: str, detail: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into public.fetch_failures
                    (source_id, url, error_class, error_detail, retry_count, run_context)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    self.source_id,
                    f"pytrends:{keyword}",
                    error_class,
                    detail[:4000],
                    0,
                    Json({"run_id": self.run.id, "parser_version": self.parser_version}),
                ),
            )
        self.conn.commit()

    # -- cache --------------------------------------------------------------
    def _cache_path(self, keyword: str, geo: str, timeframe: str) -> Path:
        key = hashlib.sha256(f"{keyword}|{geo}|{timeframe}".encode()).hexdigest()[:20]
        return self.cache_dir / f"{key}.json"

    def _cached(self, keyword: str, geo: str, timeframe: str) -> dict[str, float] | None:
        path = self._cache_path(keyword, geo, timeframe)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        # Cache for a week: the source itself only updates weekly.
        if time.time() - payload.get("cached_at", 0) > 7 * 24 * 3600:
            return None
        return {k: float(v) for k, v in payload.get("series", {}).items()}

    def _store_cache(
        self, keyword: str, geo: str, timeframe: str, series: dict[str, float]
    ) -> None:
        path = self._cache_path(keyword, geo, timeframe)
        path.write_text(
            json.dumps(
                {
                    "cached_at": time.time(),
                    "keyword": keyword,
                    "geo": geo,
                    "timeframe": timeframe,
                    "series": series,
                }
            ),
            encoding="utf-8",
        )

    # -- fetching -----------------------------------------------------------
    def _fetch_series(self, keyword: str, geo: str, timeframe: str) -> dict[str, float] | None:
        """Weekly interest for one keyword, or None if Google would not serve it."""
        cached = self._cached(keyword, geo, timeframe)
        if cached is not None:
            log.debug("trends cache hit for %s/%s", keyword, geo)
            return cached

        try:
            from pytrends.request import TrendReq
        except ImportError as exc:  # pragma: no cover
            self.record_failure(keyword, "pytrends_missing", str(exc))
            return None

        backoff = 10.0
        for attempt in range(1, 4):
            try:
                pytrends = TrendReq(hl="id-ID", tz=420, timeout=(10, 30), retries=0)
                pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
                frame = pytrends.interest_over_time()
                if frame is None or frame.empty:
                    self.record_failure(keyword, "empty_series", f"geo={geo} timeframe={timeframe}")
                    return None
                series = {
                    index.date().isoformat(): float(row[keyword])
                    for index, row in frame.iterrows()
                    if not bool(row.get("isPartial", False))
                }
                self._store_cache(keyword, geo, timeframe, series)
                return series
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                is_throttle = "429" in message or "TooManyRequests" in message
                log.warning("trends attempt %d for %r failed: %s", attempt, keyword, message)
                if attempt == 3:
                    self.record_failure(
                        keyword, "throttled" if is_throttle else "pytrends_error", message
                    )
                    return None
                time.sleep(backoff)
                backoff *= 3

        return None

    # -- z-score ------------------------------------------------------------
    @staticmethod
    def z_scores(series: dict[str, float]) -> dict[str, float | None]:
        """Trailing-52-week z-score for each week.

        Trailing only: the window ends at the week *before* the one being
        scored. Including the current week in its own baseline would damp the
        very spike the signal exists to detect — the same leak the Z-Score
        module avoids on prices.
        """
        weeks = sorted(series)
        out: dict[str, float | None] = {}
        for i, week in enumerate(weeks):
            window = [series[w] for w in weeks[max(0, i - MIN_WEEKS_FOR_Z52) : i]]
            if len(window) < MIN_WEEKS_FOR_Z52:
                out[week] = None
                continue
            mean = statistics.fmean(window)
            stdev = statistics.pstdev(window)
            out[week] = None if stdev == 0 else (series[week] - mean) / stdev
        return out

    # -- persistence --------------------------------------------------------
    def persist(
        self, commodity: CommodityConfig, scope: str, keyword: str, series: dict[str, float]
    ) -> int:
        if not series:
            return 0
        zs = self.z_scores(series)
        rows = [
            (
                commodity.slug,
                scope,
                keyword,
                datetime.strptime(week, "%Y-%m-%d").date(),
                interest,
                zs.get(week),
            )
            for week, interest in series.items()
        ]
        with self.conn.cursor() as cur:
            cur.executemany(
                """
                insert into public.demand_signals
                    (commodity_id, region_scope, keyword, week_start, interest, interest_z52)
                values ((select id from public.commodities where slug = %s), %s, %s, %s, %s, %s)
                on conflict (commodity_id, region_scope, keyword, week_start) do update set
                    interest     = excluded.interest,
                    interest_z52 = excluded.interest_z52,
                    fetched_at   = now()
                """,
                rows,
            )
        self.conn.commit()
        return len(rows)

    # -- entry point --------------------------------------------------------
    def collect(self, timeframe: str = "today 5-y") -> TrendsReport:
        """Collect the primary keyword for every commodity, in every scope.

        Only the first keyword per commodity is requested. pytrends is
        rate-limited and each extra term multiplies the chance of being cut off
        mid-run; the alternatives stay in configuration for later use.
        """
        report = TrendsReport()
        scopes = [s for s in self.reference.source(self.source_slug).regions if s in GEO_BY_SCOPE]

        for commodity in self.reference.commodities:
            keyword = commodity.trends_keywords[0]
            for scope in scopes:
                geo = GEO_BY_SCOPE[scope]
                report.requested += 1
                series = self._fetch_series(keyword, geo, timeframe)
                if series is None:
                    report.failures.append(f"{commodity.slug}/{scope}: no series")
                    continue
                report.stored += self.persist(commodity, scope, keyword, series)
                # Deliberate pacing on top of pytrends' own behaviour.
                time.sleep(3)

        if report.failures:
            self.run.note(
                f"trends: {len(report.failures)} of {report.requested} request(s) returned "
                f"nothing — fusion D degrades to 0 for those. " + "; ".join(report.failures[:8])
            )
        return report
