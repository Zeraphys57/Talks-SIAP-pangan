/**
 * Read layer for the public dashboard.
 *
 * Every query here runs under the anon key and is constrained by the RLS
 * policies in `supabase/migrations/0006_rls.sql`. The tables reachable from
 * this file are exactly the presentation tables; anything else returns nothing
 * rather than erroring, which is why `siap doctor` proves the posture with a
 * real anon HTTP request instead of trusting it.
 *
 * ### The freshness rule lives here, once
 *
 * Siskaperbapo publishes round placeholder figures on the current date and
 * replaces them with computed averages the next day — measured at 83.3% round
 * prices on the current date against a 0.4% baseline (see `docs/design.md`).
 * Those placeholders flagged 12 of 12 East Java commodities.
 *
 * So the dashboard reads the latest **settled** day: the most recent date
 * strictly before today in WIB. It is resolved per region, because the regions
 * do not share a latest date — a global `max(obs_date)` returns only East Java
 * and would leave a Yogyakarta user staring at an empty page.
 */

import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  throw new Error(
    "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY are required. " +
      "Copy web/.env.example to web/.env.local and fill both in.",
  );
}

/** Separate from the /lab client: no session, so pages can render on the server. */
export const db = createClient(url, anonKey, {
  auth: { persistSession: false, autoRefreshToken: false },
});

export type Level = "merah" | "kuning" | "hijau";

export type Region = {
  id: number;
  slug: string;
  display_name: string;
  level: string;
};

export type AlertRow = {
  commodity_slug: string;
  commodity_name: string;
  canonical_unit: string;
  level: Level;
  fusion_score: number;
  obs_date: string;
  price: number | null;
  pctChange7d: number | null;
  nSources: number;
  reason: string | null;
  recommendationId: string | null;
};

/** Today in Asia/Jakarta, as YYYY-MM-DD.
 *
 * Computed from the WIB wall clock rather than the server's, so a build running
 * in UTC does not decide that "today" is yesterday and show a day-old board as
 * provisional — or worse, admit today's placeholders. */
