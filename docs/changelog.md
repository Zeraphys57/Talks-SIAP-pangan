# Changelog and deviations

Running record of what was built, and every place the implementation departs
from the original proposal or the build brief. Deviations are listed with the
reason, so they can be defended rather than discovered.

---

## M4 — Regime clustering (2026-07-29)

K-Means at **commodity x region x month**, 1,644 cells. The full k=2..8 curve is
recorded; zones are assigned post hoc by ranking centroids.

### The silhouette preferred a k that cannot produce the specified output

| k | silhouette | merah / kuning / hijau |
|---:|---:|---|
| 2 | **0.7807** | 70 / **0** / 1574 |
| 3 | 0.6504 | 48 / 194 / 1402 |
| 4 | 0.6097 | 5 / 315 / 1324 |
| 5 | 0.6211 | 7 / 353 / 1284 |

§6.3 says "select by highest silhouette" and "do not force k=3", but also
specifies a three-zone output in which the middle rank becomes `kuning`. With
k=2 those requirements are incompatible: two clusters cannot be ranked into
three zones, so `kuning` was unreachable and **every** cell was merah or hijau.

The failure was not merely cosmetic. k=2 splits "catastrophic" from "everything
else", so `jawa_timur / cabai-rawit-merah / 2026-07` — 5% daily volatility and a
**+25% rise** — landed in the calm cluster and displayed as **hijau**. For a
warung owner that is exactly backwards.

Silhouette optimises separation, not zoning usefulness: isolating the ~4% of
extreme cells is trivially separable and scores well without describing two
meaningful regimes.

**Decision taken at the M4 gate: `k_select_min: 3`.** k=2 is still fitted,
still scored and still appears in the recorded curve and the paper figure — it
is excluded from *selection* only. "Do not force k=3" is read as "do not pin it
at exactly 3"; k remains free to be 3 through 8. The write-up must state that
k=2 scored highest and why it was excluded.

With k=3 the clusters read cleanly, and the misclassified month becomes kuning:

| cluster | volatility | cum_change | cells | zone |
|---:|---:|---:|---:|---|
| 2 | 0.05439 | **+83.36%** | 48 | merah |
| 0 | 0.05492 | −10.31% | 194 | kuning |
| 1 | 0.00893 | +0.35% | 1402 | hijau |

The gate's sanity check passes: beras-medium, beras-premium, gula-pasir and both
oils reach merah **zero** times; cabai occupies 44 of the 48 merah cells.

### Nuance for M8's copy: kuning means unstable, not rising

At k=3 the kuning centroid is *volatile and mildly falling* (−10.31%), because
the severity score weights volatility and direction equally. Both
`cabai-rawit-merah +25.23%` and `bawang-merah −25.36%` land there.

That is defensible — an unstable market is risky to buy into in either
direction — but the dashboard copy must say **"harga tidak stabil"**, not
"harga naik". Labelling a price *crash* as a rising-price warning would be
wrong, and a warung owner would notice.

---

## M3 — Anomaly modules (2026-07-29)

Z-Score and Isolation Forest per §6.1–6.2, 60 series, 78k score rows.
19 detector tests, including synthetic spikes at known indices that both arms
must recover.

### Bug found on real data: a stale source produced z = −20,824,185

The first production run scored |z| in the millions. Cause: M2 recorded that
PIHPS carries values forward between surveys rather than resurveying, and in
2023 it was the **only** source for `jawa_tengah` and `di_yogyakarta`. A 30-day
window over a feed that is repeating itself has a standard deviation of about
1e-16, so the first real movement divides by nearly zero.

Those are not anomalies. A z-score against a baseline that was not updating
measures the source's publication cadence, not the market. Fixed by adding
`zscore.min_baseline_std` (0.0005 in log space — a 0.05% daily sigma, below
which a staple price has effectively not moved for a month): such windows now
score NULL rather than producing an artefact. Regression test pins the exact
shape that caused it.

### A conflict between §6.1 and §7.2, reported rather than improvised around

