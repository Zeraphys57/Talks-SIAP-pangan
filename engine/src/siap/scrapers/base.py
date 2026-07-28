"""Polite HTTP client and the scraper contract.

Conduct rules live here rather than in individual scrapers, so a new scraper
cannot forget to be polite:

  * robots.txt is fetched once per host and honoured (RFC 9309 semantics);
  * a minimum delay is enforced between requests to the same host;
  * exactly one connection per host, no concurrency;
  * every request carries a User-Agent naming the project and a reachable
    contact address;
  * every response body is persisted to `raw_snapshots` before parsing;
  * every failure path writes a `fetch_failures` row.

That last pair is what makes the provenance claim real. A number on the
dashboard traces to a parsed observation, which names a snapshot, which names a
URL and a timestamp. A gap traces to a recorded failure.
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import ssl
import time
import urllib.robotparser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from psycopg.types.json import Json

from ..config import ScrapingConduct, SourceConfig, load_reference
from ..db import Conn, fetch_value
from ..runs import Run

log = logging.getLogger(__name__)


def build_ssl_context() -> ssl.SSLContext | bool:
    """Honour the environment's CA bundle.

    httpx verifies against its bundled certifi and ignores SSL_CERT_FILE, which
    Python's own `ssl` module respects. On machines behind a TLS-intercepting
    proxy or antivirus, that difference means urllib works and httpx does not.

    Verification is never disabled here. If a CA bundle is configured we trust
    it; otherwise we fall back to httpx's default. A project that scrapes
    government portals should not be in the habit of turning certificate
    checking off.
    """
    for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        candidate = os.environ.get(variable)
        if candidate and Path(candidate).is_file():
            log.debug("using CA bundle from %s", variable)
            return ssl.create_default_context(cafile=candidate)
    return True


class FetchError(RuntimeError):
    """Raised when a request cannot be completed within the retry budget."""

    def __init__(self, message: str, *, error_class: str, url: str, retry_count: int) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.url = url
        self.retry_count = retry_count


class RobotsDisallowed(FetchError):
    """Raised when robots.txt forbids the URL. Never retried, never overridden."""


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------
@dataclass
class RobotsPolicy:
    """Per-host robots.txt decision, cached for the process lifetime.

    RFC 9309 §2.3.1:
      * 200 with a parseable body  -> obey it
      * 4xx ("unavailable")        -> the crawler may access any resource
      * 5xx ("unreachable")        -> assume complete disallow

    Several of these portals are single-page apps that answer *any* unknown path
    with their HTML shell, including /robots.txt. That is not a robots file, and
    treating it as one would have the parser silently allow everything for the
    wrong reason. It is detected and reported as "absent" instead.
    """

    user_agent: str
    _parsers: dict[str, urllib.robotparser.RobotFileParser | None] = field(default_factory=dict)
    _reasons: dict[str, str] = field(default_factory=dict)

    def _load(self, client: httpx.Client, origin: str) -> None:
        if origin in self._parsers:
            return
        url = f"{origin}/robots.txt"
        try:
            response = client.get(url, timeout=15.0)
        except httpx.HTTPError as exc:
            # Cannot reach robots.txt at all: treat as unreachable -> disallow.
            self._parsers[origin] = None
            self._reasons[origin] = f"unreachable ({type(exc).__name__}: {exc}) -> disallow all"
            return

        if 400 <= response.status_code < 500:
            self._parsers[origin] = None
            self._reasons[origin] = f"HTTP {response.status_code} -> no restrictions (RFC 9309)"
            return
        if response.status_code >= 500:
            self._parsers[origin] = None
            self._reasons[origin] = f"HTTP {response.status_code} -> disallow all (RFC 9309)"
            return

        body = response.text
        looks_like_html = body.lstrip()[:200].lower().startswith(("<!doctype", "<html"))
        if looks_like_html:
            self._parsers[origin] = None
            self._reasons[origin] = "SPA shell returned instead of robots.txt -> treated as absent"
            return

        parser = urllib.robotparser.RobotFileParser()
        parser.parse(body.splitlines())
        self._parsers[origin] = parser
        self._reasons[origin] = f"parsed ({len(body)} bytes)"

    def can_fetch(self, client: httpx.Client, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        self._load(client, origin)
        parser = self._parsers[origin]
        if parser is None:
            # Only the 5xx and unreachable cases deny; both set that in _reasons.
            return "disallow all" not in self._reasons[origin]
        return parser.can_fetch(self.user_agent, url)

    def reason(self, url: str) -> str:
        parts = urlsplit(url)
        return self._reasons.get(f"{parts.scheme}://{parts.netloc}", "not checked")


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
@dataclass
class Fetched:
    url: str
    status_code: int
    body: bytes
    headers: dict[str, str]
    elapsed_ms: int
    attempts: int


class PoliteClient:
    """Synchronous HTTP client that enforces the conduct rules in sources.yaml."""

    # Retried: transient. 429 is explicitly rate limiting and gets a longer wait.
    RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

    def __init__(self, conduct: ScrapingConduct, contact: str) -> None:
        self.conduct = conduct
        self.user_agent = conduct.resolved_user_agent(contact)
        self.robots = RobotsPolicy(user_agent=self.user_agent)
        self._last_request_at: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent},
            timeout=httpx.Timeout(conduct.timeout_seconds),
            follow_redirects=True,
            verify=build_ssl_context(),
            # One connection per host, no concurrency, as declared in sources.yaml.
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _wait_turn(self, url: str) -> None:
        host = urlsplit(url).netloc
        last = self._last_request_at.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            remaining = self.conduct.min_delay_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at[host] = time.monotonic()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Fetched:
        if self.conduct.respect_robots_txt and not self.robots.can_fetch(self._client, url):
            raise RobotsDisallowed(
                f"robots.txt disallows {url} ({self.robots.reason(url)})",
                error_class="robots_disallowed",
                url=url,
                retry_count=0,
            )

        last_error: str = "no attempt made"
        for attempt in range(1, self.conduct.max_retries + 2):
            self._wait_turn(url)
            started = time.perf_counter()
            try:
                response = self._client.request(
                    method, url, params=params, data=data, headers=headers
                )
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("attempt %d for %s failed: %s", attempt, url, last_error)
                self._backoff(attempt)
                continue

            elapsed_ms = int((time.perf_counter() - started) * 1000)

            if response.status_code in self.RETRY_STATUS:
                last_error = f"HTTP {response.status_code}"
                # Honour Retry-After when the server supplies one.
                retry_after = response.headers.get("Retry-After")
                log.warning(
                    "attempt %d for %s got %s (retry-after=%s)",
                    attempt,
                    url,
                    last_error,
                    retry_after,
                )
                self._backoff(attempt, retry_after=retry_after)
                continue

            return Fetched(
                url=str(response.url),
                status_code=response.status_code,
                body=response.content,
                headers=dict(response.headers),
                elapsed_ms=elapsed_ms,
                attempts=attempt,
            )

        raise FetchError(
            f"giving up on {url} after {self.conduct.max_retries + 1} attempt(s): {last_error}",
            error_class="exhausted_retries",
            url=url,
            retry_count=self.conduct.max_retries + 1,
        )

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 120.0))
                return
            except ValueError:
                pass
        time.sleep(self.conduct.backoff_base_seconds * (2 ** (attempt - 1)))

    def get(self, url: str, **kwargs: Any) -> Fetched:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Fetched:
        return self.request("POST", url, **kwargs)


# ---------------------------------------------------------------------------
# What a scraper produces
# ---------------------------------------------------------------------------
@dataclass
class RawObservation:
    """One price as the portal published it, before any mapping or conversion.

    Deliberately holds the *raw* commodity name and unit. Mapping to a commodity
    slug and converting to the canonical unit happens in `normalize.py`, so a
    parsing bug and a mapping bug stay distinguishable.
    """

    source_slug: str
    region_slug: str
    obs_date: date
    commodity_name_raw: str
    price_raw: float
    unit_raw: str | None
    snapshot_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scraper contract
# ---------------------------------------------------------------------------
class BaseScraper(ABC):
    """Base for every source scraper.

    Subclasses declare `source_slug` and `parser_version`, and implement
    `fetch_day`. `parser_version` must be bumped whenever parsing logic changes:
    it is what allows stored snapshots to be re-parsed later instead of
    re-scraped from an archive that may no longer exist.
    """

    source_slug: str
    parser_version: str

    def __init__(self, conn: Conn, client: PoliteClient, run: Run) -> None:
        self.conn = conn
        self.client = client
        self.run = run
        self.reference = load_reference()
        self.config: SourceConfig = self.reference.source(self.source_slug)
        self.source_id = int(
            fetch_value(conn, "select id from public.sources where slug = %s", (self.source_slug,))
        )

    # -- provenance ---------------------------------------------------------
    def store_snapshot(self, fetched: Fetched) -> int:
        """Persist a response body and return its `raw_snapshots.id`.

        Bodies are gzipped and hashed. When the immediately preceding snapshot
        for the same URL carries an identical hash, the body is not stored a
        second time — the row is still written, so the fetch remains in the
        record, but `body_compressed` is NULL and points at unchanged content.
        Re-running a daily scrape therefore costs a row, not a blob.
        """
        content_hash = hashlib.sha256(fetched.body).hexdigest()
        previous = fetch_value(
            self.conn,
            "select content_hash from public.raw_snapshots "
            "where source_id = %s and url = %s order by fetched_at desc limit 1",
            (self.source_id, fetched.url),
        )
        unchanged = previous == content_hash
        body = None if unchanged else gzip.compress(fetched.body)

        snapshot_id = fetch_value(
            self.conn,
            """
            insert into public.raw_snapshots
                (source_id, url, http_status, content_hash, body_compressed,
                 parser_version, request_headers, byte_size)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (
                self.source_id,
                fetched.url,
                fetched.status_code,
                content_hash,
                body,
                self.parser_version,
                Json({"User-Agent": self.client.user_agent}),
                len(fetched.body),
            ),
        )
        return int(snapshot_id)

    def record_failure(
        self,
        url: str | None,
        error_class: str,
        error_detail: str,
        retry_count: int = 0,
    ) -> None:
        """Write a `fetch_failures` row. Called on every error path, no exceptions."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                insert into public.fetch_failures
                    (source_id, url, error_class, error_detail, retry_count, run_context)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    self.source_id,
                    url,
                    error_class,
                    error_detail[:4000],
                    retry_count,
                    Json({"run_id": self.run.id, "parser_version": self.parser_version}),
                ),
            )
        self.conn.commit()

    def fetch_stored(self, method: str, url: str, **kwargs: Any) -> tuple[Fetched, int]:
        """Fetch, persist the snapshot, and return both. Failures are recorded then re-raised."""
        try:
            fetched = self.client.request(method, url, **kwargs)
        except FetchError as exc:
            self.record_failure(exc.url, exc.error_class, str(exc), exc.retry_count)
            raise
        except Exception as exc:
            self.record_failure(url, type(exc).__name__, str(exc))
            raise
        snapshot_id = self.store_snapshot(fetched)
        self.conn.commit()
        return fetched, snapshot_id

    # -- the thing subclasses implement -------------------------------------
    @abstractmethod
    def fetch_day(self, obs_date: date) -> list[RawObservation]:
        """Return every observation this source published for `obs_date`.

        An empty list means "the source genuinely reported nothing"; it must
        never mean "something went wrong". Errors raise, and the raising path
        has already written a `fetch_failures` row.
        """

    def available_regions(self) -> list[str]:
        return list(self.config.regions)
