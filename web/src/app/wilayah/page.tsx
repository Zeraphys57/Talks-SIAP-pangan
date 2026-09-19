/**
 * Region chooser.
 *
 * Was the front page until the landing took that slot. It keeps the argument
 * that put it there: a warung buys where it is, so asking for the region first
 * is one tap that makes every number afterwards the reader's own price rather
 * than a national average that describes nobody. `nasional` exists as a series
 * but is deliberately not offered (see docs/design.md).
 *
 * Each choice carries that region's own headline count, so the tap is an
 * informed one.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { fetchLastUpdated, fetchRegionSummaries, type RegionSummary } from "@/lib/dashboard";
import { COPY, LEVEL_MARK } from "@/content/id";
import PageFooter from "@/components/PageFooter";
import SiteHeader from "@/components/SiteHeader";
import { INTERACTION, MUTED, PANEL, PAGE, SECTION_LABEL } from "@/lib/ui";

export const revalidate = 1800;

export const metadata: Metadata = {
  title: "Pilih wilayah — SIAP-PANGAN",
  description: "Harga bahan pangan per wilayah, dari portal resmi pemerintah.",
};

/**
 * The one line under a region's name.
 *
 * The order of the tests is the guard the board uses: "semua bergerak wajar"
 * may only be said when something was actually found to be normal. A region
 * whose commodities all landed in `belum_dapat_dinilai` has had nothing
 * checked, and calling it calm would be the strongest possible claim drawn from
 * the weakest possible evidence.
 */
function summaryLine(region: RegionSummary): { mark: string; text: string; urgent: boolean } {
  if (!region.obsDate) {
    return { mark: LEVEL_MARK.belum_dapat_dinilai, text: COPY.regionNoData, urgent: false };
  }
  if (region.attention > 0) {
    return { mark: LEVEL_MARK.siaga, text: COPY.regionAttention(region.attention), urgent: true };
  }
  if (region.calm > 0) {
    return { mark: LEVEL_MARK.tenang, text: COPY.regionAllCalm, urgent: false };
  }
  return { mark: LEVEL_MARK.belum_dapat_dinilai, text: COPY.regionUnjudgedOnly, urgent: false };
}

export default async function RegionChooser() {
  const [regions, lastUpdated] = await Promise.all([fetchRegionSummaries(), fetchLastUpdated()]);

  return (
    <>
      <SiteHeader cta={false} />
      <main className={PAGE.home}>
        <header>
          <h1 className="text-2xl font-extrabold tracking-tight">{COPY.chooseRegion}</h1>
          <p className={`mt-2 text-sm leading-relaxed ${MUTED}`}>{COPY.regionHint}</p>
        </header>

        <section>
          <h2 className={`${SECTION_LABEL} sr-only`}>{COPY.chooseRegion}</h2>
          <ul className="grid gap-3 sm:grid-cols-2">
            {regions.map((region) => {
              const summary = summaryLine(region);
              return (
                <li key={region.slug}>
                  <Link
                    href={`/wilayah/${region.slug}`}
                    className={`flex h-full items-center justify-between gap-3 ${PANEL} px-5 py-4 hover:border-brand hover:shadow-raised ${INTERACTION}`}
                  >
                    <span className="min-w-0">
                      <span className="block text-base font-bold">{region.display_name}</span>

                      {/* Mark then words. The mark is shape and the sentence is
                          the signal; neither is a colour, so the card still
                          reads for someone who cannot separate the tones. */}
                      <span
                        className={`mt-1 block text-sm ${summary.urgent ? "font-semibold" : MUTED}`}
                      >
                        <span aria-hidden className="mr-1.5 text-xs">
                          {summary.mark}
                        </span>
                        {summary.text}
                      </span>

                      {region.topCommodity && (
                        <span className={`mt-0.5 block truncate text-xs ${MUTED}`}>
                          {COPY.regionTop(region.topCommodity, region.attention - 1)}
                        </span>
                      )}
                    </span>

                    <span aria-hidden className={`shrink-0 text-lg ${MUTED}`}>
                      &rarr;
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </section>

        <PageFooter lastUpdated={lastUpdated} />
      </main>
    </>
  );
}
