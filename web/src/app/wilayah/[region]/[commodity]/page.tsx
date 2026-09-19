/**
 * One commodity in one region.
 *
 * Order follows what the reader needs: what is happening now, then the picture
 * it came from, then the longer-run context (seasonal weeks, regime zone), then
 * where the numbers came from. Provenance last but always present — the claim
 * that any figure walks back to a URL is only real if the reader can see it.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { db, fetchCommodity, fetchLastUpdated, fetchRegions } from "@/lib/dashboard";
import {
  formatLongDate,
  formatPercent,
  formatPercentMagnitude,
  formatRupiah,
  formatShortDate,
  formatShortDateWithYear,
  formatWeekRange,
} from "@/lib/format";
import {
  COPY,
  LEVEL_LABEL,
  LEVEL_MARK,
  LEVEL_MEANING,
  REASON_COPY,
  ZONE_COPY,
  alertHeadline,
  recommendation,
} from "@/content/id";
import PriceChart from "@/components/PriceChart";
import PageFooter from "@/components/PageFooter";
import SiteHeader from "@/components/SiteHeader";
import CommodityIcon from "@/components/CommodityIcon";
import { INTERACTION, MUTED, PANEL, PAGE, SECTION_LABEL } from "@/lib/ui";

/**
 * How this region's price compares with another's.
 *
 * Below two percent the answer is "the same": the two figures come from
 * different portals with different collection methods, and presenting a 1%
 * gap as a reason to buy elsewhere would be reading noise as signal.
 */
function comparison(peerPrice: number, here: number): string {
  const diff = peerPrice / here - 1;
  if (Math.abs(diff) < 0.02) return COPY.peerSame;
  const magnitude = formatPercentMagnitude(diff);
  return diff < 0 ? COPY.peerCheaper(magnitude) : COPY.peerPricier(magnitude);
}

export const revalidate = 1800;

/**
 * The commodity set is fixed and known, so every page is prerendered: 4 regions
 * x 12 commodities. That makes the common case instant instead of six sequential
 * database round-trips, and it removes the need for a loading skeleton.
 *
 * `dynamicParams = false` is the reason a mistyped slug now returns a real 404.
 * Rendering unknown params on demand meant streaming began — headers went out
 * with 200 — before `notFound()` was ever reached, so a page that does not exist
 * answered "200 OK".
 */
export const dynamicParams = false;

export async function generateStaticParams() {
  const [regions, { data }] = await Promise.all([
    fetchRegions(),
    db.from("commodities").select("slug").order("sort_order"),
  ]);
  const commodities = (data ?? []) as { slug: string }[];
  return regions.flatMap((r) =>
    commodities.map((c) => ({ region: r.slug, commodity: c.slug })),
  );
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ region: string; commodity: string }>;
}): Promise<Metadata> {
  const { region, commodity } = await params;
  const detail = await fetchCommodity(commodity, region);
  if (!detail) return { title: "Tidak ditemukan — SIAP-PANGAN" };
  return {
    title: `${detail.name} di ${detail.regionName} — SIAP-PANGAN`,
    description: `Pergerakan harga ${detail.name} di ${detail.regionName} dari portal resmi. Deskriptif, bukan ramalan harga.`,
  };
}

