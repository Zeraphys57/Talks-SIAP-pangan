// M0 placeholder.
//
// This page exists to prove the app builds and serves. It is NOT the dashboard —
// that is built in M8, after docs/design.md sets the direction.
//
// It shows no prices, because there are none yet. Rendering invented numbers to
// make a screenshot look finished is the one thing this project must never do.

export default function Home() {
  return (
    <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-6 px-6 py-16">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">SIAP-PANGAN</h1>
        <p className="mt-1 text-sm text-neutral-500">Sistem Analitik Harga Pangan</p>
      </div>

      <div className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <p className="text-sm font-medium">Belum ada data harga</p>
        <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
          Pengumpulan data dari portal resmi belum dimulai, jadi belum ada angka yang bisa
          ditampilkan di sini.
        </p>
      </div>

      <p className="text-xs text-neutral-500">
        Tim RGB &middot; TALKS Season 2 &middot; Universitas Atma Jaya Yogyakarta
      </p>
    </main>
  );
}
