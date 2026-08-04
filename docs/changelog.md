# Changelog and deviations

Running record of what was built, and every place the implementation departs
from the original proposal or the build brief. Deviations are listed with the
reason, so they can be defended rather than discovered.

---

## Incident — the schedule ran pre-M10 code against an M10 schema (2026-08-04)

Migration `0011` was applied to production on 2026-07-30 17:31 UTC, narrowing
`alerts_level_known` to `tenang/waspada/siaga/belum_dapat_dinilai`. The M10
commits that emit that vocabulary were never pushed, so GitHub Actions kept
checking out `7a734fb`, where `LEVELS = ("hijau", "kuning", "merah")`. Every
scheduled `siap fuse` from run #79 onward violated the constraint.

The control is unusually clean: same database, same evening. Fusion #69 (17:44)
and #72 (17:54) ran M10 code and succeeded; #79 (20:23) ran the CI checkout and
failed. #88, #95, #102 and #109 followed. `alerts` was last written by run #72 —
39,173 rows, `obs_date` ending 2026-07-29 — so the dashboard served six-day-old
levels while reporting nothing wrong.

**The constraint worked. The reporting did not.** Every module closes its run
from a `finally`, but `Run.finish` issued its UPDATE on the same connection,
which a constraint violation had already put in INERROR. The UPDATE was refused,
the row stayed `running`, and the failure read as a hang until the next day's
`siap runs --close-stale 6` swept it. `finish` now rolls back an aborted
transaction before recording the status; `start_run` commits the run row, so
there is nothing else to lose. Covered by `engine/tests/test_runs.py`.

Two lessons kept rather than fixed silently:

- **A migration applied by hand to production is a deploy.** Schema moved on one
  path (local `siap migrate`) and code on another (`git push`), and nothing
  compared them. `siap doctor` checks the schema against the catalog, not the
  schema against the code that writes to it.
- **`running` is not a state a dead process can report.** Any status that
  depends on the failing process still being alive will be wrong exactly when it
  matters; `close_stale` is the backstop, not the mechanism.

No ground-truth labels existed at any point during this window, so nothing
downstream of `gt_labels` is affected.

---

## M10 — Two vocabularies, a provenance gate, and three measurements (2026-07-31)

### The zone and the level stopped sharing words

`cluster_assignments.zone` and `alerts.level` were both `merah/kuning/hijau`,
and both render on the commodity page. They are different quantities — the zone
is a monthly K-Means regime, the level a daily fusion score — and they disagree
on **22.6% of 39,089 pairs**, including 272 cells where the zone reads `merah`
while the level on the same screen reads `hijau`.

The zone keeps the colour words: proposal Tujuan 3 commits in writing to K-Means
producing "zona strategis (merah, kuning, hijau)". Fusion carries no such
commitment, so fusion moved: `hijau → tenang`, `kuning → waspada`,
`merah → siaga`. This also closes the last place design.md's "never encode
meaning by colour alone" was satisfied on a technicality — the rule was met by
printing a text label, but the label *was* a colour word.

### A fourth state, on both

`anomaly_term` ended in `max(scores) if scores else 0.0`, so a date neither
detector could score produced A = 0.0 — indistinguishable from a date both
examined and found calm — and rendered as "tidak ada yang tidak biasa".
`alerts.level` gains `belum_dapat_dinilai`, outside the severity ordering, with
`fusion_score` NULL and no recommendation. 348 rows change, all from `tenang`.

**Correction to the diagnosis that prompted this:** the 41.31% (`nasional`) and
13.66% (`di_yogyakarta`) figures are the *z-score* NULL rates, not this code
path. Those dates still had an Isolation Forest score. The path fires where
*neither* detector scored: 1.18% / 0.90% / 0.89% / 0.64%, and 100% of
`kota_yogyakarta` — which was exact.

### Provenance gate on cluster cells (migration 0011)

Cells are excluded from the fit on **where their numbers came from**, never on
the feature value: real observation count, distinct real values, share of
observations inside a 7-day carry-forward run, and imputed share. A volatility
threshold was rejected — it cannot separate a genuinely stable price from a
stuck feed, so it would suppress real stable commodities to hide a data problem.

Checked against the 36 zero-volatility cells: the gate catches **36 of 36**, all
as `insufficient_distinct_values`. None were genuinely stable.

