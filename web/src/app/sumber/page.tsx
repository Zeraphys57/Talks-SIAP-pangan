/**
 * Every portal the system draws from.
 *
 * design.md §"Provenance on the surface" promises that each screen "states its
 * date, its source count, and links to a page naming the portals". The first two
 * were implemented and this page was not, so the chain that architecture.md claims
 * — any figure walks back to a URL and a timestamp — stopped short of the reader.
 * That document is blunt about the stakes: "if that chain is invisible to the
 * reader it is not a real property of the product."
 *
 * Inactive portals are listed too. `panelharga` is disabled because its endpoints
 * fail upstream, not because the project lost interest, and anyone comparing this
 * against the proposal is entitled to see the difference.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { fetchLastUpdated, fetchPortals } from "@/lib/dashboard";
import { COPY } from "@/content/id";
import PageFooter from "@/components/PageFooter";
import { INTERACTION, MUTED, PAGE } from "@/lib/ui";

export const revalidate = 1800;

export const metadata: Metadata = {
  title: `${COPY.sourcesPageTitle} — SIAP-PANGAN`,
  description:
    "Portal resmi yang menjadi sumber setiap angka di SIAP-PANGAN, beserta status dan cakupannya.",
};

export default async function SourcesPage() {
  const [sources, lastUpdated] = await Promise.all([fetchPortals(), fetchLastUpdated()]);

  return (
    <main className={PAGE.reading}>
      <header>
        <Link href="/" className={`text-sm ${MUTED} underline underline-offset-2`}>
          &larr; {COPY.back}
        </Link>
        <h1 className="mt-3 text-xl font-semibold tracking-tight">{COPY.sourcesPageTitle}</h1>
        <p className={`mt-2 text-sm leading-relaxed ${MUTED}`}>{COPY.sourcesPageIntro}</p>
      </header>

      <ul className="flex flex-col gap-3">
        {sources.map((s) => (
          <li
            key={s.slug}
            className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800"
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h2 className="text-base font-medium">{s.display_name}</h2>
              {/* Status as a word, not a coloured dot. Same reasoning as the alert
                  levels: colour alone is the least reliable encoding, and this
                  distinction decides whether a reader trusts the coverage. */}
              <p className={`text-xs ${MUTED}`}>
                <span aria-hidden className="mr-1">
                  {s.is_active ? "●" : "○"}
                </span>
                {s.is_active ? COPY.sourceActive : COPY.sourceInactive}
              </p>
            </div>

            <dl className={`mt-2 flex flex-col gap-1 text-xs ${MUTED}`}>
              {s.owner && (
                <div className="flex gap-2">
                  <dt className="shrink-0">{COPY.sourceOwner}:</dt>
                  <dd>{s.owner}</dd>
                </div>
              )}
              {s.scope && (
                <div className="flex gap-2">
                  <dt className="shrink-0">{COPY.sourceScope}:</dt>
                  <dd>{s.scope}</dd>
                </div>
              )}
              {s.cadence && (
                <div className="flex gap-2">
                  <dt className="shrink-0">{COPY.sourceCadence}:</dt>
                  <dd>{s.cadence}</dd>
                </div>
              )}
            </dl>

            {s.notes && <p className={`mt-2 text-xs leading-relaxed ${MUTED}`}>{s.notes}</p>}

            {s.base_url && (
              <a
                href={s.base_url}
                target="_blank"
                rel="noreferrer noopener"
                className={`mt-3 inline-block rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium dark:border-neutral-800 ${INTERACTION}`}
              >
                {COPY.sourceVisit} &rarr;
              </a>
            )}
          </li>
        ))}
      </ul>

      <p className={`text-xs leading-relaxed ${MUTED}`}>{COPY.sourcesPageSchedule}</p>

      <PageFooter lastUpdated={lastUpdated} showSourcesLink={false} />
    </main>
  );
}
