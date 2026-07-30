/**
 * The commodity price chart.
 *
 * ## What this actually draws, and how it differs from `/lab`
 *
 * This file used to claim it was "the same construction the annotators saw in
 * /lab". That was false, and the correction matters because the two views answer
 * different questions:
 *
 * - `/lab` (`app/lab/PriceWindow.tsx`) draws the **annotation criterion** for one
 *   focus date: ±`definition_pct` around the arithmetic mean of raw
 *   `price_median` over calendar days t-30..t-1, imputed rows excluded, minimum
 *   20 observations. One scalar, correct for that view, read frozen out of
 *   `gt_candidates.context` — never recomputed in TypeScript.
 * - This chart spans 120 days of browsing and currently receives that same
 *   *shape* of number: one scalar `baselineMean`.
 *
 * **Known defect, stated rather than hidden:** the band here is flat across the
 * whole window, so points early in the window are compared against a mean drawn
 * partly from days that come after them. That is lookahead, and it is wrong in a
 * figure that goes in the paper. The fix is a persisted per-date baseline read
 * from Postgres (deferred to its own pass); until then the band is a rough guide
 * to scale, not a per-date judgement, and the caption says so.
 *
 * The detector's criterion is a third thing again — |z| >= 2.5 on **log** price —
 * and is deliberately not drawn here. Ground truth has to stay independent of the
 * detector or precision and recall become circular.
 *
 * No flags are drawn: `SeriesPoint` carries no flag field.
 *
 * ## Why hand-rolled SVG
 *
 * This loads on an entry-level Android over mobile data, and a charting bundle
 * would be the largest thing on the page by an order of magnitude. That argument
 * only holds if the output stays small, which is why every coordinate is rounded
 * to one decimal.
 */

import type { SeriesPoint } from "@/lib/dashboard";
import { buildSegments, r1 } from "@/lib/chartSegments";
import { DEFINITION_PCT } from "@/lib/dashboard";
import { formatPercent, formatRupiah, formatShortDate } from "@/lib/format";
import { MUTED } from "@/lib/ui";

const W = 680;
const H = 240;
const PAD = { top: 12, right: 12, bottom: 26, left: 68 };

/** Axis labels at ~7.8:1 in both schemes. `fill-neutral-500` was 4.17:1 on the
 *  dark background — the same defect measured across the app, in fill form. */
const AXIS_FILL = "fill-neutral-600 dark:fill-neutral-400";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Whole days since the epoch. Asserts the format instead of returning NaN: if
 *  `obs_date` ever becomes `timestamptz`, `"2026-07-29T00:00:00+07"` would split
 *  to NaN and every coordinate would silently become NaN. */
function dayNumber(iso: string): number {
  if (!ISO_DATE.test(iso)) {
    throw new Error(
      `PriceChart expects obs_date as YYYY-MM-DD, got "${iso}". ` +
        "If the column changed type, convert before it reaches this component.",
    );
  }
  const [y, m, d] = iso.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / 86_400_000);
}

