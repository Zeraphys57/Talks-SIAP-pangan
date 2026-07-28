"""Scraper-level behaviour that does not need a network or a database.

Parsing is separated from fetching in every scraper precisely so it can be
tested against captured payloads — which is also what makes stored snapshots
re-parsable under a new parser_version without re-scraping.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from siap.config import load_reference
from siap.ingest import _chunks
from siap.scrapers.base import RobotsPolicy


# ---------------------------------------------------------------------------
# robots.txt semantics (RFC 9309)
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """Stands in for httpx.Client, returning one canned robots.txt."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def get(self, url: str, timeout: float = 0) -> _FakeResponse:
        return self._response


@pytest.mark.parametrize(
    ("status", "body", "allowed"),
    [
        # 4xx is "unavailable" -> the crawler may access resources.
        (404, "", True),
        (403, "", True),
        (410, "", True),
        # 5xx is "unreachable" -> assume complete disallow.
        (500, "", False),
        (503, "", False),
        # A real robots.txt is obeyed.
        (200, "User-agent: *\nAllow: /\n", True),
        (200, "User-agent: *\nDisallow: /\n", False),
    ],
)
def test_robots_status_semantics(status: int, body: str, allowed: bool) -> None:
    policy = RobotsPolicy(user_agent="SIAP-PANGAN/0.1")
    client = _FakeClient(_FakeResponse(status, body))
    assert policy.can_fetch(client, "https://example.invalid/data") is allowed  # type: ignore[arg-type]


def test_spa_shell_is_not_mistaken_for_a_robots_file() -> None:
    """Several portals answer any unknown path with their HTML shell.

    Parsing that as robots.txt would find no directives and allow everything —
    the right answer, but for the wrong reason, and it would hide the fact that
    the site publishes no policy at all.
    """
    policy = RobotsPolicy(user_agent="SIAP-PANGAN/0.1")
    client = _FakeClient(_FakeResponse(200, "<!doctype html><html><head><title>App</title>"))
    assert policy.can_fetch(client, "https://example.invalid/data") is True
    assert "SPA shell" in policy.reason("https://example.invalid/data")


def test_disallowed_reason_is_reported_for_5xx() -> None:
    policy = RobotsPolicy(user_agent="SIAP-PANGAN/0.1")
    client = _FakeClient(_FakeResponse(503))
    assert policy.can_fetch(client, "https://example.invalid/x") is False
    assert "disallow all" in policy.reason("https://example.invalid/x")


# ---------------------------------------------------------------------------
# Backfill chunking
# ---------------------------------------------------------------------------
def test_chunks_cover_the_period_exactly_without_overlap() -> None:
    windows = _chunks(date(2024, 1, 1), date(2024, 1, 10), 4)
    assert windows == [
        (date(2024, 1, 1), date(2024, 1, 4)),
        (date(2024, 1, 5), date(2024, 1, 8)),
        (date(2024, 1, 9), date(2024, 1, 10)),
    ]


def test_chunks_returns_the_whole_range_when_unlimited() -> None:
    assert _chunks(date(2024, 1, 1), date(2026, 1, 1), None) == [
        (date(2024, 1, 1), date(2026, 1, 1))
    ]


def test_single_day_range_is_one_chunk() -> None:
    assert _chunks(date(2024, 5, 5), date(2024, 5, 5), 120) == [
        (date(2024, 5, 5), date(2024, 5, 5))
    ]


# ---------------------------------------------------------------------------
# PIHPS parsing, against a captured payload shape
# ---------------------------------------------------------------------------
PIHPS_PAYLOAD = json.dumps(
    {
        "data": [
            # level 1 is a group heading and must be skipped, or the group is
            # counted a second time alongside its own members.
            {"no": "I", "name": "Beras", "level": 1, "27/07/2026": "16,200"},
            {
                "no": 1,
                "name": "Beras Kualitas Medium I",
                "level": 2,
                "27/07/2026": "16,400",
                "28/07/2026": "16,200",
            },
            # "-" means the market did not report: a gap, not a zero.
            {
                "no": 2,
                "name": "Cabai Rawit Merah",
                "level": 2,
                "27/07/2026": "-",
                "28/07/2026": "54,350",
            },
        ]
    }
).encode()


def test_pihps_parse_skips_group_headings_and_missing_days() -> None:
    from siap.scrapers.pihps import PihpsScraper

    rows = PihpsScraper.parse(PihpsScraper, PIHPS_PAYLOAD, "jawa_tengah")  # type: ignore[arg-type]
    names = {r.commodity_name_raw for r in rows}
    assert "Beras" not in names, "level-1 group heading was ingested"
    assert names == {"Beras Kualitas Medium I", "Cabai Rawit Merah"}

    by_key = {(r.commodity_name_raw, r.obs_date): r.price_raw for r in rows}
    assert by_key[("Beras Kualitas Medium I", date(2026, 7, 27))] == "16,400"
    assert ("Cabai Rawit Merah", date(2026, 7, 27)) not in by_key  # the "-" day
    assert by_key[("Cabai Rawit Merah", date(2026, 7, 28))] == "54,350"


def test_pihps_parse_leaves_unit_to_configuration() -> None:
    """PIHPS emits no unit; the scraper must not invent one per row."""
    from siap.scrapers.pihps import PihpsScraper

    rows = PihpsScraper.parse(PihpsScraper, PIHPS_PAYLOAD, "jawa_tengah")  # type: ignore[arg-type]
    assert all(r.unit_raw is None for r in rows)
    assert load_reference().source("pihps").default_unit == "kg"


def test_pihps_province_ids_are_the_verified_ones() -> None:
    """Regression guard: 15 vs 26 tie on Beras and were separated empirically."""
    from siap.scrapers.pihps import PROVINCE_ID

    assert PROVINCE_ID == {"jawa_tengah": 14, "di_yogyakarta": 15, "jawa_timur": 16}


# ---------------------------------------------------------------------------
# Every implemented scraper is registered and declares its identity
# ---------------------------------------------------------------------------
def test_registered_scrapers_declare_slug_and_parser_version() -> None:
    from siap.ingest import SCRAPERS

    for slug, cls in SCRAPERS.items():
        assert cls.source_slug == slug, f"{cls.__name__} slug mismatch"
        assert cls.parser_version, f"{cls.__name__} has no parser_version"


def test_every_registered_scraper_exists_in_sources_yaml() -> None:
    from siap.ingest import SCRAPERS

    known = {s.slug for s in load_reference().sources}
    assert set(SCRAPERS) <= known, f"unknown source slugs: {set(SCRAPERS) - known}"


def test_panelharga_is_registered_but_inactive() -> None:
    """Registered so an explicit run records a failure; inactive so daily skips it."""
    from siap.ingest import SCRAPERS

    assert "panelharga" in SCRAPERS
    assert load_reference().source("panelharga").is_active is False
