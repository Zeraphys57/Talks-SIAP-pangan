/**
 * The board for one region: what needs attention, and what does not.
 *
 * Sorted by fusion score, then split into "perlu diperhatikan" and the rest.
 * The split matters more than the ordering: a warung owner has attention for
 * two or three things, and a list of twelve equally-weighted rows spends that
 * attention on nothing.
 */

import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchBoard, fetchRegions } from "@/lib/dashboard";
import { COPY } from "@/content/id";
import AlertCard from "@/components/AlertCard";
import { formatLongDate } from "@/lib/format";

export const revalidate = 1800;

export async function generateStaticParams() {
  const regions = await fetchRegions();
  return regions.map((r) => ({ region: r.slug }));
}

export default async function RegionPage({
  params,
}: {
  params: Promise<{ region: string }>;
}) {
  const { region } = await params;
  const board = await fetchBoard(region);
  if (!board) notFound();

  const attention = board.alerts.filter((a) => a.level !== "hijau");
  const calm = board.alerts.filter((a) => a.level === "hijau");

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col gap-6 px-5 py-8">
      <header>
        <Link href="/" className="text-sm text-neutral-500 underline underline-offset-2">
          &larr; {COPY.back}
        </Link>
        <h1 className="mt-3 text-xl font-semibold tracking-tight">{board.regionName}</h1>
        {board.obsDate ? (
          <p className="mt-1 text-sm text-neutral-500">
            {COPY.dataFrom}: {formatLongDate(board.obsDate)}
          </p>
        ) : null}
      </header>

      {board.todayWithheld && (
        <p className="rounded-lg bg-neutral-100 px-4 py-3 text-xs leading-relaxed text-neutral-600 dark:bg-neutral-900 dark:text-neutral-400">
          {COPY.todayWithheld}
        </p>
      )}

      {!board.obsDate && (
        <section className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
          <p className="text-sm font-medium">{COPY.noData}</p>
          <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
            {COPY.noDataHelp}
          </p>
        </section>
      )}

      {attention.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium">{COPY.needsAttention}</h2>
          {attention.map((alert) => (
            <AlertCard key={alert.commodity_slug} alert={alert} regionSlug={region} />
          ))}
        </section>
      )}

      {board.obsDate && attention.length === 0 && (
        <p className="rounded-lg border border-neutral-200 px-4 py-4 text-sm dark:border-neutral-800">
          {COPY.allNormal}
        </p>
      )}

      {calm.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-neutral-500">{COPY.normalPrices}</h2>
          {calm.map((alert) => (
            <AlertCard key={alert.commodity_slug} alert={alert} regionSlug={region} compact />
          ))}
        </section>
      )}

      <p className="text-xs leading-relaxed text-neutral-500">{COPY.notForecast}</p>
      <p className="mt-auto text-xs text-neutral-500">{COPY.footer}</p>
    </main>
  );
}
