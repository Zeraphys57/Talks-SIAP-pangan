# Data sources

Reconnaissance performed **2026-07-28**, before any scraper was written, per the
brief's instruction to verify every URL live and prefer a JSON endpoint behind
the UI over HTML parsing.

Every request in this reconnaissance used a descriptive User-Agent, a >= 2 s
delay, and one connection at a time.

## Summary

| slug | status | mechanism | archive depth |
|---|---|---|---|
| `sp2kp` | ✅ **confirmed working** | clean unauthenticated JSON API | **2024-02-01 → today (~130 wk)** |
| `siskaperbapo` | ✅ **confirmed working** | `POST /harga/tabel.nodesign/` | **3 years verified** |
| `pihps` | ✅ viable | `GET /hargapangan/WebSite/TabelHarga/GetGridDataDaerah` | not yet measured |
| `jogja` | ⚠️ needs session handling | Laravel + CSRF token (bare POST → HTTP 419) | not yet measured |
| `panelharga` | ❌ **blocked — upstream outage** | its own frontend is broken; see below | unknown |
| `trends` | not yet attempted | pytrends | n/a |

### Resulting region coverage

| region | sources | fusion `C` viable? |
|---|---|---|
| `nasional` | sp2kp | single source → capped at kuning |
| `jawa_tengah` | sp2kp + pihps | yes |
| `di_yogyakarta` | sp2kp + pihps | yes |
| `jawa_timur` | sp2kp + pihps + siskaperbapo | yes, strongest |
| `kota_yogyakarta` | jogja | single source → capped at kuning |

Panel Harga being unavailable costs redundancy but does not remove any region,
because SP2KP's `province-comparison` endpoint returns all 37 provinces.

## robots.txt

| slug | result | interpretation |
|---|---|---|
| `pihps` | 200, real file. `Allow: /`, disallows only SharePoint internals | `/hargapangan` permitted |
| `panelharga` | 200 but returns the SPA shell — no robots.txt exists | RFC 9309: allow |
| `sp2kp` | 200 but returns the SPA shell — no robots.txt exists | RFC 9309: allow |
| `siskaperbapo` | 404 | RFC 9309 "unavailable" → allow |
| `jogja` | 403 | RFC 9309 "unavailable" → allow; the 403 suggests a WAF |

RFC 9309 §2.3.1.3: a 4xx response means the crawler may access resources; a 5xx
means assume complete disallow. Nothing here disallows the paths we need.

---

## siskaperbapo — Pemprov Jawa Timur ✅

The one source fully verified end to end so far.

**Endpoint.** `POST https://siskaperbapo.jatimprov.go.id/harga/tabel.nodesign/`
with form-encoded body:

| field | meaning | example |
|---|---|---|
| `tanggal` | observation date, `YYYY-MM-DD` | `2023-07-28` |
| `kabkota` | kabupaten/kota id; empty = provincial average | `` |
| `pasar` | market id; empty = all markets | `` |

Discovered in the inline `LoadPage()` handler on `/harga/tabel`. A companion
endpoint `GET /harga/pasar.json/{kabkota}` returns the market list as JSON.

`.nodesign` returns the table fragment without page chrome — roughly 30 KB and
87 `<tr>` per request, versus the full page.

**Archive depth: confirmed at 3 years.** `tanggal=2023-07-28` returns populated
data, not an empty template. This is the single most important finding of the
reconnaissance, because STL in M5 needs >= 104 weeks and cannot be satisfied by
forward scraping.

**Price level.** The table header reads *"Harga Rata-Rata Provinsi Jawa Timur di
Tingkat Konsumen"* — consumer level, which is the correct level for a UMKM
buyer. Each row carries the previous day's price, the current price, the
absolute difference and the percentage change.

**obs_date convention.** The requested `tanggal` is echoed in the table header,
so a row returned for date *D* describes prices reported for *D*. WIB.

### Confirmed data hazards

Real rows from `2023-07-28`, which validate three of the brief's §10 traps:

```
- Beras Premium                    | kg      | 12.508 | 12.506 | -3   | -0,02%
- Gula Kristal Putih               | kg      | 13.347 | 13.347 | 0    |  0,00%
- Minyak Goreng Curah              | kg      | 15.031 | 15.035 | 5    |  0,03%
- Minyak Goreng Kemasan Premium    | 1 liter | 19.767 | 19.767 | 0    |  0,00%
- Daging Sapi Paha Belakang        | kg      | 116.461| 116.461| 0    |  0,00%
- Daging Ayam Kampung              | ekor    | 66.105 | 66.012 | -93  | -0,14%
```

