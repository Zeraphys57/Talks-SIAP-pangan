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

const monthShort = new Intl.DateTimeFormat("id-ID", { month: "short" });

/**
 * The calendar week an ISO week number actually refers to: "24–30 Mar".
 *
 * `seasonal_components` is computed weekly, so a risky period is identified by
 * its ISO week number — and the commodity page was rendering that number raw,
 * as "Minggu 13". Nobody buying cabai thinks in ISO weeks; the number is an
 * artefact of how the decomposition is indexed, not information about when to
 * expect a price rise. `startsOn` was already being fetched alongside it and
 * thrown away at the component.
 *
 * No year, deliberately. This is a pattern that recurs annually, so naming one
 * specific March would read as a claim about that year. The consequence is that
 * the dates shift by a few days between years, which the caption states.
 */
export function formatWeekRange(startsOnIso: string): string {
  const start = localDate(startsOnIso);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);

  return start.getMonth() === end.getMonth()
    ? `${start.getDate()}–${end.getDate()} ${monthShort.format(end)}`
    : `${start.getDate()} ${monthShort.format(start)} – ${end.getDate()} ${monthShort.format(end)}`;
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

/**
 * Unsigned, whole-number percentage, e.g. "8%".
 *
 * For differences whose direction is carried by the words around them — "8%
 * lebih murah". A signed "-8%" beside "lebih murah" states the direction twice
 * and invites the reader to wonder whether the two disagree. Whole numbers
 * because a tenth of a percent is below the resolution at which anyone decides
 * which market to buy from.
 */
export function formatPercentMagnitude(fraction: number): string {
  return `${Math.round(Math.abs(fraction) * 100)}%`;
}

/** Signed percentage, e.g. "+12,4%". Indonesian uses a comma for decimals. */
export function formatPercent(fraction: number): string {
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toLocaleString("id-ID", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}
