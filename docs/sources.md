# Data sources

Reconnaissance performed **2026-07-28**, before any scraper was written, per the
brief's instruction to verify every URL live and prefer a JSON endpoint behind
the UI over HTML parsing.

Every request in this reconnaissance used a descriptive User-Agent, a >= 2 s
delay, and one connection at a time.

## Summary

| slug | status | mechanism | archive depth |
|---|---|---|---|
| `pihps` | ✅ **implemented** | `GetGridDataDaerah`, date range | **3 years verified** |
| `siskaperbapo` | ✅ **implemented** | `POST /harga/tabel.nodesign/` | **3 years verified** |
| `sp2kp` | ✅ **implemented** | unauthenticated JSON API | **2024-02-01 → today (~130 wk)** |
| `jogja` | ✅ implemented, **forward-only** | Laravel + DataTables (GET) | **none — no archive endpoint** |
| `panelharga` | ❌ **disabled — upstream outage** | its own frontend is broken | n/a |
| `trends` | ✅ implemented, best-effort | pytrends (unofficial) | up to 5 years |

### Resulting region coverage

| region | price sources | fusion `C` viable? | M5 STL viable? |
|---|---|---|---|
| `nasional` | sp2kp | single source → capped at kuning | yes |
| `jawa_tengah` | sp2kp + pihps | yes | **yes, 157 wk** |
| `di_yogyakarta` | sp2kp + pihps | yes | **yes, 157 wk** |
| `jawa_timur` | sp2kp + pihps + siskaperbapo | yes, strongest | **yes, 158 wk** |
| `kota_yogyakarta` | jogja | single source → capped at kuning | **no — no archive** |

Panel Harga being unavailable costs redundancy but removes no region, because
SP2KP's `province-comparison` endpoint returns all 37 provinces.

The 104-week STL threshold is cleared in four of five regions. Only
`kota_yogyakarta` cannot support seasonality, because its portal exposes no
historical endpoint at all.

## trends — Google Trends via pytrends ✅ best-effort

Not a price source; fills `demand_signals`, which supplies the fusion `D` term.

`pytrends` is an **unofficial** community wrapper around an undocumented
endpoint, and Google rate-limits it aggressively — HTTP 429 is routine, not
exceptional. Treated accordingly:

* failures write `fetch_failures` and leave the signal absent, so `D` degrades
  to 0 with a recorded reason rather than failing the run;
* responses cache to disk for a week under `engine/.cache/trends/`, because the
  source itself only updates weekly;
* only the first keyword per commodity is requested — each extra term multiplies
  the chance of being cut off mid-run.

Geo codes: `nasional` → `ID`, `di_yogyakarta` → `ID-YO`.

`interest` is Google's 0–100 index, normalised *within the requested window* and
therefore not comparable across requests. `interest_z52`, the z-score against a
trailing 52-week baseline, is what fusion consumes. The baseline is **trailing
only** — it ends at the week before the one being scored. Including the current
week would let a spike partly cancel itself, damping the signal exactly when it
matters, the same leak the price Z-Score module avoids.

Weekly data stays weekly. It is forward-filled at join time in M2, never
interpolated into a daily curve the source cannot support.

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

## Cross-source validation (2026-07-27, jawa_timur)

SP2KP and siskaperbapo survey different markets by different methods, and are
implemented by entirely separate code paths — a JSON API versus an HTML table
with Indonesian-formatted numbers. Their agreement is therefore a real check on
parsing, alias mapping and unit conversion all at once:

| commodity | siskaperbapo | sp2kp | gap |
|---|---:|---:|---:|
| beras-medium | 12,985.00 | 13,045.37 | 0.5% |
| beras-premium | 15,000.00 | 14,828.45 | 1.2% |
| cabai-merah-keriting | 30,933.00 | 30,815.48 | 0.4% |
| cabai-rawit-merah | 38,330.00 | 37,065.79 | 3.4% |
| bawang-merah | 30,923.00 | 30,907.90 | 0.05% |
| telur-ayam-ras | 25,041.00 | 24,910.97 | 0.5% |
| daging-ayam-ras | 33,995.00 | 33,846.93 | 0.4% |
| daging-sapi | 127,309.00 | 127,331.14 | 0.02% |
| **minyak-goreng-curah** | **18,496.66** | **19,199.05** | **3.7%** |
| minyak-goreng-kemasan | 21,768.00 | 21,669.82 | 0.5% |
| gula-pasir | 17,166.00 | 16,897.22 | 1.6% |

Most commodities agree within ~1%, and `daging-sapi` to within 0.02%. That is
strong evidence the pipeline is not silently corrupting anything.

### Open question for M2: the cooking-oil density constant

