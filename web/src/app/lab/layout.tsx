import type { Metadata } from "next";

/**
 * `/lab` is the team's research console, not part of the product.
 *
 * `noindex, nofollow` keeps it out of search results. That is hygiene, not
 * security — the actual protection is RLS, which returns nothing to anyone
 * without a registered annotator session (verified by `siap lab-check`). But an
 * indexed labelling queue invites strangers at the sign-in form, and a
 * ground-truth task has no business being discoverable.
 */
export const metadata: Metadata = {
  title: "Lab — SIAP-PANGAN",
  description: "Konsol penelitian internal. Khusus anggota tim.",
  robots: { index: false, follow: false },
};

export default function LabLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
