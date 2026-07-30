# SIAP-PANGAN

**Sistem Analitik Harga Pangan** — Tim RGB, TALKS Season 2 (S2 Informatika × TICELS UAJY).

Research implementation of *Deteksi Anomali dan Klasterisasi Harga Komoditas Pangan
Menggunakan Metode Hybrid Statistical-Machine Learning untuk Efisiensi Stok UMKM.*

The system aggregates Indonesian food-commodity prices from four official portals
plus a Google Trends demand signal, runs anomaly detection, clustering and
seasonal decomposition over them, fuses the outputs into one alert level per
commodity, and presents the result as a mobile-first dashboard for UMKM owners.

> **Scope boundary.** This system is descriptive and diagnostic. It detects
> anomalies that have already happened, classifies current conditions, and
> surfaces recurring historical patterns. **It does not forecast prices.**

**Live dashboard:** <https://talks-siap-pangan.vercel.app> — labelling console at
`/lab`, reachable only with an annotator account.

## Layout

| Path | What lives there |
|---|---|
| `engine/` | Python analysis engine: scrapers, preprocessing, models, evaluation |
| `engine/config/` | All tunable parameters and reference data (YAML) |
| `supabase/migrations/` | Numbered SQL migrations — the single source of schema truth |
| `web/` | Next.js dashboard (read-only) and `/lab` research console |
| `scripts/` | Repo-wide checks that belong to neither side, run by CI |
| `docs/` | **[panduan](docs/panduan.md) — operator's guide, in Indonesian: what every step does, and how the annotators get in.** Then [architecture](docs/architecture.md), [methods](docs/methods.md), [design](docs/design.md), [reproducibility](docs/reproducibility.md), [deployment](docs/deployment.md), [sources](docs/sources.md), [labelling](docs/labelling.md), [changelog](docs/changelog.md) |
| `paper-exports/` | Generated figures and tables (gitignored) |

## Setup

Requires Python 3.12+, Node 22 (see `.node-version`), pnpm, and a Supabase project.

```bash
cp .env.example .env          # then fill in the values

# engine
cd engine
py -3.12 -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[dev]"          # development
# or, to reproduce a published number exactly:
#   pip install -r requirements.lock && pip install -e . --no-deps

siap config                   # validate engine/config/*.yaml, no database needed
siap migrate                  # apply supabase/migrations/*.sql in order
siap seed                     # load reference data from engine/config/*.yaml
siap doctor                   # verify schema, RLS posture and seeded data

# ingestion
siap ingest                              # yesterday, all active sources
siap ingest --source pihps --date 2026-07-27
siap backfill --source pihps --start 2023-07-29 --end 2026-07-29   # resumable
siap trends                              # demand signal; best-effort
siap coverage --detail --samples 5       # coverage + provenance samples

# analysis
siap preprocess               # rebase sources, rebuild the daily series
siap analyze                  # Z-Score + Isolation Forest
siap cluster                  # K-Means regimes
siap seasonal                 # STL
siap fuse                     # one alert level per commodity
siap reproduce                # recompute the last run and diff it, score by score

# research
siap gt-pool                  # stratified ground-truth pool
siap lab-check                # attack the /lab access model, then roll back
siap kappa                    # inter-annotator agreement (the M7 stop condition)
siap ablate                   # parameter sensitivity
siap export                   # figures and tables -> paper-exports/

# web
cd ../web
cp .env.example .env.local    # then fill in the two NEXT_PUBLIC_ values
pnpm install
pnpm dev
```

Run the checks the way CI does:

```bash
cd engine && ruff check . && ruff format --check . && mypy && pytest
cd ../web && pnpm typecheck && pnpm lint && pnpm build
cd ..    && python scripts/assert_no_service_role.py \
         && python scripts/assert_no_service_role.py --self-test
```

The last one asserts no service-role credential is reachable from `web/`, then
asserts the check itself still catches a planted leak. It inspects key *values*,
not the variable name — the name appears legitimately in the comment warning
about it and in the runtime guard that rejects it.

### Windows + fnm

