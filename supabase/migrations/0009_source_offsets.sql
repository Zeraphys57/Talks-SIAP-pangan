-- 0009_source_offsets.sql
-- Put every source on a common level before reconciling them.
--
-- THE DEFECT THIS FIXES
--
-- `price_daily_unified.price_median` was a median over whichever sources
-- happened to report that day. The sources are not measuring the same thing:
-- PIHPS samples traditional-market retail, SP2KP is Kemendag's own panel,
-- Siskaperbapo is East Java's provincial survey. They sit systematically apart
-- (pihps/sp2kp ratio 1.0516 over 19,644 overlapping days; 18% for beras-medium
-- in Jawa Tengah, where pihps averages 15,691 and sp2kp 13,257).
--
-- So when a source dropped out, the "median" stepped by the gap between them.
-- That step is not a price movement, and the detectors could not tell:
--
--   6,399 of 39,077 series-days (16.4%) changed source composition
--   938 of 1,897 daily moves above 5% (49.4%) coincided with one
--   673 of 2,979 Z-Score flags (22.6%) sat on one
--   75 of the 399 ground-truth candidates (18.8%) sat on one
--
-- THE CORRECTION
--
-- Standard index linking. For each commodity x region, the best-covered source
-- becomes the reference; every other source is multiplied by the median ratio
-- of reference-price to its own price over the days both reported. Prices are
-- then reconciled on one basis, so composition changes no longer move the level.
--
-- WHY A CONSTANT FACTOR IS DEFENSIBLE HERE
--
-- Measured before choosing it, across all 60 (commodity, region, source-pair)
-- combinations, every one of which has at least 30 overlapping days:
--
--   within-series coefficient of variation   median 1.9%, max 9.5%
--   drift, first third vs last third         median 1.1%, max 10.5%
--
-- The pooled 7.9% spread was an artefact of averaging across commodities. A
-- residual of ~2% is an order of magnitude below the 18% level gap it removes
-- and well under the 10% bar in the operational definition of an anomaly. Six
-- of 60 series drift more than 5% across three years; a time-varying factor
-- would chase that, and would also absorb genuine divergence between markets,
-- so the drift is recorded as a limitation instead of modelled away.
--
-- This is not the cooking-oil density that M2 refused to refit. A density is a
-- physical constant with a true value that fitting would corrupt. A survey-frame
-- offset has no true value — the two surveys really do price different baskets,
-- and linking series collected on different frames is what the correction is
-- for.

-- ---------------------------------------------------------------------------
-- One row per (commodity, region, source) per preprocess run.
--
-- Persisted rather than recomputed on demand: every price in
-- price_daily_unified is a raw observation times one of these numbers, and a
-- correction that cannot be inspected is a correction nobody can check.
-- ---------------------------------------------------------------------------
create table if not exists public.source_offsets (
    id                  bigint generated always as identity primary key,
    run_id              bigint  not null references public.analysis_runs (id) on delete cascade,
    commodity_id        bigint  not null references public.commodities (id),
    region_id           bigint  not null references public.regions (id),
    source_id           bigint  not null references public.sources (id),

    -- The source this one was linked to. Equal to source_id for the reference
    -- itself, whose factor is 1 by definition.
    reference_source_id bigint  not null references public.sources (id),

    factor              numeric(12,6) not null,
    n_overlap           integer not null,

    -- Dispersion of the ratio the factor was taken from: how much of the
    -- day-to-day difference between the two sources the single number fails to
    -- explain. Large values mean the link is weak for this series.
    ratio_cv_pct        numeric(8,4),

    -- Ratio drift between the first and last third of the overlap, in percent.
    -- The constant-factor assumption is exactly what this measures.
    ratio_drift_pct     numeric(8,4),

    -- Set when a source could not be linked: too few overlapping days with the
    -- reference. Such a source contributes nothing to the level and is excluded
    -- from n_sources, because an unlinked price is on an unknown basis.
    excluded_reason     text,

    created_at          timestamptz not null default now(),

    constraint source_offsets_factor_positive check (factor > 0),
    constraint source_offsets_overlap_nonneg  check (n_overlap >= 0),
    constraint source_offsets_unique
        unique (run_id, commodity_id, region_id, source_id)
);

create index if not exists source_offsets_series_idx
    on public.source_offsets (run_id, commodity_id, region_id);

comment on table public.source_offsets is
    'Multiplicative factors linking each source to a per-series reference level, so price_daily_unified is not a median across incompatible measurement frames. Written by `siap preprocess`.';
comment on column public.source_offsets.factor is
    'Multiply this source''s raw price by this to express it on the reference source''s level. Exactly 1 for the reference.';
comment on column public.source_offsets.ratio_cv_pct is
    'Coefficient of variation of the reference/source ratio over the overlap. This is the residual the constant-factor assumption leaves behind; measured at a median of 1.9% across all series.';

-- ---------------------------------------------------------------------------
-- price_daily_unified now describes a rebased series. Say so on the table.
-- ---------------------------------------------------------------------------
comment on column public.price_daily_unified.price_median is
    'Median of same-day source prices AFTER rebasing each source onto the series reference level (see source_offsets). Before 0009 this was a median across raw prices from sources with systematically different levels, so it stepped whenever source composition changed.';
comment on column public.price_daily_unified.source_spread_pct is
    'Disagreement between sources on the rebased scale, so it measures genuine same-day disagreement rather than the constant level gap between survey frames.';
comment on column public.price_daily_unified.n_sources is
    'Sources contributing to the level on this day. A source that could not be linked to the reference is not counted, because a price on an unknown basis cannot be reconciled with the others.';

alter table public.source_offsets enable row level security;

-- Audience: LAB. The factors are research provenance rather than dashboard
-- content, but anyone checking a published number must be able to see them.
create policy "lab_read_source_offsets" on public.source_offsets
    for select to authenticated using (true);