After the fix, flags were still dominated by trivial price movements. Measured
across the full run:

| method | flags on <1% moves | flags on >=10% moves |
|---|---:|---:|
| zscore | **54.6%** | 7.9% |
| iforest | 36.2% | 17.3% |

The brief defines an anomaly (§7.2) as a change exceeding **±10%** against the
trailing 30-day mean, sustained two days. But §6.1 specifies a detector that
flags at |z| >= 2.5, which corresponds to a 10% move *only when the baseline
standard deviation happens to be about 4%*. On a calm series — and staple foods
under price control are often very calm — 2.5 sigma is a 0.3% move.

**The detector measures statistical unusualness; the ground truth encodes
operational significance.** They are different quantities, and the gap is
structural, not a tuning problem: no choice of threshold fixes a mismatch in the
denominator.

**Nothing was changed in the detector.** Adding a magnitude gate to the Z-Score
arm was considered and rejected, because it would defeat the experiment. The
four ablation arms exist so that `fusion` has to earn its complexity against a
*naive* baseline; quietly making the baseline smarter would rig that comparison.

More to the point, the brief already anticipates this. Fusion's second term is
`M = clip(|pct_change_7d| / 0.15, 0, 1)` — a pure magnitude signal. The
prediction this sets up, which M7 will measure rather than assume:

* `zscore_only` will show **low precision** against the adjudicated ground
  truth, with a ceiling near 8%;
* `fusion` should beat it substantially, and the reason will be attributable to
  `M` specifically.

If fusion does *not* beat it, that is the reportable result.

### Note on Isolation Forest flag counts

Every commodity flags at exactly 3.06%, because `contamination = 0.03` *defines*
the proportion flagged rather than discovering it. The flag count therefore
carries no information about how anomalous a commodity is; only the ranking
within a series does. This is why `norm_score` is a percentile rank, and why M7
sweeps contamination on a held-out split rather than reading anything into the
default.

### Deviation from the brief

| # | Brief says | Built as | Why |
|---|---|---|---|
| 16 | `\|z\| >= 2.5` flags | plus `min_baseline_std` guard | a stale-source baseline of sigma~1e-16 produced z in the millions; the window is now declared unusable instead |
| 17 | Python 3.11 | Python 3.12 floor | numpy's bundled stubs use `type` statement syntax that only parses on 3.12+; claiming 3.11 support we cannot type-check would be worse |

---

## M1 — Ingestion and historical backfill (2026-07-28 → 29)

Reconnaissance came first, per the brief's instruction to verify every URL live
before writing a scraper. Full findings in [`docs/sources.md`](sources.md); the
decisions and surprises are recorded here.

### Outcome per source

| source | result |
|---|---|
| `pihps` | implemented, **3-year archive**, date-range endpoint |
| `siskaperbapo` | implemented, **3-year archive** |
| `sp2kp` | implemented, archive to 2024-02-01 (~130 wk) |
| `jogja` | implemented, **forward-only — no archive exists** |
| `panelharga` | **disabled**, upstream outage |
| `trends` | implemented, currently throttled by Google (429) |

**M5's STL dependency is satisfied**: 157–158 weeks covered for `jawa_tengah`,
`di_yogyakarta` and `jawa_timur`, against a 104-week requirement. Only
`kota_yogyakarta` cannot support seasonality, because its portal exposes no
historical endpoint at all.

### Two judgement calls that changed the plan

**Panel Harga is disabled, and its admin endpoints were left alone.** Its API
returns 401 to the key embedded in its own deployed bundle. A browser session
confirmed the portal itself is broken — blank page, then a crash mapping over
the error object. The bundle also exposes 168 `/cms/*` administrative paths, one
of which answers anonymously. They were not probed. Harvesting a government
system's back-office is not data this project is entitled to, and it would
poison the provenance story the whole project rests on. The correct route, if
Panel Harga is wanted, is a written request to Bapanas.

