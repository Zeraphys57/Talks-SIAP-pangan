"use client";

/**
 * The evidence chart: 30 days before the candidate date and 14 after.
 *
 * The shaded band is +/-10% around the trailing 30-day mean, which is the
 * operational definition of an anomaly stated in the brief. Drawing it makes
 * both halves of that definition readable at a glance — magnitude, from how far
 * outside the band a point sits, and persistence, from how many consecutive
 * days stay outside.
 *
 * It contains no model output. There is no anomaly score here, no alert level
 * and no flag; showing one would make the label a judgement about the model
 * rather than independent evidence about the world.
 */

import type { CandidateContext } from "@/lib/types";
import { formatRupiah, formatShortDate } from "@/lib/format";

const W = 720;
const H = 260;
const PAD = { top: 16, right: 16, bottom: 28, left: 74 };

type Props = { context: CandidateContext };

function dayNumber(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / 86_400_000);
}

export default function PriceWindow({ context }: Props) {
  const points = context.window;
  const priced = points.filter((p) => p.price !== null);

  if (priced.length < 2) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-neutral-300 px-4 text-center text-sm text-neutral-600 dark:text-neutral-400 dark:border-neutral-700">
        Data harga di sekitar tanggal ini terlalu sedikit untuk digambar.
      </div>
    );
  }

  const mean = context.baseline.mean_price;
  const pct = context.definition_pct;
  const focus = dayNumber(context.focus_date);

  const x0 = dayNumber(points[0].date);
  const x1 = dayNumber(points[points.length - 1].date);
  const spanX = Math.max(1, x1 - x0);

  // The band must be inside the y-range even when no price reaches it,
  // otherwise a series that never leaves the band would render the band
  // clipped and the "how far outside" reading would be wrong.
  const values = priced.map((p) => p.price as number);
  if (mean !== null) values.push(mean * (1 - pct), mean * (1 + pct));
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
  // segment over a two-week gap looks like data that was never collected.
  const segments: string[] = [];
  let current: string[] = [];
  for (const p of points) {
    if (p.price === null) {
      if (current.length > 1) segments.push(current.join(" "));
      current = [];
      continue;
    }
    current.push(`${current.length ? "L" : "M"}${sx(p.date)},${sy(p.price)}`);
  }
  if (current.length > 1) segments.push(current.join(" "));

  const focusX = PAD.left + ((focus - x0) / spanX) * (W - PAD.left - PAD.right);
  const focusPoint = points.find((p) => p.date === context.focus_date);

  const ticks = mean === null ? [yLo, yHi] : [mean * (1 - pct), mean, mean * (1 + pct)];

  return (
    <figure className="w-full">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`Grafik harga dari ${points[0].date} sampai ${points[points.length - 1].date}`}
      >
        {mean !== null && (
          <>
            <rect
              x={PAD.left}
              y={sy(mean * (1 + pct))}
              width={W - PAD.left - PAD.right}
              height={Math.max(0, sy(mean * (1 - pct)) - sy(mean * (1 + pct)))}
              className="fill-amber-100/70 dark:fill-amber-500/10"
            />
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={sy(mean)}
              y2={sy(mean)}
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

        {/* The day being judged. */}
        <line
          x1={focusX}
          x2={focusX}
          y1={PAD.top}
          y2={H - PAD.bottom}
          className="stroke-neutral-900 dark:stroke-neutral-100"
          strokeWidth={1.5}
        />
        <text
          x={focusX}
          y={H - PAD.bottom + 16}
          textAnchor="middle"
          className="fill-neutral-900 text-[11px] font-medium dark:fill-neutral-100"
        >
          {formatShortDate(context.focus_date)}
        </text>

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

        {/* Interpolated days are hollow: the annotator must be able to tell a
            price that was collected from one this system filled in. */}
        {points
          .filter((p) => p.price !== null && p.imputed)
          .map((p) => (
            <circle
              key={p.date}
              cx={sx(p.date)}
              cy={sy(p.price as number)}
              r={3}
              className="fill-white stroke-neutral-500 dark:fill-neutral-950"
              strokeWidth={1.25}
            />
          ))}

        {focusPoint?.price != null && (
          <circle
            cx={focusX}
            cy={sy(focusPoint.price)}
            r={5}
            className="fill-neutral-900 dark:fill-neutral-100"
          />
        )}

        <text x={PAD.left} y={H - PAD.bottom + 16} className="fill-neutral-500 text-[11px]">
          {formatShortDate(points[0].date)}
        </text>
        <text
          x={W - PAD.right}
          y={H - PAD.bottom + 16}
          textAnchor="end"
          className="fill-neutral-500 text-[11px]"
        >
          {formatShortDate(points[points.length - 1].date)}
        </text>
      </svg>

      <figcaption className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-600 dark:text-neutral-400">
        {mean !== null ? (
          <span>
            <span className="mr-1 inline-block h-2 w-3 rounded-sm bg-amber-100 align-middle dark:bg-amber-500/20" />
            pita &plusmn;{Math.round(pct * 100)}% dari rata-rata {context.baseline.days} hari
            sebelumnya
          </span>
        ) : (
          <span className="text-amber-700 dark:text-amber-500">
            Rata-rata {context.baseline.days} hari sebelumnya tidak bisa dihitung (hanya{" "}
            {context.baseline.n_obs} hari ada data, minimal {context.baseline.min_obs}). Nilai
            wajar/tidaknya harus dinilai dari bentuk grafik saja.
          </span>
        )}
        <span>
          <span className="mr-1 inline-block h-2 w-2 rounded-full border border-neutral-500 align-middle" />
          titik kosong = harga hasil interpolasi
        </span>
      </figcaption>
    </figure>
  );
}
