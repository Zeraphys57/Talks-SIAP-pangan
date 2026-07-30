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

// There is deliberately no BORDER token. `border-neutral-200 … dark:border-
// neutral-800` appears nine times, but always interleaved with per-use spacing
// (`p-4`, `px-3 py-2`, `px-2 py-1`), so one constant cannot express it without
// also dictating padding. More to the point, all nine already agree — unlike the
// muted colour, there is no divergence to fix, and a token nobody uses is worse
// than no token.

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
