"use client";

/**
 * Route-level error boundary.
 *
 * The realistic cause is Supabase being unreachable or slow. Without this, a
 * production build shows "Application error: a server-side exception has
 * occurred", which tells a warung owner nothing and an annotator nothing.
 *
 * It deliberately does **not** fall back to cached or placeholder numbers. An
 * empty screen that says the data could not be loaded is correct; a screen
 * showing stale prices as if they were current is the failure mode this whole
 * project is built to avoid.
 *
 * The digest is shown because it is the only handle a user can quote when
 * reporting the problem — the message itself is withheld by Next in production.
 */

import { useEffect } from "react";
import { COPY } from "@/content/id";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[siap] render failed:", error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-6">
      <h1 className="text-xl font-semibold tracking-tight">Data gagal dimuat</h1>
      <p className="text-sm text-neutral-600 dark:text-neutral-400">
        Sambungan ke penyimpanan data sedang bermasalah, jadi angka tidak bisa ditampilkan
        sekarang. Tidak ada angka lama yang ditampilkan sebagai pengganti.
      </p>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={reset}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white dark:bg-neutral-100 dark:text-neutral-900"
        >
          Coba lagi
        </button>
        {/* Deliberately a plain anchor, not <Link>: client-side navigation
            re-uses the React tree that just threw, whereas a full document load
            resets everything — which is what someone stuck here needs. */}
        {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
        <a
          href="/"
          className="rounded-md border border-neutral-300 px-4 py-2 text-sm font-medium dark:border-neutral-700"
        >
          Halaman utama
        </a>
      </div>
      {error.digest && (
        <p className="text-xs text-neutral-500">
          Kode kesalahan: <span className="font-mono">{error.digest}</span>
        </p>
      )}
      <p className="mt-6 text-xs text-neutral-500">{COPY.footer}</p>
    </main>
  );
}
