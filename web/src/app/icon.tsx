/**
 * The home-screen and browser-tab mark.
 *
 * A text mark rather than an emoji, and that is a technical choice rather than an
 * aesthetic one: `ImageResponse` renders through Satori, whose bundled face has no
 * emoji glyphs, so an emoji requires fetching an emoji font from a CDN at build
 * time. design.md refuses a network font request for the dashboard's own type; it
 * would be strange to accept one here, and a build that depends on a third-party
 * CDN is a build that can fail for reasons unrelated to this repository.
 *
 * Generated as a route, so there is no binary in the repo and no image to fall out
 * of step with the palette.
 *
 * Sized 512 and declared "any maskable" in the manifest, so the glyph sits inside
 * the central safe zone — Android crops maskable icons to a circle or squircle and
 * anything near the edge is lost. The background is full-bleed for the same
 * reason: a maskable icon must paint its whole canvas or the crop shows through.
 *
 * Colours are the app's own #0a0a0a / #ededed. No brand colour is invented here,
 * and deliberately none of the alert palette — red, amber and green mean specific
 * things in this system and must not be spent on decoration.
 */

import { ImageResponse } from "next/og";

export const size = { width: 512, height: 512 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0a0a0a",
          color: "#ededed",
          // Roughly 62% of the canvas, which keeps the glyph inside the 80% safe
          // zone with room to spare.
          fontSize: 250,
          fontWeight: 700,
          letterSpacing: -12,
        }}
      >
        SP
      </div>
    ),
    size,
  );
}
