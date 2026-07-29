# Ground-truth labelling — coordinator's runbook

Two annotators label the same 399 candidates independently. Cohen's kappa
measures whether they were applying the same definition. **κ ≥ 0.60 is a gate,
not a metric**: below it, the brief says do not proceed — revise the definition,
re-label, and report both rounds.

Nothing downstream of the labels — precision, recall, F1, the four-arm
comparison — can be computed before this is done, and none of it is estimated in
the meantime.

---

## Before anyone labels

### 1. Confirm the pipeline is current

The pool must be drawn from the data the annotators will effectively be judging.
If anything upstream has changed — new backfill, a preprocessing change — re-run
`preprocess -> analyze -> cluster -> seasonal -> fuse`, then
`siap gt-pool --redraw`, **before** labelling starts. Once a label exists the
pool must not be redrawn, and `siap gt-pool --redraw` refuses by design.

This already happened twice during M7: once when SP2KP's provincial backfill
landed, and once when source linking was added (migration 0009). Both are
recorded in `docs/changelog.md`.

One limitation survives and is worth knowing while labelling: on eight series —
cabai, bawang merah and bawang putih — the two sources diverge enough that
linking them leaves a 5-9% residual. Days where the number of reporting sources
changes are still noisier there. `source_offsets.ratio_cv_pct` identifies them.

### 2. Create the two accounts

Supabase dashboard → **Authentication → Users → Add user**. Set a password and
tick *Auto Confirm User* so no email delivery is needed.

Accounts are created by hand on purpose. There is no sign-up page: the annotator
set is two named people agreed in the protocol, not whoever finds the URL.

### 3. Register them as annotators

```
siap lab-annotator --email grace@example.com --code A1
siap lab-annotator --email roy@example.com   --code A2
siap lab-annotator                              # list, to confirm
```

Codes are pseudonymous by constraint (`^[A-Z][0-9]{1,2}$`) — they appear in the
paper, so they must not be someone's name.

A signed-in user with no `lab_annotators` row sees an empty queue and cannot
write anything. That is the same mechanism that protects the pool, not a
separate check.

### 4. Verify the access model

```
siap lab-check
```

Becomes each annotator against the live database and tries the attacks: read the
pool directly, read the other annotator's labels, write a label under the other
annotator's code, see which stratum a candidate came from. All fixture rows are
rolled back.

**If any attempt fails, do not begin labelling.** The two label sets would not
be independent and kappa would be measuring contamination.

---

## Labelling

```
cd web && pnpm dev          # http://localhost:3000/lab
```

Each annotator signs in on their own machine and works through the queue. The
order is a seeded shuffle, identical for both, and the two strata are
interleaved so neither can be told apart.

### What they are deciding

> Does the price on the marked date deviate more than **10%** from the mean of
> the previous 30 days (the shaded band), **and** stay there for at least
> **2 days**?

The chart draws the band, so both halves of that rule are readable directly.
Beyond the arithmetic, the judgement that matters is whether a move that clears
the bar is a real market event or a data artefact — and whether anything in the
world corroborates it.

| label | when |
|---|---|
| **Tidak wajar** (anomali) | Outside the band for ≥2 days, with a reason to believe it happened: news, a government announcement, a BPS release, crop failure, a holiday, a supply disruption. **Evidence URL required.** |
| **Wajar** (normal) | Inside the band, or briefly outside and back, or a pattern that recurs every year for this commodity. |
| **Ragu** | A one-day spike that vanishes, many interpolated days nearby, or a figure that looks like bad input rather than a market move. |

`Ragu` is not a failure. A forced guess is worse than an honest abstention,
because kappa cannot distinguish a guess from a judgement.

### Rules for the annotators

- **Work alone.** Do not discuss candidates until both lists are finished.
  Independence is the premise of the whole measurement.
- **Saved labels cannot be changed.** A judgement that can be revised quietly is
  not an independent judgement.
- Keyboard: `1` tidak wajar, `2` wajar, `3` ragu, `Enter` save.
- Progress is shown per annotator and is resumable; closing the tab is safe.

### What the UI deliberately does not show

The anomaly score, the alert level, which stratum a candidate came from, and
anything the other annotator has said. The first two are absent from the data
the page can reach; the last two are impossible through the API, not merely
hidden — see `supabase/migrations/0005`–`0008` and `siap lab-check`.

---

## After both have finished

```
siap kappa                       # picks the two annotators automatically
siap kappa --a A1 --b A2
```

Prints κ, the Landis & Koch band, the confusion matrix and every disagreement.

- **κ ≥ 0.60** — adjudicate the disagreements and the `ragu` labels into
  `gt_events`, then run `siap ablate` and `siap export` for the metrics.
- **κ < 0.60** — stop. Revise the operational definition, re-label, and report
  both rounds in the paper. Do not proceed to the metrics; they would be built
  on labels that failed their own precondition.

Adjudication is a third person resolving conflicts into `gt_events` rows, which
carry an extent because the definition requires persistence for ≥2 days.

---

## SUS

`/lab/sus` — the standard 10-item instrument in Indonesian, administered by a
team member sitting with the respondent. `sus_responses.sus_score` is a
GENERATED column, so the form, the analysis and the paper cannot disagree about
the formula.

Respondent codes are pseudonymous. No personally identifying information about a
UMKM respondent is stored.
