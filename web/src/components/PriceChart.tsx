/**
 * The commodity price chart.
 *
 * Deliberately the same construction the annotators saw in `/lab`: observed
 * series, the 30-day mean, and a +/-10% band. What the paper evaluated and what
 * a warung owner looks at are then the same picture, rather than two different
 * renderings of the same numbers that happen to disagree.
 *
 * Inline SVG, no chart library: this loads on an entry-level Android over
 * mobile data, and a charting bundle would be the largest thing on the page by
 * an order of magnitude.
 */

import type { SeriesPoint } from "@/lib/dashboard";
import { DEFINITION_PCT } from "@/lib/dashboard";
import { formatRupiah, formatShortDate } from "@/lib/format";

const W = 680;
const H = 240;
const PAD = { top: 12, right: 12, bottom: 26, left: 68 };

function dayNumber(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / 86_400_000);
}

export default function PriceChart({
  series,
  baselineMean,
}: {
  series: SeriesPoint[];
  baselineMean: number | null;
}) {
  const priced = series.filter((p) => p.price !== null);
  if (priced.length < 2) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-neutral-300 px-4 text-center text-sm text-neutral-500 dark:border-neutral-700">
        Belum cukup data harga untuk digambar.
      </div>
    );
  }

  const x0 = dayNumber(series[0].date);
  const x1 = dayNumber(series[series.length - 1].date);
  const spanX = Math.max(1, x1 - x0);

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

  // Break the line across missing days rather than bridging them: a straight
  // segment over a fortnight of no data looks like data.
  const segments: string[] = [];
  let current: string[] = [];
  for (const p of series) {
    if (p.price === null) {
      if (current.length > 1) segments.push(current.join(" "));
      current = [];
      continue;
    }
    current.push(`${current.length ? "L" : "M"}${sx(p.date)},${sy(p.price)}`);
  }
  if (current.length > 1) segments.push(current.join(" "));

  const ticks =
    baselineMean === null
      ? [lo, hi]
      : [
          baselineMean * (1 - DEFINITION_PCT),
          baselineMean,
          baselineMean * (1 + DEFINITION_PCT),
        ];

  return (
    <figure className="w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`Grafik harga ${formatShortDate(series[0].date)} sampai ${formatShortDate(
          series[series.length - 1].date,
        )}`}
      >
        {baselineMean !== null && (
          <>
            <rect
              x={PAD.left}
              y={sy(baselineMean * (1 + DEFINITION_PCT))}
              width={W - PAD.left - PAD.right}
              height={Math.max(
                0,
                sy(baselineMean * (1 - DEFINITION_PCT)) -
                  sy(baselineMean * (1 + DEFINITION_PCT)),
              )}
              className="fill-amber-100/70 dark:fill-amber-500/10"
            />
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={sy(baselineMean)}
              y2={sy(baselineMean)}
              className="stroke-amber-500/70"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
          </>
        )}

        {ticks.map((v) => (
          <text
            key={v}
            x={PAD.left - 8}
            y={sy(v) + 4}
            textAnchor="end"
            className="fill-neutral-500 text-[11px]"
          >
            {formatRupiah(v)}
          </text>
        ))}

        {segments.map((d, i) => (
          <path
            key={i}
            d={d}
            fill="none"
            className="stroke-neutral-800 dark:stroke-neutral-200"
            strokeWidth={1.75}
            strokeLinejoin="round"
          />
        ))}

        {series
          .filter((p) => p.price !== null && p.imputed)
          .map((p) => (
            <circle
              key={p.date}
              cx={sx(p.date)}
              cy={sy(p.price as number)}
              r={2.5}
              className="fill-white stroke-neutral-500 dark:fill-neutral-950"
              strokeWidth={1}
            />
          ))}

        <text x={PAD.left} y={H - PAD.bottom + 16} className="fill-neutral-500 text-[11px]">
          {formatShortDate(series[0].date)}
        </text>
        <text
          x={W - PAD.right}
          y={H - PAD.bottom + 16}
          textAnchor="end"
          className="fill-neutral-500 text-[11px]"
        >
          {formatShortDate(series[series.length - 1].date)}
        </text>
      </svg>
    </figure>
  );
}
