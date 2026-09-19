/**
 * The bar across the top of every public page.
 *
 * There was no header at all: each page opened with its own back link and a
 * bare `<h1>`, so nothing tied the screens together or said what the product
 * was once you were two levels deep.
 *
 * Deliberately not in the root layout. That layout also wraps `/lab`, which is
 * the annotators' console — a marketing header above a blind labelling queue
 * would be noise at best, and at worst a route out of a task that is supposed
 * to be worked start to finish.
 */

import Link from "next/link";

import { COPY } from "@/content/id";
import { INTERACTION, MUTED } from "@/lib/ui";

/** The mark: a price line that moves, which is what the product watches. */
export function BrandMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <span
      className={`${className} grid shrink-0 place-items-center rounded-xl bg-brand text-brand-on`}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 15.5 9 10l3.5 3.5L20 6" />
        <path d="M15.5 6H20v4.5" />
      </svg>
    </span>
  );
}

export default function SiteHeader({ cta = true }: { cta?: boolean }) {
  return (
    <header className="sticky top-0 z-30 border-b border-edge bg-background/85 backdrop-blur">
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-3">
        <Link
          href="/"
          className={`flex items-center gap-2.5 rounded-xl ${INTERACTION}`}
        >
          <BrandMark />
          <span className="text-sm font-extrabold tracking-tight">{COPY.appName}</span>
        </Link>

        <nav className="flex items-center gap-1 text-sm">
          <Link
            href="/sumber"
            className={`hidden rounded-full px-3 py-2 font-medium hover:bg-surface-muted sm:inline-block ${MUTED} ${INTERACTION}`}
          >
            {COPY.sourcesLink}
          </Link>
          {cta && (
            <Link
              href="/wilayah"
              className={`rounded-full bg-brand px-4 py-2 text-sm font-semibold text-brand-on hover:bg-brand-hover ${INTERACTION}`}
            >
              {COPY.navCta}
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
