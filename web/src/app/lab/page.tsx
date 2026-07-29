"use client";

/**
 * /lab — ground-truth labelling console (§7.1–7.3).
 *
 * Two annotators work through the same 399-candidate pool independently. What
 * this screen shows, and what it deliberately does not, is the whole basis of
 * whether the resulting kappa means anything:
 *
 *   shown      the price window, the trailing 30-day mean, the +/-10% band that
 *              states the operational definition, and whether a day was
 *              interpolated;
 *   not shown  the anomaly score, the alert level, which stratum the candidate
 *              came from, and anything the other annotator has said.
 *
 * The last three are enforced in the database (0005, 0006, 0007), not here.
 * This file could be rewritten carelessly and still not leak them.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "@/lib/supabase";
import { fetchProgress, fetchQueue, submitLabel } from "@/lib/lab";
import { formatLongDate, formatPercent, formatRupiah } from "@/lib/format";
import type { Candidate, Label, Progress } from "@/lib/types";
import PriceWindow from "./PriceWindow";
import SignIn from "./SignIn";

const BATCH = 20;
const REFILL_AT = 4;

const LABEL_COPY: Record<Label, { title: string; hint: string; key: string; tone: string }> = {
  anomali: {
    title: "Tidak wajar",
    hint: "Harga menyimpang jauh dari kebiasaan dan bertahan minimal 2 hari.",
    key: "1",
    tone: "border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200",
  },
  normal: {
    title: "Wajar",
    hint: "Naik-turun biasa, atau pola musiman yang memang sudah sering terjadi.",
    key: "2",
    tone: "border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200",
  },
  ragu: {
    title: "Ragu",
    hint: "Tidak cukup bukti untuk memutuskan. Jangan dipaksakan.",
    key: "3",
    tone: "border-neutral-300 bg-neutral-100 text-neutral-800 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-200",
  },
};

export default function LabPage() {
  const [session, setSession] = useState<Session | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  const [progress, setProgress] = useState<Progress | null>(null);
  const [queue, setQueue] = useState<Candidate[]>([]);
  const [loadingQueue, setLoadingQueue] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);

  const [label, setLabel] = useState<Label | null>(null);
  const [evidenceUrl, setEvidenceUrl] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);

  const loadingRef = useRef(false);

  // --- session ------------------------------------------------------------
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setCheckingSession(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setQueue([]);
      setProgress(null);
      setFatal(null);
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  // --- queue --------------------------------------------------------------
  const refill = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoadingQueue(true);
    try {
      const [batch, prog] = await Promise.all([fetchQueue(BATCH), fetchProgress()]);
      setProgress(prog);
      setQueue((current) => {
        const seen = new Set(current.map((c) => c.candidate_id));
        return [...current, ...batch.filter((c) => !seen.has(c.candidate_id))];
      });
    } catch (error) {
      setFatal(error instanceof Error ? error.message : String(error));
    } finally {
      loadingRef.current = false;
      setLoadingQueue(false);
    }
  }, []);

  useEffect(() => {
    if (session && queue.length <= REFILL_AT && !fatal) void refill();
  }, [session, queue.length, refill, fatal]);

  const candidate = queue[0] ?? null;

  // Reset the form whenever the card changes, so an evidence URL typed for one
  // candidate can never be saved against the next.
  useEffect(() => {
    setLabel(null);
    setEvidenceUrl("");
    setNote("");
    setSubmitError(null);
  }, [candidate?.candidate_id]);

  const needsEvidence = label === "anomali";
  const canSubmit = label !== null && (!needsEvidence || evidenceUrl.trim().length > 0) && !saving;

  const save = useCallback(async () => {
    if (!candidate || !label || !progress || saving) return;
    if (needsEvidence && !evidenceUrl.trim()) return;
    setSaving(true);
    setSubmitError(null);
    try {
      await submitLabel({
        candidateId: candidate.candidate_id,
        annotatorCode: progress.annotator_code,
        label,
        evidenceUrl: evidenceUrl.trim() || null,
        evidenceNote: note.trim() || null,
      });
      setQueue((current) => current.slice(1));
      setProgress((p) => (p ? { ...p, labeled: p.labeled + 1 } : p));
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }, [candidate, label, progress, saving, needsEvidence, evidenceUrl, note]);

  // --- keyboard -----------------------------------------------------------
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
        if (event.key === "Enter" && target.tagName === "INPUT") {
          event.preventDefault();
          void save();
        }
        return;
      }
      if (event.key === "1") setLabel("anomali");
      else if (event.key === "2") setLabel("normal");
      else if (event.key === "3") setLabel("ragu");
      else if (event.key === "Enter") void save();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);

  // --- render -------------------------------------------------------------
  if (checkingSession) {
    return <Centered>Memuat…</Centered>;
  }
  if (!session) {
    return <SignIn />;
  }
  if (fatal) {
    return (
      <Centered>
        <p className="font-medium">Tidak bisa memuat antrean.</p>
        <p className="mt-2 text-sm text-neutral-500">{fatal}</p>
        <SignOut />
      </Centered>
    );
  }
  if (!progress && loadingQueue) {
    return <Centered>Memuat antrean…</Centered>;
  }
  if (!progress) {
    return (
      <Centered>
        <p className="font-medium">Akun ini belum terdaftar sebagai annotator.</p>
        <p className="mt-2 text-sm text-neutral-500">
          Kode annotator diberikan oleh koordinator tim. Sampai kode itu terdaftar, tidak ada
          kandidat yang bisa dilihat maupun dilabeli.
        </p>
        <SignOut />
      </Centered>
    );
  }
  if (!candidate) {
    return (
      <Centered>
        <p className="text-lg font-semibold">Selesai.</p>
        <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-400">
          {progress.labeled} dari {progress.pool} kandidat sudah kamu labeli. Kappa dihitung setelah
          kedua annotator selesai.
        </p>
        <SignOut />
      </Centered>
    );
  }

  const ctx = candidate.context;
  const focusPoint = ctx.window.find((p) => p.date === ctx.focus_date);
  const mean = ctx.baseline.mean_price;
  const deviation =
    mean && focusPoint?.price != null ? focusPoint.price / mean - 1 : null;

  const newsQuery = encodeURIComponent(
    `harga ${candidate.commodity_name} ${candidate.region_name} ${candidate.obs_date.slice(0, 7)}`,
  );

  return (
    <main className="mx-auto flex min-h-dvh max-w-3xl flex-col gap-5 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-sm font-semibold tracking-tight">
            SIAP-PANGAN &middot; Pelabelan ground truth
          </h1>
          <p className="text-xs text-neutral-500">
            Annotator <span className="font-mono">{progress.annotator_code}</span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/lab/sus"
            className="text-xs text-neutral-500 underline underline-offset-2"
          >
            Form SUS
          </Link>
          <div className="text-right">
            <p className="text-sm font-medium tabular-nums">
              {progress.labeled} / {progress.pool}
            </p>
            <div className="mt-1 h-1 w-28 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
              <div
                className="h-full bg-neutral-800 dark:bg-neutral-200"
                style={{ width: `${(progress.labeled / Math.max(1, progress.pool)) * 100}%` }}
              />
            </div>
          </div>
          <SignOut compact />
        </div>
      </header>

      <section className="rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-3 text-sm dark:border-neutral-800 dark:bg-neutral-900/50">
        <p>
          <span className="font-medium">Yang dinilai:</span> apakah harga pada tanggal yang ditandai
          menyimpang lebih dari <strong>10%</strong> dari rata-rata 30 hari sebelumnya (pita kuning
          di grafik) <strong>dan</strong> bertahan minimal <strong>2 hari</strong>.
        </p>
        <button
          type="button"
          onClick={() => setGuideOpen((v) => !v)}
          className="mt-2 text-xs font-medium text-neutral-600 underline underline-offset-2 dark:text-neutral-400"
        >
          {guideOpen ? "Tutup panduan" : "Panduan lengkap"}
        </button>
        {guideOpen && (
          <div className="mt-3 flex flex-col gap-2 border-t border-neutral-200 pt-3 text-xs leading-relaxed text-neutral-600 dark:border-neutral-800 dark:text-neutral-400">
            <p>
              <strong className="text-neutral-900 dark:text-neutral-100">Tidak wajar</strong> —
              keluar dari pita dan bertahan minimal dua hari, dan kamu punya alasan untuk percaya
              itu kejadian nyata di pasar: ada berita, pengumuman pemerintah, rilis BPS, panen
              gagal, hari raya, atau gangguan pasokan. Wajib isi tautan bukti.
            </p>
            <p>
              <strong className="text-neutral-900 dark:text-neutral-100">Wajar</strong> — masih di
              dalam pita, atau keluar sebentar lalu balik lagi, atau pola yang memang berulang tiap
              tahun di komoditas ini.
            </p>
            <p>
              <strong className="text-neutral-900 dark:text-neutral-100">Ragu</strong> — lonjakan
              hanya satu hari lalu hilang, banyak titik kosong (interpolasi) di sekitarnya, atau
              angkanya terlihat seperti salah input dan bukan pergerakan pasar. Pakai ini kalau
              memang tidak yakin; menebak akan merusak angka kesepakatan.
            </p>
            <p className="text-neutral-500">
              Kerjakan sendiri. Jangan mendiskusikan kandidat dengan annotator lain sampai kedua
              daftar selesai — nilai kappa hanya bermakna kalau kedua penilaian independen.
            </p>
          </div>
        )}
      </section>

      <article className="rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">{candidate.commodity_name}</h2>
            <p className="text-sm text-neutral-500">
              {candidate.region_name} &middot; {formatLongDate(candidate.obs_date)}
            </p>
          </div>
          <div className="text-right">
            <p className="text-lg font-semibold tabular-nums">
              {formatRupiah(focusPoint?.price ?? null)}
              <span className="ml-1 text-sm font-normal text-neutral-500">
                /{candidate.canonical_unit}
              </span>
            </p>
            {deviation !== null && (
              <p className="text-sm tabular-nums text-neutral-500">
                {formatPercent(deviation)} dari rata-rata 30 hari
              </p>
            )}
          </div>
        </div>

        {focusPoint?.imputed && (
          <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            Harga pada tanggal ini bukan hasil pengambilan data, melainkan interpolasi dari hari
            sebelum dan sesudahnya. Pertimbangkan ini sebelum menilai.
          </p>
        )}

        <div className="mt-4">
          <PriceWindow context={ctx} />
        </div>
      </article>

      <section className="flex flex-col gap-3">
        <div className="grid gap-2 sm:grid-cols-3">
          {(Object.keys(LABEL_COPY) as Label[]).map((value) => {
            const copy = LABEL_COPY[value];
            const active = label === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => setLabel(value)}
                aria-pressed={active}
                className={`rounded-lg border p-3 text-left transition ${
                  active
                    ? copy.tone
                    : "border-neutral-200 hover:border-neutral-400 dark:border-neutral-800 dark:hover:border-neutral-600"
                }`}
              >
                <span className="flex items-center justify-between text-sm font-medium">
                  {copy.title}
                  <kbd className="rounded border border-current/30 px-1 text-[10px] opacity-60">
                    {copy.key}
                  </kbd>
                </span>
                <span className="mt-1 block text-xs opacity-80">{copy.hint}</span>
              </button>
            );
          })}
        </div>

        <label className="flex flex-col gap-1 text-sm">
          <span className="flex items-center justify-between">
            <span className="font-medium">
              Tautan bukti {needsEvidence && <span className="text-red-600">*</span>}
            </span>
            <a
              href={`https://www.google.com/search?tbm=nws&q=${newsQuery}`}
              target="_blank"
              rel="noreferrer noopener"
              className="text-xs text-neutral-500 underline underline-offset-2"
            >
              cari berita bulan itu &rarr;
            </a>
          </span>
          <input
            type="url"
            inputMode="url"
            placeholder="https://…"
            value={evidenceUrl}
            onChange={(e) => setEvidenceUrl(e.target.value)}
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
          {needsEvidence && (
            <span className="text-xs text-neutral-500">
              Label &ldquo;tidak wajar&rdquo; harus punya bukti dari luar sistem ini. Kalau tidak
              ketemu apa-apa, itu sendiri sebuah temuan — pilih &ldquo;Ragu&rdquo;.
            </span>
          )}
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Catatan singkat</span>
          <input
            type="text"
            maxLength={200}
            placeholder="mis. panen cabai gagal karena hujan berkepanjangan"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>

        {submitError && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
            {submitError}
          </p>
        )}

        <button
          type="button"
          onClick={() => void save()}
          disabled={!canSubmit}
          className="rounded-md bg-neutral-900 px-3 py-3 text-sm font-medium text-white disabled:opacity-40 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {saving ? "Menyimpan…" : "Simpan & lanjut"}
          <span className="ml-2 text-xs opacity-60">Enter</span>
        </button>
        <p className="text-center text-xs text-neutral-500">
          Label yang sudah disimpan tidak bisa diubah. Itu disengaja: penilaian yang bisa
          direvisi diam-diam bukan lagi penilaian independen.
        </p>
      </section>
    </main>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center px-6 text-center">
      {children}
    </main>
  );
}

function SignOut({ compact = false }: { compact?: boolean }) {
  return (
    <button
      type="button"
      onClick={() => void supabase.auth.signOut()}
      className={
        compact
          ? "text-xs text-neutral-500 underline underline-offset-2"
          : "mt-6 text-sm text-neutral-500 underline underline-offset-2"
      }
    >
      Keluar
    </button>
  );
}
