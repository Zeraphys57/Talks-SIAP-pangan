/**
 * Bahasa Indonesia copy for the public dashboard.
 *
 * Centralised because two specific wordings are easy to get wrong and were
 * identified during M6 (see `docs/design.md`):
 *
 * 1. `kuning` means the price is **unstable**, not that it is rising. It can be
 *    yellow while falling. Never write "harga naik" for a level.
 * 2. `merah` fires on |pct_change_7d|, so a *crash* scores like a spike. For a
 *    warung owner those are opposite situations, so direction is carried by a
 *    separate function and the advice follows the direction, not the level.
 *
 * Register: plain, second person, no jargon. "Tidak stabil", not "volatilitas
 * tinggi". A warung owner should not need the glossary this system was built
 * from.
 */

import type { Level } from "@/lib/dashboard";

export const LEVEL_LABEL: Record<Level, string> = {
  merah: "Perlu perhatian",
  kuning: "Kurang stabil",
  hijau: "Wajar",
};

export const LEVEL_MEANING: Record<Level, string> = {
  merah: "Pergerakan harga jauh di luar kebiasaan komoditas ini.",
  kuning: "Harga bergerak lebih besar dari biasanya, tapi belum ekstrem.",
  hijau: "Tidak ada yang tidak biasa pada harga hari itu.",
};

/** Level marks, chosen so the three are distinguishable without colour. */
export const LEVEL_MARK: Record<Level, string> = {
  merah: "▲▼",
  kuning: "◆",
  hijau: "●",
};

export type Direction = "naik" | "turun" | "datar";

export function direction(pctChange7d: number | null): Direction {
  if (pctChange7d === null || Math.abs(pctChange7d) < 0.01) return "datar";
  return pctChange7d > 0 ? "naik" : "turun";
}

/**
 * The headline sentence for one alert.
 *
 * Direction first, because that is what changes what the reader should do. A
 * level alone ("merah") tells a warung owner to worry without telling them
 * whether to buy now or wait, which is the opposite of useful.
 */
export function alertHeadline(level: Level, pctChange7d: number | null): string {
  const dir = direction(pctChange7d);
  if (level === "hijau") return "Harga bergerak wajar";
  if (dir === "datar") return "Harga bergerak tidak biasa minggu ini";
  return dir === "naik"
    ? "Harga naik tidak biasa minggu ini"
    : "Harga turun tidak biasa minggu ini";
}

/**
 * Recommendations, keyed by `fusion.yaml`'s `recommendation_id` **and** by
 * direction. Phrased as an observation plus an option — never an instruction.
 * The system does not know this person's cash, storage or customers.
 */
export function recommendation(
  recommendationId: string | null,
  pctChange7d: number | null,
): string | null {
  const dir = direction(pctChange7d);
  switch (recommendationId) {
    case "rec_merah_tunda_pembelian":
      if (dir === "turun") {
        return "Harga sedang jauh di bawah kebiasaannya. Kalau bahan ini tahan disimpan, ini bisa jadi waktu yang murah untuk menambah stok.";
      }
      return "Kalau stok masih cukup, pertimbangkan menunda pembelian besar beberapa hari sambil melihat arah harga.";
    case "rec_kuning_pantau":
      return "Belum perlu berubah, tapi ada baiknya dipantau beberapa hari ke depan sebelum belanja banyak.";
    case "rec_hijau_aman":
      return null; // Nothing unusual happened; saying so twice is noise.
    default:
      return null;
  }
}

/** Why an alert was held back from the top level. Plain language, not jargon. */
export const REASON_COPY: Record<string, string> = {
  single_source_reporting:
    "Hari itu hanya satu sumber yang melapor, jadi angkanya belum bisa dibandingkan dengan sumber lain.",
  single_source_coverage:
    "Wilayah ini hanya punya satu sumber data, jadi tidak ada pembanding.",
};

export const ZONE_COPY: Record<string, { label: string; meaning: string }> = {
  merah: {
    label: "Sering bergejolak",
    meaning: "Dibanding komoditas lain, harga bahan ini paling sering berubah tajam.",
  },
  kuning: {
    label: "Cukup bergerak",
    meaning: "Harganya bergerak lumayan, tapi tidak seliar kelompok merah.",
  },
  hijau: {
    label: "Cenderung stabil",
    meaning: "Harganya jarang berubah tajam dari bulan ke bulan.",
  },
};

export const COPY = {
  appName: "SIAP-PANGAN",
  tagline: "Pantau harga bahan pangan dari sumber resmi",

  chooseRegion: "Pilih wilayah",
  regionHint: "Harga berbeda antar daerah. Pilih yang paling dekat dengan pasar Anda.",

  dataFrom: "Data terakhir",
  noData: "Belum ada data untuk wilayah ini",
  noDataHelp:
    "Pengumpulan data untuk wilayah ini belum menghasilkan angka yang bisa ditampilkan. Tidak ada angka yang dikarang untuk mengisi kekosongan ini.",

  todayWithheld:
    "Angka hari ini belum ditampilkan karena sumbernya masih memperbarui data sepanjang hari. Yang ditampilkan adalah hari terakhir yang sudah final.",

  needsAttention: "Perlu diperhatikan",
  normalPrices: "Bergerak wajar",
  allNormal: "Semua bahan bergerak wajar hari itu.",

  sourceCount: (n: number) => (n === 1 ? "1 sumber" : `${n} sumber`),
  vsBaseline: "dibanding rata-rata 30 hari",

  detailTitle: "Rincian harga",
  chartCaption: "Garis putus-putus: rata-rata 30 hari. Area terang: batas ±10%.",
  imputedNote: "Titik kosong berarti harga hari itu diisi perkiraan dari hari sebelum dan sesudahnya, bukan hasil pencatatan.",

  riskyWeeks: "Periode rawan naik",
  riskyWeeksHelp:
    "Minggu-minggu yang secara historis harganya di atas kebiasaan tahunan bahan ini. Ini catatan dari data tahun-tahun lalu, bukan ramalan harga.",
  noRiskyWeeks: "Belum ada pola musiman yang cukup jelas untuk bahan ini.",

  zoneTitle: "Kelompok pergerakan harga",

  sourcesTitle: "Sumber data",
  sourcesHelp:
    "Angka di halaman ini berasal dari portal resmi berikut. Setiap harga bisa ditelusuri kembali ke tanggal dan halaman asalnya.",

  notForecast: "Sistem ini menjelaskan apa yang sudah terjadi pada harga. Sistem ini tidak meramal harga besok.",

  back: "Kembali",
  footer: "Tim RGB · TALKS Season 2 · Universitas Atma Jaya Yogyakarta",
} as const;
