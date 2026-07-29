/**
 * System Usability Scale, Indonesian wording (§7.6).
 *
 * The standard 10 items, translated for someone who runs a warung rather than
 * someone who evaluates software. "Cumbersome" becomes "merepotkan", not a
 * literal rendering nobody says out loud.
 *
 * ### The alternation is load-bearing
 *
 * SUS alternates positive (odd) and negative (even) items on purpose, and the
 * scoring formula depends on it:
 *
 *     score = (sum(odd - 1) + sum(5 - even)) * 2.5
 *
 * That formula lives in the database as a GENERATED column
 * (`sus_responses.sus_score`), so it cannot drift between this form, the
 * analysis and the paper. If an item's polarity were changed here without
 * changing the column, every reported score would be quietly wrong and nothing
 * would fail. `tone` is therefore recorded per item and asserted against its
 * position, so a mistranslation that flips the meaning breaks the build rather
 * than the results.
 *
 * Item text is not renumbered or reordered. A SUS score is only comparable to
 * the published literature if the instrument is the instrument.
 */

export type SusTone = "positive" | "negative";

export type SusItem = {
  /** 1-based, matching sus_responses.q1 .. q10. */
  number: number;
  text: string;
  tone: SusTone;
};

export const SUS_ITEMS: SusItem[] = [
  { number: 1, text: "Saya kira saya akan sering memakai aplikasi ini.", tone: "positive" },
  {
    number: 2,
    text: "Aplikasi ini terasa rumit, padahal menurut saya tidak perlu serumit itu.",
    tone: "negative",
  },
  { number: 3, text: "Aplikasi ini mudah dipakai.", tone: "positive" },
  {
    number: 4,
    text: "Saya rasa saya perlu dibantu orang yang mengerti teknologi untuk bisa memakai aplikasi ini.",
    tone: "negative",
  },
  {
    number: 5,
    text: "Bagian-bagian di aplikasi ini terasa nyambung satu sama lain.",
    tone: "positive",
  },
  {
    number: 6,
    text: "Menurut saya terlalu banyak hal yang tidak konsisten di aplikasi ini.",
    tone: "negative",
  },
  {
    number: 7,
    text: "Saya rasa kebanyakan orang akan cepat bisa memakai aplikasi ini.",
    tone: "positive",
  },
  { number: 8, text: "Aplikasi ini terasa merepotkan waktu dipakai.", tone: "negative" },
  { number: 9, text: "Saya merasa yakin waktu memakai aplikasi ini.", tone: "positive" },
  {
    number: 10,
    text: "Saya harus belajar banyak dulu sebelum bisa memakai aplikasi ini.",
    tone: "negative",
  },
];

/** 1..5, labelled at both ends only — the standard SUS presentation. */
export const SUS_SCALE = [
  { value: 1, label: "Sangat tidak setuju" },
  { value: 2, label: "" },
  { value: 3, label: "" },
  { value: 4, label: "" },
  { value: 5, label: "Sangat setuju" },
] as const;

export const SUS_COPY = {
  title: "Penilaian Kemudahan Pemakaian",
  intro:
    "Sepuluh pertanyaan singkat tentang aplikasi ini. Tidak ada jawaban benar atau salah — " +
    "jawab sesuai yang Bapak/Ibu rasakan saja. Nama tidak dicatat.",
  scaleHint: "1 = sangat tidak setuju, 5 = sangat setuju",
  businessType: "Jenis usaha",
  city: "Kota / kabupaten",
  respondentCode: "Kode responden",
  respondentCodeHint:
    "Diisi pewawancara. Kode saja, bukan nama — data ini dipakai untuk penelitian.",
  openFeedback: "Ada yang ingin ditambahkan?",
  openFeedbackHint: "Boleh dikosongkan.",
  submit: "Kirim",
  submitting: "Mengirim…",
  incomplete: "Masih ada pertanyaan yang belum dijawab.",
  thanks: "Terima kasih. Jawaban sudah tersimpan.",
  another: "Isi untuk responden berikutnya",
} as const;

/**
 * The invariant the database's scoring formula assumes.
 *
 * Called at module load so a bad edit fails immediately and visibly, rather
 * than producing plausible-looking scores that are wrong by a fixed amount.
 */
function assertAlternation(items: SusItem[]): void {
  if (items.length !== 10) {
    throw new Error(`SUS is a 10-item instrument; found ${items.length}`);
  }
  items.forEach((item, index) => {
    const expectedNumber = index + 1;
    const expectedTone: SusTone = expectedNumber % 2 === 1 ? "positive" : "negative";
    if (item.number !== expectedNumber) {
      throw new Error(`SUS item at position ${expectedNumber} is numbered ${item.number}`);
    }
    if (item.tone !== expectedTone) {
      throw new Error(
        `SUS item ${expectedNumber} is marked ${item.tone} but the scoring formula in ` +
          `sus_responses.sus_score treats it as ${expectedTone}. Fix the wording, not the tone.`,
      );
    }
  });
}

assertAlternation(SUS_ITEMS);