Gated cells keep their row with `zone = NULL` and a `quality_reason`. This
replaces `min_days_in_month`, which silently dropped thin months and made
coverage unreportable. Coverage is now 1,485 / 1,692 (87.8%), and uneven:
jawa_timur 97.3%, jawa_tengah 93.7%, di_yogyakarta 65.1%, kota_yogyakarta 0%.

### Measurement 1 — volatility now divides by √(days elapsed)

Excluding imputed rows made a Friday→Monday step a single 3-day return, whose
variance is ~3× a 1-day return. Unnormalised, that inflated σ by ≈1.73× on those
steps — and the steps cluster by region. jawa_timur's mean gap is exactly 1.000
days (ratio 1.000, the control); di_yogyakarta's is 1.373 (ratio **1.228**). All
regions enter one K-Means, so DIY looked ~23% more volatile than Jatim partly
because of publication timing. 137 of 1,485 fitted cells (9.23%) move to a
calmer zone, concentrated in DIY (19.72%) against Jatim (5.32%).

### Measurement 2 — the k floor is removed

Run #64's curve: **k=2 at 0.8037** against k=3 at 0.7224. The forcing was doing
real damage. But removing the floor on the raw features selects k=2, which has
no middle rank and makes `kuning` unreachable — breaking the same Tujuan 3
commitment invoked above. Measurement 1 dissolves the conflict: with normalised
returns **k=3 wins outright, 0.8019 against 0.7984**. The floor is gone and k is
selected. If future data selects k=2, two zones is the honest output.

### Measurement 3 — z-score window 30 → 45 calendar days

`nasional` scored NULL on 41.31% of dates, **91.4% of them the observation floor**
rather than a stale baseline, and flagged 5.74% against 7.86–9.43% elsewhere: it
looked calm and was unmeasured. At 45 days, NULLs fall to 5.69% and flagging
rises to 8.43%. jawa_timur moves 1.84% → 1.82% — the evidence this corrected an
artefact rather than loosened a standard. **The 20-observation floor was not
lowered.** Documented deviation; the M7 pool survives because the §7.1
annotation criterion is independent of the detector.

### Open, recorded rather than silently resolved

**Zone ranking is not monotone in volatility.** `kuning` now holds the most
violently moving months in the archive (0.13386 daily σ) while `merah` averages
0.03691, because severity is `0.5·z(volatility) + 0.5·z(cum_change)` and the
signed `cum_change` dominates. The dashboard renders those 21 cells as "tidak
seliar kelompok merah", which is the opposite of true. The weights were never
tuned. Whether severity should be composite at all is an open decision.

**The headline silhouette is dominated by one cluster.** 0.8019 is a weighted
mean in which 95.69% of cells sit in the cluster scoring 0.8235; the two
alerting clusters score 0.3570 and 0.2546. Any quality claim must cite the
composition table, not the single number.

Re-run: analyze #70, cluster #71, fuse #72.

---

## M9 — Reproducibility (2026-07-29)

The determinism claim is now checked rather than asserted. `siap reproduce`
reloads a run's **own recorded** parameters and seed — not the current
`analysis.yaml`, which may legitimately have moved — recomputes every score from
`price_daily_unified`, and diffs them row by row at the precision the database
stores.

**Result: run #47, 60 series, 78,274 scores, every one identical.** Including
IsolationForest, which was the arm that could plausibly have failed.

Then verified again from a throwaway virtualenv built only from
`requirements.lock` — same 78,274, same result. That tests the reproduction
instructions rather than just publishing them.

### Two bugs the verifier found, both in the verifier

Worth recording because they are the two ways this kind of check goes wrong.

**It reported 5,272 false mismatches on the first run.** Stored `None` against
recomputed `NaN`: the same fact, since a score inside the 30-day warm-up is not
a number and is persisted as NULL. Worse, `Decimal("NaN") != Decimal("NaN")`, so
every warm-up row appeared to mismatch *itself*. A verifier that cries wolf gets
ignored.

**It initially had nothing to check.** Run selection required
`status = 'success'`, but every anomaly run is `partial` — 12 Kota Yogyakarta
series have one week of history against IsolationForest's 60-row minimum. A
verifier that silently passes because it inspected nothing is worse than no
verifier, since it converts an unchecked claim into a checked-looking one. Both
failure modes now have tests.

