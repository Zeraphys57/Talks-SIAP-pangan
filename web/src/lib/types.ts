/**
 * Shapes returned by the /lab database functions.
 *
 * Kept apart from lab.ts so presentational components can import a type without
 * pulling in the Supabase client — a chart has no business holding a database
 * connection, and importing one would run the key assertions in supabase.ts
 * during render of a component that never queries anything.
 */

export const LABELS = ["anomali", "normal", "ragu"] as const;
export type Label = (typeof LABELS)[number];

export type WindowPoint = {
  date: string;
  price: number | null;
  imputed: boolean;
  sources: number;
};

export type CandidateContext = {
  window: WindowPoint[];
  focus_date: string;
  baseline: {
    days: number;
    n_obs: number;
    min_obs: number;
    /** null when the trailing period is too sparse to average honestly. */
    mean_price: number | null;
  };
  definition_pct: number;
};

export type Candidate = {
  candidate_id: number;
  commodity_slug: string;
  commodity_name: string;
  canonical_unit: string;
  region_slug: string;
  region_name: string;
  obs_date: string;
  context: CandidateContext;
};

export type Progress = {
  annotator_code: string;
  labeled: number;
  pool: number;
};
