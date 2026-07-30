/**
 * Turning a price series into drawable SVG pieces.
 *
 * Extracted from PriceChart for one reason: the orphan-point bug below cannot be
 * reproduced from production data, so it needs a synthetic fixture and a test, and
 * a component full of JSX is not testable without adding a test framework and a
 * JSX transform. This module is plain TypeScript, so `node --test
 * --experimental-strip-types` covers it with no new dependency.
 *
 * See `chartSegments.test.ts`, which is a permanent regression test rather than a
 * one-off check.
 */

export type SeriesLike = {
  date: string;
  price: number | null;
  imputed: boolean;
};

export type Stroke = { d: string; imputed: boolean };
export type Dot = { x: number; y: number; imputed: boolean };

/** One decimal is ~0.07px at render width — invisible, and less than half the
 *  path bytes of full float precision. Over three years of daily data that is the
 *  difference between ~26KB and ~11KB of path string, which is the whole reason
 *  this chart is hand-rolled instead of using a library. */
export const r1 = (n: number) => Math.round(n * 10) / 10;

/**
 * Split a series into strokes and isolated dots.
 *
 * Three behaviours, each deliberate:
 *
 * 1. **Gaps break the line.** A straight segment drawn over a fortnight of no
 *    data looks like data. A `price: null` entry ends the current run.
 * 2. **Imputed runs are separated** so they can be drawn dashed. The previous
 *    marker — a 2.5px circle with a 1px stroke on a 1.75px line — was invisible
 *    on screen and gone entirely on a grayscale print of a paper figure.
 * 3. **Isolated priced days become dots.** A day with gaps on both sides used to
 *    render as nothing at all: the run never reached two points, so no path was
 *    emitted and the day silently vanished. `[p, null, p, null, p]` passed the
 *    caller's `priced.length < 2` guard and then drew an empty chart.
 *
 * The boundary point between an observed run and an imputed run appears in both
 * strokes, so the line stays continuous across the style change.
 */
export function buildSegments(
  series: SeriesLike[],
  sx: (iso: string) => number,
  sy: (v: number) => number,
): { strokes: Stroke[]; dots: Dot[] } {
  const strokes: Stroke[] = [];
  const dots: Dot[] = [];

  let run: SeriesLike[] = [];

  const flush = () => {
    if (run.length === 1) {
      const p = run[0];
      dots.push({ x: r1(sx(p.date)), y: r1(sy(p.price as number)), imputed: p.imputed });
    } else if (run.length > 1) {
      let piece: SeriesLike[] = [run[0]];
      for (let i = 1; i < run.length; i++) {
        piece.push(run[i]);
        const next = run[i + 1];
        if (!next || next.imputed !== run[i].imputed) {
          strokes.push({
            d: piece
              .map((p, j) => `${j ? "L" : "M"}${r1(sx(p.date))},${r1(sy(p.price as number))}`)
              .join(" "),
            imputed: run[i].imputed,
          });
          piece = [run[i]];
        }
      }
    }
    run = [];
  };

  for (const p of series) {
    if (p.price === null) flush();
    else run.push(p);
  }
  flush();

  return { strokes, dots };
}
