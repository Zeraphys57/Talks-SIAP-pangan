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

Rolling 30-day window, minimum 20 observations, threshold |z| ≥ 2.5, computed on
**log** price. Prices are right-skewed and multiplicative: a 10% move costs the
same whether the price is 15,000 or 60,000, and only log space treats it that
way.

`min_baseline_std = 0.0005` (0.05% daily σ in log space). Without it, a stale
series with σ ≈ 1e-16 produced z = −20,824,185 — an artefact of a price that had
not moved for a month, not a finding. Such windows now score NULL.

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

`demand_missing_fill = 0.0`: Google Trends is throttled to zero at time of
writing, so `demand_z52` is absent. Filling with a constant rather than dropping
the column keeps the feature matrix identical between runs whether or not Trends
worked — a constant column yields no splits, so the model behaves as if the
feature were absent, but reproducibly so.

**Contamination is a cut depth, not a model choice.** Verified, not assumed: the
flag sets are strictly nested — every day flagged at 0.01 is flagged at 0.03,
and every day at 0.03 is flagged at 0.05 (396 ⊂ 1,188 ⊂ 1,968). Choosing 0.03
decides how many alerts a warung owner is asked to attend to; it does not change
which days rank as unusual.

---

## 3. Clustering (`analysis.kmeans`)

Monthly cells per commodity × region, minimum 15 days in a month, two features:
volatility and cumulative change, standardised. k searched over 2…8, selected by
silhouette.

**Why k is not forced to 3.** The proposal asks for "optimal k" *and* for three
zones. Silhouette selects k; the three zones are then a presentation layer, with
middle clusters merging into `kuning` when k > 3. Forcing k = 3 would report a
model-selection result that was never a selection.

**Why k = 2 cannot be selected.** k = 2 scores highest on silhouette (0.7844
against 0.6486 for k = 3), but two clusters cannot populate a three-zone output
— `kuning` would be unreachable and the middle level would never appear. So
`k_select_min = 3` floors the choice. The constraint is editorial rather than
statistical, so `fig_k_silhouette` plots k = 2 rather than dropping it: the
reader is entitled to see what the constraint cost.

Zones are assigned by ranking centroids on `0.5 × volatility + 0.5 ×
cum_change`. Zones describe how a price **has behaved**, not where it will go.

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

Thresholds: `merah` ≥ 0.70, `kuning` ≥ 0.40. `merah` additionally requires
corroboration ≥ 0.5 **and** at least 2 sources reporting. Without the second
condition, a single-source day gives C = 1/1 = 1.0 and produced 1,053 spurious
`merah` alerts; with it, 665.

**The demand weight is currently inert, not robust.** Perturbing it gives
Spearman exactly 1.0000 — because Trends is throttled, D = 0 on every scored day,
so the weight only rescales the score against fixed thresholds. It is reported
as inert because a perfect rank correlation otherwise reads as reassurance and
means the opposite. The level counts still move sharply (merah 1,406 vs 94),
which is the same fact from the other side.

**`merah` fires on |pct_change_7d|, so a crash scores like a spike.** For a
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