### Comparison is exact, deliberately

No tolerance. Floating point is deterministic for a fixed sequence of operations
on fixed inputs, so a score differing in the twelfth decimal under the same seed
and data means something genuinely non-deterministic — thread scheduling, hash
ordering, an unseeded RNG. A tolerance would hide precisely the bug this exists
to find.

Version drift is reported but does not fail the check: determinism is about the
numbers, and the remedy for drift is to cite the versions the run recorded.

### Dependencies are pinned twice, on purpose

`pyproject.toml` keeps compatible ranges — a security patch to httpx should not
need a commit. `requirements.lock` records the 57 exact versions a number came
from, because `>=1.5` does not identify the scikit-learn that produced a figure.
Both are true at once. Tests assert every analysis library is pinned and that no
entry uses anything but `==`.

### The daily pipeline only ingested

`daily.yml` collected prices and stopped. Nothing re-ran `preprocess`,
`analyze`, `cluster`, `seasonal` or `fuse`, so a scheduled deployment would have
served a dashboard whose alerts never moved past whenever someone last ran the
engine by hand.

Added as a separate `analyse` job with `needs: ingest` and deliberately **not**
`if: always()`. `preprocess` truncates and rewrites the unified series, and
doing that on top of a failed ingest would rebuild everything from data nobody
checked. Yesterday's alerts staying up is the correct failure mode; alerts
recomputed from a partial day are not. Both jobs now install from the lock, so a
scheduled run cannot silently pick up a new scikit-learn and move the numbers
with nothing in the repository to explain it.

### Documentation that was referenced but did not exist

`docs/methods.md` was cited from five places — `docs/sources.md`,
`analysis.yaml`, `fusion.yaml`, `cluster.py` and `0004_analysis.sql` — and had
never been written. `docs/reproducibility.md` was listed in the README. Both now
exist, and every `docs/*.md` reference in the repository resolves.

`docs/reproducibility.md` states what is *not* reproducible as plainly as what
is: scraping (portals revise), Google Trends (throttled), the ground truth (two
people are not a deterministic process), and wall-clock-dependent dashboard
output. A reproducibility document claiming everything reproduces is not
credible.

---

## M8 — Public dashboard (2026-07-29)

`docs/design.md` written first, as the M0 placeholder promised, so the
components implement a stated position rather than improvise one. Region
chooser, per-region alert board, commodity detail with chart, seasonal weeks,
regime zone and provenance.

### The two copy traps, now enforced in one file

Both were identified during M6 and would have been easy to get wrong:

**`kuning` does not mean "harga naik".** It means the price is behaving
unusually, and it can be yellow while *falling*. The copy reads "kurang stabil".

**`merah` fires on `|pct_change_7d|`, so a crash scores exactly like a spike.**
For a warung owner those are opposite situations. Every non-green card states
its direction, and the recommendation follows the direction rather than the
level: bawang merah at `merah` on a **-17.5% fall** now reads *"harga sedang
jauh di bawah kebiasaannya... bisa jadi waktu yang murah untuk menambah stok"*,
not "consider delaying your purchase".

Level is carried by a text label first, a mark second, colour third. `merah` and
`hijau` are precisely the pair a red-green deficiency confuses, and they are this
system's primary output.

### Freshness: the front page is deliberately not today

Measured while building. Siskaperbapo publishes **round placeholder figures on
the current date** and replaces them with computed multi-market averages the
next day. Its baseline rate of prices divisible by 500 is **0.4%**; on the
current date it is **83.3%** (10 of 12 commodities). The day before: 0%.

| region | latest day | flagged |
|---|---|---:|
| jawa_timur (unsettled) | 2026-07-29 | **12 of 12** |
| jawa_tengah | 2026-07-28 | 5 of 12 |
| di_yogyakarta | 2026-07-28 | 4 of 12 |

The dashboard therefore reads the latest **settled** day — the most recent date
strictly before today in WIB — resolved **per region**, because the regions do
not share a latest date and a global `max(obs_date)` returns only East Java,
leaving a Yogyakarta reader on an empty page. Jawa Timur now shows 3 of 12, with
the withholding explained on screen.

