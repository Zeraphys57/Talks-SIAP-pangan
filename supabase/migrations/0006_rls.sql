-- 0006_rls.sql
-- Row Level Security posture.
--
-- Three principals:
--   service_role  the Python engine. Has BYPASSRLS in Supabase; writes everything.
--   anon          the public dashboard. SELECT on presentation tables only.
--   authenticated the team, on /lab. Reads research tables, writes labels and
--                 SUS responses.
--
-- Default-deny is the mechanism: enabling RLS with no matching policy denies
-- access even though Supabase's default privileges have already granted the
-- table to anon and authenticated. Every allowance below is therefore explicit.
--
-- SUSTAINED INVARIANT: SUPABASE_SERVICE_ROLE_KEY must never reach web/. It
-- bypasses every policy in this file.

-- ---------------------------------------------------------------------------
-- Precondition. Every policy below names the `anon` and `authenticated` roles,
-- which Supabase provisions and a plain Postgres does not. Failing here with an
-- explanation beats failing twenty statements later with "role does not exist".
-- ---------------------------------------------------------------------------
do $$
declare
    missing text[];
begin
    select array_agg(r)
      into missing
      from unnest(array['anon', 'authenticated', 'service_role']) as r
     where not exists (select 1 from pg_roles where rolname = r);

    if missing is not null then
        raise exception
            'Missing role(s): %. These migrations target a Supabase project, '
            'which provisions anon / authenticated / service_role. Point '
            'DATABASE_URL at the Supabase database, or create the roles first.',
            array_to_string(missing, ', ');
    end if;
end
$$;

-- ---------------------------------------------------------------------------
-- Enable RLS everywhere. No exceptions, including reference tables.
-- ---------------------------------------------------------------------------
alter table public.commodities         enable row level security;
alter table public.regions             enable row level security;
alter table public.sources             enable row level security;
alter table public.source_regions      enable row level security;

alter table public.raw_snapshots       enable row level security;
alter table public.fetch_failures      enable row level security;
alter table public.price_observations  enable row level security;

alter table public.price_daily_unified enable row level security;
alter table public.demand_signals      enable row level security;

alter table public.analysis_runs       enable row level security;
alter table public.anomaly_scores      enable row level security;
alter table public.cluster_models      enable row level security;
alter table public.cluster_assignments enable row level security;
alter table public.seasonal_components enable row level security;
alter table public.alerts              enable row level security;

alter table public.gt_candidates       enable row level security;
alter table public.gt_labels           enable row level security;
alter table public.gt_events           enable row level security;
alter table public.evaluation_results  enable row level security;
alter table public.sus_responses       enable row level security;

-- ---------------------------------------------------------------------------
-- Presentation tables: readable by the public dashboard.
-- These are exactly the tables a number on screen can be traced to without
-- exposing raw bodies, per-source prices, or ground truth.
-- ---------------------------------------------------------------------------
create policy "public_read_commodities" on public.commodities
    for select to anon, authenticated using (true);

create policy "public_read_regions" on public.regions
    for select to anon, authenticated using (true);

create policy "public_read_sources" on public.sources
    for select to anon, authenticated using (true);

create policy "public_read_source_regions" on public.source_regions
    for select to anon, authenticated using (true);

create policy "public_read_price_daily_unified" on public.price_daily_unified
    for select to anon, authenticated using (true);

create policy "public_read_alerts" on public.alerts
    for select to anon, authenticated using (true);

create policy "public_read_anomaly_scores" on public.anomaly_scores
    for select to anon, authenticated using (true);

create policy "public_read_cluster_assignments" on public.cluster_assignments
    for select to anon, authenticated using (true);

create policy "public_read_seasonal_components" on public.seasonal_components
    for select to anon, authenticated using (true);

-- Run metadata is public on purpose: "data terakhir diperbarui" on the
-- dashboard, and the transparency claim in /tentang, both depend on it.
create policy "public_read_analysis_runs" on public.analysis_runs
    for select to anon, authenticated using (true);

-- ---------------------------------------------------------------------------
-- Research tables: /lab only. No anon policy at all, so anon is denied.
-- ---------------------------------------------------------------------------
create policy "lab_read_price_observations" on public.price_observations
    for select to authenticated using (true);

create policy "lab_read_fetch_failures" on public.fetch_failures
    for select to authenticated using (true);

create policy "lab_read_demand_signals" on public.demand_signals
    for select to authenticated using (true);

create policy "lab_read_cluster_models" on public.cluster_models
    for select to authenticated using (true);

create policy "lab_read_gt_events" on public.gt_events
    for select to authenticated using (true);

create policy "lab_read_evaluation_results" on public.evaluation_results
    for select to authenticated using (true);

-- raw_snapshots has NO policy for anon or authenticated. Compressed response
-- bodies are engine-only; they are large, and re-parsing is a service-role job.

-- ---------------------------------------------------------------------------
-- Ground truth: write-only for annotators, by design.
--
-- gt_labels grants INSERT but NOT SELECT. Two annotators working blind to each
-- other is a stated requirement of the protocol, and the cheapest way to
-- guarantee it is to make reading another annotator's labels impossible through
-- the API rather than merely absent from the UI. Cohen's kappa is computed by
-- the engine under the service role.
--
-- gt_candidates is not exposed at all; the labeling UI reads the stratum-blind
-- view gt_labeling_queue instead (granted below).
-- ---------------------------------------------------------------------------
create policy "lab_insert_gt_labels" on public.gt_labels
    for insert to authenticated with check (true);

-- The blind queue view runs with definer rights so it can read gt_candidates
-- while the base table stays closed. This is deliberate, not an oversight:
-- the view's whole purpose is to project away `sampling_stratum`.
alter view public.gt_labeling_queue set (security_invoker = false);

revoke all on public.gt_labeling_queue from anon;
grant select on public.gt_labeling_queue to authenticated;

-- ---------------------------------------------------------------------------
-- SUS: collected through the /lab form, one row per respondent.
-- ---------------------------------------------------------------------------
create policy "lab_insert_sus_responses" on public.sus_responses
    for insert to authenticated with check (true);

create policy "lab_read_sus_responses" on public.sus_responses
    for select to authenticated using (true);
