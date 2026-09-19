/**
 * Region chooser — the entry point.
 *
 * A warung buys where it is. Asking which region first is one tap that makes
 * every number afterwards the reader's own price rather than a national average
 * that describes nobody. `nasional` exists as a series but is deliberately not
 * offered here (see docs/design.md).
 *
 * Each choice now carries that region's own headline count. The rule design.md
 * sets is about *whose* prices are shown, not about making the first screen
 * blank — and a chooser with nothing on it spent a tap before the reader learned
 * anything at all.
 */

import Link from "next/link";
import { fetchLastUpdated, fetchRegionSummaries, type RegionSummary } from "@/lib/dashboard";
import { COPY, LEVEL_MARK } from "@/content/id";
import PageFooter from "@/components/PageFooter";
import { INTERACTION, MUTED, PANEL, PAGE, SECTION_LABEL } from "@/lib/ui";

export const revalidate = 1800;

/**
 * The one line under a region's name.
 *
 * The three cases are the board's three buckets, and the order of the tests is
 * the same guard the board uses: "semua bergerak wajar" may only be said when
 * something was actually found to be normal. A region whose commodities all
 * landed in `belum_dapat_dinilai` has had nothing checked, and saying it is calm
 * would be the strongest possible claim drawn from the weakest possible
 * evidence.
 */
function summaryLine(region: RegionSummary): { mark: string; text: string; urgent: boolean } {
  if (!region.obsDate) return { mark: LEVEL_MARK.belum_dapat_dinilai, text: COPY.regionNoData, urgent: false };
  if (region.attention > 0) {
    return {
      mark: LEVEL_MARK.siaga,
      text: COPY.regionAttention(region.attention),
      urgent: true,
    };
  }
  if (region.calm > 0) return { mark: LEVEL_MARK.tenang, text: COPY.regionAllCalm, urgent: false };
  return { mark: LEVEL_MARK.belum_dapat_dinilai, text: COPY.regionUnjudgedOnly, urgent: false };
}

export default async function Home() {
  const [regions, lastUpdated] = await Promise.all([fetchRegionSummaries(), fetchLastUpdated()]);

  return (
    <main className={PAGE.home}>
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">{COPY.appName}</h1>
        <p className={`mt-2 text-sm leading-relaxed ${MUTED}`}>{COPY.tagline}</p>
      </header>

      <section>
        <h2 className={SECTION_LABEL}>{COPY.chooseRegion}</h2>
        <p className={`mt-2 text-sm leading-relaxed ${MUTED}`}>{COPY.regionHint}</p>

        {/* Two columns from `sm` up: four regions fit side by side without any
            of them growing to an absurd width. Stays one column on a phone. */}
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {regions.map((region) => {
            const summary = summaryLine(region);
            return (
              <li key={region.slug}>
                <Link
                  href={`/wilayah/${region.slug}`}
                  className={`flex items-center justify-between gap-3 ${PANEL} px-4 py-4 hover:border-neutral-400 dark:hover:border-neutral-600 ${INTERACTION}`}
                >
                  <span className="min-w-0">
                    <span className="block text-base font-medium">{region.display_name}</span>

                    {/* Mark then words. The mark is shape, the sentence is the
                        signal; neither is a colour, so the card still reads for
                        the one person in twelve who cannot separate the tones. */}
                    <span
                      className={`mt-1 block text-sm ${summary.urgent ? "font-medium" : MUTED}`}
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

                  <span aria-hidden className={`shrink-0 ${MUTED}`}>
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
  );
}