The engine was not changed. `daily.yml` already ingests *yesterday* for exactly
this reason, and the upsert overwrites the placeholder on the next run; the
provisional rows exist only because backfill was run by hand against today. The
dashboard rule is defence in depth for a portal that publishes intraday.

### Provenance that named portals contributing nothing

The commodity page listed its sources from `source_regions` — configured
coverage — which for DI Yogyakarta named four: `panelharga`, `pihps`, `sp2kp`,
`trends`. Two are wrong. `panelharga` is `is_active: false` with zero
observations, and `trends` is a demand signal that never writes a price.

`docs/architecture.md` claims every number walks back to a URL. A provenance
list naming portals that contributed nothing is worse than none: it looks like a
guarantee and is not one.

Migration 0010 adds a `series_sources` view derived from the observations
themselves, which drops both on its own, and reports counts and date ranges. It
exposes **metadata only, no price column**, so `price_observations` stays closed
to anon while the dashboard can be honest. Because the view runs with definer
rights by necessity, `doctor` now fails if a price column ever appears in it —
16 checks.

The commodity chart is deliberately the same construction the annotators saw in
`/lab`: observed series, 30-day mean, +/-10% band. What the paper evaluated and
what a warung owner looks at are then the same picture rather than two
renderings that happen to disagree.

---

## M7 — Evaluation harness (2026-07-29)

Candidate pool, Cohen's kappa, four-arm matching, the label-free parameter
sweeps, the paper exports and the `/lab` labelling console. **The headline M7
numbers do not exist yet and were not estimated**: kappa and the four-arm
precision/recall need two people to label 399 candidates, and inventing labels
is the one thing this project must never do. `siap kappa` currently answers
*"need two annotators, found none"*.

### A data defect found by looking at the qualitative figure, and fixed

`fig_series_beras_medium_jawa_tengah` showed five identical one-day spikes to
the same price, at roughly monthly intervals, each returning to exactly the
prior level. Staple prices do not do that.

The cause was in M2, not the detectors. `price_daily_unified.price_median` was a
median over *whichever sources reported that day*, and the sources do not
measure the same thing — PIHPS samples traditional-market retail, SP2KP is
Kemendag's panel, Siskaperbapo is East Java's provincial survey:

| pair | overlapping days | mean ratio | sd |
|---|---:|---:|---:|
| pihps / sp2kp | 19,644 | 1.0516 | 0.0786 |
| pihps / siskaperbapo | 9,384 | 1.0384 | 0.0623 |
| siskaperbapo / sp2kp | 6,615 | 1.0060 | 0.0260 |

For beras-medium in Jawa Tengah the gap was 18% (pihps 15,691, sp2kp 13,257),
each internally stable. So when sp2kp went quiet the "median" became pihps alone
and the series stepped 8.5%. Measured before doing anything about it:

* 36 of 60 series had a varying source count;
* 6,399 of 39,077 series-days (16.4%) differed in `n_sources` from the day before;
* **938 of 1,897 daily moves above 5% (49.4%) coincided with a composition
  change**;
* 673 of 2,979 Z-Score flags (22.6%) sat on one;
* 75 of the 399 ground-truth candidates (18.8%) sat on one.

The z = 99.03 flag on 2026-03-23 was exactly this.

**Reported before deciding, because the fix reopens a verified milestone.**
Four options were put up — rebase, restrict each series to one source, flag and
exclude the step days, or leave it as a stated limitation. Rebasing was chosen.

#### The correction (migration 0009)

Standard index linking. Per commodity x region the best-covered source becomes
the reference; every other source is multiplied by the *median* ratio of
reference price to its own over the days both reported. Median rather than mean,
because one mistyped price would otherwise shift every rebased price in the
series. Ties on coverage break by name, so a re-run cannot silently pick a
different basis. A source with fewer than 30 overlapping days is excluded from
the level rather than linked on a guess — none currently is.

A constant factor was checked before being adopted, across all 60
(commodity, region, source-pair) combinations:

| | median | max |
|---|---:|---:|
| within-series ratio cv | 1.9% | 9.5% |
| drift, first third vs last third | 1.1% | 10.5% |

The pooled 7.9% was an artefact of averaging across commodities. A ~2% residual
is an order of magnitude below the 18% gap it removes and well under the 10% bar
in the operational definition.

