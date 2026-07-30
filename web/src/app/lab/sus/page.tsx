"use client";

/**
 * SUS collection form (§7.6).
 *
 * Interviewer-administered: RLS grants INSERT on `sus_responses` to
 * `authenticated` only, so a team member is signed in and sits with the
 * respondent. That is deliberate rather than a limitation worked around — an
 * open endpoint collecting research responses from anyone with the URL would
 * make the sample impossible to characterise, and n is small enough that every
 * response should be traceable to a session that actually happened.
 *
 * The score is never computed here. `sus_responses.sus_score` is a GENERATED
 * column, so the form, the analysis and the paper cannot disagree about the
 * formula.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { supabase } from "@/lib/supabase";
import { SUS_COPY, SUS_ITEMS, SUS_SCALE } from "@/content/sus-id";
import SignIn from "../SignIn";
import { MUTED } from "@/lib/ui";

type Answers = Record<number, number | undefined>;

export default function SusPage() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);

  const [answers, setAnswers] = useState<Answers>({});
  const [respondentCode, setRespondentCode] = useState("");
  const [businessType, setBusinessType] = useState("");
  const [city, setCity] = useState("");
  const [feedback, setFeedback] = useState("");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setChecking(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, next) => setSession(next));
    return () => sub.subscription.unsubscribe();
  }, []);

  const answered = SUS_ITEMS.every((item) => answers[item.number] !== undefined);
  const canSubmit = answered && respondentCode.trim().length > 0 && !saving;

  const reset = useCallback(() => {
    setAnswers({});
    setRespondentCode("");
    setBusinessType("");
    setCity("");
    setFeedback("");
    setDone(false);
    setError(null);
  }, []);

  async function submit() {
    if (!canSubmit) return;
    setSaving(true);
    setError(null);

    const payload: Record<string, unknown> = {
      respondent_code: respondentCode.trim(),
      business_type: businessType.trim() || null,
      city: city.trim() || null,
      open_feedback: feedback.trim() || null,
    };
    for (const item of SUS_ITEMS) payload[`q${item.number}`] = answers[item.number];

    const { error: insertError } = await supabase.from("sus_responses").insert(payload);
    if (insertError) {
      setError(
        insertError.code === "23505"
          ? "Kode responden ini sudah pernah dipakai. Gunakan kode lain."
          : insertError.message,
      );
      setSaving(false);
      return;
    }
    setSaving(false);
    setDone(true);
  }

  if (checking) {
    return <main className="p-6 text-sm">Memuat…</main>;
  }
  if (!session) {
    return <SignIn />;
  }
  if (done) {
    return (
      <main className="mx-auto flex min-h-dvh max-w-md flex-col justify-center gap-4 px-6 text-center">
        <p className="text-lg font-semibold">{SUS_COPY.thanks}</p>
        <button
          type="button"
          onClick={reset}
          className="rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white dark:bg-neutral-100 dark:text-neutral-900"
        >
          {SUS_COPY.another}
        </button>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col gap-6 px-4 py-8 sm:px-6">
      <header>
        <Link href="/lab" className={`text-sm ${MUTED} underline underline-offset-2`}>
          &larr; Kembali ke pelabelan
        </Link>
        <h1 className="mt-3 text-lg font-semibold tracking-tight">{SUS_COPY.title}</h1>
        <p className={`mt-2 text-sm ${MUTED}`}>{SUS_COPY.intro}</p>
      </header>

      <section className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">{SUS_COPY.respondentCode}</span>
          <input
            value={respondentCode}
            onChange={(e) => setRespondentCode(e.target.value)}
            placeholder="R01"
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">{SUS_COPY.businessType}</span>
          <input
            value={businessType}
            onChange={(e) => setBusinessType(e.target.value)}
            placeholder="warung makan"
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">{SUS_COPY.city}</span>
          <input
            value={city}
            onChange={(e) => setCity(e.target.value)}
            placeholder="Yogyakarta"
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>
      </section>
      <p className={`-mt-4 text-xs ${MUTED}`}>{SUS_COPY.respondentCodeHint}</p>

      <p className={`text-xs ${MUTED}`}>{SUS_COPY.scaleHint}</p>

      <ol className="flex flex-col gap-5">
        {SUS_ITEMS.map((item) => (
          <li key={item.number} className="flex flex-col gap-2">
            <p className="text-sm">
              <span className={`mr-2 font-mono text-xs ${MUTED}`}>{item.number}.</span>
              {item.text}
            </p>
            <div className="flex items-end gap-1">
              {SUS_SCALE.map((step) => {
                const selected = answers[item.number] === step.value;
                return (
                  <button
                    key={step.value}
                    type="button"
                    aria-pressed={selected}
                    aria-label={`${item.number}: ${step.value}`}
                    onClick={() =>
                      setAnswers((current) => ({ ...current, [item.number]: step.value }))
                    }
                    className={`flex-1 rounded-md border px-2 py-3 text-sm transition ${
                      selected
                        ? "border-neutral-900 bg-neutral-900 text-white dark:border-neutral-100 dark:bg-neutral-100 dark:text-neutral-900"
                        : "border-neutral-300 hover:border-neutral-500 dark:border-neutral-700"
                    }`}
                  >
                    <span className="block font-medium">{step.value}</span>
                    {step.label && (
                      <span className="mt-1 block text-[10px] leading-tight opacity-70">
                        {step.label}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </li>
        ))}
      </ol>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">{SUS_COPY.openFeedback}</span>
        <textarea
          rows={3}
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          className="rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-900"
        />
        <span className={`text-xs ${MUTED}`}>{SUS_COPY.openFeedbackHint}</span>
      </label>

      {error && (
        <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {error}
        </p>
      )}
      {!answered && (
        <p className={`text-sm ${MUTED}`}>{SUS_COPY.incomplete}</p>
      )}

      <button
        type="button"
        onClick={() => void submit()}
        disabled={!canSubmit}
        className="rounded-md bg-neutral-900 px-3 py-3 text-sm font-medium text-white disabled:opacity-40 dark:bg-neutral-100 dark:text-neutral-900"
      >
        {saving ? SUS_COPY.submitting : SUS_COPY.submit}
      </button>
    </main>
  );
}
