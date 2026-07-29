# Deployment

What it takes to put the dashboard and `/lab` on a URL Grace and Roy can open.

The engine does **not** deploy here — it runs on GitHub Actions against the same
Supabase project (`.github/workflows/daily.yml`). Only `web/` is hosted.

---

## Before you deploy: rotate the credentials

The `service_role` key and the database password were pasted in plain text
during development. The service role **bypasses every RLS policy in this
project** — it can read the raw snapshot bodies, the per-source prices and the
unblinded ground-truth pool.

Do this first, not later:

1. Supabase → **Project Settings → API → service_role** → *Generate new key*
2. Supabase → **Project Settings → Database** → reset the password
3. Update the repo-root `.env` (`SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`)
4. Update the GitHub Actions secrets of the same names
5. `siap doctor` to confirm the engine still connects

The **anon** key does not need rotating. It is browser-exposed by design and
constrained by RLS; that is what it is for.

---

## Deploy to Vercel

Vercel is the path of least resistance for Next.js. Any Node host works.

### 1. Import the repository

New Project → import this repo → **set Root Directory to `web`**. This matters:
the repo root holds `engine/` and `supabase/`, and Vercel would otherwise find
no Next.js app.

Node 22 comes from `web/package.json` → `engines.node`, so there is nothing to
configure. Build command, output directory and install command are all correct
by default.

### 2. Environment variables

Exactly two, both marked for Production, Preview and Development:

| name | value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the **anon** key, never the service role |

`web/src/lib/supabase.ts` decodes the key at startup and **throws if it carries
a `service_role` claim**, so a wrong paste fails the build rather than shipping
a key that reads everything.

Nothing else belongs here. `DATABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` must
never appear in a Vercel project whose output is a browser bundle.

### 3. Deploy, then check four things

```
/                                  region chooser lists 4 regions
/wilayah/di_yogyakarta             a board with a date, not an empty page
/wilayah/di_yogyakarta/bukan-bahan 404 in Indonesian, not a stack trace
/robots.txt                        Disallow: /lab
```

If the boards are empty, the analysis has not been run against this database —
see [`docs/reproducibility.md`](reproducibility.md) §3.

---

## Give Grace and Roy access

Accounts already exist. What they need is the URL and the rules.

**Send them:**

> Pelabelan ground truth SIAP-PANGAN
> `https://<your-deployment>/lab`
> Masuk pakai email dan kata sandi yang sudah dibuat koordinator.
>
> Tiga hal penting:
> 1. Kerjakan sendiri. Jangan mendiskusikan kandidat dengan annotator lain
>    sampai kedua daftar selesai — nilai kesepakatan hanya bermakna kalau kedua
>    penilaian independen.
> 2. Label yang sudah disimpan tidak bisa diubah.
> 3. Kalau ragu, pilih "Ragu". Menebak lebih merusak daripada mengaku tidak
>    yakin.
>
> Panduan lengkap ada di dalam aplikasi (tombol "Panduan lengkap").

**Before they start**, from `engine/`:

```bash
siap lab-check          # must pass 14/14, or the labels are not independent
siap lab-annotator      # confirm exactly who is registered
```

`lab-check` becomes each annotator against the live database and tries to read
the pool, read the other's labels, and write under the other's code. If any
attempt succeeds, do not begin — κ would be measuring contamination.

### One decision outstanding

Three annotators are registered: A1 (Grace), A2 (Roy) and A3. Cohen's κ is
defined for a **pair**. If A3 is the adjudicator, they should be resolving
disagreements into `gt_events` rather than labelling blind — nobody can
impartially adjudicate disagreements they are party to.

`siap kappa` refuses to guess which two, so nothing silently goes wrong. But the
cleaner course is to remove A3 before labelling starts:

```sql
delete from public.lab_annotators where annotator_code = 'A3';
```

---

## What is deployed, and what is not

| | hosted | where |
|---|---|---|
| Public dashboard | yes | Vercel, anon key + RLS |
| `/lab` labelling console | yes | Vercel, authenticated session + RLS |
| `/lab/sus` SUS form | yes | same |
| Ingestion + analysis | no | GitHub Actions, `daily.yml`, 02:00 WIB |
| Figures and tables | no | `siap export`, local, gitignored |

`/lab` is served from the same deployment as the dashboard. It is protected by
RLS, not by being hidden: an unauthenticated request to the labelling queue
returns nothing regardless of who asks. `robots.txt` disallows it as hygiene, so
it does not turn up in search results.

---

## Keeping it fresh

`daily.yml` runs at 02:00 WIB: it ingests yesterday, re-runs the whole analysis,
verifies the run reproduces, and closes abandoned runs. It needs these secrets
on the repository:

`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
`SIAP_CONTACT_EMAIL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`

Dashboard pages revalidate every 30 minutes, so new alerts appear within half an
hour of the analysis finishing without a redeploy.
