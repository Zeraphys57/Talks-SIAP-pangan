"""SISKAPERBAPO — Dinas Perindustrian dan Perdagangan, Pemprov Jawa Timur.

East Java, **not** Jawa Tengah / DIY as the original proposal states.

Endpoint (discovered in the inline `LoadPage()` handler on /harga/tabel):

    POST /harga/tabel.nodesign/
    body: tanggal=YYYY-MM-DD & kabkota= & pasar=

`.nodesign` returns the price table without page chrome. Empty `kabkota` and
`pasar` give the provincial average, which is the level this project needs.
A companion `GET /harga/pasar.json/{kabkota}` lists markets per kabupaten/kota.

Archive verified back three years (2023-07-28 returns populated data), which is
what makes M5's STL decomposition possible at all.

Parsing notes
-------------
Each price row carries two figures, distinguished by CSS class rather than
column position:

    <td class="right kemarin">14.999</td>   previous day
    <td class="right sekarang">15.000</td>  the requested date   <-- this one

Positional parsing would silently ingest yesterday's price the first time
someone inserts a column. The commodity name sits in a nested span:

    <td> - <span data-commodity-id='2'>Beras Premium</span> </td>

Group headers ("01 BERAS") share the same table but have no leading dash and
carry zeros, so item rows are identified by the leading "-".

This portal publishes 67 items including cement, rebar, nails and fertiliser.
Rows that do not map to one of our 12 commodities are ignored — they are out of
scope, not missing data. The "something went missing" check is the inverse:
`normalize` verifies every commodity we *expect* from this source was found.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawObservation

log = logging.getLogger(__name__)

BASE = "https://siskaperbapo.jatimprov.go.id"
TABLE_ENDPOINT = f"{BASE}/harga/tabel.nodesign/"

# Item rows begin with a dash; group headers do not.
_ITEM_PREFIX = re.compile(r"^\s*-\s*")


class SiskaperbapoScraper(BaseScraper):
    source_slug = "siskaperbapo"
    parser_version = "siskaperbapo-2026-07-28"

    def fetch_day(self, obs_date: date) -> list[RawObservation]:
        fetched, snapshot_id = self.fetch_stored(
            "POST",
            TABLE_ENDPOINT,
            data={"tanggal": obs_date.isoformat(), "kabkota": "", "pasar": ""},
            headers={
                "Accept": "text/html, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        return self.parse(fetched.body, obs_date, snapshot_id)

    def parse(
        self, body: bytes, obs_date: date, snapshot_id: int | None = None
    ) -> list[RawObservation]:
        """Parse a `.nodesign` table fragment.

        Split out from fetching so stored snapshots can be re-parsed under a new
        `parser_version` without touching the network.
        """
        soup = BeautifulSoup(body, "lxml")
        observations: list[RawObservation] = []

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            name_cell = cells[1]
            name_text = name_cell.get_text(" ", strip=True)
            if not _ITEM_PREFIX.match(name_text):
                continue  # a group header such as "01 BERAS"

            # Prefer the span, which holds the name without the leading dash.
            span = name_cell.find("span", attrs={"data-commodity-id": True})
            if isinstance(span, Tag):
                commodity_name = span.get_text(" ", strip=True)
            else:
                commodity_name = _ITEM_PREFIX.sub("", name_text).strip()
            if not commodity_name:
                continue

            price_cell = row.find("td", class_="sekarang")
            if not isinstance(price_cell, Tag):
                # No current-day figure at all. A gap, not a failure.
                continue
            price_text = price_cell.get_text(" ", strip=True)
            if not price_text or price_text.strip("0.,-") == "":
                continue  # zero or blank: not reported that day

            unit = cells[2].get_text(" ", strip=True) or None

            observations.append(
                RawObservation(
                    source_slug=self.source_slug,
                    region_slug="jawa_timur",
                    obs_date=obs_date,
                    commodity_name_raw=commodity_name,
                    # Kept as text: parsing Indonesian number format is
                    # normalize.py's job and is unit-tested there.
                    price_raw=price_text,
                    unit_raw=unit,
                    snapshot_id=snapshot_id,
                    extra={
                        "commodity_id_source": span.get("data-commodity-id")
                        if isinstance(span, Tag)
                        else None,
                        "scope": "province_average",
                    },
                )
            )

        return observations