1. **Unit chaos is real.** This portal publishes `Minyak Goreng Curah` in
   **kg**, while our canonical unit for cooking oil is the litre. A
   `unit_factor` is mandatory here, not hypothetical. `Daging Ayam Kampung` is
   priced **per ekor**, exactly as the brief warned — it is not one of our 12
   commodities, but it proves the hazard exists in this table.
2. **Name drift is real.** `Gula Kristal Putih` (not "Gula Pasir"),
   `Daging Sapi Paha Belakang` (our seeded aliases were "Daging Sapi Murni" /
   "Daging Sapi Has" — neither matches, so normalization would have raised,
   which is the designed behaviour). `commodities.yaml` must be reconciled
   against this list before ingestion.
3. **Indonesian number formatting.** `12.508` is twelve thousand five hundred
   and eight, not 12.508. `-0,02%` uses a decimal comma. Parsing this with a
   naive `float()` produces a 1000x error that would look exactly like an
   anomaly.

---

## pihps — Bank Indonesia ✅ viable

**Table pages**, one per price level and pivot:

```
/hargapangan/TabelHarga/PasarTradisionalDaerah      <- consumer level, by region
/hargapangan/TabelHarga/PasarTradisionalKomoditas
/hargapangan/TabelHarga/PasarModernDaerah
/hargapangan/TabelHarga/PedagangBesarDaerah
/hargapangan/TabelHarga/ProdusenDaerah
```

`PasarTradisionalDaerah` is the correct one for this project: traditional
market, consumer level.

**Data endpoint.** The page loads its grid from
`GET /hargapangan/WebSite/TabelHarga/GetGridDataDaerah` (DevExtreme data
source). Parameters not yet mapped.

---

## jogja — Pemkot Yogyakarta ⚠️

Laravel application. A bare `POST /harga_pangan` returns **HTTP 419 (Page
Expired)**, which is Laravel's CSRF rejection. Ingestion therefore needs a
session: fetch the page, read the `csrf-token` meta tag and the `XSRF-TOKEN`
cookie, then post with both. Standard, but it makes this scraper stateful in a
way the others are not.

Other endpoints seen: `/harga_pangan/perubahan_hari_ini`, `/statistik`.
`/datapasar` returns 404 from outside the app context.

---

## sp2kp — Kementerian Perdagangan ✅ best source

Initially looked hostile: a Nuxt SPA with 146 chunks that loads
`recaptcha/enterprise.js`. Observing a real browser session settled it — the
reCAPTCHA guards the feedback survey and login, **not** the data API, which is
a clean unauthenticated REST service on a separate host.

**Base:** `https://api-sp2kp.kemendag.go.id`

| endpoint | purpose |
|---|---|
| `GET /master/api/variant?take=99999&tipe_komoditas_id=1&is_active=true` | commodity variants + units (56 active) |
| `GET /master/api/komoditas?...&tipe_komoditas_id=1&is_active=true` | commodity groups |
| `GET /master/api/wilayah/provinsi?` | province list |
| `GET /report/api/latest-price-dates?tipe_komoditas_id=1` | most recent available dates |
| `GET /report/api/average-price/province-comparison?variant_id={v}&tanggal={d}` | **per-province daily price, all 37 provinces** |
| `GET /report/api/hnt/history-series?tanggal_start={a}&tanggal_end={b}&variant_id={v}` | **national daily series over a date range** |

Verified from plain Python with no cookies, no `Referer`, and our own
User-Agent: HTTP 200 on every one of these.

**Archive depth.** Requesting `history-series` for 2023-07-28 → 2026-07-28
returns 617 points, the earliest being **2024-02-01**. That is roughly 130
weeks, which clears the >= 104-week STL guard in M5. The series is not
gap-free — 617 points across ~908 days — so `price_daily_unified` gap handling
matters here.

**Response shape** (`province-comparison`):

```json
{"status":"success","data":{"tanggal":"2026-07-28","tanggal_sebelumnya":"2026-06-26",
 "variant_id":51,"variant_nama":"Beras Premium",
 "items":[{"kode_provinsi":"11","nama_provinsi":"Aceh",
           "harga":16236.727272727272,"harga_sebelumnya":15914.77,"disparitas_pct":2.02}]}}
```

Prices arrive as unrounded floats (an average across markets), not the
dot-separated strings siskaperbapo returns. Two different parsing paths.

### variant_id map for our 12 commodities

