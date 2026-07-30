/**
 * Permanent regression tests for the chart's segment builder.
 *
 * The orphan-point case exists here as a synthetic fixture because it cannot be
 * reproduced from production data: a priced day whose neighbouring rows exist but
 * hold NULL price occurs **zero times** across all 50,040 rows of
 * price_daily_unified. Interior NULLs live only in `nasional` (580) and
 * `di_yogyakarta` (48), and `nasional` is never rendered.
 *
 * So the bug was unreachable through the UI and would have stayed that way until
 * a source changed its reporting pattern. That is exactly the kind of defect that
 * needs a test rather than a screenshot.
 *
 * Run: `pnpm test` (node --test --experimental-strip-types, no test framework).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { buildSegments, r1, type SeriesLike } from "./chartSegments.ts";

/** Identity-ish scales, so assertions read in data units rather than pixels. */
const sx = (iso: string) => Number(iso.slice(-2));
const sy = (v: number) => v;

const p = (date: string, price: number | null, imputed = false): SeriesLike => ({
  date,
  price,
  imputed,
});

test("an isolated priced day between two gaps is drawn as a dot, not dropped", () => {
  // The reported failure: passes a `priced.length < 2` guard, then renders empty.
  const series = [
    p("2026-07-01", 100),
    p("2026-07-02", null),
    p("2026-07-03", 200),
    p("2026-07-04", null),
    p("2026-07-05", 300),
  ];
  const { strokes, dots } = buildSegments(series, sx, sy);

  assert.equal(strokes.length, 0, "no run reaches two points, so there is nothing to stroke");
  assert.equal(dots.length, 3, "all three priced days must still appear");
  assert.deepEqual(
    dots.map((d) => d.y),
    [100, 200, 300],
  );
});

test("a single priced day at the very start or end is not dropped", () => {
  const { strokes, dots } = buildSegments(
    [p("2026-07-01", 100), p("2026-07-02", null), p("2026-07-03", 200), p("2026-07-04", 210)],
    sx,
    sy,
  );
  assert.equal(dots.length, 1, "the leading singleton becomes a dot");
  assert.equal(dots[0].y, 100);
  assert.equal(strokes.length, 1, "the trailing pair becomes one stroke");
});

test("gaps break the line instead of bridging them", () => {
  const { strokes } = buildSegments(
    [
      p("2026-07-01", 100),
      p("2026-07-02", 110),
      p("2026-07-03", null),
      p("2026-07-04", 200),
      p("2026-07-05", 210),
    ],
    sx,
    sy,
  );
  assert.equal(strokes.length, 2, "two runs, never joined across the null");
  assert.ok(!strokes[0].d.includes("200"), "the first stroke must not reach across the gap");
});

test("an imputed run is split out so it can be dashed, and stays continuous", () => {
  const { strokes } = buildSegments(
    [
      p("2026-07-01", 100),
      p("2026-07-02", 110),
      p("2026-07-03", 120, true),
      p("2026-07-04", 130, true),
      p("2026-07-05", 140),
    ],
    sx,
    sy,
  );

  assert.deepEqual(
    strokes.map((s) => s.imputed),
    [false, true, false],
    "observed, imputed, observed",
  );

  // The transition segment belongs to the DASHED stroke, deliberately: the line
  // from the last recorded day to the first interpolated one is itself
  // interpolated movement, so drawing it solid would overstate what was measured.
  assert.equal(strokes[0].d, "M1,100 L2,110", "observed piece ends on the last recorded day");
  assert.equal(strokes[1].d, "M2,110 L3,120 L4,130", "dashed piece carries the transition");
  assert.equal(strokes[2].d, "M4,130 L5,140", "and resumes solid from the last imputed day");

  // Continuity: each stroke starts where the previous one ended, so a style
  // change never leaves a visual break.
  assert.ok(strokes[1].d.startsWith("M2,110"), "no gap between stroke 0 and 1");
  assert.ok(strokes[2].d.startsWith("M4,130"), "no gap between stroke 1 and 2");
});

test("a lone imputed day between gaps is a dot flagged imputed", () => {
  const { dots } = buildSegments(
    [p("2026-07-01", null), p("2026-07-02", 150, true), p("2026-07-03", null)],
    sx,
    sy,
  );
  assert.equal(dots.length, 1);
  assert.equal(dots[0].imputed, true, "styling depends on this, so it must survive");
});

test("an all-null series produces nothing rather than throwing", () => {
  const { strokes, dots } = buildSegments(
    [p("2026-07-01", null), p("2026-07-02", null)],
    sx,
    sy,
  );
  assert.equal(strokes.length, 0);
  assert.equal(dots.length, 0);
});

test("coordinates are rounded to one decimal", () => {
  assert.equal(r1(123.456), 123.5);
  assert.equal(r1(0.04), 0);
  const { strokes } = buildSegments(
    [p("2026-07-01", 1 / 3), p("2026-07-02", 2 / 3)],
    sx,
    sy,
  );
  assert.equal(strokes[0].d, "M1,0.3 L2,0.7", "no full-float coordinates in the path");
});
