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

// Used for coverage ranges, which span years. "31 Jul - 28 Jul" without the
// year reads as a four-day range rather than the three years it is.
const shortDateWithYear = new Intl.DateTimeFormat("id-ID", {
  day: "numeric",
  month: "short",
  year: "numeric",
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

export function formatShortDateWithYear(iso: string): string {
  return shortDateWithYear.format(localDate(iso));
}

/**
 * When the pipeline last finished, as day, date and clock time in WIB.
 *
 * Distinct from `formatLongDate`, which renders an observation *date* — the day
 * the prices belong to. This renders a *timestamp*, and the difference is the
 * whole point: a board reading "Data terakhir: Rabu, 29 Juli" tells you nothing
 * about whether the system is still running. Somebody opening it on 2 August has
 * no way to tell a settled-day lag from a pipeline that died three days ago.
 *
 * Pinned to Asia/Jakarta rather than the visitor's zone. The analysis runs on WIB
 * and the audience is in WIB; rendering 02:14 as 19:14 the previous day would be
 * accurate and useless.
 */
const updatedAt = new Intl.DateTimeFormat("id-ID", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Jakarta",
});

export function formatUpdatedAt(iso: string): string {
  return `${updatedAt.format(new Date(iso))} WIB`;
}

/** Signed percentage, e.g. "+12,4%". Indonesian uses a comma for decimals. */
export function formatPercent(fraction: number): string {
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toLocaleString("id-ID", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}
