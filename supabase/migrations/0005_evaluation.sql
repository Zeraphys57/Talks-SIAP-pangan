-- 0005_evaluation.sql
-- Ground truth, agreement, metrics and usability.
-- This is the part that makes the project a research contribution rather than
-- a demo, so the blinding and stratification constraints are enforced in the
-- schema rather than left to UI discipline.

-- ---------------------------------------------------------------------------
-- gt_candidates: the stratified pool shown to annotators.
--
-- Stratum A (rule_flagged)   dates where |z| > 1.5 OR |d7d| > 7% — deliberately
--                            more permissive than the detection thresholds.
-- Stratum B (random_control) random non-flagged dates, ~30% of pool size.
--
-- Stratum B is what makes RECALL computable. If annotators only ever saw dates
-- the model flagged, there would be no way to observe a missed event.
-- ---------------------------------------------------------------------------
create table if not exists public.gt_candidates (
    id               bigint generated always as identity primary key,
    commodity_id     bigint      not null references public.commodities (id),
    region_id        bigint      not null references public.regions (id),
    obs_date         date        not null,

    sampling_stratum text        not null,

    -- Deterministic shuffle position, drawn from the configured seed. The
    -- labeling queue orders by this so the two strata are interleaved and the
    -- stratum cannot be inferred from position.
    shuffle_key      double precision not null,

    -- Price context shown to the annotator: the surrounding series window.
    -- Must NOT contain model output, or the label stops being independent of
    -- the thing it is meant to evaluate.
    context          jsonb       not null default '{}'::jsonb,

    generated_by_run bigint      references public.analysis_runs (id),
    created_at       timestamptz not null default now(),

    constraint gt_candidates_stratum_known
        check (sampling_stratum in ('rule_flagged', 'random_control')),
    constraint gt_candidates_unique
        unique (commodity_id, region_id, obs_date)
);

create index if not exists gt_candidates_queue_idx
    on public.gt_candidates (shuffle_key);

comment on column public.gt_candidates.context is
    'Annotator-visible price context only. Never includes anomaly scores or alert levels — that would leak the prediction into its own ground truth.';

-- Blind labeling queue: the same rows with sampling_stratum removed.
-- The /lab labeling UI reads THIS, never gt_candidates directly.
create or replace view public.gt_labeling_queue as
    select id, commodity_id, region_id, obs_date, context, shuffle_key
      from public.gt_candidates
     order by shuffle_key;

comment on view public.gt_labeling_queue is
    'Stratum-blind projection of gt_candidates. The labeling UI must query this view so annotators cannot tell which stratum a candidate came from.';

-- ---------------------------------------------------------------------------
-- gt_labels: one independent judgement per annotator per candidate.
-- Annotators work blind to each other; the UNIQUE key is what makes Cohen's
-- kappa well defined over the paired labels.
-- ---------------------------------------------------------------------------
create table if not exists public.gt_labels (
    id            bigint generated always as identity primary key,
    candidate_id  bigint      not null references public.gt_candidates (id) on delete cascade,
    annotator_code text       not null,
    label         text        not null,

    evidence_url  text,
    evidence_note text,
    labeled_at    timestamptz not null default now(),

    constraint gt_labels_label_known
        check (label in ('anomali', 'normal', 'ragu')),
    constraint gt_labels_unique
        unique (candidate_id, annotator_code)
);

create index if not exists gt_labels_annotator_idx
    on public.gt_labels (annotator_code);

comment on column public.gt_labels.annotator_code is
    'Pseudonymous annotator identifier (e.g. A1, A2). Two independent annotators, blind to each other.';
comment on column public.gt_labels.evidence_url is
    'BPS release, news report or government announcement supporting the judgement. Required for anomali labels by UI validation.';