**The User-Agent now says "UAJY" rather than the university's full name.**
`hargapangan.jogjakota.go.id` returns 403 to any User-Agent containing the word
"Yogyakarta" — verified by bisection; an *anonymous* request succeeds, so this
is not bot-blocking but most likely an anti-impersonation rule. Shortening to
the institution's own standard abbreviation keeps the identification truthful
while clearing the filter. Presenting ourselves as a browser, or dropping the
User-Agent entirely, would have worked too and was rejected: both are evasion.

### Traps from §10, all confirmed live

1. **Three different number conventions.** siskaperbapo writes `"12.508"` for
   twelve thousand five hundred and eight; PIHPS writes `"16,200"` for sixteen
   thousand two hundred; SP2KP and jogja return JSON numbers. `"16,200"` is
   valid under both text conventions and means different things, so
   `number_format` is declared per source and never sniffed.
2. **Unit chaos, in three distinct flavours.** siskaperbapo publishes cooking
   oil per **kg** while our canonical unit is the litre; PIHPS publishes **no
   unit field at all**; jogja's `satuan` field is **wrong**, reporting "Kg" for
   products it names "…,1 lt". All three resolved through configuration
   (`units.yaml`, `default_unit`) rather than in scraper bodies.
3. **Commodity name drift.** Every provisional alias for siskaperbapo and jogja
   was wrong. `daging-sapi` is `Daging Sapi Paha Belakang`, not "Daging Sapi
   Murni"; gula is `Gula Kristal Putih`; jogja names rice by brand
   (`Beras Cap IR 64 (Medium)`). All reconciled against live responses.

### The unit inferences cross-validated each other

Cooking oil ended up as an unintended three-way check. For DI Yogyakarta on
2026-07-28:

| source | Rp/litre | how it was derived |
|---|---:|---|
| jogja | 18,650 | name suffix `1 lt`, taken at face value |
| pihps | 18,655 | no unit field, inferred kg, converted ×0.91 |
| sp2kp | 19,730 | published natively in litres |

jogja and PIHPS agree to **0.03%** through completely independent inference
paths. Had jogja's `satuan` been trusted, it would have read ~16,972 — 9% below
both neighbours.

### Google Trends is currently throttled to zero

Every request on 2026-07-29 returned HTTP 429, across all keywords and both
scopes, through three attempts each with exponential backoff. `demand_signals`
is therefore **empty**, and 24 `fetch_failures` rows record why.

The degradation path works exactly as the brief specifies — the run does not
fail, and fusion's `D` term will evaluate to 0 with a recorded reason. But the
consequence should be stated plainly rather than discovered at M6:

* **The `D` component contributes nothing until Trends succeeds.** Fusion still
  works; it is effectively `0.45·A + 0.25·M + 0.10·C` renormalised, and the
  weight sweep in M7 will show `D`'s contribution as zero rather than small.
* This is a property of the *unofficial wrapper*, not of the method. It may
  clear on a different network or IP, or with a slower cadence.
* If it does not clear, the honest options are to report `D` as unavailable and
  ablate it out, or to substitute a different demand proxy. Quietly leaving a
  weighted term at zero while presenting the formula as four-component would
  misrepresent the model.

### Open questions carried into M2

* **The 0.91 kg/L density constant.** siskaperbapo's per-kg oil implies 0.9446
  against SP2KP's native litre price, while PIHPS implies ~0.91. One day cannot
  separate a systematic constant error from between-market variation; hundreds
  of days can. `unit_factor` is stored per row, so a correction applies
  retroactively without re-scraping.
* **PIHPS runs systematically high**, up to +24% in DI Yogyakarta. Not a unit
  error — those appear as ×10 or ×0.91, not a scattered 5–24%. It reflects a
  small panel concentrated in provincial capitals plus differing quality tiers
  (`Beras Kualitas Medium I` ≠ `Beras Medium`). The median in
  `price_daily_unified` is the designed mitigation; M2's gate inspects it.
* **One-to-many variant mapping.** SP2KP publishes four beef cuts, two garlics,
  three oils. The rule adopted is "first listed alias present in the response
  wins", with the alternatives recorded in the run notes. Whether averaging
  would be better is an M2 question.

