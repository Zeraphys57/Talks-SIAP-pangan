-- 0007_lab.sql
-- Annotator identity for the /lab labeling console.
--
-- WHY THIS EXISTS
--
-- 0006 granted `authenticated` INSERT on gt_labels and no SELECT, so that one
-- annotator physically cannot read the other's judgements. That invariant is
-- correct and is kept. But it leaves the labeling UI unable to answer two
-- questions it must answer to be usable over 399 items:
--
--   "which candidates have I already done?"  (resume after closing the tab)
--   "how far along am I?"                    (progress)
--
-- Granting SELECT on gt_labels would answer both and destroy the invariant.
-- Instead this migration adds two SECURITY DEFINER functions scoped to the
-- caller's *own* labels, and derives the annotator code from auth.uid() rather
-- than accepting it as an argument. Consequences:
--
--   * an annotator can never see another annotator's rows, not even their
--     candidate ids — the functions filter on the caller's own code only;
--   * an annotator can never write under another annotator's code, because the
--     INSERT policy is tightened below to compare against the same lookup.
--
-- The second point is new protection: under 0006 a signed-in team member could
-- have submitted labels as "A2". Independence of the two label sets is the
-- premise of Cohen's kappa, so it belongs in the schema, not in UI discipline.

-- ---------------------------------------------------------------------------
-- Who may label, and under which pseudonymous code.
--
-- Rows are inserted by hand under the service role (see docs/labelling.md).
-- Self-service registration is deliberately absent: the annotator set is two
-- named people agreed in the protocol, not whoever can create an account.
-- ---------------------------------------------------------------------------
create table if not exists public.lab_annotators (
    user_id        uuid        primary key,
    annotator_code text        not null unique,
    display_name   text,
    created_at     timestamptz not null default now(),

    -- Pseudonymous by protocol: the code that appears in gt_labels and in the
    -- paper must not identify the person.
    constraint lab_annotators_code_is_pseudonymous
        check (annotator_code ~ '^[A-Z][0-9]{1,2}$')
);

comment on table public.lab_annotators is
    'Maps a Supabase auth user to a pseudonymous annotator code. No API access: the mapping is read only through SECURITY DEFINER functions, so one annotator cannot enumerate the others.';
comment on column public.lab_annotators.user_id is
    'auth.users(id). No foreign key: the auth schema is Supabase-managed and a migration that hard-references it cannot be applied to a plain Postgres. A stale row is inert because every lookup goes through auth.uid().';

alter table public.lab_annotators enable row level security;
-- No policy: default-deny. anon and authenticated reach this table only through
-- the definer functions below.

-- ---------------------------------------------------------------------------
-- The caller's own annotator code, or NULL if they are not an annotator.
-- ---------------------------------------------------------------------------
create or replace function public.current_annotator_code()
returns text
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select annotator_code
      from public.lab_annotators
     where user_id = auth.uid()
$$;

comment on function public.current_annotator_code() is
    'Pseudonymous code of the signed-in annotator, from auth.uid(). Takes no argument on purpose: a parameter would let any signed-in user act as any annotator.';

-- ---------------------------------------------------------------------------
-- Tighten the write policy: you may only insert labels as yourself.
--
-- A signed-in user with no lab_annotators row gets NULL, the comparison is
-- NULL, and the insert is denied.
-- ---------------------------------------------------------------------------
alter policy "lab_insert_gt_labels" on public.gt_labels
    with check (annotator_code = public.current_annotator_code());

-- ---------------------------------------------------------------------------
-- The queue: candidates this annotator has not yet labeled.
--
-- Reads gt_labeling_queue, NOT gt_candidates. That is structural rather than
-- stylistic: the view has already projected away `sampling_stratum`, so this
-- function cannot leak it even by mistake. An annotator who could tell a
-- rule_flagged candidate from a random_control one would be labeling the
-- sampler instead of the market.
--
-- Commodity and region names are joined in because an annotator cannot look
-- for corroborating evidence without knowing what and where. `context` carries
-- the surrounding price window and never any model output.
-- ---------------------------------------------------------------------------
create or replace function public.lab_queue(batch_size integer default 20)
returns table (
    candidate_id   bigint,
    commodity_slug text,
    commodity_name text,
    canonical_unit text,
    region_slug    text,
    region_name    text,
    obs_date       date,
    context        jsonb
)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select q.id, c.slug, c.display_name, c.canonical_unit,
           rg.slug, rg.display_name, q.obs_date, q.context
      from public.gt_labeling_queue q
      join public.commodities c  on c.id  = q.commodity_id
      join public.regions     rg on rg.id = q.region_id
     where public.current_annotator_code() is not null
       and not exists (
             select 1
               from public.gt_labels l
              where l.candidate_id  = q.id
                and l.annotator_code = public.current_annotator_code())
     order by q.shuffle_key
     limit greatest(1, least(coalesce(batch_size, 20), 100))
$$;

comment on function public.lab_queue(integer) is
    'Next unlabeled candidates for the signed-in annotator, in seeded shuffle order. Stratum-blind by construction: it reads the gt_labeling_queue view, which has no sampling_stratum column.';

-- ---------------------------------------------------------------------------
-- Progress, for the caller only.
-- ---------------------------------------------------------------------------
create or replace function public.lab_progress()
returns table (
    annotator_code text,
    labeled        bigint,
    pool           bigint
)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
    select public.current_annotator_code(),
           (select count(*) from public.gt_labels
             where annotator_code = public.current_annotator_code()),
           (select count(*) from public.gt_candidates)
     where public.current_annotator_code() is not null
$$;

comment on function public.lab_progress() is
    'Own labeling progress. Reports no other annotator''s count: knowing how far the other person has got is not needed to label, and the fewer channels between the two of them the better.';

-- ---------------------------------------------------------------------------
-- Grants. EXECUTE defaults to PUBLIC in Postgres, so revoke first.
-- ---------------------------------------------------------------------------
revoke all on function public.current_annotator_code()      from public;
revoke all on function public.lab_queue(integer)            from public;
revoke all on function public.lab_progress()                from public;

grant execute on function public.current_annotator_code()   to authenticated;
grant execute on function public.lab_queue(integer)         to authenticated;
grant execute on function public.lab_progress()             to authenticated;
