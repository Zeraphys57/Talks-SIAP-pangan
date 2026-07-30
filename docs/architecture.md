# Architecture

## The shape of the system

```
GitHub Actions (cron 02:00 WIB + manual dispatch)
        |
        v
  engine/  (Python 3.12)
    scrapers  -> raw_snapshots -> normalize -> price_observations
    preprocess-> price_daily_unified
    analyze   -> anomaly_scores, cluster_*, seasonal_*, alerts
    evaluate  -> evaluation_results, figures
        |
        v
  Supabase Postgres   <-- single source of truth
        |
        v
  web/  (Next.js 15 App Router, React 19, TypeScript, Tailwind v4)
    read-only via anon key + RLS   |   /lab via authenticated role
```

## Why a Python engine rather than Next.js API routes

This is the design decision most likely to be questioned, so it is stated
plainly.

The analysis this project performs is Isolation Forest, K-Means with a silhouette
based k-search, and STL decomposition. Those come from **scikit-learn** and
**statsmodels**, which the proposal names explicitly and which have no serious
JavaScript equivalent. The JS ports that exist are unmaintained, lack the
diagnostics (silhouette samples, `score_samples`, STL residual series) that the
evaluation depends on, and would make the numbers in the paper impossible to
reproduce from a citable library version.

Splitting the system this way also buys a property that matters more than
convenience: **the write path and the read path have different privileges.** The
engine connects straight to Postgres through `DATABASE_URL`, as the database
owner, and is the only thing that can write. The web app holds the anon key and
can only read what RLS permits. If the dashboard is compromised, the worst
outcome is that already-public data is read again.

Note that the engine does **not** use a Supabase `service_role` key — there is no
such credential in this project. Nothing under `engine/src` reads one
(`grep -rn SERVICE_ROLE engine/src` returns nothing); `settings.py` exposes
`database_url()`, `supabase_url()`, `supabase_anon_key()` and `contact_email()`,
and no accessor for a service role. It was provisioned in two places and read by
none, so it was removed rather than rotated — see [deployment](deployment.md).
The privilege boundary is real; it just rests on the Postgres connection string,
which is also the one credential here that can `DROP TABLE`.

Next.js keeps two jobs: rendering the public dashboard, and hosting the `/lab`
labeling UI, where being a normal authenticated web form is exactly right.

## Data flow and the provenance chain

Every number rendered in the UI must be walkable backwards:

```
alerts.fusion_score
  -> price_daily_unified   (median across sources for that day)
    -> price_observations  (one row per source, in canonical units)
      -> raw_snapshots     (the response body, gzip-compressed)
        -> url + fetched_at
```

This is why `raw_snapshots` stores response bodies rather than discarding them
after parsing. Portals redesign without notice. Keeping the body means history
can be **re-parsed** under a new `parser_version` instead of re-scraped from an
archive that may no longer exist.

`fetch_failures` is the other half of that guarantee: a gap in
`price_observations` must always be explainable by a row there. There is no
synthetic fallback anywhere in this system. A failed scrape produces a recorded
failure, never an invented price.

## Database access

| Principal | Credential | Can |
|---|---|---|
| Engine | `DATABASE_URL` + service role | Everything. Bypasses RLS. |
| Public dashboard | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `SELECT` on presentation tables only |
| `/lab` | authenticated session | Read research tables; insert labels and SUS responses |

The intended posture is declared once, in `TABLE_AUDIENCE` in
`engine/src/siap/doctor.py`, and checked against the live catalog by
`siap doctor` — including a real HTTP request with the anon key that confirms
`raw_snapshots` and the ground-truth pool are genuinely unreachable. The posture
is asserted, not assumed.

`SUPABASE_SERVICE_ROLE_KEY` must never appear under `web/`. CI fails the build
if it does.

### Why direct Postgres rather than the Supabase REST API for the engine

1. Migrations are DDL, and PostgREST cannot run DDL.
2. A three-year backfill writes tens of thousands of rows. Batched SQL is orders
   of magnitude cheaper than HTTP round trips.
3. The engine connects as the database owner (`select current_user` → `postgres`),
   which is not subject to RLS at all, so routing through the API would add
   latency without adding a safety property.

## Schema as source of truth

`supabase/migrations/*.sql` is the only definition of the schema. The runner in
`engine/src/siap/migrate.py` records a SHA-256 of every applied file and
**refuses to run if an applied migration has changed on disk**. Editing an
applied migration would mean a fresh clone builds a different database than the
one the paper's numbers came from, which would quietly break the reproducibility
claim in M9. Schema changes go forward in a new migration.

Checksums are computed over LF-normalised content so a Windows checkout does not
trip the guard.

## Determinism

Nothing is written by an analysis module without a parent `analysis_runs` row
recording the git SHA, the RNG seed, the resolved parameter set and the library
versions in effect. Every model call takes `random_state` from configuration.
Every figure in the paper can therefore be traced to the exact code and
configuration that produced it.

## Configuration

All reference data and tunable parameters live in `engine/config/*.yaml`, never
in module bodies. The loader (`engine/src/siap/config.py`) uses
`extra="forbid"`, so a mistyped YAML key raises at load time instead of being
silently ignored and discovered as missing data weeks later. Cross-file
references are validated together: a source alias naming a portal that does not
exist, or a source claiming coverage of an unknown region, is reported with the
offending key named.

## Scope boundary

The system is **descriptive and diagnostic**. It detects anomalies that have
already happened, classifies current conditions, and surfaces recurring
historical patterns.

**It does not forecast prices.** There is no LSTM, no ARIMA, and no "prediksi
harga besok" anywhere in the code or the copy. A UI string that implies
prediction is a bug, not a feature.

## Local toolchain notes

- **Node 22** (`.node-version`). Node 20 reached end of life in April 2026, and
  the corepack shipped with it cannot launch current pnpm.
- **Python 3.12** for the engine; `requires-python = ">=3.11"`.
- Machines running TLS-intercepting antivirus (AVG, Kaspersky, Zscaler and
  similar) will fail to install packages, because the interception CA is trusted
  by Windows but absent from Python's `certifi` bundle and Node's built-in
  store. The fix is to *add* that CA to a bundle and point the tools at it —
  `PIP_CERT` / `pip config set global.cert` and `NODE_EXTRA_CA_CERTS` — rather
  than disabling verification. See `docs/changelog.md`.
