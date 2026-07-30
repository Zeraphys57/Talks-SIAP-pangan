/**
 * iOS home-screen mark.
 *
 * Separate from icon.tsx because iOS does not crop to a mask — it applies its own
 * rounded rectangle — so the glyph can be larger without risking the safe zone.
 * 180 is the size iOS asks for.
 */

import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
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
          fontSize: 104,
          fontWeight: 700,
          letterSpacing: -5,
        }}
      >
        SP
      </div>
    ),
    size,
  );
}
