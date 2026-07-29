/**
 * Data access for the /lab labelling console.
 *
 * Everything here goes through `lab_queue` / `lab_progress`, the SECURITY
 * DEFINER functions added in 0007_lab.sql. That is not indirection for its own
 * sake: `gt_labels` grants INSERT and no SELECT, so an annotator physically
 * cannot read the other annotator's judgements through this API, and the
 * functions scope every read to the caller's own code derived from auth.uid().
 *
 * `gt_candidates` is never queried directly. The queue reads the stratum-blind
 * `gt_labeling_queue` view, so nothing in this file can leak which stratum a
 * candidate was drawn from.
 */

import { supabase } from "./supabase";
import type { Candidate, Label, Progress } from "./types";

export async function fetchQueue(batchSize = 20): Promise<Candidate[]> {
  const { data, error } = await supabase.rpc("lab_queue", { batch_size: batchSize });
  if (error) throw new Error(error.message);
  return (data ?? []) as Candidate[];
}

export async function fetchProgress(): Promise<Progress | null> {
  const { data, error } = await supabase.rpc("lab_progress");
  if (error) throw new Error(error.message);
  const rows = (data ?? []) as Progress[];
  return rows.length ? rows[0] : null;
}

export type LabelSubmission = {
  candidateId: number;
  annotatorCode: string;
  label: Label;
  evidenceUrl: string | null;
  evidenceNote: string | null;
};

export async function submitLabel(submission: LabelSubmission): Promise<void> {
  const { error } = await supabase.from("gt_labels").insert({
    candidate_id: submission.candidateId,
    annotator_code: submission.annotatorCode,
    label: submission.label,
    evidence_url: submission.evidenceUrl,
    evidence_note: submission.evidenceNote,
  });

  if (!error) return;

  // 23505 is the UNIQUE (candidate_id, annotator_code) violation: this row was
  // already labelled, most likely in another tab. Surfacing it as a plain
  // message beats a raw Postgres error, and re-labelling is refused rather than
  // overwritten — a label that can be revised silently is not an independent
  // judgement.
  if (error.code === "23505") {
    throw new Error("Kandidat ini sudah pernah kamu labeli. Lanjut ke berikutnya.");
  }
  // 42501 / RLS denial: the signed-in user has no lab_annotators row, or tried
  // to write under a code that is not theirs.
  if (error.code === "42501") {
    throw new Error(
      "Akun ini belum terdaftar sebagai annotator, jadi label tidak bisa disimpan. " +
        "Hubungi koordinator tim.",
    );
  }
  throw new Error(error.message);
}
