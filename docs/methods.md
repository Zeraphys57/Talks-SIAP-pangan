# Methods

Every modelling decision, with the reason it was made and the alternative it was
chosen over. Referenced from `engine/config/*.yaml`, `supabase/migrations/` and
the code, so a reader who hits a constant can find out why it holds that value.

Numbers here come from runs against the live database and are reproducible with
`siap reproduce`. Where a decision has a measured consequence, the measurement
is given rather than the intuition.

---

## 1. From portals to one series per commodity × region

### 1.1 Source linking (migration 0009)

The four price portals do not measure the same thing. PIHPS samples
traditional-market retail, SP2KP is Kemendag's own panel, Siskaperbapo is East
Java's provincial survey. Measured over days where both reported:

| pair | overlapping days | mean ratio | sd |
|---|---:|---:|---:|
| pihps / sp2kp | 19,644 | 1.0516 | 0.0786 |
| pihps / siskaperbapo | 9,384 | 1.0384 | 0.0623 |
| siskaperbapo / sp2kp | 6,615 | 1.0060 | 0.0260 |

Taking a median across whichever portals happened to report on a given day
therefore produced a series that **stepped** whenever the membership changed.
Those steps are not price movements, and the detectors could not tell:

* 6,399 of 39,077 series-days (16.4%) differ in source count from the day before
* 938 of 1,897 daily moves above 5% (49.4%) coincided with such a change
* 673 of 2,979 Z-Score flags (22.6%) sat on one

**Method.** Standard index linking. Per commodity × region the best-covered
source becomes the reference; each other source is multiplied by the *median*
ratio of reference price to its own over the overlap. Median rather than mean
because one mistyped price would otherwise shift every rebased value. Coverage
ties break by name, so a re-run cannot silently change the basis. Below 30
overlapping days a source is excluded from the level rather than linked on a
guess.

**Why a constant factor.** Measured across all 60 (commodity, region, pair)
combinations before adopting it: within-series ratio CV has median 1.9% and max
9.5%; drift between the first and last third has median 1.1%. The pooled 7.9%
above is an artefact of averaging across commodities. A ~2% residual is an order
of magnitude below the 18% gap it removes and well under the 10% anomaly bar.

**Outcome.** >5% moves coinciding with a composition change fell 938 → 372,
while moves with composition unchanged held at 959 → 942. Split by link quality:

| link | change-days | >5% moves | rate |
|---|---:|---:|---:|
| ratio CV < 5% | 5,170 | 71 | 1.37% |
| ratio CV ≥ 5% | 1,229 | 301 | 24.49% |

Base rate on days with no composition change is 2.88%, so where the sources
track each other the artefact is **gone**. The residual is 8 of 48 links, all
cabai, bawang merah and bawang putih. Those were kept: 6–9% daily divergence
between surveys of different markets is real heterogeneity, and dropping the
second source would cost corroboration on the most volatile commodities.

### 1.2 Reconciliation and interpolation

Median across rebased same-day prices. `source_spread_pct` is computed after
rebasing, so it measures genuine disagreement rather than the constant frame
offset; mean spread is 2.47%.

Gaps of at most **3 days** are linearly interpolated and marked `is_imputed`.
Longer gaps stay NULL, and interpolation never extrapolates past either end of a
series. Imputed rows are excluded from every model input
(`analysis.input.exclude_imputed`).

PIHPS publishes Monday–Friday, so its weekend gaps are exactly two days and fall
inside the window. A region covered only by PIHPS therefore shows roughly 2/7 of
days imputed; `docs/data-quality.md` reports this per series rather than burying
it.

---

## 2. Anomaly detection

Two detectors run independently over the same input. They are *not* tuned to
agree — the fusion step in §4 exists because they do not.

### 2.1 Z-Score (`analysis.zscore`)

Rolling 45-day window, minimum 20 observations, threshold |z| ≥ 2.5, computed on
**log** price. Prices are right-skewed and multiplicative: a 10% move costs the
same whether the price is 15,000 or 60,000, and only log space treats it that
way.