### Deviations from the build brief

| # | Brief says | Built as | Why |
|---|---|---|---|
| 11 | scrapers for all four price portals | four implemented, one disabled | panelharga's API is down upstream; reported rather than worked around |
| 12 | 3-year backfill per source | 3 years for pihps/siskaperbapo, ~2.5 for sp2kp, none for jogja | those are the archives that exist; jogja has no historical endpoint |
| 13 | — | `config/units.yaml` added | unit chaos is a named trap and deserves a reviewable table, not constants in code |
| 14 | — | `number_format`, `default_unit` per source | forced by three portals disagreeing on both |
| 15 | — | `siap coverage` command | the M1 gate needs coverage plus provenance samples in one place |

### Environment note: httpx and the CA bundle

httpx verifies against its bundled certifi and ignores `SSL_CERT_FILE`, which
Python's own `ssl` module honours. Behind this machine's TLS-intercepting
antivirus that meant urllib worked and httpx did not. `PoliteClient` now builds
its SSL context from `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` when present.
Verification is never disabled.

---

## M0 — Foundation (2026-07-28)

Repo scaffold, database schema, reference data, connection layer, CLI, tests, CI.

### Corrections applied to the original proposal

These are factual errors in the proposal, corrected in `config/sources.yaml` and
covered by tests in `engine/tests/test_config.py`:

1. **Panel Harga and SP2KP are separate systems.** The proposal treats them as
   one. `panelharga.badanpangan.go.id` belongs to Badan Pangan Nasional;
   `sp2kp.kemendag.go.id` belongs to Kementerian Perdagangan. They are modelled
   as two sources with different owners, scopes and cadences.
2. **SISKAPERBAPO is Jawa Timur, not Jawa Tengah/DIY.** The proposal
   misattributes it. Its declared coverage is `jawa_timur` only.
3. **Google Trends has no official API here.** `pytrends` is an unofficial
   community wrapper around an undocumented endpoint. It is recorded as such and
   treated as best-effort throughout: when it is unavailable the fusion `D`
   component degrades to 0 with a recorded reason rather than failing the run.

### Deviations from the build brief

| # | Brief says | Built as | Why |
|---|---|---|---|
| 1 | Python 3.11 | Python 3.12 (`requires-python = ">=3.11"`) | The only 3.11 on this machine is the Microsoft Store build, whose redirected app-exec path causes venv and file-permission problems on Windows. 3.12 is a real install with full wheel coverage for the scientific stack. Agreed with the team before starting. |
| 2 | (unspecified) Node | Node 22, pinned in `.node-version` | Node 20 reached end of life in April 2026, and the corepack bundled with it cannot launch current pnpm (`ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING`). Next 15 supports Node 22 fully. |
| 3 | `config/{commodities,sources,fusion,analysis}.yaml` | `commodities.yaml`, `regions.yaml`, `sources.yaml` only | Regions are reference data and needed a home; the brief lists the five region slugs but no file for them. `fusion.yaml` and `analysis.yaml` are **not** created yet — they hold parameters for M3–M6 and are written in the milestone that first reads them, so `pip install` at any commit reflects what that commit actually runs. |
| 4 | Repo root `siap-pangan/` | Repo root is `D:\Talks-SIAP` | The working directory was already dedicated to this project; a nested folder would have added a level for nothing. |
| 5 | — | `source_regions` table added | The fusion corroboration term `C` is `n_sources_flagging / n_sources_reporting`. "Reporting" needs a definition that is data, not a hardcoded assumption, so declared coverage is a table. |
| 6 | — | `gt_labeling_queue` view added | §7.1 requires annotators to be unable to tell which stratum a candidate came from. A view that projects away `sampling_stratum` enforces that at the database layer rather than trusting the UI. |
| 7 | — | `gt_candidates.shuffle_key` added | Same requirement. Deterministic shuffle position from the configured seed, so the two strata interleave reproducibly. |
| 8 | — | `evaluation_results.split` added | §10 warns against tuning thresholds on the labels you report against. Recording `dev` vs `test` on every metric row makes that leakage visible instead of merely discouraged. |
| 9 | — | `commodities.price_{min,max}_plausible` added | §10's unit-chaos trap. A missed litre/kg conversion produces a 10x "anomaly" that looks like a finding. Normalization raises outside the band. |
| 10 | — | `CommodityConfig.unavailable_at` added | Distinguishes "this portal genuinely does not publish this commodity" from "we have no alias mapping yet". Without it, the two are indistinguishable and a missing mapping looks like missing data. |

