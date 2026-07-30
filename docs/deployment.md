# Deployment

What it takes to put the dashboard and `/lab` on a URL Grace and Roy can open.

The engine does **not** deploy here — it runs on GitHub Actions against the same
Supabase project (`.github/workflows/daily.yml`). Only `web/` is hosted.

---

## Credentials: one to protect, one that should not exist

There are only two secrets in this project, and they are not equally important.

**`DATABASE_URL` is the one that matters.** It is a direct Postgres connection
used by every engine command and every workflow. It can `DROP TABLE`, which
means it can destroy three years of backfill. It was pasted in plain text during
development, so reset the password and update it in both places:

1. Supabase → **Project Settings → Database** → reset the password
2. Update the repo-root `.env`
3. Update the `DATABASE_URL` GitHub Actions secret
4. `siap doctor` to confirm the engine still connects

**There is no service role key, on purpose.** `grep -rn SERVICE_ROLE engine/src`
returns nothing: `settings.py` exposes `database_url()`, `supabase_url()`,
`supabase_anon_key()` and `contact_email()`, and no accessor for a service role.
Writes go to Postgres directly. A credential that bypasses every RLS policy —
raw snapshot bodies, per-source prices, the unblinded ground-truth pool — is not
worth storing for a feature nothing uses, so it is removed rather than rotated.
Deleting a secret is strictly stronger than replacing it.

If a `SUPABASE_SERVICE_ROLE_KEY` line survives in anyone's local `.env`, delete
it. Nothing will notice.

The legacy key still exists in the Supabase project and still works for anyone
holding a copy. Retiring it means *Disable legacy API keys*, which also retires
`anon` — so it needs a publishable key first. `web/src/lib/supabase.ts:31`
already returns early for non-JWT keys and its comment names
`sb_publishable_...` explicitly, so the app is ready for that whenever the
migration is worth doing.

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

The framework is pinned in `web/vercel.json`:

```json
{ "framework": "nextjs" }
```

`vercel.json` takes precedence over Project Settings, so framework detection is
recorded in the repo and reviewable in a diff rather than depending on a
dashboard field. It lives in `web/` because Vercel reads `vercel.json` from the
Root Directory, not the repo root. Note it only overrides the keys it names:
Root Directory is not among them and still has to be set in the dashboard.

### Two failure signatures, and what each one means

Both were hit during the first deployment. They look similar — a red build — and
have nothing to do with each other.

| build log says | duration | cause |
|---|---|---|
| `No Next.js version detected` | ~2 s | Root Directory is not `web`, so there is no `package.json` to read |
| `No Output Directory named "public" found` | ~70 s | Vercel is not treating the project as Next.js, so it looks for a static site |

The second one is confusing because the build *succeeds* — pages compile and
generate — and only the publish step fails. The tell is a missing
`Detected Next.js version` line in the log. `web/vercel.json` now prevents it.

**Check the project list before debugging anything.** Importing the repo twice
produces two projects that both build on every push and fail in different ways,
and it is easy to spend hours reading the logs of one while changing the
settings of the other. One repo, one project.

Also note that *Redeploy* rebuilds the **same commit** as the deployment it was
launched from — it does not pick up newer commits. To build something new, push,
or redeploy the deployment that push created.

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
> `https://talks-siap-pangan.vercel.app/lab`
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

`DATABASE_URL`, `SUPABASE_URL`, `SIAP_CONTACT_EMAIL`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`

**These are not currently set.** `gh api repos/<owner>/<repo>/actions/secrets`
returns `total_count: 0`, so every scheduled run fails on a missing
`DATABASE_URL` — the schedule exists but the pipeline has never completed once.
Until they are added, the dashboard is only as fresh as the last time somebody
ran the engine by hand.

Dashboard pages revalidate every 30 minutes, so new alerts appear within half an
hour of the analysis finishing without a redeploy.
