import type { Metadata, Viewport } from "next";
import "./globals.css";

// Typography is deliberately left as the system stack for now. The display /
// body / mono pairing is a design decision that belongs in docs/design.md and
// is made in M8 — picking a webfont here would prejudge it, and would add a
// build-time network fetch for no benefit.

export const metadata: Metadata = {
  title: "SIAP-PANGAN",
  description:
    "Pantau harga bahan pangan dari sumber resmi. Tahu bahan mana yang sedang naik tidak wajar.",
};

// Mobile-first: a warung owner opens this on a phone, one-handed.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id">
      <body className="antialiased">{children}</body>
    </html>
  );
}