`min_baseline_std = 0.0005` (0.05% daily σ in log space). Without it, a stale
series with σ ≈ 1e-16 produced z = −20,824,185 — an artefact of a price that had
not moved for a month, not a finding. Such windows now score NULL.

**Why the window is 45 days and not 30.** The floor is stated in *observations*
and the window in *calendar days*. Those agree only where a source publishes
daily, and `nasional` runs at ~27% systematic imputation, which put it right on
the floor. At 30 days it scored NULL on **41.31%** of its dates, and **91.4%** of
those NULLs were the observation floor rather than a stale baseline. Its flag
rate read 5.74% against 7.86–9.43% everywhere else — which looks like a calm
region and is actually an unmeasured one.

Widening the lookback to 45 days, **without lowering the floor below 20**:

| region | NULL % 30D | NULL % 45D | Δ | flag % 30D | flag % 45D | Δ |
|---|---|---|---|---|---|---|
| nasional | 41.31 | 5.69 | **−35.63** | 5.74 | 8.43 | +2.68 |
| di_yogyakarta | 13.66 | 9.55 | −4.11 | 8.08 | 8.06 | −0.02 |
| jawa_tengah | 4.70 | 3.71 | −0.99 | 9.43 | 8.82 | −0.61 |
| jawa_timur | 1.84 | 1.82 | −0.02 | 7.86 | 8.02 | +0.16 |
| kota_yogyakarta | 100.00 | 100.00 | 0.00 | 0.00 | 0.00 | 0.00 |

jawa_timur, which publishes daily, is essentially unmoved — the change reaches
only the regions the calendar window was penalising, which is the evidence that
it corrected a measurement artefact rather than loosened a standard. `nasional`'s
flag rate now sits inside the range of the other regions.

**Is the flag-rate rise coverage, or is a longer baseline manufacturing
deviations?** A 45-day window carries an older baseline, so a slow trend could
read as deviation on dates that were *already* scoreable. Decomposed, it does
not: `nasional`'s net rise of +192 flags is +201 on dates the wider window
recovered and **−8** on dates scoreable at both widths.

| | flags 30D | flags 45D | Δ |
|---|---|---|---|
| dates scoreable at both widths (4,188) | 408 | 400 | **−8** |
| dates recovered by the wider window (2,540) | — | 201 | +201 |

On the already-scoreable dates, mean \|z\| moved 1.3673 → **1.3577** — slightly
*down*, where the drift hypothesis predicts up. The churn there is symmetric
(+130 newly flagged, −138 no longer flagged), which is the baseline genuinely
changing rather than drifting one way. And the recovered dates flag at 7.91%,
just **below** the region's overall 8.43% — if the wider window were inventing
deviations, the newly-visible dates would flag at an elevated rate, not a
slightly depressed one.

Across regions, the share of the 45D flag set sitting on recovered dates is
`nasional` 33.4%, `di_yogyakarta` 3.2%, `jawa_tengah` 0.4%, `jawa_timur` 0.0% —
exactly proportional to how much coverage each region was missing.

This does **not** invalidate the M7 candidate pool: the §7.1 annotation
criterion is deliberately independent of the detector. It is a documented
deviation from the original protocol and required a full re-run.

### 2.3 Detector coverage per region, decomposed by cause

