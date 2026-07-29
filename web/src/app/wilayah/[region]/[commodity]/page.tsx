/**
 * One commodity in one region.
 *
 * Order follows what the reader needs: what is happening now, then the picture
 * it came from, then the longer-run context (seasonal weeks, regime zone), then
 * where the numbers came from. Provenance last but always present — the claim
 * that any figure walks back to a URL is only real if the reader can see it.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchCommodity } from "@/lib/dashboard";
import { formatLongDate, formatPercent, formatRupiah, formatShortDateWithYear } from "@/lib/format";
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

export const revalidate = 1800;

export default async function CommodityPage({
  params,
}: {
  params: Promise<{ region: string; commodity: string }>;
}) {
  const { region, commodity } = await params;
  const detail = await fetchCommodity(commodity, region);
  if (!detail) notFound();

  const alert = detail.alert;
  const focus = detail.series.findLast((p) => p.price !== null) ?? null;
  const deviation =
    detail.baselineMean && focus?.price != null ? focus.price / detail.baselineMean - 1 : null;
  const advice = alert ? recommendation(alert.recommendationId, alert.pctChange7d) : null;
  const zone = detail.zone ? ZONE_COPY[detail.zone] : null;
  const hasImputed = detail.series.some((p) => p.imputed);

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col gap-6 px-5 py-8">
      <header>
        <Link
          href={`/wilayah/${region}`}
          className="text-sm text-neutral-500 underline underline-offset-2"
        >
          &larr; {detail.regionName}
        </Link>
        <h1 className="mt-3 text-xl font-semibold tracking-tight">{detail.name}</h1>
        {detail.obsDate && (
          <p className="mt-1 text-sm text-neutral-500">
            {COPY.dataFrom}: {formatLongDate(detail.obsDate)}
          </p>
        )}
      </header>

      <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-2xl font-semibold tabular-nums">
            {formatRupiah(focus?.price ?? null)}
            <span className="ml-1 text-sm font-normal text-neutral-500">/{detail.unit}</span>
          </p>
          {deviation !== null && (
            <p className="text-right text-sm tabular-nums text-neutral-600 dark:text-neutral-400">
              {formatPercent(deviation)}
              <span className="block text-xs text-neutral-500">{COPY.vsBaseline}</span>
            </p>
          )}
        </div>

        {alert && (
          <>
            <p className="mt-3 text-sm font-medium">
              {alertHeadline(alert.level, alert.pctChange7d)}
            </p>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-neutral-500">
              <span>
                <span aria-hidden className="mr-1">
                  {LEVEL_MARK[alert.level]}
                </span>
                {LEVEL_LABEL[alert.level]}
              </span>
              <span>{COPY.sourceCount(alert.nSources)}</span>
            </p>
            <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
              {LEVEL_MEANING[alert.level]}
            </p>
            {alert.reason && REASON_COPY[alert.reason] && (
              <p className="mt-2 text-xs text-neutral-500">{REASON_COPY[alert.reason]}</p>
            )}
            {advice && (
              <p className="mt-3 rounded-md bg-neutral-100 px-3 py-2 text-sm dark:bg-neutral-900">
                {advice}
              </p>
            )}
          </>
        )}
      </section>

      <section>
        <PriceChart series={detail.series} baselineMean={detail.baselineMean} />
        <p className="mt-2 text-xs text-neutral-500">{COPY.chartCaption}</p>
        {hasImputed && <p className="mt-1 text-xs text-neutral-500">{COPY.imputedNote}</p>}
      </section>

      <section>
        <h2 className="text-sm font-medium">{COPY.riskyWeeks}</h2>
        {detail.riskyWeeks.length ? (
          <>
            <ul className="mt-2 flex flex-wrap gap-2">
              {detail.riskyWeeks.map((w) => (
                <li
                  key={w.week}
                  className="rounded-md border border-neutral-200 px-2 py-1 text-xs tabular-nums dark:border-neutral-800"
                >
                  Minggu {w.week}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs leading-relaxed text-neutral-500">
              {COPY.riskyWeeksHelp}
            </p>
          </>
        ) : (
          <p className="mt-1 text-sm text-neutral-500">{COPY.noRiskyWeeks}</p>
        )}
      </section>

      {zone && (
        <section>
          <h2 className="text-sm font-medium">{COPY.zoneTitle}</h2>
          <p className="mt-1 text-sm">{zone.label}</p>
          <p className="mt-1 text-xs leading-relaxed text-neutral-500">{zone.meaning}</p>
        </section>
      )}

      <section>
        <h2 className="text-sm font-medium">{COPY.sourcesTitle}</h2>
        <p className="mt-1 text-xs leading-relaxed text-neutral-500">{COPY.sourcesHelp}</p>
        <ul className="mt-2 flex flex-col gap-2">
          {detail.sources.map((s) => (
            <li
              key={s.source_slug}
              className="rounded-md border border-neutral-200 px-3 py-2 text-xs dark:border-neutral-800"
            >
              <a
                href={s.base_url}
                target="_blank"
                rel="noreferrer noopener"
                className="font-medium underline underline-offset-2"
              >
                {s.source_name}
              </a>
              <p className="mt-0.5 tabular-nums text-neutral-500">
                {s.observations.toLocaleString("id-ID")} pencatatan &middot;{" "}
                {formatShortDateWithYear(s.first_date)} &ndash;{" "}
                {formatShortDateWithYear(s.last_date)}
              </p>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-xs leading-relaxed text-neutral-500">{COPY.notForecast}</p>
      <p className="mt-auto text-xs text-neutral-500">{COPY.footer}</p>
    </main>
  );
}
