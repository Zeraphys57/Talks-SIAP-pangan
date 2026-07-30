/**
 * Region chooser — the entry point.
 *
 * A warung buys where it is. Asking which region first is one tap that makes
 * every number afterwards the reader's own price rather than a national average
 * that describes nobody. `nasional` exists as a series but is deliberately not
 * offered here (see docs/design.md).
 */

import Link from "next/link";
import { fetchLastUpdated, fetchRegions } from "@/lib/dashboard";
import { COPY } from "@/content/id";
import PageFooter from "@/components/PageFooter";
import { INTERACTION, MUTED, PAGE } from "@/lib/ui";

export const revalidate = 1800;

export default async function Home() {
  const [regions, lastUpdated] = await Promise.all([fetchRegions(), fetchLastUpdated()]);

  return (
    <main className={PAGE.home}>
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{COPY.appName}</h1>
        <p className={`mt-1 text-sm ${MUTED}`}>{COPY.tagline}</p>
      </header>

      <section>
        <h2 className="text-sm font-medium">{COPY.chooseRegion}</h2>
        <p className={`mt-1 text-sm ${MUTED}`}>{COPY.regionHint}</p>

        {/* Two columns from `sm` up: four regions fit side by side without any
            of them growing to an absurd width. Stays one column on a phone. */}
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {regions.map((region) => (
            <li key={region.slug}>
              <Link
                href={`/wilayah/${region.slug}`}
                className={`flex items-center justify-between rounded-lg border border-neutral-200 px-4 py-4 text-base font-medium hover:border-neutral-400 dark:border-neutral-800 dark:hover:border-neutral-600 ${INTERACTION}`}
              >
                {region.display_name}
                <span aria-hidden className={MUTED}>
                  &rarr;
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <PageFooter lastUpdated={lastUpdated} />
    </main>
  );
}
