# Design direction — the public dashboard

Written before the dashboard, as `web/src/app/page.tsx` and `layout.tsx` promised
in M0. The point is to decide the hard things once, in prose, so the components
are an implementation of a position rather than a series of improvisations.

## Who this is for

A warung owner in Yogyakarta, Central Java or East Java, on a phone, one-handed,
between customers. Probably an entry-level Android. Probably on data.

Everything below follows from that person, not from what looks impressive in a
presentation.

## What the dashboard is allowed to say

**It describes what has already happened.** It does not forecast. There is no
"harga besok", no projection, no trend line extended past the last observation.
This is not modesty — the system contains no forecasting model, and a UI that
implies otherwise would be claiming a capability that does not exist.

The strongest permitted statement is of the form *"harga X naik Y% dibanding
rata-rata 30 hari terakhir, dan sudah bertahan Z hari"*. Everything else is
context for that sentence.

## The four levels, and the copy trap in each

`siaga` / `waspada` / `tenang` come from the fusion score, plus
`belum_dapat_dinilai` for a date no detector could score. The obvious copy for
them is wrong in three specific ways, the first two recorded during M6:

**`waspada` does not mean "harga naik".** It means the price is behaving
unusually — unstable, moving more than this commodity normally moves. It can be
`waspada` while falling. Copy must say *"harga tidak stabil"*, never *"harga
naik"*.

**`siaga` can fire on a crash.** The fusion score uses `|pct_change_7d|`, so a
collapse scores exactly like a spike. For a warung owner these are opposite
situations: a spike means delay the purchase, a crash means buy now. **Every
alert must state its direction**, and the recommendation must follow the
direction rather than the level alone.

`tenang` means "nothing unusual", not "cheap". A commodity can sit at a
historically high price perfectly stably and be `tenang`.

**`belum_dapat_dinilai` is not a fourth severity — it sits outside the
ordering.** It means no detector produced a score for that date, which the
system previously rendered as `hijau`: absence of evidence shown as evidence of
safety, on 41.31% of `nasional` dates. Its copy must say what is *missing*, and
must never be grouped under "bergerak wajar". It carries no recommendation,
because there is no observation to base one on.

**The level names are deliberately not the cluster zone names.** `zone` stays
`merah`/`kuning`/`hijau` — the proposal commits to those words — and both render
on the commodity page while disagreeing on 22.6% of pairs. Two different
quantities spelled identically on one screen is a defect, and the one without a
textual commitment is the one that moved.

## Recommendations are observations plus an option

`fusion.yaml` already fixes this: *"pertimbangkan menunda"*, never *"jangan
beli"*. The system does not know this person's cash position, storage, or what
their customers will pay. It knows what the price did. It offers one option and
leaves the decision where it belongs.

## Freshness, and why the front page is not today

Measured during M8: on the current date, Siskaperbapo publishes **round
placeholder figures** that are replaced by computed multi-market averages the
next day. Its baseline rate of prices divisible by 500 is **0.4%**; on the
current date it is **83.3%**. Those placeholders produced a board where **12 of
12** East Java commodities were flagged, against 4 and 5 of 12 for regions whose
latest day had settled.

So **the dashboard shows the latest settled day, which is the most recent date
before today**, resolved per region because the regions do not share a latest
date. The date is always printed. A dashboard that says "hari ini" over
provisional numbers is worse than one that says "data terakhir: Selasa, 28 Juli"
and means it.

This costs nothing operationally: the engine runs at 02:00 WIB on the previous
day's data.

## Visual direction

**Type.** System stack. No webfont. A webfont is a render-blocking network
request on a slow connection, bought for an aesthetic this audience did not ask
for. Numbers use tabular figures so a column of prices aligns.

**Colour is never the only signal.** Level is carried by a text label first,
then an icon shape, then colour. Roughly 8% of men have some red-green colour
deficiency, and the red/green tone pair is precisely the confusable one. Red and
green that cannot be told apart would make the primary output of this system
unusable for that reader.

Renaming the levels to `siaga`/`waspada`/`tenang` closed the last place this
rule was being satisfied on a technicality: the label itself used to be a colour
word, so "the text carries the meaning" was true only for a reader who already
knew what the colour meant. The names now escalate in plain Indonesian, and the
tones are decoration.

**Rupiah in full, never abbreviated.** "Rp 62.500", not "Rp 62,5rb". The
abbreviation saves a few characters and introduces an ambiguity into the one
number on the page that must not be ambiguous.

**No chart the eye cannot check.** The commodity chart shows the observed
series, the 30-day mean, and a shaded band — the same construction the
annotators used in `/lab`, deliberately, so what the paper evaluated and what a
user sees are the same picture.

**Interpolated days are drawn differently** from observed ones, everywhere they
appear. A user is entitled to know which points were measured.

## Provenance on the surface

Every screen states its date, its source count, and links to a page naming the
portals. The claim in `docs/architecture.md` is that any number can be walked
back to a URL and a timestamp; if that chain is invisible to the reader it is
not a real property of the product.

The commodity page names the sources for that specific series, because coverage
differs — East Java has three sources, Kota Yogyakarta has one.

## What is deliberately absent

- Login. The dashboard is public and read-only; asking a warung owner to make an
  account to see a government price is an obstacle with no purpose.
- Notifications. Would require accounts and a delivery channel, and neither is
  in scope.
- Any national aggregate presented as *their* price. `nasional` exists as a
  series but a Yogyakarta warung buys in Yogyakarta.
