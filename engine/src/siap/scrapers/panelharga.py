"""Panel Harga Pangan — Badan Pangan Nasional (Bapanas).

**Currently disabled.** `sources.yaml` carries `is_active: false`, so the daily
run skips this source. The scraper exists anyway, for two reasons: an explicit
`siap ingest --source panelharga` still records a `fetch_failures` row, keeping
the outage visible in the data rather than as an unexplained absence; and when
Bapanas restores service, re-enabling is a one-line configuration change.

### Why it is disabled

Verified in a real browser session on 2026-07-28: **the portal's own frontend is
broken.** It renders a blank page, makes one successful API call, then dies with

    TypeError: Cannot read properties of undefined (reading 'map')

which is the app receiving its own API's 401 and trying to map over a data array
that is not there. Every `/front/*` endpoint answers

    {"status":"error","message":"Unauthorized. Invalid or missing API key."}

including when called with the `x-api-key` embedded in the bundle the site is
currently serving. Ruled out: browser User-Agent, matching Origin and Referer,
`Authorization: Bearer`, alternate header casings, and `api-key` as the header
name. This is an upstream outage or misconfiguration, not an access control
aimed at us.

### What is deliberately not attempted

The bundle also exposes 168 `/cms/*` paths — `report/history-harga`,
`report/pusat/rekapitulasi`, `setting-harga` and so on. Those are the
administrative back-office and are meant to sit behind an admin bearer token.
One of them answers anonymously, which looks like a misconfiguration on their
side. **They are not touched.** Harvesting a government system's admin endpoints
is not data this project is entitled to, and it would poison the provenance
story the whole project rests on. If Panel Harga is wanted, the route is a
written request to Bapanas for API access.

### The contract implemented here

    GET {API}/front/komoditas?level_harga_id=3
    GET {API}/front/harga-pangan-table-v2?level_harga_id=3&tanggal=YYYY-MM-DD
    GET {API}/front/harga-pangan-table-province?...

with `x-api-key` as the frontend sends it. `X-RateLimit-Limit: 60` per minute is
advertised on the responses, so the 2 s global delay is already inside budget.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from .base import BaseScraper, RawObservation

log = logging.getLogger(__name__)

API = "https://api-panelhargav2.badanpangan.go.id/api"

# Public client key lifted from the site's own deployed bundle
# (main.69d329b558fe5803.js). Not a secret: it is served to every visitor. The
# API rejects it as of 2026-07-28, which is precisely the outage described above.
CLIENT_API_KEY = (
    "zHWbt7U2qvPoUDkiUgvnOqYrtj3zClR7unnH2G4apE7HcMV4QyNC6BSD0yV3uvSHqS91"
    "TxwE8aMDTiCznmGceEX3zQmO1Xwq7TJblotIt2CpwvK6YjRKDJwcgMJwav9p4RshM3nf"
    "uFyurSQQv9BhueMJ0HJ778oD"
)

# Bapanas price levels: 1 produsen, 2 grosir, 3 konsumen. A warung owner buys at
# consumer level, so that is the one this project tracks.
LEVEL_HARGA_KONSUMEN = 3

HEADERS = {"Accept": "application/json", "x-api-key": CLIENT_API_KEY}


class PanelhargaScraper(BaseScraper):
    source_slug = "panelharga"
    parser_version = "panelharga-2026-07-28"

    def fetch_day(self, obs_date: date) -> list[RawObservation]:
        """Attempt a day's national + provincial prices.

        Expected to fail while the upstream outage lasts. The failure path in
        `fetch_stored` writes a `fetch_failures` row before re-raising, which is
        the point: a gap in this source's coverage stays explainable.
        """
        fetched, snapshot_id = self.fetch_stored(
            "GET",
            f"{API}/front/harga-pangan-table-v2",
            params={"level_harga_id": LEVEL_HARGA_KONSUMEN, "tanggal": obs_date.isoformat()},
            headers=HEADERS,
        )

        payload = json.loads(fetched.body)
        if payload.get("status") == "error":
            raise ValueError(
                f"panelharga returned an error payload: {payload.get('message')!r}. "
                f"The portal is disabled in sources.yaml pending upstream repair."
            )

        rows = payload.get("data") or []
        observations: list[RawObservation] = []
        for row in rows:
            name = str(row.get("name") or row.get("nama") or "").strip()
            price = row.get("today") if row.get("today") is not None else row.get("harga")
            if not name or price in (None, 0, "-"):
                continue
            observations.append(
                RawObservation(
                    source_slug=self.source_slug,
                    region_slug="nasional",
                    obs_date=obs_date,
                    commodity_name_raw=name,
                    price_raw=float(price),
                    unit_raw=row.get("satuan"),
                    snapshot_id=snapshot_id,
                    extra={"scope": "national", "level_harga_id": LEVEL_HARGA_KONSUMEN},
                )
            )
        return observations
