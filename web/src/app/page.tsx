/**
 * Region chooser — the entry point.
 *
 * A warung buys where it is. Asking which region first is one tap that makes
 * every number afterwards the reader's own price rather than a national average
 * that describes nobody. `nasional` exists as a series but is deliberately not
 * offered here (see docs/design.md).
 */

import Link from "next/link";
import { fetchRegions } from "@/lib/dashboard";
import { COPY } from "@/content/id";

export const revalidate = 1800;

export default async function Home() {
  const regions = await fetchRegions();

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col gap-8 px-5 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{COPY.appName}</h1>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">{COPY.tagline}</p>
      </header>

      <section>
        <h2 className="text-sm font-medium">{COPY.chooseRegion}</h2>
        <p className="mt-1 text-sm text-neutral-500">{COPY.regionHint}</p>

        <ul className="mt-4 flex flex-col gap-2">
          {regions.map((region) => (
            <li key={region.slug}>
              <Link
                href={`/wilayah/${region.slug}`}
                className="flex items-center justify-between rounded-lg border border-neutral-200 px-4 py-4 text-base font-medium hover:border-neutral-400 dark:border-neutral-800 dark:hover:border-neutral-600"
              >
                {region.display_name}
                <span aria-hidden className="text-neutral-400">
                  &rarr;
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-xs leading-relaxed text-neutral-500">{COPY.notForecast}</p>
      <p className="mt-auto text-xs text-neutral-500">{COPY.footer}</p>
    </main>
  );
}
