/**
 * Class strings that encode a decision, kept in one place because they were
 * getting decided repeatedly and inconsistently.
 *
 * This file exists because of a real bug. `text-neutral-500` was written inline
 * in 52 places as the muted colour. It resolves to #737373 in both schemes, which
 * is 4.74:1 on white — passing — and 4.17:1 on the #0a0a0a dark background, which
 * fails WCAG AA for normal text. Twelve other lines already used the correct
 * mode-aware pair. Nothing could catch the divergence because there was nothing
 * to compare against.
 *
 * `scripts/assert_ui_tokens.py` now fails CI if a muted colour is written inline
 * again.
 */

/**
 * Recessive text: labels, units, source counts, captions, footers.
 * #525252 on white and #a3a3a3 on #0a0a0a — about 7.8:1 in both schemes, still
 * clearly quieter than the #171717/#ededed foreground.
 */
export const MUTED = "text-neutral-600 dark:text-neutral-400";

// There is still deliberately no bare BORDER token — see PANEL below, which is
// the border pair *and* the radius, the two that always travel together. The
// original note here argued against a token on the grounds that padding varies
// per use and that all nine existing uses already agreed. The first half still
// holds and PANEL respects it by carrying no padding. The second half was an
// argument against tokenising something with no divergence to fix; what changed
// is the count, not the reasoning. At fourteen surfaces across five files the
// risk is no longer divergence today but drift on the next edit.

/**
 * Touch and keyboard affordance for anything tappable.
 *
 * `hover:` is dead code on the phone design.md optimises for; `active:` is the
 * state a thumb produces, and without it a tap gives no acknowledgement while the
 * next page loads over mobile data. Scale rather than a background flash, so it
 * composes with the alert level tones instead of fighting them. The focus ring
 * inherits currentColor, already high-contrast in both schemes.
 */
export const INTERACTION =
  "transition-transform active:scale-[0.99] motion-reduce:transition-none " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current";

/**
 * Section headings, in two weights — because there are two kinds of section and
 * they were being written six different ways.
 *
 * Every `<h2>` on the public pages was `text-sm font-medium`, sometimes muted
 * and sometimes not, which is the same size and weight as the body text beneath
 * it. Nothing announced itself as structure, so a page read as one flat column
 * of small text and the reader had to parse the wording to find the seams.
 *
 * `SECTION_LABEL` is the quiet kind: a name for a group the reader is scanning
 * past ("Bergerak wajar", "Sumber data"). Smaller than body text but set in
 * caps with tracking, so it reads as a label rather than as a sentence — the
 * distinction body-sized medium weight could not make.
 *
 * `SECTION_TITLE` is for the one section that is the point of the page. On the
 * board that is "Perlu diperhatikan"; giving it real size is what makes the
 * split design.md argues for visible at a glance instead of inferable.
 */
export const SECTION_LABEL = `text-xs font-semibold uppercase tracking-wider ${MUTED}`;
export const SECTION_TITLE = "text-base font-semibold tracking-tight";

/**
 * A bordered surface. Radius and border only — padding stays at the call site.
 *
 * The note below explains why there is no BORDER token; this is not that. The
 * border pair and the radius always travel together and now appear on fourteen
 * surfaces across five files, while the padding genuinely differs (`p-4`,
 * `px-3 py-2`, `px-2 py-1`). Splitting it exactly there is what lets one
 * constant hold without dictating spacing.
 */
export const PANEL = "rounded-lg border border-neutral-200 dark:border-neutral-800";

/**
 * Page shells. One column on a phone in every case — that is the layout design.md
 * argues for and the only one that has to be perfect. Wider viewports get more
 * columns or a longer measure, never bigger components.
 */
const SHELL = "mx-auto flex min-h-dvh max-w-md flex-col";

export const PAGE = {
  /** Front page: four region choices, 2-up from `sm`. */
  home: `${SHELL} gap-8 px-5 py-10 sm:max-w-xl`,
  /** Region board: holds the alert grid, so it earns the most width. */
  board: `${SHELL} gap-6 px-5 py-8 sm:max-w-2xl lg:max-w-5xl`,
  /** One narrative column — prose stops being readable well before 1000px. */
  reading: `${SHELL} gap-6 px-5 py-8 sm:max-w-2xl`,
  /** Short centred message: error, not-found. */
  message: `${SHELL} justify-center gap-4 px-6`,
} as const;

/** Alert cards: columns rather than a stretched card. See PAGE.board. */
export const CARD_GRID = "grid gap-3 sm:grid-cols-2 lg:grid-cols-3";
