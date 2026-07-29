/**
 * Indonesian formatting helpers.
 *
 * Fixed to the "id-ID" locale rather than the visitor's, so a screenshot in the
 * paper reads the same as the screen a warung owner saw. Rupiah is shown
 * without decimals: nobody prices cabai to the sen.
 */

const rupiah = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

const longDate = new Intl.DateTimeFormat("id-ID", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

const shortDate = new Intl.DateTimeFormat("id-ID", {
  day: "numeric",
  month: "short",
});

/** Parse an ISO date as local midnight, not UTC midnight.
 *
 * `new Date("2024-03-15")` is UTC, and rendering that in WIB is still 15 March
 * — but in any timezone west of UTC it prints as the 14th. The dates here are
 * calendar days from a Postgres `date` column with no time in them, so they
 * must not be shifted by a timezone. */
function localDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatRupiah(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return rupiah.format(value);
}

export function formatLongDate(iso: string): string {
  return longDate.format(localDate(iso));
}

export function formatShortDate(iso: string): string {
  return shortDate.format(localDate(iso));
}

/** Signed percentage, e.g. "+12,4%". Indonesian uses a comma for decimals. */
export function formatPercent(fraction: number): string {
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toLocaleString("id-ID", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}