Coverage is a reported metric, not a footnote — a detector that cannot score a
date is not a detector that found nothing. At the 45-day window (run #70):

| region | z-score NULL % | of which floor | of which stale baseline | iforest NULL % |
|---|---|---|---|---|
| jawa_timur | 1.82 | 1.73 | 0.00 | 0.64 |
| jawa_tengah | 3.71 | 2.41 | 1.18 | 0.89 |
| nasional | 5.69 | 3.20 | 2.32 | 1.18 |
| di_yogyakarta | 9.55 | 2.43 | 6.99 | 0.90 |
| kota_yogyakarta | 100.00 | 0.00 | 0.00 | 100.00 |

The two causes are different failures and must not be pooled.
`min_observations` is *our* window being too narrow for the source's cadence —
fixable, and fixed above. `min_baseline_std` is the *source* having stopped
publishing new values — not fixable by us, and the same defect the clustering
provenance gate catches at monthly resolution. di_yogyakarta is now dominated by
the second, which is the honest residual.

`kota_yogyakarta` has one day of data in the entire archive; it scores nothing,
clusters nothing, and every one of its alerts is `belum_dapat_dinilai`.

**Known limitation, deliberately not fixed.** The brief defines an anomaly as a
change exceeding ±10% against the trailing 30-day mean sustained two days, but
|z| ≥ 2.5 corresponds to 10% only when the baseline σ happens to be about 4%. On
a calm staple, 2.5σ is a 0.3% move. Measured: 54.6% of Z-Score flags are on
sub-1% moves; 7.9% are on ≥10% moves.

The detector measures *statistical unusualness*; the ground truth encodes
*operational significance*. These are different quantities and no threshold
reconciles them. A magnitude gate was considered and **rejected**: the four
ablation arms exist so `fusion` must earn its complexity against a naive
baseline, and quietly making the baseline smarter would rig that comparison.
Fusion's M term is the magnitude signal, and M7 measures whether it earns its
place.

### 2.2 Isolation Forest (`analysis.iforest`)

200 estimators, contamination 0.03, minimum 60 observations, six features:
`log_price`, `pct_change_1d`, `pct_change_7d`, `rolling_std_14d`, `demand_z52`,
`dow`. `random_state` comes from `analysis.seed`.

`demand_missing_fill = 0.0`: Trends is best-effort and has been unavailable for
long stretches, so `demand_z52` is filled rather than dropped. A constant column
yields no splits, so a run without Trends behaves as if the feature were absent
but stays comparable to one with it.

**Trends is collected for two scopes only** — `nasional` and `di_yogyakarta`.
Every other region is scored against the national signal (`analyze.demand_scope`).
As of 2026-08-08 Trends is answering again: 4,219 weekly `interest_z52` values
are stored and `demand_z52` is a live feature, not a constant. Any run whose
notes report it absent predates that, and the four-arm comparison in §6 must say
which regime each arm was measured under.

**Contamination is a cut depth, not a model choice.** Verified, not assumed: the
flag sets are strictly nested — every day flagged at 0.01 is flagged at 0.03,
and every day at 0.03 is flagged at 0.05 (396 ⊂ 1,188 ⊂ 1,968). Choosing 0.03
decides how many alerts a warung owner is asked to attend to; it does not change
which days rank as unusual.

---

## 3. Clustering (`analysis.kmeans`)

Monthly cells per commodity × region, two features — volatility and cumulative
change — standardised. k searched over 2…8, selected by silhouette. Cells that
fail the provenance gate keep their row and are excluded from the fit.

### 3.1 The provenance gate

A cell is excluded when it has fewer than 15 real observations, fewer than 3
distinct real values, or at least half its real observations inside a run of 7
or more identical consecutive values. Every criterion is a statement about the
**data**, never about the feature value.

That distinction is the whole point. A volatility threshold would be one line
and is indefensible: it cannot tell a genuinely stable price from a portal that
stopped resurveying, so it would suppress real stable commodities to hide a data
problem. Checked against the 36 cells whose measured volatility was exactly
zero, the provenance gate catches **36 of 36**, all as
`insufficient_distinct_values`. None passed, so no genuinely stable commodity
was being suppressed — every zero-volatility cell in the archive was a feed that
had stopped moving.

Gated cells are kept, not deleted, so coverage is reportable. It is uneven:

| region | fitted | thin | flat | stale | coverage |
|---|---|---|---|---|---|
| jawa_timur | 432 / 444 | 12 | 0 | 0 | 97.3% |
| jawa_tengah | 416 / 444 | 12 | 6 | 10 | 93.7% |
| di_yogyakarta | 289 / 444 | 12 | 73 | 70 | 65.1% |
| nasional | 348 / 348 | 0 | 0 | 0 | 100% |
| kota_yogyakarta | 0 / 12 | 12 | 0 | 0 | 0% |

**1,485 of 1,692 cells (87.8%) enter the fit.** The DIY column is the M2
stale-feed finding restated: it is the region PIHPS was the sole source for.

### 3.2 Volatility is normalised for the days each return spans

Imputed rows are excluded from the features, so consecutive real observations
are not consecutive days: a Friday→Monday step is one log return covering three
days. The variance of a 3-day return is about 3× that of a 1-day return, so an
unnormalised standard deviation inflates by ≈1.73× on every such step — and the
steps are not spread evenly across regions:

| region | mean gap (days) | volatility raw | ÷√Δt | ratio |
|---|---|---|---|---|
| jawa_timur | 1.000 | 0.00936 | 0.00936 | 1.000 |
| jawa_tengah | 1.364 | 0.01229 | 0.01031 | 1.191 |
| nasional | 1.438 | 0.01314 | 0.01149 | 1.144 |
| di_yogyakarta | 1.373 | 0.02149 | 0.01749 | **1.228** |

All regions then enter **one** K-Means, so di_yogyakarta was measured as ~23%
more volatile than jawa_timur partly because of when its portal publishes.
Dividing each log return by √(days elapsed) removes it. jawa_timur, which
publishes daily, is unmoved by construction — a useful control.

Correcting this moved **137 of 1,485 fitted cells (9.23%)** to a calmer zone
(129 `kuning`→`hijau`, 4 `merah`→`hijau`, 4 `merah`→`kuning`), and the effect is
concentrated exactly where predicted: di_yogyakarta 19.72% of its cells, against
jawa_timur's 5.32%.

### 3.3 k is selected, not forced — and the selection is stable across seeds

There was a `k_select_min = 3` floor, because on the raw features the silhouette
preferred k = 2 (**0.7896** against 0.7057 for k = 3 on run #68) and two clusters
leave `kuning` unreachable.

The floor is gone. Once the volatility feature is normalised for elapsed time,
**k = 3 wins the silhouette outright: 0.8009 against 0.7983 for k = 2.** The
earlier preference for k = 2 was substantially an artefact of the inflated
feature smearing the middle of the distribution. Nothing needs forcing, and the
three zones now come from post-hoc centroid ranking at whatever k the silhouette
selects. If future data selects k = 2, the honest output is two zones.

**A margin of 0.0026 is not, on its own, a selection.** Swept across seeds at
the original `n_init = 10`, k = 3 won on only 18 of 20 — on the other two the
k = 3 *fit* landed in a poor local optimum (silhouette 0.7167 rather than
~0.801) and k = 2 won by default. A selected k that depends on the seed cannot
be reported as a selection.

The cause was the optimiser, not the data. At `n_init = 25` and above, k = 3
wins **20 of 20 seeds**; `n_init` is now 50:

| `n_init` | k = 2 wins | k = 3 wins |
|---|---|---|
| 10 | 2 / 20 | 18 / 20 |
| 25 | 0 / 20 | **20 / 20** |
| 50 | 0 / 20 | **20 / 20** |
| 100 | 0 / 20 | **20 / 20** |

The margin over k = 2 remains thin and must be reported as thin — the claim is
that k = 3 wins *reproducibly*, not that it wins *comfortably*.
`fig_k_silhouette` plots the whole curve.

### 3.4 The headline silhouette is dominated by one cluster

**0.8009 is a weighted mean, and reporting it alone is misleading.** 95.6% of
fitted cells sit in the one cluster that scores well; the two clusters that
actually raise anything score far worse:

| cluster | zone | cells | share | silhouette | mean volatility | mean cum_change |
|---|---|---|---|---|---|---|
| 0 | `hijau` | 1,419 | 95.56% | **≈0.82** | 0.00905 | −1.00% |
| 2 | `merah` | 43 | 2.90% | **≈0.36** | 0.03691 | +86.64% |
| 1 | `kuning` | 23 | 1.55% | **≈0.25** | 0.12852 | +7.79% |

The bare number is technically true and substantively misleading: it says the
calm cluster is well separated from everything else, which was never in doubt.
The alerting clusters — the ones the system exists to produce — are weakly
separated. Any claim about clustering quality must cite this table, not 0.8009.

### 3.5 Zone ranking is not monotone in volatility

`merah` has **lower** mean volatility than `kuning` (0.03691 against 0.12852).
Unexplained, that table reads as a bug. It is not: zones rank centroids on

    severity = 0.5 · z(volatility) + 0.5 · z(max(0, cum_change))

so a cluster with moderate volatility and a +86.64% cumulative rise outranks one
with very high volatility and a +7.79% rise. On this data `cum_change` has much
the wider spread at centroid level, so it dominates the composite.

**`cum_change` is clamped at zero** because the reader is a buyer: a month whose
price fell is not a risk to them, so a falling cluster is ranked on volatility
alone rather than being pushed down the ranking by how far it fell. `abs()` was
rejected — it would rank a collapse as `merah`, warning about the one movement
in the reader's favour. Volatility contributes unsigned and in full, because
unpredictability blocks planning in either direction.

**The clamp did not restore monotonicity, and was not expected to.** It moved
zero cells on the current data — the `kuning` centroid's cum_change was already
positive (+7.79%) and `hijau`'s was −1.00%, which clamps to 0 without changing
the ranking. It is a guard for a state the archive has had before (run #68 held
a `kuning` centroid at −13.06%) rather than a fix for this one.

What *would* restore monotonicity is re-weighting, measured on the current
centroids:

| severity weights | `hijau` σ | `kuning` σ | `merah` σ | monotone? |
|---|---|---|---|---|
| 0.5 / 0.5 (current) | 0.00905 | 0.12852 | 0.03691 | no |
| 0.7 / 0.3 | 0.00905 | 0.03691 | 0.12852 | **yes** |
| 0.8 / 0.2 | 0.00905 | 0.03691 | 0.12852 | **yes** |
| volatility only | 0.00905 | 0.03691 | 0.12852 | **yes** |

This is a real trade, not a free fix: at 0.7/0.3 the cluster that rose **+86.64%
over a month** becomes `kuning` rather than `merah`. For a warung owner deciding
what to buy, a sustained 86% climb is arguably the most consequential thing on
the board. Monotonicity in volatility and severity-for-a-buyer are not the same
ordering, and the weights are left at 0.5/0.5 pending an explicit decision.

**The dashboard copy was wrong and has been fixed regardless.** `kuning`
previously read "tidak seliar kelompok merah" — false for those 23 cells, which
are the most violently swinging months in the archive. The zones are now
described by what their centroids *are* — `merah` "Naik tajam sepanjang bulan",
`kuning` "Naik-turun tajam" — rather than by an implied volatility ranking.

Zones describe how a price **has behaved**, not where it will go.

### 3.6 The global clustering largely recovers commodity identity

Measured, because it changes what the clustering can be claimed to show.

**Commodity composition of each zone (run #80):**

| zone | cells | distinct commodities | composition |
|---|---|---|---|
| `merah` | 43 | **3 / 12** | cabai-rawit 56%, cabai-keriting 40%, bawang-merah 5% |
| `kuning` | 23 | 6 / 12 | cabai-rawit 39%, cabai-keriting 35%, bawang-merah 13% |
| `hijau` | 1,419 | 12 / 12 | evenly spread, 7–10% each |

`merah` is **100% cabai and bawang-merah**. `kuning` is 87% the same three.

**Zone stability, month to month:** of 1,437 consecutive month pairs for the same
commodity × region, only **7.6% change zone**. Broken down, the movement is
almost entirely two commodities:

| commodity | flips | pairs | rate |
|---|---|---|---|
| cabai-rawit-merah | 57 | 133 | **42.9%** |
| cabai-merah-keriting | 38 | 133 | **28.6%** |
| bawang-merah | 7 | 128 | 5.5% |
| the other nine | ≤2 each | — | **0–1.5%** |

Thirty-three of 48 series never leave a single zone.

So the global model is substantially a *commodity* classifier with a temporal
component confined to cabai and bawang-merah. That is a defensible answer to
Tujuan 3, which asks for commodities grouped by volatility — but it is **not**
the claim the dashboard makes when it presents a zone as a statement about a
month.

**Secondary analysis: features standardised within each commodity.** Removing
the between-commodity level leaves only "is this commodity unusual *for itself*
this month". Run with `siap cluster --within-commodity`; it reports and does not
persist, because the primary model is the global one.

| | global | within-commodity |
|---|---|---|
| k selected | 3 | **2** |
| silhouette | 0.8009 | 0.7755 |
| `merah` composition | **3 / 12** commodities | **12 / 12**, evenly spread |
| zone flips month-to-month | 7.6% | 2.4% |

The alerting cluster goes from three commodities to all twelve — bawang-putih
17%, beras-medium 12%, bawang-merah 10%, cabai-rawit 10%. That is the temporal
reading: every commodity has its own unusual months, and the global model was
hiding eleven of them behind cabai's price level.

Both are reported. Neither replaces the other: the global model answers Tujuan 3
as written, the within-commodity model answers what the dashboard says it shows.

---

## 4. Fusion (`fusion.yaml`)

    F = 0.45·A + 0.25·M + 0.20·D + 0.10·C

* **A** — max of the two normalised detector scores, ×(1 + 0.15) when both
  flagged, capped at 1. The agreement bonus is small because agreement is rare:
  the detectors overlap on only 9.7% of flags, which is precisely why agreement
  carries information.
* **M** — `clip(|pct_change_7d| / 0.15, 0, 1)`. Pure magnitude, and the term
  that addresses the §2.1 mismatch.
* **D** — demand from Trends. Currently 0 everywhere (see below).
* **C** — corroboration: the fraction of reporting sources that also moved.

Thresholds: `siaga` ≥ 0.70, `waspada` ≥ 0.40. `siaga` additionally requires
corroboration ≥ 0.5 **and** at least 2 sources reporting. Without the second
condition, a single-source day gives C = 1/1 = 1.0 and produced 1,053 spurious
`siaga` alerts; with it, 665.

**Why the fusion levels are not spelled `merah`/`kuning`/`hijau`.** They were,
and so was `cluster_assignments.zone`. The two are different quantities — the
zone is a monthly K-Means regime, the level a daily fusion score — and they
disagree on **22.6% of 39,089 pairs**, including 272 cells rendered on the same
page where the zone reads `merah` and the level `hijau`. The zone keeps the
colour words because proposal Tujuan 3 commits in writing to K-Means producing
"zona strategis (merah, kuning, hijau)"; fusion carries no such commitment, so
fusion moved to an escalation vocabulary: `hijau → tenang`, `kuning → waspada`,
`merah → siaga`. This also gives the dashboard's primary signal names that carry
meaning without colour, which is what `docs/design.md` asks for.

**The fourth level: `belum_dapat_dinilai`.** `A` was computed as
`max(scores) if scores else 0.0`. A date neither detector could score therefore
produced A = 0.0 — the same value as a date both detectors examined and found
calm — and fell through to the lowest band, where the dashboard rendered it as
"tidak ada yang tidak biasa pada harga hari itu". Absence of evidence, presented
as evidence of safety.

`A` is now undefined rather than zero when neither detector scored, the level
propagates to `belum_dapat_dinilai`, and `fusion_score` is NULL. The level sits
**outside** the `tenang < waspada < siaga` ordering: it is not a severity, it is
the absence of a judgement, and it carries no recommendation. On the re-run
(#72 against #66) exactly 348 rows change level, all from `tenang`, and nothing
else moves.

Per region, as a share of that region's alerts: `nasional` 1.18%,
`jawa_tengah` 0.89%, `di_yogyakarta` 0.90%, `jawa_timur` 0.64%, and
`kota_yogyakarta` **100%**.

The rate is measured, not inferred from either detector's NULL rate: the path
fires only where **neither** detector scored, which is a much smaller set than
the z-score NULL rate alone (§2.3). A date the z-score could not judge but
Isolation Forest could is a scored date, on one detector's evidence.

M, D and C are still recorded on an unscored row — they are what *was*
observable, and the audit trail should show it. A large weekly move on a date no
detector could score is still an unscored date: letting M carry the row would
produce a level from a quarter of the model and present it as the whole.

**The demand weight is currently inert, not robust.** Perturbing it gives
Spearman exactly 1.0000 — because Trends is throttled, D = 0 on every scored day,
so the weight only rescales the score against fixed thresholds. It is reported
as inert because a perfect rank correlation otherwise reads as reassurance and
means the opposite. The level counts still move sharply (`siaga` 1,406 vs 94),
which is the same fact from the other side.

**`siaga` fires on |pct_change_7d|, so a crash scores like a spike.** For a
warung owner those are opposite situations, which is why the dashboard states
direction on every alert and inverts the recommendation on a fall
(`docs/design.md`).

---

## 5. Seasonality (`analysis.stl`)

STL at weekly resolution, `period = 52`, `seasonal = 13`, `robust = True`,
minimum 104 weeks. "Periode rawan naik" is the top decile of mean seasonal
component by ISO week.

**Limitation: STL cannot track a lunar festival.** Idul Fitri moves about 11
days earlier each Gregorian year — W15 in 2024 to W12 in 2026 — so a fixed
52-week period smears the Ramadan effect across roughly five weeks instead of
locating it. The seasonal weeks reported for affected commodities are therefore
wider and flatter than the real effect. Correcting this needs a Hijri-aligned
regressor, which is out of scope; it is stated as a limitation rather than
presented as a clean seasonal peak.

Weekly rather than daily because a 365-period STL over three years of daily data
has barely three cycles to estimate from.

---

## 6. Evaluation

See `docs/labelling.md` for the protocol and `engine/src/siap/evaluate/` for the
implementation. In summary: a 399-candidate stratified pool (307 rule-flagged,
92 random control), two annotators labelling blind, Cohen's κ with **0.60 as a
stop condition**, and four ablation arms (`zscore_only`, `iforest_only`,
`union`, `fusion`) matched against adjudicated events with ±3-day tolerance.

Stratum B is what makes recall computable: without dates the model did not flag,
a miss can never be observed.

Precision counts detections and recall counts events, deliberately — firing five
times inside one event is one discovery but five demands on attention.

**As of this writing κ and the four-arm metrics do not exist**, because they
require two people to label and no label has been written. Nothing in this
repository estimates them.

---

## 7. Queries behind the figures

Coverage and provenance, referenced from `docs/sources.md`:

```sql
-- Which portals actually produced a series, with counts and ranges.
select * from public.series_sources
 where commodity_id = :commodity and region_id = :region;

-- Every rebasing factor, with the residual and drift it was measured at.
select c.slug, rg.slug, s.slug, o.factor, o.n_overlap,
       o.ratio_cv_pct, o.ratio_drift_pct, o.excluded_reason
  from public.source_offsets o
  join public.commodities c on c.id = o.commodity_id
  join public.regions rg    on rg.id = o.region_id
  join public.sources s     on s.id = o.source_id
 where o.run_id = (select max(run_id) from public.source_offsets)
 order by abs(o.factor - 1) desc;

-- Walk one displayed price back to a URL and a fetch timestamp.
select u.obs_date, u.price_median, s.slug, o.price_idr,
       r.url, r.fetched_at
  from public.price_daily_unified u
  join public.price_observations o
    on o.commodity_id = u.commodity_id and o.region_id = u.region_id
   and o.obs_date = u.obs_date
  join public.sources s       on s.id = o.source_id
  join public.raw_snapshots r on r.id = o.snapshot_id
 where u.commodity_id = :commodity and u.region_id = :region
   and u.obs_date = :date;
```