-- ---------------------------------------------------------------------------
-- gt_events: adjudicated final truth. Disagreements and `ragu` labels are
-- resolved by a third adjudicator; the survivors become events with an extent,
-- because the operational definition requires persistence for >= 2 days.
-- ---------------------------------------------------------------------------
create table if not exists public.gt_events (
    id               bigint generated always as identity primary key,
    commodity_id     bigint      not null references public.commodities (id),
    region_id        bigint      not null references public.regions (id),
    start_date       date        not null,
    end_date         date        not null,

    cause_category   text,
    agreed_by        text[]      not null default '{}',
    adjudicator_note text,
    created_at       timestamptz not null default now(),

    constraint gt_events_range_ordered check (end_date >= start_date),
    constraint gt_events_cause_known
        check (cause_category is null or cause_category in (
            'supply_disruption', 'seasonal_demand', 'policy',
            'unexplained_corroborated', 'other'))
);

create index if not exists gt_events_series_idx
    on public.gt_events (commodity_id, region_id, start_date);

comment on table public.gt_events is
    'Adjudicated ground truth. Detections are matched against these with a +/- 3 day tolerance window.';

-- ---------------------------------------------------------------------------
-- evaluation_results: precision / recall / F1 per ablation arm.
-- Four arms are required: zscore_only, iforest_only, union, fusion.
-- The fusion arm must beat the baselines, or the result is reported as it is.
-- ---------------------------------------------------------------------------
create table if not exists public.evaluation_results (
    id             bigint generated always as identity primary key,
    run_id         bigint  not null references public.analysis_runs (id) on delete cascade,
    method         text    not null,
    tolerance_days integer not null default 3,

    tp             integer not null,
    fp             integer not null,
    fn             integer not null,
    precision      numeric(8,6),
    recall         numeric(8,6),
    f1             numeric(8,6),

    split          text    not null default 'test',
    notes          text,

    constraint evaluation_results_method_known
        check (method in ('zscore_only', 'iforest_only', 'union', 'fusion')),
    constraint evaluation_results_counts_nonneg
        check (tp >= 0 and fp >= 0 and fn >= 0),
    constraint evaluation_results_split_known
        check (split in ('dev', 'test')),
    constraint evaluation_results_unique
        unique (run_id, method, tolerance_days, split)
);

comment on column public.evaluation_results.split is
    'Thresholds and weights are tuned on dev only. Reporting a number tuned against the test labels is leakage; the split is recorded so that cannot be quietly skipped.';

-- ---------------------------------------------------------------------------
-- sus_responses: standard 10-item System Usability Scale, Indonesian wording.
-- sus_score is a GENERATED column so the scoring formula cannot drift between
-- the form, the analysis and the paper.
-- ---------------------------------------------------------------------------
create table if not exists public.sus_responses (
    id              bigint generated always as identity primary key,
    respondent_code text        not null unique,
    business_type   text,
    city            text,

    q1  smallint, q2  smallint, q3  smallint, q4  smallint, q5  smallint,
    q6  smallint, q7  smallint, q8  smallint, q9  smallint, q10 smallint,

    -- (sum(odd - 1) + sum(5 - even)) * 2.5
    sus_score numeric(5,2) generated always as (
        ((q1 - 1) + (q3 - 1) + (q5 - 1) + (q7 - 1) + (q9 - 1)
       + (5 - q2) + (5 - q4) + (5 - q6) + (5 - q8) + (5 - q10)) * 2.5
    ) stored,

    open_feedback text,
    collected_at  timestamptz not null default now(),

    constraint sus_q1_range  check (q1  between 1 and 5),
    constraint sus_q2_range  check (q2  between 1 and 5),
    constraint sus_q3_range  check (q3  between 1 and 5),
    constraint sus_q4_range  check (q4  between 1 and 5),
    constraint sus_q5_range  check (q5  between 1 and 5),
    constraint sus_q6_range  check (q6  between 1 and 5),
    constraint sus_q7_range  check (q7  between 1 and 5),
    constraint sus_q8_range  check (q8  between 1 and 5),
    constraint sus_q9_range  check (q9  between 1 and 5),
    constraint sus_q10_range check (q10 between 1 and 5)
);

comment on column public.sus_responses.sus_score is
    'Generated, not supplied: (sum(odd-1) + sum(5-even)) * 2.5. NULL when any item is unanswered.';
comment on column public.sus_responses.respondent_code is
    'Pseudonymous code. No personally identifying information is stored for UMKM respondents.';