| our slug | SP2KP variant | id | unit |
|---|---|---|---|
| `beras-medium` | Beras Medium | 52 | kg |
| `beras-premium` | Beras Premium | 51 | kg |
| `cabai-merah-keriting` | Cabai Merah Keriting | 2 | kg |
| `cabai-rawit-merah` | Cabai Rawit Merah | 10 | kg |
| `bawang-merah` | Bawang Merah | 13 | kg |
| `bawang-putih` | Bawang Putih Honan / Kating | 38 / 39 | kg |
| `telur-ayam-ras` | Telur Ayam Ras | 25 | kg |
| `daging-ayam-ras` | Daging Ayam Ras | 27 | kg |
| `daging-sapi` | Daging Sapi Paha Belakang | 19 | kg |
| `minyak-goreng-curah` | Minyak Goreng Sawit Curah | 16 | **lt** |
| `minyak-goreng-kemasan` | Minyak Goreng Sawit Kemasan Premium / Minyakita | 17 / 18 | **lt** |
| `gula-pasir` | Gula Pasir Curah / Kemasan | 14 / 15 | kg |

Three of these are one-to-many (`bawang-putih`, `minyak-goreng-kemasan`,
`gula-pasir`), and `daging-sapi` has four cuts. Which variant is canonical, or
whether they are averaged, is a preprocessing decision for M2 and must be
recorded there rather than chosen silently in a scraper.

SP2KP publishes cooking oil in **`lt`**, which confirms the litre canonical unit
chosen in `commodities.yaml`. It also carries `Daging Ayam Kampung` per
**`ekor`**, `Mie Instan` per `bks` and `Susu Bubuk` per `400gr` — the §10 unit
trap is live in this API, even though none of those three are among our 12.

---

## panelharga — Badan Pangan Nasional ❌ blocked

The most important source for this project — it is the only one covering
`nasional`, `jawa_tengah`, `di_yogyakarta` and `jawa_timur` together — and it is
currently unusable.

**What was found.** The site is an Angular SPA. Its bundle
(`main.69d329b558fe5803.js`, 1.59 MB) contains:

```js
apiURL: "https://api-panelhargav2.badanpangan.go.id/api"
```

and 200 distinct endpoint paths, of which these are public:

```
/front/harga-pangan-table-v2        /front/komoditas
/front/harga-pangan-table-province  /front/harga-pangan-bulanan-v2
/front/harga-pangan-informasi       /front/harga-peta-provinsi
/front/table-rekapitulasi           /provinces
```

`/front/harga-pangan-bulanan-v2` in particular looks like the monthly series a
backfill would want.

**Why it is blocked.** Every one of those endpoints returns:

```
HTTP 401  {"status":"error","message":"Unauthorized. Invalid or missing API key."}
```

The bundle embeds an `x-api-key` (160 chars, appearing twice). **That key is
rejected by the API.** The bundle we analysed is confirmed to be the one
currently deployed — the hash referenced by the live `index.html` matches the
file we downloaded — so this is not a stale-cache artefact on our side.

Tested and ruled out: browser User-Agent, `Origin` and `Referer` matching the
site, `Authorization: Bearer <key>`, alternate header casings, and `api-key` as
the header name. The `privateKey: "04062023$@Bapanas"` constant is used only for
AES-encrypting localStorage, not for request signing, and the app registers no
HTTP interceptor that injects credentials.

Response headers reveal `X-RateLimit-Limit: 60` (per minute), so the API is rate
limited and would need throttling once access is resolved.

**Resolved by browser observation (2026-07-28).** Loading the portal in Chrome
and watching the network and console settles it: **the public site itself is
broken.** It renders a blank page, issues exactly one successful API call
(`/api/cms/komoditas-pusat`, 200) and then dies with:

```
Error fetching data from API: TypeError: Cannot read properties of undefined (reading 'map')
    at panelharga.badanpangan.go.id/3108.7efa3f31e0502d4d.js
```

That is the app receiving the 401 error object and trying to `.map()` over a
data array that is not there. This is an upstream outage or misconfiguration at
Bapanas, not an access-control measure aimed at us, and not something on our
side to fix.

**Deliberately not worked around.** The bundle also exposes 168 `/cms/*` paths —
`report/history-harga`, `report/pusat/rekapitulasi`, `setting-harga` and so on.
Those are the administrative back-office and are meant to sit behind an admin
bearer token. They were **not** probed. One of them (`/cms/komoditas-pusat`)
answers anonymously, which looks like a misconfiguration on their side, but
harvesting a government system's admin endpoints is not data this project is
entitled to, and doing so would poison the provenance story the whole project
rests on. If Panel Harga is wanted later, the route is a written request to
Bapanas for API access, not a louder scraper.

**Plan.** Implement the scraper against the documented `/front/*` contract and
leave the source `is_active = false`. Every attempt writes a `fetch_failures`
row, so the outage is visible in the data rather than silently absent. Re-check
periodically; if it recovers, flip the flag.