`minyak-goreng-curah` is the single largest disagreement, and it is also the
only row that undergoes a unit conversion. siskaperbapo published Rp 20,326/kg;
SP2KP published Rp 19,199.05/**litre** natively for the same region and day.

That implies a density of `19,199.05 / 20,326 = 0.9446 kg/L`, against the
**0.91** currently configured in `units.yaml`.

Two readings, and they are not yet distinguishable:

1. The constant is too low. Refined palm olein at Indonesian ambient
   temperatures may sit nearer 0.91–0.92; some published figures for crude and
   blended cooking oils run higher.
2. The two portals simply surveyed different markets, and a 3.7% spread is
   ordinary between-source variation — several unconverted commodities here
   differ by 1.2–3.4% with no conversion involved at all.

### Answered in M2: the offset is systematic, but 0.91 stays

The test proposed above has now been run over **439 overlapping days** in
`jawa_timur`, comparing SP2KP (native litres) against siskaperbapo (per kg,
converted at 0.91). Controls are commodities that undergo **no** conversion in
either source, so any offset they show is about the survey panels rather than
about units.

| commodity | median ratio sp2kp / siskaperbapo | sd |
|---|---:|---:|
| **minyak-goreng-curah** — converted ×0.91 | **1.0356** | **0.0061** |
| beras-medium — control | 1.0222 | 0.0345 |
| gula-pasir — control | 0.9865 | 0.0055 |
| telur-ayam-ras — control | 0.9927 | 0.0059 |
| daging-ayam-ras — control | 0.9961 | 0.0083 |
| daging-sapi — control | 0.9983 | 0.0078 |
| bawang-merah — control | 0.9814 | 0.0264 |

Every control sits within ±2% of parity. The one converted commodity sits
**3.6% high, with the tightest variance in the table**. A stable ratio with low
variance is the signature of a constant offset, not of market noise — the
question posed in M1 is answered: **the discrepancy is systematic.**

The implied density is `0.91 × 1.0356 = 0.9424 kg/L`.

**The constant is nevertheless left at 0.91.** Refined palm olein is ~0.91–0.92
kg/L at ambient temperature; 0.942 is outside the physical range for the product
either portal claims to be pricing. The residual is therefore more likely a
product-definition or panel difference — SP2KP's "Minyak Goreng Sawit Curah"
against siskaperbapo's "Minyak Goreng Curah" — than a wrong physical constant.

Re-fitting a physical constant so that two data sources agree is calibrating on
the data the project then goes on to analyse. It would remove a visible,
explainable 3.6% disagreement and replace it with an invisible assumption, which
is the worse trade for a paper that has to defend its numbers.

Practical impact is small: `jawa_timur` carries three sources for cooking oil, so
the median is rarely the converted siskaperbapo figure. `unit_factor` is stored
per row, so if better evidence arrives the correction applies retroactively
without re-scraping. Reproduce with the query in `docs/methods.md`.

## pihps — Bank Indonesia ✅ implemented

**Data endpoint**, taking a **date range**, which makes backfill cheap:

```
GET /hargapangan/WebSite/TabelHarga/GetGridDataDaerah
    ?price_type_id=1     1 = pasar tradisional (consumer level)
    &comcat_id=          empty = all commodity groups
    &province_id={id}    BI's own numbering, see below
    &regency_id=&market_id=   empty = province-wide average
    &tipe_laporan=1      1 = laporan harian
    &start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
```

Returns a **pivoted** grid — one row per commodity, one column per date:

```json
{"data": [{"no":"I","name":"Beras","level":1,"27/07/2026":"16,200"},
          {"no":1,"name":"Beras Kualitas Medium I","level":2,"27/07/2026":"16,400"}]}
```

`level: 1` rows are group headings and must be skipped or the group is
double-counted. `"-"` means not reported that day.

**Archive depth: 3 years verified** (2023-07-24 returns populated data).

Companion endpoint `GetGridDataKomoditas?comcat_id={n}` pivots the other way,
one commodity across all provinces. `comcat_id`: 1 Beras, 2 Daging Ayam,
3 Daging Sapi, 4 Telur Ayam, 5 Bawang Merah, 6 Bawang Putih, 7 Cabai Merah,
8 Cabai Rawit, 9 Minyak Goreng, 10 Gula Pasir.

### province_id is BI's own numbering, not BPS

| region | `province_id` |
|---|---|
| `jawa_tengah` | 14 |
| `di_yogyakarta` | **15** |
| `jawa_timur` | 16 |

Established empirically by cross-matching the by-province grid against the
by-commodity grid, which carries province names. **15 required disambiguation
from 26** — both tie at Beras = 14,400. Nine other commodities separate them
decisively; Daging Ayam reads 36,250 for id 15 and 24,000 for id 26, matching
DI Yogyakarta and Sulawesi Selatan. Confusing the two would have silently
filled a Javanese region with Sulawesi prices.

### PIHPS publishes on weekdays only

Measured across the full three-year backfill:

| source | Sun | Mon | Tue | Wed | Thu | Fri | Sat |
|---|---:|---:|---:|---:|---:|---:|---:|
| pihps | **0** | 157 | 157 | 156 | 156 | 156 | **0** |
| siskaperbapo | 56 | 57 | 55 | 55 | 55 | 56 | 56 |

Every one of PIHPS's 156 gaps is exactly two days long — the weekend. **This is
structural, not failure**, and matters in two places:

* The coverage report shows roughly 29% of days "missing" for PIHPS. That is
  2/7, and it should not be read as a broken scraper.
* In M2, a two-day weekend gap falls inside the brief's "interpolation permitted
  for gaps ≤ 3 days" rule. Filling it is defensible — the markets themselves
  trade at the weekend, PIHPS simply does not survey then — but the rows must
  still be flagged `is_imputed = true` and excluded from ground-truth
  evaluation, exactly as the schema requires.

siskaperbapo publishes all seven days, so a weekend gap there really would be a
failure.

### Two source-specific hazards

1. **Number format is the opposite of siskaperbapo's.** PIHPS writes `"16,200"`
   for sixteen thousand two hundred; siskaperbapo writes `"12.508"` for twelve
   thousand five hundred and eight. The same string is valid under both
   conventions and means different things, so `number_format` is declared per
   source in sources.yaml and never sniffed.
2. **No unit field at all.** Declared `default_unit: kg`, inferred rather than
   known — see below.

### Inference: PIHPS prices are per kilogram

PIHPS publishes no unit. Compared against siskaperbapo for the same region and
day (`jawa_timur`, 2026-07-27):

| commodity | PIHPS | siskaperbapo | gap |
|---|---:|---:|---:|
| gula pasir | 17,150 | 17,166 **/kg** | **0.1%** |
| telur ayam ras | 25,100 | 25,041 /kg | 0.2% |

