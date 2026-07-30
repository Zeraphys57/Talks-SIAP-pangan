/**
 * The same four things at the bottom of every public screen.
 *
 * It exists because design.md §"Provenance on the surface" applies to *every*
 * screen, and the three pages were each ending with their own hand-copied pair of
 * paragraphs — which is how the front page ended up with no date, no source count
 * and no link to the portals at all.
 *
 * Order is deliberate: the scope disclaimer first because it is the strongest
 * claim on the page and must not be buried, then where the numbers came from,
 * then when they were last refreshed, then who built it.
 */

import Link from "next/link";

import { COPY } from "@/content/id";
import { formatUpdatedAt } from "@/lib/format";
import { INTERACTION, MUTED } from "@/lib/ui";

export default function PageFooter({
  lastUpdated,
  showSourcesLink = true,
}: {
  /** ISO timestamp of the last successful fusion run, or null if there is none. */
  lastUpdated: string | null;
  /** The sources page itself does not need to link to itself. */
  showSourcesLink?: boolean;
}) {
  return (
    <footer className={`mt-auto flex flex-col gap-2 text-xs ${MUTED}`}>
      <p className="leading-relaxed">{COPY.notForecast}</p>

      {showSourcesLink && (
        <p>
          <Link
            href="/sumber"
            className={`underline underline-offset-2 ${INTERACTION} inline-block`}
          >
            {COPY.sourcesLink}
          </Link>
        </p>
      )}

      {/* `tabular-nums` so the clock time does not jitter between renders, and a
          real <time> element so the machine-readable value is the ISO one rather
          than the Indonesian prose. */}
      <p className="tabular-nums">
        {lastUpdated ? (
          <>
            {COPY.updatedAt}: <time dateTime={lastUpdated}>{formatUpdatedAt(lastUpdated)}</time>
          </>
        ) : (
          COPY.updatedNever
        )}
      </p>

      <p>{COPY.footer}</p>
    </footer>
  );
}
