"""Sistem Informasi Harga Pangan Kota Yogyakarta — Pemkot Yogyakarta.

Laravel application with a DataTables front end.

    GET /harga_pangan?draw=1&start=0&length=100&id_pasar={n}
        with X-Requested-With: XMLHttpRequest
        -> {"tgl_terakhir_verif": ..., "recordsTotal": n, "data": [...]}

    GET /datapasar        market list
    GET /datakomoditas    commodity list

A session cookie is established by first requesting the page; `PoliteClient`
holds one httpx.Client for the process, so cookies persist across calls.

### Forward-only: no historical backfill

The daily endpoint returns only the most recent verified prices — every row
carries the same `tgl_harga_pangan`. History lives behind `POST /statistik`,
which is a *market comparison* view and rejects our requests with
"Silakan pilih pasar lainnya yang ingin dikomparasikan!" regardless of how the
market parameter is supplied.

So `kota_yogyakarta` accumulates forward from first run and has no archive.
Consequences, recorded rather than worked around:
  * M5's STL needs >= 104 weeks and cannot run for this region.
  * The DIY *province* is unaffected — SP2KP and PIHPS both carry 3 years for
    `di_yogyakarta`. Only the city-level series is short.

### Two hazards specific to this source

1. **The `satuan` field is wrong.** Every row reports `satuan.nama_satuan =
   "Kg"`, including `Minyak Goreng Curah,1 lt` and `Minyakita,1 lt`, whose names
   say litre. Cross-source evidence settles it: jogja's curah oil at 19,000
   sits 1.8% from PIHPS DIY (18,655/litre) and 3.8% from SP2KP DIY
   (19,730/litre); reading it as kg and converting would place it ~12% below
   both. **The unit is taken from the name suffix, and `satuan` is ignored.**

2. **Several markets per day.** Beringharjo and Prawirotaman both report, but
   `price_observations` is unique per (commodity, source, region, date). Prices
   are therefore reduced to a **median across markets**, which is the city-level
   figure this project wants — the same shape as siskaperbapo's provincial
   average. The contributing markets are recorded in `extra`.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime

from .base import BaseScraper, RawObservation

log = logging.getLogger(__name__)

ROOT = "https://hargapangan.jogjakota.go.id"
PRICE_ENDPOINT = f"{ROOT}/harga_pangan"
MARKETS_ENDPOINT = f"{ROOT}/datapasar"

AJAX_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": f"{ROOT}/harga_pangan",
}

# Trailing unit in the commodity name: "Cabai Merah Keriting,1 kg",
# "Minyak Goreng Curah,1 lt", "Gula Pasir Curah, 1kg", "Mie Instan, 1 bks".
_NAME_UNIT = re.compile(r",\s*([0-9]*\s*[A-Za-z]+)\s*$")


@dataclass
class _Bucket:
    """Prices for one commodity, gathered across the city's markets."""

    unit: str | None
    obs_date: date
    snapshot_id: int | None
    prices: list[float] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)


class JogjaScraper(BaseScraper):
    source_slug = "jogja"
    parser_version = "jogja-2026-07-29"

    def markets(self) -> list[dict[str, object]]:
        fetched, _ = self.fetch_stored("GET", MARKETS_ENDPOINT, headers=AJAX_HEADERS)
        payload = json.loads(fetched.body)
        markets = payload.get("data") or []
        if not markets:
            raise ValueError("jogja: /datapasar returned no markets")
        return list(markets)

    @staticmethod
    def unit_from_name(name: str) -> str | None:
        """Unit as stated in the commodity name.

        Deliberately preferred over the API's `satuan` field, which reports "Kg"
        for products the same API names "…,1 lt". See the module docstring.
        """
        match = _NAME_UNIT.search(name)
        if not match:
            return None
        return " ".join(match.group(1).split())

    def fetch_day(self, obs_date: date) -> list[RawObservation]:
        """Latest verified prices, reduced to one median figure per commodity.

        `obs_date` is honoured only as a filter: this endpoint publishes the
        current snapshot and cannot be asked for an arbitrary past date. Rows
        whose own `tgl_harga_pangan` differs are dropped rather than being
        relabelled with the requested date, which would fabricate provenance.
        """
        collected: dict[str, _Bucket] = {}

        for market in self.markets():
            market_id = market.get("id_pasar")
            market_name = str(market.get("nama_pasar") or market_id)
            fetched, snapshot_id = self.fetch_stored(
                "GET",
                PRICE_ENDPOINT,
                params={"draw": 1, "start": 0, "length": 200, "id_pasar": market_id},
                headers=AJAX_HEADERS,
            )
            payload = json.loads(fetched.body)
            for row in payload.get("data") or []:
                commodity = row.get("komoditas") or {}
                name = str(commodity.get("nama_komoditas") or "").strip()
                price = row.get("harga_pangan")
                raw_date = row.get("tgl_harga_pangan")
                if not name or price in (None, 0) or not raw_date:
                    continue
                try:
                    row_date = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
                if row_date != obs_date:
                    continue

                bucket = collected.setdefault(
                    name,
                    _Bucket(
                        unit=self.unit_from_name(name),
                        obs_date=row_date,
                        snapshot_id=snapshot_id,
                    ),
                )
                bucket.prices.append(float(price))
                bucket.markets.append(market_name)

        return [
            RawObservation(
                source_slug=self.source_slug,
                region_slug="kota_yogyakarta",
                obs_date=bucket.obs_date,
                commodity_name_raw=name,
                price_raw=statistics.median(bucket.prices),
                unit_raw=bucket.unit,
                snapshot_id=bucket.snapshot_id,
                extra={
                    "markets": bucket.markets,
                    "n_markets": len(bucket.prices),
                    "scope": "city_median_across_markets",
                },
            )
            for name, bucket in collected.items()
        ]
