/**
 * The board for one region: what needs attention, and what does not.
 *
 * Sorted by fusion score, then split into "perlu diperhatikan" and the rest.
 * The split matters more than the ordering: a warung owner has attention for
 * two or three things, and a list of twelve equally-weighted rows spends that
 * attention on nothing.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchBoard, fetchLastUpdated, fetchRegions } from "@/lib/dashboard";
import { COPY } from "@/content/id";
import PageFooter from "@/components/PageFooter";
import AlertCard from "@/components/AlertCard";
import { formatLongDate } from "@/lib/format";
import { CARD_GRID, MUTED, PAGE } from "@/lib/ui";

export const revalidate = 1800;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ region: string }>;
}): Promise<Metadata> {
  const { region } = await params;
  const regions = await fetchRegions();
  const name = regions.find((r) => r.slug === region)?.display_name ?? region;
  return {
    title: `Harga pangan ${name} — SIAP-PANGAN`,
    description: `Harga bahan pangan di ${name} dari portal resmi, dengan penanda bahan yang bergerak tidak biasa.`,
  };
}

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
  const [board, lastUpdated] = await Promise.all([fetchBoard(region), fetchLastUpdated()]);
  if (!board) notFound();

  // Three buckets, not two. `belum_dapat_dinilai` belongs in neither of the
  // original ones: it is not something to act on, and filing it under "bergerak
  // wajar" would be the exact claim this level exists to stop making.
  const attention = board.alerts.filter(
    (a) => a.level === "siaga" || a.level === "waspada",
  );
  const calm = board.alerts.filter((a) => a.level === "tenang");
  const unjudged = board.alerts.filter((a) => a.level === "belum_dapat_dinilai");

  return (
    <main className={PAGE.board}>
      <header>
        <Link href="/" className={`text-sm ${MUTED} underline underline-offset-2`}>
          &larr; {COPY.back}
        </Link>
        <h1 className="mt-3 text-xl font-semibold tracking-tight">{board.regionName}</h1>
        {board.obsDate ? (
          <p className={`mt-1 text-sm ${MUTED}`}>
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
          <p className={`mt-2 text-sm ${MUTED}`}>
            {COPY.noDataHelp}
          </p>
        </section>
      )}

      {attention.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium">{COPY.needsAttention}</h2>
          <div className={CARD_GRID}>
            {attention.map((alert) => (
              <AlertCard key={alert.commodity_slug} alert={alert} regionSlug={region} />
            ))}
          </div>
        </section>
      )}

      {/* `calm.length > 0` guards a specific lie: if every commodity landed in
          belum_dapat_dinilai, nothing was found to be normal — nothing was
          checked. "Semua bahan bergerak wajar" would be the strongest possible
          claim drawn from the weakest possible evidence. */}
      {board.obsDate && attention.length === 0 && calm.length > 0 && (
        <p className="rounded-lg border border-neutral-200 px-4 py-4 text-sm dark:border-neutral-800">
          {COPY.allNormal}
        </p>
      )}

      {calm.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className={`text-sm font-medium ${MUTED}`}>{COPY.normalPrices}</h2>
          <div className={CARD_GRID}>
            {calm.map((alert) => (
              <AlertCard key={alert.commodity_slug} alert={alert} regionSlug={region} compact />
            ))}
          </div>
        </section>
      )}

      {unjudged.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className={`text-sm font-medium ${MUTED}`}>{COPY.notAssessed}</h2>
          <p className={`text-xs leading-relaxed ${MUTED}`}>{COPY.notAssessedHelp}</p>
          <div className={CARD_GRID}>
            {unjudged.map((alert) => (
              <AlertCard key={alert.commodity_slug} alert={alert} regionSlug={region} compact />
            ))}
          </div>
        </section>
      )}

      <PageFooter lastUpdated={lastUpdated} />
    </main>
  );
}
