/**
 * Landing page.
 *
 * What it is allowed to claim is the whole design of this file. There are no
 * testimonials, no user counts, no "dipercaya oleh" row of logos, because this
 * project has none of those and a page whose subject is data integrity cannot
 * open by inventing some. What it has instead is real: four named government
 * portals, coverage counted from the database at build time, and the current
 * state of every region shown live rather than mocked up.
 *
 * The scope boundary — descriptive, never a forecast — sits directly under the
 * hero buttons rather than in the footer. It is the boundary the entire system
 * is built inside, and burying it is where overselling would start.
 */

import Link from "next/link";

import { fetchLastUpdated, fetchRegionSummaries, fetchStats } from "@/lib/dashboard";
import { COPY, LEVEL_MARK } from "@/content/id";
import { formatLongDate } from "@/lib/format";
import PageFooter from "@/components/PageFooter";
import SiteHeader from "@/components/SiteHeader";
import CommodityIcon from "@/components/CommodityIcon";
import {
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  CONTAINER,
  DISPLAY_TITLE,
  INTERACTION,
  MUTED,
  PANEL,
  SECTION_LABEL,
  SUBTLE,
} from "@/lib/ui";

export const revalidate = 1800;

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-2xl font-extrabold tracking-tight tabular-nums sm:text-3xl">
        {value}
      </span>
      <span className={`mt-0.5 text-xs font-medium ${MUTED}`}>{label}</span>
    </div>
  );
}

