"""PIHPS Nasional — Bank Indonesia.

Endpoint (observed in a live browser session, 2026-07-29):

    GET /hargapangan/WebSite/TabelHarga/GetGridDataDaerah
        ?price_type_id=1        1 = pasar tradisional (consumer level)
        &comcat_id=             empty = every commodity group
        &province_id={id}       BI's own numbering, see PROVINCE_ID below
        &regency_id=&market_id= empty = province-wide average
        &tipe_laporan=1         1 = laporan harian
        &start_date=YYYY-MM-DD&end_date=YYYY-MM-DD

Returns a **pivoted** grid: one row per commodity, with one column per date.

    {"data": [
      {"no": "I", "name": "Beras",                  "level": 1, "27/07/2026": "16,200"},
      {"no": 1,   "name": "Beras Kualitas Medium I","level": 2, "27/07/2026": "16,400"}
    ]}

`level` 1 rows are group headings and are skipped; `level` 2 rows are the
commodities. A "-" value means the market did not report that day, which is a
gap rather than a failure.

Because the endpoint accepts a date range, backfilling years costs one request
per province rather than one per day.

Two source-specific hazards, both handled through sources.yaml rather than here:

  * **Number format.** PIHPS writes "16,200" for sixteen thousand two hundred —
    the opposite convention to siskaperbapo's "12.508". Declared as
    `number_format: en`.
  * **No unit field.** PIHPS publishes no unit at all. Declared as
    `default_unit: kg`, inferred from a same-region same-day comparison (gula
    pasir reads within 0.1% of siskaperbapo's per-kg figure). Recorded as an
    inference to be confirmed in M2.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from .base import BaseScraper, RawObservation

log = logging.getLogger(__name__)

GRID = "https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataDaerah"

PRICE_TYPE_PASAR_TRADISIONAL = 1
LAPORAN_HARIAN = 1

# BI's internal province numbering, which is NOT the BPS code stored in
# regions.bps_code. Established empirically on 2026-07-29 by cross-matching the
# by-province grid against the by-commodity grid, which carries province names.
#
# 15 needed disambiguating from 26: both tie at Beras = 14,400. Nine other
# commodities separate them decisively — Daging Ayam reads 36,250 for id 15 and
# 24,000 for id 26, matching DI Yogyakarta and Sulawesi Selatan respectively.
PROVINCE_ID: dict[str, int] = {
    "jawa_tengah": 14,
    "di_yogyakarta": 15,
    "jawa_timur": 16,
}

_DATE_COLUMN = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_NO_DATA = {"-", "", "0"}


class PihpsScraper(BaseScraper):
    source_slug = "pihps"
    parser_version = "pihps-2026-07-29"

    def fetch_day(self, obs_date: date) -> list[RawObservation]:
        return self.fetch_range(obs_date, obs_date)

    def fetch_range(self, start: date, end: date) -> list[RawObservation]:
        """Every tracked province over a date range — one request per province."""
        observations: list[RawObservation] = []
        for region_slug in self.config.regions:
            province_id = PROVINCE_ID.get(region_slug)
            if province_id is None:
                self.run.note(f"pihps: no province_id known for {region_slug}; skipped")
                continue
            fetched, snapshot_id = self.fetch_stored(
                "GET",
                GRID,
                params={
                    "price_type_id": PRICE_TYPE_PASAR_TRADISIONAL,
                    "comcat_id": "",
                    "province_id": province_id,
                    "regency_id": "",
                    "market_id": "",
                    "tipe_laporan": LAPORAN_HARIAN,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                },
                headers={"Accept": "application/json"},
            )
            observations.extend(self.parse(fetched.body, region_slug, snapshot_id))
        return observations

    def parse(
        self, body: bytes, region_slug: str, snapshot_id: int | None = None
    ) -> list[RawObservation]:
        """Un-pivot the grid into one observation per commodity per date.

        Split from fetching so stored snapshots can be re-parsed under a new
        parser_version without going back to the network.
        """
        payload = json.loads(body)
        rows = payload.get("data") or []
        observations: list[RawObservation] = []

        for row in rows:
            # level 1 is a group heading ("Beras"); only level 2 rows are
            # commodities. Ingesting the heading would double-count the group.
            if row.get("level") != 2:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue

            for key, value in row.items():
                if not _DATE_COLUMN.match(key):
                    continue
                text = str(value).strip()
                if text in _NO_DATA:
                    continue  # not reported that day
                try:
                    obs_date = datetime.strptime(key, "%d/%m/%Y").date()
                except ValueError:
                    continue

                observations.append(
                    RawObservation(
                        source_slug=self.source_slug,
                        region_slug=region_slug,
                        obs_date=obs_date,
                        commodity_name_raw=name,
                        price_raw=text,
                        # PIHPS publishes no unit; sources.yaml declares the
                        # assumption, so normalization applies it in one place.
                        unit_raw=None,
                        snapshot_id=snapshot_id,
                        extra={"scope": "province_average"},
                    )
                )

        return observations