export default function PriceChart({
  series,
  baselineMean,
}: {
  /**
   * One entry per calendar day, ascending, with explicit `price: null` for days
   * that have no figure.
   *
   * The gap-breaking above depends on that: `price_daily_unified` is written by
   * `preprocess` as a dense spine (measured: 0 missing calendar days across all
   * 60 series), so absent days arrive as null-priced rows rather than as absent
   * array entries. If that ever stops being true, gaps will be bridged by a
   * straight line and look like data.
   */
  series: SeriesPoint[];
  /**
   * Arithmetic mean of raw price over the trailing window — a single scalar, so
   * the band it produces is flat. See the module comment: that is lookahead and
   * is scheduled for replacement by a persisted per-date baseline.
   */
  baselineMean: number | null;
}) {
  const priced = series.filter((p) => p.price !== null);
  if (priced.length < 2) {
    return (
      <div
        className={`flex h-32 items-center justify-center rounded-lg border border-dashed border-neutral-300 px-4 text-center text-sm ${MUTED} dark:border-neutral-700`}
      >
        Belum cukup data harga untuk digambar.
      </div>
    );
  }

  // Ascending order is a contract, not a hope. The previous
  // `Math.max(1, x1 - x0)` turned an unsorted or reversed array into a span of 1
  // day and squashed every point onto the left edge — a wrong chart rather than
  // an error.
  for (let i = 1; i < series.length; i++) {
    if (dayNumber(series[i].date) <= dayNumber(series[i - 1].date)) {
      throw new Error(
        `PriceChart requires dates ascending and unique; ` +
          `${series[i - 1].date} is followed by ${series[i].date}.`,
      );
    }
  }

  const x0 = dayNumber(series[0].date);
  const x1 = dayNumber(series[series.length - 1].date);
  const spanX = x1 - x0;

  const values = priced.map((p) => p.price as number);
  if (baselineMean !== null) {
    values.push(baselineMean * (1 - DEFINITION_PCT), baselineMean * (1 + DEFINITION_PCT));
  }
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const padY = (hi - lo) * 0.12 || Math.max(1, hi * 0.05);
  const yLo = lo - padY;
  const yHi = hi + padY;

  const sx = (iso: string) =>
    PAD.left + ((dayNumber(iso) - x0) / spanX) * (W - PAD.left - PAD.right);
  const sy = (v: number) =>
    PAD.top + (1 - (v - yLo) / (yHi - yLo)) * (H - PAD.top - PAD.bottom);

  const { strokes, dots } = buildSegments(series, sx, sy);
  const hasImputed = series.some((p) => p.price !== null && p.imputed);

  const bandTop = baselineMean === null ? null : baselineMean * (1 + DEFINITION_PCT);
  const bandBottom = baselineMean === null ? null : baselineMean * (1 - DEFINITION_PCT);
  const ticks =
    baselineMean === null ? [lo, hi] : [bandBottom as number, baselineMean, bandTop as number];

  // Facts, not just a date range: a screen reader user got "grafik harga 30 Mar
  // sampai 29 Jul" and nothing else.
  const last = priced[priced.length - 1];
  const lastPrice = last.price as number;
  const outside =
    bandTop !== null && bandBottom !== null && (lastPrice > bandTop || lastPrice < bandBottom);
  const deviation = baselineMean ? lastPrice / baselineMean - 1 : null;
  const ariaLabel = [
    `Grafik harga ${formatShortDate(series[0].date)} sampai ${formatShortDate(last.date)}.`,
    `Harga terakhir ${formatRupiah(lastPrice)} pada ${formatShortDate(last.date)}.`,
    baselineMean === null
      ? "Rata-rata 30 hari sebelumnya tidak bisa dihitung, jadi tidak ada pita pembanding."
      : `Rata-rata 30 hari ${formatRupiah(baselineMean)}, selisih ${formatPercent(
          deviation as number,
        )}. Harga terakhir ${outside ? "di luar" : "di dalam"} pita ±${Math.round(
          DEFINITION_PCT * 100,
        )}%.`,
    hasImputed ? "Sebagian hari adalah hasil interpolasi, digambar dengan garis putus-putus." : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <figure className="w-full">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={ariaLabel}>
        <defs>
          {/* A tint alone does not survive desaturation — `fill-amber-100/70`
              became indistinguishable from the page in grayscale, and
              design.md's own argument is that a signal carried by colour only is
              not carried at all. The hatch is geometry, so it survives. */}
          <pattern id="band-hatch" width="6" height="6" patternUnits="userSpaceOnUse">
            <path
              d="M0,6 L6,0"
              className="stroke-amber-500/50 dark:stroke-amber-400/40"
              strokeWidth={1}
            />
          </pattern>
        </defs>

        {baselineMean !== null && (
          <>
            <rect
              x={PAD.left}
              y={r1(sy(bandTop as number))}
              width={W - PAD.left - PAD.right}
              height={Math.max(0, r1(sy(bandBottom as number) - sy(bandTop as number)))}
              fill="url(#band-hatch)"
            />
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={r1(sy(baselineMean))}
              y2={r1(sy(baselineMean))}
              className="stroke-amber-600 dark:stroke-amber-400"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
          </>
        )}

        {ticks.map((v, i) => (
          // Keyed by index: `key={v}` collided whenever two ticks shared a value,
          // which happens for real when baselineMean is 0.
          <text
            key={`tick-${i}`}
            x={PAD.left - 8}
            y={r1(sy(v)) + 4}
            textAnchor="end"
            className={`${AXIS_FILL} text-[11px]`}
          >
            {formatRupiah(v)}
          </text>
        ))}

        {strokes.map((s, i) => (
          <path
            key={`s-${i}`}
            d={s.d}
            fill="none"
            className="stroke-neutral-800 dark:stroke-neutral-200"
            strokeWidth={1.75}
            strokeLinejoin="round"
            strokeDasharray={s.imputed ? "3 3" : undefined}
          />
        ))}

        {dots.map((p, i) => (
          <circle
            key={`d-${i}`}
            cx={p.x}
            cy={p.y}
            r={2.25}
            className={
              p.imputed
                ? "fill-white stroke-neutral-800 dark:fill-neutral-950 dark:stroke-neutral-200"
                : "fill-neutral-800 dark:fill-neutral-200"
            }
            strokeWidth={p.imputed ? 1.25 : 0}
          />
        ))}

        <text x={PAD.left} y={H - PAD.bottom + 16} className={`${AXIS_FILL} text-[11px]`}>
          {formatShortDate(series[0].date)}
        </text>
        <text
          x={W - PAD.right}
          y={H - PAD.bottom + 16}
          textAnchor="end"
          className={`${AXIS_FILL} text-[11px]`}
        >
          {formatShortDate(series[series.length - 1].date)}
        </text>
      </svg>

      {/* An unexplained marker means nothing to a warung owner and is a reviewer
          finding in a paper figure. */}
      <figcaption className={`mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs ${MUTED}`}>
        {baselineMean !== null ? (
          <span>
            <svg width="14" height="9" className="mr-1 inline-block align-middle" aria-hidden>
              <rect width="14" height="9" fill="url(#band-hatch)" />
            </svg>
            pita &plusmn;{Math.round(DEFINITION_PCT * 100)}% dari rata-rata 30 hari — pembanding
            kasar, dihitung sekali untuk seluruh rentang
          </span>
        ) : (
          <span>rata-rata 30 hari tidak bisa dihitung, jadi tidak ada pita pembanding</span>
        )}
        <span>
          <svg width="16" height="4" className="mr-1 inline-block align-middle" aria-hidden>
            <line
              x1="0"
              y1="2"
              x2="16"
              y2="2"
              className="stroke-neutral-800 dark:stroke-neutral-200"
              strokeWidth="1.75"
            />
          </svg>
          harga tercatat
        </span>
        {hasImputed && (
          <span>
            <svg width="16" height="4" className="mr-1 inline-block align-middle" aria-hidden>
              <line
                x1="0"
                y1="2"
                x2="16"
                y2="2"
                className="stroke-neutral-800 dark:stroke-neutral-200"
                strokeWidth="1.75"
                strokeDasharray="3 3"
              />
            </svg>
            hasil interpolasi, bukan pencatatan
          </span>
        )}
      </figcaption>
    </figure>
  );
}