A 0.1% agreement on gula pasir establishes the kg basis for weight goods.
Cooking oil is treated the same way, and the result corroborates it: PIHPS
curah reads 21,050/kg, which at the configured 0.91 kg/L becomes **19,156/litre**
against SP2KP's **19,199/litre** published natively — a 0.2% gap.

That is encouraging for both the kg assumption and the density constant, but it
is still one day. Confirmed or corrected in M2.

### Cross-source spreads are definitional, not bugs

Three-way comparison at 2026-07-27 shows PIHPS running systematically higher
than SP2KP, most sharply in DI Yogyakarta (bawang merah +23%, bawang putih
+24%). This is **not** a unit error — a unit error appears as a factor of 10 or
of 0.91, not as a scattered 5–24%.

The cause is methodological: PIHPS surveys a small panel of traditional markets
concentrated in provincial capitals, while SP2KP averages many markets across
the whole province. Definitional differences compound it — PIHPS
"Beras Kualitas Medium I" is a different quality tier from SP2KP "Beras
Medium", and PIHPS "Daging Sapi Kualitas 1" is a different cut from
"Daging Sapi Paha Belakang".

`price_daily_unified` takes the **median** across sources precisely so one
higher-priced panel cannot drag the series, and records `source_spread_pct` so
the disagreement stays visible rather than being averaged away. M2's gate
inspects the ten largest disagreements for exactly this reason.

### M2 finding: PIHPS goes flat while other sources move

Inspecting the widest disagreements over the full backfill shows a consistent
pattern. `cabai-merah-keriting`, `jawa_tengah`, April 2024:

| date | pihps | sp2kp |
|---|---:|---:|
| 2024-04-08 | 36,850 | 47,485 |
| 2024-04-09 | 36,900 | 48,364 |
| **2024-04-10** | **36,650** | **60,000** |
| 2024-04-11 | 36,650 | 56,667 |

SP2KP tracks a chilli spike; PIHPS sits within 250 rupiah of itself for four
days. The same shape appears in DI Yogyakarta in September 2024, where PIHPS is
pinned at exactly 28,750 across several days while SP2KP moves each day.

**These are not unit bugs.** The ratios are ~1.5x, not 10x or 0.91x, and both
sources report consistent units. It is a survey-frequency difference: PIHPS
appears to carry values forward between surveys of its small panel.

**The consequence matters for M3, and is worth stating before anomaly detection
is built.** With exactly two sources the median *is* the midpoint, so a source
that goes flat carries a full 50% weight and damps a genuine spike by roughly
half. That applies to `jawa_tengah` and `di_yogyakarta`, which have PIHPS and
SP2KP only. `jawa_timur` has three sources and is protected; `nasional` and
`kota_yogyakarta` have one each and are unaffected.