`fnm` does not switch Node versions automatically unless its shell integration
is installed, and `pnpm` resolves against whichever Node is active. If `pnpm`
fails with `ERR_VM_DYNAMIC_IMPORT_CALLBACK_MISSING`, an older Node is in front:
its bundled corepack cannot launch current pnpm.

One-time setup, so `.node-version` is honoured on `cd`:

```powershell
# 1. install pnpm shims for Node 22
& "$env:APPDATA\fnm\node-versions\v22.23.1\installation\corepack.cmd" `
    enable --install-directory "$env:APPDATA\fnm\node-versions\v22.23.1\installation" pnpm

# 2. add to $PROFILE.CurrentUserAllHosts
fnm env --use-on-cd --shell power-shell | Out-String | Invoke-Expression
$env:FNM_VERSION_FILE_STRATEGY = 'recursive'
```

`recursive` matters: fnm defaults to `local`, which only inspects the current
directory, and `.node-version` lives at the repo root while most work happens in
`web/`.

Note that fnm hooks the `cd` alias, not `Set-Location` — a script that uses
`Set-Location` will not trigger the version switch.

Without touching the profile, prepend Node 22 for the current shell only:

```powershell
$env:PATH = "$env:APPDATA\fnm\node-versions\v22.23.1\installation;" + $env:PATH
```

> **TLS-intercepting antivirus.** If `pip install` or `pnpm install` fails with
> `CERTIFICATE_VERIFY_FAILED`, an antivirus (AVG, Kaspersky, Zscaler…) is
> re-signing HTTPS with a CA that Windows trusts but Python and Node do not.
> Add that CA to a bundle and point the tools at it via `PIP_CERT` and
> `NODE_EXTRA_CA_CERTS`. Do not disable verification. See
> [`docs/changelog.md`](docs/changelog.md).

## Build discipline

Development proceeds one milestone at a time (M0 … M9), each ending in a stop
gate that must be verified by a human against the live database or a browser —
not by reading code. Current state and every deviation from the original brief
are recorded in [`docs/changelog.md`](docs/changelog.md).

**No fabricated data, ever.** If a scraper fails, the run fails loudly and
writes a `fetch_failures` row. Every number rendered in the UI traces to a row
in Postgres, which traces to a `raw_snapshots` entry, which traces to a URL and
a fetch timestamp.

**Determinism is checked, not asserted.** Every run records its git SHA, seed,
resolved parameters and library versions; `siap reproduce` reloads a run's own
parameters, recomputes every score and diffs them row by row. Last verified:
run #47, 78,274 scores, all identical. The same check runs on every scheduled
pipeline. See [`docs/reproducibility.md`](docs/reproducibility.md).

## Deploying, and starting the study

`web/` is the only thing hosted, at <https://talks-siap-pangan.vercel.app>; the
engine runs on GitHub Actions against the same Supabase project. Root directory
`web`, two `NEXT_PUBLIC_*` environment variables, nothing else. Full steps —
including credential rotation, which should happen first — are in
[`docs/deployment.md`](docs/deployment.md).

Before Grace and Roy label anything:

```bash
cd engine
siap lab-check        # must pass 14/14 — proves the two label sets stay independent
siap lab-annotator    # confirm exactly who is registered
```

## Data sources

| source | owner | status | archive |
|---|---|---|---|
| `sp2kp` | Kementerian Perdagangan | ✅ | 2024-02-01 → |
| `pihps` | Bank Indonesia | ✅ | 3 years |
| `siskaperbapo` | Pemprov Jawa Timur | ✅ | 3 years |
| `jogja` | Pemkot Yogyakarta | ✅ forward-only | none available |
| `panelharga` | Badan Pangan Nasional | ❌ disabled | upstream outage |
| `trends` | Google Trends (pytrends) | best-effort | up to 5 years |

Endpoints, quirks and every judgement call are documented in
[`docs/sources.md`](docs/sources.md). Scraping conduct — robots.txt, a ≥2 s
delay, one connection per host, and a User-Agent naming the project and a
contact address — is enforced centrally in the scraper base class, not per
scraper.