export default async function CommodityPage({
  params,
}: {
  params: Promise<{ region: string; commodity: string }>;
}) {
  const { region, commodity } = await params;
  const [detail, lastUpdated] = await Promise.all([
    fetchCommodity(commodity, region),
    fetchLastUpdated(),
  ]);
  if (!detail) notFound();

  const alert = detail.alert;
  const focus = detail.series.findLast((p) => p.price !== null) ?? null;
  const deviation =
    detail.baselineMean && focus?.price != null ? focus.price / detail.baselineMean - 1 : null;
  const advice = alert ? recommendation(alert.recommendationId, alert.pctChange7d) : null;
  const zone = detail.zone ? ZONE_COPY[detail.zone] : null;
  const hasImputed = detail.series.some((p) => p.imputed);

  // Widened only to `2xl`: this page is one narrative column (price, chart,
  // seasonality, regime, sources) and prose stops being readable long before
  // 1000px. The chart is a viewBox SVG at w-full, so it takes the extra width as
  // detail rather than as stretch.
  return (
    <>
      <SiteHeader cta={false} />
      <main className={PAGE.reading}>
      <header>
        <Link
          href={`/wilayah/${region}`}
          className={`text-sm font-medium ${MUTED} hover:text-brand`}
        >
          &larr; {detail.regionName}
        </Link>
        <h1 className="mt-3 flex items-center gap-2.5 text-2xl font-extrabold tracking-tight sm:text-3xl">
          <CommodityIcon slug={detail.slug} className="h-7 w-7 shrink-0 text-brand" />
          {detail.name}
        </h1>
        {detail.obsDate && (
          <p className={`mt-1 text-sm ${MUTED}`}>
            {COPY.dataFrom}: {formatLongDate(detail.obsDate)}
          </p>
        )}
      </header>

      <section className={`${PANEL} p-4`}>
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-3xl font-semibold tabular-nums">
            {formatRupiah(focus?.price ?? null)}
            <span className={`ml-1 text-sm font-normal ${MUTED}`}>/{detail.unit}</span>
          </p>
          {deviation !== null && (
            <p className={`text-right text-sm tabular-nums ${MUTED}`}>
              {formatPercent(deviation)}
              <span className={`block text-xs ${MUTED}`}>{COPY.vsBaseline}</span>
            </p>
          )}
        </div>

        {alert && (
          <>
            <p className="mt-3 text-sm font-medium">
              {alertHeadline(alert.level, alert.pctChange7d)}
            </p>
            <p className={`mt-1 flex flex-wrap items-center gap-x-3 text-xs ${MUTED}`}>
              <span>
                <span aria-hidden className="mr-1">
                  {LEVEL_MARK[alert.level]}
                </span>
                {LEVEL_LABEL[alert.level]}
              </span>
              <span>{COPY.sourceCount(alert.nSources)}</span>
            </p>
            <p className={`mt-2 text-sm ${MUTED}`}>
              {LEVEL_MEANING[alert.level]}
            </p>
            {alert.reason && REASON_COPY[alert.reason] && (
              <p className={`mt-2 text-xs ${MUTED}`}>{REASON_COPY[alert.reason]}</p>
            )}
            {advice && (
              <p className="mt-3 rounded-xl border border-brand-soft-border bg-brand-soft px-3.5 py-2.5 text-sm">
                {advice}
              </p>
            )}
          </>
        )}
      </section>

      <section>
        <PriceChart series={detail.series} baselineMean={detail.baselineMean} />
        <p className={`mt-2 text-xs ${MUTED}`}>{COPY.chartCaption}</p>
        {hasImputed && <p className={`mt-1 text-xs ${MUTED}`}>{COPY.imputedNote}</p>}
      </section>

      <section>
        <h2 className={SECTION_LABEL}>{COPY.riskyWeeks}</h2>
        {detail.riskyWeeks.length ? (
          <>
            <ul className="mt-2 flex flex-wrap gap-2">
              {detail.riskyWeeks.map((w) => (
                <li
                  key={w.week}
                  className="rounded-lg border border-edge bg-surface px-2.5 py-1 text-xs font-medium tabular-nums"
                >
                  {formatWeekRange(w.startsOn)}
                </li>
              ))}
            </ul>
            <p className={`mt-2 text-xs leading-relaxed ${MUTED}`}>
              {COPY.riskyWeeksHelp}
            </p>
          </>
        ) : (
          <p className={`mt-1 text-sm ${MUTED}`}>{COPY.noRiskyWeeks}</p>
        )}
      </section>

      {zone && (
        <section>
          <h2 className={SECTION_LABEL}>{COPY.zoneTitle}</h2>
          <p className="mt-1 text-sm">{zone.label}</p>
          <p className={`mt-1 text-xs leading-relaxed ${MUTED}`}>{zone.meaning}</p>
        </section>
      )}

      {detail.peers.length > 0 && (
        <section>
          <h2 className={SECTION_LABEL}>{COPY.peersTitle}</h2>
          <ul className="mt-2 flex flex-col gap-2">
            {detail.peers.map((peer) => (
              <li key={peer.regionSlug}>
                {/* A link, not a row of text: having learned cabai is cheaper in
                    Jawa Timur, the next thing the reader wants is that region's
                    page for it. */}
                <Link
                  href={`/wilayah/${peer.regionSlug}/${detail.slug}`}
                  className={`flex items-center justify-between gap-3 ${PANEL} px-3 py-2 hover:border-neutral-400 dark:hover:border-neutral-600 ${INTERACTION}`}
                >
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{peer.regionName}</span>
                    {/* Only when it differs from the date this page is showing.
                        Printing the same date on every row would be noise;
                        printing none would hide a real mismatch. */}
                    {peer.obsDate !== detail.obsDate && (
                      <span className={`block text-xs tabular-nums ${MUTED}`}>
                        {formatShortDate(peer.obsDate)}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="block text-sm font-semibold tabular-nums">
                      {formatRupiah(peer.price)}
                      <span className={`ml-1 text-xs font-normal ${MUTED}`}>/{detail.unit}</span>
                    </span>
                    {focus?.price != null && (
                      <span className={`block text-xs ${MUTED}`}>
                        {comparison(peer.price, focus.price)}
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <p className={`mt-2 text-xs leading-relaxed ${MUTED}`}>{COPY.peersHelp}</p>
        </section>
      )}

      <section>
        <h2 className={SECTION_LABEL}>{COPY.sourcesTitle}</h2>
        <p className={`mt-1 text-xs leading-relaxed ${MUTED}`}>{COPY.sourcesHelp}</p>
        <ul className="mt-2 flex flex-col gap-2">
          {detail.sources.map((s) => (
            <li
              key={s.source_slug}
              className={`${PANEL} px-3.5 py-2.5 text-xs`}
            >
              <a
                href={s.base_url}
                target="_blank"
                rel="noreferrer noopener"
                className="font-medium underline underline-offset-2"
              >
                {s.source_name}
              </a>
              <p className={`mt-0.5 tabular-nums ${MUTED}`}>
                {s.observations.toLocaleString("id-ID")} pencatatan &middot;{" "}
                {formatShortDateWithYear(s.first_date)} &ndash;{" "}
                {formatShortDateWithYear(s.last_date)}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <PageFooter lastUpdated={lastUpdated} />
      </main>
    </>
  );
}
