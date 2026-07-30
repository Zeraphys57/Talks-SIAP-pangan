/**
 * The preview card when this link is pasted into WhatsApp.
 *
 * WhatsApp is the realistic distribution channel here — it is how a warung owner
 * receives a link, and how this project gets sent to the team and to examiners.
 * Without this the preview is a bare URL.
 *
 * Generated as a route rather than committed as a PNG, so there is no binary in
 * the repository to drift out of date, and the scope disclaimer on the card comes
 * from the same COPY constant as the pages. It renders at build time.
 *
 * No webfont is loaded. design.md refuses a render-blocking font request for the
 * dashboard itself, and there is no reason to hold a different standard here; the
 * default face Satori ships with is used as-is.
 */

import { ImageResponse } from "next/og";

import { COPY } from "@/content/id";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "SIAP-PANGAN — pantau harga bahan pangan dari sumber resmi";

export default function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#0a0a0a",
          color: "#ededed",
          padding: 72,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ fontSize: 82, fontWeight: 700, letterSpacing: -2 }}>SIAP-PANGAN</div>
          <div style={{ fontSize: 36, color: "#a3a3a3", marginTop: 16 }}>{COPY.tagline}</div>
        </div>

        {/* The one claim that must survive being screenshotted out of context. */}
        <div
          style={{
            display: "flex",
            fontSize: 26,
            color: "#a3a3a3",
            lineHeight: 1.4,
            borderTop: "2px solid #262626",
            paddingTop: 28,
          }}
        >
          {COPY.notForecast}
        </div>
      </div>
    ),
    size,
  );
}