This is **not** the cooking-oil density M2 refused to refit. A density is a
physical constant with a true value that fitting would corrupt; a survey-frame
offset has no true value, because the two surveys really do price different
baskets. Linking series collected on different frames is what the correction is
for. Every factor is persisted in `source_offsets` with its overlap, residual
and drift, so no rebased price is unauditable.

#### What it actually achieved, measured

| | before | after |
|---|---:|---:|
| >5% moves coinciding with a composition change | 938 | 372 |
| >5% moves with composition unchanged | 959 | 942 |
| excess move rate on composition-change days | 5.02x | 2.02x |

The genuine moves are untouched, which is the point. And the residual is sharply
localised — split by how well a single factor describes the link:

| link quality | composition-change days | >5% moves | rate |
|---|---:|---:|---:|
| ratio cv < 5% | 5,170 | 71 | **1.37%** |
| ratio cv >= 5% | 1,229 | 301 | **24.49%** |

Base rate on days with no composition change is 2.88%. So where the two sources
track each other the artefact is **gone** — 1.37% is *below* the base rate.
Everything left lives in 8 of 48 links, all of them chillies, shallots and
garlic.

**Those 8 were kept, not dropped.** A 6-9% daily divergence between two surveys
of different markets for cabai is real heterogeneity, not a broken link, and
excluding the second source would cost corroboration on precisely the most
volatile commodities. `siap preprocess` names them at every run and
`source_offsets.ratio_cv_pct` identifies the affected days, so the limitation is
visible rather than buried.

Not claimed: that composition artefacts are eliminated. 19.8% of Z-Score flags
and 41.7% of IsolationForest flags still fall on composition-change days, above
the 16.4% base rate. What is claimed is what the table above shows.

#### Knock-on

`source_spread_pct` is now computed on the rebased scale, so the
"largest cross-source disagreements" report measures genuine same-day
disagreement instead of re-reporting the constant offset. Mean spread is 2.47%.

