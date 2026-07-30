/**
 * 404. Reached by a mistyped URL, or by `notFound()` when a region or commodity
 * slug does not exist.
 *
 * Indonesian, because everyone who sees it is an Indonesian user — Next's
 * default is an English stack-trace-adjacent page that tells a warung owner
 * nothing and tells an annotator nothing either.
 */

import Link from "next/link";
import { COPY } from "@/content/id";
import { MUTED, PAGE } from "@/lib/ui";

export default function NotFound() {
  return (
    <main className={PAGE.message}>
      <h1 className="text-xl font-semibold tracking-tight">Halaman tidak ditemukan</h1>
      <p className={`text-sm ${MUTED}`}>
        Alamat yang dibuka tidak ada. Mungkin salah ketik, atau wilayah/bahan yang dicari memang
        belum ada datanya.
      </p>
      <Link
        href="/"
        className="w-fit rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white dark:bg-neutral-100 dark:text-neutral-900"
      >
        Ke halaman utama
      </Link>
      <p className={`mt-6 text-xs ${MUTED}`}>{COPY.footer}</p>
    </main>
  );
}
