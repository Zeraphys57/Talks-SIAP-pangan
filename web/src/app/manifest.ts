/**
 * Lets the dashboard be added to a phone's home screen.
 *
 * design.md does not ask for this, so it is an addition rather than an unmet
 * promise — but it follows from the same audience: a warung owner checking prices
 * between customers, every day, on an entry-level Android. A home-screen icon
 * removes a browser, a tab and a typed URL from that loop.
 *
 * `display: "browser"` on purpose, not "standalone". Standalone hides the address
 * bar, and this dashboard publishes government price data that people are entitled
 * to verify the origin of — hiding the URL of a site whose whole argument is
 * provenance would be the wrong trade.
 *
 * The icon is the existing favicon. A proper 512px maskable icon is still missing;
 * that needs a designed asset, and inventing a logo for someone else's project is
 * not mine to do.
 */

import type { MetadataRoute } from "next";

import { COPY } from "@/content/id";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: `${COPY.appName} — ${COPY.tagline}`,
    short_name: COPY.appName,
    description: COPY.notForecast,
    start_url: "/",
    display: "browser",
    lang: "id",
    background_color: "#0a0a0a",
    theme_color: "#0a0a0a",
    icons: [{ src: "/favicon.ico", sizes: "any", type: "image/x-icon" }],
  };
}