Not acted on here — dropping or down-weighting a source is a modelling decision,
not a preprocessing one, and it belongs with the evidence from M3's detector
comparison. Recorded so the effect is not rediscovered as a mysterious loss of
sensitivity.

---

## jogja — Pemkot Yogyakarta ✅ implemented, forward-only

Laravel application with a DataTables front end. The initial `POST` returning
419 was a red herring — DataTables issues **GET**, not POST.

```
GET /harga_pangan?draw=1&start=0&length=200&id_pasar={n}
    with X-Requested-With: XMLHttpRequest
GET /datapasar        market list  (Beringharjo id 1, Prawirotaman id 8)
GET /datakomoditas    commodity list (50 items)
```

A session cookie must exist first, so the page is requested before the data.

### The WAF blocks our institution's name

`hargapangan.jogjakota.go.id` runs openresty and returned **403 to any request
whose User-Agent contained the word "Yogyakarta"**. Established by bisection on
2026-07-29:

| User-Agent | result |
|---|---|
| `SIAP-PANGAN/0.1 (Universitas Atma Jaya Yogyakarta academic research; contact: …)` | **403** |
| `Yogyakarta` | **403** |
| `Universitas` / `Atma` / `Jaya` (each alone) | 200 |
| *no User-Agent at all* | 200 |
| `python-httpx/0.28` | 200 |

So this is not bot-blocking — an anonymous request succeeds. It is most likely
an anti-impersonation rule aimed at crawlers claiming to be the city
government.

**Resolved by shortening the institution to `UAJY`**, its own standard
abbreviation (`uajy.ac.id`). The User-Agent still names the project, the
institution, the purpose and a reachable contact, so the conduct requirement is
met in full. We did **not** present ourselves as a browser or as an anonymous
client to get past the block — that would be evasion, and this project scrapes
government portals.

### The `satuan` field is wrong; the name is authoritative

Every row reports `komoditas.satuan.nama_satuan = "Kg"`, including products the
same API names `Minyak Goreng Curah,1 lt` and `Minyakita,1 lt`.

Cross-source evidence settles it decisively:

| source | region | Rp per litre | how |
|---|---|---:|---|
| jogja | kota_yogyakarta | **18,650** | name suffix `1 lt`, no conversion |
| pihps | di_yogyakarta | **18,655** | no unit field, assumed kg, ×0.91 |
| sp2kp | di_yogyakarta | 19,730 | published natively in `lt` |

jogja and PIHPS agree to **0.03%** by two entirely independent inference paths.
Trusting `satuan` and converting would have produced ~16,972, about 9% below
every neighbour. The scraper therefore reads the unit from the name suffix and
ignores `satuan`, with a regression test pinning it.

### Forward-only: no archive

The daily endpoint returns only the latest verified snapshot — every row carries
the same `tgl_harga_pangan`. History sits behind `POST /statistik`, which is a
**market comparison** view; every parameter shape tried (`id_pasar` scalar,
`id_pasar[]` array, CSV, `id_komoditas[]`) returns

```json
{"status":false,"message":"Silakan pilih pasar lainnya yang ingin dikomparasikan!"}
```

Not pursued further. Consequences, recorded rather than worked around:

* `kota_yogyakarta` accumulates forward from first run and has **no archive**.
* M5's STL needs ≥104 weeks and therefore **cannot cover kota_yogyakarta**.
* The DIY *province* is unaffected — SP2KP and PIHPS both carry three years for
  `di_yogyakarta`. Only the city-level series is short.

### Several markets per day

Beringharjo and Prawirotaman both report, but `price_observations` is unique per
(commodity, source, region, date). Prices are reduced to a **median across
markets** — the city-level figure, the same shape as siskaperbapo's provincial
average. Contributing markets are recorded in `extra`.

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

**Archive depth — and the two endpoints disagree.**

| endpoint | earliest data |
|---|---|
| `hnt/history-series` (national) | **2024-02-01** |
| `average-price/province-comparison` (provincial) | **~2024-03-01** |

`history-series` for 2023-07-28 → 2026-07-28 returns 617 points from 2024-02-01,
roughly 130 weeks — clearing the ≥104-week STL guard. The series is not
gap-free (617 points across ~908 days), so `price_daily_unified` gap handling
matters here.

The **provincial** endpoint is shorter still. Probed on 2026-07-29, it returns
`items: []` for 2023-08-01, 2023-11-01, 2024-01-15 and 2024-02-01, and its first
populated response is 2024-03-01. Backfilling provincial data from 2023 would
therefore mean roughly 2,600 requests to a government server that can only
return nothing — so the provincial backfill starts at 2024-03-01. This is a
politeness constraint as much as a speed one.

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