The whole pipeline was re-run (runs #46-#50) and the pool re-sampled (#51). The
new strongest flagged move is a one-day 11% drop in daging-sapi in DI Yogyakarta
that recovers immediately — a real outlier in the source data, and exactly the
kind of case the ground truth exists to adjudicate, rather than an artefact of
our own arithmetic.

### The pool was redrawn, deliberately, twice

The SP2KP provincial backfill finished during M7, taking sp2kp from
national-only to all four regions (26,909 observations). Every downstream
artefact was stale, so preprocess -> analyze -> cluster -> seasonal -> fuse were
re-run (runs #37-#41) and the pool re-sampled from the complete data (run #42).

It was then redrawn a second time after the source-linking fix above, for the
same reason: the fix changes which days look unusual, so it changes which days
belong in the pool.

`siap gt-pool --redraw` refuses once any label exists. Redrawing is legitimate
only before anyone has judged anything. After that the pool is what the labels
are a sample of, and replacing it would silently change what every downstream
number is a statement about — which is why the defect was raised before
labelling started rather than after.

### `/lab`, and a hole the RLS posture left

0006 gave `authenticated` INSERT on `gt_labels` and no SELECT, so one annotator
cannot read the other's judgements. Correct, and kept — but it also left the UI
unable to answer "which have I already done?", which over 399 items matters.

0007 adds `lab_annotators` plus three SECURITY DEFINER functions scoped to the
caller's own code, derived from `auth.uid()` rather than passed in. That is
strictly narrower than granting SELECT, and it closes something 0006 left open:
any signed-in team member could previously have written labels attributed to
`A2`. Independence of the two label sets is the premise of kappa, so it belongs
in the schema rather than in UI discipline.

`siap lab-check` attacks the model from the client side — becomes each
annotator, tries to read the pool, read the other's labels, and write under
their code, then rolls everything back. It caught a real hole: Supabase's
default privileges grant EXECUTE on new functions to `anon` explicitly, and
`revoke ... from public` does not remove an explicit grant. Measured impact was
nil (both functions gate on `auth.uid()`, which is NULL for anon, so both
returned zero rows), but 0008 removes the grant anyway. All 14 attempts now
behave as required.

### What the label-free sweeps actually showed

Precision and recall need labels. How the output *moves* does not, so those
sweeps ran:

* **Contamination is a cut depth, not a model choice.** The flag sets are
  strictly nested — every day flagged at 0.01 is flagged at 0.03, and every day
  at 0.03 is flagged at 0.05 (verified, not assumed). Choosing 0.03 decides how
  many alerts a warung owner is asked to attend to; it does not change which
  days rank as unusual.
* **The demand weight is inert, not robust.** Perturbing it gives Spearman
  exactly 1.0000 — because Google Trends is throttled to zero, `D = 0` on every
  scored day, and the weight only rescales the score against fixed thresholds.
  Reported as inert, because a perfect rank correlation here reads as
  reassurance and means the opposite. The level counts still move sharply
  (merah 1,406 vs 94), which is the same fact seen from the other side.
* k = 2 still scores highest on silhouette (0.7844 vs 0.6486) and still cannot
  be selected. The figure plots it rather than dropping it, since the constraint
  is editorial.

### Also fixed

`siap runs --close-stale` had never worked: `make_interval(hours => ...)` takes
`int4` and the parameter is a float, so it raised `UndefinedFunction` every
time. Now multiplies `interval '1 hour'`. Closed abandoned runs #17 and #18.

---

## M5 — Seasonality (2026-07-29)

STL at weekly resolution, `period=52`, `seasonal=13`, `robust=True`.
**48 of 60 series decomposed, 12 skipped**, 7,188 weekly component rows.

The 12 skips are every `kota_yogyakarta` series, at 1 week against the 104-week
floor. That is the coverage guard doing its job, not a failure: jogja exposes no
historical endpoint, so the city has no archive and cannot have seasonality.
Each skip records its actual week count in the run notes.

### The derived "periode rawan" matches the Indonesian calendar

Independently per commodity and region, with no calendar knowledge in the code:

| commodity | top-decile weeks | corresponds to |
|---|---|---|
| beras medium & premium | W07–W13 (9 Feb – 29 Mar) | **paceklik**, the lean season before the March–April harvest |
| cabai (both) | W08–W11 **and** W45–W50 | rainy-season supply disruption, twice a year |
| telur & daging ayam | W08–W15 (Feb – mid Apr) | Ramadan and Idul Fitri demand |
| gula pasir | W14–W19 (30 Mar – 10 May) | Lebaran baking |
| minyak goreng | W12–W19 | Lebaran |
| daging sapi | W25–W31 (Jun – Aug) | **Idul Adha** / qurban |

Rice peaking before the harvest and beef peaking at qurban are exactly what the
agricultural and religious calendars predict, and neither is encoded anywhere in
the pipeline.

### Limitation: STL cannot track a lunar festival

`period=52` assumes the seasonal pattern repeats on a **fixed Gregorian**
schedule. Ramadan and Idul Fitri follow the Islamic lunar calendar and drift
about 11 days earlier each year:

| year | Idul Fitri | ISO week |
|---|---|---|
| 2024 | 10 Apr | W15 |
| 2025 | 31 Mar | W14 |
| 2026 | 20 Mar | W12 |

Across the three years of archive the festival moves roughly three weeks, so a
fixed-period decomposition **smears the Ramadan peak across ~5 weeks and
understates its amplitude**. The broad W08–W19 bands above are that smearing,
not a genuinely five-week-long demand event.

Consequences, recorded rather than worked around:

* "Periode rawan" for Ramadan-sensitive commodities (telur, ayam, gula, minyak)
  is **wider and flatter than reality**. It errs toward warning early, which is
  the safer direction for a warung owner, but it is not precise.
* The effect worsens as the archive lengthens — five years of data spread the
  festival across nearly two months.
* The clean fix is a lunar-calendar regressor or aligning observations to days
  from Idul Fitri rather than to calendar weeks. That is beyond §6.4 as
  specified and is **not** attempted here; it belongs in the paper's limitations
  section and in future work.

Commodities driven by the solar agricultural calendar — rice at paceklik, chilli
in the rainy season — are unaffected, and their windows are correspondingly
sharp.

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

> **Reversed at M10.** This floor no longer exists. The M4 analysis was correct
> about the symptom and wrong about the cause: k=2 won because the volatility
> feature did not divide log returns by the days they spanned, which inflated it
> on regions whose portals skip days and smeared the middle of the distribution.
> With that corrected, k=3 wins the silhouette outright and the floor is
> unnecessary. See M10 below.

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
