-- 0004_analysis.sql
-- Analysis runs and every artefact they produce.
--
-- Determinism contract: nothing below exists without a parent analysis_runs row
-- recording the git SHA, the RNG seed, the full parameter set and the resolved
-- library versions. Any figure in the paper can therefore be traced to the exact
-- code and configuration that produced it.

-- ---------------------------------------------------------------------------
-- analysis_runs
-- ---------------------------------------------------------------------------
create table if not exists public.analysis_runs (
    id           bigint generated always as identity primary key,
    run_type     text        not null,
    started_at   timestamptz not null default now(),
    finished_at  timestamptz,
    status       text        not null default 'running',

    git_sha      text,
    seed         integer,
    params       jsonb       not null default '{}'::jsonb,
    lib_versions jsonb       not null default '{}'::jsonb,
    notes        text,

    constraint analysis_runs_status_known
        check (status in ('running', 'success', 'failed', 'partial')),
    constraint analysis_runs_finished_after_started
        check (finished_at is null or finished_at >= started_at)
);

create index if not exists analysis_runs_type_started_idx
    on public.analysis_runs (run_type, started_at desc);

comment on table public.analysis_runs is
    'One row per analysis execution. Parent of every score, model, component and alert.';
comment on column public.analysis_runs.status is
    'partial means the run completed but skipped work (e.g. STL skipped for commodities below the 104-week coverage guard); see notes.';
comment on column public.analysis_runs.notes is
    'Human-readable record of skips and degradations, e.g. which commodities lacked coverage and why.';

-- ---------------------------------------------------------------------------
-- anomaly_scores: Z-Score and Isolation Forest output, side by side.
--
-- norm_score is nullable on purpose. The Z-Score module requires >= 20 valid
-- observations in its trailing 30-day window; below that it emits NULL rather
-- than a number computed from too little history.
-- ---------------------------------------------------------------------------
create table if not exists public.anomaly_scores (
    id             bigint generated always as identity primary key,
    run_id         bigint  not null references public.analysis_runs (id) on delete cascade,
    commodity_id   bigint  not null references public.commodities (id),
    region_id      bigint  not null references public.regions (id),
    obs_date       date    not null,

    method         text    not null,
    raw_score      numeric(14,6),
    norm_score     numeric(8,6),
    is_flagged     boolean,
    threshold_used numeric(10,4),

    constraint anomaly_scores_method_known
        check (method in ('zscore', 'iforest')),
    constraint anomaly_scores_norm_range
        check (norm_score is null or (norm_score >= 0 and norm_score <= 1)),
    constraint anomaly_scores_unique
        unique (run_id, commodity_id, region_id, obs_date, method)
);

create index if not exists anomaly_scores_series_idx
    on public.anomaly_scores (run_id, commodity_id, region_id, obs_date);
create index if not exists anomaly_scores_flagged_idx
    on public.anomaly_scores (run_id, method, obs_date)
    where is_flagged = true;

comment on column public.anomaly_scores.raw_score is
    'zscore: the signed z value. iforest: sklearn score_samples output (lower = more anomalous).';
comment on column public.anomaly_scores.norm_score is
    'Comparable 0-1 score. zscore: clip(|z|/4, 0, 1). iforest: percentile rank within that commodity''s own history. NULL when the window guard is not met.';

-- ---------------------------------------------------------------------------
-- cluster_models: one K-Means model per run, with the whole k-search retained.
--
-- The full k -> (inertia, silhouette) search is stored, not just the winner:
-- the elbow/silhouette curve is a required paper figure, and storing only the
-- selected k would make it unreproducible without a re-run.
-- ---------------------------------------------------------------------------
create table if not exists public.cluster_models (
    id             bigint generated always as identity primary key,
    run_id         bigint  not null references public.analysis_runs (id) on delete cascade,

    k_selected     integer not null,
    k_search       jsonb   not null,
    silhouette_avg numeric(8,6),
    centroids      jsonb   not null,
    scaler_params  jsonb   not null,
    zone_mapping   jsonb   not null,

    n_samples      integer,
    feature_names  text[]  not null default '{}',

    constraint cluster_models_k_range check (k_selected between 2 and 8),
    constraint cluster_models_one_per_run unique (run_id)
);

comment on column public.cluster_models.k_search is
    'Array of {k, inertia, silhouette} for every k in [2..8]. Source of the paper''s k-selection figure.';
comment on column public.cluster_models.zone_mapping is
    'Post-hoc cluster_id -> zone map, derived by ranking centroids on 0.5*z(volatility) + 0.5*z(cum_change). k is NOT forced to 3; when k > 3 the middle clusters merge into kuning.';
