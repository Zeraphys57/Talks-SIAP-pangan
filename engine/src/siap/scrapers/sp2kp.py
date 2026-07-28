"""SP2KP — Kementerian Perdagangan.

Endpoints (observed in a live browser session, 2026-07-28; see docs/sources.md):

    GET /master/api/variant?take=99999&tipe_komoditas_id=1&is_active=true
        Commodity variants with their units.

    GET /report/api/average-price/province-comparison?variant_id={v}&tanggal={d}
        One price per province (37 of them) for one commodity on one day.

    GET /report/api/hnt/history-series?tanggal_start={a}&tanggal_end={b}&variant_id={v}
        National weighted-average (HNT) daily series across a date range. This is
        the backfill path: one request covers years instead of one day.

Unauthenticated. The reCAPTCHA Enterprise script on the web UI guards the
feedback survey and login, not this API.

Provinces are matched on BPS code (`kode_provinsi`), which is the same code
stored in `regions.bps_code` — matching on province *name* would break the first
time someone writes "D.I. Yogyakarta" instead of "DI Yogyakarta".
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from .base import BaseScraper, RawObservation

log = logging.getLogger(__name__)

API = "https://api-sp2kp.kemendag.go.id"

# tipe_komoditas_id=1 is the "barang kebutuhan pokok" group shown on the public
# dashboard; other ids cover construction materials and agricultural inputs.
KOMODITAS_TYPE_POKOK = 1


class Sp2kpScraper(BaseScraper):
    source_slug = "sp2kp"
    parser_version = "sp2kp-2026-07-28"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._variants: list[dict[str, Any]] | None = None
        self._resolved: dict[str, dict[str, Any]] | None = None

        # BPS code -> our region slug, for the provinces we actually track.
        self._province_by_bps = {
            r.bps_code: r.slug
            for r in self.reference.regions
            if r.level == "province" and r.bps_code and r.slug in self.config.regions
        }

    # -- variant discovery --------------------------------------------------
    def variants(self) -> list[dict[str, Any]]:
        """Fetch the active commodity variant list once per scraper instance."""
        if self._variants is not None:
            return self._variants
        url = f"{API}/master/api/variant"
        fetched, _ = self.fetch_stored(
            "GET",
            url,
            params={
                "take": 99999,
                "tipe_komoditas_id": KOMODITAS_TYPE_POKOK,
                "is_active": "true",
            },
            headers={"Accept": "application/json"},
        )
        payload = json.loads(fetched.body)
        items = payload.get("data", payload)
        if isinstance(items, dict):
            items = items.get("items") or items.get("data") or []
        if not isinstance(items, list) or not items:
            raise ValueError(f"unexpected variant payload from {url}: {str(payload)[:200]}")
        self._variants = items
        return items

    def resolved_variants(self) -> dict[str, dict[str, Any]]:
        """Map our commodity slug -> the single SP2KP variant we ingest.

        Applies the "first listed alias present in the response wins" rule from
        commodities.yaml. Alternatives that exist but were not chosen are noted
        on the run, so the decision is visible rather than implicit.
        """
        if self._resolved is not None:
            return self._resolved

        by_name = {" ".join(str(v.get("nama", "")).split()).casefold(): v for v in self.variants()}
        resolved: dict[str, dict[str, Any]] = {}
        skipped: list[str] = []

        for commodity in self.reference.commodities:
            aliases = commodity.source_aliases.get(self.source_slug, [])
            chosen: dict[str, Any] | None = None
            for alias in aliases:
                candidate = by_name.get(" ".join(alias.split()).casefold())
                if candidate is not None:
                    if chosen is None:
                        chosen = candidate
                    else:
                        skipped.append(f"{commodity.slug}: not used -> {alias}")
            if chosen is None:
                self.run.note(
                    f"sp2kp: no variant matched for {commodity.slug}; "
                    f"tried {aliases}. The portal may have renamed it."
                )
                continue
            resolved[commodity.slug] = chosen

        if skipped:
            self.run.note("sp2kp canonical variant choices — " + "; ".join(sorted(skipped)))

        self._resolved = resolved
        return resolved

    @staticmethod
    def _unit_of(variant: dict[str, Any]) -> str | None:
        satuan = variant.get("satuan")
        if isinstance(satuan, dict):
            display = satuan.get("display")
            return str(display) if display else None
        return str(satuan) if satuan else None

    # -- provincial ---------------------------------------------------------
    def fetch_day(self, obs_date: date) -> list[RawObservation]:
        """Provincial prices for every resolved commodity, plus the national series."""
        observations: list[RawObservation] = []
        for variant in self.resolved_variants().values():
            observations.extend(self._fetch_provinces(variant, obs_date))
        observations.extend(self.fetch_national_range(obs_date, obs_date))
        return observations

    def _fetch_provinces(self, variant: dict[str, Any], obs_date: date) -> list[RawObservation]:
        fetched, snapshot_id = self.fetch_stored(
            "GET",
            f"{API}/report/api/average-price/province-comparison",
            params={"variant_id": variant["id"], "tanggal": obs_date.isoformat()},
            headers={"Accept": "application/json"},
        )
        payload = json.loads(fetched.body)
        data = payload.get("data") or {}
        items = data.get("items") or []
        unit = self._unit_of(variant)
        name = str(variant.get("nama", ""))

        out: list[RawObservation] = []
        for item in items:
            region_slug = self._province_by_bps.get(str(item.get("kode_provinsi")))
            if region_slug is None:
                continue  # a province we do not track
            price = item.get("harga")
            if price is None:
                continue  # genuinely not reported that day; a gap, not a failure
            out.append(
                RawObservation(
                    source_slug=self.source_slug,
                    region_slug=region_slug,
                    obs_date=obs_date,
                    commodity_name_raw=name,
                    price_raw=float(price),
                    unit_raw=unit,
                    snapshot_id=snapshot_id,
                    extra={"variant_id": variant["id"], "scope": "province"},
                )
            )
        return out

    # -- national -----------------------------------------------------------
    def fetch_national_range(self, start: date, end: date) -> list[RawObservation]:
        """National HNT series over a date range — one request per commodity.

        This is what makes the backfill affordable: three years of national
        history for twelve commodities costs twelve requests, not thirteen
        thousand.
        """
        observations: list[RawObservation] = []
        for variant in self.resolved_variants().values():
            fetched, snapshot_id = self.fetch_stored(
                "GET",
                f"{API}/report/api/hnt/history-series",
                params={
                    "variant_id": variant["id"],
                    "tanggal_start": start.isoformat(),
                    "tanggal_end": end.isoformat(),
                },
                headers={"Accept": "application/json"},
            )
            payload = json.loads(fetched.body)
            points = payload.get("data") or []
            unit = self._unit_of(variant)
            name = str(variant.get("nama", ""))

            for point in points:
                raw_date = point.get("tanggal_data")
                price = point.get("harga")
                if not raw_date or price is None:
                    continue
                observations.append(
                    RawObservation(
                        source_slug=self.source_slug,
                        region_slug="nasional",
                        obs_date=date.fromisoformat(str(raw_date)[:10]),
                        commodity_name_raw=name,
                        price_raw=float(price),
                        unit_raw=unit,
                        snapshot_id=snapshot_id,
                        extra={"variant_id": variant["id"], "scope": "national"},
                    )
                )
        return observations