### Deliberate non-corrections

- **Slug conventions differ**: commodity slugs are hyphenated
  (`cabai-rawit-merah`), region slugs use underscores (`di_yogyakarta`). This is
  what the brief specifies in §4 and §8.3, and it is preserved rather than
  "fixed" — commodity slugs appear in public URLs, region slugs do not.

### Design choices worth recording

- **`sus_score` is a generated column**, computed by Postgres from `q1..q10`
  rather than supplied by the client. The SUS formula cannot then drift between
  the form, the analysis and the paper.
- **`gt_labels` grants INSERT but not SELECT** to authenticated users. Two
  annotators working blind to each other is a stated requirement; making a
  colleague's labels unreadable through the API is a stronger guarantee than
  omitting them from the UI. Cohen's kappa is computed by the engine under the
  service role.
- **Cooking oils are canonicalised to litres**, everything else to kilograms.
  Most portals publish Rp/litre for `minyak goreng`; the minority publishing
  Rp/kg are converted with an explicit `unit_factor` recorded per observation.
- **Migration checksums are LF-normalised** so a Windows checkout does not trip
  the drift guard.

### Supabase project

Provisioned on 2026-07-28. PostgreSQL 17.6.

- **Region is `ap-northeast-1` (Tokyo)**, not Singapore. Functionally fine; it
  costs roughly 40–60 ms of extra round-trip latency from Indonesia. Not worth
  recreating the project over, but if the M8 dashboard feels sluggish on a phone
  this is the first thing to look at.
- Connection uses the **session pooler on port 5432**. The direct host
  (`db.<ref>.supabase.co`) is IPv6-only on new projects and unreachable from
  most Indonesian home ISPs; the transaction pooler on 6543 cannot run DDL.

### RLS was proven, not assumed

`siap doctor` initially reported four passing "anon cannot read X" checks while
those tables were empty — which proves nothing, since an empty table returns
zero rows to everyone. Two things were done about it:

1. A one-off probe inserted real rows into `raw_snapshots`, `gt_candidates` and
   `sus_responses` through the service-role connection, confirmed the anon key
   still saw **0 rows** in each while a control read of `commodities` returned
   rows, then deleted the probe rows and verified the counts were back to zero.
   Nothing was written to any price table, so no value that could be mistaken
   for a real observation ever existed.
2. `check_anon_access_live` now counts each restricted table through the service
   role and labels the result *"table is EMPTY, so this pass is vacuous"* when
   applicable. A check that cannot fail should not look like a check that
   passed.

### Environment note: TLS interception

This machine runs AVG, which intercepts HTTPS and re-signs it with
`CN=AVG Web/Mail Shield Root`. That CA is trusted by Windows but absent from
Python's `certifi` bundle and Node's built-in store, so `pip install` and
`pnpm install` both failed certificate verification.

Resolved by *adding* the CA rather than disabling verification:

```
C:\Users\bryan\.certs\ca-bundle-with-avg.pem   = certifi bundle + AVG root CA
pip   -> pip config set global.cert <bundle>   (persisted in pip.ini)
node  -> NODE_EXTRA_CA_CERTS=<bundle>          (per-shell)
```

`--trusted-host` and `NODE_TLS_REJECT_UNAUTHORIZED=0` were both avoided: this
project scrapes government portals, and turning off certificate checking in the
same toolchain would be a poor habit to establish.

The bundle is machine-specific and lives outside the repo. A teammate on a
machine without interception needs none of this.