export default async function Landing() {
  const [stats, regions, lastUpdated] = await Promise.all([
    fetchStats(),
    fetchRegionSummaries(),
    fetchLastUpdated(),
  ]);

  const nf = new Intl.NumberFormat("id-ID");
  const settled = regions.find((r) => r.obsDate)?.obsDate ?? null;

  return (
    <>
      <SiteHeader />

      <main className="flex min-h-dvh flex-col">
        {/* ---- Hero ------------------------------------------------------ */}
        <section className="hero-wash border-b border-edge">
          <div className={`${CONTAINER} py-14 sm:py-20`}>
            <div className="max-w-2xl">
              <p
                className={`inline-flex items-center gap-2 rounded-full border border-brand-soft-border bg-brand-soft px-3 py-1 text-xs font-semibold text-brand`}
              >
                <span aria-hidden>●</span>
                {COPY.heroEyebrow}
              </p>

              <h1 className="mt-5 text-3xl font-extrabold leading-[1.1] tracking-tight sm:text-5xl">
                {COPY.heroTitle}
              </h1>

              <p className={`mt-5 max-w-xl text-base leading-relaxed sm:text-lg ${MUTED}`}>
                {COPY.heroBody}
              </p>

              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link href="/wilayah" className={BUTTON_PRIMARY}>
                  {COPY.heroCta}
                  <span aria-hidden>&rarr;</span>
                </Link>
                <Link href="/sumber" className={BUTTON_SECONDARY}>
                  {COPY.heroSecondary}
                </Link>
              </div>

              <p className={`mt-4 text-sm ${SUBTLE}`}>{COPY.heroBoundary}</p>
            </div>

            {/* Coverage, counted rather than asserted. */}
            <dl className="mt-12 grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-4">
              <Stat value={nf.format(stats.commodities)} label={COPY.statCommodities} />
              <Stat value={nf.format(stats.regions)} label={COPY.statRegions} />
              <Stat value={nf.format(stats.sources)} label={COPY.statSources} />
              <Stat value={nf.format(stats.observations)} label={COPY.statObservations} />
            </dl>
          </div>
        </section>

        {/* ---- Live state ------------------------------------------------ */}
        <section className={`${CONTAINER} py-14 sm:py-20`}>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="max-w-xl">
              <h2 className={DISPLAY_TITLE}>{COPY.liveTitle}</h2>
              <p className={`mt-3 text-sm leading-relaxed ${MUTED}`}>{COPY.liveBody}</p>
            </div>
            {settled && (
              <p className={`text-xs ${SUBTLE}`}>
                {COPY.dataFrom}: {formatLongDate(settled)}
              </p>
            )}
          </div>

          <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {regions.map((region) => {
              const urgent = region.attention > 0;
              // A count may only be shown where something was actually
              // assessable. Kota Yogyakarta has data but every commodity landed
              // in `belum_dapat_dinilai`, and rendering that as "0 perlu
              // diperhatikan" claims the region was checked and found clean —
              // the exact reading the fourth level exists to prevent.
              const assessed = region.obsDate !== null && (region.attention > 0 || region.calm > 0);
              return (
                <li key={region.slug}>
                  <Link
                    href={`/wilayah/${region.slug}`}
                    className={`flex h-full flex-col gap-3 ${PANEL} p-5 hover:border-brand hover:shadow-raised ${INTERACTION}`}
                  >
                    <span className={SECTION_LABEL}>{region.display_name}</span>

                    <span className="flex items-baseline gap-2">
                      {/* The tint is decoration; the digit and the words beside
                          it are what carry the meaning. */}
                      <span
                        className={`text-3xl font-extrabold tabular-nums ${urgent ? "text-brand" : ""}`}
                      >
                        {assessed ? region.attention : "—"}
                      </span>
                      <span className={`text-xs font-medium ${MUTED}`}>
                        {assessed
                          ? COPY.needsAttention.toLowerCase()
                          : region.obsDate
                            ? COPY.regionUnjudgedOnly
                            : COPY.regionNoData}
                      </span>
                    </span>

                    {region.topCommodity ? (
                      <span className="mt-auto flex items-center gap-2 text-sm font-medium">
                        <CommodityIcon
                          slug={region.topSlug ?? ""}
                          className="h-5 w-5 shrink-0 text-brand"
                        />
                        <span className="truncate">{region.topCommodity}</span>
                      </span>
                    ) : assessed ? (
                      <span className={`mt-auto text-sm ${MUTED}`}>
                        <span aria-hidden className="mr-1.5 text-xs">
                          {LEVEL_MARK.tenang}
                        </span>
                        {COPY.regionAllCalm}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>

        {/* ---- How it works ---------------------------------------------- */}
        <section className="border-y border-edge bg-surface-muted">
          <div className={`${CONTAINER} py-14 sm:py-20`}>
            <h2 className={DISPLAY_TITLE}>{COPY.howTitle}</h2>

            <ol className="mt-8 grid gap-6 sm:grid-cols-3">
              {COPY.howSteps.map((step, i) => (
                <li key={step.title} className={`${PANEL} p-6`}>
                  <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand-soft text-sm font-extrabold text-brand tabular-nums">
                    {i + 1}
                  </span>
                  <h3 className="mt-4 text-base font-bold tracking-tight">{step.title}</h3>
                  <p className={`mt-2 text-sm leading-relaxed ${MUTED}`}>{step.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ---- Provenance ------------------------------------------------- */}
        <section className={`${CONTAINER} py-14 sm:py-20`}>
          <div className="max-w-2xl">
            <h2 className={DISPLAY_TITLE}>{COPY.trustTitle}</h2>
            <p className={`mt-3 text-sm leading-relaxed ${MUTED}`}>{COPY.trustBody}</p>
            <Link
              href="/sumber"
              className={`mt-6 inline-flex items-center gap-2 text-sm font-semibold text-brand ${INTERACTION}`}
            >
              {COPY.sourcesLink}
              <span aria-hidden>&rarr;</span>
            </Link>
          </div>
        </section>

        {/* ---- Closing ---------------------------------------------------- */}
        <section className="border-t border-edge">
          <div className={`${CONTAINER} py-14 sm:py-20`}>
            <div className="flex flex-col items-start gap-6 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className={DISPLAY_TITLE}>{COPY.closingTitle}</h2>
                <p className={`mt-2 text-sm ${MUTED}`}>{COPY.closingBody}</p>
              </div>
              <Link href="/wilayah" className={`${BUTTON_PRIMARY} shrink-0`}>
                {COPY.heroCta}
                <span aria-hidden>&rarr;</span>
              </Link>
            </div>

            <div className="mt-12">
              <PageFooter lastUpdated={lastUpdated} />
            </div>
          </div>
        </section>
      </main>
    </>
  );
}
