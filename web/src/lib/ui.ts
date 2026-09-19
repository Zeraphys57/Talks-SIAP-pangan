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
 * again. The colours below moved to semantic tokens in `globals.css`, which ends
 * the class of bug outright — a token cannot resolve differently per scheme by
 * accident, because each scheme defines it explicitly — but the guard stays: it
 * is what stops anyone reaching for a raw `neutral-500` again.
 */

/**
 * Recessive text: labels, units, source counts, captions, footers.
 * `--foreground-muted` is defined per scheme and clears 4.5:1 on the surface it
 * lands on in both.
 */
export const MUTED = "text-ink-muted";

/** Quieter still: captions under a caption, legend text, timestamps. */
export const SUBTLE = "text-ink-subtle";

/**
 * Touch and keyboard affordance for anything tappable.
 *
 * `hover:` is nearly dead on the phone design.md optimises for; `active:` is the
 * state a thumb produces, and without it a tap gives no acknowledgement while the
 * next page loads over mobile data. Scale rather than a background flash, so it
 * composes with the alert level tones instead of fighting them.
 */
export const INTERACTION =
  "transition-[transform,box-shadow,border-color,background-color] duration-150 " +
  "active:scale-[0.99] motion-reduce:transition-none " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand";

/**
 * A bordered surface. Radius, border and lift — no padding, which genuinely
 * varies per use.
 */
export const PANEL = "rounded-2xl border border-edge bg-surface shadow-card";

/** The same surface, raised, for things that should read as sitting above the page. */
export const PANEL_RAISED = "rounded-2xl border border-edge bg-surface-raised shadow-raised";

/** Buttons. Text on brand is measured at the same ratio in both schemes. */
export const BUTTON_PRIMARY =
  `inline-flex items-center justify-center gap-2 rounded-full bg-brand px-5 py-3 ` +
  `text-sm font-semibold text-brand-on hover:bg-brand-hover ${INTERACTION}`;

export const BUTTON_SECONDARY =
  `inline-flex items-center justify-center gap-2 rounded-full border border-edge-strong ` +
  `bg-surface px-5 py-3 text-sm font-semibold hover:border-brand ${INTERACTION}`;

/**
 * Section headings, in two weights — because there are two kinds of section and
 * they were being written six different ways.
 *
 * `SECTION_LABEL` is the quiet kind: a name for a group the reader is scanning
 * past. Set in caps with tracking so it reads as a label rather than a sentence
 * — the distinction body-sized medium weight could not make.
 *
 * `SECTION_TITLE` is for the one section that is the point of the page.
 */
export const SECTION_LABEL = `text-xs font-bold uppercase tracking-[0.12em] ${MUTED}`;
export const SECTION_TITLE = "text-lg font-bold tracking-tight";

/** Landing-page section heading: bigger, because it is doing marketing work. */
export const DISPLAY_TITLE = "text-2xl font-extrabold tracking-tight sm:text-3xl";

/**
 * Page shells. One column on a phone in every case — that is the layout design.md
 * argues for and the only one that has to be perfect. Wider viewports get more
 * columns or a longer measure, never bigger components.
 */
const SHELL = "mx-auto flex min-h-dvh max-w-md flex-col";

export const PAGE = {
  /** Region chooser. */
  home: `${SHELL} gap-8 px-5 py-10 sm:max-w-xl`,
  /** Region board: holds the alert grid, so it earns the most width. */
  board: `${SHELL} gap-7 px-5 py-8 sm:max-w-2xl lg:max-w-5xl`,
  /** One narrative column — prose stops being readable well before 1000px. */
  reading: `${SHELL} gap-7 px-5 py-8 sm:max-w-2xl`,
  /** Short centred message: error, not-found. */
  message: `${SHELL} justify-center gap-4 px-6`,
} as const;

/** Landing page sections run full-bleed, so they carry their own inner measure. */
export const CONTAINER = "mx-auto w-full max-w-6xl px-5";

/** Alert cards: columns rather than a stretched card. See PAGE.board. */
export const CARD_GRID = "grid gap-3 sm:grid-cols-2 lg:grid-cols-3";
