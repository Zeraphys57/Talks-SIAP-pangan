/**
 * A mark per commodity.
 *
 * Decoration that carries no meaning on its own: every place one of these
 * appears, the commodity's name is next to it. That is deliberate — a warung
 * owner should never have to recognise a glyph to know whether they are looking
 * at cabai or bawang, and the icons are `aria-hidden` for the same reason.
 *
 * Hand-rolled rather than a library. Twelve commodities need eight shapes, and
 * an icon package would be the largest thing on a page that loads over mobile
 * data — the same argument that kept a webfont out until next/font made it
 * free.
 *
 * Matched on prefix: `beras-medium` and `beras-premium` are one shape, as are
 * the two cabai, the two bawang and the two minyak goreng. A commodity added
 * later gets the fallback rather than nothing.
 */

import type { ReactNode } from "react";

const ICONS: Record<string, ReactNode> = {
  // Bowl with grains above it.
  beras: (
    <>
      <path d="M3.5 13.5h17" />
      <path d="M4.5 13.5a7.5 7.5 0 0 0 15 0" />
      <ellipse cx="9.2" cy="8.4" rx="1.5" ry="2.4" transform="rotate(-28 9.2 8.4)" />
      <ellipse cx="14.4" cy="7.6" rx="1.5" ry="2.4" transform="rotate(22 14.4 7.6)" />
    </>
  ),
  // Tapered pod with a stem.
  cabai: (
    <>
      <path d="M12 21.5c-3.1 0-5.2-2.7-5.2-6.2 0-3.8 2-7.5 5.2-9.9 3.2 2.4 5.2 6.1 5.2 9.9 0 3.5-2.1 6.2-5.2 6.2Z" />
      <path d="M12 5.4V3.2" />
      <path d="M12 4.1c1.4-1.5 3.1-1.7 4.1-1.1" />
    </>
  ),
  // Wide bulb with layer lines and a shoot.
  bawang: (
    <>
      <path d="M12 21.5c-3.9 0-6.6-2.5-6.6-5.9 0-3.5 2.7-6.8 6.6-6.8s6.6 3.3 6.6 6.8c0 3.4-2.7 5.9-6.6 5.9Z" />
      <path d="M12 8.8V4.4" />
      <path d="M12 5.8c1.3-1.4 2.9-1.6 3.8-1.1" />
      <path d="M9.4 10.1c-1 2.7-1 6.6 0 10" />
      <path d="M14.6 10.1c1 2.7 1 6.6 0 10" />
    </>
  ),
  // Egg: narrower at the top than the bulb, and unadorned.
  telur: (
    <path d="M12 21.5c-3.4 0-6-2.5-6-5.7 0-4.6 2.7-11.3 6-11.3s6 6.7 6 11.3c0 3.2-2.6 5.7-6 5.7Z" />
  ),
  // Cut of meat with a bone.
  sapi: (
    <>
      <path d="M4.8 9.2c2-4.1 8.3-5.2 12.4-3.1 3.1 1.6 3.2 6.3 1.1 8.9-2.6 3.2-8.4 3.7-11.6 1-2.1-1.8-2.8-4.6-1.9-6.8Z" />
      <circle cx="9.4" cy="12.2" r="2.1" />
    </>
  ),
  // Drumstick: meat, then the bone.
  ayam: (
    <>
      <circle cx="9.3" cy="14.7" r="5.1" />
      <path d="M13 11 17 7" />
      <path d="M15.6 5.2a2.2 2.2 0 1 1 3.2 3.2 2.2 2.2 0 1 1-3.2-3.2Z" />
    </>
  ),
  // Bottle, with the level marked.
  minyak: (
    <>
      <path d="M10 2.8h4v3.1l2.1 2.2v11a2.1 2.1 0 0 1-2.1 2.1H10a2.1 2.1 0 0 1-2.1-2.1v-11L10 5.9Z" />
      <path d="M7.9 14.3h8.2" />
    </>
  ),
  // Cube, drawn isometrically.
  gula: (
    <>
      <path d="M12 3.4 19.2 7.6v8.8L12 20.6 4.8 16.4V7.6Z" />
      <path d="m4.8 7.6 7.2 4.2 7.2-4.2" />
      <path d="M12 11.8v8.8" />
    </>
  ),
  fallback: (
    <>
      <circle cx="12" cy="12" r="8.4" />
      <path d="M12 7.8v8.4" />
    </>
  ),
};

const PREFIXES: [string, string][] = [
  ["beras", "beras"],
  ["cabai", "cabai"],
  ["bawang", "bawang"],
  ["telur", "telur"],
  ["daging-sapi", "sapi"],
  ["daging-ayam", "ayam"],
  ["minyak", "minyak"],
  ["gula", "gula"],
];

export default function CommodityIcon({
  slug,
  className = "h-5 w-5",
}: {
  slug: string;
  className?: string;
}) {
  const key = PREFIXES.find(([prefix]) => slug.startsWith(prefix))?.[1] ?? "fallback";

  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {ICONS[key]}
    </svg>
  );
}
