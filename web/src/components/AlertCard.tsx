/**
 * One commodity's status for one day.
 *
 * Level is carried by a text label first, a mark second, and colour only third.
 * The red and green tones are exactly the pair a red-green colour deficiency
 * confuses, and they are the primary output of this system — a card that means
 * the opposite thing to roughly one reader in twelve is not an acceptable
 * design. Since the levels are named `siaga`/`waspada`/`tenang` rather than by
 * colour, the label no longer leans on the tone to be read at all.
 *
 * Direction is stated on every non-green card, because the fusion score is
 * computed on |pct_change_7d| and therefore treats a crash exactly like a
 * spike. For the person reading this those are opposite situations.
 */

import Link from "next/link";

import type { AlertRow } from "@/lib/dashboard";
import { formatPercent, formatRupiah } from "@/lib/format";
import { COPY, LEVEL_LABEL, LEVEL_MARK, alertHeadline, direction } from "@/content/id";
import { INTERACTION, MUTED } from "@/lib/ui";

const TONE: Record<AlertRow["level"], string> = {
  siaga: "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30",
  waspada: "border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/30",
  tenang: "border-neutral-200 dark:border-neutral-800",
  // Dashed, and no fill: "we could not judge this" should not look like a
  // verdict, and it must not borrow the calm card's styling.
  belum_dapat_dinilai: "border-dashed border-neutral-300 dark:border-neutral-700",
};

export default function AlertCard({
  alert,
  regionSlug,
  compact = false,
}: {
  alert: AlertRow;
  regionSlug: string;
  compact?: boolean;
}) {
  const dir = direction(alert.pctChange7d);

  return (
    <Link
      href={`/wilayah/${regionSlug}/${alert.commodity_slug}`}
      className={`block rounded-lg border p-4 ${INTERACTION} ${TONE[alert.level]}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {/* `truncate` protects the single-column phone layout, where every name
              in the catalogue happens to fit. In a multi-column grid the card is
              narrower than it is on a phone, and truncating turned "Minyak goreng
              kemasan" into "Minyak goreng kema…" — the one word that distinguishes
              it from the curah variety on the same board. Above `sm` the name
              wraps instead; a taller card costs nothing, a hidden name does. */}
          <p className="truncate text-base font-medium sm:overflow-visible sm:whitespace-normal">
            {alert.commodity_name}
          </p>
          {!compact && (
            <p className="mt-0.5 text-sm">{alertHeadline(alert.level, alert.pctChange7d)}</p>
          )}
        </div>
        <div className="shrink-0 text-right">
          <p className="text-base font-semibold tabular-nums">
            {formatRupiah(alert.price)}
            {/* Not text-xs: minyak goreng is priced per litre and everything
                else per kilogram, so the unit is part of what the number means,
                not a footnote to it. design.md is explicit that the one number on
                the page must not be ambiguous. */}
            <span className={`ml-1 text-sm font-normal ${MUTED}`}>
              /{alert.canonical_unit}
            </span>
          </p>
          {alert.pctChange7d !== null && dir !== "datar" && (
            <p className={`text-sm tabular-nums ${MUTED}`}>
              {/* Arrow AND sign AND word: three redundant encodings, because a
                  small coloured triangle alone is the least reliable of them. */}
              <span aria-hidden>{dir === "naik" ? "▲" : "▼"}</span>{" "}
              {formatPercent(alert.pctChange7d)}
              <span className="sr-only"> {dir} dalam 7 hari</span>
            </p>
          )}
        </div>
      </div>

      <div className={`mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs ${MUTED}`}>
        <span>
          <span aria-hidden className="mr-1">
            {LEVEL_MARK[alert.level]}
          </span>
          {LEVEL_LABEL[alert.level]}
        </span>
        <span>{COPY.sourceCount(alert.nSources)}</span>
      </div>
    </Link>
  );
}