comment on column public.cluster_models.scaler_params is
    'StandardScaler mean_ and scale_ per feature, so the fitted transform can be reapplied without refitting.';

-- ---------------------------------------------------------------------------
-- cluster_assignments: one row per clustered cell.
--
-- The unit of observation is commodity x region x MONTH, not commodity.
-- Twelve commodities alone give twelve points, on which a silhouette score
-- searching k up to 8 is noise. See docs/methods.md.
-- ---------------------------------------------------------------------------
create table if not exists public.cluster_assignments (
    id                bigint generated always as identity primary key,
    run_id            bigint  not null references public.analysis_runs (id) on delete cascade,
    commodity_id      bigint  not null references public.commodities (id),
    region_id         bigint  not null references public.regions (id),
    period_month      date    not null,

    feat_volatility   numeric(12,8),
    feat_cum_change   numeric(12,8),
    cluster_id        integer not null,
    zone              text    not null,
    silhouette_sample numeric(8,6),

    constraint cluster_assignments_zone_known
        check (zone in ('merah', 'kuning', 'hijau')),
    constraint cluster_assignments_month_is_first
        check (extract(day from period_month) = 1),
    constraint cluster_assignments_unique
        unique (run_id, commodity_id, region_id, period_month)
);

create index if not exists cluster_assignments_month_idx
    on public.cluster_assignments (run_id, period_month desc);

comment on column public.cluster_assignments.period_month is
    'First day of the clustered month. The CHECK enforces normalization to day 1.';
comment on column public.cluster_assignments.feat_volatility is
    'Standard deviation of daily log returns within the month.';
comment on column public.cluster_assignments.feat_cum_change is
    'Cumulative within-month change, (last - first) / first.';

-- ---------------------------------------------------------------------------
-- seasonal_components: STL output at weekly resolution.
--
-- Hard dependency on the M1 three-year backfill. STL needs >= 2 full seasonal
-- cycles; at period=52 the coverage guard is >= 104 weeks. Below that the
-- commodity is skipped and the reason recorded in analysis_runs.notes — never
-- decomposed anyway to produce a plausible-looking curve.
-- ---------------------------------------------------------------------------
create table if not exists public.seasonal_components (
    id            bigint generated always as identity primary key,
    run_id        bigint not null references public.analysis_runs (id) on delete cascade,
    commodity_id  bigint not null references public.commodities (id),
    region_id     bigint not null references public.regions (id),
    period_start  date   not null,

    observed      numeric(14,4),
    trend         numeric(14,4),
    seasonal      numeric(14,4),
    resid         numeric(14,4),
    resample_freq text   not null default 'W',

    constraint seasonal_components_unique
        unique (run_id, commodity_id, region_id, period_start)
);

create index if not exists seasonal_components_series_idx
    on public.seasonal_components (run_id, commodity_id, region_id, period_start);

comment on table public.seasonal_components is
    'Weekly STL decomposition. Derived output for the dashboard is the top-decile seasonal weeks per commodity ("periode rawan naik").';

-- ---------------------------------------------------------------------------
-- alerts: the fused, user-facing output.
--
-- `components` carries A, M, D, C, both_flagged, n_sources and any downgrade
-- reason. An alert a mentor cannot decompose by hand is an alert that cannot be
-- defended, so the breakdown is stored, not recomputed at render time.
-- ---------------------------------------------------------------------------
create table if not exists public.alerts (
    id                bigint  generated always as identity primary key,
    run_id            bigint  not null references public.analysis_runs (id) on delete cascade,
    commodity_id      bigint  not null references public.commodities (id),
    region_id         bigint  not null references public.regions (id),
    obs_date          date    not null,

    fusion_score      numeric(8,6) not null,
    level             text    not null,
    components        jsonb   not null,
    corroboration     numeric(8,6),
    recommendation_id text,

    created_at        timestamptz not null default now(),

    constraint alerts_level_known
        check (level in ('merah', 'kuning', 'hijau')),
    constraint alerts_score_range
        check (fusion_score >= 0 and fusion_score <= 1),
    constraint alerts_unique
        unique (run_id, commodity_id, region_id, obs_date)
);

create index if not exists alerts_board_idx
    on public.alerts (run_id, obs_date desc, level);

comment on column public.alerts.components is
    'Full breakdown: A, M, D, C, both_flagged, n_sources_flagging, n_sources_reporting, and reason when a downgrade applied.';
comment on column public.alerts.corroboration is
    'The C term: n_sources_flagging / n_sources_reporting. merah additionally requires C >= 0.5; single-source coverage caps at kuning.';
comment on column public.alerts.recommendation_id is
    'Key into the Bahasa Indonesia recommendation copy. Phrased as an observation plus an option, never a command.';