export function todayWIB(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export async function fetchRegions(): Promise<Region[]> {
  const { data, error } = await db
    .from("regions")
    .select("id, slug, display_name, level")
    .neq("slug", "nasional")
    .order("slug");
  if (error) throw new Error(error.message);
  return (data ?? []) as Region[];
}

async function latestFusionRun(): Promise<number | null> {
  const { data, error } = await db
    .from("analysis_runs")
    .select("id")
    .eq("run_type", "fusion")
    .eq("status", "success")
    .order("id", { ascending: false })
    .limit(1);
  if (error) throw new Error(error.message);
  return data?.length ? (data[0].id as number) : null;
}

/**
 * When the pipeline last finished successfully, as an ISO timestamp.
 *
 * The observation date already on every board answers "which day are these
 * prices from". This answers "is this thing still running", which the reader
 * otherwise cannot distinguish from a settled-day lag. Null if no fusion run has
 * ever succeeded, in which case the caller should say nothing rather than guess.
 */
export async function fetchLastUpdated(): Promise<string | null> {
  const { data, error } = await db
    .from("analysis_runs")
    .select("finished_at")
    .eq("run_type", "fusion")
    .eq("status", "success")
    .not("finished_at", "is", null)
    .order("finished_at", { ascending: false })
    .limit(1);
  if (error) throw new Error(error.message);
  return data?.length ? (data[0].finished_at as string) : null;
}

export type SourcePortal = {
  slug: string;
  display_name: string;
  owner: string | null;
  base_url: string | null;
  scope: string | null;
  cadence: string | null;
  is_active: boolean;
  notes: string | null;
};

/**
 * Every portal this project draws from, active or not.
 *
 * Inactive ones are included on purpose. `panelharga` is disabled because its
 * endpoints fail upstream, and a reader comparing this list against the proposal
 * is entitled to see that it was attempted rather than quietly dropped.
 */
export async function fetchPortals(): Promise<SourcePortal[]> {
  const { data, error } = await db
    .from("sources")
    .select("slug, display_name, owner, base_url, scope, cadence, is_active, notes")
    .order("is_active", { ascending: false })
    .order("slug");
  if (error) throw new Error(error.message);
  return (data ?? []) as SourcePortal[];
}

/**
 * The most recent settled date for one region, or null if it has none.
 *
 * "Settled" means strictly before today in WIB. See the module comment: today's
 * figures are still being published and are not what anyone should act on.
 */
export async function latestSettledDate(
  runId: number,
  regionId: number,
  today: string = todayWIB(),
): Promise<string | null> {
  const { data, error } = await db
    .from("alerts")
    .select("obs_date")
    .eq("run_id", runId)
    .eq("region_id", regionId)
    .lt("obs_date", today)
    .order("obs_date", { ascending: false })
    .limit(1);
  if (error) throw new Error(error.message);
  return data?.length ? (data[0].obs_date as string) : null;
}

export type Board = {
  regionSlug: string;
  regionName: string;
  obsDate: string | null;
  alerts: AlertRow[];
  /** True when data exists for today but is being withheld as unsettled. */
  todayWithheld: boolean;
};

type AlertJoin = {
  obs_date: string;
  level: Level;
  fusion_score: number;
  components: Record<string, unknown> | null;
  recommendation_id: string | null;
  commodities: { slug: string; display_name: string; canonical_unit: string } | null;
};

export async function fetchBoard(regionSlug: string): Promise<Board | null> {
  const regions = await fetchRegions();
  const region = regions.find((r) => r.slug === regionSlug);
  if (!region) return null;

  const runId = await latestFusionRun();
  if (runId === null) {
    return {
      regionSlug,
      regionName: region.display_name,
      obsDate: null,
      alerts: [],
      todayWithheld: false,
    };
  }

  const today = todayWIB();
  const obsDate = await latestSettledDate(runId, region.id, today);
  if (!obsDate) {
    return {
      regionSlug,
      regionName: region.display_name,
      obsDate: null,
      alerts: [],
      todayWithheld: false,
    };
  }

  const [{ data, error }, unsettled] = await Promise.all([
    db
      .from("alerts")
      .select(
        "obs_date, level, fusion_score, components, recommendation_id, " +
          "commodities(slug, display_name, canonical_unit)",
      )
      .eq("run_id", runId)
      .eq("region_id", region.id)
      .eq("obs_date", obsDate)
      .order("fusion_score", { ascending: false }),
    db
      .from("alerts")
      .select("obs_date")
      .eq("run_id", runId)
      .eq("region_id", region.id)
      .gte("obs_date", today)
      .limit(1),
  ]);
  if (error) throw new Error(error.message);

  const rows = (data ?? []) as unknown as AlertJoin[];
  const prices = await fetchPricesOn(region.id, obsDate);

  return {
    regionSlug,
    regionName: region.display_name,
    obsDate,
    todayWithheld: (unsettled.data?.length ?? 0) > 0,
    alerts: rows
      .filter((r) => r.commodities)
      .map((r) => {
        const c = r.components ?? {};
        const slug = r.commodities!.slug;
        return {
          commodity_slug: slug,
          commodity_name: r.commodities!.display_name,
          canonical_unit: r.commodities!.canonical_unit,
          level: r.level,
          fusion_score: Number(r.fusion_score),
          obs_date: r.obs_date,
          price: prices.get(slug) ?? null,
          pctChange7d: numberOrNull(c["pct_change_7d"]),
          nSources: Number(c["n_sources_reporting"] ?? 0),
          reason: (c["reason"] as string | undefined) ?? null,
          recommendationId: r.recommendation_id,
        };
      }),
  };
}

function numberOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

async function fetchPricesOn(regionId: number, obsDate: string): Promise<Map<string, number>> {
  const { data, error } = await db
    .from("price_daily_unified")
    .select("price_median, commodities(slug)")
    .eq("region_id", regionId)
    .eq("obs_date", obsDate);
  if (error) throw new Error(error.message);

  const out = new Map<string, number>();
  for (const row of (data ?? []) as unknown as {
    price_median: number | null;
    commodities: { slug: string } | null;
  }[]) {
    if (row.commodities && row.price_median !== null) {
      out.set(row.commodities.slug, Number(row.price_median));
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Commodity detail
// ---------------------------------------------------------------------------
export type SourceCredit = {
  source_slug: string;
  source_name: string;
  base_url: string;
  observations: number;
  first_date: string;
  last_date: string;
};

export type SeriesPoint = {
  date: string;
  price: number | null;
  imputed: boolean;
  sources: number;
};

export type CommodityDetail = {
  slug: string;
  name: string;
  unit: string;
  regionSlug: string;
  regionName: string;
  obsDate: string | null;
  series: SeriesPoint[];
  baselineMean: number | null;
  alert: AlertRow | null;
  zone: string | null;
  riskyWeeks: { week: number; startsOn: string }[];
  sources: SourceCredit[];
};

const DETAIL_WINDOW_DAYS = 120;
const BASELINE_DAYS = 30;

/** The +/-10% band the annotators judged against, so the paper and the product
 * show the same picture rather than two different ones. */
export const DEFINITION_PCT = 0.1;

export async function fetchCommodity(
  commoditySlug: string,
  regionSlug: string,
): Promise<CommodityDetail | null> {
  const [{ data: commodityRows }, regions] = await Promise.all([
    db
      .from("commodities")
      .select("id, slug, display_name, canonical_unit")
      .eq("slug", commoditySlug)
      .limit(1),
    fetchRegions(),
  ]);
  const commodity = commodityRows?.[0];
  const region = regions.find((r) => r.slug === regionSlug);
  if (!commodity || !region) return null;

  const board = await fetchBoard(regionSlug);
  const obsDate = board?.obsDate ?? null;

  const series = obsDate ? await fetchSeries(commodity.id as number, region.id, obsDate) : [];
  const observed = series.filter((p) => p.price !== null && !p.imputed);
  const baselineWindow = observed.slice(-BASELINE_DAYS);
  const baselineMean = baselineWindow.length
    ? baselineWindow.reduce((sum, p) => sum + (p.price as number), 0) / baselineWindow.length
    : null;

  const [zone, riskyWeeks, sources] = await Promise.all([
    fetchZone(commodity.id as number, region.id),
    fetchRiskyWeeks(commodity.id as number, region.id),
    fetchSources(commodity.id as number, region.id),
  ]);

  return {
    slug: commodity.slug as string,
    name: commodity.display_name as string,
    unit: commodity.canonical_unit as string,
    regionSlug,
    regionName: region.display_name,
    obsDate,
    series,
    baselineMean,
    alert: board?.alerts.find((a) => a.commodity_slug === commoditySlug) ?? null,
    zone,
    riskyWeeks,
    sources,
  };
}

async function fetchSeries(
  commodityId: number,
  regionId: number,
  obsDate: string,
): Promise<SeriesPoint[]> {
  const start = new Date(obsDate);
  start.setDate(start.getDate() - DETAIL_WINDOW_DAYS);
  const startIso = start.toISOString().slice(0, 10);

  const { data, error } = await db
    .from("price_daily_unified")
    .select("obs_date, price_median, is_imputed, n_sources")
    .eq("commodity_id", commodityId)
    .eq("region_id", regionId)
    .gte("obs_date", startIso)
    .lte("obs_date", obsDate)
    .order("obs_date");
  if (error) throw new Error(error.message);

  return ((data ?? []) as unknown as {
    obs_date: string;
    price_median: number | null;
    is_imputed: boolean;
    n_sources: number;
  }[]).map((r) => ({
    date: r.obs_date,
    price: r.price_median === null ? null : Number(r.price_median),
    imputed: Boolean(r.is_imputed),
    sources: Number(r.n_sources),
  }));
}

async function fetchZone(commodityId: number, regionId: number): Promise<string | null> {
  const { data } = await db
    .from("cluster_assignments")
    .select("zone, period_month")
    .eq("commodity_id", commodityId)
    .eq("region_id", regionId)
    .order("period_month", { ascending: false })
    .limit(1);
  return data?.length ? (data[0].zone as string) : null;
}

/** Top-decile seasonal weeks — "periode rawan naik".
 *
 * This is a statement about which weeks of the year have historically run above
 * this commodity's own trend. It is emphatically not a forecast, and the copy
 * that renders it says so. */
async function fetchRiskyWeeks(
  commodityId: number,
  regionId: number,
): Promise<{ week: number; startsOn: string }[]> {
  const { data } = await db
    .from("seasonal_components")
    .select("period_start, seasonal")
    .eq("commodity_id", commodityId)
    .eq("region_id", regionId)
    .not("seasonal", "is", null);
  if (!data?.length) return [];

  const rows = data as unknown as { period_start: string; seasonal: number }[];
  const byWeek = new Map<number, number[]>();
  for (const row of rows) {
    const week = isoWeek(row.period_start);
    if (!byWeek.has(week)) byWeek.set(week, []);
    byWeek.get(week)!.push(Number(row.seasonal));
  }

  const means = [...byWeek.entries()].map(([week, values]) => ({
    week,
    mean: values.reduce((a, b) => a + b, 0) / values.length,
    startsOn: rows.find((r) => isoWeek(r.period_start) === week)!.period_start,
  }));
  means.sort((a, b) => b.mean - a.mean);

  const cutoff = Math.max(1, Math.ceil(means.length * 0.1));
  return means
    .slice(0, cutoff)
    .filter((m) => m.mean > 0)
    .sort((a, b) => a.week - b.week)
    .map(({ week, startsOn }) => ({ week, startsOn }));
}

function isoWeek(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  return Math.ceil(((date.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7);
}

/**
 * The portals that actually produced this series.
 *
 * Reads `series_sources` (migration 0010), not `source_regions`. Configured
 * coverage is not provenance: it listed `panelharga`, whose portal is broken
 * upstream and has contributed nothing, and `trends`, which is a demand signal
 * and never writes a price. Naming either as the source of a displayed rupiah
 * figure would be false.
 */
async function fetchSources(
  commodityId: number,
  regionId: number,
): Promise<SourceCredit[]> {
  const { data, error } = await db
    .from("series_sources")
    .select("source_slug, source_name, base_url, observations, first_date, last_date")
    .eq("commodity_id", commodityId)
    .eq("region_id", regionId)
    .order("observations", { ascending: false });
  if (error) throw new Error(error.message);

  return ((data ?? []) as unknown as SourceCredit[]).map((r) => ({
    source_slug: r.source_slug,
    source_name: r.source_name,
    base_url: r.base_url,
    observations: Number(r.observations),
    first_date: r.first_date,
    last_date: r.last_date,
  }));
}
