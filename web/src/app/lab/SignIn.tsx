"use client";

/**
 * Sign-in for the labelling console.
 *
 * Email and password against Supabase Auth. There is no sign-up: the annotator
 * set is two named people agreed in the protocol, and their accounts are
 * created by the coordinator (see docs/labelling.md). Anyone who signs in
 * without a `lab_annotators` row can read nothing and write nothing — the
 * definer functions return empty and the INSERT policy denies.
 */

import { useState } from "react";
import { supabase } from "@/lib/supabase";
import { MUTED } from "@/lib/ui";

export default function SignIn() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
    if (authError) {
      setError(
        authError.message === "Invalid login credentials"
          ? "Email atau kata sandi salah."
          : authError.message,
      );
      setBusy(false);
    }
    // On success the auth listener in page.tsx swaps this component out.
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-6 px-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">SIAP-PANGAN &middot; Lab</h1>
        <p className={`mt-1 text-sm ${MUTED}`}>
          Pelabelan ground truth. Khusus anggota tim.
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Email</span>
          <input
            type="email"
            required
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-neutral-300 px-3 py-2 text-base dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Kata sandi</span>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-md border border-neutral-300 px-3 py-2 text-base dark:border-neutral-700 dark:bg-neutral-900"
          />
        </label>

        {error && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {busy ? "Masuk…" : "Masuk"}
        </button>
      </form>

      <p className={`text-xs ${MUTED}`}>
        Belum punya akun? Akun annotator dibuat oleh koordinator tim, bukan lewat pendaftaran
        sendiri.
      </p>
    </main>
  );
}
