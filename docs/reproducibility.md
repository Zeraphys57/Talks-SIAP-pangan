# Reproducibility

What it takes to get the same numbers, and how to check that you did.

The claim this project makes is narrow and testable: **given the same input
rows, the same parameters and the same seed, the detectors produce identical
scores.** `siap reproduce` checks it against the database rather than asserting
it in prose.

---

## The provenance chain

Every number on screen walks backwards:

```
alerts.fusion_score
  -> anomaly_scores        (per method, per day, with the run that wrote it)
    -> price_daily_unified (median of rebased same-day source prices)
      -> source_offsets    (the factor each source was multiplied by)
      -> price_observations(one row per source, canonical units)
        -> raw_snapshots   (the response body, gzip-compressed)
          -> url + fetched_at
```

Each link is a foreign key, not a convention. The SQL to walk it for a specific
price is in [`docs/methods.md`](methods.md) §7.

`analysis_runs` closes the loop from the other end: every run records its git
SHA, seed, resolved parameters and library versions, so a figure traces to a
commit and a configuration rather than to "the version we had in July".

---

## Reproducing a published number

### 1. Pin the environment

```bash
cd engine
python -m venv .venv
.venv/Scripts/activate           # source .venv/bin/activate elsewhere
pip install -r requirements.lock
pip install -e . --no-deps
```

`--no-deps` is not optional. Without it pip re-resolves and may lift a pin,
which defeats the point of the lock.

`pyproject.toml` declares compatible *ranges* and `requirements.lock` records
*exact* versions. Both are correct: the first says what the project works with,
the second says what the numbers came from.

### 2. Restore the schema and reference data

```bash
siap migrate                     # checksummed, applied in order
siap seed                        # reference data from engine/config/*.yaml
siap doctor                      # schema, RLS posture, live anon check
```

Migrations are checksummed with an LF-normalised SHA-256 and refuse to run if an
applied file has changed on disk. That guard is what makes "the schema is the
migrations" a fact rather than an intention.

### 3. Rebuild the analysis

```bash
siap preprocess                  # rebases sources, rebuilds the daily series
siap analyze                     # both detectors
siap cluster
siap seasonal
siap fuse
```

Order matters: `preprocess` truncates and rewrites the series everything else
reads, and `fuse` consumes the anomaly run `analyze` produced.

### 4. Check it reproduced

```bash
siap reproduce                   # latest anomaly run
siap reproduce --run 47          # a specific one
```

This reloads the run's **own recorded** parameters and seed — not the current
`analysis.yaml`, which may legitimately have moved on — recomputes every score
from `price_daily_unified`, and compares row by row at the precision the
database stores.

Last verified: **run #47, 78,274 scores, every one identical.**

```
  seed          : 20260729
  series recomputed : 60
  scores compared   : 78,274
[  ok  ] every score identical to six decimal places
[  ok  ] the input data is unchanged since the run
```

The same check runs on every scheduled pipeline in
`.github/workflows/daily.yml`, so determinism is a property that keeps being
tested rather than one that was true once.

---

## Reading a failure

The three failure modes are reported separately because they have different
remedies, and conflating them would make the check useless.

| symptom | means | do |
|---|---|---|
| **scores differ** | the seed is not reaching an estimator, or something depends on dict/row ordering | a real bug — do not cite the run |
| **row counts differ** | the input data changed since the run | re-run the analysis; this is not a determinism result |
| **library versions moved** | the run's numbers belong to versions no longer installed | cite the recorded versions; if scores also moved, that is the finding |
| **`same code: NO`** | the working tree is at a different commit, or is dirty | expected during development; must be clean for a published run |

A dirty tree makes the recorded SHA meaningless, which is why `git_sha()`
appends `-dirty` rather than pretending.

### Why the comparison is exact

Floating point is deterministic for a fixed sequence of operations on fixed
inputs. A score that differs in the twelfth decimal under the same seed and data
means something genuinely non-deterministic — thread scheduling, hash ordering,
an unseeded RNG — and a tolerance would hide precisely the bug this exists to
find.

NaN is normalised to NULL before comparison, because that is what the persister
writes: a score inside the 30-day warm-up window is not a number. Without that
normalisation every warm-up row would appear to mismatch *itself*, since NaN
never compares equal to NaN.

---

## What is not reproducible, and why

Stated plainly, because a reproducibility document that claims everything is
reproducible is not credible.

**Scraping.** Portals change and revise. Re-running `siap ingest` for a past
date may return different figures than it did originally — Siskaperbapo, for
instance, publishes round provisional values on the current date and replaces
them with computed averages the next day (0.4% of its prices are round normally;
83.3% on the current date). This is why `raw_snapshots` keeps every response
body: history can be **re-parsed** under a new `parser_version` without
re-fetching from a portal that no longer serves it.

**Google Trends.** `pytrends` wraps an undocumented, rate-limited endpoint that
currently returns nothing. Runs record whether the demand signal was available;
the fusion D term degrades to 0 with a recorded reason rather than failing.

**The ground truth.** Two people labelling 399 candidates is not a deterministic
process. What is reproducible is the *pool*: it is drawn with a seeded shuffle
from `analysis.seed`, and `siap gt-pool --redraw` refuses once any label exists,
so the sample the labels describe cannot change underneath them.

**Wall-clock-dependent output.** The dashboard resolves "the latest settled day"
against today in WIB, so a screenshot taken on a different day differs. The
underlying rows do not.

---

## Repository state

| artefact | where | committed |
|---|---|---|
| Schema | `supabase/migrations/*.sql` | yes, checksummed |
| Parameters | `engine/config/*.yaml` | yes |
| Exact dependencies | `engine/requirements.lock` | yes |
| Node version | `.node-version` | yes |
| Figures and tables | `paper-exports/` | **no** — regenerate with `siap export` |
| Data | Supabase Postgres | no |

`paper-exports/` is gitignored deliberately. A committed figure drifts from the
run that produced it; a regenerated one carries the run id it came from, stamped
on the figure itself.
